"""Controlled join of the native portal and reader owners; no capture."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_run as joined


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
        self.reader = Mock(ready=False, finished=False, drained=False)
        portal = self.patched(joined, 'DesktopScreenCast', return_value=self.portal)
        self.start_reader = self.patched(joined.DesktopScreenCapture, 'start', return_value=self.reader)
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
        self.attach()
        self.assertFalse(self.run.ready)
        self.reader.ready = True
        self.assertTrue(self.run.ready)
        self.portal.selection_current.return_value = False
        self.assertFalse(self.run.ready)
        self.assertIsNone(self.run.take_latest())
        self.reader.take_latest.assert_not_called()

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
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, True))
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
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(False, False))

    def test_portal_revoke_immediately_stops_existing_reader(self):
        tick = self.attach()
        self.reader.ready = True
        self.closed(True)
        self.reader.stop.assert_called_once()
        self.assertFalse(self.run.ready)
        self.reader.finished = True
        self.assertFalse(tick())
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, False))

    def test_stop_during_open_never_starts_late_reader(self):
        self.run.begin()
        self.selected(self.portal, self.target)
        _, attach = self.portal.open_pipewire_remote.call_args.args
        self.run.stop()
        attach(self.remote)
        self.start_reader.assert_not_called()
        self.closed(True)
        self.ended.assert_called_once_with(joined.ScreenRunCleanup(True, True))
        with self.assertRaises(RuntimeError):
            self.run.begin()


if __name__ == '__main__':
    unittest.main()
