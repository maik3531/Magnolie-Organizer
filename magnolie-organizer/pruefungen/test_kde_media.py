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
from magnolie_kde_mpris import DesktopMpris, PLAYER, TRACKLIST, ArtworkPayload, CURRENT_PLAYER


def test_closed_registered_music_and_video_keep_independent_choices_and_launch_fences(tmp_path):
    launched = []
    class App:
        def __init__(self, identifier): self.identifier = identifier
        def get_id(self): return self.identifier
        def get_categories(self): return 'AudioVideo;Player;'
        def get_nodisplay(self): return False
        def get_display_name(self): return 'Same display name'
        def launch(self, files, context):
            assert files == [] and context is None
            launched.append(self.identifier)
            return True
    apps = [App('music.desktop'), App('video.desktop')]
    gio = SimpleNamespace(AppInfo=SimpleNamespace(get_all=lambda: apps))
    provider = DesktopMpris(None, gio, None, str(tmp_path))
    provider._players = lambda _deadline: {}  # Both registered applications are closed.
    provider.configure('music.desktop', 'music')
    provider.configure('video.desktop', 'video')
    names = provider.receive({'requestPlayerList': True})[0]['playerList']
    assert names[0] == CURRENT_PLAYER and len(names) == 3 and len(set(names)) == 3
    assert provider.receive({'player': CURRENT_PLAYER})[0]['canPlay'] is False
    with pytest.raises(ValueError, match='unavailable'):
        provider.receive({'player': CURRENT_PLAYER, 'action': 'Play'})
    for name in names[1:]:
        assert provider.receive({'player': name, 'requestNowPlaying': True})[0]['canPlay']
        with pytest.raises(ValueError, match='unavailable'):
            provider.receive({'player': name, 'action': 'Pause'})
        with pytest.raises(ValueError, match='source_changed'):
            provider.receive({'player': name, 'action': 'Play'}, permitted=lambda: False)
    assert launched == []
    for name in names[1:]:
        provider.receive({'player': name, 'action': 'Play'})
        provider.receive({'player': name, 'action': 'Play'})
    assert launched == ['music.desktop', 'video.desktop']
    reopened = DesktopMpris(None, gio, None, str(tmp_path))
    assert reopened.settings()['music'] == 'music.desktop'
    assert reopened.configure('', 'music')['video'] == 'video.desktop'
    with pytest.raises(ValueError): reopened.configure('/bin/sh', 'video')
    with pytest.raises(ValueError): reopened.configure('music.desktop', 'shell')
    assert reopened.settings()['video'] == 'video.desktop'


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
            if args == ('org.mpris.MediaPlayer2',):
                return Variant('(a{sv})', ({'DesktopEntry': 'firefox'},))
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
        {'playerList': [CURRENT_PLAYER, bus.name], 'supportAlbumArtPayload': True}]
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


def test_registered_players_do_not_hide_current_browser_youtube_session():
    media, bus = local_media()
    alias = 'Magnolie · Music · VLC'
    media._selected = lambda: {alias: ('music', 'vlc.desktop', object())}
    bus.name = 'org.mpris.MediaPlayer2.firefox.instance123'
    bus.props['Metadata']['xesam:title'] = 'YouTube fixture'
    assert media.receive({'requestPlayerList': True})[0]['playerList'] == [CURRENT_PLAYER, alias, bus.name]
    state = media.receive({'player': bus.name, 'requestNowPlaying': True})[0]
    assert state['title'] == 'YouTube fixture' and state['isPlaying'] is True
    media.receive({'player': bus.name, 'action': 'Pause'})
    assert (':1.20', 'Pause', ()) in bus.calls
    assert not any(call[1] == 'StartServiceByName' for call in bus.calls)


