"""Bounded, local PipeWire video reader for one approved ScreenCast target.

No product entry, encoder, sender or input. Call start on the portal's main
context; the worker only sees a duplicated descriptor and revocation event.
"""

from dataclasses import dataclass
from fractions import Fraction
import os
from secrets import token_hex
from selectors import DefaultSelector, EVENT_READ
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic


_PYTHON = '/usr/bin/python3'
_FRAME_S = 2
_STOP_S = .5


@dataclass(frozen=True)
class ScreenCastFrame:
    sequence: int
    rgbx: bytes


def _command(fd, serial, width, height):
    return [_PYTHON, '-I', os.path.abspath(__file__), f'fd={fd}', f'target-object={serial}', str(width), str(height)]


def _pipeline(fd, serial, width, height):
    return ' '.join(['pipewiresrc', f'fd={fd}', f'target-object={serial}',
            'stream-properties=props,media.type=Video,node.dont-reconnect=true,node.dont-fallback=true', '!',
            'video/x-raw,width=(int)[1,4096],height=(int)[1,4096],framerate=(fraction)[0/1,120/1]', '!',
            'identity', 'name=source_geometry', '!',
            'videorate', 'drop-only=true', 'max-rate=15', '!', 'videoconvert', '!',
            'video/x-raw,format=RGB', '!',
            'videoscale', 'add-borders=true', '!',
            f'video/x-raw,width={width},height={height},pixel-aspect-ratio=1/1', '!', 'videoconvert', '!',
            'video/x-raw,format=RGBx', '!',
            'fdsink', 'fd=1', 'sync=false'])


def _source_geometry(caps):
    if caps is None or not caps.is_fixed() or caps.get_size() != 1:
        return None
    fields = caps.get_structure(0)
    width_ok, width = fields.get_int('width')
    height_ok, height = fields.get_int('height')
    if (fields.get_name() != 'video/x-raw' or not width_ok or not height_ok or
            not 0 < width <= 4096 or not 0 < height <= 4096):
        return None
    ratio = Fraction(1)
    if fields.has_field('pixel-aspect-ratio'):
        valid, num, den = fields.get_fraction('pixel-aspect-ratio')
        if not valid or num <= 0 or den <= 0:
            return None
        ratio = Fraction(num, den)
    return width, height, ratio


def _pin_source_geometry(Gst, pad):
    """Observe the original CAPS before transforms can hide a change."""
    retired = Event()
    original = None

    def probe(_pad, info):
        nonlocal original
        if retired.is_set():
            return Gst.PadProbeReturn.DROP
        if info.type & Gst.PadProbeType.EVENT_DOWNSTREAM:
            event = info.get_event()
            if event.type != Gst.EventType.CAPS:
                return Gst.PadProbeReturn.OK
            geometry = _source_geometry(event.parse_caps())
            if geometry is not None and (original is None or geometry == original):
                original = geometry
                return Gst.PadProbeReturn.OK
        elif original is not None:
            return Gst.PadProbeReturn.OK
        retired.set()
        return Gst.PadProbeReturn.DROP

    pad.add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM | Gst.PadProbeType.BUFFER | Gst.PadProbeType.BUFFER_LIST, probe)
    return retired


