"""Bounded protected native job discovery/reservation; no personal storage."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from cryptography.exceptions import InvalidTag
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_catalog import (NativeJobCatalogIdentity, NativeJobCatalogLimits, ProtectedTransferJobCatalog)
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_transfer_stage import FixtureCipher, binding, description


class Fixture:
    def __init__(self, root):
        self.parent = root / "native-private"
        self.parent.mkdir(mode=0o700)
        self.destination = root / "native-pictures"
        self.destination.mkdir(mode=0o700)
        self.binding = binding()
        self.current = self.binding
        self.identity = NativeJobCatalogIdentity(self.binding.receiver_id, self.binding.receiver_identity_sha256)
        self.cipher = FixtureCipher()
        self.instances = []

    @property
    def root(self):
        return self.parent / ProtectedTransferJobCatalog.NAME

    def accepted(self, transfer="a"):
        manifest = replace(description(), transfer_id=transfer * 32)
        return NativeAcceptedTransfer.capture(manifest, self.binding, {file.id: file.path for file in manifest.files},
            self.destination, lambda: self.current)

    def open(self, create=False, **options):
        args = dict(parent=self.parent, identity=self.identity, seal=self.cipher.seal, unseal=self.cipher.open, create=create)
        args.update(options)
        result = ProtectedTransferJobCatalog(**args)
        self.instances.append(result)
        return result

    def close(self):
        for instance in self.instances:
            instance.close()


@pytest.fixture
def fixture(tmp_path):
    f = Fixture(tmp_path)
    try:
        yield f
    finally:
        f.close()


def test_actual_catalog_discovers_complete_jobs_after_restart_without_live_destination_or_grant(fixture):
    f = fixture
    catalog = f.open(create=True)
    accepted = f.accepted()
    job = catalog.reserve(accepted, lambda: f.current)
    assert job.owner != accepted.manifest.transfer_id and len(job.owner) == 32
    assert not job.grants_write_authority and not job.is_saved_receipt
    before = {path.name: path.read_bytes() for path in f.root.iterdir()}
    assert all(b"Photos" not in raw and b"sender_fixture_01" not in raw for raw in before.values())
    catalog.close()
    f.current = None
    f.destination.rename(f.destination.with_name("held-pictures"))
    reopened = f.open()
    assert reopened.jobs() == (job,) and job.accepted == accepted
    assert before == {path.name: path.read_bytes() for path in f.root.iterdir()}
    assert not f.destination.exists()
    with pytest.raises(TransferError, match="binding_revoked"):
        reopened.reserve(accepted, lambda: f.current)


def test_catalog_discovery_supplies_actual_manifest_owner_and_acceptance_to_index_reopen(fixture):
    f = fixture
    catalog = f.open(create=True)
    job = catalog.reserve(f.accepted(), lambda: f.current)
    with ProtectedTransferJobIndex(f.parent, job.accepted.manifest, job.accepted.binding, lambda: f.current,
            f.cipher.seal, f.cipher.open, owner=job.owner, create=True, accepted=job.accepted) as index:
        assert index.accepted_transfer == job.accepted and index.snapshot() is None
    catalog.close()
    discovered = f.open().jobs()[0]
    with ProtectedTransferJobIndex(f.parent, discovered.accepted.manifest, discovered.accepted.binding, lambda: None,
            f.cipher.seal, f.cipher.open, owner=discovered.owner) as restored:
        assert restored.accepted_transfer == discovered.accepted


def test_count_and_byte_quotas_are_durable_and_never_silently_released(fixture):
    f = fixture
    accepted = f.accepted()
    amount = ProtectedTransferJobCatalog.reservation_bytes(accepted)
    limits = NativeJobCatalogLimits(2, amount)
    catalog = f.open(create=True, limits=limits)
    job = catalog.reserve(accepted, lambda: f.current)
    with pytest.raises(TransferError, match="quota_exceeded"):
        catalog.reserve(f.accepted("b"), lambda: f.current)
    catalog.close()
    reopened = f.open()
    assert reopened.jobs() == (job,)
    with pytest.raises(TransferError, match="quota_exceeded"):
        reopened.reserve(f.accepted("b"), lambda: f.current)
    with pytest.raises(TransferError, match="limits_changed"):
        f.open(limits=NativeJobCatalogLimits(2, amount * 2))


def test_operation_repetition_is_not_a_new_owner_or_silent_source_target_reacceptance(fixture):
    f = fixture
    catalog = f.open(create=True)
    accepted = f.accepted()
    first = catalog.reserve(accepted, lambda: f.current)
    for value in (accepted, replace(accepted, targets=((accepted.manifest.files[0].id, "different.jpg"),))):
        with pytest.raises(TransferError, match="existing_operation"):
            catalog.reserve(value, lambda: f.current)
    assert catalog.jobs() == (first,)


def test_two_native_catalog_instances_serialize_quota_reservation_to_one_winner(fixture):
    f = fixture
    first = f.open(create=True, limits=NativeJobCatalogLimits(1))
    second = f.open()
    barrier = threading.Barrier(2)
    results = []
    def run(catalog, accepted):
        barrier.wait(timeout=5)
        try:
            results.append(catalog.reserve(accepted, lambda: f.current))
        except TransferError as error:
            results.append(str(error))
    threads = [threading.Thread(target=run, args=(first, f.accepted("a"))), threading.Thread(target=run, args=(second, f.accepted("b")))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len([value for value in results if not isinstance(value, str)]) == 1
    assert "file_job_catalog_quota_exceeded" in results and len(first.jobs()) == 1


@pytest.mark.parametrize("change", ["key", "identity", "job-copy", "job-symlink", "job-corrupt", "owner-corrupt", "unknown", "lock", "root"])
def test_unknown_changed_or_corrupt_originals_are_preserved_instead_of_reset(fixture, change):
    f = fixture
    catalog = f.open(create=True)
    job = catalog.reserve(f.accepted(), lambda: f.current)
    catalog.close()
    options = {}
    path = f.root / ("job-" + job.owner + ".enc")
    if change == "key":
        options["unseal"] = FixtureCipher().open
    elif change == "identity":
        options["identity"] = replace(f.identity, receiver_identity_sha256="a" * 64)
    elif change in {"job-copy", "job-symlink"}:
        raw = path.read_bytes()
        path.rename(f.parent / "held-original.enc")
        if change == "job-copy":
            path.write_bytes(raw); path.chmod(0o600)
        else:
            path.symlink_to(f.parent / "held-original.enc")
    elif change in {"job-corrupt", "owner-corrupt"}:
        target = path if change == "job-corrupt" else f.root / "owner.enc"
        raw = bytearray(target.read_bytes()); raw[-1] ^= 1; target.write_bytes(raw)
    elif change == "unknown":
        (f.root / "unknown").write_bytes(b"keep")
    elif change == "lock":
        lock = f.root / "catalog.lock"
        lock.rename(f.parent / "held-lock")
        lock.write_bytes(b""); lock.chmod(0o600)
    else:
        f.root.rename(f.parent / "held-root")
        f.root.mkdir(mode=0o700)
    before = {p.name for p in f.root.iterdir()}
    with pytest.raises((TransferError, OSError, InvalidTag)):
        f.open(**options)
    assert before == {p.name for p in f.root.iterdir()}


@pytest.mark.parametrize("failure", ["seal", "write", "fsync", "readback", "revoke"])
def test_failed_reservation_holds_uncertain_metadata_and_fences_further_mutation(fixture, monkeypatch, failure):
    f = fixture
    catalog = f.open(create=True)
    accepted = f.accepted()
    def fault(*_):
        raise OSError("synthetic reservation fault")
    if failure == "seal":
        monkeypatch.setattr(catalog, "_seal", fault)
    elif failure == "write":
        monkeypatch.setattr(os, "write", fault)
    elif failure == "fsync":
        monkeypatch.setattr(os, "fsync", fault)
    elif failure == "readback":
        original = catalog._unseal
        def unseal(blob, domain):
            return fault() if domain.rsplit('/',1)[-1].startswith('job-') else original(blob,domain)
        monkeypatch.setattr(catalog, "_unseal", unseal)
    else:
        original = catalog._write
        def write(name, payload):
            result = original(name, payload)
            f.current = None
            return result
        monkeypatch.setattr(catalog, "_write", write)
    with pytest.raises((OSError, TransferError)):
        catalog.reserve(accepted, lambda: f.current)
    with pytest.raises(TransferError, match="repair_pending"):
        catalog.reserve(accepted, lambda: f.current)
    assert len(list(f.root.glob("job-*.enc"))) == 1


def test_reentrant_native_inspection_is_allowed_but_nested_reservation_is_not(fixture):
    f = fixture
    first = f.open(create=True)
    second = f.open()
    accepted = f.accepted()
    called = []
    def current():
        assert second.jobs() == ()
        with pytest.raises(TransferError, match="nested_reservation"):
            second.reserve(accepted, lambda: f.current)
        called.append(True)
        return f.current
    # Verification after durable reservation sees one job, so restrict this
    # callback's assertions to its prepublication phase.
    def checked_current():
        if not list(f.root.glob("job-*.enc")):
            return current()
        return f.current
    assert first.reserve(accepted, checked_current).accepted == accepted and called


def test_fresh_process_discovers_manifest_and_mapping_without_live_peer_or_destination(fixture):
    f = fixture
    catalog = f.open(create=True)
    job = catalog.reserve(f.accepted(), lambda: f.current)
    catalog.close()
    f.destination.rename(f.destination.with_name("held-pictures"))
    script = r'''
import json,sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
value=json.loads(sys.stdin.read());sys.path.insert(0,value["bin"])
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog,NativeJobCatalogIdentity
key=AESGCM(bytes.fromhex(value["key"]))
def unseal(blob,domain):return key.decrypt(blob[:12],blob[12:],domain.encode())
def no_seal(*args):raise AssertionError("discovery must not write")
with ProtectedTransferJobCatalog(value["parent"],NativeJobCatalogIdentity(**value["identity"]),no_seal,unseal) as catalog:
    job=catalog.jobs()[0];print(json.dumps({"owner":job.owner,"accepted":job.accepted.wire(),"reserved":job.reserved_bytes}))
'''
    result = subprocess.run([sys.executable, "-c", script], input=json.dumps({"bin": str(Path(__file__).resolve().parents[1] / "bin"),
        "key": f.cipher.raw_key.hex(), "parent": str(f.parent), "identity": vars(f.identity)}), text=True, capture_output=True, check=True, timeout=20)
    assert json.loads(result.stdout) == {"owner": job.owner, "accepted": job.accepted.wire(), "reserved": job.reserved_bytes}


def test_wrong_receiver_and_invalid_limits_never_reserve_a_job(fixture):
    f = fixture
    catalog = f.open(create=True)
    accepted = f.accepted()
    foreign = replace(accepted.binding, receiver_identity_sha256="a" * 64)
    with pytest.raises(TransferError, match="wrong_receiver"):
        catalog.reserve(replace(accepted, binding=foreign), lambda: foreign)
    for values in ({"max_jobs": True}, {"max_jobs": 0}, {"max_reserved_bytes": -1}, {"max_reserved_bytes": True}):
        with pytest.raises(TransferError, match="invalid_limits"):
            NativeJobCatalogLimits(**values)
    assert catalog.jobs() == ()


def test_reservation_covers_all_retained_member_temporaries_not_only_largest(fixture):
    f = fixture
    accepted = f.accepted()
    file = accepted.manifest.files[0]
    manifest = replace(accepted.manifest, files=(file, replace(file, id="d" * 32, path="second.jpg")), total_bytes=10)
    multi = replace(accepted, manifest=manifest, targets=tuple((value.id, value.path) for value in manifest.files))
    one = ProtectedTransferJobCatalog.reservation_bytes(accepted)
    two = ProtectedTransferJobCatalog.reservation_bytes(multi)
    # Additional stage bytes AND an additional potentially retained plaintext
    # temporary, plus bounded per-member frame/journal overhead.
    assert two - one == 2 * file.size + file.chunks * 128 + 3 * (4096 + 128)


def test_actual_existing_key_catalog_reopen_and_index_ownership(fixture):
    f = fixture
    telephone = f.parent / "telephone-fixture"
    telephone.mkdir(mode=0o700)
    fd = os.open(telephone / "storage.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(bytes(range(32)))
    with ExistingFileTransferProtection(telephone) as protection:
        catalog = f.open(create=True, seal=protection.seal, unseal=protection.unseal)
        reserved = catalog.reserve(f.accepted(), lambda: f.current)
        catalog.close()
        discovered = f.open(seal=protection.seal, unseal=protection.unseal).jobs()[0]
        assert discovered == reserved
        with ProtectedTransferJobIndex(f.parent, discovered.accepted.manifest, discovered.accepted.binding, lambda: f.current,
                protection.seal, protection.unseal, owner=discovered.owner, create=True, accepted=discovered.accepted) as index:
            assert index.accepted_transfer == discovered.accepted
