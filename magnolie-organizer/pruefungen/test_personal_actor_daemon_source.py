"""Actual private IPC, exact GUI-owner lease and native book provider; no listener."""
import time
import tempfile
from pathlib import Path
import pytest
import threading
import uuid
import base64
import json
import hashlib
from test_personal_actor_transport import record, gtk_actor_bridge
from test_personal_actor_source import actor_source_fixture
import magnolie_personal_actor as actor_contract
from magnolie_personal_actor_store import ActorHandle
import magnolie_telefon as phone

import magnolie_hintergrund as background
from magnolie_personal_actor_store import NativeBookOwnerScope
from test_hintergrunddienst import FakeBackend


def test_proxy_source_requires_its_exact_live_native_book_owner(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, _ = actor_source_fixture(tmp_path, monkeypatch)
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    with tempfile.TemporaryDirectory(prefix="actor-book-ipc-") as root:
        path = str(Path(root) / "bridge.sock")
        server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
        service.personal_sync_available = server.gui_personal_ready
        proxy = background.PhoneServiceProxy(path)
        other = background.PhoneServiceProxy(path)
        profile = ["native-profile-a"]
        provider = lambda: owner.current(profile[0], True)
        proxy.native_actor_book_source = provider
        try:
            assert proxy.current_actor_source(peer["device_id"], fingerprint) is None
            assert service.server is None, "A source getter started a handset listener"
            proxy.start(); proxy.set_visible(True); proxy.set_ready(True)
            first = proxy.current_actor_source(peer["device_id"], fingerprint)
            assert first and len(first) == 64
            assert proxy.current_actor_source(peer["device_id"], fingerprint) == first
            bridge = gtk_actor_bridge()
            target = {"peerId": peer["device_id"], "fingerprint": fingerprint}
            selected = bridge(None, proxy, dict(target, action="notes_actor_source"))
            assert selected["ok"] and selected["sourceRevision"] == first
            with pytest.raises(background.IPCError): proxy.create_personal_actor(peer["device_id"], fingerprint, expected_source="f" * 64)
            created = bridge(None, proxy, dict(target, action="notes_actor_create", sourceRevision=selected["sourceRevision"]))
            assert created["ok"]
            handle = background.NativePhoneActorHandle(created["actorId"], created["ownerToken"], created["bookSource"])
            original_send = channel.send
            def guarded_send(value):
                assert not service.lock._is_owned(), "Daemon actor I/O held the native service guard"
                original_send(value)
            channel.send = guarded_send
            dispatched = proxy.start_personal_actor(handle)
            assert dispatched["dispatch_started"] and not dispatched["persisted"]
            assert channel.sent[-1]["kind"] == actor_contract.START_KIND
            assert handle.owner_token not in repr(handle) and handle.book_source not in repr(handle)
            assert not proxy.read_personal_actor_staging(handle)["batch_ready"]
            actor_request = {"format": 3, "run_id": handle.actor_id, "trigger": "manual", "modules": ["notes", "tasks"]}
            image = b"\x89PNG\r\n\x1a\nPrivate IPC attachment"
            image_hash = hashlib.sha256(image).hexdigest()
            note = record(); note["value"]["attachments"] = [{"attachment_id": "private-image", "name": "private.png", "kind": "image",
                "mime": "image/png", "size": len(image), "sha256": image_hash}]
            note["hash"] = phone.personal_sync_contract.projection_hash(note["value"])
            actor_batch = {"format": 3, "run_id": handle.actor_id, "batch_id": str(uuid.uuid4()), "sequence": 0,
                "last": True, "reply": False, "records": [note], "records_hash": phone.personal_sync_contract.records_hash([note])}
            for kind, body in [("personal_sync.request", actor_request), ("personal_sync.batch", actor_batch)]:
                service._payload(peer, channel, actor_contract.wire_message(phone.PhoneService._actor_control_message(kind, body), handle.actor_id))
            staging = proxy.read_personal_actor_staging(handle)
            staged_value = json.loads(base64.b64decode(staging["data_base64"]))
            assert staging["batch_ready"] and staged_value["request"] == actor_request and staged_value["batch"]["records"] == [note]
            with pytest.raises(background.IPCError): proxy.read_personal_actor_staging(handle, expected_revision=staging["revision"], attachment_sha256=image_hash)
            chunk = {"format": 2, "run_id": handle.actor_id, "reply": False, "records_hash": actor_batch["records_hash"],
                "sha256": image_hash, "index": 0, "data": base64.b64encode(image).decode("ascii")}
            service._payload(peer, channel, actor_contract.wire_message(phone.PhoneService._actor_control_message("personal_sync.attachment_chunk", chunk), handle.actor_id))
            file_page = proxy.read_personal_actor_staging(handle, expected_revision=staging["revision"], attachment_sha256=image_hash)
            assert base64.b64decode(file_page["data_base64"]) == image and file_page["mime"] == "image/png"
            from types import SimpleNamespace
            owner.record_saved(profile[0], True, "a" * 64)
            native_window = SimpleNamespace(_telefon_actor_buchnachweis=lambda: owner.save_state(profile[0], True),
                _telefon_actor_buchquelle=provider)
            private_handle = {key: created[key] for key in ("actorId", "ownerToken", "bookSource")}
            claim = bridge(native_window, proxy, dict(private_handle, action="notes_actor_prepare_commit", expectedRevision=staging["revision"], bookSha256="b" * 64))["actor"]
            with pytest.raises(background.IPCError): bridge(native_window, proxy, dict(private_handle, action="notes_actor_commit", claimToken=claim["claim_token"], saved=True))
            owner.record_saved(profile[0], True, "b" * 64)
            committed = bridge(native_window, proxy, dict(private_handle, action="notes_actor_commit", claimToken=claim["claim_token"]))["actor"]
            assert committed["book_persisted"] and committed["core_committed"] and not committed["phone_persisted"]
            registry = server._phone_actor_registry(proxy._subscriber, handle.book_source)
            native_handle = ActorHandle(handle.actor_id, handle.owner_token)
            now = phone.now_ms()
            wire = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()), "kind": actor_contract.ACK_KIND,
                "created_ms": now, "expires_ms": now + 60000,
                "body": actor_contract.ack(handle.actor_id, str(uuid.uuid4()))}
            assert registry.put(native_handle, wire)
            assert proxy.read_personal_actor_wire(handle, wire["message_id"]) == wire
            assert service.current_actor_source(peer["device_id"], fingerprint) is None, "Aggregate GUI readiness became book authority"
            other.start(); other.set_visible(True); other.set_ready(True)
            assert other.current_actor_source(peer["device_id"], fingerprint) is None
            with pytest.raises(background.IPCError): other.personal_actor_status(handle)
            with pytest.raises(background.IPCError): background.ipc_request("phone_actor_registry", {
                "subscriber": other._subscriber, "book_source": handle.book_source,
                "request": {"action": "staging", "actor_id": handle.actor_id, "owner_token": handle.owner_token,
                    "offset": 0, "limit": 65536, "expected_revision": ""}}, path)
            raw_book = provider()
            assert background.ipc_request("phone_actor_source", {"peer_id": peer["device_id"], "fingerprint": fingerprint,
                "subscriber": other._subscriber, "book_source": raw_book}, path) is None
            owner.set_ready(False)
            assert proxy.current_actor_source(peer["device_id"], fingerprint) is None
            with pytest.raises(background.IPCError): proxy.read_personal_actor_wire(handle, wire["message_id"])
            with pytest.raises(background.IPCError): proxy.read_personal_actor_staging(handle)
            assert proxy.personal_actor_status(handle)["phase"] == "cancelled"
            assert proxy.cancel_personal_actor(handle)["phase"] == "cancelled"
            assert channel.sent[-1]["kind"] == actor_contract.CANCEL_KIND
            owner.set_ready(True)
            reowned = proxy.current_actor_source(peer["device_id"], fingerprint)
            assert reowned and reowned != first
            proxy.set_ready(False)
            assert proxy.current_actor_source(peer["device_id"], fingerprint) is None
            proxy.set_ready(True)
            refreshed = proxy.current_actor_source(peer["device_id"], fingerprint)
            assert refreshed and refreshed != reowned
            profile[0] = "native-profile-b"
            changed_profile = proxy.current_actor_source(peer["device_id"], fingerprint)
            assert changed_profile and changed_profile != refreshed
            with proxy._state_lock:
                calls = [0]
                def changing_book():
                    calls[0] += 1
                    return "a" * 64 if calls[0] == 1 else "b" * 64
                proxy.native_actor_book_source = changing_book
                assert proxy.current_actor_source(peer["device_id"], fingerprint) is None
                proxy.native_actor_book_source = provider
            refreshed = proxy.current_actor_source(peer["device_id"], fingerprint)
            assert refreshed
            with proxy._state_lock:
                current_book = provider()
                def unavailable_book(): raise RuntimeError("Synthetic unavailable native book")
                proxy.native_actor_book_source = unavailable_book
                assert proxy.current_actor_source(peer["device_id"], fingerprint) is None
                assert server.gui_actor_book_source(proxy._subscriber, current_book) is None
                proxy.native_actor_book_source = provider
            refreshed = proxy.current_actor_source(peer["device_id"], fingerprint)
            assert refreshed
            with server._event_condition:
                server._gui_subscribers[proxy._subscriber] = (time.monotonic() - 1, True, True)
                assert server.gui_actor_book_source(proxy._subscriber, provider()) is None
            background.ipc_request("poll_events", {"after": 0, "timeout": 0, "subscriber": proxy._subscriber}, path)
            after_expiry = proxy.current_actor_source(peer["device_id"], fingerprint)
            assert after_expiry and after_expiry != refreshed
            original_call = proxy._call
            def lose_book_after_create(operation, **arguments):
                result = original_call(operation, **arguments)
                if operation == "actor_registry" and arguments["request"]["action"] == "create":
                    owner.set_ready(False)
                return result
            with proxy._state_lock:
                proxy._call = lose_book_after_create
                try:
                    with pytest.raises(background.IPCError): proxy.create_personal_actor(peer["device_id"], fingerprint)
                finally:
                    proxy._call = original_call
            for actor_id, native_handle in server._phone_actor_handles.items():
                native_owner = server._phone_actor_owners[actor_id]
                assert server._phone_actor_registry(*native_owner).status(native_handle)["phase"] == "cancelled"
            proxy.stop()
            assert proxy.current_actor_source(peer["device_id"], fingerprint) is None
            assert service.server is None
        finally:
            for item in (proxy, other):
                item.stop()
                if item._event_thread is not None: item._event_thread.join(timeout=3)
            server.close()


