"""Native descriptor-bound no-replace publication groundwork (#329).

Only a native accepted operation may supply the destination, immutable mapping,
reserved private owner and live binding/publication gate. No directory chooser,
store/key/default creation, network handler, saved ACK or photo baseline exists
here. Closing preserves owned cache for explicit recovery; crash-time publication
proof still needs the durable native receipt/index integration.
"""
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import sys
import threading
from types import MappingProxyType
import unicodedata

from magnolie_file_transfer import (CHUNK_BYTES, FileManifest, ManifestFile, NativeTransferBinding,
    ResumeLedger, TransferError)
from magnolie_publication_journal import ProtectedPublicationJournal, PublicationWitness


@dataclass(frozen=True)
class NativePublishedFile:
    file_id: str
    manifest_sha256: str
    relative_path: str
    sha256: str
    size: int
    device: int
    inode: int
    cleanup_pending: bool

    @property
    def is_saved_receipt(self):
        return False  # Physical readback evidence is not a durable/shared ACK.

    @property
    def grants_write_authority(self):
        return False


class NativeFilePublisher:
    PREFIX = ".magnolie-publication-"
    MAX_DIRECTORY_ENTRIES = 10_000

    def __init__(self, destination, manifest, binding, current_binding, publication_gate, *, owner, targets=None,
            boundary=lambda _: None, journal=None):
        if sys.platform != "linux" or not hasattr(os, "O_NOFOLLOW") or not os.path.isdir("/proc/self/fd"):
            raise TransferError("native_descriptor_publication_platform_required")
        if type(manifest) is not FileManifest or type(binding) is not NativeTransferBinding:
            raise TransferError("native_publication_context_required")
        if (binding.sender_id != manifest.sender_id or binding.receiver_id != manifest.receiver_id
                or type(owner) is not str or re.fullmatch(r"[0-9a-f]{32}", owner) is None):
            raise TransferError("native_publication_identity_mismatch")
        if not callable(current_binding) or not callable(publication_gate) or current_binding() != binding:
            raise TransferError("native_publication_binding_revoked")
        values = {file.id: file.path for file in manifest.files} if targets is None else dict(targets)
        if set(values) != {file.id for file in manifest.files}:
            raise TransferError("native_publication_mapping_incomplete")
        # Reuse the complete native manifest's portable/collision/path checks.
        FileManifest(manifest.transfer_id, manifest.source_id, manifest.sender_id, manifest.receiver_id,
            tuple(ManifestFile(file.id, values[file.id], file.size, file.sha256) for file in manifest.files), manifest.total_bytes)
        if any(part.startswith(self.PREFIX) for path in values.values() for part in path.split("/")):
            raise TransferError("native_publication_reserved_mapping")
        if journal is not None:
            if type(journal) is not ProtectedPublicationJournal:
                raise TransferError("native_publication_journal_required")
            journal.require_new_operation(manifest, binding, values, owner)
        self._journal = journal
        self._manifest, self._binding = manifest, binding
        self._targets = MappingProxyType(values)
        self._current, self._publication_gate, self._boundary = current_binding, publication_gate, boundary
        self._gate = threading.RLock()
        self._root = Path(destination)
        if not self._root.is_absolute() or self._root.resolve(strict=True) != self._root:
            raise TransferError("native_publication_canonical_destination_required")
        self._ancestors = [(path, self._key(os.lstat(path))) for path in (self._root, *self._root.parents)]
        if any(not stat.S_ISDIR(os.lstat(path).st_mode) for path, _ in self._ancestors):
            raise TransferError("native_publication_linked_destination")
        self._root_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self._cache_fd = None
        self._cache_name = self.PREFIX + owner  # Native reserved owner, NOT the peer's transfer ID.
        self._closed = False
        self._owned = {}
        self._published = {}
        self._uncertain = set()
        try:
            self._directory(self._root_fd, private=False)
            self._mutate(lambda: os.mkdir(self._cache_name, mode=0o700, dir_fd=self._root_fd))
            self._cache_fd = os.open(self._cache_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._root_fd)
            self._cache_key = self._key(os.fstat(self._cache_fd))
            os.fsync(self._root_fd)
            self._fresh()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _key(metadata):
        return metadata.st_dev, metadata.st_ino

    @staticmethod
    def _signature(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_uid, value.st_gid,
                value.st_nlink, value.st_mtime_ns, value.st_ctime_ns)

    @property
    def manifest(self):
        return self._manifest

    @property
    def binding(self):
        return self._binding

    @property
    def targets(self):
        return self._targets

    @staticmethod
    def _directory(fd, *, private):
        value = os.fstat(fd)
        if (not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid()
                or value.st_mode & (0o077 if private else 0o022)):
            raise TransferError("native_publication_unsafe_directory")

    def _directories(self):
        if self._closed:
            raise TransferError("native_publication_closed")
        for path, key in self._ancestors:
            value = os.lstat(path)
            if not stat.S_ISDIR(value.st_mode) or self._key(value) != key:
                raise TransferError("native_publication_destination_changed")
        if self._key(os.fstat(self._root_fd)) != self._ancestors[0][1]:
            raise TransferError("native_publication_destination_changed")
        self._directory(self._root_fd, private=False)
        if self._cache_fd is not None:
            value = os.stat(self._cache_name, dir_fd=self._root_fd, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or self._key(value) != self._cache_key:
                raise TransferError("native_publication_cache_changed")
            self._directory(self._cache_fd, private=True)

    def _fresh(self):
        self._directories()
        if self._current() != self.binding:
            raise TransferError("native_publication_binding_revoked")

    def _cache_entries(self):
        names = set()
        with os.scandir(self._cache_fd) as entries:
            for entry in entries:
                if entry.name not in self._owned or len(names) >= len(self._owned) or not entry.is_file(follow_symlinks=False):
                    raise TransferError("native_publication_unknown_cache_preserved")
                names.add(entry.name)
        if names != set(self._owned):
            raise TransferError("native_publication_unknown_cache_preserved")
        return names

    def _mutate(self, action):
        executed = False
        value = None
        def guarded():
            nonlocal executed, value
            if executed:
                raise TransferError("native_publication_gate_repeated")
            executed = True
            self._fresh()
            value = action()
            self._fresh()
        self._fresh()
        self._publication_gate(self.binding, guarded)
        if not executed:
            raise TransferError("native_publication_gate_did_not_execute")
        return value

    @staticmethod
    def _alias(name):
        return unicodedata.normalize("NFC", name).casefold()

    def _check_alias(self, parent, name):
        count = 0
        with os.scandir(parent) as entries:
            for entry in entries:
                count += 1
                if count > self.MAX_DIRECTORY_ENTRIES:
                    raise TransferError("native_publication_directory_limit")
                if self._alias(entry.name) == self._alias(name) and entry.name != name:
                    raise TransferError("native_publication_path_alias")

    def _parents(self, relative):
        fds = [os.dup(self._root_fd)]
        try:
            for name in relative.split("/")[:-1]:
                self._fresh(); self._check_alias(fds[-1], name)
                try:
                    value = os.stat(name, dir_fd=fds[-1], follow_symlinks=False)
                except FileNotFoundError:
                    def create():
                        try:
                            os.mkdir(name, mode=0o700, dir_fd=fds[-1])
                        except FileExistsError:
                            pass
                        os.fsync(fds[-1])
                    self._mutate(create)
                    value = os.stat(name, dir_fd=fds[-1], follow_symlinks=False)
                if not stat.S_ISDIR(value.st_mode):
                    raise TransferError("native_publication_linked_parent")
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1])
                fds.append(fd)
                if self._key(os.fstat(fd)) != self._key(value):
                    raise TransferError("native_publication_parent_changed")
                self._directory(fd, private=False)
            return fds
        except BaseException:
            for fd in reversed(fds):
                os.close(fd)
            raise

    def _chain(self, relative, fds):
        self._fresh()
        for index, name in enumerate(relative.split("/")[:-1]):
            value = os.stat(name, dir_fd=fds[index], follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or self._key(value) != self._key(os.fstat(fds[index + 1])):
                raise TransferError("native_publication_parent_changed")
            self._directory(fds[index + 1], private=False)

    def _data(self, parent, name, key, file, *, links):
        self._directories()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or self._key(before) != key or before.st_uid != os.geteuid()
                    or before.st_mode & 0o077 or before.st_nlink not in links or before.st_size != file.size):
                raise TransferError("native_publication_original_changed")
            digest = sha256(); remaining = file.size
            while remaining:
                part = source.read(min(CHUNK_BYTES, remaining))
                if not part:
                    raise TransferError("native_publication_readback_truncated")
                digest.update(part); remaining -= len(part)
            if source.read(1) or digest.hexdigest() != file.sha256:
                raise TransferError("native_publication_readback_mismatch")
            after = os.fstat(source.fileno())
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (self._key(current) != key or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                    or current.st_size != file.size or current.st_mtime_ns != after.st_mtime_ns
                    or (before.st_mode, before.st_uid, before.st_gid, before.st_nlink, before.st_ctime_ns) !=
                       (after.st_mode, after.st_uid, after.st_gid, after.st_nlink, after.st_ctime_ns)
                    or (current.st_mode, current.st_uid, current.st_gid, current.st_nlink, current.st_ctime_ns) !=
                       (after.st_mode, after.st_uid, after.st_gid, after.st_nlink, after.st_ctime_ns)):
                raise TransferError("native_publication_original_changed")
        self._directories()
        return self._signature(after)

    def publish(self, file_id, ledger, read_chunk):
        with self._gate:
            self._fresh()
            self._cache_entries()
            if (type(ledger) is not ResumeLedger or ledger.manifest != self.manifest or ledger.binding != self.binding):
                raise TransferError("native_publication_ledger_mismatch")
            if file_id in self._uncertain:
                raise TransferError("native_publication_repair_pending")
            file = next((value for value in self.manifest.files if value.id == file_id), None)
            if file is None:
                raise TransferError("native_publication_unknown_member")
            relative = self.targets[file_id]
            fds = self._parents(relative)
            source_fd = None
            try:
                self._chain(relative, fds)
                name = relative.split("/")[-1]
                self._check_alias(fds[-1], name)
                previous = self._published.get(file_id)
                if previous is not None:
                    self._data(fds[-1], name, (previous.device, previous.inode), file, links={1, 2})
                    self._chain(relative, fds)
                    return previous  # Same native operation: no duplicate save.
                try:
                    os.stat(name, dir_fd=fds[-1], follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise TransferError("native_publication_existing_target_preserved")
                ledger.verified_file(file_id, read_chunk)  # Actual staged full SHA/EOF, not totals/timestamps.
                self._fresh()
                temporary = "member-" + file_id + ".part"
                fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600, dir_fd=self._cache_fd)
                key = self._key(os.fstat(fd))
                self._owned[temporary] = (key, None)
                digest = sha256(); offset = 0
                try:
                    while offset < file.size:
                        self._fresh()
                        amount = min(CHUNK_BYTES, file.size - offset)
                        part = read_chunk(file_id, offset, amount)
                        if type(part) is not bytes or len(part) != amount:
                            raise TransferError("native_publication_source_size_changed")
                        view = memoryview(part)
                        while view:
                            self._fresh()
                            written = os.write(fd, view)
                            if written <= 0:
                                raise TransferError("native_publication_stalled_write")
                            digest.update(view[:written]); offset += written; view = view[written:]
                    if read_chunk(file_id, file.size, 1) != b"" or digest.hexdigest() != file.sha256:
                        raise TransferError("native_publication_source_digest_changed")
                    os.fsync(fd)
                finally:
                    try:
                        actual = os.fstat(fd)
                        named = os.stat(temporary, dir_fd=self._cache_fd, follow_symlinks=False)
                        if self._key(actual) == key == self._key(named) and actual.st_size == offset:
                            # Exact bytes successfully written by this native
                            # instance, also after cancellation/partial failure.
                            self._owned[temporary] = (key, ManifestFile(file.id, file.path, offset, digest.hexdigest()))
                    finally:
                        os.close(fd)
                os.fsync(self._cache_fd)
                signature = self._data(self._cache_fd, temporary, key, file, links={1})
                source_fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._cache_fd)
                if self._signature(os.fstat(source_fd)) != signature:
                    raise TransferError("native_publication_original_changed")
                self._boundary("before-publication")
                self._chain(relative, fds)
                witness = PublicationWitness(file_id, key[0], key[1], tuple(self._key(os.fstat(fd)) for fd in fds))
                if self._journal is not None:
                    self._journal.append("prepared", witness)
                def link():
                    self._chain(relative, fds); self._check_alias(fds[-1], name)
                    if (self._signature(os.fstat(source_fd)) != signature or
                            self._key(os.stat(temporary, dir_fd=self._cache_fd, follow_symlinks=False)) != key):
                        raise TransferError("native_publication_original_changed")
                    # Linux linkat via this process's held file descriptor:
                    # a swapped source filename cannot publish a symlink or
                    # a different inode. No full-file IO under the grant gate,
                    # and no unsafe source-path fallback.
                    os.link("/proc/self/fd/" + str(source_fd), name, dst_dir_fd=fds[-1], follow_symlinks=True)
                    # From this exact point onward, a failed ACK/cleanup may not
                    # silently retry another filename or overwrite the target.
                    self._uncertain.add(file_id)
                    os.fsync(fds[-1])
                self._mutate(link)
                if self._journal is not None:
                    self._journal.append("linked", witness)
                self._boundary("published")
                self._data(fds[-1], name, key, file, links={2})
                self._chain(relative, fds)
                if self._journal is not None:
                    self._journal.append("verified", witness)
                    self._chain(relative, fds)
                evidence = NativePublishedFile(file_id, self.manifest.fingerprint, relative, file.sha256, file.size, key[0], key[1], False)
                self._published[file_id] = evidence
                self._uncertain.remove(file_id)
                try:
                    self._data(self._cache_fd, temporary, key, file, links={2})
                    os.unlink(temporary, dir_fd=self._cache_fd)
                    self._owned.pop(temporary)
                    os.fsync(self._cache_fd)
                except (OSError, TransferError):
                    evidence = NativePublishedFile(file_id, self.manifest.fingerprint, relative, file.sha256, file.size, key[0], key[1], True)
                    self._published[file_id] = evidence
                return evidence
            finally:
                if source_fd is not None:
                    os.close(source_fd)
                for fd in reversed(fds):
                    os.close(fd)

    def discard_owned_cache(self):
        """Exact local cache only, also after grant revocation. Never unlinks
        user destination files or removes unknown/private concurrent entries.
        This does not make a publication durable or acknowledge its sender.
        """
        with self._gate:
            self._directories()
            self._cache_entries()
            for name, (key, file) in self._owned.items():
                if file is None:
                    raise TransferError("native_publication_partial_witness_missing")
                self._data(self._cache_fd, name, key, file, links={1, 2})
            for name, (key, file) in list(self._owned.items()):
                self._data(self._cache_fd, name, key, file, links={1, 2})
                os.unlink(name, dir_fd=self._cache_fd); self._owned.pop(name)
            os.fsync(self._cache_fd)
            os.rmdir(self._cache_name, dir_fd=self._root_fd)
            os.fsync(self._root_fd)
            self.close()

    def close(self):
        with self._gate:
            if self._closed:
                return
            self._closed = True
            if self._cache_fd is not None:
                os.close(self._cache_fd)
            os.close(self._root_fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
