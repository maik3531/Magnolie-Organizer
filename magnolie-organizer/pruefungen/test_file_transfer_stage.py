"""Real encrypted owned-directory resume, without any personal store or key."""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import subprocess
import sqlite3
import threading

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_transfer import (CHUNK_BYTES, EncryptedTransferStage, FileManifest, ManifestFile,
                                    NativeTransferBinding, ResumeLedger, TransferError, TransferStageHandle)


class FixtureCipher:
    def __init__(self):
        self.raw_key = os.urandom(32)  # Ephemeral fixture key, never a personal/store key.
        self.key = AESGCM(self.raw_key)

    def seal(self, plain, domain):
        nonce = os.urandom(12)
        return nonce + self.key.encrypt(nonce, plain, domain.encode())

    def open(self, blob, domain):
        return self.key.decrypt(blob[:12], blob[12:], domain.encode())


def description(data=b"hello"):
    return FileManifest("a" * 32, "b" * 32, "sender_fixture_01", "receiver_fixture_01",
        (ManifestFile("c" * 32, "Photos/Blüte.jpg", len(data), sha256(data).hexdigest()),), len(data))


def binding():
    return NativeTransferBinding("sender_fixture_01", "receiver_fixture_01", "d" * 64, "e" * 64, "f" * 64, "0" * 64)


def stage(parent, manifest, native, cipher, current=None, owner=None):
    return EncryptedTransferStage(parent, manifest, native, current or (lambda: native),
                                  cipher.seal, cipher.open, owner=owner)


class ProtectedJobIndex:
    """Synthetic native durable-index boundary, real SQLite + AEAD, no app store."""
    def __init__(self, path, owner, manifest, cipher):
        self.gate = threading.RLock()
        self.cipher = cipher
        self.domain = "fixture-private-job-index/" + owner + "/" + manifest.fingerprint
        fresh = not path.exists()
        if fresh:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload BLOB NOT NULL)")
        if fresh:
            with self.db:
                self.db.execute("INSERT INTO jobs VALUES('unrelated',?)", (b"unrelated fixture row",))

    def publish(self, handle):
        with self.gate, self.db:
            blob = self.cipher.seal(json.dumps(vars(handle), sort_keys=True).encode(), self.domain)
            self.db.execute("INSERT OR REPLACE INTO jobs VALUES('owned',?)", (blob,))

    def read(self):
        with self.gate:
            row = self.db.execute("SELECT payload FROM jobs WHERE id='owned'").fetchone()
            if row is None:
                return None
            value = json.loads(self.cipher.open(row[0], self.domain))
            assert set(value) == {"owner", "checkpoint"}
            return TransferStageHandle(**value)

    def guard(self, expected, action):
        with self.gate:
            assert self.read() == expected
            action()

    def close(self):
        self.db.close()


def test_close_reopen_uses_actual_aead_chunks_and_immutable_checkpoint_versions(tmp_path):
    data = b"x" * CHUNK_BYTES + b"tail"
    manifest, native, cipher = description(data), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as first:
        first.create()
        root = tmp_path / ("file-transfer-" + first.owner)
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 1, b"tail", first.write_chunk, first.read_chunk)
        handle = first.save_checkpoint(ledger)
        assert ledger.verified_bytes == 4
        assert all("Photos" not in path.name and b"Photos/Bl\xc3\xbcte.jpg" not in path.read_bytes() for path in root.iterdir())
        before = {path.name: path.read_bytes() for path in root.iterdir()}
    assert root.is_dir()  # Closing must not discard resumable data.
    with stage(tmp_path, manifest, native, cipher, owner=handle.owner) as second:
        resumed = second.open_checkpoint(handle)
        assert resumed.verified_bytes == 4 and resumed.missing("c" * 32) == (0,)
        resumed.record("c" * 32, 1, b"tail", second.write_chunk, second.read_chunk)
        assert all((root / name).read_bytes() == blob for name, blob in before.items())
        resumed.record("c" * 32, 0, data[:CHUNK_BYTES], second.write_chunk, second.read_chunk)
        assert resumed.verified_file("c" * 32, second.read_chunk) == manifest.files[0]
        next_handle = second.save_checkpoint(resumed)
        assert next_handle != handle and (root / ("checkpoint-" + handle.checkpoint + ".enc")).read_bytes() == before["checkpoint-" + handle.checkpoint + ".enc"]
    with stage(tmp_path, manifest, native, cipher, owner=next_handle.owner) as third:
        resumed = third.open_checkpoint(next_handle)
        assert resumed.verified_bytes == len(data)
        assert resumed.verified_file("c" * 32, third.read_chunk) == manifest.files[0]
        third.cleanup()
    assert not root.exists()


