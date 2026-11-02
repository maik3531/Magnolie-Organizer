"""Actual native catalog/index/stage/journal/publication operation, no transport."""
from dataclasses import replace
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_receive import NativeFileReceiveOperation, NativeReceiveStartError
from magnolie_file_transfer import CHUNK_BYTES, EncryptedTransferStage, TransferError
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_transfer_job_catalog import Fixture as CatalogFixture
from test_file_transfer_stage import description


class Fixture(CatalogFixture):
    def __init__(self, root):
        super().__init__(root)
        self.catalog = self.open(create=True)
        self.operations = []

    def accept(self, data=b"hello", *, accepted=None):
        if accepted is None:
            manifest = description(data)
            accepted = NativeAcceptedTransfer.capture(manifest, self.binding, {file.id: file.path for file in manifest.files},
                self.destination, lambda: self.current)
        operation = NativeFileReceiveOperation.accept(self.catalog, accepted, lambda: self.current,
            self.cipher.seal, self.cipher.open, lambda _, action: action())
        self.operations.append(operation)
        return operation

    def resume(self, job):
        operation = NativeFileReceiveOperation.resume(self.catalog, job, lambda: self.current,
            self.cipher.seal, self.cipher.open, lambda _, action: action())
        self.operations.append(operation)
        return operation

    def close(self):
        for operation in self.operations:
            operation.close()
        super().close()


@pytest.fixture
def fixture(tmp_path):
    f = Fixture(tmp_path)
    try:
        yield f
    finally:
        f.close()


def feed(operation, data, start=0):
    file = operation.job.accepted.manifest.files[0]
    for index in range(start, file.chunks):
        operation.receive_chunk(file.id, index, data[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES])


@pytest.mark.parametrize("data", [b"hello", b"", b"a" * CHUNK_BYTES + b"tail"])
def test_native_accept_chunk_checkpoint_full_readback_and_no_replace_publication(fixture, data):
    f = fixture
    operation = f.accept(data)
    initial = operation.progress()
    assert initial.verified_bytes == initial.checkpoint_verified_bytes == 0 and not initial.is_saved_receipt
    feed(operation, data)
    ready = operation.progress()
    assert ready.verified_bytes == ready.checkpoint_verified_bytes == len(data)
    result = operation.publish_completed()
    target = f.destination / operation.job.accepted.targets[0][1]
    assert target.read_bytes() == data
    assert all(not value.is_saved_receipt for value in result)
    assert operation.progress().phase == "physically_published_unreceipted"
    assert operation.publish_completed() == result
    assert operation.inspect_publication(result[0].file_id).state == "original_present"
    assert len(f.catalog.jobs()) == 1  # Publication is not automatic quota release.
    with pytest.raises(AttributeError):
        operation.job = None


def test_incomplete_batch_never_publishes_but_can_keep_receiving(fixture):
    f = fixture
    data = b"a" * CHUNK_BYTES + b"tail"
    operation = f.accept(data)
    file = operation.job.accepted.manifest.files[0]
    operation.receive_chunk(file.id, 0, data[:CHUNK_BYTES])
    with pytest.raises(TransferError, match="incomplete_manifest"):
        operation.publish_completed()
    assert not (f.destination / file.path).exists()
    operation.receive_chunk(file.id, 1, b"tail")
    assert operation.publish_completed()[0].size == len(data)


def test_native_chunk_resume_restores_actual_checkpoint_and_holds_publication_for_repair(fixture):
    f = fixture
    data = b"a" * CHUNK_BYTES + b"tail"
    operation = f.accept(data)
    file = operation.job.accepted.manifest.files[0]
    operation.receive_chunk(file.id, 0, data[:CHUNK_BYTES])
    job = operation.job
    operation.close()
    discovered = f.catalog.jobs()[0]
    assert discovered == job
    resumed = f.resume(discovered)
    assert resumed.progress().checkpoint_verified_bytes == CHUNK_BYTES
    resumed.receive_chunk(file.id, 1, b"tail")
    assert resumed.progress().checkpoint_verified_bytes == len(data)
    with pytest.raises(TransferError, match="publication_repair_required"):
        resumed.publish_completed()
    assert not (f.destination / file.path).exists()


def test_restart_of_physically_published_batch_only_observes_original_target(fixture):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    result = operation.publish_completed()[0]
    target = f.destination / result.relative_path
    original_inode = target.stat().st_ino
    job = operation.job
    operation.close()
    resumed = f.resume(job)
    assert resumed.inspect_publication(result.file_id).state == "original_present"
    with pytest.raises(TransferError, match="publication_repair_required"):
        resumed.publish_completed()
    assert target.read_bytes() == b"hello" and target.stat().st_ino == original_inode


