"""Real lossless XZ bytes and native descriptor boundaries; no user data."""
from hashlib import sha256
from pathlib import Path
import lzma
import os
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_media_backup_codec import (
    DAY_MS, MIN_IDLE_MS, MIN_AVAILABLE_BYTES, NativeBackupIdleObservation,
    NativeBackupIdlePermit, compression_due, compress_candidate, verify_raw,
    verify_xz, worthwhile, content_key, copy_unique, restore_to_new_file,
)
from magnolie_file_transfer import TransferError


def idle():
    return NativeBackupIdleObservation(MIN_IDLE_MS, 0, MIN_AVAILABLE_BYTES)


def permit(observe=idle, current=lambda: True):
    return NativeBackupIdlePermit(observe, current)


def files(tmp_path, raw):
    source = tmp_path / 'original.jpg'
    source.write_bytes(raw); source.chmod(0o600)
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    candidate = tmp_path / 'candidate.xz'
    target_fd = os.open(candidate, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return source, source_fd, candidate, target_fd


def test_age_retention_and_exact_ten_percent_boundary():
    created = DAY_MS
    for days in (0, 90, 365):
        assert not compression_due(created, created + 30 * DAY_MS, days)
        assert compression_due(created, created + 30 * DAY_MS + 1, days)
    for days in (7, 30, -1, True, '365'):
        assert not compression_due(created, created + 60 * DAY_MS, days)
    assert not compression_due(created, created - 1, 0)
    assert worthwhile(1000, 890, 10)
    assert not worthwhile(1000, 891, 10)
    assert not worthwhile(0, 1)


@pytest.mark.parametrize('observation', [None, True,
    NativeBackupIdleObservation(MIN_IDLE_MS - 1, 0, MIN_AVAILABLE_BYTES),
    NativeBackupIdleObservation(MIN_IDLE_MS, 16, MIN_AVAILABLE_BYTES),
    NativeBackupIdleObservation(MIN_IDLE_MS, 0, MIN_AVAILABLE_BYTES - 1)])
def test_unknown_busy_or_low_resource_observation_cannot_admit_work(observation):
    with pytest.raises(TransferError):
        permit(lambda: observation)


def test_real_xz_round_trip_verifies_source_and_candidate_without_replacing_either(tmp_path):
    raw = b'original photo bytes and EXIF must be preserved\0' * 12000
    source, source_fd, candidate, target_fd = files(tmp_path, raw)
    original = source.stat()
    try:
        result = compress_candidate(source_fd, target_fd, len(raw), sha256(raw).hexdigest(), permit(), extra_bytes=4096)
        assert result and not result.grants_write_authority
        assert worthwhile(len(raw), result.stored_size, 4096)
        assert result.stored_sha256 == sha256(candidate.read_bytes()).hexdigest()
        assert lzma.decompress(candidate.read_bytes()) == raw
        assert source.read_bytes() == raw
        assert (source.stat().st_ino, source.stat().st_mtime_ns) == (original.st_ino, original.st_mtime_ns)
        assert result.file_key == (os.fstat(target_fd).st_dev, os.fstat(target_fd).st_ino)
    finally:
        os.close(source_fd); os.close(target_fd)


def test_already_compressed_random_media_is_not_claimed_profitable(tmp_path):
    raw = os.urandom(256 * 1024)
    source, source_fd, _, target_fd = files(tmp_path, raw)
    try:
        assert compress_candidate(source_fd, target_fd, len(raw), sha256(raw).hexdigest(), permit()) is None
        assert source.read_bytes() == raw
    finally:
        os.close(source_fd); os.close(target_fd)


def test_idle_revocation_is_sticky_and_keeps_original(tmp_path):
    raw = b'keep original' * 50000
    source, source_fd, _, target_fd = files(tmp_path, raw)
    active = [True]; current = permit(current=lambda: active[0])
    active[0] = False
    try:
        with pytest.raises(TransferError):
            compress_candidate(source_fd, target_fd, len(raw), sha256(raw).hexdigest(), current)
        active[0] = True
        with pytest.raises(TransferError): current.require_current()
        assert source.read_bytes() == raw and os.fstat(target_fd).st_size == 0
    finally:
        os.close(source_fd); os.close(target_fd)


def test_wrong_digest_nonempty_candidate_or_linked_object_cannot_be_reused(tmp_path):
    raw = b'original' * 20000
    source, source_fd, candidate, target_fd = files(tmp_path, raw)
    try:
        with pytest.raises(TransferError):
            verify_raw(source_fd, len(raw), '0' * 64, lambda: None)
        os.pwrite(target_fd, b'existing bytes', 0)
        with pytest.raises(TransferError):
            compress_candidate(source_fd, target_fd, len(raw), sha256(raw).hexdigest(), permit())
        assert candidate.read_bytes() == b'existing bytes'
        os.link(source, tmp_path / 'shared-writable-alias')
        with pytest.raises(TransferError): verify_raw(source_fd, len(raw), sha256(raw).hexdigest(), lambda: None)
        assert source.read_bytes() == raw
    finally:
        os.close(source_fd); os.close(target_fd)


def test_new_object_and_name_independent_identity_do_not_share_mutable_original_inode(tmp_path):
    raw = b'unchanged original' * 10000
    source, source_fd, candidate, target_fd = files(tmp_path, raw)
    digest = sha256(raw).hexdigest()
    try:
        result = copy_unique(source_fd, target_fd, len(raw), digest, lambda: None)
        assert result.codec == 'raw' and candidate.read_bytes() == raw
        assert result.file_key != (source.stat().st_dev, source.stat().st_ino)
        assert source.stat().st_nlink == candidate.stat().st_nlink == 1
        differently_named = tmp_path / 'different filename.mp4'
        differently_named.write_bytes(raw); differently_named.chmod(0o600)
        fd = os.open(differently_named, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            verify_raw(fd, len(raw), digest, lambda: None)
            assert content_key(len(raw), digest) == content_key(result.raw_size, result.raw_sha256)
            with pytest.raises(TransferError): verify_raw(fd, len(raw), '0' * 64, lambda: None)
        finally: os.close(fd)
    finally:
        os.close(source_fd); os.close(target_fd)


def test_verified_compressed_object_restores_into_new_file_and_never_overwrites_existing(tmp_path):
    raw = b'original JPEG and EXIF\0' * 30000
    source, source_fd, compressed, target_fd = files(tmp_path, raw)
    stored_fd = restored_fd = None
    try:
        result = compress_candidate(source_fd, target_fd, len(raw), sha256(raw).hexdigest(), permit())
        assert result
        os.close(target_fd); target_fd = None
        stored_fd = os.open(compressed, os.O_RDONLY | os.O_NOFOLLOW)
        restored_path = tmp_path / 'restored.jpg'
        restored_fd = os.open(restored_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        restored = restore_to_new_file(stored_fd, restored_fd, result, lambda: None)
        assert restored.codec == 'raw' and restored_path.read_bytes() == raw
        assert restored.file_key != result.file_key
        with pytest.raises(TransferError): restore_to_new_file(stored_fd, restored_fd, result, lambda: None)
        assert restored_path.read_bytes() == source.read_bytes() == raw
    finally:
        for fd in (source_fd, target_fd, stored_fd, restored_fd):
            if fd is not None: os.close(fd)


def test_changed_encoded_representation_cannot_touch_restore_target(tmp_path):
    raw = b'original bytes' * 30000
    _, source_fd, compressed, target_fd = files(tmp_path, raw)
    stored_fd = restored_fd = None
    try:
        result = compress_candidate(source_fd, target_fd, len(raw), sha256(raw).hexdigest(), permit())
        assert result
        os.close(target_fd); target_fd = None
        damaged = bytearray(compressed.read_bytes()); damaged[len(damaged) // 2] ^= 1
        compressed.write_bytes(damaged)
        stored_fd = os.open(compressed, os.O_RDONLY | os.O_NOFOLLOW)
        restored_fd = os.open(tmp_path / 'untouched-new-file', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with pytest.raises((TransferError, lzma.LZMAError)):
            restore_to_new_file(stored_fd, restored_fd, result, lambda: None)
        assert os.fstat(restored_fd).st_size == 0
    finally:
        for fd in (source_fd, target_fd, stored_fd, restored_fd):
            if fd is not None: os.close(fd)


def test_logically_compressible_sparse_file_is_not_a_real_space_saving(tmp_path):
    path = tmp_path / 'sparse-original'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    size = 1024 * 1024
    os.ftruncate(fd, size); os.close(fd)
    source_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    candidate_fd = os.open(tmp_path / 'candidate', os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        assert os.fstat(source_fd).st_blocks == 0
        assert compress_candidate(source_fd, candidate_fd, size, sha256(bytes(size)).hexdigest(), permit()) is None
        assert path.stat().st_size == size and path.stat().st_blocks == 0
    finally: os.close(source_fd); os.close(candidate_fd)


@pytest.mark.parametrize('change', ['truncated', 'trailing', 'two-streams', 'too-much-output', 'digest'])
def test_corrupt_trailing_or_expanding_archives_are_never_accepted(tmp_path, change):
    raw = b'lossless' * 10000
    encoded = lzma.compress(raw, preset=1)
    if change == 'truncated': encoded = encoded[:-5]
    if change == 'trailing': encoded += b'garbage'
    if change == 'two-streams': encoded += lzma.compress(b'additional payload')
    path = tmp_path / 'archive.xz'; path.write_bytes(encoded); path.chmod(0o600)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with pytest.raises((TransferError, lzma.LZMAError)):
            verify_xz(fd, len(raw) - (1 if change == 'too-much-output' else 0),
                '0' * 64 if change == 'digest' else sha256(raw).hexdigest(), lambda: None)
    finally: os.close(fd)
