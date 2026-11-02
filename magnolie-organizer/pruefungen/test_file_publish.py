"""Real private encrypted stage and Linux filesystem; no personal Pictures data."""
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_publish import NativeFilePublisher
from magnolie_file_transfer import CHUNK_BYTES, ResumeLedger, TransferError
from test_file_transfer_stage import FixtureCipher, binding, description, stage


class Fixture:
    def __init__(self, root, data=b"hello", *, path="Photos/Blüte.jpg"):
        self.root = root
        self.manifest = replace(description(data), files=(replace(description(data).files[0], path=path),))
        self.binding = binding()
        self.current = self.binding
        self.destination = root / "pictures-fixture"
        self.destination.mkdir(mode=0o700)
        private = root / "stage-fixture"
        private.mkdir(mode=0o700)
        self.stage = stage(private, self.manifest, self.binding, FixtureCipher(), current=lambda: self.current)
        self.stage.create()
        self.ledger = ResumeLedger(self.manifest, self.binding, lambda: self.current)
        self.file = self.manifest.files[0]
        for index in range(self.file.chunks):
            self.ledger.record(self.file.id, index, data[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES],
                self.stage.write_chunk, self.stage.read_chunk)
        self.gate = lambda _, action: action()
        self.boundary = lambda _: None
        self.publisher = None

    def open(self, **options):
        self.publisher = NativeFilePublisher(self.destination, self.manifest, self.binding, lambda: self.current,
            lambda bound, action: self.gate(bound, action), owner="1" * 32,
            boundary=lambda point: self.boundary(point), **options)
        return self.publisher

    @property
    def cache(self):
        return self.destination / (NativeFilePublisher.PREFIX + "1" * 32)

    @property
    def target(self):
        return self.destination / self.file.path

    def publish(self, reader=None):
        return self.publisher.publish(self.file.id, self.ledger, reader or self.stage.read_chunk)

    def close(self):
        if self.publisher:
            self.publisher.close()
        self.stage.close()


@pytest.fixture
def fixture(tmp_path):
    f = Fixture(tmp_path)
    try:
        yield f
    finally:
        f.close()


@pytest.mark.parametrize("data", [b"hello", b"", b"a" * CHUNK_BYTES + b"tail"])
def test_actual_unicode_nested_no_replace_readback_and_duplicate_call(tmp_path, data):
    f = Fixture(tmp_path, data)
    try:
        publisher = f.open()
        result = f.publish()
        assert f.target.read_bytes() == data and result.sha256 == sha256(data).hexdigest()
        assert (result.device, result.inode) == (f.target.stat().st_dev, f.target.stat().st_ino)
        assert not result.is_saved_receipt and not result.grants_write_authority and not result.cleanup_pending
        assert f.publish() is result and list(f.cache.iterdir()) == []
        publisher.discard_owned_cache()
        assert not f.cache.exists() and f.target.read_bytes() == data
    finally:
        f.close()


def test_mapping_is_copied_complete_and_public_context_is_immutable(fixture):
    f = fixture
    mapping = {f.file.id: "Andere/Neu.jpg"}
    publisher = f.open(targets=mapping)
    mapping[f.file.id] = "unwanted.jpg"
    with pytest.raises(TypeError):
        publisher.targets[f.file.id] = "unwanted.jpg"
    for field in ("manifest", "binding", "targets"):
        with pytest.raises(AttributeError):
            setattr(publisher, field, None)
    result = f.publish()
    assert result.relative_path == "Andere/Neu.jpg"
    assert (f.destination / result.relative_path).read_bytes() == b"hello" and not f.target.exists()


@pytest.mark.parametrize("data", [b"hello", b"personal-unknown"])
def test_even_equal_existing_target_is_never_adopted_or_overwritten(fixture, data):
    f = fixture
    f.target.parent.mkdir(mode=0o700)
    f.target.write_bytes(data)
    inode = f.target.stat().st_ino
    f.open()
    with pytest.raises(TransferError, match="existing_target_preserved"):
        f.publish()
    assert f.target.read_bytes() == data and f.target.stat().st_ino == inode
    f.publisher.discard_owned_cache()


@pytest.mark.parametrize("kind", ["case", "unicode", "symlink-parent", "symlink-target"])
def test_aliases_and_symlinks_preserve_unknown_files(fixture, kind):
    f = fixture
    outside = f.root / "outside"
    outside.mkdir()
    sentinel = outside / "personal"
    sentinel.write_bytes(b"keep")
    if kind == "case":
        (f.destination / "photos").mkdir()
    elif kind == "symlink-parent":
        (f.destination / "Photos").symlink_to(outside, target_is_directory=True)
    else:
        f.target.parent.mkdir(mode=0o700)
        if kind == "unicode":
            (f.target.parent / "Blu\u0308te.jpg").write_bytes(b"unknown")
        else:
            f.target.symlink_to(sentinel)
    f.open()
    with pytest.raises(TransferError, match="alias|linked_parent|existing_target"):
        f.publish()
    assert sentinel.read_bytes() == b"keep"


