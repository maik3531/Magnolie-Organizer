"""Strict source-policy metadata codecs (#330), not native grants or workers.

No store, directory, source scan, permission request, schedule or transport is
created here. A decoded result describes saved settings, never media READ or a
saved-destination receipt.
"""
from dataclasses import dataclass
import re
import uuid

from magnolie_file_control import MAX_REVISION, MAX_TTL_MS, MAX_WIRE_BYTES, _hex
from magnolie_file_transfer import TransferError
from magnolie_telefon import CLOCK_SKEW_MS, canonical, now_ms, valid_uuid

REQUEST = "file_transfer.sources.request"
RESULT = "file_transfer.sources.result"
CATALOG = "file_transfer.sources.catalog"
PERMISSION_RESULT = "file_transfer.sources.permission_result"
RUN_RESULT = "file_transfer.sources.run_result"
MEDIA = "file_transfer.sources.media"
RESUME = "file_transfer.sources.resume"
ABANDONED = 'file_transfer.sources.abandoned'
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
    album_id: str | None = None
    desktop_choice: bool | None = None
    run_id: str | None = None
    original_job_id: str | None = None
    original_job_version: str | None = None
    source_id: str | None = None
    transfer_id: str | None = None
    manifest_sha256: str | None = None
    attempt_id: str | None = None
    attempt_sha256: str | None = None


def parse_command(message, *, now=None):
    body = _body(message, REQUEST, now_ms() if now is None else now)
    base = {"format", "operation"}
    if body.get("operation") == "status" and set(body) == base:
        return SourceCommand(message["message_id"], "status")
    if body.get('operation') in ('media_page', 'resume_media_page'):
        if (set(body) != base | {'expected_version', 'run_id', 'after'} or not _hex(body['expected_version'])
                or not valid_uuid(body['run_id'], version=4) or type(body['after']) is not int or not 0 <= body['after'] <= 128):
            raise TransferError('file_sources_invalid_command')
        return SourceCommand(message['message_id'], body['operation'], body['expected_version'], after=body['after'], run_id=body['run_id'])
    if body.get('operation') == 'abandon_resume':
        if (set(body) != base | {'expected_version', 'run_id', 'original_job_id', 'original_job_version', 'attempt_id', 'attempt_sha256'}
                or not _hex(body['expected_version']) or not _hex(body['original_job_version']) or not _hex(body['attempt_sha256'])
                or not valid_uuid(body['run_id'], version=4) or not valid_uuid(body['attempt_id'], version=4)
                or type(body['original_job_id']) is not str or re.fullmatch(r'[0-9a-f]{32}', body['original_job_id']) is None):
            raise TransferError('file_sources_invalid_command')
        return SourceCommand(message['message_id'], 'abandon_resume', body['expected_version'], run_id=body['run_id'],
            original_job_id=body['original_job_id'], original_job_version=body['original_job_version'],
            attempt_id=body['attempt_id'], attempt_sha256=body['attempt_sha256'])
    if body.get('operation') == 'resume_lookup':
        if (set(body) != base | {'expected_version', 'source_id', 'transfer_id', 'manifest_sha256'}
                or not _hex(body['expected_version']) or not _hex(body['manifest_sha256'])
                or any(type(body[key]) is not str or re.fullmatch(r'[0-9a-f]{32}', body[key]) is None for key in ('source_id', 'transfer_id'))):
            raise TransferError('file_sources_invalid_command')
        return SourceCommand(message['message_id'], 'resume_lookup', body['expected_version'],
                             source_id=body['source_id'], transfer_id=body['transfer_id'], manifest_sha256=body['manifest_sha256'])
    if body.get('operation') in ('resume_run', 'resume_status', 'cancel_resume', 'offer_resume', 'end_resume'):
        starting = body['operation'] == 'resume_run'
        fields = {'catalog_id', 'album_id', 'desktop_choice', 'original_job_id', 'original_job_version'} if starting else {'run_id'}
        if set(body) != base | {'expected_version'} | fields or not _hex(body['expected_version']):
            raise TransferError('file_sources_invalid_command')
        if starting:
            if (type(body['catalog_id']) is not str or not valid_uuid(body['catalog_id'], version=4)
                    or type(body['album_id']) is not str or not valid_uuid(body['album_id'], version=4)
                    or type(body['desktop_choice']) is not bool or type(body['original_job_id']) is not str
                    or re.fullmatch(r'[0-9a-f]{32}', body['original_job_id']) is None or not _hex(body['original_job_version'])):
                raise TransferError('file_sources_invalid_command')
            return SourceCommand(message['message_id'], body['operation'], body['expected_version'], catalog_id=body['catalog_id'],
                                 album_id=body['album_id'], desktop_choice=body['desktop_choice'],
                                 original_job_id=body['original_job_id'], original_job_version=body['original_job_version'])
        if type(body['run_id']) is not str or not valid_uuid(body['run_id'], version=4):
            raise TransferError('file_sources_invalid_command')
        return SourceCommand(message['message_id'], body['operation'], body['expected_version'], run_id=body['run_id'])
    if body.get('operation') in ('run', 'run_status', 'cancel_run', 'offer_run', 'end_run'):
        starting = body['operation'] == 'run'
        if (set(body) != base | {'expected_version'} | ({'catalog_id', 'album_id', 'desktop_choice'} if starting else {'run_id'})
                or not _hex(body['expected_version'])):
            raise TransferError('file_sources_invalid_command')
        if starting:
            if (not valid_uuid(body['catalog_id'], version=4) or not valid_uuid(body['album_id'], version=4)
                    or type(body['desktop_choice']) is not bool):
                raise TransferError('file_sources_invalid_command')
            return SourceCommand(message['message_id'], 'run', body['expected_version'], catalog_id=body['catalog_id'],
                                 album_id=body['album_id'], desktop_choice=body['desktop_choice'])
        if not valid_uuid(body['run_id'], version=4):
            raise TransferError('file_sources_invalid_command')
        return SourceCommand(message['message_id'], body['operation'], body['expected_version'], run_id=body['run_id'])
    if body.get("operation") in ("discover", "catalog_page", "request_read"):
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


