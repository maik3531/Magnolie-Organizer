"""System output commands, native readback and paired-current-worker isolation (#262)."""
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_kde_volume import DesktopVolume, VOLUME_PACKET, VOLUME_REQUEST
from magnolie_kdeconnect import KDEConnectSMSBackend


class NativeOutputs:
    def __init__(self):
        self.name = 'owned-output'
        self.muted = True
        self.volume = 40
        self.balance = [1, 1]
        self.default = self.name
        self.writes = []
        self.on_read = lambda: None

    def run(self, arguments, **options):
        assert options['timeout'] == 1.5 and options['check'] is True
        assert options['stdin'] == subprocess.DEVNULL and 'shell' not in options
        command = arguments[1:]
        if command == ['--format=json', 'list', 'sinks']:
            self.on_read()
            value = round(self.volume * 65536 / 100)
            data = json.dumps([{'index': 17, 'name': self.name, 'description': 'Owned output',
                'mute': self.muted, 'volume': {'front-left': {'value': round(value * self.balance[0])},
                    'front-right': {'value': round(value * self.balance[1])}}}]).encode()
        elif command == ['get-default-sink']:
            data = self.default.encode() + b'\n'
        else:
            self.writes.append(command)
            assert command[1] == '17', 'Native numeric identity, never a remote-controlled command argument'
            if command[0] == 'set-sink-volume':
                values = [int(value) for value in command[2:]]
                maximum = max(values)
                self.volume = round(maximum * 100 / 65536)
                self.balance = [value / maximum if maximum else 1 for value in values]
            elif command[0] == 'set-sink-mute': self.muted = command[2] == '1'
            elif command[0] == 'set-default-sink': self.default = self.name
            else: raise AssertionError(command)
            data = b''
        return SimpleNamespace(stdout=data)


@pytest.fixture
def native():
    outputs = NativeOutputs()
    return outputs, DesktopVolume('/owned/pactl', outputs.run)


def test_read_only_device_list_and_poll_preserve_system_mute(native):
    outputs, volume = native
    result = volume.receive({'requestSinks': True})
    assert result == [volume.snapshot()]
    sink = result[0]['sinkList'][0]
    assert (sink['volume'], sink['maxVolume'], sink['muted'], sink['enabled']) == (40, 100, True, True)
    assert outputs.writes == [] and outputs.muted


def test_explicit_unmute_changes_system_output_without_touching_volume(native):
    outputs, volume = native
    result = volume.receive({'name': outputs.name, 'muted': False})
    assert outputs.writes == [['set-sink-mute', '17', '0']]
    assert result[0]['sinkList'][0]['muted'] is False
    assert result[0]['sinkList'][0]['volume'] == 40


def test_volume_action_also_unmutes_system_output_like_kde(native):
    outputs, volume = native
    result = volume.receive({'name': outputs.name, 'volume': 65})
    assert len(outputs.writes) == 2 and outputs.writes[0][:2] == ['set-sink-volume', '17']
    assert outputs.writes[1] == ['set-sink-mute', '17', '0']
    assert result[0]['sinkList'][0]['volume'] == 65
    assert result[0]['sinkList'][0]['muted'] is False


def test_explicit_mute_is_applied_after_combined_volume_action(native):
    outputs, volume = native
    result = volume.receive({'name': outputs.name, 'volume': 30, 'muted': True})
    assert outputs.muted and outputs.volume == 30
    assert result[0]['sinkList'][0]['muted'] is True


def test_system_volume_preserves_existing_channel_balance(native):
    outputs, volume = native
    outputs.balance = [.5, 1]
    result = volume.receive({'name': outputs.name, 'volume': 60})
    assert result[0]['sinkList'][0]['volume'] == 60
    assert outputs.balance[0] == pytest.approx(.5, abs=.0001)
    assert outputs.balance[1] == 1


def test_explicit_output_selection_uses_one_native_sink_argument(native):
    outputs, volume = native
    outputs.default = 'other-output'
    result = volume.receive({'name': outputs.name, 'enabled': True})
    assert outputs.writes == [['set-default-sink', '17']]
    assert result[0]['sinkList'][0]['enabled'] is True


