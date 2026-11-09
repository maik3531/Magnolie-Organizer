"""Actual retained bytes, native image/video decode and no restore/purge effects."""
import base64
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_preview import image_bounds, preview_held_file
from magnolie_media_trash import ProtectedMediaTrash
from magnolie_media_trash_ui import NativeMediaTrashUi
from test_file_authenticated_desktop import native, bind
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings
from test_media_trash_ui import request


@pytest.fixture
def image_trash(mappings, monkeypatch):
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    import test_photo_mappings as saved
    pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 800, 400); pixels.fill(0x20b040ff)
    ok, image = pixels.save_to_bufferv('png', [], []); assert ok
    original_manifest, original_chunk = saved.manifest, saved.chunk
    def manifest(fixture, count):
        full = original_manifest(fixture, count)
        return replace(full, files=tuple(replace(file, size=len(image), sha256=sha256(image).hexdigest()) for file in full.files), total_bytes=len(image) * count)
    monkeypatch.setattr(saved, 'manifest', manifest)
    monkeypatch.setattr(saved, 'chunk', lambda message, _: original_chunk(message, image))
    fixture, store = mappings
    receiver, pages, association = saved.save(fixture)
    _, records = store.commit_received(store.issue_action(), store.read(), receiver, pages)
    owner = ProtectedMediaTrash(fixture[3]._authority)
    try:
        before, _ = owner.read(); snapshot, entry = owner.prepare_local(owner.issue_action(), before, store, association, records[0].protected_record_sha256)
        snapshot, entry = owner.trash(owner.issue_action(), snapshot, entry.operation, lambda: True)
        original = fixture[4] / entry.mapping.relative_path; payload = original.parent / entry.payload_name
        yield fixture, owner, snapshot, entry, image, original, payload
    finally:owner.close()


@pytest.mark.parametrize('mode,maximum', [('thumbnail', 192), ('preview', 1024)])
def test_actual_offline_trash_preview_reads_exact_retained_image_without_move_or_history_write(image_trash, mode, maximum):
    fixture, owner, before, entry, image, original, payload = image_trash
    sent = fixture[2].send.call_count; key = payload.stat().st_ino
    ui = NativeMediaTrashUi(str(fixture[0].store.root), lambda: True)
    row = ui.handle(request())['entries'][0]; fields = {key: row[key] for key in ('scope', 'operation', 'version')}
    fixture[0].enabled = False # LOCAL history remains readable without a running phone service.
    result = ui.handle(request(mode, **fields)); preview = result['preview']
    encoded = base64.b64decode(preview['data_base64'], validate=True)
    assert result['ok'] and result['scope'] == row['scope'] and result['operation'] == entry.operation and result['version'] == before.version
    assert preview['mime_type'] == 'image/jpeg' and 0 < max(preview['width'], preview['height']) <= maximum
    assert image_bounds(encoded)[1:] == (preview['width'], preview['height']) and 'completed' not in result
    assert ui.handle(request())['entries'] == [row] and payload.read_bytes() == image and payload.stat().st_ino == key and not original.exists()
    assert fixture[2].send.call_count == sent and str(payload) not in str(result)


def test_preview_rejects_stale_selection_paths_and_foreign_replacement_before_decoder(image_trash, monkeypatch):
    fixture, owner, _, entry, image, original, payload = image_trash
    import magnolie_media_preview as decoder
    monkeypatch.setattr(decoder, 'preview_held_file', lambda *_args, **_kwargs: pytest.fail('Invalid selection reached native image decoding'))
    ui = NativeMediaTrashUi(str(fixture[0].store.root), lambda: True); row = ui.handle(request())['entries'][0]
    fields = {key: row[key] for key in ('scope', 'operation', 'version')}
    with pytest.raises(TransferError, match='invalid_request'):ui.handle(request('preview', **fields, path=str(payload)))
    with pytest.raises(TransferError, match='stale_choice'):ui.handle(request('preview', **{**fields, 'version': '0' * 64}))
    kept = payload.with_name('original-preview-fixture-kept'); payload.rename(kept); payload.write_bytes(image); payload.chmod(0o600)
    with pytest.raises(TransferError, match='original_file_changed'):ui.handle(request('thumbnail', **fields))
    assert kept.read_bytes() == image and payload.read_bytes() == image and not original.exists() and owner.read()[1] == (entry,)


def test_native_ui_withdrawal_after_decode_never_returns_preview_or_mutates_history(image_trash, monkeypatch):
    fixture, owner, before, entry, image, original, payload = image_trash
    import magnolie_media_preview as decoder
    allowed = True; encode = decoder._encode
    def retire(*args):
        nonlocal allowed
        result = encode(*args); allowed = False; return result
    monkeypatch.setattr(decoder, '_encode', retire)
    ui = NativeMediaTrashUi(str(fixture[0].store.root), lambda: allowed); row = ui.handle(request())['entries'][0]
    with pytest.raises(TransferError, match='native_ui_changed'):
        ui.handle(request('preview', **{key: row[key] for key in ('scope', 'operation', 'version')}))
    assert owner.read() == (before, (entry,)) and payload.read_bytes() == image and not original.exists()


def test_image_dimension_bounds_and_unknown_active_formats_hold_without_decoding():
    for width, height in ((0, 4), (40000, 1), (10000, 10000)):
        with pytest.raises(TransferError, match='pixel_bound'):
            image_bounds(b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR' + struct.pack('>II', width, height))
    for value in (b'<svg href="file:///private"/>', b'#EXTM3U\nhttps://invalid.invalid/stream', b'hello'):
        with pytest.raises(TransferError):image_bounds(value)


def test_real_video_frame_uses_readonly_descriptor_and_no_retained_preview_file(tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('prlimit'):pytest.skip('Native optional ffmpeg/prlimit decoder unavailable')
    video = tmp_path / 'native-frame.mp4'
    subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-filter_threads', '1',
        '-f', 'lavfi', '-i', 'color=c=green:s=640x320:d=0.1', '-frames:v', '2', '-an', '-c:v', 'mpeg4', '-threads', '1', str(video)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=True, timeout=10)
    video.chmod(0o600); before = video.read_bytes(); names = set(tmp_path.iterdir())
    fd = os.open(video, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:result = preview_held_file(fd, len(before), 'video', 'thumbnail', lambda: True)
    finally:os.close(fd)
    encoded = base64.b64decode(result['data_base64'], validate=True)
    assert image_bounds(encoded)[1:] == (result['width'], result['height']) and max(result['width'], result['height']) <= 192
    assert video.read_bytes() == before and set(tmp_path.iterdir()) == names