def create_command(operation, *, expected_version=None, enabled=None, kinds=(), catalog_id=None, after=None,
                   album_id=None, desktop_choice=None, run_id=None, original_job_id=None, original_job_version=None,
                   source_id=None, transfer_id=None, manifest_sha256=None, attempt_id=None, attempt_sha256=None, now=None, message_id=None):
    at = now_ms() if now is None else now
    if type(at) is not int:
        raise TransferError("file_sources_invalid_time")
    body = {"format": 1, "operation": operation}
    if operation != 'resume_lookup' and any(value is not None for value in (source_id, transfer_id, manifest_sha256)):
        raise TransferError('file_sources_invalid_command')
    if operation != 'abandon_resume' and any(value is not None for value in (attempt_id, attempt_sha256)):
        raise TransferError('file_sources_invalid_command')
    if operation not in ('resume_run', 'abandon_resume') and any(value is not None for value in (original_job_id, original_job_version)):
        raise TransferError('file_sources_invalid_command')
    if operation not in ('run', 'run_status', 'cancel_run', 'offer_run', 'end_run', 'media_page', 'resume_media_page', 'resume_run', 'resume_status', 'cancel_resume', 'offer_resume', 'end_resume', 'abandon_resume') and any(value is not None for value in (album_id, desktop_choice, run_id)):
        raise TransferError('file_sources_invalid_command')
    if operation == 'abandon_resume':
        if enabled is not None or kinds != () or any(value is not None for value in (catalog_id, after, album_id, desktop_choice)):
            raise TransferError('file_sources_invalid_command')
        body.update(expected_version=expected_version, run_id=run_id, original_job_id=original_job_id,
                    original_job_version=original_job_version, attempt_id=attempt_id, attempt_sha256=attempt_sha256)
    elif operation == 'resume_lookup':
        if enabled is not None or kinds != () or any(value is not None for value in (catalog_id, after, album_id, desktop_choice, run_id)):
            raise TransferError('file_sources_invalid_command')
        body.update(expected_version=expected_version, source_id=source_id, transfer_id=transfer_id, manifest_sha256=manifest_sha256)
    elif operation in ('resume_run', 'resume_status', 'cancel_resume', 'offer_resume', 'end_resume'):
        if enabled is not None or kinds != () or after is not None:
            raise TransferError('file_sources_invalid_command')
        body['expected_version'] = expected_version
        if operation == 'resume_run':
            if run_id is not None:
                raise TransferError('file_sources_invalid_command')
            body.update(catalog_id=catalog_id, album_id=album_id, desktop_choice=desktop_choice,
                        original_job_id=original_job_id, original_job_version=original_job_version)
        else:
            if any(value is not None for value in (catalog_id, album_id, desktop_choice)):
                raise TransferError('file_sources_invalid_command')
            body['run_id'] = run_id
    elif operation in ('media_page', 'resume_media_page'):
        if enabled is not None or kinds != () or any(value is not None for value in (catalog_id, album_id, desktop_choice)):
            raise TransferError('file_sources_invalid_command')
        body.update(expected_version=expected_version, run_id=run_id, after=after)
    elif operation in ('run', 'run_status', 'cancel_run', 'offer_run', 'end_run'):
        if enabled is not None or kinds != () or after is not None:
            raise TransferError('file_sources_invalid_command')
        body['expected_version'] = expected_version
        if operation == 'run':
            if run_id is not None: raise TransferError('file_sources_invalid_command')
            body.update(catalog_id=catalog_id, album_id=album_id, desktop_choice=desktop_choice)
        else:
            if any(value is not None for value in (catalog_id, album_id, desktop_choice)):
                raise TransferError('file_sources_invalid_command')
            body['run_id'] = run_id
    elif operation in ('discover', 'catalog_page', 'request_read'):
        if enabled is not None or kinds != () or operation != 'catalog_page' and (catalog_id is not None or after is not None):
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


