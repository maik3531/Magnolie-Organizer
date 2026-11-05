"""Bounded lossless PC-backup primitives (#392), never file mutation authority.

Only held descriptors are used. This module cannot publish, remove, expire,
rename or deduplicate a user's file. The native backup catalog must durably
register a verified representation before retiring an old representation.
"""
from dataclasses import dataclass
from hashlib import sha256
import fcntl
import lzma
import os
import stat

from magnolie_file_transfer import CHUNK_BYTES, MAX_FILE_BYTES, TransferError


DAY_MS = 86400000
MIN_AGE_MS = 30 * DAY_MS
MIN_IDLE_MS = 10 * 60 * 1000
MIN_AVAILABLE_BYTES = 2 * 1024**3
MAX_CPU_PERCENT = 15
XZ_MEMORY_LIMIT = 64 * 1024**2
XZ_PRESET = 1  # Small dictionary; never the very memory-hungry preset 9.


def compression_due(saved_ms, now_ms, retention_days):
    """Age of the backup version, not source EXIF/mtime; zero means Never.

    This scheduling predicate grants no expiry/deletion or IO authority.
    """
    return (type(saved_ms) is int and type(now_ms) is int and type(retention_days) is int
            and retention_days in (0, 90, 365) and 0 < saved_ms < now_ms <= 253402300799999
            and now_ms - saved_ms > MIN_AGE_MS)


def worthwhile(raw_bytes, stored_bytes, extra_bytes=0):
    """At least 10% actual total saving, including representation overhead."""
    return (type(raw_bytes) is int and type(stored_bytes) is int and type(extra_bytes) is int
            and 0 < raw_bytes <= MAX_FILE_BYTES and stored_bytes > 0 and 0 <= extra_bytes <= 1024**2
            and (stored_bytes + extra_bytes) * 10 <= raw_bytes * 9)


@dataclass(frozen=True)
class NativeBackupIdleObservation:
    idle_ms: int
    cpu_percent: int
    available_bytes: int


class NativeBackupIdlePermit:
    """Live native idle/resource observation; unknown observations fail closed.

    Callback is supplied by a native scheduler, never decoded from a UI flag.
    Becoming busy is sticky for this attempt; a fresh attempt observes again.
    It must also be bound to the scheduler's single worker/book/stop ownership.
    """
    def __init__(self, observe, current):
        if not callable(observe) or not callable(current):
            raise TransferError('media_backup_native_idle_required')
        self._observe, self._current, self._revoked = observe, current, False
        self.require_current()

    def require_current(self):
        try:
            value = self._observe()
            if (self._revoked or self._current() is not True or type(value) is not NativeBackupIdleObservation
                    or type(value.idle_ms) is not int or value.idle_ms < MIN_IDLE_MS
                    or type(value.cpu_percent) is not int or not 0 <= value.cpu_percent <= MAX_CPU_PERCENT
                    or type(value.available_bytes) is not int or value.available_bytes < MIN_AVAILABLE_BYTES):
                raise TransferError('media_backup_not_idle')
        except BaseException:
            self._revoked = True
            raise

    def scoped(self, current):
        def allowed():
            self.require_current(); current(); return True
        return NativeBackupIdlePermit(self._observe, allowed)


@dataclass(frozen=True)
class VerifiedBackupRepresentation:
    raw_size: int
    raw_sha256: str
    stored_size: int
    stored_sha256: str
    file_key: tuple
    codec: str = 'xz'

    @property
    def grants_write_authority(self):
        return False


def _signature(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _plain(fd, *, candidate=False):
    value = os.fstat(fd)
    if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_uid != os.geteuid()
            or value.st_mode & 0o077 or value.st_size > MAX_FILE_BYTES):
        raise TransferError('media_backup_original_private_file_required')
    mode = fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE
    if mode != (os.O_RDWR if candidate else os.O_RDONLY):
        raise TransferError('media_backup_descriptor_mode_invalid')
    return value


