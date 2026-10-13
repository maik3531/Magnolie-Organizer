"""Use existing local MPRIS players; never launch a player (issue #28)."""
import threading
import time

from magnolie_kde_media import ACTIONS, command_body, player_name

PATH = '/org/mpris/MediaPlayer2'
PLAYER = 'org.mpris.MediaPlayer2.Player'
PROPERTIES = 'org.freedesktop.DBus.Properties'


class DesktopMpris:
    def __init__(self, bus, gio, glib):
        self.bus, self.gio, self.glib = bus, gio, glib
        self.lock = threading.RLock()

    @classmethod
    def create(cls):
        try:
            from gi.repository import Gio, GLib
            return cls(Gio.bus_get_sync(Gio.BusType.SESSION, None), Gio, GLib)
        except Exception:
            return None

    def _call(self, owner, path, interface, method, signature=None, args=(), reply=None, deadline=None):
        timeout = min(800, int(((deadline or time.monotonic() + 0.8) - time.monotonic()) * 1000))
        if timeout <= 0:
            raise TimeoutError('local_media_timeout')
        return self.bus.call_sync(owner, path, interface, method,
            self.glib.Variant(signature, args) if signature else None,
            self.glib.VariantType.new(reply) if reply else None,
            self.gio.DBusCallFlags.NO_AUTO_START, timeout, None).unpack()

    def _players(self, deadline):
        names = self._call('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'ListNames', reply='(as)', deadline=deadline)[0]
        if not isinstance(names, (list, tuple)) or len(names) > 4096 or any(not isinstance(n, str) for n in names):
            raise ValueError('invalid_local_media_list')
        values = {}
        for name in sorted(names):
            # Native KDE remote proxies must not be re-exported to their source.
            if (not isinstance(name, str) or not name.startswith('org.mpris.MediaPlayer2.')
                    or name.startswith('org.mpris.MediaPlayer2.kdeconnect.')):
                continue
            try:
                player_name(name)
                owner = self._call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'GetNameOwner', '(s)', (name,), '(s)', deadline=deadline)[0]
                props = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)',
                    (PLAYER,), '(a{sv})', deadline=deadline)[0]
                if props.get('CanControl') is not True:
                    continue
                values[name] = (owner, props)
            except Exception:
                continue
            if len(values) == 32:
                break
        return values

    @staticmethod
    def _metadata(name, props):
        metadata = props.get('Metadata') or {}
        title = metadata.get('xesam:title', '')
        artists = metadata.get('xesam:artist', [])
        album = metadata.get('xesam:album', '')
        result = {'player': name, 'isPlaying': props.get('PlaybackStatus') == 'Playing'}
        for key, value in (('title', title), ('artist', ', '.join(artists[:16]) if
                isinstance(artists, (list, tuple)) and all(isinstance(v, str) for v in artists[:16]) else ''), ('album', album)):
            result[key] = value[:4096] if isinstance(value, str) else ''
        for local, remote in (('CanPlay', 'canPlay'), ('CanPause', 'canPause'),
                ('CanGoNext', 'canGoNext'), ('CanGoPrevious', 'canGoPrevious'), ('CanSeek', 'canSeek')):
            result[remote] = props.get(local) is True
        for remote, value in (('pos', props.get('Position')), ('length', metadata.get('mpris:length'))):
            if type(value) is int and 0 <= value <= 2**63 - 1:
                result[remote] = value // 1000
        volume = props.get('Volume')
        if type(volume) in (int, float) and 0 <= volume <= 1:
            result['volume'] = round(volume * 100)
        return result

    def receive(self, body, permitted=lambda: True):
        if not isinstance(body, dict):
            raise ValueError('invalid_local_media_request')
        with self.lock:
            if not permitted():
                raise ValueError('local_media_source_changed')
            deadline = time.monotonic() + 2.0
            players = self._players(deadline)
            if body.get('requestPlayerList') is True:
                return [{'playerList': list(players), 'supportAlbumArtPayload': False}]
            name = player_name(body.get('player'))
            if name not in players:
                return [{'playerList': list(players)}]
            owner, props = players[name]
            actions = [key for key in ('action', 'setVolume', 'SetPosition', 'Seek') if key in body]
            if len(actions) > 1:
                raise ValueError('invalid_local_media_request')
            if actions:
                key = actions[0]
                action = body[key] if key == 'action' else {'setVolume': 'volume', 'SetPosition': 'position', 'Seek': 'seek'}[key]
                value = None if key == 'action' else body[key]
                command_body(name, action, value)
                required = {'Play': 'CanPlay', 'Pause': 'CanPause', 'Next': 'CanGoNext',
                    'Previous': 'CanGoPrevious', 'position': 'CanSeek', 'seek': 'CanSeek'}
                if action in required and props.get(required[action]) is not True:
                    raise ValueError('local_media_action_unavailable')
                if not permitted():
                    raise ValueError('local_media_source_changed')
                if action in ACTIONS:
                    self._call(owner, PATH, PLAYER, action, reply='()', deadline=deadline)
                elif action == 'volume':
                    self._call(owner, PATH, PROPERTIES, 'Set', '(ssv)',
                        (PLAYER, 'Volume', self.glib.Variant('d', value / 100)), '()', deadline=deadline)
                elif action == 'seek':
                    self._call(owner, PATH, PLAYER, 'Seek', '(x)', (value,), '()', deadline=deadline)
                else:
                    track = (props.get('Metadata') or {}).get('mpris:trackid')
                    if not isinstance(track, str) or not track.startswith('/') or value > (2**63 - 1) // 1000:
                        raise ValueError('local_media_position_unavailable')
                    self._call(owner, PATH, PLAYER, 'SetPosition', '(ox)', (track, value * 1000), '()', deadline=deadline)
            # A request addresses the existing unique bus owner, never its next
            # replacement or an executable inferred from its displayed name.
            current = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)', (PLAYER,), '(a{sv})', deadline=deadline)[0]
            return [self._metadata(name, current)]