@pytest.mark.parametrize('body', [None, [], {}, {'requestSinks': 1}, {'requestSinks': False},
    {'requestSinks': True, 'muted': False}, {'name': 'owned-output'},
    {'name': 'owned-output', 'volume': True}, {'name': 'owned-output', 'volume': 1.5},
    {'name': 'owned-output', 'volume': -1}, {'name': 'owned-output', 'volume': 101},
    {'name': 'owned-output', 'muted': 0}, {'name': 'owned-output', 'enabled': 'true'},
    {'name': 'owned-output', 'muted': False, 'command': 'anything'},
    {'name': 'bad\nname', 'muted': False}])
def test_invalid_commands_do_not_invoke_native_tools(native, body):
    outputs, volume = native
    with pytest.raises(ValueError): volume.receive(body)
    assert outputs.writes == []


def test_unknown_output_cannot_be_used_as_a_native_command_argument(native):
    outputs, volume = native
    with pytest.raises(ValueError): volume.receive({'name': '--server=foreign', 'muted': False})
    assert outputs.writes == []
    outputs.name = '--owned-native-name'
    volume.receive({'name': outputs.name, 'muted': False})
    assert outputs.writes == [['set-sink-mute', '17', '0']]


def test_revocation_during_native_read_prevents_the_mutating_command(native):
    outputs, volume = native
    allowed = [True]
    outputs.on_read = lambda: allowed.__setitem__(0, False)
    with pytest.raises(ValueError): volume.receive({'name': outputs.name, 'muted': False}, lambda: allowed[0])
    assert outputs.writes == [] and outputs.muted


def test_reply_is_native_readback_not_the_requested_value(native):
    outputs, volume = native
    real = outputs.run
    def coerced(arguments, **options):
        result = real(arguments, **options)
        if arguments[1] == 'set-sink-volume': outputs.volume = 58
        return result
    volume.run = coerced
    result = volume.receive({'name': outputs.name, 'volume': 60})
    assert result[0]['sinkList'][0]['volume'] == 58


def backend_fixture(volume):
    backend = KDEConnectSMSBackend.__new__(KDEConnectSMSBackend)
    backend._connection_lock = threading.RLock()
    backend._stop_event = threading.Event()
    backend._system_volume = volume
    backend.store = SimpleNamespace(peers={'owned': {'paired': True}})
    backend._media_pin_matches = lambda _id, entry: entry.get('pin') is True
    messages = []
    worker = SimpleNamespace(identity={'deviceId': 'owned', 'incomingCapabilities': [VOLUME_PACKET],
        'outgoingCapabilities': [VOLUME_REQUEST]}, stopped=threading.Event(), send=messages.append)
    backend._connections = {'owned': {'worker': worker, 'pin': True}}
    return backend, worker, messages


def test_native_packet_path_rechecks_pairing_pin_capability_and_current_connection(native):
    outputs, volume = native
    backend, worker, messages = backend_fixture(volume)
    packet = {'type': VOLUME_REQUEST, 'body': {'name': outputs.name, 'muted': False}}
    for change in ('unpaired', 'pin', 'capability', 'replacement', 'stopped'):
        original = backend._connections['owned'].copy()
        worker.identity['outgoingCapabilities'] = [VOLUME_REQUEST]
        backend.store.peers['owned']['paired'] = True
        backend._stop_event.clear()
        if change == 'unpaired': backend.store.peers['owned']['paired'] = False
        elif change == 'pin': backend._connections['owned']['pin'] = False
        elif change == 'capability': worker.identity['outgoingCapabilities'] = []
        elif change == 'replacement': backend._connections['owned']['worker'] = object()
        else: backend._stop_event.set()
        backend._system_volume_packet(worker, packet)
        assert not messages and not outputs.writes
        backend._connections['owned'] = original
    worker.identity['outgoingCapabilities'] = [VOLUME_REQUEST]
    backend._stop_event.clear()
    backend._system_volume_packet(worker, packet)
    assert len(messages) == 1 and messages[0]['type'] == VOLUME_PACKET
    assert messages[0]['body']['sinkList'][0]['muted'] is False


def test_monitor_publishes_the_initial_native_device_state_without_unmuting(native):
    outputs, volume = native
    backend, worker, messages = backend_fixture(volume)
    def receive(packet):
        messages.append(packet)
        backend._stop_event.set()
    worker.send = receive
    thread = threading.Thread(target=backend._system_volume_loop)
    thread.start(); thread.join(2)
    assert not thread.is_alive()
    assert len(messages) == 1 and messages[0]['body']['sinkList'][0]['muted'] is True
    assert outputs.writes == []