@pytest.mark.parametrize("operation,arguments", [
    ("gui_actor_book_source", {"subscriber": "a" * 32, "source": "client-book-name"}),
    ("phone_actor_source", {"subscriber": "a" * 32, "peer_id": "not-a-peer", "fingerprint": "AAAA-BBBB-CCCC-DDDD", "book_source": "b" * 64}),
    ("phone_actor_source", {"subscriber": "a" * 32, "peer_id": "11111111-1111-4111-8111-111111111111", "fingerprint": "client-revision", "book_source": "b" * 64}),
])
def test_actor_owner_ipc_shape_does_not_accept_display_names_or_client_revisions(operation, arguments):
    with pytest.raises(background.IPCError): background._request_shape(operation, arguments)


@pytest.mark.parametrize("field,value", [("offset", True), ("offset", 1), ("limit", 65537), ("expected_revision", "client-revision"),
    ("attachment_sha256", "a" * 64), ("attachment_sha256", "not-a-file-hash"), ("attachment_sha256", True)])
def test_actor_staging_ipc_requires_bounded_typed_revisioned_continuations(field, value):
    request = {"action": "staging", "actor_id": "11111111-1111-4111-8111-111111111111", "owner_token": "a" * 64,
        "offset": 0, "limit": 65536, "expected_revision": ""}
    request[field] = value
    with pytest.raises(background.IPCError): background._request_shape("phone_actor_registry", {
        "subscriber": "b" * 32, "book_source": "c" * 64, "request": request})