def _expected(size, digest):
    if (type(size) is not int or not 0 <= size <= MAX_FILE_BYTES or type(digest) is not str
            or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
        raise TransferError('media_backup_original_digest_required')


def verify_raw(fd, size, digest, current, *, candidate=False):
    """Full held-file verification before reusing an existing content object."""
    _expected(size, digest)
    current(); before = _plain(fd, candidate=candidate)
    if before.st_size != size:
        raise TransferError('media_backup_original_content_changed')
    actual = sha256(); offset = 0
    while offset < size:
        current(); part = os.pread(fd, min(CHUNK_BYTES, size - offset), offset)
        if not part:
            raise TransferError('media_backup_original_content_changed')
        actual.update(part); offset += len(part)
    current()
    if actual.hexdigest() != digest or os.pread(fd, 1, offset) or _signature(os.fstat(fd)) != _signature(before):
        raise TransferError('media_backup_original_content_changed')
    return before


def verify_xz(fd, raw_size, raw_digest, current, *, candidate=False, consume=None):
    """Exactly ONE XZ stream, bounded output and decoder memory, no extraction paths."""
    _expected(raw_size, raw_digest)
    current(); before = _plain(fd, candidate=candidate)
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=XZ_MEMORY_LIMIT)
    raw = sha256(); stored = sha256(); offset = total = 0
    while not decoder.eof:
        current()
        if decoder.needs_input:
            data = os.pread(fd, min(CHUNK_BYTES, before.st_size - offset), offset)
            if not data:
                raise TransferError('media_backup_xz_truncated')
            offset += len(data); stored.update(data)
        else:
            data = b''
        part = decoder.decompress(data, max_length=min(CHUNK_BYTES, raw_size - total + 1))
        total += len(part)
        if total > raw_size:
            raise TransferError('media_backup_xz_output_limit')
        raw.update(part)
        if part and consume is not None:
            current(); consume(part); current()
    current()
    if (decoder.unused_data or offset != before.st_size or total != raw_size or raw.hexdigest() != raw_digest
            or os.pread(fd, 1, offset) or _signature(os.fstat(fd)) != _signature(before)):
        raise TransferError('media_backup_xz_content_changed')
    return VerifiedBackupRepresentation(raw_size, raw_digest, before.st_size, stored.hexdigest(), (before.st_dev, before.st_ino))


def content_key(raw_size, raw_digest):
    """Name-independent key, NOT evidence that an existing object is intact."""
    _expected(raw_size, raw_digest)
    return f'{raw_digest}-{raw_size}'


def copy_unique(source_fd, candidate_fd, raw_size, raw_digest, current):
    """Copy a genuinely new object only; catalog checks existing objects first.

    No links to writable originals and no filename-based content identity.
    """
    before = verify_raw(source_fd, raw_size, raw_digest, current)
    target = _plain(candidate_fd, candidate=True)
    if target.st_size or (before.st_dev, before.st_ino) == (target.st_dev, target.st_ino):
        raise TransferError('media_backup_new_candidate_required')
    offset = 0
    while offset < raw_size:
        current(); data = os.pread(source_fd, min(CHUNK_BYTES, raw_size - offset), offset)
        if not data:
            raise TransferError('media_backup_original_content_changed')
        position = 0
        while position < len(data):
            current(); count = os.pwrite(candidate_fd, data[position:], offset + position)
            if count <= 0:
                raise TransferError('media_backup_candidate_short_write')
            position += count
        offset += len(data)
    os.fsync(candidate_fd); current()
    copied = verify_raw(candidate_fd, raw_size, raw_digest, current, candidate=True)
    original = verify_raw(source_fd, raw_size, raw_digest, current)
    if _signature(copied)[:6] != _signature(target)[:6] or _signature(original) != _signature(before):
        raise TransferError('media_backup_original_content_changed')
    return VerifiedBackupRepresentation(raw_size, raw_digest, raw_size, raw_digest,
        (target.st_dev, target.st_ino), codec='raw')


