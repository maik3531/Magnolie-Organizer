"""Private immutable file-manifest and readback-bound resume state (#329).

No listener, capability advertisement, personal store, destination publication
or implicit consent. All I/O callbacks belong to a native accepted operation,
never to a network request. Persisted chunk claims are re-read, not trusted.
"""

from dataclasses import dataclass
from hashlib import sha256
import re
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