def test_current_playback_routes_to_playing_browser_then_new_playing_session():
    class Sessions(LocalBus):
        def __init__(self):
            super().__init__()
            self.music = dict(self.props, PlaybackStatus='Paused', Metadata={'xesam:title': 'Music fixture'})
            self.browser = dict(self.props, Metadata={'xesam:title': 'YouTube fixture'})
        def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
            args = parameters.unpack() if parameters else ()
            self.calls.append((owner, method, args))
            if method == 'ListNames': return Variant('(as)', (['org.mpris.MediaPlayer2.vlc', 'org.mpris.MediaPlayer2.firefox'],))
            if method == 'GetNameOwner': return Variant('(s)', (':1.21' if args[0].endswith('.vlc') else ':1.22',))
            if method == 'GetAll': return Variant('(a{sv})', (dict(self.music if owner == ':1.21' else self.browser),))
            return Variant('()', ())
    _, gio = native()
    from test_kde_native import GLIB
    bus = Sessions(); media = DesktopMpris(bus, gio, GLIB)
    state = media.receive({'player': CURRENT_PLAYER})[0]
    assert state['title'] == 'YouTube fixture' and state['isPlaying'] is True
    media.receive({'player': CURRENT_PLAYER, 'action': 'Pause'})
    assert (':1.22', 'Pause', ()) in bus.calls and (':1.21', 'Pause', ()) not in bus.calls
    bus.browser['PlaybackStatus'] = 'Paused'; bus.music['PlaybackStatus'] = 'Playing'
    assert media.receive({'player': CURRENT_PLAYER})[0]['title'] == 'Music fixture'
    media.receive({'player': CURRENT_PLAYER, 'action': 'Pause'})
    assert (':1.21', 'Pause', ()) in bus.calls
    before = len(bus.calls)
    with pytest.raises(ValueError, match='source_changed'):
        media.receive({'player': CURRENT_PLAYER, 'action': 'Play'}, permitted=lambda: False)
    assert len(bus.calls) == before


def test_only_installed_tv_apps_without_player_category_are_video_choices(tmp_path):
    class App:
        def __init__(self, identifier, categories): self.identifier, self.categories = identifier, categories
        def get_id(self): return self.identifier
        def get_categories(self): return self.categories
        def get_nodisplay(self): return False
        def get_display_name(self): return self.identifier
    apps = [App('iptv-recorder.desktop', 'AudioVideo;Video;Recorder;'), App('hypnotix.desktop', 'AudioVideo;Video;'),
        App('vlc.desktop', 'AudioVideo;Audio;Video;Player;'), App('unknown-recorder.desktop', 'AudioVideo;Video;Recorder;')]
    gio = SimpleNamespace(AppInfo=SimpleNamespace(get_all=lambda: apps))
    media = DesktopMpris(None, gio, None, str(tmp_path))
    assert media.selected_apps == {'music': 'vlc.desktop', 'video': 'vlc.desktop'}
    choices = {entry['id']: entry for entry in media.settings()['applications']}
    assert set(choices) == {'iptv-recorder.desktop', 'hypnotix.desktop', 'vlc.desktop'}
    assert choices['iptv-recorder.desktop']['slots'] == choices['hypnotix.desktop']['slots'] == ['video']
    assert choices['iptv-recorder.desktop']['can_open_files'] is False
    with pytest.raises(ValueError): media.configure('iptv-recorder.desktop', 'music')
    assert media.configure('iptv-recorder.desktop', 'video')['video'] == 'iptv-recorder.desktop'
    apps[:] = [app for app in apps if app.identifier != 'hypnotix.desktop']
    assert 'hypnotix.desktop' not in {entry['id'] for entry in media.settings()['applications']}


def test_play_raises_existing_mpris_window_but_pause_does_not():
    class RaisingBus(LocalBus):
        def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
            args = parameters.unpack() if parameters else ()
            if method == 'GetAll' and args == ('org.mpris.MediaPlayer2',):
                self.calls.append((owner, method, args))
                return Variant('(a{sv})', ({'DesktopEntry': 'fixture', 'CanRaise': True},))
            return super().call_sync(owner, path, interface, method, parameters, reply, flags, timeout, cancellable)
    _, gio = native()
    from test_kde_native import GLIB
    bus = RaisingBus(); media = DesktopMpris(bus, gio, GLIB)
    media.receive({'player': CURRENT_PLAYER, 'action': 'Play'})
    assert (':1.20', 'Raise', ()) in bus.calls
    assert bus.calls.index((':1.20', 'Raise', ())) < bus.calls.index((':1.20', 'Play', ()))
    bus.calls.clear()
    media.receive({'player': CURRENT_PLAYER, 'action': 'Pause'})
    assert not any(method == 'Raise' for _owner, method, _args in bus.calls)
    bus.props['PlaybackStatus'] = 'Paused'
    media.receive({'player': CURRENT_PLAYER, 'action': 'PlayPause'})
    assert (':1.20', 'Raise', ()) in bus.calls


