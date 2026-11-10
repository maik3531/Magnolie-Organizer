"""One original pre-dialog destination context (#499), never a data grant.

Preferences are compared before mutation and passed as the original native CAS
input. The writer callback rechecks independent metadata only: it must not read
its own pending preference writer and accidentally replace the original context.
"""
from hashlib import sha256
import os
from pathlib import Path
import secrets
import threading
import time

from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_source_choice import native_folder_witness
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_telefon import canonical


class NativeDialogBook:
    """The GUI's actual held saved-book node, not a renderer path or grant."""
    def __init__(self,path):
        from magnolie_file_protection import ExistingFileTransferProtection
        self.path=Path(path);self.fd=None;self._signature=ExistingFileTransferProtection._signature
        try:
            self.fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            ProtectedPhotoPreferences._private(os.fstat(self.fd))
            self.signature=self._signature(os.fstat(self.fd))
            self.require_current()
        except BaseException:self.close();raise

    def require_current(self):
        if (self.fd is None or self._signature(os.fstat(self.fd))!=self.signature or
                self._signature(os.stat(self.path,follow_symlinks=False))!=self.signature):
            raise TransferError('media_destination_original_book_changed')
        return True

    def close(self):
        fd,self.fd=self.fd,None
        if fd is not None:os.close(fd)


