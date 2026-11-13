"""Bounded native AV output for an explicitly admitted phone-camera session.

No camera capture, network listener, driver installation or device-default changes.
The authenticated transport must supply its original, revocable session guard.
Linux requires an existing writable v4l2loopback node and PulseAudio/PipeWire.
"""
import ctypes
import fcntl
import math
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
import threading
import time
import uuid


class WebcamUnavailable(Exception):
    pass


WIDTH, HEIGHT, FPS = 640, 480, 15
VIDEO_BYTES = WIDTH * HEIGHT * 3 // 2
SAMPLE_RATE, CHANNELS, AUDIO_SAMPLES = 48000, 1, 960
AUDIO_BYTES = AUDIO_SAMPLES * CHANNELS * 2


def _query_video(fd):
    body = bytearray(104)
    fcntl.ioctl(fd, 0x80685600, body, True)  # VIDIOC_QUERYCAP
    driver = bytes(body[:16]).split(b'\0', 1)[0]
    capabilities, device_caps = struct.unpack_from('=II', body, 84)
    caps = device_caps if capabilities & 0x80000000 else capabilities
    if driver not in (b'v4l2 loopback', b'v4l2loopback') or not caps & 0x2 or not caps & 0x01000000:
        raise WebcamUnavailable('webcam_existing_loopback_output_required')


class _FormatUnion(ctypes.Union):
    _fields_ = [('raw', ctypes.c_ubyte * 200), ('alignment', ctypes.c_uint64)]


class _Format(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint32), ('data', _FormatUnion)]


