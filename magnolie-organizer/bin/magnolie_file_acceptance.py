"""Immutable native accepted transfer description (#330), not a live grant.

Capture belongs to an actual native destination-choice/acceptance operation.
Parsing protected stored metadata performs no filesystem I/O and restores no
permission. Before execution, native identity/grants and original destination
identity must be freshly checked; pairing or a parsed record is insufficient.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from magnolie_file_transfer import FileManifest, ManifestFile, NativeTransferBinding, TransferError


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise TransferError("file_acceptance_unexpected_fields")


def _version(value):
    if type(value) is not int or value != 1:
        raise TransferError("file_acceptance_unsupported_format")


@dataclass(frozen=True)
class NativeAcceptedDestination:
    path: str
    # Root followed by its ancestors up to /. All names derive from path.
    ancestor_keys: tuple

    def __post_init__(self):
        if (type(self.path) is not str or not self.path or "\0" in self.path or len(self.path.encode("utf-8")) > 4096
                or not Path(self.path).is_absolute() or str(Path(self.path)) != self.path
                or ".." in Path(self.path).parts or type(self.ancestor_keys) is not tuple
                or not 1 <= len(self.ancestor_keys) <= 128
                or len(self.ancestor_keys) != len(Path(self.path).parents) + 1):
            raise TransferError("file_acceptance_invalid_destination")
        for key in self.ancestor_keys:
            if (type(key) is not tuple or len(key) != 2
                    or any(type(value) is not int or not 0 <= value < 2**64 for value in key) or key[1] == 0):
                raise TransferError("file_acceptance_invalid_destination_witness")

    @classmethod
    def capture(cls, path):
        path = Path(path)
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise TransferError("file_acceptance_canonical_destination_required")
        keys = []
        for item in (path, *path.parents):
            value = os.lstat(item)
            if not stat.S_ISDIR(value.st_mode):
                raise TransferError("file_acceptance_linked_destination")
            keys.append((value.st_dev, value.st_ino))
        result = cls(str(path), tuple(keys))
        result.verify()
        return result

    def verify(self):
        path = Path(self.path)
        for item, key in zip((path, *path.parents), self.ancestor_keys):
            value = os.lstat(item)
            if not stat.S_ISDIR(value.st_mode) or (value.st_dev, value.st_ino) != key:
                raise TransferError("file_acceptance_destination_changed")
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            value = os.fstat(fd)
            if (not stat.S_ISDIR(value.st_mode) or (value.st_dev, value.st_ino) != self.ancestor_keys[0]
                    or value.st_uid != os.geteuid() or value.st_mode & 0o022):
                raise TransferError("file_acceptance_unsafe_destination")
        finally:
            os.close(fd)

    def wire(self):
        return {"format": 1, "path": self.path, "ancestor_keys": [list(key) for key in self.ancestor_keys]}

    @classmethod
    def parse(cls, value):
        _fields(value, ("format", "path", "ancestor_keys"))
        _version(value["format"])
        keys = value["ancestor_keys"]
        if type(keys) is not list or any(type(key) is not list for key in keys):
            raise TransferError("file_acceptance_invalid_destination_witness")
        return cls(value["path"], tuple(tuple(key) for key in keys))

    @property
    def grants_write_authority(self):
        return False


@dataclass(frozen=True)
class NativeAcceptedTransfer:
    manifest: FileManifest
    binding: NativeTransferBinding
    targets: tuple
    destination: NativeAcceptedDestination

    def __post_init__(self):
        if (type(self.manifest) is not FileManifest or type(self.binding) is not NativeTransferBinding
                or type(self.destination) is not NativeAcceptedDestination or type(self.targets) is not tuple
                or (self.manifest.sender_id, self.manifest.receiver_id) != (self.binding.sender_id, self.binding.receiver_id)
                or any(type(entry) is not tuple or len(entry) != 2 for entry in self.targets)
                or tuple(entry[0] for entry in self.targets) != tuple(file.id for file in self.manifest.files)):
            raise TransferError("file_acceptance_native_context_required")
        FileManifest(self.manifest.transfer_id, self.manifest.source_id, self.manifest.sender_id, self.manifest.receiver_id,
            tuple(ManifestFile(file.id, entry[1], file.size, file.sha256) for file, entry in zip(self.manifest.files, self.targets)),
            self.manifest.total_bytes)

    @classmethod
    def capture(cls, manifest, binding, targets, destination, current_binding):
        if not callable(current_binding) or current_binding() != binding:
            raise TransferError("file_acceptance_binding_revoked")
        mapping = dict(targets)
        if type(manifest) is not FileManifest or set(mapping) != {file.id for file in manifest.files}:
            raise TransferError("file_acceptance_mapping_incomplete")
        result = cls(manifest, binding, tuple((file.id, mapping[file.id]) for file in manifest.files),
            NativeAcceptedDestination.capture(destination))
        result.verify(current_binding)
        return result

    def verify(self, current_binding):
        if not callable(current_binding) or current_binding() != self.binding:
            raise TransferError("file_acceptance_binding_revoked")
        self.destination.verify()
        if current_binding() != self.binding:
            raise TransferError("file_acceptance_binding_revoked")

    def wire(self):
        return {"format": 1, "manifest": self.manifest.wire(), "binding": dict(vars(self.binding)),
            "targets": [{"file_id": file_id, "path": path} for file_id, path in self.targets], "destination": self.destination.wire()}

    @classmethod
    def parse(cls, value):
        _fields(value, ("format", "manifest", "binding", "targets", "destination"))
        _version(value["format"])
        _fields(value["binding"], NativeTransferBinding.__dataclass_fields__)
        if type(value["targets"]) is not list:
            raise TransferError("file_acceptance_mapping_incomplete")
        targets = []
        for entry in value["targets"]:
            _fields(entry, ("file_id", "path"))
            targets.append((entry["file_id"], entry["path"]))
        return cls(FileManifest.parse(value["manifest"]), NativeTransferBinding(**value["binding"]), tuple(targets),
            NativeAcceptedDestination.parse(value["destination"]))

    @property
    def fingerprint(self):
        raw = json.dumps(self.wire(), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return sha256(b"magnolie-native-file-acceptance-v1\0" + raw).hexdigest()

    @property
    def grants_write_authority(self):
        return False

    @property
    def is_saved_receipt(self):
        return False
