"""Bounded native Notes owner/receive-worker join; NOT registered in production.

Receive stages authenticated frames only. Native callers run work later under
the book gate, submit the returned real writer invocation, then report actual
completion through after_saved (which rechecks the genuine saved witness).
No renderer factory, source chooser, polling thread or automatic key creation.
Private pending history supports read-only restart recovery, never provider replay.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
import json
import threading
import math
from cryptography.exceptions import InvalidTag

from magnolie_contact_notes_consent import NativeNotesChoiceStore
from magnolie_contact_notes_return import (NativeNotesAckIntents, NativeNotesFsOrigin,
    NativeNotesPendingResult, NativeNotesProtocolNegotiation, NativeNotesExportChoice, NativeNotesNoMutationRequired, _frame_bytes)
from magnolie_contact_notes_requests import NativeNotesRequestIntents, NativeNotesRecoveryNeedsSave, NativeNotesBootstrapSave


@dataclass(frozen=True)
class NativeNotesWork:
    kind: str
    intent: object = None
    request_id: str = ''


@dataclass
class _Owner:
    pins: tuple
    physical: tuple
    request: dict
    protocol: NativeNotesProtocolNegotiation
    pending: object = None
    history: str = ''
    commit: object = None
    held: bool = False
    ack: object = None
    unconfirmed: object = None
    bootstrap: object = None
    ack_sent: bool = False


@dataclass(frozen=True)
class _Frame:
    pins: tuple
    kind: str
    text: bytes
    origin: NativeNotesFsOrigin
    transport: str
    owner: object


@dataclass
class _ExportBootstrap:
    pins: tuple
    identity: tuple
    protocol: NativeNotesProtocolNegotiation
    bootstrap: object = None


class NativeNotesController:
    def __init__(self, consent, outcomes, book_gate, *, max_peers=8, per_peer=8, frame_budget=256 * 1024):
        if (type(consent) is not NativeNotesChoiceStore or type(outcomes) is not NativeNotesAckIntents or
                not callable(book_gate) or type(max_peers) is not int or not 1 <= max_peers <= 32 or
                type(per_peer) is not int or not 1 <= per_peer <= 16 or
                type(frame_budget) is not int or not 1024 <= frame_budget <= 1024 * 1024):
            raise TypeError('notes_controller_native_dependencies_required')
        self._consent, self._outcomes, self._book_gate = consent, outcomes, book_gate
        self._requests = NativeNotesRequestIntents(outcomes.root + '-pending', outcomes._existing_key)
        self._max_peers, self._per_peer, self._budget = max_peers, per_peer, frame_budget
        self._lock, self._work = threading.RLock(), threading.RLock()
        self._active = True
        self._peers, self._owners, self._physical = {}, {}, {}
        self._export_bootstraps = {}
        self._frames = OrderedDict()
        self._held = deque(maxlen=max_peers * per_peer)
        self._send_due = {}
        self._send_cursor = 0

    def begin_peer(self, peer, own):
        protocol = NativeNotesProtocolNegotiation(peer, own)
        pins = peer, own
        with self._lock:
            self._require_active()
            if pins in self._peers:
                return self._peers[pins]
            if len(self._peers) >= self._max_peers:
                raise PermissionError('notes_controller_peer_budget')
            self._peers[pins] = protocol
        return protocol

    def _require_active(self):
        if not self._active:
            raise PermissionError('notes_controller_stopped')

    def _guard(self, owner):
        # No callbacks/IO under registry lock: worker may hold the native book
        # gate while FS1 receive holds the tree gate and briefly stages a frame.
        with self._lock:
            self._require_active()
            if self._owners.get((owner.pins, owner.request['request_id'])) is not owner or owner.held:
                raise PermissionError('notes_controller_owner_held_or_replaced')

    def _guard_export(self, owner):
        with self._lock:
            self._require_active()
            if self._export_bootstraps.get(owner.identity) is not owner or self._peers.get(owner.pins) is not owner.protocol:
                raise PermissionError('notes_controller_export_bootstrap_replaced')
        owner.protocol.require_current()

    def _guard_pending(self, owner, pending):
        self._guard(owner)
        with self._lock:
            if owner.pending is not pending:
                raise PermissionError('notes_controller_pending_replaced')

    def _demote_stale(self, owner):
        pending = owner.pending
        if (pending is not None and owner.commit is None and owner.unconfirmed is None and
                pending._capture() != pending._snapshot):
            self._guard(owner)
            query = self._requests.demote_to_query(pending, self._consent)
            self._guard(owner)
            with self._lock:
                owner.unconfirmed, owner.pending = query, None

    def _book_save_busy(self):
        # Serialize book metadata saves until their genuine ACK history is
        # sealed, not merely until native_write returned. Other provider slots
        # and read-only queries are independent of this short local-save lane.
        for owner in self._owners.values():
            if owner.commit is not None and not owner.history and not owner.held:
                if owner.commit.done.is_set() and owner.commit.result.get('confirmed') is not True:
                    owner.held = True
                else:
                    return True
        return False

    def _bootstrap_busy(self):
        with self._lock:
            saves = [owner.bootstrap for owner in self._owners.values()]
            saves += [owner.bootstrap for owner in self._export_bootstraps.values()]
        return any(save is not None and not save.done.is_set() for save in saves)

    def _register(self, owner):
        with self._lock:
            self._require_active()
            key = owner.pins, owner.request['request_id']
            if (self._peers.get(owner.pins) is not owner.protocol or key in self._owners or
                    owner.physical in self._physical or len(self._owners) >= self._max_peers * self._per_peer):
                raise PermissionError('notes_controller_physical_owner_held')
            self._owners[key] = owner
            self._physical[owner.physical] = owner

    def register_pending(self, pending, protocol):
        if type(pending) is not NativeNotesPendingResult:
            raise PermissionError('notes_controller_native_pending_required')
        with self._work:
            choice = pending._source_choice
            if (type(protocol) is not NativeNotesProtocolNegotiation or type(choice) is not NativeNotesExportChoice or
                    getattr(getattr(choice, '_private_seal', None), 'store', None) is not self._consent or
                    getattr(pending, '_controller_guard', None) is not None):
                raise PermissionError('notes_controller_foreign_pending')
            pins = protocol.require_current()
            if pins != (pending._peer, pending._own):
                raise PermissionError('notes_controller_foreign_pending')
            request = pending.request()
            if self._requests.target_unchanged(request['ziel'], json.loads(choice._body_text)['kontakt']):
                raise ValueError('notes_controller_no_target_change')
            owner = _Owner(pins, (self._consent.root, choice._id), request, protocol, pending=pending)
            self._register(owner)
            pending._controller_guard = lambda: self._guard_pending(owner, pending)
            try:
                self._requests.seal(pending)
                pending._for_negotiated_protocol(protocol)
                self._guard(owner)
            except Exception:
                with self._lock:
                    owner.held = True
                raise
            return NativeNotesWork('request', pending, request['request_id'])

    def register_history(self, key, protocol):
        with self._work:
            query = self._outcomes.readonly_query(key, self._consent)
            request = query._for_negotiated_protocol(protocol)
            record = self._outcomes._read_history_proof(query._proof.history)
            owner = _Owner(protocol.require_current(), (self._consent.root, record['local_id']), request,
                protocol, history=key)
            self._register(owner)
            return NativeNotesWork('query', query, request['request_id'])

    def register_unconfirmed(self, key, protocol, *, physical=None):
        with self._work:
            query = self._requests.readonly_query(key, self._consent, physical=physical)
            request = query._for_negotiated_protocol(protocol)
            record = self._requests._read_query_proof(query._proof.history)
            owner = _Owner(protocol.require_current(), (self._consent.root, record['local_id']), request,
                protocol, unconfirmed=query)
            self._register(owner)
            return NativeNotesWork('query', query, request['request_id'])

    def discover(self, protocol):
        """Native worker: known consent slots only; genuine saved ACK wins."""
        if type(protocol) is not NativeNotesProtocolNegotiation:
            raise PermissionError('notes_controller_owned_protocol_required')
        with self._work:
            pins = protocol.require_current()
            with self._lock:
                self._require_active()
                if self._peers.get(pins) is not protocol:
                    raise PermissionError('notes_controller_owned_protocol_required')
            works = []
            with self._book_gate():
                selected = self._consent._discovery_sources(pins)
                if selected is None:
                    return ()
                binding, sources = selected
                for source in sources:  # Consent schema caps the entire list at 256.
                    with self._lock:
                        self._require_active()
                        if (self._consent.root, source['local_id']) in self._physical:
                            continue
                        if sum(owner.pins == pins for owner in self._owners.values()) >= self._per_peer:
                            break
                    try:
                        found = self._requests._discover_slot(binding, source)
                        if found is None:
                            continue
                        key, physical, record = found
                        if record['state'] == 'request_settled':
                            continue
                        saved_key = self._outcomes._key(record)
                        saved = self._outcomes.load_held(saved_key)
                        if saved is not None:
                            # A corrupt/conflicting saved ACK must hold this
                            # source, never downgrade to unconfirmed recovery.
                            if (saved.get('request_intention') != key or
                                    _frame_bytes(saved.get('request')) != _frame_bytes(record['request'])):
                                raise PermissionError('notes_controller_discovery_saved_history_changed')
                            work = self.register_history(saved_key, protocol)
                        else:
                            work = self.register_unconfirmed(key, protocol, physical=physical)
                        works.append(work)
                    except (PermissionError, ValueError, OSError, RuntimeError, InvalidTag):
                        with self._lock:
                            self._held.append('discovery')
                protocol.require_current()
            return tuple(works)

    def next_transport(self, now):
        """One rate-limited typed send plan; caller sends outside every gate."""
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('notes_controller_monotonic_time_required')
        with self._work:
            with self._book_gate():
                self._require_active()
                selected = self._consent._discovery_sources(None)
                if selected is None:
                    return None
                _, sources = selected
                allowed = {(tuple(source['peer']), tuple(source['own'])) for source in sources}
                for source in sources:
                    pins = tuple(source['peer']), tuple(source['own'])
                    if pins not in self._peers and len(self._peers) < self._max_peers:
                        self.begin_peer(*pins)
                plans = []
                for pins, protocol in tuple(self._peers.items()):
                    if pins not in allowed:
                        continue
                    try:
                        if protocol._offer is None:
                            protocol._native_probe()
                            plans.append((NativeNotesWork('probe', protocol), protocol))
                        else:
                            self.discover(protocol)
                    except (PermissionError, ValueError, OSError, RuntimeError, InvalidTag):
                        continue
                for owner in tuple(self._owners.values()):
                    if owner.held or owner.pins not in allowed or owner.commit is not None and not owner.history:
                        continue
                    try:
                        self._guard(owner)
                        self._demote_stale(owner)
                        if (owner.history and owner.pending is not None and owner.commit is not None and
                                self._consent._capture() != owner.commit._confirmed_snapshot):
                            # A later real book save invalidates the old live
                            # witness, not its independent sealed ACK history.
                            # Query for a fresh native proof before reauthorizing.
                            with self._lock:
                                owner.pending, owner.commit, owner.ack = None, None, None
                                owner.ack_sent = False
                        if owner.ack is not None and not owner.ack_sent:
                            work = NativeNotesWork('ack', owner.ack, owner.request['request_id'])
                        elif owner.history:
                            work = NativeNotesWork('query', self._outcomes.readonly_query(owner.history, self._consent), owner.request['request_id'])
                        elif owner.unconfirmed is not None:
                            work = NativeNotesWork('query', owner.unconfirmed, owner.request['request_id'])
                        elif owner.pending is not None:
                            work = NativeNotesWork('request', owner.pending, owner.request['request_id'])
                        else:
                            continue
                        plans.append((work, owner.protocol))
                    except (PermissionError, ValueError, OSError, RuntimeError, InvalidTag):
                        owner.held = True
                live = {(pins[0], pins[1], 'probe', '') for pins in self._peers}
                live.update((owner.pins[0], owner.pins[1], kind, owner.request['request_id'])
                    for owner in self._owners.values() for kind in ('request', 'query', 'ack'))
                self._send_due = {key: due for key, due in self._send_due.items() if key in live}
                for offset in range(len(plans)):
                    index = (self._send_cursor + offset) % len(plans)
                    work, protocol = plans[index]
                    key = protocol._peer, protocol._own, work.kind, work.request_id
                    if self._send_due.get(key, 0) > now:
                        continue
                    self._send_due[key] = now + 30
                    self._send_cursor = index + 1
                    return work, protocol
                return None

    def transport_finished(self, work, protocol, delivered):
        """Transport delivery is not negotiation, a saved witness or settlement."""
        if type(work) is not NativeNotesWork or type(protocol) is not NativeNotesProtocolNegotiation or type(delivered) is not bool:
            raise PermissionError('notes_controller_typed_transport_required')
        with self._lock:
            self._require_active()
            if self._peers.get((protocol._peer, protocol._own)) is not protocol:
                raise PermissionError('notes_controller_owned_protocol_required')
            owner = self._owners.get(((protocol._peer, protocol._own), work.request_id))
            if owner is not None and delivered:
                if work.kind == 'ack' and owner.ack is work.intent:
                    owner.ack_sent = True
                elif work.kind == 'query' and owner.ack is not None:
                    owner.ack_sent = False

    def receive(self, peer, body, origin, transport):
        """Actual native FS1 callback: no book/key/consent/journal/worker calls."""
        if type(origin) is not NativeNotesFsOrigin or not isinstance(body, dict):
            return False
        pins = origin.require_current(body, transport)
        if (not isinstance(peer, dict) or (peer.get('kennung'), peer.get('oeffentlich')) != pins[0]):
            return False
        text = _frame_bytes(body)
        if len(text) > self._budget:
            return False
        kind = body.get('art')
        if not isinstance(kind, str):
            return False
        with self._lock:
            self._require_active()
            protocol = self._peers.get(pins)
            if protocol is None:
                return False
            owner = None
            if kind == 'kontakt_original_aushandlung':
                if text != _frame_bytes(dict(protocol.request(), antwort=True)):
                    return False
                identity = body['challenge']
            elif kind == 'kontakt_original_export':
                if any(not isinstance(body.get(name), str) or not body[name] for name in ('share_id', 'setup_id')):
                    return False
                identity = body['share_id'], body['setup_id']
            elif kind in ('kontakt_original_ergebnis', 'kontakt_original_abschlussstatus'):
                identity = body.get('request_id')
                if not isinstance(identity, str):
                    return False
                owner = self._owners.get((pins, identity))
                if owner is None or owner.held or (kind == 'kontakt_original_abschlussstatus' and not owner.history and owner.unconfirmed is None):
                    return False
                for name in ('request_id', 'share_id', 'before_basis', 'target_sha256'):
                    if _frame_bytes(body.get(name)) != _frame_bytes(owner.request[name]):
                        return False
            else:
                return False
            key = pins, kind, identity
            existing = self._frames.get(key)
            if existing is not None and existing.text != text:
                return False
            if existing is None and sum(frame.pins == pins for frame in self._frames.values()) >= self._per_peer:
                return False
            self._frames[key] = _Frame(pins, kind, text, origin, transport, owner)
        origin.require_current(body, transport)
        return True

    def process_one(self):
        """Native worker only, outside receive. Errors hold one owner, not all."""
        with self._work:
            with self._lock:
                self._require_active()
                if not self._frames:
                    return None
                _, frame = self._frames.popitem(last=False)
                protocol = self._peers[frame.pins]
            try:
                body = json.loads(frame.text)
                frame.origin.require_current(body, frame.transport)
                if frame.kind == 'kontakt_original_export' and protocol._offer is None:
                    with self._lock:
                        self._require_active()
                        self._frames[(frame.pins, frame.kind, (body['share_id'], body['setup_id']))] = frame
                    return NativeNotesWork('waiting')
                with self._book_gate():
                    if frame.kind == 'kontakt_original_aushandlung':
                        protocol.accept(body, frame.origin, frame.transport)
                        result = NativeNotesWork('negotiated', protocol)
                    elif frame.kind == 'kontakt_original_export':
                        protocol.require_current()
                        identity = frame.pins, body['share_id'], body['setup_id']
                        if self._consent._capture() is None:
                            with self._lock:
                                self._require_active()
                                lease = self._export_bootstraps.get(identity)
                                if lease is None:
                                    if self._export_bootstraps or self._bootstrap_busy():
                                        key = frame.pins, frame.kind, (body['share_id'], body['setup_id'])
                                        if key not in self._frames and sum(item.pins == frame.pins for item in self._frames.values()) < self._per_peer:
                                            self._frames[key] = frame
                                        return NativeNotesWork('waiting')  # One real book bootstrap, not one full-book copy per source.
                                    lease = _ExportBootstrap(frame.pins, identity, protocol)
                                    self._export_bootstraps[identity] = lease
                            new = lease.bootstrap is None
                            if new:
                                try:
                                    lease.bootstrap = self._consent.bootstrap_export(body, frame.origin, frame.transport,
                                        lambda lease=lease: self._guard_export(lease))
                                except Exception:
                                    with self._lock:
                                        if self._export_bootstraps.get(identity) is lease:
                                            del self._export_bootstraps[identity]
                                    raise
                            with self._lock:
                                self._require_active()
                                key = frame.pins, frame.kind, (body['share_id'], body['setup_id'])
                                if key not in self._frames and sum(item.pins == frame.pins for item in self._frames.values()) < self._per_peer:
                                    self._frames[key] = frame
                            return NativeNotesWork('needs-real-save', lease.bootstrap) if new else NativeNotesWork('waiting')
                        with self._lock:
                            self._export_bootstraps.pop(identity, None)
                        choice = self._consent.restore(body, frame.origin, frame.transport)
                        try:
                            pending = choice.pending()
                        except NativeNotesNoMutationRequired:
                            result = NativeNotesWork('unchanged')
                        else:
                            patch = pending.request()['ziel']
                            # Semantic hashes deliberately omit some legacy name
                            # representations; compare exact modeled fields.
                            unchanged = self._requests.target_unchanged(patch, body['kontakt'])
                            result = NativeNotesWork('unchanged') if unchanged else self.register_pending(pending, protocol)
                    else:
                        owner = frame.owner
                        self._guard(owner)
                        if owner.history:
                            intent = self._outcomes.reauthorize(owner.history, self._consent, body, frame.origin, frame.transport)
                            if intent.terminal_confirmed():
                                self._outcomes.confirm_terminal(intent)
                                confirmed = self._outcomes.reauthorize(owner.history, self._consent, body, frame.origin, frame.transport)
                                self._requests.retire_from_terminal(confirmed)
                                self._guard(owner)
                                with self._lock:
                                    del self._owners[(owner.pins, owner.request['request_id'])]
                                    del self._physical[owner.physical]
                                result = NativeNotesWork('settled', request_id=owner.request['request_id'])
                            else:
                                self._guard(owner)
                                stale_witness = (owner.commit is not None and
                                    self._consent._capture() != owner.commit._confirmed_snapshot)
                                with self._lock:
                                    self._require_active()
                                    owner.ack = intent
                                    if stale_witness:
                                        owner.pending, owner.commit = None, None
                                result = NativeNotesWork('ack', intent, owner.request['request_id'])
                        else:
                            if owner.commit is None and self._book_save_busy():
                                with self._lock:
                                    self._require_active()
                                    key = frame.pins, frame.kind, body['request_id']
                                    existing = self._frames.get(key)
                                    if existing is not None and existing.text != frame.text:
                                        raise PermissionError('notes_controller_conflicting_deferred_result')
                                    if existing is None and sum(item.pins == frame.pins for item in self._frames.values()) < self._per_peer:
                                        self._frames[key] = frame
                                return NativeNotesWork('waiting', request_id=owner.request['request_id'])
                            self._demote_stale(owner)
                            if owner.pending is None and owner.unconfirmed is not None:
                                try:
                                    pending = self._requests.resume_verified(owner.unconfirmed, body, frame.origin, frame.transport)
                                except NativeNotesRecoveryNeedsSave as needed:
                                    with self._lock:
                                        self._require_active()
                                        key = frame.pins, frame.kind, body['request_id']
                                        queued = self._frames.get(key)
                                        if queued is not None and queued.text != frame.text:
                                            raise PermissionError('notes_controller_conflicting_recovery_result')
                                        if queued is None and sum(item.pins == frame.pins for item in self._frames.values()) < self._per_peer:
                                            self._frames[key] = frame
                                    if owner.bootstrap is None and not self._bootstrap_busy():
                                        owner.bootstrap = NativeNotesBootstrapSave(needed.context, lambda owner=owner: self._guard(owner))
                                        return NativeNotesWork('needs-real-save', owner.bootstrap, owner.request['request_id'])
                                    return NativeNotesWork('waiting', request_id=owner.request['request_id'])
                                owner.pending = pending
                                pending._controller_guard = lambda owner=owner, pending=pending: self._guard_pending(owner, pending)
                            owner.pending.stage_result(body, frame.origin, frame.transport)
                            commit = owner.pending.prepare_commit()
                            if owner.commit is None:
                                owner.commit = commit
                                result = NativeNotesWork('save', commit, owner.request['request_id'])
                            else:
                                result = NativeNotesWork('duplicate', request_id=owner.request['request_id'])
                    with self._lock:
                        self._require_active()
                    return result
            except (PermissionError, ValueError, OSError, RuntimeError, InvalidTag):
                with self._lock:
                    if frame.owner is not None:
                        frame.owner.held = True
                    self._held.append(frame.kind)
                return NativeNotesWork('held')

    def after_saved(self, request_id, protocol):
        """A callback Boolean cannot complete a save: the real witness is read."""
        if type(protocol) is not NativeNotesProtocolNegotiation:
            raise PermissionError('notes_controller_owned_protocol_required')
        with self._work:
            pins = protocol.require_current()
            with self._lock:
                owner = self._owners.get((pins, request_id))
            if owner is None or owner.protocol is not protocol or owner.pending is None or owner.history:
                raise PermissionError('notes_controller_pending_save_required')
            self._guard(owner)
            with self._book_gate():
                intent = self._outcomes.seal_after_save(owner.pending)
                self._guard(owner)
                with self._lock:
                    self._require_active()
                    owner.history = intent._proof.key
                    owner.ack = intent
                return NativeNotesWork('ack', intent, request_id)

    def finish_save(self, work):
        if type(work) is not NativeNotesWork or work.kind != 'save':
            raise PermissionError('notes_controller_owned_save_work_required')
        with self._work:
            with self._lock:
                matches = [owner for owner in self._owners.values()
                    if owner.request['request_id'] == work.request_id and owner.commit is work.intent]
            if len(matches) != 1:
                raise PermissionError('notes_controller_owned_save_work_required')
            try:
                return self.after_saved(work.request_id, matches[0].protocol)
            except (PermissionError, ValueError, OSError, RuntimeError, InvalidTag):
                if work.intent.done.is_set():
                    with self._lock:
                        matches[0].held = True
                raise

    def finish_bootstrap(self, work):
        if type(work) is not NativeNotesWork or work.kind != 'needs-real-save' or type(work.intent) is not NativeNotesBootstrapSave:
            raise PermissionError('notes_controller_owned_bootstrap_required')
        with self._work:
            with self._lock:
                matches = [owner for owner in self._owners.values()
                    if owner.request['request_id'] == work.request_id and owner.bootstrap is work.intent]
                exports = [owner for owner in self._export_bootstraps.values() if owner.bootstrap is work.intent]
                if work.intent.done.is_set() and work.intent.result != {'confirmed': True}:
                    for owner in exports:
                        del self._export_bootstraps[owner.identity]
                        pins, share, setup = owner.identity
                        self._frames.pop((pins, 'kontakt_original_export', (share, setup)), None)
                        self._held.append('kontakt_original_export')
                    for owner in matches:
                        owner.held = True
            if not work.request_id and len(exports) == 1 and work.intent.result == {'confirmed': True}:
                self._guard_export(exports[0])
                return NativeNotesWork('bootstrap-saved')
            if len(matches) != 1 or work.intent.result != {'confirmed': True}:
                raise PermissionError('notes_controller_bootstrap_unconfirmed')
            self._guard(matches[0])
            return NativeNotesWork('bootstrap-saved', request_id=work.request_id)

    def ready_acks(self):
        with self._lock:
            self._require_active()
            return tuple(NativeNotesWork('ack', owner.ack, owner.request['request_id'])
                for owner in self._owners.values() if owner.ack is not None and not owner.held)

    def stop(self):
        with self._lock:
            self._active = False
            for protocol in self._peers.values():
                protocol.cancel()
            self._frames.clear()
            self._export_bootstraps.clear()
            self._send_due.clear()
            self._requests.forget_process_proofs()

    def counts(self):
        with self._lock:
            return {'peers': len(self._peers), 'owners': len(self._owners),
                'queued': len(self._frames), 'held': len(self._held)}
