"""Local JPEG bounds, color and latest-frame behavior; no desktop or device."""

from io import BytesIO
from pathlib import Path
import sys
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_encode as encode
from magnolie_desktop_screen_capture import ScreenCastFrame


class TestDesktopScreenEncoder(unittest.TestCase):
    def worker(self, width=17, height=19):
        worker = encode.DesktopScreenEncoder(width, height)
        self.addCleanup(lambda: self.wait_for(lambda: worker.drained))
        self.addCleanup(worker.stop)
        return worker

    def wait_for(self, condition):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            result = condition()
            if result:
                return result
            sleep(.005)
        self.fail('encoder test deadline exceeded')

    def test_real_baseline_jpeg_keeps_odd_dimensions_and_rgb_order(self):
        worker = self.worker()
        self.assertTrue(worker.offer(ScreenCastFrame(11, b'\x12\x67\xa4\x00' * (17 * 19))))
        result = self.wait_for(worker.take_latest)
        self.assertEqual(result.sequence, 11)
        self.assertLessEqual(len(result.data), encode.MAX_JPEG_BYTES)
        self.assertTrue(result.data.startswith(b'\xff\xd8') and result.data.endswith(b'\xff\xd9'))
        self.assertIn(b'\xff\xc0', result.data)
        with Image.open(BytesIO(result.data)) as jpg:
            self.assertEqual((jpg.format, jpg.size, jpg.mode), ('JPEG', (17, 19), 'RGB'))
            self.assertNotIn('progressive', jpg.info)
            self.assertTrue(all(abs(a - b) <= 4 for a, b in zip(jpg.getpixel((8, 9)), (18, 103, 164))))

    def test_capped_pillow_write_never_returns_partial_jpeg(self):
        with patch.object(encode, 'MAX_JPEG_BYTES', 128):
            self.assertIsNone(encode._encode(bytes(17 * 19 * 4), (17, 19), lambda: True))

    def test_bad_shapes_and_replayed_sequences_never_enter_slot(self):
        worker = self.worker()
        for bad in (ScreenCastFrame(0, bytes(17 * 19 * 4 - 1)), ScreenCastFrame(True, bytes(17 * 19 * 4)),
                    ScreenCastFrame(2**63 - 1, bytes(17 * 19 * 4))):
            with self.assertRaises(ValueError):
                worker.offer(bad)
        frame = ScreenCastFrame(7, bytes(17 * 19 * 4))
        self.assertTrue(worker.offer(frame))
        self.assertFalse(worker.offer(frame))
        self.assertFalse(worker.offer(ScreenCastFrame(6, frame.rgbx)))

    def test_only_newest_waits_and_stop_discards_inflight_result(self):
        worker = self.worker(16, 16)
        entered, release, second, finish = Event(), Event(), Event(), Event()
        seen = []

        def controlled(data, _size, _current):
            seen.append(data[0])
            if len(seen) == 1:
                entered.set()
                release.wait(2)
            else:
                second.set()
                finish.wait(2)
            return b'controlled output'

        with patch.object(encode, '_encode', side_effect=controlled):
            try:
                for sequence in (0, 1, 2):
                    self.assertTrue(worker.offer(ScreenCastFrame(sequence, bytes([sequence]) * 1024)))
                    if sequence == 0:
                        self.assertTrue(entered.wait(2))
                release.set()
                self.assertTrue(second.wait(2))
                self.assertEqual(seen, [0, 2])
                worker.stop()
                self.assertFalse(worker.drained)
                self.assertIsNone(worker.take_latest())
            finally:
                release.set()
                finish.set()
                worker.stop()
                self.wait_for(lambda: worker.drained)
        self.assertIsNone(worker.take_latest())

    def test_codec_failure_retires_worker(self):
        worker = self.worker(16, 16)
        with patch.object(encode, '_encode', side_effect=OSError):
            worker.offer(ScreenCastFrame(0, bytes(1024)))
            self.wait_for(lambda: worker.drained)
        self.assertTrue(worker.failed)
        self.assertFalse(worker.offer(ScreenCastFrame(1, bytes(1024))))
        self.assertIsNone(worker.take_latest())


if __name__ == '__main__':
    unittest.main()
