"""Actual destination readback and durable SQL file receipts, no book ACKs."""
import os
from pathlib import Path
import sys

from cryptography.exceptions import InvalidTag
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_receive import NativeFileReceiveOperation
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_receive import Fixture, feed


@pytest.fixture
def fixture(tmp_path):
    f = Fixture(tmp_path)
    try:
        yield f
    finally:
        f.close()


@pytest.mark.parametrize("data", [b"hello", b""])
def test_actual_file_save_receipt_requires_readback_and_preserves_original_heads_and_owner(fixture, data):
    f = fixture
    operation = f.accept(data)
    feed(operation, data)
    operation.publish_completed()
    index = operation._index
    original_owner = index._db.execute("SELECT payload FROM meta WHERE id=1").fetchone()[0]
    original_heads = index._db.execute("SELECT revision,payload FROM heads ORDER BY revision").fetchall()
    assert index.saved_receipts() == () and index._schema_version == 1
    receipts = operation.commit_saved_receipts()
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.is_saved_receipt and not receipt.is_book_save_ack and not receipt.grants_write_authority
    assert receipt.size == len(data) and (f.destination / receipt.relative_path).read_bytes() == data
    assert operation.progress().phase == "saved_locally"
    assert index._schema_version == 2
    assert index._db.execute("SELECT payload FROM meta WHERE id=1").fetchone()[0] == original_owner
    assert index._db.execute("SELECT revision,payload FROM heads ORDER BY revision").fetchall() == original_heads
    assert operation.commit_saved_receipts() == receipts
    operation.close()
    restored = NativeFileReceiveOperation.read_saved_receipts(f.catalog, operation.job, lambda: f.current, f.cipher.seal, f.cipher.open)
    assert restored == receipts


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_historical_saved_receipt_does_not_recopy_or_overwrite_later_pc_edits_or_tombstones(fixture, change):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    receipts = operation.commit_saved_receipts()
    target = f.destination / receipts[0].relative_path
    if change == "edit":
        target.write_bytes(b"user crop")
    else:
        target.unlink()  # Explicit simulated user deletion of our fixture only.
    assert operation.commit_saved_receipts() == receipts
    with pytest.raises(TransferError, match="already_saved"):
        operation.publish_completed()
    operation._stage.cleanup()  # Historical receipts must not depend on source cache.
    operation.close()
    restored = NativeFileReceiveOperation.read_saved_receipts(f.catalog, operation.job, lambda: f.current, f.cipher.seal, f.cipher.open)
    assert restored == receipts
    if change == "edit":
        assert target.read_bytes() == b"user crop"
    else:
        assert not target.exists()


def test_explicit_restart_recovery_reads_original_target_without_repeating_publication(fixture):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    published = operation.publish_completed()[0]
    target = f.destination / published.relative_path
    original_inode = target.stat().st_ino
    operation.close()
    resumed = f.resume(operation.job)
    receipts = resumed.commit_saved_receipts()
    assert receipts[0].is_saved_receipt and receipts[0].file_key == (published.device, published.inode)
    assert target.stat().st_ino == original_inode and target.read_bytes() == b"hello"
    with pytest.raises(TransferError, match="already_saved"):
        resumed.publish_completed()


@pytest.mark.parametrize("change", ["edited", "missing", "new-inode"])
def test_unreceipted_destination_changes_never_become_saved_receipts(fixture, change):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    published = operation.publish_completed()[0]
    target = f.destination / published.relative_path
    if change == "edited":
        target.write_bytes(b"user crop")
    else:
        target.rename(f.destination / "held-original.jpg")
        if change == "new-inode":
            target.write_bytes(b"hello"); target.chmod(0o600)
    with pytest.raises(TransferError, match="original_destination_unconfirmed"):
        operation.commit_saved_receipts()
    assert operation._index.saved_receipts() == ()
    if change == "edited":
        assert target.read_bytes() == b"user crop"
    elif change == "missing":
        assert not target.exists()


