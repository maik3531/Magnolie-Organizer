"""Explicit acquired native setup -> deferred worker -> one-use UI dispatch.

Construction starts no thread/service and registers no action or capability.
The native host owns run()'s worker and post_ui's main-thread lifecycle. Status
is informational only, never source permission, a saved witness or a SaveACK.
"""
from dataclasses import dataclass
import threading

from magnolie_contact_notes_setup import NativeNotesSetupAcquisition


@dataclass(frozen=True)
class NativeNotesSetupSelectionView:
    peer: tuple
    export: dict


class NativeNotesSetupRun:
    _TERMINAL = frozenset(('configured', 'cancelled', 'waiting-network', 'held'))

    def __init__(self, acquisition, post_ui, choose_source, finished, *, choose_contact=None):
        if (type(acquisition) is not NativeNotesSetupAcquisition or
                not all(callable(value) for value in (post_ui, choose_source, finished)) or
                choose_contact is not None and not callable(choose_contact)):
            raise TypeError('notes_setup_native_run_required')
        self._acquisition, self._post, self._choose, self._finished = acquisition, post_ui, choose_source, finished
        self._contact = choose_contact
        self._lock, self.done = threading.RLock(), threading.Event()
        self._phase, self._pending, self._notice, self._candidates = 'created', None, None, ()

    @property
    def phase(self):
        with self._lock:
            return self._phase

    def run(self):
        """Called once by an explicit native worker, never by receive/main UI."""
        with self._lock:
            if self._phase != 'created':
                return
            self._phase = 'probing'
            acquisition = self._acquisition
        if threading.current_thread() is threading.main_thread():
            self._finish('held')
            return  # Never perform network/event waits on the native UI thread.
        try:
            if not acquisition.probe():
                self._finish('waiting-network')
                return
            with self._lock:
                if self._phase in self._TERMINAL:
                    return
                self._phase = 'waiting-export'
            candidates = acquisition.wait()  # Bounded/cancelled by the owned acquisition.
            token = object()
            with self._lock:
                if self._phase in self._TERMINAL:
                    return
                self._phase, self._pending, self._candidates = 'offering', token, candidates
            if self._post(lambda: self._choose_ui(token)) is not True:
                self._finish('held')
        except Exception:
            self._finish('held')

    def _choose_ui(self, token):
        with self._lock:
            if self._pending is not token or self._phase != 'offering':
                return False
            acquisition, candidates = self._acquisition, self._candidates
            self._candidates = ()
            self._pending, self._phase = None, 'choosing'
        if threading.current_thread() is not threading.main_thread():
            self._finish('held')
            return False
        try:
            acquisition.candidates()  # Recheck original private/native context BEFORE another dialog.
            valid, views = [], []
            for candidate in candidates:
                try:
                    view = NativeNotesSetupSelectionView(candidate.peer, candidate.display())
                except (PermissionError, ValueError, RuntimeError):
                    continue  # Isolate an expired/conflicting frame; never rematch by name/ID.
                valid.append(candidate); views.append(view)
            if not valid:
                self._finish('held')
                return False
            index = self._choose(tuple(views))  # Detached display; no book/tree/private gates held.
            if index is None:
                self.cancel()
                return False
            if type(index) is not int or not 0 <= index < len(valid):
                raise PermissionError('notes_setup_native_source_selection_required')
            configured = acquisition.configure(valid[index], self._contact)
            self._finish('configured' if configured else 'cancelled')
        except Exception:
            self._finish('held')
        return False  # One-shot native UI dispatch, not a polling callback.

    def cancel(self):
        self._finish('cancelled')

    def _finish(self, phase):
        with self._lock:
            if self._phase in self._TERMINAL:
                return
            self._phase, self._pending = phase, None
            acquisition, self._acquisition, self._candidates = self._acquisition, None, ()
            notice = self._notice = object()
        try:
            acquisition.stop()  # No callbacks under the run lock; only owned memory lanes.
        finally:
            self.done.set()
        def notify():
            with self._lock:
                if self._notice is not notice:
                    return False
                self._notice = None
            if threading.current_thread() is not threading.main_thread():
                return False
            try:
                self._finished(phase)  # Native UI status only, never a grant.
            except Exception:
                pass  # UI failure cannot replay or undo an actual source decision.
            return False
        try:
            self._post(notify)
        except Exception:
            pass  # A closed UI cannot keep worker/candidate authority alive.
