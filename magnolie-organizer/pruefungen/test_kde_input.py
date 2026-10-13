"""Issue #149: bounded input and lifetime fences; no native input injection."""
import sys
from pathlib import Path
from unittest.mock import Mock
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_kde_input import input_body, presenter_body, InputTarget
import magnolie_kdeconnect as kde
from types import SimpleNamespace
from test_kde_native import Bus, Variant, native


@pytest.mark.parametrize('body', [{'dx': 10.5, 'dy': -2}, {'x': 300, 'y': 400},
    {'singleclick': True}, {'singlehold': True}, {'singlerelease': True},
    {'scroll': True, 'dy': 120}, {'key': 'ä 😀', 'shift': False, 'sendAck': True},
    {'specialKey': 9}, {'specialKey': 25}, {'specialKey': 14}])
def test_protocol_actions_and_presentation_keys(body):
    assert input_body(body) == body


@pytest.mark.parametrize('body', [{}, {'singleclick': 1}, {'dx': True}, {'dy': float('nan')},
    {'dx': 4097}, {'x': 100}, {'x': 100, 'y': 100, 'dx': 1},
    {'key': '\0'}, {'key': 'x' * 1025}, {'specialKey': True}, {'specialKey': 33},
    {'key': 'x', 'specialKey': 12}, {'singleclick': True, 'rightclick': True},
    {'singleclick': True, 'key': 'x'}, {'ctrl': True, 'dx': 1}, {'shell': 'anything'},
    {'scroll': True, 'x': 1, 'y': 1}])
def test_malformed_or_ambiguous_requests_are_rejected(body):
    with pytest.raises(ValueError):
        input_body(body)


def test_target_replacement_revocation_and_late_release_are_scoped():
    sink = Mock()
    target = InputTarget(sink)
    old, new = object(), object()
    old_token, new_token = str(uuid.uuid4()), str(uuid.uuid4())
    allowed = [True]
    target.arm(old, old_token, lambda: allowed[0])
    assert target.accept(old, {'singlehold': True})
    target.arm(new, new_token, lambda: allowed[0])
    sink.release.assert_called_once()
    assert not target.accept(old, {'key': 'late'})
    assert not target.disarm(token=old_token)
    assert target.accept(new, {'specialKey': 9})
    allowed[0] = False
    assert not target.accept(new, {'key': 'blocked'})
    assert sink.release.call_count == 2 and target.owner is None
    assert sink.apply.call_count == 2


def test_invalid_packet_or_failed_sink_releases_held_input():
    sink = Mock()
    target = InputTarget(sink)
    owner = object()
    target.arm(owner, str(uuid.uuid4()), lambda: True)
    target.accept(owner, {'singlehold': True})
    with pytest.raises(ValueError): target.accept(owner, {'specialKey': 33})
    assert target.owner is None
    sink.release.assert_called_once()
    target.arm(owner, str(uuid.uuid4()), lambda: True)
    sink.apply.side_effect = OSError('native sink unavailable')
    with pytest.raises(OSError): target.accept(owner, {'key': 'x'})
    assert target.owner is None and sink.release.call_count == 2


def test_presenter_packet_is_only_pointer_deltas_or_stop():
    assert presenter_body({'dx': 0.01, 'dy': -0.01}) == {'dx': 0.01, 'dy': -0.01}
    assert presenter_body({'stop': True}) == {'stop': True}
    for body in ({'key': 'x'}, {'dx': float('inf'), 'dy': 0}, {'dx': 2, 'dy': 0},
                 {'stop': True, 'dx': 0, 'dy': 0}, {'stop': 1}):
        with pytest.raises(ValueError): presenter_body(body)


