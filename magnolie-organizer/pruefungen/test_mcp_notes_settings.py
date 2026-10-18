"""Actual shared preference handlers and stores, including daemon ownership."""
import copy
import json
import pytest
from test_mcp_phone import owned_service
import magnolie_telefon as phone
import magnolie_hintergrund as background
from test_hintergrunddienst import FakeBackend


def request(service, action="notes_settings_read", **extra):
    peer = service.store.peers[0]
    return {"action": action, "peerId": peer["device_id"],
        "fingerprint": phone.fingerprint(phone.unb64(peer["static_public"], 32)), **extra}


def modern_service(tmp_path):
    service, peer, events = owned_service(tmp_path)
    peer["capabilities"] = phone.desktop_capabilities()
    peer["personal_sync"] = {"own_device": False, "remote_own_device": False, "auto_wifi": False, "last_report": {}}
    for name in ("personal_notes_sync", "personal_tasks_sync"):
        peer["capabilities"]["items"][name].update(available=True, versions=[1, 2, 3, 4, 5, 7, 9, 11])
    service.store.save_peers()
    return service, peer, events


def change(service, field="auto_mode", value="wifi", **extra):
    state = service.mcp_action(request(service))["notesSettings"]
    return service.mcp_action(request(service, "notes_settings_update", expectedRevision=state["revision"],
        initial=copy.deepcopy(phone.shared_sync_contract.DEFAULTS), field=field, value=value, **extra))


def test_read_is_side_effect_free_and_revision_tracks_consent_not_reports(tmp_path):
    service, peer, events = modern_service(tmp_path)
    before_peers = copy.deepcopy(service.store._load_peers())
    first = service.mcp_action(request(service))
    assert first["ok"] and first["notesSettings"]["shared"] == {"supported": True, "initialized": False, "ready": False, "values": None}
    assert service.store._load_peers() == before_peers and not events and not service.server
    peer["personal_sync"]["last_report"] = {"private": "owned-content-not-for-settings"}
    assert service.mcp_action(request(service)) == first
    assert "owned-content" not in json.dumps(first)
    peer["personal_sync"]["remote_own_device"] = True
    assert service.mcp_action(request(service))["notesSettings"]["revision"] != first["notesSettings"]["revision"]
    replacement = phone.PhoneService(str(tmp_path / "phone"), "Owned desktop")
    assert replacement.mcp_action(request(replacement))["notesSettings"]["revision"] != service.mcp_action(request(service))["notesSettings"]["revision"]


def test_gui_handler_activation_shared_vectors_and_store_readback(tmp_path):
    service, peer, events = modern_service(tmp_path)
    saved = change(service)
    assert saved["ok"], saved
    assert saved["persisted"] and saved["localVerified"] and saved["deliveryConfirmed"] is False
    assert saved["notesSettings"]["own_device"] and not saved["notesSettings"]["remote_own_device"]
    assert saved["notesSettings"]["shared"]["values"]["auto_mode"] == "wifi"
    assert service.store._load_peers()[0]["personal_sync"]["auto_wifi"]
    other = change(service, "skip_deletions", False)
    assert other["ok"] and other["notesSettings"]["shared"]["values"]["auto_mode"] == "wifi"
    assert service.store._load_peers()[0]["local_grants"]["grants"]["personal_deletions_sync"]
    assert not events and not service.server


def test_stale_wrong_peer_unsupported_and_commit_race_are_rejected(tmp_path, monkeypatch):
    service, peer, events = modern_service(tmp_path)
    state = service.mcp_action(request(service))["notesSettings"]
    args = request(service, "notes_settings_update", expectedRevision=state["revision"],
        initial=copy.deepcopy(phone.shared_sync_contract.DEFAULTS), field="auto_mode", value="wifi")
    assert service.mcp_action({**args, "fingerprint": "0000-0000-0000-0000"})["code"] == "conflict"
    original = service.change_common_preference
    def raced(*pos, **kw):
        peer["personal_sync"]["remote_own_device"] = True
        return original(*pos, **kw)
    monkeypatch.setattr(service, "change_common_preference", raced)
    assert service.mcp_action(args)["code"] == "conflict"
    assert service.store.shared_settings(peer["device_id"], peer["static_public"]) is None
    monkeypatch.setattr(service, "change_common_preference", original)
    for name in ("personal_notes_sync", "personal_tasks_sync"):
        peer["capabilities"]["items"][name]["versions"] = [1, 2, 3]
    assert service.mcp_action(request(service))["notesSettings"]["shared"]["supported"] is False
    assert not change(service)["ok"] and not events


def test_daemon_proxy_uses_actual_store_without_gui_subscription(tmp_path):
    service, peer, events = modern_service(tmp_path)
    path = str(tmp_path / "runtime" / "background.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path)
    try:
        state = proxy.mcp_action(request(service))["notesSettings"]
        saved = proxy.mcp_action(request(service, "notes_settings_update", expectedRevision=state["revision"],
            initial=copy.deepcopy(phone.shared_sync_contract.DEFAULTS), field="auto_mode", value="manual"))
        assert saved["ok"] and saved["persisted"] and proxy._event_thread is None and not service.server
        assert not events
        with pytest.raises(background.IPCError):
            proxy.mcp_action({"action": "notes_settings_update"})
    finally:
        server.close()


def test_actual_preference_readback_is_required(tmp_path, monkeypatch):
    service, peer, events = modern_service(tmp_path)
    original = service.store._load_peers
    def inconsistent_disk():
        peers = original()
        peers[0]["personal_sync"]["auto_wifi"] = False
        return peers
    monkeypatch.setattr(service.store, "_load_peers", inconsistent_disk)
    result = change(service)
    assert result == {"ok": False, "code": "verification_failed"} and not events


@pytest.mark.parametrize("field,value", [("content_mode", "two_way"), ("auto_mode", "connection"),
    ("custom_enabled", True), ("time_enabled", True), ("time_mode", "two_way")])
def test_all_shared_choice_types_use_existing_handler(tmp_path, field, value):
    service, peer, events = modern_service(tmp_path)
    result = change(service, field, value)
    assert result["ok"], result
    assert result["notesSettings"]["shared"]["values"][field] == value
    assert not events
