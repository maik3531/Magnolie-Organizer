"""Real private byte readbacks; no listeners, personal stores or publication."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import copy
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_transfer import (CHUNK_BYTES, FileManifest, ManifestFile, NativeTransferBinding,
                                    ResumeLedger, TransferError)


def manifest(data=b"hello", path="Photos/Blüte.jpg"):
    return FileManifest("a" * 32, "b" * 32, "sender_fixture_01", "receiver_fixture_01",
        (ManifestFile("c" * 32, path, len(data), sha256(data).hexdigest()),), len(data))


def binding():
    return NativeTransferBinding("sender_fixture_01", "receiver_fixture_01", "d" * 64, "e" * 64, "f" * 64, "0" * 64)


class OwnedFiles:
    def __init__(self, root):
        self.root = root
        self.writes = 0

    def write(self, file_id, offset, data):
        assert file_id == "c" * 32
        path = self.root / (file_id + ".part")
        with path.open("r+b" if path.exists() else "x+b") as target:
            target.seek(offset)
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        self.writes += 1

    def read(self, file_id, offset, size):
        path = self.root / (file_id + ".part")
        with path.open("rb") as source:
            source.seek(offset)
            return source.read(size)


def test_manifest_is_immutable_and_binds_every_member_and_native_receiver():
    original = manifest()
    wire = original.wire()
    parsed = FileManifest.parse(wire)
    assert parsed == original and parsed.fingerprint == original.fingerprint
    wire["files"][0]["path"] = "other.jpg"
    assert original.files[0].path == "Photos/Blüte.jpg"
    assert FileManifest.parse(wire).fingerprint != original.fingerprint
    for changed in (replace(original, transfer_id="1" * 32), replace(original, source_id="2" * 32),
                    replace(original, receiver_id="another_receiver_01"), replace(original, sender_id="another_sender_01"),
                    replace(original, files=(replace(original.files[0], sha256="1" * 64),))):
        assert changed.fingerprint != original.fingerprint
    with pytest.raises(FrozenInstanceError):
        original.files[0].size = 2
    with pytest.raises(FrozenInstanceError):
        original.source_id = "2" * 32


def test_shared_utf8_manifest_vector_has_exact_framing_and_digest(tmp_path):
    vectors = json.loads((Path(__file__).resolve().parents[2] / "contracts/file-transfer-manifest-v1-vectors.json").read_text())
    for vector in vectors["vectors"]:
        description = FileManifest.parse(vector["manifest"])
        assert description.fingerprint == vector["manifest_sha256"]
        assert sha256(bytes.fromhex(vector["file_bytes_hex"])).hexdigest() == description.files[0].sha256
        owned = OwnedFiles(tmp_path)
        native = binding()
        ledger = ResumeLedger(description, native, lambda: native)
        ledger.record(description.files[0].id, 0, bytes.fromhex(vector["file_bytes_hex"]), owned.write, owned.read)
        assert ledger.checkpoint() == vector["resume_checkpoint"]
        restored = ResumeLedger.restore(description, native, lambda: native, vector["resume_checkpoint"], owned.read)
        assert restored.verified_file(description.files[0].id, owned.read) == description.files[0]


@pytest.mark.parametrize("path", ["../x", "/absolute", "a//b", "a/./b", "a/../b", "C:drive", "a\\b",
    "a/b.", "a/b ", "CON.txt", "dir/COM¹.jpg", "CON .jpg", "nul", "a/\u202e.jpg", "a/\ud800", "e\u0301.jpg",
    "/".join(["a"] * 17), "a" * 256])
def test_manifest_rejects_unsafe_or_ambiguous_portable_paths(path):
    with pytest.raises(TransferError):
        manifest(path=path)


@pytest.mark.parametrize("field,value", [("format", True), ("format", 2), ("chunk_bytes", 65536.0),
    ("total_bytes", True), ("total_bytes", 4), ("files", []), ("sender_id", "bad"), ("transfer_id", "A" * 32)])
def test_manifest_wire_types_are_exact(field, value):
    wire = manifest().wire()
    wire[field] = value
    with pytest.raises(TransferError):
        FileManifest.parse(wire)


def test_manifest_rejects_extra_fields_duplicate_ids_case_aliases_and_file_parent_collisions():
    wire = manifest().wire()
    wire["grant"] = True
    with pytest.raises(TransferError):
        FileManifest.parse(wire)
    first = manifest().files[0]
    for second in (replace(first, path="other.jpg"), replace(first, id="d" * 32, path="photos/BLÜTE.jpg"),
                   replace(first, id="d" * 32, path="Photos/Blüte.jpg/child")):
        with pytest.raises(TransferError):
            replace(manifest(), files=(first, second), total_bytes=10)


def test_real_partial_transfer_resume_reads_back_claims_and_does_not_rewrite_duplicates(tmp_path):
    data = b"a" * CHUNK_BYTES + b"tail"
    description, native = manifest(data), binding()
    owned = OwnedFiles(tmp_path)
    ledger = ResumeLedger(description, native, lambda: native)
    file_id = description.files[0].id
    ledger.record(file_id, 1, b"tail", owned.write, owned.read)
    assert ledger.verified_bytes == 4 and ledger.missing(file_id) == (0,)
    checkpoint = ledger.checkpoint()
    resumed = ResumeLedger.restore(description, native, lambda: native, checkpoint, owned.read)
    resumed.record(file_id, 1, b"tail", owned.write, owned.read)
    assert owned.writes == 1
    resumed.record(file_id, 0, b"a" * CHUNK_BYTES, owned.write, owned.read)
    assert resumed.verified_bytes == len(data) and resumed.missing(file_id) == ()
    assert resumed.verified_file(file_id, owned.read) == description.files[0]
    assert owned.writes == 2
    checkpoint["chunks"].clear()
    assert resumed.verified_bytes == len(data)
    with pytest.raises(AttributeError):
        resumed.binding = replace(native, destination_token="2" * 64)


def test_corrupt_persisted_chunk_never_acquires_resume_or_final_receipt(tmp_path):
    description, native = manifest(), binding()
    owned = OwnedFiles(tmp_path)
    ledger = ResumeLedger(description, native, lambda: native)
    file_id = description.files[0].id
    ledger.record(file_id, 0, b"hello", owned.write, owned.read)
    checkpoint = ledger.checkpoint()
    (tmp_path / (file_id + ".part")).write_bytes(b"other")
    with pytest.raises(TransferError, match="persisted_resume_chunk_changed"):
        ResumeLedger.restore(description, native, lambda: native, checkpoint, owned.read)
    with pytest.raises(TransferError, match="verified_transfer_chunk_changed"):
        ledger.verified_file(file_id, owned.read)
    assert owned.writes == 1


def test_destination_permission_peer_or_source_change_never_inherits_persisted_acceptance(tmp_path):
    description, native = manifest(), binding()
    owned = OwnedFiles(tmp_path)
    ledger = ResumeLedger(description, native, lambda: native)
    ledger.record(description.files[0].id, 0, b"hello", owned.write, owned.read)
    checkpoint = ledger.checkpoint()
    for changed in (replace(native, sender_identity_sha256="1" * 64), replace(native, receiver_identity_sha256="1" * 64),
                    replace(native, permission_epoch="1" * 64), replace(native, destination_token="1" * 64)):
        with pytest.raises(TransferError):
            ResumeLedger.restore(description, changed, lambda: changed, checkpoint, owned.read)
        with pytest.raises(TransferError):
            ResumeLedger.restore(description, native, lambda: changed, checkpoint, owned.read)
    with pytest.raises(TransferError):
        ResumeLedger.restore(replace(description, source_id="1" * 32), native, lambda: native, checkpoint, owned.read)


def test_readback_failure_and_revoke_during_io_do_not_invent_verified_progress(tmp_path):
    description, native = manifest(), binding()
    owned = OwnedFiles(tmp_path)
    live = native
    ledger = ResumeLedger(description, native, lambda: live)
    with pytest.raises(TransferError, match="readback"):
        ledger.record(description.files[0].id, 0, b"hello", owned.write, lambda *_: b"wrong")
    assert ledger.verified_bytes == 0
    def revoke(*args):
        nonlocal live
        owned.write(*args)
        live = replace(native, permission_epoch="1" * 64)
    with pytest.raises(TransferError):
        ledger.record(description.files[0].id, 0, b"hello", revoke, owned.read)
    live = native
    assert ledger.verified_bytes == 0 and ledger.missing(description.files[0].id) == (0,)


def test_checkpoint_claims_have_exact_bounded_shapes_and_no_final_hash_bypass(tmp_path):
    description, native = manifest(), binding()
    owned = OwnedFiles(tmp_path)
    ledger = ResumeLedger(description, native, lambda: native)
    ledger.record(description.files[0].id, 0, b"hello", owned.write, owned.read)
    checkpoint = ledger.checkpoint()
    for alter in (lambda value: value.update(format=True), lambda value: value.update(extra=True),
                  lambda value: value["chunks"].append(copy.deepcopy(value["chunks"][0])),
                  lambda value: value["chunks"][0].update(index=True),
                  lambda value: value["chunks"][0].update(sha256="0" * 64)):
        changed = copy.deepcopy(checkpoint)
        alter(changed)
        with pytest.raises(TransferError):
            ResumeLedger.restore(description, native, lambda: native, changed, owned.read)
    (tmp_path / (description.files[0].id + ".part")).write_bytes(b"helloEXTRA")
    with pytest.raises(TransferError, match="final_integrity"):
        ledger.verified_file(description.files[0].id, owned.read)


def test_empty_file_still_needs_final_digest_and_eof_verification(tmp_path):
    description, native = manifest(b""), binding()
    owned = OwnedFiles(tmp_path)
    ledger = ResumeLedger(description, native, lambda: native)
    assert ledger.missing(description.files[0].id) == () and ledger.verified_bytes == 0
    with pytest.raises(FileNotFoundError):
        ledger.verified_file(description.files[0].id, owned.read)
    (tmp_path / (description.files[0].id + ".part")).write_bytes(b"")
    assert ledger.verified_file(description.files[0].id, owned.read) == description.files[0]
    (tmp_path / (description.files[0].id + ".part")).write_bytes(b"extra")
    with pytest.raises(TransferError):
        ledger.verified_file(description.files[0].id, owned.read)


def test_successful_chunk_readback_does_not_replace_the_full_source_digest(tmp_path):
    description, native = manifest(), binding()
    owned = OwnedFiles(tmp_path)
    ledger = ResumeLedger(description, native, lambda: native)
    ledger.record(description.files[0].id, 0, b"wrong", owned.write, owned.read)
    assert ledger.verified_bytes == 5
    with pytest.raises(TransferError, match="final_integrity"):
        ledger.verified_file(description.files[0].id, owned.read)
