"""Real encrypted socket to bounded native-output adapters, not installed capture."""
from pathlib import Path
import socket
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_phone_camera_receiver import WebcamReceiveRun
from magnolie_phone_camera_transport import WebcamMediaSocket
from magnolie_phone_webcam import NativeWebcamSession, VIDEO_BYTES, AUDIO_BYTES


class Output:
    def __init__(self, identity):
        self.identity = identity
        self.frames = []
        self.closed = False
        self.arrived = threading.Event()

    def write(self, data):
        assert not self.closed
        self.frames.append(data)
        self.arrived.set()
        return True

    def close(self):
        self.closed = True


def joined(guard=lambda: None, **options):
    left, right = socket.socketpair()
    identity, secret = 'a' * 32, bytes(range(32))
    sender = WebcamMediaSocket(left, identity, secret, guard, sending=True)
    def outputs(device, current, **settings):
        return NativeWebcamSession(device, current, video_factory=Output, audio_factory=Output, **settings)
    run = WebcamReceiveRun(right, identity, secret, '/dev/video42', guard, output_factory=outputs, **options)
    return sender, run


def test_actual_encrypted_av_packets_reach_paired_outputs_with_common_identity_then_stop():
    sender, run = joined()
    try:
        assert run.state == 'starting'
        assert run.outputs.identity == run.outputs.audio.identity == 'a' * 32
        sender.send('video', 0, 0, b'v' * VIDEO_BYTES)
        assert run.outputs.video.arrived.wait(timeout=1)
        assert run.state == 'starting'  # Video alone is NOT a ready AV session.
        sender.send('audio', 0, 0, b'a' * AUDIO_BYTES)
        assert run.outputs.audio.arrived.wait(timeout=1)
        # Serialize with the writer before inspecting its final state update.
        with run.outputs.lock:
            assert run.outputs.video.frames == [b'v' * VIDEO_BYTES]
            assert run.outputs.audio.frames == [b'a' * AUDIO_BYTES]
        run.stop()
        assert run.state == 'stopped' and run.outputs.video.closed and run.outputs.audio.closed
        assert not run.worker.is_alive() and not run.outputs.monitor.is_alive()
    finally:
        sender.close(); run.stop()


def test_transport_disconnect_closes_both_native_endpoints_without_another_packet():
    sender, run = joined()
    sender.close()
    try:
        assert run.ended.wait(timeout=1)
        assert run.state == 'failed' and run.outputs.video.closed and run.outputs.audio.closed
    finally: run.stop()


def test_early_native_timeout_closes_stalled_socket_and_both_endpoints():
    sender, run = joined()
    try:
        run.outputs.started -= 3
        assert run.ended.wait(timeout=1)
        assert run.state == 'failed' and run.channel.closed and run.outputs.closed
    finally: sender.close(); run.stop()


def test_original_guard_revocation_closes_actual_socket_and_outputs():
    allowed = [True]
    def guard():
        if not allowed[0]: raise PermissionError('revoked')
    sender, run = joined(guard)
    try:
        allowed[0] = False
        assert run.ended.wait(timeout=1)
        allowed[0] = True
        assert run.state == 'failed' and run.channel.closed and run.outputs.closed
    finally: sender.close(); run.stop()


def test_no_video_only_fallback_when_an_authenticated_audio_packet_is_invalid():
    sender, run = joined()
    try:
        sender.send('video', 0, 0, bytes(VIDEO_BYTES))
        assert run.outputs.video.arrived.wait(timeout=1)
        # Transport authentically encodes the packet; source sequence is stale.
        sender.send('audio', 8, 0, bytes(AUDIO_BYTES))
        assert run.ended.wait(timeout=1)
        assert run.state == 'failed' and not run.outputs.audio.frames
        assert run.outputs.video.closed and run.outputs.audio.closed
    finally: sender.close(); run.stop()
