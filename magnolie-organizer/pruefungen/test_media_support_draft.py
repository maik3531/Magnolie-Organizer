"""#330 discovery component over a private wire; no production dispatcher."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import socket
import sys
from threading import Event
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
import magnolie_media_sync as media
from magnolie_media_transport import NativeMediaSettingsTransport
from magnolie_media_support import NativeMediaSupportAttempt, TTL, ack, offer, valid
from magnolie_file_native_authority import capture_authenticated_binding
from magnolie_file_desktop_connection import NativeDesktopFileConnection
from magnolie_photo_preferences import ProtectedPhotoPreferences
from test_media_transport import AT, PeerWire, incoming
from test_file_authenticated_desktop import native
from test_telefon import FakeBluetooth, _complete_peer
from test_file_video_authority import ack_all


FULL = [1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 17, 18, 19, 20, 21, 22]


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
        attempt = NativeMediaSupportAttempt(channel, lambda: live[0], lambda: at, lambda: tick[0])
        assert not attempt.supports(channel) and attempt.send() and not attempt.send()
        own = wire.receive()
        assert valid(own, at)
        wire.send(ack(own))
        assert attempt.receive(channel, channel.receive()) and not attempt.supports(channel)
        remote = offer(at)
        assert not attempt.receive(object(), remote)
        wire.send(remote)
        assert attempt.receive(channel, channel.receive()) and wire.receive() == ack(remote)
        assert attempt.supports(channel)
        assert legacy == legacy_state() and len(legacy['items']['device_status']['versions']) == 16
        live[0] = False
        assert not attempt.supports(channel)
        live[0] = True
        assert not attempt.supports(channel) and not attempt.send()


def test_full_legacy_schema_reaches_actual_settings_store_and_requires_separate_agreement(native):
    service, peer, _ = native
    peer['capabilities'] = legacy_state()
    service.store.save_peers()
    with wire_pair() as (channel, wire), wire_pair() as (foreign, foreign_wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, 'wifi', file_binding=binding)
        authority = service.open_native_file_authority(peer['device_id'], peer['static_public'], channel, binding.generation)
        preferences = ProtectedPhotoPreferences(authority)
        live = [True]
        attempt = NativeMediaSupportAttempt(channel, lambda: live[0], lambda: AT)
        other = NativeMediaSupportAttempt(foreign, lambda: True, lambda: AT)
        transport = None

        def deliver(target, wire, message, receiver):
            wire.send(message)
            return receiver(target, target.receive())

        def exchange(target, wire, owner):
            assert owner.send()
            sent = wire.receive()
            assert deliver(target, wire, ack(sent), owner.receive)
            remote = offer(AT)
            assert deliver(target, wire, remote, owner.receive) and wire.receive() == ack(remote)
            assert owner.supports(target)

        try:
            with pytest.raises(PermissionError, match='peer_unsupported'):
                NativeMediaSettingsTransport(authority, lambda: True, support=attempt)
            exchange(foreign, foreign_wire, other)
            with pytest.raises(PermissionError, match='peer_unsupported'):
                NativeMediaSettingsTransport(authority, lambda: True, support=other)
            exchange(channel, wire, attempt)
            transport = NativeMediaSettingsTransport(authority, lambda: True, clock=lambda: AT, support=attempt)
            assert transport.display_snapshot()['configured'] is False
            assert transport.intent_for('images') is None and preferences.read().policy is None
            transport.change('enabled', True)
            transport.change('direction', 'two_way')
            transport.change('auto_mode', 'wifi')
            transport.change('videos_enabled', True)
            transport.change('skip_deletions', True)
            sent = transport.send_settings()
            assert sent == wire.receive()
            assert deliver(channel, wire, ack(sent), transport.observe)
            assert transport.intent_for('images') is None
            echoed = incoming(sent['body'])
            assert deliver(channel, wire, echoed, transport.observe) and wire.receive() == ack(echoed)
            assert transport.intent_for('images', to_phone=True) is not None
            assert transport.intent_for('video', to_phone=False) is not None  # settings only, not video-batch support
            projection = transport.display_snapshot()
            assert projection['agreed'] and {key:projection['values'][key] for key in
                ('collection_mode','direction','auto_mode','skip_deletions')} == dict(
                collection_mode='phone_inventory',direction='two_way',auto_mode='wifi',skip_deletions=True)
            assert not preferences.local_grant(True).grants.send_files
            assert not preferences.local_grant(True).grants.receive_files and preferences.read().policy is None
            assert peer['capabilities']['items']['device_status']['versions'] == FULL

            live[0] = False
            assert transport.intent_for('images') is None and transport.display_snapshot() is None
            with pytest.raises(PermissionError):transport.change('direction', 'phone_to_pc')
            live[0] = True
            assert transport.intent_for('images') is None
            assert media.NativeMediaSettingsStore.has_stored_settings(authority)
            assert preferences.read().policy is None
        finally:
            if transport is not None:transport.close()
            attempt.close();other.close();preferences.close();authority.close()


@pytest.mark.parametrize('field,value', [('format', True), ('feature', 'pc_image_batch'), ('grant', True)])
def test_draft_offers_neither_batching_nor_permissions(field, value):
    message = offer(1)
    message['body'][field] = value
    assert not valid(message, 1)


def test_stale_receipt_cannot_extend_the_local_deadline():
    tick = [100]
    with wire_pair() as (channel, wire):
        attempt = NativeMediaSupportAttempt(channel, lambda: True, lambda: 100_000, lambda: tick[0])
        assert attempt.send()
        own = wire.receive()
        tick[0] += TTL
        assert not attempt.receive(channel, ack(own))
        assert not attempt.receive(channel, offer(100_000))
        assert not attempt.supports(channel)


@pytest.mark.parametrize('completion', ['written', 'failed', 'withdrawn', 'expired'])
def test_early_encrypted_receipt_waits_for_the_original_writer(monkeypatch, completion):
    at, tick, live = phone.now_ms(), [100], [True]
    with wire_pair() as (channel, wire), ThreadPoolExecutor(max_workers=1) as worker:
        original_write = channel.send_ephemeral
        finish = Event()

        def held_result(payload, current):
            original_write(payload, current)
            if payload['type'] == 'message':
                assert finish.wait(2)
                if completion == 'failed':
                    raise OSError('synthetic incomplete write result')

        monkeypatch.setattr(channel, 'send_ephemeral', held_result)
        attempt = NativeMediaSupportAttempt(channel, lambda: live[0], lambda: at, lambda: tick[0])
        remote = offer(at)
        wire.send(remote)
        assert attempt.receive(channel, channel.receive()) and wire.receive() == ack(remote)
        result = worker.submit(attempt.send)
        try:
            own = wire.receive()
            wire.send(ack(own))
            assert attempt.receive(channel, channel.receive())
            assert not attempt.supports(channel)
            if completion == 'withdrawn':
                live[0] = False
            elif completion == 'expired':
                tick[0] += TTL
        finally:
            finish.set()
        assert result.result(timeout=2) == (completion == 'written')
        live[0] = True
        assert attempt.supports(channel) == (completion == 'written') and not attempt.send()


def test_failed_opposite_receipt_write_does_not_establish_support(monkeypatch):
    at = phone.now_ms()
    with wire_pair() as (channel, wire):
        attempt = NativeMediaSupportAttempt(channel, lambda: True, lambda: at, lambda: 100)
        assert attempt.send()
        own = wire.receive()
        wire.send(ack(own))
        assert attempt.receive(channel, channel.receive())

        def failed_write(payload, current):
            assert payload['type'] == 'ack'
            current()
            raise OSError('synthetic failed opposite receipt write')

        monkeypatch.setattr(channel, 'send_ephemeral', failed_write)
        remote = offer(at)
        wire.send(remote)
        assert not attempt.receive(channel, channel.receive())
        assert not attempt.supports(channel)
        assert not attempt.receive(channel, remote) and not attempt.send()


@pytest.mark.parametrize('error', ['unsupported', 'invalid_schema'])
def test_matching_legacy_rejection_ends_only_that_attempt(error):
    at = phone.now_ms()
    with wire_pair() as (channel, wire):
        attempt = NativeMediaSupportAttempt(channel, lambda: True, lambda: at, lambda: 100)
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
        assert not attempt.supports(channel) and not attempt.send()


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


@pytest.mark.parametrize('transport', ['wifi', 'bluetooth'])
def test_actual_reader_joins_only_original_wlan_after_acks_and_never_uses_outbox(native, monkeypatch, transport):
    service, peer, _ = native
    peer['capabilities'] = legacy_state()
    service.store.save_peers()
    monkeypatch.setattr(service, '_native_media_support_checked', True)
    monkeypatch.setattr(service, '_resume_automatic_photos', lambda *args: None)
    monkeypatch.setattr(NativeDesktopFileConnection, '_data_handlers_ready', True)
    with wire_pair() as (channel, wire):
        binding = capture_authenticated_binding(dict(service.store.identity), dict(peer), service._generation, service.store)
        service._activate_connection(peer['device_id'], channel, transport, file_binding=binding)
        def deliver(frame):
            wire.send(frame)
            service._payload(peer, channel, channel.receive())
        try:
            deliver(offer(phone.now_ms()))
            assert not service._native_media_support and channel.send_seq==0  # Already authenticated, but no fresh controls.
            ack_all(service, peer, channel)
            remote_probe = offer(phone.now_ms())
            deliver(remote_probe)
            assert not service._native_file_connections
            if transport=='bluetooth':
                assert not service._native_media_support and channel.send_seq==0
                return
            owner=service._native_media_support[channel]
            local=wire.receive();assert valid(local,phone.now_ms())
            assert wire.receive()==ack(remote_probe) and not owner.supports(channel)
            with monkeypatch.context() as patch:
                patch.setattr(service.store,'outbox_policy',lambda *args,**kwargs:pytest.fail('Discovery ACK used the personal outbox'))
                deliver(ack(local))
                assert owner.supports(channel)
                assert not service._native_file_connections  # Support does not create a file owner.
                connection=service.open_native_file_connection(peer['device_id'],peer['static_public'],channel,binding.generation)
                assert connection._media_source is None and not connection.desktop_snapshot()['shared_media']['configured']
                selected=media.change(media.create(peer['device_id']),peer['device_id'],service.store.identity['device_id'],'enabled',True)
                selected=media.change(selected,peer['device_id'],service.store.identity['device_id'],'direction','two_way')
                def settings(body):
                    message=incoming(body)
                    at=phone.now_ms()
                    return dict(message,created_ms=at,expires_ms=at+60_000)
                proposal=settings(selected);deliver(proposal)
                assert wire.receive()==ack(proposal)
                reply=wire.receive();assert reply['kind']==media.KIND
                deliver(ack(reply))
                assert not connection.desktop_snapshot()['shared_media']['agreed']
                echo=settings(reply['body']);deliver(echo)
                assert wire.receive()==ack(echo)
                assert connection.desktop_snapshot()['shared_media']['agreed']
                assert connection._desktop_session is None and connection._preferences.read().policy is None
                assert not connection._local().grants.receive_files and not connection._local().grants.send_files
                send_seq=channel.send_seq
                withdrawn=dict(offer(phone.now_ms()),kind='personal_sync.settings',body=dict(format=1,own_device=False))
                service._observe_native_file_control(peer,channel,withdrawn['kind'],withdrawn,acknowledged=False)
                assert not owner.supports(channel)
                ack_all(service,peer,channel)
                deliver(ack(local)) # Even after withdrawal this is not a personal ACK or a fresh attempt.
                deliver(offer(phone.now_ms()))
                assert not owner.supports(channel) and channel.send_seq==send_seq
                assert 'shared_media' not in connection.desktop_snapshot()
            assert peer['capabilities']['items']['device_status']['versions']==FULL
            assert service._native_file_connections[channel] is connection
            heartbeat=dict(type='ping',ping_id=str(uuid.uuid4()),sent_ms=phone.now_ms())
            deliver(heartbeat)
            assert wire.receive()==dict(heartbeat,type='pong')
        finally:service._end_native_file_connection(channel)
        assert not service._native_media_support
