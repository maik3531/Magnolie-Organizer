"""Unregistered #245 draft controls. No product dispatch, persistence or I/O."""

import hmac
from math import isfinite
import re
import socket
from threading import Lock
from time import monotonic, time_ns


DRAFT = 'desktop-screen-control/1'
DRAFT_FRAME = 'desktop_screen_draft'
MAX_SETUP_MS = 30_000
_INT_MAX = 2**53 - 1  # Exact across all JSON transports.
_COMMON = {'draft', 'op', 'request', 'mode', 'setup_until_ms'}
_OPS = {
    'request': ('phone', ()),
    'offer': ('desktop', ('session', 'secret', 'port', 'width', 'height')),
    'prepared': ('phone', ('session', 'transcript')),
    'send': ('desktop', ('session', 'transcript')),
    'stop': (None, ('session',)),
}


def parse_control(body, sender):
    """Validate exact small typed fields after authenticated framing. No grants."""
    if type(body) is not dict or sender not in ('phone', 'desktop'):
        raise ValueError('desktop_screen_control_invalid')
    op = body.get('op')
    role, extras = _OPS.get(op, (None, ())) if type(op) is str else (None, ())
    if (type(op) is not str or op not in _OPS or role not in (None, sender) or body.keys() != _COMMON.union(extras) or
            type(body['draft']) is not str or body['draft'] != DRAFT or
            type(body['mode']) is not int or body['mode'] not in (1, 2) or
            type(body['setup_until_ms']) is not int or not 1 <= body['setup_until_ms'] <= _INT_MAX):
        raise ValueError('desktop_screen_control_invalid')
    for key, width in (('request', 32), ('session', 32), ('secret', 64), ('transcript', 64)):
        if key in body and (type(body[key]) is not str or re.fullmatch(f'[0-9a-f]{{{width}}}', body[key]) is None):
            raise ValueError('desktop_screen_control_invalid')
    if op == 'offer':
        port, width, height = (body[k] for k in ('port', 'width', 'height'))
        if (any(type(v) is not int for v in (port, width, height)) or not 1024 <= port <= 65535 or
                not 16 <= width <= 1920 or not 16 <= height <= 1920 or width * height > 1920 * 1080):
            raise ValueError('desktop_screen_control_invalid')
    return body.copy()


class DesktopScreenDraftChannel:
    """Unregistered desktop adapter for one already authenticated WLAN parent.

    The trusted caller selects that parent and supplies its live ownership and
    consent guard. Only its original reader may supply received packets.
    """

    def __init__(self, channel, require_original):
        from magnolie_telefon import SecureChannel
        if type(channel) is not SecureChannel or channel.sock.family not in (socket.AF_INET, socket.AF_INET6) or (
                channel.sock.type & socket.SOCK_STREAM) != socket.SOCK_STREAM:
            raise ValueError('desktop_screen_original_wlan_required')
        self._channel, self._socket = channel, channel.sock
        self._guard = require_original
        self.require_current()
        self._socket.getpeername()  # Reject an unconnected socket without opening anything.

    def require_current(self):
        self._guard()
        if self._channel.sock is not self._socket or self._socket.fileno() < 0:
            raise PermissionError('desktop_screen_original_wlan_retired')

    def body_from(self, actual, packet):
        if actual is not self._channel:
            return None
        self.require_current()
        if type(packet) is not dict or packet.keys() != {'type', 'body'} or packet['type'] != DRAFT_FRAME:
            raise ValueError('desktop_screen_draft_frame_invalid')
        return parse_control(packet['body'], 'phone')

    def write(self, body, at_write):
        packet = dict(type=DRAFT_FRAME, body=parse_control(body, 'desktop'))
        self._channel.send_ephemeral(packet, self.require_current, at_write=at_write)
        # The caller records the completed write separately from the subsequent
        # live consent check. Only a fully written offer can warrant STOP.
        return True

    def open_original_listener(self, guard):
        # Reuse only the address-bound native TCP primitive, not v26 control
        # or its proof. No address or interface can come from the phone.
        from magnolie_phone_screen_transport import PhoneScreenWlanListener
        return PhoneScreenWlanListener(self._channel, guard)


