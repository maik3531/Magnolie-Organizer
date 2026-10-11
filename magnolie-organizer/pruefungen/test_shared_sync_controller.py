"""Real local bridge/controller boundary; previews do not invent shared choices."""
import copy
import tempfile
from pathlib import Path

import pytest
from test_shared_sync_transport import fixture
import magnolie_hintergrund as background
import magnolie_shared_sync as shared
import magnolie_telefon as phone
from test_hintergrunddienst import FakeBackend


def test_common_choice_uses_authenticated_local_ipc_and_current_fingerprint(tmp_path, monkeypatch):
    service, peer, _, _ = fixture(tmp_path, monkeypatch, initialize=False)
    before = copy.deepcopy(peer)
    peer_id = peer["device_id"]
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    initial = dict(shared.DEFAULTS, content_mode="phone_import", auto_mode="wifi", time_enabled=True)
    assert service.shared_settings_status(peer_id) == {"supported": True, "initialized": False, "ready": False, "values": None}
    assert service.store.shared_settings(peer_id, peer["static_public"]) is None
    with tempfile.TemporaryDirectory(prefix="shared-ui-") as root:
        socket = str(Path(root) / "bridge.sock")
        server = background.IPCServer(FakeBackend(), socket, phone_backend=service).start()
        try:
            proxy = background.PhoneServiceProxy(socket)
            result = proxy.initialize_common_preferences(peer_id, fingerprint, initial)
            assert result["initialized"] and result["values"] == initial
            result = proxy.change_common_preference(peer_id, fingerprint, "content_mode", "phone_scope", initial)
            assert result["values"]["content_mode"] == "phone_scope"
            assert proxy.initialize_common_preferences(peer_id, fingerprint, initial)["values"] == result["values"]
            for field, value, seed, key in [("content_mode", "unknown", initial, fingerprint),
                    ("time_enabled", "true", initial, fingerprint), ("auto_mode", "manual", {}, fingerprint),
                    ("auto_mode", "manual", initial, "old-key")]:
                with pytest.raises(background.IPCError):
                    proxy.change_common_preference(peer_id, key, field, value, seed)
            assert service.shared_settings_status(peer_id)["values"] == result["values"]
        finally:
            server.close()
    assert peer["personal_sync"]["auto_wifi"] is True
    assert peer["time_sync"]["local"]["enabled"] is True
    assert peer["static_public"] == before["static_public"]
    assert peer["local_grants"] == before["local_grants"]
    assert peer["grants"] == before["grants"]


def test_unsupported_peer_cannot_initialize_from_a_local_preview(tmp_path, monkeypatch):
    service, peer, _, _ = fixture(tmp_path, monkeypatch, negotiated=False, initialize=False)
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    assert not service.shared_settings_status(peer["device_id"])["supported"]
    with pytest.raises(PermissionError):
        service.initialize_common_preferences(peer["device_id"], fingerprint, shared.DEFAULTS)
    assert service.store.shared_settings(peer["device_id"], peer["static_public"]) is None
