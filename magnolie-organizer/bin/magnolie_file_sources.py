"""Strict source-policy metadata codecs (#330), not native grants or workers.

No store, directory, source scan, permission request, schedule or transport is
created here. A decoded result describes saved settings, never media READ or a
saved-destination receipt.
"""
from dataclasses import dataclass
import uuid

from magnolie_file_control import MAX_REVISION, MAX_TTL_MS, MAX_WIRE_BYTES, _hex
from magnolie_file_transfer import TransferError
from magnolie_telefon import CLOCK_SKEW_MS, canonical, now_ms, valid_uuid

REQUEST = "file_transfer.sources.request"
RESULT = "file_transfer.sources.result"
CATALOG = "file_transfer.sources.catalog"
KINDS = frozenset({"camera", "downloads", "screenshots", "whatsapp_received"})


def _kinds(value):
    if (type(value) is not list or len(value) > len(KINDS)
            or any(type(item) is not str or item not in KINDS for item in value)
            or value != sorted(set(value))):
        raise TransferError("file_sources_invalid_kinds")
    return tuple(value)


def _body(message, kind, now):
    if (type(now) is not int or type(message) is not dict or set(message) != {
            "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body"}
            or message["type"] != "message" or type(message["v"]) is not int or message["v"] != 1
            or not valid_uuid(message["message_id"], version=4) or message["kind"] != kind
            or type(message["created_ms"]) is not int or not 0 <= message["created_ms"] <= 253_402_300_799_999
            or type(message["expires_ms"]) is not int
            or not 1 <= message["expires_ms"] - message["created_ms"] <= MAX_TTL_MS
            or now >= message["expires_ms"] or message["created_ms"] > now + CLOCK_SKEW_MS
            or type(message["body"]) is not dict or len(canonical(message)) > MAX_WIRE_BYTES):
        raise TransferError("file_sources_invalid_envelope")
    body = message["body"]
    if type(body.get("format")) is not int or body["format"] != 1:
        raise TransferError("file_sources_invalid_format")
    return body


@dataclass(frozen=True)
class SourceCommand:
    request_id: str
    operation: str
    expected_version: str | None = None
    enabled: bool | None = None
    kinds: tuple = ()
    catalog_id: str | None = None
    after: int = 0


def parse_command(message, *, now=None):
    body = _body(message, REQUEST, now_ms() if now is None else now)
    base = {"format", "operation"}
    if body.get("operation") == "status" and set(body) == base:
        return SourceCommand(message["message_id"], "status")
    if body.get("operation") in ("discover", "catalog_page"):
        paging = body['operation'] == 'catalog_page'
        if (set(body) != base | {'expected_version'} | ({'catalog_id', 'after'} if paging else set())
                or not _hex(body['expected_version']) or paging and (
                    not valid_uuid(body['catalog_id'], version=4) or type(body['after']) is not int or not 0 <= body['after'] <= 128)):
            raise TransferError('file_sources_invalid_command')
        return SourceCommand(message['message_id'], body['operation'], body['expected_version'],
                             catalog_id=body['catalog_id'] if paging else None, after=body['after'] if paging else 0)
    if (body.get("operation") != "configure" or set(body) != base | {"expected_version", "enabled", "kinds"}
            or not _hex(body["expected_version"]) or type(body["enabled"]) is not bool):
        raise TransferError("file_sources_invalid_command")
    kinds = _kinds(body["kinds"])
    if body["enabled"] and not kinds:
        raise TransferError("file_sources_invalid_command")
    return SourceCommand(message["message_id"], "configure", body["expected_version"], body["enabled"], kinds)


def create_command(operation, *, expected_version=None, enabled=None, kinds=(), catalog_id=None, after=None, now=None, message_id=None):
    at = now_ms() if now is None else now
    if type(at) is not int:
        raise TransferError("file_sources_invalid_time")
    body = {"format": 1, "operation": operation}
    if operation in ('discover', 'catalog_page'):
        if enabled is not None or kinds != () or operation == 'discover' and (catalog_id is not None or after is not None):
            raise TransferError('file_sources_invalid_command')
        body['expected_version'] = expected_version
        if operation == 'catalog_page': body.update(catalog_id=catalog_id, after=after)
    elif operation == "configure":
        if type(kinds) is not tuple:
            raise TransferError("file_sources_invalid_kinds")
        if catalog_id is not None or after is not None:
            raise TransferError('file_sources_invalid_command')
        body.update(expected_version=expected_version, enabled=enabled, kinds=list(kinds))
    elif expected_version is not None or enabled is not None or kinds != () or catalog_id is not None or after is not None:
        raise TransferError("file_sources_invalid_command")
    message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()) if message_id is None else message_id,
               "kind": REQUEST, "created_ms": at, "expires_ms": at + MAX_TTL_MS, "body": body}
    parse_command(message, now=at)
    return message


