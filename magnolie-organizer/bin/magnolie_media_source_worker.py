"""Bounded mapped/explicitly selected PC pass (#488), never arbitrary-PC scan."""
from hashlib import sha256
from pathlib import Path
import os
import threading
import time

from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention
from magnolie_telefon import canonical


class NativeMappedMediaWorker:
    PAGE_SIZE=32
    def __init__(self,connection,kind,book_fence=None,*,automatic=False,native_current=None):
        from magnolie_file_desktop_connection import NativeDesktopFileConnection
        if (type(connection) is not NativeDesktopFileConnection or kind not in ('images','video')
                or type(automatic) is not bool
                or native_current is not None and not callable(native_current)
                or book_fence is not None and (type(book_fence) is not tuple or len(book_fence)!=3)):
            raise TransferError('media_source_native_worker_required')
        self._connection=connection;self._kind=kind
        self._stop=threading.Event();self._ended=threading.Event();self._lock=threading.Lock()
        self._thread=threading.Thread(target=self._run,name='magnolie-mapped-media',daemon=True)
        self._state='starting';self._error=None;self._saved=self._known=0
        self._token=None;self._preferences=None;self._book=None;self._deadline=None
        self._book_fence=book_fence
        self._automatic=automatic
        self._native_current=native_current
        self._collection=None;self._collection_control=None;self._active_sender=None;self._filtered=0

    def start(self):self._thread.start()
    def stop(self):self._stop.set();self._connection._wake_album_worker()
    def join(self,timeout=None):self._thread.join(timeout);return not self._thread.is_alive()
    def progress(self):
        with self._lock:return dict(state=self._state,error=self._error,saved_files=self._saved,known_files=self._known,
            filtered_files=self._filtered,conflicts=[])

    def _current(self):
        c=self._connection;c._ready()
        if (self._stop.is_set() or self._ended.is_set() or c._mapped_worker is not self
                or self._deadline is None or time.monotonic()>=self._deadline
                or self._token is None or c._media_transport.intent_for(self._kind,to_phone=True) is not self._token):
            raise TransferError('media_source_native_operation_ended')
        if c._native_metadata_current() is not True:raise TransferError('media_source_current_metadata_required')
        if self._collection_control is not None:
            controls,session,challenge=self._collection_control
            remote=controls._remote
            if c._controls is not controls or controls._session_epoch!=session or remote is None or remote.challenge!=challenge:
                raise TransferError('media_collection_original_send_binding_required')
        if self._native_current is not None and self._native_current() is not True:raise TransferError('media_source_native_operation_ended')
        if self._automatic:
            from magnolie_media_sync import effective
            if effective(self._token.body)['auto_mode']!='wifi' or c._native_wifi_current() is not True:
                raise TransferError('media_source_native_wifi_required')
        # Open on the calling lane: sender callbacks also run on the socket
        # dispatcher, never share a worker-thread SQLite handle with that lane.
        with NativeMediaRetention(c._authority.binding.native_directory) as policy:
            if policy.saved_book_version()!=self._book:raise TransferError('media_source_original_book_required')
        # Actual source/sender operations independently revalidate preferences
        # under their serialized I/O owner. Do not poll that nonwaiting store
        # concurrently with the socket dispatcher and manufacture a busy failure.
        peer=c._authority.current_peer();policy=self._preferences.policy
        consent=policy.sending if policy is not None else None
        if (peer is None or consent is None or consent.pairing_epoch!=peer.pairing_epoch
                or not (consent.photos if self._kind=='images' else consent.videos)):
            raise TransferError('media_source_local_consent_required')
        return True

    def _idle_sender_current(self,sender):
        # Only the idle worker polls here, never a held source/cache callback.
        # Controls consult local mapping availability. Serialize that lookup
        # with actual socket handlers, but do not block or manufacture a busy
        # consent failure while such a handler still owns real I/O.
        c=self._connection
        if not c._gate.acquire(blocking=False):return
        try:
            self._current()
            if sender._closed.is_set() or c._media_sender is not sender:
                raise TransferError('media_source_sender_retired')
            if c._preferences.read()!=self._preferences:
                raise TransferError('media_source_local_consent_required')
            binding=sender._binding
            if binding is None or c._controls.binding(binding.destination_token,sender_is_local=True)!=binding:
                raise TransferError('media_source_sender_binding_changed')
            self._current()
        finally:c._gate.release()

    def _archive(self,sender,record):
        from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupLocations
        from magnolie_media_source_backup import backup_prepared_source
        from magnolie_media_source_retirement import _NativeSourceRetirement
        from magnolie_media_source_roots import NativeMediaCollectionRootRecord
        c=self._connection;destination=record.directory if type(record) is NativeMediaCollectionRootRecord else record.destination
        scope=sha256(canonical(dict(subject=c._preferences._subject,media_type=self._kind))).hexdigest()
        with NativeMediaBackupLocations(c._authority.binding.native_directory,scope,self._current) as locations:
            selected=locations.read()
            if not selected.parents:selected=locations.choose(locations.issue_action(),selected,destination,None)
            storage=selected.current(destination)
            def current():
                self._current()
                if locations.read()!=selected:raise TransferError('media_backup_locations_changed')
                return True
            with NativeMediaBackups(destination,c._authority.protection,current,
                    create=not os.path.lexists(Path(storage.path)/'Backup'),storage_parent=storage) as backups:
                # The readback projection can appear before its socket handler
                # exits. Own the actual connection lane before touching cache
                # I/O; never treat that projection as source-END/drain.
                with c._operation(incoming=True):
                    version=backup_prepared_source(backups,sender._source,sender._job)
                retirement=_NativeSourceRetirement(sender,backups,version)
                while True:
                    self._current()
                    try:retirement.run();break
                    except TransferError as error:
                        if str(error)!='file_desktop_connection_busy':raise
                        with c._update_condition:c._update_condition.wait(.25)

    def _send_file(self,cache,record):
        c=self._connection
        sender=c.open_prepared_media_sender(cache.manifest.source_id);self._active_sender=sender
        sender.send_media_offer()
        while True:
            self._current();self._idle_sender_current(sender)
            observed=sender._record
            # Projection alone is never END; _archive joins actual independent
            # backup, exact protected exchange and native/socket drain.
            if observed is not None and observed.body['phase']=='peer_readback':break
            with c._update_condition:c._update_condition.wait(.25)
        self._archive(sender,record);self._active_sender=None
        with self._lock:self._saved+=1

    def _collection_files(self):
        c=self._connection
        for selected,member in self._collection.members():
            if self._collection.already_checked_mapping(selected,member):continue
            try:
                try:cache=c.prepare_worker_collection_media_source(self,self._preferences,selected,member)
                except TransferError as error:
                    if str(error)!='media_collection_existing_source_held':raise
                    cache=c.prepare_worker_collection_media_source(self,self._preferences,selected,member,completed_successor=True)
            except TransferError as error:
                if str(error)=='media_collection_latest_payload_already_sent':
                    with self._lock:self._known+=1
                    continue
                if str(error) in ('media_source_photo_metadata_required','media_collection_known_other_type'):
                    with self._lock:self._filtered+=1
                    continue
                raise
            self._send_file(cache,selected)
        self._collection.finish()

    def _run(self):
        c=self._connection
        try:
            self._preferences=c._preferences.read()
            self._token=c._media_transport.intent_for(self._kind,to_phone=True)
            if self._token is None:raise TransferError('media_source_current_intent_required')
            from magnolie_media_sync import effective
            mode=effective(self._token.body)['collection_mode']
            if mode not in ('phone_inventory','entire_collection'):
                raise TransferError('media_source_current_intent_required')
            if mode=='entire_collection' and self._automatic:
                # A manual composition proof is not native acceptance of an
                # unattended whole-collection export. Keep that gate explicit.
                raise TransferError('media_source_entire_collection_automatic_acceptance_required')
            with NativeMediaRetention(c._authority.binding.native_directory) as policy:
                self._book=policy.saved_book_version();self._deadline=time.monotonic()+policy.MAX_ACTIVE_COPY_SECONDS
            if self._book_fence is not None:
                version,started,deadline=self._book_fence
                if (version!=self._book or type(started) not in (int,float) or type(deadline) not in (int,float)
                        or not started<=time.monotonic()<deadline<=self._deadline):
                    raise TransferError('media_source_original_book_required')
                self._deadline=deadline
            self._current()
            # Outside the mapping lease: resolving controls consults the local
            # mapping availability and must not recursively acquire that lease.
            if c._controls.binding('0'*64,sender_is_local=True) is None:
                raise TransferError('media_source_current_send_control_required')
            if mode=='entire_collection':
                controls=c._controls
                with controls._gate:self._collection_control=(controls,controls._session_epoch,controls._remote.challenge)
                from magnolie_media_source_collection_pass import NativeCollectionPass
                self._collection=NativeCollectionPass(self)
            with self._lock:self._state='syncing'
            snapshot=None;cursor=None
            while True:
                self._current()
                snapshot,records,cursor=c._mappings.candidate_page(self._kind,after=cursor,expected=snapshot,limit=self.PAGE_SIZE)
                for record in records:
                    self._current()
                    if self._collection is not None and record.file_key in self._collection._mapped:
                        raise TransferError('media_collection_ambiguous_mapped_identity')
                    try:
                        selected=c.prepare_changed_media_source(c.issue_receive_action(),self._preferences,record.association,
                            record.protected_record_sha256,kind=self._kind,native_current=self._current,mapping_snapshot=snapshot)
                    except TransferError as error:
                        if self._collection is None or str(error)!='media_source_photo_metadata_required':raise
                        with self._lock:self._filtered+=1
                        continue
                    if selected.cache is None:
                        if self._collection is not None:self._collection.note_checked_mapping(selected.plan.observation)
                        with self._lock:self._known+=1
                        continue
                    self._send_file(selected.cache,record)
                    if self._collection is not None:self._collection.note_checked_mapping(selected.plan.observation)
                if cursor is None:break
            if self._collection is not None:self._collection_files()
            self._current()
            if c._mappings.read()!=snapshot:raise TransferError('photo_mappings_candidate_snapshot_changed')
            if c._preferences.read()!=self._preferences:raise TransferError('media_source_local_consent_required')
            with self._lock:self._state='complete'
        except Exception as error:
            with self._lock:self._state='stopped' if self._stop.is_set() else 'held';self._error=str(error)
        finally:
            # Cancellation narrows authority immediately, but never closes a
            # descriptor beneath actual source/socket I/O. Drain the native
            # connection lane before releasing this worker's ownership.
            self._ended.set()
            sender=self._active_sender
            if sender is not None:sender.close()
            try:
                if self._collection is not None:self._collection.close()
            except Exception as error:
                with self._lock:self._state='held';self._error=str(error)
            try:
                from magnolie_file_control import MAX_TTL_MS
                if not c._gate.acquire(timeout=MAX_TTL_MS/1000):raise TransferError('file_desktop_connection_busy')
                try:
                    if sender is not None and c._media_sender is sender:c._media_sender=None
                    if c._mapped_worker is self:c._mapped_worker=None
                finally:c._gate.release()
            except Exception as error:
                with self._lock:self._state='held';self._error=str(error)
            c._wake_album_worker()
            if c._closed.is_set():c._close_resources()
