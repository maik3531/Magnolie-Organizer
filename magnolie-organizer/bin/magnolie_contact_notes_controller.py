"""Bounded native Notes owner/receive-worker join; NOT registered in production.

Receive stages authenticated frames only. Native callers run work later under
the book gate, submit the returned real writer invocation, then report actual
completion through after_saved (which rechecks the genuine saved witness).
No renderer factory, source chooser, polling thread or automatic key creation.
Pre-save pending durability/restart restoration is not supplied by this registry.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
import json
import threading
from cryptography.exceptions import InvalidTag

from magnolie_contact_notes_consent import NativeNotesChoiceStore
from magnolie_contact_notes_return import (NativeNotesAckIntents, NativeNotesFsOrigin,
    NativeNotesPendingResult, NativeNotesProtocolNegotiation, NativeNotesExportChoice, NativeNotesNoMutationRequired, _frame_bytes)
from magnolie_contact_notes_requests import NativeNotesRequestIntents


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


@dataclass(frozen=True)
class _Frame:
    pins: tuple
    kind: str
    text: bytes
    origin: NativeNotesFsOrigin
    transport: str
    owner: object


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
        self._frames = OrderedDict()
        self._held = deque(maxlen=max_peers * per_peer)

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
            pending._controller_guard = lambda: self._guard(owner)
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
                if owner is None or owner.held or (kind == 'kontakt_original_abschlussstatus' and not owner.history):
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
                                with self._lock:
                                    self._require_active()
                                    owner.ack = intent
                                result = NativeNotesWork('ack', intent, owner.request['request_id'])
                        else:
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
            return self.after_saved(work.request_id, matches[0].protocol)

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
            self._requests.forget_process_proofs()

    def counts(self):
        with self._lock:
            return {'peers': len(self._peers), 'owners': len(self._owners),
                'queued': len(self._frames), 'held': len(self._held)}
