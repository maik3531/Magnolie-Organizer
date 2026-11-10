"""Real local control/media TCP sockets + generated outputs, not installed AV."""
from pathlib import Path
import socket
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_phone_camera_control import REQUEST, REPORT, validate_body
from magnolie_phone_camera_exchange import DesktopWebcamControlExchange
from magnolie_phone_camera_transport import WebcamMediaSocket
from magnolie_phone_webcam import NativeWebcamSession, VIDEO_BYTES, AUDIO_BYTES


class Output:
    def __init__(self, identity):
        self.identity, self.closed, self.frames = identity, False, []
        self.arrived = threading.Event()
    def write(self, value):
        assert not self.closed
        self.frames.append(value); self.arrived.set()
        return True
    def close(self): self.closed = True


class Fixture:
    def __init__(self):
        server = socket.socket()
        try:
            server.bind(('127.0.0.1', 0)); server.listen(1)
            self.phone_control = socket.create_connection(server.getsockname(), timeout=2)
            self.desktop_control, _ = server.accept()
            self.desktop_control.settimeout(2)
        finally: server.close()
        self.parent, self.live, self.now = object(), True, 1.0
        self.exchange = DesktopWebcamControlExchange(self.parent, self.desktop_control, self.current, clock=lambda: self.now)
        self.probe = dict(version=24, request_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', nonce='b' * 64, op='probe')
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0)); self.listener.listen(1); self.listener.settimeout(2)
        self.media = []
        self.outputs = []
        self.ready = []
    def current(self):
        if not self.live: raise PermissionError('original native Organizer opt-in retired')
    def offer(self):
        self.value = self.exchange.offer(self.parent, self.probe, self.listener)
        validate_body(self.value, REPORT)
        return self.value
    def packet(self, op):
        return dict(self.probe, op=op, session=self.value['session'])
    def connect(self):
        phone = socket.create_connection(('127.0.0.1', self.value['port']), timeout=2)
        accepted, _ = self.listener.accept()
        self.media += [phone, accepted]
        return phone, accepted
    def native(self, device, guard, **settings):
        value = NativeWebcamSession(device, guard, video_factory=Output, audio_factory=Output, **settings)
        self.outputs.append(value)
        return value
    def send_ready(self, value):
        validate_body(value, REPORT)
        assert self.outputs and not self.outputs[0].closed
        assert self.outputs[0].audio is not None and self.outputs[0].video is not None
        self.ready.append(value)
    def close(self):
        self.exchange.close()
        for value in self.media: value.close()
        self.listener.close(); self.phone_control.close(); self.desktop_control.close()
        for output in self.outputs:
            output.close(); output.monitor.join(2)
            assert not output.monitor.is_alive()


@pytest.fixture
def f():
    value = Fixture()
    try: yield value
    finally: value.close()


def test_fresh_original_probe_binds_listener_and_random_key_without_starting_native_outputs(f):
    offer = f.offer()
    assert offer['port'] == f.listener.getsockname()[1]
    assert len(bytes.fromhex(offer['secret'])) == 32 and len(offer['session']) == 32
    assert offer['muted'] is False and offer['front'] is False
    assert not f.outputs and not f.ready and f.exchange.run is None
    assert 24 == offer['version'] and 'url' not in offer


def test_prepared_real_socket_and_actual_output_readiness_precede_send_then_bound_av_and_stop(f):
    offer = f.offer(); phone, accepted = f.connect()
    f.exchange.prepared(f.parent, f.packet('prepared'))
    run = f.exchange.bind_receiver(f.parent, accepted, '/dev/video42', f.send_ready, output_factory=f.native)
    assert len(f.ready) == 1 and f.ready[0] == dict(f.probe, op='send', session=offer['session'])
    sender = WebcamMediaSocket(phone, offer['session'], bytes.fromhex(offer['secret']), f.current, sending=True)
    try:
        sender.send('video', 0, 0, b'v' * VIDEO_BYTES)
        sender.send('audio', 0, 0, b'a' * AUDIO_BYTES)
        assert run.outputs.video.arrived.wait(1) and run.outputs.audio.arrived.wait(1)
        f.exchange.stop(f.parent, f.packet('stop'))
        assert run.state == 'stopped' and run.outputs.video.closed and run.outputs.audio.closed
        assert not run.worker.is_alive() and not run.outputs.monitor.is_alive()
        assert f.exchange.material is None
        # Optional capture stop must not close/reconnect the parent phone session.
        f.phone_control.sendall(b'parent-still-open')
        assert f.desktop_control.recv(64) == b'parent-still-open'
    finally: sender.close()


