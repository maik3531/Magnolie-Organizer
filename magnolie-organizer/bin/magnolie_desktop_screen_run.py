"""Join one portal selection, reader and encoder on the native main context (#245).

No product registration or network permission is implied by local readiness.
"""

from dataclasses import dataclass
from threading import Event
from time import monotonic

from gi.repository import GLib

from magnolie_desktop_screen_capture import DesktopScreenCapture
from magnolie_desktop_screen_cast import DesktopScreenCast
from magnolie_desktop_screen_encode import DesktopScreenEncoder


@dataclass(frozen=True)
class ScreenRunCleanup:
    portal_closed: bool
    reader_drained: bool
    encoder_drained: bool


class DesktopScreenLocalRun:
    def __init__(self, bus, provider, mode, parent_window, width, height, require_original, ended):
        self._portal = DesktopScreenCast(bus, provider, mode, parent_window, require_original,
                                         self._selected, self._portal_ended)
        self._size = width, height
        self._ended = ended
        self._phase = 'new'
        self._target = self._capture = self._encoder = self._timer = self._portal_result = None
        self._media_ready = False
        self._media_retired = Event()

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
        return (self._media_ready and self._current() and self._capture.ready
                and not self._encoder.failed and not self._encoder.drained)

    def take_latest(self):
        if not self.ready:
            return None
        return self._encoder.take_latest()

    def media_current(self):
        """Worker-safe check; never reads or drives the GTK/portal context."""
        capture, encoder = self._capture, self._encoder
        return (not self._media_retired.is_set() and capture is not None and capture.ready and
                encoder is not None and not encoder.failed and not encoder.drained)

    def stop(self):
        if self._phase in ('closing', 'ended'):
            return
        self._phase = 'closing'
        self._retire_media()
        self._portal.stop()

    def _portal_ended(self, confirmed):
        if self._portal_result is not None:
            return
        self._portal_result = confirmed
        self._phase = 'closing'
        self._retire_media()
        self._finish_if_joined()

    def _retire_media(self):
        self._media_retired.set()
        if self._encoder is not None:
            self._encoder.stop()
        if self._capture is not None:
            self._capture.stop()

    def _tick(self):
        if self._phase == 'live':
            try:
                self._pump()
            except Exception:
                self.stop()
        self._finish_if_joined()
        return self._phase != 'ended'

    def _pump(self):
        if not self._current() or self._capture.finished:
            self.stop()
            return
        if not self._media_ready and monotonic() >= self._portal.setup_deadline:
            self.stop()
            return
        if self._encoder is not None:
            if self._encoder.failed or self._encoder.drained:
                self.stop()
                return
            if not self._media_ready and self._encoder.has_frame:
                if monotonic() >= self._portal.setup_deadline:
                    self.stop()
                    return
                self._media_ready = True
        frame = self._capture.take_latest()
        if frame is not None:
            if self._encoder is None:
                self._encoder = DesktopScreenEncoder(*self._size)
            self._encoder.offer(frame)

    def _finish_if_joined(self):
        if self._phase != 'closing' or self._portal_result is None:
            return
        if self._capture is not None and not self._capture.finished:
            return
        if self._encoder is not None and not self._encoder.drained:
            return
        drained = self._capture is None or self._capture.drained
        self._phase = 'ended'
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        self._ended(ScreenRunCleanup(self._portal_result, drained, True))
