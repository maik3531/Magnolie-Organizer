"""Original native PC folder choice (#488), not SEND or RECEIVE authority.

Only the private native UI/IPC route can supply a folder selection. The public
photo action/wire grammar has no source path, native identity or approval flag.
"""
from hashlib import sha256
from contextlib import closing
import secrets
import time

from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_sync import effective
from magnolie_telefon import canonical


def native_folder_witness(root):
    if type(root) is not NativeCollectionRoot:raise TransferError('media_collection_native_root_required')
    root._require()
    return dict(directory=root._directory.wire(),key=list(root.key),birthtime=list(root.birthtime),mount_id=root.mount_id)


def roots_projection(snapshot):
    return dict(version=snapshot.version,roots=[dict(id=root.id,version=root.version,media_type='video' if root.media_type=='videos' else 'images',
        display_path=root.directory.path) for root in snapshot.roots])


class NativeCollectionFolderChoice:
    def __init__(self,connection,kind,version):
        from magnolie_file_desktop_connection import NativeDesktopFileConnection
        if type(connection) is not NativeDesktopFileConnection or kind not in ('images','video'):
            raise TransferError('media_collection_native_choice_required')
        self._connection=connection;self._kind=kind;self._issued=self._last=time.monotonic()
        self._closed=False;self._used=False;self.selection=secrets.token_hex(32)
        self._controls=connection._controls
        self._control=self._control_snapshot()
        self._expected=connection._preferences.read()
        if self._expected.policy is None or not self._expected.associated:
            raise TransferError('media_collection_roots_existing_preferences_required')
        self._new_catalog=self._expected.policy.collection_roots is None
        self._token=connection._media_transport.intent_for(kind,to_phone=True) if connection._media_transport is not None else None
        self._book=None;self._snapshot=None
        self.current()
        if sha256(canonical(self._token.body)).hexdigest()!=version:
            self.close();raise TransferError('media_collection_native_choice_changed')
        with NativeMediaRetention(connection._authority.binding.native_directory) as retention:
            with retention.permit(self.current) as permit:
                if permit is None:raise TransferError('media_collection_saved_book_required')
                self._book=sha256(canonical(retention._read())).hexdigest()
                with self._catalog() as catalog:
                    self._snapshot=catalog.read()
                    if self._new_catalog and self._snapshot.version!=catalog._absent:
                        raise TransferError('media_collection_roots_original_witness_required')
                permit.require_current();self.current()

    def _catalog(self):
        from magnolie_media_source_roots import ProtectedMediaCollectionRoots
        return closing(ProtectedMediaCollectionRoots(self._connection._authority,original=self._expected.policy.collection_roots))

    def _control_snapshot(self):
        with self._controls._gate:
            remote=self._controls._remote
            return (self._controls._session_epoch,None if remote is None else (remote.challenge,remote.grants))

    def current(self):
        c=self._connection;c._ready();now=time.monotonic()
        if (self._closed or now<self._last or now-self._issued>=60 or c._controls is not self._controls
                or self._control_snapshot()!=self._control or c._media_pc_source is None
                or c._native_metadata_current() is not True or self._token is None
                or c._media_transport.intent_for(self._kind,to_phone=True) is not self._token
                or effective(self._token.body)['collection_mode']!='entire_collection'
                or c._preferences.read()!=self._expected):
            self.close();raise TransferError('media_collection_native_choice_changed')
        self._last=now;return True

    def page(self):
        self.current()
        return dict(selection=self.selection,media_type=self._kind,**roots_projection(self._snapshot))

    def commit(self,path,witness):
        if self._used:raise TransferError('media_collection_native_choice_changed')
        self._used=True;c=self._connection
        if type(path) is not str or not path or len(path)>4096 or type(witness) is not dict:
            self.close();raise TransferError('media_collection_native_selection_required')
        try:
            self.current()
            with NativeMediaRetention(c._authority.binding.native_directory) as retention:
                with retention.permit(self.current) as permit:
                    if permit is None or sha256(canonical(retention._read())).hexdigest()!=self._book:
                        raise TransferError('media_collection_saved_book_required')
                    def current():
                        self.current();permit.require_current()
                        if sha256(canonical(retention._read())).hexdigest()!=self._book:
                            raise TransferError('media_collection_saved_book_required')
                        return True
                    with NativeCollectionRoot(path,current) as root:
                        # The native GTK dialog owner retains its actual root FD
                        # until the private RPC returns. A substituted selection
                        # cannot be re-identified later just by its pathname.
                        if canonical(native_folder_witness(root))!=canonical(witness):
                            raise TransferError('media_collection_original_selection_required')
                        with self._catalog() as catalog:
                            selected=catalog.add(catalog.issue_action(),self._snapshot,root,
                                'images' if self._kind=='images' else 'videos')
                            current()
                            if self._new_catalog:
                                self._expected=c._preferences.bind_collection_roots(c._preferences.issue_action(),self._expected,catalog)
                                c._local() # Refresh passive UI metadata; grant fields stay unchanged.
                                current()
                        return roots_projection(selected)
        finally:self.close()

    def close(self):self._closed=True
