"""Read-only wire endpoint for the original #245 phone-view lane."""

import hmac
import secrets
import socket
import struct
import threading
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


_DOMAIN = b"magnolie-phone-screen-view/1\x00phone_to_desktop\x00"
_PROOF_DOMAIN = b"magnolie-phone-screen-proof/1\x00"
_HEADER = struct.Struct("!IQ")
_MAX_BYTES = 1_048_576


def _context(session, secret, width, height):
    if (type(session) is not bytes or len(session) != 16 or type(secret) is not bytes or len(secret) != 32 or
            type(width) is not int or type(height) is not int or not 2 <= width <= 1920 or
            not 2 <= height <= 1920 or width * height > 1920 * 1080):
        raise ValueError("screen_lane_original_context_required")
    return _DOMAIN + session + struct.pack("!HH", width, height)


class PhoneScreenWlanListener:
    """Single provisional accept on the original authenticated TCP interface.

    The native caller must first check explicit desktop opt-in and WLAN. The
    address check is not authentication; the accepted socket still needs proof.
    """

    def __init__(self, channel, require_original):
        from magnolie_telefon import SecureChannel
        if type(channel) is not SecureChannel or type(channel.sock) is not socket.socket or channel.sock.family not in (socket.AF_INET, socket.AF_INET6):
            raise TypeError("screen_listener_original_tcp_required")
        self._channel = channel
        self._parent = channel.sock
        self._local, self._peer = self._parent.getsockname(), self._parent.getpeername()
        self._guard = require_original
        self._lock = threading.Lock()
        self._used = False
        self._closed = threading.Event()
        self._current()
        listener = socket.socket(self._parent.family, socket.SOCK_STREAM)
        try:
            if listener.family == socket.AF_INET6:
                listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            listener.bind((self._local[0], 0, 0, self._local[3]) if listener.family == socket.AF_INET6 else (self._local[0], 0))
            listener.listen(1)
            listener.settimeout(.1)
            self._address = listener.getsockname()
            self._current()
        except BaseException:
            listener.close()
            raise
        self._listener = listener
        self.port = self._address[1]

    def _current(self):
        self._guard()
        if (self._closed.is_set() or self._channel.sock is not self._parent or
                self._parent.getsockname() != self._local or self._parent.getpeername() != self._peer):
            raise PermissionError("screen_listener_original_socket_lost")

    def accept(self):
        with self._lock:
            if self._used or self._closed.is_set():
                raise PermissionError("screen_listener_already_used")
            self._used = True
        accepted = None
        try:
            end = time.monotonic() + 5
            while True:
                self._current()
                if time.monotonic() >= end:
                    raise TimeoutError("screen_listener_timeout")
                try:
                    accepted, peer = self._listener.accept()
                    break
                except socket.timeout:
                    continue
            if (accepted.family != self._parent.family or accepted.getsockname() != self._address or
                    peer[0] != self._peer[0] or (len(peer) == 4 and peer[3] != self._peer[3])):
                raise PermissionError("screen_listener_unrelated_address")
            self._current()
            result, accepted = accepted, None
            return result
        finally:
            if accepted is not None:
                accepted.close()
            self.close()

    def close(self):
        with self._lock:
            if not self._closed.is_set():
                self._closed.set()
                self._listener.close()


def prove_phone_screen_socket(sock, session, secret, width, height, require_original):
    """On failure close the exact accepted socket; on success no frame was read."""
    try:
        context = _context(session, secret, width, height)
        challenge = secrets.token_bytes(16)
        expected = hmac.digest(secret, _PROOF_DOMAIN + context + challenge, "sha256")
        end = time.monotonic() + 2
        sock.settimeout(.1)

        def current():
            require_original()
            if time.monotonic() >= end:
                raise TimeoutError("screen_socket_proof_timeout")

        def transfer(data, operation):
            pending = memoryview(data)
            while pending:
                current()
                try:
                    used = operation(pending)
                except socket.timeout:
                    continue
                if not used:
                    raise EOFError("screen_socket_proof_disconnected")
                pending = pending[used:]

        transfer(challenge, sock.send)
        reply = bytearray(32)
        transfer(reply, sock.recv_into)
        if not hmac.compare_digest(reply, expected):
            raise PermissionError("screen_socket_proof_invalid")
        current()
    except BaseException:
        sock.close()
        raise