class NativeDestinationFolderChoice:
    def __init__(self, connection, kind, *, book_version, book_witness, clock=time.monotonic):
        from magnolie_file_desktop_connection import NativeDesktopFileConnection
        from magnolie_file_control import _hex
        if type(connection) is not NativeDesktopFileConnection or kind not in ('images', 'video'):
            raise TransferError('media_destination_native_choice_required')
        if (not _hex(book_version) or type(book_witness) is not list or len(book_witness)!=9 or
                any(type(number) is not int or number<0 for number in book_witness)):
            raise TransferError('media_destination_original_book_required')
        self.connection, self.kind, self.clock = connection, kind, clock
        self.selection = secrets.token_hex(32)
        self.issued = self.last = clock()
        self.closed = threading.Event()
        self._fd_gate = threading.Lock()
        self.used = False
        self.book_fd = None
        self.meta_fd = None
        try:
            connection._ready()
            self.authority = connection._authority
            self.peer = self.authority.current_peer()
            if self.peer is None:
                raise TransferError('media_destination_original_context_changed')
            self.controls = connection._controls
            self.control = self._control_position()
            self.transport = connection._media_transport
            self.intent = self._intent_position()
            self.expected = connection._preferences.read()
            if self.expected.policy is None or not self.expected.associated:
                raise TransferError('media_destination_existing_preferences_required')
            if (kind == 'images' and self.expected.policy.enabled or
                    kind == 'video' and self.expected.policy.videos is not None and self.expected.policy.videos.enabled):
                raise TransferError('media_destination_disable_first')
            if kind == 'video' and (not self.expected.policy.enabled or not connection._video_data_handlers_ready or not connection._authority.video_available()):
                raise TransferError('video_preferences_destination_choice_requires_off')
            root = Path(connection._authority.binding.native_directory)
            self.book_fd = os.open(root.parent / 'daten.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            with NativeMediaRetention(root) as book:
                self.meta_fd = os.dup(book._fd)
                self.meta_identity = book._identity
                ProtectedPhotoPreferences._private(os.fstat(self.book_fd))
                self.book_signature = tuple(book._protection._signature(os.fstat(self.book_fd)))
                if tuple(book._book_file()) != self.book_signature:
                    raise TransferError('media_destination_original_book_changed')
                # Authenticate the saved metadata head without requiring trash
                # enablement or borrowing a deletion/copy permit.
                self.book_record = self._book_position(book)
                saved=book._read()
                if (saved is None or saved['book_file']!=book_witness or tuple(book_witness)!=self.book_signature or
                        saved['book_sha256']!=book_version):
                    raise TransferError('media_destination_original_saved_book_required')
            self.current()
        except BaseException:
            self.close()
            raise

    def _control_position(self):
        controls = self.controls
        remote = controls._remote
        return (controls._session_epoch, None if remote is None else (remote.challenge, remote.grants), controls._sent_grants)

    @staticmethod
    def _book_position(book):
        # One bounded SQLite read snapshot: no unbounded/cross-version BLOB
        # fetch between shape validation and authenticating the original head.
        if not book._db.in_transaction:book._db.execute('BEGIN')
        shape = book._db.execute('SELECT typeof(value),length(value) FROM meta WHERE key=?', (book.KEY,)).fetchone()
        if shape is None:return None
        if shape[0] != 'blob' or not 28 <= shape[1] <= 8192:
            raise TransferError('media_destination_original_book_changed')
        book._read()  # Authenticate even an unchanged-looking encrypted head.
        row = book._db.execute('SELECT value FROM meta WHERE key=?', (book.KEY,)).fetchone()
        return None if row is None else sha256(bytes(row[0])).hexdigest()

    def _intent_position(self):
        transport = self.connection._media_transport
        if transport is None:
            return None
        # Original immutable publications; no transport/control monitor or
        # protected store lookup while a preferences writer owns its lock.
        return (transport._generation, transport._intent, transport._closed.is_set(),
            sha256(canonical([transport._display_body, transport._sent, transport._acknowledged, transport._received])).hexdigest())

    def context_current(self):
        try:
            connection = self.connection
            now = self.clock()
            connection._ready()
            if (self.closed.is_set() or now < self.last or now - self.issued >= 60 or
                    connection._controls is not self.controls or self._control_position() != self.control or
                    connection._media_transport is not self.transport or self._intent_position() != self.intent or
                    connection._authority is not self.authority or self.authority.current_peer() != self.peer):
                raise TransferError('media_destination_original_context_changed')
            with NativeMediaRetention(connection._authority.binding.native_directory) as book:
                fd, meta_fd = self.book_fd, self.meta_fd
                if fd is None or meta_fd is None:
                    raise TransferError('media_destination_original_context_changed')
                if (book._identity != self.meta_identity or book._protection._key(os.fstat(meta_fd)) != self.meta_identity or
                        self._book_position(book) != self.book_record or
                        tuple(book._book_file()) != self.book_signature or
                        tuple(book._protection._signature(os.fstat(fd))) != self.book_signature):
                    raise TransferError('media_destination_original_book_changed')
            ended = self.clock()
            if self.closed.is_set() or ended < now or ended - self.issued >= 60:
                raise TransferError('media_destination_original_context_changed')
            self.last = ended
            return True
        except BaseException:
            self.close()
            raise

    def current(self):
        self.context_current()
        if self.connection._preferences.read() != self.expected:
            self.close()
            raise TransferError('media_destination_original_preferences_changed')
        return True

    def commit(self, path, witness):
        if self.used:
            raise TransferError('media_destination_original_context_changed')
        self.used = True
        try:
            if type(path) is not str or not path or len(path) > 4096 or type(witness) is not dict:
                raise TransferError('media_destination_original_selection_required')
            self.current()
            connection = self.connection
            if (connection._mapped_worker is not None or connection._album_worker is not None or connection._run is not None or
                    connection._source_pending is not None or connection._source_run is not None or connection._media_sender is not None or
                    connection._desktop_session is not None and connection._desktop_session._running or
                    connection._media_source is not None and connection._media_source._prepared or
                    connection._media_pc_source is not None and connection._media_pc_source._prepared):
                raise TransferError('file_desktop_album_worker_busy')
            with NativeCollectionRoot(path, self.context_current) as selected:
                if canonical(native_folder_witness(selected)) != canonical(witness):
                    raise TransferError('media_destination_original_selection_required')
                self.current()
                # Serialize with the existing native save/pause publisher in
                # phone.db. This is only its metadata writer lease: no trash
                # setting, deletion permit, transfer or capture right is borrowed.
                with NativeMediaRetention(connection._authority.binding.native_directory) as book:
                    with book._transaction():
                        self.current()
                        return self._commit_selected(selected, path)
        finally:
            self.close()

    def _commit_selected(self, selected, path):
        from magnolie_photo_destination import NativePhotoDestinationController, NativeVideoDestinationController
        connection = self.connection
        controller = (NativePhotoDestinationController if self.kind == 'images' else NativeVideoDestinationController)(connection._authority)
        try:
            choice = controller.choose_custom(controller.issue_action(), path)
            self.current()
            preferences = connection._preferences
            session = connection.desktop_session()
            previous = self.expected.policy.destination if self.kind == 'images' else (
                self.expected.policy.videos.destination if self.expected.policy.videos is not None else None)
            session._retain_backup_destination(self.expected, self.kind, previous, choice.destination, _native_current=self.context_current)
            self.current()
            def writer_current():
                self.context_current()
                selected._require()
                return True
            action = preferences.issue_action(_native_current=writer_current)
            if self.kind == 'images':
                saved = preferences.set_photo_destination(action, self.expected, choice, historical_choice='keep_existing')
            else:
                saved = preferences.set_video_scope(action, self.expected, enabled=False, destination_choice=choice, historical_choice='keep_existing')
            writer_current()
            if preferences.read() != saved:
                raise TransferError('media_destination_original_readback_changed')
            session._destination_choice_committed(self.kind, saved)
            return dict(version=saved.version)
        finally:
            controller.close()

    def close(self):
        self.closed.set()
        with self._fd_gate:
            fd, self.book_fd = self.book_fd, None
            meta_fd, self.meta_fd = self.meta_fd, None
        try:
            if fd is not None:os.close(fd)
        finally:
            if meta_fd is not None:os.close(meta_fd)