@dataclass(frozen=True)
class SourcePolicyStatus:
    request_id: str
    operation: str
    version: str
    revision: int
    enabled: bool
    associated: bool
    repair_pending: bool
    kinds: tuple


def parse_result(message, *, expected_request_id, expected_operation, now=None):
    body = _body(message, RESULT, now_ms() if now is None else now)
    if (set(body) != {"format", "request_id", "operation", "version", "revision", "enabled", "associated", "repair_pending", "kinds"}
            or not valid_uuid(body["request_id"], version=4) or body["request_id"] != expected_request_id
            or body["operation"] not in ("status", "configure") or body["operation"] != expected_operation
            or not _hex(body["version"]) or type(body["revision"]) is not int or not 0 <= body["revision"] <= MAX_REVISION
            or any(type(body[key]) is not bool for key in ("enabled", "associated", "repair_pending"))):
        raise TransferError("file_sources_invalid_result")
    kinds = _kinds(body["kinds"])
    if body["enabled"] and not kinds or body["revision"] == 0 and (body["enabled"] or body["associated"] or kinds):
        raise TransferError("file_sources_invalid_result")
    return SourcePolicyStatus(body["request_id"], body["operation"], body["version"], body["revision"],
                              body["enabled"], body["associated"], body["repair_pending"], kinds)


@dataclass(frozen=True)
class AlbumMetadata:
    album_id: str
    kind: str
    display_name: str
    visible_images: int
    needs_choice: bool


@dataclass(frozen=True)
class SourceCatalogPage:
    catalog_id: str
    after: int
    next_cursor: int | None
    coverage: str
    albums: tuple


def parse_catalog(message, *, expected_request_id, expected_operation, expected_version,
                  expected_catalog_id=None, expected_after=0, now=None):
    if type(expected_after) is not int or not 0 <= expected_after <= 128:
        raise TransferError('file_sources_invalid_catalog')
    body = _body(message, CATALOG, now_ms() if now is None else now)
    if (set(body) != {'format', 'request_id', 'operation', 'version', 'page'}
            or not valid_uuid(body['request_id'], version=4) or body['request_id'] != expected_request_id
            or body['operation'] not in ('discover', 'catalog_page') or body['operation'] != expected_operation
            or not _hex(body['version']) or body['version'] != expected_version or type(body['page']) is not dict):
        raise TransferError('file_sources_invalid_catalog')
    page = body['page']
    if (set(page) != {'format', 'catalog_id', 'after', 'next_cursor', 'coverage', 'proves_deletion', 'albums'}
            or type(page['format']) is not int or page['format'] != 1 or not valid_uuid(page['catalog_id'], version=4)
            or type(page['after']) is not int or not 0 <= page['after'] <= 128 or page['after'] != expected_after
            or type(page['proves_deletion']) is not bool or page['proves_deletion'] is not False
            or page['coverage'] not in ('none', 'selected_only', 'full_images')
            or type(page['albums']) is not list or len(page['albums']) + page['after'] > 128
            or page['coverage'] == 'none' and page['albums']
            or expected_operation == 'catalog_page' and (not valid_uuid(expected_catalog_id, version=4) or page['catalog_id'] != expected_catalog_id)
            or expected_operation == 'discover' and (expected_catalog_id is not None or page['after'] != 0)):
        raise TransferError('file_sources_invalid_catalog')
    following = page['next_cursor']
    if following is not None and (type(following) is not int or not page['albums']
                                 or following != page['after'] + len(page['albums']) or following > 128):
        raise TransferError('file_sources_invalid_catalog')
    albums = []
    ids = set()
    for album in page['albums']:
        if (type(album) is not dict or set(album) != {'album_id', 'kind', 'display_name', 'visible_images', 'needs_choice'}
                or not valid_uuid(album['album_id'], version=4) or album['album_id'] in ids
                or type(album['kind']) is not str or album['kind'] not in KINDS
                or type(album['display_name']) is not str or not 1 <= len(album['display_name'].encode('utf-16-le')) // 2 <= 256
                or any(ord(character) < 32 or ord(character) == 127 for character in album['display_name'])
                or type(album['visible_images']) is not int or not 0 <= album['visible_images'] <= 50_000
                or type(album['needs_choice']) is not bool):
            raise TransferError('file_sources_invalid_catalog')
        ids.add(album['album_id'])
        albums.append(AlbumMetadata(album['album_id'], album['kind'], album['display_name'], album['visible_images'], album['needs_choice']))
    return SourceCatalogPage(page['catalog_id'], page['after'], following, page['coverage'], tuple(albums))
