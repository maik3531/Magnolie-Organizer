"""Private draft attachment on the actual authenticated Linux reader."""

from threading import Event, Thread
from time import time_ns
from uuid import uuid4

import pytest

from test_phone_camera_native_dispatch import connected, native  # shared authenticated fixture
from magnolie_desktop_screen_dispatch import DesktopScreenDraftDispatch


def request():
    return dict(type='desktop_screen_draft', body=dict(draft='desktop-screen-control/1',
        op='request', request=uuid4().hex, mode=2, setup_until_ms=time_ns() // 1_000_000 + 5000))


def ping(client):
    frame = dict(type='ping', ping_id=str(uuid4()), sent_ms=time_ns() // 1_000_000)
    client.send(frame)
    assert client.receive() == dict(frame, type='pong')


def attach(service, peer, client, receive):
    dispatch = service._desktop_screen_draft_dispatch = DesktopScreenDraftDispatch(service)
    original = dispatch.attach(peer['device_id'], client.channel, receive)
    return dispatch, original


def test_dormant_and_bad_draft_frames_never_reach_normal_message_path(connected, monkeypatch):
    service, peer, client = connected
    monkeypatch.setattr(service.store, 'remember_message', lambda *a: pytest.fail('draft persisted'))
    monkeypatch.setattr(service.store, 'dedupe_result', lambda *a: pytest.fail('draft replay lookup'))
    frame = request()
    client.send(frame)
    ping(client)  # No draft ACK, no disconnect, no durable handling.
    seen = []
    dispatch, original = attach(service, peer, client, lambda *args: seen.append(args))
    service._payload(peer, client.channel, frame, scoped_reference=object())
    client.send(dict(frame, kind='device_status.request'))
    client.send(dict(frame, body=dict(frame['body'], mode=True)))
    ping(client)
    assert seen == []
    client.send(frame)
    ping(client)
    assert seen == [(original, frame['body'], frame)]
    with pytest.raises(PermissionError):
        original.release()
    unrelated = type('UnrelatedChannel', (), {})()
    service._signal_native_screen_retire(unrelated)
    original.require_current()
    service._signal_native_screen_retire(client.channel)
    with pytest.raises(PermissionError):
        original.require_current()
    with pytest.raises(PermissionError):
        dispatch.attach(peer['device_id'], client.channel, lambda *_: None)
    client.send(frame)
    ping(client)
    assert len(seen) == 1 and original.release()


def test_auth_snapshot_and_live_wlan_pairing_are_both_required(connected):
    service, peer, client = connected
    seen = []
    dispatch, original = attach(service, peer, client, lambda *args: seen.append(args))
    frame = request()
    frozen_peer = dict(peer)
    assert not dispatch.receive_authenticated(object(), service._generation, frozen_peer, client.channel, frame)
    assert not dispatch.receive_authenticated(service.store, service._generation + 1, frozen_peer, client.channel, frame)
    assert not dispatch.receive_authenticated(service.store, service._generation,
        dict(frozen_peer, static_public='changed'), client.channel, frame)
    assert not dispatch.receive_authenticated(service.store, service._generation, frozen_peer, object(), frame)
    assert seen == []
    service.connection_transports[peer['device_id']] = 'bluetooth'
    with pytest.raises(PermissionError):
        original.require_current()
    service.connection_transports[peer['device_id']] = 'wifi'
    service.store.peer(peer['device_id'])['static_public'] = 'changed'
    try:
        client.send(frame)
        ping(client)
        assert seen == [] and original.retired.is_set()
    finally:
        service.store.peer(peer['device_id'])['static_public'] = frozen_peer['static_public']


def test_retirement_fences_inflight_handoff_and_waits_for_reader(connected):
    service, peer, client = connected
    entered, resume = Event(), Event()
    seen = []

    def receive(original, body, packet):
        entered.set()
        assert resume.wait(2)
        original.require_current()
        seen.append(body)

    dispatch, original = attach(service, peer, client, receive)
    try:
        client.send(request())
        assert entered.wait(2)
        original.retire()
        assert not original.release()
        with pytest.raises(PermissionError):
            dispatch.attach(peer['device_id'], client.channel, receive)
    finally:
        resume.set()
    ping(client)
    assert not seen and original.release()


def test_optional_receiver_error_does_not_close_original_notes_parent(connected):
    service, peer, client = connected

    def broken(*_):
        raise RuntimeError('controlled native receiver failure')

    _, original = attach(service, peer, client, broken)
    client.send(request())
    ping(client)
    assert original.retired.is_set() and original.release()


def test_disconnect_retires_bound_lease(connected):
    service, peer, client = connected
    _, original = attach(service, peer, client, lambda *_: None)
    workers = [worker for worker in service._workers if isinstance(worker, Thread)]
    assert workers
    client.send(dict(type='close', reason='normal'))
    assert original.retired.wait(2)
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    assert original.release()
