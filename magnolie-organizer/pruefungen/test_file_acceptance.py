"""Native accepted manifest/mapping/root persistence without personal folders."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_acceptance import NativeAcceptedDestination, NativeAcceptedTransfer
from magnolie_file_transfer import FileManifest, ManifestFile, TransferError
from test_file_transfer_stage import binding, description
from test_transfer_job_index import Fixture as IndexFixture
from test_file_publish import Fixture as PublisherFixture
from magnolie_publication_journal import ProtectedPublicationJournal


@pytest.fixture
def destination(tmp_path):
    root = tmp_path / "pictures-fixture"
    root.mkdir(mode=0o700)
    return root


def capture(destination, *, manifest=None, targets=None):
    manifest = description() if manifest is None else manifest
    native = binding()
    return NativeAcceptedTransfer.capture(manifest, native,
        {file.id: file.path for file in manifest.files} if targets is None else targets, destination, lambda: native)


def test_full_manifest_mapping_and_original_root_roundtrip_has_no_grant(destination):
    manifest = description()
    mapping = {manifest.files[0].id: "Telefon-Fotos/Blüte.jpg"}
    accepted = capture(destination, targets=mapping)
    mapping[manifest.files[0].id] = "unwanted.jpg"
    restored = NativeAcceptedTransfer.parse(json.loads(json.dumps(accepted.wire())))
    assert restored == accepted and restored.fingerprint == accepted.fingerprint
    assert restored.targets == ((manifest.files[0].id, "Telefon-Fotos/Blüte.jpg"),)
    assert not restored.grants_write_authority and not restored.is_saved_receipt
    assert not restored.destination.grants_write_authority and not list(destination.iterdir())
    restored.verify(lambda: binding())
    with pytest.raises(FrozenInstanceError):
        restored.targets = ()


def test_parse_is_metadata_only_after_destination_disappears(destination):
    accepted = capture(destination)
    raw = accepted.wire()
    destination.rename(destination.with_name("held-original"))
    restored = NativeAcceptedTransfer.parse(raw)
    assert restored == accepted and not destination.exists()
    with pytest.raises(FileNotFoundError):
        restored.verify(lambda: binding())
    assert not destination.exists()


@pytest.mark.parametrize("change", ["root", "ancestor", "mode", "symlink"])
def test_changed_destination_never_becomes_fresh_native_acceptance(destination, change):
    accepted = capture(destination)
    if change == "root":
        destination.rename(destination.with_name("held-original"))
        destination.mkdir(mode=0o700)
    elif change == "ancestor":
        parent = destination.parent
        parent.rename(parent.with_name(parent.name + "-original"))
        parent.mkdir(mode=0o700)
        destination.mkdir(mode=0o700)
    elif change == "mode":
        destination.chmod(0o777)
    else:
        original = destination.with_name("held-original")
        destination.rename(original)
        destination.symlink_to(original, target_is_directory=True)
    with pytest.raises(TransferError, match="destination_changed|unsafe_destination"):
        accepted.verify(lambda: binding())


@pytest.mark.parametrize("change", ["relative", "symlink", "writable"])
def test_capture_rejects_unsafe_native_roots_without_creating_or_fixing_them(destination, change):
    root = destination
    if change == "relative":
        root = Path("not-a-native-absolute-path")
    elif change == "symlink":
        root = destination.with_name("linked-pictures")
        root.symlink_to(destination, target_is_directory=True)
    else:
        root.chmod(0o777)
    with pytest.raises(TransferError):
        capture(root)
    if change == "writable":
        assert root.stat().st_mode & 0o777 == 0o777
    assert not list(destination.iterdir())


def test_capture_and_execution_check_native_binding_before_and_after_destination_read(destination, monkeypatch):
    native = binding()
    with pytest.raises(TransferError, match="binding_revoked"):
        NativeAcceptedTransfer.capture(description(), native, {description().files[0].id: "photo.jpg"}, destination, lambda: None)
    accepted = capture(destination)
    live = native
    original_verify = NativeAcceptedDestination.verify
    def verify(value):
        nonlocal live
        original_verify(value)
        live = None
    monkeypatch.setattr(NativeAcceptedDestination, "verify", verify)
    with pytest.raises(TransferError, match="binding_revoked"):
        accepted.verify(lambda: live)


@pytest.mark.parametrize("change", ["subset", "order", "traversal", "collision", "file-parent", "unknown"])
def test_complete_mapping_and_manifest_order_are_required(destination, change):
    original = description().files[0]
    manifest = replace(description(), files=(original, replace(original, id="d" * 32, path="second.jpg")), total_bytes=10)
    accepted = capture(destination, manifest=manifest)
    value = deepcopy(accepted.wire())
    if change == "subset":
        value["targets"].pop()
    elif change == "order":
        value["targets"].reverse()
    elif change == "traversal":
        value["targets"][0]["path"] = "../personal.jpg"
    elif change == "collision":
        value["targets"][1]["path"] = value["targets"][0]["path"]
    elif change == "file-parent":
        value["targets"][1]["path"] = value["targets"][0]["path"] + "/child.jpg"
    else:
        value["targets"][0]["peer_hint"] = True
    with pytest.raises(TransferError):
        NativeAcceptedTransfer.parse(value)


@pytest.mark.parametrize("change", ["format-bool", "root-format-bool", "inode-bool", "extra", "wrong-peer", "root-depth"])
def test_strict_stored_shapes_never_create_default_acceptance(destination, change):
    value = capture(destination).wire()
    if change == "format-bool":
        value["format"] = True
    elif change == "root-format-bool":
        value["destination"]["format"] = True
    elif change == "inode-bool":
        value["destination"]["ancestor_keys"][0][1] = True
    elif change == "extra":
        value["automatic"] = True
    elif change == "wrong-peer":
        value["binding"]["sender_id"] = "another_sender_fixture_01"
    else:
        value["destination"]["ancestor_keys"].pop()
    with pytest.raises(TransferError):
        NativeAcceptedTransfer.parse(value)


def test_index_persists_complete_acceptance_and_restores_metadata_without_live_grant(tmp_path, destination):
    f = IndexFixture(tmp_path)
    try:
        accepted = capture(destination, targets={f.manifest.files[0].id: "Telefon-Fotos/Blüte.jpg"})
        index = f.open(create=True, accepted=accepted)
        first = index.publish_head(f.handle, None)
        index.close()
        f.current = None
        destination.rename(destination.with_name("held-original"))
        reopened = f.open()
        assert reopened.accepted_transfer == accepted and reopened.snapshot() == first
        assert reopened.accepted_transfer.manifest.wire() == f.manifest.wire()
        with pytest.raises(TransferError, match="binding_revoked"):
            reopened.publish_head(replace(f.handle, checkpoint="3" * 32), first)
        f.current = f.binding
        with pytest.raises(FileNotFoundError):
            reopened.publish_head(replace(f.handle, checkpoint="3" * 32), first)
        assert not destination.exists()
    finally:
        f.close()


def test_legacy_head_index_reopens_with_no_invented_destination_or_mapping(tmp_path):
    f = IndexFixture(tmp_path)
    try:
        index = f.open(create=True)
        head = index.publish_head(f.handle, None)
        original = (f.root / "index.sqlite").read_bytes()
        index.close()
        reopened = f.open()
        assert reopened.accepted_transfer is None and reopened.snapshot() == head
        assert (f.root / "index.sqlite").read_bytes() == original
    finally:
        f.close()


def test_stored_acceptance_cannot_be_reopened_as_another_destination(tmp_path, destination):
    f = IndexFixture(tmp_path)
    try:
        accepted = capture(destination)
        f.open(create=True, accepted=accepted).close()
        other = destination.with_name("other-pictures")
        other.mkdir(mode=0o700)
        with pytest.raises(TransferError, match="owner_changed"):
            f.open(accepted=capture(other))
    finally:
        f.close()


def test_large_complete_native_mapping_is_stored_without_truncation(tmp_path, destination):
    f = IndexFixture(tmp_path)
    try:
        files = tuple(ManifestFile(f"{index:032x}", "Fotos/" + str(index) + "-" + "ü" * 100 + ".jpg", 0,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") for index in range(128))
        f.manifest = FileManifest("a" * 32, "b" * 32, f.binding.sender_id, f.binding.receiver_id, files, 0)
        accepted = capture(destination, manifest=f.manifest)
        f.open(create=True, accepted=accepted).close()
        reopened = f.open()
        assert reopened.accepted_transfer == accepted and len(reopened.accepted_transfer.targets) == 128
        assert len(json.dumps(accepted.wire()).encode()) > 4096
    finally:
        f.close()


def test_restored_index_acceptance_binds_real_publisher_and_private_journal(tmp_path):
    index_fixture = IndexFixture(tmp_path)
    publisher = PublisherFixture(tmp_path)
    try:
        accepted = capture(publisher.destination)
        index_fixture.open(create=True, accepted=accepted).close()
        index = index_fixture.open()
        restored = index.accepted_transfer
        with ProtectedPublicationJournal(index_fixture.parent, restored.manifest, restored.binding, dict(restored.targets),
                index_fixture.cipher.seal, index_fixture.cipher.open, owner=index_fixture.owner, create=True) as journal:
            publisher.open(accepted=restored, journal=journal, targets=dict(restored.targets))
            result = publisher.publish()
            assert publisher.target.read_bytes() == b"hello" and not result.is_saved_receipt
            assert journal.inspect(publisher.file.id).phase == "verified"
            publisher.publisher.discard_owned_cache()
    finally:
        publisher.close()
        index_fixture.close()


@pytest.mark.parametrize("change", ["root", "mapping", "destination", "binding"])
def test_restored_acceptance_cannot_publish_against_changed_native_context(tmp_path, change):
    index_fixture = IndexFixture(tmp_path)
    publisher = PublisherFixture(tmp_path)
    try:
        accepted = capture(publisher.destination)
        index_fixture.open(create=True, accepted=accepted).close()
        restored = index_fixture.open().accepted_transfer
        options = {"accepted": restored}
        if change == "root":
            publisher.destination.rename(tmp_path / "original-destination")
            publisher.destination.mkdir(mode=0o700)
            (publisher.destination / "personal-sentinel").write_bytes(b"keep")
        elif change == "mapping":
            options["targets"] = {publisher.file.id: "other.jpg"}
        elif change == "destination":
            publisher.destination = tmp_path / "other-destination"
            publisher.destination.mkdir(mode=0o700)
        else:
            publisher.current = None
        with pytest.raises(TransferError, match="destination_changed|acceptance_mismatch|binding_revoked"):
            publisher.open(**options)
        assert not publisher.cache.exists() and not publisher.target.exists()
        if change == "root":
            assert (publisher.destination / "personal-sentinel").read_bytes() == b"keep"
    finally:
        publisher.close()
        index_fixture.close()
