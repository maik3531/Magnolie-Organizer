"""Bounded authenticated-byte container identification, not pixel validation.

Matches Windows NativeMediaContentMime. No filename/MIME guess grants a source
owner; the receiver still inspects the full hash-verified native media file.
"""
import struct
from magnolie_file_transfer import TransferError

PREFIX_BYTES = 1024 * 1024
_SOF_MARKERS = frozenset((*range(0xc0, 0xc4), *range(0xc5, 0xc8), *range(0xc9, 0xcc), *range(0xcd, 0xd0)))


def identify_collection(prefix,total_bytes,kind):
    """Deny-only known opposite-container exclusion, never a video SEND grant.

    Only an independently admitted native collection source calls this. Unknown,
    broken or out-of-bound bytes still HOLD; do not catch mime_unknown as skip.
    Sender/receiver identification remains strict and unchanged.
    """
    if kind not in ('images','video'):raise TransferError('media_source_mime_unknown')
    try:return identify(prefix,total_bytes,kind)
    except TransferError as error:
        if str(error)!='media_source_mime_unknown':raise
    identify(prefix,total_bytes,'video' if kind=='images' else 'images')
    raise TransferError('media_collection_known_other_type')


def _dimensions(width, height):
    if not 1 <= width <= 32768 or not 1 <= height <= 32768 or width * height > 24000000:
        raise TransferError('media_source_mime_dimensions')


def identify(prefix, total_bytes, kind):
    if type(prefix) not in (bytes, bytearray) or type(total_bytes) is not int or len(prefix) > PREFIX_BYTES or total_bytes < len(prefix) or total_bytes < 1:
        raise TransferError('media_source_mime_bound')
    if kind == 'images':
        if len(prefix) >= 33 and prefix[:16] == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
            _dimensions(*struct.unpack_from('>ii', prefix, 16))
            if prefix[24] not in (1, 2, 4, 8, 16) or prefix[25] not in (0, 2, 3, 4, 6) or prefix[26] != 0 or prefix[27] != 0 or prefix[28] > 1:
                raise TransferError('media_source_mime_unknown')
            return 'image/png'
        if len(prefix) >= 4 and prefix[:2] == b'\xff\xd8':
            offset = 2
            while offset < len(prefix):
                if prefix[offset] != 255:break
                while offset < len(prefix) and prefix[offset] == 255:offset += 1
                if offset >= len(prefix):break
                marker = prefix[offset]; offset += 1
                if marker in (0, 0xd9, 0xda):break
                if marker == 1 or 0xd0 <= marker <= 0xd8:continue
                if offset + 2 > len(prefix):break
                size = struct.unpack_from('>H', prefix, offset)[0]
                if size < 2 or size > len(prefix) - offset:break
                if marker in _SOF_MARKERS:
                    if size < 8 or prefix[offset + 2] not in (8, 12):break
                    height, width = struct.unpack_from('>HH', prefix, offset + 3)
                    _dimensions(width, height)
                    return 'image/jpeg'
                offset += size
    elif kind == 'video' and len(prefix) >= 16 and prefix[4:8] == b'ftyp':
        size = struct.unpack_from('>I', prefix)[0]
        if 16 <= size <= 1024 and size <= len(prefix) and (size - 16) % 4 == 0:
            brand = prefix[8:12]
            if brand == b'qt  ':return 'video/quicktime'
            if brand in (b'isom', b'iso2', b'mp41', b'mp42', b'avc1', b'M4V '):return 'video/mp4'
    raise TransferError('media_source_mime_unknown')
