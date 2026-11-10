"""Actual signed PhoneService handshake/dispatcher and encrypted parent/media.
Generated AV → controlled output adapters only; no installed or physical capture.
"""
from pathlib import Path
import hashlib
import hmac
import secrets
import socket
import sqlite3
import sys
import threading
import time
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
from magnolie_phone_camera_transport import WebcamMediaSocket
from magnolie_phone_webcam import NativeWebcamSession, VIDEO_BYTES, AUDIO_BYTES
from test_file_authenticated_desktop import native
from test_phone_camera_receiver import Output


class AuthenticatedPhone:
    def __init__(self, service, peer, private, monkeypatch):
        self.service, self.peer = service, peer
        service._native_photo_built = False  # Camera must work without photo handlers/bindings.
        service._native_camera_built = True
        monkeypatch.setattr(service, '_queue_note_settings', lambda *args, **kwargs: None)
        pending = service.store.pending
        monkeypatch.setattr(service.store, 'pending', lambda *args, **kwargs:
            [value for value in pending(*args, **kwargs) if value['kind'] in ('capabilities.update', 'grants.update')])
        self.activated = threading.Event()
        self.activity = threading.Event()
        service.callback = lambda event, value: (self.activated.set() if event == 'status' else
            self.activity.set() if event == 'personal_sync_activity' else None)
        listener = socket.socket()
        try:
            listener.bind(('127.0.0.1', 0)); listener.listen(1)
            self.sock = socket.create_connection(listener.getsockname(), timeout=3)
            accepted, _ = listener.accept()
        finally: listener.close()
        assert service._start_handler(accepted, '127.0.0.1', 'wifi')
        identity = dict(service.store.identity)
        ids = b'\0'.join(sorted([peer['device_id'].encode(), identity['device_id'].encode()]))
        static_root = phone.hkdf(private.exchange(X25519PublicKey.from_public_bytes(phone.unb64(identity['static_public'], 32))),
            hashlib.sha256(b'magnolie-phone-fs1/static-salt\0' + ids).digest(), b'magnolie-phone-fs1/static-root\0' + ids, 32)
        auth = phone.hkdf(static_root, None, b'magnolie-phone-fs1/auth\0', 32)
        ephemeral = X25519PrivateKey.generate()
        self.sid = bytes([5]) * 16
        start = dict(p=phone.PROTOCOL, type='session_start', sid=phone.b64(self.sid),
            **{'from': peer['device_id'], 'to': identity['device_id']}, initiator_role='phone',
            ephemeral_public=phone.b64(ephemeral.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)),
            nonce=phone.b64(bytes([6]) * 32), versions=[1])
        start['mac'] = phone.b64(hmac.new(auth, b'magnolie-phone-fs1/start\0' + phone.canonical(start), hashlib.sha256).digest())
        phone.send_frame(self.sock, start)
        response = phone.receive_frame(self.sock, phone.PAIR_FRAME_MAX)
        unsigned = dict(response); unsigned.pop('mac')
        assert hmac.compare_digest(phone.unb64(response['mac'], 32),
            hmac.new(auth, b'magnolie-phone-fs1/response\0' + phone.canonical(start) + phone.canonical(unsigned), hashlib.sha256).digest())
        transcript = hashlib.sha256(phone.canonical(start) + phone.canonical(response)).digest()
        salt = hmac.new(static_root, b'magnolie-phone-fs1/session-salt\0' + transcript, hashlib.sha256).digest()
        self.material = phone.hkdf(ephemeral.exchange(X25519PublicKey.from_public_bytes(phone.unb64(response['ephemeral_public'], 32))),
            salt, b'magnolie-phone-fs1/session-keys\0' + transcript, 72)
        self.sent = self.received = 0
        self.ids = []
        self.send(dict(type='session_ready', connection_id=str(uuid.uuid4()), capabilities_revision=1, last_received_seq=-1))
        assert self.receive()['type'] == 'session_ready'
        for _ in range(2):
            message = self.receive()
            assert message['kind'] in ('capabilities.update', 'grants.update')
            self.ack(message)
        assert self.activated.wait(3)
        self.channel = service.connections[peer['device_id']]
        assert not service._file_channel_bindings
        assert service._native_webcam_owner is None

    def send(self, payload):
        aad = dict(p=phone.PROTOCOL, sid=phone.b64(self.sid), seq=self.sent, dir='phone_to_desktop')
        encrypted = AESGCM(self.material[:32]).encrypt(self.material[32:36] + self.sent.to_bytes(8, 'big'),
            phone.canonical(payload), phone.canonical(aad))
        phone.send_frame(self.sock, dict(aad, ciphertext=phone.b64(encrypted)))
        self.sent += 1

    def receive(self):
        frame = phone.receive_frame(self.sock, phone.SECURE_FRAME_MAX)
        aad = dict(p=phone.PROTOCOL, sid=phone.b64(self.sid), seq=self.received, dir='desktop_to_phone')
        assert {key: value for key, value in frame.items() if key != 'ciphertext'} == aad
        plain = AESGCM(self.material[36:68]).decrypt(self.material[68:72] + self.received.to_bytes(8, 'big'),
            phone.base64.b64decode(frame['ciphertext'], validate=True), phone.canonical(aad))
        self.received += 1
        return phone.strict_json(plain)

    def ack(self, message):
        self.send(dict(type='ack', message_id=message['message_id'], status='accepted', error='none'))

    def request(self, body):
        message = self.service._webcam_control_message('device_status.request', body)
        self.ids.append(message['message_id']); self.send(message)
        return message

    def report(self, op):
        for _ in range(8):
            message = self.receive()
            if message.get('type') == 'ack':
                continue
            assert message['kind'] == 'device_status.report'
            self.ids.append(message['message_id']); self.ack(message)
            if message['body']['op'] == op:
                return message['body']
        pytest.fail('expected native webcam control report')

    def close(self):
        self.service.stop_event.set()
        self.service._signal_native_webcam_retire()
        try: self.sock.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        self.sock.close()
        deadline = time.monotonic() + 6
        while True:
            workers = list(self.service._workers)
            if not workers: break
            for worker in workers: worker.join(max(0, deadline - time.monotonic()))
            if time.monotonic() >= deadline:
                assert not any(worker.is_alive() for worker in self.service._workers)
                break