@pytest.mark.parametrize('change', ['none', 'revoked', 'expired', 'changed', 'stop'])
def test_closed_player_play_is_delivered_once_after_start_with_original_source_fence(change):
    media, bus = local_media()
    bus.props['PlaybackStatus'] = 'Paused'
    alias = 'Magnolie · Video · Fixture'
    launched = []
    app = SimpleNamespace(launch=lambda _files, _context: launched.append(True) or True)
    media.selected_apps = {'music': '', 'video': 'fixture.desktop'}
    media._selected = lambda: {alias: ('video', 'fixture.desktop', app)}
    ready, allowed = [False], [True]
    media._players = lambda _deadline: {alias: (':1.20', dict(bus.props))} if ready[0] else {}
    media.receive({'player': alias, 'action': 'Play'}, permitted=lambda: allowed[0])
    assert launched == [True] and media.deferred_play
    if change == 'revoked': allowed[0] = False
    if change == 'expired': media.deferred_play['video']['until'] = 0
    if change == 'changed': media.selected_apps['video'] = 'other.desktop'
    if change == 'stop': media.receive({'player': alias, 'action': 'Stop'})
    ready[0] = True
    media.receive({'player': alias, 'requestNowPlaying': True})
    plays = [value for value in bus.calls if value[1] == 'Play']
    assert len(plays) == (1 if change == 'none' else 0)
    media.receive({'player': alias, 'requestNowPlaying': True})
    assert len([value for value in bus.calls if value[1] == 'Play']) == len(plays)
    assert not media.deferred_play


def test_native_track_selection_filters_music_video_and_binds_current_player():
    class TrackBus(LocalBus):
        def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
            args = parameters.unpack() if parameters else ()
            if args == (TRACKLIST,):
                return Variant('(a{sv})', ({'Tracks': ['/fixture/music', '/fixture/video']},))
            if interface == TRACKLIST:
                assert owner == ':1.20'
                self.calls.append((owner, method, args))
                if method == 'GetTracksMetadata':
                    return Variant('(aa{sv})', ([{'mpris:trackid': '/fixture/music', 'xesam:url': 'file:///music/song.mp3', 'xesam:title': 'Owned music', 'xesam:artist': ['Artist']},
                        {'mpris:trackid': '/fixture/video', 'xesam:url': 'file:///video/film.mp4', 'xesam:title': 'Owned video'}],))
                return Variant('()', ())
            return super().call_sync(owner, path, interface, method, parameters, reply, flags, timeout, cancellable)
    _, gio = native()
    from test_kde_native import GLIB
    bus = TrackBus()
    media = DesktopMpris(bus, gio, GLIB)
    media.selected_apps = {'music': 'firefox.desktop', 'video': 'firefox.desktop'}
    media._selected = lambda: {'Music': ('music', 'firefox.desktop', None), 'Video': ('video', 'firefox.desktop', None)}
    music, video = media.tracks('music'), media.tracks('video')
    assert [item['title'] for item in music['tracks']] == ['Owned music']
    assert [item['title'] for item in video['tracks']] == ['Owned video']
    media.tracks('music', '/fixture/music', music['token'])
    assert (':1.20', 'GoTo', ('/fixture/music',)) in bus.calls
    for track, token in [('/fixture/video', music['token']), ('/fixture/music', '0' * 64)]:
        before = len(bus.calls)
        with pytest.raises(ValueError, match='source_changed'): media.tracks('music', track, token)
        assert not any(call[1] == 'GoTo' for call in bus.calls[before:])
    with pytest.raises(ValueError, match='source_changed'):
        media.tracks('music', '/fixture/music', music['token'], permitted=lambda: False)


