"""Isolated Linux composition for a single approved desktop-screen draft."""

from dataclasses import dataclass
import secrets
from threading import Event, Lock, Thread
from time import monotonic

from gi.repository import GLib

from magnolie_desktop_screen_control import DesktopScreenDraftChannel, DesktopScreenDraftControl
from magnolie_desktop_screen_run import DesktopScreenLocalRun, ScreenRunCleanup
from magnolie_desktop_screen_send import DesktopScreenSendLane


@dataclass(frozen=True)
class DesktopScreenAttemptCleanup:
    local: ScreenRunCleanup
    transport_drained: bool


class DesktopScreenDraftAttempt:
    """Native caller retains one slot through cleanup. Construct and begin on
    the GTK main context after explicit local approval; the trusted guard must
    work on either thread. The existing authenticated reader calls receive().
    No registration or automatic prompt is provided here.
    """

    def __init__(self, channel, request, require_original, *, bus, provider, mode,
                 parent_window, width, height, deadline, ended, require_terminal_parent=None, setup=None):
        if (type(request) is not dict or mode not in ('monitor', 'window', 'extend') or
                request.get('mode') != (2 if mode == 'extend' else 1)):
            raise ValueError('desktop_screen_original_mode_required')
        self._parent = channel
        self._stop = Event()
        self._media_ready = Event()
        self._resources = Lock()
        self._listener = self._lane = self._latest = None
        self._transport_clean = True
        self._wire = DesktopScreenDraftChannel(channel, require_original)
        self._terminal = DesktopScreenDraftChannel(channel, require_terminal_parent or require_original)
        self._control = DesktopScreenDraftControl(channel, request, self._wire.require_current, deadline=deadline,
                                                  setup=setup)
        self._local = DesktopScreenLocalRun(bus, provider, mode, parent_window, width, height,
                                           self._current, self._local_ended)
        self._mode = request['mode']
        self._size = width, height
        self._ended = ended
        self._local_result = self._timer = None
        self._begun = False
        self._worker = Thread(target=self._send, name='magnolie-desktop-screen-send', daemon=True)

    def begin(self):
        if self._begun or self._stop.is_set():
            raise RuntimeError('desktop_screen_original_attempt_already_used')
        self._begun = True
        self._timer = GLib.timeout_add(25, self._tick)
        try:
            self._local.begin()
        except Exception:
            self.stop()
            raise

    def _current(self):
        if self._stop.is_set():
            raise PermissionError('desktop_screen_original_attempt_retired')
        self._control.require_current()
        if self._stop.is_set() or (self._media_ready.is_set() and not self._local.media_current()):
            raise PermissionError('desktop_screen_original_attempt_retired')

    def receive(self, actual, packet):
        if self._stop.is_set() or not self._begun:
            return False
        body = self._wire.body_from(actual, packet)
        if body is None or not self._control.receive(actual, body):
            return False
        if body['op'] == 'stop':
            self.stop()
        return True

    def stop(self):
        """Signal-only across threads; GTK and join work stay on main."""
        self._stop.set()
        self._control.close()
        with self._resources:
            self._latest = None
            if self._listener is not None:
                try:
                    self._listener.close()
                except OSError:
                    self._transport_clean = False
            if self._lane is not None:
                self._lane.stop()

    def _local_ended(self, result):
        self._local_result = result
        self.stop()

    def _tick(self):
        if not self._stop.is_set():
            try:
                self._current()
                if self._local.ready:
                    frame = self._local.take_latest()
                    if frame is not None:
                        with self._resources:
                            if not self._stop.is_set():
                                self._latest = frame
                                if not self._media_ready.is_set():
                                    self._media_ready.set()
                                    self._worker.start()
                elif self._media_ready.is_set():
                    self.stop()
            except Exception:
                self.stop()
        if self._stop.is_set():
            self._local.stop()
            if self._local_result is not None and not self._worker.is_alive():
                self._timer = None
                drained = self._transport_clean and (self._lane is None or self._lane.drained)
                self._ended(DesktopScreenAttemptCleanup(self._local_result, drained))
                return False
        return True

    def _send(self):
        listener = None
        try:
            self._current()
            listener = self._wire.open_original_listener(self._current)
            with self._resources:
                self._current()
                self._listener = listener
            session, secret = secrets.token_bytes(16), secrets.token_bytes(32)
            width, height = self._size
            self._control.publish_offer(session=session.hex(), secret=secret.hex(), port=listener.port,
                                        width=width, height=height, write_original=self._wire.write)
            with listener.accept() as accepted:
                with self._resources:
                    self._current()
                    self._lane = DesktopScreenSendLane(accepted, session, secret, self._mode, width, height,
                                                      self._control.setup_deadline, self._current)
                del secret
                transcript = self._lane.prove()
                while not self._control.prepared_for(transcript):
                    self._stop.wait(.02)
                    self._current()
                self._lane.authorize_send(transcript, self._media_ready.is_set,
                    lambda guard: self._control.publish_send(transcript, guard, self._wire.write))
                heartbeat_at = monotonic() + .75
                while not self._stop.is_set():
                    self._control.require_send()
                    with self._resources:
                        frame, self._latest = self._latest, None
                    if frame is not None or monotonic() >= heartbeat_at:
                        self._lane.write_record(frame)
                        heartbeat_at = monotonic() + .75
                    else:
                        self._stop.wait(.02)
        except Exception:
            pass  # This draft attempt terminates; never retry on another parent.
        finally:
            if listener is not None:
                try:
                    listener.close()
                except OSError:
                    with self._resources:
                        self._transport_clean = False
            self.stop()
            try:
                self._control.publish_stop(self._terminal.write)
            except (OSError, ValueError):
                pass  # Best effort on the exact original transport; no retry.
