"""Join one portal selection and reader on the native main context (#245).

No product registration or network permission is implied by local readiness.
"""

from dataclasses import dataclass

from gi.repository import GLib

from magnolie_desktop_screen_capture import DesktopScreenCapture
from magnolie_desktop_screen_cast import DesktopScreenCast


@dataclass(frozen=True)
class ScreenRunCleanup:
    portal_closed: bool
    reader_drained: bool


class DesktopScreenLocalRun:
    def __init__(self, bus, provider, mode, parent_window, width, height, require_original, ended):
        self._portal = DesktopScreenCast(bus, provider, mode, parent_window, require_original,
                                         self._selected, self._portal_ended)
        self._size = width, height
        self._ended = ended
        self._phase = 'new'
        self._target = self._capture = self._timer = self._portal_result = None

    def begin(self):
        if self._phase != 'new':
            raise RuntimeError('screen_cast_local_run_already_used')
        self._phase = 'live'
        try:
            self._portal.begin()
        except Exception:
            self.stop()
            raise

    def _selected(self, original, target):
        if self._phase != 'live' or original is not self._portal:
            return
        self._target = target
        original.open_pipewire_remote(target, self._attach)

    def _attach(self, remote):
        if not self._current():
            return
        self._capture = DesktopScreenCapture.start(remote, self._target, *self._size)
        self._timer = GLib.timeout_add(50, self._tick)

    def _current(self):
        return (self._phase == 'live' and self._target is not None and
                self._portal.selection_current(self._target))

    @property
    def ready(self):
        return self._capture is not None and self._current() and self._capture.ready

    def take_latest(self):
        if self._capture is None or not self._current():
            return None
        return self._capture.take_latest()

    def stop(self):
        if self._phase in ('closing', 'ended'):
            return
        self._phase = 'closing'
        if self._capture is not None:
            self._capture.stop()
        self._portal.stop()

    def _portal_ended(self, confirmed):
        if self._portal_result is not None:
            return
        self._portal_result = confirmed
        self._phase = 'closing'
        if self._capture is not None:
            self._capture.stop()
        self._finish_if_joined()

    def _tick(self):
        if self._phase == 'live' and self._capture.finished:
            self.stop()
        self._finish_if_joined()
        return self._phase != 'ended'

    def _finish_if_joined(self):
        if self._phase != 'closing' or self._portal_result is None:
            return
        if self._capture is not None and not self._capture.finished:
            return
        drained = self._capture is None or self._capture.drained
        self._phase = 'ended'
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        self._ended(ScreenRunCleanup(self._portal_result, drained))