def restore_to_new_file(stored_fd, candidate_fd, representation, current):
    """Automatic bounded decoding into a NEW private unpublished file.

    No publication, reassociation, Saved/END, deletion replay or overwrite. The
    caller's native restore journal still controls mapping and no-replace move.
    """
    if type(representation) is not VerifiedBackupRepresentation or representation.codec not in ('raw', 'xz'):
        raise TransferError('media_backup_representation_required')
    current(); source = _plain(stored_fd); target = _plain(candidate_fd, candidate=True)
    if (source.st_dev, source.st_ino) != representation.file_key or source.st_size != representation.stored_size:
        raise TransferError('media_backup_original_representation_changed')
    if target.st_size or (target.st_dev, target.st_ino) == representation.file_key:
        raise TransferError('media_backup_new_candidate_required')
    if representation.codec == 'raw':
        if representation.stored_size != representation.raw_size or representation.stored_sha256 != representation.raw_sha256:
            raise TransferError('media_backup_original_representation_changed')
        return copy_unique(stored_fd, candidate_fd, representation.raw_size, representation.raw_sha256, current)
    observed = verify_xz(stored_fd, representation.raw_size, representation.raw_sha256, current)
    if observed != representation:
        raise TransferError('media_backup_original_representation_changed')
    offset = 0

    def consume(data):
        nonlocal offset
        position = 0
        while position < len(data):
            current(); count = os.pwrite(candidate_fd, data[position:], offset)
            if count <= 0:
                raise TransferError('media_backup_candidate_short_write')
            position += count; offset += count

    second = verify_xz(stored_fd, representation.raw_size, representation.raw_sha256, current, consume=consume)
    if second != representation:
        raise TransferError('media_backup_original_representation_changed')
    os.fsync(candidate_fd); current()
    copied = verify_raw(candidate_fd, representation.raw_size, representation.raw_sha256, current, candidate=True)
    if _signature(copied)[:6] != _signature(target)[:6]:
        raise TransferError('media_backup_original_representation_changed')
    return VerifiedBackupRepresentation(representation.raw_size, representation.raw_sha256, representation.raw_size,
        representation.raw_sha256, (target.st_dev, target.st_ino), codec='raw')


def compress_candidate(source_fd, candidate_fd, raw_size, raw_digest, permit, *, extra_bytes=0):
    """Prepare and verify only. None means not profitable; source is NEVER changed.

    Caller owns a private, new, O_EXCL/O_NOFOLLOW temporary descriptor. Neither
    that temporary nor the original is unlinked here, including on exceptions.
    Successful result still requires the native catalog's publication journal.
    """
    if type(permit) is not NativeBackupIdlePermit:
        raise TransferError('media_backup_native_idle_required')
    _expected(raw_size, raw_digest)
    if type(extra_bytes) is not int or not 0 <= extra_bytes <= 1024**2:
        raise TransferError('media_backup_overhead_invalid')
    current = permit.require_current
    before = verify_raw(source_fd, raw_size, raw_digest, current)
    target = _plain(candidate_fd, candidate=True)
    if target.st_size or (before.st_dev, before.st_ino) == (target.st_dev, target.st_ino):
        raise TransferError('media_backup_new_candidate_required')
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_XZ, check=lzma.CHECK_SHA256, preset=XZ_PRESET)
    digest = sha256(); offset = written = 0

    def write(data):
        nonlocal written
        position = 0
        while position < len(data):
            current()
            if written + len(data) - position + extra_bytes > raw_size * 9 // 10:
                return False
            count = os.pwrite(candidate_fd, data[position:position + CHUNK_BYTES], written)
            if count <= 0:
                raise TransferError('media_backup_candidate_short_write')
            written += count; position += count
        return True

    while offset < raw_size:
        current(); part = os.pread(source_fd, min(CHUNK_BYTES, raw_size - offset), offset)
        if not part:
            raise TransferError('media_backup_original_content_changed')
        digest.update(part); offset += len(part)
        if not write(compressor.compress(part)):
            return None
    current()
    if digest.hexdigest() != raw_digest or os.pread(source_fd, 1, offset) or _signature(os.fstat(source_fd)) != _signature(before):
        raise TransferError('media_backup_original_content_changed')
    if not write(compressor.flush()) or not worthwhile(raw_size, written, extra_bytes):
        return None
    os.fsync(candidate_fd); current()
    allocated_source = before.st_blocks * 512
    allocated_target = os.fstat(candidate_fd).st_blocks * 512
    if not worthwhile(allocated_source, allocated_target, extra_bytes):
        return None  # Sparse or block-rounded files must save real disk space too.
    result = verify_xz(candidate_fd, raw_size, raw_digest, current, candidate=True)
    original = verify_raw(source_fd, raw_size, raw_digest, current)
    if result.file_key != (target.st_dev, target.st_ino) or _signature(original) != _signature(before):
        raise TransferError('media_backup_original_content_changed')
    return result
