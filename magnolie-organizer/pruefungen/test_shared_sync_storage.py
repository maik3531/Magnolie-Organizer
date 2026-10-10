"""Private common-function metadata is encrypted, transactional and pair-bound."""
import copy
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
