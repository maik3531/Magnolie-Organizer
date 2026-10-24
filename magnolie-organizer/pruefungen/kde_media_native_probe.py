#!/usr/bin/env python3
"""Real Gio/D-Bus media probe; run ONLY inside a fresh dbus-run-session."""
from pathlib import Path
import os
import sys
import threading

os.environ['GIO_USE_VFS'] = 'local'
os.environ['NO_AT_BRIDGE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from gi.repository import Gio, GLib
from magnolie_kdeconnect import KDEConnectNativeBackend
from magnolie_kde_mpris import DesktopMpris, ArtworkPayload, CURRENT_PLAYER


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
        'org.freedesktop.DBus', 'ListNames', None, GLib.VariantType.new('(as)'),
        Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()[0]
    assert all(name == 'org.freedesktop.DBus' or name.startswith(':') for name in names), 'Fresh isolated D-Bus required'
    calls = []
    device = 'a' * 32
    media = dict(playerList=['Fixture'], player='Fixture', title='Native fixture', artist='', album='',
                 position=1000, length=20000, volume=50, canSeek=True, isPlaying=False)
    local = dict(CanControl=True, CanPlay=True, CanPause=True, CanSeek=True,
        CanGoNext=True, CanGoPrevious=True, PlaybackStatus='Playing', Volume=0.5, Position=3000000, Shuffle=False, LoopStatus='None',
        Metadata={'xesam:title': GLib.Variant('s', 'Local fixture'),
            'xesam:artist': GLib.Variant('as', ['Artist']),
            'mpris:length': GLib.Variant('x', 20000000),
             'mpris:trackid': GLib.Variant('o', '/fixture/track')})
    root_props = dict(DesktopEntry='fixture', CanRaise=True, CanQuit=True)
    track_props = dict(Tracks=['/fixture/track', '/fixture/video'])
    device_props = dict(isPaired=True, isReachable=True, type='phone', name='Fixture phone')
    registrations = []

    def register(path, name, methods, props=None):
        props = props or {}
        xml = '<node><interface name="' + name + '">' + methods
        for key, signature in props.items():
            xml += '<property name="' + key + '" type="' + signature + '" access="readwrite"/>'
        xml += '</interface></node>'
        info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
        values = local if name == 'org.mpris.MediaPlayer2.Player' else root_props if name == 'org.mpris.MediaPlayer2' else track_props if name == 'org.mpris.MediaPlayer2.TrackList' else media if name.endswith('.mprisremote') else device_props

        def method(connection, sender, object_path, interface, member, parameters, invocation):
            args = parameters.unpack(); calls.append((name, member, args))
            if name == 'org.mpris.MediaPlayer2.Player' and member in ('Play', 'Stop'):
                local['PlaybackStatus'] = 'Playing' if member == 'Play' else 'Stopped'
            if name == 'org.mpris.MediaPlayer2' and member == 'Quit':
                bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                    'ReleaseName', GLib.Variant('(s)', ('org.mpris.MediaPlayer2.fixture',)),
                    GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 1000, None)
            if member == 'devices': invocation.return_value(GLib.Variant('(as)', ([device],)))
            elif member == 'hasPlugin': invocation.return_value(GLib.Variant('(b)', (args[0] in ('kdeconnect_sms', 'kdeconnect_mprisremote'),)))
            elif member == 'GetTracksMetadata': invocation.return_value(GLib.Variant('(aa{sv})', ([
                {'mpris:trackid': GLib.Variant('o', '/fixture/track'), 'xesam:url': GLib.Variant('s', 'file:///fixture/song.mp3'), 'xesam:title': GLib.Variant('s', 'Owned music')},
                {'mpris:trackid': GLib.Variant('o', '/fixture/video'), 'xesam:url': GLib.Variant('s', 'file:///fixture/movie.mp4'), 'xesam:title': GLib.Variant('s', 'Owned video')}],)))
            else: invocation.return_value(GLib.Variant('()', ()))

        def get_property(connection, sender, object_path, interface, prop):
            return GLib.Variant(props[prop], values[prop])

        def set_property(connection, sender, object_path, interface, prop, value):
            calls.append((name, 'Set', (prop, value.unpack())))
            values[prop] = value.unpack(); return True

        registrations.append(bus.register_object(path, info, method, get_property, set_property))

    register('/modules/kdeconnect', 'org.kde.kdeconnect.daemon',
        '<method name="devices"><arg type="b" direction="in"/><arg type="b" direction="in"/><arg type="as" direction="out"/></method>')
    register('/modules/kdeconnect/devices/' + device, 'org.kde.kdeconnect.device',
        '<method name="hasPlugin"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>',
        dict(isPaired='b', isReachable='b', type='s', name='s'))
    register('/modules/kdeconnect/devices/' + device + '/mprisremote', 'org.kde.kdeconnect.device.mprisremote',
        '<method name="requestPlayerList"/><method name="sendAction"><arg type="s" direction="in"/></method>'
        '<method name="seek"><arg type="i" direction="in"/></method>',
        dict(playerList='as', player='s', title='s', artist='s', album='s', position='i', length='i', volume='i', canSeek='b', isPlaying='b'))
    register('/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player',
        '<method name="Play"/><method name="Pause"/><method name="Stop"/><method name="Seek"><arg type="x" direction="in"/></method>'
        '<method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>',
        dict(CanControl='b', CanPlay='b', CanPause='b', CanSeek='b', CanGoNext='b', CanGoPrevious='b',
            PlaybackStatus='s', Volume='d', Position='x', Metadata='a{sv}', Shuffle='b', LoopStatus='s'))
    register('/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2', '<method name="Raise"/><method name="Quit"/>',
        dict(DesktopEntry='s', CanRaise='b', CanQuit='b'))
    register('/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.TrackList',
        '<method name="GetTracksMetadata"><arg type="ao" direction="in"/><arg type="aa{sv}" direction="out"/></method>'
        '<method name="GoTo"><arg type="o" direction="in"/></method>', dict(Tracks='ao'))
    for name in ('org.kde.kdeconnect', 'org.mpris.MediaPlayer2.fixture'):
        result = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'RequestName', GLib.Variant('(su)', (name, 0)), GLib.VariantType.new('(u)'),
            Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        assert result == 1
    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run, daemon=True); thread.start()
    try:
        native = KDEConnectNativeBackend(bus, Gio, GLib)
        assert native.media_devices()['devices'] == [{'device_id': device, 'device_name': 'Fixture phone'}]
        status = native.media_status(device)
        assert status['players'][0]['title'] == 'Native fixture'
        native.media_command(device, status['token'], 'Fixture', 'Play')
        native.media_command(device, status['token'], 'Fixture', 'volume', 25)
        native.media_command(device, status['token'], 'Fixture', 'position', 5000)
        assert media['volume'] == 25 and media['position'] == 5000
        assert ('org.kde.kdeconnect.device.mprisremote', 'sendAction', ('Play',)) in calls
        desktop = DesktopMpris(bus, Gio, GLib)
        desktop.selected_apps = {'music': '', 'video': ''}
        assert desktop.receive({'requestPlayerList': True})[0]['playerList'] == [CURRENT_PLAYER, 'org.mpris.MediaPlayer2.fixture']
        assert desktop.receive({'player': CURRENT_PLAYER})[0]['title'] == 'Local fixture'
        desktop.receive({'player': CURRENT_PLAYER, 'action': 'Pause'})
        assert ('org.mpris.MediaPlayer2.Player', 'Pause', ()) in calls
        state = desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'requestNowPlaying': True})[0]
        assert state['title'] == 'Local fixture' and state['pos'] == 3000 and state['length'] == 20000
        desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'SetPosition': 5000})
        assert ('org.mpris.MediaPlayer2.Player', 'SetPosition', ('/fixture/track', 5000000)) in calls
        desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'Seek': -1000000})
        assert ('org.mpris.MediaPlayer2.Player', 'Seek', (-1000000,)) in calls
        desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'setShuffle': True})
        desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'setLoopStatus': 'Track'})
        assert local['Shuffle'] is True and local['LoopStatus'] == 'Track'
        desktop.selected_apps = {'music': 'fixture.desktop', 'video': 'fixture.desktop'}
        desktop._selected = lambda: {'Music': ('music', 'fixture.desktop', None), 'Video': ('video', 'fixture.desktop', None)}
        tracks = desktop.tracks('music')
        assert [track['title'] for track in tracks['tracks']] == ['Owned music']
        assert [track['title'] for track in desktop.tracks('video')['tracks']] == ['Owned video']
        desktop.tracks('music', tracks['tracks'][0]['id'], tracks['token'])
        assert ('org.mpris.MediaPlayer2.TrackList', 'GoTo', ('/fixture/track',)) in calls
        import tempfile
        with tempfile.TemporaryDirectory(prefix='kde-media-art-', dir='/tmp/opencode') as directory:
            cover = Path(directory) / 'owned.png'; cover.write_bytes(b'\x89PNG\r\n\x1a\nowned cover')
            local['Metadata']['mpris:artUrl'] = GLib.Variant('s', cover.as_uri())
            art = desktop.receive({'player': 'Music', 'albumArtUrl': cover.as_uri()})[0]
            assert isinstance(art, ArtworkPayload) and art.data == cover.read_bytes()
        from types import SimpleNamespace
        launched = []
        def launch(_files, _context):
            launched.append('fixture.desktop')
            bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                'RequestName', GLib.Variant('(su)', ('org.mpris.MediaPlayer2.fixture', 0)),
                GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 1000, None)
            return True
        app = SimpleNamespace(launch=launch)
        desktop.selected_apps = {'music': 'fixture.desktop', 'video': ''}
        desktop._selected = lambda: {'Music': ('music', 'fixture.desktop', app)}
        calls.clear(); local['PlaybackStatus'] = 'Playing'
        desktop.receive({'player': 'Music', 'action': 'Stop'})
        assert local['PlaybackStatus'] == 'Stopped' and not any(member == 'Quit' for _, member, _ in calls)
        desktop.receive({'player': 'Music', 'action': 'Stop'})
        assert any(member == 'Quit' for _, member, _ in calls)
        desktop.receive({'player': 'Music', 'action': 'Play'})
        assert launched == ['fixture.desktop']
        desktop.receive({'player': 'Music', 'requestNowPlaying': True})
        assert local['PlaybackStatus'] == 'Playing' and not any(member == 'Raise' for _, member, _ in calls)
        desktop.selected_apps = {'music': '', 'video': 'fixture.desktop'}
        desktop._selected = lambda: {'Video': ('video', 'fixture.desktop', app)}
        calls.clear()
        desktop.receive({'player': 'Video', 'action': 'Stop'})
        desktop.receive({'player': 'Video', 'action': 'Stop'})
        assert not any(member == 'Quit' for _, member, _ in calls)
        desktop.receive({'player': 'Video', 'action': 'Play'})
        assert any(member == 'Raise' for _, member, _ in calls)
        print('PASS: isolated real Gio/D-Bus remote controls and local MPRIS; position ms/us, volume, current players, separate music/video TrackList+GoTo, shuffle/repeat, actual cover bytes, unique owners')
        print('PASS: music Stop/Stop/Quit, exact registered restart without Raise; video Stop stays player-owned and Play raises')
    finally:
        loop.quit(); thread.join(1)
        for registration in registrations: bus.unregister_object(registration)


