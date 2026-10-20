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


def owned_transport(tmp_path, monkeypatch, *, deletions=False, skip_deletions=None, book_source=None):
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
    service.native_actor_book_source = book_source or (lambda: "a" * 64)
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


def gtk_actor_bridge():
    import ast
    from pathlib import Path
    from magnolie_hintergrund import PhoneServiceProxy
    source = Path(phone.__file__).with_name("magnolie-organizer")
    node = next(node for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.FunctionDef) and node.name == "_telefon_actor_mcp")
    namespace = {"PhoneServiceProxy": PhoneServiceProxy}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["_telefon_actor_mcp"]


def test_private_gtk_actor_bridge_uses_actual_source_and_existing_controller(tmp_path, monkeypatch):
    service, peer, channel, registry, _, events = owned_transport(tmp_path, monkeypatch)
    bridge = gtk_actor_bridge()
    target = {"peerId": peer["device_id"], "fingerprint": phone.fingerprint(phone.unb64(peer["static_public"], 32))}
    source = bridge(None, service, dict(target, action="notes_actor_source"))
    assert source["ok"]
    assert not bridge(None, service, dict(target, action="notes_actor_create", sourceRevision="f" * 64))["ok"]
    created = bridge(None, service, dict(target, action="notes_actor_create", sourceRevision=source["sourceRevision"]))
    assert created["ok"] and created["bookSource"] == ""
    handle = {key: created[key] for key in ("actorId", "ownerToken", "bookSource")}
    assert bridge(None, service, dict(handle, action="notes_actor_start"))["actor"]["dispatch_started"]
    assert channel.sent[-1]["kind"] == actor.START_KIND
    waiting = bridge(None, service, dict(handle, action="notes_actor_read"))
    assert waiting["ok"] and not waiting["actor"]["batch_ready"]
    with pytest.raises(PermissionError): bridge(None, service, dict(handle, action="notes_actor_read", ownerToken="f" * 64))
    assert bridge(None, service, dict(handle, action="notes_actor_cancel"))["actor"]["phase"] == "cancelled"
    with pytest.raises(PermissionError): bridge(None, service, dict(handle, action="notes_actor_read"))
    assert not events


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
    view = service.read_personal_actor_staging(registry, handle)
    with pytest.raises(ValueError): service.read_personal_actor_staging(registry, handle,
        expected_revision=view["revision"], attachment_sha256=digest)
    with pytest.raises(PermissionError): service.read_personal_actor_staging(registry, handle,
        expected_revision=view["revision"], attachment_sha256="b" * 64)
    with pytest.raises(ValueError): service.read_personal_actor_staging(registry, handle, attachment_sha256=digest)
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
    file_first = service.read_personal_actor_staging(registry, handle, expected_revision=view["revision"], attachment_sha256=digest, limit=7)
    file_bytes = bytearray(base64.b64decode(file_first["data_base64"]))
    offset = file_first["next_offset"]
    while offset is not None:
        part = service.read_personal_actor_staging(registry, handle, offset=offset, limit=7, expected_revision=view["revision"], attachment_sha256=digest)
        file_bytes.extend(base64.b64decode(part["data_base64"])); offset = part["next_offset"]
    assert bytes(file_bytes) == raw and file_first["total_bytes"] == len(raw) and file_first["mime"] == "image/png"
    assert file_first["attachment_sha256"] == digest and file_first["revision"] == view["revision"]
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
    assert value["content_scope"]["members"] == {"notes": ["note-one"], "tasks": ["task-one"]}
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


