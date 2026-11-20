import socket
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_phone_screen_control import PhoneScreenDesktopChannel, PhoneScreenDesktopControl, PhoneScreenDesktopDispatch, REPORT, REQUEST, validate_body
from magnolie_telefon import PhoneService, PhoneStore, SecureChannel, b64, canonical, now_ms, receive_frame, strict_json


PROBE = dict(version=26, request_id='4b6aef60-a7bf-4a17-8a6b-56928034dd5d', nonce='a' * 64, op='probe')
SHAPE = dict(port=55443, width=720, height=1600, density=160)


def begin():
    parent = object()
    now = [100]
    owner = PhoneScreenDesktopControl(parent, PROBE, lambda: None, clock=lambda: now[0])
    offer = owner.offer(**SHAPE)
    prepared = dict(PROBE, op='prepared', session=offer['session'])
    return parent, now, owner, offer, prepared


@pytest.mark.parametrize('edit', [dict(width=True), dict(port=1023), dict(density=1001), dict(width=1920, height=1920),
                                  dict(host='example.invalid'), dict(secret='x' * 64), dict(muted=True), dict(version=26.0)])
def test_shape_and_mixed_control_fields_rejected(edit):
    _, _, _, offer, _ = begin()
    validate_body(offer, REPORT)
    with pytest.raises(ValueError):
        validate_body(dict(offer, **edit), REPORT)


def test_original_probe_prepared_send_and_terminal_stop():
    parent, now, owner, offer, prepared = begin()
    with pytest.raises(PermissionError):
        owner.offer(**SHAPE)
    assert not owner.receive(object(), prepared)
    assert not owner.receive(parent, dict(prepared, session='b' * 32))
    with pytest.raises(PermissionError):
        owner.authorize(lambda: None, lambda *args: pytest.fail('no SEND before PREPARED'))
    assert owner.receive(parent, prepared)
    assert not owner.receive(parent, prepared)
    records = []

    def write(packet, guard):
        with pytest.raises(PermissionError):
            owner.require_send()
        guard()
        records.append(validate_body(packet, REPORT))

    owner.authorize(lambda: None, write)
    assert records == [dict(prepared, op='send')]
    now[0] += 60
    owner.require_send()
    assert owner.receive(parent, dict(prepared, op='stop'))
    with pytest.raises(PermissionError):
        owner.require_send()


def test_expired_or_revoked_control_cannot_publish_send():
    parent, now, owner, _, prepared = begin()
    now[0] += 60
    with pytest.raises(PermissionError):
        owner.receive(parent, prepared)
    parent, _, owner, _, prepared = begin()
    assert owner.receive(parent, prepared)

    def write(packet, guard):
        assert owner.receive(parent, dict(prepared, op='stop'))
        guard()

    with pytest.raises(PermissionError):
        owner.authorize(lambda: None, write)
    with pytest.raises(PermissionError):
        owner.require_send()


def test_native_channel_guard_rejects_before_wire_and_live_write_is_encrypted():
    a, b = socket.socketpair()
    with a, b:
        a.settimeout(.25)
        b.settimeout(.25)
        sid, key, prefix = bytes(16), bytes(range(32)), b'\x04' * 4
        native = SecureChannel(a, sid, key, prefix, key, b'\x05' * 4)
        live = [False]

        def require():
            if not live[0]:
                raise PermissionError('original channel retired')

        binding = PhoneScreenDesktopChannel(native, require)
        _, _, _, offer, _ = begin()
        with pytest.raises(PermissionError):
            binding.write(offer, lambda: None)
        assert native.send_seq == 0
        live[0] = True
        binding.write(offer, lambda: None)
        frame = receive_frame(b, 8192)
        header = {key: value for key, value in frame.items() if key != 'ciphertext'}
        assert header['sid'] == b64(sid) and header['seq'] == 0
        import base64
        value = AESGCM(key).decrypt(prefix + bytes(8), base64.b64decode(frame['ciphertext']), canonical(header))
        assert strict_json(value)['body'] == offer
        with pytest.raises(PermissionError):
            binding.body_from(object(), strict_json(value))


def test_original_phone_dispatch_uses_only_current_advertised_probe_and_ephemeral_ack(tmp_path):
    a, b = socket.socketpair()
    with a, b:
        a.settimeout(.25)
        b.settimeout(.25)
        sid, key, prefix = bytes(16), bytes(range(32)), b'\x04' * 4
        channel = SecureChannel(a, sid, key, prefix, key, b'\x05' * 4)
        service = PhoneService.__new__(PhoneService)
        peer = {'device_id': 'phone', 'state': 'paired', 'static_public': 'fixture-key'}
        service.store = SimpleNamespace(peers=[peer])
        service.enabled, service._generation, service.stop_event = True, 1, threading.Event()
        service.connections, service.connection_transports = {'phone': channel}, {'phone': 'wifi'}
        service._screen_dispatch = PhoneScreenDesktopDispatch(service)
        now = now_ms()
        msg = dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=REQUEST, created_ms=now,
                   expires_ms=now + 60_000, body=PROBE)

        def ack(sequence):
            frame = receive_frame(b, 8192)
            assert frame['seq'] == sequence
            header = {key: value for key, value in frame.items() if key != 'ciphertext'}
            import base64
            return strict_json(AESGCM(key).decrypt(prefix + sequence.to_bytes(8, 'big'),
                               base64.b64decode(frame['ciphertext']), canonical(header)))

        service._payload(peer, channel, msg)
        assert ack(0)['status'] == 'rejected'
        assert not service.native_screen_available('phone')
        channel.last_capabilities = {'items': {'device_status': {'available': True, 'versions': [1, 26]}}}
        service._payload(peer, channel, msg)
        assert ack(1)['status'] == 'accepted'
        assert service.native_screen_available('phone')
        service._payload(peer, channel, msg)
        assert ack(2)['status'] == 'rejected'

        called, stopped = [], []
        owner = SimpleNamespace(stop=lambda: stopped.append(True), is_drained=lambda: bool(stopped))
        outgoing = str(uuid.uuid4())

        def native_start(original, probe, *shape, require_original, track):
            assert original is channel and probe == PROBE and shape == (720, 1600, 160)
            require_original()
            track(outgoing)
            called.append(True)
            return owner

        assert service.begin_native_screen('phone', 720, 1600, 160, native_start) is owner
        assert called == [True] and not service.native_screen_available('phone')
        service._payload(peer, channel, dict(type='ack', message_id=outgoing, status='rejected', error='not_granted'))
        assert stopped == [True]
        assert not service.native_screen_available('phone')
        store = PhoneStore(str(tmp_path / 'phone'), 'fixture')
        with pytest.raises(ValueError, match='persistent replay'):
            store.remember_message('phone', msg, 'accepted', 'none')
