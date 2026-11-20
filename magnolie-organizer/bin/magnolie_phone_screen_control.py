"""Ephemeral view-only control bodies for #245; no advertisement or authority."""
import re
import secrets
import threading
import time
import uuid
import weakref
from collections import deque

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

    def __init__(self, channel, require_current, track=lambda *_: None):
        from magnolie_telefon import SecureChannel
        if type(channel) is not SecureChannel:
            raise TypeError('screen_control_original_channel_required')
        self._channel = channel
        self._current = require_current
        self._track = track

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
        self._current()
        guard()
        self._track(message['message_id'])

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

    def __init__(self, parent, probe, require_current, *, clock=time.monotonic, deadline=None):
        validate_body(probe, REQUEST)
        if parent is None or probe['op'] != 'probe':
            raise ValueError('screen_original_probe_required')
        self._parent = parent
        self._base = {key: probe[key] for key in ('version', 'request_id', 'nonce')}
        self._current = require_current
        self._clock = clock
        self._issued = clock()
        self._deadline = self._issued + 60 if deadline is None else min(self._issued + 60, deadline)
        self._lock = threading.Lock()
        self._phase = 'probe'
        self._identity = None

    def _require(self):
        try:
            self._current()
            with self._lock:
                now = self._clock()
                if self._phase == 'closed' or not now >= self._issued or (self._phase != 'sending' and not now < self._deadline):
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


class PhoneScreenDesktopRun:
    """One explicit native Linux viewing request, on its exact live WLAN parent.

    The caller attaches the GTK view and routes v26 controls from the ordinary
    authenticated parent reader. Checks must be nonblocking and must not acquire
    the PhoneService monitor. Stopping signals only; the caller waits for drain.
    """

    def __init__(self, parent, probe, width, height, density, *, require_original, require_view, offer_rgb, track=lambda *_: None, deadline=None):
        self._parent = parent
        self._require_original = require_original
        self._require_view = require_view
        self._offer_rgb = offer_rgb
        self._width, self._height, self._density = width, height, density
        self._stop = threading.Event()
        self._prepared = threading.Event()
        self._lock = threading.Lock()
        self._listener = self._receiver = None
        self._started = self._peer_ended = False
        self._control = PhoneScreenDesktopControl(parent, probe, self._current, deadline=deadline)
        self._wire = PhoneScreenDesktopChannel(parent, require_original, track)
        self.failure = None
        self.cleanup_error = None
        self._thread = threading.Thread(target=self._run, name='magnolie-phone-screen-control', daemon=True)

    def start(self):
        with self._lock:
            if self._started or self._stop.is_set():
                raise RuntimeError('screen_desktop_owner_already_used')
            self._started = True
            try:
                self._thread.start()
            except Exception:
                self._stop.set()
                self._control.close()
                raise

    def _current(self):
        self._require_original()
        self._require_view()
        if self._stop.is_set():
            raise PermissionError('screen_desktop_owner_retired')

    def receive(self, actual, message):
        body = self._wire.body_from(actual, message)
        if not self._control.receive(actual, body):
            return False
        if body['op'] == 'prepared':
            self._prepared.set()
        else:
            self._peer_ended = True
            self.stop()
        return True

    def _run(self):
        from magnolie_phone_screen_transport import PhoneScreenReceiveRun, PhoneScreenWlanListener

        listener = socket = receiver = offer = None
        published = False
        try:
            listener = PhoneScreenWlanListener(self._parent, self._current)
            with self._lock:
                if self._stop.is_set():
                    raise PermissionError('screen_desktop_owner_retired')
                self._listener = listener
            offer = self._control.offer(port=listener.port, width=self._width, height=self._height, density=self._density)
            self._wire.write(offer, self._current)
            published = True
            while not self._prepared.wait(.1):
                self._control._require()
            self._current()
            socket = listener.accept()
            receiver = PhoneScreenReceiveRun(socket, bytes.fromhex(offer['session']), bytes.fromhex(offer['secret']),
                                             self._width, self._height, require_original=self._current,
                                             authorize_send=lambda: self._control.authorize(self._current, self._wire.write),
                                             require_send=self._control.require_send, offer_rgb=self._offer_rgb)
            with self._lock:
                if self._stop.is_set():
                    raise PermissionError('screen_desktop_owner_retired')
                self._receiver = receiver
                receiver.start()
            offer.pop('secret')
            receiver.join_worker()
            self.failure = receiver.failure
        except Exception as error:
            if not self._stop.is_set():
                self.failure = error
        finally:
            self.stop()
            self._cleanup(lambda: listener.close() if listener is not None else None)
            if receiver is not None:
                self._cleanup(receiver.stop)
                if receiver.cleanup_error is not None:
                    self.cleanup_error = receiver.cleanup_error
            elif socket is not None:
                self._cleanup(socket.close)
            if published and not self._peer_ended:
                try:
                    terminal = {key: offer[key] for key in ('version', 'request_id', 'nonce', 'session')}
                    self._wire.write(dict(terminal, op='stop'), self._require_original)
                except Exception:
                    # Parent may already have disconnected; Android independently
                    # observes loss of the control connection/data socket.
                    pass

    def _cleanup(self, action):
        try:
            action()
        except Exception as error:
            self.cleanup_error = error

    def stop(self):
        with self._lock:
            self._stop.set()
            self._control.close()
            if self._listener is not None:
                self._cleanup(self._listener.close)
            if self._receiver is not None:
                self._cleanup(self._receiver.stop)

    def is_drained(self):
        with self._lock:
            return bool(self._stop.is_set() and not self._thread.is_alive() and self.cleanup_error is None and
                        (self._receiver is None or self._receiver.is_drained()))

    @property
    def retired(self):
        return self._stop.is_set()


