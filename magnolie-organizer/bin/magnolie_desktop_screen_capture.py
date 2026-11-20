"""Bounded, local PipeWire video reader for one approved ScreenCast target.

No product entry, encoder, sender or input. Call start on the portal's main
context; the worker only sees a duplicated descriptor and revocation event.
"""

from dataclasses import dataclass
import os
from secrets import token_hex
from selectors import DefaultSelector, EVENT_READ
import subprocess
from threading import Event, Lock, Thread
from time import monotonic


_TOOL = '/usr/bin/gst-launch-1.0'
_FRAME_S = 2
_STOP_S = .5


@dataclass(frozen=True)
class ScreenCastFrame:
    sequence: int
    rgbx: bytes


def _command(fd, serial, width, height):
    return [_TOOL, '-q', 'pipewiresrc', f'fd={fd}', f'target-object={serial}',
            'stream-properties=props,media.type=Video,node.dont-reconnect=true,node.dont-fallback=true', '!',
            'video/x-raw,width=(int)[1,4096],height=(int)[1,4096],framerate=(fraction)[0/1,120/1]', '!',
            'videorate', 'drop-only=true', 'max-rate=15', '!', 'videoconvert', '!',
            'video/x-raw,format=RGB', '!',
            'videoscale', 'add-borders=true', '!',
            f'video/x-raw,width={width},height={height},pixel-aspect-ratio=1/1', '!', 'videoconvert', '!',
            'video/x-raw,format=RGBx', '!',
            'fdsink', 'fd=1', 'sync=false']


class DesktopScreenCapture:
    """A latest-frame slot, not a sender or a claim that a monitor exists."""

    @classmethod
    def start(cls, remote, target, width, height):
        if (type(width) is not int or type(height) is not int or not 16 <= width <= 1920 or
                not 16 <= height <= 1920 or width * height > 1920 * 1080):
            raise ValueError('screen_cast_capture_size_invalid')
        serial = target.serial
        if type(serial) is not int or not 0 < serial < 2**64:
            raise PermissionError('screen_cast_original_serial_required')
        if not os.access(_TOOL, os.X_OK):
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
