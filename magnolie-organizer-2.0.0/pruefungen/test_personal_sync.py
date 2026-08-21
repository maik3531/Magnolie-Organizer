import importlib.util
import json
import pathlib
import sys
import uuid
import copy
import io
import hashlib
import base64
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_personal_sync as sync
import magnolie_telefon as phone


def contract():
    return json.loads((ROOT / "pruefungen" / "personal-sync-contract.json").read_text(encoding="utf-8"))


def test_shared_golden_vector():
    value = contract()
    assert sync.canonical(value["value"]).decode() == value["canonical"]
    assert sync.projection_hash(value["value"]) == value["sha256"]
    conflict = value["conflict"]
    assert sync.conflict_id(conflict["kind"], conflict["id"], conflict["loser_hash"]) == conflict["id_v4"]
    assert uuid.UUID(conflict["id_v4"]).version == 4
    assert sync.compare_clock(value["clock"]["left"], value["clock"]["right"]) == "concurrent"
    deletion = value["deletions"]
    assert sync.deletion_proposal_id(deletion["peer_device_id"], deletion["kind"], deletion["id"],
        deletion["parent_id"], deletion["clock"], deletion["prior_hash"]) == deletion["proposal_id"]
    unicode_order = value["unicode_order"]
    assert sync.canonical(unicode_order["value"]).decode() == unicode_order["canonical"]
    format2 = value["format2"]
    assert sync.canonical(format2["value"]).decode() == format2["canonical"]
    assert sync.projection_hash(format2["value"]) == format2["sha256"]
    descriptor, raw = sync.attachment_descriptor({"id": "att-1", "name": "image.png",
        "data": format2["data_url"]})
    assert descriptor == format2["descriptor"] and sync.mime_from_magic(raw) == "image/png"


def test_shared_invalid_vectors_and_utf8_boundaries():
    shared = contract()
    invalid = shared["invalid"]
    value = shared["value"]
    base = {"kind": "note", "id": invalid["id_160_utf8"], "state": "live",
        "clock": shared["clock"]["left"], "hash": sync.projection_hash(value),
        "modified_ms": value["modified_ms"], "value": value}
    assert len(base["id"].encode("utf-8")) == 160
    assert sync.validate_record(base) is base
    mutations = []
    mutations.append(dict(base, id=invalid["whitespace_id"]))
    mutations.append(dict(base, id=invalid["id_162_utf8"]))
    for field in ("modified_ms",):
        mutations.append(dict(base, **{field: invalid["numeric_string"]}))
        mutations.append(dict(base, **{field: invalid["boolean_number"]}))
        mutations.append(dict(base, **{field: invalid["huge_timestamp"]}))
    mutations.append(dict(base, clock=invalid["unsorted_clock"]))
    mutations.append(dict(base, clock=invalid["duplicate_clock"]))
    extra = dict(base); extra[invalid["unexpected_field"]] = 1; mutations.append(extra)
    numeric_value = copy.deepcopy(value); numeric_value["created_ms"] = invalid["numeric_string"]
    mutations.append(dict(base, value=numeric_value, hash=sync.projection_hash(numeric_value)))
    bool_value = copy.deepcopy(value); bool_value["created_ms"] = invalid["boolean_number"]
    mutations.append(dict(base, value=bool_value, hash=sync.projection_hash(bool_value)))
    for mutation in mutations:
        try:
            sync.validate_record(mutation)
        except ValueError:
            pass
        else:
            raise AssertionError("shared invalid vector accepted")
    descriptor = dict(shared["format2"]["descriptor"],
        attachment_id=invalid["whitespace_attachment_id"])
    with __import__("pytest").raises(ValueError):
        sync.validate_attachment_descriptor(descriptor)
    bad_value = dict(value, notebook_id=invalid["whitespace_notebook_id"])
    with __import__("pytest").raises(ValueError):
        sync.validate_value("note", bad_value)
    boundary = [invalid[name] for name in ("leading_space_id", "trailing_space_id",
        "leading_tab_id", "trailing_tab_id")]
    for identifier in boundary:
        with __import__("pytest").raises(ValueError):
            sync.validate_record(dict(base, id=identifier))
        with __import__("pytest").raises(ValueError):
            sync.validate_attachment_descriptor(dict(shared["format2"]["descriptor"], attachment_id=identifier))
        with __import__("pytest").raises(ValueError):
            sync.validate_value("note", dict(value, notebook_id=identifier))
    interior = invalid["interior_space_id"]
    assert sync.validate_record(dict(base, id=interior))["id"] == interior
    assert sync.validate_attachment_descriptor(dict(shared["format2"]["descriptor"],
        attachment_id=interior))["attachment_id"] == interior
    assert sync.validate_value("note", dict(value, notebook_id=interior))["notebook_id"] == interior


