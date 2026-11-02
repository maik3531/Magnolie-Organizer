"""Private immutable publication evidence, separate from transfer checkpoints.

No key generation, personal store, destination writes, transport ACKs or consent.
Restart inspection is deliberately read-only: an absent later record does not
prove that a link never happened. Native recovery/readback must resolve that
uncertainty before a coordinator may resume any operation.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import threading

from magnolie_file_transfer import FileManifest, ManifestFile, NativeTransferBinding, TransferError


@dataclass(frozen=True)
class PublicationWitness:
    file_id: str
    source_device: int
    source_inode: int
    # Root, then every target parent. Names come only from the immutable mapping.
    parent_keys: tuple

    def __post_init__(self):
        if (type(self.file_id) is not str or re.fullmatch(r"[0-9a-f]{32}", self.file_id) is None
                or type(self.parent_keys) is not tuple or not 1 <= len(self.parent_keys) <= 16):
            raise TransferError("publication_journal_invalid_witness")
        for key in ((self.source_device, self.source_inode), *self.parent_keys):
            if (type(key) is not tuple or len(key) != 2
                    or any(type(value) is not int or not 0 <= value < 2**64 for value in key)
                    or key[1] == 0):
                raise TransferError("publication_journal_invalid_witness")


@dataclass(frozen=True)
class PublicationJournalEvidence:
    phase: str
    witness: PublicationWitness
    protected_record_sha256: str

    @property
    def is_saved_receipt(self):
        return False

    @property
    def grants_write_authority(self):
        return False


class ProtectedPublicationJournal:
    PREFIX = "publication-journal-"
    PHASES = ("prepared", "linked", "verified")
    MAX_RECORD_BYTES = 1024 * 1024
    MAX_PROTECTION_OVERHEAD = 128

    def __init__(self, parent, manifest, binding, targets, seal, unseal, *, owner, create=False):
        if (type(manifest) is not FileManifest or type(binding) is not NativeTransferBinding
                or (manifest.sender_id, manifest.receiver_id) != (binding.sender_id, binding.receiver_id)
                or type(owner) is not str or re.fullmatch(r"[0-9a-f]{32}", owner) is None
                or type(create) is not bool or not callable(seal) or not callable(unseal)):
            raise TransferError("publication_journal_native_context_required")
        targets = dict(targets)
        if set(targets) != {file.id for file in manifest.files}:
            raise TransferError("publication_journal_mapping_incomplete")
        FileManifest(manifest.transfer_id, manifest.source_id, manifest.sender_id, manifest.receiver_id,
            tuple(ManifestFile(file.id, targets[file.id], file.size, file.sha256) for file in manifest.files), manifest.total_bytes)
        self._context = {"format": 1, "owner": owner, "manifest_sha256": manifest.fingerprint,
            "binding": vars(binding), "targets": targets}
        self._domain = "magnolie-publication-journal-v1/" + owner + "/" + manifest.fingerprint + "/"
        self._seal, self._unseal = seal, unseal
        self._gate = threading.RLock()
        self._parent = Path(parent)
        if not self._parent.is_absolute() or self._parent.resolve(strict=True) != self._parent:
            raise TransferError("publication_journal_canonical_parent_required")
        self._ancestors = [(path, self._key(os.lstat(path))) for path in (self._parent, *self._parent.parents)]
        self._parent_fd = os.open(self._parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self._root_fd = None
        self._name = self.PREFIX + owner
        self._closed = False
        self._writable = create
        self._known = {}
        self._failed = False
        try:
            self._private(os.fstat(self._parent_fd), directory=True)
            if create:
                os.mkdir(self._name, mode=0o700, dir_fd=self._parent_fd)
            self._root_fd = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=self._parent_fd)
            self._root_key = self._key(os.fstat(self._root_fd))
            self._directories()
            if create:
                self._write("owner.enc", {"context": self._context})
                os.fsync(self._parent_fd)
            else:
                payload, _ = self._read("owner.enc")
                if payload != {"context": self._context}:
                    raise TransferError("publication_journal_context_mismatch")
            self._entries()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _key(value):
        return value.st_dev, value.st_ino

    @staticmethod
    def _private(value, *, directory=False):
        if (not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
                or value.st_uid != os.geteuid() or value.st_mode & 0o077
                or not directory and value.st_nlink != 1):
            raise TransferError("publication_journal_unsafe_entry")

    def _directories(self):
        if self._closed:
            raise TransferError("publication_journal_closed")
        for path, key in self._ancestors:
            value = os.lstat(path)
            if not stat.S_ISDIR(value.st_mode) or self._key(value) != key:
                raise TransferError("publication_journal_parent_changed")
        parent = os.fstat(self._parent_fd)
        self._private(parent, directory=True)
        if self._key(parent) != self._ancestors[0][1]:
            raise TransferError("publication_journal_parent_changed")
        root = os.stat(self._name, dir_fd=self._parent_fd, follow_symlinks=False)
        self._private(root, directory=True)
        if self._key(root) != self._root_key or self._key(os.fstat(self._root_fd)) != self._root_key:
            raise TransferError("publication_journal_root_changed")

    def _entries(self):
        self._directories()
        allowed = {"owner.enc"} | {phase + "-" + file_id + ".enc"
            for phase in self.PHASES for file_id in self._context["targets"]}
        names = set()
        with os.scandir(self._root_fd) as entries:
            for entry in entries:
                if entry.name not in allowed or not entry.is_file(follow_symlinks=False):
                    raise TransferError("publication_journal_unknown_entry_preserved")
                names.add(entry.name)
        if "owner.enc" not in names or not set(self._known) <= names:
            raise TransferError("publication_journal_original_missing")
        payload, _ = self._read("owner.enc")
        if payload != {"context": self._context}:
            raise TransferError("publication_journal_context_mismatch")
        return names

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")

    def _read(self, name):
        self._directories()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._root_fd)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            self._private(before)
            if not 1 <= before.st_size <= self.MAX_RECORD_BYTES + self.MAX_PROTECTION_OVERHEAD:
                raise TransferError("publication_journal_record_size")
            blob = source.read(self.MAX_RECORD_BYTES + self.MAX_PROTECTION_OVERHEAD + 1)
            after = os.fstat(source.fileno())
            named = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
            def signature(value):
                return (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_uid,
                    value.st_gid, value.st_nlink, value.st_mtime_ns, value.st_ctime_ns)
            if (signature(before) != signature(after) or signature(named) != signature(after)
                    or len(blob) != before.st_size):
                raise TransferError("publication_journal_record_changed")
        plain = self._unseal(blob, self._domain + name)
        if type(plain) is not bytes or len(plain) > self.MAX_RECORD_BYTES:
            raise TransferError("publication_journal_invalid_protection")
        value = json.loads(plain)
        if (type(value) is not dict or set(value) != {"format", "root_key", "file_key", "payload"}
                or type(value["format"]) is not int or value["format"] != 1
                or value["root_key"] != list(self._root_key) or value["file_key"] != list(self._key(before))
                or self._json(value) != plain):
            raise TransferError("publication_journal_record_identity_mismatch")
        proof = self._key(before), sha256(blob).hexdigest()
        if name in self._known and self._known[name] != proof:
            raise TransferError("publication_journal_original_changed")
        self._directories()
        self._known[name] = proof
        return value["payload"], proof[1]

    def _write(self, name, payload):
        self._directories()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=self._root_fd)
        try:
            os.fchmod(fd, 0o600)
            plain = self._json({"format": 1, "root_key": self._root_key, "file_key": self._key(os.fstat(fd)), "payload": payload})
            if len(plain) > self.MAX_RECORD_BYTES:
                raise TransferError("publication_journal_record_size")
            blob = self._seal(plain, self._domain + name)
            if type(blob) is not bytes or not len(plain) <= len(blob) <= len(plain) + self.MAX_PROTECTION_OVERHEAD:
                raise TransferError("publication_journal_invalid_protection")
            view = memoryview(blob)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise TransferError("publication_journal_stalled_write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self._root_fd)
        actual, digest = self._read(name)
        if self._json(actual) != self._json(payload):
            raise TransferError("publication_journal_readback_failed")
        return digest

    def inspect(self, file_id):
        with self._gate:
            if file_id not in self._context["targets"]:
                raise TransferError("publication_journal_unknown_member")
            names = self._entries()
            previous = ""
            witness = None
            evidence = None
            absent = False
            for phase in self.PHASES:
                name = phase + "-" + file_id + ".enc"
                if name not in names:
                    absent = True
                    continue
                if absent:
                    raise TransferError("publication_journal_phase_gap")
                payload, digest = self._read(name)
                if (type(payload) is not dict or set(payload) != {"phase", "witness", "previous"}
                        or payload["phase"] != phase or payload["previous"] != previous):
                    raise TransferError("publication_journal_invalid_transition")
                raw = payload["witness"]
                if type(raw) is not dict or set(raw) != {"file_id", "source_device", "source_inode", "parent_keys"}:
                    raise TransferError("publication_journal_invalid_witness")
                if type(raw["parent_keys"]) is not list or any(type(key) is not list for key in raw["parent_keys"]):
                    raise TransferError("publication_journal_invalid_witness")
                current = PublicationWitness(raw["file_id"], raw["source_device"], raw["source_inode"], tuple(tuple(key) for key in raw["parent_keys"]))
                if (current.file_id != file_id or len(current.parent_keys) != len(self._context["targets"][file_id].split("/"))
                        or witness is not None and witness != current):
                    raise TransferError("publication_journal_witness_changed")
                witness, previous = current, digest
                evidence = PublicationJournalEvidence(phase, current, digest)
            return evidence

    def append(self, phase, witness):
        with self._gate:
            if not self._writable or self._failed:
                raise TransferError("publication_journal_recovery_read_only")
            if phase not in self.PHASES or type(witness) is not PublicationWitness:
                raise TransferError("publication_journal_invalid_transition")
            previous = self.inspect(witness.file_id)
            if previous is not None and previous.phase == phase and previous.witness == witness:
                return previous
            index = self.PHASES.index(phase)
            if ((index == 0) != (previous is None) or previous is not None and
                    (previous.phase != self.PHASES[index - 1] or previous.witness != witness)
                    or len(witness.parent_keys) != len(self._context["targets"][witness.file_id].split("/"))):
                raise TransferError("publication_journal_invalid_transition")
            try:
                self._write(phase + "-" + witness.file_id + ".enc", {"phase": phase, "witness": vars(witness),
                    "previous": previous.protected_record_sha256 if previous is not None else ""})
                return self.inspect(witness.file_id)
            except BaseException:
                self._failed = True  # Never silently retry/adopt an uncertain write.
                raise

    def require_new_operation(self, manifest, binding, targets, owner):
        """Native attachment preflight, never resume/write permission."""
        with self._gate:
            self._directories()
            if (not self._writable or self._failed or self._context != {"format": 1, "owner": owner,
                    "manifest_sha256": manifest.fingerprint, "binding": vars(binding), "targets": dict(targets)}):
                raise TransferError("publication_journal_operation_mismatch")
            if any(self.inspect(file_id) is not None for file_id in self._context["targets"]):
                raise TransferError("publication_journal_operation_already_started")

    def close(self):
        with self._gate:
            if not self._closed:
                self._closed = True
                if self._root_fd is not None:
                    os.close(self._root_fd)
                os.close(self._parent_fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
