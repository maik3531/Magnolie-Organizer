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


@pytest.mark.parametrize("action", ["choice", "start"])
def test_paired_preferences_do_not_require_another_confirmation_or_restore_revoked_modules(tmp_path, monkeypatch, action):
    service, peer, _, _ = fixture(tmp_path, monkeypatch, initialize=False)
    peer["personal_sync"]["own_device"] = False
    peer["local_grants"]["grants"].update(personal_notes_sync=False, personal_tasks_sync=False)
    service.store.save_peers()
    peer_id = peer["device_id"]
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    initial = dict(shared.DEFAULTS)
    assert not service.shared_settings_status(peer_id)["initialized"]
    service.initialize_common_preferences(peer_id, fingerprint, initial)
    saved = service.store.shared_settings(peer_id, peer["static_public"])
    for field, value, key in [("content_mode", "invalid", fingerprint), ("auto_mode", "wifi", "stale")]:
        with pytest.raises((ValueError, PermissionError)):
            service.change_common_preference(peer_id, key, field, value, initial)
    assert peer["personal_sync"]["own_device"]
    assert service.store.shared_settings(peer_id, peer["static_public"]) == saved
    with tempfile.TemporaryDirectory(prefix="shared-optin-") as root:
        socket = str(Path(root) / "bridge.sock")
        server = background.IPCServer(FakeBackend(), socket, phone_backend=service).start()
        try:
            proxy = background.PhoneServiceProxy(socket)
            if action == "choice":
                result = proxy.change_common_preference(peer_id, fingerprint, "auto_mode", "wifi", initial)
                assert result["initialized"] and result["values"]["auto_mode"] == "wifi"
            else:
                proxy.start_common_sync(peer_id, fingerprint, initial)
                assert service.store.has_kind(peer_id, shared.START_KIND)
            assert peer["personal_sync"]["own_device"]
            assert not any(peer["local_grants"]["grants"][field] for field in ("personal_notes_sync", "personal_tasks_sync"))
        finally:
            server.close()


def test_notes_only_gui_readiness_enables_contact_read_without_kde_or_new_grants(tmp_path, monkeypatch):
    service, peer, channel, _ = fixture(tmp_path, monkeypatch, initialize=False)
    service.enabled = True  # Synthetic current connection, without a network listener.
    peer['capabilities']['items']['device_status'] = {'available': True, 'reason': 'available', 'versions': [5, 7]}
    peer['grants']['grants']['device_status'] = True
    peer['local_grants']['grants']['device_status'] = True
    service.note_controls[channel]['capabilities.update'] = copy.deepcopy(peer['capabilities'])
    service.note_controls[channel]['grants.update'] = copy.deepcopy(peer['grants'])
    before = copy.deepcopy(peer)
    with tempfile.TemporaryDirectory(prefix='own-profile-ready-') as root:
        socket = str(Path(root) / 'bridge.sock')
        server = background.IPCServer(FakeBackend(), socket, phone_backend=service).start()
        service.personal_sync_available = server.gui_personal_ready
        proxy = background.PhoneServiceProxy(socket)
        try:
            proxy.start()
            assert proxy.set_visible(True)
            assert not service.contacts_available(peer['device_id'])
            assert proxy.set_ready(True)
            assert service.contacts_available(peer['device_id'])
            assert proxy.set_ready(False) is False
            assert not service.contacts_available(peer['device_id'])
            assert proxy.set_ready(True)
            assert proxy.set_visible(False) is False
            assert not service.contacts_available(peer['device_id'])
            assert peer == before, 'Readiness must not create consent or rewrite grants'
        finally:
            proxy.stop(); server.close()


@pytest.mark.parametrize('ready_first', [False, True])
def test_late_gui_readiness_resumes_initialized_shared_exchange(tmp_path, monkeypatch, ready_first):
    service, peer, channel, body = fixture(tmp_path, monkeypatch)
    before = copy.deepcopy(peer)
    with tempfile.TemporaryDirectory(prefix='shared-late-ready-') as root:
        socket = str(Path(root) / 'bridge.sock')
        server = background.IPCServer(FakeBackend(), socket, phone_backend=service).start()
        service.personal_sync_available = server.gui_personal_ready
        proxy = background.PhoneServiceProxy(socket)
        try:
            proxy.start()
            if ready_first: proxy.set_ready(True)
            else: proxy.set_visible(True)
            service._queue_shared_settings(peer['device_id'], channel)
            assert not any(item.get('kind') == shared.KIND for item in channel.sent)
            if ready_first: proxy.set_visible(True)
            else: proxy.set_ready(True)
            sent = [item for item in channel.sent if item.get('kind') == shared.KIND]
            assert len(sent) == 1, 'GUI became ready after controls, but shared exchange never resumed'
            assert sent[0]['body'] == body
            proxy.set_ready(True)
            assert len([item for item in channel.sent if item.get('kind') == shared.KIND]) == 1
            assert service.store.shared_settings(peer['device_id'], peer['static_public']) == body
            assert peer == before
        finally:
            proxy.stop(); server.close()


@pytest.mark.parametrize('gate', ['uninitialized', 'controls', 'disconnected'])
def test_gui_resume_never_creates_shared_choices_or_bypasses_controls(tmp_path, monkeypatch, gate):
    service, peer, channel, _ = fixture(tmp_path, monkeypatch, initialize=gate != 'uninitialized')
    if gate == 'controls': service.note_controls[channel].pop('grants.update')
    if gate == 'disconnected': service.connections.clear()
    before = copy.deepcopy(peer)
    saved = service.store.shared_settings(peer['device_id'], peer['static_public'])
    service.resume_common_preferences()
    assert not channel.sent
    assert not service.store.pending(peer['device_id'])
    assert service.store.shared_settings(peer['device_id'], peer['static_public']) == saved
    assert peer == before