def test_exact_batch_and_no_tombstones():
    value = contract()["value"]
    record = {"kind": "note", "id": "note-1", "state": "live",
        "clock": contract()["clock"]["left"], "hash": sync.projection_hash(value),
        "modified_ms": value["modified_ms"], "value": value}
    batch = {"format": 1, "run_id": str(uuid.uuid4()), "batch_id": str(uuid.uuid4()),
        "sequence": 0, "last": True, "reply": False, "records": [record]}
    assert sync.validate_body("personal_sync.batch", batch) is batch
    for mutation in (dict(batch, deletion=True), dict(batch, records=[dict(record, state="deleted")])):
        try:
            sync.validate_body("personal_sync.batch", mutation)
        except ValueError:
            pass
        else:
            raise AssertionError("schema accepted deletion")


def test_settings_default_fail_closed_shape():
    assert sync.validate_body("personal_sync.settings", {"format": 1, "own_device": False})
    for bad in ({"format": 1, "own_device": False, "auto_wifi": False},
                {"format": 1, "own_device": 1}):
        try:
            sync.validate_body("personal_sync.settings", bad)
        except ValueError:
            pass
        else:
            raise AssertionError("non-exact settings accepted")


def test_encrypted_aggregate_is_contiguous_and_committed_after_save(tmp_path):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer = str(uuid.uuid4())
    run = str(uuid.uuid4())
    def message(sequence, last):
        now = phone.now_ms()
        return {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
            "kind": "personal_sync.batch", "created_ms": now, "expires_ms": now + 60000,
            "body": {"format": 1, "run_id": run, "batch_id": str(uuid.uuid4()),
                "sequence": sequence, "last": last, "reply": False, "records": []}}
    second = message(1, True)
    assert store.stage_personal_batch(peer, second) is None
    first = message(0, False)
    aggregate = store.stage_personal_batch(peer, first)
    assert aggregate and aggregate["records"] == []
    # Transport acceptance is durable staging; semantic apply is committed separately.
    assert store.dedupe_result(peer, first["message_id"]) == ("accepted", "none")
    raw = (tmp_path / "phone" / "phone.db").read_bytes()
    assert b'"records":' not in raw
    committed_peer, ids = store.commit_personal_batch(
        peer, aggregate["message_id"], aggregate["commit_token"])
    assert committed_peer == peer and set(ids) == {first["message_id"], second["message_id"]}
    assert store.dedupe_result(peer, first["message_id"]) == ("accepted", "none")


def test_wifi_policy_and_revocation_purge(tmp_path):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer = str(uuid.uuid4())
    body = {"format": 1, "run_id": str(uuid.uuid4()), "trigger": "auto_wifi", "modules": ["notes"]}
    queued = store.queue(peer, "personal_sync.request", body, 60000, "wifi_only")
    setting = store.queue(peer, "personal_sync.settings",
        {"format": 1, "own_device": False}, 60000)
    call = store.queue(peer, "end_call.command", {"opaque": True}, 60000)
    assert queued["message_id"] not in {
        item["message_id"] for item in store.pending(peer, "bluetooth")}
    assert queued["message_id"] in {
        item["message_id"] for item in store.pending(peer, "wifi")}
    store.purge_personal(peer)
    remaining = {item["message_id"] for item in store.pending(peer, "wifi")}
    assert remaining == {setting["message_id"], call["message_id"]}


def test_module_revocation_keeps_independent_task_run(tmp_path):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer = str(uuid.uuid4())
    notes_run, tasks_run = str(uuid.uuid4()), str(uuid.uuid4())
    for run_id, module in ((notes_run, "notes"), (tasks_run, "tasks")):
        request = {"format": 1, "run_id": run_id, "trigger": "manual", "modules": [module]}
        store.remember_personal_run(peer, request)
        store.queue(peer, "personal_sync.request", request, phone.DAY_MS)
        batch = _empty_batch(run_id)["body"]; batch["reply"] = False
        store.queue(peer, "personal_sync.batch", batch, phone.DAY_MS)
    store.purge_personal_modules(peer, {"notes"})
    remaining = store.pending(peer)
    assert {item["body"]["run_id"] for item in remaining} == {tasks_run}
    assert store.personal_run(peer, notes_run) == {}
    assert store.personal_run(peer, tasks_run)["modules"] == ["tasks"]


def test_deletion_decision_replay_is_idempotent_until_accepted(tmp_path):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer, run, decision = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    body = {"format": 1, "run_id": run, "decision_id": decision, "decisions": [{
        "proposal_id": str(uuid.uuid4()), "decision": "restore",
        "expected_clock": contract()["clock"]["left"]}]}
    first = store.queue_deletion_decision(peer, body, phone.DAY_MS, "any")
    second = store.queue_deletion_decision(peer, body, phone.DAY_MS, "any")
    assert first["message_id"] == second["message_id"]
    assert store.acknowledge(peer, first["message_id"]) == decision
    assert store.pending(peer) == []


