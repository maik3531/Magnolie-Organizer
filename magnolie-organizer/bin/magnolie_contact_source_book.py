"""Native saved-book boundary for original-contact updates; no source grants.

Only the existing native writer records a commit. Document fields, renderer ACKs
and phone-actor ownership are not substitutes for this independent observation.
Callers hold the native data lock while observing/replacing the current book.
"""
import hashlib
import hmac
import json
import os
import threading

from magnolie_native_book_json import book_hash
from magnolie_personal_actor_store import NativeBookOwnerScope, NativeProducerBookSnapshot


class NativeContactSourceBook:
    def __init__(self):
        self._lock = threading.RLock()
        self._owner = NativeBookOwnerScope()
        self._observed = None

    def set_ready(self, ready):
        with self._lock:
            self._owner.set_ready(ready)
            if not ready:
                self._observed = None

    def invalidate_saved(self):
        """Before the existing writer touches snapshots/encryption/storage.

        Preserve native book identity/save sequence, but no old saved witness
        may survive an unconfirmed attempt or a repair-pending acknowledgment.
        """
        with self._lock:
            self._observed = None

    def record_saved(self, binding, available, payload):
        """Native writer only, after its confirmed commit AND repair checks."""
        with self._lock:
            self._observed = None
            try:
                if not isinstance(payload, str):
                    return None
                data = json.loads(payload)
                if not isinstance(data, dict):
                    return None
                fingerprint = book_hash(data)
                saved_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            except (TypeError, ValueError, UnicodeError, OverflowError, RuntimeError):
                return None
            state = self._owner.record_saved(binding, available, saved_hash)
            if state is not None:
                self._observed = (state['book_source'], state['sequence'], fingerprint)
            return state

    def current(self, binding, available, data):
        with self._lock:
            state = self._owner.save_state(binding, available)
            observed = self._observed
            if state is None:
                self._observed = None
                return None
            if observed is None or (state['book_source'], state['sequence']) != observed[:2]:
                return None
            try:
                return state if isinstance(data, dict) and book_hash(data) == observed[2] else None
            except (TypeError, ValueError, UnicodeError, OverflowError, RuntimeError):
                return None

    def capture(self, binding, available, data):
        with self._lock:
            return NativeProducerBookSnapshot.capture(
                lambda: self.current(binding, available, data), lambda: data,
                lambda: self._observed)


class NativeContactSourceSavedWitness:
    """Process-local confirmed-writer evidence, never a JSON/transport grant.

    Only the exact completed invocation retains this witness. A copied result
    Boolean, a look-alike owner or a reconstructed object cannot attest itself.
    Consumers must recheck immediately before generating an authenticated ACK.
    """
    def __init__(self, owner):
        self._owner = owner

    def require_current(self):
        owner = self._owner
        if type(owner) is not NativeContactSourceResultCommit:
            raise PermissionError('contact_source_native_saved_witness_required')
        return NativeContactSourceResultCommit._require_saved_witness(owner, self)