class DesktopScreenDraftControl:
    """One authenticated request from the selected peer. The caller owns the
    original WLAN identity, trusted UI, data socket and guarded control writer.

    Incoming control must come from the already authenticated reader; the
    caller owns a one-slot admission and must not reconstruct it from replay.
    """

    def __init__(self, parent, request, require_original, *, deadline, clock=monotonic, wall_ms=None):
        request = parse_control(request, 'phone')
        if parent is None or request['op'] != 'request' or not isfinite(deadline):
            raise ValueError('desktop_screen_draft_request_required')
        now = time_ns() // 1_000_000 if wall_ms is None else wall_ms()
        budget = request['setup_until_ms'] - now
        if not 0 < budget <= MAX_SETUP_MS:
            raise TimeoutError('desktop_screen_draft_setup_window')
        self._parent = parent
        self._guard = require_original
        self._clock = clock
        self._issued = clock()
        self._deadline = min(deadline, self._issued + budget / 1000)
        self._base = {k: request[k] for k in _COMMON if k != 'op'}
        self._lock = Lock()
        self._phase = 'requested'
        self._session = self._prepared = None
        self._offer_edge = False
        self._offer_written = self._terminal_used = False
        self._current()

    @property
    def setup_deadline(self):
        return self._deadline

    def _current(self):
        try:
            self._guard()
            with self._lock:
                self._check_locked()
        except Exception:
            self.close()
            raise

    def _check_locked(self):
        now = self._clock()
        if (self._phase == 'closed' or not self._issued <= now or
                (self._phase != 'sending' and now >= self._deadline)):
            self._phase = 'closed'
            self._prepared = None
            raise PermissionError('desktop_screen_draft_retired')

    def publish_offer(self, *, session, secret, port, width, height, write_original):
        # The trusted caller has already approved the exact requested mode and
        # created the listener; this component neither chooses nor opens it.
        self._current()
        body = parse_control(dict(self._base, op='offer', session=session, secret=secret,
                                  port=port, width=width, height=height), 'desktop')
        with self._lock:
            if self._phase != 'requested':
                raise PermissionError('desktop_screen_draft_offer_already_used')
            self._session = session
            self._phase = 'offering'

        def at_write():
            self._current()
            with self._lock:
                self._check_locked()
                if self._phase != 'offering':
                    raise PermissionError('desktop_screen_draft_offer_retired')
                self._offer_edge = True

        try:
            if write_original(body, at_write) is not True:
                raise PermissionError('desktop_screen_draft_offer_not_written')
            with self._lock:
                self._offer_written = self._offer_edge
            self._current()
            with self._lock:
                self._check_locked()
                if self._phase != 'offering' or not self._offer_edge:
                    raise PermissionError('desktop_screen_draft_offer_retired')
                self._phase = 'offered'
        except Exception:
            self.close()
            raise

    def receive(self, actual_parent, incoming):
        if actual_parent is not self._parent:
            return False
        body = parse_control(incoming, 'phone')
        if any(body[k] != value for k, value in self._base.items()):
            return False
        self._current()
        with self._lock:
            if not self._offer_edge or body.get('session') != self._session or self._phase == 'closed':
                return False
            if body['op'] == 'stop':
                self._phase = 'closed'
                self._prepared = None
                self._terminal_used = True  # Do not echo a remote STOP.
                return True
            if (body['op'] != 'prepared' or self._phase not in ('offering', 'offered') or
                    self._prepared is not None):
                return False
            self._prepared = bytes.fromhex(body['transcript'])
            return True

    def publish_send(self, transcript, require_proof_and_media, write_original):
        # Both local readiness and proof are rechecked at the original writer.
        self._current()
        with self._lock:
            if (type(transcript) is not bytes or len(transcript) != 32 or self._phase != 'offered' or
                    self._prepared is None or not hmac.compare_digest(transcript, self._prepared)):
                raise PermissionError('desktop_screen_draft_original_prepared_required')
            self._phase = 'publishing'
            body = dict(self._base, op='send', session=self._session, transcript=transcript.hex())
        wrote_guard = False

        def current():
            self._current()
            require_proof_and_media()
            with self._lock:
                self._check_locked()
                if self._phase != 'publishing':
                    raise PermissionError('desktop_screen_draft_send_retired')

        def at_write():
            nonlocal wrote_guard
            current()
            wrote_guard = True

        try:
            current()
            if write_original(body, at_write) is not True or not wrote_guard:
                raise PermissionError('desktop_screen_draft_send_not_written')
            current()
            with self._lock:
                self._check_locked()
                if self._phase != 'publishing':
                    raise PermissionError('desktop_screen_draft_send_retired')
                self._phase = 'sending'
                self._prepared = None
            return True
        except Exception:
            self.close()
            raise

    def require_current(self):
        """Guard for proof/data I/O bound by the same original controller."""
        self._current()

    def publish_stop(self, write_terminal):
        """After retirement, report only the fully written original OFFER.

        The nominated terminal writer checks parent identity, not live consent.
        Consume the one terminal write before any blocking I/O; never retry it.
        """
        with self._lock:
            if self._phase != 'closed' or not self._offer_written or self._terminal_used:
                return False
            self._terminal_used = True
            body = dict(self._base, op='stop', session=self._session)
        return write_terminal(body, lambda: None) is True

    def prepared_for(self, transcript):
        self._current()
        with self._lock:
            self._check_locked()
            if self._phase != 'offered' or self._prepared is None:
                return False
            if not hmac.compare_digest(self._prepared, transcript):
                raise PermissionError('desktop_screen_draft_original_prepared_required')
            return True

    def require_send(self):
        self._current()
        with self._lock:
            if self._phase != 'sending':
                raise PermissionError('desktop_screen_draft_send_required')

    def close(self):
        with self._lock:
            self._phase = 'closed'
            self._prepared = None
