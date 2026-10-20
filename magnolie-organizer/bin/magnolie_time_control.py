"""Negotiated native Notes timer commands (v13), never TimeSync record writes."""
import re
from magnolie_time_sync import _exact, _number, _text, _uuid, validate_record, MAX_MINUTE, MAX_COUNTER

VERSION = 13
REQUEST = "time_tracking.control_request"
REPORT = "time_tracking.control_report"
KINDS = frozenset((REQUEST, REPORT))
MAX_WIRE = 192 * 1024
HASH = re.compile(r"[a-f0-9]{64}\Z")
ERRORS = frozenset(("none", "not_granted", "unsupported_feature", "conflict", "no_running_entry", "already_running", "save_failed", "protocol", "unknown"))
REQUEST_FIELDS = frozenset(("format", "request_id", "action", "operation_id", "expected_revision", "restore_epoch", "entry_id", "activity", "note"))
REPORT_FIELDS = frozenset(("format", "request_id", "operation_id", "status", "error", "restore_epoch", "revision", "enabled", "entries", "paused",
                          "server_minute", "operation_applied", "persisted", "applied_entry_id", "applied_clock", "runtime_request"))


def _hash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("invalid_timer_revision")


def validate_request(body):
    _exact(body, REQUEST_FIELDS); _number(body["format"], VERSION, VERSION); _uuid(body["request_id"])
    _text(body["restore_epoch"], 256)
    action = body["action"]
    if action == "read":
        if any(body[key] != "" for key in REQUEST_FIELDS - {"format", "request_id", "action"}):
            raise ValueError("timer_read_must_not_mutate")
    else:
        if action not in ("start", "pause", "resume", "finish"):
            raise ValueError("invalid_timer_action")
        _uuid(body["operation_id"]); _hash(body["expected_revision"])
        _text(body["activity"], 120); _text(body["note"], 20000)
        if action == "start":
            if body["entry_id"] != "": raise ValueError("invalid_timer_start_identity")
        else:
            _uuid(body["entry_id"])
            if body["activity"] != "" or body["note"] != "": raise ValueError("timer_control_must_not_edit")
    return body


def request(request_id, action="read", *, operation_id="", expected_revision="", restore_epoch="", entry_id="", activity="", note=""):
    return validate_request(dict(format=VERSION, request_id=request_id, action=action, operation_id=operation_id,
        expected_revision=expected_revision, restore_epoch=restore_epoch, entry_id=entry_id, activity=activity, note=note))


def validate_report(body):
    _exact(body, REPORT_FIELDS); _number(body["format"], VERSION, VERSION); _uuid(body["request_id"])
    operation = body["operation_id"]
    if operation != "": _uuid(operation)
    if body["status"] not in ("ok", "duplicate", "rejected") or not isinstance(body["error"], str) or body["error"] not in ERRORS:
        raise ValueError("invalid_timer_outcome")
    _text(body["restore_epoch"], 256); _number(body["server_minute"], 0, MAX_MINUTE)
    if any(type(body[key]) is not bool for key in ("enabled", "paused", "operation_applied", "persisted")):
        raise ValueError("invalid_timer_boolean")
    if not isinstance(body["entries"], list) or len(body["entries"]) > 1 or not isinstance(body["applied_clock"], dict):
        raise ValueError("invalid_timer_state")
    if body["runtime_request"] not in ("none", "requested", "failed"):
        raise ValueError("invalid_timer_runtime_outcome")
    if body["status"] == "rejected":
        if (body["error"] == "none" or any(body[key] for key in ("restore_epoch", "revision", "enabled", "entries", "paused", "server_minute",
                "operation_applied", "persisted", "applied_entry_id", "applied_clock")) or body["runtime_request"] != "none"):
            raise ValueError("rejected_timer_data_or_save_claim")
        return body
    _hash(body["revision"])
    if body["error"] != "none": raise ValueError("invalid_timer_success_error")
    for record in body["entries"]:
        validate_record(record)
        if record["deleted"] or record["endMinute"] is not None: raise ValueError("timer_status_must_be_running")
    if not body["entries"] and body["paused"]: raise ValueError("paused_timer_missing")
    if operation == "":
        if (body["status"] != "ok" or body["operation_applied"] or body["persisted"] or body["applied_entry_id"] or body["applied_clock"] or body["runtime_request"] != "none"):
            raise ValueError("timer_read_claimed_command")
    else:
        if not body["operation_applied"] or not body["persisted"] or not 1 <= len(body["applied_clock"]) <= 32:
            raise ValueError("timer_save_proof_missing")
        _uuid(body["applied_entry_id"])
        for actor, count in body["applied_clock"].items(): _uuid(actor); _number(count, 1, MAX_COUNTER)
    return body