def test_offer_or_connected_socket_alone_never_opens_native_endpoints_or_announces_send(f):
    f.offer(); _, accepted = f.connect()
    with pytest.raises(PermissionError, match='capture_prepared'):
        f.exchange.bind_receiver(f.parent, accepted, '/dev/video42', f.send_ready, output_factory=f.native)
    assert not f.outputs and not f.ready and accepted.fileno() == -1


def test_receiver_ready_control_failure_closes_outputs_without_data_or_parent_reconnect(f):
    f.offer(); _, accepted = f.connect(); f.exchange.prepared(f.parent, f.packet('prepared'))
    def failed(value):
        f.send_ready(value)
        raise PermissionError('original authenticated ready send failed')
    with pytest.raises(PermissionError, match='ready send failed'):
        f.exchange.bind_receiver(f.parent, accepted, '/dev/video42', failed, output_factory=f.native)
    assert f.outputs[0].closed and not f.outputs[0].video.frames and not f.outputs[0].audio.frames
    assert f.exchange.phase == 'retired' and f.exchange.material is None
    assert f.desktop_control.fileno() >= 0


def test_socket_from_another_listener_cannot_be_substituted_for_the_original_bound_channel(f):
    f.offer(); f.exchange.prepared(f.parent, f.packet('prepared'))
    other = socket.socket()
    try:
        other.bind(('127.0.0.1', 0)); other.listen(1); other.settimeout(2)
        client = socket.create_connection(other.getsockname(), timeout=2)
        try:
            accepted, _ = other.accept()
            with pytest.raises(PermissionError, match='original_media_socket'):
                f.exchange.bind_receiver(f.parent, accepted, '/dev/video42', f.send_ready, output_factory=f.native)
            assert accepted.fileno() == -1 and not f.outputs and not f.ready
        finally: client.close()
    finally: other.close()


@pytest.mark.parametrize('mode', ['original_guard', 'deadline', 'clock_rollback'])
def test_original_context_loss_cannot_be_recovered_by_restoring_matching_flags(f, mode):
    f.offer()
    if mode == 'original_guard': f.live = False
    elif mode == 'deadline': f.now += 60
    else: f.now -= .1
    with pytest.raises(PermissionError): f.exchange.prepared(f.parent, f.packet('prepared'))
    f.live, f.now = True, 1.0
    with pytest.raises(PermissionError): f.exchange.prepared(f.parent, f.packet('prepared'))
    assert f.exchange.material is None and not f.outputs and not f.ready


def test_foreign_parent_and_old_nonce_do_not_retire_a_different_current_exchange(f):
    f.offer()
    with pytest.raises(PermissionError, match='original_parent'):
        f.exchange.prepared(object(), f.packet('prepared'))
    with pytest.raises(PermissionError, match='foreign_exchange'):
        f.exchange.prepared(f.parent, dict(f.packet('prepared'), nonce='0' * 64))
    f.exchange.prepared(f.parent, f.packet('prepared'))
    assert f.exchange.phase == 'prepared'


def test_data_guard_remains_live_after_native_preparation_without_another_packet(f):
    offer = f.offer(); phone, accepted = f.connect(); f.exchange.prepared(f.parent, f.packet('prepared'))
    run = f.exchange.bind_receiver(f.parent, accepted, '/dev/video42', f.send_ready, output_factory=f.native)
    f.live = False
    assert run.ended.wait(2)
    assert run.state == 'failed' and run.outputs.closed and f.exchange.phase == 'retired'
    f.live = True
    with pytest.raises(PermissionError): f.exchange.prepared(f.parent, f.packet('prepared'))
