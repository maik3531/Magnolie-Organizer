"""Actual socket/AEAD tests. No phone permission, personal capture or native OBS test."""
from pathlib import Path
import socket
import hashlib
import sys
import threading

from cryptography.exceptions import InvalidTag
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_phone_camera_transport as transport
from magnolie_phone_webcam import AUDIO_BYTES, VIDEO_BYTES, WebcamUnavailable


def pair():
    left, right = socket.socketpair()
    return (transport.WebcamMediaSocket(left, 'a' * 32, bytes(range(32)), lambda: None, sending=True),
            transport.WebcamMediaSocket(right, 'a' * 32, bytes(range(32)), lambda: None, sending=False))


def wire(sender, stream='audio', pts=0):
    data = b'\x12\x34' * (AUDIO_BYTES // 2)
    plain = sender._packet(stream, 0, pts, data)
    header = transport.HEADER.pack(len(plain) + 16, sender.sequence)
    return header + sender.cipher.encrypt(sender.prefix + sender.sequence.to_bytes(8, 'big'), plain, sender.aad + header)


def test_actual_binary_socket_round_trip_video_and_audio_without_document_json():
    sender, receiver = pair()
    packets = [('video', 0, 0, bytes(VIDEO_BYTES)), ('audio', 0, 0, b'\x12\x34' * (AUDIO_BYTES // 2)),
               ('audio', 1, 20000, b'\x56\x78' * (AUDIO_BYTES // 2))]
    errors = []
    def send():
        try:
            for packet in packets: sender.send(*packet)
        except BaseException as error: errors.append(error)
    thread = threading.Thread(target=send)
    try:
        thread.start()
        assert [receiver.receive() for _ in packets] == packets
        thread.join(timeout=3)
        assert not thread.is_alive() and not errors and sender.sequence == receiver.sequence == 3
    finally:
        sender.close(); receiver.close(); thread.join(timeout=3)


def test_wire_matches_android_codec_shared_audio_then_video_vectors():
    sender, receiver = pair()
    try:
        audio = wire(sender)
        assert hashlib.sha256(audio).hexdigest() == 'ac07c1baeaea58c00f70d794813f653e1409f865dc7363ecba9703612d0707e0'
        sender.sequence = 1
        plain = sender._packet('video', 0, 66667, bytes(VIDEO_BYTES))
        header = transport.HEADER.pack(len(plain) + 16, 1)
        video = header + sender.cipher.encrypt(sender.prefix + (1).to_bytes(8, 'big'), plain, sender.aad + header)
        assert hashlib.sha256(video).hexdigest() == '8b253d9e1bf3129a3b7e3a1caa5aac9316cf9dc8a7348a71aca8e9c3f8ccaee3'
    finally: sender.close(); receiver.close()


@pytest.mark.parametrize('scenario', ['secret', 'session', 'ciphertext', 'header'])
def test_aead_binds_actual_original_secret_session_direction_and_header(scenario):
    sender, receiver = pair()
    try:
        packet = bytearray(wire(sender))
        if scenario == 'secret':
            other, unused = socket.socketpair()
            foreign = transport.WebcamMediaSocket(other, 'a' * 32, b'x' * 32, lambda: None, sending=True)
            packet = wire(foreign); foreign.close(); unused.close()
        if scenario == 'session':
            other, unused = socket.socketpair()
            foreign = transport.WebcamMediaSocket(other, 'b' * 32, bytes(range(32)), lambda: None, sending=True)
            packet = wire(foreign); foreign.close(); unused.close()
        if scenario == 'ciphertext': packet[-1] ^= 1
        if scenario == 'header': packet[11] ^= 1
        sender.sock.sendall(packet)
        with pytest.raises((InvalidTag, WebcamUnavailable)):
            receiver.receive()
        assert receiver.closed
    finally:
        sender.close(); receiver.close()


def test_replay_retires_channel_without_reconstructing_session():
    sender, receiver = pair()
    try:
        packet = wire(sender)
        sender.sock.sendall(packet)
        assert receiver.receive()[:3] == ('audio', 0, 0)
        sender.sock.sendall(packet)
        with pytest.raises(WebcamUnavailable, match='envelope_invalid'): receiver.receive()
        with pytest.raises(WebcamUnavailable, match='retired'): receiver.receive()
    finally:
        sender.close(); receiver.close()


@pytest.mark.parametrize('length', [0, 17, transport.MAX_CIPHER + 1, 2**32 - 1])
def test_oversized_length_is_refused_before_reading_or_allocating_payload(length):
    sender, receiver = pair()
    try:
        sender.sock.sendall(transport.HEADER.pack(length, 0))
        with pytest.raises(WebcamUnavailable, match='envelope_invalid'): receiver.receive()
        assert receiver.closed
    finally:
        sender.close(); receiver.close()


def test_partial_frame_eof_retires_both_sides():
    sender, receiver = pair()
    sender.sock.sendall(wire(sender)[:-10]); sender.close()
    try:
        with pytest.raises(WebcamUnavailable, match='eof'): receiver.receive()
        assert receiver.closed
    finally: receiver.close()


def test_live_guard_is_rechecked_during_a_stalled_frame_and_denial_is_sticky():
    sender, receiver = pair()
    allowed = [True]
    entered = threading.Event(); failures = []
    def guard():
        entered.set()
        if not allowed[0]: raise PermissionError('original context revoked')
    receiver.guard = guard
    def read():
        try: receiver.receive()
        except BaseException as error: failures.append(error)
    thread = threading.Thread(target=read)
    try:
        thread.start(); assert entered.wait(timeout=1)
        allowed[0] = False
        thread.join(timeout=1)
        assert not thread.is_alive() and isinstance(failures[0], PermissionError) and receiver.closed
        allowed[0] = True
        with pytest.raises(WebcamUnavailable, match='retired'): receiver.receive()
    finally:
        sender.close(); receiver.close(); thread.join(timeout=3)


def test_receiver_cannot_be_used_to_send_and_sender_cannot_receive():
    sender, receiver = pair()
    try:
        with pytest.raises(WebcamUnavailable, match='direction'): sender.receive()
        with pytest.raises(WebcamUnavailable, match='direction'): receiver.send('audio', 0, 0, bytes(AUDIO_BYTES))
        assert sender.closed and receiver.closed
    finally: sender.close(); receiver.close()
