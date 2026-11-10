"""Bounded original SecureChannel writes, including ordinary-frame regression."""
from pathlib import Path
import socket
import sys
import threading
import time

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone


@pytest.fixture
def link():
    left, right = socket.socketpair()
    left.settimeout(.1); right.settimeout(.1)
    channel = phone.SecureChannel(left, b's' * 16, b'k' * 32, b'p' * 4, b'r' * 32, b'q' * 4)
    try: yield channel, right
    finally: left.close(); right.close()


def receive(channel, peer):
    frame = phone.receive_frame(peer, phone.SECURE_FRAME_MAX)
    aad = {key: value for key, value in frame.items() if key != 'ciphertext'}
    plain = AESGCM(b'k' * 32).decrypt(b'p' * 4 + frame['seq'].to_bytes(8, 'big'),
        phone.base64.b64decode(frame['ciphertext'], validate=True), phone.canonical(aad))
    return phone.strict_json(plain)


def test_actual_ephemeral_and_normal_writes_share_original_crypto_sequence_without_timeout_changes(link):
    channel, peer = link
    value = dict(type='message', kind='capabilities.update', body={'items': {}})
    checks = []
    channel.send_ephemeral(value, lambda: checks.append(True))
    assert receive(channel, peer) == value and channel.send_seq == 1 and len(checks) >= 2
    assert channel.sock.gettimeout() == .1
    value['body']['items']['later_mutation'] = True
    assert channel.last_capabilities == {'items': {}}
    channel.send({'type': 'pong'})
    assert receive(channel, peer) == {'type': 'pong'} and channel.send_seq == 2


def test_busy_original_writer_has_a_deadline_and_does_not_publish_or_close_parent(link):
    channel, peer = link
    channel.lock.acquire()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match='writer_busy'):
            channel.send_ephemeral({'type': 'probe'}, lambda: None, timeout=.03)
    finally: channel.lock.release()
    assert time.monotonic() - started < .5 and channel.send_seq == 0 and channel.sock.fileno() >= 0
    with pytest.raises(socket.timeout): peer.recv(1)


def test_original_owner_is_rechecked_after_waiting_for_the_writer_lock(link):
    channel, peer = link
    entered = threading.Event()
    live, errors = [True], []
    def guard():
        entered.set()
        if not live[0]: raise PermissionError('original activation revoked')
    def send():
        try: channel.send_ephemeral({'type': 'probe'}, guard)
        except Exception as error: errors.append(error)
    channel.lock.acquire()
    worker = threading.Thread(target=send)
    try:
        worker.start(); assert entered.wait(1)
        live[0] = False
    finally: channel.lock.release(); worker.join(3)
    assert not worker.is_alive() and len(errors) == 1 and isinstance(errors[0], PermissionError)
    assert channel.send_seq == 0 and channel.sock.fileno() >= 0
    with pytest.raises(socket.timeout): peer.recv(1)


def test_unbounded_parent_socket_is_refused_without_mutating_receive_timeout(link):
    channel, peer = link
    channel.sock.settimeout(None)
    with pytest.raises(TimeoutError, match='write_not_bounded'):
        channel.send_ephemeral({'type': 'probe'}, lambda: None)
    assert channel.sock.gettimeout() is None and channel.send_seq == 0
    with pytest.raises(socket.timeout): peer.recv(1)


def test_revocation_after_encryption_but_before_publication_consumes_no_nonce_or_parent(link):
    channel, peer = link
    checks = [0]
    def guard():
        checks[0] += 1
        if checks[0] == 3: raise PermissionError('original context changed before publication')
    with pytest.raises(PermissionError, match='before publication'):
        channel.send_ephemeral({'type': 'probe'}, guard)
    assert channel.send_seq == 0 and channel.sock.fileno() >= 0
    with pytest.raises(socket.timeout): peer.recv(1)


def test_failed_actual_frame_write_retires_only_its_original_uncertain_ciphertext_socket(link):
    channel, peer = link
    peer.close()
    with pytest.raises(OSError): channel.send_ephemeral({'type': 'probe'}, lambda: None)
    assert channel.send_seq == 1 and channel.sock.fileno() == -1


@pytest.mark.parametrize('timeout', [True, 0, 3, float('nan')])
def test_invalid_private_deadlines_are_not_native_write_authority(link, timeout):
    channel, peer = link
    with pytest.raises(ValueError): channel.send_ephemeral({'type': 'probe'}, lambda: None, timeout=timeout)
    assert channel.send_seq == 0