class LinuxVideoOutput:
    """A held loopback OUTPUT descriptor, never a physical camera capture FD."""
    def __init__(self, device):
        self.fd = None
        self.ready = False
        if type(device) is not str or not re.fullmatch(r'/dev/video[0-9]+', device):
            raise WebcamUnavailable('webcam_existing_loopback_output_required')
        try:
            self.fd = os.open(device, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
            if not stat.S_ISCHR(os.fstat(self.fd).st_mode):
                raise WebcamUnavailable('webcam_existing_loopback_output_required')
            _query_video(self.fd)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # v4l2_format's union has native 64-bit alignment on 64-bit Linux.
            body = bytearray(ctypes.sizeof(_Format))
            offset = _Format.data.offset
            struct.pack_into('=I', body, 0, 2)  # V4L2_BUF_TYPE_VIDEO_OUTPUT
            struct.pack_into('=IIIIII', body, offset, WIDTH, HEIGHT,
                             int.from_bytes(b'YU12', 'little'), 1, WIDTH, VIDEO_BYTES)
            request = 0xC0000000 | (len(body) << 16) | (ord('V') << 8) | 5
            fcntl.ioctl(self.fd, request, body, True)  # VIDIOC_S_FMT
            width, height, pixel, field, stride, size = struct.unpack_from('=IIIIII', body, offset)
            page = os.sysconf('SC_PAGE_SIZE')
            allocation = ((VIDEO_BYTES + page - 1) // page) * page
            # v4l2loopback may report a page-rounded allocation, not image
            # payload bytes. Keep the packed I420 geometry/stride and writes exact.
            if ((width, height, pixel, field, stride) != (
                    WIDTH, HEIGHT, int.from_bytes(b'YU12', 'little'), 1, WIDTH) or
                    size not in (VIDEO_BYTES, allocation)):
                raise WebcamUnavailable('webcam_native_video_format_unsupported')
            parameters = bytearray(204)
            struct.pack_into('=I', parameters, 0, 2)
            struct.pack_into('=II', parameters, 12, 1, FPS)
            fcntl.ioctl(self.fd, 0xC0CC5616, parameters, True)  # VIDIOC_S_PARM
            numerator, denominator = struct.unpack_from('=II', parameters, 12)
            if numerator != 1 or denominator != FPS:
                raise WebcamUnavailable('webcam_native_video_rate_unsupported')
            # Fail closed on missing timeout controls. A killed producer must
            # not leave its last personal frame presented indefinitely.
            for control, value in ((0x0098F901, 0), (0x0098F902, 1000)):
                setting = bytearray(struct.pack('=Ii', control, value))
                fcntl.ioctl(self.fd, 0xC008561C, setting, True)  # VIDIOC_S_CTRL
            self.ready = True
        except BaseException:
            self.close()
            raise

    def write(self, data):
        if self.fd is None:
            raise WebcamUnavailable('webcam_output_closed')
        try:
            count = os.write(self.fd, data)
        except BlockingIOError:
            return False  # Drop ONE complete video frame; no pending-frame queue.
        if count != len(data):
            raise WebcamUnavailable('webcam_native_video_short_write')
        return True

    def close(self):
        fd, self.fd = self.fd, None
        if fd is not None:
            try:
                # Limited-range I420 black, no retained personal image. The
                # kernel timeout also covers EAGAIN, process death and crashes.
                if self.ready:
                    os.write(fd, b'\x10' * (WIDTH * HEIGHT) + b'\x80' * (WIDTH * HEIGHT // 2))
            except OSError:
                pass
            finally:
                os.close(fd)


class LinuxAudioOutput:
    """One owned native microphone source; never changes the default input."""
    def __init__(self, session, owner_factory=None):
        if type(session) is not str or not re.fullmatch('[0-9a-f]{32}', session):
            raise ValueError('invalid webcam session identity')
        self.owner = self.fd = self.directory = None
        if owner_factory is None:
            from magnolie_phone_camera_pulse import PulsePipeSource
            owner_factory = PulsePipeSource
        self.name = 'magnolie_phone_' + session
        keeper = None
        try:
            # Private directory/FIFO: no user-controlled path or shared /tmp name.
            self.directory = tempfile.TemporaryDirectory(prefix='magnolie-webcam-')
            pipe = self.pipe = str(Path(self.directory.name) / 'microphone.pcm')
            os.mkfifo(pipe, 0o600)
            keeper = os.open(pipe, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
            self.owner = owner_factory(self.name, pipe)
            self.owner.require()
            self.fd = os.open(pipe, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
            self.owner.require()
        except BaseException:
            self.close()
            raise
        finally:
            if keeper is not None:
                os.close(keeper)

    def write(self, data):
        if self.fd is None:
            raise WebcamUnavailable('webcam_output_closed')
        self.owner.require()
        # One 20-ms packet is below PIPE_BUF. No silent partial/stale audio queue.
        try:
            count = os.write(self.fd, data)
        except (BlockingIOError, BrokenPipeError) as error:
            raise WebcamUnavailable('webcam_native_audio_backpressure') from error
        if count != len(data):
            raise WebcamUnavailable('webcam_native_audio_short_write')
        self.owner.require()
        return True

    def close(self):
        fd, self.fd = self.fd, None
        if fd is not None:
            os.close(fd)
        if self.owner is not None:
            self.owner.close()
            self.owner = None
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None


class _PresentationClock:
    """One fixed local anchor for BOTH tracks, never a clock per packet/track."""
    def __init__(self):
        self.anchor = self.first_pts = self.last_now = None

    def delay(self, pts_us, now):
        if not math.isfinite(now) or self.last_now is not None and now < self.last_now:
            raise WebcamUnavailable('webcam_presentation_clock_changed')
        self.last_now = now
        if self.anchor is None:
            self.anchor, self.first_pts = now, pts_us
        # Subtract integer PTS before conversion; large valid timestamps must
        # not lose their sub-second spacing through floating-point cancellation.
        due = self.anchor + (pts_us - self.first_pts) / 1_000_000
        remaining = due - now
        if remaining > .250 + 1e-9:
            raise WebcamUnavailable('webcam_presentation_too_far_ahead')
        if remaining < -.250 - 1e-9:
            raise WebcamUnavailable('webcam_presentation_too_late')
        if remaining <= 1e-9: return 0
        return min(max(remaining, 0), .010)


class NativeWebcamSession:
    """Both native outputs live and die together, with no reusable consent.

    Instances are NOT capabilities/advertisements or an Android consent token.
    Never pass an unconditional guard from the actual transport/UI integration.
    No capture is started here, including when audio is explicitly muted.
    """
    def __init__(self, device, guard, *, muted=False, video_factory=LinuxVideoOutput, audio_factory=LinuxAudioOutput,
                 clock=time.monotonic, identity=None, wait=None, prepare_only=False):
        if not callable(guard) or type(muted) is not bool or type(prepare_only) is not bool:
            raise ValueError('invalid webcam session')
        self.identity = uuid.uuid4().hex if identity is None else identity
        if type(self.identity) is not str or not re.fullmatch('[0-9a-f]{32}', self.identity):
            raise ValueError('invalid webcam session identity')
        self.guard, self.muted = guard, muted
        self.video = self.audio = None
        self.closed = False
        self.error = None
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.stop = threading.Event()
        self.wait = self.stop.wait if wait is None else wait
        if not callable(self.wait): raise ValueError('invalid webcam presentation wait')
        self.presentation = _PresentationClock()
        self.clock = clock
        self.started = None if prepare_only else clock()
        self.last_io = {}
        self.positions = {}
        try:
            self.guard()
            self.video = video_factory(device)
            self.guard()
            if not muted:
                self.audio = audio_factory(self.identity)
            self.guard()
            # The receiver additionally arms this ONLY after its original READY
            # control send and separate live data agreement have succeeded.
            # Original permission/deadline checks remain active during preparation.
            self.started = None if prepare_only else self.clock()
        except BaseException:
            self.close()
            raise
        self.monitor = threading.Thread(target=self._monitor, name='Magnolie webcam lifetime', daemon=True)
        self.monitor.start()

    def _monitor(self):
        while not self.stop.wait(.1):
            try:
                self.check_lifetime()
            except Exception as error:
                self.error = error
                return

    def check_lifetime(self):
        with self.lock:
            try:
                if self.closed:
                    raise WebcamUnavailable('webcam_session_retired')
                self.guard()
                now = self.clock()
                if self.started is None:
                    return  # Preparation is not SEND or media-arrival readiness.
                for stream in (('video',) if self.muted else ('video', 'audio')):
                    last = self.last_io.get(stream)
                    if (last is None and now - self.started > 2 or
                            last is not None and now - last > .5):
                        raise WebcamUnavailable('webcam_stream_timeout')
            except BaseException:
                self.close()
                raise

    def arm_media_deadline(self):
        """One-shot timing ONLY, not consent, READY, SEND or a PTS epoch.

        The original receiver must first recheck its separate real data guard.
        Every later write/monitor still invokes that SAME original live guard.
        """
        with self.lock:
            try:
                self.check_lifetime()
                if self.started is not None or self.positions:
                    raise WebcamUnavailable('webcam_media_deadline_already_armed')
                self.started = self.clock()
                self.guard()
            except BaseException:
                self.close()
                raise

    def _pace(self, pts_us):
        deadline = time.monotonic() + .300
        for _ in range(64):
            with self.lock:
                self.check_lifetime()
                delay = self.presentation.delay(pts_us, self.clock())
            if delay <= 0: return
            # No native-state lock while waiting: close and the lifetime monitor
            # can retire both outputs and wake this ORIGINAL one-packet wait.
            if time.monotonic() >= deadline:
                raise WebcamUnavailable('webcam_presentation_wait_timeout')
            if self.wait(delay): raise WebcamUnavailable('webcam_session_retired')
        raise WebcamUnavailable('webcam_presentation_wait_timeout')

    def write(self, stream, sequence, pts_us, data):
        # Serialize writes without blocking close/monitor on the state lock.
        # There is no detached playback queue or extra copy of captured frames.
        with self.write_lock:
            try:
                with self.lock:
                    self.check_lifetime()
                    if self.started is None:
                        raise WebcamUnavailable('webcam_actual_sending_not_admitted')
                    if (stream not in ('video', 'audio') or stream == 'audio' and self.muted or
                            type(sequence) is not int or type(pts_us) is not int or
                            not 0 <= sequence < 2**63 or pts_us < 0 or pts_us > 9_007_199_254_740_991 or
                            type(data) is not bytes or len(data) != (VIDEO_BYTES if stream == 'video' else AUDIO_BYTES)):
                        raise WebcamUnavailable('webcam_packet_invalid')
                    previous = self.positions.get(stream)
                    if sequence != (previous[0] + 1 if previous else 0) or previous and pts_us <= previous[1]:
                        raise WebcamUnavailable('webcam_packet_stale')
                    other = self.positions.get('audio' if stream == 'video' else 'video')
                    if other and abs(pts_us - other[1]) > 250_000:
                        raise WebcamUnavailable('webcam_av_clock_diverged')
                self._pace(pts_us)
                with self.lock:
                    self.check_lifetime()
                    written = (self.video if stream == 'video' else self.audio).write(data)
                    self.positions[stream] = (sequence, pts_us)
                    self.last_io[stream] = self.clock()
                    self.guard()
                    return written
            except BaseException:
                self.close()
                raise

    def close(self):
        with self.lock:
            self.closed = True
            self.stop.set()
            try:
                if self.audio is not None:
                    self.audio.close()
            finally:
                if self.video is not None:
                    self.video.close()
