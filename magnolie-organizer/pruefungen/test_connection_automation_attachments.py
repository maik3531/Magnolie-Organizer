import base64
import sqlite3
import uuid

import pytest

import magnolie_content_scope as scope
import magnolie_personal_sync as personal
from test_content_scope_transport import connection_automation_fixture, message, reconnect_automation_fixture
from test_personal_attachment_manifest import RAW, _descriptor, _record


@pytest.mark.parametrize("variant", ["original", "replacement", "corrupt", "two_windows"])
def test_connection_attachment_waits_for_verified_bytes_from_original_reader(tmp_path, monkeypatch, variant):
    service, peer, reader, remote, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    peer_id = peer["device_id"]
    run = str(uuid.uuid4())
    raw = RAW + b"x" * (8 * personal.CHUNK_RAW) if variant == "two_windows" else RAW
    descriptor = _descriptor(raw, "original.png")
    record = dict(_record(1, [descriptor]), id=manifest["members"]["notes"][0])
    digest, records_hash = descriptor["sha256"], personal.records_hash([record])
    events = []

    def collect(event, body):
        events.append((event, body))
        if event == "personal_sync":
            assert service.commit_personal_sync(peer_id, body["pending_message_id"], body["commit_token"], False)

    def send(channel, kind, body):
        packet = dict(message(scope.wrap(kind, body, manifest)), kind=scope.DATA_KIND)
        service._payload(peer, channel, packet)
        return next(item for item in channel.sent if item.get("message_id") == packet["message_id"])

    service.callback = collect
    assert send(reader, "personal_sync.request", {"format": 3, "run_id": run, "trigger": personal.AUTO_CONNECTION_TRIGGER,
                "modules": ["notes", "tasks"]})["status"] == "accepted"
    batch = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
             "reply": False, "records": [record], "records_hash": records_hash}
    assert send(reader, "personal_sync.batch", batch)["status"] == "accepted"
    assert not any(event == "personal_sync" for event, _ in events)
    assert not any(event == "personal_sync_attachment_index" for event, _ in events)
    with pytest.raises(PermissionError, match="require the original reader"):
        service.index_local_attachments(peer_id, run, False, records_hash, [])
    wants, = [wire for wire in reader.sent if wire.get("kind") == scope.DATA_KIND
              and wire["body"]["kind"] == "personal_sync.attachment_request"]
    expected_end = 8 if variant == "two_windows" else 1
    assert wants["body"]["body"]["wants"] == [{"sha256": digest, "ranges": [[0, expected_end]]}]
    assert service.store.outbox_policy(peer_id, wants["message_id"]) == "connection_only"
    staged, = [aggregate for stored_peer, aggregate in service.store.ready_personal_batches() if stored_peer == peer_id]
    claim = {"peer": peer_id, "messageId": staged["message_id"], "token": staged["commit_token"], "before": "a" * 64}
    with pytest.raises(PermissionError, match="bytes have not been verified"):
        service.prepare_connection_batch_save(claim, "{}", "fixture-book")

    if variant == "two_windows":
        def receive_window(request, start, end):
            service._payload(peer, reader, {"type": "ack", "message_id": request["message_id"], "status": "accepted", "error": "none"})
            for index in range(start, end):
                part = raw[index * personal.CHUNK_RAW:(index + 1) * personal.CHUNK_RAW]
                assert send(reader, "personal_sync.attachment_chunk", {"format": 2, "run_id": run, "reply": False,
                    "records_hash": records_hash, "sha256": digest, "index": index, "data": base64.b64encode(part).decode()})["status"] == "accepted"
                if index < end - 1:
                    assert [item for item in reader.sent if item.get("kind") == scope.DATA_KIND
                            and item["body"]["kind"] == "personal_sync.attachment_request"][-1] == request

        receive_window(wants, 0, 8)
        assert not any(event == "personal_sync" for event, _ in events)
        second = [item for item in reader.sent if item.get("kind") == scope.DATA_KIND
                  and item["body"]["kind"] == "personal_sync.attachment_request"][-1]
        assert second["message_id"] != wants["message_id"]
        assert second["body"]["body"]["wants"] == [{"sha256": digest, "ranges": [[8, 9]]}]
        receive_window(second, 8, 9)
        delivered, = [body for event, body in events if event == "personal_sync"]
        assert base64.b64decode(delivered["body"]["attachment_data"][digest].split(",", 1)[1]) == raw
        return

    original_bytes = base64.b64encode(RAW).decode("ascii")
    delivered_bytes = base64.b64encode(RAW[:-1] + b"x").decode("ascii") if variant == "corrupt" else original_bytes
    chunk = {"format": 2, "run_id": run, "reply": False, "records_hash": records_hash,
             "sha256": digest, "index": 0, "data": delivered_bytes}
    channel = reconnect_automation_fixture(service, peer, reader, remote, manifest) if variant == "replacement" else reader
    ack = send(channel, "personal_sync.attachment_chunk", chunk)
    if variant == "replacement":
        assert (ack["status"], ack["error"]) == ("rejected", "not_granted")
        assert service.store.attachment_missing_ranges(peer_id, run, False, records_hash, digest) == [[0, 1]]
        assert not any(event == "personal_sync" for event, _ in events)
    elif variant == "corrupt":
        assert ack["status"] == "accepted"  # The transport ACK covers encrypted staging only.
        assert not any(event == "personal_sync" for event, _ in events)
        assert any(event == "personal_sync_error" for event, _ in events)
    else:
        assert ack["status"] == "accepted"
        delivered, = [body for event, body in events if event == "personal_sync"]
        assert delivered["transport"] == "bluetooth" and delivered["body"]["trigger"] == personal.AUTO_CONNECTION_TRIGGER
        assert delivered["body"]["records"] == [record]
        assert delivered["body"]["attachment_data"] == {digest: "data:image/png;base64," + original_bytes}
        assert service.prepare_connection_batch_save(claim, "{}", "fixture-book").token == staged["commit_token"]


