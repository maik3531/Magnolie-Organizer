#!/usr/bin/env python3
"""Issue #76: real encrypted runtime with a synthetic established pairing."""
import base64
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
import magnolie_personal_sync as sync

PHONE = "22222222-2222-4222-8222-222222222222"


def main():
    with tempfile.TemporaryDirectory(prefix="note-mode-host-") as directory:
        imported = []
        service = phone.PhoneService(str(Path(directory) / "phone"), "Synthetic desktop")
        local, remote = phone.desktop_grants(), phone.desktop_grants()
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            local["grants"][name] = True
        peer = {"device_id": PHONE, "display_name": "Synthetic phone", "static_public": phone.b64(b"p" * 32),
                "state": "paired", "grants": remote, "local_grants": local,
                "capabilities": phone.desktop_capabilities(), "last_contact_ms": 0,
                "bluetooth": {"enabled": False, "address": ""},
                "personal_sync": {"own_device": True, "remote_own_device": False, "auto_wifi": False, "last_report": {}}}
        service.store.peers.append(peer)
        service.store.save_peers()
        service.store.set_note_settings(PHONE, sync.note_settings("phone_import"))
        service.set_desktop_features(True, True)

        def receive(event, payload):
            if event == "personal_sync_attachment_index":
                service.index_local_attachments(PHONE, payload["run_id"], payload["reply"], payload["records_hash"], [])
            if event == "personal_sync" and payload.get("kind") == "personal_sync.batch":
                body = payload["body"]
                notes = [record for record in body["records"] if record["kind"] == "note"]
                assert len(notes) == 1 and notes[0]["value"]["title"] == "Offline note"
                assert notes[0]["value"]["html"] == "<b>Phone formatting</b>"
                attachments = notes[0]["value"]["attachments"]
                assert len(attachments) == 1
                raw = base64.b64decode(body["attachment_data"][attachments[0]["sha256"]].split(",", 1)[1])
                assert raw == b"%PDF-1.4\n" and hashlib.sha256(raw).hexdigest() == attachments[0]["sha256"]
                # Stand-in for the tested desktop document save: acknowledge only
                # after the exact import payload has survived a durable reopen.
                target = Path(directory) / "import.json"
                with target.open("w", encoding="utf-8") as output:
                    output.write(json.dumps(body)); output.flush()
                    import os
                    os.fsync(output.fileno())
                assert json.loads(target.read_text()) == body
                assert service.commit_personal_sync(PHONE, payload["pending_message_id"], payload["commit_token"], True)
                imported.append(notes[0]["id"])

        service.callback = receive
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(25)
            print(listener.getsockname()[1], flush=True)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                channel = phone.SecureChannel(connection, bytes([7]) * 32,
                    bytes([13]) * 32, bytes([14]) * 4, bytes([11]) * 32, bytes([12]) * 4)
                packet = {}
                receipt = {"dropped": None, "replayed": False}
                send = channel.send
                def trace_ack(message):
                    if message.get("type") == "ack" and message.get("status") == "rejected":
                        print("Rejected fixture packet:", packet.get("kind"), packet.get("body", {}).get("revision"), message, file=sys.stderr, flush=True)
                    if (message.get("type") == "ack" and message.get("status") in ("accepted", "duplicate")
                            and packet.get("kind") == "personal_sync.batch"):
                        if receipt["dropped"] is None:
                            receipt["dropped"] = message["message_id"]
                            return  # Lose one application ACK before secure framing.
                        if message["message_id"] == receipt["dropped"]:
                            receipt["replayed"] = True
                    send(message)
                channel.send = trace_ack
                service.connections[PHONE] = channel
                service.connection_transports[PHONE] = "wifi"
                service._ensure_desktop_updates(PHONE)
                service._queue_note_settings(PHONE, channel, force=True)
                for message in service.store.pending(PHONE):
                    service._send_message(channel, PHONE, message)
                requested = False
                features_paused = False
                last_ping = time.monotonic()
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        packet = channel.receive()
                        service._payload(peer, channel, packet)
                    except socket.timeout:
                        pass
                    if service._note_ready(PHONE) and not requested:
                        requested = True
                        run = str(uuid.uuid4())
                        request = {"format": 2, "run_id": run, "trigger": "manual", "modules": ["notes"]}
                        service.store.remember_personal_run(PHONE, request)
                        value = {"title": "Desktop private", "text": "Never send", "html": "", "notebook_id": "private",
                                 "symbol": "note", "created_ms": 1, "modified_ms": 1, "attachments": []}
                        record = {"kind": "note", "id": "desktop-private", "state": "live", "clock": [{"actor_id": str(uuid.uuid4()), "counter": 1}],
                                  "hash": sync.projection_hash(value), "modified_ms": 1, "value": value}
                        forbidden = {"format": 2, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0,
                                     "last": True, "reply": False, "records": [record], "records_hash": sync.records_hash([record])}
                        queued = service.store.queue(PHONE, "personal_sync.batch", forbidden, phone.DAY_MS)
                        sequence = channel.send_seq
                        assert not service._send_message(channel, PHONE, queued)
                        assert channel.send_seq == sequence, "forbidden note reached the encrypted stream"
                        empty = dict(forbidden, batch_id=str(uuid.uuid4()), records=[], records_hash=sync.records_hash([]))
                        service.send_personal_sync_run(PHONE, request, [empty], [])
                    for message in service.store.pending(PHONE):
                        service._send_message(channel, PHONE, message)
                    if receipt["dropped"] and not receipt["replayed"] and time.monotonic() - last_ping >= 0.5:
                        channel.send({"type": "ping", "ping_id": str(uuid.uuid4()), "sent_ms": phone.now_ms()})
                        last_ping = time.monotonic()
                    if imported and receipt["replayed"] and peer["personal_sync"]["last_report"].get("state") == "complete":
                        if not features_paused:
                            features_paused = True
                            service.set_desktop_features(False, False)
                            continue
                        if service.store.has_kind(PHONE, sync.DESKTOP_FEATURES_KIND):
                            continue
                        assert imported == ["phone-note"], imported
                        assert not service.store.ready_personal_batches()
                        channel.send({"type": "close", "reason": "normal"})
                        print("Python import, lost ACK replay, attachment, durable commit, reverse-note suppression and desktop availability passed.", flush=True)
                        return
                raise TimeoutError("V5 note transport did not finish")


if __name__ == "__main__":
    main()
