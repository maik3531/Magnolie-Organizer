"""Bounded developer reads use synthetic own-phone sessions and private IPC only."""
import copy
import sqlite3
import threading
import uuid
from types import SimpleNamespace

import pytest
from test_background_reliability import phone, private


class Channel:
    def __init__(self):
        self.sent = []
        self.respond = lambda message: None

    def send(self, message):
        self.sent.append(copy.deepcopy(message))
        if message.get('kind') == 'device_status.request':
            self.respond(message)


@pytest.fixture
def setup(private):
    service = phone.PhoneService(str(private / 'phone'), 'Fixture')
    service.enabled = True
    peer = {'device_id': str(uuid.uuid4()), 'display_name': 'Fixture',
        'static_public': phone.b64(b'p' * 32), 'state': 'paired',
        'capabilities': phone.desktop_capabilities(), 'grants': phone.desktop_grants(),
        'local_grants': phone.desktop_grants(), 'last_contact_ms': 0,
        'personal_sync': {'own_device': True, 'remote_own_device': True, 'auto_wifi': False, 'last_report': {}}}
    peer['capabilities']['items']['device_status']['versions'].append(11)
    service.store.peers.append(peer)
    service.store.save_peers()
    channel = Channel()
    service.connections[peer['device_id']] = channel
    service.connection_transports[peer['device_id']] = 'wifi'
    service.note_controls[channel] = copy.deepcopy({'capabilities.update': peer['capabilities'],
        'grants.update': peer['grants'], 'personal_sync.settings': {'format': 1, 'own_device': True}})
    return service, peer, channel


def response(request):
    now = phone.now_ms()
    return {'type': 'message', 'v': 1, 'message_id': str(uuid.uuid4()),
        'kind': 'device_status.report', 'created_ms': now, 'expires_ms': now + 60000,
        'body': {'version': 11, 'request_id': request['body']['request_id'], 'format': 1,
            'app_version': 'fixture', 'events': [{'time_ms': now, 'stage': 'online',
                'transport': 'wifi', 'failure': False}]}}


@pytest.mark.parametrize('proxy', [False, True])
def test_read_uses_actual_payload_dispatch_and_private_ipc_without_persistence(setup, private, proxy):
    service, peer, channel = setup
    def respond(request):
        assert request['body']['version'] == 11
        service._payload(peer, channel, response(request))
    channel.respond = respond
    server = None
    try:
        transport = service
        if proxy:
            import magnolie_hintergrund as background
            path = str(private / 'background.sock')
            server = background.IPCServer(SimpleNamespace(), path, phone_backend=service).start()
            transport = background.PhoneServiceProxy(path=path)
        result = transport.read_developer_diagnostics(peer['device_id'])
        assert result['app_version'] == 'fixture' and result['events'][0]['stage'] == 'online'
        assert channel.sent[-1]['status'] == 'accepted'
        assert not service.developer_requests and not service.store.status(peer['device_id'])
        with sqlite3.connect(service.store.database_path) as db:
            assert db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
    finally:
        if server:
            server.close()


@pytest.mark.parametrize('change', ['own', 'remote_own', 'remote_grant', 'local_grant', 'bluetooth',
    'disconnected', 'fresh_controls', 'unsupported', 'disabled', 'stopping'])
def test_unavailable_source_never_sends(setup, change):
    service, peer, channel = setup
    if change == 'own': peer['personal_sync']['own_device'] = False
    if change == 'remote_own': peer['personal_sync']['remote_own_device'] = False
    if change == 'remote_grant': peer['grants']['grants']['device_status'] = False
    if change == 'local_grant': peer['local_grants']['grants']['device_status'] = False
    if change == 'bluetooth': service.connection_transports[peer['device_id']] = 'bluetooth'
    if change == 'disconnected': service.connections.clear()
    if change == 'fresh_controls': service.note_controls.clear()
    if change == 'unsupported': peer['capabilities']['items']['device_status']['versions'].remove(11)
    if change == 'disabled': service.enabled = False
    if change == 'stopping': service.stop_event.set()
    with pytest.raises(PermissionError): service.read_developer_diagnostics(peer['device_id'])
    assert not channel.sent and not service.developer_requests