@dataclass(frozen=True)
class SourcePermissionResult:
    request_id: str
    version: str
    state: str


def parse_permission_result(message, *, expected_request_id, expected_version, now=None):
    body = _body(message, PERMISSION_RESULT, now_ms() if now is None else now)
    if (set(body) != {'format', 'request_id', 'operation', 'version', 'state'}
            or not valid_uuid(body['request_id'], version=4) or body['request_id'] != expected_request_id
            or body['operation'] != 'request_read' or not _hex(body['version']) or body['version'] != expected_version
            or body['state'] not in ('requested', 'notification_posted', 'foreground_required', 'failed')):
        raise TransferError('file_sources_invalid_permission_result')
    return SourcePermissionResult(body['request_id'], body['version'], body['state'])


@dataclass(frozen=True)
class SourceRunResult:
    request_id: str
    operation: str
    version: str
    run_id: str
    state: str
    source_io_ended: bool
    offer_id: str | None = None
    manifest_sha256: str | None = None
    run_ended: bool = False


@dataclass(frozen=True)
class SourceResumeHistory:
    request_id: str
    version: str
    job_id: str
    job_version: str
    phase: str
    source_id: str
    transfer_id: str
    manifest_sha256: str
    remote_saved_history: bool
    attempt_phase: str | None
    attempt_id: str | None = None
    attempt_sha256: str | None = None


@dataclass(frozen=True)
class SourceResumeAbandonment:
    request_id: str
    version: str
    run_id: str
    job_id: str
    job_version: str
    attempt_id: str
    attempt_sha256: str
    receipt_sha256: str


def parse_resume_abandonment(message, command, *, now=None):
    body = _body(message, ABANDONED, now_ms() if now is None else now)
    if (type(command) is not SourceCommand or command.operation != 'abandon_resume'
            or set(body) != {'format', 'operation', 'request_id', 'version', 'run_id', 'job_id', 'job_version',
                             'attempt_id', 'attempt_sha256', 'receipt_sha256'}
            or body['operation'] != 'abandon_resume' or not _hex(body['receipt_sha256'])
            or body['request_id'] != command.request_id or body['version'] != command.expected_version
            or body['run_id'] != command.run_id or body['job_id'] != command.original_job_id
            or body['job_version'] != command.original_job_version or body['attempt_id'] != command.attempt_id
            or body['attempt_sha256'] != command.attempt_sha256):
        raise TransferError('file_sources_invalid_resume_abandonment')
    return SourceResumeAbandonment(**{key: body[key] for key in SourceResumeAbandonment.__dataclass_fields__})


