"""Issue #171: current paired LAN source, bounded SFTP replies and native dispatch."""
import copy
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_kdeconnect as kde
import magnolie_kde_filesystem as fs
import magnolie_hintergrund as background
from test_kde_native import Bus, Variant, native


def body():
    return {'ip': '203.0.113.99', 'port': 1739, 'user': 'kdeconnect', 'path': '/', 'password': 'synthetic-only'}


@pytest.mark.parametrize('field,value', [('port', True), ('port', 0), ('port', 65536), ('user', '-option'),
    ('user', 'user@host'), ('path', '/a/../b'), ('path', 'relative'), ('password', 'bad\nsecret'),
    ('multiPaths', ['/good', '../bad']), ('pathNames', ['without paths'])])
def test_bad_descriptions_cannot_create_mount_arguments(field, value):
    invalid = body(); invalid[field] = value
    with pytest.raises(fs.FilesystemError): fs.description(invalid)


def test_address_is_pinned_to_tls_source_and_password_never_enters_uri_or_repr():
    report = fs.description(body())
    assert fs.uri('192.0.2.10', report) == 'sftp://kdeconnect@192.0.2.10:1739/'
    assert fs.uri('2001:db8::10', report) == 'sftp://kdeconnect@[2001:db8::10]:1739/'
    assert 'synthetic-only' not in repr(report) and 'synthetic-only' not in fs.uri('192.0.2.10', report)
    for address in ['AA:BB:CC:DD:EE:FF', 'example.invalid', '0.0.0.0']:
        with pytest.raises(fs.FilesystemError): fs.uri(address, report)


class SftpBus(Bus):
    def __init__(self):
        super().__init__()
        self.sms = False
        self.sftp = True
        self.props['a' * 32].update(reachableAddresses=['192.0.2.10'], verificationKey='fixture-key')
    def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
        args = parameters.unpack() if parameters else ()
        if method == 'hasPlugin' and args == ('kdeconnect_sftp',):
            assert owner == self.owner and flags == 4
            self.calls.append((owner, path, interface, method, args))
            return Variant('(b)', (self.sftp,))
        if method == 'startBrowsing':
            assert owner == self.owner and path == '/modules/kdeconnect/devices/' + 'a' * 32 + '/sftp'
            assert interface == 'org.kde.kdeconnect.device.sftp' and flags == 4 and 0 < timeout <= 12000
            self.calls.append((owner, path, interface, method, args))
            return Variant('(b)', (True,))
        return super().call_sync(owner, path, interface, method, parameters, reply, flags, timeout, cancellable)


@pytest.mark.parametrize('change', ['none', 'offline', 'bluetooth', 'unpaired', 'disabled', 'rekey', 'owner'])
def test_native_browser_requires_current_network_peer_and_module(change):
    bus = SftpBus(); backend, _ = native(bus)
    device = backend.filesystem_status()['devices'][0]
    assert device['device_name'] == 'Phone' and device['transport'] == 'wifi'
    props = bus.props['a' * 32]
    if change == 'offline': props['isReachable'] = False
    if change == 'bluetooth': props['reachableAddresses'] = ['AA:BB:CC:DD:EE:FF']
    if change == 'unpaired': props['isPaired'] = False
    if change == 'disabled': bus.sftp = False
    if change == 'rekey': props['verificationKey'] = 'different-key'
    if change == 'owner': bus.owner = ':1.11'
    if change == 'none':
        assert backend.open_filesystem(device['device_id'], device['token'])['ok']
    else:
        with pytest.raises(kde.ProtocolError): backend.open_filesystem(device['device_id'], device['token'])
    assert any(call[3] == 'startBrowsing' for call in bus.calls) is (change == 'none')
    assert not any(call[3] in ('setPluginEnabled', 'requestPairing', 'StartServiceByName') for call in bus.calls)