def test_file_choice_opens_only_matching_media_kind_with_the_selected_application(tmp_path):
    launched = []
    class App:
        def get_id(self): return 'fixture.desktop'
        def get_categories(self): return 'AudioVideo;Player;'
        def get_nodisplay(self): return False
        def get_display_name(self): return 'Fixture'
        def launch(self, files, context): launched.extend(files); return True
    gio = SimpleNamespace(AppInfo=SimpleNamespace(get_all=lambda: [App()]), File=SimpleNamespace(new_for_path=lambda value: value))
    media = DesktopMpris(None, gio, None)
    media.selected_apps = {'music': 'fixture.desktop', 'video': 'fixture.desktop'}
    for slot, extension in [('music', '.mp3'), ('video', '.mp4')]:
        path = tmp_path / ('owned' + extension); path.write_bytes(b'owned media fixture')
        assert media.open_file(slot, str(path), 'fixture.desktop')['state'] == 'handed_off'
        with pytest.raises(ValueError): media.open_file('video' if slot == 'music' else 'music', str(path), 'fixture.desktop')
        with pytest.raises(ValueError): media.open_file(slot, str(path), 'different.desktop')
    assert launched == [str(tmp_path / 'owned.mp3'), str(tmp_path / 'owned.mp4')]


def test_actual_cover_metadata_and_local_payload_are_bound_to_current_player(tmp_path):
    media, bus = local_media()
    bus.props['Metadata']['mpris:artUrl'] = 'https://example.test/current-cover.jpg'
    assert media.receive({'player': bus.name, 'requestNowPlaying': True})[0]['albumArtUrl'] == 'https://example.test/current-cover.jpg'
    art = tmp_path / 'owned.png'; art.write_bytes(b'\x89PNG\r\n\x1a\nowned image fixture')
    bus.props['Metadata']['mpris:artUrl'] = art.as_uri()
    payload = media.receive({'player': bus.name, 'albumArtUrl': art.as_uri()})[0]
    assert isinstance(payload, ArtworkPayload) and payload.data == art.read_bytes()
    assert payload.body == {'player': bus.name, 'albumArtUrl': art.as_uri(), 'transferringAlbumArt': True}
    with pytest.raises(ValueError, match='source_changed'):
        media.receive({'player': bus.name, 'albumArtUrl': (tmp_path / 'another.png').as_uri()})
    art.write_bytes(b'not an image')
    with pytest.raises(ValueError, match='art_unavailable'):
        media.receive({'player': bus.name, 'albumArtUrl': art.as_uri()})
    for url in ['javascript:alert(1)', 'https://user:password@example.test/private', 'http:relative']:
        bus.props['Metadata']['mpris:artUrl'] = url
        assert media.receive({'player': bus.name, 'requestNowPlaying': True})[0]['albumArtUrl'] == '', 'Unavailable art must clear the previous cover'


def test_optional_shuffle_and_repeat_use_actual_supported_mpris_properties():
    media, bus = local_media()
    assert 'shuffle' not in media.receive({'player': bus.name})[0]
    with pytest.raises(ValueError, match='action_unavailable'):
        media.receive({'player': bus.name, 'setShuffle': True})
    bus.props.update(Shuffle=False, LoopStatus='None')
    state = media.receive({'player': bus.name})[0]
    assert state['shuffle'] is False and state['loopStatus'] == 'None'
    media.receive({'player': bus.name, 'setShuffle': True})
    media.receive({'player': bus.name, 'setLoopStatus': 'Track'})
    changes = [args for _owner, method, args in bus.calls if method == 'Set']
    assert changes[-2][1] == 'Shuffle' and changes[-2][2].unpack() is True
    assert changes[-1][1] == 'LoopStatus' and changes[-1][2].unpack() == 'Track'
    for body in [{'setShuffle': 1}, {'setLoopStatus': 'anything'}, {'setShuffle': True, 'action': 'Play'}]:
        before = len(bus.calls)
        with pytest.raises(ValueError): media.receive(dict(player=bus.name, **body))
        assert not any(method == 'Set' for _owner, method, _args in bus.calls[before:])


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
    assert worker.outgoing.get_nowait()['body']['playerList'] == [CURRENT_PLAYER, bus.name]
    assert worker.outgoing.empty()
    packet = kde.network_packet(MEDIA_REQUEST, {'player': bus.name, 'action': 'Play'})
    backend._local_media_packet(worker, packet)
    assert any(call[1] == 'Play' for call in bus.calls)
    before = len(bus.calls)
    backend.store.peers[device]['paired'] = False
    backend._local_media_packet(worker, packet)
    assert len(bus.calls) == before