def test_actor_core_commit_requires_fresh_native_book_save_and_bound_review_claim(tmp_path, monkeypatch):
    from magnolie_personal_actor_store import NativeBookOwnerScope
    from types import SimpleNamespace
    book = NativeBookOwnerScope(); book.set_ready(True)
    provider = lambda: book.current("native-profile", True)
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch, book_source=provider)
    service.start_personal_actor(registry, handle)
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    records = [record()]
    batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
        "reply": False, "records": records, "records_hash": personal.records_hash(records)}
    for kind, body in [("personal_sync.request", request), ("personal_sync.batch", batch)]:
        service._payload(peer, channel, actor.wire_message(frame(kind, body), handle.actor_id))
    channel.sent.clear()
    view = service.read_personal_actor_staging(registry, handle)
    with pytest.raises(PermissionError): service.prepare_personal_actor_commit(registry, handle, view["revision"], "b" * 64, None, provider())
    before = book.record_saved("native-profile", True, "a" * 64)
    claim = service.prepare_personal_actor_commit(registry, handle, view["revision"], "b" * 64, before, provider())
    assert not claim["book_persisted"]
    with pytest.raises(PermissionError): service.queue_personal_actor_reply(registry, handle, claim["claim_token"], [dict(batch, reply=True)], [], before, provider())
    assert claim == service.prepare_personal_actor_commit(registry, handle, view["revision"], "b" * 64, before, provider())
    with pytest.raises(PermissionError): service.commit_personal_actor(registry, handle, claim["claim_token"], before, provider())
    wrong = book.record_saved("native-profile", True, "c" * 64)
    with pytest.raises(PermissionError): service.commit_personal_actor(registry, handle, claim["claim_token"], wrong, provider())
    actual = book.record_saved("native-profile", True, "b" * 64)
    with pytest.raises(PermissionError): service.commit_personal_actor(registry, handle, "f" * 64, actual, provider())
    bridge = gtk_actor_bridge()
    native_window = SimpleNamespace(_telefon_actor_buchnachweis=lambda: None, _telefon_actor_buchquelle=provider)
    arguments = {"action": "notes_actor_commit", "actorId": handle.actor_id, "ownerToken": handle.owner_token,
        "bookSource": "", "claimToken": claim["claim_token"], "saved": True, "native_saved_book": actual}
    with pytest.raises(PermissionError): bridge(native_window, service, arguments)
    assert service.store.ready_personal_batches()
    native_window._telefon_actor_buchnachweis = lambda: book.save_state("native-profile", True)
    committed = bridge(native_window, service, arguments)["actor"]
    assert committed["book_persisted"] and committed["core_committed"] and not committed["phone_persisted"]
    assert committed == service.commit_personal_actor(registry, handle, claim["claim_token"], actual, provider())
    assert not any(owner == actor.storage_peer(handle.actor_id) for owner, _ in service.store.ready_personal_batches())
    assert not channel.sent and not events
    image = b"\x89PNG\r\n\x1a\nSaved reply source"
    image_hash = hashlib.sha256(image).hexdigest()
    reply_record = copy.deepcopy(records[0]); reply_record["value"]["text"] = "Saved native reply"
    reply_record["value"]["attachments"] = [{"attachment_id": "saved-image", "name": "saved.png", "kind": "image", "mime": "image/png", "size": len(image), "sha256": image_hash}]
    reply_record["hash"] = personal.projection_hash(reply_record["value"])
    reply = [dict(batch, batch_id=str(uuid.uuid4()), reply=True, records=[reply_record], records_hash=personal.records_hash([reply_record]))]
    sources = [{"sha256": image_hash, "data": "data:image/png;base64," + base64.b64encode(image).decode("ascii")}]
    with pytest.raises(PermissionError): service.queue_personal_actor_reply(registry, handle, "f" * 64, reply, sources, actual, provider())
    with pytest.raises(PermissionError): service.queue_personal_actor_reply(registry, handle, claim["claim_token"], reply, sources, dict(actual, sha256="c" * 64), provider())
    queued = service.queue_personal_actor_reply(registry, handle, claim["claim_token"], reply, sources, actual, provider())
    pending = service.store.pending(peer["device_id"])
    assert queued["reply_queued"] and not queued["delivery_confirmed"] and not queued["phone_persisted"]
    assert len(pending) == 1 and actor.unwrap(pending[0]["body"]) == ("personal_sync.batch", reply[0])
    assert queued == service.queue_personal_actor_reply(registry, handle, claim["claim_token"], reply, sources, actual, provider())
    assert pending == service.store.pending(peer["device_id"])
    changed_reply = copy.deepcopy(reply); changed_reply[0]["batch_id"] = str(uuid.uuid4())
    with pytest.raises(PermissionError): service.queue_personal_actor_reply(registry, handle, claim["claim_token"], changed_reply, sources, actual, provider())
    assert service._send_message(channel, peer["device_id"], pending[0]) and channel.sent[-1] == pending[0]
    wants = {"format": 2, "run_id": handle.actor_id, "reply": True, "records_hash": reply[0]["records_hash"], "wants": [{"sha256": image_hash, "ranges": [[0, 1]]}]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.attachment_request", wants), handle.actor_id))
    outgoing = [actor.unwrap(value["body"]) for value in service.store.pending(peer["device_id"]) if value.get("kind") == actor.DATA_KIND]
    assert any(kind == "personal_sync.attachment_chunk" and base64.b64decode(value["data"]) == image for kind, value in outgoing)
    service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, pending[0]["message_id"])))
    assert not service.personal_actor_status(registry, handle)["phone_persisted"]
    assert not service.personal_actor_status(registry, handle)["completion_report_queued"], "Batch ACK was mistaken for complete file transfer"
    result = {"format": 2, "run_id": handle.actor_id, "reply": True, "records_hash": reply[0]["records_hash"], "sha256": image_hash,
        "state": "complete", "error": "none"}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.attachment_result", result), handle.actor_id))
    reports = [value for value in service.store.pending(peer["device_id"]) if value.get("kind") == actor.DATA_KIND and actor.unwrap(value["body"])[0] == "personal_sync.report"]
    assert len(reports) == 1 and actor.unwrap(reports[0]["body"])[1]["sent"]["notes"] == 1
    assert not service.personal_actor_status(registry, handle)["phone_persisted"], "File integrity result was mistaken for a remote book save"
    service._payload(peer, channel, {"type": "ack", "message_id": reports[0]["message_id"], "status": "accepted", "error": "none"})
    assert not service.personal_actor_status(registry, handle)["phone_persisted"]
    service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, reports[0]["message_id"])))
    assert service.personal_actor_status(registry, handle)["phone_persisted"]
    assert not events


