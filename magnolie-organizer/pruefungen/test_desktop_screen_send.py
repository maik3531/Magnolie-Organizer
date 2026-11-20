"""Draft media lane against independent synthetic peers on TCP loopback."""

import base64
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import socket
import struct
import sys
from threading import Event, Thread
from time import monotonic, time_ns
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_send as send
from magnolie_desktop_screen_control import DRAFT_FRAME, DesktopScreenDraftChannel, DesktopScreenDraftControl, parse_control
from magnolie_desktop_screen_encode import DesktopScreenJpeg
from magnolie_telefon import PROTOCOL, SecureChannel, b64, canonical, receive_frame, send_frame, strict_json


SESSION, SECRET = bytes(range(16)), bytes(range(32, 64))
PHONE, DESKTOP = bytes(range(64, 80)), bytes(range(80, 96))
CONTEXT = b'magnolie-desktop-screen-send/1\0desktop_to_phone\0' + SESSION + b'\x02\x00\x39\x00\x21'
PREPARED = bytes.fromhex('ce58cdbe420a3f03e2a6ddadf0c3c064080472ad7826d59d692e67de9e5de863')
MATERIAL = bytes.fromhex('f2076c96174d23d200b45ec33273d4fe035e12da30dae7bd3f986b1f79a2976ee2fc6010')
HEARTBEAT = bytes.fromhex('000000100000000000000000bfb6de89f9e5ca0e92e7696a2a090be9')


def read_exact(sock, length):
    value = bytearray()
    while len(value) < length:
        part = sock.recv(length - len(value))
        if not part:
            raise EOFError
        value.extend(part)
    return bytes(value)


