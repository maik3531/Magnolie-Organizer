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


def parse_command(message, *, now=None):
    body = _body(message, REQUEST, now_ms() if now is None else now)
    base = {"format", "operation"}
    if body.get("operation") == "status" and set(body) == base:
        return SourceCommand(message["message_id"], "status")
    if (body.get("operation") != "configure" or set(body) != base | {"expected_version", "enabled", "kinds"}
            or not _hex(body["expected_version"]) or type(body["enabled"]) is not bool):
        raise TransferError("file_sources_invalid_command")
    kinds = _kinds(body["kinds"])
    if body["enabled"] and not kinds:
        raise TransferError("file_sources_invalid_command")
    return SourceCommand(message["message_id"], "configure", body["expected_version"], body["enabled"], kinds)


def create_command(operation, *, expected_version=None, enabled=None, kinds=(), now=None, message_id=None):
    at = now_ms() if now is None else now
    if type(at) is not int:
        raise TransferError("file_sources_invalid_time")
    body = {"format": 1, "operation": operation}
    if operation == "configure":
        if type(kinds) is not tuple:
            raise TransferError("file_sources_invalid_kinds")
        body.update(expected_version=expected_version, enabled=enabled, kinds=list(kinds))
    elif expected_version is not None or enabled is not None or kinds != ():
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
