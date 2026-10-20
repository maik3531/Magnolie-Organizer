#!/usr/bin/env python3
"""Owned Python actor runtime over real encrypted TCP; no GUI/book adoption."""
import json
import hashlib
from pathlib import Path
import socket
import sys
import tempfile
import io
import time
import uuid
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
                    "dropped_request": None, "request_replayed": False}; received = Counter(); rejected = []; sent_kinds = {}; sent_semantic = {}
                send = channel.send
                def send_actor(value):
                    if value.get("kind") == actor.DATA_KIND: sent_semantic[value["message_id"]] = actor.unwrap(value["body"])[0]
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
                handle = None; registry = service.personal_actor_registry(); transfer_confirmed = False
                deadline = time.monotonic() + 50
                while time.monotonic() < deadline:
                    try:
                        packet = channel.receive()
                        received[packet.get("kind", packet.get("type", "unknown"))] += 1
                        if packet.get("status") == "rejected": rejected.append({"kind": sent_kinds.get(packet.get("message_id")), "error": packet.get("error")})
                        service._payload(peer, channel, packet)
                        if (handle is not None and packet.get("kind") == actor.ACK_KIND and
                                sent_semantic.get(packet["body"]["message_id"]) == "personal_sync.attachment_result" and
                                packet["body"]["status"] in {"accepted", "duplicate"}):
                            assert registry.read(handle, packet["message_id"]) == packet
                            transfer_confirmed = True
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
                            value = sink.getvalue()
                            assert len(value) == phone.CHUNK_RAW * 9 + 11
                            assert value[:11] == bytes([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3]) and value[11:] == bytes(len(value) - 11)
                            assert receipt["request_replayed"]
                            if not transfer_confirmed:
                                continue
                            review = service.read_personal_actor_staging(registry, handle)
                            review_bytes = phone.base64.b64decode(review["data_base64"])
                            assert review["batch_ready"] and review["next_offset"] is None
                            assert hashlib.sha256(review_bytes).hexdigest() == review["revision"]
                            assert json.loads(review_bytes)["batch"]["records"] == records
                            file_page = service.read_personal_actor_staging(registry, handle, expected_revision=review["revision"],
                                attachment_sha256=descriptor["sha256"])
                            assert phone.base64.b64decode(file_page["data_base64"]) == value[:65536]
                            assert file_page["total_bytes"] == len(value) and file_page["next_offset"] == 65536 and file_page["mime"] == "image/png"
                            assert not any(event == "personal_sync" and
                                (value.get("kind") == "personal_sync.batch" or
                                 value.get("body", {}).get("run_id") == handle.actor_id)
                                for event, value in events)
                            reply_record = json.loads(json.dumps(next(value for value in records if value["kind"] == "note")))
                            reply_record["value"]["text"] = "Private desktop draft"
                            reply_bytes = value[:-1] + bytes([42])
                            reply_digest = hashlib.sha256(reply_bytes).hexdigest()
                            reply_record["value"]["attachments"][0]["sha256"] = reply_digest
                            reply_record["hash"] = phone.personal_sync_contract.projection_hash(reply_record["value"])
                            reply_body = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()),
                                "sequence": 0, "last": True, "reply": True, "records": [reply_record],
                                "records_hash": phone.personal_sync_contract.records_hash([reply_record])}
                            with service.lock: registry.require_current(handle)
                            reply_wire = service._actor_control_message("personal_sync.batch", reply_body)
                            reply_wire["expires_ms"] = reply_wire["created_ms"] + 86400000
                            service.store.stage_personal_batch(private, reply_wire)
                            service.store.stage_outgoing_attachment(private, handle.actor_id, True, reply_body["records_hash"],
                                reply_digest, "image/png", reply_bytes, "any", reply_wire["expires_ms"])
                            channel.send(actor.wire_message(reply_wire, handle.actor_id))
                            reply_deadline = time.monotonic() + 5
                            while time.monotonic() < reply_deadline:
                                try: reply = channel.receive()
                                except socket.timeout: continue
                                if (reply.get("kind") == actor.ACK_KIND and reply["body"]["run_id"] == handle.actor_id and
                                        reply["body"]["message_id"] == reply_wire["message_id"]):
                                    actor.validate_ack(reply["body"])
                                    assert reply["body"]["status"] in {"accepted", "duplicate"}
                                    break
                                service._payload(peer, channel, reply)
                            else: raise AssertionError("Private Notes reply staging receipt missing")
                            reply_deadline = time.monotonic() + 10
                            while time.monotonic() < reply_deadline:
                                for queued in service.store.pending(phone_id): service._send_message(channel, phone_id, queued)
                                try: reply = channel.receive()
                                except socket.timeout: continue
                                service._payload(peer, channel, reply)
                                if reply.get("kind") == actor.DATA_KIND:
                                    semantic, content = actor.unwrap(reply["body"])
                                    if semantic == "personal_sync.attachment_result" and content["reply"] and content["sha256"] == reply_digest:
                                        assert content["state"] == "complete" and registry.read(handle, reply["message_id"]) == reply
                                        assert not service.store.has_outgoing_attachments(private, handle.actor_id)
                                        break
                            else: raise AssertionError("Native desktop reply attachment result missing")
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
