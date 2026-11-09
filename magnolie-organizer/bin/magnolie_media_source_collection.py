"""Read-only native Linux collection primitives (#429), not a transfer owner.

The private native picker/composition must supply a current guard. No browser
path, phone mapping, receive destination or old snapshot grants sending here.
This module starts no worker and creates no storage. Missing real birthtime is
HOLD; ctime is a content-change signature, never a substitute generation ID.
"""
from dataclasses import dataclass
from contextlib import contextmanager
import ctypes
import fcntl
from functools import lru_cache
import os
import stat
import struct
import sys
import threading

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_transfer import CHUNK_BYTES, MAX_FILE_BYTES, TransferError
from magnolie_photo_destination import require_media_directory


@lru_cache(maxsize=1)
def _statx_query():
    if sys.platform != 'linux':raise TransferError('media_collection_linux_birthtime_required')
    try:query = ctypes.CDLL(None, use_errno=True).statx
    except AttributeError as error:raise TransferError('media_collection_birthtime_unavailable') from error
    query.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p)
    query.restype = ctypes.c_int
    return query


def _native_witness(fd):
    query = _statx_query()
    data = ctypes.create_string_buffer(256)
    # AT_EMPTY_PATH, STATX_BTIME|STATX_MNT_ID: actual held descriptor, not a
    # resolved name. struct statx has a fixed 256-byte extensible UAPI layout.
    if query(fd, b'', 0x1000, 0x1800, data) != 0:
        raise TransferError('media_collection_birthtime_unavailable') from OSError(ctypes.get_errno(), 'statx')
    mask = struct.unpack_from('=I', data.raw, 0)[0]
    seconds, nanos = struct.unpack_from('=qI', data.raw, 80)
    mount = struct.unpack_from('=Q', data.raw, 144)[0]
    if mask & 0x1800 != 0x1800 or not 0 <= nanos < 1_000_000_000 or mount == 0:
        raise TransferError('media_collection_birthtime_required')
    return (seconds, nanos), mount


def _birthtime(fd):return _native_witness(fd)[0]
def _mount_id(fd):return _native_witness(fd)[1]


