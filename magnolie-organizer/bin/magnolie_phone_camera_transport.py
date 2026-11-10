"""Dedicated bounded, encrypted binary AV channel (not the document channel).

The caller must first bind a NEW random secret/session to the original paired
control channel AND genuine current Android capture consent. This module creates
no listener and grants no permission. Reconnect needs a new session and secret.
"""
import re
import socket
import struct
import threading
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from magnolie_phone_webcam import AUDIO_BYTES, VIDEO_BYTES, WebcamUnavailable


PROTOCOL = b'magnolie-phone-webcam/1\0phone_to_desktop\0'
HEADER = struct.Struct('!IQ')  # Ciphertext length, global authenticated sequence.
PACKET = struct.Struct('!BBQQ')  # Version, track, per-track sequence, PTS microseconds.
MAX_CIPHER = PACKET.size + VIDEO_BYTES + 16


class WebcamMediaSocket:
    """One-way channel; no retry/restart/reuse after EOF, timeout or rejection."""
    def __init__(self, sock, session, secret, guard, *, sending):
        if (type(session) is not str or not re.fullmatch('[0-9a-f]{32}', session) or
                type(secret) is not bytes or len(secret) != 32 or
                not callable(guard) or type(sending) is not bool):
            raise ValueError('invalid webcam channel context')
        material = HKDF(algorithm=hashes.SHA256(), length=36,
            salt=bytes.fromhex(session), info=PROTOCOL).derive(secret)
        self.cipher, self.prefix = AESGCM(material[:32]), material[32:]
        self.aad = PROTOCOL + bytes.fromhex(session)
        self.sock, self.guard, self.sending = sock, guard, sending
        self.sequence = 0
        self.closed = False
        self.lock = threading.Lock()
        try:
            guard()
            sock.settimeout(.1)
        except BaseException:
            self.close()
            raise

    def _current(self, deadline):
        if self.closed:
            raise WebcamUnavailable('webcam_media_channel_retired')
        self.guard()
        if time.monotonic() >= deadline:
            raise WebcamUnavailable('webcam_media_channel_timeout')

    def _read(self, length, deadline):
        data = bytearray(length)
        view = memoryview(data)
        at = 0
        while at < length:
            self._current(deadline)
            try:
                count = self.sock.recv_into(view[at:], length - at)
            except socket.timeout:
                continue
            if count == 0:
                raise WebcamUnavailable('webcam_media_channel_eof')
            at += count
        self._current(deadline)
        return bytes(data)

    @staticmethod
    def _packet(stream, sequence, pts_us, data):
        if (stream not in ('video', 'audio') or type(sequence) is not int or not 0 <= sequence < 2**63 or
                type(pts_us) is not int or not 0 <= pts_us <= 9_007_199_254_740_991 or
                type(data) is not bytes or len(data) != (VIDEO_BYTES if stream == 'video' else AUDIO_BYTES)):
            raise WebcamUnavailable('webcam_packet_invalid')
        return PACKET.pack(1, 1 if stream == 'video' else 2, sequence, pts_us) + data

    def send(self, stream, sequence, pts_us, data):
        with self.lock:
            try:
                if not self.sending or self.sequence >= 2**63 - 1:
                    raise WebcamUnavailable('webcam_media_direction_invalid')
                deadline = time.monotonic() + 2
                self._current(deadline)
                plain = self._packet(stream, sequence, pts_us, data)
                header = HEADER.pack(len(plain) + 16, self.sequence)
                encrypted = self.cipher.encrypt(self.prefix + self.sequence.to_bytes(8, 'big'), plain, self.aad + header)
                packet = memoryview(header + encrypted)
                while packet:
                    self._current(deadline)
                    try:
                        count = self.sock.send(packet)
                    except socket.timeout:
                        continue
                    if count == 0:
                        raise WebcamUnavailable('webcam_media_channel_eof')
                    packet = packet[count:]
                self._current(deadline)
                self.sequence += 1
            except BaseException:
                self.close()
                raise

    def receive(self):
        with self.lock:
            try:
                if self.sending or self.sequence >= 2**63 - 1:
                    raise WebcamUnavailable('webcam_media_direction_invalid')
                deadline = time.monotonic() + 2
                self._current(deadline)
                header = self._read(HEADER.size, deadline)
                length, sequence = HEADER.unpack(header)
                # Reject BEFORE allocating/reading the declared ciphertext.
                if sequence != self.sequence or not PACKET.size + 16 <= length <= MAX_CIPHER:
                    raise WebcamUnavailable('webcam_media_envelope_invalid')
                encrypted = self._read(length, deadline)
                plain = self.cipher.decrypt(self.prefix + sequence.to_bytes(8, 'big'), encrypted, self.aad + header)
                version, track, packet_sequence, pts = PACKET.unpack_from(plain)
                if version != 1 or track not in (1, 2):
                    raise WebcamUnavailable('webcam_packet_invalid')
                stream, data = ('video' if track == 1 else 'audio'), plain[PACKET.size:]
                self._packet(stream, packet_sequence, pts, data)
                self._current(deadline)
                self.sequence += 1
                return stream, packet_sequence, pts, data
            except BaseException:
                self.close()
                raise

    def close(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
