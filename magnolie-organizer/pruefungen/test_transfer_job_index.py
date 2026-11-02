"""Real per-operation SQLite/CAS and encrypted stage, not a receipt fixture."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

from cryptography.exceptions import InvalidTag
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_transfer import ResumeLedger, TransferError, TransferStageHandle
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_transfer_stage import FixtureCipher, binding, description, stage


class Fixture:
    def __init__(self, root):
        self.parent = root / "private-jobs"
        self.parent.mkdir(mode=0o700)
        self.manifest = description()
        self.binding = binding()
        self.current = self.binding
        self.cipher = FixtureCipher()
        self.owner = "1" * 32
        self.handle = TransferStageHandle(self.owner, "2" * 32)
        self.indexes = []

    @property
    def root(self):
        return self.parent / (ProtectedTransferJobIndex.PREFIX + self.owner)

    def open(self, create=False, **options):
        args = dict(parent=self.parent, manifest=self.manifest, binding=self.binding, current_binding=lambda: self.current,
            seal=self.cipher.seal, unseal=self.cipher.open, owner=self.owner, create=create)
        args.update(options)
        index = ProtectedTransferJobIndex(**args)
        self.indexes.append(index)
        return index

    def close(self):
        for index in self.indexes:
            index.close()


@pytest.fixture
def fixture(tmp_path):
    f = Fixture(tmp_path)
    try:
        yield f
    finally:
        f.close()


def test_actual_sqlite_head_reopen_and_stale_compare_and_swap(fixture):
    f = fixture
    index = f.open(create=True)
    assert index.snapshot() is None and index.read_head() is None
    first = index.publish_head(f.handle, None)
    assert first.revision == 1 and first.handle == f.handle
    assert not first.is_saved_receipt and not first.grants_write_authority
    with pytest.raises(TransferError, match="cas_failed"):
        index.publish_head(replace(f.handle, checkpoint="3" * 32), None)
    second = index.publish_head(replace(f.handle, checkpoint="3" * 32), first)
    assert second.revision == 2
    index.close()
    reopened = f.open()
    assert reopened.snapshot() == second and reopened.read_head() == second.handle
    raw = (f.root / "index.sqlite").read_bytes()
    assert b"sender_fixture_01" not in raw and f.handle.checkpoint.encode() not in raw
    with pytest.raises(FileExistsError):
        f.open(create=True)


def test_real_stage_checkpoint_commits_and_retires_through_actual_product_index(fixture):
    f = fixture
    index = f.open(create=True)
    with stage(f.parent, f.manifest, f.binding, f.cipher, owner=f.owner, current=lambda: f.current) as encrypted:
        encrypted.create()
        ledger = ResumeLedger(f.manifest, f.binding, lambda: f.current)
        ledger.record(f.manifest.files[0].id, 0, b"hello", encrypted.write_chunk, encrypted.read_chunk)
        expected = index.snapshot()
        def publish(handle):
            index.publish_head(handle, expected)
        first = encrypted.commit_checkpoint(ledger, publish, index.read_head, index.guard_head)
        assert index.read_head() == first.handle
        expected = index.snapshot()
        second = encrypted.commit_checkpoint(ledger, publish, index.read_head, index.guard_head)
        assert second.handle != first.handle and second.retired_versions == 1
        assert not first.cleanup_pending and not second.cleanup_pending
    index.close()
    restored_index = f.open()
    with stage(f.parent, f.manifest, f.binding, f.cipher, owner=f.owner, current=lambda: f.current) as restored:
        ledger = restored.open_checkpoint(restored_index.read_head())
        assert ledger.verified_file(f.manifest.files[0].id, restored.read_chunk) == f.manifest.files[0]


def test_two_native_index_objects_allow_one_cas_winner(fixture):
    f = fixture
    first, second = f.open(create=True), f.open()
    ready = threading.Barrier(2)
    results = []
    def run(index, checkpoint):
        ready.wait(timeout=5)
        try:
            results.append(index.publish_head(TransferStageHandle(f.owner, checkpoint * 32), None).revision)
        except TransferError as error:
            results.append(str(error))
    threads = [threading.Thread(target=run, args=(first, "2")), threading.Thread(target=run, args=(second, "3"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(map(str, results)) == ["1", "transfer_job_index_head_cas_failed"]


def test_nested_cross_object_read_keeps_os_lock_but_head_change_inside_action_is_denied(fixture):
    f = fixture
    first, second = f.open(create=True), f.open()
    head = first.publish_head(f.handle, None)
    called = []
    def action():
        assert second.read_head() == head.handle
        with pytest.raises(TransferError, match="head_action_active"):
            second.publish_head(replace(f.handle, checkpoint="3" * 32), head)
        called.append(True)
    first.guard_head(f.handle, action)
    assert called == [True] and first.read_head() == f.handle
    first.guard_head(f.handle, lambda: called.append(True))
    assert called == [True, True]


def test_revocation_stops_updates_and_cleanup_actions_not_local_head_inspection(fixture):
    f = fixture
    index = f.open(create=True)
    head = index.publish_head(f.handle, None)
    f.current = None
    assert index.snapshot() == head
    called = []
    with pytest.raises(TransferError, match="binding_revoked"):
        index.guard_head(f.handle, lambda: called.append(True))
    with pytest.raises(TransferError, match="binding_revoked"):
        index.publish_head(replace(f.handle, checkpoint="3" * 32), head)
    assert not called
    index.close()
    assert f.open().snapshot() == head


@pytest.mark.parametrize("change", ["key", "binding", "manifest", "missing-db", "unknown", "copy-db", "root-swap"])
def test_corrupt_missing_or_changed_originals_are_never_regenerated(fixture, change):
    f = fixture
    index = f.open(create=True)
    index.publish_head(f.handle, None)
    index.close()
    options = {}
    if change == "key":
        options["unseal"] = FixtureCipher().open
    elif change == "binding":
        options["binding"] = replace(f.binding, permission_epoch="a" * 64)
    elif change == "manifest":
        options["manifest"] = replace(f.manifest, source_id="2" * 32)
    elif change in {"missing-db", "copy-db"}:
        path = f.root / "index.sqlite"
        raw = path.read_bytes()
        path.rename(f.parent / "held-original.sqlite")
        if change == "copy-db":
            path.write_bytes(raw); path.chmod(0o600)
    elif change == "unknown":
        (f.root / "unknown").write_bytes(b"keep")
    else:
        f.root.rename(f.parent / "held-original-root")
        f.root.mkdir(mode=0o700)
    before = {path.name for path in f.root.iterdir()}
    with pytest.raises((TransferError, InvalidTag, FileNotFoundError)):
        f.open(**options)
    assert before == {path.name for path in f.root.iterdir()}


@pytest.mark.parametrize("table,column,value", [("heads", "revision", 1), ("meta", "id", 1)])
def test_owner_and_head_ciphertext_tampering_fails_without_reset(fixture, table, column, value):
    f = fixture
    index = f.open(create=True)
    index.publish_head(f.handle, None)
    with sqlite3.connect(f.root / "index.sqlite") as db:
        raw = db.execute(f"SELECT payload FROM {table} WHERE {column}=?", (value,)).fetchone()[0]
        changed = bytearray(raw); changed[-1] ^= 1
        db.execute(f"UPDATE {table} SET payload=? WHERE {column}=?", (bytes(changed), value))
    with pytest.raises(InvalidTag):
        index.snapshot()
    with sqlite3.connect(f.root / "index.sqlite") as db:
        assert db.execute(f"SELECT payload FROM {table} WHERE {column}=?", (value,)).fetchone()[0] == bytes(changed)


def test_uncertain_commit_readback_fences_later_updates_until_explicit_native_reopen(fixture, monkeypatch):
    f = fixture
    index = f.open(create=True)
    original = index._snapshot
    calls = 0
    def snapshot():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic post-commit readback fault")
        return original()
    monkeypatch.setattr(index, "_snapshot", snapshot)
    with pytest.raises(OSError, match="synthetic"):
        index.publish_head(f.handle, None)
    with pytest.raises(TransferError, match="repair_pending"):
        index.publish_head(f.handle, None)
    index.close()
    # Reopening only restores a checkpoint pointer; the encrypted stage must
    # independently re-read every claimed chunk before any resume acceptance.
    assert f.open().read_head() == f.handle


def test_original_live_head_cannot_roll_back_silently(fixture):
    f = fixture
    index = f.open(create=True)
    first = index.publish_head(f.handle, None)
    index.publish_head(replace(f.handle, checkpoint="3" * 32), first)
    with sqlite3.connect(f.root / "index.sqlite") as db:
        db.execute("DELETE FROM heads WHERE revision=2")
    with pytest.raises(TransferError, match="head_rollback"):
        index.snapshot()


def test_fresh_process_inspects_actual_head_without_grants_or_key_creation(fixture):
    f = fixture
    index = f.open(create=True)
    expected = index.publish_head(f.handle, None)
    index.close()
    script = r'''
import json, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
value = json.loads(sys.stdin.read())
sys.path.insert(0, value["bin"])
from magnolie_file_transfer import FileManifest, NativeTransferBinding
from magnolie_transfer_job_index import ProtectedTransferJobIndex
key = AESGCM(bytes.fromhex(value["key"]))
def no_seal(*args): raise AssertionError("inspection must not seal")
def unseal(blob, domain): return key.decrypt(blob[:12], blob[12:], domain.encode())
with ProtectedTransferJobIndex(value["parent"], FileManifest.parse(value["manifest"]), NativeTransferBinding(**value["binding"]),
        lambda: None, no_seal, unseal, owner=value["owner"]) as index:
    head = index.snapshot()
    print(json.dumps({"revision": head.revision, "handle": vars(head.handle), "sha": head.protected_sha256, "saved": head.is_saved_receipt}))
'''
    process = subprocess.run([sys.executable, "-c", script], input=json.dumps({"bin": str(Path(__file__).resolve().parents[1] / "bin"),
        "key": f.cipher.raw_key.hex(), "parent": str(f.parent), "manifest": f.manifest.wire(), "binding": vars(f.binding), "owner": f.owner}),
        text=True, capture_output=True, check=True, timeout=20)
    assert json.loads(process.stdout) == {"revision": expected.revision, "handle": vars(expected.handle),
        "sha": expected.protected_sha256, "saved": False}


def test_unowned_sqlite_journal_is_preserved_before_connection_or_write(fixture):
    f = fixture
    index = f.open(create=True)
    index.publish_head(f.handle, None)
    index.close()
    journal = f.root / "index.sqlite-journal"
    journal.write_bytes(b"unknown interrupted or concurrent sidecar")
    journal.chmod(0o600)
    database = (f.root / "index.sqlite").read_bytes()
    with pytest.raises(TransferError, match="journal_repair_required"):
        f.open()
    assert journal.read_bytes() == b"unknown interrupted or concurrent sidecar"
    assert (f.root / "index.sqlite").read_bytes() == database


def test_weakened_sqlite_durability_is_rejected_before_head_update(fixture):
    f = fixture
    index = f.open(create=True)
    index._db.execute("PRAGMA synchronous=OFF")
    with pytest.raises(TransferError, match="unsupported_journal"):
        index.publish_head(f.handle, None)
    assert index._db.execute("SELECT COUNT(*) FROM heads").fetchone() == (0,)
