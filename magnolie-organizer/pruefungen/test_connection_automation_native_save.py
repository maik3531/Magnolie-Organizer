import base64
import hashlib
import json
import queue
import sqlite3
import threading
import uuid
from types import MethodType, SimpleNamespace

import pytest

import magnolie_content_scope as scope
import magnolie_personal_sync as personal
import magnolie_telefon as phone
from magnolie_personal_actor_store import NativeBookOwnerScope
from test_content_scope_transport import connection_automation_fixture, message, reconnect_automation_fixture
from test_personal_actor_historical_file_writer import native_store
from test_personal_attachment_manifest import RAW, _descriptor


@pytest.mark.parametrize("stale", [False, True])
def test_connection_gui_start_uses_exact_native_writer_ack(tmp_path, monkeypatch, stale):
    native = native_store(tmp_path, monkeypatch)
    service, peer, reader, _, manifest = connection_automation_fixture(tmp_path / "phone", monkeypatch, "bluetooth",
        peer_id="ffffffff-ffff-4fff-bfff-ffffffffffff")
    reader.last_capabilities = phone.desktop_capabilities()
    peer_id = peer["device_id"]
    current = {"notizen": [{"id": "phone-note", "titel": "Before"}], "personalSync": {"applied_batches": []}}
    before = json.dumps(current)
    password = "synthetic-connection-start"
    encrypted, dek, dek_id, wrapper = native.daten_huelle_anlegen(before, password)
    path = tmp_path / "organizer-book.json"
    monkeypatch.setattr(native, "daten_datei", lambda: str(path))
    monkeypatch.setattr(native, "erinnerungsdaten_schreiben", lambda **_kwargs: True)
    native.speichere_text(encrypted)
    owner = NativeBookOwnerScope()
    owner.set_ready(True)
    replies = queue.Queue()
    window = SimpleNamespace(_organizer_vertraut=lambda: True, _darf_schreiben=lambda: True,
        _kennwort=password, _daten_dek=dek, _daten_dek_kennung=dek_id, _daten_umschlag=wrapper,
        _aktuelle_daten=current, _daten_sperre=threading.RLock(), _speicher_auftraege=queue.Queue(),
        _gesperrt=False, _ladefehler="", _telefon=service, _baum_sync_snapshot=native.BaumSyncSnapshot(),
        _notes_actor_book_owner=owner, _telefon_actor_buchbindung=lambda: ("synthetic-native-book", True),
        _journal_snapshot=lambda _reason: None, antwort=lambda callback, args: replies.put((callback, args)))
    for name in ("_vielleicht_verschluesseln", "_telefon_actor_buchquelle", "_telefon_actor_buchnachweis"):
        setattr(window, name, MethodType(getattr(native.Fenster, name), window))
    service.native_actor_book_source = window._telefon_actor_buchquelle
    service.native_actor_saved_book = window._telefon_actor_buchnachweis

    def bridge(cmd, **data):
        native.Fenster.bei_nachricht(window, json.dumps({"cmd": cmd, **data}))
        return replies.get(timeout=10)

    worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(window,), daemon=True)
    worker.start()
    try:
        callback, first = bridge("speichern", id=1, text=before)
        assert callback == "App.gespeichert" and first["committed"] is True
        peer_status, = service.report()["peers"]
        assert peer_status["gui_connection_start"] is True
        callback, prepared = bridge("telefon_personal_connection_prepare", requestId="prepare", kennung=peer_id,
                                    fingerprint=peer_status["fingerprint"])
        assert callback == "App.personalConnectionStartErgebnis" and prepared["ok"]
        plan = prepared["plan"]
        assert plan["scope"] == manifest
        after = json.dumps(dict(current, notizen=[{"id": "phone-note", "titel": "After"}]))
        callback, second = bridge("speichern", id=2, text=after)
        assert callback == "App.gespeichert" and second["committed"] is True
        assert native.daten_entschluesseln(path.read_text(), password) == after
        assert second["standSha256"] != first["standSha256"]
        request = {"format": plan["format"], "run_id": plan["run_id"], "trigger": "auto_connection",
                   "modules": ["notes", "tasks"]}
        batch = {"format": plan["format"], "run_id": plan["run_id"], "batch_id": str(uuid.uuid4()), "sequence": 0,
                 "last": True, "reply": False, "records": [], "records_hash": personal.records_hash([])}
        reader.sent.clear()
        callback, started = bridge("telefon_personal_connection_start", requestId="start", kennung=peer_id,
            token=plan["token"], savedHash=(first if stale else second)["standSha256"], request=request,
            batches=[batch], sources=[])
        assert callback == "App.personalConnectionStartErgebnis" and started["ok"] is not stale
        if stale:
            assert reader.sent == []
        else:
            assert reader.sent[-1]["body"] == scope.wrap("personal_sync.request", request, manifest)
    finally:
        window._speicher_auftraege.put(None)
        worker.join(timeout=10)
        assert not worker.is_alive()


