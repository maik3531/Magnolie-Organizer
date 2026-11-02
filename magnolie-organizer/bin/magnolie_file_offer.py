"""Complete immutable offer preflight (#329), not an enabled transfer handler.

No stores, listeners, grants, destination selection or filesystem operations.
The caller supplies actual authenticated peer IDs, not IDs inferred from wire.
"""
import uuid

from magnolie_file_transfer import FileManifest, TransferError
from magnolie_telefon import APPLICATION_MAX, CLOCK_SKEW_MS, canonical, now_ms, valid_uuid

KIND = "file_transfer.offer"
MAX_TTL_MS = 60_000


def create_offer(manifest, *, now=None, message_id=None, ttl_ms=MAX_TTL_MS):
    if type(manifest) is not FileManifest or type(ttl_ms) is not int or not 1 <= ttl_ms <= MAX_TTL_MS:
        raise TransferError("file_offer_invalid_ttl_or_manifest")
    now = now_ms() if now is None else now
    message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()) if message_id is None else message_id,
               "kind": KIND, "created_ms": now, "expires_ms": now + ttl_ms,
               "body": {"version": 1, "manifest": manifest.wire(), "manifest_sha256": manifest.fingerprint}}
    validate_offer(message, manifest.sender_id, manifest.receiver_id, now=now)
    return message


def validate_offer(message, sender_id, receiver_id, *, now=None):
    # The normal bounded strict/canonical transport decoder runs before this.
    if len(canonical(message)) > APPLICATION_MAX:
        raise TransferError("file_offer_envelope_too_large")
    now = now_ms() if now is None else now
    if (type(message) is not dict or set(message) != {
            "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body"}
            or message["type"] != "message" or type(message["v"]) is not int or message["v"] != 1
            or not valid_uuid(message["message_id"], version=4) or message["kind"] != KIND
            or type(message["created_ms"]) is not int or not 0 <= message["created_ms"] <= 253_402_300_799_999
            or type(message["expires_ms"]) is not int
            or not 1 <= message["expires_ms"] - message["created_ms"] <= MAX_TTL_MS
            or now > message["expires_ms"] + CLOCK_SKEW_MS or message["created_ms"] > now + CLOCK_SKEW_MS):
        raise TransferError("file_offer_invalid_envelope")
    body = message["body"]
    if (type(body) is not dict or set(body) != {"version", "manifest", "manifest_sha256"}
            or type(body["version"]) is not int or body["version"] != 1):
        raise TransferError("file_offer_invalid_envelope")
    manifest = FileManifest.parse(body["manifest"])
    if (manifest.sender_id != sender_id or manifest.receiver_id != receiver_id
            or body["manifest_sha256"] != manifest.fingerprint):
        raise TransferError("file_offer_manifest_binding_changed")
    return manifest