def test_expired_auto_run_is_recovered_and_no_longer_blocks(tmp_path):
    root = str(tmp_path / "phone")
    peer, run = str(uuid.uuid4()), str(uuid.uuid4())
    created = 1_700_000_000_000
    with mock.patch.object(phone, "now_ms", return_value=created):
        store = phone.PhoneStore(root, "Test")
        store.remember_personal_run(peer, {"format": 1, "run_id": run,
            "trigger": "auto_wifi", "modules": ["notes"]})
        store.set_active_auto_run(peer, run)
        partial = _empty_batch(run)
        partial["created_ms"] = created; partial["expires_ms"] = created + phone.DAY_MS
        partial["body"].update(sequence=1, last=False, reply=False)
        store.stage_personal_batch(peer, partial)
        with __import__("sqlite3").connect(store.database_path) as db:
            db.execute("DELETE FROM meta WHERE key=?", ("personal_active_auto:" + peer,))
    with mock.patch.object(phone, "now_ms", return_value=created + phone.DAY_MS - 1):
        # The durable run closes the crash window before the separate marker save.
        assert store.active_auto_run(peer) == run
    with mock.patch.object(phone, "now_ms", return_value=created + phone.DAY_MS + 1):
        store.cleanup()
        store.cleanup()
        assert store.active_auto_run(peer) == ""
        assert store.personal_run(peer, run) == {}
        reports = [item for item in store.pending(peer) if item["kind"] == "personal_sync.report"
                   and item["body"]["state"] == "partial"]
        assert len(reports) == 1


def _personal_service(tmp_path, callback):
    service = phone.PhoneService(str(tmp_path / "phone"), "Test", callback=callback)
    peer_id = str(uuid.uuid4())
    local = phone.desktop_grants()
    remote = phone.desktop_grants()
    local["grants"]["personal_notes_sync"] = True
    remote["grants"]["personal_notes_sync"] = True
    service.store.peers.append({"device_id": peer_id, "display_name": "Phone",
        "static_public": phone.b64(b"p" * 32), "state": "paired", "grants": remote,
        "local_grants": local, "capabilities": {}, "last_contact_ms": 0,
        "bluetooth": {"enabled": False, "address": ""}, "personal_sync": {
            "own_device": True, "remote_own_device": True, "auto_wifi": False,
            "last_report": {}}})
    service.store.save_peers()
    return service, peer_id


def _empty_batch(run_id=None, message_id=None):
    now = phone.now_ms()
    return {"type": "message", "v": 1, "message_id": message_id or str(uuid.uuid4()),
        "kind": "personal_sync.batch", "created_ms": now, "expires_ms": now + 60000,
        "body": {"format": 1, "run_id": run_id or str(uuid.uuid4()),
            "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
            "reply": True, "records": []}}


def _remember_request(service, peer_id, message, trigger="manual", modules=None):
    service.store.remember_personal_run(peer_id, {"format": 1,
        "run_id": message["body"]["run_id"], "trigger": trigger,
        "modules": modules or ["notes"]})


def test_batch_ack_waits_for_exact_durable_commit_and_replay_is_deduped(tmp_path):
    events = []
    service, peer_id = _personal_service(tmp_path, lambda event, payload: events.append(payload))
    message = _empty_batch()
    _remember_request(service, peer_id, message)

    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    channel = Channel()

    def commit_after_save(_event, payload):
        assert channel.sent[-1]["status"] == "accepted"
        assert service.store.dedupe_result(peer_id, message["message_id"]) == ("accepted", "none")
        events.append(payload)
        assert not service.commit_personal_sync(peer_id, str(uuid.uuid4()),
                                                payload["commit_token"], True)
        assert service.store.ready_personal_batches()
        assert service.commit_personal_sync(peer_id, payload["pending_message_id"],
                                            payload["commit_token"], True)

    service.callback = commit_after_save
    service._payload(service.store.peer(peer_id), channel, message)
    assert channel.sent == [{"type": "ack", "message_id": message["message_id"],
                             "status": "accepted", "error": "none"}]
    assert service.store.dedupe_result(peer_id, message["message_id"]) == ("accepted", "none")

    service._payload(service.store.peer(peer_id), channel, message)
    assert len(events) == 1
    assert channel.sent[-1]["status"] == "accepted"


def test_failed_or_timed_out_save_stays_pending_and_is_redelivered(tmp_path):
    delivered = []
    service, peer_id = _personal_service(tmp_path,
        lambda _event, payload: delivered.append(payload))
    message = _empty_batch()
    _remember_request(service, peer_id, message)

    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    first = Channel()
    with mock.patch.object(phone, "PERSONAL_COMMIT_SECONDS", 0.01):
        service._payload(service.store.peer(peer_id), first, message)
    assert first.sent[-1]["status"] == "accepted"
    assert service.store.dedupe_result(peer_id, message["message_id"]) == ("accepted", "none")
    assert service.store.ready_personal_batches()

    def commit_retry(_event, payload):
        delivered.append(payload)
        service.commit_personal_sync(peer_id, payload["pending_message_id"],
                                     payload["commit_token"], True)
    service.callback = commit_retry
    service.replay_personal_sync()
    assert len(delivered) == 2
    assert not service.store.ready_personal_batches()


