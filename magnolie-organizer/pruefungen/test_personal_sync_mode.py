"""Issue #27: one explicit mode choice configures the local personal-sync scope."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_personal_sync as sync
import magnolie_telefon as phone
from test_personal_sync import _personal_service


def test_mode_choice_enables_notes_tasks_and_default_deletion_review(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id)
    peer["personal_sync"]["own_device"] = False
    peer["personal_sync"]["remote_own_device"] = False
    peer["local_grants"]["grants"]["personal_notes_sync"] = False
    service.store.save_peers()
    service.set_personal_sync_mode(peer_id, True, False)
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Synthetic")
    saved = reopened.peer(peer_id)
    assert saved["personal_sync"]["own_device"] and saved["personal_sync"]["auto_wifi"]
    assert not saved["personal_sync"]["remote_own_device"], "local operation must not invent remote consent"
    assert all(saved["local_grants"]["grants"][name] for name in (
        "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync"))
    assert saved["local_grants"]["grants"]["selected_notifications_readonly"]
    pending = reopened.pending(peer_id)
    assert {message["kind"] for message in pending} == {"grants.update", "personal_sync.settings"}
    assert next(message for message in pending if message["kind"] == "grants.update")["body"]["grants"]["personal_deletions_sync"]


def test_manual_and_skip_choice_preserve_other_preferences_and_note_direction(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id)
    peer["local_grants"]["grants"]["incoming_call_state"] = True
    peer["local_grants"]["grants"]["selected_notifications_readonly"] = False
    policy = sync.note_settings("phone_import")
    service.store.set_note_settings(peer_id, policy)
    service.set_personal_sync_mode(peer_id, False, True)
    grants = peer["local_grants"]["grants"]
    assert grants["personal_notes_sync"] and grants["personal_tasks_sync"]
    assert not grants["personal_deletions_sync"] and not peer["personal_sync"]["auto_wifi"]
    assert grants["incoming_call_state"] and not grants["selected_notifications_readonly"]
    assert service.store.note_settings(peer_id)["local"] == policy


def test_failed_mode_save_does_not_publish_or_keep_partial_permissions(tmp_path, monkeypatch):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    previous = copy.deepcopy(service.store.peer(peer_id))
    def fail():
        raise OSError("synthetic save failure")
    monkeypatch.setattr(service.store, "save_peers", fail)
    with pytest.raises(OSError):
        service.set_personal_sync_mode(peer_id, True, False)
    assert service.store.peer(peer_id) == previous
    assert service.store.pending(peer_id) == []
    with pytest.raises(ValueError):
        service.set_personal_sync_mode(peer_id, 1, False)