class PhoneScreenViewLane:
    def __init__(self, sock, session, secret, width, height, require_original):
        self._sock = sock
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._ordinal = 0
        self._require_original = require_original
        try:
            self._context = _context(session, secret, width, height)
            material = HKDF(algorithm=hashes.SHA256(), length=36, salt=session, info=self._context).derive(secret)
            self._cipher, self._prefix = AESGCM(material[:32]), material[32:]
            self._require_original()
            sock.settimeout(.1)
        except BaseException:
            self.close()
            raise

    def _current(self, end):
        if self._closed.is_set():
            raise OSError("screen_lane_closed")
        self._require_original()
        if time.monotonic() >= end:
            raise TimeoutError("screen_lane_record_timeout")

    def _read(self, count, end):
        data = bytearray(count)
        pending = memoryview(data)
        while pending:
            self._current(end)
            try:
                used = self._sock.recv_into(pending)
            except socket.timeout:
                continue
            if not used:
                raise EOFError("screen_lane_disconnected")
            pending = pending[used:]
        self._current(end)
        return data

    def receive(self):
        with self._lock:
            try:
                end = time.monotonic() + 2
                header = bytes(self._read(_HEADER.size, end))
                length, ordinal = _HEADER.unpack(header)
                if ordinal != self._ordinal or ordinal >= 2**63 - 1 or not 16 <= length <= _MAX_BYTES + 16:
                    raise ValueError("screen_lane_envelope")
                cipher = bytes(self._read(length, end))
                data = self._cipher.decrypt(self._prefix + header[4:], cipher, self._context + header)
                self._current(end)
                self._ordinal += 1
                return data
            except BaseException:
                self.close()
                raise

    def close(self):
        if not self._closed.is_set():
            self._closed.set()
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()


class PhoneScreenReceiveRun:
    """One exact accepted socket -> proof -> authenticated SEND -> JPEG worker.

    The native control owner hands in the already selected socket and view.
    authorize_send publishes the one original protected SEND decision; it must
    return only after that decision is current on the original control socket.
    require_send independently checks that lease before frame IO/decoding.
    Neither a data socket nor construction is permission to start a session.
    """

    def __init__(self, sock, session, secret, width, height, *, require_original,
                 authorize_send, require_send, offer_rgb):
        self._socket = sock
        self._session = session
        self._secret = secret
        self._width = width
        self._height = height
        self._require_original = require_original
        self._authorize_send = authorize_send
        self._require_send = require_send
        self._offer_rgb = offer_rgb
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False
        self.failure = None
        self.cleanup_error = None
        self._worker = threading.Thread(target=self._run, name="magnolie-phone-screen-receive", daemon=True)

    def start(self):
        with self._lock:
            if self._started or self._stop.is_set():
                raise RuntimeError("screen_receiver_already_used")
            self._started = True
            try:
                self._worker.start()
            except Exception:
                self._stop.set()
                self._close_socket()
                self._secret = None
                raise

    def _current(self):
        if self._stop.is_set():
            raise OSError("screen_receiver_stopped")
        self._require_original()

    def _send_current(self):
        self._current()
        self._require_send()
        if self._stop.is_set():
            raise OSError("screen_receiver_stopped")
        return True

    def _run(self):
        lane = None
        try:
            from magnolie_phone_screen_window import PhoneScreenJpegReceiver
            decoder = PhoneScreenJpegReceiver(self._width, self._height,
                                              is_current=self._send_current, offer_rgb=self._offer_rgb)
            prove_phone_screen_socket(self._socket, self._session, self._secret,
                                     self._width, self._height, self._current)
            self._current()
            self._authorize_send()
            self._send_current()
            lane = PhoneScreenViewLane(self._socket, self._session, self._secret,
                                      self._width, self._height, self._send_current)
            self._secret = None
            while True:
                jpeg = lane.receive()
                if jpeg and decoder.receive(jpeg) is not True:
                    raise OSError("screen_receiver_view_retired")
        except Exception as error:
            if not self._stop.is_set():
                self.failure = error
        finally:
            self._secret = None
            with self._lock:
                if lane is not None and not self._stop.is_set():
                    try:
                        lane.close()
                    except OSError as error:
                        self.cleanup_error = error
                self._stop.set()
                self._close_socket()

    def _close_socket(self):
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError as error:
            self.cleanup_error = error

    def stop(self):
        with self._lock:
            self._stop.set()
            if not self._started:
                self._secret = None
            self._close_socket()

    def is_drained(self):
        with self._lock:
            return self._stop.is_set() and not self._worker.is_alive() and self.cleanup_error is None

    def join_worker(self):
        """Only the owning background controller joins; Stop is nonblocking."""
        self._worker.join()