@pytest.mark.parametrize("mode", ["noop", "repeat", "revoke"])
def test_native_gate_must_execute_exactly_once_and_recheck_binding(fixture, mode):
    f = fixture
    f.open()
    f.target.parent.mkdir(mode=0o700)
    if mode == "noop":
        f.gate = lambda _, action: None
    elif mode == "repeat":
        def repeated(_, action):
            action()
            action()
        f.gate = repeated
    else:
        def revoked(_, action):
            f.current = None
            action()
        f.gate = revoked
    with pytest.raises(TransferError, match="gate_did_not_execute|gate_repeated|binding_revoked"):
        f.publish()
    if mode == "repeat":
        assert f.target.read_bytes() == b"hello"
        with pytest.raises(TransferError, match="repair_pending"):
            f.publish()
    else:
        assert not f.target.exists()
    f.publisher.discard_owned_cache()
    assert not f.cache.exists()


@pytest.mark.parametrize("point", ["before-publication", "published"])
def test_revocation_before_link_blocks_and_after_link_retains_uncertainty(fixture, point):
    f = fixture
    f.open()
    def boundary(actual):
        if actual == point:
            f.current = None
    f.boundary = boundary
    with pytest.raises(TransferError, match="binding_revoked"):
        f.publish()
    assert f.target.exists() == (point == "published")
    f.current = f.binding
    if point == "published":
        with pytest.raises(TransferError, match="repair_pending"):
            f.publish()
    f.current = None
    f.publisher.discard_owned_cache()
    if point == "published":
        assert f.target.read_bytes() == b"hello"


@pytest.mark.parametrize("kind", ["parent", "cache", "temporary", "destination"])
def test_path_swaps_never_publish_or_delete_unknown_replacements(fixture, kind):
    f = fixture
    f.open()
    def boundary(point):
        if point != "before-publication":
            return
        path = {"parent": f.target.parent, "cache": f.cache, "temporary": f.cache / ("member-" + f.file.id + ".part"),
            "destination": f.destination}[kind]
        path.rename(path.with_name(path.name + "-original"))
        if kind == "temporary":
            path.write_bytes(b"unknown")
        else:
            path.mkdir()
            (path / "unknown").write_bytes(b"keep")
    f.boundary = boundary
    with pytest.raises((TransferError, FileNotFoundError)):
        f.publish()
    assert not f.target.exists()
    if kind == "parent":
        # Only the destination parent changed; private original cache remains
        # independently removable, without touching either destination tree.
        f.publisher.discard_owned_cache()
        assert (f.target.parent / "unknown").read_bytes() == b"keep"
    else:
        with pytest.raises((TransferError, FileNotFoundError)):
            f.publisher.discard_owned_cache()


def test_source_failure_tracks_exact_partial_bytes_for_explicit_revoked_cleanup(tmp_path):
    f = Fixture(tmp_path, b"a" * CHUNK_BYTES + b"tail")
    try:
        f.open()
        passes = 0
        def reader(file_id, offset, size):
            nonlocal passes
            if offset == 0:
                passes += 1
            if passes == 2 and offset == CHUNK_BYTES:
                raise OSError("synthetic source read failure")
            return f.stage.read_chunk(file_id, offset, size)
        with pytest.raises(OSError, match="synthetic"):
            f.publish(reader)
        assert not f.target.exists()
        temporary = next(f.cache.iterdir())
        assert temporary.read_bytes() == b"a" * CHUNK_BYTES
        f.current = None
        f.publisher.discard_owned_cache()
        assert not f.cache.exists()
    finally:
        f.close()


def test_unknown_cache_entries_and_changed_originals_are_preserved(fixture):
    f = fixture
    f.open()
    unknown = f.cache / "unknown"
    unknown.write_bytes(b"keep")
    with pytest.raises(TransferError, match="unknown_cache_preserved"):
        f.publish()
    with pytest.raises(TransferError, match="unknown_cache_preserved"):
        f.publisher.discard_owned_cache()
    assert unknown.read_bytes() == b"keep"


def test_close_preserves_cache_and_new_constructor_never_adopts_existing_owner(fixture):
    f = fixture
    f.open().close()
    assert f.cache.is_dir()
    with pytest.raises(FileExistsError):
        f.open()
    assert f.cache.is_dir()