def test_second_receiver_cannot_start_while_native_worker_owns_operation(fixture):
    f = fixture
    operation = f.accept()
    with pytest.raises(NativeReceiveStartError, match="operation_busy"):
        f.resume(operation.job)
    assert operation.progress().verified_bytes == 0
    operation.close()
    assert f.resume(operation.job).progress().verified_bytes == 0


def test_native_revocation_stops_chunk_and_target_io_without_releasing_data_or_quota(fixture):
    f = fixture
    operation = f.accept()
    file = operation.job.accepted.manifest.files[0]
    f.current = None
    with pytest.raises(TransferError, match="binding_revoked"):
        operation.receive_chunk(file.id, 0, b"hello")
    with pytest.raises(TransferError, match="binding_revoked"):
        operation.publish_completed()
    operation.close()
    assert len(f.catalog.jobs()) == 1 and not (f.destination / file.path).exists()


def test_unknown_equal_target_is_preserved_and_operation_fences_without_saved_receipt(fixture):
    f = fixture
    operation = f.accept()
    file = operation.job.accepted.manifest.files[0]
    target = f.destination / file.path
    target.parent.mkdir(mode=0o700)
    target.write_bytes(b"hello")
    original_inode = target.stat().st_ino
    feed(operation, b"hello")
    with pytest.raises(TransferError, match="existing_target_preserved"):
        operation.publish_completed()
    with pytest.raises(TransferError, match="repair_pending"):
        operation.checkpoint()
    assert target.read_bytes() == b"hello" and target.stat().st_ino == original_inode
    assert len(f.catalog.jobs()) == 1


def test_start_failure_exposes_reserved_job_and_preserves_partial_native_cache(fixture, monkeypatch):
    f = fixture
    original_create = EncryptedTransferStage.create
    def create(stage):
        original_create(stage)
        raise OSError("synthetic stage startup interruption")
    monkeypatch.setattr(EncryptedTransferStage, "create", create)
    with pytest.raises(NativeReceiveStartError) as failed:
        f.accept()
    job = failed.value.job
    assert f.catalog.jobs() == (job,)
    assert (f.parent / ("file-transfer-" + job.owner) / "owner.enc").is_file()
    with ProtectedTransferJobIndex(f.parent, job.accepted.manifest, job.accepted.binding, lambda: f.current,
            f.cipher.seal, f.cipher.open, owner=job.owner) as index:
        assert index.snapshot() is None  # Failed worker released lease, not data.


def test_changed_duplicate_chunk_is_not_replaced_or_accepted(fixture):
    f = fixture
    operation = f.accept()
    file = operation.job.accepted.manifest.files[0]
    operation.receive_chunk(file.id, 0, b"hello")
    assert operation.receive_chunk(file.id, 0, b"hello").verified_bytes == 5
    with pytest.raises(TransferError, match="changed_duplicate"):
        operation.receive_chunk(file.id, 0, b"other")
    with pytest.raises(TransferError, match="repair_pending"):
        operation.publish_completed()
    assert not (f.destination / file.path).exists()


def test_checkpoint_cadence_does_not_exhaust_head_history_after_128_chunks(fixture):
    f = fixture
    data = b"a" * (CHUNK_BYTES * 130)
    operation = f.accept(data)
    feed(operation, data)
    progress = operation.progress()
    assert progress.checkpoint_verified_bytes == progress.verified_bytes == len(data)
    assert operation._index.snapshot().revision <= operation._index.MAX_REVISIONS
    assert not progress.checkpoint_cleanup_pending


def test_close_waits_for_real_native_io_end_before_releasing_worker_owner(fixture, monkeypatch):
    f = fixture
    operation = f.accept()
    file = operation.job.accepted.manifest.files[0]
    entered, release, close_started, close_done = (threading.Event() for _ in range(4))
    failures = []
    original_write = operation._stage.write_chunk
    def write(*args):
        entered.set()
        if not release.wait(timeout=10):
            raise AssertionError("native I/O test release missing")
        return original_write(*args)
    monkeypatch.setattr(operation._stage, "write_chunk", write)
    def receive():
        try:
            operation.receive_chunk(file.id, 0, b"hello")
        except Exception as error:
            failures.append(error)
    def close():
        close_started.set()
        operation.close()
        close_done.set()
    receiving = threading.Thread(target=receive)
    closing = threading.Thread(target=close)
    receiving.start()
    try:
        assert entered.wait(timeout=5)
        closing.start()
        assert close_started.wait(timeout=5) and not close_done.is_set()
        with pytest.raises(NativeReceiveStartError, match="operation_busy"):
            f.resume(operation.job)
    finally:
        release.set()
        receiving.join(timeout=10)
        if closing.ident is not None:
            closing.join(timeout=10)
    assert not receiving.is_alive() and not closing.is_alive() and close_done.is_set() and not failures
    assert f.resume(operation.job).progress().verified_bytes == 5
