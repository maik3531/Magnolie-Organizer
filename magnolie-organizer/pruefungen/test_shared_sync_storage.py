"""Private common-function metadata is encrypted, transactional and pair-bound."""
import copy
import uuid
import sqlite3
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_shared_sync as shared
import magnolie_telefon as phone
from test_personal_sync import _personal_service


def fixture(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    return service, peer_id, service.store.peer(peer_id)["static_public"]


def test_preview_never_initializes_metadata_or_changes_any_permissions(tmp_path):
    service, peer_id, public = fixture(tmp_path)
    before = copy.deepcopy(service.store.peer(peer_id))
    assert service.store.shared_settings(peer_id, public) is None
    assert service.store.peer(peer_id) == before
    assert service.store.pending(peer_id) == []
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'shared_settings:%'").fetchone()[0] == 0


def test_explicit_initialization_preserves_legacy_choices_at_zero_and_never_reseeds(tmp_path):
    service, peer_id, public = fixture(tmp_path)
    before = copy.deepcopy(service.store.peer(peer_id))
    initial = {"content_mode": "phone_import", "auto_mode": "wifi", "skip_deletions": True,
               "custom_enabled": False, "time_enabled": True, "time_mode": "phone_import"}
    body = service.store.initialize_shared_settings(peer_id, public, initial)
    assert shared.effective(body) == initial
    assert all(edit["counter"] == 0 for field in body["settings"].values() for edit in field.values())
    changed = service.store.change_shared_setting(peer_id, public, "content_mode", "phone_scope")
    assert service.store.initialize_shared_settings(peer_id, public, dict(initial, content_mode="two_way")) == changed
    assert service.store.peer(peer_id) == before and service.store.pending(peer_id) == []


def test_one_local_change_is_encrypted_and_survives_reopen_without_granting(tmp_path):
    service, peer_id, public = fixture(tmp_path)
    before = copy.deepcopy(service.store.peer(peer_id))
    body = service.store.change_shared_setting(peer_id, public, "content_mode", "two_way")
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Synthetic")
    assert reopened.shared_settings(peer_id, public) == body
    assert shared.effective(body)["content_mode"] == "two_way"
    assert service.store.peer(peer_id) == before
    assert service.store.pending(peer_id) == []
    with sqlite3.connect(service.store.database_path) as db:
        sealed = bytes(db.execute("SELECT value FROM meta WHERE key LIKE 'shared_settings:%'").fetchone()[0])
        assert b"content_mode" not in sealed and b"two_way" not in sealed


def test_remote_change_and_echo_update_the_same_persisted_choice_once(tmp_path):
    service, peer_id, public = fixture(tmp_path)
    local = service.store.identity["device_id"]
    body = service.store.change_shared_setting(peer_id, public, "content_mode", "two_way")
    remote = shared.merge(shared.create(peer_id), body, peer_id, local)
    remote = shared.change(remote, peer_id, local, "content_mode", "phone_scope")
    accepted = service.store.merge_shared_settings(peer_id, public, remote)
    assert shared.effective(accepted)["content_mode"] == "phone_scope"
    assert service.store.merge_shared_settings(peer_id, public, remote) == accepted
    assert service.store.shared_settings(peer_id, public) == accepted


def test_stale_bootstrap_reasserts_current_choice_and_converges_durably(tmp_path):
    service, peer_id, public = fixture(tmp_path)
    local = service.store.identity["device_id"]
    old = shared.create(local)
    remote = shared.merge(shared.create(peer_id), old, peer_id, local)
    for _ in range(2):
        remote = shared.change(remote, peer_id, local, "auto_mode", "wifi")
    before = service.store.initialize_shared_settings(peer_id, public, {"auto_mode": "wifi"})
    with pytest.raises(ValueError):
        shared.merge(before, remote, local, peer_id)
    repaired = service.store.merge_shared_settings(peer_id, public, remote)
    assert repaired["settings"]["auto_mode"][local] == {"counter": 1, "value": "wifi"}
    echoed = shared.merge(remote, repaired, peer_id, local)
    assert service.store.merge_shared_settings(peer_id, public, echoed) == repaired
    assert phone.PhoneStore(str(tmp_path / "phone"), "Synthetic").shared_settings(peer_id, public) == repaired
    assert service.store.merge_shared_settings(peer_id, public, remote) == repaired
    bad = copy.deepcopy(remote)
    bad["settings"]["custom_enabled"][local] = {"counter": 100, "value": True}
    with pytest.raises(ValueError):
        service.store.merge_shared_settings(peer_id, public, bad)
    assert service.store.shared_settings(peer_id, public) == repaired


def test_rejected_multi_field_merge_and_failed_seal_roll_back(tmp_path, monkeypatch):
    service, peer_id, public = fixture(tmp_path)
    local = service.store.identity["device_id"]
    body = service.store.change_shared_setting(peer_id, public, "content_mode", "two_way")
    remote = shared.merge(shared.create(peer_id), body, peer_id, local)
    remote["settings"]["auto_mode"][peer_id] = {"counter": 1, "value": "connection"}
    remote["settings"]["content_mode"][local] = {"counter": 100, "value": "phone_scope"}
    with pytest.raises(ValueError):
        service.store.merge_shared_settings(peer_id, public, remote)
    assert service.store.shared_settings(peer_id, public) == body
    original = service.store._encrypt
    def fail(*args):
        raise OSError("synthetic seal failure")
    monkeypatch.setattr(service.store, "_encrypt", fail)
    with pytest.raises(OSError):
        service.store.change_shared_setting(peer_id, public, "auto_mode", "connection")
    monkeypatch.setattr(service.store, "_encrypt", original)
    assert service.store.shared_settings(peer_id, public) == body


def test_changed_peer_key_and_unpair_do_not_reuse_old_common_settings(tmp_path):
    service, peer_id, public = fixture(tmp_path)
    body = service.store.change_shared_setting(peer_id, public, "content_mode", "two_way")
    different = phone.b64(bytes([71]) * 32)
    with pytest.raises(PermissionError):
        service.store.shared_settings(peer_id, different)
    with pytest.raises(PermissionError):
        service.store.change_shared_setting(peer_id, different, "auto_mode", "connection")
    assert service.store.shared_settings(peer_id, public) == body
    service.remove(peer_id)
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'shared_settings:%'").fetchone()[0] == 0


class SharedChannel:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


def connected_fixture(tmp_path):
    service, peer_id, public = fixture(tmp_path)
    peer = service.store.peer(peer_id)
    peer["capabilities"] = phone.desktop_capabilities()
    channel = SharedChannel()
    service.connections[peer_id] = channel
    service.connection_transports[peer_id] = "wifi"
    service.note_controls[channel] = {"capabilities.update": copy.deepcopy(peer["capabilities"]),
        "grants.update": copy.deepcopy(peer["grants"]),
        "personal_sync.settings": {"format": 1, "own_device": True}}
    return service, peer, channel


def test_runtime_read_does_not_initialize_queue_or_create_session(tmp_path):
    service, peer, channel = connected_fixture(tmp_path)
    before = copy.deepcopy(peer)
    result = service.shared_settings_runtime(peer["device_id"])
    assert result["controls_ready"] and not result["session_present"]
    assert result["last_ack"] is None and result["last_incoming"] is None
    assert service.store.shared_settings(peer["device_id"], peer["static_public"]) is None
    assert not service.shared_sessions and not service.store.pending(peer["device_id"])
    assert peer == before and not channel.sent


def test_runtime_records_rejected_ack_without_changing_retry_policy(tmp_path):
    service, peer, channel = connected_fixture(tmp_path)
    peer_id = peer["device_id"]
    body = service.store.initialize_shared_settings(peer_id, peer["static_public"], {})
    session = service._shared_session(peer, channel)
    session["sent"] = copy.deepcopy(body)
    message = service.store.queue(peer_id, shared.KIND, body, phone.DAY_MS)
    service._payload(peer, channel, {"type": "ack", "message_id": message["message_id"],
        "status": "rejected", "error": "not_granted"})
    result = service.shared_settings_runtime(peer_id)
    assert result["last_ack"] == {"status": "rejected", "error": "not_granted"}
    assert result["sent_matches"] and not result["received_present"]
    assert service.store.outbox_message(peer_id, message["message_id"]) is None
    result["last_ack"]["error"] = "changed"
    assert session["last_ack"]["error"] == "not_granted"
    assert service.store.shared_settings(peer_id, peer["static_public"]) == body


def test_runtime_distinguishes_controls_and_strict_merge_rejection(tmp_path):
    service, peer, channel = connected_fixture(tmp_path)
    peer_id = peer["device_id"]
    local = service.store.identity["device_id"]
    body = service.store.initialize_shared_settings(peer_id, peer["static_public"], {})
    incoming = shared.merge(shared.create(peer_id), body, peer_id, local)
    incoming["settings"]["auto_mode"][local] = {"counter": 100, "value": "wifi"}
    now = phone.now_ms()
    message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
        "kind": shared.KIND, "created_ms": now, "expires_ms": now + 60000, "body": incoming}
    service.personal_sync_available = lambda: False
    service._payload(peer, channel, message)
    assert service.shared_settings_runtime(peer_id)["last_incoming"] == {
        "status": "rejected", "error": "not_granted", "stage": "controls"}
    service.personal_sync_available = lambda: True
    service._payload(peer, channel, message)
    result = service.shared_settings_runtime(peer_id)
    last = result["last_incoming"]
    assert {key: last[key] for key in ("status", "error", "stage")} == {
        "status": "rejected", "error": "invalid_schema", "stage": "merge"}
    assert last["merge_rejection"] == "unknown_local_echo"
    assert last["merge_checks"]["auto_mode"] == {"foreign_actor": False,
        "local_counter": 0, "echo_counter": 100, "echo_value_matches": False, "peer_counter": 0}
    assert local not in str(last) and peer_id not in str(last)
    assert not result["received_present"]
    assert service.store.shared_settings(peer_id, peer["static_public"]) == body
    assert service.store.dedupe_result(peer_id, message["message_id"]) is None
    assert all(isinstance(value, (bool, dict, type(None))) for value in result.values())
    service.connections[peer_id] = SharedChannel()
    assert service.shared_settings_runtime(peer_id)["last_incoming"] is None
