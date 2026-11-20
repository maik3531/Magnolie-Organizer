"""Ephemeral view-only control bodies for #245; no advertisement or authority."""
import re
import secrets
import threading
import time
import uuid

VERSION = 26
REQUEST = 'device_status.request'  # Phone -> desktop
REPORT = 'device_status.report'   # Desktop -> phone
MAX_TTL_MS = 60_000
MAX_WIRE_BYTES = 4096
_BASE = {'version', 'request_id', 'nonce', 'op'}
_REASONS = {'not_granted', 'unsupported', 'foreground_required', 'permission_denied', 'capture_failed', 'output_failed', 'retired'}
_FIELDS = {'probe': (REQUEST, ()), 'offer': (REPORT, ('session', 'secret', 'port', 'width', 'height', 'density')),
           'prepared': (REQUEST, ('session',)), 'send': (REPORT, ('session',)),
           'stop': (None, ('session',)), 'error': (None, ('session', 'reason'))}


def validate_message(message, now=None):
    from magnolie_telefon import canonical, now_ms, valid_timestamp, valid_uuid
    if now is None:
        now = now_ms()
    if (type(message) is not dict or message.keys() != {'type', 'v', 'message_id', 'kind', 'created_ms', 'expires_ms', 'body'} or
            message['type'] != 'message' or type(message['v']) is not int or message['v'] != 1 or
            not valid_uuid(message['message_id'], 4) or not valid_timestamp(message['created_ms']) or
            not valid_timestamp(message['expires_ms']) or not 0 < message['expires_ms'] - message['created_ms'] <= MAX_TTL_MS or
            message['created_ms'] > now + MAX_TTL_MS or message['expires_ms'] <= now):
        raise ValueError('screen_control_envelope_invalid')
    body = validate_body(message['body'], message['kind'])
    if len(canonical(message)) > MAX_WIRE_BYTES:
        raise ValueError('screen_control_envelope_invalid')
    return body


class PhoneScreenDesktopChannel:
    """Adapter to the original SecureChannel's protected ephemeral writer.

    The service still owns dispatch and supplies a nonblocking live WLAN/pairing
    guard. Incoming values must already have arrived on its authenticated reader.
    """

    def __init__(self, channel, require_current):
        from magnolie_telefon import SecureChannel
        if type(channel) is not SecureChannel:
            raise TypeError('screen_control_original_channel_required')
        self._channel = channel
        self._current = require_current

    def body_from(self, actual, message):
        if actual is not self._channel or type(message) is not dict or message.get('kind') != REQUEST:
            raise PermissionError('screen_control_original_channel_required')
        self._current()
        return validate_message(message)

    def write(self, body, guard):
        from magnolie_telefon import now_ms
        now = now_ms()
        message = dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=REPORT,
                       created_ms=now, expires_ms=now + MAX_TTL_MS, body=body.copy())
        validate_message(message, now)

        def admitted():
            self._current()
            guard()

        self._channel.send_ephemeral(message, admitted)


def validate_body(body, kind):
    def invalid():
        raise ValueError('screen_control_invalid')

    def matches(key, size):
        value = body.get(key)
        return type(value) is str and re.fullmatch('[a-f0-9]{%d}' % size, value) is not None

    if type(body) is not dict or kind not in (REQUEST, REPORT):
        invalid()
    if type(body.get('version')) is not int or body['version'] != VERSION:
        invalid()
    request_id = body.get('request_id')
    if type(request_id) is not str or len(request_id) != 36:
        invalid()
    try:
        identity = uuid.UUID(request_id)
    except ValueError:
        invalid()
    if str(identity) != request_id or identity.version != 4 or not matches('nonce', 64):
        invalid()
    op = body.get('op')
    if type(op) is not str or op not in _FIELDS:
        invalid()
    direction, extra = _FIELDS[op]
    if direction not in (None, kind) or body.keys() != _BASE.union(extra):
        invalid()
    if 'session' in extra and not matches('session', 32):
        invalid()
    if op == 'error' and (type(body['reason']) is not str or body['reason'] not in _REASONS):
        invalid()
    if op == 'offer':
        port, width, height, density = (body[k] for k in ('port', 'width', 'height', 'density'))
        if (not matches('secret', 64) or any(type(v) is not int for v in (port, width, height, density)) or
                not 1024 <= port <= 65535 or not 2 <= width <= 1920 or not 2 <= height <= 1920 or
                width * height > 1920 * 1080 or not 1 <= density <= 1000):
            invalid()
    return body


class PhoneScreenDesktopControl:
    """Original opt-in + probe belong to one parent. Side effects are supplied by its native caller."""

    def __init__(self, parent, probe, require_current, *, clock=time.monotonic):
        validate_body(probe, REQUEST)
        if parent is None or probe['op'] != 'probe':
            raise ValueError('screen_original_probe_required')
        self._parent = parent
        self._base = {key: probe[key] for key in ('version', 'request_id', 'nonce')}
        self._current = require_current
        self._clock = clock
        self._issued = clock()
        self._lock = threading.Lock()
        self._phase = 'probe'
        self._identity = None

    def _require(self):
        try:
            self._current()
            with self._lock:
                age = self._clock() - self._issued
                if self._phase == 'closed' or not age >= 0 or (self._phase != 'sending' and not age < 60):
                    raise PermissionError('screen_original_control_retired')
        except Exception:
            self.close()
            raise

    def offer(self, *, port, width, height, density):
        """Only after the caller's explicit native opt-in and owned listener bind."""
        self._require()
        with self._lock:
            if self._phase != 'probe':
                raise PermissionError('screen_probe_already_consumed')
            packet = dict(self._base, op='offer', session=secrets.token_hex(16), secret=secrets.token_hex(32),
                          port=port, width=width, height=height, density=density)
            validate_body(packet, REPORT)
            self._identity = packet['session']
            self._phase = 'offered'
            return packet

    def receive(self, actual_parent, body):
        validate_body(body, REQUEST)
        if actual_parent is not self._parent or any(body[key] != value for key, value in self._base.items()):
            return False
        self._require()
        with self._lock:
            if self._identity is None or body.get('session') != self._identity or self._phase == 'closed':
                return False
            if body['op'] in ('stop', 'error'):
                self._phase = 'closed'
                return True
            if body['op'] != 'prepared' or self._phase != 'offered':
                return False
            self._phase = 'prepared'
            return True

    def authorize(self, require_view_and_proof, write_original):
        """Called by the original data worker. Both resource guards must be live
        through the protected control write; a successful callback is not an ACK."""
        self._require()
        with self._lock:
            if self._phase != 'prepared':
                raise PermissionError('screen_prepared_required')
            self._phase = 'publishing'
            packet = dict(self._base, op='send', session=self._identity)

        def require_write():
            self._require()
            require_view_and_proof()
            with self._lock:
                if self._phase != 'publishing':
                    raise PermissionError('screen_original_send_retired')

        try:
            require_write()
            write_original(packet, require_write)
            require_write()
            with self._lock:
                if self._phase != 'publishing':
                    raise PermissionError('screen_original_send_retired')
                self._phase = 'sending'
        except Exception:
            self.close()
            raise

    def require_send(self):
        self._require()
        with self._lock:
            if self._phase != 'sending':
                raise PermissionError('screen_original_send_required')

    def close(self):
        with self._lock:
            self._phase = 'closed'
