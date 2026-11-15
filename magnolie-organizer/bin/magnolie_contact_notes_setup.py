"""Bounded native setup acquisition, not a source grant or startup factory.

Receive only retains genuine FS1 origins. Book/chooser/consent work is deferred;
no thread, timer, listener, key or writer is created by constructing a collector.
"""
from dataclasses import dataclass
import json
import threading
import time

from magnolie_contact_notes_return import (NativeNotesFsOrigin, NativeNotesProtocolNegotiation,
    NativeNotesExportChoice, _validate_notes_export, _frame_bytes)


@dataclass(frozen=True)
class _Frame:
    text: bytes
    origin: NativeNotesFsOrigin
    transport: str


@dataclass(frozen=True)
class _CandidateProof:
    owner: object
    key: tuple
    frame: _Frame


class NativeNotesSetupCandidate:
    def __init__(self, proof):
        self.__proof = proof

    def _native(self):
        proof = self.__proof
        if type(proof) is not _CandidateProof or type(proof.owner) is not NativeNotesSetupCollector:
            raise PermissionError('notes_setup_native_candidate_required')
        proof.owner._require_candidate(proof.key, proof.frame)
        return proof

    def display(self):
        return json.loads(self._native().frame.text)

    @property
    def peer(self):
        return self._native().owner._pins[0]

    def choose(self, snapshot, capture_current, choose_native):
        proof = self._native()
        def current():
            proof.owner._require_candidate(proof.key, proof.frame)
        return NativeNotesExportChoice(json.loads(proof.frame.text), proof.frame.origin, proof.frame.transport,
            snapshot, capture_current, choose_native, require_native_selection=current)


class NativeNotesSetupCollector:
    def __init__(self, service, protocol, *, clock=time.monotonic, budget=8):
        if (type(protocol) is not NativeNotesProtocolNegotiation or not callable(clock) or
                type(budget) is not int or not 1 <= budget <= 32):
            raise TypeError('notes_setup_native_dependencies_required')
        self._service, self.protocol, self._clock, self._budget = service, protocol, clock, budget
        self._pins, probe = protocol._native_probe()
        self._expected_offer = _frame_bytes(dict(probe, antwort=True))
        self._deadline = clock() + 120
        self._lock, self._changed = threading.RLock(), threading.Event()
        self._active, self._attached, self._offer = True, False, None
        self._exports, self._conflicts = {}, set()

    def _require_active(self):
        if not self._active or self._clock() >= self._deadline:
            raise PermissionError('notes_setup_acquisition_expired')

    def attach(self):
        with self._lock:
            self._require_active()
            if self._attached:
                raise PermissionError('notes_setup_already_attached')
        self._service._notes_setup_attach(self)
        with self._lock:
            if self._active and self._clock() < self._deadline:
                self._attached = True
                return
        self._service._notes_setup_detach(self)
        raise PermissionError('notes_setup_acquisition_expired')

    def receive(self, body, origin, transport):
        try:
            if type(origin) is not NativeNotesFsOrigin or origin.require_current(body, transport) != self._pins:
                return False
            text = _frame_bytes(body)
            if len(text) > 256 * 1024:
                return False
            frame = _Frame(text, origin, transport)
            if body.get('art') == 'kontakt_original_aushandlung':
                if text != self._expected_offer:
                    return False
                with self._lock:
                    self._require_active()
                    self._offer = frame
                    if self._exports: self._changed.set()
                return True
            if body.get('art') != 'kontakt_original_export':
                return False
            _validate_notes_export(body)
            key = body['share_id'], body['setup_id']
            with self._lock:
                self._require_active()
                if key in self._conflicts:
                    return False
                if key in self._exports:
                    if self._exports[key].text != text:
                        del self._exports[key]
                        self._conflicts.add(key)
                        return False
                elif len(self._exports) + len(self._conflicts) >= self._budget:
                    return False
                self._exports[key] = frame
                if self._offer is not None: self._changed.set()
                return True
        except (PermissionError, TypeError, ValueError):
            return False

    def candidates(self):
        with self._lock:
            self._require_active()
            offer, exports = self._offer, tuple(self._exports.items())
        if offer is None:
            raise PermissionError('notes_setup_protocol_offer_required')
        self.protocol.accept(json.loads(offer.text), offer.origin, offer.transport)
        self.protocol.require_current()
        result = []
        for key, frame in exports:
            self._require_candidate(key, frame)
            result.append(NativeNotesSetupCandidate(_CandidateProof(self, key, frame)))
        return tuple(result)

    def _require_candidate(self, key, frame):
        def current():
            with self._lock:
                self._require_active()
                if not self._attached or self._exports.get(key) is not frame or key in self._conflicts:
                    raise PermissionError('notes_setup_candidate_changed')
        current()
        self.protocol.require_current()
        if frame.origin.require_current(json.loads(frame.text), frame.transport) != self._pins:
            raise PermissionError('notes_setup_peer_changed')
        current()

    def wait(self):
        """Deferred native worker only; stop cancels promptly without polling."""
        with self._lock:
            self._require_active()
            remaining = self._deadline - self._clock()
        if not self._changed.wait(remaining):
            raise TimeoutError('notes_setup_acquisition_expired')
        return self.candidates()

    def stop(self):
        with self._lock:
            if not self._active:
                return
            self._active, self._attached, self._offer = False, False, None
            self._exports.clear(); self._conflicts.clear()
        self._changed.set()
        self.protocol.cancel()
        self._service._notes_setup_detach(self)  # Outside acquisition lock, owned detach only.


@dataclass(frozen=True)
class NativeNotesSetupView:
    addition: bool
    export: dict
    peer: tuple
    contacts: tuple


class NativeNotesSetupFlow:
    """Explicit native candidate -> conscious chooser -> before-dialog CAS.

    The native caller runs GTK on its main thread; no book/private/tree lock is
    held while the chooser runs. This class creates no UI thread or registration.
    """
    def __init__(self, consent, capture_current, book_gate, require_usable=lambda: None):
        from magnolie_contact_notes_consent import NativeNotesChoiceStore
        if (type(consent) is not NativeNotesChoiceStore or
                not all(callable(value) for value in (capture_current, book_gate, require_usable))):
            raise TypeError('notes_setup_native_dependencies_required')
        self._consent, self._capture, self._book_gate, self._usable = consent, capture_current, book_gate, require_usable

    def configure(self, candidate, choose_native):
        if type(candidate) is not NativeNotesSetupCandidate or not callable(choose_native):
            raise PermissionError('notes_setup_native_candidate_and_chooser_required')
        with self._book_gate():
            self._usable()
            export = candidate.display()
            decision = self._consent.begin_setup_decision()
            peer = candidate.peer
        contacts = tuple(json.loads(json.dumps(contact, ensure_ascii=False))
            for contact in decision.snapshot.book().get('kontakte', []))
        selected = choose_native(NativeNotesSetupView(decision.is_addition, export, peer, contacts))
        self._usable()
        if selected is None:
            return False
        with self._book_gate():
            self._usable()
            choice = candidate.choose(decision.snapshot, self._capture, lambda _: selected)
            self._usable()
            decision.commit(choice)
        return True
