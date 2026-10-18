"""Public native phone-control snapshots; no listener or cached content reads."""
import json
import sys
import threading
from types import SimpleNamespace
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
from test_telefon import _complete_peer, FakeBluetooth
import magnolie_hintergrund as background
from test_hintergrunddienst import FakeBackend


def test_public_snapshot_revision_excludes_tokens_status_and_volatile_clocks(tmp_path):
    events = []
    service = phone.PhoneService(str(tmp_path / "phone"), "Owned desktop", callback=lambda *args: events.append(args), bluetooth_backend=FakeBluetooth())
    peer = _complete_peer("11111111-1111-4111-8111-111111111111")
    peer["display_name"] = "Owned phone"
    peer["grants"]["grants"]["device_status"] = True
    peer["status"] = {"private": "owned-private-device-cache"}
    service.store.peers = [peer]
    service.store.save_peers()
    service.pairing_token = bytes(range(16))
    service.pairing_until = float("inf")
    before = service.mcp_status()
    assert before["revision"] == service.mcp_status()["revision"] and not service.server and not events
    text = json.dumps(before)
    assert phone.b64(service.pairing_token) not in text and "owned-private" not in text and "static_public" not in text
    assert before["peers"][0]["id"] == peer["device_id"] and before["peers"][0]["remote_grants"]["device_status"] is True
    peer["last_contact_ms"] = 123456
    peer["status"] = {"private": "changed-private-device-cache"}
    assert service.mcp_status()["revision"] == before["revision"]
    peer["local_grants"]["grants"]["selected_notifications_readonly"] = True
    after = service.mcp_status()
    assert after["revision"] != before["revision"] and after["peers"][0]["local_grants"]["selected_notifications_readonly"]


def test_snapshot_uses_actual_pending_pairing_context_and_process_key(tmp_path):
    root = str(tmp_path / "phone")
    service = phone.PhoneService(root, "Owned desktop", bluetooth_backend=FakeBluetooth())
    initial = service.mcp_status()
    service.pairings["owned-attempt"] = {"event": threading.Event(), "decision": None, "socket": None,
        "public": {"attempt_id": "owned-attempt", "id": "11111111-1111-4111-8111-111111111111", "name": "Owned pending phone", "code": "123456",
                   "fingerprint": "A" * 64, "confirmation_required": True}}
    pending = service.mcp_status()
    assert pending["revision"] != initial["revision"] and pending["pending_pairings"][0]["attempt_id"] == "owned-attempt"
    assert pending["pending_pairings"][0]["decision_pending"] is True
    service.confirm_pairing("owned-attempt", False)
    assert service.mcp_status()["pending_pairings"][0]["decision_pending"] is False
    replacement = phone.PhoneService(root, "Owned desktop", bluetooth_backend=FakeBluetooth())
    assert replacement.mcp_status()["revision"] != initial["revision"]


