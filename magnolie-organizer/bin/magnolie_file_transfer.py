"""Private immutable file-manifest and readback-bound resume state (#329).

No listener, capability advertisement, personal store, destination publication
or implicit consent. All I/O callbacks belong to a native accepted operation,
never to a network request. Persisted chunk claims are re-read, not trusted.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import threading
import unicodedata
from functools import wraps


class TransferError(ValueError):
    pass


_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_DEVICE = re.compile(r"[A-Za-z0-9_-]{16,160}\Z")
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    prefix + suffix for prefix in ("COM", "LPT") for suffix in "123456789¹²³"}
CHUNK_BYTES = 65536
MAX_FILES = 128
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 400 * 1024 * 1024


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise TransferError("unexpected_transfer_fields")


def _text(value, pattern):
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise TransferError("invalid_transfer_identity")
    return value


def _integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise TransferError("invalid_transfer_integer")
    return value


def _portable_path(path):
    if (type(path) is not str or not path or unicodedata.normalize("NFC", path) != path
            or any(unicodedata.category(c).startswith("C") for c in path)
            or len(path) > 1024 or len(path.encode("utf-8", errors="strict")) > 4096):
        raise TransferError("invalid_transfer_path")
    parts = path.split("/")
    if len(parts) > 16:
        raise TransferError("transfer_path_too_deep")
    for part in parts:
        if (not part or part in (".", "..") or len(part.encode("utf-16-le")) // 2 > 255
                or part.endswith((".", " ")) or any(c in '<>:"\\|?*' for c in part)
                or any(unicodedata.category(c).startswith("C") for c in part)
                or part.split(".")[0].rstrip(" ").upper() in _RESERVED):
            raise TransferError("unsafe_transfer_path")
    return path


@dataclass(frozen=True)
class ManifestFile:
    id: str
    path: str
    size: int
    sha256: str

    @property
    def chunks(self):
        return (self.size + CHUNK_BYTES - 1) // CHUNK_BYTES


@dataclass(frozen=True)
class FileManifest:
    transfer_id: str
    source_id: str
    sender_id: str
    receiver_id: str
    files: tuple
    total_bytes: int

    def __post_init__(self):
        _text(self.transfer_id, _ID)
        _text(self.source_id, _ID)
        _text(self.sender_id, _DEVICE)
        _text(self.receiver_id, _DEVICE)
        if self.sender_id == self.receiver_id or type(self.files) is not tuple or not 1 <= len(self.files) <= MAX_FILES:
            raise TransferError("invalid_manifest_members")
        ids, paths = set(), set()
        for member in self.files:
            if type(member) is not ManifestFile:
                raise TransferError("invalid_manifest_member")
            _text(member.id, _ID)
            _text(member.sha256, _HEX)
            _integer(member.size, MAX_FILE_BYTES)
            path = _portable_path(member.path).casefold()
            if member.id in ids or path in paths:
                raise TransferError("duplicate_transfer_member")
            ids.add(member.id)
            paths.add(path)
        # A path cannot simultaneously be a file and a parent directory,
        # including case-insensitive aliases on the receiving filesystem.
        for path in paths:
            parts = path.split("/")
            if any("/".join(parts[:index]) in paths for index in range(1, len(parts))):
                raise TransferError("transfer_file_directory_collision")
        if _integer(self.total_bytes, MAX_TOTAL_BYTES) != sum(member.size for member in self.files):
            raise TransferError("manifest_total_mismatch")

    @classmethod
    def parse(cls, value):
        _exact(value, ("format", "transfer_id", "source_id", "sender_id", "receiver_id", "chunk_bytes", "total_bytes", "files"))
        if type(value["format"]) is not int or value["format"] != 1 or type(value["chunk_bytes"]) is not int or value["chunk_bytes"] != CHUNK_BYTES:
            raise TransferError("unsupported_transfer_format")
        if type(value["files"]) is not list or not 1 <= len(value["files"]) <= MAX_FILES:
            raise TransferError("invalid_manifest_members")
        files = []
        for member in value["files"]:
            _exact(member, ("id", "path", "size", "sha256"))
            files.append(ManifestFile(**member))
        return cls(value["transfer_id"], value["source_id"], value["sender_id"], value["receiver_id"], tuple(files), value["total_bytes"])

    def wire(self):
        return {"format": 1, "transfer_id": self.transfer_id, "source_id": self.source_id,
                "sender_id": self.sender_id, "receiver_id": self.receiver_id, "chunk_bytes": CHUNK_BYTES,
                "total_bytes": self.total_bytes, "files": [dict(id=f.id, path=f.path, size=f.size, sha256=f.sha256) for f in self.files]}

    @property
    def fingerprint(self):
        # Explicit binary framing avoids JSON encoder/Unicode escape differences.
        digest = sha256(b"magnolie-file-manifest-v1\0")
        def text(value):
            raw = value.encode("utf-8")
            digest.update(struct.pack(">I", len(raw)))
            digest.update(raw)
        for value in (self.transfer_id, self.source_id, self.sender_id, self.receiver_id):
            text(value)
        digest.update(struct.pack(">IIQ", CHUNK_BYTES, len(self.files), self.total_bytes))
        for member in self.files:
            text(member.id)
            text(member.path)
            digest.update(struct.pack(">Q", member.size))
            digest.update(bytes.fromhex(member.sha256))
        return digest.hexdigest()


@dataclass(frozen=True)
class NativeTransferBinding:
    sender_id: str
    receiver_id: str
    sender_identity_sha256: str
    receiver_identity_sha256: str
    permission_epoch: str
    destination_token: str

    def __post_init__(self):
        _text(self.sender_id, _DEVICE)
        _text(self.receiver_id, _DEVICE)
        for value in (self.sender_identity_sha256, self.receiver_identity_sha256, self.permission_epoch, self.destination_token):
            _text(value, _HEX)


def _serialized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._gate:
            return method(self, *args, **kwargs)
    return guarded


class ResumeLedger:
    """Native chunk/readback ledger, not a wire ACK or a publication permission.

    Each write must target owned staging at an explicit file/offset, durably
    finish, and be read back before a chunk proof is retained. Resume rechecks
    every persisted claim against actual bytes and a fresh native binding.
    """

    def __init__(self, manifest, binding, current_binding):
        if (type(manifest) is not FileManifest or type(binding) is not NativeTransferBinding
                or (manifest.sender_id, manifest.receiver_id) != (binding.sender_id, binding.receiver_id)):
            raise TransferError("manifest_native_peer_mismatch")
        self._gate = threading.RLock()
        self._manifest, self._binding = manifest, binding
        self._current_binding = current_binding
        self._proofs = {}
        self._require()

    @property
    def manifest(self):
        return self._manifest

    @property
    def binding(self):
        return self._binding

    def _require(self):
        if self._current_binding() != self.binding:
            raise TransferError("transfer_permission_source_or_destination_changed")

    def _member(self, file_id, index):
        self._require()
        member = next((f for f in self.manifest.files if f.id == file_id), None)
        if member is None or type(index) is not int or not 0 <= index < member.chunks:
            raise TransferError("invalid_transfer_chunk")
        return member, index * CHUNK_BYTES, min(CHUNK_BYTES, member.size - index * CHUNK_BYTES)

    @property
    @_serialized
    def verified_bytes(self):
        self._require()
        return sum(self._member(file_id, index)[2] for file_id, index in self._proofs)

    @_serialized
    def record(self, file_id, index, data, write_exact, read_chunk):
        member, offset, size = self._member(file_id, index)
        if type(data) is not bytes or len(data) != size:
            raise TransferError("transfer_chunk_size_mismatch")
        witness = sha256(data).hexdigest()
        key = (file_id, index)
        if key in self._proofs:
            if self._proofs[key] != witness:
                raise TransferError("changed_duplicate_transfer_chunk")
        else:
            write_exact(member.id, offset, data)
        self._require()
        actual = read_chunk(member.id, offset, size)
        if type(actual) is not bytes or len(actual) != size or sha256(actual).hexdigest() != witness:
            raise TransferError("transfer_chunk_readback_mismatch")
        self._require()
        self._proofs[key] = witness

    @_serialized
    def checkpoint(self):
        self._require()
        return {"format": 1, "manifest_sha256": self.manifest.fingerprint,
                "binding": dict(vars(self.binding)),
                "chunks": [{"file_id": file_id, "index": index, "sha256": witness}
                           for (file_id, index), witness in sorted(self._proofs.items())]}

    @classmethod
    def restore(cls, manifest, binding, current_binding, checkpoint, read_chunk):
        _exact(checkpoint, ("format", "manifest_sha256", "binding", "chunks"))
        if (type(checkpoint["format"]) is not int or checkpoint["format"] != 1
                or checkpoint["manifest_sha256"] != manifest.fingerprint
                or checkpoint["binding"] != vars(binding) or type(checkpoint["chunks"]) is not list
                or len(checkpoint["chunks"]) > sum(f.chunks for f in manifest.files)):
            raise TransferError("resume_manifest_or_native_binding_changed")
        result = cls(manifest, binding, current_binding)
        for proof in checkpoint["chunks"]:
            _exact(proof, ("file_id", "index", "sha256"))
            witness = _text(proof["sha256"], _HEX)
            member, offset, size = result._member(proof["file_id"], proof["index"])
            key = member.id, proof["index"]
            if key in result._proofs:
                raise TransferError("duplicate_resume_chunk_claim")
            actual = read_chunk(member.id, offset, size)
            if type(actual) is not bytes or len(actual) != size or sha256(actual).hexdigest() != witness:
                raise TransferError("persisted_resume_chunk_changed")
            result._require()
            result._proofs[key] = witness
        return result

    @_serialized
    def missing(self, file_id):
        self._require()
        member = next((f for f in self.manifest.files if f.id == file_id), None)
        if member is None:
            raise TransferError("unknown_transfer_file")
        return tuple(index for index in range(member.chunks) if (file_id, index) not in self._proofs)

    @_serialized
    def verified_file(self, file_id, read_chunk):
        if self.missing(file_id):
            raise TransferError("incomplete_transfer_file")
        member = next(f for f in self.manifest.files if f.id == file_id)
        digest = sha256()
        for index in range(member.chunks):
            _, offset, size = self._member(file_id, index)
            actual = read_chunk(member.id, offset, size)
            if type(actual) is not bytes or len(actual) != size or sha256(actual).hexdigest() != self._proofs[(file_id, index)]:
                raise TransferError("verified_transfer_chunk_changed")
            digest.update(actual)
            self._require()
        if read_chunk(member.id, member.size, 1) != b"" or digest.hexdigest() != member.sha256:
            raise TransferError("transfer_final_integrity_mismatch")
        self._require()
        return member


@dataclass(frozen=True)
class TransferStageHandle:
    owner: str
    checkpoint: str

    def __post_init__(self):
        _text(self.owner, _ID)
        _text(self.checkpoint, _ID)


@dataclass(frozen=True)
class NativeCheckpointCommit:
    handle: TransferStageHandle
    retired_versions: int
    cleanup_pending: bool
    cleanup_error: str = ""


class EncryptedTransferStage:
    """Linux native, directory-fd-bound encrypted staging and immutable checkpoints.

    The native coordinator supplies existing local protection callbacks, an
    accepted manifest/binding and its own private job handle. No key creation,
    directory scanning, peer store construction or destination publication.
    Closing releases descriptors only; cleanup is a separate explicit action.
    """

    MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
    MAX_PROTECTION_OVERHEAD = 128
    MAX_CHECKPOINTS = 8

    def __init__(self, parent, manifest, binding, current_binding, seal, unseal, *, owner=None):
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise TransferError("guarded_native_staging_platform_required")
        # The same constructor validation as the ledger, without adopting any
        # persisted authority or constructing a personal identity/key store.
        ResumeLedger(manifest, binding, current_binding)
        self._manifest, self._binding = manifest, binding
        self._current_binding = current_binding
        self._seal, self._unseal = seal, unseal
        self._owner = _text(owner, _ID) if owner is not None else secrets.token_hex(16)
        self._root_name = "file-transfer-" + self.owner
        self._parent = Path(parent)
        if not self._parent.is_absolute() or self._parent.resolve(strict=True) != self._parent:
            raise TransferError("canonical_existing_staging_parent_required")
        for path in (self._parent, *self._parent.parents):
            if stat.S_ISLNK(os.lstat(path).st_mode):
                raise TransferError("linked_staging_parent")
        self._parent_fd = os.open(self._parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self._root_fd = None
        self._closed = False
        self._owned = {}
        self._gate = threading.RLock()
        try:
            metadata = os.fstat(self._parent_fd)
            if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                raise TransferError("native_owned_staging_parent_required")
        except BaseException:
            os.close(self._parent_fd)
            self._closed = True
            raise
        binding_hash = sha256(json.dumps(vars(binding), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self._domain = "device-file-stage-v1/" + self.owner + "/" + manifest.fingerprint + "/" + binding_hash + "/"

    @property
    def manifest(self):
        return self._manifest

    @property
    def binding(self):
        return self._binding

    @property
    def owner(self):
        return self._owner

    def _fresh(self):
        if self._closed or self._current_binding() != self.binding:
            raise TransferError("staging_native_binding_revoked")

    @staticmethod
    def _same(first, second):
        return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)

    def _directories(self):
        if self._closed or self._root_fd is None:
            raise TransferError("staging_not_open")
        if (not self._same(os.fstat(self._parent_fd), os.lstat(self._parent)) or
                not self._same(os.fstat(self._root_fd), os.stat(self._root_name, dir_fd=self._parent_fd, follow_symlinks=False))):
            raise TransferError("staging_directory_identity_changed")
        root = os.fstat(self._root_fd)
        if not stat.S_ISDIR(root.st_mode) or root.st_uid != os.geteuid() or root.st_mode & 0o077:
            raise TransferError("staging_directory_privacy_changed")
        owner_proof = self._owned.get("owner.enc")
        if owner_proof is not None:
            blob, metadata = self._raw_read_cipher("owner.enc", 4096 + self.MAX_PROTECTION_OVERHEAD)
            if (metadata.st_dev, metadata.st_ino, sha256(blob).hexdigest()) != owner_proof:
                raise TransferError("staging_owner_witness_changed")

    def _owner_bytes(self):
        return json.dumps({"format": 1, "owner": self.owner, "manifest_sha256": self.manifest.fingerprint,
                           "binding": vars(self.binding)}, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _read_cipher(self, name, maximum):
        self._directories()
        return self._raw_read_cipher(name, maximum)

    def _raw_read_cipher(self, name, maximum):
        # Nonblocking open also rejects a substituted FIFO/device without
        # hanging before fstat can establish the regular-file boundary.
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=self._root_fd)
        with os.fdopen(fd, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != os.geteuid()
                    or metadata.st_mode & 0o077 or metadata.st_size > maximum):
                raise TransferError("unsafe_or_oversized_staging_entry")
            blob = source.read(maximum + 1)
            if len(blob) > maximum:
                raise TransferError("staging_entry_grew")
        return blob, metadata

    def _adopt(self, name, blob, metadata):
        proof = metadata.st_dev, metadata.st_ino, sha256(blob).hexdigest()
        if name in self._owned and self._owned[name] != proof:
            raise TransferError("original_staging_witness_changed")
        self._owned[name] = proof

    def _read(self, name, maximum):
        self._fresh()
        blob, metadata = self._read_cipher(name, maximum + self.MAX_PROTECTION_OVERHEAD)
        plain = self._unseal(blob, self._domain + name)
        if type(plain) is not bytes or len(plain) > maximum:
            raise TransferError("invalid_protected_staging_entry")
        self._fresh()
        self._adopt(name, blob, metadata)
        return plain

    def _write_new(self, name, plain):
        self._fresh()
        self._directories()
        blob = self._seal(plain, self._domain + name)
        if type(blob) is not bytes or not len(plain) <= len(blob) <= len(plain) + self.MAX_PROTECTION_OVERHEAD:
            raise TransferError("invalid_native_staging_protection")
        self._fresh()
        try:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=self._root_fd)
        except FileExistsError:
            if self._read(name, len(plain)) != plain:
                raise TransferError("existing_staging_entry_changed")
            return
        with os.fdopen(fd, "w+b") as target:
            try:
                target.write(blob)
                target.flush()
                os.fsync(target.fileno())
                self._adopt(name, blob, os.fstat(target.fileno()))
                os.fsync(self._root_fd)
                self._fresh()
            except BaseException:
                # Capture only the exact inode/bytes we created. A later changed
                # inode or content will not be deleted by explicit cleanup.
                try:
                    target.flush()
                    target.seek(0)
                    actual = target.read(len(blob) + 1)
                    self._adopt(name, actual, os.fstat(target.fileno()))
                except OSError:
                    pass
                raise

    @_serialized
    def create(self):
        self._fresh()
        if self._root_fd is not None:
            raise TransferError("staging_already_open")
        if not self._same(os.fstat(self._parent_fd), os.lstat(self._parent)):
            raise TransferError("staging_parent_changed")
        os.mkdir(self._root_name, mode=0o700, dir_fd=self._parent_fd)
        self._root_fd = os.open(self._root_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._parent_fd)
        self._write_new("owner.enc", self._owner_bytes())
        os.fsync(self._parent_fd)
        for file in self.manifest.files:
            if file.size == 0:
                self._write_new("empty-" + file.id + ".enc", b"empty-file-v1")

    def _chunk(self, file_id, offset, size):
        file = next((entry for entry in self.manifest.files if entry.id == file_id), None)
        if (file is None or type(offset) is not int or type(size) is not int or offset < 0
                or offset % CHUNK_BYTES or offset >= file.size or size != min(CHUNK_BYTES, file.size - offset)):
            raise TransferError("invalid_native_staging_chunk_range")
        return file_id + "-" + str(offset // CHUNK_BYTES) + ".enc"

    @_serialized
    def write_chunk(self, file_id, offset, data):
        if type(data) is not bytes:
            raise TransferError("native_staging_bytes_required")
        name = self._chunk(file_id, offset, len(data))
        # A version byte also keeps empty-plaintext protection edge cases out
        # of the existing phone-storage AEAD interface.
        self._write_new(name, b"\x01" + data)

    @_serialized
    def read_chunk(self, file_id, offset, size):
        self._fresh()
        file = next((entry for entry in self.manifest.files if entry.id == file_id), None)
        if file is None:
            raise TransferError("unknown_native_staging_member")
        if type(offset) is int and type(size) is int and offset == file.size and size == 1:
            if file.size == 0:
                if self._read("empty-" + file.id + ".enc", 32) != b"empty-file-v1":
                    raise TransferError("missing_owned_empty_file")
            else:
                last = ((file.size - 1) // CHUNK_BYTES) * CHUNK_BYTES
                self.read_chunk(file_id, last, file.size - last)
            return b""
        name = self._chunk(file_id, offset, size)
        plain = self._read(name, size + 1)
        if len(plain) != size + 1 or plain[:1] != b"\x01":
            raise TransferError("protected_staging_chunk_size_changed")
        return plain[1:]

    def save_checkpoint(self, ledger):
        if ledger.manifest != self.manifest or ledger.binding != self.binding:
            raise TransferError("checkpoint_native_owner_mismatch")
        # Never take the ledger lock while holding the staging lock: chunk IO
        # has the opposite (ledger -> stage) order. A subset snapshot is valid;
        # resumed claims are always re-read before reuse.
        plain = json.dumps(ledger.checkpoint(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(plain) > self.MAX_CHECKPOINT_BYTES:
            raise TransferError("checkpoint_too_large")
        with self._gate:
            self._fresh()
            names = self._entry_names()
            if sum(name.startswith("checkpoint-") for name in names) >= self.MAX_CHECKPOINTS:
                raise TransferError("native_checkpoint_version_limit_reached")
            checkpoint = secrets.token_hex(16)
            self._write_new("checkpoint-" + checkpoint + ".enc", plain)
            return TransferStageHandle(self.owner, checkpoint)

    @_serialized
    def open_checkpoint(self, handle):
        self._fresh()
        if type(handle) is not TransferStageHandle or handle.owner != self.owner or self._root_fd is not None:
            raise TransferError("invalid_native_checkpoint_handle")
        self._root_fd = os.open(self._root_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._parent_fd)
        if self._read("owner.enc", 4096) != self._owner_bytes():
            raise TransferError("protected_staging_owner_changed")
        raw = self._read("checkpoint-" + handle.checkpoint + ".enc", self.MAX_CHECKPOINT_BYTES)
        def strict_pairs(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise TransferError("duplicate_checkpoint_key")
                value[key] = item
            return value
        checkpoint = json.loads(raw, object_pairs_hook=strict_pairs,
                                parse_constant=lambda _: (_ for _ in ()).throw(TransferError("nonfinite_checkpoint_value")))
        return ResumeLedger.restore(self.manifest, self.binding, self._current_binding, checkpoint, self.read_chunk)

    def commit_checkpoint(self, ledger, publish_head, read_head, head_gate):
        """Publish through a native durable job index, then retire old versions.

        Callbacks are existing native storage/serialization authority, never
        received IPC objects. publish_head must durably finish; read_head must
        read back that scoped protected job, not echo its argument. head_gate
        serializes retirement with all native changes to that job's head/scope.
        A head commit is NOT a saved destination or a Notes/Organizer SaveACK.
        """
        handle = self.save_checkpoint(ledger)
        self._fresh()
        publish_head(handle)
        self._fresh()
        observed = read_head()
        if type(observed) is not TransferStageHandle or observed != handle:
            raise TransferError("native_checkpoint_head_readback_failed")
        return self.retire_checkpoint_versions(handle, read_head, head_gate)

    def retire_checkpoint_versions(self, handle, read_head, head_gate):
        """Retire only noncurrent versions of an actually observed native head.

        This recovery path also works when previous failed head publications
        have filled the bounded version slots. It never creates a new head or
        discards chunks. Native head changes must share the supplied gate.
        """
        self._fresh()
        if type(handle) is not TransferStageHandle or handle.owner != self.owner or read_head() != handle:
            raise TransferError("native_checkpoint_head_not_current")
        retired = 0
        executed = False
        def retire():
            nonlocal retired, executed
            if executed:
                raise TransferError("duplicate_native_head_gate_invocation")
            executed = True
            with self._gate:
                self._fresh()
                if read_head() != handle:
                    raise TransferError("native_checkpoint_head_changed_before_retirement")
                self._read("checkpoint-" + handle.checkpoint + ".enc", self.MAX_CHECKPOINT_BYTES)
                names = [name for name in self._entry_names() if name.startswith("checkpoint-")
                         and name != "checkpoint-" + handle.checkpoint + ".enc"]
                # Authenticate/preflight ALL old versions first. A changed
                # original witness remains a failed baseline, not a replacement.
                for name in names:
                    self._read(name, self.MAX_CHECKPOINT_BYTES)
                for name in names:
                    self._fresh()
                    if read_head() != handle:
                        raise TransferError("native_checkpoint_head_changed_during_retirement")
                    blob, metadata = self._read_cipher(name, self.MAX_CHECKPOINT_BYTES + self.MAX_PROTECTION_OVERHEAD)
                    proof = metadata.st_dev, metadata.st_ino, sha256(blob).hexdigest()
                    if self._owned.get(name) != proof:
                        raise TransferError("checkpoint_version_changed_before_retirement")
                    os.unlink(name, dir_fd=self._root_fd)
                    self._owned.pop(name)
                    retired += 1
                os.fsync(self._root_fd)
        try:
            head_gate(handle, retire)
            if not executed:
                raise TransferError("native_head_gate_did_not_execute")
        except Exception as error:
            # The durable head already committed. Preserve that distinction
            # and retain real metadata/quota for any failed retirement.
            return NativeCheckpointCommit(handle, retired, True, type(error).__name__)
        return NativeCheckpointCommit(handle, retired, False)

    @_serialized
    def cleanup(self):
        # Revocation must not prevent removal of the exact local bytes already
        # adopted by this native instance. It never authorizes reading/publishing
        # new transfer data or recursively removing unfamiliar files.
        self._directories()
        names = self._entry_names()
        # Authenticate bounded recognized leftovers (e.g. a crash after chunk
        # fsync but before checkpoint publication) without treating them as
        # resume/progress proofs. Unknown files make cleanup fail before deletion.
        for name in names:
            if name not in self._owned:
                maximum = self.MAX_CHECKPOINT_BYTES if name.startswith("checkpoint-") else CHUNK_BYTES + 1
                blob, metadata = self._read_cipher(name, maximum + self.MAX_PROTECTION_OVERHEAD)
                plain = self._unseal(blob, self._domain + name)
                if type(plain) is not bytes or len(plain) > maximum:
                    raise TransferError("unrecognized_protected_staging_entry")
                self._adopt(name, blob, metadata)
        # Check ALL adopted witnesses before deleting ANY entry.
        for name, proof in self._owned.items():
            try:
                blob, metadata = self._read_cipher(name, self.MAX_CHECKPOINT_BYTES + self.MAX_PROTECTION_OVERHEAD)
            except FileNotFoundError:
                continue
            if (metadata.st_dev, metadata.st_ino, sha256(blob).hexdigest()) != proof:
                raise TransferError("adopted_staging_entry_changed_before_cleanup")
        for name, proof in sorted(self._owned.items(), key=lambda item: item[0] == "owner.enc"):
            try:
                blob, metadata = self._read_cipher(name, self.MAX_CHECKPOINT_BYTES + self.MAX_PROTECTION_OVERHEAD)
            except FileNotFoundError:
                self._owned.pop(name)
                continue
            if (metadata.st_dev, metadata.st_ino, sha256(blob).hexdigest()) != proof:
                raise TransferError("adopted_staging_entry_changed_before_cleanup")
            os.unlink(name, dir_fd=self._root_fd)
            self._owned.pop(name)
        os.fsync(self._root_fd)
        os.rmdir(self._root_name, dir_fd=self._parent_fd)
        os.fsync(self._parent_fd)

    def _entry_names(self):
        self._directories()
        files = {file.id: file for file in self.manifest.files}
        maximum = 1 + self.MAX_CHECKPOINTS + sum(max(1, file.chunks) for file in self.manifest.files)
        names = []
        checkpoints = 0
        with os.scandir(self._root_fd) as entries:
            for entry in entries:
                if len(names) >= maximum or not entry.is_file(follow_symlinks=False):
                    raise TransferError("unknown_or_unbounded_staging_entries")
                name = entry.name
                known = name == "owner.enc"
                if name.startswith("checkpoint-") and name.endswith(".enc"):
                    known = _ID.fullmatch(name[11:-4]) is not None
                    checkpoints += 1
                    if checkpoints > self.MAX_CHECKPOINTS:
                        raise TransferError("native_checkpoint_version_limit_reached")
                elif name.startswith("empty-") and name.endswith(".enc"):
                    file = files.get(name[6:-4])
                    known = file is not None and file.size == 0
                elif name.endswith(".enc") and len(name) > 37:
                    file_id, _, number = name[:-4].partition("-")
                    file = files.get(file_id)
                    known = (file is not None and number.isascii() and number.isdecimal() and len(number) <= 4
                             and number == str(int(number)) and int(number) < file.chunks)
                if not known:
                    raise TransferError("unfamiliar_staging_entry_preserved")
                names.append(name)
        return names

    def close(self):
        with self._gate:
            if self._closed:
                return
            self._closed = True
            if self._root_fd is not None:
                os.close(self._root_fd)
            os.close(self._parent_fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
