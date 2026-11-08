"""Bounded capture-metadata selection, not provenance or file-kind authority.

No paths, directory labels or extensions are accepted as evidence. Unsupported,
stripped and malformed metadata is excluded by the optional photos-only filter.
"""
from datetime import datetime
import re

MAX_METADATA_BYTES = 1024 * 1024


def _tiff_matches(data):
    if len(data) < 8 or bytes(data[:2]) not in (b'II', b'MM'):
        return False
    order = 'little' if bytes(data[:2]) == b'II' else 'big'
    def number(offset, size):
        if offset < 0 or offset + size > len(data):
            raise ValueError('truncated EXIF')
        return int.from_bytes(data[offset:offset + size], order)
    def directory(offset):
        if offset < 8:
            raise ValueError('invalid EXIF directory')
        count = number(offset, 2)
        if count > 256 or offset + 2 + count * 12 + 4 > len(data):
            raise ValueError('invalid EXIF directory')
        tags = {}
        for index in range(count):
            item = offset + 2 + index * 12
            tag = number(item, 2)
            if tag in tags:
                raise ValueError('ambiguous EXIF tag')
            tags[tag] = (number(item + 2, 2), number(item + 4, 4), item + 8)
        return tags
    def text(entry, maximum):
        if entry is None:
            return None
        kind, count, value = entry
        if kind != 2 or not 2 <= count <= maximum + 1:
            return None
        offset = value if count <= 4 else number(value, 4)
        if offset + count > len(data):
            return None
        raw = bytes(data[offset:offset + count])
        if raw[-1:] != b'\0' or any(value < 32 or value > 126 for value in raw[:-1]):
            return None
        return raw[:-1].decode('ascii')
    try:
        if number(2, 2) != 42:
            return False
        tags = directory(number(4, 4))
        make, model = text(tags.get(0x010f), 128), text(tags.get(0x0110), 128)
        if not any(value and value.strip() for value in (make, model)):
            return False
        pointer = tags.get(0x8769)
        if pointer is None or pointer[:2] != (4, 1):
            return False
        capture = directory(number(pointer[2], 4))
        taken = text(capture.get(0x9003), 19)
        if taken is None or not re.fullmatch(r'[0-9]{4}:[0-9]{2}:[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}', taken):
            return False
        return datetime.strptime(taken, '%Y:%m:%d %H:%M:%S').year >= 1900
    except (ValueError, OverflowError):
        return False


def camera_photo_matches(prefix):
    """Inspect at most the caller's first MiB; never decode pixels or follow IO.

    JPEG EXIF, TIFF and PNG eXIf are recognized. Other formats remain unknown;
    this criterion is not a replacement for native media-format validation.
    """
    if not isinstance(prefix, (bytes, bytearray, memoryview)) or len(prefix) > MAX_METADATA_BYTES:
        return False
    data = memoryview(prefix)
    if bytes(data[:2]) in (b'II', b'MM'):
        return _tiff_matches(data)
    if bytes(data[:2]) == b'\xff\xd8':
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 255:
                return False
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset + 3 > len(data) or data[offset] in (0, 0xd9, 0xda):
                return False
            marker = data[offset]; offset += 1
            size = int.from_bytes(data[offset:offset + 2], 'big')
            if size < 2 or offset + size > len(data):
                return False
            payload = data[offset + 2:offset + size]
            if marker == 0xe1 and bytes(payload[:6]) == b'Exif\0\0':
                return _tiff_matches(payload[6:])
            offset += size
        return False
    if bytes(data[:8]) == b'\x89PNG\r\n\x1a\n':
        offset = 8
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], 'big')
            if offset + size + 12 > len(data):
                return False
            kind = bytes(data[offset + 4:offset + 8])
            if kind == b'eXIf':
                return _tiff_matches(data[offset + 8:offset + 8 + size])
            if kind == b'IEND':
                return False
            offset += size + 12
    return False
