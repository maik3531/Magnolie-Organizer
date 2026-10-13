"""Issue #28: player lifetime, hostile packets and native D-Bus routing."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_kdeconnect as kde
from magnolie_kde_media import RemotePlayers, command_body, MEDIA_PACKET, MEDIA_REQUEST
from magnolie_hintergrund import _request_shape, IPCError
from test_kde_native import Bus, Variant, native
from magnolie_kde_mpris import DesktopMpris, PLAYER


def test_list_bootstrap_updates_removal_and_new_context():
    state = RemotePlayers()
    assert not state.snapshot('device')['ready']
    assert state.accept({'playerList': ['Music']}) == [
        {'player': 'Music', 'requestNowPlaying': True, 'requestVolume': True}]
    token = state.token
    state.accept({'player': 'Music', 'title': 'Track', 'volume': 50, 'canSeek': True})
    assert state.command(token, 'Music', 'seek', -1000000) == {'player': 'Music', 'Seek': -1000000}
    state.accept({'playerList': []})
    state.accept({'player': 'Music', 'title': 'Late response'})
    assert state.snapshot('device')['players'] == []
    with pytest.raises(ValueError, match='source_changed'):
        state.command(token, 'Music', 'Play')
    state.accept({'playerList': ['Music']})
    assert state.token != token
    assert state.snapshot('device')['players'] == [{'player': 'Music'}]


@pytest.mark.parametrize('body', [
    {'playerList': ['same', 'same']}, {'playerList': ['x'] * 33},
    {'playerList': ['bad\nname']}, {'playerList': [True]},
    {'player': 'Music', 'volume': True}, {'player': 'Music', 'volume': 101},
    {'player': 'Music', 'pos': float('nan')}, {'player': 'Music', 'canSeek': 1},
    {'player': 'Music', 'title': False},
])
def test_invalid_packet_does_not_corrupt_previous_state(body):
    state = RemotePlayers()
    state.accept({'playerList': ['Music']})
    before = state.snapshot('device')
    with pytest.raises(ValueError):
        state.accept(body)
    assert state.snapshot('device') == before


@pytest.mark.parametrize('action,value', [('shell', None), ('volume', True),
    ('volume', -1), ('position', -1), ('seek', float('inf')), ('Play', 'extra')])
def test_invalid_commands_cannot_reach_transport(action, value):
    with pytest.raises(ValueError):
        command_body('Music', action, value)


def test_capability_denial_and_ipc_shape():
    state = RemotePlayers()
    state.accept({'playerList': ['Music'], 'player': 'Music', 'canSeek': False})
    with pytest.raises(ValueError, match='unavailable'):
        state.command(state.token, 'Music', 'position', 0)
    _request_shape('media_command', dict(device_id='a' * 32, token=state.token,
        player='Music', action='Play'))
    for args in ({'device_id': '../path'}, {'device_id': 'a' * 32, 'shell': 'anything'}):
        with pytest.raises(IPCError):
            _request_shape('media_status', args)


def test_long_unicode_metadata_is_bounded_without_dropping_playback_state():
    state = RemotePlayers()
    state.accept({'playerList': ['Music'], 'player': 'Music', 'title': '😀' * 1000, 'isPlaying': True})
    player = state.snapshot('device')['players'][0]
    assert player['title'] == '😀' * 32 and player['isPlaying'] is True


def test_direct_bootstrap_only_paired_capable_peer_and_late_worker_is_ignored(tmp_path):
    backend = kde.KDEConnectSMSBackend(str(tmp_path))
    device_id = 'a' * 32
    backend.store.peers[device_id] = {'paired': True, 'certificate': backend.store.certificate.public_bytes(kde.serialization.Encoding.PEM).decode('ascii')}
    identity = dict(deviceId=device_id, deviceName='Test phone', incomingCapabilities=[MEDIA_REQUEST], outgoingCapabilities=[MEDIA_PACKET])
    worker = kde._ConnectionWorker(backend, SimpleNamespace(), identity)
    backend._connections[device_id] = dict(worker=worker, identity=identity, certificate=backend.store.certificate)
    worker.enable_media()
    worker.enable_media()
    assert worker.outgoing.get_nowait()['body'] == {'requestPlayerList': True}
    assert worker.outgoing.empty()
    backend._media_packet(worker, dict(type=MEDIA_PACKET, body={'playerList': ['Music']}))
    assert worker.outgoing.get_nowait()['body']['requestNowPlaying']
    status = backend.media_status(device_id)
    assert backend.media_command(device_id, status['token'], 'Music', 'Next')['state'] == 'queued'
    assert worker.outgoing.get_nowait()['body'] == {'player': 'Music', 'action': 'Next'}
    replacement = kde._ConnectionWorker(backend, SimpleNamespace(), identity)
    backend._connections[device_id]['worker'] = replacement
    backend._media_packet(worker, dict(type=MEDIA_PACKET, body={'playerList': ['Late']}))
    assert not replacement.media.ready
    with pytest.raises(ValueError, match='source_changed'):
        backend.media_command(device_id, status['token'], 'Music', 'Next')
    backend.store.peers[device_id]['paired'] = False
    replacement.enable_media()
    assert replacement.outgoing.empty()
    with pytest.raises(kde.ProtocolError, match='unavailable'):
        backend.media_status(device_id)


class MediaBus(Bus):
    def __init__(self):
        super().__init__()
        self.media = {'playerList': ['Music'], 'player': 'Music', 'title': 'Track',
                      'position': 100, 'length': 10000, 'volume': 50, 'canSeek': True}
        self.enabled = True

    def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
        args = parameters.unpack() if parameters else ()
        if args == ('kdeconnect_mprisremote',) or path.endswith('/mprisremote'):
            assert owner == self.owner and flags == 4 and 0 < timeout <= 1500
            self.calls.append((owner, path, interface, method, args))
            if method == 'hasPlugin': return Variant('(b)', (self.enabled,))
            if method == 'GetAll': return Variant('(a{sv})', (dict(self.media),))
            return Variant('()', ())
        return super().call_sync(owner, path, interface, method, parameters, reply, flags, timeout, cancellable)


def test_native_media_uses_existing_plugin_and_binds_actions_to_list_and_owner():
    bus = MediaBus()
    backend, _ = native(bus)
    status = backend.media_status('a' * 32)
    assert status['players'][0]['title'] == 'Track'
    backend.media_command('a' * 32, status['token'], 'Music', 'Next')
    assert [call[3] for call in bus.calls[-2:]] == ['Set', 'sendAction']
    assert bus.calls[-1][4] == ('Next',)
    bus.media['playerList'] = []
    before = sum(call[3] == 'sendAction' for call in bus.calls)
    with pytest.raises(kde.ProtocolError, match='source_changed'):
        backend.media_command('a' * 32, status['token'], 'Music', 'Next')
    assert sum(call[3] == 'sendAction' for call in bus.calls) == before
    assert not any(call[3] in ('setPluginEnabled', 'requestPairing', 'StartServiceByName') for call in bus.calls)


@pytest.mark.parametrize('change', ['offline', 'unpaired', 'plugin', 'owner'])
def test_native_old_context_rejected_after_disconnect_or_backend_change(change):
    bus = MediaBus()
    backend, _ = native(bus)
    status = backend.media_status('a' * 32)
    if change == 'offline': bus.props['a' * 32]['isReachable'] = False
    elif change == 'unpaired': bus.props['a' * 32]['isPaired'] = False
    elif change == 'plugin': bus.enabled = False
    else: bus.owner = ':1.11'
    with pytest.raises(kde.ProtocolError):
        backend.media_command('a' * 32, status['token'], 'Music', 'Play')
    assert not any(call[3] == 'sendAction' for call in bus.calls)


class LocalBus:
    def __init__(self):
        self.calls = []
        self.name = 'org.mpris.MediaPlayer2.fixture'
        self.props = dict(CanControl=True, CanPlay=True, CanPause=True, CanSeek=True,
            CanGoNext=True, CanGoPrevious=True, PlaybackStatus='Playing', Volume=0.5,
            Position=3000000, Metadata={'xesam:title': 'Fixture', 'xesam:artist': ['Artist'],
                'mpris:length': 20000000, 'mpris:trackid': '/fixture/track'})
        self.after_read = lambda: None

    def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
        assert flags == 4 and 0 < timeout <= 800
        args = parameters.unpack() if parameters else ()
        self.calls.append((owner, method, args))
        if method == 'ListNames': return Variant('(as)', ([self.name, 'org.mpris.MediaPlayer2.kdeconnect.remote'],))
        if method == 'GetNameOwner':
            assert args == (self.name,)
            return Variant('(s)', (':1.20',))
        assert owner == ':1.20'
        if method == 'GetAll':
            assert args == (PLAYER,)
            self.after_read()
            return Variant('(a{sv})', (dict(self.props),))
        return Variant('()', ())


def local_media():
    _, gio = native()
    from test_kde_native import GLIB
    bus = LocalBus()
    return DesktopMpris(bus, gio, GLIB), bus


def test_local_player_queries_and_controls_keep_unique_owner_and_protocol_units():
    media, bus = local_media()
    assert media.receive({'requestPlayerList': True}) == [
        {'playerList': [bus.name], 'supportAlbumArtPayload': False}]
    state = media.receive({'player': bus.name, 'requestNowPlaying': True})[0]
    assert state['title'] == 'Fixture' and state['pos'] == 3000 and state['length'] == 20000
    assert state['volume'] == 50 and state['canSeek'] is True
    media.receive({'player': bus.name, 'SetPosition': 5000})
    assert (':1.20', 'SetPosition', ('/fixture/track', 5000000)) in bus.calls
    media.receive({'player': bus.name, 'Seek': -1000000})
    assert (':1.20', 'Seek', (-1000000,)) in bus.calls
    media.receive({'player': bus.name, 'setVolume': 25})
    volume = [call for call in bus.calls if call[1] == 'Set'][-1][2][2]
    assert volume.signature == 'd' and volume.unpack() == 0.25
    assert not any(call[1] == 'StartServiceByName' for call in bus.calls)


@pytest.mark.parametrize('kind', ['unpaired', 'capability', 'unknown', 'multiple'])
def test_local_actions_rejected_without_permission_or_supported_request(kind):
    media, bus = local_media()
    permitted = [True]
    body = {'player': bus.name, 'action': 'Play'}
    if kind == 'unpaired': bus.after_read = lambda: permitted.__setitem__(0, False)
    if kind == 'capability': bus.props['CanPlay'] = False
    if kind == 'unknown': body['action'] = 'shell'
    if kind == 'multiple': body['Seek'] = 1000
    with pytest.raises(ValueError):
        media.receive(body, permitted=lambda: permitted[0])
    assert not any(call[1] in ('Play', 'Seek', 'Set', 'SetPosition') for call in bus.calls)


def test_local_packet_only_uses_current_pinned_worker(tmp_path):
    backend = kde.KDEConnectSMSBackend(str(tmp_path))
    backend._local_media, bus = local_media()
    device = 'a' * 32
    backend.store.peers[device] = {'paired': True, 'certificate': backend.store.certificate.public_bytes(kde.serialization.Encoding.PEM).decode('ascii')}
    identity = dict(deviceId=device, deviceName='Fixture', incomingCapabilities=[MEDIA_PACKET], outgoingCapabilities=[MEDIA_REQUEST])
    worker = kde._ConnectionWorker(backend, SimpleNamespace(), identity)
    backend._connections[device] = dict(worker=worker, certificate=backend.store.certificate)
    worker.enable_media(); worker.enable_media()
    assert worker.outgoing.get_nowait()['body']['playerList'] == [bus.name]
    assert worker.outgoing.empty()
    packet = kde.network_packet(MEDIA_REQUEST, {'player': bus.name, 'action': 'Play'})
    backend._local_media_packet(worker, packet)
    assert any(call[1] == 'Play' for call in bus.calls)
    before = len(bus.calls)
    backend.store.peers[device]['paired'] = False
    backend._local_media_packet(worker, packet)
    assert len(bus.calls) == before
