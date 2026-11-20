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
from magnolie_desktop_screen_output import KWinOutputFeed


_REMOVAL_WAIT_S = 1.5


@dataclass(frozen=True)
class ScreenRunCleanup:
    portal_closed: bool
    reader_drained: bool
    encoder_drained: bool
    virtual_start_submitted: bool = False
    virtual_output_removed: bool = False


class DesktopScreenLocalRun:
    def __init__(self, bus, provider, mode, parent_window, width, height, require_original, ended, *,
                 kde_output_feed=None):
        # Private opt-in composition only. The caller must already know that
        # this portal uses the KDE backend and own the feed through this run.
        if kde_output_feed is not None and (mode != 'extend' or type(kde_output_feed) is not KWinOutputFeed):
            raise ValueError('screen_cast_original_kde_output_feed_required')
        self._output_feed = kde_output_feed
        self._output = kde_output_feed.take_for_run() if kde_output_feed is not None else None
        self._portal = DesktopScreenCast(bus, provider, mode, parent_window, require_original,
                                         self._selected, self._portal_ended,
                                         before_virtual_start=None if kde_output_feed is None else kde_output_feed.mark_start)
        self._opening = False
        self._removal_deadline = None
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
            if self._output is not None:
                self._timer = GLib.timeout_add(50, self._tick)
            self._portal.begin()
        except Exception:
            self.stop()
            raise

    def _selected(self, original, target):
        if self._phase != 'live' or original is not self._portal:
            return
        self._target = target
        if self._output is not None and not self._output.bind(target):
            self.stop()
            return
        self._maybe_open()

    def _maybe_open(self):
        if not self._opening and self._current():
            self._opening = True
            self._portal.open_pipewire_remote(self._target, self._attach)

    def _attach(self, remote):
        if not self._current():
            self.stop()
            return
        self._capture = DesktopScreenCapture.start(remote, self._target, *self._size)
        if self._timer is None:
            self._timer = GLib.timeout_add(50, self._tick)

    def _current(self):
        return (self._phase == 'live' and self._target is not None and
                self._portal.selection_current(self._target) and
                (self._output is None or self._output.present(self._target)))

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
                encoder is not None and not encoder.failed and not encoder.drained and
                (self._output is None or self._output.present(self._target)))

    def output_removal_current(self):
        return (self._output is not None and self._portal.virtual_start_submitted and self._opening and
                self._output.removal_observed(self._target) and self._output_feed.settled)

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
        self._removal_deadline = monotonic() + _REMOVAL_WAIT_S
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
                if self._capture is not None:
                    self._pump()
                elif self._output is not None:
                    if (self._output.lost or monotonic() >= self._portal.setup_deadline or
                            self._output.removal_observed(self._target)):
                        self.stop()
                    elif self._target is not None:
                        self._maybe_open()
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
        output_removed = False
        if self._output is not None and self._opening and self._portal.virtual_start_submitted:
            output_removed = self.output_removal_current()
            if (not output_removed and self._portal_result and
                    (self._output.present(self._target) or self._output.removal_observed(self._target)) and
                    monotonic() < self._removal_deadline):
                return
        drained = self._capture is None or self._capture.drained
        self._phase = 'ended'
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        self._ended(ScreenRunCleanup(self._portal_result, drained, True, self._portal.virtual_start_submitted,
                                     output_removed))
