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
                if ordinal != self._ordinal or ordinal >= 2**63 - 1 or not 17 <= length <= _MAX_BYTES + 16:
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