def test_direct_input_initializes_and_stops_on_gui_revocation_and_source_change(tmp_path):
    backend = kde.KDEConnectSMSBackend(str(tmp_path))
    device = 'a' * 32
    backend.store.peers[device] = {'paired': True,
        'certificate': backend.store.certificate.public_bytes(kde.serialization.Encoding.PEM).decode('ascii')}
    identity = dict(deviceId=device, deviceName='Fixture', deviceType='desktop',
        incomingCapabilities=[kde.INPUT_PACKET, kde.KEYBOARD_STATE], outgoingCapabilities=[kde.INPUT_PACKET, kde.KEYBOARD_STATE])
    worker = kde._ConnectionWorker(backend, SimpleNamespace(), identity)
    backend._connections[device] = dict(identity=identity, worker=worker, certificate=backend.store.certificate)
    sink = Mock(); sink.status.return_value = {'pointer': True, 'keyboard': True}
    backend._input_sink = sink; backend._input_target = InputTarget(sink)
    ready = [True]
    backend.configure_input(permitted=lambda: ready[0])
    backend._refresh_input()
    assert worker.outgoing.get_nowait()['body'] == {'state': True}
    backend._input_packet(worker, kde.network_packet(kde.INPUT_PACKET, {'singlehold': True}))
    sink.apply.assert_called_once_with({'singlehold': True})
    backend._input_packet(worker, kde.network_packet(kde.KEYBOARD_STATE, {'state': True}))
    info = backend.input_status()['devices'][0]
    assert info['keyboard'] and info['pointer']
    backend.input_send(device, info['token'], {'specialKey': 9})
    assert worker.outgoing.get_nowait()['body'] == {'specialKey': 9}
    ready[0] = False
    backend._refresh_input()
    assert backend._input_target.owner is None
    assert worker.outgoing.get_nowait()['body'] == {'state': False}
    backend._input_packet(worker, kde.network_packet(kde.INPUT_PACKET, {'key': 'blocked'}))
    assert sink.apply.call_count == 1
    backend.store.peers[device]['paired'] = False
    with pytest.raises(kde.ProtocolError): backend.input_send(device, info['token'], {'key': 'blocked'})


class InputBus(Bus):
    def __init__(self):
        super().__init__()
        self.props['a' * 32]['type'] = 'desktop'
        self.keyboard_ready = True

    def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
        args = parameters.unpack() if parameters else ()
        if method == 'hasPlugin' and args[0] in ('kdeconnect_mousepad', 'kdeconnect_remotecontrol', 'kdeconnect_remotekeyboard'):
            self.calls.append((owner, path, interface, method, args))
            return Variant('(b)', (True,))
        if path.endswith('/remotekeyboard') or path.endswith('/remotecontrol'):
            assert owner == self.owner and flags == 4 and 0 < timeout <= 1500
            self.calls.append((owner, path, interface, method, args))
            if method == 'GetAll': return Variant('(a{sv})', ({'remoteState': self.keyboard_ready},))
            return Variant('()', ())
        return super().call_sync(owner, path, interface, method, parameters, reply, flags, timeout, cancellable)


def test_native_sender_uses_system_keyboard_and_pointer_without_changing_plugins(monkeypatch):
    bus = InputBus(); backend, _ = native(bus)
    monkeypatch.setattr(backend, '_contact_fingerprint', lambda _: 'f' * 64)
    status = backend.input_status()
    assert status['receiver']['system_managed'] and status['receiver']['ready'] is None
    device = status['devices'][0]
    backend.input_send(device['device_id'], device['token'], {'key': 'a', 'ctrl': True})
    assert bus.calls[-1][3:] == ('sendKeyPress', ('a', 0, False, True, False, False, False))
    backend.input_send(device['device_id'], device['token'], {'dx': 2, 'dy': -1})
    assert bus.calls[-1][3] == 'sendCommand'
    assert bus.calls[-1][4][0]['dx'].unpack() == 2.0
    bus.keyboard_ready = False
    before = sum(call[3] == 'sendKeyPress' for call in bus.calls)
    with pytest.raises(kde.ProtocolError): backend.input_send(device['device_id'], device['token'], {'key': 'blocked'})
    assert sum(call[3] == 'sendKeyPress' for call in bus.calls) == before
    with pytest.raises(kde.ProtocolError): backend.configure_input(enabled=False)
    assert not any(call[3] in ('setPluginEnabled', 'requestPairing', 'StartServiceByName') for call in bus.calls)
