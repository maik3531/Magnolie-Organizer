"""Actual phone control/scope adapters; the native book owner is synthetic here."""
import copy
import re
import sqlite3

import pytest
from test_shared_sync_transport import fixture, Channel, message
import magnolie_telefon as phone
import magnolie_content_scope as scope
import magnolie_shared_sync as shared


def actor_source_fixture(tmp_path, monkeypatch):
    service, peer, channel, _ = fixture(tmp_path, monkeypatch)
    original = phone.desktop_capabilities
    def capabilities(*args, **kwargs):
        value = original(*args, **kwargs)
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            value["items"][name]["versions"].append(12)
        return value
    monkeypatch.setattr(phone, "desktop_capabilities", capabilities)
    peer["capabilities"] = capabilities()
    peer["local_grants"]["grants"]["personal_tasks_sync"] = True
    peer["grants"]["grants"]["personal_tasks_sync"] = True
    service.enabled = True
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    service.note_controls[channel]["grants.update"] = copy.deepcopy(peer["grants"])
    local = service.store.shared_settings(peer["device_id"], peer["static_public"])
    remote = shared.merge(shared.create(peer["device_id"]), local, peer["device_id"], service.store.identity["device_id"])
    service._payload(peer, channel, message(remote))
    assert service.shared_settings_ready(peer["device_id"])
    assert service._content_scope_authorized(peer, channel)
    manifest = scope.create(["note-one"], ["task-one"])
    binding = (peer["device_id"], peer["static_public"], id(channel))
    session = scope.ScopeSession(binding)
    for part in scope.chunks(manifest):
        session.receive(binding, part)
    service.content_scope_sessions[channel] = session
    service._observe_note_control(peer, channel, "personal_sync.settings", {"format": 1, "own_device": True})
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    return service, peer, channel, fingerprint, manifest


