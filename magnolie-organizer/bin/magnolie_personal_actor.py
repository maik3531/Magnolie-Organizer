"""Correlated manual Notes content starts; transport/ownership are caller gates.

The marker is intentionally not advertised until the actor staging path exists.
Existing v9 GUI starts keep their original independently generated run IDs.
"""
import copy
import uuid
import magnolie_shared_sync as shared
import magnolie_personal_sync as personal
import magnolie_content_scope as scope
import magnolie_phone_ack as phone_ack

VERSION = 12
START_KIND = "personal_sync.actor_start"
DATA_KIND = "personal_sync.actor_data"
ACK_KIND = "personal_sync.actor_ack"
CANCEL_KIND = "personal_sync.actor_cancel"
RESERVED_KINDS = frozenset({START_KIND, DATA_KIND, ACK_KIND, CANCEL_KIND})
STORAGE_PEER_PREFIX = "@mcp-actor-"
DATA_KINDS = frozenset({"personal_sync.request", "personal_sync.batch", "personal_sync.report",
    "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
    "personal_sync.deletion_proposals", "personal_sync.deletion_decision", scope.DATA_KIND})


def is_reserved_message(value):
    return isinstance(value, dict) and value.get("type") == "message" and is_reserved_kind(value.get("kind"))


def is_reserved_kind(kind):
    return isinstance(kind, str) and kind in RESERVED_KINDS


def storage_peer(run_id):
    start(run_id)
    return STORAGE_PEER_PREFIX + run_id


def is_storage_peer(value):
    return isinstance(value, str) and value.startswith(STORAGE_PEER_PREFIX)


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


def validate_ack(body):
    if not isinstance(body, dict) or set(body) != {"format", "run_id", "message_id", "status", "error"} or type(body.get("format")) is not int or body["format"] != VERSION:
        raise ValueError("Invalid actor acknowledgement fields")
    start(body["run_id"])
    phone_ack.validate({"type": "ack", "message_id": body["message_id"], "status": body["status"], "error": body["error"]})
    return body


def ack(run_id, message_id, status="accepted", error="none"):
    return validate_ack({"format": VERSION, "run_id": run_id, "message_id": message_id, "status": status, "error": error})


def validate_cancel(body):
    if not isinstance(body, dict) or set(body) != {"format", "run_id"} or type(body.get("format")) is not int or body["format"] != VERSION:
        raise ValueError("Invalid actor cancellation fields")
    start(body["run_id"])
    return body


def cancel(run_id):
    return validate_cancel({"format": VERSION, "run_id": run_id})


def deletion_review(run_id, plan, native_intents):
    """Bind a private review to native staged tokens; this grants no save/scope right."""
    start(run_id)
    if not isinstance(native_intents, list) or len(native_intents) > 256:
        raise ValueError("invalid_actor_deletion_review")
    references, proposals = {}, {}
    for intent in native_intents:
        if not isinstance(intent, dict) or set(intent) != {"kind", "message_id", "commit_token", "body"}:
            raise ValueError("invalid_actor_native_intent")
        kind, body = intent["kind"], intent["body"]
        if kind not in ("personal_sync.deletion_proposals", "personal_sync.deletion_decision"):
            raise ValueError("invalid_actor_native_intent")
        personal.validate_body(kind, body)
        if body["run_id"] != run_id:
            raise ValueError("actor_deletion_run_changed")
        reference = {key:intent[key] for key in ("kind", "message_id", "commit_token")}
        # The owner token is an opaque native capability, never wire authority.
        phone_ack.validate({"type":"ack", "message_id":reference["message_id"], "status":"accepted", "error":"none"})
        token = reference["commit_token"]
        if not isinstance(token, str) or not token or len(token.encode("utf-8")) > 256 or reference["message_id"] in references:
            raise ValueError("invalid_actor_native_intent")
        references[reference["message_id"]] = reference
        if kind == "personal_sync.deletion_proposals":
            for proposal in body["proposals"]:
                if proposal["kind"] not in {"note", "task", "attachment"}:
                    raise ValueError("actor_deletion_kind_not_supported")
                identity = proposal["proposal_id"]
                if identity in proposals and personal.canonical(proposals[identity]) != personal.canonical(proposal):
                    raise ValueError("actor_deletion_proposal_changed")
                proposals[identity] = proposal
    if plan is None and not native_intents:
        return {"choices":[], "intents":[]}
    if (not isinstance(plan, dict) or set(plan) != {"choices", "intents"} or
            not isinstance(plan["choices"], list) or len(plan["choices"]) > 256 or
            not isinstance(plan["intents"], list) or len(plan["intents"]) != len(references)):
        raise ValueError("actor_deletion_review_required")
    reviewed = {}
    for reference in plan["intents"]:
        if (not isinstance(reference, dict) or set(reference) != {"kind", "message_id", "commit_token"} or
                not isinstance(reference.get("message_id"), str) or reference["message_id"] in reviewed or
                reference != references.get(reference["message_id"])):
            raise ValueError("actor_deletion_intent_changed")
        reviewed[reference["message_id"]] = reference
    choices = {}
    for choice in plan["choices"]:
        if (not isinstance(choice, dict) or set(choice) != {"proposal_id", "decision", "expected_clock", "allow_conflict"} or
                not isinstance(choice.get("proposal_id"), str) or choice["proposal_id"] in choices or
                choice["proposal_id"] not in proposals or not isinstance(choice["decision"], str) or choice["decision"] not in {"delete", "restore"} or
                type(choice["allow_conflict"]) is not bool or
                personal.canonical(choice["expected_clock"]) != personal.canonical(proposals[choice["proposal_id"]]["clock"])):
            raise ValueError("actor_deletion_choice_changed")
        choices[choice["proposal_id"]] = choice
    if set(choices) != set(proposals):
        raise ValueError("actor_deletion_choice_missing")
    return copy.deepcopy({"choices":[choices[key] for key in sorted(choices)], "intents":[reviewed[key] for key in sorted(reviewed)]})


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
    if len(personal.canonical(result)) > personal.MAX_PACKET:
        raise ValueError("Actor wire frame too large")
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
