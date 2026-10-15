"""Issue #28: launch only two owned registered desktop fixtures on a private bus.

Run with dbus-run-session -- python3 -B <this file>. No user applications or
profiles are selected, and both short-lived fixture children finish themselves.
"""
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    with tempfile.TemporaryDirectory(prefix='magnolie-player-native-', dir='/tmp/opencode') as directory:
        root = Path(directory)
        applications = root / 'data' / 'applications'
        applications.mkdir(parents=True)
        os.environ['XDG_DATA_HOME'] = str(root / 'data')
        os.environ['XDG_DATA_DIRS'] = str(root / 'empty-data')
        os.environ['XDG_CONFIG_HOME'] = str(root / 'config')
        child = root / 'owned_child.py'
        child.write_text('import pathlib,sys\npathlib.Path(sys.argv[1]).write_text("owned-launch\\n")\n', encoding='utf-8')
        for slot in ('music', 'video'):
            (applications / (slot + '.desktop')).write_text(
                '[Desktop Entry]\nType=Application\nName=Owned ' + slot + ' fixture\n'
                'Exec=' + sys.executable + ' ' + str(child) + ' ' + str(root / (slot + '.marker')) + '\n'
                'Categories=AudioVideo;Player;\nTerminal=false\n', encoding='utf-8')
        from gi.repository import Gio, GLib
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
        from magnolie_kde_mpris import DesktopMpris
        provider = DesktopMpris(Gio.bus_get_sync(Gio.BusType.SESSION, None), Gio, GLib, str(root))
        assert {item['id'] for item in provider.settings()['applications']} == {'music.desktop', 'video.desktop'}
        provider.configure('music.desktop', 'music')
        provider.configure('video.desktop', 'video')
        names = provider.receive({'requestPlayerList': True})[0]['playerList']
        assert len(names) == 2
        for name in names:
            assert provider.receive({'player': name, 'requestNowPlaying': True})[0]['canPlay']
            try:
                provider.receive({'player': name, 'action': 'Play'}, permitted=lambda: False)
            except ValueError:
                pass
            else:
                raise AssertionError('Revoked source launched an application')
        assert not list(root.glob('*.marker'))
        for name in names:
            provider.receive({'player': name, 'action': 'Play'})
        deadline = time.monotonic() + 5
        while len(list(root.glob('*.marker'))) != 2 and time.monotonic() < deadline:
            time.sleep(.02)
        assert all((root / (slot + '.marker')).read_text() == 'owned-launch\n' for slot in ('music', 'video'))
        assert (root / 'media-player.json').stat().st_mode & 0o777 == 0o600
        reopened = DesktopMpris(provider.bus, Gio, GLib, str(root))
        assert reopened.settings()['music'] == 'music.desktop' and reopened.settings()['video'] == 'video.desktop'
        print('Native GIO registry, two closed players, revoked-source fence, both owned launches and persisted choices: PASS')


if __name__ == '__main__':
    main()
