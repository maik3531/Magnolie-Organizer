"""Bounded original selected-root pass (#488), never wire/source authority.

Freeze the explicit native membership BEFORE offers. Each offered file still
needs its own actual source/cache/SEND owner and independent backup/source END.
No old catalog flag, path, enumeration order or mapped subset is completion.
"""
from magnolie_file_transfer import TransferError
import threading


class NativeCollectionPass:
    MAX_MEMBERS=4096

    def __init__(self,worker):
        from magnolie_media_source_worker import NativeMappedMediaWorker
        if type(worker) is not NativeMappedMediaWorker:
            raise TransferError('media_collection_original_worker_required')
        self._worker=worker;self._catalog=None;self._frames=[];self._active=None;self._closed=False
        self._mapped={}
        try:
            worker._current();c=worker._connection
            if worker._preferences.policy is None or worker._preferences.policy.collection_roots is None:
                raise TransferError('media_collection_explicit_source_roots_required')
            self._catalog=c._preferences.open_collection_roots();self._snapshot=self._catalog.read()
            kind='videos' if worker._kind=='video' else 'images'
            selected=[root for root in self._snapshot.roots if root.media_type==kind]
            if not selected:raise TransferError('media_collection_explicit_source_roots_required')
            identities=set()
            for selection in selected:
                root=self._catalog.open_root(selection,self._scan_current)
                frame=(selection,root,None,{})
                self._frames.append(frame) # Ownership before any failing scan.
                with self._catalog.selected_root_lease(selection):
                    inventory=root.inventory(cancelled=worker._stop.is_set,maximum_entries=self.MAX_MEMBERS)
                    if inventory.needs_review:raise TransferError('media_collection_incomplete_native_inventory')
                    signatures=frame[3]
                    for member in inventory.members:
                        worker._current()
                        if member.key in identities:raise TransferError('media_collection_ambiguous_identity')
                        identities.add(member.key)
                        if len(identities)>self.MAX_MEMBERS:raise TransferError('media_collection_inventory_bound')
                        with root.open_member(member) as lease:signatures[member]=lease._signature
                self._frames[-1]=(selection,root,inventory,signatures)
            self._catalog_current()
        except BaseException:self.close();raise

    def _scan_current(self):
        # Only the original worker's inventory lane calls this, never a live
        # source/socket callback. Recheck local opt-outs while enumerating too.
        self._worker._current()
        if self._worker._connection._preferences.read()!=self._worker._preferences:
            raise TransferError('media_source_local_consent_required')
        return True

    def _catalog_current(self):
        self._scan_current()
        if self._closed or self._catalog.read()!=self._snapshot:
            raise TransferError('media_collection_original_catalog_changed')

    def require_member(self,selected,member):
        # Used from source/socket callbacks: no SQLite handle, catalog monitor
        # or inventory crosses from the original worker into another IO lane.
        self._worker._current();active=self._active
        if self._closed or self._worker._collection is not self or active is None or active[0] is not selected or active[1] is not member:
            raise TransferError('media_collection_original_batch_member_required')
        return True

    def note_checked_mapping(self,observation):
        from magnolie_media_source import NativeMediaSourceObservation
        self._worker._current()
        if (threading.current_thread() is not self._worker._thread or self._worker._collection is not self
                or self._closed or self._active is not None or type(observation) is not NativeMediaSourceObservation
                or observation.file_key in self._mapped):
            raise TransferError('media_collection_original_mapping_observation_required')
        # Data from the actual full native comparison, recorded only after an
        # unchanged comparison or a changed source's real backup/END. It never
        # grants a second send, publication, native READ or a new PC identity.
        self._mapped[observation.file_key]=observation

    def already_checked_mapping(self,selected,member):
        self.require_member(selected,member);observation=self._mapped.get(member.key)
        if observation is None:return False
        frame=next(frame for frame in self._frames if frame[0] is selected)
        if observation.signature!=frame[3][member]:
            raise TransferError('media_collection_original_inventory_changed')
        return True

    def members(self):
        for selected,root,inventory,signatures in self._frames:
            for member in inventory.members:
                self._catalog_current()
                with self._catalog.selected_root_lease(selected),root.open_member(member) as lease:
                    if lease._signature!=signatures[member]:
                        raise TransferError('media_collection_original_inventory_changed')
                self._active=(selected,member)
                try:yield selected,member
                finally:self._active=None

    def finish(self):
        # Actual END closes each offered member's IO lease. Re-check the whole
        # frozen inventory so edits/new files/moves after an earlier END cannot
        # be hidden by a successful later file or a stable size/generation.
        self._catalog_current()
        for selected,root,inventory,signatures in self._frames:
            with self._catalog.selected_root_lease(selected):
                latest=root.inventory(cancelled=self._worker._stop.is_set,maximum_entries=self.MAX_MEMBERS)
                if latest.needs_review or frozenset(latest.members)!=frozenset(inventory.members):
                    raise TransferError('media_collection_original_inventory_changed')
                for member,signature in signatures.items():
                    with root.open_member(member) as lease:
                        if lease._signature!=signature:raise TransferError('media_collection_original_inventory_changed')
        self._catalog_current()

    def close(self):
        self._closed=True;self._active=None
        failure=None
        for _,root,_,_ in self._frames:
            try:root.close()
            except Exception as error:
                if failure is None:failure=error
        if self._catalog is not None:
            try:self._catalog.close()
            except Exception as error:
                if failure is None:failure=error
        if failure is not None:raise failure
