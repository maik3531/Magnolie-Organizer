"""Passive native connectivity, not pairing/discovery and not an activation."""
from pathlib import Path
from types import SimpleNamespace
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'bin'))
import magnolie_kdeconnect as kde
import magnolie_hintergrund as background
from test_kde_native import Bus, Variant, native


class ConnectedBus(Bus):
    def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
        assert 0 < timeout <= 250 and flags == 4
        if method == 'devices':
            assert parameters.unpack() == (True, True)
            self.calls.append((owner, path, interface, method, parameters.unpack()))
            return Variant('(as)', (self.ids,))
        return super().call_sync(owner, path, interface, method, parameters, reply, flags, timeout, cancellable)


def test_system_projection_uses_paired_reachable_native_query_without_activation_or_plugin_reads():
    bus = ConnectedBus(); backend, _ = native(bus)
    assert backend.tray_connection_state() == {'connected': True, 'count': 1}
    assert [item[3] for item in bus.calls] == ['GetNameOwner', 'devices', 'GetNameOwner']
    bus.ids = []
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}
    bus.running = False
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}
    assert backend._activation_attempted is False
    assert not any(item[3] in ('StartServiceByName', 'GetAll', 'hasPlugin', 'requestPairing') for item in bus.calls)


def test_system_projection_rejects_replaced_service_owner_and_malformed_native_ids():
    bus = ConnectedBus(); backend, _ = native(bus)
    original = backend._owner; calls = []
    def owner(**kwargs):
        calls.append(None)
        return original(**kwargs) if len(calls) == 1 else ':1.11'
    backend._owner = owner
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}
    backend._owner = original; bus.ids = ['not/a/device']
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}


def test_system_native_connection_signals_are_readonly_deduplicated_and_unsubscribed():
    class SignalBus(Bus):
        def __init__(self):super().__init__();self.signals = {};self.unsubscribed = [];self.next_signal = 0;self.closed = None
        def signal_subscribe(self, *args):
            self.next_signal += 1;self.signals[self.next_signal] = args;return self.next_signal
        def signal_unsubscribe(self, value):self.unsubscribed.append(value);self.signals.pop(value)
        def connect(self, name, callback):assert name == 'closed';self.closed = callback;return 17
        def disconnect(self, value):assert value == 17;self.closed = None
    bus = SignalBus(); backend, gio = native(bus); events = []
    gio.DBusSignalFlags = SimpleNamespace(NONE=0); backend.callback = lambda *event:events.append(event)
    assert backend.start() and backend.start(); assert len(bus.signals) == 2
    assert events == [('connection_changed', {})], 'Explicit start must refresh an already connected native service exactly once'
    events.clear()
    assert any(value[1:3] == ('org.kde.kdeconnect.device', None) for value in bus.signals.values())
    assert any(value[2] == 'NameOwnerChanged' and value[4] == 'org.kde.kdeconnect' for value in bus.signals.values())
    next(iter(bus.signals.values()))[-1]('ignored stale packet')
    assert events == [('connection_changed', {})], 'Events must request a fresh native projection, not claim connected from payload'
    bus.closed();assert events[-1] == ('connection_changed', {})
    backend.stop(); backend.stop(); assert not bus.signals and len(bus.unsubscribed) == 2 and bus.closed is None
    assert not any(item[3] == 'StartServiceByName' for item in bus.calls)


def test_direct_projection_requires_live_worker_and_exact_current_confirmed_certificate(tmp_path):
    first = kde.IdentityStore(str(tmp_path / 'first'), 'Fixture one')
    second = kde.IdentityStore(str(tmp_path / 'second'), 'Fixture two')
    certificate = first.certificate.public_bytes(kde.serialization.Encoding.PEM).decode('ascii')
    backend = kde.KDEConnectSMSBackend.__new__(kde.KDEConnectSMSBackend)
    backend._state_lock = threading.RLock(); backend._connection_lock = threading.RLock()
    backend.store = SimpleNamespace(peers={'a' * 32: {'paired': True, 'certificate': certificate}})
    worker = SimpleNamespace(stopped=threading.Event())
    backend._connections = {}
    backend.start = lambda: pytest.fail('Passive tray projection started a transport')
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}, 'Paired is not connected'
    entry = {'worker': worker, 'certificate': first.certificate}; backend._connections['a' * 32] = entry
    assert backend.tray_connection_state() == {'connected': True, 'count': 1}
    worker.stopped.set()
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}
    worker.stopped.clear(); backend.store.peers['a' * 32]['paired'] = False
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}, 'Unconfirmed discovery is not a connection'
    backend.store.peers['a' * 32]['paired'] = True; entry['certificate'] = second.certificate
    assert backend.tray_connection_state() == {'connected': False, 'count': 0}, 'Old/foreign TLS identity is not the current partner'


def test_real_local_ipc_projection_never_bootstraps_backend_and_rejects_browser_state_claims(tmp_path):
    path = str(tmp_path / 'runtime' / 'tray.sock')
    server = background.IPCServer(None, path).start()
    try:
        proxy = background.KDEConnectProxy(path)
        assert proxy.tray_connection_state() == {'connected': False, 'count': 0}
        assert server.backend is None
        server.backend = SimpleNamespace(native=True, tray_connection_state=lambda: {'connected': True, 'count': 2})
        assert proxy.tray_connection_state() == {'connected': True, 'count': 2}
        with pytest.raises(background.IPCError):background.ipc_request('tray_connection_state', {'connected': True}, path)
    finally:server.close()