def test_explicit_failed_save_has_no_ack_or_dedupe(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda _event, _payload: None)
    message = _empty_batch()
    _remember_request(service, peer_id, message)

    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    channel = Channel()

    def fail_save(_event, payload):
        assert service.commit_personal_sync(peer_id, payload["pending_message_id"],
                                            payload["commit_token"], False)
    service.callback = fail_save
    service._payload(service.store.peer(peer_id), channel, message)
    assert channel.sent[-1]["status"] == "accepted"
    assert service.store.dedupe_result(peer_id, message["message_id"]) == ("accepted", "none")
    assert service.store.ready_personal_batches()


def test_pending_batch_survives_restart_and_body_is_encrypted(tmp_path):
    root = tmp_path / "phone"
    store = phone.PhoneStore(str(root), "Test")
    peer = str(uuid.uuid4())
    sample = "private sample note 7d68308f"
    message = _empty_batch()
    message["body"]["records"] = [{"kind": "note", "sample": sample}]
    aggregate = store.stage_personal_batch(peer, message)
    assert aggregate is not None
    del store

    reopened = phone.PhoneStore(str(root), "Test")
    replay = reopened.ready_personal_batches()
    assert replay and replay[0][1]["records"][0]["sample"] == sample
    for path in root.glob("phone.db*"):
        assert sample.encode() not in path.read_bytes()


def test_auto_run_policy_survives_restart_and_manual_uses_bluetooth(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    channel = Channel()
    service.connections[peer_id] = channel
    service.connection_transports[peer_id] = "bluetooth"
    run = str(uuid.uuid4())
    request = {"format": 1, "run_id": run, "trigger": "auto_wifi", "modules": ["notes"]}
    request_id = service.send_personal_sync(peer_id, "personal_sync.request", request, "auto_wifi")
    batch = _empty_batch(run)["body"]
    batch["reply"] = False
    batch_id = service.send_personal_sync(peer_id, "personal_sync.batch", batch, "manual")
    assert channel.sent == []
    assert {item["message_id"] for item in service.store.pending(peer_id, "bluetooth")} == set()

    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    assert {item["message_id"] for item in reopened.pending(peer_id, "wifi")} == {request_id, batch_id}
    assert reopened.personal_run(peer_id, run) == request

    manual_run = str(uuid.uuid4())
    service.send_personal_sync(peer_id, "personal_sync.request", {"format": 1,
        "run_id": manual_run, "trigger": "manual", "modules": ["notes"]})
    assert channel.sent[-1]["body"]["run_id"] == manual_run


def test_every_auto_run_message_and_ack_is_rejected_on_bluetooth(tmp_path):
    service, peer = _personal_service(tmp_path, lambda *_: None)
    service.connection_transports[peer] = "bluetooth"
    run = str(uuid.uuid4())
    request = {"format": 1, "run_id": run, "trigger": "auto_wifi", "modules": ["notes"]}
    service.store.remember_personal_run(peer, request)
    service.store.set_active_auto_run(peer, run)
    zero = {"notes": 0, "tasks": 0, "notebooks": 0}
    deletion_counts = {"pending": 0, "deleted": 0, "restored": 0, "conflicts": 0, "blocked": 0,
        "trash": {"notes": 0, "tasks": 0, "notebooks": 0, "attachments": 0}}
    digest = "a" * 64
    proposal = str(uuid.uuid4())
    bodies = {
        "personal_sync.request": request,
        "personal_sync.batch": {"format": 1, "run_id": run, "batch_id": str(uuid.uuid4()),
            "sequence": 0, "last": True, "reply": False, "records": []},
        "personal_sync.report": {"format": 1, "run_id": run, "state": "complete", "trigger": "auto_wifi",
            "transport": "bluetooth", "sent": zero, "received": zero, "conflicts": 0,
            "attachments_omitted": 0, "oversized_skipped": 0, "started_ms": 1, "finished_ms": 1,
            "error": "none", "deletions": deletion_counts},
        "personal_sync.attachment_request": {"format": 2, "run_id": run, "reply": False,
            "records_hash": digest, "wants": [{"sha256": digest, "ranges": [[0, 1]]}]},
        "personal_sync.attachment_chunk": {"format": 2, "run_id": run, "reply": False,
            "records_hash": digest, "sha256": digest, "index": 0, "data": "eA=="},
        "personal_sync.attachment_result": {"format": 2, "run_id": run, "reply": False,
            "records_hash": digest, "sha256": digest, "state": "complete", "error": "none"},
        "personal_sync.deletion_proposals": {"format": 1, "run_id": run,
            "proposal_batch_id": str(uuid.uuid4()), "sequence": 0, "last": True, "proposals": []},
        "personal_sync.deletion_decision": {"format": 1, "run_id": run, "decision_id": str(uuid.uuid4()),
            "decisions": [{"proposal_id": proposal, "decision": "delete",
                "expected_clock": contract()["clock"]["left"]}]},
    }
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    channel = Channel()
    for kind, body in bodies.items():
        now = phone.now_ms()
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()), "kind": kind,
            "created_ms": now, "expires_ms": now + 60_000, "body": body}
        with __import__("pytest").raises(ValueError):
            service._payload(service.store.peer(peer), channel, message)
        assert service.store.dedupe_result(peer, message["message_id"]) is None
    queued = service.store.queue(peer, "personal_sync.report", bodies["personal_sync.report"],
        60_000, "wifi_only")
    with __import__("pytest").raises(ValueError):
        service._payload(service.store.peer(peer), channel, {"type": "ack",
            "message_id": queued["message_id"], "status": "accepted", "error": "none"})
    assert service.store.outbox_policy(peer, queued["message_id"]) == "wifi_only"
    assert service.store.active_auto_run(peer) == run


