"""Actual native sender/outbox ordering; injected metadata owner and channel.

No normal Mixed preparation, GUI save or physical encrypted phone acceptance.
"""
import copy
import sqlite3
import pytest
import magnolie_telefon as phone
from magnolie_personal_actor_store import ActorStore
from test_mcp_phone import owned_service
from test_personal_actor_mixed_report_owner import mixed_report_fixture


@pytest.mark.parametrize('fault', ['none', 'io', 'authority-after-send', 'channel-after-send', 'authority-after-attempt', 'completion-after-send', 'owner-after-send', 'bytes-after-send'])
def test_fixed_frame_actual_send_return_precedes_report_authority(tmp_path, monkeypatch, fault):
    create, state, owner, read, report, controls, target, fixed = mixed_report_fixture()
    waiting = create()
    service, peer, events = owned_service(tmp_path)
    registry = ActorStore(service.store, lambda *_: 'a' * 64)
    handle = registry.create(peer['device_id'], phone.fingerprint(phone.unb64(peer['static_public'], 32)), 'a' * 64, run_id=waiting.run_id)
    registry.begin_decision_review(handle, waiting.validator)
    sent = []
    class Channel:
        def send(self, wire):
            assert not service.lock._is_owned(), 'Native network I/O held the service guard'
            assert waiting.validate('send_report', report) is None
            if fault == 'io': raise OSError('Synthetic channel write failure')
            sent.append(copy.deepcopy(wire))
            if fault == 'authority-after-send': state['authority'] = 'e' * 64
            if fault == 'channel-after-send': service.connections[peer['device_id']] = object()
            if fault == 'completion-after-send': admission['completion'] = object()
            if fault == 'owner-after-send': admission['report_owner'] = object()
            if fault == 'bytes-after-send': wire['body']['body']['decisions'][0]['decision'] = 'restore'
    channel = Channel()
    admission = dict(peer=peer['device_id'], channel=channel, registry=registry, handle=handle,
        outbound={fixed['message_id'], report['message_id']}, report_owner=waiting)
    service.connections[peer['device_id']] = channel
    service.personal_actor_admissions[handle.actor_id] = admission
    # Isolated sealed outbox fixture; no claim that the normal controller has
    # prepared these rows or that a real peer has received this channel data.
    with sqlite3.connect(service.store.database_path) as db:
        for wire in (fixed, report):
            db.execute("INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES(?,?,?,?,?,?,0,?,'','any')",
                (wire['message_id'], peer['device_id'], 'personal_sync.deletion_decision' if wire is fixed else 'personal_sync.report',
                 wire['created_ms'], wire['expires_ms'], service.store._encrypt(phone.canonical(wire), 'outbox', wire['message_id']), wire['created_ms']))
    assert service._send_personal_actor_queued(channel, peer['device_id'], report) is False
    assert not sent and waiting.fixed_sent == set()
    if fault == 'authority-after-attempt':
        attempt = service.store.mark_attempt
        def changed(*args):
            attempt(*args); state['authority'] = 'e' * 64
        monkeypatch.setattr(service.store, 'mark_attempt', changed)
    if fault in ('io', 'authority-after-send', 'channel-after-send', 'completion-after-send', 'owner-after-send', 'bytes-after-send'):
        with pytest.raises((OSError, PermissionError, ValueError)):
            service._send_personal_actor_queued(channel, peer['device_id'], fixed)
    else:
        assert service._send_personal_actor_queued(channel, peer['device_id'], fixed) is (fault == 'none')
    if fault == 'none':
        assert sent == [fixed] and waiting.fixed_sent == {fixed['message_id']}
        # Separate report send uses the exact same guarded native sender.
        def send_report(wire):
            assert waiting.fixed_sent == {fixed['message_id']}
            assert not service.lock._is_owned()
            sent.append(copy.deepcopy(wire))
        channel.send = send_report
        assert service._send_personal_actor_queued(channel, peer['device_id'], report)
        assert sent == [fixed, report]
    else:
        assert not waiting.fixed_sent
    assert read() == waiting.data_saved_book and not events
