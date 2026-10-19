"""Native actor dispatch and existing private-domain staging, without GUI adoption."""
import sqlite3
import uuid
import base64
import hashlib
import io
import pytest
from test_personal_actor_source import actor_source_fixture
import magnolie_telefon as phone
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal


def frame(kind, body):
    return phone.PhoneService._actor_control_message(kind, body)


def owned_transport(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, _ = actor_source_fixture(tmp_path, monkeypatch)
    service.native_actor_book_source = lambda: "a" * 64
    registry = service.personal_actor_registry()
    handle = registry.create(peer["device_id"], fingerprint, service.current_actor_source(peer["device_id"], fingerprint))
    original_send = channel.send
    def send(value):
        assert not service.lock._is_owned(), "Actor network write held the service/source guard"
        original_send(value)
    channel.send = send
    events = []; service.callback = lambda *event: events.append(event)
    channel.sent.clear()
    return service, peer, channel, registry, handle, events


def record(identifier="note-one"):
    value = {"title": "Owned phone snapshot", "text": "Only staged", "html": "", "notebook_id": "", "symbol": "note",
        "created_ms": 1, "modified_ms": 2, "attachments": []}
    return {"kind": "note", "id": identifier, "state": "live", "clock": [{"actor_id": str(uuid.uuid4()), "counter": 1}],
        "hash": personal.projection_hash(value), "modified_ms": 2, "value": value}


def test_actor_start_and_correlated_snapshot_reuse_private_core_stagers(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch)
    result = service.start_personal_actor(registry, handle)
    start = channel.sent.pop()
    assert start["kind"] == actor.START_KIND and result["dispatch_started"] and not result["persisted"]
    assert service.start_personal_actor(registry, handle)["message_id"] == start["message_id"]
    channel.sent.clear()
    service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, start["message_id"])))
    assert not channel.sent, "An actor ACK was itself acknowledged"
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    request_wire = actor.wire_message(frame("personal_sync.request", request), handle.actor_id)
    service._payload(peer, channel, request_wire)
    assert channel.sent[-1]["kind"] == actor.ACK_KIND and channel.sent[-1]["body"]["message_id"] == request_wire["message_id"]
    records = [record()]
    batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
        "reply": False, "records": records, "records_hash": personal.records_hash(records)}
    wire = actor.wire_message(frame("personal_sync.batch", batch), handle.actor_id)
    service._payload(peer, channel, wire)
    assert channel.sent[-1]["kind"] == actor.ACK_KIND and channel.sent[-1]["body"]["message_id"] == wire["message_id"]
    private = actor.storage_peer(handle.actor_id)
    staged = [(owner, value) for owner, value in service.store.ready_personal_batches() if owner == private]
    assert len(staged) == 1 and staged[0][1]["records"] == records
    assert registry.read(handle, wire["message_id"]) == wire
    service.replay_personal_sync()
    assert not events and service.server is None
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM personal_batch WHERE peer_id=?", (peer["device_id"],)).fetchone()[0] == 0


def test_actor_scope_rejection_precedes_raw_persistence_and_never_falls_back(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch)
    service.start_personal_actor(registry, handle); channel.sent.clear()
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.request", request), handle.actor_id))
    channel.sent.clear(); before = registry.status(handle)["packets"]
    records = [record("private-outside-scope")]
    batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
        "reply": False, "records": records, "records_hash": personal.records_hash(records)}
    wire = actor.wire_message(frame("personal_sync.batch", batch), handle.actor_id)
    service._payload(peer, channel, wire)
    assert registry.status(handle)["packets"] == before and not channel.sent and not events
    with pytest.raises(KeyError): registry.read(handle, wire["message_id"])


def test_native_source_loss_prevents_dispatch_and_incoming_raw_access(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch)
    service.start_personal_actor(registry, handle); channel.sent.clear()
    service.native_actor_book_source = lambda: None
    with pytest.raises(PermissionError): service.start_personal_actor(registry, handle)
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.request", request), handle.actor_id))
    assert not channel.sent and not events and registry.status(handle)["packets"] == 0
    assert registry.status(handle)["phase"] == "cancelled"


def test_actor_attachment_uses_private_manifest_and_native_integrity_checks(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch)
    service.start_personal_actor(registry, handle)
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.request", request), handle.actor_id))
    raw = b"\x89PNG\r\n\x1a\nOwned private actor attachment"
    digest = hashlib.sha256(raw).hexdigest()
    item = record()
    item["value"]["attachments"] = [{"attachment_id": "actor-image", "name": "owned.png", "kind": "image",
        "mime": "image/png", "size": len(raw), "sha256": digest}]
    item["hash"] = personal.projection_hash(item["value"])
    batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
        "reply": False, "records": [item], "records_hash": personal.records_hash([item])}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.batch", batch), handle.actor_id))
    queued = [value for value in service.store.pending(peer["device_id"]) if value.get("kind") == actor.DATA_KIND]
    assert len(queued) == 1 and actor.unwrap(queued[0]["body"])[0] == "personal_sync.attachment_request"
    assert service._send_message(channel, peer["device_id"], queued[0])
    request_id = queued[0]["message_id"]
    service._payload(peer, channel, {"type": "ack", "message_id": request_id, "status": "accepted", "error": "none"})
    assert service.store.outbox_message(peer["device_id"], request_id) == queued[0]
    service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, request_id)))
    assert service.store.outbox_message(peer["device_id"], request_id) is None
    body = {"format": 2, "run_id": handle.actor_id, "reply": False, "records_hash": batch["records_hash"],
        "sha256": digest, "index": 0, "data": base64.b64encode(raw).decode("ascii")}
    channel.sent.clear()
    before = registry.status(handle)["packets"]
    unrelated = actor.wire_message(frame("personal_sync.attachment_chunk", dict(body, reply=True)), handle.actor_id)
    service._payload(peer, channel, unrelated)
    assert not channel.sent and registry.status(handle)["packets"] == before
    wire = actor.wire_message(frame("personal_sync.attachment_chunk", body), handle.actor_id)
    service._payload(peer, channel, wire)
    assert channel.sent[-1]["body"]["message_id"] == wire["message_id"]
    private = actor.storage_peer(handle.actor_id)
    sink = io.BytesIO()
    assert service.store.verify_incoming_attachment(private, handle.actor_id, False, batch["records_hash"], digest, sink)
    assert sink.getvalue() == raw
    service._payload(peer, channel, wire)  # Exact replay reuses the native chunk dedupe.
    with sqlite3.connect(service.store.database_path) as db:
        rows = db.execute("SELECT peer_id,payload FROM personal_attachment_chunk").fetchall()
    assert len(rows) == 1 and rows[0][0] == private and raw not in rows[0][1]
    results = [value for value in service.store.pending(peer["device_id"]) if value.get("kind") == actor.DATA_KIND]
    assert len(results) == 1
    kind, result = actor.unwrap(results[0]["body"])
    assert kind == "personal_sync.attachment_result" and result["state"] == "complete" and result["sha256"] == digest
    service.cancel_personal_actor(registry, handle); channel.sent.clear()
    assert service.store.outbox_message(peer["device_id"], results[0]["message_id"]) is None
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.attachment_chunk", body), handle.actor_id))
    assert not channel.sent and not events
