import copy
from pathlib import Path
import sqlite3
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_content_scope as scope
import magnolie_telefon as phone
from test_shared_sync_storage import fixture


def prepare(tmp_path):
    service, peer, public = fixture(tmp_path)
    service.store.change_shared_setting(peer, public, "content_mode", "phone_scope")
    request = {"format": 3, "run_id": str(uuid.uuid4()), "trigger": "manual", "modules": ["notes", "tasks"]}
    reference = scope.reference(scope.create(["mobile-note"], ["mobile-task"]))
    expires = phone.now_ms() + 60000
    return service, peer, public, request, reference, expires


def test_scoped_run_and_exact_reference_persist_together_and_replay_is_idempotent(tmp_path):
    service, peer, public, request, reference, expires = prepare(tmp_path)
    service.store.remember_scoped_run(peer, public, request, reference, expires)
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Synthetic")
    assert reopened.personal_run(peer, request["run_id"]) == request
    assert reopened.scoped_run_reference(peer, public, request["run_id"]) == reference
    reopened.remember_scoped_run(peer, public, request, reference, expires)
    with pytest.raises(ValueError):
        reopened.remember_scoped_run(peer, public, request, reference, expires + 1)
    changed = copy.deepcopy(reference); changed["scope_revision"] += 1
    with pytest.raises(ValueError):
        reopened.remember_scoped_run(peer, public, request, changed, expires)


def test_content_choice_invalidates_run_but_separate_time_choice_does_not(tmp_path):
    service, peer, public, request, reference, expires = prepare(tmp_path)
    service.store.remember_scoped_run(peer, public, request, reference, expires)
    service.store.change_shared_setting(peer, public, "time_mode", "two_way")
    assert service.store.scoped_run_reference(peer, public, request["run_id"]) == reference
    service.store.change_shared_setting(peer, public, "content_mode", "two_way")
    with pytest.raises(PermissionError):
        service.store.scoped_run_reference(peer, public, request["run_id"])
    service.store.change_shared_setting(peer, public, "content_mode", "phone_scope")
    with pytest.raises(PermissionError):
        service.store.scoped_run_reference(peer, public, request["run_id"])


def test_changed_key_expiry_or_legacy_collision_cannot_adopt_scoped_run(tmp_path, monkeypatch):
    service, peer, public, request, reference, expires = prepare(tmp_path)
    service.store.remember_scoped_run(peer, public, request, reference, expires)
    with pytest.raises(PermissionError):
        service.store.scoped_run_reference(peer, phone.b64(b"x" * 32), request["run_id"])
    legacy = dict(request, run_id=str(uuid.uuid4()))
    service.store.remember_personal_run(peer, legacy, expires)
    with pytest.raises(ValueError):
        service.store.remember_scoped_run(peer, public, legacy, reference, expires)
    monkeypatch.setattr(phone, "now_ms", lambda: expires + 1)
    with pytest.raises(PermissionError):
        service.store.scoped_run_reference(peer, public, request["run_id"])


def test_failed_second_seal_rolls_back_both_run_and_scope_metadata(tmp_path, monkeypatch):
    service, peer, public, request, reference, expires = prepare(tmp_path)
    original = service.store._encrypt
    def fail_scope(data, kind, primary):
        if kind == "personal_scope":
            raise OSError("synthetic scope seal failure")
        return original(data, kind, primary)
    monkeypatch.setattr(service.store, "_encrypt", fail_scope)
    with pytest.raises(OSError):
        service.store.remember_scoped_run(peer, public, request, reference, expires)
    assert service.store.personal_run(peer, request["run_id"]) == {}
    assert service.store.scoped_run_reference(peer, public, request["run_id"]) is None


def test_revocation_and_unpair_remove_scoped_run_bindings(tmp_path):
    service, peer, public, request, reference, expires = prepare(tmp_path)
    service.store.remember_scoped_run(peer, public, request, reference, expires)
    service.store.purge_personal_modules(peer, {"notes"})
    assert service.store.scoped_run_reference(peer, public, request["run_id"]) is None
    service.store.remember_scoped_run(peer, public, dict(request, run_id=str(uuid.uuid4())), reference, expires)
    service.remove(peer)
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT count(*) FROM meta WHERE key LIKE 'personal_scope:%'").fetchone()[0] == 0