@pytest.fixture
def direct(tmp_path, monkeypatch):
    backend = kde.KDEConnectSMSBackend(str(tmp_path / 'identity'), 'Fixture')
    identifier = 'a' * 32
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identifier)])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
    backend.store.confirm_peer_and_cleanup(identifier, 'Synthetic phone', certificate, '192.0.2.10', 1716)
    identity = {'deviceId': identifier, 'deviceName': 'Synthetic phone', 'deviceType': 'phone',
        'incomingCapabilities': [fs.REQUEST], 'outgoingCapabilities': [fs.PACKET]}
    class Worker:
        def __init__(self):
            self.identity = identity
            self.stopped = threading.Event()
            self.filesystem_token = uuid.uuid4().hex
            self.filesystem_gate = threading.Lock()
            self.filesystem_condition = threading.Condition()
            self.filesystem_pending = None
            self.filesystem_blocked = False
            self.sent = []
            self.respond = lambda: backend._filesystem_packet(self, kde.network_packet(fs.PACKET, body()))
        def send(self, message):
            self.sent.append(copy.deepcopy(message))
            self.respond()
    worker = Worker()
    backend._connections[identifier] = {'worker': worker, 'identity': identity, 'certificate': certificate,
        'address': '192.0.2.10', 'port': 1716, 'generation': 1}
    monkeypatch.setattr(backend._filesystem_browser, 'available', lambda: True)
    opened = []
    def open_browser(source, address, report, certificate, current):
        assert source is worker and current()
        opened.append((address, report, certificate))
        return {'ok': True, 'state': 'opened'}
    monkeypatch.setattr(backend._filesystem_browser, 'open', open_browser)
    return backend, worker, opened


@pytest.mark.parametrize('proxy', [False, True])
def test_explicit_encrypted_request_and_source_bound_reply_over_private_ipc(direct, tmp_path, proxy):
    backend, worker, opened = direct
    server = None
    try:
        transport = backend
        if proxy:
            path = str(tmp_path / 'background.sock')
            server = background.IPCServer(backend, path).start()
            transport = background.KDEConnectProxy(path=path)
        device = transport.filesystem_status()['devices'][0]
        assert 'password' not in json.dumps(device)
        result = transport.open_filesystem(device['device_id'], device['token'])
        assert result['state'] == 'opened' and len(opened) == 1
        assert opened[0][0] == '192.0.2.10' and opened[0][1].password == 'synthetic-only'
        assert worker.sent[0]['type'] == fs.REQUEST and worker.sent[0]['body'] == {'startBrowsing': True}
        assert worker.filesystem_pending is None
    finally:
        if server: server.close()


@pytest.mark.parametrize('change', ['token', 'closed', 'certificate', 'bluetooth', 'capability', 'client', 'stopping'])
def test_direct_unavailable_source_never_requests_or_opens(direct, change, monkeypatch):
    backend, worker, opened = direct
    device = backend.filesystem_status()['devices'][0]
    if change == 'token': device['token'] = 'b' * 32
    if change == 'closed': worker.stopped.set()
    if change == 'certificate': backend._connections[device['device_id']]['certificate'] = None
    if change == 'bluetooth': backend._connections[device['device_id']]['address'] = 'AA:BB:CC:DD:EE:FF'
    if change == 'capability': worker.identity['outgoingCapabilities'] = []
    if change == 'client': monkeypatch.setattr(backend._filesystem_browser, 'available', lambda: False)
    if change == 'stopping': backend._stop_event.set()
    with pytest.raises(kde.ProtocolError): backend.open_filesystem(device['device_id'], device['token'])
    assert not worker.sent and not opened


def test_unsolicited_reply_is_not_cached_and_revocation_during_reply_prevents_open(direct):
    backend, worker, opened = direct
    backend._filesystem_packet(worker, kde.network_packet(fs.PACKET, body()))
    assert worker.filesystem_pending is None
    def revoked():
        backend._filesystem_packet(worker, kde.network_packet(fs.PACKET, body()))
        worker.stopped.set()
    worker.respond = revoked
    with pytest.raises(kde.ProtocolError): backend.open_filesystem('a' * 32, worker.filesystem_token)
    assert not opened and worker.filesystem_pending is None


def test_ipc_does_not_accept_uri_password_or_arbitrary_target():
    good = {'device_id': 'a' * 32, 'token': 'b' * 32}
    background._request_shape('open_filesystem', good)
    for invalid in [dict(good, uri='file:///'), dict(good, password='secret'), dict(good, device_id='../target'),
                    dict(good, token=True), {'device_id': 'a' * 32}]:
        with pytest.raises(background.IPCError): background._request_shape('open_filesystem', invalid)