def rhythmbox_probe():
    """Exercise the installed player with an empty disposable profile and display."""
    import signal
    import subprocess
    import tempfile
    import time
    with tempfile.TemporaryDirectory(prefix='magnolie-rhythmbox-', dir='/tmp/opencode') as directory:
        root = Path(directory)
        for key, folder in (('HOME', 'home'), ('XDG_DATA_HOME', 'data'), ('XDG_CONFIG_HOME', 'config'),
                ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state'), ('XDG_RUNTIME_DIR', 'runtime')):
            path = root / folder; path.mkdir(mode=0o700)
            os.environ[key] = str(path)
        os.environ.pop('GTK_USE_PORTAL', None)
        os.environ['GSETTINGS_BACKEND'] = 'keyfile'
        for key in ('SSH_AUTH_SOCK', 'GNOME_KEYRING_CONTROL'):
            os.environ.pop(key, None)
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'ListNames', None, GLib.VariantType.new('(as)'), Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()[0]
        assert all(name == 'org.freedesktop.DBus' or name.startswith(':') for name in names), 'Private D-Bus required'
        activation = {key: value for key, value in os.environ.items()
            if key == 'HOME' or key.startswith('XDG_') or key in ('GSETTINGS_BACKEND', 'GIO_USE_VFS', 'NO_AT_BRIDGE')}
        bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'UpdateActivationEnvironment', GLib.Variant('(a{ss})', (activation,)), None,
            Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
        subprocess.run(['gsettings', 'set', 'org.gnome.rhythmbox.plugins', 'active-plugins', "['mpris']"],
            check=True, timeout=5, capture_output=True)
        provider = DesktopMpris(bus, Gio, GLib, str(root))
        identifier = next(key for key in provider._applications() if 'rhythmbox' in key.lower())
        provider.configure(identifier, 'music'); provider.configure('', 'video')
        alias = next(iter(provider._selected()))
        log = (root / 'rhythmbox.log').open('w+')
        process = subprocess.Popen(['rhythmbox', '--no-update'], stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
        def player():
            players = provider._players(time.monotonic() + 2)
            return players.get(alias)
        def wait_for(present):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                current = player()
                if bool(current) == present: return current
                time.sleep(.1)
            raise AssertionError('Installed Rhythmbox did not reach the expected MPRIS lifecycle state')
        try:
            current = wait_for(True)
            assert current[1]['PlaybackStatus'] == 'Stopped', 'Empty private profile unexpectedly playing'
            provider.receive({'player': alias, 'action': 'Stop'})
            wait_for(False)
            assert process.wait(8) == 0, 'Regular MPRIS Quit did not exit cleanly'
            provider.receive({'player': alias, 'action': 'Play'})
            wait_for(True)
            # The empty profile has no selected source to play. Delivery of Play
            # and the no-Raise behavior are covered by the real D-Bus fixture.
            assert provider.settings()['music'] == identifier
            provider.receive({'player': alias, 'action': 'Stop'})
            if player(): provider.receive({'player': alias, 'action': 'Stop'})
            wait_for(False)
            print('PASS: installed Rhythmbox, private empty profile, regular MPRIS Quit and exact registered Play restart')
        except BaseException:
            log.flush(); log.seek(0)
            print(log.read()[-4000:], file=sys.stderr)
            names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                'ListNames', None, GLib.VariantType.new('(as)'), Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()[0]
            print('Rhythmbox probe process exit:', process.poll(), 'MPRIS services:',
                [name for name in names if name.startswith('org.mpris.')], file=sys.stderr)
            raise
        finally:
            current = player()
            if current:
                pid = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                    'GetConnectionUnixProcessID', GLib.Variant('(s)', (current[0],)), GLib.VariantType.new('(u)'),
                    Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()[0]
                try: os.kill(pid, signal.SIGTERM)
                except ProcessLookupError: pass
            if process.poll() is None: process.terminate()
            try: process.wait(5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(3)
            log.close()
            for folder in ('doc', 'gvfs'):
                mount = root / 'runtime' / folder
                if os.path.ismount(mount):
                    subprocess.run(['fusermount3', '-u', str(mount)], timeout=5, capture_output=True)
                    if os.path.ismount(mount):
                        subprocess.run(['fusermount3', '-uz', str(mount)], timeout=5, capture_output=True, check=True)


if __name__ == '__main__':
    rhythmbox_probe() if '--rhythmbox' in sys.argv else main()