@pytest.mark.parametrize("field,value", [("sequence", True), ("sequence", 0), ("book_source", "d" * 64), ("sha256", "client-saved")])
def test_actor_commit_ipc_cannot_replace_native_saved_book_binding(field, value):
    saved = {"book_source": "c" * 64, "sequence": 1, "sha256": "e" * 64}; saved[field] = value
    with pytest.raises(background.IPCError): background._request_shape("phone_actor_registry", {
        "subscriber": "b" * 32, "book_source": "c" * 64, "request": {"action": "commit", "actor_id": "11111111-1111-4111-8111-111111111111",
            "owner_token": "a" * 64, "claim_token": "f" * 64, "native_saved_book": saved}})


def test_unsupported_actor_metadata_does_not_drop_ordinary_proxy_events(tmp_path, monkeypatch):
    service, peer, _, fingerprint, _ = actor_source_fixture(tmp_path, monkeypatch)
    with tempfile.TemporaryDirectory(prefix="actor-old-daemon-") as root:
        path = str(Path(root) / "bridge.sock")
        server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
        service.personal_sync_available = server.gui_personal_ready
        delivered = threading.Event()
        server.phone_event_getter = lambda ticket: {"event": "owned-normal-event", "payload": {"ticket": ticket}}
        proxy = background.PhoneServiceProxy(path, callback=lambda event, payload: delivered.set())
        proxy.native_actor_book_source = lambda: "a" * 64
        try:
            proxy.start(); proxy.set_visible(True); proxy.set_ready(True)
            assert proxy.current_actor_source(peer["device_id"], fingerprint)
            original = background.ipc_request
            def previous_daemon(operation, *args, **kwargs):
                if operation == "gui_actor_book_source": raise background.IPCError("Unsupported previous daemon operation")
                return original(operation, *args, **kwargs)
            monkeypatch.setattr(background, "ipc_request", previous_daemon)
            server.publish_event("phone_event", {"ticket": "owned-event-ticket"})
            assert delivered.wait(3), "Actor metadata incompatibility suppressed an ordinary GUI event"
        finally:
            proxy.stop()
            if proxy._event_thread is not None: proxy._event_thread.join(timeout=3)
            server.close()
