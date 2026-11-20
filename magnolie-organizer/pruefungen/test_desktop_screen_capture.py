"""Controlled subprocess/descriptor tests; no desktop or phone is opened."""

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from time import monotonic, sleep
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_capture as capture
from magnolie_desktop_screen_cast import ScreenCastRemote, ScreenCastTarget


class Owner:
    def __init__(self, serial):
        self._target = ScreenCastTarget('extend', 7, serial)
        self._deadline = monotonic() + 5

    def _current(self):
        return True


class TestDesktopScreenCapture(unittest.TestCase):
    def remote(self, serial=987654321):
        self.owner = Owner(serial)
        original, self.control = socket.socketpair()
        self.remote_fd = original.detach()
        self.remote_handle = ScreenCastRemote(self.owner, self.remote_fd)
        self.addCleanup(self.control.close)
        self.addCleanup(self.remote_handle._close)
        return self.remote_handle, self.owner._target

    def wait_for(self, condition):
        deadline = monotonic() + 3
        while not condition():
            self.assertLess(monotonic(), deadline, 'capture worker exceeded test deadline')
            sleep(.005)

    def start(self, remote, target, program):
        original_popen = subprocess.Popen
        started = []

        def popen(argv, **kwargs):
            self.assertIn(f'target-object={target.serial}', argv)
            self.assertNotIn(f'path={target.node}', argv)
            self.assertTrue(kwargs['env']['PIPEWIRE_REMOTE'].startswith('magnolie-unused-'))
            fd, = kwargs['pass_fds']
            self.assertIn(f'fd={fd}', argv)
            self.assertNotEqual(fd, self.remote_fd)
            self.assertFalse(os.get_inheritable(fd))
            child = original_popen([sys.executable, '-c', program, str(fd)], **kwargs)
            started.append((child, fd))
            return child

        with patch.object(capture.subprocess, 'Popen', side_effect=popen), patch.object(capture.os, 'access', return_value=True):
            run = capture.DesktopScreenCapture.start(remote, target, 16, 16)
            self.addCleanup(run.stop)
            self.wait_for(lambda: started or run.finished)
        return run, started

    def test_complete_latest_frame_and_original_remote_revocation(self):
        remote, target = self.remote()
        run, started = self.start(remote, target, '''
import os, sys, time
fd = int(sys.argv[1]); os.write(fd, b'owned')
for value in range(3):
    frame = bytes([value]) * 1024
    os.write(1, frame[:33]); os.write(1, frame[33:])
os.write(fd, b'wrote'); time.sleep(10)
''')
        self.control.settimeout(2)
        self.assertEqual(self.control.recv(5, socket.MSG_WAITALL), b'owned')
        self.assertEqual(self.control.recv(5, socket.MSG_WAITALL), b'wrote')
        last = []

        def newest():
            value = run.take_latest()
            if value is not None and value.sequence == 2:
                last.append(value)
            return last

        self.wait_for(newest)
        self.assertEqual(last[0].rgbx, b'\x02' * 1024)
        self.assertTrue(run.ready)
        self.assertIsNone(run.take_latest())
        with patch.object(capture.os, 'access', return_value=True), self.assertRaises(PermissionError):
            capture.DesktopScreenCapture.start(remote, target, 16, 16)
        remote._close()
        self.assertFalse(run.ready)
        self.wait_for(lambda: run.finished)
        self.assertTrue(run.drained)
        child, duplicate = started[0]
        self.assertIsNotNone(child.returncode)
        self.assertTrue(child.stdout.closed)
        with self.assertRaises(OSError):
            os.fstat(duplicate)

    def test_partial_frame_never_ready(self):
        remote, target = self.remote()
        run, _ = self.start(remote, target, 'import os; os.write(1, bytes(1023))')
        self.wait_for(lambda: run.finished)
        self.assertTrue(run.drained)
        self.assertFalse(run.ready)
        self.assertIsNone(run.take_latest())
        self.assertEqual(run.reason, 'screen_cast_capture_partial_frame')

    def test_no_first_frame_after_original_deadline(self):
        remote, target = self.remote()
        self.owner._deadline = monotonic() + .35
        run, _ = self.start(remote, target, 'import time; time.sleep(10)')
        self.wait_for(lambda: run.finished)
        self.assertTrue(run.drained)
        self.assertFalse(run.ready)
        self.assertEqual(run.reason, 'screen_cast_capture_frame_timeout')

    def test_stop_reaps_child_which_ignores_terminate(self):
        remote, target = self.remote()
        run, started = self.start(remote, target, '''
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.write(int(sys.argv[1]), b'armed')
time.sleep(10)
''')
        self.control.settimeout(2)
        self.assertEqual(self.control.recv(5, socket.MSG_WAITALL), b'armed')
        run.stop()
        self.assertFalse(run.ready)
        self.wait_for(lambda: run.finished)
        self.assertTrue(run.drained)
        self.assertEqual(started[0][0].returncode, -signal.SIGKILL)

    def test_value_equal_target_and_missing_serial_are_not_authority(self):
        remote, target = self.remote()
        with patch.object(capture.os, 'access', return_value=True):
            with self.assertRaises(PermissionError):
                capture.DesktopScreenCapture.start(remote, ScreenCastTarget('extend', 7, target.serial), 16, 16)
            remote, target = self.remote(serial=None)
            with self.assertRaises(PermissionError):
                capture.DesktopScreenCapture.start(remote, target, 16, 16)

    def test_native_geometry_change_cannot_reach_the_fixed_viewport(self):
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst

        Gst.init(None)
        for width, height, ratio in ((96, 32, '1/1'), (64, 48, '1/1'), (64, 32, '2/1')):
            with self.subTest(width=width, height=height, ratio=ratio):
                pipeline = Gst.parse_launch('appsrc name=source format=time ! identity name=source_geometry ! '
                    'videoscale add-borders=true ! video/x-raw,width=16,height=16,pixel-aspect-ratio=1/1 ! '
                    'appsink name=output sync=false wait-on-eos=false')
                source, sink = [pipeline.get_by_name(name) for name in ('source', 'output')]
                pad = pipeline.get_by_name('source_geometry').get_static_pad('src')
                retired = capture._pin_source_geometry(Gst, pad)

                def push(w, h, par):
                    caps = f'video/x-raw,format=RGBx,width={w},height={h},framerate=30/1,pixel-aspect-ratio={par}'
                    source.set_property('caps', Gst.Caps.from_string(caps))
                    frame = Gst.Buffer.new_allocate(None, w * h * 4, None)
                    frame.fill(0, bytes(w * h * 4))
                    self.assertEqual(source.emit('push-buffer', frame), Gst.FlowReturn.OK)

                try:
                    self.assertNotEqual(pipeline.set_state(Gst.State.PLAYING), Gst.StateChangeReturn.FAILURE)
                    for _ in range(2):
                        push(64, 32, '1/1')
                        sample = sink.emit('try-pull-sample', Gst.SECOND)
                        self.assertIsNotNone(sample)
                        self.assertEqual(capture._source_geometry(sample.get_caps())[:2], (16, 16))
                        self.assertFalse(retired.is_set())
                    push(width, height, ratio)
                    self.assertTrue(retired.wait(1))
                    push(64, 32, '1/1')  # Old geometry does not reanimate it.
                    self.assertIsNone(sink.emit('try-pull-sample', 80 * Gst.MSECOND))
                finally:
                    pipeline.set_state(Gst.State.NULL)


if __name__ == '__main__':
    unittest.main()