def test_wrong_key_manifest_target_or_unknown_handle_does_not_reset_saved_bytes(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as first:
        first.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 0, b"hello", first.write_chunk, first.read_chunk)
        handle = first.save_checkpoint(ledger)
        root = tmp_path / ("file-transfer-" + handle.owner)
        original = {path.name: path.read_bytes() for path in root.iterdir()}
        for changed_manifest, changed_native, changed_cipher in (
            (manifest, native, FixtureCipher()), (replace(manifest, source_id="1" * 32), native, cipher),
            (manifest, replace(native, destination_token="1" * 64), cipher)):
            with stage(tmp_path, changed_manifest, changed_native, changed_cipher, owner=handle.owner) as attempted:
                with pytest.raises((TransferError, InvalidTag)):
                    attempted.open_checkpoint(handle)
            assert original == {path.name: path.read_bytes() for path in root.iterdir()}
        with stage(tmp_path, manifest, native, cipher, owner=handle.owner) as attempted:
            with pytest.raises(FileNotFoundError):
                attempted.open_checkpoint(TransferStageHandle(handle.owner, "2" * 32))
        assert original == {path.name: path.read_bytes() for path in root.iterdir()}
        first.cleanup()


def test_a_fresh_process_restores_only_the_authenticated_checkpoint_and_actual_staged_bytes(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as first:
        first.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 0, b"hello", first.write_chunk, first.read_chunk)
        handle = first.save_checkpoint(ledger)
    script = r'''
import json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
value = json.loads(sys.stdin.read())
sys.path.insert(0, value["source_bin"])
from magnolie_file_transfer import FileManifest, NativeTransferBinding, EncryptedTransferStage, TransferStageHandle
manifest = FileManifest.parse(value["manifest"])
binding = NativeTransferBinding(**value["binding"])
key = AESGCM(bytes.fromhex(value["fixture_key"]))
def seal(data, domain):
    nonce = os.urandom(12)
    return nonce + key.encrypt(nonce, data, domain.encode())
def unseal(blob, domain):
    return key.decrypt(blob[:12], blob[12:], domain.encode())
handle = TransferStageHandle(**value["handle"])
with EncryptedTransferStage(value["parent"], manifest, binding, lambda: binding, seal, unseal, owner=handle.owner) as stage:
    ledger = stage.open_checkpoint(handle)
    member = ledger.verified_file(manifest.files[0].id, stage.read_chunk)
    print(json.dumps({"bytes": ledger.verified_bytes, "manifest_sha256": manifest.fingerprint, "file_sha256": member.sha256}))
'''
    value = {"source_bin": str(Path(__file__).resolve().parents[1] / "bin"), "parent": str(tmp_path),
             "manifest": manifest.wire(), "binding": vars(native), "handle": vars(handle), "fixture_key": cipher.raw_key.hex()}
    result = subprocess.run([sys.executable, "-c", script], input=json.dumps(value), text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert proof == {"bytes": 5, "manifest_sha256": manifest.fingerprint, "file_sha256": manifest.files[0].sha256}
    with stage(tmp_path, manifest, native, cipher, owner=handle.owner) as resumed:
        resumed.open_checkpoint(handle)
        resumed.cleanup()


def test_existing_conflicting_or_later_changed_cipher_is_never_overwritten_or_rebaselined(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        owned.write_chunk("c" * 32, 0, b"hello")
        root = tmp_path / ("file-transfer-" + owned.owner)
        path = root / ("c" * 32 + "-0.enc")
        original = path.read_bytes()
        with pytest.raises(TransferError):
            owned.write_chunk("c" * 32, 0, b"other")
        assert path.read_bytes() == original
        changed = cipher.seal(b"\x01other", owned._domain + path.name)
        path.write_bytes(changed)  # Explicit own fixture simulates a concurrent valid ciphertext replacement.
        with pytest.raises(TransferError, match="original_staging_witness"):
            owned.read_chunk("c" * 32, 0, 5)
        with pytest.raises(TransferError):
            owned.cleanup()
        assert path.read_bytes() == changed and (root / "owner.enc").exists()
        path.write_bytes(original)  # Restore only these exact known fixture bytes, not a personal baseline.
        owned.cleanup()


def test_unknown_file_blocks_cleanup_before_any_owned_entry_is_removed(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        owned.write_chunk("c" * 32, 0, b"hello")
        root = tmp_path / ("file-transfer-" + owned.owner)
        original = {path.name: path.read_bytes() for path in root.iterdir()}
        unknown = root / "unfamiliar-user-work.txt"
        unknown.write_text("keep")
        with pytest.raises(TransferError):
            owned.cleanup()
        assert unknown.read_text() == "keep"
        assert all((root / name).read_bytes() == blob for name, blob in original.items())
        unknown.unlink()  # Only the test's own explicitly created unfamiliar-file fixture.
        owned.cleanup()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_linked_or_special_member_never_reads_writes_or_deletes_a_foreign_target(tmp_path, kind):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    target = tmp_path / "unrelated.txt"
    target.write_bytes(b"keep foreign data")
    target.chmod(0o600)
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        owned.write_chunk("c" * 32, 0, b"hello")
        root = tmp_path / ("file-transfer-" + owned.owner)
        path = root / ("c" * 32 + "-0.enc")
        held = tmp_path / "held-own-cipher"
        path.rename(held)
        if kind == "symlink":
            path.symlink_to(target)
        elif kind == "hardlink":
            os.link(target, path)
        else:
            os.mkfifo(path, mode=0o600)
        with pytest.raises((TransferError, OSError)):
            owned.read_chunk("c" * 32, 0, 5)
        with pytest.raises((TransferError, OSError)):
            owned.cleanup()
        assert target.read_bytes() == b"keep foreign data" and (root / "owner.enc").exists()
        path.unlink()
        held.rename(path)
        owned.cleanup()
    assert target.read_bytes() == b"keep foreign data"


def test_replaced_directory_identity_cannot_redirect_a_live_stage_into_user_work(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        root = tmp_path / ("file-transfer-" + owned.owner)
        held = tmp_path / "held-own-root"
        root.rename(held)
        root.mkdir(mode=0o700)
        unknown = root / "user-work"
        unknown.write_text("keep")
        with pytest.raises(TransferError, match="directory_identity"):
            owned.write_chunk("c" * 32, 0, b"hello")
        with pytest.raises(TransferError):
            owned.cleanup()
        assert unknown.read_text() == "keep" and (held / "owner.enc").exists()
        unknown.unlink()
        root.rmdir()
        held.rename(root)
        owned.cleanup()


def test_revoke_during_seal_blocks_new_entry_and_owned_cleanup_still_works(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    live = native
    revoke = False
    def seal(plain, domain):
        nonlocal live
        result = cipher.seal(plain, domain)
        if revoke:
            live = None
        return result
    with EncryptedTransferStage(tmp_path, manifest, native, lambda: live, seal, cipher.open) as owned:
        owned.create()
        root = tmp_path / ("file-transfer-" + owned.owner)
        revoke = True
        with pytest.raises(TransferError):
            owned.write_chunk("c" * 32, 0, b"hello")
        assert sorted(path.name for path in root.iterdir()) == ["owner.enc"]
        owned.cleanup()
    assert not root.exists()


def test_checkpoint_versions_are_bounded_and_snapshot_does_not_invert_ledger_stage_locks(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 0, b"hello", owned.write_chunk, owned.read_chunk)
        original = ledger.checkpoint
        def checkpoint():
            assert not owned._gate._is_owned(), "Stage -> ledger lock order can deadlock actual ledger -> stage chunk IO"
            return original()
        ledger.checkpoint = checkpoint
        handles = [owned.save_checkpoint(ledger) for _ in range(owned.MAX_CHECKPOINTS)]
        with pytest.raises(TransferError, match="version_limit"):
            owned.save_checkpoint(ledger)
        root = tmp_path / ("file-transfer-" + owned.owner)
        assert len(list(root.glob("checkpoint-*.enc"))) == owned.MAX_CHECKPOINTS
        assert len(set(handles)) == owned.MAX_CHECKPOINTS
        owned.cleanup()


def test_durable_protected_index_readback_precedes_retirement_and_keeps_versions_bounded(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 0, b"hello", owned.write_chunk, owned.read_chunk)
        root = tmp_path / ("file-transfer-" + owned.owner)
        index = ProtectedJobIndex(tmp_path / "owned-index.db", owned.owner, manifest, cipher)
        try:
            for _ in range(owned.MAX_CHECKPOINTS + 4):
                committed = owned.commit_checkpoint(ledger, index.publish, index.read, index.guard)
                assert not committed.cleanup_pending and index.read() == committed.handle
                assert len(list(root.glob("checkpoint-*.enc"))) == 1
                assert ledger.verified_file("c" * 32, owned.read_chunk) == manifest.files[0]
            assert index.db.execute("SELECT payload FROM jobs WHERE id='unrelated'").fetchone()[0] == b"unrelated fixture row"
            handle = index.read()
        finally:
            index.close()
        reopened = ProtectedJobIndex(tmp_path / "owned-index.db", owned.owner, manifest, cipher)
        try:
            assert reopened.read() == handle
        finally:
            reopened.close()
        owned.cleanup()


def test_failed_or_unacknowledged_head_publication_preserves_prior_checkpoint_and_can_recover(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 0, b"hello", owned.write_chunk, owned.read_chunk)
        index = ProtectedJobIndex(tmp_path / "owned-index.db", owned.owner, manifest, cipher)
        try:
            initial = owned.commit_checkpoint(ledger, index.publish, index.read, index.guard)
            root = tmp_path / ("file-transfer-" + owned.owner)
            old = root / ("checkpoint-" + initial.handle.checkpoint + ".enc")
            original = old.read_bytes()
            def fail_before(_handle):
                raise OSError("synthetic durable-index write failure")
            with pytest.raises(OSError):
                owned.commit_checkpoint(ledger, fail_before, index.read, index.guard)
            assert index.read() == initial.handle and old.read_bytes() == original
            def fail_after(handle):
                index.publish(handle)
                raise OSError("synthetic acknowledgement failure after durable commit")
            with pytest.raises(OSError):
                owned.commit_checkpoint(ledger, fail_after, index.read, index.guard)
            assert index.read() != initial.handle and old.read_bytes() == original
            recovered = owned.retire_checkpoint_versions(index.read(), index.read, index.guard)
            assert not recovered.cleanup_pending and recovered.retired_versions == 2
            assert len(list(root.glob("checkpoint-*.enc"))) == 1
        finally:
            index.close()
        owned.cleanup()


def test_head_readback_failure_or_noop_native_gate_never_fakes_retirement(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 0, b"hello", owned.write_chunk, owned.read_chunk)
        index = ProtectedJobIndex(tmp_path / "owned-index.db", owned.owner, manifest, cipher)
        try:
            initial = owned.commit_checkpoint(ledger, index.publish, index.read, index.guard)
            root = tmp_path / ("file-transfer-" + owned.owner)
            with pytest.raises(TransferError, match="readback_failed"):
                owned.commit_checkpoint(ledger, index.publish, lambda: None, index.guard)
            assert (root / ("checkpoint-" + initial.handle.checkpoint + ".enc")).exists()
            result = owned.commit_checkpoint(ledger, index.publish, index.read, lambda _expected, _action: None)
            assert result.cleanup_pending and result.retired_versions == 0 and result.cleanup_error == "TransferError"
            assert len(list(root.glob("checkpoint-*.enc"))) == 3
            owned.retire_checkpoint_versions(index.read(), index.read, index.guard)
            assert len(list(root.glob("checkpoint-*.enc"))) == 1
        finally:
            index.close()
        owned.cleanup()


def test_changed_original_version_is_preserved_after_real_head_commit_with_cleanup_pending(tmp_path):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        ledger.record("c" * 32, 0, b"hello", owned.write_chunk, owned.read_chunk)
        index = ProtectedJobIndex(tmp_path / "owned-index.db", owned.owner, manifest, cipher)
        try:
            initial = owned.commit_checkpoint(ledger, index.publish, index.read, index.guard)
            root = tmp_path / ("file-transfer-" + owned.owner)
            old = root / ("checkpoint-" + initial.handle.checkpoint + ".enc")
            original = old.read_bytes()
            changed = cipher.seal(b"changed native fixture metadata", owned._domain + old.name)
            old.write_bytes(changed)
            committed = owned.commit_checkpoint(ledger, index.publish, index.read, index.guard)
            assert committed.cleanup_pending and committed.retired_versions == 0 and index.read() == committed.handle
            assert old.read_bytes() == changed
            old.write_bytes(original)  # Exact known injected fixture only; real failed baselines stay unchanged.
            recovered = owned.retire_checkpoint_versions(index.read(), index.read, index.guard)
            assert not recovered.cleanup_pending and recovered.retired_versions == 1
        finally:
            index.close()
        owned.cleanup()


@pytest.mark.parametrize("change", ["native_head", "permission"])
def test_native_head_or_permission_change_inside_retirement_gate_preserves_all_versions(tmp_path, change):
    manifest, native, cipher = description(), binding(), FixtureCipher()
    live = native
    with stage(tmp_path, manifest, native, cipher, current=lambda: live) as owned:
        owned.create()
        ledger = ResumeLedger(manifest, native, lambda: live)
        ledger.record("c" * 32, 0, b"hello", owned.write_chunk, owned.read_chunk)
        index = ProtectedJobIndex(tmp_path / "owned-index.db", owned.owner, manifest, cipher)
        try:
            initial = owned.commit_checkpoint(ledger, index.publish, index.read, index.guard)
            def changed_gate(_expected, action):
                nonlocal live
                with index.gate:
                    if change == "native_head":
                        index.publish(initial.handle)  # Synthetic concurrent native head rollback, not a checkpoint echo.
                    else:
                        live = None
                    action()
            result = owned.commit_checkpoint(ledger, index.publish, index.read, changed_gate)
            root = tmp_path / ("file-transfer-" + owned.owner)
            assert result.cleanup_pending and result.retired_versions == 0
            assert len(list(root.glob("checkpoint-*.enc"))) == 2
            assert (root / ("checkpoint-" + initial.handle.checkpoint + ".enc")).exists()
            if change == "native_head":
                assert index.read() == initial.handle
        finally:
            index.close()
        owned.cleanup()  # Explicit owned-cache cleanup remains allowed after revocation.


def test_missing_empty_marker_and_changed_owner_marker_are_not_successful_file_receipts(tmp_path):
    manifest, native, cipher = description(b""), binding(), FixtureCipher()
    with stage(tmp_path, manifest, native, cipher) as owned:
        owned.create()
        ledger = ResumeLedger(manifest, native, lambda: native)
        assert ledger.verified_file("c" * 32, owned.read_chunk).size == 0
        root = tmp_path / ("file-transfer-" + owned.owner)
        marker = root / "owner.enc"
        original = marker.read_bytes()
        marker.write_bytes(b"changed marker")
        with pytest.raises(TransferError, match="owner_witness"):
            ledger.verified_file("c" * 32, owned.read_chunk)
        with pytest.raises(TransferError):
            owned.cleanup()
        assert marker.read_bytes() == b"changed marker"
        marker.write_bytes(original)
        empty = root / ("empty-" + "c" * 32 + ".enc")
        held = tmp_path / "held-empty-marker"
        empty.rename(held)
        with pytest.raises(FileNotFoundError):
            ledger.verified_file("c" * 32, owned.read_chunk)
        held.rename(empty)
        owned.cleanup()