def _child(args):
    # This optional GI backend is isolated with the original PipeWire FD and
    # the parent's usual bounded reap. Missing backend means no capture.
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst

    fd_arg, target_arg, width, height = args
    fd, serial = int(fd_arg.removeprefix('fd=')), int(target_arg.removeprefix('target-object='))
    width, height = int(width), int(height)
    if fd <= 2 or not 0 < serial < 2**64 or not _viewport(width, height):
        return 2
    Gst.init(None)
    pipeline = Gst.parse_launch(_pipeline(fd, serial, width, height))
    retired = _pin_source_geometry(Gst, pipeline.get_by_name('source_geometry').get_static_pad('src'))
    bus = pipeline.get_bus()
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            return 2
        while not retired.is_set():
            message = bus.timed_pop_filtered(20 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if message is not None:
                return 0 if message.type == Gst.MessageType.EOS else 2
        return 3
    finally:
        pipeline.set_state(Gst.State.NULL)


def _viewport(width, height):
    return (type(width) is int and type(height) is int and 16 <= width <= 1920 and
            16 <= height <= 1920 and width * height <= 1920 * 1080)


class DesktopScreenCapture:
    """A latest-frame slot, not a sender or a claim that a monitor exists."""

    @classmethod
    def start(cls, remote, target, width, height):
        if not _viewport(width, height):
            raise ValueError('screen_cast_capture_size_invalid')
        serial = target.serial
        if type(serial) is not int or not 0 < serial < 2**64:
            raise PermissionError('screen_cast_original_serial_required')
        if not os.access(_PYTHON, os.X_OK):
            raise FileNotFoundError('screen_cast_capture_tool_unavailable')
        fd, revoked, deadline = remote._claim_capture(target)
        try:
            return cls(fd, serial, width, height, revoked, deadline)
        except BaseException:
            os.close(fd)
            raise

    def __init__(self, fd, serial, width, height, revoked, deadline):
        self.width, self.height = width, height
        self._revoked, self._stop = revoked, Event()
        self._lock = Lock()
        self._latest = None
        self._ready = False
        self._end = Event()
        self._drained = False
        self.reason = None
        self._worker = Thread(target=self._work, args=(fd, serial, deadline), name='magnolie-screen-reader', daemon=True)
        self._worker.start()

    def _current(self):
        return not (self._stop.is_set() or self._revoked.is_set() or self._end.is_set())

    @property
    def ready(self):
        with self._lock:
            return self._current() and self._ready

    @property
    def finished(self):
        return self._end.is_set() and not self._worker.is_alive()

    @property
    def drained(self):
        return self.finished and self._drained

    def take_latest(self):
        with self._lock:
            latest, self._latest = self._latest, None
            return latest if self._current() else None

    def stop(self):
        self._stop.set()
        with self._lock:
            self._latest = None

    def _work(self, fd, serial, deadline):
        process = None
        clean = True
        try:
            first_deadline = min(deadline, monotonic() + _FRAME_S)
            if not self._current():
                return
            if monotonic() >= first_deadline:
                self.reason = 'screen_cast_capture_frame_timeout'
                return
            # If the plugin does not honor fd, there is no eligible default
            # server name in this worker. No pipeline string or PATH override.
            env = {key: value for key, value in os.environ.items() if not key.startswith('GST_')}
            env['PIPEWIRE_REMOTE'] = 'magnolie-unused-' + token_hex(16)
            process = subprocess.Popen(_command(fd, serial, self.width, self.height), env=env,
                                       pass_fds=(fd,), close_fds=True, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            self._read(process.stdout.fileno(), first_deadline)
        except (OSError, ValueError):
            if self._current():
                self.reason = 'screen_cast_capture_io_failed'
        finally:
            self.stop()
            if process is not None:
                clean = self._reap(process)
            try:
                os.close(fd)
            except OSError:
                clean = False
            self._drained = clean
            self._end.set()

    def _read(self, fd, deadline):
        frame_size = self.width * self.height * 4
        pending = bytearray()
        sequence = 0
        os.set_blocking(fd, False)
        with DefaultSelector() as selector:
            selector.register(fd, EVENT_READ)
            while self._current():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    self.reason = 'screen_cast_capture_frame_timeout'
                    return
                if not selector.select(min(remaining, .05)) or not self._current():
                    continue
                try:
                    part = os.read(fd, min(65536, frame_size - len(pending)))
                except BlockingIOError:
                    continue
                if not part:
                    self.reason = 'screen_cast_capture_partial_frame' if pending else 'screen_cast_capture_ended'
                    return
                pending.extend(part)
                if len(pending) == frame_size:
                    if monotonic() >= deadline:
                        self.reason = 'screen_cast_capture_frame_timeout'
                        return
                    with self._lock:
                        if not self._current():
                            return
                        self._latest = ScreenCastFrame(sequence, bytes(pending))
                        self._ready = True
                    sequence += 1
                    pending.clear()
                    deadline = monotonic() + _FRAME_S

    @staticmethod
    def _reap(process):
        clean = True
        try:
            process.stdout.close()
        except OSError:
            clean = False
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=_STOP_S)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=_STOP_S)
            return clean
        except (OSError, subprocess.TimeoutExpired):
            return False


if __name__ == '__main__':
    sys.exit(_child(sys.argv[1:]))
