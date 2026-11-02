"""Bounded pure offer checks, no personal stores/listeners/native publication."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_transfer import FileManifest, ManifestFile, TransferError
from magnolie_file_offer import KIND, create_offer, validate_offer
from magnolie_telefon import APPLICATION_MAX, CAPABILITY_NAMES, canonical

ROOT = Path(__file__).resolve().parents[2]
NOW = 1_800_000_000_000
MESSAGE_ID = "00000000-0000-4000-8000-000000000001"


def manifest():
    return FileManifest.parse(json.loads((ROOT / "contracts/file-transfer-manifest-v1-vectors.json").read_text())["vectors"][0]["manifest"])


def raw(value):
    return {"type": "message", "v": 1, "message_id": MESSAGE_ID, "kind": KIND, "created_ms": NOW,
            "expires_ms": NOW + 60_000, "body": {"version": 1, "manifest": value.wire(), "manifest_sha256": value.fingerprint}}


def large_manifest(characters, padding=0):
    original = manifest()
    members = []
    for index in range(128):
        length = characters // 128 + (index < characters % 128)
        text = "界" * length
        path = "/".join(text[start:start + 200] for start in range(0, length, 200))
        path += f"/file-{index}" + ("x" * padding if index == 0 else "") + ".jpg"
        members.append(ManifestFile(f"{index + 1:032x}", path, 0, sha256(b"").hexdigest()))
    return FileManifest(original.transfer_id, original.source_id, original.sender_id, original.receiver_id, tuple(members), 0)


def for_envelope_bytes(target):
    low, high = 128 * 580, 128 * 700
    while low < high:
        middle = (low + high + 1) // 2
        if len(canonical(raw(large_manifest(middle)))) <= target:
            low = middle
        else:
            high = middle - 1
    difference = target - len(canonical(raw(large_manifest(low))))
    assert 0 <= difference <= 4
    value = large_manifest(low, difference)
    assert len(canonical(raw(value))) == target
    return value


def test_shared_complete_unicode_offer_bytes_and_hash_match():
    vector = json.loads((ROOT / "contracts/file-transfer-offer-v1-vectors.json").read_text())
    value = manifest()
    message = create_offer(value, now=vector["created_ms"], message_id=vector["message_id"], ttl_ms=vector["ttl_ms"])
    assert len(canonical(message)) == vector["canonical_bytes"]
    assert sha256(canonical(message)).hexdigest() == vector["canonical_sha256"]
    assert validate_offer(message, value.sender_id, value.receiver_id, now=NOW) == value
    assert "file_transfer" not in CAPABILITY_NAMES


def test_exact_whole_application_limit_accepts_and_one_extra_byte_fails_without_subset():
    value = for_envelope_bytes(APPLICATION_MAX)
    message = create_offer(value, now=NOW, message_id=MESSAGE_ID)
    assert len(canonical(message)) == APPLICATION_MAX
    assert len(validate_offer(message, value.sender_id, value.receiver_id, now=NOW).files) == 128
    excess = for_envelope_bytes(APPLICATION_MAX + 1)
    assert len(canonical(excess.wire())) < APPLICATION_MAX
    with pytest.raises(TransferError, match="file_offer_envelope_too_large"):
        create_offer(excess, now=NOW, message_id=MESSAGE_ID)
    with pytest.raises(TransferError, match="file_offer_envelope_too_large"):
        validate_offer(raw(excess), excess.sender_id, excess.receiver_id, now=NOW)
    assert len(excess.files) == 128


def test_exact_shape_types_header_identity_short_ttl_and_native_peers_are_required():
    value = manifest()
    message = create_offer(value, now=NOW, message_id=MESSAGE_ID)
    changes = [lambda m: m.update(extra=True), lambda m: m.update(v=True), lambda m: m.update(message_id="invalid"),
               lambda m: m.update(kind="personal_sync.attachment_request"), lambda m: m.update(expires_ms=NOW + 60_001),
               lambda m: m["body"].update(version=True), lambda m: m["body"].update(version="1"),
               lambda m: m["body"].update(extra=True), lambda m: m["body"].update(manifest_sha256="0" * 64),
               lambda m: m["body"]["manifest"].update(source_id="f" * 32)]
    for change in changes:
        modified = copy.deepcopy(message)
        change(modified)
        with pytest.raises(TransferError):
            validate_offer(modified, value.sender_id, value.receiver_id, now=NOW)
    for sender, receiver in [("another_sender_01", value.receiver_id), (value.sender_id, "another_receiver_01")]:
        with pytest.raises(TransferError):
            validate_offer(message, sender, receiver, now=NOW)
    with pytest.raises(TransferError):
        create_offer(value, now=NOW, message_id=MESSAGE_ID, ttl_ms=True)
    with pytest.raises(TransferError):
        validate_offer(message, value.sender_id, value.receiver_id, now=NOW + 360_001)