@pytest.fixture
def connected(native, monkeypatch):
    service, peer, private = native
    try:
        client = AuthenticatedPhone(service, peer, private, monkeypatch)
    except BaseException:
        service.stop_event.set(); service._signal_native_webcam_retire()
        for value in list(service._sockets):
            try: value.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            value.close()
        for worker in list(service._workers): worker.join(4)
        raise
    try: yield service, peer, client
    finally: client.close()


def probe():
    return dict(version=24, request_id=str(uuid.uuid4()), nonce=secrets.token_hex(32), op='probe')


def test_actual_encrypted_unsolicited_control_is_rejected_without_owner_or_persistence(connected, monkeypatch):
    service, peer, client = connected
    monkeypatch.setattr(service.store, 'remember_message', lambda *args: pytest.fail('webcam persisted'))
    monkeypatch.setattr(service.store, 'dedupe_result', lambda *args: pytest.fail('webcam replay lookup'))
    message = client.request(probe())
    ack = client.receive()
    assert ack == dict(type='ack', message_id=message['message_id'], status='rejected', error='not_granted')
    assert service._native_webcam_owner is None and service._native_media_activity()['camera'] is False
    client.send(dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
    assert client.receive()['type'] == 'pong'


def test_signed_native_dispatch_negotiates_ephemeral_offer_prepared_and_ready_then_real_encrypted_av(connected):
    service, peer, client = connected
    outputs = []
    def native_outputs(device, guard, **settings):
        value = NativeWebcamSession(device, guard, video_factory=Output, audio_factory=Output, **settings)
        outputs.append(value); return value
    owner = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    owner.output_factory = native_outputs  # Internal controlled source test only; production default is native.
    discovery = client.receive()
    client.ids.append(discovery['message_id']); client.ack(discovery)
    assert discovery['kind'] == 'capabilities.update'
    assert 24 in discovery['body']['items']['device_status']['versions']
    assert not outputs and service._native_media_activity()['camera'] is False
    original = probe(); client.request(original)
    offer = client.report('offer')
    assert offer['request_id'] == original['request_id'] and offer['nonce'] == original['nonce']
    assert not outputs and service._native_media_activity()['camera'] is False
    media = socket.create_connection(('127.0.0.1', offer['port']), timeout=2)
    sender = WebcamMediaSocket(media, offer['session'], bytes.fromhex(offer['secret']), owner.current, sending=True)
    try:
        client.request(dict(original, op='prepared', session=offer['session']))
        ready = client.report('send')
        assert ready == dict(original, op='send', session=offer['session'])
        assert len(outputs) == 1 and not outputs[0].closed
        assert service._native_media_activity()['camera'] is False  # READY is not activity.
        sender.send('video', 0, 0, b'v' * VIDEO_BYTES)
        assert outputs[0].video.arrived.wait(2)
        assert service._native_media_activity()['camera'] is False  # Default AV needs actual audio too.
        sender.send('audio', 0, 0, b'a' * AUDIO_BYTES)
        assert outputs[0].audio.arrived.wait(2)
        assert client.activity.wait(2)
        assert service._native_media_activity()['camera'] is True
        assert service.end_native_webcam(owner)
        assert service._native_media_activity()['camera'] is False
        assert client.report('stop') == dict(original, op='stop', session=offer['session'])
        assert owner.done.wait(4); owner.worker.join(1)
        assert owner.is_completely_stopped() and outputs[0].closed
        revoked = client.receive()
        assert revoked['kind'] == 'capabilities.update' and 24 not in revoked['body']['items']['device_status']['versions']
        client.ids.append(revoked['message_id']); client.ack(revoked)
        # No source/grant/shared-policy binding was borrowed from photo sync.
        assert not service._file_channel_bindings and not service._native_file_connections
        with sqlite3.connect(service.store.database_path) as db:
            marks = ','.join('?' for _ in client.ids)
            for table in ('outbox', 'inbox', 'dedupe'):
                assert db.execute('SELECT COUNT(*) FROM ' + table + ' WHERE message_id IN (' + marks + ')', client.ids).fetchone()[0] == 0
        client.send(dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
        assert client.receive()['type'] == 'pong'  # Optional stop preserves encrypted parent.
    finally: sender.close(); service.end_native_webcam(owner)


def test_camera_controls_cannot_be_queued_or_remembered_even_outside_dispatcher(connected):
    service, peer, client = connected
    for version in (24, '24', 24.0):
        body = dict(probe(), version=version)
        with pytest.raises(ValueError, match='persistent queue'):
            service.store.queue(peer['device_id'], 'device_status.request', body, 60_000)
        message = service._webcam_control_message('device_status.report', body)
        with pytest.raises(ValueError, match='replay history'):
            service.store.remember_message(peer['device_id'], message, 'accepted', 'none')
        assert service._send_message(client.channel, peer['device_id'], message) is False


def test_disabled_build_never_creates_owner_or_advertises_v24(connected, monkeypatch):
    service, peer, client = connected
    service._native_camera_built = False
    monkeypatch.setattr(phone.importlib, 'import_module', lambda *args: pytest.fail('disabled camera import'))
    with pytest.raises(ValueError, match='not_in_build'):
        service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    assert service._native_webcam_owner is None
    assert 24 not in client.channel.last_capabilities['items']['device_status']['versions']


def test_old_phone_without_probe_gets_no_capture_and_repeated_enable_cannot_replace_owner(connected):
    service, peer, client = connected
    first = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    message = client.receive(); client.ack(message)
    assert 24 in message['body']['items']['device_status']['versions']
    with pytest.raises(PermissionError, match='owner_busy'):
        service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    assert first.exchange is None and service._native_media_activity()['camera'] is False
    assert service.end_native_webcam(first)
    assert first.done.wait(4); first.worker.join(1)
    revoked = client.receive(); client.ack(revoked)
    assert 24 not in revoked['body']['items']['device_status']['versions']
    assert first.is_completely_stopped()
    client.send(dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
    assert client.receive()['type'] == 'pong'


@pytest.mark.parametrize('change', ['generation', 'peer_key', 'enabled'])
def test_actual_original_owner_retires_on_live_context_loss_and_cannot_revive_after_restore(connected, change):
    service, peer, client = connected
    owner = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    message = client.receive(); client.ack(message)
    old_generation, old_key = service._generation, peer['static_public']
    if change == 'generation': service._generation += 1
    elif change == 'peer_key': peer['static_public'] = phone.b64(bytes([33]) * 32)
    else: service.enabled = False
    assert owner.done.wait(4); owner.worker.join(1)
    service._generation, peer['static_public'], service.enabled = old_generation, old_key, True
    assert owner.is_completely_stopped() and owner.exchange is None
    with pytest.raises(PermissionError, match='owner_retired'):
        owner.submit('device_status.request', probe())


def test_old_owner_stop_and_duplicate_ack_cannot_retire_a_new_native_activation(connected):
    service, peer, client = connected
    first = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    first_discovery = client.receive(); client.ack(first_discovery)
    assert service.end_native_webcam(first)
    assert first.done.wait(4); first.worker.join(1)
    client.ack(client.receive())  # Original v24 withdrawal.
    second = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    client.ack(client.receive())
    assert not service.end_native_webcam(first)
    client.send(dict(type='ack', message_id=first_discovery['message_id'], status='rejected', error='not_granted'))
    client.send(dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
    assert client.receive()['type'] == 'pong'
    assert not second.stopping.is_set() and service._native_webcam_owner is second
    service.end_native_webcam(second)


def test_late_encrypted_stop_for_old_exchange_cannot_stop_another_new_original_owner(connected):
    service, peer, client = connected
    first = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    client.ack(client.receive())
    old_probe = probe(); client.request(old_probe); old_offer = client.report('offer')
    service.end_native_webcam(first)
    client.report('stop')
    assert first.done.wait(4); first.worker.join(1)
    client.ack(client.receive())
    second = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    client.ack(client.receive())
    replayed = client.request(old_probe)
    rejected = client.receive()
    assert rejected == dict(type='ack', message_id=replayed['message_id'], status='rejected', error='not_granted')
    assert second.exchange is None
    new_probe = probe(); client.request(new_probe); client.report('offer')
    late = client.request(dict(old_probe, op='stop', session=old_offer['session']))
    ack = None
    for _ in range(4):
        value = client.receive()
        if value.get('type') == 'ack' and value['message_id'] == late['message_id']:
            ack = value; break
        if value.get('type') == 'message': client.ack(value)
    assert ack is not None and ack['status'] == 'rejected' and ack['error'] == 'not_granted'
    assert service._native_webcam_owner is second and not second.stopping.is_set()
    client.send(dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
    assert client.receive()['type'] == 'pong'


def test_failed_output_constructor_retains_actual_uncertain_native_owner_and_blocks_capture_slot_reuse(connected):
    from test_phone_camera_pulse import NativePulse
    from magnolie_phone_camera_pulse import PulsePipeSource
    from magnolie_phone_webcam import LinuxAudioOutput
    service, peer, client = connected
    native = NativePulse(); native.wrong_format = native.reject_unload = True
    videos = []
    def video(path):
        value = Output(path); videos.append(value); return value
    def audio(identity):
        native.name = ('magnolie_phone_' + identity).encode('ascii')
        return LinuxAudioOutput(identity, owner_factory=lambda name, path:
            PulsePipeSource(name, path, library_factory=lambda: native))
    def controlled_native(device, guard, **settings):
        return NativeWebcamSession(device, guard, video_factory=video, audio_factory=audio, **settings)
    owner = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    owner.output_factory = controlled_native
    client.ack(client.receive())
    original = probe(); client.request(original); offer = client.report('offer')
    media = socket.create_connection(('127.0.0.1', offer['port']), timeout=2)
    try:
        client.request(dict(original, op='prepared', session=offer['session']))
        client.report('stop')  # No SEND/streaming can escape failed output preparation.
        assert owner.done.wait(4); owner.worker.join(1)
        client.ack(client.receive())  # Withdraw v24 on this still-live parent.
        assert owner.exchange.run is None and videos[0].closed
        assert not owner.is_completely_stopped() and not owner.cleanup_confirmed
        pending = owner.pending_cleanup_owner
        assert pending is not None and pending.module == 42
        assert pending.context is None and pending.loop is None and not pending.started
        assert native.calls.count('context-new') == 1 and native.calls.count('unload-original') == 1
        with pytest.raises(PermissionError, match='owner_busy'):
            service.begin_native_webcam(peer['device_id'], device='/dev/video42')
        assert service._native_media_activity()['camera'] is False
        client.send(dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
        assert client.receive()['type'] == 'pong'
    finally: media.close()


def test_original_phone_permission_denial_is_retained_as_failure_without_output_or_parent_loss(connected):
    service, peer, client = connected
    owner = service.begin_native_webcam(peer['device_id'], device='/dev/video42')
    client.ack(client.receive())
    original = probe(); client.request(original); offer = client.report('offer')
    client.request(dict(original, op='error', session=offer['session'], reason='permission_denied'))
    client.report('stop')
    assert owner.done.wait(4); owner.worker.join(1)
    client.ack(client.receive())
    assert str(owner.error) == 'webcam_permission_denied'
    assert owner.exchange.run is None and owner.is_completely_stopped()
    assert service._native_media_activity()['camera'] is False
    client.send(dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
    assert client.receive()['type'] == 'pong'