def test_no_publication_or_foreign_worker_is_not_a_saved_file(fixture):
    f = fixture
    operation = f.accept()
    file_id = operation.job.accepted.manifest.files[0].id
    index = operation._index
    with pytest.raises(TransferError, match="receipt_worker_required"):
        index.commit_saved_file(operation._journal, file_id, object())
    with pytest.raises(TransferError, match="missing_publication_evidence"):
        index.commit_saved_file(operation._journal, file_id, operation._lease)
    assert index.saved_receipts() == () and index._schema_version == 1


def test_uncertain_receipt_readback_fences_mutation_until_reopen_and_authentication(fixture, monkeypatch):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    index = operation._index
    original = index._open
    def readback(blob, suffix):
        if suffix.startswith("receipt/"):
            raise OSError("synthetic receipt readback failure")
        return original(blob, suffix)
    monkeypatch.setattr(index, "_open", readback)
    with pytest.raises(OSError, match="synthetic"):
        operation.commit_saved_receipts()
    with pytest.raises(TransferError, match="repair_pending"):
        index.saved_receipts()
    operation.close()
    # Receipt SQL commit completed after actual original-byte readback. Reopen
    # authenticates that durable historical record instead of saving a duplicate.
    result = NativeFileReceiveOperation.read_saved_receipts(f.catalog, operation.job, lambda: f.current, f.cipher.seal, f.cipher.open)
    assert len(result) == 1 and result[0].is_saved_receipt


def test_schema_upgrade_revocation_rolls_back_without_resetting_checkpoint_history(fixture):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    index = operation._index
    before = index._db.execute("SELECT revision,payload FROM heads ORDER BY revision").fetchall()
    def trace(sql):
        if sql == "PRAGMA user_version=2":
            f.current = None
    index._db.set_trace_callback(trace)
    with pytest.raises(TransferError, match="binding_revoked"):
        operation.commit_saved_receipts()
    index._db.set_trace_callback(None)
    assert index._db.execute("PRAGMA user_version").fetchone() == (1,)
    assert index._db.execute("SELECT revision,payload FROM heads ORDER BY revision").fetchall() == before
    operation.close()
    with ProtectedTransferJobIndex(f.parent, operation.job.accepted.manifest, operation.job.accepted.binding, lambda: None,
            f.cipher.seal, f.cipher.open, owner=operation.job.owner) as reopened:
        assert reopened.saved_receipts() == ()


def test_receipt_tampering_is_not_a_default_empty_receipt_list(fixture):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    operation.commit_saved_receipts()
    index = operation._index
    row = index._db.execute("SELECT file_id,payload FROM receipts").fetchone()
    raw = bytearray(row[1]); raw[-1] ^= 1
    with index._db:
        index._db.execute("UPDATE receipts SET payload=? WHERE file_id=?", (bytes(raw), row[0]))
    with pytest.raises(InvalidTag):
        index.saved_receipts()


def test_revocation_before_saved_readback_cannot_commit_or_return_receipt(fixture):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    f.current = None
    with pytest.raises(TransferError, match="binding_revoked"):
        operation.commit_saved_receipts()
    operation.close()
    with pytest.raises(TransferError, match="binding_revoked"):
        NativeFileReceiveOperation.read_saved_receipts(f.catalog, operation.job, lambda: f.current, f.cipher.seal, f.cipher.open)


def test_receipt_can_explicitly_recover_a_real_link_with_only_prepared_journal_evidence(fixture, monkeypatch):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    append = operation._journal.append
    def interrupted(phase, witness):
        if phase == "linked":
            raise OSError("synthetic lost post-link journal write")
        return append(phase, witness)
    monkeypatch.setattr(operation._journal, "append", interrupted)
    with pytest.raises(OSError, match="synthetic"):
        operation.publish_completed()
    operation.close()
    resumed = f.resume(operation.job)
    file = operation.job.accepted.manifest.files[0]
    assert resumed.inspect_publication(file.id).journal_phase == "prepared"
    result = resumed.commit_saved_receipts()[0]
    assert result.is_saved_receipt and result.journal_phase == "prepared"
    assert (f.destination / file.path).read_bytes() == b"hello"