def test_daemon_proxy_status_uses_existing_owner_without_subscription_or_replay(tmp_path, monkeypatch):
    service = phone.PhoneService(str(tmp_path / "phone"), "Owned daemon desktop", bluetooth_backend=FakeBluetooth())
    peer = _complete_peer("11111111-1111-4111-8111-111111111111")
    service.store.peers = [peer]; service.store.save_peers()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Status must not start a phone listener or replay personal content")
    monkeypatch.setattr(service, "start", forbidden)
    monkeypatch.setattr(service, "replay_personal_sync", forbidden)
    path = str(tmp_path / "runtime" / "background.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path, callback=forbidden)
    try:
        direct = service.mcp_status()
        result = proxy.mcp_status()
        assert result == direct and proxy._event_thread is None and service.server is None
        target = result["peers"][0]
        request = {"action": "grant", "expectedRevision": result["revision"], "peerId": target["id"], "fingerprint": target["fingerprint"], "name": "selected_notifications_readonly", "enabled": True}
        saved = proxy.mcp_action(request)
        assert saved["ok"] and saved["persisted"] and service.store._load_peers()[0]["local_grants"]["grants"]["selected_notifications_readonly"]
        assert proxy._event_thread is None and service.server is None
        with pytest.raises(background.IPCError):
            background.ipc_request("phone_mcp_action", {"request": {}}, path)
        setup = server.setup_sessions
        server.setup_sessions = SimpleNamespace(connecting_transport="wifi")
        try:
            with pytest.raises(background.IPCError, match="setup session"):
                proxy.mcp_action({**request, "expectedRevision": proxy.mcp_status()["revision"], "enabled": False})
            assert service.store._load_peers()[0]["local_grants"]["grants"]["selected_notifications_readonly"]
        finally:
            server.setup_sessions = setup
    finally:
        server.close()


def owned_service(tmp_path):
    events = []
    service = phone.PhoneService(str(tmp_path / "phone"), "Owned desktop", callback=lambda *args: events.append(args), bluetooth_backend=FakeBluetooth())
    peer = _complete_peer("11111111-1111-4111-8111-111111111111")
    service.store.peers = [peer]; service.store.save_peers()
    return service, peer, events


def action(service, action_name, **values):
    state = service.mcp_status()
    target = state["peers"][0] if state["peers"] else {}
    return service.mcp_action({"action": action_name, "expectedRevision": state["revision"], "peerId": target.get("id", ""), "fingerprint": target.get("fingerprint", ""), **values})


def test_existing_phone_handlers_store_readback_fingerprints_and_scoped_callbacks(tmp_path):
    service, peer, events = owned_service(tmp_path)
    initial = service.mcp_status()
    disabled = action(service, "settings", enabled=False)
    assert disabled["ok"] and disabled["persisted"] and not service.store.settings()["enabled"] and not service.server
    granted = action(service, "grant", name="selected_notifications_readonly", enabled=True)
    assert granted["ok"] and granted["localVerified"] and granted["persisted"] and granted["deliveryConfirmed"] is False
    assert service.store._load_peers()[0]["local_grants"]["grants"]["selected_notifications_readonly"] is True
    bluetooth = action(service, "bluetooth", enabled=True, address="aa:bb:cc:dd:ee:ff")
    assert bluetooth["ok"] and bluetooth["persisted"] and service.store._load_peers()[0]["bluetooth"] == {"enabled": True, "address": "AA:BB:CC:DD:EE:FF"}
    wrong = action(service, "grant", name="selected_notifications_readonly", enabled=False, fingerprint="wrong")
    assert not wrong["ok"] and wrong["code"] == "conflict"
    stale = action(service, "remove", expectedRevision=initial["revision"])
    assert not stale["ok"] and stale["code"] == "conflict" and len(service.store._load_peers()) == 1
    static = action(service, "grant", name="device_status", enabled=False)
    assert not static["ok"] and static["code"] == "unsupported_feature" and not events
    service.set_grant(peer["device_id"], "selected_notifications_readonly", False)
    assert [event[0] for event in events] == ["status"]
    events.clear()
    removed = action(service, "remove")
    assert removed["ok"] and removed["persisted"] and not service.store._load_peers() and not events


def test_pending_pairing_decisions_are_attempt_bound_not_completed_pairing_claims(tmp_path):
    service, peer, events = owned_service(tmp_path)
    target = service.mcp_status()["peers"][0]
    def pending(attempt):
        context = {"event": threading.Event(), "decision": None, "socket": None, "public": {"attempt_id": attempt, "id": target["id"], "name": "Owned phone", "code": "123456", "fingerprint": target["fingerprint"], "confirmation_required": True}}
        service.pairings[attempt] = context
        return context
    first = pending("first-attempt")
    stale = action(service, "pairing_confirm", attemptId="other-attempt", accept=True)
    assert not stale["ok"] and first["decision"] is None
    accepted = action(service, "pairing_confirm", attemptId="first-attempt", accept=True)
    assert accepted["ok"] and not accepted["persisted"] and not accepted["deliveryConfirmed"] and first["decision"] is True and first["event"].is_set()
    service.pairings.clear()
    expired = pending("expired-attempt"); expired["mcp_deadline"] = 0
    assert service.mcp_status()["pending_pairings"] == []
    too_late = action(service, "pairing_confirm", attemptId="expired-attempt", accept=True)
    assert not too_late["ok"] and too_late["code"] == "conflict" and expired["decision"] is None
    service.pairings.clear()
    second = pending("second-attempt")
    rejected = action(service, "pairing_cancel", attemptId="second-attempt")
    assert rejected["ok"] and not rejected["persisted"] and second["decision"] is False and second["event"].is_set() and not service.pairings and not events


def test_phone_mutator_rechecks_revision_at_commit_and_does_not_fake_readback(tmp_path, monkeypatch):
    service, peer, events = owned_service(tmp_path)
    original = service.set_grant
    def concurrent_preference(*args, **kwargs):
        peer["local_grants"]["grants"]["selected_notifications_readonly"] = True
        service.store.save_peers()
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "set_grant", concurrent_preference)
    result = action(service, "grant", name="selected_notifications_readonly", enabled=False)
    assert not result["ok"] and result["code"] == "conflict" and service.store._load_peers()[0]["local_grants"]["grants"]["selected_notifications_readonly"] is True
    monkeypatch.setattr(service, "set_grant", original)
    monkeypatch.setattr(service.store, "_load_peers", lambda: [])
    failed = action(service, "grant", name="selected_notifications_readonly", enabled=False)
    assert not failed["ok"] and failed["code"] == "verification_failed" and not events


def test_disabled_preference_is_not_a_drained_listener_receipt(tmp_path, monkeypatch):
    service, peer, events = owned_service(tmp_path)
    monkeypatch.setattr(service, "stop", lambda: False)
    class Undrained:
        def is_alive(self): return True
    service._workers.add(Undrained())
    try:
        result = action(service, "settings", enabled=False)
        assert not result["ok"] and result["code"] == "verification_failed" and not service.store.settings()["enabled"] and not events
    finally:
        service._workers.clear()


def test_pending_phone_binding_can_be_removed_without_becoming_grant_target(tmp_path):
    service, peer, events = owned_service(tmp_path)
    peer.update(state="pair_commit_pending", pending_transcript=phone.b64(bytes([1]) * 32),
        pending_phone_finish_proof=phone.b64(bytes([2]) * 32), pending_desktop_finish_proof=phone.b64(bytes([3]) * 32), pending_expires_ms=phone.now_ms() + 60000)
    service.store.save_peers()
    denied = action(service, "grant", name="selected_notifications_readonly", enabled=True)
    assert not denied["ok"] and denied["code"] == "conflict"
    removed = action(service, "remove")
    assert removed["ok"] and removed["persisted"] and not service.store._load_peers() and not events