def test_empty_nonreply_batch_uses_persisted_request_modules_once(tmp_path):
    delivered = []
    service, peer_id = _personal_service(tmp_path, lambda event, payload: delivered.append((event, payload)))
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    channel = Channel()
    run = str(uuid.uuid4())
    now = phone.now_ms()
    request = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
        "kind": "personal_sync.request", "created_ms": now, "expires_ms": now + 60000,
        "body": {"format": 1, "run_id": run, "trigger": "manual", "modules": ["notes"]}}
    service._payload(service.store.peer(peer_id), channel, request)
    assert delivered == []

    batch = _empty_batch(run)
    batch["body"]["reply"] = False
    def commit(_event, payload):
        delivered.append(("personal_sync", payload))
        assert payload["body"]["requested_modules"] == ["notes"]
        service.commit_personal_sync(peer_id, payload["pending_message_id"], payload["commit_token"], True)
    service.callback = commit
    service._payload(service.store.peer(peer_id), channel, batch)
    assert len(delivered) == 1
    service._payload(service.store.peer(peer_id), channel, batch)
    assert len(delivered) == 1


def test_conflicting_final_sequence_rolls_back_without_stage_ack(tmp_path):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer, run = str(uuid.uuid4()), str(uuid.uuid4())
    first = _empty_batch(run)
    first["body"].update(sequence=1, last=True, reply=False)
    assert store.stage_personal_batch(peer, first) is None
    conflicting = _empty_batch(run)
    conflicting["body"].update(sequence=2, last=False, reply=False)
    try:
        store.stage_personal_batch(peer, conflicting)
    except ValueError:
        pass
    else:
        raise AssertionError("sequence beyond final batch was accepted")
    assert store.dedupe_result(peer, conflicting["message_id"]) is None


def test_format2_attachment_protocol_and_encrypted_resume(tmp_path):
    shared = contract()["format2"]
    sync.validate_attachment_descriptor(shared["descriptor"])
    for name in shared["invalid_names"]:
        with __import__("pytest").raises(ValueError):
            sync.validate_attachment_descriptor(dict(shared["descriptor"], name=name))
    peer, run, aggregate = str(uuid.uuid4()), str(uuid.uuid4()), "a" * 64
    raw = b"\x89PNG\r\n\x1a\n" + b"private-signature" * 12000
    digest = hashlib.sha256(raw).hexdigest()
    root = tmp_path / "phone"
    store = phone.PhoneStore(str(root), "Test")
    store.stage_incoming_attachment(peer, run, False, aggregate, digest, len(raw), "image/png",
        1, raw[sync.CHUNK_RAW:], "wifi_only", phone.now_ms() + 60000)
    assert store.attachment_missing_ranges(peer, run, False, aggregate, digest) == [[0, 1]]
    store.stage_incoming_attachment(peer, run, False, aggregate, digest, len(raw), "image/png",
        0, raw[:sync.CHUNK_RAW], "wifi_only", phone.now_ms() + 60000)
    # Exact duplicate is idempotent; conflicting bytes are rejected.
    store.stage_incoming_attachment(peer, run, False, aggregate, digest, len(raw), "image/png",
        0, raw[:sync.CHUNK_RAW], "wifi_only", phone.now_ms() + 60000)
    with __import__("pytest").raises(ValueError):
        store.stage_incoming_attachment(peer, run, False, aggregate, digest, len(raw), "image/png",
            0, b"x" * sync.CHUNK_RAW, "wifi_only", phone.now_ms() + 60000)
    reopened = phone.PhoneStore(str(root), "Test")
    assert reopened.attachment_missing_ranges(peer, run, False, aggregate, digest) == []
    sink = io.BytesIO()
    assert reopened.verify_incoming_attachment(peer, run, False, aggregate, digest, sink)
    assert sink.getvalue() == raw
    for path in root.glob("phone.db*"):
        if path.exists():
            assert b"private-signature" not in path.read_bytes()
    reopened.purge_personal(peer)
    assert reopened.attachment_missing_ranges(peer, run, False, aggregate, digest) == []


