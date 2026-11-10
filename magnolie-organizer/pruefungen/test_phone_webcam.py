"""Native-output boundary tests; not phone capture or an OBS device acceptance."""
from pathlib import Path
import os
import stat
import struct
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_phone_webcam as webcam


class Output:
    def __init__(self, *_):
        self.closed = False
        self.frames = []
        self.failure = None

    def write(self, data):
        if self.failure:
            raise self.failure
        assert not self.closed
        self.frames.append(data)
        return True

    def close(self):
        self.closed = True


def session(guard=lambda: None, **options):
    return webcam.NativeWebcamSession('/dev/video42', guard,
        video_factory=Output, audio_factory=Output, **options)


def test_default_is_genuine_paired_output_not_silent_video_fallback():
    value = session()
    try:
        assert value.audio is not None and value.video is not None
        assert value.write('video', 0, 0, bytes(webcam.VIDEO_BYTES))
        assert value.write('audio', 0, 0, bytes(webcam.AUDIO_BYTES))
        assert value.positions == {'video': (0, 0), 'audio': (0, 0)}
    finally:
        value.close()
    assert value.audio.closed and value.video.closed
    with pytest.raises(webcam.WebcamUnavailable, match='retired'):
        value.write('video', 1, 66667, bytes(webcam.VIDEO_BYTES))


def test_unavailable_microphone_closes_video_instead_of_claiming_av_ready():
    video = Output()
    def unavailable(_):
        raise webcam.WebcamUnavailable('microphone unavailable')
    with pytest.raises(webcam.WebcamUnavailable, match='microphone'):
        webcam.NativeWebcamSession('/dev/video42', lambda: None,
            video_factory=lambda _: video, audio_factory=unavailable)
    assert video.closed


def test_only_explicit_mute_omits_audio_and_rejects_received_audio():
    value = session(muted=True)
    assert value.audio is None
    with pytest.raises(webcam.WebcamUnavailable, match='packet_invalid'):
        value.write('audio', 0, 0, bytes(webcam.AUDIO_BYTES))
    assert value.closed and value.video.closed


@pytest.mark.parametrize('change', ['replay', 'sequence_gap', 'clock_backwards', 'clock_drift', 'short', 'bool', 'unknown'])
def test_bad_packet_retires_both_outputs_permanently(change):
    value = session()
    value.write('video', 0, 100, bytes(webcam.VIDEO_BYTES))
    value.write('audio', 0, 100, bytes(webcam.AUDIO_BYTES))
    stream, seq, pts, data = 'video', 1, 66767, bytes(webcam.VIDEO_BYTES)
    if change == 'replay': seq = 0
    if change == 'sequence_gap': seq = 2
    if change == 'clock_backwards': pts = 100
    if change == 'clock_drift': pts = 300101
    if change == 'short': data = data[:-1]
    if change == 'bool': seq = True
    if change == 'unknown': stream = 'not-a-stream'
    with pytest.raises(webcam.WebcamUnavailable):
        value.write(stream, seq, pts, data)
    assert value.closed and value.audio.closed and value.video.closed
    assert len(value.video.frames) == 1


def test_revoked_original_guard_never_revives_on_return_to_same_consent():
    allowed = True
    def guard():
        if not allowed:
            raise PermissionError('revoked')
    value = session(guard)
    allowed = False
    with pytest.raises(PermissionError):
        value.write('video', 0, 0, bytes(webcam.VIDEO_BYTES))
    allowed = True
    with pytest.raises(webcam.WebcamUnavailable, match='retired'):
        value.write('video', 0, 0, bytes(webcam.VIDEO_BYTES))
    assert not value.video.frames and value.audio.closed and value.video.closed


def test_audio_failure_retires_both_and_does_not_retry_stale_audio():
    value = session()
    value.audio.failure = webcam.WebcamUnavailable('backpressure')
    with pytest.raises(webcam.WebcamUnavailable, match='backpressure'):
        value.write('audio', 0, 0, bytes(webcam.AUDIO_BYTES))
    assert value.closed and value.audio.closed and value.video.closed


def test_whole_video_frame_backpressure_drops_without_queue_or_sequence_reuse():
    value = session()
    value.video.write = lambda _: False
    assert value.write('video', 0, 0, bytes(webcam.VIDEO_BYTES)) is False
    assert value.positions['video'] == (0, 0) and not value.closed
    value.close()


def video_kernel(monkeypatch, *, driver=b'v4l2 loopback', wrong_format=False):
    writes, controls, closes = [], [], []
    monkeypatch.setattr(webcam.os, 'open', lambda *_: 91)
    monkeypatch.setattr(webcam.os, 'fstat', lambda _: type('Stat', (), {'st_mode': stat.S_IFCHR})())
    monkeypatch.setattr(webcam.os, 'close', closes.append)
    monkeypatch.setattr(webcam.os, 'write', lambda fd, data: writes.append(data) or len(data))
    monkeypatch.setattr(webcam.fcntl, 'flock', lambda *_: None)
    def ioctl(fd, request, body, mutate):
        assert fd == 91 and mutate
        if request == 0x80685600:
            body[:len(driver)] = driver
            struct.pack_into('=II', body, 84, 0x80000000, 0x01000002)
        elif request == 0xC008561C:
            controls.append(struct.unpack('=Ii', body))
        elif request == 0xC0CC5616:
            assert struct.unpack_from('=II', body, 12) == (1, 15)
        else:
            assert request & 0xffff == 0x5605
            assert len(body) == 208 and webcam._Format.data.offset == 8
            if wrong_format:
                struct.pack_into('=I', body, webcam._Format.data.offset, 320)
    monkeypatch.setattr(webcam.fcntl, 'ioctl', ioctl)
    return writes, controls, closes


