"""Couple the Notes and Organizer connection handlers over an encrypted loopback stream."""
import base64
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

import magnolie_content_scope as scope
import magnolie_personal_sync as personal
import magnolie_telefon as phone
from magnolie_personal_actor_store import NativeBookOwnerScope
from test_personal_actor_historical_file_writer import native_store
from test_personal_attachment_manifest import RAW, _descriptor


def main():
    phone_id = os.environ["PHONE_TEST_DEVICE_ID"]
    original, = json.loads(os.environ["PHONE_TEST_ORIGINAL_RECORDS"])
    notes_original = os.environ.get("PHONE_TEST_INITIATOR_ORIGINAL_SHA256")
    desktop_id = os.environ.get("ORGANIZER_TEST_DEVICE_ID", "11111111-1111-4111-8111-111111111111")
    run_id = None
    with tempfile.TemporaryDirectory(prefix="magnolie-connection-host-") as directory, pytest.MonkeyPatch.context() as patch:
        root = Path(directory)
        native = native_store(root, patch)
        service = phone.PhoneService(str(root / "phone"), "Synthetic desktop")
        service.store.identity["device_id"] = desktop_id
        original_capabilities = phone.desktop_capabilities

        def marked_capabilities(*args, **kwargs):
            result = original_capabilities(*args, **kwargs)
            for module in ("personal_notes_sync", "personal_tasks_sync"):
                versions = result["items"][module]["versions"]
                # The synthetic Organizer offers format 3, while Notes can
                # also advertise 14. Both must use their exact common format.
                result["items"][module]["versions"] = sorted(set(versions + [personal.AUTO_CONNECTION_VERSION]) - {14})
            return result

        patch.setattr(phone, "desktop_capabilities", marked_capabilities)
        local, remote = phone.desktop_grants(), phone.desktop_grants()
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            local["grants"][name] = remote["grants"][name] = True
        peer = {"device_id": phone_id, "display_name": "Synthetic Notes", "static_public": phone.b64(b"p" * 32),
                "state": "paired", "grants": remote, "local_grants": local, "capabilities": marked_capabilities(),
                "last_contact_ms": 0, "bluetooth": {"enabled": False, "address": ""},
                "personal_sync": {"own_device": True, "remote_own_device": True, "auto_wifi": False, "last_report": {}}}
        service.store.peers.append(peer)
        service.store.save_peers()
        service.store.initialize_shared_settings(phone_id, peer["static_public"],
            dict(phone.shared_sync_contract.DEFAULTS, content_mode="phone_scope"))
        service.store.change_shared_setting(phone_id, peer["static_public"], "auto_mode", "connection")

        raw = RAW + b"x" * (8 * personal.CHUNK_RAW)
        descriptor = _descriptor(raw, "organizer-original.png")
        digest = descriptor["sha256"]
        book = root / "organizer-book.json"
        password = "synthetic-connection-interop"
        source = "synthetic-connection-book-owner"
        owner = NativeBookOwnerScope()
        owner.set_ready(True)
        initial = {"notizen": [], "personalSync": {"applied_batches": []}}
        initial_text = json.dumps(initial)
        encrypted, dek, dek_id, wrapper = native.daten_huelle_anlegen(initial_text, password)
        native.atomar_text_schreiben(str(book), encrypted)
        saved_source = owner.record_saved(source, True, hashlib.sha256(initial_text.encode()).hexdigest())["book_source"]
        service.native_actor_book_source = lambda: owner.current(source, True)
        service.native_actor_saved_book = lambda: owner.save_state(source, True)
        saved = False
        successful_report = None

        def receive(event, payload):
            nonlocal saved, successful_report
            if event != "personal_sync":
                return
            body = payload["body"]
            if payload["kind"] == "personal_sync.report":
                successful_report = body
                return
            if payload["kind"] != "personal_sync.batch":
                return
            assert not saved and body["reply"] == (notes_original is None) and body["run_id"] == run_id
            notes = [row for row in body["records"] if row["kind"] == "note"]
            note, = [row for row in notes if row["id"] == "phone-note"]
            incoming_digest = notes_original or digest
            incoming_data = body["attachment_data"][incoming_digest]
            incoming_raw = base64.b64decode(incoming_data.split(",", 1)[1])
            assert hashlib.sha256(incoming_raw).hexdigest() == incoming_digest
            if notes_original is None:
                assert incoming_raw == raw and note["value"]["text"] == "Organizer original update"
            message_id, token = payload["pending_message_id"], payload["commit_token"]
            assert not service.commit_personal_sync(phone_id, message_id, token, True)
            candidate = {"notizen": notes, "original": incoming_data,
                         "personalSync": {"applied_batches": [token]}}
            text = json.dumps(candidate)
            before = hashlib.sha256(initial_text.encode()).hexdigest()
            job = service.prepare_connection_batch_save(
                {"peer": phone_id, "messageId": message_id, "token": token, "before": before}, text, saved_source)

            def write(value):
                envelope = native.daten_verschluesseln(value, password, dek, dek_id, wrapper)
                native.atomar_text_schreiben(str(book), envelope)
                owner.record_saved(source, True, hashlib.sha256(value.encode()).hexdigest())

            service.write_connection_batch_save(job, saved_source, before, initial, candidate, text, write)
            assert json.loads(native.daten_entschluesseln(book.read_text(), password)) == candidate
            saved = True
            if notes_original is None:
                assert service.commit_personal_sync(phone_id, message_id, token, True)
            else:
                target, = [row for row in notes if row["id"] == "return-note"]
                reply = update_note(target, desktop_id, descriptor)
                data = "data:image/png;base64," + base64.b64encode(raw).decode()
                service.finish_connection_batch_reply(phone_id, message_id, token,
                    [batch_frame(run_id, reply, is_reply=True)], sources=[{"sha256": digest, "data": data}])

        service.callback = receive
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(25)
            print(listener.getsockname()[1], flush=True)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(15)
                reader = phone.SecureChannel(connection, b"\x07" * 16, b"\x0d" * 32,
                    b"\x0e" * 4, b"\x0b" * 32, b"\x0c" * 4)
                wire_kinds = {}
                def trace(direction, packet):
                    kind = packet.get("kind", "")
                    if kind == scope.DATA_KIND:
                        kind = packet["body"]["kind"]
                    if packet["type"] == "message":
                        wire_kinds[packet["message_id"]] = kind
                    elif packet["type"] == "ack":
                        kind = f'{wire_kinds.get(packet["message_id"])} {packet["status"]} {packet["error"]}'
                    print(direction, packet["type"], kind, file=sys.stderr, flush=True)

                send = reader.send
                def traced_send(packet):
                    trace("Organizer → Notes", packet)
                    send(packet)
                reader.send = traced_send
                service.connections[phone_id] = reader
                service.connection_transports[phone_id] = "wifi"
                service._ensure_desktop_updates(phone_id)
                deadline = time.monotonic() + 65
                while time.monotonic() < deadline:
                    authority = None
                    if run_id is not None:
                        run = service.store._personal_run_record(phone_id, run_id)
                        authority = service._connection_run_authority(service.store.sole_peer(phone_id), reader, run)
                    for frame in service.store.pending(phone_id, connection_authority=authority):
                        service._send_message(reader, phone_id, frame)
                    packet = reader.receive()
                    trace("Notes → Organizer", packet)
                    if notes_original and packet.get("kind") == scope.DATA_KIND and packet["body"]["kind"] == "personal_sync.request":
                        request = packet["body"]["body"]
                        assert request["trigger"] == personal.AUTO_CONNECTION_TRIGGER and request["format"] == 3
                        assert run_id in (None, request["run_id"])
                        run_id = request["run_id"]
                    service._payload(peer, reader, packet)
                    if run_id is None and service.gui_connection_start_ready(phone_id):
                        assert notes_original is None, "Both endpoints were ready but Linux was not elected"
                        plan = service.prepare_gui_connection_start(phone_id, phone.fingerprint(phone.unb64(peer["static_public"], 32)))
                        assert plan["scope"]["members"]["notes"] == ["phone-note"] and plan["format"] == 3
                        run_id = plan["run_id"]
                        request = {"format": plan["format"], "run_id": run_id, "trigger": personal.AUTO_CONNECTION_TRIGGER,
                                   "modules": ["notes", "tasks"]}
                        assert original["kind"] == "note" and original["id"] == "phone-note"
                        batch = batch_frame(run_id, update_note(original, desktop_id, descriptor), is_reply=False)
                        data = "data:image/png;base64," + base64.b64encode(raw).decode()
                        service.start_gui_connection_run(phone_id, plan["token"], service.native_actor_saved_book()["sha256"],
                            request, [batch], [{"sha256": digest, "data": data}])
                    if notes_original and run_id and service.store._personal_run_record(phone_id, run_id).get("finished_ms"):
                        assert saved
                        reader.send({"type": "close", "reason": "normal"})
                        print("Original bytes, protected book save and final report confirmed on Linux.", flush=True)
                        print(digest, flush=True)
                        return
                    if successful_report is not None:
                        assert saved and successful_report["transport"] == "wifi"
                        assert successful_report["attachments"]["sent"] == successful_report["attachments"]["received"] == 1
                        assert successful_report["attachments"]["bytes"] == len(raw)
                        assert service.store.personal_success(phone_id)["trigger"] == personal.AUTO_CONNECTION_TRIGGER
                        reader.send({"type": "close", "reason": "normal"})
                        print("Original bytes, protected book save and final report confirmed on Linux.", flush=True)
                        return
                raise TimeoutError("Organizer did not receive the bound Notes report.")


def update_note(record, desktop_id, descriptor):
    value = dict(record["value"], text="Organizer original update", html="",
                 modified_ms=record["modified_ms"] + 1, attachments=[descriptor])
    clocks = {entry["actor_id"]: entry["counter"] for entry in record["clock"]}
    clocks[desktop_id] = clocks.get(desktop_id, 0) + 1
    return dict(record, value=value, hash=personal.projection_hash(value), modified_ms=value["modified_ms"],
                clock=[{"actor_id": actor, "counter": clocks[actor]} for actor in sorted(clocks)])


def batch_frame(run_id, record, *, is_reply):
    return {"format": 3, "run_id": run_id, "batch_id": str(uuid.uuid4()), "sequence": 0,
            "last": True, "reply": is_reply, "records": [record], "records_hash": personal.records_hash([record])}


if __name__ == "__main__":
    main()
