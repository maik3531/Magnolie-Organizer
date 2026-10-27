"""One set of start vectors shared by the Kotlin, C# and Python contracts."""
import copy
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "magnolie-organizer/bin"))
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
import magnolie_phone_ack as phone_ack

VECTORS = json.loads((ROOT / "magnolie-notes/app/src/test/resources/notes-actor-start.json").read_text())["cases"]
DATA_VECTORS = json.loads((ROOT / "magnolie-notes/app/src/test/resources/notes-actor-data.json").read_text())["cases"]
ACK_VECTORS = json.loads((ROOT / "magnolie-notes/app/src/test/resources/notes-actor-ack.json").read_text())["cases"]
CANCEL_VECTORS = json.loads((ROOT / "magnolie-notes/app/src/test/resources/notes-actor-cancel.json").read_text())["cases"]


@pytest.mark.parametrize("case", VECTORS, ids=lambda case: case["name"])
def test_shared_start_vector(case):
    if case["valid"]:
        assert actor.validate_start(case["body"]) == case["body"]
        assert actor.start(case["body"]["run_id"]) == case["body"]
    else:
        with pytest.raises(ValueError):
            actor.validate_start(case["body"])


def test_declared_support_requires_shared_and_actor_markers_for_both_modules_and_peers():
    values = {name: {"available": True, "versions": [9, 12]} for name in ("personal_notes_sync", "personal_tasks_sync")}
    assert actor.supported(values, values)
    for name in values:
        for versions in ([9], [12], [9, 12.0]):
            missing = copy.deepcopy(values); missing[name]["versions"] = versions
            assert not actor.supported(values, missing) and not actor.supported(missing, values)
        unavailable = copy.deepcopy(values); unavailable[name]["available"] = False
        assert not actor.supported(values, unavailable)


@pytest.mark.parametrize("case", DATA_VECTORS, ids=lambda case: case["name"])
def test_shared_actor_data_vector_and_roundtrip(case):
    body = case["body"]
    if not case["valid"]:
        with pytest.raises(ValueError):
            actor.validate_data(body)
        return
    assert actor.validate_data(body) == body
    assert actor.wrap(body["run_id"], body["kind"], body["body"]) == body
    kind, original = actor.unwrap(body)
    assert kind == body["kind"] and original == body["body"]
    original["owned_mutation"] = True
    assert "owned_mutation" not in body["body"]


@pytest.mark.parametrize("case", ACK_VECTORS, ids=lambda case: case["name"])
def test_shared_actor_ack_and_existing_transport_schema(case):
    body = case["body"]
    if not case["valid"]:
        with pytest.raises(ValueError):
            actor.validate_ack(body)
        return
    assert actor.validate_ack(body) == body
    assert actor.ack(body["run_id"], body["message_id"], body["status"], body["error"]) == body
    assert phone_ack.validate({"type": "ack", **{key: body[key] for key in ("message_id", "status", "error")}})
    assert actor.is_reserved_message({"type": "message", "kind": actor.ACK_KIND, "body": body})
    with pytest.raises(ValueError):
        actor.wrap(body["run_id"], actor.ACK_KIND, body)


def test_actor_wire_budget_preserves_inner_limits_and_includes_header_overhead():
    fixture = json.loads((ROOT / "magnolie-notes/app/src/test/resources/notes-actor-data.json").read_text())["wire_budget"]
    run = "11111111-1111-4111-8111-111111111111"
    def record(name, length):
        value = copy.deepcopy(fixture["value"]); value["text"] = "A" * length
        return {"kind": "note", "id": name, "state": "live", "clock": [{"actor_id": run, "counter": 1}],
            "hash": personal.projection_hash(value), "modified_ms": 0, "value": value}
    records = [record("note-a", 128 * 1024), record("note-b", 0)]
    body = {"format": 1, "run_id": run, "batch_id": "33333333-3333-4333-8333-333333333333", "sequence": 0, "last": True, "reply": False, "records": records}
    message = {"type": "message", "v": 1, "message_id": "22222222-2222-4222-8222-222222222222", "kind": "personal_sync.batch",
        "created_ms": 1700000000000, "expires_ms": 1700000060000, "body": body}
    records[1] = record("note-b", fixture["portable_body_bytes"] - len(personal.canonical(body)))
    assert len(personal.canonical(body)) == fixture["portable_body_bytes"]
    portable = actor.wire_message(message, run)
    assert len(personal.canonical(portable)) > 192 * 1024 and len(personal.canonical(portable)) <= personal.MAX_PACKET
    # The former Python-only larger acceptance is now rejected at the shared
    # inner limit, before an actor envelope could exceed the full wire budget.
    records[1] = record("note-b", 0)
    records[1] = record("note-b", fixture["python_original_bytes"] - len(personal.canonical(message)))
    assert len(personal.canonical(message)) == fixture["python_original_bytes"]
    assert len(personal.canonical(body)) > personal.MAX_BATCH_BODY
    with pytest.raises(ValueError):
        personal.validate_body("personal_sync.batch", body)
    with pytest.raises(ValueError):
        actor.wrap(run, "personal_sync.batch", body)
    with pytest.raises(ValueError):
        actor.wire_message(message, run)


@pytest.mark.parametrize("case", CANCEL_VECTORS, ids=lambda case: case["name"])
def test_shared_actor_cancel_is_control_not_nested_data(case):
    body = case["body"]
    if not case["valid"]:
        with pytest.raises(ValueError):
            actor.validate_cancel(body)
        return
    assert actor.validate_cancel(body) == body and actor.cancel(body["run_id"]) == body
    assert actor.is_reserved_message({"type": "message", "kind": actor.CANCEL_KIND, "body": body})
    with pytest.raises(ValueError):
        actor.wrap(body["run_id"], actor.CANCEL_KIND, body)
