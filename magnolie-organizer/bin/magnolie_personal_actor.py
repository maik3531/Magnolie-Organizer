"""Correlated manual Notes content starts; transport/ownership are caller gates.

The marker is intentionally not advertised until the actor staging path exists.
Existing v9 GUI starts keep their original independently generated run IDs.
"""
import copy
import uuid
import magnolie_shared_sync as shared
import magnolie_personal_sync as personal
import magnolie_content_scope as scope

VERSION = 12
START_KIND = "personal_sync.actor_start"
DATA_KIND = "personal_sync.actor_data"
DATA_KINDS = frozenset({"personal_sync.request", "personal_sync.batch", "personal_sync.report",
    "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
    "personal_sync.deletion_proposals", "personal_sync.deletion_decision", scope.DATA_KIND})


def is_reserved_message(value):
    return isinstance(value, dict) and value.get("type") == "message" and value.get("kind") in (START_KIND, DATA_KIND)


def validate_start(body):
    if not isinstance(body, dict) or set(body) != {"format", "run_id", "trigger"}:
        raise ValueError("Invalid actor start fields")
    if type(body["format"]) is not int or body["format"] != VERSION or body["trigger"] != "manual":
        raise ValueError("Invalid actor start format or trigger")
    value = body["run_id"]
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
    except (ValueError, AttributeError):
        parsed = None
    if parsed is None or parsed.version != 4 or str(parsed) != value:
        raise ValueError("Invalid actor run identity")
    return body


def start(run_id):
    return validate_start({"format": VERSION, "run_id": run_id, "trigger": "manual"})


def validate_data(value):
    if (not isinstance(value, dict) or set(value) != {"format", "run_id", "kind", "body"} or
            type(value.get("format")) is not int or value["format"] != VERSION or
            not isinstance(value.get("kind"), str) or value["kind"] not in DATA_KINDS or not isinstance(value.get("body"), dict)):
        raise ValueError("Invalid actor data envelope")
    start(value["run_id"])
    kind, body = value["kind"], value["body"]
    if kind == scope.DATA_KIND:
        scope.validate_data(body)
        record_body = body["body"]
    else:
        personal.validate_body(kind, body)
        record_body = body
    if (record_body.get("run_id") != value["run_id"] or
            "trigger" in record_body and record_body["trigger"] != "manual" or
            len(personal.canonical(value)) > personal.MAX_PACKET):
        raise ValueError("Actor data identity or size mismatch")
    return value


def wrap(run_id, kind, body):
    return validate_data({"format": VERSION, "run_id": run_id, "kind": kind, "body": copy.deepcopy(body)})


def unwrap(value):
    validate_data(value)
    return value["kind"], copy.deepcopy(value["body"])


def wire_message(message, run_id):
    """Caller validates the original header; preserve its ACK identity/lifetime."""
    result = copy.deepcopy(message)
    result["body"] = wrap(run_id, message["kind"], message["body"])
    result["kind"] = DATA_KIND
    return result


def semantic_message(message):
    """For explicit policy/ACK inspection, never for replacing a stored wire frame."""
    if message.get("kind") != DATA_KIND:
        return message
    kind, body = unwrap(message["body"])
    result = copy.deepcopy(message)
    result.update(kind=kind, body=body)
    return result


def supported(local, remote):
    return shared.supported(local, remote) and all(
        type(item.get("available")) is bool and item["available"] and any(type(value) is int and value == VERSION for value in item.get("versions", []))
        for values in (local, remote) for name in ("personal_notes_sync", "personal_tasks_sync")
        for item in (values.get(name, {}),))
