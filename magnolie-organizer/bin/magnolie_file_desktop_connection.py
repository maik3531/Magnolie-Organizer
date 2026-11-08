"""Native desktop file controls and explicitly enabled photo workflows.

The receive data/UI/recovery union is not ready: every outgoing data grant stays
OFF by default, including when a protected enabled preference exists. Construction
does not send packets, create preferences or start a worker. Accepted controllers
may drive automatic runs only from protected explicit desktop mode consent.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import re
import threading
import time
import uuid
from cryptography.exceptions import InvalidTag

from magnolie_file_control import KIND, MAX_TTL_MS, FileControlPacket, NativeFileControlSession
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_file_sources import _body
import magnolie_file_sources as source_messages
from magnolie_file_media import parse_media_page, correlate_media_pages
from magnolie_file_media_history import NativeMediaHistory
from magnolie_file_transfer import TransferError
from magnolie_photo_schedule import PhotoSyncSchedule, NativePhotoSyncScope
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_offer import KIND as OFFER, validate_offer
from magnolie_file_chunk_message import RESULT as CHUNK
from magnolie_file_chunk_message import REQUEST as CHUNK_REQUEST
from magnolie_file_accept_message import KIND as ACCEPT
from magnolie_file_saved_message import KIND as SAVED
from magnolie_file_published_readback import KIND as PUBLISHED_READBACK
from magnolie_file_chunk_message import parse_chunk
from magnolie_file_receive import NativeFileReceiveOperation, NativeReceiveStartError
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_mappings import ProtectedPhotoMappings, PhotoMappingAssociation
from magnolie_photo_destination import NativePhotoDestinationController, NativePhotoDestinationAction
from magnolie_telefon import now_ms, canonical, strict_json, SecureChannel


def is_reserved_file_message(message):
    return isinstance(message, dict) and isinstance(message.get('kind'), str) and message['kind'].startswith('file_transfer.')


class NativeDesktopFileConnection:
    # Compiled native receivers, not consent or a file/OS grant. Optional package
    # composition still excludes them where unsupported. Explicit protected
    # choices/current ACKs remain mandatory; candidate native acceptance precedes
    # delivery and is not replaced by these implementation-availability flags.
    _data_handlers_ready = True
    _video_data_handlers_ready = True

    def __init__(self, authority, channel, *, released=lambda owner:None, activity_changed=None, status_changed=None,
                 native_wifi_current=lambda:False,native_metadata_current=lambda:False):
        if not callable(native_wifi_current) or not callable(native_metadata_current):raise TransferError('media_source_native_wifi_required')
        self._native_wifi_current=native_wifi_current
        self._native_metadata_current=native_metadata_current
        if (type(authority) is not NativeDesktopFileAuthority or channel is not authority.native_channel
                or not callable(getattr(channel, 'send', None)) or not callable(released)):
            raise TransferError('file_desktop_native_owner_required')
        if activity_changed is not None and not callable(activity_changed):
            raise TransferError('file_desktop_native_activity_callback_required')
        self._activity_changed = activity_changed
        if status_changed is not None and not callable(status_changed):
            raise TransferError('file_desktop_native_activity_callback_required')
        self._status_changed = status_changed
        self._desktop_session = None
        self._authority = authority
        self._channel = channel
        self._closed = threading.Event()
        self._released = released
        self._release_reported = False
        self._cleanup_error = None
        self._gate = threading.Lock()
        self._controls = None
        self._catalog = self._run = self._offer = self._mutation_action = None
        self._offer_binding = self._offer_policy_version = None
        self._source_pending = self._source_status = self._source_catalog = self._source_run = self._source_result = None
        self._source_albums = {}
        self._source_album_kind = None
        self._source_control_required = None
        self._source_offer = None
        self._source_media_pages = ()
        self._source_media_entries = None
        self._resume_lookup_selection = self._resume_history = None
        self._resume_source_id = None
        self._resume_ended_manifest = None
        self._receive_stop_gate = threading.Lock()
        self._receive_stop = None
        self._stopped_receive_run = None
        self._checkpoint_binding_owner = None
        self._resume_end_confirmation = self._resume_abandonment = None
        self._selected_preview = self._selected_source_id = None
        self._ended_batch = self._ended_batch_policy = None
        self._album_media_scope = None
        self._update_condition = threading.Condition()
        self._update_generation = 0
        self._album_worker = None
        self._mapped_worker = None
        self._catalog_expectation_uncertain = False
        self._preferences = ProtectedPhotoPreferences(authority)
        self._mappings = ProtectedPhotoMappings(authority)
        self._media_trash = None
        self._media_transport = self._media_source = self._media_sender = None
        self._media_sending_state = None
        self._media_sending_choice = None
        self._destination = NativePhotoDestinationController(authority)
        try:
            # Stable composition for this authenticated connection, never a bit
            # toggled by transient worker activity. Discovery23 stays closed.
            peers=strict_json(authority.protection.read_native_peers_blob())['items']
            peer=peers[0] if len(peers)==1 else {}
            status=peer.get('capabilities',{}).get('items',{}).get('device_status',{})
            if type(channel) is SecureChannel and status.get('available') is True and 23 in status.get('versions',[]):
                from magnolie_media_transport import NativeMediaSettingsTransport
                from magnolie_media_source import NativeMappedMediaSource
                self._media_transport=NativeMediaSettingsTransport(authority,
                    lambda:not self._closed.is_set() and self._media_source is not None and self._data_handlers_ready)
                self._media_source=NativeMappedMediaSource(self._preferences,self._mappings,self._media_transport)
            self._controls = NativeFileControlSession(authority.identity, self._peer, self._local)
        except BaseException:
            self.close()
            raise

    def _ready(self):
        if self._closed.is_set():
            raise TransferError('file_desktop_connection_closed')

    def _peer(self):
        self._ready()
        peer = self._authority.current_peer()
        self._ready()
        return peer.control_peer(self, ready=True, handlers_ready=True) if peer is not None else None

    def _local(self):
        self._ready()
        # Do not claim receiver readiness from preferences or control codecs.
        grant,snapshot=self._preferences.native_local_state(self._data_handlers_ready,source_handlers_ready=self._media_source is not None)
        consent=snapshot.policy.sending if snapshot.associated and snapshot.policy is not None else None
        if consent is not None and consent.pairing_epoch!=snapshot.policy.pairing_epoch:consent=None
        self._media_sending_state=dict(version=snapshot.version,photos=bool(consent is not None and consent.photos),
            videos=bool(consent is not None and consent.videos))
        if grant.grants.send_files or grant.grants.receive_files:
            witness=snapshot.policy.mapping_store
            if witness is not None:
                try:self._mappings.validate_availability(witness)
                except (TransferError,OSError,InvalidTag):return replace(grant,policy_ready=False)
            if snapshot.policy.job_catalog is not None:
                try:self._verify_catalog_witness(snapshot.policy.job_catalog)
                except (TransferError,OSError,InvalidTag):return replace(grant,policy_ready=False)
        self._ready()
        if self._authority.current_peer() is None:raise TransferError('file_desktop_native_authority_changed')
        return grant

    def _verify_catalog_witness(self,witness):
        if self._catalog_expectation_uncertain:raise TransferError('file_desktop_catalog_repair_pending')
        try:
            if self._catalog is not None:return self._catalog.verify_witness(witness)
            protection=self._authority.protection
            with ProtectedTransferJobCatalog(Path(self._authority.binding.native_directory),self._authority.identity,
                    protection.seal,protection.unseal,owner_only=True) as observer:
                return observer.verify_witness(witness)
        except Exception as error:
            if not isinstance(error,TransferError) or str(error)!='file_job_catalog_busy':self._catalog_expectation_uncertain=True
            raise

    @contextmanager
    def _operation(self, *, incoming=False):
        # The authenticated socket dispatcher is an I/O lane, not the UI. It
        # waits boundedly behind an actual outbound write so an immediate reply
        # is not discarded just because send() has not returned to its caller.
        acquired = self._gate.acquire(timeout=MAX_TTL_MS/1000) if incoming else self._gate.acquire(blocking=False)
        if not acquired:
            raise TransferError('file_desktop_connection_busy')
        try:
            self._ready()
            yield
        finally:
            self._gate.release()
            if self._closed.is_set():
                self._close_resources()
            else:
                run = self._run
                if run is not None and run.stop_requested.is_set():
                    self._finish_receive_stop()
            if incoming:
                self._wake_album_worker()

    def _wake_album_worker(self):
        with self._update_condition:
            self._update_generation += 1
            self._update_condition.notify_all()

    def start_album_worker(self, action, album_id, desktop_choice, *, activity_changed=None, media_type='images',book_fence=None):
        """Explicit native worker start; construction/import/pairing starts nothing."""
        self._take_action(action)
        with self._operation():
            snapshot = self._receiving_policy(); action.validate(self)
            source_messages._media_type(media_type)
            if (snapshot.direction != 'phone_to_desktop'
                    or snapshot.policy.phone_to_pc_delete or snapshot.policy.pc_to_phone_delete):
                raise TransferError('file_desktop_album_options_unavailable')
            if media_type == 'video':
                if not self._video_data_handlers_ready:
                    raise TransferError('file_desktop_video_data_join_unavailable')
                self._require_video_metadata_scope()
            if self._album_worker is not None or self._mapped_worker is not None or self._source_pending is not None or self._source_run is not None or self._run is not None:
                raise TransferError('file_desktop_album_worker_busy')
            if self._ended_batch is not None and self._ended_batch.batch_end is not True:
                raise TransferError('file_desktop_album_worker_busy')
            if (type(album_id) is not str or type(desktop_choice) is not bool or album_id not in self._source_albums
                    or self._source_catalog is None or self._source_catalog.media_type != media_type):
                raise TransferError('file_desktop_source_album_not_current')
            if activity_changed is not None and not callable(activity_changed):
                raise TransferError('file_desktop_native_activity_callback_required')
            worker = NativePhotoAlbumWorker(self, album_id, desktop_choice, activity_changed, media_type=media_type,book_fence=book_fence)
            self._album_worker = worker
        try:
            worker._thread.start() # Never race a first command against our held operation lock.
        except BaseException:
            with self._gate:
                if self._album_worker is worker: self._album_worker = None
            raise
        return worker

    def request_normal_receive_stop(self, action, *, finish=True):
        """Ordinary receiver stop with the same drain/checkpoint/actual-close
        requirements as resume. UI callers request only; the I/O worker finishes.
        """
        if type(finish) is not bool:
            raise TransferError('file_desktop_native_stop_choice_required')
        self._take_action(action)
        with self._receive_stop_gate:
            self._ready()
            run = self._run
            if (run is None or run.job is None or self._source_run is None or self._resume_source_id is not None):
                raise TransferError('file_desktop_normal_receiver_required')
            if not run.stop_requested.is_set():
                self._receive_stop = NativeReceiveStop(run.job.owner, self._source_run.run_id, 'pending')
                run.stop_requested.set()
        if finish: self._finish_receive_stop()
        self._wake_album_worker()
        return self.receive_stop_state()

    def receive_stop_state(self):
        """Nonblocking-I/O historical status, never a saved/repair/quota grant."""
        with self._receive_stop_gate:
            return self._receive_stop

    def request_receive_stop(self, action, *, finish=True):
        if type(finish) is not bool:raise TransferError('file_desktop_native_stop_choice_required')
        self._take_action(action)
        with self._receive_stop_gate:
            self._ready()
            run = self._run
            if (run is None or run.job is None or self._resume_source_id is None or self._source_run is None
                    or self._source_run.run_id != self._resume_source_id or self._resume_lookup_selection is None
                    or self._resume_lookup_selection.job.owner != run.job.owner):
                raise TransferError('file_desktop_resumed_receiver_required')
            if not run.stop_requested.is_set():
                self._receive_stop = NativeReceiveStop(run.job.owner, self._resume_source_id, 'pending')
                run.stop_requested.set()  # Never waits behind actual stage/socket I/O.
        if finish:self._finish_receive_stop()
        self._wake_album_worker()
        return self.receive_stop_state()

    def _finish_receive_stop(self):
        if not self._gate.acquire(blocking=False):
            return False
        try:
            with self._receive_stop_gate:
                run = self._run
                state = self._receive_stop
                if (self._closed.is_set() or run is None or state is None or not run.stop_requested.is_set()
                        or state.owner != run.job.owner or state.state != 'pending'):
                    return False
                if run.request is not None and run.request_output_started and not run.stop_barrier_confirmed:
                    return False  # Drain this known request or its ordered source-cancel barrier first.
            progress = None; failure = None; closed = False
            receiver = run.receiver
            if receiver is None:
                failure = TransferError('file_desktop_receive_repair_pending')
            else:
                already_closed = receiver._closed
                if run.media_type=='video':self._checkpoint_binding_owner=(run,threading.get_ident())
                try:
                    try:
                        self._receive_binding()
                        progress = receiver.checkpoint()  # Includes protected commit/readback.
                        if progress.checkpoint_verified_bytes != progress.verified_bytes:
                            raise TransferError('file_desktop_stop_checkpoint_not_proven')
                    except Exception as error:
                        failure = error
                    try:
                        receiver.close()  # Actual descriptors close after native I/O, index last.
                        closed = not already_closed  # A prior close no-op is not new cleanup proof.
                    except Exception as error:
                        self._cleanup_error = type(error).__name__
                        if failure is None: failure = error
                    try:
                        self._receive_binding()
                    except Exception as error:
                        if failure is None: failure = error
                finally:
                    self._checkpoint_binding_owner=None
                if not closed and failure is None:
                    failure = TransferError('file_desktop_stop_cleanup_not_proven')
            with self._receive_stop_gate:
                self._receive_stop = NativeReceiveStop(state.owner, state.source_run_id, 'stopped' if failure is None else 'failed',
                    io_ended=True, checkpoint_committed=progress is not None and progress.checkpoint_verified_bytes == progress.verified_bytes,
                    resources_closed=closed, verified_bytes=progress.verified_bytes if progress else None,
                    checkpoint_verified_bytes=progress.checkpoint_verified_bytes if progress else None,
                    checkpoint_cleanup_pending=progress.checkpoint_cleanup_pending if progress else None)
                if failure is None:
                    self._stopped_receive_run = run
                    self._run = None
                    self._offer = self._offer_binding = self._offer_policy_version = self._source_offer = None
            return failure is None
        finally:
            self._gate.release()

    def _send_controls(self, clock):
        if not self._controls.needs_packet:
            return False
        packet = self._controls.packet()
        at = clock()
        message = dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=KIND,
                       created_ms=at, expires_ms=at+MAX_TTL_MS, body=packet.wire())
        _body(message, KIND, clock())
        self._ready()
        if self._peer() is None:
            raise TransferError('file_desktop_native_authority_changed')
        _body(message, KIND, clock())
        self._channel.send(message)  # Actual secure output, not queue acceptance.
        self._ready()
        _body(message, KIND, clock())
        self._controls.mark_sent(packet)
        return True

    def send_controls(self, *, clock=now_ms):
        with self._operation():
            return self._send_controls(clock)

    def receive(self, message, *, clock=now_ms):
        if message.get('kind') in (ACCEPT,CHUNK_REQUEST,SAVED,PUBLISHED_READBACK):
            sender=self._media_sender
            if sender is None:raise TransferError('media_source_sender_actual_preparation_required')
            return sender.observe(self._channel,message)
        with self._operation(incoming=True):
            if self._media_transport is not None and message.get('kind')=='file_transfer.shared_settings':
                result=self._media_transport.observe(self._channel,message)
                self._shared_schedule_changed()
                return result
            if self._data_handlers_ready and message.get('kind') in (source_messages.RESULT, source_messages.CATALOG,
                    source_messages.PERMISSION_RESULT, source_messages.RUN_RESULT, source_messages.MEDIA, source_messages.RESUME, source_messages.ABANDONED):
                self._receive_source_result(message, clock)
                return
            if self._data_handlers_ready and message.get('kind') == OFFER:
                self._observe_offer(message, clock)
                return
            if self._data_handlers_ready and message.get('kind') == CHUNK:
                self._receive_chunk(message, clock)
                return
            # Unsupported/reserved data never falls through to personal staging.
            body = _body(message, KIND, clock())
            packet = FileControlPacket.parse(body)
            self._controls.observe_remote(packet, self._peer())
            self._send_controls(clock)
            self._shared_schedule_changed()

    def _shared_schedule_changed(self):
        transport=self._media_transport
        if transport is None:return
        # Refresh native consent on this serialized observer lane, not inside
        # a source/mapping callback and not from a passive UI status request.
        try:self._local()
        except (TransferError,OSError,InvalidTag):return
        if self._desktop_session is None and any(transport.intent_for(kind,to_phone=True) is not None for kind in ('images','video')):
            self._desktop_session=NativePhotoDesktopSession(self)
        if self._desktop_session is not None:self._desktop_session.shared_settings_changed()

    def receive_media_ack(self,message):
        transport=self._media_transport
        # Ownership hint only, never an ACK/grant decision: unrelated personal
        # ACKs must not wait behind a blocked file output. Recheck under locks.
        if transport is None or message.get('message_id') not in transport._attempts:return False
        with self._operation(incoming=True):
            with transport._gate:
                if message.get('message_id') not in transport._attempts:return False
                result=transport.observe(self._channel,message)
                self._shared_schedule_changed()
                return result

    def prepare_media_source(self,action,expected,association,record_sha256,*,kind='images'):
        self._take_action(action)
        with self._operation():
            if self._media_source is None:raise TransferError('media_source_native_composition_required')
            if self._album_worker is not None or self._run is not None or self._source_pending is not None:
                raise TransferError('file_desktop_album_worker_busy')
            return self._media_source.freeze(self._preferences.issue_action(),expected,association,record_sha256,kind=kind)

    def plan_media_source(self,action,expected,association,record_sha256,*,kind='images'):
        self._take_action(action)
        with self._operation():
            if self._media_source is None:raise TransferError('media_source_native_composition_required')
            if self._album_worker is not None or self._run is not None or self._source_pending is not None:
                raise TransferError('file_desktop_album_worker_busy')
            return self._media_source.plan(self._preferences.issue_action(),expected,association,record_sha256,kind=kind)

    def prepare_changed_media_source(self,action,expected,association,record_sha256,*,kind='images',native_current=None,mapping_snapshot=None):
        if native_current is not None and not callable(native_current):
            raise TransferError('media_source_native_operation_required')
        self._take_action(action)
        with self._operation():
            if self._media_source is None:raise TransferError('media_source_native_composition_required')
            if self._album_worker is not None or self._run is not None or self._source_pending is not None or self._media_sender is not None:
                raise TransferError('file_desktop_album_worker_busy')
            def agreed():
                if native_current is not None and native_current() is not True:
                    raise TransferError('media_source_native_operation_ended')
                if self._controls.binding('0'*64,sender_is_local=True) is None:
                    raise TransferError('media_source_current_send_control_required')
            agreed()
            plan=self._media_source.plan(self._preferences.issue_action(),expected,association,record_sha256,kind=kind,
                native_current=native_current,mapping_snapshot=mapping_snapshot)
            agreed()
            cache=None
            if plan.changed:
                cache=self._media_source.freeze_observed(self._preferences.issue_action(),expected,association,
                    record_sha256,plan.observation,kind=kind,catalog_version=plan.catalog_version,
                    native_current=native_current,mapping_snapshot=mapping_snapshot)
            from magnolie_media_source_planning import NativeMediaSourcePreparation
            return NativeMediaSourcePreparation(plan,cache)

    def start_mapped_media_worker(self,action,*,kind='images',book_fence=None,automatic=False):
        self._take_action(action)
        with self._operation():
            if self._media_source is None:raise TransferError('media_source_native_composition_required')
            if (self._mapped_worker is not None or self._album_worker is not None or self._run is not None
                    or self._source_pending is not None or self._source_run is not None or self._media_sender is not None):
                raise TransferError('file_desktop_album_worker_busy')
            from magnolie_media_source_worker import NativeMappedMediaWorker
            worker=NativeMappedMediaWorker(self,kind,book_fence,automatic=automatic);self._mapped_worker=worker
            try:worker.start()
            except BaseException:self._mapped_worker=None;raise
            return worker

    def open_prepared_media_sender(self,job_id):
        with self._operation():
            if self._media_source is None or self._media_sender is not None:
                raise TransferError('media_source_sender_original_connection_required')
            from magnolie_media_source_sender import _NativeMediaSourceSender
            sender=_NativeMediaSourceSender(self._media_source,job_id,_connection=self)
            self._media_sender=sender
            return sender

    def issue_receive_action(self):
        self._ready()
        return NativePhotoDestinationAction(self, lambda: time.monotonic_ns()//1_000_000)

    def source_state(self):
        """Native UI metadata only; no serialized status/album grants OS READ."""
        with self._operation():
            return dict(status=self._source_status, catalog=self._source_catalog, albums=tuple(self._source_albums.values()),
                         run=self._source_run, result=self._source_result, pending=self._source_pending is not None,
                         media_pages=self._source_media_pages, media_manifest_correlated=self._source_media_entries is not None,
                          resume_history=self._resume_history)

    def desktop_session(self):
        if self._desktop_session is not None:return self._desktop_session
        with self._operation():
            if self._desktop_session is None:self._desktop_session=NativePhotoDesktopSession(self)
            return self._desktop_session

    def desktop_snapshot(self):
        session=self._desktop_session
        value=session.snapshot() if session is not None else dict(available=True,state='off',enabled=False,mode='manual',albums=[])
        if self._media_source is not None and self._media_sending_state is not None:
            value['sending_consent']=dict(self._media_sending_state) # Memory only: report may own the service monitor.
            transport=self._media_transport
            token=next((intent for kind,field in (('images','photos'),('video','videos'))
                if self._media_sending_state.get(field) is True
                and (kind!='video' or self._video_data_handlers_ready)
                and (intent:=transport.intent_for(kind,to_phone=True)) is not None),None) if transport is not None else None
            value['mapped_outgoing']=token is not None
            if token is not None:
                from magnolie_media_sync import effective
                value['mapped_direction']=effective(token.body)['direction']
        if self._media_source is not None and self._media_transport is not None:
            shared=self._media_transport.display_snapshot()
            if shared is not None:value['shared_media']=shared
        return value

    def native_shared_media_setting(self,field,value,version):
        from hashlib import sha256
        from magnolie_file_control import _hex
        from magnolie_media_retention import NativeMediaRetention
        import magnolie_media_sync as media
        if type(field) is not str or type(value) not in (bool,str) or not _hex(version):
            raise TransferError('media_settings_native_choice_invalid')
        with self._operation():
            transport=self._media_transport
            if self._media_source is None or transport is None:raise TransferError('media_source_native_composition_required')
            def current():
                self._ready()
                if self._native_metadata_current() is not True:raise TransferError('media_source_current_metadata_required')
                return True
            with NativeMediaRetention(self._authority.binding.native_directory) as retention:
                # Shared registers live in phone.db too. A maintenance writer
                # lease here would block our separate metadata transaction.
                # Only a revalidated saved-book observation is needed; no
                # destructive maintenance or file publication is performed.
                with retention.active_copy_permit(current) as permit:
                    if permit is None:raise TransferError('media_settings_saved_book_required')
                    body=transport._store.read()
                    if sha256(canonical(body)).hexdigest()!=version:raise TransferError('media_settings_native_choice_changed')
                    # Validate on a pure projection before touching the actual
                    # registers or invalidating any current agreement.
                    local=self._authority.identity.receiver_id;peer=self._authority.binding.peer_id
                    media.change(body if body is not None else media.create(local),local,peer,field,value)
                    permit.require_current();current()
                    transport.change(field,value);transport.send_settings()
                    self._shared_schedule_changed()
                    permit.require_current();current()
            return self.desktop_snapshot()

    def native_sending_consent(self,operation,*,photos=None,videos=None,selection=None,version=None):
        """Two-phase private native dialog choice; never a wire/browser approval.

        The one-use ticket belongs to this exact connection, saved book, policy,
        desired type choices and a bounded monotonic lifetime. No file is opened
        and no worker is started by preparing or confirming local rights.
        """
        from magnolie_file_control import _hex
        from hashlib import sha256
        from magnolie_media_retention import NativeMediaRetention
        if (operation not in ('prepare','commit','cancel') or
                (type(photos) is not bool or type(videos) is not bool or selection is not None or not _hex(version) if operation=='prepare'
                 else not _hex(selection) or photos is not None or videos is not None or version is not None)):
            raise TransferError('media_sending_native_choice_invalid')
        with self._operation():
            if self._media_source is None:raise TransferError('media_source_native_composition_required')
            if operation=='cancel':
                choice=self._media_sending_choice
                if choice is None or choice[0]!=selection:raise TransferError('media_sending_native_choice_changed')
                self._media_sending_choice=None
                return dict(canceled=True)
            expected=self._preferences.read()
            if operation=='prepare' and expected.version!=version:raise TransferError('media_sending_native_choice_changed')
            def current():self._ready();return True
            with NativeMediaRetention(self._authority.binding.native_directory) as retention:
                with retention.permit(current) as permit:
                    if permit is None:raise TransferError('media_sending_saved_book_required')
                    book_version=sha256(canonical(retention._read())).hexdigest()
                    if operation=='prepare':
                        ticket=uuid.uuid4().hex+uuid.uuid4().hex
                        self._media_sending_choice=(ticket,time.monotonic()+60,expected,book_version,photos,videos)
                        consent=expected.policy.sending if expected.associated and expected.policy is not None else None
                        if consent is not None and consent.pairing_epoch!=expected.policy.pairing_epoch:consent=None
                        return dict(selection=ticket,version=expected.version,photos=photos,videos=videos,
                            current_photos=bool(consent is not None and consent.photos),current_videos=bool(consent is not None and consent.videos),
                            display_name=self._authority.current_peer().display_name)
                    choice=self._media_sending_choice
                    if choice is None or choice[0]!=selection:raise TransferError('media_sending_native_choice_changed')
                    self._media_sending_choice=None
                    if (time.monotonic()>=choice[1] or expected!=choice[2] or book_version!=choice[3]):
                        raise TransferError('media_sending_native_choice_changed')
                    permit.require_current();self._ready()
                    result=self._preferences.configure_sending(self._preferences.issue_action(),expected,photos=choice[4],videos=choice[5])
                    permit.require_current();self._ready()
                    if self._preferences.read()!=result:raise TransferError('media_sending_native_choice_changed')
                    self._send_controls(now_ms)
                    return dict(version=result.version,photos=choice[4],videos=choice[5])

    def native_backup_locations(self,media_type,*,operation='read',version=None,book_version=None,native_path=None):
        """Private native picker/preflight API; never a source-wire command.

        The preflight returns an opaque saved-book witness as well as selection
        CAS. A delayed folder dialog cannot apply a choice to another saved book.
        No peer file permission or synchronization action is produced here.
        """
        from hashlib import sha256
        from magnolie_media_backups import NativeMediaBackupLocations
        from magnolie_media_retention import NativeMediaRetention
        from magnolie_file_acceptance import NativeAcceptedDestination
        from magnolie_file_control import _hex
        if (media_type not in ('images','video') or operation not in ('read','choose','default')
                or (operation=='choose')!=(native_path is not None)
                or native_path is not None and (type(native_path) is not str or not native_path or len(native_path)>4096)
                or operation=='read' and (version is not None or book_version is not None)
                or operation!='read' and (not _hex(version) or not _hex(book_version))):
            raise TransferError('media_backup_native_request_invalid')
        with self._operation():
            expected=self._preferences.read();policy=expected.policy
            destination=(policy.destination if media_type=='images' else policy.videos.destination if policy.videos is not None else None) if policy else None
            if destination is None:raise TransferError('media_backup_default_required')
            directory=self._authority.binding.native_directory
            scope=sha256(canonical(dict(subject=self._preferences._subject,media_type=media_type))).hexdigest()
            def current():
                self._ready()
                if self._authority.current_peer() is None or self._preferences.read()!=expected:
                    raise TransferError('media_backup_native_owner_changed')
                return True
            with NativeMediaRetention(directory) as retention:
                with retention.permit(current) as permit:
                    if permit is None:raise TransferError('media_backup_current_saved_book_required')
                    saved=sha256(canonical(retention._read())).hexdigest()
                    if operation!='read' and book_version!=saved:raise TransferError('media_backup_saved_book_changed')
                    def owned():
                        current();permit.require_current();return True
                    with NativeMediaBackupLocations(directory,scope,owned) as locations:
                        snapshot=locations.read()
                        if operation!='read':
                            if self._album_worker is not None or self.desktop_snapshot().get('busy'):
                                raise TransferError('media_backup_native_worker_busy')
                            if snapshot.version!=version:raise TransferError('media_backup_locations_cas_conflict')
                            parent=NativeAcceptedDestination.capture(native_path) if operation=='choose' else None
                            snapshot=locations.choose(locations.issue_action(),snapshot,destination,parent)
                        owned()
                        return dict(version=snapshot.version,book_version=saved,is_default=snapshot.selected is None,
                            current_path=str(Path(snapshot.current(destination).path)/'Backup'),
                            sources=[dict(id=source_id,path=str(Path(parent.path)/'Backup')) for source_id,parent in locations.sources(destination)])

    def _source_command_authority(self, pending, clock):
        closing=pending.command.operation in ('run_status','cancel_run','end_run','end_album','resume_status','cancel_resume','end_resume')
        self._receiving_policy(closing=closing)
        if pending.command.media_type=='video' and closing:
            owner=self._ended_batch if pending.command.operation=='end_album' else self._source_run
            if owner is None or owner.run_id!=pending.command.run_id or owner.media_type!='video':
                raise TransferError('file_desktop_video_source_owner_changed')
        elif (pending.command.media_type=='video' or pending.command.operation=='configure_videos' and pending.command.enabled):
            if (pending.command.media_type=='video' and pending.command.operation not in ('discover','catalog_page','request_read')
                    and not self._video_data_handlers_ready):
                raise TransferError('file_desktop_video_data_join_unavailable')
            scope=self._require_video_metadata_scope()
            if scope.version!=pending.video_policy_version:raise TransferError('file_desktop_video_policy_changed')
        if not self._controls.receiver_command_current(pending.ticket):
            raise TransferError('file_desktop_source_command_authority_changed')
        _body(pending.message, source_messages.REQUEST, clock())
        if pending.command.operation == 'resume_lookup':
            self._require_resume_lookup_selection()
        elif pending.command.operation == 'abandon_resume':
            self._require_resume_abandonment_intent()
        elif pending.command.operation == 'select_run':
            selected = self._selected_preview
            if (selected is None or self._source_run is None or self._source_run.run_id != selected.source_run_id
                    or self._selected_source_id is not None or self._offer is None
                    or pending.command.selection_manifest_sha256 != selected.manifest.fingerprint
                    or pending.command.selected_file_ids != selected.file_ids
                    or self._mappings.read() != selected.mapping_snapshot):
                raise TransferError('file_desktop_photo_selection_not_current')
        elif pending.command.operation in ('next_batch', 'end_album'):
            ended = self._require_ended_batch(require_more=pending.command.operation == 'next_batch')
            if pending.command.run_id != ended.run_id or pending.command.expected_version != ended.version:
                raise TransferError('file_desktop_batch_continuation_not_current')
        elif pending.command.operation in ('resume_run', 'resume_status', 'cancel_resume', 'offer_resume', 'resume_media_page', 'end_resume'):
            ending=pending.command.operation in ('cancel_resume','resume_status','end_resume')
            self._require_resume_lookup_selection(allow_source_run=True,
                allow_stopping_receiver=pending.command.operation in ('cancel_resume','resume_status'),allow_saved_receiver=ending,closing=ending)

    def _require_video_metadata_scope(self):
        if not self._authority.video_available():raise TransferError('file_desktop_video_metadata_unavailable')
        scope=self._preferences.read()
        if not scope.include_videos:raise TransferError('file_desktop_video_consent_unavailable')
        scope.policy.videos.destination.verify()
        if not self._authority.video_available():raise TransferError('file_desktop_video_metadata_unavailable')
        return scope

    def _video_resume_closing_scope(self,selected):
        # Configuration-only comparison. Never install this as a data callback
        # or widen the separately owned checkpoint/close stack authority.
        snapshot=self._receiving_policy(closing=True);policy=snapshot.policy
        if (policy.videos is None or policy.videos.destination!=selected.job.accepted.destination
                or self._source_run is None or self._source_run.media_type!='video'
                or self._source_run.run_id!=self._resume_source_id):
            raise TransferError('file_desktop_video_resume_closing_scope_changed')
        binding=self._controls.binding(policy.videos.destination_token)
        if binding is None or binding!=selected.job.accepted.binding:
            raise TransferError('file_desktop_video_resume_closing_scope_changed')
        policy.videos.destination.verify()
        if self._preferences.read()!=snapshot or self._controls.binding(policy.videos.destination_token)!=binding:
            raise TransferError('file_desktop_video_resume_closing_scope_changed')
        return snapshot,policy.videos.destination,binding

    def _require_resume_lookup_selection(self, *, allow_source_run=False, allow_stopping_receiver=False, allow_saved_receiver=False,closing=False):
        selected = self._resume_lookup_selection
        video_closing=closing and selected is not None and selected.media_type=='video'
        if video_closing:snapshot,destination,binding=self._video_resume_closing_scope(selected)
        else:
            snapshot = self._receiving_policy()
            destination=self._receive_destination(snapshot,media_type=selected.media_type) if selected is not None else None
            binding=self._receive_binding() if selected is not None else None
        receiver = self._run
        stopping = (allow_stopping_receiver and receiver is not None and receiver.stop_requested.is_set()
                     and selected is not None and receiver.job == selected.job)
        saved=False
        if (allow_saved_receiver and receiver is not None and selected is not None and receiver.job==selected.job
                and receiver.saved_mapping_ready and receiver.request is None and receiver.receiver is not None):
            native=receiver.receiver
            if video_closing:
                if native._closed or native._failed:raise TransferError('file_desktop_video_resume_saved_owner_changed')
                native._index._require_end_worker(native._lease)
            else:native._require();native._index._require_receipt_worker(native._lease)
            saved=native._phase=='saved_locally' and native._index.saved_mapping_receipt() is not None
        if (selected is None or not video_closing and snapshot.version != selected.policy_version or receiver is not None and not (stopping or saved)
                or self._source_run is not None and (not allow_source_run or self._source_run.run_id != self._resume_source_id)
                or (self._source_run is None) != (self._resume_source_id is None)
                or self._source_status is None or self._source_status.version != selected.source_version
                or binding != selected.job.accepted.binding or destination != selected.job.accepted.destination
                or (self._catalog is None if video_closing else not self._open_catalog(allow_create=False))):
            raise TransferError('file_desktop_resume_lookup_not_current')
        current = next((job for job in self._catalog.jobs() if job.owner == selected.job.owner), None)
        if current != selected.job:
            raise TransferError('file_desktop_resume_original_job_changed')
        if not video_closing:selected.job.accepted.verify(self._receive_binding)
        return selected

    def request_resume_lookup(self, action, native_job_owner, *, media_type='images', clock=now_ms):
        """Explicit protected original-job selection; history is not a run grant."""
        self._take_action(action)
        source_messages._media_type(media_type)
        with self._operation():
            snapshot = self._receiving_policy()
            if self._source_pending is not None or self._run is not None or self._source_run is not None or self._offer is not None:
                raise TransferError('file_desktop_receive_run_held')
            if (self._source_status is None or self._source_status.repair_pending or not self._source_status.enabled
                    or not self._source_status.associated):
                raise TransferError('file_desktop_source_status_required')
            if self._source_control_required is not None:
                witness = self._controls.remote_control_witness(); required = self._source_control_required
                if witness is None or witness[0] != required[0] or witness[1] <= required[1]:
                    raise TransferError('file_desktop_source_controls_pending')
            if not self._open_catalog(allow_create=False):
                raise TransferError('file_desktop_resume_unavailable')
            job = next((job for job in self._catalog.jobs() if job.owner == native_job_owner), None)
            if job is None:
                raise TransferError('file_desktop_resume_original_job_changed')
            if media_type=='video':
                if self._source_status.videos is None or not self._source_status.videos.enabled:
                    raise TransferError('file_desktop_video_source_not_configured')
                destination=self._receive_destination(snapshot,media_type='video')
                binding=self._receive_binding(media_type='video')
                if job.accepted.binding!=binding or job.accepted.destination!=destination:
                    raise TransferError('file_desktop_video_resume_original_scope_changed')
                # Inert protected metadata identifies the explicit original
                # selection; it cannot supply an old READ/source epoch grant.
                protection=self._authority.protection
                with self._catalog.inspect_jobs() as (parent,jobs):
                    if job not in jobs:raise TransferError('file_desktop_resume_original_job_changed')
                    with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,lambda:None,
                            protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                        history=index.media_history
                        if history is None or history.media_type!='video':
                            raise TransferError('file_desktop_video_resume_original_media_required')
                if self._preferences.read()!=snapshot:raise TransferError('file_desktop_video_policy_changed')
            self._resume_lookup_selection = _NativeDesktopResumeLookup(job, snapshot.version, self._source_status.version,media_type)
            self._resume_history = None
            self._resume_abandonment = None
            self._require_resume_lookup_selection(); action.validate(self)
            manifest = job.accepted.manifest
            message = source_messages.create_command('resume_lookup', expected_version=self._source_status.version,
                source_id=manifest.source_id, transfer_id=manifest.transfer_id, manifest_sha256=manifest.fingerprint,
                media_type='video' if media_type=='video' else None,now=clock())
            command = source_messages.parse_command(message, now=clock())
            ticket = self._controls.receiver_command_ticket()
            self._source_pending = _NativeDesktopSourceCommand(ticket, message, command, self._controls.receiver_command_witness(ticket),
                video_policy_version=snapshot.version if media_type=='video' else None)
            self._source_control_required = None
            self._send_source_pending(clock, action)
            return message['message_id']

    def _require_resume_abandonment_intent(self):
        selected = self._require_resume_lookup_selection()
        state = self.receive_stop_state()
        stopped = self._stopped_receive_run
        ended = self._resume_end_confirmation
        history = self._resume_history
        if (state is None or state.state != 'stopped' or not state.io_ended or not state.checkpoint_committed
                or not state.resources_closed or stopped is None or stopped.job != selected.job
                or state.owner != selected.job.owner or stopped.receiver is None or not stopped.receiver._closed
                or ended is None or ended[0] != selected.job or not ended[1].run_ended
                or ended[1].run_id != state.source_run_id or history is None or history.phase != 'sealed'
                or history.remote_saved_history or history.attempt_phase is None
                or history.attempt_id is None or history.attempt_sha256 is None):
            raise TransferError('file_desktop_resume_abandonment_proof_required')
        protection = self._authority.protection
        original = NativeFileReceiveOperation.read_media_history(self._catalog, selected.job,
            self._receive_binding, protection.seal, protection.unseal)
        if original is None: raise TransferError('file_desktop_resume_media_history_required')
        self._verify_job_mapping_store(original)
        return selected, history, state

    def request_resume_abandonment(self, action, *, clock=now_ms):
        """Explicit current native intent; wire/history tokens alone cannot call it."""
        self._take_action(action)
        with self._operation():
            if self._source_pending is not None or self._offer is not None:
                raise TransferError('file_desktop_receive_run_held')
            selected, history, state = self._require_resume_abandonment_intent()
            action.validate(self)
            message = source_messages.create_command('abandon_resume', expected_version=self._source_status.version,
                run_id=state.source_run_id, original_job_id=history.job_id, original_job_version=history.job_version,
                attempt_id=history.attempt_id, attempt_sha256=history.attempt_sha256,
                media_type='video' if selected.media_type=='video' else None,now=clock())
            command = source_messages.parse_command(message, now=clock())
            ticket = self._controls.receiver_command_ticket()
            self._source_pending = _NativeDesktopSourceCommand(ticket, message, command, self._controls.receiver_command_witness(ticket),
                video_policy_version=selected.policy_version if selected.media_type=='video' else None)
            self._send_source_pending(clock, action)
            return message['message_id']

    def _send_source_pending(self, clock, action=None):
        pending = self._source_pending
        if pending is None:
            raise TransferError('file_desktop_source_command_not_current')
        self._source_command_authority(pending, clock)
        if action is not None:
            action.validate(self)
        self._channel.send(pending.message)
        self._source_command_authority(pending, clock)
        if action is not None:
            action.validate(self)
        pending.sent = True

    def _require_ended_batch(self, *, require_more=True):
        ended = self._ended_batch
        policy = self._receiving_policy()
        if (ended is None or not ended.batched or (ended.batch_end is not False if require_more else ended.batch_end is True)
                or ended.state != 'canceled_held'
                or not ended.source_io_ended or self._run is not None or self._source_run is not None
                or self._selected_preview is not None or self._source_status is None
                or not self._source_status.enabled or not self._source_status.associated
                or self._source_status.version != ended.version or policy.version != self._ended_batch_policy):
            raise TransferError('file_desktop_batch_continuation_not_current')
        return ended

    def request_source(self, action, operation, *, enabled=None, kinds=(), album_id=None, desktop_choice=None,
            media_type=None, clock=now_ms):
        """One explicit native source command, not a personal queue or scheduler.
        Native receive consent/actual control echo may bootstrap source send-OFF.
        Exact remote catalog selections remain metadata, never an Android read grant.
        """
        self._take_action(action)
        if type(operation) is not str:raise TransferError('file_desktop_source_invalid_options')
        with self._operation():
            self._receiving_policy(closing=operation in ('run_status','cancel_run','end_run','end_album','resume_status','cancel_resume','end_resume'))
            if self._source_pending is not None:
                raise TransferError('file_desktop_source_command_busy')
            if self._source_control_required is not None:
                witness = self._controls.remote_control_witness()
                required = self._source_control_required
                if witness is None or witness[0] != required[0] or witness[1] <= required[1]:
                    raise TransferError('file_desktop_source_controls_pending')
            options = {}
            follow=('run_status','cancel_run','offer_run','media_page','end_run','resume_status','cancel_resume','offer_resume','resume_media_page','end_resume')
            owner=self._source_run if operation in follow else self._ended_batch if operation in ('next_batch','end_album') else None
            if owner is not None:
                if media_type is not None and media_type!=owner.media_type:
                    raise TransferError('file_desktop_source_media_scope_changed')
                if owner.media_type=='video':media_type='video'
            if operation=='resume_run' and self._resume_lookup_selection is not None:
                selected_media=self._resume_lookup_selection.media_type
                if media_type is not None and media_type!=selected_media:raise TransferError('file_desktop_source_media_scope_changed')
                if selected_media=='video':media_type='video'
            if media_type is not None:
                source_messages._media_type(media_type)
                if operation not in source_messages.SCOPED_OPERATIONS:
                    raise TransferError('file_desktop_source_invalid_options')
                if media_type=='video' and operation not in ('discover','catalog_page','request_read'):
                    closing=operation in ('run_status','cancel_run','end_run','end_album','resume_status','cancel_resume','end_resume') and owner is not None
                    if (operation not in ('run','batch_run','next_batch','run_status','cancel_run','offer_run','media_page','end_run','end_album',
                            'resume_run','resume_status','cancel_resume','offer_resume','resume_media_page','end_resume')
                            or not closing and not self._video_data_handlers_ready):
                        raise TransferError('file_desktop_video_data_join_unavailable')
                options['media_type']=media_type
            if operation != 'status':
                if self._source_status is None or self._source_status.repair_pending:
                    raise TransferError('file_desktop_source_status_required')
                options['expected_version'] = self._source_status.version
            if operation not in ('configure','configure_videos') and (enabled is not None or kinds != ()):
                raise TransferError('file_desktop_source_invalid_options')
            if operation not in ('run', 'batch_run', 'resume_run') and (album_id is not None or desktop_choice is not None):
                raise TransferError('file_desktop_source_invalid_options')
            if operation == 'configure_videos':
                if (self._album_worker is not None or self._run is not None or self._source_run is not None or self._ended_batch is not None
                        and self._ended_batch.batch_end is not True):
                    raise TransferError('file_desktop_receive_run_held')
                if kinds!=():raise TransferError('file_desktop_source_invalid_options')
                options['enabled']=enabled
            elif operation == 'configure':
                if self._run is not None or self._source_run is not None:
                    raise TransferError('file_desktop_receive_run_held')
                options.update(enabled=enabled, kinds=kinds)
            elif operation in ('next_batch', 'end_album'):
                options['run_id'] = self._require_ended_batch(require_more=operation == 'next_batch').run_id
            elif operation in ('discover', 'request_read', 'run', 'batch_run', 'resume_run', 'catalog_page'):
                if not self._source_status.enabled or not self._source_status.associated:
                    raise TransferError('file_desktop_source_not_configured')
                requested=media_type or 'images'
                if requested=='video' and (self._source_status.videos is None or not self._source_status.videos.enabled):
                    raise TransferError('file_desktop_video_source_not_configured')
                if operation == 'catalog_page':
                    if (self._source_catalog is None or self._source_catalog.next_cursor is None
                            or self._source_catalog.media_type!=requested):
                        raise TransferError('file_desktop_source_catalog_not_current')
                    options.update(catalog_id=self._source_catalog.catalog_id, after=self._source_catalog.next_cursor)
                elif operation in ('run', 'batch_run', 'resume_run'):
                    if self._run is not None or self._source_run is not None:
                        raise TransferError('file_desktop_receive_run_held')
                    album = self._source_albums.get(album_id)
                    if (album is None or self._source_catalog is None or self._source_catalog.media_type!=requested or type(desktop_choice) is not bool
                            or album.needs_choice and not desktop_choice):
                        raise TransferError('file_desktop_source_album_not_current')
                    options.update(catalog_id=self._source_catalog.catalog_id, album_id=album.album_id, desktop_choice=desktop_choice)
                    if operation == 'resume_run':
                        selected = self._require_resume_lookup_selection()
                        history = self._resume_history
                        repaired = (self._resume_abandonment is not None and history is not None
                            and self._resume_abandonment.job_id == history.job_id and self._resume_abandonment.job_version == history.job_version
                            and self._resume_abandonment.attempt_id == history.attempt_id and self._resume_abandonment.attempt_sha256 == history.attempt_sha256)
                        if history is None or history.phase != 'sealed' or history.remote_saved_history or history.attempt_phase is not None and not repaired:
                            raise TransferError('file_desktop_resume_history_requires_reconcile')
                        protection = self._authority.protection
                        original = NativeFileReceiveOperation.read_media_history(self._catalog, selected.job,
                            self._receive_binding, protection.seal, protection.unseal)
                        if original is None:
                            raise TransferError('file_desktop_resume_media_history_required')
                        self._verify_job_mapping_store(original)
                        options.update(original_job_id=history.job_id, original_job_version=history.job_version)
                        self._source_media_pages = (); self._source_media_entries = None; self._source_offer = None
            elif operation in ('run_status', 'cancel_run', 'offer_run', 'media_page', 'end_run', 'resume_status', 'cancel_resume', 'offer_resume', 'resume_media_page', 'end_resume'):
                if self._source_run is None:
                    raise TransferError('file_desktop_source_run_not_current')
                resumed = operation in ('resume_status', 'cancel_resume', 'offer_resume', 'resume_media_page', 'end_resume')
                if resumed != (self._resume_source_id is not None and self._source_run.run_id == self._resume_source_id):
                    raise TransferError('file_desktop_resume_source_owner_changed')
                if resumed:
                    ending=operation in ('cancel_resume','resume_status','end_resume')
                    self._require_resume_lookup_selection(allow_source_run=True,
                        allow_stopping_receiver=operation in ('cancel_resume','resume_status'),allow_saved_receiver=ending,closing=ending)
                stopped = self._receive_stop
                if (resumed and stopped is not None and stopped.source_run_id == self._resume_source_id
                        and operation in ('offer_resume', 'resume_media_page')):
                    raise TransferError('file_desktop_receive_stop_requested')
                if operation == 'end_resume' and (self._source_run.state != 'canceled_held' or not self._source_run.source_io_ended):
                    raise TransferError('file_desktop_resume_source_io_pending')
                if operation == 'end_run' and (self._run is not None or self._source_run.state != 'canceled_held'
                        or not self._source_run.source_io_ended):
                    raise TransferError('file_desktop_source_io_pending')
                if operation in ('offer_run', 'media_page', 'offer_resume', 'resume_media_page') and (self._run is not None or self._offer is not None
                        or self._source_run.state != 'snapshot_ready' or not self._source_run.source_io_ended
                        or self._source_run.version != self._source_status.version
                        or not self._source_status.enabled or not self._source_status.associated):
                    raise TransferError('file_desktop_source_offer_not_ready')
                if operation in ('media_page', 'resume_media_page'):
                    after = self._source_media_pages[-1].next_cursor if self._source_media_pages else 0
                    if after is None:
                        raise TransferError('file_desktop_source_media_pages_complete')
                    options['after'] = after
                elif operation in ('offer_run', 'offer_resume') and self._source_media_pages and self._source_media_pages[-1].next_cursor is not None:
                    raise TransferError('file_desktop_source_media_pages_incomplete')
                if operation == 'offer_resume' and not self._source_media_pages:
                    raise TransferError('file_desktop_resume_media_history_required')
                options['run_id'] = self._source_run.run_id
            message = source_messages.create_command(operation, now=clock(), **options)
            command = source_messages.parse_command(message, now=clock())
            video_policy_version=None
            if (command.media_type=='video' and operation not in ('run_status','cancel_run','end_run','end_album','resume_status','cancel_resume','end_resume')
                    or operation=='configure_videos' and command.enabled):
                video_policy_version=self._require_video_metadata_scope().version
            ticket = self._controls.receiver_command_ticket()
            self._source_pending = _NativeDesktopSourceCommand(ticket, message, command, self._controls.receiver_command_witness(ticket),
                album_kind=album.kind if operation in ('run','batch_run','resume_run') else None,
                video_negotiated=self._authority.video_available(),video_policy_version=video_policy_version)
            self._source_control_required = None
            self._send_source_pending(clock, action)
            return message['message_id']

    def retry_source_command(self, *, clock=now_ms):
        with self._operation():
            self._send_source_pending(clock)

    def _receive_source_result(self, message, clock):
        pending = self._source_pending
        if pending is None or not pending.sent:
            raise TransferError('file_desktop_source_result_not_requested')
        self._source_command_authority(pending, clock)
        command = pending.command
        at = clock()
        if command.operation in ('status', 'configure', 'configure_videos'):
            result = source_messages.parse_result(message, expected_request_id=command.request_id,
                expected_operation=command.operation,
                expect_videos=pending.video_negotiated and self._authority.video_available(),now=at)
            old = self._source_status
            if old is not None and (result.revision < old.revision or result.revision == old.revision
                    and (result.version, result.enabled, result.associated, result.kinds) != (old.version, old.enabled, old.associated, old.kinds)
                    or old.videos is not None and result.videos is not None and (result.videos.revision<old.videos.revision
                        or result.revision==old.revision and result.videos!=old.videos
                        or result.videos.revision==old.videos.revision and result.videos!=old.videos)):
                raise TransferError('file_desktop_source_status_rollback')
        elif command.operation in ('discover', 'catalog_page'):
            result = source_messages.parse_catalog(message, expected_request_id=command.request_id, expected_operation=command.operation,
                expected_version=command.expected_version, expected_catalog_id=command.catalog_id, expected_after=command.after,
                expected_media_type=command.media_type,now=at)
            if command.operation == 'catalog_page' and any(album.album_id in self._source_albums for album in result.albums):
                raise TransferError('file_desktop_source_duplicate_album')
        elif command.operation == 'request_read':
            result = source_messages.parse_permission_result(message, expected_request_id=command.request_id,
                expected_version=command.expected_version, expected_media_type=command.media_type,now=at)
        elif command.operation == 'abandon_resume':
            self._require_resume_abandonment_intent()
            result = source_messages.parse_resume_abandonment(message, command, now=at)
            if message['expires_ms'] > pending.message['expires_ms']:
                raise TransferError('file_desktop_resume_lookup_deadline_changed')
        elif command.operation == 'resume_lookup':
            selected = self._require_resume_lookup_selection()
            manifest = selected.job.accepted.manifest
            result = source_messages.parse_resume_history(message, expected_request_id=command.request_id,
                expected_version=command.expected_version, expected_source_id=manifest.source_id,
                expected_transfer_id=manifest.transfer_id, expected_manifest_sha256=manifest.fingerprint,
                expected_media_type=command.media_type,now=at)
            if message['expires_ms'] > pending.message['expires_ms']:
                raise TransferError('file_desktop_resume_lookup_deadline_changed')
        elif command.operation in ('media_page', 'resume_media_page'):
            first = self._source_media_pages[0] if self._source_media_pages else None
            resumed = command.operation == 'resume_media_page'
            original_manifest = self._require_resume_lookup_selection(allow_source_run=True).job.accepted.manifest if resumed else None
            result = parse_media_page(message, expected_request_id=command.request_id, expected_version=command.expected_version,
                expected_run_id=command.run_id, expected_after=command.after,
                expected_manifest_sha256=first.manifest_sha256 if first else original_manifest.fingerprint if resumed else None,
                expected_source_epoch=first.source_epoch if first else None, expected_operation=command.operation,
                expected_media_type=command.media_type,now=at)
            if message['expires_ms'] > pending.message['expires_ms']:
                raise TransferError('file_desktop_source_media_deadline_changed')
            if first is not None and (result.media_type, result.insertion_witness, result.total_files) != (
                    first.media_type, first.insertion_witness, first.total_files):
                raise TransferError('file_desktop_source_media_scope_changed')
            if self._source_run.batched and self._album_media_scope is not None and (
                    result.source_epoch, result.media_type, result.insertion_witness) != self._album_media_scope:
                raise TransferError('file_desktop_source_batch_scope_changed')
            known_files = {entry.file_id for page in self._source_media_pages for entry in page.entries}
            known_photos = {entry.photo_id for page in self._source_media_pages for entry in page.entries}
            if any(entry.file_id in known_files or entry.photo_id in known_photos for entry in result.entries):
                raise TransferError('file_desktop_source_duplicate_media')
            selected = self._selected_preview
            if selected is not None and self._selected_source_id == command.run_id:
                expected = {entry.file_id: entry for entry in selected.entries}
                if ((result.source_epoch, result.media_type, result.insertion_witness, result.total_files) !=
                        (selected.source_epoch, selected.media_type, selected.insertion_witness, len(selected.file_ids))
                        or any(expected.get(entry.file_id) != entry for entry in result.entries)):
                    raise TransferError('file_desktop_photo_selection_changed')
        else:
            result = source_messages.parse_run_result(message, expected_request_id=command.request_id, expected_operation=command.operation,
                expected_version=command.expected_version, expected_run_id=None if command.operation in ('select_run', 'next_batch') else command.run_id,
                expected_media_type=command.media_type,now=at)
            if command.operation in ('select_run', 'next_batch') and result.run_id == command.run_id:
                raise TransferError('file_desktop_photo_selection_owner_reused')
            old = self._source_run
            if old is not None and command.operation != 'end_run' and (
                    old.batched != result.batched or old.batched and old.batch_end is not None and old.batch_end != result.batch_end):
                raise TransferError('file_desktop_source_batch_scope_changed')
            if old is not None and old.run_id == result.run_id and (
                    old.source_io_ended and not result.source_io_ended
                    or old.state in ('cancel_pending', 'canceled_held') and result.state not in ('cancel_pending', 'canceled_held')
                    or old.state in ('failed_held', 'empty_ready') and result.state not in (old.state, 'canceled_held')):
                raise TransferError('file_desktop_source_run_state_rollback')
            if command.operation in ('offer_run', 'offer_resume'):
                self._correlate_source_offer(result, clock)
                if message['expires_ms'] > min(pending.message['expires_ms'], self._offer['expires_ms']):
                    raise TransferError('file_desktop_source_offer_correlation')
        self._source_command_authority(pending, clock)
        if (command.operation == 'resume_run' and self._receive_stop is not None
                and result.run_id == self._receive_stop.source_run_id):
            raise TransferError('file_desktop_resume_source_owner_ended')
        if command.operation in ('run','batch_run','resume_run') and pending.album_kind not in source_messages.KINDS:
            raise TransferError('file_desktop_source_album_kind_required')
        self._controls.finish_receiver_command(pending.ticket)
        self._source_pending = None
        if command.operation in ('status', 'configure', 'configure_videos'):
            if self._source_status is None or self._source_status.version != result.version:
                self._source_catalog = None
                self._source_albums = {}
                self._source_media_pages = ()
                self._source_media_entries = None
                self._resume_lookup_selection = self._resume_history = None
                self._ended_batch = self._ended_batch_policy = None
                self._album_media_scope = None
                self._source_album_kind = None
            self._source_status = result
            if command.operation == 'configure':
                # The phone changes native send state in this transaction and
                # writes its updated controls after the metadata reply. That
                # reply alone cannot authorize a following source command.
                self._source_control_required = pending.remote_witness
        elif command.operation in ('discover', 'catalog_page'):
            if command.operation == 'discover':
                self._source_albums = {}
            self._source_catalog = result
            self._source_albums.update((album.album_id, album) for album in result.albums)
        elif command.operation == 'end_run':
            self._ended_batch = self._source_run if self._source_run.batched else None
            self._ended_batch_policy = self._receiving_policy().version if self._ended_batch is not None else None
            self._source_run = self._source_offer = None
            self._offer = self._offer_binding = self._offer_policy_version = None
            self._source_media_pages = (); self._source_media_entries = None
            self._selected_preview = self._selected_source_id = None
            if self._ended_batch is None or self._ended_batch.batch_end is True:self._source_album_kind=None
        elif command.operation == 'end_album':
            self._ended_batch = self._ended_batch_policy = self._album_media_scope = None
            self._source_album_kind=None
        elif command.operation == 'end_resume':
            self._resume_end_confirmation = (self._resume_lookup_selection.job, result)
            self._resume_ended_manifest = self._resume_lookup_selection.job.accepted.manifest.fingerprint
            self._source_run = self._source_offer = self._resume_source_id = None
            self._resume_lookup_selection = self._resume_history = None
            self._offer = self._offer_binding = self._offer_policy_version = None
            self._source_media_pages = (); self._source_media_entries = None
            self._source_album_kind=None
        elif command.operation == 'select_run':
            self._source_run = result
            self._selected_source_id = result.run_id
            self._offer = self._offer_binding = self._offer_policy_version = self._source_offer = None
            self._source_media_pages = (); self._source_media_entries = None
        elif command.operation in ('run', 'batch_run', 'next_batch', 'run_status', 'cancel_run', 'offer_run', 'resume_run', 'resume_status', 'cancel_resume', 'offer_resume'):
            self._source_run = result  # Canceled/snapshot-ready still do not release a native whole run.
            if command.operation in ('run', 'batch_run', 'next_batch', 'resume_run'):
                self._ended_batch = self._ended_batch_policy = None
                if command.operation != 'next_batch':
                    self._album_media_scope = None
                if command.operation!='next_batch':self._source_album_kind=pending.album_kind
            if command.operation == 'resume_run': self._resume_source_id = result.run_id
            if (command.operation in ('cancel_run', 'cancel_resume') and result.state == 'canceled_held' and result.source_io_ended
                    and self._run is not None and self._run.stop_requested.is_set()
                    and self._receive_stop is not None and self._receive_stop.source_run_id == result.run_id):
                self._run.stop_barrier_confirmed = True
            if command.operation in ('offer_run', 'offer_resume'):
                self._source_offer = result
            elif result.state != 'snapshot_ready':
                self._source_offer = None
                self._source_media_pages = ()
                self._source_media_entries = None
        elif command.operation in ('media_page', 'resume_media_page'):
            self._source_media_pages += (result,)
            if self._source_run.batched:
                self._album_media_scope = (result.source_epoch, result.media_type, result.insertion_witness)
        elif command.operation == 'resume_lookup':
            self._resume_history = result  # Historical hint only; no receive/run/READ authority.
        elif command.operation == 'abandon_resume':
            self._resume_abandonment = result  # Exact explicitly confirmed history, never a READ/run grant.
        self._source_result = result

    def _take_action(self, action):
        if type(action) is not NativePhotoDestinationAction:
            raise TransferError('file_desktop_native_action_required')
        action.consume(self)

    def _receiving_policy(self,*,closing=False):
        self._ready()
        if not self._data_handlers_ready:
            raise TransferError('file_desktop_data_handlers_unavailable')
        snapshot = self._preferences.read()
        if (snapshot.policy is None or not snapshot.policy.enabled or not snapshot.associated
                or not snapshot.destination_available):
            raise TransferError('file_desktop_receive_consent_unavailable')
        if not closing and self._run is not None and snapshot.version != self._run.policy_version:
            raise TransferError('file_desktop_receive_policy_changed')
        return snapshot

    def _receive_destination(self,snapshot,*,media_type='images'):
        source_messages._media_type(media_type)
        if media_type=='images':return snapshot.policy.destination
        if not self._video_data_handlers_ready:raise TransferError('file_desktop_video_data_join_unavailable')
        scope=self._require_video_metadata_scope()
        if scope.version!=snapshot.version:raise TransferError('file_desktop_video_policy_changed')
        return scope.policy.videos.destination

    def _receive_binding(self,*,media_type=None):
        if media_type is not None:source_messages._media_type(media_type)
        active=self._run.media_type if self._run is not None else self._source_run.media_type if self._source_run is not None else None
        owned=active or (self._resume_lookup_selection.media_type if self._resume_lookup_selection is not None else None)
        if self._run is not None and self._source_run is not None and self._source_run.media_type!=owned:
            raise TransferError('file_desktop_source_media_scope_changed')
        if media_type is not None and active is not None and media_type!=active:
            raise TransferError('file_desktop_source_media_scope_changed')
        media_type=media_type or owned or 'images'
        checkpoint=self._checkpoint_binding_owner
        if checkpoint is not None and checkpoint[1]==threading.get_ident() and media_type=='video':
            return self._owned_video_checkpoint_binding(checkpoint[0])
        snapshot = self._receiving_policy()
        destination=self._receive_destination(snapshot,media_type=media_type)
        token=snapshot.policy.destination_token if media_type=='images' else snapshot.policy.videos.destination_token
        if media_type=='video' and token==snapshot.policy.destination_token:
            raise TransferError('file_desktop_video_destination_token_aliased')
        binding = self._controls.binding(token)
        if binding is None:
            raise TransferError('file_desktop_receive_controls_not_agreed')
        if media_type=='video':
            destination.verify()
            if self._require_video_metadata_scope()!=snapshot:raise TransferError('file_desktop_video_policy_changed')
        self._ready()
        if self._mutation_action is not None:
            self._mutation_action.validate(self)
        return binding

    def _owned_video_checkpoint_binding(self,run):
        """Exact drained owner on the checkpoint/close stack only, never READ.

        Derive current base transport authority and current protected destination;
        the accepted historical binding is compared, never returned as a grant.
        """
        state=self._receive_stop
        if (self._checkpoint_binding_owner is None or self._checkpoint_binding_owner[0] is not run
                or self._checkpoint_binding_owner[1]!=threading.get_ident() or self._run is not run
                or not run.stop_requested.is_set() or run.media_type!='video' or run.job is None
                or state is None or state.state!='pending' or state.owner!=run.job.owner
                or self._source_run is None or self._source_run.media_type!='video'
                or self._source_run.run_id!=state.source_run_id
                or run.request is not None and run.request_output_started and not run.stop_barrier_confirmed):
            raise TransferError('file_desktop_video_checkpoint_owner_changed')
        self._ready();snapshot=self._preferences.read()
        policy=snapshot.policy
        if (policy is None or not policy.enabled or not snapshot.associated or not snapshot.destination_available
                or policy.videos is None or policy.videos.destination!=run.accepted.destination):
            raise TransferError('file_desktop_video_checkpoint_scope_changed')
        binding=self._controls.binding(policy.videos.destination_token)
        if binding is None or binding!=run.accepted.binding:
            raise TransferError('file_desktop_video_checkpoint_scope_changed')
        policy.videos.destination.verify();self._ready()
        if self._preferences.read()!=snapshot or self._controls.binding(policy.videos.destination_token)!=binding:
            raise TransferError('file_desktop_video_checkpoint_scope_changed')
        return binding

    def _observe_offer(self, message, clock):
        snapshot = self._receiving_policy()
        binding = self._receive_binding()
        manifest = validate_offer(message, binding.sender_id, binding.receiver_id, now=clock())
        selected = self._selected_preview
        if selected is not None and self._source_run is not None and self._source_run.run_id == self._selected_source_id:
            expected_files = tuple(file for file in selected.manifest.files if file.id in selected.file_ids)
            if (manifest.files != expected_files or manifest.source_id == selected.manifest.source_id
                    or manifest.transfer_id == selected.manifest.transfer_id):
                raise TransferError('file_desktop_photo_selection_changed')
        if self._source_run is None and manifest.fingerprint == self._resume_ended_manifest:
            raise TransferError('file_desktop_resume_source_owner_ended')
        if clock() >= message['expires_ms']:
            raise TransferError('file_desktop_offer_expired')
        if self._run is not None:
            raise TransferError('file_desktop_receive_run_held')
        if self._source_run is not None:
            pending = self._source_pending
            expected_operation = 'offer_resume' if self._resume_source_id is not None else 'offer_run'
            if expected_operation == 'offer_resume':
                selected = self._require_resume_lookup_selection(allow_source_run=True)
                if manifest != selected.job.accepted.manifest:
                    raise TransferError('file_desktop_resume_original_manifest_changed')
            if (pending is None or not pending.sent or pending.command.operation != expected_operation
                    or pending.command.run_id != self._source_run.run_id):
                raise TransferError('file_desktop_source_offer_not_requested')
            self._source_command_authority(pending, clock)
            if message['expires_ms'] > pending.message['expires_ms']:
                raise TransferError('file_desktop_source_offer_correlation')
        frozen = canonical(message)
        if self._offer is not None and canonical(self._offer) != frozen:
            raise TransferError('file_desktop_offer_already_pending')
        if self._offer is not None and (self._offer_binding != binding or self._offer_policy_version != snapshot.version):
            raise TransferError('file_desktop_offer_authority_changed')
        if self._receiving_policy().version != snapshot.version:
            raise TransferError('file_desktop_offer_authority_changed')
        media_entries = correlate_media_pages(self._source_media_pages, manifest) if self._source_media_pages else None
        self._offer = strict_json(frozen)  # Detach mutable dispatcher/wire input.
        self._offer_binding = binding
        self._offer_policy_version = snapshot.version
        self._source_media_entries = media_entries

    def _correlate_source_offer(self, result, clock):
        binding = self._receive_binding()
        if (self._offer is None or self._offer['message_id'] != result.offer_id
                or binding != self._offer_binding or self._receiving_policy().version != self._offer_policy_version):
            raise TransferError('file_desktop_source_offer_correlation')
        manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
        if manifest.fingerprint != result.manifest_sha256 or clock() >= self._offer['expires_ms']:
            raise TransferError('file_desktop_source_offer_correlation')

    def _require_source_offer(self, clock):
        snapshot = self._receiving_policy()
        if snapshot.direction != 'phone_to_desktop':
            raise TransferError('file_desktop_reverse_handlers_unavailable')
        media_type=self._source_run.media_type if self._source_run is not None else 'images'
        if media_type=='video':
            if not self._video_data_handlers_ready:raise TransferError('file_desktop_video_data_join_unavailable')
            self._require_video_metadata_scope()
        if (media_type=='video' or snapshot.include_videos) and (
                self._source_run is None or not self._source_media_pages or self._source_media_entries is None):
            raise TransferError('file_desktop_source_media_not_correlated')
        if snapshot.separate_own_recordings and (self._source_album_kind not in source_messages.KINDS
                or self._source_media_entries is None or self._source_run is None):
            raise TransferError('file_desktop_source_album_kind_required')
        if snapshot.separate_animations and self._source_media_entries is None:
            raise TransferError('file_desktop_source_media_not_correlated')
        if self._source_media_pages:
            if self._offer is None or self._source_media_pages[0].media_type != media_type:
                raise TransferError('file_desktop_media_target_routing_unavailable')
            binding = self._receive_binding()
            manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
            if self._source_media_entries != correlate_media_pages(self._source_media_pages, manifest):
                raise TransferError('file_desktop_source_media_not_correlated')
        if self._source_run is not None:
            if (self._source_pending is not None or self._source_offer is None
                    or self._source_run.state != 'snapshot_ready'
                    or self._source_run.run_id != self._source_offer.run_id
                    or self._source_run.version != self._source_offer.version
                    or self._source_status is None or self._source_status.version != self._source_offer.version):
                raise TransferError('file_desktop_source_offer_not_confirmed')
            self._correlate_source_offer(self._source_offer, clock)

    def _require_unmapped_media(self, *, resume_owner=None):
        """Historical association wins over current target settings.

        This only fences new admission. It neither proves first use after lost
        restart metadata nor implements reconciliation or mapping recovery.
        """
        if self._source_run is not None and not self._source_media_pages:
            raise TransferError('file_desktop_source_media_history_required')
        if self._source_media_pages:
            policy=self._receiving_policy().policy
            if policy.mapping_store is None or policy.job_catalog is None:
                raise TransferError('file_desktop_media_storage_bootstrap_required')
        self._verify_expected_mapping_store()
        before, _ = self._mappings.lookup(())
        if before.revision and not before.associated:
            raise TransferError('file_desktop_photo_mapping_reassociation_required')
        if not self._source_media_pages:
            if before.count:
                raise TransferError('file_desktop_photo_mapping_media_required')
            return self._require_unreserved_media_history(resume_owner)
        page = self._source_media_pages[0]
        entries = self._source_media_entries
        if entries is None:
            raise TransferError('file_desktop_source_media_not_correlated')
        parents=self._version_admission_parents(resume_owner)
        for offset in range(0, len(entries), 128):
            associations = tuple(PhotoMappingAssociation(page.source_epoch, entry.photo_id, page.media_type)
                                 for entry in entries[offset:offset+128])
            current, records = self._mappings.lookup(associations)
            if current != before:
                raise TransferError('file_desktop_photo_mapping_changed')
            if parents and resume_owner is None and (self._selected_source_id!=self._source_run.run_id
                    or self._selected_preview.mapping_snapshot!=before):
                raise TransferError('file_desktop_photo_version_not_current')
            for association,record in zip(associations,records):
                parent=parents.get(association.photo_id)
                if record is not None and (parent is None or parent!=record.protected_record_sha256):
                    raise TransferError('file_desktop_photo_mapping_requires_reconcile')
                if parent is not None and record is None:raise TransferError('file_desktop_photo_version_not_current')
        return self._require_unreserved_media_history(resume_owner,version_parents=parents)

    def _version_admission_parents(self,resume_owner):
        if resume_owner is None:
            return dict(self._selected_preview.version_parents) if self._selected_preview is not None else {}
        if not self._open_catalog(allow_create=False):return {}
        job=next((job for job in self._catalog.jobs() if job.owner==resume_owner),None)
        if job is None or job.accepted.binding!=self._receive_binding():
            raise TransferError('file_desktop_resume_original_job_changed')
        protection=self._authority.protection
        history=NativeFileReceiveOperation.read_media_history(self._catalog,job,self._receive_binding,
            protection.seal,protection.unseal)
        self._verify_job_mapping_store(history)
        return dict(history.version_parents) if history is not None else {}

    def review_pending_photos(self, action, *, clock=now_ms):
        """Compare the fresh phone manifest with original saves and current PC
        bytes BEFORE requesting downloads. Never adopt a same-hash unknown file,
        reopen a stage, overwrite an edit or turn absence into deletion evidence.
        """
        from magnolie_photo_plan import (NativePhotoAssociation, NativePhotoBaseline, NativePhotoObservation,
            PhotoContentWitness, compare_photo)
        from magnolie_photo_target import observe_saved_target
        from magnolie_photo_review import NativePhotoReview, NativePhotoReviewItem
        self._take_action(action)
        with self._operation():
            if self._run is not None or self._offer is None:
                raise TransferError('file_desktop_offer_not_current')
            self._require_source_offer(clock)
            if not self._source_media_pages or self._source_media_entries is None:
                raise TransferError('file_desktop_source_media_history_required')
            self._verify_expected_mapping_store()
            binding = self._receive_binding()
            manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
            first = self._source_media_pages[0]
            associations = tuple(PhotoMappingAssociation(first.source_epoch, entry.photo_id, first.media_type)
                for entry in self._source_media_entries)
            contents=tuple((file.sha256,file.size) for file in manifest.files)
            snapshot, records = self._mappings.lookup(associations,contents=contents)
            if not snapshot.associated:
                raise TransferError('file_desktop_photo_mapping_reassociation_required')
            items = []
            if not self._open_catalog(allow_create=False):
                raise TransferError('file_desktop_media_storage_bootstrap_required')
            protection = self._authority.protection
            with self._catalog.inspect_jobs() as (parent, jobs):
                owners = {job.owner: job for job in jobs}
                for file, entry, mapping in zip(manifest.files, self._source_media_entries, records):
                    action.validate(self); self._receive_binding()
                    if mapping is None:
                        items.append(NativePhotoReviewItem(file.id, entry.photo_id, 'new_photo'))
                        continue
                    job = owners.get(mapping.job_owner)
                    if job is None or job.accepted.binding != binding or mapping.destination != job.accepted.destination:
                        raise TransferError('file_desktop_photo_review_original_job_required')
                    job.accepted.verify(self._receive_binding)
                    with ProtectedTransferJobIndex(parent, job.accepted.manifest, binding, self._receive_binding,
                            protection.seal, protection.unseal, owner=job.owner, accepted=job.accepted) as index:
                        with index._locked():
                            evidence = index.saved_mapping_receipt(); history = index.media_history
                            if evidence is None or history is None:
                                raise TransferError('file_desktop_saved_recovery_complete_evidence_required')
                            if job.saved_mapping_sha256 is not None:
                                from hashlib import sha256
                                if sha256(canonical(evidence.wire())).hexdigest() != job.saved_mapping_sha256:
                                    raise TransferError('file_desktop_saved_mapping_receipt_changed')
                            self._verify_job_mapping_store(history); self._mappings.verify_checkpoint(evidence.store)
                            linked = next((item for item in evidence.entries if item.file_id == mapping.source_file_id), None)
                            receipt = next((item for item in index.saved_receipts() if item.file_id == mapping.source_file_id), None)
                            if (linked is None or receipt is None or linked.photo_id != entry.photo_id
                                    or history.source_epoch != first.source_epoch or history.media_type != first.media_type
                                    or linked.mapping_record_sha256 != mapping.protected_record_sha256
                                    or linked.saved_receipt_sha256 != mapping.receipt_sha256
                                    or receipt.protected_record_sha256 != mapping.receipt_sha256
                                    or receipt.relative_path != mapping.relative_path or receipt.file_key != mapping.file_key
                                    or receipt.parent_keys != mapping.parent_keys or receipt.sha256 != mapping.saved_sha256
                                    or receipt.size != mapping.saved_size):
                                raise TransferError('file_desktop_saved_mapping_receipt_changed')
                            desktop = observe_saved_target(job.accepted, receipt, self._receive_binding)
                            association = NativePhotoAssociation(binding, first.source_epoch, entry.photo_id, mapping.protected_record_sha256)
                            baseline = NativePhotoBaseline(association, PhotoContentWitness(receipt.sha256, receipt.size), receipt.protected_record_sha256)
                            phone = NativePhotoObservation('present', PhotoContentWitness(file.sha256, file.size),
                                insertion_proven=first.insertion_witness)
                            decision = compare_photo(association, baseline, phone, desktop.observation)
                            if index.saved_mapping_receipt() != evidence or receipt not in index.saved_receipts():
                                raise TransferError('file_desktop_saved_recovery_evidence_changed')
                            kind='copy_phone_version' if decision.kind=='unsupported_desktop_replace' else decision.kind
                            items.append(NativePhotoReviewItem(file.id, entry.photo_id, kind, job.owner,
                                mapping.protected_record_sha256 if kind=='copy_phone_version' else None))
                if self._catalog.jobs() != jobs or self._mappings.lookup(associations,contents=contents) != (snapshot, records):
                    raise TransferError('file_desktop_photo_mapping_changed')
            action.validate(self); self._receive_binding()
            if clock() >= self._offer['expires_ms']:
                raise TransferError('file_desktop_offer_expired')
            return NativePhotoReview(manifest.fingerprint, tuple(items))

    def pending_photo_resume_candidate(self,action,*,clock=now_ms):
        """One exact pending original whose entire membership is in this scan.

        Fresh album metadata is a filter, NOT a READ or stage-reopen grant. The
        source must still perform its real original-job lookup and renewal.
        """
        self._take_action(action)
        with self._operation():
            self._require_source_offer(clock)
            if self._run is not None or not self._source_media_pages or self._source_media_entries is None:
                raise TransferError('file_desktop_photo_resume_not_current')
            if not self._open_catalog(allow_create=False):return None
            binding=self._receive_binding();first=self._source_media_pages[0]
            manifest=validate_offer(self._offer,binding.sender_id,binding.receiver_id,now=clock())
            current={entry.photo_id:(entry,file) for entry,file in zip(self._source_media_entries,manifest.files)}
            protection=self._authority.protection
            candidates=[]
            with self._catalog.inspect_jobs() as (parent,jobs):
                events=self._catalog._registry.attempts(jobs) if self._catalog._registry is not None else ()
                for job in jobs:
                    if job.cache_retirement_sha256 is not None or job.accepted.binding!=binding:continue
                    with ProtectedTransferJobIndex(parent,job.accepted.manifest,binding,self._receive_binding,
                            protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                        history=index.media_history
                        if history is None:raise TransferError('file_desktop_photo_job_history_required')
                        if (history.source_epoch,history.media_type)!=(first.source_epoch,first.media_type):continue
                        overlap=set(current)&{entry.photo_id for entry in history.entries}
                        if not overlap:continue
                        if index.saved_mapping_receipt() is not None:continue
                        if len(overlap)!=len(history.entries):
                            raise TransferError('file_desktop_photo_resume_album_membership_unproven')
                        for entry,file in zip(history.entries,job.accepted.manifest.files):
                            live,now=current[entry.photo_id]
                            if (live.media_kind,now.sha256,now.size)!=(entry.media_kind,file.sha256,file.size):
                                raise TransferError('file_desktop_photo_resume_source_changed')
                        last=next((value for value,_ in reversed(events) if value['owner']==job.owner),None)
                        if last is None or last['operation']!='closed':
                            raise TransferError('file_receive_publication_repair_required')
                        if job.accepted.destination!=self._receive_destination(self._receiving_policy(),media_type=first.media_type):
                            raise TransferError('file_desktop_photo_resume_destination_changed')
                        candidates.append(job)
            if len(candidates)>1:raise TransferError('file_desktop_photo_resume_ambiguous')
            action.validate(self);self._receive_binding()
            return candidates[0] if candidates else None

    def select_pending_new_photos(self, action, *, clock=now_ms, include_versions=False):
        """Select fresh native downloads, optionally preserving changed versions.
        Known photos retain their individual historical targets and local edits;
        a version intent retains the exact previous mapping, never a replace flag.
        """
        if type(include_versions) is not bool:raise TransferError('file_desktop_native_version_choice_required')
        reviewed = self.review_pending_photos(action, clock=clock)
        with self._operation():
            action.validate(self)
            if (self._run is not None or self._resume_source_id is not None or self._source_pending is not None
                    or self._source_run is None or self._source_run.state != 'snapshot_ready' or not self._source_run.source_io_ended
                    or self._selected_preview is not None):
                raise TransferError('file_desktop_photo_selection_not_current')
            self._require_source_offer(clock)
            binding = self._receive_binding()
            manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
            if manifest.fingerprint != reviewed.manifest_sha256:
                raise TransferError('file_desktop_photo_selection_not_current')
            ids = tuple(sorted(item.file_id for item in reviewed.items
                if item.decision == 'new_photo' or include_versions and item.decision=='copy_phone_version'))
            if not ids:
                return None  # Explicit no-download review, not a Saved receipt.
            first = self._source_media_pages[0]
            entries = tuple(entry for entry in self._source_media_entries if entry.file_id in ids)
            self._selected_preview = _NativeDesktopPhotoSelection(manifest, self._source_run.run_id, ids, entries,
                first.source_epoch, first.media_type, first.insertion_witness, self._mappings.read(),
                tuple(sorted((item.photo_id,item.prior_mapping_sha256) for item in reviewed.items
                    if include_versions and item.decision=='copy_phone_version')))
            message = source_messages.create_command('select_run', expected_version=self._source_status.version,
                run_id=self._source_run.run_id, manifest_sha256=manifest.fingerprint, file_ids=list(ids), now=clock(),
                **({'media_type': 'video'} if first.media_type == 'video' else {}))
            command = source_messages.parse_command(message, now=clock())
            ticket = self._controls.receiver_command_ticket()
            self._source_pending = _NativeDesktopSourceCommand(ticket, message, command, self._controls.receiver_command_witness(ticket),
                video_negotiated=self._authority.video_available(),
                video_policy_version=self._require_video_metadata_scope().version if first.media_type == 'video' else None)
            self._send_source_pending(clock, action)
            return message['message_id']

    def _require_unreserved_media_history(self,resume_owner,*,version_parents=None):
        # Job anchors precede publication/mapping. Their absence/corruption is
        # not evidence of first use or permission to reserve another copy.
        if not self._open_catalog(allow_create=False):return ()
        peer=self._authority.current_peer()
        if peer is None:raise TransferError('file_desktop_native_authority_changed')
        wanted=set()
        if self._source_media_pages:
            first=self._source_media_pages[0]
            wanted={(first.source_epoch,entry.photo_id,first.media_type) for entry in self._source_media_entries}
        video_epochs={photo:epoch for epoch,photo,media in wanted if media=='video'}
        protection=self._authority.protection
        with self._catalog.inspect_jobs() as (parent,jobs):
            for job in jobs:
                self._ready()
                binding=job.accepted.binding
                if (binding.sender_id!=peer.peer_id or binding.sender_identity_sha256!=peer.identity_sha256
                        or job.owner==resume_owner):continue
                try:
                    # Historical metadata only: no target verification, source
                    # READ renewal, stage worker or publication is authorized.
                    with ProtectedTransferJobIndex(parent,job.accepted.manifest,binding,lambda:None,
                            protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                        history=index.media_history
                        changed_video_epoch=bool(history is not None and history.media_type=='video' and any(
                            entry.photo_id in video_epochs and video_epochs[entry.photo_id]!=history.source_epoch
                            for entry in history.entries))
                        matching={(history.source_epoch,entry.photo_id,history.media_type) for entry in history.entries}&wanted if history else set()
                        versions=version_parents or {}
                        if not changed_video_epoch and matching and all(photo in versions for _,photo,_ in matching):
                            self._verify_completed_mapping_job(index,job,history)
                            continue
                except Exception as error:
                    raise TransferError('file_desktop_photo_job_repair_pending') from error
                self._ready()
                if changed_video_epoch:
                    # Video off/on renews source epoch but not native media IDs.
                    # An old accepted anchor is not first use in the new scope,
                    # even when a caller offers version-parent hints. Metadata
                    # inspection above supplies no historical READ authority.
                    raise TransferError('file_desktop_video_source_reassociation_required')
                if history is None:
                    if wanted:raise TransferError('file_desktop_photo_job_history_required')
                    continue # Limited generic legacy file path, not media readiness.
                if not wanted:raise TransferError('file_desktop_photo_job_media_required')
                if any((history.source_epoch,entry.photo_id,history.media_type) in wanted for entry in history.entries):
                    raise TransferError('file_desktop_photo_job_requires_reconcile')
            return jobs

    def _verify_completed_mapping_job(self,index,job,history):
        """An older fully saved version is history, never a receive reservation."""
        from hashlib import sha256
        from magnolie_photo_mapping_receipt import SavedPhotoMappingReceipt
        evidence=index.saved_mapping_receipt()
        if (job.saved_mapping_sha256 is None or evidence is None
                or sha256(canonical(evidence.wire())).hexdigest()!=job.saved_mapping_sha256):
            raise TransferError('file_desktop_photo_version_original_job_held')
        associations=tuple(PhotoMappingAssociation(history.source_epoch,entry.photo_id,history.media_type) for entry in history.entries)
        _,records=self._mappings.lookup_saved(associations,tuple(entry.saved_receipt_sha256 for entry in evidence.entries))
        receipts=index.saved_receipts()
        if any(record is None for record in records) or SavedPhotoMappingReceipt.capture(
                job.accepted,history,job.owner,receipts,records,evidence.store)!=evidence:
            raise TransferError('file_desktop_saved_mapping_receipt_changed')
        self._verify_job_mapping_store(history);self._mappings.verify_checkpoint(evidence.store)

    def _verify_expected_mapping_store(self):
        snapshot=self._receiving_policy()
        witness=snapshot.policy.mapping_store
        if witness is not None:
            return self._mappings.checkpoint(witness)

    def _verify_job_mapping_store(self,history):
        witness=self._receiving_policy().policy.mapping_store
        checkpoint=history.mapping_store if history is not None else None
        if (checkpoint is None)!=(witness is None):
            raise TransferError('file_desktop_job_mapping_checkpoint_required')
        if checkpoint is not None:
            if checkpoint.witness!=witness:raise TransferError('file_desktop_job_mapping_store_changed')
            self._mappings.verify_checkpoint(checkpoint)

    def _open_catalog(self, *, allow_create=True):
        snapshot=self._receiving_policy()
        if snapshot.policy.job_catalog is not None:self._verify_catalog_witness(snapshot.policy.job_catalog)
        if self._catalog is None:
            parent = Path(self._authority.binding.native_directory)
            try:
                (parent/ProtectedTransferJobCatalog.NAME).lstat()
                create = False
            except FileNotFoundError:
                if not allow_create:
                    return False
                create = True
            protection = self._authority.protection
            self._receive_binding()
            self._catalog = ProtectedTransferJobCatalog(parent, self._authority.identity,
                protection.seal, protection.unseal, create=create)
        return True

    def native_receive_jobs(self):
        """Existing jobs only, under freshly agreed current native consent.
        No source reauthorization, worker start, reservation or implicit resume.
        """
        with self._operation():
            snapshot = self._receiving_policy()
            binding = self._receive_binding()
            if not self._open_catalog(allow_create=False):
                return ()
            jobs = tuple(job for job in self._catalog.jobs()
                         if job.accepted.binding == binding and job.accepted.destination == snapshot.policy.destination)
            self._receive_binding()
            return jobs

    def _publication_gate(self, binding, mutation):
        if self._run is not None and self._run.stop_requested.is_set():
            raise TransferError('file_desktop_receive_stop_requested')
        action = self._mutation_action
        if action is None:
            raise TransferError('file_desktop_native_publication_action_required')
        if self._receive_binding() != binding:
            raise TransferError('file_desktop_native_authority_changed')
        self._verify_expected_mapping_store()
        if self._run is not None and self._run.receiver is not None:
            self._verify_job_mapping_store(self._run.receiver._index.media_history)
        action.validate(self)
        if self._run is not None and self._run.stop_requested.is_set():
            raise TransferError('file_desktop_receive_stop_requested')
        result = mutation()
        if self._run is not None and self._run.stop_requested.is_set():
            raise TransferError('file_desktop_receive_stop_requested')
        if self._receive_binding() != binding:
            raise TransferError('file_desktop_native_authority_changed')
        action.validate(self)
        return result

    def _send_data(self, message, clock, *, action=None, on_output=None):
        run = self._run
        if run is not None and run.stop_requested.is_set():
            raise TransferError('file_desktop_receive_stop_requested')
        self._receive_binding()
        self._ready()
        if action is not None:
            action.validate(self)
        if clock() >= message['expires_ms']:
            raise TransferError('file_desktop_output_expired')
        with self._receive_stop_gate:
            if run is not None and run.stop_requested.is_set():
                raise TransferError('file_desktop_receive_stop_requested')
            if on_output is not None: on_output()
        self._channel.send(message)
        if run is not None and run.stop_requested.is_set():
            raise TransferError('file_desktop_receive_stop_requested')
        self._receive_binding()
        if action is not None:
            action.validate(self)
        if clock() >= message['expires_ms']:
            raise TransferError('file_desktop_output_expired')

    def accept_pending_offer(self, action, offer_id, *, clock=now_ms):
        """Native I/O-lane admission only; no UI-thread work or implicit run."""
        self._take_action(action)
        selection=self._selected_preview
        if selection is not None and selection.version_parents:
            reviewed=self.review_pending_photos(self.issue_receive_action(),clock=clock)
            if (tuple(sorted((item.photo_id,item.prior_mapping_sha256) for item in reviewed.items
                    if item.decision=='copy_phone_version'))!=selection.version_parents
                    or any(item.decision not in ('new_photo','copy_phone_version') for item in reviewed.items)):
                raise TransferError('file_desktop_photo_version_review_changed')
        with self._operation():
            if self._run is not None or self._offer is None or self._offer['message_id'] != offer_id:
                raise TransferError('file_desktop_offer_not_current')
            self._require_source_offer(clock)
            observed_jobs=self._require_unmapped_media()
            snapshot = self._receiving_policy()
            binding = self._receive_binding()
            if binding != self._offer_binding or snapshot.version != self._offer_policy_version:
                raise TransferError('file_desktop_offer_authority_changed')
            manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
            if clock() >= self._offer['expires_ms']:
                raise TransferError('file_desktop_offer_expired')
            targets={file.id:file.path for file in manifest.files}
            media_type=self._source_run.media_type if self._source_run is not None else 'images'
            destination=self._receive_destination(snapshot,media_type=media_type)
            if snapshot.separate_animations:
                # Only fresh, correlated animation members are routed. Known
                # historical associations were fenced before deriving paths.
                entries={entry.file_id:entry for entry in self._source_media_entries}
                targets={file.id:('Animationen/'+file.path if entries[file.id].media_kind=='animation' else file.path)
                    for file in manifest.files}
            if snapshot.separate_own_recordings and self._source_album_kind=='camera':
                targets={file_id:'Eigene Aufnahmen/'+path for file_id,path in targets.items()}
            parents=selection.version_parents if selection is not None else ()
            if parents:
                from magnolie_photo_mappings import photo_version_path
                first=self._source_media_pages[0];by_file={entry.file_id:entry for entry in self._source_media_entries}
                for file in manifest.files:
                    photo_id=by_file[file.id].photo_id
                    if photo_id in dict(parents):
                        association=PhotoMappingAssociation(first.source_epoch,photo_id,first.media_type)
                        _,(original,)=self._mappings.lookup((association,))
                        if original is None or original.destination!=destination:
                            raise TransferError('file_desktop_photo_version_destination_changed')
                        targets[file.id]=photo_version_path(association,file)
            accepted = NativeAcceptedTransfer.capture(manifest, binding, targets,
                destination.path, self._receive_binding)
            if accepted.destination != destination:
                raise TransferError('file_desktop_original_destination_changed')
            history = NativeMediaHistory.capture(accepted,self._source_media_pages,
                mapping_store=self._verify_expected_mapping_store(),version_parents=parents) if self._source_media_pages else None
            self._verify_job_mapping_store(history)
            action.validate(self)
            self._run = _NativeDesktopReceiveRun(snapshot.version, accepted,
                media_type=self._source_run.media_type if self._source_run is not None else 'images')
            self._mutation_action = action
            try:
                self._open_catalog()
                self._receive_binding(); action.validate(self)
                if clock() >= self._offer['expires_ms']:
                    raise TransferError('file_desktop_offer_expired')
                protection = self._authority.protection
                self._run.receiver = NativeFileReceiveOperation.accept(self._catalog, accepted,
                    self._receive_binding, protection.seal, protection.unseal, self._publication_gate,media_history=history,
                    expected_jobs=observed_jobs)
                self._run.job = self._run.receiver.job
                self._selected_preview = self._selected_source_id = None
                self._run.acceptance = self._run.receiver.acceptance_message(self._offer, now=clock())
                action.validate(self)
                self._send_data(self._run.acceptance, clock, action=action)
                self._run.acceptance_sent = True
                return self._run.receiver.progress()
            except NativeReceiveStartError as error:
                self._run.job = error.job  # Reservation/cache stay held for recovery.
                raise
            finally:
                self._mutation_action = None

    def retry_acceptance(self, *, clock=now_ms):
        with self._operation():
            run = self._require_receiver()
            if run.acceptance is None:
                raise TransferError('file_desktop_acceptance_repair_pending')
            self._send_data(run.acceptance, clock)
            if run.stop_requested.is_set(): raise TransferError('file_desktop_receive_stop_requested')
            run.acceptance_sent = True

    def resume_pending_offer(self, action, offer_id, native_job_owner, *, clock=now_ms):
        """Exact current offer + existing native reservation, never bytes/totals.
        Restores verified checkpoint/staged bytes without recreating publication
        authority. Phone restart READ renewal must be proved separately there.
        """
        self._take_action(action)
        with self._operation():
            if self._run is not None or self._offer is None or self._offer['message_id'] != offer_id:
                raise TransferError('file_desktop_offer_not_current')
            if self._source_run is not None and self._source_run.media_type=='video' and (
                    self._resume_source_id!=self._source_run.run_id or self._resume_lookup_selection is None
                    or self._resume_lookup_selection.media_type!='video'):
                raise TransferError('file_desktop_video_original_resume_join_unavailable')
            if self._resume_source_id is not None:
                selected = self._require_resume_lookup_selection(allow_source_run=True)
                if native_job_owner != selected.job.owner:
                    raise TransferError('file_desktop_resume_original_job_changed')
            self._require_source_offer(clock)
            observed_jobs=self._require_unmapped_media(resume_owner=native_job_owner)
            snapshot = self._receiving_policy()
            binding = self._receive_binding()
            if binding != self._offer_binding or snapshot.version != self._offer_policy_version:
                raise TransferError('file_desktop_offer_authority_changed')
            manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
            if clock() >= self._offer['expires_ms'] or not self._open_catalog(allow_create=False):
                raise TransferError('file_desktop_resume_unavailable')
            current_jobs=self._catalog.jobs()
            if current_jobs!=observed_jobs:raise TransferError('file_desktop_photo_job_history_changed')
            job = next((job for job in current_jobs if job.owner == native_job_owner), None)
            destination=self._receive_destination(snapshot,media_type=self._source_run.media_type if self._source_run is not None else 'images')
            if (job is None or job.accepted.manifest != manifest or job.accepted.binding != binding
                    or job.accepted.destination != destination):
                raise TransferError('file_desktop_resume_not_current')
            job.accepted.verify(self._receive_binding)
            action.validate(self)
            protection = self._authority.protection
            original = NativeFileReceiveOperation.read_media_history(self._catalog,job,self._receive_binding,
                protection.seal,protection.unseal)
            self._verify_job_mapping_store(original)
            if original is not None or self._source_media_pages:
                if original is None or not self._source_media_pages:
                    raise TransferError('file_desktop_resume_media_history_required')
                current = NativeMediaHistory.capture(job.accepted,self._source_media_pages)
                if (original.source_epoch,original.media_type,original.entries) != (current.source_epoch,current.media_type,current.entries):
                    raise TransferError('file_desktop_resume_media_association_changed')
            action.validate(self)
            self._run = _NativeDesktopReceiveRun(snapshot.version, job.accepted, job=job,
                media_type=self._source_run.media_type if self._source_run is not None else 'images',
                resume_source_run_id=self._resume_source_id)
            self._run.receiver = NativeFileReceiveOperation.resume(self._catalog, job, self._receive_binding,
                protection.seal, protection.unseal, self._publication_gate)
            if self._run.stop_requested.is_set(): raise TransferError('file_desktop_receive_stop_requested')
            action.validate(self)
            self._run.acceptance = self._run.receiver.acceptance_message(self._offer, now=clock())
            self._send_data(self._run.acceptance, clock, action=action)
            if self._run.stop_requested.is_set(): raise TransferError('file_desktop_receive_stop_requested')
            self._run.acceptance_sent = True
            return self._run.receiver.progress()

    def _require_receiver(self, *, allow_stopping=False):
        self._receive_binding()
        if self._run is None or self._run.receiver is None:
            raise TransferError('file_desktop_receive_repair_pending')
        if self._run.stop_requested.is_set() and not allow_stopping:
            raise TransferError('file_desktop_receive_stop_requested')
        return self._run

    def request_next_chunk(self, *, clock=now_ms):
        with self._operation():
            run = self._require_receiver()
            if not run.acceptance_sent:
                raise TransferError('file_desktop_acceptance_not_sent')
            if run.request is None or clock() >= run.request['expires_ms']:
                run.request = run.receiver.next_chunk_request_message(now=clock())
                run.request_sent = False
                run.request_output_started = False
            if run.request is None:
                return None  # No missing bytes is not publication/save/sync END.
            self._send_data(run.request, clock, on_output=lambda:setattr(run, 'request_output_started', True))
            if run.stop_requested.is_set(): raise TransferError('file_desktop_receive_stop_requested')
            run.request_sent = True
            return strict_json(canonical(run.request))

    def _receive_chunk(self, message, clock):
        request_id = message.get('body', {}).get('request_id') if type(message.get('body')) is dict else None
        stopped = self._stopped_receive_run
        if stopped is not None and stopped.last_request is not None and request_id == stopped.last_request['message_id']:
            data = bytearray(parse_chunk(message, stopped.last_request, stopped.accepted, self._receive_binding, now=clock()))
            try:
                if stopped.last_chunk_sha256 is None or message['body']['data_sha256'] != stopped.last_chunk_sha256:
                    raise TransferError('file_desktop_stopped_chunk_changed')
            finally:
                data[:] = b'\x00' * len(data)  # Verified old duplicate, no stage reopen or data authority.
            return
        run = self._require_receiver(allow_stopping=True)
        duplicate = run.last_request is not None and request_id == run.last_request['message_id']
        request = run.last_request if duplicate else run.request
        draining = (run.stop_requested.is_set() and run.request_output_started and request is not None
                    and request_id == request['message_id'])
        if request is None or not duplicate and not run.request_sent and not draining:
            raise TransferError('file_desktop_chunk_not_requested')
        run.receiver.receive_chunk_message(message, request, now=clock())
        self._receive_binding()
        checked = clock()
        if checked >= request['expires_ms'] or checked >= message['expires_ms']:
            raise TransferError('file_desktop_chunk_expired_during_native_io')
        if not duplicate:
            run.last_request = request
            run.last_chunk_sha256 = message['body']['data_sha256']
            run.request = None
            run.request_sent = False
            run.request_output_started = False

    def receive_progress(self):
        with self._operation():
            return self._require_receiver().receiver.progress()

    def observe_saved_photo(self, file_id):
        """Native read-only conflict input; no wire/UI or deletion authority."""
        with self._operation():
            run = self._require_receiver()
            result = run.receiver.observe_saved_photo(file_id)
            self._receive_binding()
            return result

    def publish_received(self, action, *, clock=now_ms):
        """Explicit native publication/readback only. Never overwrites a target;
        changed versions use separate immutable targets, not an in-place replace.
        """
        self._take_action(action)
        with self._operation():
            run = self._require_receiver()
            if not run.acceptance_sent:
                raise TransferError('file_desktop_acceptance_not_sent')
            self._mutation_action = action
            try:
                action.validate(self)
                self._verify_version_parent_targets(run)
                run.receiver.publish_completed()
                self._receive_binding(); action.validate(self)
                run.receiver.commit_saved_receipts()
                self._commit_saved_media(run, action=action)
                run.saved_mapping_ready=run.receiver._index.saved_mapping_receipt() is not None
                confirmation = run.receiver.saved_receipt_message(now=clock())
                action.validate(self)
                self._send_data(confirmation, clock, action=action)
                return run.receiver.progress()  # Local save != whole-sync END/quota release.
            finally:
                self._mutation_action = None

    def _verify_version_parent_targets(self,run):
        """A PC edit during download is still a conflict, not a new baseline.

        Only read the protected original target; publication always uses another
        no-replace path. Never change, rename or lock the user's original file.
        """
        from magnolie_photo_target import observe_saved_target
        history=run.receiver._index.media_history
        if history is None or not history.version_parents:return
        protection=self._authority.protection
        with self._catalog.inspect_jobs() as (parent,jobs):
            owners={job.owner:job for job in jobs}
            for photo,expected in history.version_parents:
                association=PhotoMappingAssociation(history.source_epoch,photo,history.media_type)
                _,(mapping,)=self._mappings.lookup((association,))
                if mapping is None or mapping.protected_record_sha256!=expected:
                    raise TransferError('file_desktop_photo_version_parent_changed')
                original=owners.get(mapping.job_owner)
                if original is None or original.accepted.binding!=run.accepted.binding:
                    raise TransferError('file_desktop_photo_version_parent_changed')
                with ProtectedTransferJobIndex(parent,original.accepted.manifest,original.accepted.binding,self._receive_binding,
                        protection.seal,protection.unseal,owner=original.owner,accepted=original.accepted) as index:
                    self._verify_completed_mapping_job(index,original,index.media_history)
                    receipt=next((receipt for receipt in index.saved_receipts() if receipt.file_id==mapping.source_file_id),None)
                    if receipt is None:raise TransferError('file_desktop_photo_version_parent_changed')
                    observed=observe_saved_target(original.accepted,receipt,self._receive_binding).observation
                    if (observed.state!='present' or not observed.managed
                            or (observed.content.sha256,observed.content.size)!=(mapping.saved_sha256,mapping.saved_size)):
                        raise TransferError('file_desktop_photo_version_parent_edited')
            self._receive_binding()

    def _commit_saved_media(self, run, *, action=None):
        # Use the original protected job anchor, never the current wire cache.
        self._verify_expected_mapping_store()
        history = run.receiver._index.media_history
        self._verify_job_mapping_store(history)
        if history is None:
            if self._source_media_pages:
                raise TransferError('file_desktop_saved_media_history_required')
            return  # Limited legacy photo fixture, not media-feature readiness.
        if action is not None:
            action.validate(self)
        self._receive_binding()
        existing=run.receiver._index.saved_mapping_receipt()
        if existing is None:
            snapshot,records=self._mappings.commit_saved_history(self._mappings.issue_action(),self._mappings.read(),run.receiver)
            checkpoint=self._mappings.checkpoint(self._mappings._store_witness())
            if checkpoint.version!=snapshot.version:
                raise TransferError('file_desktop_saved_mapping_checkpoint_changed')
            run.receiver._index.commit_saved_mapping(records,checkpoint,run.receiver._lease)
        else:
            _,records=self._mappings.lookup_saved(tuple(PhotoMappingAssociation(history.source_epoch,entry.photo_id,history.media_type)
                for entry in history.entries),tuple(entry.saved_receipt_sha256 for entry in existing.entries))
            if (any(record is None for record in records)
                    or tuple(record.protected_record_sha256 for record in records)!=tuple(entry.mapping_record_sha256 for entry in existing.entries)):
                raise TransferError('file_desktop_saved_mapping_receipt_changed')
            self._mappings.verify_checkpoint(existing.store)
        if run.receiver._index.saved_mapping_receipt() is None:
            raise TransferError('file_desktop_saved_mapping_receipt_required')
        self._receive_binding()
        if action is not None:
            action.validate(self)

    def send_saved_confirmation(self, *, clock=now_ms):
        """Retry historical protected receipts without re-publication or overwrite."""
        with self._operation():
            run = self._require_receiver()
            if not run.acceptance_sent:
                raise TransferError('file_desktop_acceptance_not_sent')
            self._commit_saved_media(run)
            message = run.receiver.saved_receipt_message(now=clock())
            self._send_data(message, clock)

    def finish_saved_receive(self, action, *, retire_cache=False):
        """Close a fully saved native receiver, retaining original history/quota.
        This is local completion only, not proof that the phone saw the message.
        """
        if type(retire_cache) is not bool:
            raise TransferError('file_desktop_native_cache_choice_required')
        self._take_action(action)
        with self._operation():
            run = self._require_receiver()
            if run.resume_source_run_id is not None:
                ended=self._resume_end_confirmation
                if (self._resume_source_id is not None or ended is None or ended[0]!=run.job
                        or ended[1].run_id!=run.resume_source_run_id or not ended[1].run_ended
                        or not ended[1].source_io_ended):
                    raise TransferError('file_desktop_resume_source_end_required')
            self._commit_saved_media(run, action=action)
            evidence = run.receiver._index.saved_mapping_receipt()
            if evidence is None:
                raise TransferError('file_desktop_saved_recovery_complete_evidence_required')
            backup_history = run.receiver._index.media_history
            progress = run.receiver.checkpoint()
            if progress.verified_bytes != progress.total_bytes or progress.checkpoint_verified_bytes != progress.total_bytes:
                raise TransferError('file_desktop_saved_receive_incomplete')
            action.validate(self)
            if retire_cache:
                run.job = self._catalog.retire_saved_cache(run.receiver)
                action.validate(self)
            try:
                run.receiver.close()
            except Exception as error:
                self._cleanup_error = type(error).__name__
                raise
            action.validate(self); self._receive_binding()
            if self._album_worker is not None and self._desktop_session is not None:
                history = backup_history
                if history is not None:
                    for entry in history.entries:
                        proof = next((value for value in evidence.entries if value.file_id == entry.file_id), None)
                        if proof is None:raise TransferError('file_desktop_saved_mapping_receipt_changed')
                        self._album_worker._backup_versions.add((PhotoMappingAssociation(history.source_epoch,entry.photo_id,history.media_type),
                            proof.mapping_record_sha256))
            self._run = None
            self._offer = self._offer_binding = self._offer_policy_version = None
            return progress  # Never a remote ACK, baseline reset or quota cleanup.

    def set_future_animation_layout(self,action,*,separate,historical_choice):
        return self._set_future_layout(action,'animation',separate,historical_choice)

    def set_future_capture_layout(self,action,*,separate,historical_choice):
        return self._set_future_layout(action,'capture',separate,historical_choice)

    def _set_future_layout(self,action,kind,separate,historical_choice):
        self._take_action(action)
        with self._operation():
            if (self._album_worker is not None or self._run is not None or self._source_pending is not None
                    or self._source_run is not None or self._offer is not None):
                raise TransferError('file_desktop_receive_already_active')
            binding=self._receive_binding();before=self._preferences.read()
            setter=self._preferences.set_animation_layout if kind=='animation' else self._preferences.set_capture_layout
            changed=setter(self._preferences.issue_action(),before,
                separate=separate,historical_choice=historical_choice)
            action.validate(self)
            if self._receive_binding()!=binding:raise TransferError('photo_preferences_authority_changed')
            return changed

    def inspect_photo_recovery(self, action):
        """Bounded native metadata overview; never a repair/publication permit.

        No stage, publisher, destination-file read or source lookup is opened.
        Every subsequent explicit recovery action revalidates the original job.
        """
        self._take_action(action)
        with self._operation():
            if self._run is not None or self._source_pending is not None or self._source_run is not None or self._offer is not None:
                raise TransferError('file_desktop_receive_already_active')
            binding=self._receive_binding();snapshot=self._receiving_policy()
            if not self._open_catalog(allow_create=False):return ()
            protection=self._authority.protection;result=[]
            with self._catalog.inspect_jobs() as (parent,jobs):
                events=self._catalog._registry.attempts(jobs) if self._catalog._registry is not None else ()
                for job in jobs:
                    if job.accepted.binding!=binding or job.accepted.destination!=snapshot.policy.destination:continue
                    state='held'
                    try:
                        with ProtectedTransferJobIndex(parent,job.accepted.manifest,binding,self._receive_binding,
                                protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                            history=index.media_history;receipt=index.saved_mapping_receipt()
                            if history is not None:
                                self._verify_expected_mapping_store();self._verify_job_mapping_store(history)
                                if receipt is not None:
                                    self._mappings.verify_checkpoint(receipt.store)
                                    _,records=self._mappings.lookup_saved(tuple(PhotoMappingAssociation(history.source_epoch,entry.photo_id,history.media_type)
                                        for entry in history.entries),tuple(entry.saved_receipt_sha256 for entry in receipt.entries))
                                    if (all(record is not None for record in records) and
                                            tuple(record.protected_record_sha256 for record in records)==tuple(entry.mapping_record_sha256 for entry in receipt.entries)):
                                        state='saved_confirmation'
                                else:
                                    receipts={value.file_id:value for value in index.saved_receipts()}
                                    if set(receipts)=={entry.file_id for entry in history.entries}:
                                        _,records=self._mappings.lookup_saved(tuple(PhotoMappingAssociation(history.source_epoch,entry.photo_id,history.media_type)
                                            for entry in history.entries),tuple(receipts[entry.file_id].protected_record_sha256 for entry in history.entries))
                                        if all(record is not None for record in records):state='mapping_receipt_repair'
                                    elif job.cache_retirement_sha256 is None:
                                        last=next((value for value,_ in reversed(events) if value['owner']==job.owner),None)
                                        if last is not None and last['operation']=='closed':state='resumable'
                    except Exception:
                        # Corrupt/inaccessible metadata is displayed as held, not
                        # reinitialized or converted into missing-file evidence.
                        self._receive_binding();action.validate(self)
                    result.append(dict(job_owner=job.owner,state=state,files=len(job.accepted.manifest.files)))
                if self._catalog.jobs()!=jobs:raise TransferError('file_desktop_saved_recovery_evidence_changed')
            action.validate(self);self._receive_binding()
            return tuple(result)

    def recover_saved_confirmation(self, action, native_job_owner, *, clock=now_ms):
        """Explicit historical media ACK retry, never source/stage recovery.

        Requires a complete original post-mapping receipt. Unfinished or legacy
        jobs need separate repair; no guessed mapping, target read or new worker.
        """
        from magnolie_file_saved_message import create_saved
        self._take_action(action)
        with self._operation():
            action.validate(self)
            if self._run is not None or self._source_pending is not None or self._source_run is not None or self._offer is not None:
                raise TransferError('file_desktop_receive_already_active')
            if not self._open_catalog(allow_create=False):
                raise TransferError('file_desktop_saved_recovery_unavailable')
            binding=self._receive_binding();snapshot=self._receiving_policy()
            protection=self._authority.protection
            with self._catalog.inspect_jobs() as (parent,jobs):
                job=next((job for job in jobs if job.owner==native_job_owner),None)
                if (job is None or job.accepted.binding!=binding or job.accepted.destination!=snapshot.policy.destination):
                    raise TransferError('file_desktop_saved_recovery_original_job_required')
                job.accepted.verify(self._receive_binding);action.validate(self)
                with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,self._receive_binding,
                        protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                    # Hold the exact original index lock until actual output ends.
                    # A live receiver lease on another instance fails busy.
                    with index._locked():
                        evidence=index.saved_mapping_receipt();history=index.media_history
                        if evidence is None or history is None:
                            raise TransferError('file_desktop_saved_recovery_complete_evidence_required')
                        self._verify_expected_mapping_store();self._verify_job_mapping_store(history)
                        self._mappings.verify_checkpoint(evidence.store)
                        _,records=self._mappings.lookup_saved(tuple(PhotoMappingAssociation(history.source_epoch,entry.photo_id,history.media_type)
                            for entry in history.entries),tuple(entry.saved_receipt_sha256 for entry in evidence.entries))
                        if (any(record is None for record in records)
                                or tuple(record.protected_record_sha256 for record in records)!=tuple(entry.mapping_record_sha256 for entry in evidence.entries)):
                            raise TransferError('file_desktop_saved_mapping_receipt_changed')
                        receipts=index.saved_receipts()
                        message=create_saved(job.accepted,receipts,self._receive_binding,job.owner,now=clock())
                        action.validate(self)
                        if self._catalog.jobs()!=jobs or index.saved_mapping_receipt()!=evidence:
                            raise TransferError('file_desktop_saved_recovery_evidence_changed')
                        self._send_data(message,clock,action=action)
                        if index.saved_mapping_receipt()!=evidence:
                            raise TransferError('file_desktop_saved_recovery_evidence_changed')
                        return evidence  # Historical only; quota and local bytes stay held.

    def repair_saved_mapping_receipt(self, action, native_job_owner):
        """Explicitly finish only original complete save→mapping evidence.

        No socket confirmation or missing-mapping reconstruction is performed.
        A separate native recovery action is needed to send the historical ACK.
        """
        self._take_action(action)
        with self._operation():
            action.validate(self)
            if self._run is not None or self._source_pending is not None or self._source_run is not None or self._offer is not None:
                raise TransferError('file_desktop_receive_already_active')
            self._mutation_action=action
            try:
                if not self._open_catalog(allow_create=False):
                    raise TransferError('file_desktop_saved_recovery_unavailable')
                binding=self._receive_binding();snapshot=self._receiving_policy();protection=self._authority.protection
                with self._catalog.inspect_jobs() as (parent,jobs):
                    job=next((job for job in jobs if job.owner==native_job_owner),None)
                    if (job is None or job.accepted.binding!=binding or job.accepted.destination!=snapshot.policy.destination):
                        raise TransferError('file_desktop_saved_recovery_original_job_required')
                    job.accepted.verify(self._receive_binding)
                    with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,self._receive_binding,
                            protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                        lease=index.claim_operation()
                        history=index.media_history
                        if history is None:raise TransferError('file_desktop_saved_recovery_original_history_required')
                        self._verify_expected_mapping_store();self._verify_job_mapping_store(history)
                        receipts={receipt.file_id:receipt for receipt in index.saved_receipts()}
                        if set(receipts)!={entry.file_id for entry in history.entries}:
                            raise TransferError('file_desktop_saved_recovery_complete_evidence_required')
                        snapshot,records=self._mappings.lookup_saved(tuple(PhotoMappingAssociation(history.source_epoch,entry.photo_id,history.media_type)
                            for entry in history.entries),tuple(receipts[entry.file_id].protected_record_sha256 for entry in history.entries))
                        if any(record is None for record in records):
                            raise TransferError('file_desktop_saved_recovery_original_mappings_required')
                        checkpoint=self._mappings.checkpoint(self._mappings._store_witness())
                        if checkpoint.version!=snapshot.version:
                            raise TransferError('file_desktop_saved_mapping_checkpoint_changed')
                        existing=index.saved_mapping_receipt()
                        if existing is not None:
                            if tuple(record.protected_record_sha256 for record in records)!=tuple(entry.mapping_record_sha256 for entry in existing.entries):
                                raise TransferError('file_desktop_saved_mapping_receipt_changed')
                            self._mappings.verify_checkpoint(existing.store)
                        self._receive_binding();action.validate(self)
                        if self._catalog.jobs()!=jobs:raise TransferError('file_desktop_saved_recovery_evidence_changed')
                        result=index.commit_saved_mapping(records,checkpoint,lease)
                        if index.saved_mapping_receipt()!=result:raise TransferError('file_desktop_saved_recovery_evidence_changed')
                        self._receive_binding();action.validate(self)
                        return result
            finally:self._mutation_action=None

    def read_preferences(self):
        with self._operation():
            return self._preferences.read()

    def _media_trash_owner(self):
        if self._media_trash is None:
            from magnolie_media_trash import ProtectedMediaTrash
            self._media_trash=ProtectedMediaTrash(self._authority)
        return self._media_trash

    def _media_trash_gate(self,action):
        self._ready();action.validate(self)
        if not self._data_handlers_ready:
            raise TransferError('file_desktop_data_handlers_unavailable')
        if (self._album_worker is not None or self._run is not None or self._source_pending is not None
                or self._source_run is not None or self._offer is not None):
            raise TransferError('file_desktop_receive_already_active')
        self._verify_expected_mapping_store()
        self._ready();action.validate(self)
        return True

    def inspect_media_trash(self,action):
        """Explicit native read only; no absent defaults, moves or remote ACK."""
        self._take_action(action)
        with self._operation():
            action.validate(self)
            result=self._media_trash_owner().read()
            action.validate(self);return result

    def prepare_media_trash(self,action,expected,association,mapping_sha256):
        """Native selected mapping only, never a web path or scan absence."""
        self._take_action(action)
        with self._operation():
            self._media_trash_gate(action);owner=self._media_trash_owner()
            result=owner.prepare_local(owner.issue_action(),expected,self._mappings,association,mapping_sha256)
            self._media_trash_gate(action);return result

    def move_media_to_trash(self,action,expected,operation):
        return self._move_local_media_trash(action,expected,operation,restore=False)

    def restore_media_from_trash(self,action,expected,operation):
        return self._move_local_media_trash(action,expected,operation,restore=True)

    def cancel_prepared_media_trash(self,action,expected,operation):
        self._take_action(action)
        with self._operation():
            self._media_trash_gate(action);owner=self._media_trash_owner()
            result=owner.cancel_prepared(owner.issue_action(),expected,operation,lambda:self._media_trash_gate(action))
            self._media_trash_gate(action);return result

    def _move_local_media_trash(self,action,expected,operation,*,restore):
        self._take_action(action)
        with self._operation():
            self._media_trash_gate(action);owner=self._media_trash_owner()
            method=owner.restore if restore else owner.trash
            result=method(owner.issue_action(),expected,operation,lambda:self._media_trash_gate(action))
            self._media_trash_gate(action);return result

    def close(self):
        self._closed.set()
        if self._mapped_worker is not None:self._mapped_worker.stop()
        self._media_sending_choice=None
        for owner in (self._media_sender,self._media_source,self._media_transport):
            if owner is not None:owner.close() # Signals only; active connection I/O owns cleanup.
        self._wake_album_worker()
        self._authority.revoke()  # Nonwaiting even during blocked native/socket I/O.
        return self._close_resources()

    def _close_resources(self):
        if not self._gate.acquire(blocking=False):
            return False
        try:
            if self._mapped_worker is not None:return False # Its real I/O lane has not drained yet.
            failure = None
            if self._source_pending is not None and self._controls is not None:
                try:
                    self._controls.finish_receiver_command(self._source_pending.ticket)
                    self._source_pending = None
                except Exception as error:
                    failure = error
            receiver = self._run.receiver if self._run is not None else None
            for resource in (receiver, self._media_sender, self._media_source, self._media_transport, self._catalog, self._destination, self._media_trash, self._mappings, self._preferences, self._controls, self._authority):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception as error:
                        if failure is None:
                            failure = error
            if failure is not None:
                self._cleanup_error = type(failure).__name__
                raise failure
            if self._cleanup_error is not None:
                return False  # A prior uncertain cleanup is not proof of release.
            if not self._release_reported:
                self._release_reported = True
                self._released(self)
            return True
        finally:
            self._gate.release()


@dataclass
class _NativeDesktopReceiveRun:
    policy_version: str
    accepted: NativeAcceptedTransfer
    receiver: NativeFileReceiveOperation | None = None
    job: object = None
    acceptance: dict | None = None
    acceptance_sent: bool = False
    request: dict | None = None
    request_sent: bool = False
    last_request: dict | None = None
    last_chunk_sha256: str | None = None
    stop_requested: threading.Event = field(default_factory=threading.Event)
    request_output_started: bool = False
    stop_barrier_confirmed: bool = False
    saved_mapping_ready: bool = False
    media_type: str = 'images'
    resume_source_run_id: str | None = None


@dataclass(frozen=True)
class NativeReceiveStop:
    owner: str
    source_run_id: str
    state: str
    io_ended: bool = False
    checkpoint_committed: bool = False
    resources_closed: bool = False
    verified_bytes: int | None = None
    checkpoint_verified_bytes: int | None = None
    checkpoint_cleanup_pending: bool | None = None

    @property
    def is_saved_receipt(self): return False

    @property
    def grants_write_authority(self): return False

    @property
    def grants_repair_authority(self): return False


@dataclass(frozen=True)
class _NativeDesktopResumeLookup:
    job: object
    policy_version: str
    source_version: str
    media_type: str = 'images'


class NativePhotoAlbumWorker:
    """Actual explicit native album I/O. No pairing-triggered start or dummy data.
    Activity callbacks receive this exact owner, so an old END cannot clear a
    newer worker's tray state. OS/UI consumers must marshal callbacks themselves.
    """
    def __init__(self, connection, album_id, desktop_choice, activity_changed, *, media_type='images',book_fence=None):
        self._connection = connection
        self._album_id = album_id; self._desktop_choice = desktop_choice
        self._media_type = media_type
        self._book_fence=book_fence;self._book_policy=None;self._cleaning=False
        self._activity_changed = activity_changed
        self._stop = threading.Event(); self._ended = threading.Event()
        self._state_gate = threading.Lock()
        self._state = 'starting'; self._error = self._activity_error = None
        self._saved = 0; self._known = 0; self._conflicts = []
        self._backup_versions = set()
        self._thread = threading.Thread(target=self._run, name='magnolie-photo-album', daemon=True)

    @property
    def io_ended(self):
        return self._ended.is_set()

    def progress(self):
        with self._state_gate:
            return dict(state=self._state, saved_files=self._saved, known_files=self._known,
                conflicts=tuple(self._conflicts), error=self._error, activity_error=self._activity_error,
                io_ended=self.io_ended)

    def join(self, timeout=None):
        self._thread.join(timeout)
        return self.io_ended

    def stop(self):
        self._stop.set()
        try:
            connection=self._connection
            stop=connection.request_receive_stop if connection._resume_source_id is not None else connection.request_normal_receive_stop
            stop(connection.issue_receive_action(), finish=False)
        except TransferError:
            pass # No receiver/offline is not proof of an END; _run still performs cleanup or reports held.
        self._connection._wake_album_worker()

    def _activity(self, active):
        # The native service observer cannot be replaced by a frontend observer.
        for observer in (self._connection._activity_changed, self._activity_changed):
            if observer is None: continue
            try: observer(self, active)
            except Exception as error:
                with self._state_gate: self._activity_error = type(error).__name__

    def _wait(self, predicate, *, timeout=MAX_TTL_MS/1000):
        connection = self._connection
        deadline = time.monotonic() + timeout
        while True:
            with connection._update_condition:
                generation = connection._update_generation
            if connection._closed.is_set(): raise TransferError('file_desktop_connection_closed')
            self._require_book()
            try:
                value = predicate()
                if value: return value
            except TransferError as error:
                if str(error) != 'file_desktop_connection_busy': raise
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TransferError('file_desktop_album_reply_timeout')
            with connection._update_condition:
                if generation == connection._update_generation:
                    connection._update_condition.wait(min(remaining, 0.25))

    def _require_book(self):
        if self._book_fence is not None and not self._cleaning:
            version,started,deadline=self._book_fence
            now=time.monotonic()
            if (now<started or now>=deadline or self._book_policy is None
                    or self._book_policy.saved_book_version()!=version):
                raise TransferError('media_retention_lease_changed')

    def _command(self, operation, **options):
        connection = self._connection
        if self._media_type == 'video':
            options['media_type'] = self._media_type
        def send():
            return connection.request_source(connection.issue_receive_action(), operation, **options)
        request_id = self._wait(send)
        def received():
            state = connection.source_state(); result = state['result']
            return result if not state['pending'] and getattr(result, 'request_id', None) == request_id else None
        return self._wait(received)

    def _call(self, operation):
        # Dispatch can still own the nonblocking connection gate immediately
        # after waking us. Busy means the operation has NOT begun; retry only
        # that pre-entry boundary, never a failed/uncertain I/O operation.
        return self._wait(lambda:(operation(),))[0]

    def _prepared(self, result, *, resumed=False):
        deadline = time.monotonic() + MAX_TTL_MS/1000
        while result.state == 'preparing':
            if self._stop.wait(0.25): raise TransferError('file_desktop_album_stop_requested')
            if time.monotonic() >= deadline: raise TransferError('file_desktop_album_prepare_timeout')
            result = self._command('resume_status' if resumed else 'run_status')
        if self._stop.is_set(): raise TransferError('file_desktop_album_stop_requested')
        if result.state not in ('snapshot_ready', 'empty_ready'):
            raise TransferError('file_desktop_album_source_held')
        return result

    def _offer(self, *, resumed=False):
        while True:
            page = self._command('resume_media_page' if resumed else 'media_page')
            if page.next_cursor is None: break
        return self._command('offer_resume' if resumed else 'offer_run')

    def _end_source(self):
        resumed=self._connection._resume_source_id is not None
        result = self._command('cancel_resume' if resumed else 'cancel_run')
        deadline = time.monotonic() + MAX_TTL_MS/1000
        while not result.source_io_ended:
            if time.monotonic() >= deadline: raise TransferError('file_desktop_album_stop_timeout')
            with self._connection._update_condition:
                self._connection._update_condition.wait(0.25)
            result = self._command('resume_status' if resumed else 'run_status')
        return self._command('end_resume' if resumed else 'end_run')

    def _backup_completed_versions(self):
        """Same actual media lane, AFTER source END; no timer or UI-thread IO."""
        from hashlib import sha256
        connection = self._connection
        if not self._backup_versions:return
        from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupLocations
        from magnolie_media_retention import NativeMediaRetention
        def native_current():
            self._require_book()
            connection._ready()
            if self._stop.is_set() or connection._album_worker is not self:
                raise TransferError('file_desktop_album_stop_requested')
            # END may legitimately close the phone's data grant. This is only
            # LOCAL Saved-version copying, never another phone READ/WRITE.
            connection._preferences._fresh()
            if connection._preferences._snapshot()!=expected_policy:
                raise TransferError('file_desktop_receive_policy_changed')
            return True
        with connection._operation():
            expected_policy=connection._receiving_policy()
            prefs=connection._preferences
            with prefs._operation(), prefs._locked(), NativeMediaRetention(connection._authority.binding.native_directory) as policy:
                native_current()
                for association, expected in tuple(self._backup_versions):
                    with policy.active_copy_permit(native_current) as retention:
                        if retention is None:raise TransferError('media_backup_current_saved_book_required')
                        def current():
                            native_current();retention.require_current();return True
                        # Resolve metadata only through the exact authenticated
                        # historical version, not a current head or a UI path.
                        with connection._mappings.saved_record_lease(association,expected) as (record, _):
                            destination=record.destination
                        # Stable local peer/domain scope, not a transport epoch
                        # or source grant. Passive lookup creates no settings.
                        scope=sha256(canonical(dict(subject=prefs._subject,media_type=self._media_type))).hexdigest()
                        with NativeMediaBackupLocations(connection._authority.binding.native_directory,scope,current) as locations:
                            selected=locations.read()
                            if not selected.parents:
                                # Register the authenticated original default
                                # before any backup bytes, so local/offline
                                # recovery does not depend on a surviving peer.
                                selected=locations.choose(locations.issue_action(),selected,destination,None)
                            storage=selected.current(destination)
                            def storage_current():
                                current()
                                if locations.read()!=selected:raise TransferError('media_backup_locations_changed')
                                return True
                            create=not os.path.lexists(Path(storage.path)/'Backup')
                            with NativeMediaBackups(destination,connection._authority.protection,storage_current,
                                    create=create,storage_parent=storage) as backups:
                                backups.save_from_mappings(connection._mappings,association,expected)
                        current();self._backup_versions.remove((association,expected))

    def _lookup(self, job):
        connection=self._connection
        request_id=self._wait(lambda:connection.request_resume_lookup(connection.issue_receive_action(),job.owner,media_type=self._media_type))
        return self._wait(lambda: self._reply(request_id))

    def _reply(self, request_id):
        state=self._connection.source_state();result=state['result']
        return result if not state['pending'] and getattr(result,'request_id',None)==request_id else None

    def _receive(self):
        connection=self._connection
        while True:
            if self._stop.is_set():raise TransferError('file_desktop_album_stop_requested')
            requested=self._call(connection.request_next_chunk)
            if requested is None:break
            def chunk_arrived():
                with connection._operation():
                    return connection._require_receiver().request is None
            self._wait(chunk_arrived)
        self._call(lambda:connection.publish_received(connection.issue_receive_action()))

    def _resume(self, job):
        connection=self._connection
        # The fresh preview was never accepted. Release its real scan before
        # asking the source to open the original immutable cache/attempt.
        self._end_source()
        if connection._ended_batch is not None and connection._ended_batch.batch_end is not True:
            self._command('end_album')
        self._lookup(job)
        self._prepared(self._command('resume_run',album_id=self._album_id,
            desktop_choice=self._desktop_choice),resumed=True)
        offered=self._offer(resumed=True)
        if self._stop.is_set():raise TransferError('file_desktop_album_stop_requested')
        self._call(lambda:connection.resume_pending_offer(connection.issue_receive_action(),offered.offer_id,job.owner))
        self._receive()
        # Exact Saved receipt + live original receiver authorize END. Retiring
        # locally first would change the selected catalog job and invalidate it.
        self._end_source()
        self._call(lambda:connection.finish_saved_receive(connection.issue_receive_action(),retire_cache=True))
        self._call(self._backup_completed_versions)
        with self._state_gate:self._saved+=len(job.accepted.manifest.files)

    def _cleanup(self):
        connection = self._connection
        state = self._call(connection.source_state)
        if state['pending']: raise TransferError('file_desktop_album_command_held')
        resumed=connection._resume_source_id is not None
        job=connection._resume_lookup_selection.job if resumed else None
        stop=connection.request_receive_stop if resumed else connection.request_normal_receive_stop
        try: self._call(lambda:stop(connection.issue_receive_action()))
        except TransferError as error:
            if str(error) != ('file_desktop_resumed_receiver_required' if resumed else 'file_desktop_normal_receiver_required'): raise
        if state['run'] is not None:
            self._end_source()
        if connection._ended_batch is not None and connection._ended_batch.batch_end is not True:
            self._command('end_album')
        stopped=connection.receive_stop_state()
        if resumed and stopped is not None and stopped.owner==job.owner and stopped.state=='stopped':
            self._lookup(job)
            request_id=self._call(lambda:connection.request_resume_abandonment(connection.issue_receive_action()))
            self._wait(lambda:self._reply(request_id))

    def _run(self):
        connection = self._connection
        self._activity(True)
        with self._state_gate: self._state = 'running'
        activity=ExitStack();admitted=False
        try:
            from magnolie_media_retention import NativeMediaRetention
            policy=activity.enter_context(NativeMediaRetention(connection._authority.binding.native_directory))
            self._book_policy=policy
            self._require_book()
            lease=activity.enter_context(policy.activity(lambda:not connection._closed.is_set()))
            if lease is None:raise TransferError('media_retention_maintenance_busy')
            admitted=True
            if self._stop.is_set(): raise TransferError('file_desktop_album_stop_requested')
            result = self._prepared(self._command('batch_run', album_id=self._album_id, desktop_choice=self._desktop_choice))
            while True:
                if result.state != 'empty_ready':
                    offered = self._offer()
                    pending=self._call(lambda:connection.pending_photo_resume_candidate(connection.issue_receive_action()))
                    if pending is not None:
                        self._resume(pending)
                        if self._stop.is_set():raise TransferError('file_desktop_album_stop_requested')
                        result=self._prepared(self._command('batch_run',album_id=self._album_id,
                            desktop_choice=self._desktop_choice))
                        continue
                    review = self._call(lambda:connection.review_pending_photos(connection.issue_receive_action()))
                    if connection._desktop_session is not None:
                        first=connection._source_media_pages[0]
                        for item in review.items:
                            if item.decision in ('unchanged','copy_phone_version') and item.prior_mapping_sha256 is not None:
                                self._backup_versions.add((PhotoMappingAssociation(first.source_epoch,item.photo_id,self._media_type),item.prior_mapping_sha256))
                    new = [item for item in review.items if item.decision in ('new_photo','copy_phone_version')]
                    with self._state_gate:
                        self._known += sum(item.decision in ('unchanged', 'keep_local_edit') for item in review.items)
                        self._conflicts.extend(item for item in review.items if item.decision not in ('new_photo','copy_phone_version','unchanged','keep_local_edit'))
                    if new:
                        if len(new) != len(review.items) or any(item.decision=='copy_phone_version' for item in new):
                            request_id = self._call(lambda:connection.select_pending_new_photos(connection.issue_receive_action(),include_versions=True))
                            def selected():
                                state = connection.source_state(); value = state['result']
                                return value if not state['pending'] and getattr(value, 'request_id', None) == request_id else None
                            self._prepared(self._wait(selected)); offered = self._offer()
                        if self._stop.is_set(): raise TransferError('file_desktop_album_stop_requested')
                        self._call(lambda:connection.accept_pending_offer(connection.issue_receive_action(), offered.offer_id))
                        self._receive()
                        self._call(lambda:connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True))
                        with self._state_gate: self._saved += len(new)
                final = self._call(connection.source_state)['run'].batch_end
                self._end_source()
                self._call(self._backup_completed_versions)
                if self._stop.is_set():
                    if final is False: self._command('end_album')
                    with self._state_gate: self._state = 'canceled'
                    break
                if final is True:
                    with self._state_gate: self._state = 'conflicts' if self._conflicts else 'complete'
                    break
                if final is not False: raise TransferError('file_desktop_album_completion_unknown')
                result = self._prepared(self._command('next_batch'))
        except Exception as error:
            cleanup_error = None
            self._cleaning=True # Retired book blocks new work, never the owned END/drain.
            try:
                if admitted:self._cleanup()
            except Exception as failure: cleanup_error = str(failure)
            with self._state_gate:
                self._state = 'canceled' if self._stop.is_set() and cleanup_error is None else 'held'
                self._error = cleanup_error or str(error)
        finally:
            try:activity.close()
            finally:
                with connection._gate:
                    if connection._album_worker is self: connection._album_worker = None
                self._ended.set() # All actual worker I/O has returned, not just a cancel request.
                self._activity(False)


class NativePhotoDesktopSession:
    """One real Organizer action lane per authenticated connection.

    UI/IPC returns metadata immediately. All folder/policy/control/source I/O
    and the actual album worker remain on owned native background lanes.
    No action is scheduled by construction, pairing or status inspection.
    """
    READ_WAIT_SECONDS = 120
    AUTO_TICK_SECONDS = 1

    def __init__(self, connection):
        self.connection=connection; self._lock=threading.RLock()
        self._thread=None; self._running=False; self._stop=threading.Event(); self._worker=None
        self._state='off'; self._error=None; self._enabled=False
        self._active_media='images'
        self._destination=None; self._albums=[]; self._permission=None
        self._disable_pending=False
        self._video_disable_pending=False
        self._video_supported=False; self._video_enabled=False
        self._video_destination=None; self._video_albums=[]; self._video_permission=None
        self._mode='manual';self._pending_mode=None;self._automatic_paused=False
        self._shared_schedule_token=None;self._shared_automatic=False
        self._timer=None;self._sync_active=False
        self._recovery=[];self._recovery_result=None
        self._separate_animations=False
        self._separate_captures=False
        self._schedule=PhotoSyncSchedule(self._schedule_scope,lambda:time.monotonic_ns()//1_000_000)

    def snapshot(self):
        with self._lock:
            value=dict(available=True,state=self._state,error=self._error,enabled=self._enabled,mode=self._pending_mode or self._mode,
                destination=self._destination,albums=[dict(album) for album in self._albums],permission=self._permission,
                busy=self._running,automatic_supported=True,active_media=self._active_media)
            value.update(recovery_supported=True,recovery=[dict(item) for item in self._recovery],recovery_result=self._recovery_result)
            value.update(animation_grouping_supported=True,separate_animations=self._separate_animations)
            value.update(capture_grouping_supported=True,separate_own_recordings=self._separate_captures)
            if self._video_supported:
                value.update(video_supported=True,video_enabled=self._video_enabled,video_destination=self._video_destination,
                    video_albums=[dict(album) for album in self._video_albums],video_permission=self._video_permission)
            worker=self._worker
        if worker is not None:
            progress=worker.progress()
            value.update(saved_files=progress['saved_files'],known_files=progress['known_files'],conflicts=len(progress['conflicts']))
        return value

    def _notify(self):
        callback=self.connection._status_changed
        if callback is not None:
            try:callback()
            except Exception:pass # A failed frontend cannot replace native ownership.

    def start(self, operation, album_id=None, *, schedule_run=None, job_owner=None,historical_choice=None,destination_path=None,video_album_id=None):
        if operation not in ('enable','disable','request_read','discover','sync','stop','mode_manual','mode_automatic','automatic','resume_automatic',
                'inspect_recovery','recover_saved','repair_receipt','animations_separate','animations_together','captures_separate','captures_together',
                'videos_enable','videos_disable','videos_request_read','videos_discover','videos_sync','videos_destination','videos_default_destination',
                'photos_destination','photos_default_destination','sync_selected','sync_shared'):
            raise TransferError('photo_sync_invalid_action')
        if (video_album_id is not None and (operation!='sync_selected' or type(video_album_id) is not str)
                or operation=='sync_selected' and (album_id is not None and type(album_id) is not str or album_id is None and video_album_id is None)):
            raise TransferError('photo_sync_invalid_action')
        if ((operation in ('videos_destination','photos_destination')) != (destination_path is not None)
                or destination_path is not None and (type(destination_path) is not str or not destination_path or len(destination_path)>4096)):
            raise TransferError('photo_sync_invalid_action')
        if operation in ('animations_separate','animations_together','captures_separate','captures_together'):
            if type(historical_choice) is not str or historical_choice!='keep_existing':
                raise TransferError('photo_preferences_historical_layout_choice_required')
        elif historical_choice is not None:raise TransferError('photo_sync_invalid_action')
        if ((operation in ('recover_saved','repair_receipt')) != (job_owner is not None)
                or job_owner is not None and (type(job_owner) is not str or re.fullmatch('[0-9a-f]{32}',job_owner) is None)):
            raise TransferError('photo_sync_invalid_action')
        with self._lock:
            running=self._running
            if operation.startswith('mode_') and running:
                self._pending_mode=operation.removeprefix('mode_')
                self._schedule.set_mode(self._pending_mode) # Stop repeats now; commit UI mode after real I/O END.
            elif operation in ('stop','disable','videos_disable') and running:
                self._disable_pending=operation=='disable' or self._disable_pending
                self._video_disable_pending=operation=='videos_disable' or self._video_disable_pending
                self._automatic_paused=True
                self._stop.set(); worker=self._worker; self._state='stopping'
                if worker is not None:worker.stop()
                self.connection._wake_album_worker()
            elif operation=='stop':
                self._automatic_paused=True;self._state='canceled'
                return self.snapshot()
            else:
                if running:raise TransferError('photo_sync_busy')
                if operation=='sync' and not any(album['album_id']==album_id for album in self._albums):
                    raise TransferError('file_desktop_source_album_not_current')
                if operation=='videos_sync' and not any(album['album_id']==album_id for album in self._video_albums):
                    raise TransferError('file_desktop_source_album_not_current')
                if operation=='sync_selected':
                    if album_id is not None and not any(album['album_id']==album_id for album in self._albums):
                        raise TransferError('file_desktop_source_album_not_current')
                    if video_album_id is not None and (not self._video_enabled or not any(album['album_id']==video_album_id for album in self._video_albums)):
                        raise TransferError('file_desktop_source_album_not_current')
                if operation=='automatic' and (schedule_run is None or self._schedule.active is not schedule_run
                        or self._schedule.mode!='automatic'):
                    raise TransferError('photo_sync_invalid_action')
                if operation in ('sync','videos_sync','sync_selected','sync_shared'):schedule_run=self._schedule.request_now()
                self._stop.clear(); self._error=None; self._state=operation;self._recovery_result=None
                if not operation.startswith('mode_'):
                    self._active_media='video' if operation.startswith('videos_') or operation=='sync_selected' and album_id is None else 'images'
                if operation not in ('automatic','inspect_recovery','recover_saved','repair_receipt','animations_separate','animations_together',
                        'captures_separate','captures_together','videos_destination','videos_default_destination','photos_destination','photos_default_destination'):
                    self._automatic_paused=False
                self._running=True
                arguments=(operation,album_id,schedule_run,job_owner,historical_choice,destination_path)
                if operation=='sync_selected':arguments+=(video_album_id,)
                self._thread=threading.Thread(target=self._run,args=arguments,
                    name='magnolie-photo-desktop-action',daemon=True)
                try:self._thread.start()
                except BaseException:
                    self._running=False
                    if schedule_run is not None:self._schedule.finished(schedule_run)
                    raise
        self._notify()
        return self.snapshot()

    def join(self, timeout=None):
        thread=self._thread
        if thread is not None:thread.join(timeout)
        timer=self._timer
        if self.connection._closed.is_set() and timer is not None:timer.join(timeout)
        return (thread is None or not thread.is_alive()) and (not self.connection._closed.is_set() or timer is None or not timer.is_alive())

    def _schedule_scope(self):
        # A schedule observation must not run _local()/mapping availability
        # concurrently with native source/control I/O. Busy is simply not due,
        # never a new consent epoch or permission to inspect held cache leases.
        connection=self.connection
        if not connection._gate.acquire(blocking=False):return None
        try:return self._schedule_scope_owned()
        finally:connection._gate.release()

    def _schedule_scope_owned(self):
        # Scheduling is not READ authority. Its generation is the authenticated
        # source-policy witness; every scan/file still obtains fresh native grants.
        # Do not take the UI lock from the schedule's native-scope callback.
        transport=self.connection._media_transport
        if transport is not None:
            sending=self.connection._media_sending_state or {}
            outgoing=next((token for kind in ('images','video')
                if sending.get('photos' if kind=='images' else 'videos') is True
                and (token:=transport.intent_for(kind,to_phone=True)) is not None),None)
            if outgoing is not None:
                try:
                    binding=self.connection._controls.binding('0'*64,sender_is_local=True)
                    if binding is not None:
                        from hashlib import sha256
                        return NativePhotoSyncScope(binding,sha256(canonical(outgoing.body)).hexdigest(),self.connection)
                except (TransferError,OSError):return None
        status=self.connection._source_status
        if not self._enabled or status is None or not status.enabled or not status.associated or status.repair_pending:return None
        try:return NativePhotoSyncScope(self.connection._receive_binding(),status.version,self.connection)
        except (TransferError,OSError):return None

    def shared_settings_changed(self):
        """Only actual matched native transport observations call this hook."""
        from magnolie_media_sync import effective
        transport=self.connection._media_transport
        sending=self.connection._media_sending_state or {}
        token=next((value for kind in ('images','video')
            if sending.get('photos' if kind=='images' else 'videos') is True
            and (value:=transport.intent_for(kind,to_phone=True)) is not None),None) if transport is not None else None
        automatic=token is not None and effective(token.body)['auto_mode']=='wifi'
        with self._lock:
            previous=self._shared_schedule_token
            if previous is token:return # Duplicate echo cannot undo local Stop/manual mode.
            self._shared_schedule_token=token;self._shared_automatic=automatic
            self._mode='automatic' if automatic else 'manual'
        # Same token/echo never clears _automatic_paused after explicit Stop.
        self._schedule.set_mode('automatic' if automatic else 'manual')
        self._ensure_timer()

    def _ensure_timer(self):
        with self._lock:
            if ((not self._enabled and not self._shared_automatic) or self._mode!='automatic' or self.connection._closed.is_set()
                    or self._timer is not None and self._timer.is_alive()):return
            self._timer=threading.Thread(target=self._automatic_loop,name='magnolie-photo-schedule',daemon=True)
            self._timer.start()

    def _automatic_loop(self):
        try:
            while not self.connection._closed.wait(self.AUTO_TICK_SECONDS):
                with self._lock:
                    if self._running or self._automatic_paused or not self._enabled and not self._shared_automatic:continue
                    if self._shared_automatic and self.connection._native_wifi_current() is not True:continue
                    run=self._schedule.take_due()
                    if run is None:continue
                    try:self.start('automatic',schedule_run=run)
                    except Exception:
                        self._schedule.finished(run);self._automatic_paused=True
        except Exception as error:
            with self._lock:self._state='held';self._error=str(error);self._automatic_paused=True
            self._notify()
        finally:self._schedule.close() # Active token remains held until its real action END.

    def _sync_activity(self, active):
        self._sync_active=active
        observer=self.connection._activity_changed
        if observer is not None:
            try:observer(self,active)
            except Exception:pass

    def _apply_mode(self, mode):
        if self._shared_schedule_token is not None:
            # Shared mode is its own protected register, not receiving consent.
            # A PC-only user must not enable RECEIVE just to choose manual/WLAN.
            with self.connection._operation():
                transport=self.connection._media_transport
                transport.change('auto_mode','wifi' if mode=='automatic' else 'manual')
                transport.send_settings()
                self.shared_settings_changed() # Invalidate scheduling until the new exact ACK/echo.
            with self._lock:self._pending_mode=None
            return
        prefs=self.connection._preferences
        changed=prefs.set_mode(prefs.issue_action(),prefs.read(),mode)
        with self._lock:self._mode=changed.mode;self._pending_mode=None
        self._schedule.set_mode(mode)

    def _wait(self, generation, seconds=.25):
        if self._stop.is_set():raise TransferError('photo_sync_action_stopped')
        self.connection._ready()
        with self.connection._update_condition:
            if self.connection._update_generation==generation:
                self.connection._update_condition.wait(seconds)

    def _command(self, operation, **options):
        deadline=time.monotonic()+MAX_TTL_MS/1000; sent=False
        while time.monotonic()<deadline:
            generation=self.connection._update_generation
            if self._stop.is_set():raise TransferError('photo_sync_action_stopped')
            try:
                if not sent:
                    self.connection.request_source(self.connection.issue_receive_action(),operation,**options)
                    sent=True
                state=self.connection.source_state()
                if not state['pending']:return state
            except TransferError as error:
                if str(error) not in ('file_control_receiver_command_not_ready','file_desktop_source_controls_pending','file_desktop_connection_busy'):
                    raise
            self._wait(generation)
        raise TransferError('photo_sync_native_reply_timeout')

    def _local_enabled(self, enabled):
        connection=self.connection; preferences=connection._preferences; before=preferences.read()
        if enabled and (before.policy is None or before.policy.mapping_store is None or before.policy.job_catalog is None):
            from magnolie_media_storage_bootstrap import NativeMediaStorageBootstrap
            bootstrap=NativeMediaStorageBootstrap(connection._authority)
            try:bootstrap.prepare(bootstrap.issue_action(),before)
            finally:bootstrap.close()
            before=preferences.read()
        policy=before.policy
        if enabled and (before.direction!='phone_to_desktop'
                or policy is not None and (policy.phone_to_pc_delete or policy.pc_to_phone_delete)):
            raise TransferError('file_desktop_album_options_unavailable')
        choice=None
        if enabled and (policy is None or policy.destination is None):
            choice=connection._destination.choose_default(connection._destination.issue_action())
        if policy is None or policy.enabled is not enabled or not before.associated:
            options={} if policy is not None else dict(include_videos=False,separate_animations=False,
                separate_own_recordings=False,direction='phone_to_desktop')
            before=preferences.configure(preferences.issue_action(),before,enabled=enabled,mode=before.mode,
                phone_to_pc_delete=policy.phone_to_pc_delete if policy is not None else False,
                destination_choice=choice,**options)
        with self._lock:
            self._enabled=enabled;self._mode=before.mode;self._separate_animations=before.separate_animations
            self._separate_captures=before.separate_own_recordings
            self._destination=before.policy.destination.path if before.policy and before.policy.destination else None
            self._video_enabled=bool(before.policy and before.policy.videos and before.policy.videos.enabled)
            self._video_destination=before.policy.videos.destination.path if before.policy and before.policy.videos and before.policy.videos.destination else None
        self._schedule.set_mode(before.mode if enabled else 'manual')
        connection.send_controls()

    def _local_video_enabled(self, enabled):
        connection=self.connection; preferences=connection._preferences; before=preferences.read()
        if enabled:
            if not connection._video_data_handlers_ready or not connection._authority.video_available():
                raise TransferError('file_desktop_video_data_join_unavailable')
            if (before.policy is None or not before.policy.enabled or not before.associated
                    or before.direction!='phone_to_desktop' or before.policy.mapping_store is None or before.policy.job_catalog is None
                    or before.policy.phone_to_pc_delete or before.policy.pc_to_phone_delete):
                raise TransferError('file_desktop_album_options_unavailable')
            # Restore only the already enabled/associated base session. This
            # never enables an absent/off photo policy or changes its mode.
            self._local_enabled(True)
            before=preferences.read()
        chooser=None
        try:
            choice=None
            if enabled and (before.policy.videos is None or before.policy.videos.destination is None):
                from magnolie_photo_destination import NativeVideoDestinationController
                chooser=NativeVideoDestinationController(connection._authority)
                choice=chooser.choose_default(chooser.issue_action())
            saved=preferences.set_video_scope(preferences.issue_action(),before,enabled=enabled,destination_choice=choice)
        finally:
            if chooser is not None:chooser.close()
        with self._lock:
            self._video_enabled=bool(saved.policy.videos and saved.policy.videos.enabled)
            self._video_destination=saved.policy.videos.destination.path if saved.policy.videos and saved.policy.videos.destination else None
            if enabled:self._video_supported=True
            if not enabled:self._video_albums=[];self._video_permission=None
        return saved

    def _prepare_video(self):
        connection=self.connection
        if not connection._video_data_handlers_ready:
            raise TransferError('file_desktop_video_data_join_unavailable')
        connection._require_video_metadata_scope()
        state=self._command('status')
        if state['status'].repair_pending:raise TransferError('photo_sync_source_repair_pending')
        # Metadata tickets alone are not a data-ACK witness. This exact current
        # native binding must exist BEFORE the positive session configuration.
        connection._receive_binding(media_type='video')
        self._command('configure_videos',enabled=True) # Required even for saved ON/idempotent policy.
        with self._lock:self._video_supported=True

    def _retain_backup_destination(self,before,media_type,previous,selected):
        if previous is None or previous==selected:return
        connection=self.connection;preferences=connection._preferences
        from magnolie_media_backups import NativeMediaBackupLocations
        from hashlib import sha256
        scope=sha256(canonical(dict(subject=preferences._subject,media_type=media_type))).hexdigest()
        def current():
            connection._ready()
            if preferences.read()!=before:raise TransferError('photo_preferences_cas_conflict')
            return True
        with NativeMediaBackupLocations(connection._authority.binding.native_directory,scope,current) as locations:
            retained=locations.read()
            if retained.parents and previous not in retained.parents:
                locations.choose(locations.issue_action(),retained,previous,retained.selected)

    def _choose_photo_destination(self,path):
        connection=self.connection;preferences=connection._preferences;before=preferences.read();policy=before.policy
        if policy is None or policy.enabled or not before.associated:
            raise TransferError('photo_preferences_destination_choice_requires_off')
        chooser=connection._destination
        choice=(chooser.choose_default(chooser.issue_action()) if path is None else chooser.choose_custom(chooser.issue_action(),path))
        self._retain_backup_destination(before,'images',policy.destination,choice.destination)
        saved=preferences.set_photo_destination(preferences.issue_action(),before,choice,historical_choice='keep_existing')
        with self._lock:
            self._destination=saved.policy.destination.path;self._state='off';self._albums=[];self._permission=None

    def _choose_video_destination(self, path):
        connection=self.connection;preferences=connection._preferences;before=preferences.read()
        if not connection._video_data_handlers_ready or not connection._authority.video_available():
            raise TransferError('file_desktop_video_data_join_unavailable')
        if (before.policy is None or not before.policy.enabled or not before.associated
                or before.policy.videos is not None and before.policy.videos.enabled):
            raise TransferError('video_preferences_destination_choice_requires_off')
        from magnolie_photo_destination import NativeVideoDestinationController
        chooser=NativeVideoDestinationController(connection._authority)
        try:
            choice=(chooser.choose_default(chooser.issue_action()) if path is None else chooser.choose_custom(chooser.issue_action(),path))
            previous=before.policy.videos.destination if before.policy.videos is not None else None
            self._retain_backup_destination(before,'video',previous,choice.destination)
            saved=preferences.set_video_scope(preferences.issue_action(),before,enabled=False,destination_choice=choice,historical_choice='keep_existing')
        finally:chooser.close()
        with self._lock:
            self._video_supported=True;self._video_enabled=False
            self._video_destination=saved.policy.videos.destination.path
            self._state='videos_off';self._video_albums=[];self._video_permission=None

    def _disable_video(self):
        saved=self._local_video_enabled(False) # Local consent closes before any remote output or failure.
        if saved.policy.enabled:
            self._command('status')
            self._command('configure_videos',enabled=False)
        with self._lock:self._state='videos_off';self._active_media='video'

    def _discover(self, media_type='images'):
        options={'media_type':'video'} if media_type=='video' else {}
        state=self._command('discover',**options)
        while state['catalog'].next_cursor is not None:state=self._command('catalog_page',**options)
        albums=[dict(album_id=album.album_id,display_name=album.display_name,kind=album.kind,
            visible_images=album.visible_images,needs_choice=album.needs_choice) for album in state['albums']]
        with self._lock:
            if media_type=='video':self._video_albums=albums
            else:self._albums=albums
            self._state='albums' if state['catalog'].coverage!='none' else 'permission_required'

    def _run(self, operation, album_id, schedule_run=None, job_owner=None,historical_choice=None,destination_path=None,video_album_id=None):
        syncing=operation in ('sync','videos_sync','sync_selected','sync_shared','automatic')
        if syncing:self._sync_activity(True)
        try:
            book_fence=None
            if syncing:
                from magnolie_media_retention import maintain_native_media_trash
                maintain_native_media_trash(self.connection._authority.binding.native_directory,
                    lambda:not self._stop.is_set() and not self.connection._closed.is_set())
            if operation in ('sync_selected','sync_shared'):
                from magnolie_media_retention import NativeMediaRetention
                with NativeMediaRetention(self.connection._authority.binding.native_directory) as policy:
                    started=time.monotonic()
                    book_fence=(policy.saved_book_version(),started,started+policy.MAX_ACTIVE_COPY_SECONDS)
            if operation in ('enable','resume_automatic'):
                if operation=='resume_automatic':
                    before=self.connection._preferences.read();policy=before.policy
                    if (policy is None or not before.associated or not policy.enabled or before.mode!='automatic'
                            or not before.destination_available or policy.mapping_store is None or policy.job_catalog is None
                            or before.direction!='phone_to_desktop'
                            or policy.phone_to_pc_delete or policy.pc_to_phone_delete):
                        raise TransferError('photo_sync_resume_consent_changed')
                    with self._lock:
                        self._enabled=True;self._mode=before.mode;self._destination=policy.destination.path
                        self._separate_animations=before.separate_animations
                        self._separate_captures=before.separate_own_recordings
                        self._video_enabled=bool(policy.videos and policy.videos.enabled)
                        self._video_destination=policy.videos.destination.path if policy.videos and policy.videos.destination else None
                    self._schedule.set_mode(before.mode)
                    self.connection.send_controls()
                else:self._local_enabled(True)
                state=self._command('status'); status=state['status']
                if status.repair_pending:raise TransferError('photo_sync_source_repair_pending')
                if not status.enabled or not status.associated:
                    if operation=='resume_automatic':raise TransferError('photo_sync_source_consent_changed')
                    self._command('configure',enabled=True,kinds=tuple(sorted(source_messages.KINDS)))
                self._discover() # Existing OS READ needs no new prompt.
                if self.snapshot()['state']=='permission_required' and operation=='enable':
                    state=self._command('request_read')
                    with self._lock:self._permission=state['result'].state
                    self._notify()
                    deadline=time.monotonic()+self.READ_WAIT_SECONDS
                    while time.monotonic()<deadline:
                        self._discover() # Actual current coverage, never reply-as-READ.
                        self._notify()
                        if self.snapshot()['state']!='permission_required':break
                        self._wait(self.connection._update_generation,2)
            elif operation=='disable':
                self._local_enabled(False)
                with self._lock:self._state='off'
            elif operation=='request_read':
                state=self._command('request_read')
                with self._lock:self._permission=state['result'].state; self._state='permission_required'
            elif operation=='discover':self._discover()
            elif operation in ('videos_enable','videos_discover','videos_request_read'):
                if operation=='videos_enable':self._local_video_enabled(True)
                self._prepare_video()
                if operation=='videos_request_read':
                    state=self._command('request_read',media_type='video')
                    with self._lock:self._video_permission=state['result'].state
                self._discover('video') # Actual native coverage, never a permission reply as READ.
            elif operation=='videos_disable':self._disable_video()
            elif operation in ('videos_destination','videos_default_destination'):self._choose_video_destination(destination_path)
            elif operation in ('photos_destination','photos_default_destination'):self._choose_photo_destination(destination_path)
            elif operation in ('animations_separate','animations_together','captures_separate','captures_together'):
                if self._stop.is_set():raise TransferError('photo_sync_action_stopped')
                setter=self.connection.set_future_animation_layout if operation.startswith('animations_') else self.connection.set_future_capture_layout
                changed=setter(self.connection.issue_receive_action(),
                    separate=operation.endswith('_separate'),historical_choice=historical_choice)
                with self._lock:
                    self._separate_animations=changed.separate_animations
                    self._separate_captures=changed.separate_own_recordings;self._state='layout'
            elif operation in ('inspect_recovery','recover_saved','repair_receipt'):
                if self._stop.is_set():raise TransferError('photo_sync_action_stopped')
                if operation=='recover_saved':
                    self.connection.recover_saved_confirmation(self.connection.issue_receive_action(),job_owner)
                elif operation=='repair_receipt':
                    self.connection.repair_saved_mapping_receipt(self.connection.issue_receive_action(),job_owner)
                if self._stop.is_set():raise TransferError('photo_sync_action_stopped')
                recovery=self.connection.inspect_photo_recovery(self.connection.issue_receive_action())
                with self._lock:
                    self._recovery=list(recovery);self._state='recovery'
                    self._recovery_result={'recover_saved':'confirmation_sent','repair_receipt':'receipt_repaired'}.get(operation)
            elif operation.startswith('mode_'):
                self._apply_mode(operation.removeprefix('mode_'))
                with self._lock:self._state='albums' if self._albums else 'permission_required'
            elif syncing:
                media_types=['video'] if operation=='videos_sync' else ['images']
                if operation=='sync_shared' or operation=='automatic' and self._shared_automatic:
                    transport=self.connection._media_transport
                    media_types=[kind for kind in ('images','video') if transport is not None and (
                        transport.intent_for(kind) is not None or transport.intent_for(kind,to_phone=True) is not None)]
                    if not media_types:raise TransferError('media_source_current_intent_required')
                if operation=='sync_selected':media_types=(['images'] if album_id is not None else [])+(['video'] if video_album_id is not None else [])
                if (operation=='automatic' and 'video' not in media_types and self._video_enabled and self.connection._video_data_handlers_ready
                        and self.connection._authority.video_available()):media_types.append('video')
                for media_type in media_types:
                    if self._stop.is_set():break
                    if book_fence is not None:
                        with NativeMediaRetention(self.connection._authority.binding.native_directory) as policy:
                            if policy.saved_book_version()!=book_fence[0]:raise TransferError('media_retention_lease_changed')
                    with self._lock:self._active_media=media_type
                    transport=self.connection._media_transport
                    outgoing=transport.intent_for(media_type,to_phone=True) if transport is not None else None
                    if outgoing is not None:
                        if operation=='automatic' and (not self._shared_automatic or self._shared_schedule_token is not outgoing):
                            raise TransferError('media_source_wifi_automatic_composition_required')
                        worker=self.connection.start_mapped_media_worker(self.connection.issue_receive_action(),kind=media_type,
                            book_fence=book_fence,automatic=operation=='automatic')
                        with self._lock:self._worker=worker;self._state='syncing'
                        self._notify()
                        while not worker.join(.25):
                            if self._stop.is_set():worker.stop()
                        progress=worker.progress()
                        with self._lock:self._state=progress['state'];self._error=progress['error']
                        if progress['state']!='complete':break
                        if not outgoing.requested_for(media_type):continue # PC-only never requests phone READ.
                        if operation=='automatic' and not self._enabled:
                            raise TransferError('media_source_shared_incoming_review_required')
                    if media_type=='video':self._prepare_video()
                    catalog=self.connection._source_catalog
                    if operation in ('automatic','sync_shared') or media_type=='video' or catalog is None or catalog.media_type!=media_type:
                        self._discover(media_type)
                    current=self._video_albums if media_type=='video' else self._albums
                    selected_album=video_album_id if operation=='sync_selected' and media_type=='video' else album_id
                    if operation=='sync_shared' and any(album['needs_choice'] for album in current):
                        raise TransferError('file_desktop_source_album_choice_required')
                    albums=[album['album_id'] for album in current if not album['needs_choice']] if operation in ('automatic','sync_shared') else [selected_album]
                    if any(selected not in {album['album_id'] for album in current} for selected in albums):
                        raise TransferError('file_desktop_source_album_not_current')
                    complete=True
                    for selected in albums:
                        if self._stop.is_set():break
                        options=dict(media_type=media_type,activity_changed=lambda owner,active:self._notify())
                        if book_fence is not None:options['book_fence']=book_fence
                        worker=self.connection.start_album_worker(self.connection.issue_receive_action(),selected,True,**options)
                        with self._lock:self._worker=worker; self._state='syncing'
                        self._notify()
                        while not worker.join(.25):
                            if self._stop.is_set():worker.stop()
                        progress=worker.progress()
                        with self._lock:
                            self._state=('syncing' if operation=='sync_selected' and media_type!=media_types[-1] and progress['state']=='complete' else progress['state'])
                            self._error=progress['error']
                        if progress['state']!='complete':complete=False;break
                    if not complete:break
                if operation=='sync_selected' and self._stop.is_set():
                    with self._lock:
                        if self._state in ('stopping','syncing','albums','discover'):self._state='canceled'
        except Exception as error:
            with self._lock:self._state='held';self._error=str(error)
        finally:
            try:
                with self._lock:
                    disable=self._disable_pending;self._disable_pending=False
                    disable_video=self._video_disable_pending;self._video_disable_pending=False
                if disable:
                    self._local_enabled(False)
                    with self._lock:self._state='off'
                if disable_video:
                    self._stop.clear() # Worker has really ended; only decrease metadata follows.
                    self._disable_video()
                if not disable and self._pending_mode is not None:self._apply_mode(self._pending_mode)
            except Exception as error:
                with self._lock:self._state='held';self._error=str(error)
            if syncing:self._sync_activity(False)
            if schedule_run is not None:
                try:self._schedule.finished(schedule_run)
                except TransferError as error:
                    with self._lock:self._state='held';self._error=str(error)
            with self._lock:
                self._running=False
                if self._state in ('held','conflicts','canceled'):self._automatic_paused=True
            self._notify()
            self._ensure_timer()


@dataclass(frozen=True)
class _NativeDesktopPhotoSelection:
    manifest: object
    source_run_id: str
    file_ids: tuple
    entries: tuple
    source_epoch: str
    media_type: str
    insertion_witness: bool
    mapping_snapshot: object
    version_parents: tuple = ()


@dataclass
class _NativeDesktopSourceCommand:
    ticket: object
    message: dict
    command: source_messages.SourceCommand
    remote_witness: tuple
    sent: bool = False
    album_kind: str | None = None
    video_negotiated: bool = False
    video_policy_version: str | None = None
