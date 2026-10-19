#!/usr/bin/env python3
"""Owned Python actor runtime over real encrypted TCP; no GUI/book adoption."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import io
import time
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
import magnolie_personal_actor as actor
import magnolie_shared_sync as shared
from magnolie_personal_actor_store import NativeBookOwnerScope


class NoBluetooth:
    def availability(self): return False, "not_implemented"
    def paired_devices(self): return []


def main():
    phone_id, phone_key = sys.argv[1:3]
    original = phone.desktop_capabilities
    def capabilities(*args, **kwargs):
        result = original(*args, **kwargs)
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            result["items"][name]["versions"] = sorted(set(result["items"][name]["versions"] + [12]))
        return result
    phone.desktop_capabilities = capabilities  # Owned fixture only; production never advertises 12 yet.
    with tempfile.TemporaryDirectory(prefix="actor-wire-host-") as directory:
        events = []
        service = phone.PhoneService(str(Path(directory) / "phone"), "Owned actor desktop", callback=lambda *event: events.append(event), bluetooth_backend=NoBluetooth())
        service.enabled = True
        local, remote = phone.desktop_grants(), phone.desktop_grants()
        for name in ("personal_notes_sync", "personal_tasks_sync"): local["grants"][name] = True
        peer = {"device_id": phone_id, "display_name": "Owned synthetic phone", "static_public": phone_key,
            "state": "paired", "grants": remote, "local_grants": local, "capabilities": capabilities(), "last_contact_ms": 0,
            "bluetooth": {"enabled": False, "address": ""}, "personal_sync": {
                "own_device": True, "remote_own_device": False, "auto_wifi": False, "last_report": {}}}
        service.store.peers = [peer]; service.store.save_peers()
        service.store.initialize_shared_settings(phone_id, phone_key, dict(shared.DEFAULTS, auto_mode="manual"))
        book = NativeBookOwnerScope(); book.set_ready(True)
        service.native_actor_book_source = lambda: book.current("owned-native-actor-book", True)
        service.personal_sync_available = lambda: True
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(25)
            print(json.dumps({"port": listener.getsockname()[1], "device_id": service.store.identity["device_id"],
                "static_public": service.store.identity["static_public"]}), flush=True)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                channel = phone.SecureChannel(connection, bytes([7]) * 32,
                    bytes([13]) * 32, bytes([14]) * 4, bytes([11]) * 32, bytes([12]) * 4)
                service.connections[phone_id] = channel; service.connection_transports[phone_id] = "wifi"
                packet = {}; receipt = {"dropped": None, "replayed": False, "cancel_id": None,
                    "dropped_request": None, "request_replayed": False}; received = Counter(); rejected = []; sent_kinds = {}
                send = channel.send
                def send_actor(value):
                    if value.get("kind") == actor.CANCEL_KIND: receipt["cancel_id"] = value["message_id"]
                    if value.get("kind") == actor.DATA_KIND and actor.unwrap(value["body"])[0] == "personal_sync.attachment_request":
                        if receipt["dropped_request"] is None:
                            receipt["dropped_request"] = value["message_id"]
                            return  # Drop before cipher framing; native due/attempt scheduling must retry.
                        if receipt["dropped_request"] == value["message_id"]: receipt["request_replayed"] = True
                    if "message_id" in value: sent_kinds[value["message_id"]] = value.get("kind", value.get("type"))
                    if (value.get("kind") == actor.ACK_KIND and packet.get("kind") == actor.DATA_KIND and
                            actor.unwrap(packet["body"])[0] == "personal_sync.batch" and
                            value["body"]["message_id"] == packet["message_id"]):
                        if receipt["dropped"] is None:
                            receipt["dropped"] = packet["message_id"]
                            return
                        if receipt["dropped"] == packet["message_id"]: receipt["replayed"] = True
                    send(value)
                channel.send = send_actor
                service._ensure_desktop_updates(phone_id)
                handle = None; registry = service.personal_actor_registry()
                deadline = time.monotonic() + 50
                while time.monotonic() < deadline:
                    try:
                        packet = channel.receive()
                        received[packet.get("kind", packet.get("type", "unknown"))] += 1
                        if packet.get("status") == "rejected": rejected.append({"kind": sent_kinds.get(packet.get("message_id")), "error": packet.get("error")})
                        service._payload(peer, channel, packet)
                    except socket.timeout:
                        pass
                    for queued in service.store.pending(phone_id): service._send_message(channel, phone_id, queued)
                    fingerprint = phone.fingerprint(phone.unb64(phone_key, 32))
                    source = service.current_actor_source(phone_id, fingerprint)
                    if handle is None and source is not None:
                        handle = registry.create(phone_id, fingerprint, source)
                        service.start_personal_actor(registry, handle)
                    if handle is not None:
                        private = actor.storage_peer(handle.actor_id)
                        batches = [value for owner, value in service.store.ready_personal_batches() if owner == private]
                        if batches and receipt["replayed"]:
                            records = batches[0]["records"]
                            assert [value["id"] for value in records if value["kind"] == "note"] == ["phone-note"]
                            assert [value["id"] for value in records if value["kind"] == "task"] == ["phone-task"]
                            descriptor = next(value for record in records if record["kind"] == "note" for value in record["value"]["attachments"])
                            aggregate_hash = batches[0]["messages"][-1]["body"]["records_hash"]
                            sink = io.BytesIO()
                            if not service.store.verify_incoming_attachment(private, handle.actor_id, False, aggregate_hash, descriptor["sha256"], sink):
                                continue
                            assert sink.getvalue() == bytes([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3])
                            assert receipt["request_replayed"]
                            assert not any(event == "personal_sync" and
                                (value.get("kind") == "personal_sync.batch" or
                                 value.get("body", {}).get("run_id") == handle.actor_id)
                                for event, value in events)
                            service.cancel_personal_actor(registry, handle)
                            cancel_deadline = time.monotonic() + 5
                            while time.monotonic() < cancel_deadline:
                                try: reply = channel.receive()
                                except socket.timeout: continue
                                if (reply.get("kind") == actor.ACK_KIND and
                                        reply.get("body", {}).get("message_id") == receipt["cancel_id"]):
                                    break
                                service._payload(peer, channel, reply)
                            else: raise AssertionError("Native actor cancel receipt missing")
                            send({"type": "close", "reason": "normal"})
                            print(json.dumps({"actor_id": handle.actor_id, "private_core_records": len(records),
                                "lost_marked_ack_replayed": True, "attachment_request_retried": True, "attachment_integrity_verified": True,
                                "gui_adoption": False, "book_persisted": False}), flush=True)
                            return
                scope_session = service.content_scope_sessions.get(channel)
                diagnostic = {"received": dict(received), "rejected": rejected[-3:], "actor": handle.actor_id if handle else None,
                    "own": peer.get("personal_sync"), "local_grants": peer.get("local_grants"), "remote_grants": peer.get("grants"),
                    "versions": {name: peer.get("capabilities", {}).get("items", {}).get(name, {}).get("versions")
                        for name in ("personal_notes_sync", "personal_tasks_sync")},
                    "fresh": list(service.note_controls.get(channel, {})), "shared": service.shared_settings_ready(phone_id),
                    "scope_complete": bool(scope_session and scope_session._manifest is not None), "receipt": receipt,
                    "shared_local": service.store.shared_settings(phone_id, phone_key),
                    "shared_session": service.shared_sessions.get(channel)}
                print("Owned actor handshake diagnostic:\n" + json.dumps(diagnostic, indent=2), file=sys.stderr, flush=True)
                raise TimeoutError("Native actor exchange incomplete")


if __name__ == "__main__":
    main()
