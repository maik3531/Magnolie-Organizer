"""Private draft desktop-to-phone lane. No capability, listener or dispatcher."""

from contextlib import contextmanager
from hashlib import sha256
from hmac import compare_digest, digest
from math import isfinite
import secrets
import socket
from struct import Struct, pack, unpack_from
from threading import Event, Lock
from time import monotonic

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from magnolie_desktop_screen_encode import DesktopScreenJpeg, MAX_JPEG_BYTES


_DOMAIN = b'magnolie-desktop-screen-send/1\0desktop_to_phone\0'
_PROOF = b'magnolie-desktop-screen-proof/1\0'
_HEADER = Struct('!IQ')
_LIMIT = 2**63 - 1


def _require_jpeg(data, size):
    # Local encoder only. Check the baseline shape without decoding another
    # image here; the receiving viewer still validates independently.
    if not 14 <= len(data) <= MAX_JPEG_BYTES or not (data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9')):
        raise ValueError('desktop_screen_jpeg_envelope')
    at, baseline, end = 2, False, len(data) - 2
    while at + 4 <= end and data[at] == 0xff:
        marker = data[at + 1]
        length, = unpack_from('!H', data, at + 2)
        following = at + 2 + length
        if length < 2 or following > end:
            break
        if marker == 0xc0:
            if (baseline or length != 17 or data[at + 4] != 8 or data[at + 9] != 3 or
                    unpack_from('!HH', data, at + 5) != size[::-1]):
                break
            baseline = True
        elif marker == 0xda:
            if baseline and length == 12 and data[at + 4] == 3 and following < end:
                return
            break
        elif marker not in (0xc4, 0xdb, 0xdd, 0xfe) and not 0xe0 <= marker <= 0xef:
            break
        at = following
    raise ValueError('desktop_screen_jpeg_header')


class DesktopScreenSendLane:
    """Owns one accepted data socket and serializes proof, SEND and records.

    The trusted native caller must check the original authenticated parent,
    peer/address and consent in require_original, and supply PREPARED only from
    that control channel. Call publish_send with the supplied live guard at its
    actual bounded control writer; return only after that write completes.
    None of these callbacks may be supplied by a browser or media peer.
    """

    def __init__(self, sock, session, secret, mode, width, height, setup_deadline, require_original):
        self._sock = sock
        self._stop = Event()
        self._worker = Lock()
        self._retirement = Lock()
        self._socket_closed = False
        self._transcript = self._cipher = self._prefix = None
        self._sending = False
        self._ordinal = 0
        self._last_frame = -1
        self._require_original = require_original
        self._deadline = setup_deadline
        try:
            if (type(session) is not bytes or len(session) != 16 or
                    type(secret) is not bytes or len(secret) != 32 or type(mode) is not int or mode not in (1, 2) or
                    type(width) is not int or type(height) is not int or
                    not 16 <= width <= 1920 or not 16 <= height <= 1920 or width * height > 1920 * 1080 or
                    type(setup_deadline) not in (float, int) or not isfinite(setup_deadline)):
                raise ValueError('desktop_screen_original_offer_invalid')
            self._size = width, height
            self._context = _DOMAIN + session + pack('!BHH', mode, width, height)
            self._session, self._secret = session, secret
            self._current(self._deadline)
            sock.settimeout(.05)
        except BaseException:
            self.stop()
            raise

    def _current(self, deadline):
        if self._stop.is_set():
            raise PermissionError('desktop_screen_lane_retired')
        self._require_original()
        if self._stop.is_set():
            raise PermissionError('desktop_screen_lane_retired')
        if monotonic() >= deadline:
            raise TimeoutError('desktop_screen_lane_timeout')

    @contextmanager
    def _owned(self):
        with self._retirement:
            if self._stop.is_set():
                raise PermissionError('desktop_screen_lane_retired')
            if not self._worker.acquire(blocking=False):
                raise RuntimeError('desktop_screen_lane_busy')
        try:
            yield
        except BaseException:
            self.stop()
            raise
        finally:
            with self._retirement:
                if self._stop.is_set():
                    self._discard()
                self._worker.release()

    def _transfer(self, data, operation, deadline):
        remaining = memoryview(data)
        while remaining:
            self._current(deadline)
            try:
                count = operation(remaining)
            except socket.timeout:
                continue
            if not count:
                raise EOFError('desktop_screen_data_socket_ended')
            remaining = remaining[count:]
        self._current(deadline)

    def prove(self):
        with self._owned():
            if self._transcript is not None:
                raise RuntimeError('desktop_screen_proof_already_attempted')
            deadline = min(self._deadline, monotonic() + 2)
            self._current(deadline)
            phone = bytearray(16)
            self._transfer(phone, self._sock.recv_into, deadline)
            desktop = secrets.token_bytes(16)
            transcript = self._context + phone + desktop
            secret = self._secret
            self._transfer(desktop + digest(secret, _PROOF + b'\x01' + transcript, 'sha256'), self._sock.send, deadline)
            answer = bytearray(32)
            self._transfer(answer, self._sock.recv_into, deadline)
            if not compare_digest(answer, digest(secret, _PROOF + b'\x02' + transcript, 'sha256')):
                raise PermissionError('desktop_screen_phone_proof_invalid')
            material = HKDF(algorithm=hashes.SHA256(), length=36, salt=self._session, info=self._context).derive(secret)
            self._cipher, self._prefix = AESGCM(material[:32]), material[32:]
            self._secret = None
            self._current(deadline)
            self._transcript = sha256(transcript).digest()
            return self._transcript

    def authorize_send(self, prepared, require_local_jpeg, publish_send):
        with self._owned():
            deadline = min(self._deadline, monotonic() + 2)

            def current():
                self._current(deadline)
                if require_local_jpeg() is not True:
                    raise PermissionError('desktop_screen_local_jpeg_not_ready')
                self._current(deadline)

            if (self._sending or self._transcript is None or type(prepared) is not bytes or
                    not compare_digest(prepared, self._transcript)):
                raise PermissionError('desktop_screen_original_prepared_required')
            current()
            if publish_send(current) is not True:
                raise PermissionError('desktop_screen_send_not_published')
            current()
            self._sending = True

    def write_record(self, frame):
        """Write an encoder result or None for a caller-scheduled heartbeat."""
        with self._owned():
            deadline = monotonic() + 2
            self._current(deadline)
            if not self._sending or self._ordinal >= _LIMIT:
                raise PermissionError('desktop_screen_live_send_required')
            data = b''
            if frame is not None:
                if (type(frame) is not DesktopScreenJpeg or type(frame.sequence) is not int or
                        not self._last_frame < frame.sequence < _LIMIT or type(frame.data) is not bytes):
                    raise ValueError('desktop_screen_original_frame_required')
                data = frame.data
                _require_jpeg(data, self._size)
            header = _HEADER.pack(len(data) + 16, self._ordinal)
            cipher = self._cipher.encrypt(self._prefix + header[4:], data, self._context + header)
            self._transfer(header, self._sock.send, deadline)
            self._transfer(cipher, self._sock.send, deadline)
            self._ordinal += 1
            if frame is not None:
                self._last_frame = frame.sequence

    def _discard(self):
        self._cipher = self._prefix = self._secret = self._transcript = None

    def stop(self):
        with self._retirement:
            if self._stop.is_set():
                return
            self._stop.set()
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
                self._socket_closed = True
            except OSError:
                pass  # Never retry a close with uncertain descriptor ownership.
            if self._worker.acquire(blocking=False):
                try:
                    self._discard()
                finally:
                    self._worker.release()

    @property
    def drained(self):
        # Socket close alone cannot certify a proof/control-write/record drain.
        with self._retirement:
            return self._socket_closed and not self._worker.locked()