class PhoneScreenDesktopDispatch:
    """Private volatile dispatch on the original PhoneService, not a GUI command."""

    def __init__(self, service):
        self._service = service
        self._lock = threading.Lock()
        self._probes = weakref.WeakKeyDictionary()
        self._acks = weakref.WeakKeyDictionary()
        self._owner = None

    def _guard(self, peer, channel):
        service = self._service
        store, generation, caps = service.store, service._generation, channel.last_capabilities
        peer_id, key = peer['device_id'], peer['static_public']
        channel_ref = weakref.ref(channel)

        def require():
            channel = channel_ref()
            live = next((p for p in store.peers if p.get('device_id') == peer_id), None)
            status = (caps or {}).get('items', {}).get('device_status', {})
            if (channel is None or service.store is not store or service._generation != generation or not service.enabled or
                    service.stop_event.is_set() or service.connections.get(peer_id) is not channel or
                    service.connection_transports.get(peer_id) != 'wifi' or channel.sock.fileno() < 0 or
                    channel.last_capabilities is not caps or not live or live.get('state') != 'paired' or
                    live.get('static_public') != key or status.get('available') is not True or VERSION not in status.get('versions', ())):
                raise PermissionError('screen_original_wlan_parent_retired')
        return require

    def receive(self, peer, channel, message):
        from magnolie_telefon import now_ms
        status, error = 'rejected', 'not_granted'
        try:
            body = validate_message(message)
            if message['kind'] != REQUEST:
                raise ValueError('screen_original_phone_request_required')
            if body['op'] == 'probe':
                require = self._guard(peer, channel)
                require()
                deadline = time.monotonic() + (message['expires_ms'] - now_ms()) / 1000
                with self._lock:
                    history = self._probes.setdefault(channel, deque(maxlen=16))
                    if any(item[0]['request_id'] == body['request_id'] or item[0]['nonce'] == body['nonce'] for item in history):
                        raise PermissionError('screen_probe_already_seen')
                    history.append([body.copy(), deadline, require, False, peer['device_id']])
                status, error = 'accepted', 'none'
            else:
                with self._lock:
                    own = self._owner
                if own is not None and own[0] is channel and own[2] is not None and own[2].receive(channel, message):
                    status, error = 'accepted', 'none'
        except ValueError:
            error = 'invalid_schema'
        except (PermissionError, OSError):
            pass
        channel.send(dict(type='ack', message_id=message['message_id'], status=status, error=error))

    def _candidate(self, peer_id):
        channel = self._service.connections.get(peer_id)
        history = self._probes.get(channel, ()) if channel is not None else ()
        latest = history[-1] if history else None
        if latest is None or latest[3] or latest[4] != peer_id or time.monotonic() >= latest[1]:
            raise PermissionError('screen_original_probe_required')
        latest[2]()
        return channel, latest

    def available(self, peer_id):
        with self._lock:
            try:
                if self._owner is not None and (self._owner[2] is None or not self._owner[2].is_drained()):
                    return False
                self._candidate(peer_id)
                return True
            except PermissionError:
                return False

    def candidate(self, peer_id):
        """Opaque in-process witness for the native confirmation dialog."""
        with self._lock:
            channel, probe = self._candidate(peer_id)
            return channel, probe

    def begin(self, peer_id, width, height, density, native_start, *, expected=None):
        with self._lock:
            if self._owner is not None and (self._owner[2] is None or not self._owner[2].is_drained()):
                raise PermissionError('screen_original_view_busy')
            channel, probe = self._candidate(peer_id)
            if expected is not None and (channel is not expected[0] or probe is not expected[1]):
                raise PermissionError('screen_original_probe_changed')
            probe[3] = True
            token = object()
            slot = [channel, token, None, False]
            self._owner = slot

        def track(id_):
            with self._lock:
                self._acks.setdefault(channel, deque(maxlen=16)).append((id_, token))

        try:
            owner = native_start(channel, probe[0], width, height, density, require_original=probe[2], track=track, deadline=probe[1])
        except Exception:
            with self._lock:
                if self._owner is slot:
                    self._owner = None
            raise
        with self._lock:
            slot[2] = owner
            retired = slot[3]
        try:
            probe[2]()
            if retired:
                raise PermissionError('screen_original_view_retired')
        except PermissionError:
            owner.stop()
            raise
        return owner

    def ack(self, channel, message):
        with self._lock:
            token = next((item[1] for item in self._acks.get(channel, ()) if item[0] == message['message_id']), None)
            slot = self._owner
            if token is not None and slot is not None and slot[1] is token and message['status'] == 'rejected':
                slot[3] = True
                owner = slot[2]
            else:
                owner = None
        if token is None:
            return False
        if owner is not None:
            owner.stop()
        return True

    def retire(self, channel=None):
        with self._lock:
            if channel is None:
                self._probes.clear()
            else:
                self._probes.pop(channel, None)
            slot = self._owner
            if slot is None or channel is not None and slot[0] is not channel:
                return
            slot[3] = True
            owner = slot[2]
        if owner is not None:
            owner.stop()
