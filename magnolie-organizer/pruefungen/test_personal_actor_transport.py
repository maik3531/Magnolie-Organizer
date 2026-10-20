"""Native actor dispatch and existing private-domain staging, without GUI adoption."""
import sqlite3
import uuid
import base64
import hashlib
import io
import copy
import json
import pytest
from test_personal_actor_source import actor_source_fixture
import magnolie_telefon as phone
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal


def frame(kind, body):
    return phone.PhoneService._actor_control_message(kind, body)


def owned_transport(tmp_path, monkeypatch, *, deletions=False, skip_deletions=None):
    service, peer, channel, fingerprint, _ = actor_source_fixture(tmp_path, monkeypatch)
    if deletions:
        peer["local_grants"]["grants"]["personal_deletions_sync"] = True
        peer["grants"]["grants"]["personal_deletions_sync"] = True
        service.note_controls[channel]["grants.update"] = copy.deepcopy(peer["grants"])
        service.store.save_peers()
    if skip_deletions is not None:
        body = service.store.change_shared_setting(peer["device_id"], peer["static_public"], "skip_deletions", skip_deletions)
        service.shared_sessions[channel]["sent"] = copy.deepcopy(body)
        service.shared_sessions[channel]["received"] = copy.deepcopy(body)
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


def test_actor_private_staging_reader_is_bounded_revisioned_and_owner_guarded(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch)
    with pytest.raises(PermissionError): service.read_personal_actor_staging(registry, handle)
    service.start_personal_actor(registry, handle)
    waiting = service.read_personal_actor_staging(registry, handle)
    assert not waiting["batch_ready"]
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.request", request), handle.actor_id))
    item = record(); item["value"]["text"] = "Private Grüße 🌸"; item["hash"] = personal.projection_hash(item["value"])
    batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
        "reply": False, "records": [item], "records_hash": personal.records_hash([item])}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.batch", batch), handle.actor_id))
    channel.sent.clear()
    with pytest.raises(PermissionError): service.read_personal_actor_staging(registry, handle, expected_revision=waiting["revision"])
    first = service.read_personal_actor_staging(registry, handle, limit=17)
    raw = bytearray(base64.b64decode(first["data_base64"]))
    offset = first["next_offset"]
    with pytest.raises(ValueError): service.read_personal_actor_staging(registry, handle, offset=offset)
    with pytest.raises(ValueError): service.read_personal_actor_staging(registry, handle, limit=65537)
    while offset is not None:
        part = service.read_personal_actor_staging(registry, handle, offset=offset, limit=17, expected_revision=first["revision"])
        assert len(base64.b64decode(part["data_base64"])) <= 17
        raw.extend(base64.b64decode(part["data_base64"])); offset = part["next_offset"]
    assert hashlib.sha256(raw).hexdigest() == first["revision"] and len(raw) == first["total_bytes"]
    value = json.loads(raw)
    assert value["request"] == request and value["batch"]["records"] == [item] and value["intents"] == []
    native = next(value for owner, value in service.store.ready_personal_batches() if owner == actor.storage_peer(handle.actor_id))
    assert value["batch"]["commit_token"] == native["commit_token"]
    native_now = phone.now_ms
    monkeypatch.setattr(phone, "now_ms", lambda: native_now() + 60001)
    with pytest.raises(PermissionError): service.read_personal_actor_staging(registry, handle)
    monkeypatch.setattr(phone, "now_ms", native_now)
    service.native_actor_book_source = lambda: "b" * 64
    with pytest.raises(PermissionError): service.read_personal_actor_staging(registry, handle)
    service.native_actor_book_source = lambda: "a" * 64
    service.cancel_personal_actor(registry, handle)
    with pytest.raises(PermissionError): service.read_personal_actor_staging(registry, handle)
    assert not events


