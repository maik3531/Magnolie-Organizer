"""Native saved-book boundary for original-contact updates; no source grants.

Only the existing native writer records a commit. Document fields, renderer ACKs
and phone-actor ownership are not substitutes for this independent observation.
Callers hold the native data lock while observing/replacing the current book.
"""
import hashlib
import json
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
