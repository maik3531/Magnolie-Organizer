"""Negative ownership checks for the isolated desktop draft composition."""

import socket
import sys
from pathlib import Path
from time import monotonic, time_ns
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_attempt as draft
from magnolie_desktop_screen_run import ScreenRunCleanup
from magnolie_telefon import SecureChannel


class TestDesktopScreenDraftAttempt(unittest.TestCase):
    def setUp(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            self.peer = socket.create_connection(listener.getsockname(), timeout=.05)
            self.addCleanup(self.peer.close)
            native, _ = listener.accept()
        self.addCleanup(native.close)
        self.parent = SecureChannel(native, bytes(16), bytes(32), b'\x04' * 4, bytes(32), b'\x05' * 4)
        self.request = dict(draft='desktop-screen-control/1', op='request', request='aa' * 16,
                            mode=2, setup_until_ms=time_ns() // 1_000_000 + 3000)
        self.outcomes = []

    def create(self, mode):
        return draft.DesktopScreenDraftAttempt(self.parent, self.request, lambda: None,
            bus=None, provider=None, mode=mode, parent_window='synthetic', width=57, height=33,
            deadline=monotonic() + 2, ended=self.outcomes.append)

    def test_requested_extension_cannot_open_existing_surface(self):
        with patch.object(draft, 'DesktopScreenLocalRun') as portal, self.assertRaises(ValueError):
            self.create('monitor')
        portal.assert_not_called()

    def test_no_jpeg_means_no_listener_and_stop_waits_for_portal(self):
        with patch.object(draft, 'DesktopScreenLocalRun') as portal, patch.object(draft.GLib, 'timeout_add', return_value=7):
            portal.return_value.ready = False
            run = self.create('extend')
            complete_local = portal.call_args.args[-1]
            self.addCleanup(run.stop)
            run.begin()
            with patch.object(run._wire, 'open_original_listener') as listen:
                self.assertTrue(run._tick())
                run.stop()
                self.assertTrue(run._tick())
                listen.assert_not_called()
            self.assertEqual(self.outcomes, [])
            self.assertEqual(self.parent.send_seq, 0)
            with self.assertRaises(socket.timeout):
                self.peer.recv(1)
            local = ScreenRunCleanup(False, True, True)
            complete_local(local)
            self.assertFalse(run._tick())
            self.assertEqual(self.outcomes, [draft.DesktopScreenAttemptCleanup(local, True)])
            with self.assertRaises(RuntimeError):
                run.begin()

    def test_output_proof_is_rechecked_after_the_transport_exits(self):
        with patch.object(draft, 'DesktopScreenLocalRun') as factory, patch.object(draft.GLib, 'timeout_add'):
            run = self.create('extend')
            run.begin()
            run._local_ended(ScreenRunCleanup(True, True, True, True, True))
            with patch.object(run._worker, 'is_alive', return_value=True):
                self.assertTrue(run._tick())
                self.assertEqual(self.outcomes, [])
            factory.return_value.output_removal_current.return_value = False
            self.assertFalse(run._tick())
            self.assertEqual(self.outcomes, [draft.DesktopScreenAttemptCleanup(
                ScreenRunCleanup(True, True, True, True, False), True)])


if __name__ == '__main__':
    unittest.main()
