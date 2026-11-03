"""Native protected accepted-job discovery and conservative cache reservations.

No transfer worker, key/store creation, destination writes or implicit resume.
Reservations deliberately have no release/delete shortcut: real private-cache
retirement evidence must be integrated before quota may be returned (#330).
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import weakref

from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_transfer import EncryptedTransferStage, TransferError


_ROOT_GATES = weakref.WeakValueDictionary()
_ROOT_GATES_LOCK = threading.Lock()
_LOCAL = threading.local()


@dataclass(frozen=True)
class NativeJobCatalogIdentity:
    receiver_id: str
    receiver_identity_sha256: str

    def __post_init__(self):
        if (type(self.receiver_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{16,160}", self.receiver_id) is None
                or type(self.receiver_identity_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.receiver_identity_sha256) is None):
            raise TransferError("file_job_catalog_invalid_identity")


@dataclass(frozen=True)
class NativeJobCatalogLimits:
    max_jobs: int = 32
    max_reserved_bytes: int = 1024 * 1024 * 1024

    def __post_init__(self):
        if (type(self.max_jobs) is not int or not 1 <= self.max_jobs <= 128 or type(self.max_reserved_bytes) is not int
                or not 0 <= self.max_reserved_bytes <= 2 * 1024 * 1024 * 1024):
            raise TransferError("file_job_catalog_invalid_limits")


@dataclass(frozen=True)
class NativeReservedTransferJob:
    owner: str
    accepted: NativeAcceptedTransfer
    reserved_bytes: int
    protected_record_sha256: str

    @property
    def grants_write_authority(self):
        return False

    @property
    def is_saved_receipt(self):
        return False


class ProtectedTransferJobCatalog:
    NAME = "file-job-catalog"
    MAX_RECORD_BYTES = 2 * 1024 * 1024
    MAX_METADATA_BYTES = 128 * (MAX_RECORD_BYTES + 128) + 8192

    def __init__(self, parent, identity, seal, unseal, *, create=False, limits=None):
        if (type(identity) is not NativeJobCatalogIdentity or type(create) is not bool
                or not callable(seal) or not callable(unseal) or limits is not None and type(limits) is not NativeJobCatalogLimits):
            raise TransferError("file_job_catalog_native_context_required")
        self._identity, self._seal, self._unseal = identity, seal, unseal
        self._domain = "magnolie-file-job-catalog-v1/" + identity.receiver_id + "/" + identity.receiver_identity_sha256 + "/"
        self._parent = Path(parent)
        if not self._parent.is_absolute() or self._parent.resolve(strict=True) != self._parent:
            raise TransferError("file_job_catalog_canonical_parent_required")
        self._ancestors = [(path, self._key(os.lstat(path))) for path in (self._parent, *self._parent.parents)]
        self._parent_fd = os.open(self._parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self._root_fd = self._lock_fd = None
        self._gate = threading.RLock()
        self._closed = False
        self._failed = False
        self._known = {}
        try:
            self._private(os.fstat(self._parent_fd), directory=True)
            if create:
                os.mkdir(self.NAME, mode=0o700, dir_fd=self._parent_fd)
            self._root_fd = os.open(self.NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._parent_fd)
            self._root_key = self._key(os.fstat(self._root_fd))
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            self._lock_fd = os.open("catalog.lock", flags, 0o600, dir_fd=self._root_fd)
            self._lock_key = self._key(os.fstat(self._lock_fd))
            with _ROOT_GATES_LOCK:
                self._root_gate = _ROOT_GATES.setdefault(self._root_key, threading.RLock())
            with self._locked():
                if create:
                    self._limits = NativeJobCatalogLimits() if limits is None else limits
                    self._write("owner.enc", {"format": 1, "identity": vars(identity), "limits": vars(self._limits),
                        "lock_key": self._lock_key})
                    os.fsync(self._parent_fd)
                else:
                    payload, _ = self._read("owner.enc")
                    self._parse_owner(payload, limits)
                self._jobs()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _key(value):
        return value.st_dev, value.st_ino

    @staticmethod
    def _private(value, *, directory=False):
        if (not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
                or value.st_uid != os.geteuid() or value.st_mode & 0o077 or not directory and value.st_nlink != 1):
            raise TransferError("file_job_catalog_unsafe_entry")

    def _directories(self):
        if self._closed:
            raise TransferError("file_job_catalog_closed")
        for path, key in self._ancestors:
            value = os.lstat(path)
            if not stat.S_ISDIR(value.st_mode) or self._key(value) != key:
                raise TransferError("file_job_catalog_parent_changed")
        parent = os.fstat(self._parent_fd)
        self._private(parent, directory=True)
        root = os.stat(self.NAME, dir_fd=self._parent_fd, follow_symlinks=False)
        self._private(root, directory=True)
        if (self._key(parent) != self._ancestors[0][1] or self._key(root) != self._root_key
                or self._key(os.fstat(self._root_fd)) != self._root_key):
            raise TransferError("file_job_catalog_root_changed")
        lock = os.stat("catalog.lock", dir_fd=self._root_fd, follow_symlinks=False)
        self._private(lock)
        self._private(os.fstat(self._lock_fd))
        if self._key(lock) != self._lock_key or self._key(os.fstat(self._lock_fd)) != self._lock_key or lock.st_size != 0:
            raise TransferError("file_job_catalog_lock_changed")

    @contextmanager
    def _locked(self):
        with self._gate, self._root_gate:
            self._directories()
            held = getattr(_LOCAL, "held", None)
            if held is None:
                held = _LOCAL.held = set()
            first = self._root_key not in held
            if first:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
                held.add(self._root_key)
            try:
                self._directories()
                yield
                self._directories()
            finally:
                if first:
                    held.remove(self._root_key)
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()

    def _read(self, name):
        self._directories()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._root_fd)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            self._private(before)
            if not 1 <= before.st_size <= self.MAX_RECORD_BYTES + 128:
                raise TransferError("file_job_catalog_record_size")
            blob = source.read(self.MAX_RECORD_BYTES + 129)
            after = os.fstat(source.fileno())
            named = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
            def signature(value):
                return (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_uid,
                    value.st_gid, value.st_nlink, value.st_mtime_ns, value.st_ctime_ns)
            if signature(before) != signature(after) or signature(after) != signature(named) or len(blob) != before.st_size:
                raise TransferError("file_job_catalog_record_changed")
        plain = self._unseal(blob, self._domain + name)
        if type(plain) is not bytes or len(plain) > self.MAX_RECORD_BYTES:
            raise TransferError("file_job_catalog_invalid_protection")
        value = json.loads(plain)
        if (type(value) is not dict or set(value) != {"format", "root_key", "file_key", "payload"}
                or type(value["format"]) is not int or value["format"] != 1 or value["root_key"] != list(self._root_key)
                or value["file_key"] != list(self._key(before)) or self._json(value) != plain):
            raise TransferError("file_job_catalog_record_identity_changed")
        proof = self._key(before), sha256(blob).hexdigest()
        if name in self._known and self._known[name] != proof:
            raise TransferError("file_job_catalog_original_changed")
        self._directories()
        self._known[name] = proof
        return value["payload"], proof[1]

    def _write(self, name, payload):
        self._directories()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._root_fd)
        try:
            plain = self._json({"format": 1, "root_key": self._root_key, "file_key": self._key(os.fstat(fd)), "payload": payload})
            if len(plain) > self.MAX_RECORD_BYTES:
                raise TransferError("file_job_catalog_record_size")
            blob = self._seal(plain, self._domain + name)
            if type(blob) is not bytes or not len(plain) <= len(blob) <= len(plain) + 128:
                raise TransferError("file_job_catalog_invalid_protection")
            view = memoryview(blob)
            while view:
                amount = os.write(fd, view)
                if amount <= 0:
                    raise TransferError("file_job_catalog_stalled_write")
                view = view[amount:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self._root_fd)
        actual, digest = self._read(name)
        if self._json(actual) != self._json(payload):
            raise TransferError("file_job_catalog_readback_failed")
        return digest

    def _parse_owner(self, payload, expected_limits=None):
        if (type(payload) is not dict or set(payload) != {"format", "identity", "limits", "lock_key"}
                or type(payload["format"]) is not int or payload["format"] != 1 or payload["identity"] != vars(self._identity)
                or payload["lock_key"] != list(self._lock_key) or type(payload["limits"]) is not dict
                or set(payload["limits"]) != {"max_jobs", "max_reserved_bytes"}):
            raise TransferError("file_job_catalog_owner_changed")
        limits = NativeJobCatalogLimits(**payload["limits"])
        if expected_limits is not None and expected_limits != limits:
            raise TransferError("file_job_catalog_limits_changed")
        self._limits = limits

    @staticmethod
    def reservation_bytes(accepted):
        if type(accepted) is not NativeAcceptedTransfer:
            raise TransferError("file_job_catalog_native_acceptance_required")
        manifest = accepted.manifest
        # Conservative upper bounds for owned encrypted stage+checkpoints,
        # private index/catalog/journal metadata and all potentially retained
        # publication temporaries. A failed member must not make the following
        # member's allocation exceed this reservation.
        # Actual target photos are not a disposable private-cache allocation.
        return (manifest.total_bytes + sum(file.chunks for file in manifest.files) * 128
            + EncryptedTransferStage.MAX_CHECKPOINTS * (EncryptedTransferStage.MAX_CHECKPOINT_BYTES + 128)
            + 8 * 1024 * 1024 + 3 * len(manifest.files) * (4096 + 128)
            + manifest.total_bytes)

    def _jobs(self):
        payload, _ = self._read("owner.enc")
        self._parse_owner(payload, self._limits)
        names = set()
        total = 0
        with os.scandir(self._root_fd) as entries:
            for entry in entries:
                if (entry.name not in {"owner.enc", "catalog.lock"}
                        and re.fullmatch(r"job-[0-9a-f]{32}\.enc", entry.name) is None):
                    raise TransferError("file_job_catalog_unknown_entry_preserved")
                value = entry.stat(follow_symlinks=False)
                self._private(value)
                total += value.st_size
                if len(names) >= self._limits.max_jobs + 2 or total > self.MAX_METADATA_BYTES:
                    raise TransferError("file_job_catalog_metadata_limit")
                names.add(entry.name)
        if not {"owner.enc", "catalog.lock"} <= names or not set(self._known) <= names:
            raise TransferError("file_job_catalog_original_missing")
        jobs = []
        for name in sorted(names - {"owner.enc", "catalog.lock"}):
            payload, digest = self._read(name)
            owner = name[4:-4]
            if (type(payload) is not dict or set(payload) != {"format", "owner", "accepted", "reserved_bytes"}
                    or type(payload["format"]) is not int or payload["format"] != 1 or payload["owner"] != owner):
                raise TransferError("file_job_catalog_invalid_job")
            accepted = NativeAcceptedTransfer.parse(payload["accepted"])
            if (accepted.binding.receiver_id != self._identity.receiver_id
                    or accepted.binding.receiver_identity_sha256 != self._identity.receiver_identity_sha256
                    or type(payload["reserved_bytes"]) is not int or payload["reserved_bytes"] != self.reservation_bytes(accepted)):
                raise TransferError("file_job_catalog_invalid_reservation")
            jobs.append(NativeReservedTransferJob(owner, accepted, payload["reserved_bytes"], digest))
        if sum(job.reserved_bytes for job in jobs) > self._limits.max_reserved_bytes:
            raise TransferError("file_job_catalog_quota_exceeded")
        return tuple(jobs)

    def jobs(self):
        with self._locked():
            return self._jobs()  # Discovery is metadata-only, not resume consent.

    @contextmanager
    def inspect_jobs(self):
        """Bounded authenticated metadata snapshot; never create or reserve.
        The native parent is for historical index reads, not target authority.
        """
        with self._locked():
            inspecting=getattr(_LOCAL,'inspecting',None)
            if inspecting is None:inspecting=_LOCAL.inspecting=set()
            if self._root_key in inspecting:raise TransferError('file_job_catalog_history_busy')
            inspecting.add(self._root_key)
            try:
                jobs=self._jobs()
                yield self._parent,jobs
                if self._jobs()!=jobs:raise TransferError('file_job_catalog_history_changed')
            finally:inspecting.remove(self._root_key)

    def require_reserved(self, job):
        """Authenticate exact native operation metadata and private parent.
        This does not start work, grant permission or release any reservation.
        """
        with self._locked():
            if type(job) is not NativeReservedTransferJob or not any(value == job for value in self._jobs()):
                raise TransferError("file_job_catalog_unknown_native_reservation")
            return self._parent

    def reserve(self, accepted, current_binding, *, expected_jobs=None):
        with self._locked():
            reserving = getattr(_LOCAL, "reserving", None)
            if reserving is None:
                reserving = _LOCAL.reserving = set()
            if self._root_key in reserving:
                raise TransferError("file_job_catalog_nested_reservation")
            reserving.add(self._root_key)
            try:
                return self._reserve(accepted, current_binding, expected_jobs=expected_jobs)
            finally:
                reserving.remove(self._root_key)

    def _reserve(self, accepted, current_binding, *, expected_jobs=None):
        with self._locked():
            if self._root_key in getattr(_LOCAL,'inspecting',set()):raise TransferError('file_job_catalog_history_readonly')
            if self._failed:
                raise TransferError("file_job_catalog_repair_pending")
            if (type(accepted) is not NativeAcceptedTransfer or accepted.binding.receiver_id != self._identity.receiver_id
                    or accepted.binding.receiver_identity_sha256 != self._identity.receiver_identity_sha256):
                raise TransferError("file_job_catalog_wrong_receiver")
            accepted.verify(current_binding)
            jobs = self._jobs()
            if expected_jobs is not None:
                if type(expected_jobs) is not tuple or any(type(job) is not NativeReservedTransferJob for job in expected_jobs):
                    raise TransferError('file_job_catalog_native_history_required')
                if jobs!=expected_jobs:raise TransferError('file_job_catalog_history_changed')
            if any(job.accepted.manifest.transfer_id == accepted.manifest.transfer_id
                    and job.accepted.binding.sender_id == accepted.binding.sender_id for job in jobs):
                raise TransferError("file_job_catalog_existing_operation")
            amount = self.reservation_bytes(accepted)
            if len(jobs) >= self._limits.max_jobs or amount + sum(job.reserved_bytes for job in jobs) > self._limits.max_reserved_bytes:
                raise TransferError("file_job_catalog_quota_exceeded")
            owner = secrets.token_hex(16)  # Native reservation, never a peer transfer ID.
            accepted.verify(current_binding)
            self._failed = True
            digest = self._write("job-" + owner + ".enc", {"format": 1, "owner": owner,
                "accepted": accepted.wire(), "reserved_bytes": amount})
            accepted.verify(current_binding)
            job = next(value for value in self._jobs() if value.owner == owner)
            if job.protected_record_sha256 != digest:
                raise TransferError("file_job_catalog_readback_failed")
            self._failed = False
            return job

    def close(self):
        with self._gate:
            if not self._closed:
                self._closed = True
                for fd in (self._lock_fd, self._root_fd, self._parent_fd):
                    if fd is not None:
                        os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
