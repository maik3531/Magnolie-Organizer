"""Bounded local previews of an already authenticated, held recovery file.

No path selection, archive creation, restore, deletion or remote source rights.
Only fixed native sizes and PNG/JPEG output cross the browser boundary.
"""
import base64
import os
import shutil
import struct
import subprocess

from magnolie_file_transfer import MAX_FILE_BYTES, CHUNK_BYTES, TransferError

SIZES = {'thumbnail': 192, 'preview': 1024}
MAX_ENCODED = 512 * 1024
MAX_PIXELS = 24_000_000


def image_bounds(prefix):
    if prefix[:16] == b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR' and len(prefix) >= 24:
        kind = 'png'; width, height = struct.unpack('>II', prefix[16:24])
    elif prefix[:2] == b'\xff\xd8':
        kind = 'jpeg'; width = height = 0; offset = 2
        while offset < len(prefix):
            if prefix[offset] != 255:break
            while offset < len(prefix) and prefix[offset] == 255:offset += 1
            if offset >= len(prefix):break
            marker = prefix[offset];offset += 1
            if marker in (0,0xd9,0xda):break
            if marker == 0x01 or 0xd0 <= marker <= 0xd8:continue
            if offset + 2 > len(prefix):break
            size = int.from_bytes(prefix[offset:offset+2], 'big')
            if size < 2 or offset + size > len(prefix):break
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf) and size >= 8:
                height, width = struct.unpack('>HH', prefix[offset+3:offset+7]);break
            offset += size
    else:raise TransferError('media_preview_format_unavailable')
    if not (1 <= width <= 32768 and 1 <= height <= 32768 and width * height <= MAX_PIXELS):
        raise TransferError('media_preview_pixel_bound')
    return kind, width, height


def _encode(pixbuf, side, current):
    from gi.repository import GdkPixbuf
    width, height = pixbuf.get_width(), pixbuf.get_height()
    scale = min(1, side / max(width, height))
    if scale < 1:pixbuf = pixbuf.scale_simple(max(1, int(width * scale)), max(1, int(height * scale)), GdkPixbuf.InterpType.BILINEAR)
    if pixbuf.get_has_alpha():
        pixbuf = pixbuf.composite_color_simple(pixbuf.get_width(), pixbuf.get_height(), GdkPixbuf.InterpType.BILINEAR, 255, 8, 0xeeeeee, 0xffffff)
    for _ in range(4):
        current()
        ok, encoded = pixbuf.save_to_bufferv('jpeg', ['quality'], ['80'])
        current()
        if ok and len(encoded) <= MAX_ENCODED:
            return dict(mime_type='image/jpeg', width=pixbuf.get_width(), height=pixbuf.get_height(),
                data_base64=base64.b64encode(encoded).decode('ascii'))
        pixbuf = pixbuf.scale_simple(max(1, pixbuf.get_width() // 2), max(1, pixbuf.get_height() // 2), GdkPixbuf.InterpType.BILINEAR)
    raise TransferError('media_preview_output_bound')


def _image(fd, size, side, current):
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    prefix = os.pread(fd, min(size, 1024 * 1024), 0); current()
    kind, width, height = image_bounds(prefix)
    loader = GdkPixbuf.PixbufLoader.new_with_type(kind)
    scale = min(1, side / max(width, height))
    loader.set_size(max(1, int(width * scale)), max(1, int(height * scale)))
    closed = False
    try:
        for offset in range(0, size, CHUNK_BYTES):
            current(); chunk = os.pread(fd, min(CHUNK_BYTES, size - offset), offset)
            if len(chunk) != min(CHUNK_BYTES, size - offset):raise TransferError('media_preview_short_read')
            loader.write(chunk); current()
        loader.close(); closed = True; current()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None or pixbuf.get_width() > side or pixbuf.get_height() > side:raise TransferError('media_preview_decode_failed')
        pixbuf = pixbuf.apply_embedded_orientation()
        return _encode(pixbuf, side, current)
    finally:
        if not closed:
            try:loader.close()
            except Exception:pass


def _video(fd, size, side, current):
    # No shell/filename/playlist/network input. The child inherits ONLY the
    # authenticated original descriptor and returns one bounded still frame.
    ffmpeg, prlimit = shutil.which('ffmpeg'), shutil.which('prlimit')
    if not ffmpeg or not prlimit:raise TransferError('media_preview_decoder_unavailable')
    prefix = os.pread(fd, min(size, 32), 0); current()
    if len(prefix) >= 12 and prefix[4:8] == b'ftyp':container = 'mov'
    elif prefix[:4] == b'\x1aE\xdf\xa3':container = 'matroska'
    elif prefix[:4] == b'RIFF' and prefix[8:12] == b'AVI ':container = 'avi'
    else:raise TransferError('media_preview_format_unavailable')
    os.lseek(fd, 0, os.SEEK_SET); current()
    references = ['-enable_drefs', '0', '-use_absolute_path', '0'] if container == 'mov' else []
    arguments = [prlimit, '--as=1073741824', '--cpu=6:6', '--', ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-max_alloc', '67108864', '-threads', '1', '-filter_threads', '1', '-protocol_whitelist', 'file,pipe',
        '-format_whitelist', container, '-f', container, *references, '-i', '/proc/self/fd/' + str(fd), '-map', '0:V:0', '-frames:v', '1',
        '-an', '-sn', '-dn', '-vf', f"scale=w='min({side},iw)':h='min({side},ih)':force_original_aspect_ratio=decrease",
        '-c:v', 'mjpeg', '-threads', '1', '-q:v', '7', '-f', 'image2pipe', 'pipe:1']
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            pass_fds=(fd,), timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:raise TransferError('media_preview_decode_failed') from error
    current()
    if result.returncode or not result.stdout or len(result.stdout) > MAX_ENCODED:raise TransferError('media_preview_decode_failed')
    _, width, height = image_bounds(result.stdout)
    if max(width, height) > side:raise TransferError('media_preview_pixel_bound')
    return dict(mime_type='image/jpeg', width=width, height=height, data_base64=base64.b64encode(result.stdout).decode('ascii'))


def preview_held_file(fd, size, media_type, mode, current):
    if (type(fd) is not int or type(size) is not int or not 1 <= size <= MAX_FILE_BYTES or mode not in SIZES
            or media_type not in ('images','video') or not callable(current)):
        raise TransferError('media_preview_native_source_required')
    def active():
        if current() is not True:raise TransferError('media_preview_owner_changed')
        return True
    active()
    result = (_image if media_type == 'images' else _video)(fd, size, SIZES[mode], active)
    active();return result
