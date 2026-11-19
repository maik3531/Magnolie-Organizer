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
        self.quiesced, self._active_work = threading.Event(), 0
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
            self._active_work += 1
        try:
            if threading.current_thread() is threading.main_thread():
                self._finish('held')
                return  # Never perform network/event waits on the native UI thread.
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
        finally:
            self._exit_work()

    def _choose_ui(self, token):
        with self._lock:
            if self._pending is not token or self._phase != 'offering':
                return False
            acquisition, candidates = self._acquisition, self._candidates
            self._candidates = ()
            self._pending, self._phase = None, 'choosing'
            self._active_work += 1
        try:
            if threading.current_thread() is not threading.main_thread():
                self._finish('held')
                return False
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
        finally:
            self._exit_work()
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
            self._try_quiesce()
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

    def _exit_work(self):
        with self._lock:
            self._active_work -= 1
        self._try_quiesce()

    def _try_quiesce(self):
        with self._lock:
            if self.done.is_set() and self._active_work == 0:
                self.quiesced.set()  # Started worker/dialog callbacks returned; not a UI-thread join.


class NativeNotesSetupHost:
    """Explicit UI-owned preparation/run lifetime; poll never waits on GTK."""
    def __init__(self, begin, cancel_prepare, launch_worker, post_ui, choose_source, choose_contact,
            finished, native_quiet):
        if not all(callable(value) for value in (begin, cancel_prepare, launch_worker, post_ui,
                choose_source, choose_contact, finished, native_quiet)):
            raise TypeError('notes_setup_native_host_required')
        self._begin, self._cancel_prepare, self._launch, self._post = begin, cancel_prepare, launch_worker, post_ui
        self._choose, self._contact, self._finished, self._quiet = choose_source, choose_contact, finished, native_quiet
        self.cancelled, self.quiesced = threading.Event(), threading.Event()
        self._lock = threading.RLock()
        self._run = self._worker = self._owned = None
        self._preparing, self._received, self._cancel_sent = False, False, False
        self._phase, self._result = 'created', None

    @property
    def phase(self):
        with self._lock:
            return self._phase

    @staticmethod
    def _ui():
        if threading.current_thread() is not threading.main_thread():
            raise PermissionError('notes_setup_native_ui_required')

    def start(self):
        self._ui()
        with self._lock:
            if self._phase != 'created' or self.cancelled.is_set():
                raise PermissionError('notes_setup_host_already_used')
            self._phase, self._preparing = 'preparing', True
        try:
            self._begin(self.acquired)
        except Exception:
            self.fail()

    def acquired(self, acquisition):
        self._ui()
        with self._lock:
            if self._received or self.quiesced.is_set():
                return
            self._received, self._preparing = True, False
        if self.cancelled.is_set():
            if type(acquisition) is NativeNotesSetupAcquisition: acquisition.stop()
            return
        if acquisition is None:
            self._result = 'cancelled'
            return
        if type(acquisition) is not NativeNotesSetupAcquisition:
            self.fail()
            return
        self._owned = acquisition
        self._run = NativeNotesSetupRun(acquisition, self._post, self._choose, lambda _: None,
            choose_contact=self._contact)
        self._phase = 'running'
        try:
            worker = self._launch(self._run.run)
            if type(worker) is not threading.Thread or worker.ident is None:
                raise TypeError('notes_setup_owned_started_worker_required')
            self._worker = worker
        except Exception:
            self.fail()

    def fail(self):
        self._ui()
        if self._result is None:
            self._result = 'cancelled' if self.cancelled.is_set() else 'held'
        self._preparing = False
        self.stop()

    def stop(self):
        self.cancelled.set()
        with self._lock:
            run = self._run
        if run is not None: run.cancel()
        # Native preparation/timer mutation is performed by poll on UI only.

    def poll(self):
        """UI timer: True while owned work remains, False after real quiescence."""
        self._ui()
        if self.quiesced.is_set(): return False
        if self.cancelled.is_set() and not self._cancel_sent:
            self._cancel_sent, self._preparing = True, False
            try: self._cancel_prepare()
            except Exception: self._result = 'held'
        if self._preparing or not self._quiet(): return True
        run, worker = self._run, self._worker
        if run is not None and not run.quiesced.is_set(): return True
        if worker is not None:
            if worker.is_alive(): return True
            worker.join(timeout=0)  # Actual thread join only AFTER it returned; never a blocking UI wait.
        result = self._result or (run.phase if run is not None else 'cancelled')
        if self._owned is not None: self._owned.stop()
        self._run = self._worker = self._owned = None
        finished, self._finished = self._finished, None
        self._begin = self._cancel_prepare = self._launch = self._choose = self._contact = self._quiet = None
        self._phase = result
        self.quiesced.set()
        try: finished(result)  # Informational native UI callback only, not an ACK or source grant.
        except Exception: pass
        return False