def test_actor_commit_rejects_changed_native_staging_after_book_save(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_transport(tmp_path, monkeypatch, deletions=True, skip_deletions=False)
    service.start_personal_actor(registry, handle)
    request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    records = [record()]
    batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True, "reply": False,
        "records": records, "records_hash": personal.records_hash(records)}
    for kind, body in [("personal_sync.request", request), ("personal_sync.batch", batch)]:
        service._payload(peer, channel, actor.wire_message(frame(kind, body), handle.actor_id))
    before = {"book_source": "a" * 64, "sequence": 1, "sha256": "a" * 64}
    view = service.read_personal_actor_staging(registry, handle)
    claim = service.prepare_personal_actor_commit(registry, handle, view["revision"], "b" * 64, before, "a" * 64)
    proposal = {"format": 1, "run_id": handle.actor_id, "proposal_batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
        "proposals": [{"proposal_id": str(uuid.uuid4()), "kind": "note", "id": "note-one", "parent_id": "", "clock": records[0]["clock"],
            "prior_hash": records[0]["hash"], "deleted_ms": 2, "label": "Owned pending deletion"}]}
    service._payload(peer, channel, actor.wire_message(frame("personal_sync.deletion_proposals", proposal), handle.actor_id))
    with pytest.raises(PermissionError): service.commit_personal_actor(registry, handle, claim["claim_token"], dict(before, sequence=2, sha256="b" * 64), "a" * 64)
    changed = service.read_personal_actor_staging(registry, handle)
    with pytest.raises(PermissionError): service.prepare_personal_actor_commit(registry, handle, changed["revision"], "b" * 64, before, "a" * 64)
    assert service.store.ready_personal_batches() and service.store.ready_personal_domains() and not events


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
