"""#519: generated protected files and actual native authority, no real device/key."""
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_sources import request, response, ALBUM, CATALOG
from test_file_desktop_video_metadata import prepare, status
import magnolie_file_sources as sources
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError


def video_catalog(fixture, tmp_path, monkeypatch):
    target = prepare(fixture, tmp_path, monkeypatch)
    status(fixture)
    command = request(fixture, 'discover', media_type='video')
    fixture[0]._payload(fixture[1], fixture[2], response(command, sources.CATALOG, version='3'*64,
        media_type='video', page=dict(format=1, catalog_id=CATALOG, after=0, next_cursor=None,
            coverage='full_videos', proves_deletion=False,
            albums=[dict(album_id=ALBUM, kind='camera', display_name='Synthetic camera', visible_images=1, needs_choice=False)])))
    return target


@pytest.mark.parametrize('fault', ['missing', 'replaced', 'permissions'])
@pytest.mark.parametrize('phase', ['before_snapshot', 'inside_snapshot_unseal'])
@pytest.mark.parametrize('pending', [False, True])
def test_early_protected_source_snapshot_cannot_revive_after_key_returns(receiving, tmp_path, monkeypatch, fault, phase, pending):
    target = video_catalog(receiving, tmp_path, monkeypatch)
    service, peer, channel, connection, photo_target = receiving
    assert connection._source_catalog.media_type == 'video'
    assert connection._preferences.read().include_videos
    # Test-only native readiness lets the real binding callback prove that
    # denial below is not merely the still-closed production video data gate.
    monkeypatch.setattr(type(connection), '_video_data_handlers_ready', True)
    assert connection._receive_binding(media_type='video') is not None
    if pending:
        request(receiving, 'request_read', media_type='video')
    key = Path(service.store.storage_path)
    assert key.is_relative_to(tmp_path), 'Only this fixture-generated key may be withdrawn'
    held = key.with_name('synthetic-held-storage-key')
    withdrawn = False

    def withdraw():
        nonlocal withdrawn
        assert not withdrawn
        if fault == 'permissions':
            key.chmod(0o644)
        else:
            key.rename(held)
            if fault == 'replaced':
                key.write_bytes(bytes([7])*32)
                key.chmod(0o600)
        withdrawn = True

    original_unseal = ExistingFileTransferProtection.unseal

    def unseal(owner, blob, domain):
        if owner is connection._authority.protection and domain.startswith(connection._preferences._domain) and not withdrawn:
            withdraw()
        return original_unseal(owner, blob, domain)

    if phase == 'before_snapshot':
        withdraw()
    else:
        # Inject only the physical file change at the actual decryption seam;
        # the real protection implementation must observe and reject it.
        monkeypatch.setattr(ExistingFileTransferProtection, 'unseal', unseal)
    before = channel.send.call_count
    try:
        with pytest.raises((OSError, TransferError, InvalidTag)):
            if pending:
                connection.retry_source_command()
            else:
                request(receiving, 'request_read', media_type='video')
        assert withdrawn and channel.send.call_count == before
    finally:
        if fault == 'permissions':
            key.chmod(0o600)
        elif withdrawn:
            if key.exists():
                key.unlink()  # Only the newly written synthetic replacement.
            held.rename(key)
        monkeypatch.setattr(ExistingFileTransferProtection, 'unseal', original_unseal)

    # Restoring the original physical key is not fresh consent. Neither a new
    # command nor the original pending ticket may reuse the old positive state.
    for operation in ('request_read', 'discover'):
        with pytest.raises((OSError, TransferError, InvalidTag)):
            request(receiving, operation, media_type='video')
    if pending:
        with pytest.raises((OSError, TransferError, InvalidTag)):
            connection.retry_source_command()
    with pytest.raises((OSError, TransferError, InvalidTag)):
        connection._receive_binding(media_type='video')
    assert channel.send.call_count == before
    assert connection._run is None and connection._catalog is None
    assert not list(target.iterdir()) and not list(photo_target.iterdir())
    assert connection._authority._revoked.is_set() or connection._preferences._uncertain


def test_current_healthy_protected_source_snapshot_still_allows_explicit_metadata_command(receiving, tmp_path, monkeypatch):
    video_catalog(receiving, tmp_path, monkeypatch)
    before = receiving[2].send.call_count
    command = request(receiving, 'request_read', media_type='video')
    assert command['body']['operation'] == 'request_read' and command['body']['media_type'] == 'video'
    assert receiving[2].send.call_count == before + 1
    assert receiving[3]._run is None and receiving[3]._catalog is None