@pytest.mark.parametrize('change', ['unsolicited', 'key', 'channel', 'grant', 'late', 'expired',
    'payload', 'too_many', 'stage', 'duplicate'])
def test_bad_or_late_reports_receive_negative_ack_without_data_release(setup, change):
    service, peer, channel = setup
    request = {'body': {'request_id': str(uuid.uuid4())}}
    ticket = {'peer': peer['device_id'], 'key': peer['static_public'], 'channel': channel,
        'event': threading.Event(), 'result': None, 'error': None, 'deadline': phone.time.monotonic() + 10}
    if change != 'unsolicited': service.developer_requests[request['body']['request_id']] = ticket
    report = response(request)
    source = peer
    if change == 'key': source = dict(peer, static_public=phone.b64(b'x' * 32))
    if change == 'channel': service.connections[peer['device_id']] = Channel()
    if change == 'grant': peer['local_grants']['grants']['device_status'] = False
    if change == 'late': ticket['deadline'] = phone.time.monotonic() - 1
    if change == 'expired': report['created_ms'] -= 120000; report['expires_ms'] -= 120000
    if change == 'payload': report['body']['contacts'] = ['private']
    if change == 'too_many': report['body']['events'] *= 129
    if change == 'stage': report['body']['events'][0]['stage'] = ['invalid']
    if change == 'duplicate': service._payload(source, channel, report); ticket['event'].clear()
    service._payload(source, channel, report)
    assert channel.sent[-1]['status'] == 'rejected'
    assert not ticket['event'].is_set()
    if change != 'duplicate': assert ticket['result'] is None


def test_remote_disabled_ack_finishes_read_immediately(setup):
    service, peer, channel = setup
    channel.respond = lambda request: service._payload(peer, channel, {'type': 'ack',
        'message_id': request['message_id'], 'status': 'rejected', 'error': 'not_granted'})
    with pytest.raises(PermissionError, match='not_granted'):
        service.read_developer_diagnostics(peer['device_id'])
    assert not service.developer_requests


def test_revocation_after_report_before_return_is_rechecked(setup):
    service, peer, channel = setup
    def respond(request):
        service._payload(peer, channel, response(request))
        peer['personal_sync']['own_device'] = False
    channel.respond = respond
    with pytest.raises(PermissionError, match='source_changed'):
        service.read_developer_diagnostics(peer['device_id'])
    assert not service.developer_requests


@pytest.mark.parametrize('change', ['none', 'oversize', 'wrong_version', 'revoked'])
def test_saved_crash_report_negotiates_new_version_without_weakening_legacy_reads(setup, change):
    service, peer, channel = setup
    peer['capabilities']['items']['device_status']['versions'].append(13)
    service.note_controls[channel]['capabilities.update'] = copy.deepcopy(peer['capabilities'])
    text = 'Magnolie Notes crash report\nSynthetic first-focus crash\nfixture.stack.Frame\npassword=fixture-password; mail=person@example.test; phone=+49 351 1234567'
    def respond(request):
        assert request['body']['version'] == 13
        report = response(request)
        if change != 'wrong_version':
            report['body']['version'] = 13
            report['body']['crash_report'] = {'available': True, 'text': text if change != 'oversize' else 'x' * 16388, 'truncated': False}
        service._payload(peer, channel, report)
        if change == 'revoked':
            peer['capabilities']['items']['device_status']['versions'].remove(13)
            service.note_controls[channel]['capabilities.update'] = copy.deepcopy(peer['capabilities'])
        if change in ('oversize', 'wrong_version'):
            assert channel.sent[-1]['status'] == 'rejected'
            service._payload(peer, channel, {'type': 'ack', 'message_id': request['message_id'], 'status': 'rejected', 'error': 'invalid_schema'})
    channel.respond = respond
    if change == 'none':
        result = service.read_developer_diagnostics(peer['device_id'])
        assert result['version'] == 13 and 'Synthetic first-focus crash' in result['crash_report']['text']
        assert 'password=***' in result['crash_report']['text']
        assert not any(value in result['crash_report']['text'] for value in ('fixture-password', 'person@example.test', '1234567'))
    else:
        with pytest.raises(PermissionError): service.read_developer_diagnostics(peer['device_id'])
    assert not service.developer_requests and not service.store.status(peer['device_id'])
