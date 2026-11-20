"""Controlled join of the native portal and reader owners; no capture."""

import sys
from io import BytesIO
from time import monotonic, sleep
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_run as joined
from magnolie_desktop_screen_capture import ScreenCastFrame
from magnolie_desktop_screen_encode import DesktopScreenEncoder


class TestDesktopScreenLocalRun(unittest.TestCase):
    def patched(self, *args, **kwargs):
        patcher = patch.object(*args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def setUp(self):
        self.target, self.remote = object(), object()
        self.ended = Mock()
        self.portal = Mock()
        self.portal.selection_current.return_value = True
        self.portal.setup_deadline = monotonic() + 10
        self.reader = Mock(ready=False, finished=False, drained=False)
        self.reader.take_latest.return_value = None
        self.encoder = Mock(drained=False, failed=False, has_frame=False)
        portal = self.patched(joined, 'DesktopScreenCast', return_value=self.portal)
        self.start_reader = self.patched(joined.DesktopScreenCapture, 'start', return_value=self.reader)
        self.start_encoder = self.patched(joined, 'DesktopScreenEncoder', return_value=self.encoder)
        self.timer = self.patched(joined.GLib, 'timeout_add', return_value=37)
        self.remove_timer = self.patched(joined.GLib, 'source_remove')
        self.run = joined.DesktopScreenLocalRun(None, None, 'extend', 'x11:1234', 57, 33, lambda: None, self.ended)
        self.selected, self.closed = portal.call_args.args[-2:]

    def attach(self):
        self.run.begin()
        self.selected(self.portal, self.target)
        target, attach = self.portal.open_pipewire_remote.call_args.args
        self.assertIs(target, self.target)
        attach(self.remote)
        self.start_reader.assert_called_once_with(self.remote, self.target, 57, 33)
        return self.timer.call_args.args[1]

    def test_local_ready_requires_original_live_target_and_reader(self):
        tick = self.attach()
        self.assertFalse(self.run.ready)
        self.reader.ready = True
        self.reader.take_latest.return_value = object()
        self.assertTrue(tick())
        self.start_encoder.assert_called_once_with(57, 33)
        self.assertFalse(self.run.ready, 'An RGBx frame does not establish JPEG readiness')
        self.reader.take_latest.return_value = None
        self.encoder.has_frame = True
        self.assertTrue(tick())
        self.assertTrue(self.run.ready)
        self.assertIs(self.run.take_latest(), self.encoder.take_latest.return_value)
        self.portal.selection_current.return_value = False
        self.assertFalse(self.run.ready)
        self.assertIsNone(self.run.take_latest())
        self.encoder.take_latest.assert_called_once()

    def test_portal_closed_before_reader_exit_does_not_report_early(self):
        tick = self.attach()
        self.run.stop()
        self.assertIsNone(self.run.take_latest())
        self.portal.stop.assert_called_once()
        self.closed(True)
        self.assertTrue(tick())
        self.ended.assert_not_called()
        self.reader.finished = self.reader.drained = True
        self.assertFalse(tick())
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, True, True))
        self.remove_timer.assert_called_once_with(37)
        self.closed(False)
        self.ended.assert_called_once()

    def test_reader_failure_closes_portal_without_certifying_unconfirmed_drain(self):
        tick = self.attach()
        self.reader.finished = True
        self.assertTrue(tick())
        self.portal.stop.assert_called_once()
        self.ended.assert_not_called()
        self.closed(False)
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(False, False, True))

    def test_portal_revoke_immediately_stops_existing_reader(self):
        tick = self.attach()
        self.reader.ready = True
        self.closed(True)
        self.reader.stop.assert_called_once()
        self.assertFalse(self.run.ready)
        self.reader.finished = True
        self.assertFalse(tick())
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, False, True))

    def test_stop_during_open_never_starts_late_reader(self):
        self.run.begin()
        self.selected(self.portal, self.target)
        _, attach = self.portal.open_pipewire_remote.call_args.args
        self.run.stop()
        attach(self.remote)
        self.start_reader.assert_not_called()
        self.closed(True)
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, True, True))
        with self.assertRaises(RuntimeError):
            self.run.begin()

    def test_late_encoder_frame_never_becomes_ready_or_reports_early_drain(self):
        tick = self.attach()
        self.reader.ready = True
        self.reader.take_latest.return_value = object()
        tick()
        self.encoder.has_frame = True
        self.portal.setup_deadline = monotonic()
        self.assertTrue(tick())
        self.assertFalse(self.run.ready)
        self.assertIsNone(self.run.take_latest())
        self.portal.stop.assert_called_once()
        self.closed(True)
        self.reader.finished = self.reader.drained = True
        self.assertTrue(tick())
        self.ended.assert_not_called()
        self.encoder.drained = True
        self.assertFalse(tick())
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, True, True))

    def test_codec_failure_closes_exact_portal_and_reader(self):
        tick = self.attach()
        self.reader.take_latest.return_value = object()
        tick()
        self.encoder.failed = True
        tick()
        self.assertFalse(self.run.ready)
        self.portal.stop.assert_called_once()
        self.encoder.stop.assert_called_once()
        self.reader.stop.assert_called_once()

    def test_real_encoder_output_exposed_only_for_current_selection(self):
        from PIL import Image

        encoder = DesktopScreenEncoder(57, 33)
        self.addCleanup(encoder.stop)
        self.start_encoder.return_value = encoder
        tick = self.attach()
        self.reader.ready = True
        raw = ScreenCastFrame(3, b'\x21\xa0\x40\x00' * (57 * 33))
        self.reader.take_latest.side_effect = [raw] + [None] * 500
        deadline = monotonic() + 2
        while not self.run.ready:
            self.assertLess(monotonic(), deadline)
            self.assertTrue(tick())
            sleep(.005)
        frame = self.run.take_latest()
        self.assertEqual(frame.sequence, 3)
        with Image.open(BytesIO(frame.data)) as image:
            self.assertEqual(image.size, (57, 33))
            self.assertTrue(all(abs(a - b) <= 4 for a, b in zip(image.getpixel((28, 16)), (33, 160, 64))))
        self.closed(True)
        self.assertFalse(self.run.ready)
        self.assertIsNone(self.run.take_latest())
        self.reader.finished = self.reader.drained = True
        deadline = monotonic() + 2
        while tick():
            self.assertLess(monotonic(), deadline)
            sleep(.005)
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, True, True))


if __name__ == '__main__':
    unittest.main()