def test_format2_exact_messages_and_chunk_window(tmp_path):
    run, aggregate, digest = str(uuid.uuid4()), "b" * 64, "c" * 64
    request = {"format": 2, "run_id": run, "reply": False, "records_hash": aggregate,
        "wants": [{"sha256": digest, "ranges": [[0, 9]]}]}
    assert sync.validate_body("personal_sync.attachment_request", request)
    raw = b"\x89PNG\r\n\x1a\n" + b"x" * (sync.CHUNK_RAW * 8)
    digest = hashlib.sha256(raw).hexdigest(); request["wants"][0]["sha256"] = digest
    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer = str(uuid.uuid4())
    store.stage_outgoing_attachment(peer, run, False, aggregate, digest, "image/png", raw,
        "wifi_only", phone.now_ms() + 60000)
    assert store.requested_attachment_chunks(peer, run, False, aggregate, request["wants"], "bluetooth") == []
    assert len(store.requested_attachment_chunks(peer, run, False, aggregate, request["wants"], "wifi")) == 8
    store.complete_outgoing_attachment(peer, run, False, aggregate, digest)
    assert not store.has_outgoing_attachments(peer, run)
    reuse_run, reuse_aggregate = str(uuid.uuid4()), "d" * 64
    descriptor = {"attachment_id": "same", "name": "same.png", "kind": "image",
        "mime": "image/png", "size": len(raw), "sha256": digest}
    assert store.reuse_staged_attachment(peer, reuse_run, False, reuse_aggregate, descriptor,
        "any", phone.now_ms() + 60000)
    assert store.attachment_missing_ranges(peer, reuse_run, False, reuse_aggregate, digest) == []


def test_attachment_security_metadata_columns_fail_closed_when_tampered(tmp_path):
    raw = b"\x89PNG\r\n\x1a\nsecure"
    digest, aggregate = hashlib.sha256(raw).hexdigest(), "a" * 64
    mutations = {
        "peer_id": "'" + str(uuid.uuid4()) + "'", "run_id": "'" + str(uuid.uuid4()) + "'",
        "reply": "1", "records_hash": "'" + "b" * 64 + "'", "sha256": "'" + "c" * 64 + "'",
        "direction": "'incoming'", "size": str(len(raw) + 1), "mime": "'image/jpeg'",
        "transport_policy": "'any'", "expires_ms": "expires_ms+1", "complete": "1",
        "metadata": "zeroblob(length(metadata))",
    }
    for field, expression in mutations.items():
        root = tmp_path / field
        store = phone.PhoneStore(str(root), "Test")
        peer, run = str(uuid.uuid4()), str(uuid.uuid4())
        store.stage_outgoing_attachment(peer, run, False, aggregate, digest, "image/png", raw,
            "wifi_only", phone.now_ms() + 60_000, "attachment-1")
        with __import__("sqlite3").connect(store.database_path) as db:
            db.execute("UPDATE personal_attachment_transfer SET %s=%s" % (field, expression))
        try:
            chunks = store.requested_attachment_chunks(peer, run, False, aggregate,
                [{"sha256": digest, "ranges": [[0, 1]]}], "wifi")
        except Exception:
            chunks = []
        assert chunks == [], field


def test_android_to_desktop_format2_contract_vector_and_run_barrier(tmp_path):
    vector = contract()["format2_cross_platform"]["android_to_desktop"]
    raw = base64.b64decode(vector["data_base64"], validate=True)
    assert len(raw) == vector["size"]
    assert hashlib.sha256(raw).hexdigest() == vector["sha256"]
    assert sync.mime_from_magic(raw) == vector["mime"]
    scenarios = set(contract()["format2_cross_platform"]["scenarios"])
    assert {"interrupted_chunks_resume_missing", "hash_magic_failure_domain_unchanged",
            "format1_fallback", "empty_attachment_list", "duplicate_hash_reuse",
            "additive_omitted", "concurrent_ownership", "save_failure_retry", "revoke",
            "auto_wifi_policy"} == scenarios

    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer, run = str(uuid.uuid4()), str(uuid.uuid4())
    descriptor = {"attachment_id": "pdf", "name": "vector.pdf", "kind": "pdf",
        "mime": vector["mime"], "size": vector["size"], "sha256": vector["sha256"]}
    record = {"kind": "note", "id": "note", "state": "live",
        "clock": [{"actor_id": str(uuid.uuid4()), "counter": 1}], "modified_ms": 1,
        "value": {"title": "", "text": "", "html": "", "notebook_id": "book",
            "symbol": "notiz", "created_ms": 1, "modified_ms": 1, "attachments": [descriptor]}}
    record["hash"] = sync.projection_hash(record["value"])
    aggregate = sync.records_hash([record])
    request = {"format": 2, "run_id": run, "trigger": "manual", "modules": ["notes"]}
    batch = {"format": 2, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0,
        "last": True, "reply": False, "records_hash": aggregate, "records": [record]}
    with __import__("pytest").raises(ValueError):
        store.queue_format2_run(peer, [("personal_sync.request", request, 60000),
            ("personal_sync.batch", batch, 60000)], [(descriptor, raw + b"x")], "any")
    assert store.pending(peer) == []
    assert not store.has_outgoing_attachments(peer, run)
    queued = store.queue_format2_run(peer, [("personal_sync.request", request, 60000),
        ("personal_sync.batch", batch, 60000)], [(descriptor, raw)], "any")
    assert [item["kind"] for item in queued] == ["personal_sync.request", "personal_sync.batch"]
    assert store.has_outgoing_attachments(peer, run)