def parse_resume_history(message, *, expected_request_id, expected_version, expected_source_id,
                         expected_transfer_id, expected_manifest_sha256, now=None):
    """Historical hints only: never receiver/source readiness or a resume grant."""
    body = _body(message, RESUME, now_ms() if now is None else now)
    if (set(body) != {'format', 'request_id', 'operation', 'version', 'history'}
            or body['operation'] != 'resume_lookup' or not valid_uuid(body['request_id'], version=4)
            or body['request_id'] != expected_request_id or not _hex(body['version']) or body['version'] != expected_version
            or type(body['history']) is not dict):
        raise TransferError('file_sources_invalid_resume_history')
    value = body['history']
    fields = {'job_id', 'job_version', 'phase', 'source_id', 'transfer_id', 'manifest_sha256', 'remote_saved_history', 'attempt_phase'}
    tokens = {'attempt_id', 'attempt_sha256'}
    if (set(value) not in (fields, fields | tokens)
            or any(type(value[key]) is not str or re.fullmatch(r'[0-9a-f]{32}', value[key]) is None for key in ('job_id', 'source_id', 'transfer_id'))
            or not _hex(value['job_version']) or not _hex(value['manifest_sha256']) or value['phase'] not in ('sealed', 'retired')
            or value['source_id'] != expected_source_id or value['transfer_id'] != expected_transfer_id
            or value['manifest_sha256'] != expected_manifest_sha256 or type(value['remote_saved_history']) is not bool
            or value['attempt_phase'] not in (None, 'prepared', 'sent', 'accepted')):
        raise TransferError('file_sources_invalid_resume_history')
    if value['attempt_phase'] is None:
        if value.get('attempt_id') is not None or value.get('attempt_sha256') is not None:
            raise TransferError('file_sources_invalid_resume_history')
    elif (set(value) != fields | tokens or not valid_uuid(value['attempt_id'], version=4) or not _hex(value['attempt_sha256'])):
        raise TransferError('file_sources_invalid_resume_history')
    return SourceResumeHistory(body['request_id'], body['version'], **value)


def parse_run_result(message, *, expected_request_id, expected_operation, expected_version,
                     expected_run_id=None, now=None):
    body = _body(message, RUN_RESULT, now_ms() if now is None else now)
    if body.get('operation') in ('resume_run', 'resume_status', 'cancel_resume', 'offer_resume', 'end_resume'):
        if (any(type(body.get(key)) is not str for key in ('request_id', 'run_id'))
                or body['operation'] == 'offer_resume' and type(body.get('offer_id')) is not str
                or body['operation'] != 'resume_run' and type(expected_run_id) is not str):
            raise TransferError('file_sources_invalid_run_result')
    offering = body.get('operation') in ('offer_run', 'offer_resume')
    ending = body.get('operation') in ('end_run', 'end_resume')
    if (set(body) != {'format', 'request_id', 'operation', 'version', 'run_id', 'state', 'source_io_ended'} |
            ({'offer_id', 'manifest_sha256'} if offering else {'run_ended'} if ending else set())
            or not valid_uuid(body['request_id'], version=4) or body['request_id'] != expected_request_id
            or body['operation'] not in ('run', 'run_status', 'cancel_run', 'offer_run', 'end_run', 'resume_run', 'resume_status', 'cancel_resume', 'offer_resume', 'end_resume') or body['operation'] != expected_operation
            or not _hex(body['version']) or body['version'] != expected_version or not valid_uuid(body['run_id'], version=4)
            or body['operation'] not in ('run', 'resume_run') and (not valid_uuid(expected_run_id, version=4) or body['run_id'] != expected_run_id)
            or body['operation'] in ('run', 'resume_run') and expected_run_id is not None and body['run_id'] != expected_run_id
            or type(body['source_io_ended']) is not bool
            or body['state'] not in ('preparing', 'snapshot_ready', 'cancel_pending', 'canceled_held', 'failed_held')
            or body['source_io_ended'] != (body['state'] in ('snapshot_ready', 'canceled_held', 'failed_held'))
            or body['operation'] in ('cancel_run', 'cancel_resume') and body['state'] not in ('cancel_pending', 'canceled_held')
            or ending and (body['state'] != 'canceled_held' or body.get('run_ended') is not True)
            or offering and (body['state'] != 'snapshot_ready' or not valid_uuid(body['offer_id'], version=4)
                             or not _hex(body['manifest_sha256']))):
        raise TransferError('file_sources_invalid_run_result')
    return SourceRunResult(body['request_id'], body['operation'], body['version'], body['run_id'], body['state'],
                           body['source_io_ended'], body.get('offer_id'), body.get('manifest_sha256'), body.get('run_ended', False))
