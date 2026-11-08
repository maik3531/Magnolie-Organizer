from pathlib import Path
import struct
import sys
import zlib

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_photo_metadata import camera_photo_matches, MAX_METADATA_BYTES


def capture_tiff(order='<', taken=b'2026:11:08 13:14:15\0'):
    head = (b'II' if order == '<' else b'MM') + struct.pack(order + 'HIH', 42, 8, 2)
    tags = struct.pack(order + 'HHII', 0x010f, 2, 6, 38) + struct.pack(order + 'HHII', 0x8769, 4, 1, 44)
    capture = struct.pack(order + 'HHHIII', 1, 0x9003, 2, 20, 62, 0)
    return head + tags + struct.pack(order + 'I', 0) + b'Phone\0' + capture + taken


def capture_jpeg(order='<', taken=b'2026:11:08 13:14:15\0'):
    payload = b'Exif\0\0' + capture_tiff(order, taken)
    return b'\xff\xd8\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload + b'\xff\xd9'


@pytest.mark.parametrize('order', ['<', '>'])
def test_capture_metadata_in_jpeg_tiff_and_png_uses_actual_tags_not_file_names(order):
    tiff = capture_tiff(order)
    chunk = b'eXIf' + tiff
    png = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', len(tiff)) + chunk + struct.pack('>I', zlib.crc32(chunk))
    assert camera_photo_matches(tiff)
    assert camera_photo_matches(capture_jpeg(order))
    assert camera_photo_matches(png)
    assert not camera_photo_matches(b'DCIM/Camera/IMG_1234.jpg Phone 2026:11:08 13:14:15')


@pytest.mark.parametrize('taken', [b'2026:02:29 13:14:15\0', b'0000:00:00 00:00:00\0', b'2026:11:08 25:14:15\0'])
def test_invalid_capture_timestamp_is_not_a_photograph(taken):
    assert not camera_photo_matches(capture_jpeg(taken=taken))


def test_unknown_stripped_truncated_oversized_and_hostile_offsets_are_excluded():
    assert not camera_photo_matches(b'\xff\xd8\xff\xd9')
    assert not camera_photo_matches(capture_jpeg()[:-8])
    assert not camera_photo_matches(b'x' * (MAX_METADATA_BYTES + 1))
    tiff = bytearray(capture_tiff()); tiff[4:8] = b'\xff' * 4
    assert not camera_photo_matches(tiff)
    tiff = bytearray(capture_tiff()); tiff[8:10] = b'\xff' * 2
    assert not camera_photo_matches(tiff)
    tiff = bytearray(capture_tiff()); tiff[38:44] = b'     \0'
    assert not camera_photo_matches(tiff)
