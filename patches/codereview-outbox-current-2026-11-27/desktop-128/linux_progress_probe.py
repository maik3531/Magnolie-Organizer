#!/usr/bin/env python3
"""Identical progress assertion; baseline uses its original store/sender loop."""
import json
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

source = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(source / "magnolie-organizer/pruefungen"), str(source / "magnolie-organizer/bin")]
from test_mcp_phone import owned_service
from test_telefon import FakeBluetooth
import magnolie_telefon as phone
import magnolie_personal_actor as actor

with tempfile.TemporaryDirectory(prefix="magnolie-pending-fairness-") as temporary:
    service, peer, events = owned_service(Path(temporary))
    peer_id = peer["device_id"]
    run = str(uuid.uuid4())
    request = {"format": 3, "run_id": run, "trigger": "manual", "modules": ["notes", "tasks"]}
    service.store.remember_personal_run(actor.storage_peer(run), request)
    held = []
    for sequence in range(65):
        body = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": sequence,
                "last": sequence == 64, "reply": False, "records_hash": phone.records_hash([]), "records": []}
        held.append(service.store.queue(peer_id, "personal_sync.batch", body, 60000, actor_run_id=run))
    ordinary = service.store.queue(peer_id, "device_status.request", {"request_id": str(uuid.uuid4())}, 60000)
    # Real persisted store/service reconstruction; this does not authenticate a
    # physical phone or claim a GUI/process-lifecycle acceptance test.
    service = phone.PhoneService(str(Path(temporary) / "phone"), "Owned desktop", bluetooth_backend=FakeBluetooth())

    class Channel:
        def __init__(self): self.sent = []
        def send(self, message): self.sent.append(message)

    channel = Channel()
    pump = getattr(service, "_pump_pending", None)
    observations = []
    for cycle in range(3):
        before = len(channel.sent)
        if pump is None:
            for message in service.store.pending(peer_id, "wifi"):
                service._send_message(channel, peer_id, message)
        else:
            pump(channel, peer_id, "wifi")
        observations.append({"cycle": cycle, "sent": len(channel.sent) - before})
    progressed = ordinary in channel.sent
    with sqlite3.connect(service.store.database_path) as db:
        actor_attempts = db.execute("SELECT COALESCE(SUM(attempts),0) FROM outbox WHERE kind='personal_sync.batch'").fetchone()[0]
    retained = all(service.store.outbox_message(peer_id, wire["message_id"]) == wire for wire in held)
    result = {"source": str(source), "basis": "9de81cc10d72ca7b176b5c501ff20689cdd53c31",
              "entry": "original pending/_send_message loop" if pump is None else "actual _pump_pending live receiver helper",
              "observations": observations, "progress_within_three_pumps": progressed,
              "actors_retained": retained, "actor_attempts": actor_attempts, "server_started": service.server is not None}
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if progressed and retained and actor_attempts == 0 else 1)
