"""Persist the explicit wire marker, independently of volatile actor ownership."""
import json
import sqlite3
import pytest
from test_mcp_phone import owned_service
import magnolie_telefon as phone
import magnolie_personal_actor as actor


RUN = "11111111-1111-4111-8111-111111111111"
REQUEST = {"format": 3, "run_id": RUN, "trigger": "manual", "modules": ["notes", "tasks"]}


def test_encrypted_outbox_reopen_keeps_wire_actor_and_semantic_queue_kind(tmp_path):
    service, peer, events = owned_service(tmp_path)
    store = service.store
    wire = store.queue(peer["device_id"], "personal_sync.request", REQUEST, 60000, actor_run_id=RUN)
    assert wire["kind"] == actor.DATA_KIND and actor.unwrap(wire["body"]) == ("personal_sync.request", REQUEST)
    with sqlite3.connect(store.database_path) as db:
        row = db.execute("SELECT message_id,kind,created_ms,expires_ms,payload FROM outbox").fetchone()
    assert row[:4] == (wire["message_id"], "personal_sync.request", wire["created_ms"], wire["expires_ms"])
    assert json.loads(store._decrypt(row[4], "outbox", wire["message_id"])) == wire
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Owned desktop")
    assert reopened.pending(peer["device_id"]) == [wire]
    decision_id = "44444444-4444-4444-8444-444444444444"
    decision = {"format": 1, "run_id": RUN, "decision_id": decision_id, "decisions": [{
        "proposal_id": "55555555-5555-4555-8555-555555555555", "decision": "restore",
        "expected_clock": [{"actor_id": "66666666-6666-4666-8666-666666666666", "counter": 1}]}]}
    decision_wire = reopened.queue(peer["device_id"], "personal_sync.deletion_decision", decision, 60000, actor_run_id=RUN)
    assert reopened.acknowledge(peer["device_id"], decision_wire["message_id"]) == decision_id
    assert reopened.pending(peer["device_id"]) == [wire]
    reopened.acknowledge(peer["device_id"], wire["message_id"])
    assert reopened.pending(peer["device_id"]) == []
    assert not events and service.server is None


def test_legacy_queue_and_invalid_actor_selection_do_not_mix(tmp_path):
    service, peer, events = owned_service(tmp_path)
    store = service.store
    ordinary = store.queue(peer["device_id"], "personal_sync.request", REQUEST, 60000)
    assert ordinary["kind"] == "personal_sync.request" and ordinary["body"] == REQUEST
    for kind, body, run in [
        ("personal_sync.request", REQUEST, "22222222-2222-4222-8222-222222222222"),
        ("personal_sync.settings", {"format": 1, "own_device": True}, RUN),
        (actor.START_KIND, actor.start(RUN), RUN),
    ]:
        with pytest.raises(ValueError):
            store.queue(peer["device_id"], kind, body, 60000, actor_run_id=run)
    assert store.pending(peer["device_id"]) == [ordinary] and not events
