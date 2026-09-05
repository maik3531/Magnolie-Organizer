#!/usr/bin/env python3
"""Neutraler V1/V2-Kern fuer persoenlichen Sync ueber magnolie-phone/1."""

import base64
import hashlib
import json
import re
import uuid

FORMATS = [1, 2, 3]
FORMAT = 1
MAX_RECORDS = 32
MAX_PACKET = 192 * 1024
MAX_ID = 160
MAX_TEXT = 128 * 1024
MAX_TIMESTAMP = 253402300799999
MAX_SAFE_INTEGER = 9007199254740991
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"note", "task", "notebook"}
DELETION_KINDS = KINDS | {"attachment"}
CHUNK_RAW = 180000
MAX_ATTACHMENT = 8 * 1024 * 1024
MAX_ATTACHMENTS = 64
MIMES = {"image/jpeg": "image", "image/png": "image", "image/webp": "image",
         "image/gif": "image", "application/pdf": "pdf"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def projection_hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def records_hash(records):
    """Hash of one complete, deterministically ordered V2 direction."""
    keys = [(item.get("kind"), item.get("id")) for item in records]
    if keys != sorted(set(keys), key=lambda item: (item[0].encode(), item[1].encode())):
        raise ValueError("invalid personal sync record ordering")
    return hashlib.sha256(canonical(records)).hexdigest()


def mime_from_magic(raw):
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def decode_attachment_data_url(value):
    """Strict sender preflight. The returned bytes are suitable for snapshot staging."""
    if not isinstance(value, str) or len(value) > 12_000_000 or not value.startswith("data:"):
        raise ValueError("invalid attachment data URL")
    marker = ";base64,"
    split = value.find(marker)
    if split <= 5 or value.find(marker, split + 1) >= 0:
        raise ValueError("invalid attachment data URL")
    mime, encoded = value[5:split], value[split + len(marker):]
    if mime not in MIMES or not encoded or not re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", encoded):
        raise ValueError("invalid attachment data URL")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("invalid attachment base64") from error
    if not 1 <= len(raw) <= MAX_ATTACHMENT or base64.b64encode(raw).decode("ascii") != encoded:
        raise ValueError("invalid attachment size or base64")
    if mime_from_magic(raw) != mime:
        raise ValueError("attachment MIME mismatch")
    return mime, raw


def attachment_descriptor(attachment):
    """Build a V2 descriptor only after validating the actual data URL."""
    if not isinstance(attachment, dict):
        raise ValueError("invalid attachment")
    attachment_id, name = attachment.get("id"), attachment.get("name")
    mime, raw = decode_attachment_data_url(attachment.get("data", attachment.get("daten")))
    descriptor = {"attachment_id": attachment_id, "name": name,
                  "kind": MIMES[mime], "mime": mime, "size": len(raw),
                  "sha256": hashlib.sha256(raw).hexdigest()}
    validate_attachment_descriptor(descriptor)
    return descriptor, raw


def validate_attachment_descriptor(value):
    fields = {"attachment_id", "name", "kind", "mime", "size", "sha256"}
    if (not isinstance(value, dict) or set(value) != fields
            or not _identifier(value.get("attachment_id"))
            or "\0" in value["attachment_id"] or not _text(value.get("name"), 720)
            or not value["name"] or any(ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in value["name"])
            or value.get("mime") not in MIMES or value.get("kind") != MIMES.get(value.get("mime"))
            or isinstance(value.get("size"), bool) or not isinstance(value.get("size"), int)
            or not 1 <= value["size"] <= MAX_ATTACHMENT or not HASH.fullmatch(value.get("sha256", ""))):
        raise ValueError("invalid attachment descriptor")
    return value


def normalize_clock(clock):
    if not isinstance(clock, list) or not 1 <= len(clock) <= 16:
        raise ValueError("invalid personal sync clock")
    result = []
    previous = ""
    for item in clock:
        if (not isinstance(item, dict) or set(item) != {"actor_id", "counter"}
                or not UUID4.fullmatch(item.get("actor_id", ""))
                or isinstance(item.get("counter"), bool)
                or not isinstance(item.get("counter"), int)
                or not 1 <= item["counter"] <= MAX_SAFE_INTEGER
                or item["actor_id"].encode("utf-8") <= previous.encode("utf-8")):
            raise ValueError("invalid personal sync clock")
        previous = item["actor_id"]
        result.append({"actor_id": previous, "counter": item["counter"]})
    return result


def compare_clock(left, right):
    a = {item["actor_id"]: item["counter"] for item in normalize_clock(left)}
    b = {item["actor_id"]: item["counter"] for item in normalize_clock(right)}
    greater = any(a.get(key, 0) > b.get(key, 0) for key in a.keys() | b.keys())
    smaller = any(a.get(key, 0) < b.get(key, 0) for key in a.keys() | b.keys())
    if greater and smaller:
        return "concurrent"
    if greater:
        return "dominates"
    if smaller:
        return "dominated"
    return "equal"


def merge_clocks(left, right):
    values = {}
    for item in normalize_clock(left) + normalize_clock(right):
        values[item["actor_id"]] = max(values.get(item["actor_id"], 0), item["counter"])
    if len(values) > 16:
        raise ValueError("personal sync clock overflow")
    return [{"actor_id": key, "counter": values[key]}
            for key in sorted(values, key=lambda item: item.encode("utf-8"))]


def conflict_id(kind, original_id, loser_hash):
    raw = hashlib.sha256((kind + "\0" + original_id + "\0" + loser_hash).encode("utf-8")).digest()
    shaped = bytearray(raw[:16])
    shaped[6] = (shaped[6] & 0x0f) | 0x40
    shaped[8] = (shaped[8] & 0x3f) | 0x80
    return str(uuid.UUID(bytes=bytes(shaped)))


def deletion_proposal_id(peer_device_id, kind, entity_id, parent_id, clock, prior_hash):
    """Stable per-peer id; old peer tombstones cannot target a replacement peer."""
    normalize_clock(clock)
    if (not UUID4.fullmatch(peer_device_id) or kind not in DELETION_KINDS
            or not _identifier(entity_id) or not _identifier(parent_id, allow_empty=True)):
        raise ValueError("invalid deletion proposal identity")
    material = canonical([peer_device_id, kind, entity_id, parent_id, clock, prior_hash])
    raw = hashlib.sha256(b"personal-deletion-v1\0" + material).digest()
    shaped = bytearray(raw[:16])
    shaped[6] = (shaped[6] & 0x0f) | 0x40
    shaped[8] = (shaped[8] & 0x3f) | 0x80
    return str(uuid.UUID(bytes=bytes(shaped)))


def _text(value, maximum=MAX_TEXT):
    return isinstance(value, str) and len(value.encode("utf-8")) <= maximum


def _identifier(value, allow_empty=False):
    return (_text(value, MAX_ID) and "\0" not in value and value == value.strip()
            and (allow_empty or bool(value)))


def validate_value(kind, value, format=1):
    if not isinstance(value, dict):
        raise ValueError("invalid personal sync value")
    fields = {
        "note": {"title", "text", "html", "notebook_id", "symbol", "created_ms", "modified_ms"} |
                ({"attachments"} if format >= 2 else set()),
        "task": {"title", "note", "due", "priority", "completed", "remind", "lead_days",
                  "reminder_minute", "created_ms", "modified_ms"} |
                ({"uid", "parent_uid", "order"} if format == 3 else set()),
        "notebook": {"name", "modified_ms"},
    }[kind]
    if set(value) != fields:
        raise ValueError("invalid personal sync value fields")
    for name, item in value.items():
        if name == "attachments":
            if not isinstance(item, list) or len(item) > MAX_ATTACHMENTS:
                raise ValueError("invalid attachments")
            ids = []
            for descriptor in item:
                validate_attachment_descriptor(descriptor)
                ids.append(descriptor["attachment_id"])
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate attachment id")
            continue
        if name in {"created_ms", "modified_ms", "priority", "lead_days", "reminder_minute", "order"}:
            if (isinstance(item, bool) or not isinstance(item, int) or item < 0
                    or item > (MAX_TIMESTAMP if name.endswith("_ms") else MAX_SAFE_INTEGER)):
                raise ValueError("invalid personal sync number")
        elif name in {"completed", "remind"}:
            if not isinstance(item, bool):
                raise ValueError("invalid personal sync boolean")
        elif not _text(item, 160 if name in {"notebook_id", "symbol", "due", "uid", "parent_uid"} else MAX_TEXT):
            raise ValueError("invalid personal sync text")
        elif name in {"notebook_id", "uid", "parent_uid"} and item != item.strip():
            raise ValueError("invalid notebook id")
    if kind == "task" and (value["priority"] not in {1, 2, 3}
                            or value["lead_days"] > 365 or value["reminder_minute"] > 1439
                            or value["due"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["due"])):
        raise ValueError("invalid personal sync task")
    return value


def validate_record(record, format=1):
    fields = {"kind", "id", "state", "clock", "hash", "modified_ms", "value"}
    if (not isinstance(record, dict) or set(record) != fields or record.get("kind") not in KINDS
            or record.get("state") != "live" or not _identifier(record.get("id"))
            or not HASH.fullmatch(record.get("hash", ""))
            or isinstance(record.get("modified_ms"), bool) or not isinstance(record.get("modified_ms"), int)
            or not 0 <= record["modified_ms"] <= MAX_TIMESTAMP):
        raise ValueError("invalid personal sync record")
    normalize_clock(record["clock"])
    validate_value(record["kind"], record["value"], format)
    if projection_hash(record["value"]) != record["hash"] or record["modified_ms"] != record["value"]["modified_ms"]:
        raise ValueError("invalid personal sync record hash")
    return record


def validate_body(kind, body):
    if not isinstance(body, dict):
        raise ValueError("invalid personal sync body")
    if kind == "personal_sync.settings":
        if set(body) != {"format", "own_device"} or body.get("format") != FORMAT or not isinstance(body.get("own_device"), bool):
            raise ValueError("invalid personal sync settings")
    elif kind == "personal_sync.request":
        if (set(body) != {"format", "run_id", "trigger", "modules"} or body.get("format") not in FORMATS
                or not UUID4.fullmatch(body.get("run_id", "")) or body.get("trigger") not in {"manual", "auto_wifi"}
                or body.get("modules") not in (["notes"], ["tasks"], ["notes", "tasks"])):
            raise ValueError("invalid personal sync request")
    elif kind == "personal_sync.batch":
        format = body.get("format")
        fields = {"format", "run_id", "batch_id", "sequence", "last", "reply", "records"} | ({"records_hash"} if format >= 2 else set())
        if (set(body) != fields or format not in FORMATS
                or not UUID4.fullmatch(body.get("run_id", ""))
                or not UUID4.fullmatch(body.get("batch_id", ""))
                or isinstance(body.get("sequence"), bool) or not isinstance(body.get("sequence"), int)
                or not 0 <= body["sequence"] <= 100000 or not isinstance(body.get("last"), bool)
                or not isinstance(body.get("reply"), bool) or not isinstance(body.get("records"), list)
                or len(body["records"]) > MAX_RECORDS):
            raise ValueError("invalid personal sync batch")
        keys = []
        for record in body["records"]:
            validate_record(record, format)
            keys.append((record["kind"], record["id"]))
        ordered = sorted(set(keys), key=lambda item: (item[0].encode("utf-8"), item[1].encode("utf-8")))
        if keys != ordered or len(canonical(body)) > MAX_PACKET or (format >= 2 and not HASH.fullmatch(body.get("records_hash", ""))):
            raise ValueError("invalid personal sync batch ordering")
    elif kind == "personal_sync.report":
        format = body.get("format")
        fields = {"format", "run_id", "state", "trigger", "transport", "sent", "received",
                   "conflicts", "attachments_omitted", "oversized_skipped", "started_ms", "finished_ms", "error",
                   "deletions"}
        if format >= 2:
            fields.add("attachments")
        if set(body) != fields or format not in FORMATS or not UUID4.fullmatch(body.get("run_id", "")):
            raise ValueError("invalid personal sync report")
        if body.get("state") not in {"complete", "partial", "blocked", "failed"} or body.get("trigger") not in {"manual", "auto_wifi"} or body.get("transport") not in {"wifi", "bluetooth"}:
            raise ValueError("invalid personal sync report state")
        counts = {"notes", "tasks", "notebooks"}
        if any(not isinstance(body.get(name), int) or isinstance(body.get(name), bool) or body[name] < 0
               or body[name] > (MAX_TIMESTAMP if name.endswith("_ms") else MAX_SAFE_INTEGER)
               for name in {"conflicts", "attachments_omitted", "oversized_skipped", "started_ms", "finished_ms"}):
            raise ValueError("invalid personal sync report count")
        if (any(not isinstance(body.get(name), dict) or set(body[name]) != counts or any(
                 not isinstance(number, int) or isinstance(number, bool) or
                 not 0 <= number <= MAX_SAFE_INTEGER for number in body[name].values())
               for name in {"sent", "received"}) or body.get("error") not in {
                   "none", "offline", "not_granted", "too_large", "save_failed", "protocol", "unknown"}
                 or body["finished_ms"] < body["started_ms"]):
            raise ValueError("invalid personal sync report counters")
        if format >= 2:
            attachments = body["attachments"]
            names = {"declared", "requested", "sent", "received", "reused", "preserved", "failed", "bytes"}
            if (not isinstance(attachments, dict) or set(attachments) != names or any(
                    isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= MAX_SAFE_INTEGER
                    for number in attachments.values())):
                raise ValueError("invalid attachment report")
        deletions = body["deletions"]
        if (not isinstance(deletions, dict) or set(deletions) != {
                "pending", "deleted", "restored", "conflicts", "blocked", "trash"}):
            raise ValueError("invalid deletion report")
        trash = deletions.get("trash")
        if (not isinstance(trash, dict) or set(trash) != {"notes", "tasks", "notebooks", "attachments"}
                or any(isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= MAX_SAFE_INTEGER
                       for number in trash.values())
                or any(isinstance(deletions[name], bool) or not isinstance(deletions[name], int)
                       or not 0 <= deletions[name] <= MAX_SAFE_INTEGER
                       for name in {"pending", "deleted", "restored", "conflicts", "blocked"})):
            raise ValueError("invalid deletion report counters")
    elif kind == "personal_sync.attachment_request":
        fields = {"format", "run_id", "reply", "records_hash", "wants"}
        if (set(body) != fields or body.get("format") != 2 or not UUID4.fullmatch(body.get("run_id", ""))
                or not isinstance(body.get("reply"), bool) or not HASH.fullmatch(body.get("records_hash", ""))
                or not isinstance(body.get("wants"), list) or not 1 <= len(body["wants"]) <= 64):
            raise ValueError("invalid attachment request")
        hashes = []
        for want in body["wants"]:
            if (not isinstance(want, dict) or set(want) != {"sha256", "ranges"}
                    or not HASH.fullmatch(want.get("sha256", "")) or not isinstance(want.get("ranges"), list)
                    or not 1 <= len(want["ranges"]) <= 128):
                raise ValueError("invalid attachment want")
            previous = -1
            for pair in want["ranges"]:
                if (not isinstance(pair, list) or len(pair) != 2 or any(isinstance(n, bool) or not isinstance(n, int) for n in pair)
                        or not 0 <= pair[0] < pair[1] <= 47 or pair[0] < previous):
                    raise ValueError("invalid attachment ranges")
                previous = pair[1]
            hashes.append(want["sha256"])
        if hashes != sorted(set(hashes), key=lambda item: item.encode()):
            raise ValueError("invalid attachment want ordering")
    elif kind == "personal_sync.attachment_chunk":
        fields = {"format", "run_id", "reply", "records_hash", "sha256", "index", "data"}
        if (set(body) != fields or body.get("format") != 2 or not UUID4.fullmatch(body.get("run_id", ""))
                or not isinstance(body.get("reply"), bool) or not HASH.fullmatch(body.get("records_hash", ""))
                or not HASH.fullmatch(body.get("sha256", "")) or isinstance(body.get("index"), bool)
                or not isinstance(body.get("index"), int) or not 0 <= body["index"] < 47
                or not isinstance(body.get("data"), str)):
            raise ValueError("invalid attachment chunk")
        try:
            raw = base64.b64decode(body["data"], validate=True)
        except ValueError as error:
            raise ValueError("invalid attachment chunk base64") from error
        if not raw or len(raw) > CHUNK_RAW or base64.b64encode(raw).decode("ascii") != body["data"] or len(canonical(body)) > MAX_PACKET:
            raise ValueError("invalid attachment chunk size")
    elif kind == "personal_sync.attachment_result":
        fields = {"format", "run_id", "reply", "records_hash", "sha256", "state", "error"}
        if (set(body) != fields or body.get("format") != 2 or not UUID4.fullmatch(body.get("run_id", ""))
                or not isinstance(body.get("reply"), bool) or not HASH.fullmatch(body.get("records_hash", ""))
                or not HASH.fullmatch(body.get("sha256", "")) or body.get("state") not in {"complete", "failed"}
                or body.get("error") not in {"none", "not_found", "invalid", "too_large", "save_failed"}
                or (body["state"] == "complete") != (body["error"] == "none")):
            raise ValueError("invalid attachment result")
    elif kind == "personal_sync.deletion_proposals":
        fields = {"format", "run_id", "proposal_batch_id", "sequence", "last", "proposals"}
        if (set(body) != fields or body.get("format") != 1
                or not UUID4.fullmatch(body.get("run_id", ""))
                or not UUID4.fullmatch(body.get("proposal_batch_id", ""))
                or isinstance(body.get("sequence"), bool) or not isinstance(body.get("sequence"), int)
                or not 0 <= body["sequence"] <= 100000 or not isinstance(body.get("last"), bool)
                or not isinstance(body.get("proposals"), list) or len(body["proposals"]) > MAX_RECORDS):
            raise ValueError("invalid deletion proposals")
        ids = []
        for proposal in body["proposals"]:
            exact = {"proposal_id", "kind", "id", "parent_id", "clock", "prior_hash", "deleted_ms", "label"}
            if (not isinstance(proposal, dict) or set(proposal) != exact
                    or not UUID4.fullmatch(proposal.get("proposal_id", ""))
                    or proposal.get("kind") not in DELETION_KINDS
                    or not _identifier(proposal.get("id"))
                    or not _identifier(proposal.get("parent_id"), allow_empty=True)
                    or (proposal["kind"] == "attachment") != bool(proposal["parent_id"])
                    or not HASH.fullmatch(proposal.get("prior_hash", ""))
                    or isinstance(proposal.get("deleted_ms"), bool) or not isinstance(proposal.get("deleted_ms"), int)
                    or not 0 <= proposal["deleted_ms"] <= MAX_TIMESTAMP
                    or not _text(proposal.get("label"), 240)
                    or any(ord(char) < 32 or ord(char) == 127 for char in proposal["label"])):
                raise ValueError("invalid deletion proposal")
            normalize_clock(proposal["clock"]); ids.append(proposal["proposal_id"])
        if ids != sorted(set(ids), key=lambda item: item.encode("utf-8")) or len(canonical(body)) > MAX_PACKET:
            raise ValueError("invalid deletion proposal ordering")
    elif kind == "personal_sync.deletion_decision":
        fields = {"format", "run_id", "decision_id", "decisions"}
        if (set(body) != fields or body.get("format") != 1
                or not UUID4.fullmatch(body.get("run_id", ""))
                or not UUID4.fullmatch(body.get("decision_id", ""))
                or not isinstance(body.get("decisions"), list)
                or not 1 <= len(body["decisions"]) <= MAX_RECORDS):
            raise ValueError("invalid deletion decision")
        ids = []
        for decision in body["decisions"]:
            if (not isinstance(decision, dict) or set(decision) != {"proposal_id", "decision", "expected_clock"}
                    or not UUID4.fullmatch(decision.get("proposal_id", ""))
                    or decision.get("decision") not in {"delete", "restore"}):
                raise ValueError("invalid deletion decision")
            normalize_clock(decision["expected_clock"]); ids.append(decision["proposal_id"])
        if ids != sorted(set(ids), key=lambda item: item.encode("utf-8")) or len(canonical(body)) > MAX_PACKET:
            raise ValueError("invalid deletion decision ordering")
    else:
        raise ValueError("unknown personal sync kind")
    return body