@pytest.mark.parametrize("kind", ["writable", "symlink", "mapping", "reserved"])
def test_unsafe_root_and_invalid_mapping_fail_without_adoption(fixture, kind):
    f = fixture
    options = {}
    if kind == "writable":
        f.destination.chmod(0o777)
    elif kind == "symlink":
        link = f.root / "linked-root"
        link.symlink_to(f.destination, target_is_directory=True)
        f.destination = link
    elif kind == "mapping":
        options["targets"] = {}
    else:
        options["targets"] = {f.file.id: NativeFilePublisher.PREFIX + "x/photo.jpg"}
    with pytest.raises(TransferError):
        f.open(**options)
    assert not f.cache.exists()


def test_target_created_at_last_gate_is_preserved_without_retry_name(fixture):
    f = fixture
    f.open()
    def boundary(point):
        if point == "before-publication":
            f.target.write_bytes(b"concurrent personal file")
    f.boundary = boundary
    with pytest.raises(FileExistsError):
        f.publish()
    assert f.target.read_bytes() == b"concurrent personal file"
    assert sorted(p.name for p in f.target.parent.iterdir()) == [f.target.name]
    f.publisher.discard_owned_cache()
    assert f.target.read_bytes() == b"concurrent personal file"


@pytest.mark.parametrize("kind", ["directory-fsync", "readback-fault", "changed-content"])
def test_after_link_faults_hold_uncertain_publication_and_never_duplicate(fixture, monkeypatch, kind):
    f = fixture
    publisher = f.open()
    original_fsync = os.fsync
    if kind == "directory-fsync":
        def fsync(fd):
            if f.target.exists():
                raise OSError("synthetic post-link fsync fault")
            return original_fsync(fd)
        monkeypatch.setattr(os, "fsync", fsync)
    else:
        def boundary(point):
            if point == "published":
                if kind == "readback-fault":
                    raise OSError("synthetic post-link readback fault")
                f.target.write_bytes(b"other")
        f.boundary = boundary
    with pytest.raises((OSError, TransferError)):
        f.publish()
    monkeypatch.setattr(os, "fsync", original_fsync)
    assert f.target.exists()
    with pytest.raises(TransferError, match="repair_pending"):
        f.publish()
    if kind == "changed-content":
        with pytest.raises(TransferError, match="readback_mismatch"):
            publisher.discard_owned_cache()
        assert f.target.read_bytes() == b"other" and list(f.cache.iterdir())
    else:
        publisher.discard_owned_cache()
        assert f.target.read_bytes() == b"hello"


@pytest.mark.parametrize("written", [0, 2])
def test_zero_and_partial_native_write_failure_cleanup_uses_actual_owned_bytes(fixture, monkeypatch, written):
    f = fixture
    f.open()
    original_write = os.write
    calls = 0
    def write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1 and written:
            return original_write(fd, data[:written])
        raise OSError("synthetic write failure")
    monkeypatch.setattr(os, "write", write)
    with pytest.raises(OSError, match="synthetic write"):
        f.publish()
    monkeypatch.setattr(os, "write", original_write)
    assert next(f.cache.iterdir()).read_bytes() == b"hello"[:written]
    f.current = None
    f.publisher.discard_owned_cache()
    assert not f.cache.exists() and not f.target.exists()


def test_changed_same_operation_target_is_not_returned_as_original_evidence(fixture):
    f = fixture
    f.open()
    f.publish()
    f.target.write_bytes(b"other")
    with pytest.raises(TransferError, match="readback_mismatch"):
        f.publish()
    f.publisher.discard_owned_cache()
    assert f.target.read_bytes() == b"other"


def test_missing_original_partial_witness_cannot_be_adopted_for_cleanup(fixture):
    f = fixture
    publisher = f.open()
    def boundary(point):
        if point == "before-publication":
            raise OSError("synthetic interruption")
    f.boundary = boundary
    with pytest.raises(OSError, match="synthetic"):
        f.publish()
    name, (key, _) = next(iter(publisher._owned.items()))
    publisher._owned[name] = (key, None)  # Explicit native unknown-witness boundary.
    with pytest.raises(TransferError, match="partial_witness_missing"):
        publisher.discard_owned_cache()
    assert (f.cache / name).read_bytes() == b"hello"


def test_native_gate_does_not_hash_full_files_under_permission_lock(fixture, monkeypatch):
    f = fixture
    publisher = f.open()
    locked = False
    original_data = publisher._data
    def readback(*args, **kwargs):
        assert not locked
        return original_data(*args, **kwargs)
    def gate(_, action):
        nonlocal locked
        locked = True
        try:
            action()
        finally:
            locked = False
    monkeypatch.setattr(publisher, "_data", readback)
    f.gate = gate
    f.publish()
    assert f.target.read_bytes() == b"hello"
