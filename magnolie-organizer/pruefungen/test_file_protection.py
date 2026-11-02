"""Native existing-key adapter in isolated private fixtures; no PhoneStore."""
from pathlib import Path
import os
import struct
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import EncryptedTransferStage, ResumeLedger, TransferError
from magnolie_publication_journal import ProtectedPublicationJournal, PublicationWitness
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_transfer_stage import binding, description


@pytest.fixture
def telephone(tmp_path):
    root = tmp_path / "native-telephone-fixture"
    root.mkdir(mode=0o700)
    fd = os.open(root / "storage.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(bytes(range(32)))  # Public ephemeral fixture bytes, not a product key.
    for name in ("identity.json", "identity.key", "peers.json", "phone.db", "settings.json"):
        (root / name).write_bytes(b"opaque personal-data sentinel")
    return root


@pytest.mark.parametrize("data", [b"", b"hello", b"a" * 65536])
def test_existing_key_crypto_domain_framing_and_no_personal_store_changes(telephone, data):
    before = {p.name: (p.stat().st_ino, p.read_bytes()) for p in telephone.iterdir()}
    domain = "native-fixture/Blüte"
    with ExistingFileTransferProtection(telephone) as protection:
        blob = protection.seal(data, domain)
        assert len(blob) == len(data) + 28 and protection.unseal(blob, domain) == data
        aad = b"magnolie-file-transfer-protection-v1\0" + struct.pack(">I", len(domain.encode())) + domain.encode()
        assert AESGCM(bytes(range(32))).decrypt(blob[:12], blob[12:], aad) == data
        with pytest.raises(InvalidTag):
            protection.unseal(blob, "different-record")
        assert protection.seal(data, domain) != blob
    assert before == {p.name: (p.stat().st_ino, p.read_bytes()) for p in telephone.iterdir()}


@pytest.mark.parametrize("kind", ["missing", "short", "long", "permissions", "symlink", "hardlink", "directory"])
def test_missing_corrupt_or_unsafe_key_never_creates_defaults(telephone, kind):
    path = telephone / "storage.key"
    if kind == "missing":
        path.rename(telephone / "held-original.key")
    elif kind in {"short", "long"}:
        path.write_bytes(b"a" * (31 if kind == "short" else 33))
    elif kind == "permissions":
        path.chmod(0o644)
    else:
        path.rename(telephone / "held-original.key")
        if kind == "symlink":
            path.symlink_to(telephone / "held-original.key")
        elif kind == "hardlink":
            os.link(telephone / "held-original.key", path)
        else:
            path.mkdir(mode=0o700)
    before = {p.name for p in telephone.iterdir()}
    with pytest.raises((TransferError, OSError)):
        ExistingFileTransferProtection(telephone)
    assert before == {p.name for p in telephone.iterdir()}
    if kind == "missing":
        assert not path.exists()
    assert (telephone / "peers.json").read_bytes() == b"opaque personal-data sentinel"


@pytest.mark.parametrize("kind", ["rotation", "same-bytes-new-inode", "removed", "root-swap", "root-mode"])
def test_live_changes_invalidate_existing_adapter_instead_of_reusing_stale_key(telephone, kind):
    with ExistingFileTransferProtection(telephone) as protection:
        blob = protection.seal(b"hello", "record")
        path = telephone / "storage.key"
        if kind == "rotation":
            path.write_bytes(b"z" * 32)
        elif kind in {"same-bytes-new-inode", "removed"}:
            path.rename(telephone / "held-original.key")
            if kind == "same-bytes-new-inode":
                path.write_bytes(bytes(range(32))); path.chmod(0o600)
        elif kind == "root-swap":
            telephone.rename(telephone.with_name("held-telephone"))
            telephone.mkdir(mode=0o700)
        else:
            telephone.chmod(0o755)
        for operation in (lambda: protection.seal(b"new", "record"), lambda: protection.unseal(blob, "record")):
            with pytest.raises((TransferError, FileNotFoundError)):
                operation()


def test_rotation_during_crypto_cannot_return_stale_plaintext(telephone, monkeypatch):
    with ExistingFileTransferProtection(telephone) as protection:
        blob = protection.seal(b"hello", "record")
        original = AESGCM.decrypt
        def decrypt(cipher, *args):
            plain = original(cipher, *args)
            (telephone / "storage.key").write_bytes(b"z" * 32)
            return plain
        monkeypatch.setattr(AESGCM, "decrypt", decrypt)
        with pytest.raises(TransferError, match="existing_key_changed"):
            protection.unseal(blob, "record")


def test_stage_checkpoint_and_publication_journal_use_actual_existing_key_adapter(telephone, tmp_path):
    manifest, native = description(), binding()
    private = tmp_path / "stage-and-journal"
    private.mkdir(mode=0o700)
    with ExistingFileTransferProtection(telephone) as protection:
        with EncryptedTransferStage(private, manifest, native, lambda: native, protection.seal, protection.unseal) as encrypted:
            encrypted.create()
            ledger = ResumeLedger(manifest, native, lambda: native)
            ledger.record(manifest.files[0].id, 0, b"hello", encrypted.write_chunk, encrypted.read_chunk)
            handle = encrypted.save_checkpoint(ledger)
        with EncryptedTransferStage(private, manifest, native, lambda: native, protection.seal, protection.unseal, owner=handle.owner) as restored:
            ledger = restored.open_checkpoint(handle)
            assert ledger.verified_file(manifest.files[0].id, restored.read_chunk) == manifest.files[0]
        with ProtectedPublicationJournal(private, manifest, native, {f.id: f.path for f in manifest.files},
                protection.seal, protection.unseal, owner="1" * 32, create=True) as journal:
            journal.append("prepared", PublicationWitness(manifest.files[0].id, 1, 2, ((3, 4), (5, 6))))
        with ProtectedPublicationJournal(private, manifest, native, {f.id: f.path for f in manifest.files},
                protection.seal, protection.unseal, owner="1" * 32) as reopened:
            assert reopened.inspect(manifest.files[0].id).phase == "prepared"


def test_invalid_domains_data_and_closed_adapters_never_touch_key(telephone):
    with ExistingFileTransferProtection(telephone) as protection:
        for domain in (None, "", "bad\0domain", "a" * 4097):
            with pytest.raises(TransferError, match="invalid_domain"):
                protection.seal(b"hello", domain)
        for data in (None, bytearray(b"hello"), b"a" * (protection.MAX_PLAIN_BYTES + 1)):
            with pytest.raises(TransferError, match="invalid_data_size"):
                protection.seal(data, "record")
        with pytest.raises(TransferError, match="invalid_data_size"):
            protection.unseal(b"short", "record")
    with pytest.raises(TransferError, match="closed"):
        protection.seal(b"hello", "record")


def test_detected_key_change_remains_fenced_even_if_original_bytes_return(telephone):
    with ExistingFileTransferProtection(telephone) as protection:
        blob = protection.seal(b"hello", "record")
        key = telephone / "storage.key"
        key.write_bytes(b"z" * 32)
        with pytest.raises(TransferError, match="existing_key_changed"):
            protection.unseal(blob, "record")
        key.write_bytes(bytes(range(32)))
        with pytest.raises(TransferError, match="native_reopen_required"):
            protection.unseal(blob, "record")
    with ExistingFileTransferProtection(telephone) as fresh_native_instance:
        assert fresh_native_instance.unseal(blob, "record") == b"hello"


@pytest.mark.parametrize("kind", ["missing", "symlink", "permissions"])
def test_unsafe_or_missing_native_root_is_not_created_or_fixed(telephone, kind):
    root = telephone
    if kind == "missing":
        root = telephone / "not-created"
    elif kind == "symlink":
        root = telephone.with_name("linked-telephone")
        root.symlink_to(telephone, target_is_directory=True)
    else:
        root.chmod(0o755)
    with pytest.raises((TransferError, FileNotFoundError)):
        ExistingFileTransferProtection(root)
    if kind == "missing":
        assert not root.exists()
    elif kind == "permissions":
        assert root.stat().st_mode & 0o777 == 0o755


def test_existing_key_adapter_protects_real_job_index_and_checkpoint_head(telephone, tmp_path):
    manifest, native = description(), binding()
    private = tmp_path / "indexed-checkpoint"
    private.mkdir(mode=0o700)
    owner = "1" * 32
    with ExistingFileTransferProtection(telephone) as protection:
        with ProtectedTransferJobIndex(private, manifest, native, lambda: native, protection.seal, protection.unseal,
                owner=owner, create=True) as index:
            with EncryptedTransferStage(private, manifest, native, lambda: native, protection.seal, protection.unseal, owner=owner) as encrypted:
                encrypted.create()
                ledger = ResumeLedger(manifest, native, lambda: native)
                ledger.record(manifest.files[0].id, 0, b"hello", encrypted.write_chunk, encrypted.read_chunk)
                result = encrypted.commit_checkpoint(ledger, lambda handle: index.publish_head(handle, None), index.read_head, index.guard_head)
                assert not result.cleanup_pending and index.read_head() == result.handle
        with ProtectedTransferJobIndex(private, manifest, native, lambda: None, protection.seal, protection.unseal, owner=owner) as reopened:
            assert reopened.read_head() == result.handle
            assert not reopened.snapshot().is_saved_receipt
