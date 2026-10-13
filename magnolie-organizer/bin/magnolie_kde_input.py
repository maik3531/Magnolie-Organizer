"""KDE Connect input contract and connection-scoped receive target (issue #149)."""
import math
import threading
import uuid

INPUT_PACKET = 'kdeconnect.mousepad.request'
INPUT_ECHO = 'kdeconnect.mousepad.echo'
KEYBOARD_STATE = 'kdeconnect.mousepad.keyboardstate'
PRESENTER_PACKET = 'kdeconnect.presenter'
CLICKS = ('singleclick', 'doubleclick', 'middleclick', 'rightclick', 'singlehold', 'singlerelease')
MODIFIERS = ('ctrl', 'alt', 'shift', 'super')


def input_body(body):
    if not isinstance(body, dict) or set(body) - set(CLICKS + MODIFIERS + (
            'dx', 'dy', 'x', 'y', 'scroll', 'key', 'specialKey', 'sendAck')):
        raise ValueError('invalid_remote_input')
    result = dict(body)
    for flag in CLICKS + MODIFIERS + ('scroll', 'sendAck'):
        if flag in body and type(body[flag]) is not bool:
            raise ValueError('invalid_remote_input_flag')
    for axis in ('dx', 'dy', 'x', 'y'):
        if axis in body:
            value = body[axis]
            maximum = 32768 if axis in ('x', 'y') else 4096
            minimum = -maximum
            if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError('invalid_remote_input_coordinate')
    if ('x' in body) != ('y' in body) or 'x' in body and ('dx' in body or 'dy' in body):
        raise ValueError('invalid_remote_input_coordinate')
    if 'key' in body:
        value = body['key']
        if (not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 1024 or
                any(ord(c) < 32 for c in value)):
            raise ValueError('invalid_remote_input_text')
    if 'specialKey' in body and (type(body['specialKey']) is not int or not 1 <= body['specialKey'] <= 32):
        raise ValueError('invalid_remote_input_key')
    if 'key' in body and 'specialKey' in body:
        raise ValueError('invalid_remote_input_key')
    click_count = sum(body.get(flag) is True for flag in CLICKS)
    keyboard = 'key' in body or 'specialKey' in body
    movement = any(axis in body for axis in ('dx', 'dy', 'x', 'y'))
    scroll = body.get('scroll') is True
    if (click_count > 1 or keyboard and (click_count or movement or scroll) or
            click_count and (movement or scroll) or scroll and 'x' in body or
            any(body.get(flag) is True for flag in MODIFIERS) and not keyboard):
        raise ValueError('ambiguous_remote_input')
    if not (keyboard or click_count or movement):
        raise ValueError('empty_remote_input')
    return result


def presenter_body(body):
    if not isinstance(body, dict) or set(body) - {'dx', 'dy', 'stop'}:
        raise ValueError('invalid_presenter_input')
    if body.get('stop') is True and set(body) == {'stop'}:
        return {'stop': True}
    if 'stop' in body and type(body['stop']) is not bool:
        raise ValueError('invalid_presenter_input')
    if body.get('stop') is True or not {'dx', 'dy'} <= set(body):
        raise ValueError('invalid_presenter_input')
    for axis in ('dx', 'dy'):
        value = body[axis]
        if type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError('invalid_presenter_input')
    return dict(body)


class InputTarget:
    """The transport initializes automatically; input still needs a live target.

    The operating-system sink is injected so authorization and protocol tests
    cannot accidentally type into the user's applications.
    """
    def __init__(self, sink):
        self.sink = sink
        self.lock = threading.RLock()
        self.owner = None
        self.token = ''
        self.permitted = lambda: False

    def arm(self, owner, token, permitted):
        if not isinstance(token, str):
            raise ValueError('invalid_input_target')
        try:
            uuid.UUID(token)
        except ValueError as error:
            raise ValueError('invalid_input_target') from error
        if not permitted():
            raise ValueError('input_target_not_ready')
        with self.lock:
            self.disarm()
            self.owner, self.token, self.permitted = owner, token, permitted

    def disarm(self, owner=None, token=None):
        with self.lock:
            if owner is not None and self.owner is not owner or token is not None and self.token != token:
                return False
            if self.owner is not None:
                try:
                    self.sink.release()
                finally:
                    self.owner, self.token, self.permitted = None, '', lambda: False
            return True

    def accept(self, owner, body):
        with self.lock:
            if self.owner is not owner:
                return False
            if not self._allowed():
                self.disarm(owner=owner)
                return False
            try:
                parsed = input_body(body)
                self.sink.apply(parsed)
                return True
            except Exception:
                self.disarm(owner=owner)
                raise

    def _allowed(self):
        try:
            return self.permitted() is True
        except Exception:
            return False

    def expire(self):
        with self.lock:
            if self.owner is not None and not self._allowed():
                self.disarm()
                return True
            return False
