"""Actual sealed raw inbox/owner leases; no GUI adoption or transport receipts."""
import copy
import json
import sqlite3
import pytest
from test_mcp_phone import owned_service
import magnolie_personal_actor as actor
import magnolie_personal_actor_store as registry
import magnolie_telefon as phone

RUN = "11111111-1111-4111-8111-111111111111"
MESSAGE = "22222222-2222-4222-8222-222222222222"


def fixture(tmp_path):
    service, peer, events = owned_service(tmp_path)
    source = {"revision": "a" * 64, "calls": 0, "fail_at": None}
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    clock = {"now": 1700000000000, "monotonic": 1000000}
    def current(peer_id, expected):
        source["calls"] += 1
        if source["fail_at"] is not None and source["calls"] >= source["fail_at"]:
            return None
        return source["revision"] if (peer_id, expected) == (peer["device_id"], fingerprint) else None
    store = registry.ActorStore(service.store, current, clock=lambda: clock["now"], monotonic_clock=lambda: clock["monotonic"])
    handle = store.create(peer["device_id"], fingerprint, source["revision"], run_id=RUN)
    request = {"format": 3, "run_id": RUN, "trigger": "manual", "modules": ["notes", "tasks"]}
    original = {"type": "message", "v": 1, "message_id": MESSAGE, "kind": "personal_sync.request", "created_ms": clock["now"],
        "expires_ms": clock["now"] + 60000, "body": request}
    wire = actor.wire_message(original, RUN)
    return service, peer, events, source, clock, store, handle, wire, current