def test_actual_video_adapter_requests_native_output_format_and_crash_timeout(monkeypatch):
    writes, controls, closes = video_kernel(monkeypatch)
    value = webcam.LinuxVideoOutput('/dev/video42')
    assert value.write(bytes(webcam.VIDEO_BYTES))
    value.close(); value.close()
    assert controls == [(0x0098F901, 0), (0x0098F902, 1000)]
    assert len(writes) == 2 and writes[-1] == b'\x10' * (640 * 480) + b'\x80' * (640 * 480 // 2)
    assert closes == [91]


@pytest.mark.parametrize('change', ['physical_camera', 'format'])
def test_native_video_refuses_physical_capture_and_format_substitution(monkeypatch, change):
    writes, _, closes = video_kernel(monkeypatch,
        driver=b'uvcvideo' if change == 'physical_camera' else b'v4l2 loopback', wrong_format=change == 'format')
    with pytest.raises(webcam.WebcamUnavailable):
        webcam.LinuxVideoOutput('/dev/video42')
    assert not writes and closes == [91]


@pytest.mark.parametrize('path', ['/tmp/video42', '/dev/video42/../video0', '/dev/video42;anything', None])
def test_native_video_rejects_non_device_paths_without_opening(monkeypatch, path):
    opening = Mock(side_effect=AssertionError('unexpected device open'))
    monkeypatch.setattr(webcam.os, 'open', opening)
    with pytest.raises(webcam.WebcamUnavailable):
        webcam.LinuxVideoOutput(path)
    opening.assert_not_called()


def test_native_microphone_is_real_fifo_source_and_never_changes_default(monkeypatch):
    monkeypatch.setattr(webcam.shutil, 'which', lambda _: '/usr/bin/pactl')
    calls = []; name = 'magnolie_phone_' + 'a' * 32; pipe = None; reader = None
    def command(args):
        nonlocal pipe, reader
        calls.append(args)
        if args[1] == 'load-module':
            pipe = next(arg[5:] for arg in args if arg.startswith('file='))
            assert stat.S_ISFIFO(os.stat(pipe).st_mode) and os.stat(pipe).st_mode & 0o777 == 0o600
            reader = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
            return '42\n'
        if args[-1] == 'sources': return '9\t' + name + '\tmodule-pipe-source\ts16le 1ch 48000Hz\tIDLE\n'
        if args[-1] == 'modules': return '42\tmodule-pipe-source\tsource_name=' + name + ' file=' + pipe + '\t0\n'
        assert args[1:] == ['unload-module', '42']; return ''
    value = webcam.LinuxAudioOutput('a' * 32, command=command)
    try:
        assert value.write(b'\x12\x34' * webcam.AUDIO_SAMPLES)
        assert os.read(reader, webcam.AUDIO_BYTES) == b'\x12\x34' * webcam.AUDIO_SAMPLES
    finally:
        value.close()
        if reader is not None: os.close(reader)
    assert not Path(pipe).exists()
    assert [call[1] for call in calls] == ['load-module', 'list', 'list', 'unload-module']


def test_audio_cleanup_never_unloads_reused_foreign_module_id(monkeypatch):
    value = object.__new__(webcam.LinuxAudioOutput)
    calls = []
    value.fd = value.directory = None
    value.module = '42'; value.name = 'magnolie_phone_' + 'a' * 32
    value.pipe = '/private/owned/microphone.pcm'; value.pactl = '/usr/bin/pactl'
    value.command = lambda args: calls.append(args) or '42\tmodule-pipe-source\tsource_name=foreign file=/foreign\t0\n'
    value.close()
    assert len(calls) == 1 and calls[0][-1] == 'modules' and value.module is None


def test_pair_cleanup_closes_camera_even_if_audio_server_refuses_unload():
    value = session()
    value.audio.close = Mock(side_effect=webcam.WebcamUnavailable('unload failed'))
    with pytest.raises(webcam.WebcamUnavailable, match='unload failed'):
        value.close()
    assert value.closed and value.video.closed


@pytest.mark.parametrize('scenario', ['startup_missing_audio', 'stalled_video', 'stalled_audio'])
def test_common_lifetime_stops_both_outputs_when_either_track_is_missing(scenario):
    now = [0.0]
    value = session(clock=lambda: now[0])
    value.write('video', 0, 0, bytes(webcam.VIDEO_BYTES))
    if scenario != 'startup_missing_audio':
        value.write('audio', 0, 0, bytes(webcam.AUDIO_BYTES))
    now[0] = 2.1 if scenario == 'startup_missing_audio' else .6
    if scenario == 'stalled_video': value.last_io['audio'] = now[0]
    else: value.last_io['video'] = now[0]
    with pytest.raises(webcam.WebcamUnavailable, match='stream_timeout'):
        value.check_lifetime()
    value.monitor.join(timeout=1)
    assert value.closed and value.video.closed and value.audio.closed and not value.monitor.is_alive()


def test_lifetime_monitor_revokes_without_another_incoming_packet():
    now = [0.0]
    value = session(clock=lambda: now[0])
    now[0] = 3.0
    value.monitor.join(timeout=1)
    assert not value.monitor.is_alive() and value.closed
    assert isinstance(value.error, webcam.WebcamUnavailable)