class NativeContactSourceResultCommit:
    """Exact one-use native proposal -> existing writer invocation.

    Not an IPC type or a document permission. Native orchestration supplies the
    proposal and current-book/session callbacks; any attempted invocation consumes
    it, including denial or an unknown outcome. Ordinary saves keep their policy.
    """
    def __init__(self, snapshot, proposal, capture_current, require_session, *, serialized=None):
        if (type(snapshot) is not NativeProducerBookSnapshot or not isinstance(proposal, dict) or
                not callable(capture_current) or not callable(require_session)):
            raise TypeError('contact_source_native_result_required')
        self._lock = threading.RLock()
        self._snapshot, self._capture, self._session = snapshot, capture_current, require_session
        self._used, self._written, self._result = False, False, None
        self._saved_witness, self._confirmed_snapshot = None, None
        self.offer_token = None
        self.done = threading.Event()
        canonical = json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        self._content_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        if serialized is not None and (not isinstance(serialized, str) or
                book_hash(json.loads(serialized)) != self._content_hash):
            raise ValueError('contact_source_exact_result_required')
        self._text = canonical if serialized is None else serialized
        self._canonical = canonical
        self._hash = hashlib.sha256(self._text.encode('utf-8')).hexdigest()
        original = snapshot.book()
        if (hashlib.sha256(snapshot.text.encode('utf-8')).hexdigest() != snapshot.content_sha256 or
                {k: v for k, v in proposal.items() if k != 'kontakte'} !=
                {k: v for k, v in original.items() if k != 'kontakte'} or
                not isinstance(proposal.get('kontakte'), list) or
                [(item.get('id'), item.get('uid')) for item in proposal['kontakte']] !=
                [(item.get('id'), item.get('uid')) for item in original.get('kontakte', [])]):
            raise ValueError('contact_source_exact_result_scope_required')
        self._require_current()

    @property
    def text(self):
        return self._text

    @property
    def result(self):
        with self._lock:
            return dict(self._result) if self._result is not None else None

    def saved_witness(self):
        with self._lock:
            witness = self._saved_witness
            if type(witness) is not NativeContactSourceSavedWitness:
                raise PermissionError('contact_source_save_unconfirmed')
        witness.require_current()
        return witness

    def _require_saved_witness(self, witness):
        with self._lock:
            expected = self._confirmed_snapshot
            if (type(witness) is not NativeContactSourceSavedWitness or self._saved_witness is not witness or
                    expected is None or not self.done.is_set() or self._result is None or
                    self._result['confirmed'] is not True):
                raise PermissionError('contact_source_native_saved_witness_required')
            self._session()
            current = self._capture()
            self._session()
            if type(current) is not NativeProducerBookSnapshot or current != expected:
                raise PermissionError('contact_source_saved_witness_stale')
            return (current.book_source, current.sequence, current.saved_sha256, current.content_sha256)

    def _require_current(self):
        self._session()
        current = self._capture()
        if type(current) is not NativeProducerBookSnapshot or current != self._snapshot:
            raise PermissionError('contact_source_saved_book_changed')

    def write(self, payload, native_write):
        with self._lock:
            if self._used:
                raise PermissionError('contact_source_result_commit_consumed')
            self._used = True
            if payload != self._text or not callable(native_write):
                raise PermissionError('contact_source_exact_result_required')
            self._require_current()
            native_write(payload)
            self._written = True

    def complete(self, acknowledgment):
        """Existing writer only, after repair checks and new native observation."""
        with self._lock:
            if self.done.is_set():
                return
            self._used = True
            confirmed = False
            try:
                current = self._capture()
                confirmed = (self._written and acknowledgment.get('ok') is True and
                    acknowledgment.get('committed') is True and acknowledgment.get('repairPending') is False and
                    acknowledgment.get('standSha256') == self._hash and
                    type(current) is NativeProducerBookSnapshot and current.book_source == self._snapshot.book_source and
                    current.sequence == self._snapshot.sequence + 1 and current.saved_sha256 == self._hash and
                    current.content_sha256 == self._content_hash and current.text == self._canonical)
            except Exception:
                pass
            self._result = {'confirmed': bool(confirmed),
                            'committed': acknowledgment.get('committed') is True,
                             'repairPending': acknowledgment.get('repairPending') is True}
            if confirmed:
                self._confirmed_snapshot = current
                self._saved_witness = NativeContactSourceSavedWitness(self)
            self.done.set()


class NativeContactSourceCommitOffer:
    """Opaque one-use offer, never reconstructible from renderer JSON.

    Renderer serialization may differ in property order/whitespace, but must
    match the entire exact native proposal structure (including number types).
    The resulting invocation then binds THAT exact raw text to the real writer.
    """
    def __init__(self, snapshot, proposal, capture_current, require_session):
        validated = NativeContactSourceResultCommit(snapshot, proposal, capture_current, require_session)
        self._snapshot, self._text = snapshot, validated.text
        self._capture, self._session = capture_current, require_session
        self._lock, self._used = threading.RLock(), False
        self.token = os.urandom(32).hex()

    def offer(self):
        with self._lock:
            if self._used:
                raise PermissionError('contact_source_result_offer_consumed')
            return {'token': self.token, 'originalSha256': self._snapshot.saved_sha256,
                    'kontakte': json.loads(self._text)['kontakte']}

    def claim(self, token, payload):
        with self._lock:
            if self._used:
                raise PermissionError('contact_source_result_offer_consumed')
            self._used = True
            if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
                raise PermissionError('contact_source_result_offer_unknown')
            invocation = NativeContactSourceResultCommit(self._snapshot, json.loads(self._text),
                self._capture, self._session, serialized=payload)
            invocation.offer_token = self.token
            return invocation