def test_raw_actor_wire_and_binding_are_sealed_and_reopen_without_gui_replay(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    assert handle.owner_token not in repr(handle)
    before = store.status(handle)
    assert store.put(handle, wire) is True and store.put(handle, wire) is False
    assert store.status(handle)["revision"] != before["revision"]
    with sqlite3.connect(service.store.database_path) as db:
        protected = db.execute("SELECT payload FROM personal_actor_context WHERE actor_id=?", (RUN,)).fetchone()[0]
        assert handle.owner_token.encode() not in protected
        payload = db.execute("SELECT payload FROM personal_actor_wire WHERE actor_id=? AND message_id=?", (RUN, MESSAGE)).fetchone()[0]
    assert json.loads(service.store._decrypt(payload, "personal_actor_wire", RUN + ":" + MESSAGE)) == wire
    reopened = registry.ActorStore(service.store, current, epoch=store.epoch, clock=lambda: clock["now"], monotonic_clock=lambda: clock["monotonic"])
    assert reopened.read(handle, MESSAGE) == wire
    service.replay_personal_sync()
    assert not events and service.server is None
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0


def test_wrong_owner_or_new_native_epoch_cannot_read_or_cancel_old_context(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    wrong = registry.ActorHandle(handle.actor_id, "0" * 64)
    for operation in (lambda: store.read(wrong, MESSAGE), lambda: store.cancel(wrong), lambda: store.status(wrong)):
        with pytest.raises(PermissionError, match="actor_not_found"):
            operation()
    restarted = registry.ActorStore(service.store, current, clock=lambda: clock["now"], monotonic_clock=lambda: clock["monotonic"])
    with pytest.raises(PermissionError, match="actor_not_found"):
        restarted.read(handle, MESSAGE)
    assert store.read(handle, MESSAGE) == wire


def test_source_revocation_blocks_raw_getter_but_owner_can_retire_without_source(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    source["revision"] = "b" * 64
    with pytest.raises(PermissionError, match="actor_source_changed"):
        store.read(handle, MESSAGE)
    assert store.cancel(handle)["phase"] == "cancelled"
    with pytest.raises(PermissionError, match="actor_inactive"):
        store.read(handle, MESSAGE)
    assert not events


def test_expiry_and_duplicate_conflict_do_not_expose_or_replace_packets(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    changed = copy.deepcopy(wire); changed["body"]["body"]["modules"] = ["notes"]
    with pytest.raises(ValueError, match="actor_frame_conflict"):
        store.put(handle, changed)
    assert store.read(handle, MESSAGE) == wire
    clock["now"] += registry.LIFETIME_MS + 1
    with pytest.raises(PermissionError, match="actor_inactive"):
        store.read(handle, MESSAGE)
    assert store.cancel(handle)["phase"] == "cancelled"


def test_source_changes_during_put_roll_back_binding_and_raw_packet(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    source["fail_at"] = source["calls"] + 2
    with pytest.raises(PermissionError, match="actor_source_changed"):
        store.put(handle, wire)
    assert store.status(handle)["packets"] == 0 and store.status(handle)["phase"] == "registered"


@pytest.mark.parametrize("clock_name", ["now", "monotonic"])
def test_native_reaper_reclaims_expired_private_context_and_preserves_gui_queue(tmp_path, clock_name):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    private = actor.storage_peer(handle.actor_id)
    service.store.remember_personal_run(private, wire["body"]["body"])
    outgoing = service.store.queue(peer["device_id"], "personal_sync.request", wire["body"]["body"], 60000, actor_run_id=handle.actor_id)
    ordinary = service.store.queue(peer["device_id"], "personal_sync.settings", {"format": 1, "own_device": True}, 60000)
    clock[clock_name] += registry.LIFETIME_MS + 1
    assert store.reap() == 1
    with pytest.raises(PermissionError, match="actor_not_found"): store.status(handle)
    assert service.store.personal_run(private, handle.actor_id) == {}
    assert service.store.outbox_message(peer["device_id"], outgoing["message_id"]) is None
    assert service.store.outbox_message(peer["device_id"], ordinary["message_id"]) == ordinary
    assert not events


def test_native_reaper_keeps_other_gui_owners_and_discards_previous_process_epoch(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.source_owned = lambda actor_id: actor_id == handle.actor_id
    other = registry.ActorStore(service.store, lambda *_: "b" * 64, epoch=store.epoch,
        clock=lambda: clock["now"], monotonic_clock=lambda: clock["monotonic"], source_owned=lambda actor_id: actor_id != handle.actor_id)
    second = other.create(peer["device_id"], phone.fingerprint(phone.unb64(peer["static_public"], 32)), "b" * 64)
    assert store.reap() == 0 and other.reap() == 0
    store.require_current(handle); other.require_current(second)
    restarted = registry.ActorStore(service.store, current, clock=lambda: clock["now"], monotonic_clock=lambda: clock["monotonic"])
    assert restarted.reap() == 2
    with pytest.raises(PermissionError): restarted.status(handle)
    with pytest.raises(PermissionError): other.require_current(second)


def test_reaper_cleanup_failure_leaves_irreversibly_retired_context_for_retry(tmp_path, monkeypatch):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    purge = service.store.purge_personal
    monkeypatch.setattr(service.store, "purge_personal", lambda _: (_ for _ in ()).throw(OSError("owned cleanup failure")))
    source["revision"] = "b" * 64
    with pytest.raises(OSError, match="owned cleanup failure"): store.reap()
    source["revision"] = "a" * 64
    assert store.status(handle)["phase"] == "cancelled"
    with pytest.raises(PermissionError, match="actor_inactive"): store.read(handle, MESSAGE)
    monkeypatch.setattr(service.store, "purge_personal", purge)
    assert store.reap() == 1 and not events
    monkeypatch.setattr(service.store, "purge_personal", lambda _: (_ for _ in ()).throw(AssertionError("completed cleanup repeated")))
    assert store.reap() == 0


def test_restored_precleanup_binding_cannot_inherit_a_volatile_cleanup_receipt(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    private = actor.storage_peer(handle.actor_id)
    key = "personal_run:%s:%s" % (private, handle.actor_id)
    service.store.remember_personal_run(private, wire["body"]["body"])
    with sqlite3.connect(service.store.database_path) as db:
        context = db.execute("SELECT actor_id,expires_ms,payload FROM personal_actor_context").fetchone()
        run = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]
    source["revision"] = "b" * 64
    assert store.reap() == 1 and store.reap() == 0
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("INSERT OR REPLACE INTO personal_actor_context VALUES(?,?,?)", context)
        db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, run))
    assert store.reap() == 1
    assert service.store.personal_run(private, handle.actor_id) == {}
    assert store.status(handle)["phase"] == "cancelled" and not events


def test_plaintext_binding_metadata_cannot_extend_a_protected_lease(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("UPDATE personal_actor_context SET expires_ms=expires_ms+60000 WHERE actor_id=?", (RUN,))
    with pytest.raises(ValueError, match="protected actor binding"):
        store.status(handle)


def test_active_context_capacity_is_bounded_without_evicting_live_owners(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    handles = [handle]
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    for _ in range(registry.MAX_ACTIVE - 1):
        handles.append(store.create(peer["device_id"], fingerprint, source["revision"]))
    with pytest.raises(RuntimeError, match="actor_capacity"):
        store.create(peer["device_id"], fingerprint, source["revision"])
    assert all(store.status(value)["phase"] == "registered" for value in handles)


def test_wall_clock_rollback_cannot_extend_native_owner_lease(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    clock["now"] -= 86400000
    clock["monotonic"] += registry.LIFETIME_MS + 1
    with pytest.raises(PermissionError, match="actor_inactive"):
        store.read(handle, MESSAGE)


def test_revocation_during_raw_read_is_rechecked_before_returning_data(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    source["fail_at"] = source["calls"] + 2
    with pytest.raises(PermissionError, match="actor_source_changed"):
        store.read(handle, MESSAGE)


def test_storage_quota_uses_actual_sealed_bytes_not_plaintext_size_hints(tmp_path, monkeypatch):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    with sqlite3.connect(service.store.database_path) as db:
        sealed_size = db.execute("SELECT length(payload) FROM personal_actor_wire WHERE actor_id=?", (RUN,)).fetchone()[0]
        db.execute("UPDATE personal_actor_wire SET byte_count=0 WHERE actor_id=?", (RUN,))
    monkeypatch.setattr(registry, "MAX_ACTOR_BYTES", sealed_size)
    second = copy.deepcopy(wire); second["message_id"] = "33333333-3333-4333-8333-333333333333"
    assert len(registry.personal.canonical(second)) <= sealed_size
    with pytest.raises(RuntimeError, match="actor_capacity"):
        store.put(handle, second)
    assert store.status(handle)["packets"] == 1
    with pytest.raises(ValueError, match="protected actor packet"):
        store.read(handle, MESSAGE)


def test_actor_raw_storage_does_not_extend_inner_request_or_ack_lifetimes(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    excessive = copy.deepcopy(wire); excessive["expires_ms"] = excessive["created_ms"] + 3600001
    with pytest.raises(ValueError, match="lifetime"):
        store.put(handle, excessive)
    marked_ack = {**wire, "kind": actor.ACK_KIND, "body": actor.ack(RUN, MESSAGE), "expires_ms": wire["created_ms"] + 60001}
    with pytest.raises(ValueError, match="lifetime"):
        store.put(handle, marked_ack)
    assert store.status(handle)["packets"] == 0


def test_another_valid_actor_handle_cannot_read_a_different_context_packet(tmp_path):
    service, peer, events, source, clock, store, handle, wire, current = fixture(tmp_path)
    store.put(handle, wire)
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    other = store.create(peer["device_id"], fingerprint, source["revision"])
    with pytest.raises(KeyError, match="actor_packet_not_found"):
        store.read(other, MESSAGE)
    assert store.read(handle, MESSAGE) == wire
