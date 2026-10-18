"""Correlated manual Notes content starts; transport/ownership are caller gates.

The marker is intentionally not advertised until the actor staging path exists.
Existing v9 GUI starts keep their original independently generated run IDs.
"""
import uuid
import magnolie_shared_sync as shared

VERSION = 12
START_KIND = "personal_sync.actor_start"


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


def supported(local, remote):
    return shared.supported(local, remote) and all(
        type(item.get("available")) is bool and item["available"] and any(type(value) is int and value == VERSION for value in item.get("versions", []))
        for values in (local, remote) for name in ("personal_notes_sync", "personal_tasks_sync")
        for item in (values.get(name, {}),))
