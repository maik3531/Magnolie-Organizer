"""Opt-in #330 discovery design only. No product caller or capability change."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import socket
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
from magnolie_file_native_authority import capture_authenticated_binding
from test_media_transport import PeerWire
from test_telefon import FakeBluetooth, _complete_peer


KIND = 'media_support.hello'
TTL = 10_000
FULL = [1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 17, 18, 19, 20, 21, 22]
FIELDS = {'type', 'v', 'message_id', 'kind', 'created_ms', 'expires_ms', 'body'}


def offer(at):
    return dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=KIND,
                created_ms=at, expires_ms=at + TTL,
                body=dict(format=1, feature='shared_settings'))


def ack(message):
    return dict(type='ack', message_id=message['message_id'], status='accepted', error='none')


def valid(message, at):
    if type(message) is not dict or set(message) != FIELDS:
        return False
    body = message['body']
    return (message['type'] == 'message' and type(message['v']) is int and message['v'] == 1
            and message['kind'] == KIND and phone.valid_uuid(message['message_id'], 4)
            and type(message['created_ms']) is int and type(message['expires_ms']) is int
            and 0 <= message['created_ms'] <= at < message['expires_ms'] <= 253402300799999
            and message['expires_ms'] - message['created_ms'] <= TTL
            and type(body) is dict and set(body) == {'format', 'feature'}
            and type(body['format']) is int and body['format'] == 1 and body['feature'] == 'shared_settings')


class ReferenceAttempt:
    """Single-reader/writer model, intentionally only in this test module."""

    def __init__(self, channel, current, wall, monotonic_ms):
        self._channel, self._current, self._wall, self._clock = channel, current, wall, monotonic_ms
        self._deadline = monotonic_ms() + TTL
        self._sent = self._written = self._local_ack = self._remote_ack = self._established = self._closed = False
        self._offer = offer(wall())

    def _fresh(self, channel):
        if channel is not self._channel:
            return False
        if not self._current() or (not self._established and self._clock() >= self._deadline):
            self._closed = True
        return not self._closed

    def _require_write(self):
        if not self._fresh(self._channel):
            raise PermissionError('original media discovery attempt retired')

    def send(self):
        if self._sent or not self._fresh(self._channel):
            return False
        self._sent = True
        try:
            self._channel.send_ephemeral(self._offer, self._require_write)
        except (PermissionError, OSError, ValueError):
            self._closed = True
            return False
        self._written = self._fresh(self._channel)
        return self._written

    def receive(self, channel, message):
        if type(message) is not dict or not self._fresh(channel) or self._established:
            return False
        if message.get('type') == 'ack':
            if not self._written or self._local_ack or message.get('message_id') != self._offer['message_id']:
                return False
            if message != ack(self._offer):
                self._closed = True
                return False
            self._local_ack = True
        elif not self._remote_ack and valid(message, self._wall()) and message['message_id'] != self._offer['message_id']:
            try:
                channel.send_ephemeral(ack(message), self._require_write)
            except (PermissionError, OSError, ValueError):
                self._closed = True
                return False
            self._remote_ack = self._fresh(channel)
        else:
            return False
        self._established = self._written and self._local_ack and self._remote_ack
        return True

    @property
    def shared_settings_supported(self):
        return self._fresh(self._channel) and self._established


@contextmanager
def wire_pair():
    left, right = socket.socketpair()
    with left, right:
        left.settimeout(.25)
        right.settimeout(1)
        yield phone.SecureChannel(left, bytes([3])*16, bytes([1])*32, bytes([1])*4,
                                  bytes([2])*32, bytes([2])*4), PeerWire(right)


def legacy_state():
    capabilities = phone.desktop_capabilities()
    capabilities['items']['device_status']['versions'] = list(FULL)
    return phone.validate_capabilities(capabilities)


def test_encrypted_support_requires_both_completions_and_retains_every_legacy_version():
    live, tick = [True], [100]
    at = phone.now_ms()
    legacy = legacy_state()
    with wire_pair() as (channel, wire):
        attempt = ReferenceAttempt(channel, lambda: live[0], lambda: at, lambda: tick[0])
        assert not attempt.shared_settings_supported and attempt.send() and not attempt.send()
        own = wire.receive()
        assert valid(own, at)
        wire.send(ack(own))
        assert attempt.receive(channel, channel.receive()) and not attempt.shared_settings_supported
        remote = offer(at)
        assert not attempt.receive(object(), remote)
        wire.send(remote)
        assert attempt.receive(channel, channel.receive()) and wire.receive() == ack(remote)
        assert attempt.shared_settings_supported
        assert legacy == legacy_state() and len(legacy['items']['device_status']['versions']) == 16
        live[0] = False
        assert not attempt.shared_settings_supported
        live[0] = True
        assert not attempt.shared_settings_supported and not attempt.send()


@pytest.mark.parametrize('field,value', [('format', True), ('feature', 'pc_image_batch'), ('grant', True)])
def test_draft_offers_neither_batching_nor_permissions(field, value):
    message = offer(1)
    message['body'][field] = value
    assert not valid(message, 1)


def test_stale_receipt_cannot_extend_the_local_deadline():
    tick = [100]
    with wire_pair() as (channel, wire):
        attempt = ReferenceAttempt(channel, lambda: True, lambda: 100_000, lambda: tick[0])
        assert attempt.send()
        own = wire.receive()
        tick[0] += TTL
        assert not attempt.receive(channel, ack(own))
        assert not attempt.receive(channel, offer(100_000))
        assert not attempt.shared_settings_supported


@pytest.mark.parametrize('error', ['unsupported', 'invalid_schema'])
def test_matching_legacy_rejection_ends_only_that_attempt(error):
    at = phone.now_ms()
    with wire_pair() as (channel, wire):
        attempt = ReferenceAttempt(channel, lambda: True, lambda: at, lambda: 100)
        assert attempt.send()
        own = wire.receive()
        unrelated = dict(ack(offer(at)), status='rejected', error=error)
        wire.send(unrelated)
        assert not attempt.receive(channel, channel.receive())
        remote = offer(at)
        wire.send(remote)
        assert attempt.receive(channel, channel.receive()) and wire.receive() == ack(remote)
        wire.send(dict(ack(own), status='rejected', error=error))
        assert not attempt.receive(channel, channel.receive())
        wire.send(ack(own))
        assert not attempt.receive(channel, channel.receive())
        assert not attempt.shared_settings_supported and not attempt.send()


def test_legacy_rejection_does_not_stop_the_authenticated_parent(tmp_path, monkeypatch):
    service = phone.PhoneService(str(tmp_path/'synthetic'), 'Fixture', bluetooth_backend=FakeBluetooth())
    # Source-only tests do not contain the installed package composition.
    monkeypatch.setattr(service, '_native_photo_built', True)
    peer = _complete_peer()
    peer['capabilities'] = legacy_state()
    peer['personal_sync'].update(own_device=True, remote_own_device=True)
    service.store.peers = [peer]
    service.store.save_peers()
    service.enabled = True
    before = deepcopy(service.store.peers)
    with wire_pair() as (channel, wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, 'wifi', file_binding=binding)
        message = offer(phone.now_ms())
        wire.send(message)
        service._payload(peer, channel, channel.receive())
        assert wire.receive() == dict(ack(message), status='rejected', error='unsupported')
        reserved = dict(offer(phone.now_ms()), kind='file_transfer.shared_support')
        with pytest.raises(ValueError, match='file_desktop_native_route_unavailable'):
            service._payload(peer, channel, reserved)
        heartbeat = dict(type='ping', ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms())
        wire.send(heartbeat)
        service._payload(peer, channel, channel.receive())
        assert wire.receive() == dict(heartbeat, type='pong')
        assert service.store.peers == before
        assert not service._native_file_connections
