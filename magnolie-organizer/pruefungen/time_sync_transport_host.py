#!/usr/bin/env python3
"""Synthetic established session exercising the real v7 service and encrypted store."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
import magnolie_time_sync as sync

PHONE = "22222222-2222-4222-8222-222222222222"
DESKTOP_RECORD = "77777777-7777-4777-8777-777777777777"
ACTOR = "88888888-8888-4888-8888-888888888888"


def main():
    with tempfile.TemporaryDirectory(prefix="time-sync-host-") as directory:
        service = phone.PhoneService(str(Path(directory) / "phone"), "Synthetic desktop")
        peer = dict(device_id=PHONE, display_name="Synthetic phone", static_public=phone.b64(b"p" * 32),
            state="paired", grants=phone.desktop_grants(), local_grants=phone.desktop_grants(),
            capabilities=phone.desktop_capabilities(), last_contact_ms=0, bluetooth=dict(enabled=False, address=""),
            personal_sync=dict(own_device=True, remote_own_device=False, auto_wifi=False, last_report={}))
        service.store.peers.append(peer); service.store.save_peers()
        service.set_time_sync(PHONE, True)
        imported = []

        def receive(event, payload):
            if event != "personal_time_batch":
                return
            body = payload["body"]
            assert any(entry["note"] == "Phone time fixture" for entry in body["entries"])
            assert "calendar" not in body and all(not entry["deleted"] for entry in body["entries"])
            target = Path(directory) / "document.json"
            with target.open("w", encoding="utf-8") as output:
                json.dump(body, output); output.flush(); os.fsync(output.fileno())
            assert json.loads(target.read_text()) == body
            assert service.commit_personal_sync(PHONE, payload["pending_message_id"], payload["commit_token"], True)
            imported.append(payload["pending_message_id"])

        service.callback = receive
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(25)
            print(listener.getsockname()[1], flush=True)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                channel = phone.SecureChannel(connection, bytes([7]) * 32,
                    bytes([13]) * 32, bytes([14]) * 4, bytes([11]) * 32, bytes([12]) * 4)
                service.connections[PHONE] = channel; service.connection_transports[PHONE] = "wifi"
                original_send = channel.send
                dropped = None; replayed = False; current = {}

                def send(value):
                    nonlocal dropped, replayed
                    if value.get("type") == "ack" and current.get("kind") == sync.BATCH:
                        assert value["status"] in ("accepted", "duplicate"), value
                        if dropped is None:
                            dropped = value["message_id"]; return
                        if value["message_id"] == dropped:
                            replayed = True
                    original_send(value)

                channel.send = send
                service._ensure_desktop_updates(PHONE)
                started = False; revoked = False; outbound = []; last_ping = 0
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    for queued in service.store.pending(PHONE): service._send_message(channel, PHONE, queued)
                    try:
                        current = channel.receive()
                        service._payload(peer, channel, current)
                    except socket.timeout:
                        pass
                    if service.time_status(PHONE).get("ready") and not started:
                        started = True
                        entry = dict(id=DESKTOP_RECORD, startMinute=1000, endMinute=1120, pauseMinute=None,
                            pauseMinutes=15, zone="UTC", type="Desktop time fixture", note="Desktop time fixture",
                            modifiedMs=1000, deleted=False, clock={ACTOR: 1}, pausePlan=None)
                        calendar = dict(enabled=True, country="DE", regions=["DE-BE"], holidays=[
                            dict(date="2026-10-03", name="Synthetic national holiday", country="DE", nationwide=True, regions=[])])
                        outbound = service.send_time_records(PHONE, [entry], calendar)
                        policies = service.store.time_settings(PHONE)
                        service.send_personal_sync(PHONE, sync.REQUEST, sync.request_body(policies["local"], policies["remote"]))
                    if not revoked and time.monotonic() - last_ping >= 0.5:
                        channel.send(dict(type="ping", ping_id=str(uuid.uuid4()), sent_ms=phone.now_ms()))
                        last_ping = time.monotonic()
                    if not revoked and started and imported and replayed and all(service.store.outbox_policy(PHONE, value) is None for value in outbound):
                        assert len(imported) == 1, "Lost ACK applied the phone batch again"
                        service.set_time_sync(PHONE, False)
                        revoked = True
                        for queued in service.store.pending(PHONE): service._send_message(channel, PHONE, queued)
                        continue
                    if revoked and not service.store.has_kind(PHONE, sync.SETTINGS):
                        channel.send(dict(type="close", reason="normal"))
                        print("Time synchronization: bidirectional durable data, calendar, lost ACK replay and revocation passed.", flush=True)
                        return
                raise TimeoutError("Time synchronization fixture did not finish")


if __name__ == "__main__":
    main()