def test_native_source_is_stable_and_has_no_wire_queue_or_gui_read_side_effects(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    before_peer = copy.deepcopy(peer)
    before_wire = copy.deepcopy(channel.sent)
    emitted = []
    service.callback = lambda *event: emitted.append(event)
    with sqlite3.connect(service.store.database_path) as db:
        before_outbox = db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    revision = service.current_actor_source(peer["device_id"], fingerprint, lambda: "a" * 64)
    assert revision and re.fullmatch(r"[0-9a-f]{64}", revision)
    assert service.current_actor_source(peer["device_id"], fingerprint, lambda: "a" * 64) == revision
    assert service.current_actor_source(peer["device_id"], fingerprint, lambda: "b" * 64) != revision
    snapshot = service.content_scope_sessions[channel].current_reference((peer["device_id"], peer["static_public"], id(channel)))
    snapshot["scope_hash"] = "0" * 64
    assert service.current_actor_source(peer["device_id"], fingerprint, lambda: "a" * 64) == revision
    assert peer == before_peer and channel.sent == before_wire
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == before_outbox
    assert emitted == []


@pytest.mark.parametrize("gate", ["disabled", "transport", "key", "capability", "local_capability", "fresh", "unconfirmed", "grant", "shared", "scope", "book", "invalid_book"])
def test_missing_native_authority_never_uses_a_cached_or_client_scope(tmp_path, monkeypatch, gate):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    book = lambda: "a" * 64
    if gate == "disabled": service.enabled = False
    elif gate == "transport": service.connection_transports.clear()
    elif gate == "key": fingerprint = "AAAA-BBBB-CCCC-DDDD"
    elif gate == "capability":
        peer["capabilities"]["items"]["personal_notes_sync"]["versions"].remove(12)
        service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    elif gate == "local_capability":
        original = phone.desktop_capabilities
        def without_actor(*args, **kwargs):
            value = original(*args, **kwargs)
            value["items"]["personal_tasks_sync"]["versions"].remove(12)
            return value
        monkeypatch.setattr(phone, "desktop_capabilities", without_actor)
    elif gate == "fresh": service.note_controls[channel].pop("grants.update")
    elif gate == "unconfirmed": peer["state"] = "paired_unverified"
    elif gate == "grant": peer["local_grants"]["grants"]["personal_tasks_sync"] = False
    elif gate == "shared": service.shared_sessions[channel]["received"] = None
    elif gate == "scope": service.content_scope_sessions[channel] = scope.ScopeSession((peer["device_id"], peer["static_public"], id(channel)))
    elif gate == "book": book = None
    elif gate == "invalid_book": book = lambda: "not-a-native-book-identity"
    assert service.current_actor_source(peer["device_id"], fingerprint, book) is None
    assert service.current_actor_completion_authority(peer["device_id"], fingerprint, book) is None


def test_connection_and_scope_replacements_and_book_races_invalidate_source(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    read = lambda callback: service.current_actor_source(peer["device_id"], fingerprint, callback)
    before = read(lambda: "a" * 64)
    replacement = Channel()
    service.connections[peer["device_id"]] = replacement
    service.note_controls[replacement] = copy.deepcopy(service.note_controls[channel])
    service.shared_sessions[replacement] = copy.deepcopy(service.shared_sessions[channel])
    binding = (peer["device_id"], peer["static_public"], id(replacement))
    session = scope.ScopeSession(binding)
    for part in scope.chunks(manifest): session.receive(binding, part)
    service.content_scope_sessions[replacement] = session
    service._observe_note_control(peer, replacement, "personal_sync.settings", {"format": 1, "own_device": True})
    replaced = read(lambda: "a" * 64)
    assert replaced and replaced != before
    updated = scope.create(["note-two"], ["task-one"], revision=2)
    for part in scope.chunks(updated): session.receive(binding, part)
    changed = read(lambda: "a" * 64)
    assert changed and changed != replaced
    values = iter(["a" * 64, "b" * 64])
    assert read(lambda: next(values)) is None
    partial = scope.create([f"note-{index:02}" for index in range(40)], ["task-one"], revision=3)
    session.receive(binding, scope.chunks(partial, size=32)[0])
    assert read(lambda: "a" * 64) is None, "An incomplete newer generation cannot reuse old membership"


def test_accepted_remote_feature_regrant_cannot_inherit_an_earlier_source(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, _ = actor_source_fixture(tmp_path, monkeypatch)
    def read(): return service.current_actor_source(peer["device_id"], fingerprint, lambda: "a" * 64)
    before = read()
    peer["grants"]["revision"] += 1
    peer["grants"]["grants"]["personal_notes_sync"] = False
    service._observe_note_control(peer, channel, "grants.update", peer["grants"])
    assert read() is None
    peer["grants"]["revision"] += 1
    peer["grants"]["grants"]["personal_notes_sync"] = True
    service._observe_note_control(peer, channel, "grants.update", peer["grants"])
    after = read()
    assert after and after != before
    service._observe_note_control(peer, channel, "grants.update", peer["grants"])
    assert read() == after


def test_host_native_book_provider_is_required_and_invalidated_with_its_owner(tmp_path, monkeypatch):
    from magnolie_personal_actor_store import NativeBookOwnerScope
    service, peer, channel, fingerprint, _ = actor_source_fixture(tmp_path, monkeypatch)
    assert service.current_actor_source(peer["device_id"], fingerprint) is None
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    service.native_actor_book_source = lambda: owner.current("actual-native-profile", True)
    first = service.current_actor_source(peer["device_id"], fingerprint)
    assert first
    owner.set_ready(False)
    assert service.current_actor_source(peer["device_id"], fingerprint) is None
    owner.set_ready(True)
    assert service.current_actor_source(peer["device_id"], fingerprint) != first


def test_native_registry_factory_uses_host_book_and_service_guard_for_raw_work(tmp_path, monkeypatch):
    from magnolie_personal_actor_store import NativeBookOwnerScope
    import magnolie_personal_actor as actor
    import uuid
    service, peer, channel, fingerprint, _ = actor_source_fixture(tmp_path, monkeypatch)
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    service.native_actor_book_source = lambda: owner.current("actual-native-profile", True)
    revision = service.current_actor_source(peer["device_id"], fingerprint)
    registry = service.personal_actor_registry()
    assert registry is service.personal_actor_registry() and registry.source_guard is service.lock
    handle = registry.create(peer["device_id"], fingerprint, revision)
    now = phone.now_ms()
    wire = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()), "kind": actor.ACK_KIND,
        "created_ms": now, "expires_ms": now + 60000, "body": actor.ack(handle.actor_id, str(uuid.uuid4()))}
    assert registry.put(handle, wire)
    assert registry.read(handle, wire["message_id"]) == wire
    owner.set_ready(False)
    with pytest.raises(PermissionError): registry.read(handle, wire["message_id"])
    assert registry.cancel(handle)["phase"] == "cancelled"


def test_completion_authority_stays_distinct_from_old_scope_data_rights(tmp_path, monkeypatch):
    import uuid
    import magnolie_personal_actor as actor
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    service.native_actor_book_source = lambda: 'a'*64
    source = service.current_actor_source(peer['device_id'], fingerprint)
    authority = service.current_actor_completion_authority(peer['device_id'], fingerprint)
    assert source and authority and source != authority
    registry = service.personal_actor_registry()
    handle = registry.create(peer['device_id'], fingerprint, source)
    now = phone.now_ms()
    wire = {'type':'message', 'v':1, 'message_id':str(uuid.uuid4()), 'kind':actor.ACK_KIND,
        'created_ms':now, 'expires_ms':now+60000, 'body':actor.ack(handle.actor_id, str(uuid.uuid4()))}
    registry.put(handle, wire)
    session = service.content_scope_sessions[channel]
    binding = (peer['device_id'], peer['static_public'], id(channel))
    updated = scope.advance(manifest, ['note-one','restored-note'], ['task-one'])
    for part in scope.chunks(updated): session.receive(binding, part)
    assert service.current_actor_source(peer['device_id'], fingerprint) != source
    assert service.current_actor_completion_authority(peer['device_id'], fingerprint) == authority
    with pytest.raises(PermissionError): registry.read(handle, wire['message_id'])
    with pytest.raises(PermissionError): registry.create(peer['device_id'], fingerprint, authority)
    incomplete = scope.advance(updated, [f'note-{i:02}' for i in range(40)], ['task-one'])
    parts = scope.chunks(incomplete, size=32)
    session.receive(binding, parts[0])
    assert service.current_actor_source(peer['device_id'], fingerprint) is None
    assert service.current_actor_completion_authority(peer['device_id'], fingerprint) is None
    for part in parts[1:]: session.receive(binding, part)
    assert service.current_actor_completion_authority(peer['device_id'], fingerprint) == authority
    peer['local_grants']['grants']['personal_tasks_sync'] = False
    assert service.current_actor_completion_authority(peer['device_id'], fingerprint) is None