@pytest.mark.parametrize("case", ["current", "reader_replaced", "book_reopened", "independent_save",
                                  "reader_replaced_after_save", "reply", "reply_rejected",
                                  "reply_report_replaced", "reply_sql_retry", "received_attachment", "outgoing_attachment",
                                  "attachment_reader_replaced", "manual", "initiator_report"])
def test_connection_batch_save_checks_original_reader_at_the_native_worker(tmp_path, monkeypatch, case):
    native = native_store(tmp_path, monkeypatch)
    service, peer, reader, remote, manifest = connection_automation_fixture(tmp_path / "phone", monkeypatch, "bluetooth")
    peer_id = peer["device_id"]
    run = str(uuid.uuid4())
    request = {"format": 3, "run_id": run, "trigger": personal.AUTO_CONNECTION_TRIGGER, "modules": ["notes", "tasks"]}

    def send(kind, body):
        packet = dict(message(scope.wrap(kind, body, manifest)), kind=scope.DATA_KIND)
        service._payload(peer, reader, packet)
        ack = next(item for item in reader.sent if item.get("message_id") == packet["message_id"])
        assert ack["status"] == "accepted"

    if case == "initiator_report":
        initial = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
                   "reply": False, "records": [], "records_hash": personal.records_hash([])}
        service.send_personal_sync_run(peer_id, request, [initial], [], request["trigger"])
        for kind in ("personal_sync.request", "personal_sync.batch"):
            frame = next(item for item in reader.sent if item.get("kind") == scope.DATA_KIND and item["body"]["kind"] == kind)
            service._payload(peer, reader, {"type": "ack", "message_id": frame["message_id"], "status": "accepted", "error": "none"})
    else:
        send("personal_sync.request", request)
    value = {"title": "Phone edit", "text": "Changed", "html": "", "notebook_id": "", "symbol": "note",
             "created_ms": 1, "modified_ms": 2, "attachments": []}
    if case == "received_attachment":
        attachment = _descriptor(RAW, "phone.png")
        value["attachments"].append(attachment)
    record = {"kind": "note", "id": "phone-note", "state": "live", "clock": [{"actor_id": peer_id, "counter": 1}],
              "hash": personal.projection_hash(value), "modified_ms": 2, "value": value}
    delivered = []

    def stage(event, payload):
        if event == "personal_sync":
            delivered.append(payload)
            if payload["kind"] == "personal_sync.batch":
                assert service.commit_personal_sync(peer_id, payload["pending_message_id"], payload["commit_token"], False)

    service.callback = stage
    send("personal_sync.batch", {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()),
          "sequence": 0, "last": True, "reply": case in {"current", "reader_replaced_after_save", "received_attachment", "initiator_report"},
         "records": [record], "records_hash": personal.records_hash([record])})
    if case == "received_attachment":
        assert delivered == []
        send("personal_sync.attachment_chunk", {"format": 2, "run_id": run, "reply": True,
            "records_hash": personal.records_hash([record]), "sha256": attachment["sha256"],
            "index": 0, "data": base64.b64encode(RAW).decode("ascii")})
    batch, = delivered
    message_id, token = batch["pending_message_id"], batch["commit_token"]
    if case == "initiator_report":
        zero = dict.fromkeys(("notes", "tasks", "notebooks"), 0)
        report = {"format": 3, "run_id": run, "state": "complete", "trigger": request["trigger"], "transport": "bluetooth",
                  "sent": dict(zero, notes=1), "received": zero, "conflicts": 0, "attachments_omitted": 0,
                  "oversized_skipped": 0, "started_ms": 1, "finished_ms": 2, "error": "none",
                  "deletions": dict.fromkeys(("pending", "deleted", "restored", "conflicts", "blocked"), 0) |
                      {"trash": dict(zero, attachments=0)},
                  "attachments": dict.fromkeys(("declared", "requested", "sent", "received", "reused", "preserved", "failed", "bytes"), 0)}
        report_frame = dict(message(scope.wrap("personal_sync.report", report, manifest)), kind=scope.DATA_KIND)
        service._payload(peer, reader, report_frame)
        assert reader.sent[-1]["status"] == "rejected"
        assert service.store.personal_success(peer_id) is None
        assert service.store.dedupe_result(peer_id, report_frame["message_id"]) is None

    current = {"notizen": [{"id": "phone-note", "titel": "Before"}], "personalSync": {"applied_batches": []}}
    before = json.dumps(current)
    password = "synthetic-connection-work"
    encrypted, dek, dek_id, wrapper = native.daten_huelle_anlegen(before, password)
    path = tmp_path / "organizer-book.json"
    monkeypatch.setattr(native, "daten_datei", lambda: str(path))
    monkeypatch.setattr(native, "erinnerungsdaten_schreiben", lambda **_kwargs: True)
    native.speichere_text(encrypted)
    original = path.read_bytes()
    save_lease = native.BaumSyncSnapshot()
    save_lease.ack = hashlib.sha256(before.encode()).hexdigest()
    owner = NativeBookOwnerScope()
    owner.set_ready(True)
    responses = []
    window = SimpleNamespace(_organizer_vertraut=lambda: True, _darf_schreiben=lambda: True,
        _kennwort=password, _daten_dek=dek, _daten_dek_kennung=dek_id, _daten_umschlag=wrapper,
        _aktuelle_daten=current, _daten_sperre=threading.RLock(), _speicher_auftraege=queue.Queue(),
        _gesperrt=False, _ladefehler="", _telefon=service, _baum_sync_snapshot=save_lease,
        _notes_actor_book_owner=owner, _telefon_actor_buchbindung=lambda: ("synthetic-native-book", True),
        _journal_snapshot=lambda _reason: None, antwort=lambda callback, args: responses.append((callback, args)))
    for name in ("_vielleicht_verschluesseln", "_telefon_actor_buchquelle", "_telefon_actor_buchnachweis"):
        setattr(window, name, MethodType(getattr(native.Fenster, name), window))
    service.native_actor_saved_book = window._telefon_actor_buchnachweis
    assert not service.commit_personal_sync(peer_id, message_id, token, True), "A Boolean receipt bypassed the native book writer."
    candidate = {"notizen": [{"id": "phone-note", "titel": "Manual edit" if case == "manual" else value["title"]}],
                 "personalSync": {"applied_batches": [] if case == "manual" else [token]}}
    if case == "received_attachment":
        original_data = batch["body"]["attachment_data"][attachment["sha256"]]
        candidate["notizen"][0]["anhaenge"] = [{"id": attachment["attachment_id"], "daten": original_data}]
        assert not any(item.get("kind") == scope.DATA_KIND and item["body"]["kind"] == "personal_sync.attachment_result" for item in reader.sent)
    payload = {"cmd": "speichern", "id": 1, "text": json.dumps(candidate)}
    if case != "manual":
        payload["personalConnectionLauf"] = {"peer": peer_id, "messageId": message_id, "token": token,
                                            "before": save_lease.ack}
    native.Fenster.bei_nachricht(window, json.dumps(payload))
    assert window._speicher_auftraege.qsize() == 1, responses
    if case == "reader_replaced":
        reconnect_automation_fixture(service, peer, reader, remote, manifest)
    elif case == "book_reopened":
        owner.invalidate()
    elif case == "independent_save":
        private_job = window._speicher_auftraege.get_nowait()
        window._speicher_auftraege.task_done()
        independently_saved = dict(current, notizen=[{"id": "phone-note", "titel": "Independent edit"}])
        native.Fenster.bei_nachricht(window, json.dumps({"cmd": "speichern", "id": 2, "text": json.dumps(independently_saved)}))
        window._speicher_auftraege.put(private_job)
    window._speicher_auftraege.put(None)
    worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(window,), daemon=True)
    worker.start()
    worker.join(timeout=15)
    assert not worker.is_alive()
    ack, = [result for callback, result in responses if callback == "App.gespeichert" and result["id"] == 1]
    if case in {"reader_replaced", "book_reopened", "independent_save"}:
        assert ack["ok"] is False
        if case == "independent_save":
            assert native.daten_entschluesseln(path.read_text(), password) == json.dumps(independently_saved)
            assert window._aktuelle_daten == independently_saved
        else:
            assert path.read_bytes() == original
            assert window._aktuelle_daten == current
        assert service.store.has_personal_batch(peer_id, message_id, token)
    else:
        assert ack["ok"] is True, ack
        assert native.daten_entschluesseln(path.read_text(), password) == payload["text"]
        if case in {"outgoing_attachment", "attachment_reader_replaced"}:
            attachment = _descriptor(RAW, "organizer.png")
            value = dict(record["value"], attachments=[attachment])
            original = dict(record, value=value, hash=personal.projection_hash(value))
            digest = personal.records_hash([original])
            reply = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
                     "reply": True, "records": [original], "records_hash": digest}
            sources = [{"sha256": attachment["sha256"], "data": "data:image/png;base64," + base64.b64encode(RAW).decode("ascii")}]
            with pytest.raises(ValueError, match="sources do not match"):
                service.finish_connection_batch_reply(peer_id, message_id, token, [reply])
            with sqlite3.connect(service.store.database_path) as db:
                db.execute("""CREATE TRIGGER fail_connection_chunk BEFORE INSERT ON personal_attachment_chunk
                    WHEN NEW.direction='outgoing' BEGIN SELECT RAISE(ABORT,'test encrypted chunk fault'); END""")
            with pytest.raises(sqlite3.IntegrityError, match="test encrypted chunk fault"):
                service.finish_connection_batch_reply(peer_id, message_id, token, [reply], sources=sources)
            assert service.store.has_personal_batch(peer_id, message_id, token)
            with sqlite3.connect(service.store.database_path) as db:
                assert not db.execute("SELECT 1 FROM personal_attachment_transfer WHERE direction='outgoing'").fetchone()
                assert not db.execute("SELECT 1 FROM outbox WHERE kind IN ('personal_sync.batch','personal_sync.report')").fetchone()
                db.execute("DROP TRIGGER fail_connection_chunk")
            reply_id, = service.finish_connection_batch_reply(peer_id, message_id, token, [reply], sources=sources)
            receipt = {"type": "ack", "message_id": reply_id, "status": "accepted", "error": "none"}
            service._payload(peer, reader, receipt)
            with sqlite3.connect(service.store.database_path) as db:
                report_id, = db.execute("SELECT message_id FROM outbox WHERE kind='personal_sync.report'").fetchone()
                encrypted, = db.execute("SELECT payload FROM personal_attachment_chunk WHERE direction='outgoing'").fetchone()
                assert RAW not in encrypted
            report = service.store.outbox_message(peer_id, report_id)
            result = {"format": 2, "run_id": run, "reply": True, "records_hash": digest,
                      "sha256": attachment["sha256"], "state": "complete", "error": "none"}
            request_attachment = {key: result[key] for key in ("format", "run_id", "reply", "records_hash")}
            request_attachment["wants"] = [{"sha256": attachment["sha256"], "ranges": [[0, 1]]}]
            assert not service._send_message(reader, peer_id, report)

            def attachment_packet(kind, body):
                return dict(message(scope.wrap(kind, body, manifest)), kind=scope.DATA_KIND)

            early = attachment_packet("personal_sync.attachment_result", result)
            service._payload(peer, reader, early)
            assert reader.sent[-1]["error"] == "not_granted"
            assert service.store.requested_attachment_chunks(peer_id, run, True, digest, request_attachment["wants"], "bluetooth") == []
            service._payload(peer, reader, attachment_packet("personal_sync.attachment_request", request_attachment))
            chunks = [item for item in reader.sent if item.get("kind") == scope.DATA_KIND
                      and item["body"]["kind"] == "personal_sync.attachment_chunk"]
            chunk, = chunks
            assert base64.b64decode(chunk["body"]["body"]["data"]) == RAW
            assert service.store.outbox_policy(peer_id, chunk["message_id"]) == "connection_only"
            if case == "attachment_reader_replaced":
                replacement = reconnect_automation_fixture(service, peer, reader, remote, manifest)
                with pytest.raises(ValueError, match="connection policy"):
                    service._payload(peer, replacement, dict(receipt, message_id=chunk["message_id"]))
                service._payload(peer, replacement, early)
                assert replacement.sent[-1]["error"] == "not_granted"
                assert not service._send_message(replacement, peer_id, report)
                assert not service.store.outgoing_attachment_complete(peer_id, run, True, digest, attachment["sha256"])
                return
            service._payload(peer, reader, early)
            assert reader.sent[-1]["error"] == "not_granted"
            assert not service._send_message(reader, peer_id, report)
            service._payload(peer, reader, dict(receipt, message_id=chunk["message_id"]))
            service._payload(peer, reader, early)
            assert reader.sent[-1]["status"] == "accepted"
            assert service._send_message(reader, peer_id, report)
            assert scope.unwrap(reader.sent[-1]["body"], manifest)[1]["attachments"]["sent"] == 1
            return
        if case in {"reply", "reply_rejected", "reply_report_replaced", "reply_sql_retry"}:
            reply = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
                     "reply": True, "records": [record], "records_hash": personal.records_hash([record])}
            if case != "reply_sql_retry":
                task_value = {"title": "Scoped task", "note": "", "due": "", "priority": 2, "completed": False,
                              "remind": False, "lead_days": 0, "reminder_minute": 480, "created_ms": 1, "modified_ms": 2,
                              "uid": "phone-task", "parent_uid": "", "order": 0}
                task = dict(record, kind="task", id="phone-task", value=task_value, hash=personal.projection_hash(task_value))
                reply.update(last=False, records_hash=personal.records_hash([record, task]))
                batches = [reply, dict(reply, sequence=1, last=True, records=[task], batch_id=str(uuid.uuid4()))]
            else:
                batches = [reply]
            assert not service.commit_personal_sync(peer_id, message_id, token, True)
            if case == "reply_sql_retry":
                for kind in ("personal_sync.batch", "personal_sync.report"):
                    with sqlite3.connect(service.store.database_path) as db:
                        db.execute(f"""CREATE TRIGGER fail_connection_reply BEFORE INSERT ON outbox
                            WHEN NEW.kind='{kind}' BEGIN SELECT RAISE(ABORT,'test reply fault'); END""")
                    with pytest.raises(sqlite3.IntegrityError, match="test reply fault"):
                        service.finish_connection_batch_reply(peer_id, message_id, token, [reply])
                    assert service.store.has_personal_batch(peer_id, message_id, token)
                    with sqlite3.connect(service.store.database_path) as db:
                        assert not db.execute("SELECT 1 FROM outbox WHERE kind IN ('personal_sync.batch','personal_sync.report')").fetchone()
                        db.execute("DROP TRIGGER fail_connection_reply")
                outgoing, = service.finish_connection_batch_reply(peer_id, message_id, token, [reply])
            else:
                sent = threading.Event()
                send_frame = reader.send

                def observe(frame):
                    send_frame(frame)
                    sent.set()

                reader.send = observe
                native.Fenster.bei_nachricht(window, json.dumps({"cmd": "telefon_personal_connection_reply",
                    "kennung": peer_id, "messageId": message_id, "token": token, "batches": batches, "conflicts": 1}))
                assert sent.wait(4), responses
                with service.lock:  # The real background worker also records the send attempt.
                    outgoing = reader.sent[-len(batches)]["message_id"]
            assert not service.store.has_personal_batch(peer_id, message_id, token)
            wire = reader.sent[-len(batches)]
            assert wire["message_id"] == outgoing and scope.unwrap(wire["body"], manifest) == ("personal_sync.batch", reply)
            assert service.store.outbox_policy(peer_id, outgoing) == "connection_only"
            queued = service.store.outbox_message(peer_id, outgoing)
            assert not service._send_message(reader, peer_id, dict(queued, message_id=str(uuid.uuid4())))
            with sqlite3.connect(service.store.database_path) as db:
                report_id, = db.execute("SELECT message_id FROM outbox WHERE kind='personal_sync.report'").fetchone()
            report_frame = service.store.outbox_message(peer_id, report_id)
            authority = service._connection_automation_authority(peer, reader, request)
            assert not service._send_message(reader, peer_id, report_frame)
            assert service.store.personal_success(peer_id) is None
            receipt = {"type": "ack", "message_id": outgoing, "status": "accepted", "error": "none"}
            if case == "reply_sql_retry":
                replacement = reconnect_automation_fixture(service, peer, reader, remote, manifest)
                with pytest.raises(ValueError, match="connection policy"):
                    service._payload(peer, replacement, receipt)
                assert service.store.outbox_message(peer_id, outgoing)
                assert not service._send_message(replacement, peer_id, service.store.outbox_message(peer_id, outgoing))
                assert not service._send_message(replacement, peer_id, report_frame)
            else:
                with sqlite3.connect(service.store.database_path) as db:
                    db.execute("UPDATE outbox SET attempts=0, next_attempt_ms=0 WHERE message_id=?", (outgoing,))
                with pytest.raises(ValueError, match="connection policy"):
                    service._payload(peer, reader, receipt)
                assert not any(item["message_id"] == outgoing for item in service.store.pending(peer_id, "bluetooth"))
                retry, = [item for item in service.store.pending(peer_id, "bluetooth", connection_authority=authority)
                          if item["message_id"] == outgoing]
                assert service._send_message(reader, peer_id, retry)
                service._payload(peer, reader, receipt)
                assert service.store.outbox_message(peer_id, outgoing) is None
                second_id = next(item["message_id"] for item in reader.sent
                                 if item.get("kind") == scope.DATA_KIND and item["body"]["kind"] == "personal_sync.batch"
                                 and item["body"]["body"]["sequence"] == 1)
                second_ack = dict(receipt, message_id=second_id)
                service._payload(peer, reader, dict(second_ack, status="rejected", error="temporary_failure"))
                assert not service._send_message(reader, peer_id, report_frame)
                if case == "reply_rejected":
                    service._payload(peer, reader, dict(second_ack, status="rejected", error="not_granted"))
                    service._payload(peer, reader, second_ack)
                    assert not service._send_message(reader, peer_id, report_frame)
                    assert service.store.personal_success(peer_id) is None
                    return
                service._payload(peer, reader, second_ack)
                assert service._send_message(reader, peer_id, report_frame)
                kind, body = scope.unwrap(reader.sent[-1]["body"], manifest)
                assert kind == "personal_sync.report" and body["trigger"] == request["trigger"] and body["transport"] == "bluetooth"
                assert body["sent"] == {"notes": 1, "tasks": 1, "notebooks": 0} and body["conflicts"] == 1
                assert service.store.personal_success(peer_id) is None
                report_ack = dict(receipt, message_id=report_id)
                if case == "reply_report_replaced":
                    replacement = reconnect_automation_fixture(service, peer, reader, remote, manifest)
                    with pytest.raises(ValueError, match="connection policy"):
                        service._payload(peer, replacement, report_ack)
                    assert service.store.outbox_message(peer_id, report_id) == report_frame
                    assert service.store.personal_success(peer_id) is None
                    return
                service._payload(peer, reader, report_ack)
                assert service.store.personal_success(peer_id)["trigger"] == request["trigger"]
                assert not service.store.active_auto_run(peer_id, connection_authority=authority)
            return
        if case == "reader_replaced_after_save":
            reconnect_automation_fixture(service, peer, reader, remote, manifest)
        if case == "received_attachment":
            with sqlite3.connect(service.store.database_path) as db:
                db.execute("""CREATE TRIGGER fail_attachment_result BEFORE INSERT ON outbox
                    WHEN NEW.kind='personal_sync.attachment_result' BEGIN SELECT RAISE(ABORT,'test attachment receipt fault'); END""")
            with pytest.raises(sqlite3.IntegrityError, match="test attachment receipt fault"):
                service.commit_personal_sync(peer_id, message_id, token, True)
            assert service.store.has_personal_batch(peer_id, message_id, token)
            assert not any(item.get("kind") == scope.DATA_KIND and item["body"]["kind"] == "personal_sync.attachment_result" for item in reader.sent)
            with sqlite3.connect(service.store.database_path) as db:
                db.execute("DROP TRIGGER fail_attachment_result")
        assert service.commit_personal_sync(peer_id, message_id, token, True) is (case in {"current", "received_attachment", "initiator_report"})
        if case == "initiator_report":
            replacement = reconnect_automation_fixture(service, peer, reader, remote, manifest)
            service._payload(peer, replacement, report_frame)
            assert replacement.sent[-1]["status"] == "rejected"
            assert service.store.dedupe_result(peer_id, report_frame["message_id"]) is None
            service.connections[peer_id] = reader
            wrong_transport = dict(message(scope.wrap("personal_sync.report", dict(report, transport="wifi"), manifest)),
                                   kind=scope.DATA_KIND)
            service._payload(peer, reader, wrong_transport)
            assert reader.sent[-1]["error"] == "not_granted"
            assert service.store.dedupe_result(peer_id, wrong_transport["message_id"]) is None
            with sqlite3.connect(service.store.database_path) as db:
                db.execute("CREATE TRIGGER fail_connection_report_receipt BEFORE INSERT ON inbox "
                           "WHEN NEW.kind='personal_sync.report' BEGIN SELECT RAISE(ABORT,'test report receipt fault'); END")
            try:
                service._payload(peer, reader, report_frame)
                assert reader.sent[-1]["error"] == "temporary_failure"
                assert service.store.dedupe_result(peer_id, report_frame["message_id"]) is None
                assert service.store.personal_success(peer_id) is None
                assert "finished_ms" not in service.store._personal_run_record(peer_id, run)
            finally:
                with sqlite3.connect(service.store.database_path) as db:
                    db.execute("DROP TRIGGER fail_connection_report_receipt")
            service._payload(peer, reader, report_frame)
            assert reader.sent[-1]["status"] == "accepted"
            assert service.store.personal_success(peer_id)["trigger"] == request["trigger"]
            service._payload(peer, reader, report_frame)
            assert reader.sent[-1]["status"] == "duplicate"
            assert [item["body"] for item in delivered if item["kind"] == "personal_sync.report"] == [report]
            return
        if case == "received_attachment":
            stored_attachment = json.loads(native.daten_entschluesseln(path.read_text(), password))["notizen"][0]["anhaenge"][0]["daten"]
            assert base64.b64decode(stored_attachment.split(",", 1)[1]) == RAW
            wire = reader.sent[-1]
            kind, result = scope.unwrap(wire["body"], manifest)
            assert kind == "personal_sync.attachment_result" and result == {"format": 2, "run_id": run, "reply": True,
                "records_hash": personal.records_hash([record]), "sha256": attachment["sha256"], "state": "complete", "error": "none"}
            service._payload(peer, reader, {"type": "ack", "message_id": wire["message_id"], "status": "accepted", "error": "none"})
            assert service.store.outbox_message(peer_id, wire["message_id"]) is None
