"""Read-only existing independent phone secret, never a key/store factory.

Native callers supply their exact current profile's phone root. No default path,
PhoneStore, identity, database, keyring fallback or consent/book key is consulted.
"""
from contextlib import contextmanager
import hmac
import os

from magnolie_contact_source_authority import NativeContactSourceApprovalStore as _PrivateFiles


class NativeNotesExistingJournalKey:
    DOMAIN = b'Magnolie/notes-original/journal/from-existing-phone-storage/linux/v1'

    def __init__(self, phone_root):
        if type(phone_root) is not str or not os.path.isabs(phone_root) or os.path.normpath(phone_root) != phone_root:
            raise TypeError('notes_existing_key_native_root_required')
        self.root = phone_root

    @staticmethod
    def _directory_identity(value):
        return value.st_dev, value.st_ino, value.st_uid, value.st_mode

    @staticmethod
    def _leaf_identity(value):
        return (value.st_dev, value.st_ino, value.st_uid, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    @contextmanager
    def _existing_buffer(self):
        directory, source, raw = None, None, bytearray(33)
        try:
            try:
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            except FileNotFoundError:
                yield None
                return
            root = os.fstat(directory)
            _PrivateFiles._private(root, directory=True)
            try:
                descriptor = os.open('storage.key', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
            except FileNotFoundError:
                yield None
                return
            try:
                source = os.fdopen(descriptor, 'rb', buffering=0)
            except Exception:
                try: os.close(descriptor)
                except OSError: pass  # FileIO may already have closed a rejected descriptor.
                raise
            leaf = os.fstat(source.fileno())
            _PrivateFiles._private(leaf)
            if leaf.st_size != 32 or source.readinto(raw) != 32:
                raise PermissionError('notes_existing_key_length_invalid')
            identity = self._directory_identity(root), self._leaf_identity(leaf)
            yield memoryview(raw)[:32], identity
            # Recheck path/descriptor correlation even after the second read.
            current_root = os.stat(self.root, follow_symlinks=False)
            current_leaf = os.stat('storage.key', dir_fd=directory, follow_symlinks=False)
            _PrivateFiles._private(current_root, directory=True)
            _PrivateFiles._private(current_leaf)
            if identity != (self._directory_identity(current_root), self._leaf_identity(current_leaf)) or self._leaf_identity(os.fstat(source.fileno())) != identity[1]:
                raise PermissionError('notes_existing_key_changed_during_read')
        finally:
            raw[:] = b'\0' * len(raw)
            if source is not None: source.close()
            if directory is not None: os.close(directory)

    def read_existing(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        with self._existing_buffer() as before:
            if before is None:
                return None
            secret, identity = before
            derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=self.DOMAIN).derive(secret)
            with self._existing_buffer() as after:
                if after is None or after[1] != identity or not hmac.compare_digest(secret, after[0]):
                    raise PermissionError('notes_existing_key_changed_during_read')
            return derived  # Journal consumer owns this separate derived copy.