def test_actor_reply_attachment_requests_use_declared_private_sources_and_marked_queue(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch)
    service.start_personal_actor(registry, handle)
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.request", request), handle.actor_id))
    private = actor.storage_peer(handle.actor_id)
    raw = b"\x89PNG\r\n\x1a\nPrivate desktop reply"
    digest = hashlib.sha256(raw).hexdigest()
    item = record(); item["value"]["attachments"] = [{"attachment_id": "reply-image", "name": "reply.png", "kind": "image",
        "mime": "image/png", "size": len(raw), "sha256": digest}]
    item["hash"] = personal.projection_hash(item["value"])
    batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
        "reply": True, "records": [item], "records_hash": personal.records_hash([item])}
    service.store.stage_personal_batch(private, frame("personal_sync.batch", batch))
    service.store.stage_outgoing_attachment(private, handle.actor_id, True, batch["records_hash"], digest, "image/png", raw, "any", phone.now_ms() + phone.DAY_MS)
    content = {"format": 2, "run_id": handle.actor_id, "reply": True, "records_hash": batch["records_hash"],
        "wants": [{"sha256": digest, "ranges": [[0, 1]]}]}
    channel.sent.clear(); before = registry.status(handle)["packets"]
    for bad in [dict(content, reply=False), dict(content, records_hash="a" * 64),
            dict(content, wants=[{"sha256": "b" * 64, "ranges": [[0, 1]]}]),
            dict(content, wants=[{"sha256": digest, "ranges": [[0, 2]]}])]:
        service._payload(peer, channel, actor.wire_message(frame("personal_sync.attachment_request", bad), handle.actor_id))
    assert not channel.sent and registry.status(handle)["packets"] == before
    wire = actor.wire_message(frame("personal_sync.attachment_request", content), handle.actor_id)
    service._payload(peer, channel, wire); service._payload(peer, channel, wire)
    queued = [value for value in service.store.pending(peer["device_id"]) if value.get("kind") == actor.DATA_KIND]
    assert len(queued) == 1
    kind, chunk = actor.unwrap(queued[0]["body"])
    assert kind == "personal_sync.attachment_chunk" and chunk["reply"] is True and base64.b64decode(chunk["data"]) == raw
    result = {"format": 2, "run_id": handle.actor_id, "reply": True, "records_hash": batch["records_hash"], "sha256": digest,
        "state": "complete", "error": "none"}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.attachment_result", result), handle.actor_id))
    assert not service.store.has_outgoing_attachments(private, handle.actor_id) and not events
    service.cancel_personal_actor(registry, handle)
    assert service.store.outbox_message(peer["device_id"], queued[0]["message_id"]) is None


@pytest.mark.parametrize("granted,skip", [(False, False), (True, True), (True, False)])
def test_actor_deletion_intents_require_scope_consent_and_prior_proposals_without_save_ack(tmp_path, monkeypatch, granted, skip):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch, deletions=granted, skip_deletions=skip)
    service.start_personal_actor(registry, handle)
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.request", request), handle.actor_id))
    proposal = {"proposal_id": str(uuid.uuid4()), "kind": "note", "id": "note-one", "parent_id": "",
        "clock": [{"actor_id": peer["device_id"], "counter": 2}], "prior_hash": "a" * 64, "deleted_ms": 2, "label": "Owned proposal"}
    body = {"format": 1, "run_id": handle.actor_id, "proposal_batch_id": str(uuid.uuid4()), "sequence": 0, "last": True, "proposals": [proposal]}
    channel.sent.clear(); before = registry.status(handle)["packets"]
    wire = actor.wire_message(frame("personal_sync.deletion_proposals", body), handle.actor_id)
    service._payload(peer, channel, wire)
    assert not channel.sent and not events
    if not granted or skip:
        assert registry.status(handle)["packets"] == before and not service.store.ready_personal_domains()
        return
    private = actor.storage_peer(handle.actor_id)
    intents = service.store.ready_personal_domains()
    assert len(intents) == 1 and intents[0][0] == private and intents[0][1]["body"] == body
    readback = json.loads(base64.b64decode(service.read_personal_actor_staging(registry, handle)["data_base64"]))
    assert readback["intents"] == [{key: intents[0][1][key] for key in ("kind", "body", "pending_message_id", "commit_token")}]
    assert registry.read(handle, wire["message_id"]) == wire
    service._payload(peer, channel, wire)
    assert service.store.ready_personal_domains() == intents
    outside = copy.deepcopy(body); outside["proposals"][0]["id"] = "outside-phone-scope"
    bad = actor.wire_message(frame("personal_sync.deletion_proposals", outside), handle.actor_id)
    service._payload(peer, channel, bad)
    with pytest.raises(KeyError): registry.read(handle, bad["message_id"])
    decision = {"format": 1, "run_id": handle.actor_id, "decision_id": str(uuid.uuid4()), "decisions": [
        {"proposal_id": proposal["proposal_id"], "decision": "delete", "expected_clock": proposal["clock"]}]}
    unknown = actor.wire_message(frame("personal_sync.deletion_decision", decision), handle.actor_id)
    service._payload(peer, channel, unknown)
    with pytest.raises(KeyError): registry.read(handle, unknown["message_id"])
    service.store.remember_personal_proposal_kinds(private, body, True)
    stale = copy.deepcopy(decision); stale["decisions"][0]["expected_clock"][0]["counter"] += 1
    stale_wire = actor.wire_message(frame("personal_sync.deletion_decision", stale), handle.actor_id)
    service._payload(peer, channel, stale_wire)
    with pytest.raises(KeyError): registry.read(handle, stale_wire["message_id"])
    known = actor.wire_message(frame("personal_sync.deletion_decision", decision), handle.actor_id)
    service._payload(peer, channel, known)
    assert len(service.store.ready_personal_domains()) == 2
    service.replay_personal_sync()
    assert not channel.sent and not events, "A private deletion intent was acknowledged or replayed before book commit"