@pytest.mark.parametrize("change", ["owner", "manifest", "acceptance", "size-bool", "inode-bool", "path", "checkpoint", "phase"])
def test_authenticated_but_wrong_receipt_metadata_is_not_accepted_or_rebased(fixture, change):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    receipt = operation.commit_saved_receipts()[0]
    value = receipt.wire()
    if change == "owner":
        value["owner"] = "e" * 32
    elif change == "manifest":
        value["manifest_sha256"] = "e" * 64
    elif change == "acceptance":
        value["accepted_sha256"] = "e" * 64
    elif change == "size-bool":
        value["size"] = True
    elif change == "inode-bool":
        value["file_key"][1] = True
    elif change == "path":
        value["relative_path"] = "different.jpg"
    elif change == "checkpoint":
        value["checkpoint_sha256"] = "e" * 64
    else:
        value["journal_phase"] = "wire_claim"
    index = operation._index
    blob = index._protect(value, "receipt/" + receipt.file_id)
    with index._db:
        index._db.execute("UPDATE receipts SET payload=? WHERE file_id=?", (blob, receipt.file_id))
    with pytest.raises(TransferError):
        index.saved_receipts()
    assert index._db.execute("SELECT payload FROM receipts WHERE file_id=?", (receipt.file_id,)).fetchone()[0] == blob


def test_actual_existing_key_protects_catalog_stage_and_durable_receipt_reopen(fixture):
    f = fixture
    telephone = f.parent / "existing-key-fixture"
    telephone.mkdir(mode=0o700)
    fd = os.open(telephone / "storage.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(bytes(range(32)))
    private = f.parent / "existing-key-receive"
    private.mkdir(mode=0o700)
    with ExistingFileTransferProtection(telephone) as protection:
        with ProtectedTransferJobCatalog(private, f.identity, protection.seal, protection.unseal, create=True) as catalog:
            with NativeFileReceiveOperation.accept(catalog, f.accepted(), lambda: f.current, protection.seal,
                    protection.unseal, lambda _, action: action()) as operation:
                feed(operation, b"hello")
                operation.publish_completed()
                receipt = operation.commit_saved_receipts()[0]
                job = operation.job
            result = NativeFileReceiveOperation.read_saved_receipts(catalog, job, lambda: f.current, protection.seal, protection.unseal)
            assert result == (receipt,) and receipt.is_saved_receipt and not receipt.is_book_save_ack


def test_open_transaction_is_not_exposed_as_durable_saved_evidence(fixture):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    receipt = operation.commit_saved_receipts()[0]
    index = operation._index
    index._db.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(TransferError, match="repair_pending"):
            index.saved_receipts()
    finally:
        index._db.rollback()
    assert index.saved_receipts() == (receipt,)


def test_failed_postcommit_directory_sync_never_returns_receipt_until_fresh_durable_read(fixture, monkeypatch):
    f = fixture
    operation = f.accept()
    feed(operation, b"hello")
    operation.publish_completed()
    index = operation._index
    inserted = False
    def trace(sql):
        nonlocal inserted
        if sql.startswith("INSERT INTO receipts"):
            inserted = True
    index._db.set_trace_callback(trace)
    original_fsync = os.fsync
    def fsync(fd):
        if inserted and fd == index._root_fd:
            raise OSError("synthetic receipt directory sync failure")
        return original_fsync(fd)
    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(OSError, match="synthetic"):
        operation.commit_saved_receipts()
    with pytest.raises(TransferError, match="repair_pending"):
        index.saved_receipts()
    index._db.set_trace_callback(None)
    operation.close()
    monkeypatch.setattr(os, "fsync", original_fsync)
    result = NativeFileReceiveOperation.read_saved_receipts(f.catalog, operation.job, lambda: f.current, f.cipher.seal, f.cipher.open)
    assert len(result) == 1 and result[0].is_saved_receipt
