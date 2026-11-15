"""Owned native Notes work -> ordinary numeric UI save, never source authority.

No startup factory, thread, key or listener. Writer completion runs under the
actual book gate WITHOUT taking controller._work (worker order is work -> book).
"""
import secrets
import threading
import time

from magnolie_contact_notes_controller import NativeNotesController, NativeNotesWork
from magnolie_contact_notes_requests import NativeNotesBootstrapSave
from magnolie_contact_source_book import NativeContactSourceResultCommit


class _SaveProof:
    def __init__(self, controller, work):
        self.controller, self.work = controller, work
        self._lock = threading.RLock()
        self._started = self._finished = False
        self._owner = self._require_owned()

    def _require_owned(self):
        c, work = self.controller, self.work
        if type(c) is not NativeNotesController or type(work) is not NativeNotesWork:
            raise PermissionError('notes_ui_native_work_required')
        with c._lock:
            c._require_active()
            if work.kind == 'save' and type(work.intent) is NativeContactSourceResultCommit:
                owners = [owner for owner in c._owners.values() if not owner.held and
                    owner.request['request_id'] == work.request_id and owner.commit is work.intent and not owner.history]
            elif work.kind == 'needs-real-save' and type(work.intent) is NativeNotesBootstrapSave:
                owners = [owner for owner in c._owners.values() if not owner.held and
                    owner.request['request_id'] == work.request_id and owner.bootstrap is work.intent]
                if not work.request_id:
                    owners = [owner for owner in c._export_bootstraps.values() if owner.bootstrap is work.intent]
            else:
                owners = []
            if len(owners) != 1:
                raise PermissionError('notes_ui_owned_work_required')
            return owners[0]

    def begin(self, text):
        with self._lock:
            if self._started or self._finished:
                raise PermissionError('notes_ui_completion_already_used')
            self._started = True
        if self._require_owned() is not self._owner or text != self.work.intent.text:
            raise PermissionError('notes_ui_exact_work_required')

    def complete(self, acknowledgment):
        """Caller holds the real native book gate across witness + journal seal."""
        with self._lock:
            if not self._started or self._finished:
                raise PermissionError('notes_ui_completion_not_started')
            self._finished = True
        c, work = self.controller, self.work
        if self._require_owned() is not self._owner:
            raise PermissionError('notes_ui_owner_changed')
        work.intent.complete(acknowledgment)
        if work.kind == 'save':
            owner = self._owner
            c._guard(owner)
            intent = c._outcomes.seal_after_save(owner.pending)
            c._guard(owner)
            with c._lock:
                c._require_active()
                owner.history, owner.ack = intent._proof.key, intent
        else:
            if work.intent.result != {'confirmed': True}:
                raise PermissionError('notes_ui_bootstrap_unconfirmed')
            if work.request_id:
                c._guard(self._owner)
            else:
                c._guard_export(self._owner)

    def failed(self):
        with self._lock:
            self._finished = True
        c, work = self.controller, self.work
        with c._lock:
            if work.kind == 'needs-real-save' and not work.request_id:
                for identity, owner in tuple(c._export_bootstraps.items()):
                    if owner.bootstrap is work.intent:
                        del c._export_bootstraps[identity]
                        pins, share, setup = identity
                        c._frames.pop((pins, 'kontakt_original_export', (share, setup)), None)
                        c._held.append('bootstrap-save')
            else:
                for owner in c._owners.values():
                    if owner.request['request_id'] == work.request_id and (
                            owner.commit is work.intent or owner.bootstrap is work.intent):
                        owner.held = True  # Memory lane only; physical disk holds/history survive.


class NativeNotesUiSaveSession:
    def __init__(self, controller, owned_text, *, clock=time.monotonic):
        if type(controller) is not NativeNotesController or not callable(owned_text) or not callable(clock):
            raise TypeError('notes_ui_native_dependencies_required')
        self.controller, self._text, self._clock = controller, owned_text, clock
        self._lock, self._active, self._pending = threading.RLock(), True, None

    def publish(self, work):
        self.expire()
        proof = _SaveProof(self.controller, work)
        before = self._text()
        if type(before) is not str:
            proof.failed()
            raise PermissionError('notes_ui_native_model_required')
        text = work.intent.text
        if self._text() != before:
            proof.failed()
            raise PermissionError('notes_ui_native_model_changed')
        offer = {'token': secrets.token_hex(32), 'kind': 'bootstrap' if work.kind == 'needs-real-save' else 'save',
            'beforeText': before, 'text': text}
        with self._lock:
            if not self._active or self._pending is not None:
                proof.failed()
                raise PermissionError('notes_ui_slot_unavailable')
            self._pending = offer, proof, self._clock() + 8
        return dict(offer)

    def claim(self, token, text):
        self.expire()
        with self._lock:
            if not self._active or self._pending is None or type(token) is not str or token != self._pending[0]['token']:
                raise PermissionError('notes_ui_owned_token_required')
            offer, proof, _ = self._pending
            self._pending = None  # One use even on later failure.
        try:
            if text != offer['text'] or self._text() != offer['beforeText']:
                raise PermissionError('notes_ui_exact_current_book_required')
            proof.begin(text)
            return proof
        except Exception:
            proof.failed()
            raise

    def cancel(self, token):
        with self._lock:
            pending = self._pending
            if pending is None or token != pending[0]['token']:
                return
            self._pending = None
        pending[1].failed()

    def expire(self):
        with self._lock:
            pending = self._pending
            if pending is None or self._clock() < pending[2]:
                return
            self._pending = None
        pending[1].failed()

    def stop(self):
        with self._lock:
            self._active, pending, self._pending = False, self._pending, None
        if pending is not None:
            pending[1].failed()
