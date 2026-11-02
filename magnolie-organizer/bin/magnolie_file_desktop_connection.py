"""Native desktop file-control owner; no automatic transfer or scheduler.

The receive data/UI/recovery union is not ready: every outgoing data grant stays
OFF, including when a protected enabled preference exists. Construction itself
does not send packets, create preferences or start any worker.
"""
from contextlib import contextmanager
import threading
import uuid

from magnolie_file_control import KIND, MAX_TTL_MS, FileControlPacket, NativeFileControlSession
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_file_sources import _body
from magnolie_file_transfer import TransferError
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_destination import NativePhotoDestinationController
from magnolie_telefon import now_ms


def is_reserved_file_message(message):
    return isinstance(message, dict) and isinstance(message.get('kind'), str) and message['kind'].startswith('file_transfer.')


class NativeDesktopFileConnection:
    def __init__(self, authority, channel):
        if (type(authority) is not NativeDesktopFileAuthority or channel is not authority.native_channel
                or not callable(getattr(channel, 'send', None))):
            raise TransferError('file_desktop_native_owner_required')
        self._authority = authority
        self._channel = channel
        self._closed = threading.Event()
        self._gate = threading.Lock()
        self._controls = None
        self._preferences = ProtectedPhotoPreferences(authority)
        self._destination = NativePhotoDestinationController(authority)
        try:
            self._controls = NativeFileControlSession(authority.identity, self._peer, self._local)
        except BaseException:
            self.close()
            raise

    def _ready(self):
        if self._closed.is_set():
            raise TransferError('file_desktop_connection_closed')

    def _peer(self):
        self._ready()
        peer = self._authority.current_peer()
        self._ready()
        return peer.control_peer(self, ready=True, handlers_ready=True) if peer is not None else None

    def _local(self):
        self._ready()
        # Do not claim receiver readiness from preferences or control codecs.
        return self._preferences.local_grant(False)

    @contextmanager
    def _operation(self):
        if not self._gate.acquire(blocking=False):
            raise TransferError('file_desktop_connection_busy')
        try:
            self._ready()
            yield
        finally:
            self._gate.release()
            if self._closed.is_set():
                self._close_resources()

    def _send_controls(self, clock):
        if not self._controls.needs_packet:
            return False
        packet = self._controls.packet()
        at = clock()
        message = dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=KIND,
                       created_ms=at, expires_ms=at+MAX_TTL_MS, body=packet.wire())
        _body(message, KIND, clock())
        self._ready()
        if self._peer() is None:
            raise TransferError('file_desktop_native_authority_changed')
        _body(message, KIND, clock())
        self._channel.send(message)  # Actual secure output, not queue acceptance.
        self._ready()
        _body(message, KIND, clock())
        self._controls.mark_sent(packet)
        return True

    def send_controls(self, *, clock=now_ms):
        with self._operation():
            return self._send_controls(clock)

    def receive(self, message, *, clock=now_ms):
        with self._operation():
            # Unsupported/reserved data never falls through to personal staging.
            body = _body(message, KIND, clock())
            packet = FileControlPacket.parse(body)
            self._controls.observe_remote(packet, self._peer())
            self._send_controls(clock)

    def read_preferences(self):
        with self._operation():
            return self._preferences.read()

    def close(self):
        self._closed.set()
        self._authority.revoke()  # Nonwaiting even during blocked native/socket I/O.
        return self._close_resources()

    def _close_resources(self):
        if not self._gate.acquire(blocking=False):
            return False
        try:
            self._destination.close()
            self._preferences.close()
            if self._controls is not None:
                self._controls.close()
            self._authority.close()
            return True
        finally:
            self._gate.release()