def test_connection_start_keeps_its_original_until_every_sent_chunk_is_acknowledged(tmp_path, monkeypatch):
    service, peer, reader, _, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    peer_id = peer["device_id"]
    run_id = str(uuid.uuid4())
    request = {"format": 3, "run_id": run_id, "trigger": personal.AUTO_CONNECTION_TRIGGER,
               "modules": ["notes", "tasks"]}
    raw = RAW + b"a" * (8 * personal.CHUNK_RAW)
    descriptor = _descriptor(raw, "organizer-original.png")
    record = dict(_record(1, [descriptor]), id=manifest["members"]["notes"][0])
    digest, aggregate = descriptor["sha256"], personal.records_hash([record])
    batch = {"format": 3, "run_id": run_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
             "reply": False, "records": [record], "records_hash": aggregate}

    def frames(kind):
        return [item for item in reader.sent if item.get("kind") == scope.DATA_KIND and item["body"]["kind"] == kind]

    def acknowledge(frame):
        service._payload(peer, reader, {"type": "ack", "message_id": frame["message_id"], "status": "accepted", "error": "none"})

    def packet(kind, **values):
        return dict(message(scope.wrap(kind, dict(format=2, run_id=run_id, reply=False,
            records_hash=aggregate, **values), manifest)), kind=scope.DATA_KIND)

    def receive(frame):
        service._payload(peer, reader, frame)
        return next(item for item in reversed(reader.sent) if item.get("message_id") == frame["message_id"])

    data = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    service.send_personal_sync_run(peer_id, request, [batch], [{"sha256": digest, "data": data}], request["trigger"])
    first = packet("personal_sync.attachment_request", wants=[{"sha256": digest, "ranges": [[0, 8]]}])
    assert receive(first)["status"] == "rejected"
    assert not frames("personal_sync.attachment_chunk")
    acknowledge(frames("personal_sync.request")[0])
    acknowledge(frames("personal_sync.batch")[0])
    large = packet("personal_sync.attachment_request", wants=[{"sha256": digest, "ranges": [[0, 9]]}])
    assert receive(large)["status"] == "rejected"
    second = packet("personal_sync.attachment_request", wants=[{"sha256": digest, "ranges": [[8, 9]]}])
    result = packet("personal_sync.attachment_result", sha256=digest, state="complete", error="none")
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("CREATE TRIGGER fail_connection_window_receipt BEFORE INSERT ON inbox "
                   "WHEN NEW.kind='personal_sync.attachment_request' BEGIN SELECT RAISE(ABORT,'window receipt fault'); END")
    try:
        assert receive(first)["error"] == "temporary_failure"
        assert not frames("personal_sync.attachment_chunk")
        assert service.store.dedupe_result(peer_id, first["message_id"]) is None
        with sqlite3.connect(service.store.database_path) as db:
            assert not db.execute("SELECT 1 FROM outbox WHERE kind='personal_sync.attachment_chunk'").fetchone()
    finally:
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("DROP TRIGGER fail_connection_window_receipt")
    assert receive(first)["status"] == "accepted"
    assert receive(first)["status"] == "duplicate"
    assert receive(second)["status"] == "rejected"
    assert receive(result)["status"] == "rejected"
    for frame in frames("personal_sync.attachment_chunk"):
        acknowledge(frame)
    assert receive(second)["status"] == "accepted"
    chunks = sorted(frames("personal_sync.attachment_chunk"), key=lambda item: item["body"]["body"]["index"])
    assert [item["body"]["body"]["index"] for item in chunks] == list(range(9))
    assert b"".join(base64.b64decode(item["body"]["body"]["data"]) for item in chunks) == raw
    assert receive(result)["status"] == "rejected"
    acknowledge(chunks[-1])
    assert receive(result)["status"] == "accepted"
    assert receive(result)["status"] == "duplicate"
    assert service.store.outgoing_attachment_complete(peer_id, run_id, False, aggregate, digest)
    assert service.store.personal_success(peer_id) is None
