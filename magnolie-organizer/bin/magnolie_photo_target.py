"""Fresh native target bytes for photo conflict planning, never mutation authority.

The receiver supplies a freshly authenticated historical local save receipt. That
receipt does not prove current presence; missing paths never prove deletion.
"""
from dataclasses import dataclass
from hashlib import sha256
import os
import stat

from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_receipt import NativeSavedFileReceipt
from magnolie_file_transfer import CHUNK_BYTES, MAX_FILE_BYTES, TransferError
from magnolie_photo_plan import NativePhotoObservation, PhotoContentWitness
from magnolie_photo_destination import media_directory_is_backup


@dataclass(frozen=True)
class NativePhotoTargetReadback:
    file_id: str
    saved_record_sha256: str
    observation: NativePhotoObservation

    @property
    def grants_write_authority(self):
        return False

    @property
    def is_saved_receipt(self):
        return False


def observe_saved_target(accepted, receipt, current_binding):
    """Descriptor-bound read-only observation; no adoption of replacement files.

    Callers must obtain and revalidate receipt provenance through the protected
    native index, not accept a constructed/serialized receipt from a UI or peer.
    """
    if (type(accepted) is not NativeAcceptedTransfer or type(receipt) is not NativeSavedFileReceipt
            or not callable(current_binding) or receipt.manifest_sha256 != accepted.manifest.fingerprint
            or receipt.accepted_sha256 != accepted.fingerprint
            or dict(accepted.targets).get(receipt.file_id) != receipt.relative_path
            or len(receipt.parent_keys) != len(receipt.relative_path.split('/'))
            or not receipt.parent_keys or receipt.parent_keys[0] != accepted.destination.ancestor_keys[0]):
        raise TransferError('photo_target_native_receipt_context_required')
    names = receipt.relative_path.split('/')
    fds = []

    def fresh():
        accepted.verify(current_binding)

    def directories():
        fresh()
        for index, fd in enumerate(fds):
            value = os.fstat(fd)
            if (not stat.S_ISDIR(value.st_mode) or (value.st_dev, value.st_ino) != receipt.parent_keys[index]
                    or value.st_uid != os.geteuid() or value.st_mode & 0o022):
                raise TransferError('photo_target_original_parent_changed')
            if index:
                named = os.stat(names[index-1], dir_fd=fds[index-1], follow_symlinks=False)
                if not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != receipt.parent_keys[index]:
                    raise TransferError('photo_target_original_parent_changed')

    def result(state, content=None, managed=False):
        fresh()
        return NativePhotoTargetReadback(receipt.file_id, receipt.protected_record_sha256,
            NativePhotoObservation(state, content, managed))

    def signature(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_uid,
                value.st_gid, value.st_nlink, value.st_mtime_ns, value.st_ctime_ns)

    fresh()
    if media_directory_is_backup(os.path.join(accepted.destination.path,*names[:-1])):
        # A saved historical mapping is not permission to compare backup bytes.
        # Excluded content is UNKNOWN, never missing/deleted or a new baseline.
        return result('unknown')
    try:
        fds.append(os.open(accepted.destination.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC))
        directories()
        for name in names[:-1]:
            fds.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1]))
            directories()
        fd = os.open(names[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fds[-1])
        try:
            before = os.fstat(fd)
            managed = (before.st_dev, before.st_ino) == receipt.file_key
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_mode & 0o077
                    or before.st_nlink not in ({1, 2} if managed else {1})
                    or not 0 <= before.st_size <= MAX_FILE_BYTES):
                return result('unknown')
            digest = sha256(); remaining = before.st_size
            while remaining:
                directories()
                part = os.read(fd, min(CHUNK_BYTES, remaining))
                if not part:
                    return result('unknown')
                digest.update(part); remaining -= len(part)
            if os.read(fd, 1):
                return result('unknown')
            after = os.fstat(fd)
            named = os.stat(names[-1], dir_fd=fds[-1], follow_symlinks=False)
            directories()
            if signature(before) != signature(after) or signature(after) != signature(named):
                return result('unknown')
            return result('present', PhotoContentWitness(digest.hexdigest(), before.st_size), managed)
        finally:
            os.close(fd)
    except FileNotFoundError:
        # This is only an observed absence, not a tombstone or a complete scan.
        directories()
        return result('missing')
    except (OSError, TransferError):
        # Native root/consent revocation is never downgraded to valid metadata.
        fresh()
        return result('unknown')
    finally:
        for fd in reversed(fds):
            os.close(fd)
