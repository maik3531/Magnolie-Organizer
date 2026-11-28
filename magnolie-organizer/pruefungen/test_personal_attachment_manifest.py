"""Attachment references are checked before ordinary Personal Sync staging."""
import base64
import hashlib
import sqlite3
import uuid

import pytest

from test_personal_sync import _personal_service, phone, sync

RAW = b"\x89PNG\r\n\x1a\nfixture"
PDF = b"%PDF-fixture"


def _descriptor(raw, name, mime="image/png"):
    return dict(attachment_id=name, name=name, kind="image" if mime.startswith("image/") else "pdf",
                mime=mime, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def _record(index, items):
    value = dict(title="note", text="", html="", notebook_id="", symbol="",
                 created_ms=1, modified_ms=2, attachments=items)
    return dict(kind="note", id=str(index), state="live",
                clock=[dict(actor_id="00000000-0000-4000-8000-000000000001", counter=1)],
                hash=sync.projection_hash(value), modified_ms=2, value=value)


def _received_batches(store, peer, records, split):
    run = str(uuid.uuid4())
    request = dict(format=2, run_id=run, trigger="manual", modules=["notes"])
    store.remember_personal_run(peer, request)
    groups = [[record] for record in records] if split else [records]
    now = phone.now_ms()
    return [dict(type="message", v=1, kind="personal_sync.batch", message_id=str(uuid.uuid4()),
                 created_ms=now, expires_ms=now + 60_000,
                 body=dict(format=2, run_id=run, batch_id=str(uuid.uuid4()), sequence=index,
                           last=index == len(groups) - 1, reply=False, records=group,
                           records_hash=sync.records_hash(records)))
            for index, group in enumerate(groups)]


@pytest.mark.parametrize("field,value", [("size", 23), ("mime", "application/pdf")])
@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_received_attachment_conflict_has_no_accepted_ack(tmp_path, field, value, split, reverse):
    service, peer = _personal_service(tmp_path, lambda *_: None)
    peer_record = service.store.peer(peer)
    peer_record["capabilities"] = phone.desktop_capabilities()
    peer_record["capabilities"]["items"]["personal_notes_sync"]["versions"] = [1, 2]
    service.store.save_peers()
    first, second = _descriptor(RAW, "a.png"), _descriptor(RAW, "b.png")
    second[field] = value
    if field == "mime":
        second.update(kind="pdf", name="b.pdf")
    if reverse:
        first, second = second, first
    messages = _received_batches(service.store, peer, [_record(1, [first]), _record(2, [second])], split)
    sent = []
    channel = type("Channel", (), {"send": staticmethod(sent.append)})()
    service.connections[peer] = channel
    service.connection_transports[peer] = "wifi"
    for message in messages:
        service._payload(peer_record, channel, message)
    assert [(ack["message_id"], ack["status"], ack["error"]) for ack in sent if ack["type"] == "ack"] == (
        [(messages[0]["message_id"], "accepted", "none")] * int(split) +
        [(messages[-1]["message_id"], "rejected", "invalid_schema")])
    run = messages[-1]["body"]["run_id"]
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT sequence FROM personal_batch WHERE peer_id=? AND run_id=?", (peer, run)).fetchall() == (
            [(0,)] if split else [])
        assert db.execute("SELECT COUNT(*) FROM personal_attachment_transfer WHERE peer_id=? AND run_id=?",
                          (peer, run)).fetchone()[0] == 0
    assert service.store.dedupe_result(peer, messages[-1]["message_id"]) == ("rejected", "invalid_schema")


def test_historical_attachment_conflict_does_not_block_other_run(tmp_path, monkeypatch):
    store = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    peer = str(uuid.uuid4())
    first = _descriptor(RAW, "a.png")
    historical = _received_batches(store, peer, [_record(1, [first]), _record(2, [dict(first, size=23)])], True)
    current = _received_batches(store, peer, [_record(1, [first]), _record(2, [dict(first, name="b.png")])], True)
    with monkeypatch.context() as import_legacy:
        import_legacy.setattr(phone, "_check_attachment_manifest", lambda *_: None)
        for message in historical + current:
            store.stage_personal_batch(peer, message)

    def history_rows():
        with sqlite3.connect(store.database_path) as db:
            run = historical[0]["body"]["run_id"]
            return db.execute("SELECT * FROM personal_batch WHERE peer_id=? AND run_id=? ORDER BY sequence",
                              (peer, run)).fetchall()

    before = history_rows()
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    ready = reopened.ready_personal_batches()
    assert [aggregate["run_id"] for _, aggregate in ready] == [current[0]["body"]["run_id"]]
    assert len(before) == 2 and history_rows() == before


@pytest.mark.parametrize("mutation, split, reverse", [
    ("size", False, False), ("size", True, False), ("mime", False, False), ("mime", True, False),
    ("size", False, True), ("mime", False, True), ("none", False, False), ("none", True, False),
    ("distinct", False, False), ("empty", False, False),
])
def test_grouped_attachment_manifest_before_any_staging(tmp_path, mutation, split, reverse):
    service, peer = _personal_service(tmp_path, lambda *_: None)
    service.store.peer(peer)["capabilities"] = phone.desktop_capabilities()
    service.store.save_peers()
    first = _descriptor(RAW, "a.png")
    second = _descriptor(RAW, "b.png")
    raw_sources = [RAW]
    if mutation == "size":
        first["size"] += 1
    elif mutation == "mime":
        first.update(mime="application/pdf", kind="pdf")
    elif mutation == "distinct":
        second = _descriptor(PDF, "c.pdf", "application/pdf")
        raw_sources.append(PDF)
    if reverse:
        first, second = second, first
    records = [_record(1, [first]), _record(2, [second])]
    if mutation == "empty":
        records = [_record(1, [])]
        raw_sources = []
    groups = [[record] for record in records] if split else [records]
    request = dict(format=2, run_id=str(uuid.uuid4()), trigger="auto_wifi", modules=["notes"])
    run = request["run_id"]
    batches = [dict(format=2, run_id=run, batch_id=str(uuid.uuid4()), sequence=index,
                    last=index == len(groups) - 1, reply=False, records=group,
                    records_hash=sync.records_hash(records)) for index, group in enumerate(groups)]
    sources = [dict(sha256=hashlib.sha256(raw).hexdigest(),
                    data="data:" + sync.mime_from_magic(raw) + ";base64," +
                    base64.b64encode(raw).decode("ascii")) for raw in raw_sources]
    if mutation in ("size", "mime"):
        with pytest.raises(ValueError, match="conflicting attachment manifest"):
            service.send_personal_sync_run(peer, request, batches, sources)
        reopened = phone.PhoneStore(str(tmp_path / "phone"), "Test")
        assert reopened.personal_run(peer, run) == {}
        assert reopened.active_auto_run(peer) == ""
        assert reopened.pending(peer, "wifi") == []
        expected = 0
    else:
        service.send_personal_sync_run(peer, request, batches, sources)
        assert service.store.personal_run(peer, run) == request
        queued = service.store.pending(peer, "wifi")
        assert len(queued) == 1 + len(groups)
        sent = sorted((message["body"] for message in queued if message["kind"] == "personal_sync.batch"),
                      key=lambda batch: batch["sequence"])
        assert [record for batch in sent for record in batch["records"]] == records
        expected = len(raw_sources)
    with sqlite3.connect(service.store.database_path) as db:
        for table in ("personal_attachment_transfer", "personal_attachment_chunk"):
            assert db.execute("SELECT COUNT(*) FROM " + table + " WHERE peer_id=? AND run_id=?",
                              (peer, run)).fetchone()[0] == expected
