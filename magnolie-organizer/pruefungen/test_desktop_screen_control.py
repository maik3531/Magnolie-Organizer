"""Shared draft contract vectors and one original desktop control attempt."""

import json
from pathlib import Path
import socket
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'magnolie-organizer/bin'))
from magnolie_desktop_screen_control import DesktopScreenDraftControl, parse_control
from magnolie_telefon import SecureChannel, receive_frame


VECTORS = json.loads((ROOT / 'contracts/desktop-screen-control-draft-v1-vectors.json').read_text())
REQUEST = VECTORS['request']
OFFER = VECTORS['offer_fields']
PROOF = bytes.fromhex(VECTORS['transcript'])


class TestDesktopScreenDraftControl(unittest.TestCase):
    def test_secure_write_edge_is_not_called_while_busy_or_on_preflight_rejection(self):
        native, peer = socket.socketpair()
        with native, peer:
            native.settimeout(.01)
            peer.settimeout(.5)
            channel = SecureChannel(native, bytes(16), bytes(32), b'\x04' * 4, bytes(32), b'\x05' * 4)
            entered = []
            packet = {'type': 'desktop_screen_draft', 'body': REQUEST}
            with channel.lock, self.assertRaises(TimeoutError):
                channel.send_ephemeral(packet, lambda: None, timeout=.04, at_write=lambda: entered.append(1))
            self.assertEqual(entered, [])

            def revoked():
                entered.append(2)
                raise PermissionError('controlled write edge retirement')

            with self.assertRaises(PermissionError):
                channel.send_ephemeral(packet, lambda: None, at_write=revoked)
            self.assertEqual(channel.send_seq, 0)
            channel.send_ephemeral(packet, lambda: None, at_write=lambda: entered.append(3))
            self.assertEqual(entered, [2, 3])
            self.assertEqual(receive_frame(peer, 8192)['seq'], 0)

    def start(self, budget=30_000, end=150):
        self.parent = object()
        self.mono = 100
        self.live = True

        def require_original():
            if not self.live:
                raise PermissionError('controlled original parent gone')

        self.control = DesktopScreenDraftControl(self.parent, REQUEST, require_original, clock=lambda: self.mono,
                                                 wall_ms=lambda: REQUEST['setup_until_ms'] - budget, deadline=end)
        return self.control

    @staticmethod
    def packet(op, **extra):
        fields = {'session': OFFER['session']}
        if op in ('send', 'prepared'):
            fields['transcript'] = PROOF.hex()
        return {**REQUEST, **fields, 'op': op, **extra}

    def test_shared_vectors_and_explicit_roles(self):
        offer = {**REQUEST, **OFFER, 'op': 'offer'}
        for op, sender, packet in [('request', 'phone', REQUEST), ('offer', 'desktop', offer),
                                   ('prepared', 'phone', self.packet('prepared')), ('send', 'desktop', self.packet('send'))]:
            with self.subTest(op=op):
                self.assertEqual(parse_control(packet, sender), packet)
                with self.assertRaises(ValueError):
                    parse_control(packet, 'phone' if sender == 'desktop' else 'desktop')
        for sender in ('phone', 'desktop'):
            self.assertEqual(parse_control(self.packet('stop'), sender), self.packet('stop'))
        for mutation in VECTORS['bad_offer_mutations']:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse_control({**offer, **mutation}, 'desktop')

    def test_requires_original_offer_write_then_matching_prepared_and_send_write(self):
        run = self.start()
        prepared = self.packet('prepared')
        self.assertFalse(run.receive(self.parent, prepared))

        def writer(body, guard):
            self.assertEqual(body, {**REQUEST, **OFFER, 'op': 'offer'})
            self.assertFalse(run.receive(self.parent, prepared))
            guard()
            self.assertFalse(run.receive(object(), prepared))
            for change in ({'mode': 1}, {'session': 'ff' * 16}, {'request': 'ff' * 16},
                           {'setup_until_ms': REQUEST['setup_until_ms'] + 1}):
                self.assertFalse(run.receive(self.parent, {**prepared, **change}))
            self.assertTrue(run.receive(self.parent, prepared))
            self.assertFalse(run.receive(self.parent, prepared))
            with self.assertRaises(PermissionError):
                run.publish_send(PROOF, lambda: None, lambda *_: True)
            return True

        run.publish_offer(**OFFER, write_original=writer)
        with self.assertRaises(PermissionError):
            run.publish_send(b'\xff' * 32, lambda: None, lambda *_: True)
        checks = []

        def send(body, guard):
            self.assertEqual(body, self.packet('send'))
            with self.assertRaises(PermissionError):
                run.require_send()
            guard()
            return True

        self.assertTrue(run.publish_send(PROOF, lambda: checks.append(True), send))
        self.assertEqual(len(checks), 3)
        self.mono += 120
        run.require_send()
        self.assertTrue(run.receive(self.parent, self.packet('stop')))
        with self.assertRaises(PermissionError):
            run.require_send()

    def test_no_success_without_write_edge_or_when_stopped_during_write(self):
        run = self.start()
        with self.assertRaises(PermissionError):
            run.publish_offer(**OFFER, write_original=lambda *_: True)
        for stop in (False, True):
            with self.subTest(stop=stop):
                run = self.start()
                run.publish_offer(**OFFER, write_original=lambda _, guard: (guard(), True)[1])
                self.assertTrue(run.receive(self.parent, self.packet('prepared')))

                def writer(_, guard):
                    if stop:
                        guard()
                        self.assertTrue(run.receive(self.parent, self.packet('stop')))
                    return True

                with self.assertRaises(PermissionError):
                    run.publish_send(PROOF, lambda: None, writer)
                with self.assertRaises(PermissionError):
                    run.require_send()

    def test_setup_deadline_only_shrinks_and_original_loss_cannot_reopen(self):
        for invalid in (0, -1, 30_001):
            with self.subTest(invalid=invalid), self.assertRaises(TimeoutError):
                self.start(budget=invalid)
        run = self.start(budget=6_000, end=140)
        self.assertEqual(run.setup_deadline, 106)
        run = self.start(budget=6_000, end=104)
        self.assertEqual(run.setup_deadline, 104)

        def writer(_, guard):
            guard()
            self.mono = 104
            return True

        with self.assertRaises(PermissionError):
            run.publish_offer(**OFFER, write_original=writer)
        run = self.start()
        self.live = False
        with self.assertRaises(PermissionError):
            run.publish_offer(**OFFER, write_original=lambda *_: True)
        self.live = True
        with self.assertRaises(PermissionError):
            run.publish_offer(**OFFER, write_original=lambda *_: True)


if __name__ == '__main__':
    unittest.main()
