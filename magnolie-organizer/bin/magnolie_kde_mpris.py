"""Local MPRIS and an explicitly selected registered player (issue #28)."""
import json
import os
import re
import tempfile
import threading
import time

from magnolie_kde_media import ACTIONS, command_body, player_name

PATH = '/org/mpris/MediaPlayer2'
PLAYER = 'org.mpris.MediaPlayer2.Player'
PROPERTIES = 'org.freedesktop.DBus.Properties'


class DesktopMpris:
    def __init__(self, bus, gio, glib, directory=None):
        self.bus, self.gio, self.glib = bus, gio, glib
        self.lock = threading.RLock()
        self.settings_path = os.path.join(directory, 'media-player.json') if directory else None
        self.selected_apps = {'music': '', 'video': ''}
        self.launch_pending = {}
        loaded = False
        if self.settings_path:
            try:
                with open(self.settings_path, 'rb') as stream:
                    raw = stream.read(4097)
                if len(raw) <= 4096:
                    saved = json.loads(raw)
                    loaded = isinstance(saved, dict)
                    for slot in self.selected_apps:
                        value = saved.get(slot, saved.get('application', '') if slot == 'music' else '')
                        if self._valid_application(value): self.selected_apps[slot] = value
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        if not loaded:
            apps = self._applications()
            for slot, mime, category in (('music', 'audio/mpeg', 'Audio'), ('video', 'video/mp4', 'Video')):
                default = (self.gio.AppInfo.get_default_for_type(mime, False)
                    if hasattr(getattr(self.gio, 'AppInfo', None), 'get_default_for_type') else None)
                identifier = default.get_id() if default is not None else None
                if identifier not in apps:
                    identifier = next((key for key, app in sorted(apps.items())
                        if category in (app.get_categories() or '').split(';')), '')
                self.selected_apps[slot] = identifier

    @classmethod
    def create(cls, directory=None):
        try:
            from gi.repository import Gio, GLib
            return cls(Gio.bus_get_sync(Gio.BusType.SESSION, None), Gio, GLib, directory)
        except Exception:
            return None

    @staticmethod
    def _valid_application(value):
        return isinstance(value, str) and (value == '' or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,240}\.desktop', value) is not None)

    def _applications(self):
        if not hasattr(self.gio, 'AppInfo'):
            return {}
        result = {}
        for app in self.gio.AppInfo.get_all():
            identifier = app.get_id()
            if (self._valid_application(identifier) and identifier and hasattr(app, 'get_categories')
                    and 'Player' in (app.get_categories() or '').split(';') and not app.get_nodisplay()):
                result[identifier] = app
        return result

    def settings(self):
        with self.lock:
            apps = self._applications()
            return {'available': bool(apps), **self.selected_apps,
                'applications': [{'id': identifier, 'name': app.get_display_name()}
                    for identifier, app in sorted(apps.items())][:64]}

    def configure(self, application, slot='music'):
        with self.lock:
            if slot not in self.selected_apps:
                raise ValueError('invalid_media_slot')
            if not self._valid_application(application) or application and application not in self._applications():
                raise ValueError('media_application_unavailable')
            selected = dict(self.selected_apps, **{slot: application})
            if self.settings_path:
                directory = os.path.dirname(self.settings_path)
                fd, path = tempfile.mkstemp(prefix='.media-player-', dir=directory)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write((json.dumps(selected) + '\n').encode())
                        stream.flush(); os.fsync(stream.fileno())
                    os.chmod(path, 0o600); os.replace(path, self.settings_path)
                finally:
                    if os.path.exists(path): os.unlink(path)
            self.selected_apps = selected
            self.launch_pending.pop(slot, None)
            return self.settings()

    def _selected(self):
        apps = self._applications()
        result = {}
        for slot, identifier in self.selected_apps.items():
            app = apps.get(identifier)
            if app is not None:
                name = 'Magnolie · ' + ('Musik · ' if slot == 'music' else 'Video · ') + app.get_display_name()
                alias = name.encode('utf-8')[:240].decode('utf-8', errors='ignore')
                result[alias] = (slot, identifier, app)
        return result

    @staticmethod
    def _dormant(name):
        return {'player': name, 'title': '', 'isPlaying': False, 'canPlay': True,
            'canPause': False, 'canGoNext': False, 'canGoPrevious': False, 'canSeek': False}

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
        selected = self._selected()
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
                if selected:
                    root = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)',
                        ('org.mpris.MediaPlayer2',), '(a{sv})', deadline=deadline)[0]
                    entry = root.get('DesktopEntry')
                    for alias, (_slot, identifier, _app) in selected.items():
                        if entry in (identifier, identifier[:-8]):
                            values[alias] = (owner, props)
                else:
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
            selected = self._selected()
            names = list(selected) if selected else list(players)
            if body.get('requestPlayerList') is True:
                return [{'playerList': names, 'supportAlbumArtPayload': False}]
            name = player_name(body.get('player'))
            if name in selected and name not in players:
                slot, _identifier, app = selected[name]
                actions = [key for key in ('action', 'setVolume', 'SetPosition', 'Seek') if key in body]
                if len(actions) > 1:
                    raise ValueError('invalid_local_media_request')
                if actions:
                    if actions != ['action'] or body['action'] not in ('Play', 'PlayPause'):
                        raise ValueError('local_media_action_unavailable')
                    if not permitted():
                        raise ValueError('local_media_source_changed')
                    if self.launch_pending.get(slot, 0) <= time.monotonic():
                        # The registered desktop application supplies its own
                        # launch command. Network packets supply only Play.
                        if not app.launch([], None):
                            raise ValueError('media_application_start_failed')
                        self.launch_pending[slot] = time.monotonic() + 10
                return [self._dormant(name)]
            if name not in players:
                return [{'playerList': names}]
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
