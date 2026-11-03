"""Native desktop file-control owner; no automatic transfer or scheduler.

The receive data/UI/recovery union is not ready: every outgoing data grant stays
OFF, including when a protected enabled preference exists. Construction itself
does not send packets, create preferences or start any worker.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import threading
import time
import uuid

from magnolie_file_control import KIND, MAX_TTL_MS, FileControlPacket, NativeFileControlSession
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_file_sources import _body
import magnolie_file_sources as source_messages
from magnolie_file_media import parse_media_page, correlate_media_pages
from magnolie_file_media_history import NativeMediaHistory
from magnolie_file_transfer import TransferError
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_offer import KIND as OFFER, validate_offer
from magnolie_file_chunk_message import RESULT as CHUNK
from magnolie_file_receive import NativeFileReceiveOperation, NativeReceiveStartError
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_mappings import ProtectedPhotoMappings, PhotoMappingAssociation
from magnolie_photo_destination import NativePhotoDestinationController, NativePhotoDestinationAction
from magnolie_telefon import now_ms, canonical, strict_json


def is_reserved_file_message(message):
    return isinstance(message, dict) and isinstance(message.get('kind'), str) and message['kind'].startswith('file_transfer.')


class NativeDesktopFileConnection:
    # Private native release gate, never a serialized setting or UI preference.
    # Full data/recovery/baseline and frontend acceptance is still outstanding.
    _data_handlers_ready = False

    def __init__(self, authority, channel, *, released=lambda owner:None):
        if (type(authority) is not NativeDesktopFileAuthority or channel is not authority.native_channel
                or not callable(getattr(channel, 'send', None)) or not callable(released)):
            raise TransferError('file_desktop_native_owner_required')
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
        self._source_control_required = None
        self._source_offer = None
        self._source_media_pages = ()
        self._source_media_entries = None
        self._preferences = ProtectedPhotoPreferences(authority)
        self._mappings = ProtectedPhotoMappings(authority)
        self._destination = NativePhotoDestinationController(authority)
        try:
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
        return self._preferences.local_grant(self._data_handlers_ready)

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
        with self._operation(incoming=True):
            if self._data_handlers_ready and message.get('kind') in (source_messages.RESULT, source_messages.CATALOG,
                    source_messages.PERMISSION_RESULT, source_messages.RUN_RESULT, source_messages.MEDIA):
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

    def issue_receive_action(self):
        self._ready()
        return NativePhotoDestinationAction(self, lambda: time.monotonic_ns()//1_000_000)

    def source_state(self):
        """Native UI metadata only; no serialized status/album grants OS READ."""
        with self._operation():
            return dict(status=self._source_status, catalog=self._source_catalog, albums=tuple(self._source_albums.values()),
                        run=self._source_run, result=self._source_result, pending=self._source_pending is not None,
                        media_pages=self._source_media_pages, media_manifest_correlated=self._source_media_entries is not None)

    def _source_command_authority(self, pending, clock):
        self._receiving_policy()
        if not self._controls.receiver_command_current(pending.ticket):
            raise TransferError('file_desktop_source_command_authority_changed')
        _body(pending.message, source_messages.REQUEST, clock())

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

    def request_source(self, action, operation, *, enabled=None, kinds=(), album_id=None, desktop_choice=None, clock=now_ms):
        """One explicit native source command, not a personal queue or scheduler.
        Native receive consent/actual control echo may bootstrap source send-OFF.
        Exact remote catalog selections remain metadata, never an Android read grant.
        """
        self._take_action(action)
        with self._operation():
            self._receiving_policy()
            if self._source_pending is not None:
                raise TransferError('file_desktop_source_command_busy')
            if self._source_control_required is not None:
                witness = self._controls.remote_control_witness()
                required = self._source_control_required
                if witness is None or witness[0] != required[0] or witness[1] <= required[1]:
                    raise TransferError('file_desktop_source_controls_pending')
            options = {}
            if operation != 'status':
                if self._source_status is None or self._source_status.repair_pending:
                    raise TransferError('file_desktop_source_status_required')
                options['expected_version'] = self._source_status.version
            if operation != 'configure' and (enabled is not None or kinds != ()):
                raise TransferError('file_desktop_source_invalid_options')
            if operation != 'run' and (album_id is not None or desktop_choice is not None):
                raise TransferError('file_desktop_source_invalid_options')
            if operation == 'configure':
                if self._run is not None or self._source_run is not None:
                    raise TransferError('file_desktop_receive_run_held')
                options.update(enabled=enabled, kinds=kinds)
            elif operation in ('discover', 'request_read', 'run', 'catalog_page'):
                if not self._source_status.enabled or not self._source_status.associated:
                    raise TransferError('file_desktop_source_not_configured')
                if operation == 'catalog_page':
                    if self._source_catalog is None or self._source_catalog.next_cursor is None:
                        raise TransferError('file_desktop_source_catalog_not_current')
                    options.update(catalog_id=self._source_catalog.catalog_id, after=self._source_catalog.next_cursor)
                elif operation == 'run':
                    if self._run is not None or self._source_run is not None:
                        raise TransferError('file_desktop_receive_run_held')
                    album = self._source_albums.get(album_id)
                    if (album is None or self._source_catalog is None or type(desktop_choice) is not bool
                            or album.needs_choice and not desktop_choice):
                        raise TransferError('file_desktop_source_album_not_current')
                    options.update(catalog_id=self._source_catalog.catalog_id, album_id=album.album_id, desktop_choice=desktop_choice)
            elif operation in ('run_status', 'cancel_run', 'offer_run', 'media_page'):
                if self._source_run is None:
                    raise TransferError('file_desktop_source_run_not_current')
                if operation in ('offer_run', 'media_page') and (self._run is not None or self._offer is not None
                        or self._source_run.state != 'snapshot_ready' or not self._source_run.source_io_ended
                        or self._source_run.version != self._source_status.version
                        or not self._source_status.enabled or not self._source_status.associated):
                    raise TransferError('file_desktop_source_offer_not_ready')
                if operation == 'media_page':
                    after = self._source_media_pages[-1].next_cursor if self._source_media_pages else 0
                    if after is None:
                        raise TransferError('file_desktop_source_media_pages_complete')
                    options['after'] = after
                elif operation == 'offer_run' and self._source_media_pages and self._source_media_pages[-1].next_cursor is not None:
                    raise TransferError('file_desktop_source_media_pages_incomplete')
                options['run_id'] = self._source_run.run_id
            message = source_messages.create_command(operation, now=clock(), **options)
            command = source_messages.parse_command(message, now=clock())
            ticket = self._controls.receiver_command_ticket()
            self._source_pending = _NativeDesktopSourceCommand(ticket, message, command, self._controls.receiver_command_witness(ticket))
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
        if command.operation in ('status', 'configure'):
            result = source_messages.parse_result(message, expected_request_id=command.request_id,
                expected_operation=command.operation, now=at)
            old = self._source_status
            if old is not None and (result.revision < old.revision or result.revision == old.revision
                    and (result.version, result.enabled, result.associated, result.kinds) != (old.version, old.enabled, old.associated, old.kinds)):
                raise TransferError('file_desktop_source_status_rollback')
        elif command.operation in ('discover', 'catalog_page'):
            result = source_messages.parse_catalog(message, expected_request_id=command.request_id, expected_operation=command.operation,
                expected_version=command.expected_version, expected_catalog_id=command.catalog_id, expected_after=command.after, now=at)
            if command.operation == 'catalog_page' and any(album.album_id in self._source_albums for album in result.albums):
                raise TransferError('file_desktop_source_duplicate_album')
        elif command.operation == 'request_read':
            result = source_messages.parse_permission_result(message, expected_request_id=command.request_id,
                expected_version=command.expected_version, now=at)
        elif command.operation == 'media_page':
            first = self._source_media_pages[0] if self._source_media_pages else None
            result = parse_media_page(message, expected_request_id=command.request_id, expected_version=command.expected_version,
                expected_run_id=command.run_id, expected_after=command.after, expected_manifest_sha256=first.manifest_sha256 if first else None,
                expected_source_epoch=first.source_epoch if first else None, now=at)
            if message['expires_ms'] > pending.message['expires_ms']:
                raise TransferError('file_desktop_source_media_deadline_changed')
            if first is not None and (result.media_type, result.insertion_witness, result.total_files) != (
                    first.media_type, first.insertion_witness, first.total_files):
                raise TransferError('file_desktop_source_media_scope_changed')
            known_files = {entry.file_id for page in self._source_media_pages for entry in page.entries}
            known_photos = {entry.photo_id for page in self._source_media_pages for entry in page.entries}
            if any(entry.file_id in known_files or entry.photo_id in known_photos for entry in result.entries):
                raise TransferError('file_desktop_source_duplicate_media')
        else:
            result = source_messages.parse_run_result(message, expected_request_id=command.request_id, expected_operation=command.operation,
                expected_version=command.expected_version, expected_run_id=command.run_id, now=at)
            old = self._source_run
            if old is not None and old.run_id == result.run_id and (
                    old.source_io_ended and not result.source_io_ended
                    or old.state in ('cancel_pending', 'canceled_held') and result.state not in ('cancel_pending', 'canceled_held')
                    or old.state == 'failed_held' and result.state not in ('failed_held', 'canceled_held')):
                raise TransferError('file_desktop_source_run_state_rollback')
            if command.operation == 'offer_run':
                self._correlate_source_offer(result, clock)
                if message['expires_ms'] > min(pending.message['expires_ms'], self._offer['expires_ms']):
                    raise TransferError('file_desktop_source_offer_correlation')
        self._source_command_authority(pending, clock)
        self._controls.finish_receiver_command(pending.ticket)
        self._source_pending = None
        if command.operation in ('status', 'configure'):
            if self._source_status is None or self._source_status.version != result.version:
                self._source_catalog = None
                self._source_albums = {}
                self._source_media_pages = ()
                self._source_media_entries = None
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
        elif command.operation in ('run', 'run_status', 'cancel_run', 'offer_run'):
            self._source_run = result  # Canceled/snapshot-ready still do not release a native whole run.
            if command.operation == 'offer_run':
                self._source_offer = result
            elif result.state != 'snapshot_ready':
                self._source_offer = None
                self._source_media_pages = ()
                self._source_media_entries = None
        elif command.operation == 'media_page':
            self._source_media_pages += (result,)
        self._source_result = result

    def _take_action(self, action):
        if type(action) is not NativePhotoDestinationAction:
            raise TransferError('file_desktop_native_action_required')
        action.consume(self)

    def _receiving_policy(self):
        self._ready()
        if not self._data_handlers_ready:
            raise TransferError('file_desktop_data_handlers_unavailable')
        snapshot = self._preferences.read()
        if (snapshot.policy is None or not snapshot.policy.enabled or not snapshot.associated
                or not snapshot.destination_available):
            raise TransferError('file_desktop_receive_consent_unavailable')
        if self._run is not None and snapshot.version != self._run.policy_version:
            raise TransferError('file_desktop_receive_policy_changed')
        return snapshot

    def _receive_binding(self):
        snapshot = self._receiving_policy()
        binding = self._controls.binding(snapshot.policy.destination_token)
        if binding is None:
            raise TransferError('file_desktop_receive_controls_not_agreed')
        self._ready()
        if self._mutation_action is not None:
            self._mutation_action.validate(self)
        return binding

    def _observe_offer(self, message, clock):
        snapshot = self._receiving_policy()
        binding = self._receive_binding()
        manifest = validate_offer(message, binding.sender_id, binding.receiver_id, now=clock())
        if clock() >= message['expires_ms']:
            raise TransferError('file_desktop_offer_expired')
        if self._run is not None:
            raise TransferError('file_desktop_receive_run_held')
        if self._source_run is not None:
            pending = self._source_pending
            if (pending is None or not pending.sent or pending.command.operation != 'offer_run'
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
        if snapshot.include_videos or snapshot.separate_animations or snapshot.separate_own_recordings:
            if self._source_media_entries is None:
                raise TransferError('file_desktop_source_media_not_correlated')
            # Native per-file destination/semantic grouping is not yet joined.
            # Never silently ignore an explicitly selected unsupported option.
            raise TransferError('file_desktop_media_target_routing_unavailable')
        if self._source_media_pages:
            if self._offer is None or self._source_media_pages[0].media_type != 'images':
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

    def _require_unmapped_media(self):
        """Historical association wins over current target settings.

        This only fences new admission. It neither proves first use after lost
        restart metadata nor implements reconciliation or mapping recovery.
        """
        before, _ = self._mappings.lookup(())
        if before.revision and not before.associated:
            raise TransferError('file_desktop_photo_mapping_reassociation_required')
        if not self._source_media_pages:
            if before.count:
                raise TransferError('file_desktop_photo_mapping_media_required')
            return
        page = self._source_media_pages[0]
        entries = self._source_media_entries
        if entries is None:
            raise TransferError('file_desktop_source_media_not_correlated')
        for offset in range(0, len(entries), 128):
            associations = tuple(PhotoMappingAssociation(page.source_epoch, entry.photo_id, page.media_type)
                                 for entry in entries[offset:offset+128])
            current, records = self._mappings.lookup(associations)
            if current != before:
                raise TransferError('file_desktop_photo_mapping_changed')
            if any(record is not None for record in records):
                raise TransferError('file_desktop_photo_mapping_requires_reconcile')

    def _open_catalog(self, *, allow_create=True):
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
        action = self._mutation_action
        if action is None:
            raise TransferError('file_desktop_native_publication_action_required')
        if self._receive_binding() != binding:
            raise TransferError('file_desktop_native_authority_changed')
        action.validate(self)
        result = mutation()
        if self._receive_binding() != binding:
            raise TransferError('file_desktop_native_authority_changed')
        action.validate(self)
        return result

    def _send_data(self, message, clock, *, action=None):
        self._receive_binding()
        self._ready()
        if action is not None:
            action.validate(self)
        if clock() >= message['expires_ms']:
            raise TransferError('file_desktop_output_expired')
        self._channel.send(message)
        self._receive_binding()
        if action is not None:
            action.validate(self)
        if clock() >= message['expires_ms']:
            raise TransferError('file_desktop_output_expired')

    def accept_pending_offer(self, action, offer_id, *, clock=now_ms):
        """Native I/O-lane admission only; no UI-thread work or implicit run."""
        self._take_action(action)
        with self._operation():
            if self._run is not None or self._offer is None or self._offer['message_id'] != offer_id:
                raise TransferError('file_desktop_offer_not_current')
            self._require_source_offer(clock)
            self._require_unmapped_media()
            snapshot = self._receiving_policy()
            binding = self._receive_binding()
            if binding != self._offer_binding or snapshot.version != self._offer_policy_version:
                raise TransferError('file_desktop_offer_authority_changed')
            manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
            if clock() >= self._offer['expires_ms']:
                raise TransferError('file_desktop_offer_expired')
            accepted = NativeAcceptedTransfer.capture(manifest, binding, {file.id:file.path for file in manifest.files},
                snapshot.policy.destination.path, self._receive_binding)
            if accepted.destination != snapshot.policy.destination:
                raise TransferError('file_desktop_original_destination_changed')
            history = NativeMediaHistory.capture(accepted,self._source_media_pages) if self._source_media_pages else None
            action.validate(self)
            self._run = _NativeDesktopReceiveRun(snapshot.version, accepted)
            self._mutation_action = action
            try:
                self._open_catalog()
                self._receive_binding(); action.validate(self)
                if clock() >= self._offer['expires_ms']:
                    raise TransferError('file_desktop_offer_expired')
                protection = self._authority.protection
                self._run.receiver = NativeFileReceiveOperation.accept(self._catalog, accepted,
                    self._receive_binding, protection.seal, protection.unseal, self._publication_gate,media_history=history)
                self._run.job = self._run.receiver.job
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
            self._require_source_offer(clock)
            self._require_unmapped_media()
            snapshot = self._receiving_policy()
            binding = self._receive_binding()
            if binding != self._offer_binding or snapshot.version != self._offer_policy_version:
                raise TransferError('file_desktop_offer_authority_changed')
            manifest = validate_offer(self._offer, binding.sender_id, binding.receiver_id, now=clock())
            if clock() >= self._offer['expires_ms'] or not self._open_catalog(allow_create=False):
                raise TransferError('file_desktop_resume_unavailable')
            job = next((job for job in self._catalog.jobs() if job.owner == native_job_owner), None)
            if (job is None or job.accepted.manifest != manifest or job.accepted.binding != binding
                    or job.accepted.destination != snapshot.policy.destination):
                raise TransferError('file_desktop_resume_not_current')
            job.accepted.verify(self._receive_binding)
            action.validate(self)
            self._run = _NativeDesktopReceiveRun(snapshot.version, job.accepted, job=job)
            protection = self._authority.protection
            self._run.receiver = NativeFileReceiveOperation.resume(self._catalog, job, self._receive_binding,
                protection.seal, protection.unseal, self._publication_gate)
            action.validate(self)
            self._run.acceptance = self._run.receiver.acceptance_message(self._offer, now=clock())
            self._send_data(self._run.acceptance, clock, action=action)
            self._run.acceptance_sent = True
            return self._run.receiver.progress()

    def _require_receiver(self):
        self._receive_binding()
        if self._run is None or self._run.receiver is None:
            raise TransferError('file_desktop_receive_repair_pending')
        return self._run

    def request_next_chunk(self, *, clock=now_ms):
        with self._operation():
            run = self._require_receiver()
            if not run.acceptance_sent:
                raise TransferError('file_desktop_acceptance_not_sent')
            if run.request is None or clock() >= run.request['expires_ms']:
                run.request = run.receiver.next_chunk_request_message(now=clock())
                run.request_sent = False
            if run.request is None:
                return None  # No missing bytes is not publication/save/sync END.
            self._send_data(run.request, clock)
            run.request_sent = True
            return strict_json(canonical(run.request))

    def _receive_chunk(self, message, clock):
        run = self._require_receiver()
        request_id = message.get('body', {}).get('request_id') if type(message.get('body')) is dict else None
        duplicate = run.last_request is not None and request_id == run.last_request['message_id']
        request = run.last_request if duplicate else run.request
        if request is None or not duplicate and not run.request_sent:
            raise TransferError('file_desktop_chunk_not_requested')
        run.receiver.receive_chunk_message(message, request, now=clock())
        self._receive_binding()
        checked = clock()
        if checked >= request['expires_ms'] or checked >= message['expires_ms']:
            raise TransferError('file_desktop_chunk_expired_during_native_io')
        if not duplicate:
            run.last_request = request
            run.request = None
            run.request_sent = False

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
        existing-file replacement/conflict/baseline union is not implied here.
        """
        self._take_action(action)
        with self._operation():
            run = self._require_receiver()
            if not run.acceptance_sent:
                raise TransferError('file_desktop_acceptance_not_sent')
            self._mutation_action = action
            try:
                action.validate(self)
                run.receiver.publish_completed()
                self._receive_binding(); action.validate(self)
                run.receiver.commit_saved_receipts()
                confirmation = run.receiver.saved_receipt_message(now=clock())
                action.validate(self)
                self._send_data(confirmation, clock, action=action)
                return run.receiver.progress()  # Local save != whole-sync END/quota release.
            finally:
                self._mutation_action = None

    def send_saved_confirmation(self, *, clock=now_ms):
        """Retry historical protected receipts without re-publication or overwrite."""
        with self._operation():
            run = self._require_receiver()
            if not run.acceptance_sent:
                raise TransferError('file_desktop_acceptance_not_sent')
            message = run.receiver.saved_receipt_message(now=clock())
            self._send_data(message, clock)

    def read_preferences(self):
        with self._operation():
            return self._preferences.read()

    def close(self):
        self._closed.set()
        self._authority.revoke()  # Nonwaiting even during blocked native/socket I/O.
        return self._close_resources()

    def _close_resources(self):
        if not self._gate.acquire(blocking=False):
            return False
        try:
            failure = None
            if self._source_pending is not None and self._controls is not None:
                try:
                    self._controls.finish_receiver_command(self._source_pending.ticket)
                    self._source_pending = None
                except Exception as error:
                    failure = error
            receiver = self._run.receiver if self._run is not None else None
            for resource in (receiver, self._catalog, self._destination, self._mappings, self._preferences, self._controls, self._authority):
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


@dataclass
class _NativeDesktopSourceCommand:
    ticket: object
    message: dict
    command: source_messages.SourceCommand
    remote_witness: tuple
    sent: bool = False