def _key(value):return value.st_dev, value.st_ino
def _signature(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns
def _leaf(name):
    if type(name) is not str or not name or name in ('.', '..') or '/' in name or '\0' in name:
        raise TransferError('media_collection_leaf_required')
    try:
        if len(name.encode('utf-8')) > 255:raise TransferError('media_collection_leaf_required')
    except UnicodeError as error:raise TransferError('media_collection_leaf_required') from error
    return name
def _excluded(name):return name.casefold() == 'backup' or name.casefold().startswith('.magnolie-')


@contextmanager
def _entries(fd):
    # A new open description, not dup(fd): scans never share/inherit a cursor.
    scan = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    try:
        with os.scandir(scan) as entries:yield entries
    finally:os.close(scan)


@dataclass(frozen=True)
class NativeCollectionDirectory:
    name: str
    key: tuple
    birthtime: tuple


@dataclass(frozen=True)
class NativeCollectionMember:
    root_key: tuple
    root_birthtime: tuple
    root_mount_id: int
    parents: tuple
    name: str
    key: tuple
    birthtime: tuple
    size: int

    @property
    def grants_read_authority(self):return False
    @property
    def proves_deletion(self):return False


@dataclass(frozen=True)
class NativeCollectionInventory:
    members: tuple
    needs_review: bool


class NativeCollectionRoot:
    """One held read-only native selection, not persisted intent or consent.

    A caller must close/drain its member leases before claiming its own native
    source-END. Closing this root alone makes no such completion assertion.
    """
    def __init__(self, path, native_current):
        if not callable(native_current):raise TransferError('media_collection_native_guard_required')
        self._gate = threading.RLock(); self._closed = threading.Event(); self._fd = None
        self._current = native_current
        require_media_directory(path)
        if any(_excluded(part) for part in str(path).split('/')):raise TransferError('media_collection_private_storage_excluded')
        self._directory = NativeAcceptedDestination.capture(path)
        try:
            if native_current() is False:raise TransferError('media_collection_native_owner_revoked')
            self._fd = os.open(self._directory.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self.key = _key(os.fstat(self._fd)); self.birthtime, self.mount_id = _native_witness(self._fd)
            self._require()
        except BaseException:
            self.close(); raise

    def _require(self):
        with self._gate:
            try:
                if self._closed.is_set() or self._fd is None or self._current() is False:
                    raise TransferError('media_collection_native_owner_revoked')
                self._directory.verify()
                if _key(os.fstat(self._fd)) != self.key or _native_witness(self._fd) != (self.birthtime, self.mount_id):
                    raise TransferError('media_collection_original_root_required')
                named = os.open(self._directory.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    if _key(os.fstat(named)) != self.key or _native_witness(named) != (self.birthtime, self.mount_id):
                        raise TransferError('media_collection_original_root_required')
                finally:os.close(named)
            except BaseException:
                self._closed.set(); raise

    def inventory(self, *, cancelled=lambda:False, maximum_entries=4096, maximum_depth=16):
        with self._gate:
            return self._inventory(cancelled, maximum_entries, maximum_depth)

    def _inventory(self, cancelled, maximum_entries, maximum_depth):
        if (type(maximum_entries) is not int or not 1 <= maximum_entries <= 4096 or
                type(maximum_depth) is not int or not 0 <= maximum_depth <= 16 or not callable(cancelled)):
            raise TransferError('media_collection_inventory_bound')
        members = []; visited = {self.key}; count = 0; review = False
        def current():
            self._require()
            if cancelled():raise TransferError('media_collection_cancelled')
        def walk(fd, parents, expected_key, expected_birth):
            nonlocal count, review
            def directory_current():
                current(); value = os.fstat(fd)
                if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or _key(value) != expected_key or _native_witness(fd) != (expected_birth, self.mount_id):
                    raise TransferError('media_collection_original_parent_required')
            directory_current()
            names = set()
            with _entries(fd) as entries:
                for entry in entries:
                    directory_current(); count += 1
                    if count > maximum_entries:raise TransferError('media_collection_inventory_bound')
                    name = _leaf(entry.name)
                    if name in names:raise TransferError('media_collection_ambiguous_name')
                    names.add(name)
                    if _excluded(name):continue
                    value = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(value.st_mode) or value.st_dev != self.key[0] or value.st_uid != os.geteuid():
                        review = True; continue
                    if not stat.S_ISREG(value.st_mode) and not stat.S_ISDIR(value.st_mode):review = True; continue
                    key = _key(value)
                    if key in visited or stat.S_ISREG(value.st_mode) and value.st_nlink != 1:
                        raise TransferError('media_collection_ambiguous_identity')
                    visited.add(key)
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_DIRECTORY if stat.S_ISDIR(value.st_mode) else os.O_NONBLOCK)
                    child = os.open(name, flags, dir_fd=fd)
                    try:
                        opened = os.fstat(child); birth, mount = _native_witness(child)
                        if mount != self.mount_id:review = True; continue
                        if _signature(opened) != _signature(value):raise TransferError('media_collection_member_changed')
                        if stat.S_ISDIR(opened.st_mode):
                            if len(parents) >= maximum_depth:raise TransferError('media_collection_inventory_bound')
                            walk(child, parents + (NativeCollectionDirectory(name, key, birth),), key, birth)
                        elif not 1 <= opened.st_size <= MAX_FILE_BYTES:review = True
                        else:members.append(NativeCollectionMember(self.key, self.birthtime, self.mount_id, parents, name, key, birth, opened.st_size))
                    finally:os.close(child)
            directory_current()
        current(); walk(self._fd, (), self.key, self.birthtime); current()
        return NativeCollectionInventory(tuple(members), review)

    def open_member(self, member):
        with self._gate:return self._open_member(member)

    def _open_member(self, member):
        if type(member) is not NativeCollectionMember or type(member.parents) is not tuple or len(member.parents) > 16:
            raise TransferError('media_collection_original_member_required')
        if (member.root_key, member.root_birthtime, member.root_mount_id) != (self.key, self.birthtime, self.mount_id):
            raise TransferError('media_collection_original_root_required')
        self._require(); owned = []; parent = self._fd
        try:
            for item in member.parents:
                if type(item) is not NativeCollectionDirectory or _excluded(_leaf(item.name)):
                    raise TransferError('media_collection_original_parent_required')
                child = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                owned.append(child); parent = child
            if _excluded(_leaf(member.name)):raise TransferError('media_collection_private_storage_excluded')
            fd = os.open(member.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent); owned.append(fd)
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            lease = _CollectionReadLease(self, member, tuple(owned)); lease._require(); return lease
        except BaseException:
            for fd in reversed(owned):os.close(fd)
            raise

    def close(self):
        self._closed.set()
        with self._gate:
            if self._fd is not None:os.close(self._fd); self._fd = None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class _CollectionReadLease:
    def __init__(self, root, member, owned):
        self._root = root; self._member = member; self._owned = owned; self._gate = threading.RLock(); self._closed = threading.Event()
        self._signature = _signature(os.fstat(owned[-1]))
    def _require(self):
        # Root close must not release/reuse its descriptor between validation
        # and fd-relative name checks. Member close separately drains reads.
        with self._root._gate:self._require_held_root()

    def _require_held_root(self):
        try:
            if self._closed.is_set():raise TransferError('media_collection_reader_retired')
            self._root._require(); parent = self._root._fd
            for item, fd in zip(self._member.parents, self._owned[:-1]):
                value = os.fstat(fd); named = os.stat(item.name, dir_fd=parent, follow_symlinks=False)
                if (not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or _key(value) != item.key or
                        _key(named) != item.key or not stat.S_ISDIR(named.st_mode) or _native_witness(fd) != (item.birthtime, self._root.mount_id)):
                    raise TransferError('media_collection_original_parent_required')
                parent = fd
            value = os.fstat(self._owned[-1]); named = os.stat(self._member.name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.geteuid() or value.st_nlink != 1 or
                    _key(value) != self._member.key or value.st_size != self._member.size or not 1 <= value.st_size <= MAX_FILE_BYTES or
                    _native_witness(self._owned[-1]) != (self._member.birthtime, self._root.mount_id) or _signature(value) != self._signature or _signature(named) != self._signature):
                raise TransferError('media_collection_original_file_changed')
            self._root._require()
        except BaseException:
            self._closed.set(); raise
    def read_exact(self, offset, count):
        with self._gate:
            self._require()
            if type(offset) is not int or type(count) is not int or offset < 0 or not 1 <= count <= CHUNK_BYTES or offset > self._member.size - count:
                raise TransferError('media_collection_read_bound')
            data = bytearray(count)
            try:
                at = 0
                while at < count:
                    self._require(); read = os.preadv(self._owned[-1], [memoryview(data)[at:]], offset + at)
                    if read == 0:raise TransferError('media_collection_short_read')
                    at += read
                self._require(); return data
            except BaseException:
                data[:] = b'\0' * len(data); self._closed.set(); raise
    def close(self):
        self._closed.set()
        with self._gate:
            for fd in reversed(self._owned):os.close(fd)
            self._owned = ()
    def __enter__(self):
        try:self._require(); return self
        except BaseException:self.close(); raise
    def __exit__(self,*_):self.close()