def test_deletion_messages_are_exact_bounded_and_content_free():
    run, proposal = str(uuid.uuid4()), str(uuid.uuid4())
    item = {"proposal_id": proposal, "kind": "attachment", "id": "att-1",
        "parent_id": "note-1", "clock": contract()["clock"]["left"],
        "prior_hash": "a" * 64, "deleted_ms": 1700000000000, "label": "image.png"}
    body = {"format": 1, "run_id": run, "proposal_batch_id": str(uuid.uuid4()),
        "sequence": 0, "last": True, "proposals": [item]}
    assert sync.validate_body("personal_sync.deletion_proposals", body) is body
    decision = {"format": 1, "run_id": run, "decision_id": str(uuid.uuid4()),
        "decisions": [{"proposal_id": proposal, "decision": "delete",
            "expected_clock": item["clock"]}]}
    assert sync.validate_body("personal_sync.deletion_decision", decision) is decision
    with __import__("pytest").raises(ValueError):
        sync.validate_body("personal_sync.deletion_proposals", dict(body, contents="forbidden"))
    whitespace = copy.deepcopy(body)
    whitespace["proposals"][0]["parent_id"] = contract()["invalid"]["whitespace_parent_id"]
    with __import__("pytest").raises(ValueError):
        sync.validate_body("personal_sync.deletion_proposals", whitespace)
    invalid = contract()["invalid"]
    for identifier in [invalid[name] for name in ("leading_space_id", "trailing_space_id",
            "leading_tab_id", "trailing_tab_id")]:
        for field in ("id", "parent_id"):
            altered = copy.deepcopy(body); altered["proposals"][0][field] = identifier
            with __import__("pytest").raises(ValueError):
                sync.validate_body("personal_sync.deletion_proposals", altered)
    interior = copy.deepcopy(body)
    interior["proposals"][0].update(id=invalid["interior_space_id"],
        parent_id=invalid["interior_space_id"])
    assert sync.validate_body("personal_sync.deletion_proposals", interior) is interior


def test_deletion_proposal_id_is_peer_bound_and_deterministic():
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    clock = contract()["clock"]["left"]
    value = sync.deletion_proposal_id(first, "note", "n", "", clock, "b" * 64)
    assert value == sync.deletion_proposal_id(first, "note", "n", "", clock, "b" * 64)
    assert value != sync.deletion_proposal_id(second, "note", "n", "", clock, "b" * 64)


def test_deletion_proposal_waits_for_document_commit_and_replays(tmp_path):
    delivered = []
    service, peer_id = _personal_service(tmp_path, lambda _event, payload: delivered.append(payload))
    service.store.peer(peer_id)["local_grants"]["grants"]["personal_deletions_sync"] = True
    service.store.peer(peer_id)["grants"]["grants"]["personal_deletions_sync"] = True
    service.store.save_peers()
    run, proposal = str(uuid.uuid4()), str(uuid.uuid4())
    service.store.remember_personal_run(peer_id, {"format": 1, "run_id": run,
        "trigger": "manual", "modules": ["notes"]})
    body = {"format": 1, "run_id": run, "proposal_batch_id": str(uuid.uuid4()),
        "sequence": 0, "last": True, "proposals": [{"proposal_id": proposal,
            "kind": "note", "id": "n", "parent_id": "", "clock": contract()["clock"]["left"],
            "prior_hash": "a" * 64, "deleted_ms": 1, "label": "Private title"}]}
    now = phone.now_ms()
    message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
        "kind": "personal_sync.deletion_proposals", "created_ms": now,
        "expires_ms": now + 60000, "body": body}
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    channel = Channel()
    with mock.patch.object(phone, "PERSONAL_COMMIT_SECONDS", 0.01):
        service._payload(service.store.peer(peer_id), channel, message)
    assert channel.sent == []
    assert service.store.dedupe_result(peer_id, message["message_id"]) is None
    assert len(delivered) == 1
    for path in (tmp_path / "phone").glob("phone.db*"):
        assert b"Private title" not in path.read_bytes()

    reopened = phone.PhoneService(str(tmp_path / "phone"), "Test", callback=lambda _e, value: delivered.append(value))
    reopened.replay_personal_sync()
    replay = delivered[-1]
    assert reopened.commit_personal_sync(peer_id, replay["pending_message_id"], replay["commit_token"], True)
    assert reopened.store.dedupe_result(peer_id, message["message_id"]) == ("accepted", "none")
    assert reopened.store.ready_personal_domains() == []


