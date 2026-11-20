"""Bounded local JPEG encoder; this module never opens a socket or grants SEND."""

from dataclasses import dataclass
from io import BytesIO
from threading import Condition, Thread

from magnolie_desktop_screen_capture import ScreenCastFrame


MAX_JPEG_BYTES = 1_048_576
_QUALITY = (70, 48)


class _Oversize(Exception):
    pass


class _BoundedOutput(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_JPEG_BYTES:
            raise _Oversize
        return super().write(data)


@dataclass(frozen=True)
class DesktopScreenJpeg:
    sequence: int
    data: bytes


def _encode(rgbx, size, current):
    from PIL import Image  # Optional, only imported inside an explicitly started worker.

    if not current():
        return None
    with Image.frombytes('RGB', size, rgbx, 'raw', 'RGBX') as image:
        for quality in _QUALITY:
            if not current():
                return None
            with _BoundedOutput() as output:
                try:
                    image.save(output, format='JPEG', quality=quality, subsampling=2,
                               progressive=False, optimize=False)
                except _Oversize:
                    continue
                return output.getvalue() if current() else None
        return None  # No partial JPEG or resized frame can escape the encoder.


class DesktopScreenEncoder:
    """Owns one in-flight job, one waiting RGBx frame and one finished JPEG."""

    def __init__(self, width, height):
        if (type(width) is not int or type(height) is not int or not 16 <= width <= 1920 or
                not 16 <= height <= 1920 or width * height > 1920 * 1080):
            raise ValueError('screen_cast_encode_size_invalid')
        self._size = width, height
        self._length = width * height * 4
        self._condition = Condition()
        self._pending = self._latest = None
        self._last_sequence = -1
        self._stopped = False
        self._failed = False
        self._worker = Thread(target=self._work, name='magnolie-screen-encoder', daemon=True)
        self._worker.start()

    def offer(self, frame):
        if (type(frame) is not ScreenCastFrame or type(frame.sequence) is not int or
                not 0 <= frame.sequence < 2**63 - 1 or type(frame.rgbx) is not bytes or
                len(frame.rgbx) != self._length):
            raise ValueError('screen_cast_encode_frame_invalid')
        with self._condition:
            if self._stopped or frame.sequence <= self._last_sequence:
                return False
            self._last_sequence = frame.sequence
            self._pending = frame
            self._condition.notify()
            return True

    def take_latest(self):
        with self._condition:
            latest, self._latest = self._latest, None
            return latest if not self._stopped else None

    @property
    def has_frame(self):
        with self._condition:
            return self._latest is not None and not self._stopped

    @property
    def drained(self):
        return not self._worker.is_alive()

    @property
    def failed(self):
        with self._condition:
            return self._failed

    def stop(self):
        with self._condition:
            self._stopped = True
            self._pending = self._latest = None
            self._condition.notify()

    def _current(self):
        with self._condition:
            return not self._stopped

    def _work(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stopped or self._pending is not None)
                    if self._stopped:
                        return
                    frame, self._pending = self._pending, None
                jpeg = _encode(frame.rgbx, self._size, self._current)
                with self._condition:
                    if self._stopped:
                        return
                    if jpeg is not None:
                        self._latest = DesktopScreenJpeg(frame.sequence, jpeg)
                del frame, jpeg
        except Exception:
            with self._condition:
                self._failed = True
        finally:
            self.stop()