class TestDesktopScreenSend(unittest.TestCase):
    def open_lane(self, *, deadline=5, require_control=lambda: None):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            self.peer = socket.create_connection(listener.getsockname(), timeout=2)
            self.addCleanup(self.peer.close)
            original, _ = listener.accept()
        self.socket = original
        self.live = True

        def guard():
            if not self.live:
                raise PermissionError('controlled original owner gone')
            require_control()

        self.lane = send.DesktopScreenSendLane(original, SESSION, SECRET, 2, 57, 33, monotonic() + deadline, guard)
        self.addCleanup(self.lane.stop)

    def in_worker(self, run):
        result = []

        def execute():
            try:
                result.append(run())
            except Exception as error:
                result.append(error)

        thread = Thread(target=execute, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)

        def wait():
            thread.join(3)
            self.assertFalse(thread.is_alive(), 'original socket worker remained live')
            return result[0]

        return wait

    def prove(self, *, reflect=False, context=CONTEXT):
        with patch.object(send.secrets, 'token_bytes', return_value=DESKTOP):
            wait = self.in_worker(self.lane.prove)
            self.peer.sendall(PHONE[:4])
            self.peer.sendall(PHONE[4:])
            proof = read_exact(self.peer, 48)
            self.assertEqual(proof, DESKTOP + bytes.fromhex('ec75759e7d5860bbd671444a447c6c6a07eb3688aff15db1a5ec3f78fb934cac'))
            answer = proof[16:] if reflect else hmac.digest(
                SECRET, b'magnolie-desktop-screen-proof/1\0\x02' + context + PHONE + DESKTOP, hashlib.sha256)
            self.peer.sendall(answer)
            return wait()

    def no_data(self):
        prior = self.peer.gettimeout()
        try:
            self.peer.settimeout(.05)
            with self.assertRaises(socket.timeout):
                self.peer.recv(1)
        finally:
            self.peer.settimeout(prior)

    def test_independent_vector_and_real_jpeg_after_guarded_send(self):
        self.open_lane()
        self.assertEqual(self.prove(), PREPARED)
        self.no_data()

        def publish(guard):
            guard()
            self.no_data()
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                self.lane.write_record(None)
            return True

        self.lane.authorize_send(PREPARED, lambda: True, publish)
        self.lane.write_record(None)
        self.assertEqual(read_exact(self.peer, len(HEARTBEAT)), HEARTBEAT)
        output = BytesIO()
        with Image.new('RGB', (57, 33), (15, 142, 210)) as image:
            image.save(output, 'JPEG')
        jpeg = output.getvalue()
        self.lane.write_record(DesktopScreenJpeg(3, jpeg))
        header = read_exact(self.peer, 12)
        length, ordinal = struct.unpack('!IQ', header)
        self.assertEqual((length, ordinal), (len(jpeg) + 16, 1))
        encrypted = read_exact(self.peer, length)
        self.assertEqual(AESGCM(MATERIAL[:32]).decrypt(MATERIAL[32:] + header[4:], encrypted, CONTEXT + header), jpeg)
        with self.assertRaises(ValueError):
            self.lane.write_record(DesktopScreenJpeg(3, jpeg))
        self.assertTrue(self.lane.drained)

    def test_reflected_role_and_other_mode_or_session_are_terminal(self):
        for reflect, context in ((True, CONTEXT), (False, CONTEXT[:-5] + b'\x01' + CONTEXT[-4:]),
                                 (False, CONTEXT[:-21] + bytes(reversed(SESSION)) + CONTEXT[-5:]),
                                 (False, CONTEXT.replace(b'desktop_to_phone', b'phone_to_desktop'))):
            with self.subTest(reflect=reflect, context=context):
                self.open_lane()
                self.assertIsInstance(self.prove(reflect=reflect, context=context), PermissionError)
                self.assertEqual(self.peer.recv(1), b'')
                self.assertTrue(self.lane.drained)

    def test_no_send_without_exact_prepared_ready_and_successful_publication(self):
        for prepared, local_ready, published in ((b'\x00' * 32, True, True), (PREPARED, False, True),
                                                  (PREPARED, True, False)):
            with self.subTest(prepared=prepared, local_ready=local_ready, published=published):
                self.open_lane()
                self.assertEqual(self.prove(), PREPARED)
                with self.assertRaises(PermissionError):
                    self.lane.authorize_send(prepared, lambda: local_ready, lambda guard: published)
                self.assertEqual(self.peer.recv(1), b'')
                self.assertTrue(self.lane.drained)

    def test_prepared_and_proof_without_send_never_write_data(self):
        self.open_lane()
        self.assertEqual(self.prove(), PREPARED)
        with self.assertRaises(PermissionError):
            self.lane.write_record(None)
        self.assertEqual(self.peer.recv(1), b'')

    def test_invalid_shape_or_progressive_jpeg_fails_before_header(self):
        for size, progressive in (((58, 33), False), ((57, 33), True)):
            self.open_lane()
            self.assertEqual(self.prove(), PREPARED)
            self.lane.authorize_send(PREPARED, lambda: True, lambda guard: True)
            output = BytesIO()
            with Image.new('RGB', size) as image:
                image.save(output, 'JPEG', progressive=progressive)
            with self.assertRaises(ValueError):
                self.lane.write_record(DesktopScreenJpeg(0, output.getvalue()))
            self.assertEqual(self.peer.recv(1), b'')

    def test_stop_interrupts_pending_proof_and_waits_for_control_writer(self):
        self.open_lane()
        wait = self.in_worker(self.lane.prove)
        self.peer.sendall(PHONE)
        read_exact(self.peer, 48)
        self.lane.stop()
        self.assertIsInstance(wait(), (EOFError, OSError))
        self.assertTrue(self.lane.drained)

        self.open_lane()
        self.assertEqual(self.prove(), PREPARED)
        entered, resume = Event(), Event()

        def publish(guard):
            guard()
            entered.set()
            resume.wait(2)
            return True

        wait = self.in_worker(lambda: self.lane.authorize_send(PREPARED, lambda: True, publish))
        try:
            self.assertTrue(entered.wait(2))
            self.lane.stop()
            self.assertEqual(self.peer.recv(1), b'')
            self.assertFalse(self.lane.drained)
        finally:
            resume.set()
        self.assertIsInstance(wait(), PermissionError)
        self.assertTrue(self.lane.drained)

    def test_original_deadline_and_live_guard_are_not_replaced(self):
        self.open_lane(deadline=.12)
        with self.assertRaises(TimeoutError):
            self.lane.prove()
        self.assertTrue(self.lane.drained)
        self.open_lane()
        self.assertEqual(self.prove(), PREPARED)

        def publish(guard):
            guard()
            self.live = False
            return True

        with self.assertRaises(PermissionError):
            self.lane.authorize_send(PREPARED, lambda: True, publish)
        self.assertEqual(self.peer.recv(1), b'')
        self.assertTrue(self.lane.drained)

    def test_stop_interrupts_backpressure_without_retrying_record(self):
        self.open_lane()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        self.peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.assertEqual(self.prove(), PREPARED)
        self.lane.authorize_send(PREPARED, lambda: True, lambda guard: True)
        output = BytesIO()
        with Image.new('RGB', (57, 33)) as image:
            image.save(output, 'JPEG')
        jpeg = output.getvalue()
        # Legal APP segments keep the viewport fixed but exceed the socket buffers.
        segment = b'\xff\xed' + struct.pack('!H', 60002) + bytes(60000)
        jpeg = jpeg[:2] + segment * 15 + jpeg[2:]
        wait = self.in_worker(lambda: self.lane.write_record(DesktopScreenJpeg(0, jpeg)))
        self.assertEqual(read_exact(self.peer, 12), struct.pack('!IQ', len(jpeg) + 16, 0))
        self.lane.stop()
        self.assertIsInstance(wait(), (PermissionError, OSError))
        self.assertTrue(self.lane.drained)
        with self.assertRaises(PermissionError):
            self.lane.write_record(None)

    def test_draft_control_and_proven_tcp_socket_share_send_and_stop(self):
        vectors = json.loads((Path(__file__).resolve().parents[2] /
                              'contracts/desktop-screen-control-draft-v1-vectors.json').read_text())
        request = dict(vectors['request'], setup_until_ms=time_ns() // 1_000_000 + 4000)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            phone = socket.create_connection(listener.getsockname(), timeout=1)
            native, _ = listener.accept()
        with native, phone:
            native.settimeout(.25)
            parent = SecureChannel(native, SESSION, SECRET, b'\x04' * 4, b'\x02' * 32, b'\x05' * 4)
            channel = DesktopScreenDraftChannel(parent, lambda: None)

            def phone_writes(body, sequence):
                header = dict(p=PROTOCOL, sid=b64(SESSION), seq=sequence, dir='phone_to_desktop')
                payload = canonical(dict(type=DRAFT_FRAME, body=body))
                ciphertext = AESGCM(b'\x02' * 32).encrypt(b'\x05' * 4 + sequence.to_bytes(8, 'big'), payload, canonical(header))
                send_frame(phone, dict(header, ciphertext=b64(ciphertext)))
                return parent.receive()

            def phone_reads(sequence):
                packet = receive_frame(phone, 8192)
                ciphertext = base64.b64decode(packet.pop('ciphertext'), validate=True)
                self.assertEqual(packet, dict(p=PROTOCOL, sid=b64(SESSION), seq=sequence, dir='desktop_to_phone'))
                payload = strict_json(AESGCM(SECRET).decrypt(b'\x04' * 4 + sequence.to_bytes(8, 'big'), ciphertext, canonical(packet)))
                self.assertEqual(payload['type'], DRAFT_FRAME)
                return parse_control(payload['body'], 'desktop')

            original_request = channel.body_from(parent, phone_writes(request, 0))
            control = DesktopScreenDraftControl(parent, original_request, channel.require_current, deadline=monotonic() + 4)
            control.publish_offer(**vectors['offer_fields'], write_original=channel.write)
            offer = phone_reads(0)
            self.assertEqual(offer, dict(request, **vectors['offer_fields'], op='offer'))
            self.open_lane(require_control=control.require_current)
            self.assertEqual(self.prove(), PREPARED)
            prepared = dict(request, op='prepared', session=offer['session'], transcript=PREPARED.hex())
            self.assertTrue(control.receive(parent, channel.body_from(parent, phone_writes(prepared, 1))))
            self.no_data()
            self.lane.authorize_send(PREPARED, lambda: True,
                                     lambda guard: control.publish_send(PREPARED, guard, channel.write))
            self.assertEqual(phone_reads(1), dict(prepared, op='send'))
            control.require_send()
            self.lane.write_record(None)
            self.assertEqual(read_exact(self.peer, len(HEARTBEAT)), HEARTBEAT)
            stop = dict(request, op='stop', session=offer['session'])
            stop_packet = phone_writes(stop, 2)
            self.assertIsNone(channel.body_from(object(), stop_packet))
            self.assertTrue(control.receive(parent, channel.body_from(parent, stop_packet)))
            with self.assertRaises(PermissionError):
                self.lane.write_record(None)
            self.assertTrue(self.lane.drained)
            self.assertEqual(self.peer.recv(1), b'')
            channel.require_current()  # Ending the draft must not close Notes.


if __name__ == '__main__':
    unittest.main()
