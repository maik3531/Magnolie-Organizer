"""Exact bounded source media metadata, not native READ/write/baseline authority."""
from dataclasses import dataclass
import re

from magnolie_file_control import _hex
from magnolie_file_sources import MEDIA, _body
from magnolie_file_transfer import FileManifest, TransferError
from magnolie_telefon import now_ms, valid_uuid


@dataclass(frozen=True)
class SourceMediaEntry:
    file_id: str
    photo_id: str
    media_kind: str


@dataclass(frozen=True)
class SourceMediaPage:
    request_id: str
    version: str
    run_id: str
    manifest_sha256: str
    source_epoch: str
    media_type: str
    insertion_witness: bool
    after: int
    next_cursor: int | None
    total_files: int
    entries: tuple

    @property
    def grants_write_authority(self):
        return False

    @property
    def is_saved_receipt(self):
        return False


def parse_media_page(message, *, expected_request_id, expected_version, expected_run_id,
        expected_after=0, expected_manifest_sha256=None, expected_source_epoch=None, expected_operation='media_page', now=None):
    def fail():
        raise TransferError('file_sources_invalid_media_page')
    if type(expected_after) is not int or not 0 <= expected_after <= 128 or expected_operation not in ('media_page', 'resume_media_page'):
        fail()
    body = _body(message, MEDIA, now_ms() if now is None else now)
    if (set(body) != {'format', 'request_id', 'operation', 'version', 'run_id', 'page'}
            or not valid_uuid(body['request_id'], version=4) or body['request_id'] != expected_request_id
            or body['operation'] != expected_operation or not _hex(body['version']) or body['version'] != expected_version
            or not valid_uuid(body['run_id'], version=4) or body['run_id'] != expected_run_id or type(body['page']) is not dict):
        fail()
    page = body['page']
    if (set(page) != {'format', 'manifest_sha256', 'source_epoch', 'media_type', 'insertion_witness',
                     'after', 'next_cursor', 'total_files', 'entries'}
            or type(page['format']) is not int or page['format'] != 1
            or not _hex(page['manifest_sha256']) or not _hex(page['source_epoch'])
            or expected_manifest_sha256 is not None and page['manifest_sha256'] != expected_manifest_sha256
            or expected_source_epoch is not None and page['source_epoch'] != expected_source_epoch
            or page['media_type'] not in ('images', 'video') or type(page['insertion_witness']) is not bool
            or type(page['total_files']) is not int or not 1 <= page['total_files'] <= 128
            or type(page['after']) is not int or not 0 <= page['after'] <= page['total_files'] or page['after'] != expected_after
            or type(page['entries']) is not list or not 0 <= len(page['entries']) <= 8
            or not page['entries'] and page['after'] < page['total_files']
            or page['after'] + len(page['entries']) > page['total_files']):
        fail()
    end = page['after'] + len(page['entries'])
    if end < page['total_files']:
        if type(page['next_cursor']) is not int or page['next_cursor'] != end:
            fail()
    elif page['next_cursor'] is not None:
        fail()
    entries = []
    for value in page['entries']:
        if (type(value) is not dict or set(value) != {'file_id', 'photo_id', 'media_kind'}
                or type(value['file_id']) is not str or re.fullmatch('[0-9a-f]{32}', value['file_id']) is None
                or not _hex(value['photo_id']) or value['media_kind'] not in (
                    ('image', 'animation', 'unknown_image') if page['media_type'] == 'images' else ('video',))):
            fail()
        entries.append(SourceMediaEntry(value['file_id'], value['photo_id'], value['media_kind']))
    if len({entry.file_id for entry in entries}) != len(entries) or len({entry.photo_id for entry in entries}) != len(entries):
        fail()
    return SourceMediaPage(body['request_id'], body['version'], body['run_id'], page['manifest_sha256'], page['source_epoch'],
        page['media_type'], page['insertion_witness'], page['after'], page['next_cursor'], page['total_files'], tuple(entries))


def correlate_media_pages(pages, manifest):
    """Whole immutable manifest correlation only, never source/device ownership.
    Native callers must separately retain their exact authenticated command/run
    and current consent. An opaque source ID is not a provider URI or write grant.
    """
    def fail():
        raise TransferError('file_sources_media_manifest_mismatch')
    if type(pages) is not tuple or not pages or any(type(page) is not SourceMediaPage for page in pages) or type(manifest) is not FileManifest:
        fail()
    first = pages[0]
    cursor = 0; entries = []
    for page in pages:
        if (cursor is None or page.after != cursor or page.manifest_sha256 != manifest.fingerprint
                or page.total_files != len(manifest.files)
                or (page.version, page.run_id, page.source_epoch, page.media_type, page.insertion_witness) !=
                   (first.version, first.run_id, first.source_epoch, first.media_type, first.insertion_witness)):
            fail()
        entries.extend(page.entries); cursor = page.next_cursor
    if (cursor is not None or tuple(entry.file_id for entry in entries) != tuple(file.id for file in manifest.files)
            or len({entry.photo_id for entry in entries}) != len(entries)):
        fail()
    return tuple(entries)
