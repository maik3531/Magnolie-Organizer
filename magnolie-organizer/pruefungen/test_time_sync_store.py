"""Encrypted v7 staging: actual phone store, synthetic peer, no network."""
import copy
import sqlite3
from uuid import uuid4
import pytest
from test_personal_sync import _personal_service
from test_time_sync import settings, request, record
import magnolie_telefon as phone
import magnolie_time_sync as time


def time_store(tmp_path):
    service, peer = _personal_service(tmp_path, lambda *_: None)
    local, remote = settings(), settings()
    service.store.set_time_settings(peer, local)
    service.store.set_time_settings(peer, remote, remote=True)
    now = phone.now_ms()
    message = dict(type="message", v=1, message_id=str(uuid4()), kind=time.BATCH,
        created_ms=now, expires_ms=now + 60000, body=dict(request(local, remote), entries=[record()]))
    return service.store, peer, message


def test_receipt_waits_for_exact_commit_and_survives_restart(tmp_path):
    store, peer, message = time_store(tmp_path)
    message["body"]["entries"][0]["note"] = "Synthetic confidential record"
    staged = store.stage_time_batch(peer, message)
    assert store.dedupe_result(peer, message["message_id"]) is None
    assert store.stage_time_batch(peer, message) == staged
    restored = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    assert restored.stage_time_batch(peer, message) == staged
    assert not restored.commit_time_batch(peer, message["message_id"], "wrong", lambda _: True)
    assert not restored.commit_time_batch(peer, message["message_id"], staged["commit_token"], lambda _: False)
    assert restored.dedupe_result(peer, message["message_id"]) is None
    assert restored.commit_time_batch(peer, message["message_id"], staged["commit_token"], lambda value: value == message)
    assert restored.dedupe_result(peer, message["message_id"]) == ("accepted", "none")
    assert not restored.commit_time_batch(peer, message["message_id"], staged["commit_token"], lambda _: True)
    assert all(b"Synthetic confidential record" not in path.read_bytes() for path in (tmp_path / "phone").iterdir() if path.is_file())


def test_revocation_purges_pending_records_and_invalidates_delayed_commit(tmp_path):
    store, peer, message = time_store(tmp_path)
    staged = store.stage_time_batch(peer, message)
    store.set_time_settings(peer, settings(False, 2), remote=True)
    assert not store.commit_time_batch(peer, message["message_id"], staged["commit_token"], lambda _: True)
    assert store.dedupe_result(peer, message["message_id"]) is None
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM time_batch").fetchone()[0] == 0
    restored = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    assert restored.time_settings(peer)["remote"]["enabled"] is False


def test_changed_message_identity_and_peer_key_cannot_reuse_a_token(tmp_path):
    store, peer, message = time_store(tmp_path)
    staged = store.stage_time_batch(peer, message)
    changed = copy.deepcopy(message)
    changed["body"]["entries"][0]["note"] = "Different body"
    with pytest.raises(ValueError): store.stage_time_batch(peer, changed)
    store.sole_peer(peer)["static_public"] = phone.b64(b"q" * 32)
    assert not store.commit_time_batch(peer, message["message_id"], staged["commit_token"], lambda _: True)
    with pytest.raises(ValueError): store.stage_time_batch(peer, message)


def test_failed_policy_save_blocks_staging_until_persistence_recovers(tmp_path, monkeypatch):
    store, peer, message = time_store(tmp_path)
    save = store.save_peers
    def fail(): raise OSError("synthetic write failure")
    monkeypatch.setattr(store, "save_peers", fail)
    disabled = settings(False, 2)
    with pytest.raises(OSError): store.set_time_settings(peer, disabled)
    with pytest.raises(RuntimeError): store.stage_time_batch(peer, message)
    monkeypatch.setattr(store, "save_peers", save)
    store.set_time_settings(peer, disabled)
    assert store.time_settings(peer)["local"] == disabled


def test_expiry_is_checked_again_before_commit(tmp_path, monkeypatch):
    store, peer, message = time_store(tmp_path)
    staged = store.stage_time_batch(peer, message)
    monkeypatch.setattr(phone, "now_ms", lambda: message["expires_ms"])
    assert not store.commit_time_batch(peer, message["message_id"], staged["commit_token"], lambda _: True)
    store.cleanup()
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM time_batch").fetchone()[0] == 0
