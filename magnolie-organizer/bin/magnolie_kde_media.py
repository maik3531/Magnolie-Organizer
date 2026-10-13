"""Bounded KDE Connect remote-player state and commands (issue #28).

Player names are protocol identifiers, never executable names or URLs. State is
owned by one authenticated connection and is discarded when that link changes.
"""
import math
import threading
import uuid

MEDIA_PACKET = 'kdeconnect.mpris'
MEDIA_REQUEST = 'kdeconnect.mpris.request'
ACTIONS = frozenset(('Play', 'Pause', 'PlayPause', 'Stop', 'Next', 'Previous'))
MAX_PLAYERS = 32
MAX_TIME = 2**53 - 1


def player_name(value):
    if (not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 256 or
            any(ord(c) < 32 for c in value)):
        raise ValueError('invalid_media_player')
    return value


def player_list(value):
    if not isinstance(value, (list, tuple)) or len(value) > MAX_PLAYERS:
        raise ValueError('invalid_media_players')
    result = [player_name(item) for item in value]
    if len(set(result)) != len(result):
        raise ValueError('invalid_media_players')
    return result


def command_body(player, action, value=None):
    body = {'player': player_name(player)}
    if action in ACTIONS:
        if value is not None:
            raise ValueError('invalid_media_value')
        body['action'] = action
    elif action in ('volume', 'position', 'seek'):
        low, high = (0, 100) if action == 'volume' else (
            (0, MAX_TIME) if action == 'position' else (-MAX_TIME, MAX_TIME))
        if type(value) is not int or not low <= value <= high:
            raise ValueError('invalid_media_value')
        body[{'volume': 'setVolume', 'position': 'SetPosition', 'seek': 'Seek'}[action]] = value
    else:
        raise ValueError('invalid_media_action')
    return body


class RemotePlayers:
    def __init__(self):
        self.lock = threading.RLock()
        self.token = uuid.uuid4().hex
        self.players = {}
        self.ready = False

    def accept(self, body):
        if not isinstance(body, dict):
            raise ValueError('invalid_media_packet')
        # Album-art payloads are not downloaded or exposed as arbitrary URLs.
        if body.get('transferringAlbumArt') is True:
            return []
        names = player_list(body['playerList']) if 'playerList' in body else None
        name = player_name(body['player']) if 'player' in body else None
        update = {}
        for key in ('title', 'artist', 'album', 'nowPlaying'):
            if key in body:
                value = body[key]
                if not isinstance(value, str):
                    raise ValueError('invalid_media_metadata')
                clean = ''.join(c for c in value if c.isprintable())
                update[key] = clean.encode('utf-8')[:128].decode('utf-8', errors='ignore')
        for key in ('isPlaying', 'canPause', 'canPlay', 'canGoNext', 'canGoPrevious', 'canSeek'):
            if key in body:
                if type(body[key]) is not bool:
                    raise ValueError('invalid_media_capability')
                update[key] = body[key]
        for key in ('pos', 'length', 'volume'):
            if key in body:
                value = body[key]
                if (type(value) not in (int, float) or not math.isfinite(value) or
                        not 0 <= value <= (100 if key == 'volume' else MAX_TIME)):
                    raise ValueError('invalid_media_value')
                update[key] = int(value)
        with self.lock:
            added = []
            if names is not None:
                added = [item for item in names if item not in self.players]
                if set(names) != set(self.players):
                    self.token = uuid.uuid4().hex
                self.players = {item: self.players.get(item, {}) for item in names}
                self.ready = True
            # A late update cannot resurrect a player removed by a new list.
            if name is not None and name in self.players:
                self.players[name].update(update)
            return [{'player': item, 'requestNowPlaying': True, 'requestVolume': True}
                    for item in added]

    def snapshot(self, device_id):
        with self.lock:
            return {'available': True, 'device_id': device_id, 'token': self.token,
                    'ready': self.ready,
                    'players': [dict(value, player=name) for name, value in self.players.items()]}

    def command(self, token, player, action, value=None):
        body = command_body(player, action, value)
        with self.lock:
            if token != self.token or not self.ready or player not in self.players:
                raise ValueError('media_source_changed')
            flags = self.players[player]
            required = {'Play': 'canPlay', 'Pause': 'canPause', 'Next': 'canGoNext',
                        'Previous': 'canGoPrevious', 'seek': 'canSeek', 'position': 'canSeek'}
            if required.get(action) and flags.get(required[action]) is False:
                raise ValueError('media_action_unavailable')
            return body