def test_expired_personal_classes_are_terminal_before_dedupe_or_dispatch(tmp_path):
    delivered = []
    service, peer = _personal_service(tmp_path, lambda event, value: delivered.append((event, value)))
    service.store.peer(peer)["local_grants"]["grants"]["personal_deletions_sync"] = True
    service.store.peer(peer)["grants"]["grants"]["personal_deletions_sync"] = True
    service.store.save_peers()
    run = str(uuid.uuid4())
    now = phone.now_ms()
    with mock.patch.object(phone, "now_ms", return_value=now - phone.DAY_MS - 1):
        service.store.remember_personal_run(peer, {"format": 1, "run_id": run,
            "trigger": "manual", "modules": ["notes"]})
    zero = {"notes": 0, "tasks": 0, "notebooks": 0}
    digest, proposal = "a" * 64, str(uuid.uuid4())
    bodies = {
        "personal_sync.batch": {"format": 1, "run_id": run, "batch_id": str(uuid.uuid4()),
            "sequence": 0, "last": True, "reply": True, "records": []},
        "personal_sync.attachment_request": {"format": 2, "run_id": run, "reply": True,
            "records_hash": digest, "wants": [{"sha256": digest, "ranges": [[0, 1]]}]},
        "personal_sync.attachment_chunk": {"format": 2, "run_id": run, "reply": True,
            "records_hash": digest, "sha256": digest, "index": 0, "data": "eA=="},
        "personal_sync.attachment_result": {"format": 2, "run_id": run, "reply": True,
            "records_hash": digest, "sha256": digest, "state": "complete", "error": "none"},
        "personal_sync.deletion_proposals": {"format": 1, "run_id": run,
            "proposal_batch_id": str(uuid.uuid4()), "sequence": 0, "last": True, "proposals": []},
        "personal_sync.deletion_decision": {"format": 1, "run_id": run,
            "decision_id": str(uuid.uuid4()), "decisions": [{"proposal_id": proposal,
                "decision": "delete", "expected_clock": contract()["clock"]["left"]}]},
        "personal_sync.report": {"format": 1, "run_id": run, "state": "complete",
            "trigger": "manual", "transport": "wifi", "sent": zero, "received": zero,
            "conflicts": 0, "attachments_omitted": 0, "oversized_skipped": 0,
            "started_ms": 1, "finished_ms": 1, "error": "none", "deletions": {
                "pending": 0, "deleted": 0, "restored": 0, "conflicts": 0, "blocked": 0,
                "trash": {"notes": 0, "tasks": 0, "notebooks": 0, "attachments": 0}}},
    }
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    channel = Channel()
    for kind, body in bodies.items():
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()), "kind": kind,
            "created_ms": now, "expires_ms": now + 60_000, "body": body}
        service._payload(service.store.peer(peer), channel, message)
        assert channel.sent[-1]["status"] == "rejected" and channel.sent[-1]["error"] == "expired"
        assert service.store.dedupe_result(peer, message["message_id"]) == ("rejected", "expired")
    assert delivered == [] and service.store.ready_personal_batches() == []
    assert service.store.ready_personal_domains() == [] and not service.store.has_outgoing_attachments(peer, run)

    queued = service.store.queue(peer, "personal_sync.report", bodies["personal_sync.report"], 60_000, "any")
    with __import__("pytest").raises(ValueError):
        service._payload(service.store.peer(peer), channel, {"type": "ack",
            "message_id": queued["message_id"], "status": "accepted", "error": "none"})
    assert any(item["message_id"] == queued["message_id"] for item in service.store.pending(peer))


def test_report_deletion_counters_are_exact():
    counts = {"notes": 0, "tasks": 0, "notebooks": 0}
    body = {"format": 1, "run_id": str(uuid.uuid4()), "state": "complete", "trigger": "manual",
        "transport": "wifi", "sent": counts, "received": counts, "conflicts": 0,
        "attachments_omitted": 0, "oversized_skipped": 0, "started_ms": 1, "finished_ms": 2,
        "error": "none", "deletions": {"pending": 2, "deleted": 1, "restored": 1,
            "conflicts": 1, "blocked": 0, "trash": {"notes": 1, "tasks": 0,
                "notebooks": 0, "attachments": 0}}}
    assert sync.validate_body("personal_sync.report", body)
    with __import__("pytest").raises(ValueError):
        sync.validate_body("personal_sync.report", dict(body, deletions=dict(body["deletions"], extra=0)))
