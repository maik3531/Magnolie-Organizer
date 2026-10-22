"""Local MPRIS and an explicitly selected registered player (issue #28)."""
import json
import hashlib
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, unquote

from magnolie_kde_media import ACTIONS, command_body, player_name

PATH = '/org/mpris/MediaPlayer2'
PLAYER = 'org.mpris.MediaPlayer2.Player'
PROPERTIES = 'org.freedesktop.DBus.Properties'
TRACKLIST = 'org.mpris.MediaPlayer2.TrackList'
MEDIA_EXTENSIONS = {
    'music': ('.mp3', '.flac', '.wav', '.ogg', '.opus', '.m4a', '.aac', '.aiff', '.aif', '.wma'),
    'video': ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.mpeg', '.mpg', '.ogv', '.wmv', '.ts'),
}
MAX_ART_BYTES = 2 * 1024 * 1024
CURRENT_PLAYER = 'Magnolie · Aktuelle Wiedergabe'
TV_APPLICATIONS = frozenset(('iptv-recorder.desktop', 'hypnotix.desktop', 'com.github.linuxmint.hypnotix.desktop'))


@dataclass(frozen=True)
class ArtworkPayload:
    body: dict
    data: bytes


class DesktopMpris:
    def __init__(self, bus, gio, glib, directory=None):
        self.bus, self.gio, self.glib = bus, gio, glib
        self.lock = threading.RLock()
        self.settings_path = os.path.join(directory, 'media-player.json') if directory else None
        self.selected_apps = {'music': '', 'video': ''}
        self.launch_pending = {}
        self.deferred_play = {}
        self.current_owner = None
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
                        if self._valid_application(value) and not (slot == 'music' and value in TV_APPLICATIONS): self.selected_apps[slot] = value
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        if not loaded:
            apps = self._applications()
            for slot, mime, category in (('music', 'audio/mpeg', 'Audio'), ('video', 'video/mp4', 'Video')):
                default = (self.gio.AppInfo.get_default_for_type(mime, False)
                    if hasattr(getattr(self.gio, 'AppInfo', None), 'get_default_for_type') else None)
                identifier = default.get_id() if default is not None else None
                if identifier not in apps or slot == 'music' and identifier in TV_APPLICATIONS:
                    identifier = next((key for key, app in sorted(apps.items(), key=lambda entry: (entry[0] in TV_APPLICATIONS, entry[0]))
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
                    and ('Player' in (app.get_categories() or '').split(';') or identifier in TV_APPLICATIONS
                         and 'Video' in (app.get_categories() or '').split(';')) and not app.get_nodisplay()):
                result[identifier] = app
        return result

    def settings(self):
        with self.lock:
            apps = self._applications()
            return {'available': bool(apps), **self.selected_apps,
                'applications': [{'id': identifier, 'name': app.get_display_name(),
                                  'slots': ['video'] if identifier in TV_APPLICATIONS else ['music', 'video'],
                                  'can_open_files': identifier not in TV_APPLICATIONS}
                    for identifier, app in sorted(apps.items())][:64]}

    def configure(self, application, slot='music'):
        with self.lock:
            if slot not in self.selected_apps:
                raise ValueError('invalid_media_slot')
            if not self._valid_application(application) or application and application not in self._applications():
                raise ValueError('media_application_unavailable')
            if slot == 'music' and application in TV_APPLICATIONS:
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
            self.deferred_play.pop(slot, None)
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

    def open_file(self, slot, path, application):
        """Open the native chooser's local file with the explicitly assigned app."""
        with self.lock:
            if slot not in MEDIA_EXTENSIONS or self.selected_apps.get(slot) != application:
                raise ValueError('local_media_source_changed')
            app = self._applications().get(application)
            if app is None or application in TV_APPLICATIONS or not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path) or not path.lower().endswith(MEDIA_EXTENSIONS[slot]):
                raise ValueError('media_application_unavailable')
            if not app.launch([self.gio.File.new_for_path(path)], None):
                raise ValueError('media_application_start_failed')
            return {'state': 'handed_off', 'slot': slot}

    def tracks(self, slot, selected_track=None, token=None, permitted=lambda: True):
        """Use the assigned player's optional MPRIS TrackList, never a guessed library."""
        from urllib.parse import urlsplit, unquote
        with self.lock:
            if slot not in MEDIA_EXTENSIONS or not permitted():
                raise ValueError('local_media_source_changed')
            deadline = time.monotonic() + 2
            selected = next(((name, entry) for name, entry in self._selected().items() if entry[0] == slot), None)
            players = self._players(deadline)
            if selected is None or selected[0] not in players:
                return {'available': False, 'tracks': [], 'slot': slot}
            name, (_slot, application, _app) = selected
            owner = players[name][0]
            try:
                props = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)', (TRACKLIST,), '(a{sv})', deadline=deadline)[0]
                ids = props.get('Tracks')
                if not isinstance(ids, (list, tuple)) or len(ids) > 1000 or any(not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_/]+', value) for value in ids):
                    raise ValueError('invalid_local_media_tracklist')
                metadata = self._call(owner, PATH, TRACKLIST, 'GetTracksMetadata', '(ao)', (list(ids),), '(aa{sv})', deadline=deadline)[0] if ids else []
                if not isinstance(metadata, (list, tuple)) or len(metadata) > 1000:
                    raise ValueError('invalid_local_media_tracklist')
            except Exception:
                if selected_track is not None:
                    raise ValueError('local_media_source_changed')
                return {'available': False, 'tracks': [], 'slot': slot}
            tracks = []
            for item in metadata[:1000]:
                if not isinstance(item, dict) or item.get('mpris:trackid') not in ids:
                    continue
                uri = item.get('xesam:url', '')
                if not isinstance(uri, str): continue
                try: path = unquote(urlsplit(uri).path)
                except ValueError: continue
                if not path.lower().endswith(MEDIA_EXTENSIONS[slot]): continue
                artist = item.get('xesam:artist', [])
                tracks.append({'id': item['mpris:trackid'], 'title': str(item.get('xesam:title') or os.path.basename(path))[:500],
                    'artist': ', '.join(value[:200] for value in artist[:16] if isinstance(value, str)) if isinstance(artist, (list, tuple)) else ''})
            current_token = hashlib.sha256(json.dumps([application, owner, ids], ensure_ascii=True).encode()).hexdigest()
            if not permitted() or self.selected_apps.get(slot) != application:
                raise ValueError('local_media_source_changed')
            if selected_track is not None:
                if token != current_token or selected_track not in {item['id'] for item in tracks}:
                    raise ValueError('local_media_source_changed')
                self._call(owner, PATH, TRACKLIST, 'GoTo', '(o)', (selected_track,), '()', deadline=deadline)
                return {'state': 'handed_off', 'slot': slot}
            return {'available': True, 'tracks': tracks, 'slot': slot, 'token': current_token}

    @staticmethod
    def _dormant(name):
        return {'player': name, 'title': '', 'albumArtUrl': '', 'isPlaying': False, 'canPlay': True,
            'canPause': False, 'canGoNext': False, 'canGoPrevious': False, 'canSeek': False}

    def _call(self, owner, path, interface, method, signature=None, args=(), reply=None, deadline=None):
        timeout = min(800, int(((deadline or time.monotonic() + 0.8) - time.monotonic()) * 1000))
        if timeout <= 0:
            raise TimeoutError('local_media_timeout')
        return self.bus.call_sync(owner, path, interface, method,
            self.glib.Variant(signature, args) if signature else None,
            self.glib.VariantType.new(reply) if reply else None,
             self.gio.DBusCallFlags.NO_AUTO_START, timeout, None).unpack()

    def _raise_for_play(self, owner, deadline, permitted):
        try:
            root = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)', ('org.mpris.MediaPlayer2',), '(a{sv})', deadline=deadline)[0]
        except Exception:
            return
        if root.get('CanRaise') is True:
            if not permitted(): raise ValueError('local_media_source_changed')
            try:
                self._call(owner, PATH, 'org.mpris.MediaPlayer2', 'Raise', reply='()', deadline=deadline)
            except Exception:
                pass  # Missing window activation must not break supported playback.

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
                values[name] = (owner, props)
                if selected:
                    root = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)',
                        ('org.mpris.MediaPlayer2',), '(a{sv})', deadline=deadline)[0]
                    entry = root.get('DesktopEntry')
                    for alias, (_slot, identifier, _app) in selected.items():
                        if entry in (identifier, identifier[:-8]):
                            values[alias] = (owner, props)
                            values.pop(name, None)
            except Exception:
                continue
            if len(values) >= 32:
                break
        candidates = list(values.values())
        playing = [value for value in candidates if value[1].get('PlaybackStatus') == 'Playing']
        choices = playing or candidates
        current = next((value for value in choices if value[0] == self.current_owner), choices[0] if choices else None)
        if current:
            self.current_owner = current[0]
            values[CURRENT_PLAYER] = current
        else:
            self.current_owner = None
        return values

    @staticmethod
    def _metadata(name, props):
        metadata = props.get('Metadata') or {}
        title = metadata.get('xesam:title', '')
        artists = metadata.get('xesam:artist', [])
        album = metadata.get('xesam:album', '')
        result = {'player': name, 'isPlaying': props.get('PlaybackStatus') == 'Playing', 'albumArtUrl': ''}
        art = metadata.get('mpris:artUrl')
        if isinstance(art, str) and len(art) <= 4096 and not any(ord(char) < 32 for char in art):
            try:
                uri = urlsplit(art)
                if (uri.scheme in ('http', 'https') and uri.hostname or uri.scheme == 'file' and uri.netloc in ('', 'localhost')) and not uri.username and not uri.password:
                    result['albumArtUrl'] = art
            except ValueError:
                pass
        for key, value in (('title', title), ('artist', ', '.join(artists[:16]) if
                isinstance(artists, (list, tuple)) and all(isinstance(v, str) for v in artists[:16]) else ''), ('album', album)):
            result[key] = value[:4096] if isinstance(value, str) else ''
        for local, remote in (('CanPlay', 'canPlay'), ('CanPause', 'canPause'),
                ('CanGoNext', 'canGoNext'), ('CanGoPrevious', 'canGoPrevious'), ('CanSeek', 'canSeek')):
            result[remote] = props.get(local) is True
        if type(props.get('Shuffle')) is bool:
            result['shuffle'] = props['Shuffle']
        if props.get('LoopStatus') in ('None', 'Track', 'Playlist'):
            result['loopStatus'] = props['LoopStatus']
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
            for slot, pending in list(self.deferred_play.items()):
                if pending['until'] <= time.monotonic() or not pending['permitted']() or self.selected_apps.get(slot) != pending['application']:
                    self.deferred_play.pop(slot, None)
            # Registered launchers complement active MPRIS sessions. Selecting
            # VLC must not hide Firefox/Chromium playing a browser video.
            names = list(dict.fromkeys([CURRENT_PLAYER, *selected, *players]))[:32]
            if body.get('requestPlayerList') is True:
                return [{'playerList': names, 'supportAlbumArtPayload': True}]
            name = player_name(body.get('player'))
            if name == CURRENT_PLAYER and name not in players:
                if any(key in body for key in ('action', 'setVolume', 'SetPosition', 'Seek', 'setShuffle', 'setLoopStatus', 'albumArtUrl')):
                    raise ValueError('local_media_action_unavailable')
                return [dict(self._dormant(name), canPlay=False)]
            if name in selected and name not in players:
                slot, _identifier, app = selected[name]
                actions = [key for key in ('action', 'setVolume', 'SetPosition', 'Seek', 'setShuffle', 'setLoopStatus') if key in body]
                if len(actions) > 1:
                    raise ValueError('invalid_local_media_request')
                if actions:
                    if body.get('action') in ('Pause', 'Stop') and slot in self.deferred_play:
                        self.deferred_play.pop(slot, None)
                        return [self._dormant(name)]
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
                    self.deferred_play[slot] = {'application': _identifier, 'until': time.monotonic() + 30, 'permitted': permitted}
                return [self._dormant(name)]
            if name not in players:
                return [{'playerList': names}]
            owner, props = players[name]
            entry = selected.get(name)
            if entry and body.get('action'):
                self.deferred_play.pop(entry[0], None)
            if 'albumArtUrl' in body:
                art = body['albumArtUrl']
                if not isinstance(art, str) or art != (props.get('Metadata') or {}).get('mpris:artUrl') or len(art) > 4096:
                    raise ValueError('local_media_source_changed')
                uri = urlsplit(art)
                path = unquote(uri.path)
                if uri.scheme != 'file' or uri.netloc not in ('', 'localhost') or not os.path.isabs(path) or not os.path.isfile(path):
                    raise ValueError('local_media_art_unavailable')
                with open(path, 'rb') as stream:
                    data = stream.read(MAX_ART_BYTES + 1)
                image = data.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'GIF87a', b'GIF89a')) or data.startswith(b'RIFF') and data[8:12] == b'WEBP'
                if not data or len(data) > MAX_ART_BYTES or not image or not permitted():
                    raise ValueError('local_media_art_unavailable')
                return [ArtworkPayload({'player': name, 'albumArtUrl': art, 'transferringAlbumArt': True}, data)]
            actions = [key for key in ('action', 'setVolume', 'SetPosition', 'Seek', 'setShuffle', 'setLoopStatus') if key in body]
            if len(actions) > 1:
                raise ValueError('invalid_local_media_request')
            if actions:
                key = actions[0]
                if key in ('setShuffle', 'setLoopStatus'):
                    if key == 'setShuffle':
                        if type(body[key]) is not bool or type(props.get('Shuffle')) is not bool:
                            raise ValueError('local_media_action_unavailable')
                        prop, variant = 'Shuffle', self.glib.Variant('b', body[key])
                    else:
                        if body[key] not in ('None', 'Track', 'Playlist') or props.get('LoopStatus') not in ('None', 'Track', 'Playlist'):
                            raise ValueError('local_media_action_unavailable')
                        prop, variant = 'LoopStatus', self.glib.Variant('s', body[key])
                    if not permitted(): raise ValueError('local_media_source_changed')
                    self._call(owner, PATH, PROPERTIES, 'Set', '(ssv)', (PLAYER, prop, variant), '()', deadline=deadline)
                    current = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)', (PLAYER,), '(a{sv})', deadline=deadline)[0]
                    return [self._metadata(name, current)]
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
                    if action == 'Play' or action == 'PlayPause' and props.get('PlaybackStatus') != 'Playing':
                        self._raise_for_play(owner, deadline, permitted)
                        if not permitted(): raise ValueError('local_media_source_changed')
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
            if entry:
                slot, application, _app = entry
                self.launch_pending.pop(slot, None)
                pending = self.deferred_play.get(slot)
                if pending and pending['application'] == application and (props.get('CanPlay') is True or props.get('PlaybackStatus') == 'Playing'):
                    self.deferred_play.pop(slot, None)
                    if not permitted() or not pending['permitted'](): raise ValueError('local_media_source_changed')
                    self._raise_for_play(owner, deadline, permitted)
                    if not permitted() or not pending['permitted'](): raise ValueError('local_media_source_changed')
                    if props.get('PlaybackStatus') != 'Playing':
                        self._call(owner, PATH, PLAYER, 'Play', reply='()', deadline=deadline)
            # A request addresses the existing unique bus owner, never its next
            # replacement or an executable inferred from its displayed name.
            current = self._call(owner, PATH, PROPERTIES, 'GetAll', '(s)', (PLAYER,), '(a{sv})', deadline=deadline)[0]
            return [self._metadata(name, current)]
