import base64
import copy
import json
import socket
import sys
import uuid
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_content_scope as scope
import magnolie_personal_sync as personal
import magnolie_shared_sync as shared
import magnolie_telefon as phone
from test_shared_sync_transport import fixture as shared_fixture, Channel, message


def fixture(tmp_path, monkeypatch, *, peer_id=None):
    service, peer, channel, body = shared_fixture(tmp_path, monkeypatch, peer_id=peer_id)
    original = phone.desktop_capabilities
    def capabilities(*args, **kwargs):
        result = original(*args, **kwargs)
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            result["items"][name]["versions"] = sorted(set(result["items"][name]["versions"] + [scope.VERSION]))
        return result
    monkeypatch.setattr(phone, "desktop_capabilities", capabilities)
    peer["capabilities"] = capabilities()
    peer["local_grants"]["grants"]["personal_tasks_sync"] = True
    peer["grants"]["grants"]["personal_tasks_sync"] = True
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    service.note_controls[channel]["grants.update"] = copy.deepcopy(peer["grants"])
    remote = shared.merge(shared.create(peer["device_id"]), body, peer["device_id"], service.store.identity["device_id"])
    service._payload(peer, channel, message(remote))
    assert service.shared_settings_ready(peer["device_id"])
    return service, peer, channel


def frame(part):
    value = message(part); value["kind"] = scope.KIND
    return value


@pytest.mark.parametrize("transport, trigger, accepted", [
    ("wifi", "auto_wifi", True),
    ("bluetooth", "auto_wifi", False),
    ("bluetooth", "manual", True),
])
def test_scoped_request_checks_transport_before_persisting(tmp_path, monkeypatch, transport, trigger, accepted):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    peer_id = peer["device_id"]
    service.connection_transports[peer_id] = transport
    mode = "wifi" if trigger == "auto_wifi" else "manual"
    agreed = service.store.change_shared_setting(peer_id, peer["static_public"], "auto_mode", mode)
    remote = shared.merge(shared.create(peer_id), agreed, peer_id, service.store.identity["device_id"])
    service._payload(peer, channel, message(remote))
    assert service.shared_settings_ready(peer_id)
    manifest = scope.create(["phone-note"], ["phone-task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    assert channel.sent[-1]["status"] == "accepted"

    run = str(uuid.uuid4())
    request = {"format": 3, "run_id": run, "trigger": trigger, "modules": ["notes", "tasks"]}
    packet = dict(message(scope.wrap("personal_sync.request", request, manifest)), kind=scope.DATA_KIND)
    service._payload(peer, channel, packet)
    ack = next(item for item in reversed(channel.sent) if item.get("message_id") == packet["message_id"])
    assert (ack["status"] == "accepted") is accepted, ack
    assert service.store.personal_run(peer_id, run) == (request if accepted else {})
    if not accepted:
        assert ack["error"] == "invalid_schema"
        assert service.store.scoped_run_reference(peer_id, peer["static_public"], run) is None
        assert service.store.active_auto_run(peer_id) == ""


def connection_automation_fixture(tmp_path, monkeypatch, transport, gate=None, *, peer_id=None):
    # Inbound fixtures represent the elected phone; GUI start fixtures pass
    # their own peer ID to exercise the desktop's election separately.
    if peer_id is None:
        peer_id = "00000000-0000-4000-8000-000000000000"
    service, peer, channel = fixture(tmp_path, monkeypatch, peer_id=peer_id)
    channel.sid = uuid.uuid4().bytes
    channel.reader_nonce = uuid.uuid4().bytes + uuid.uuid4().bytes
    capabilities = phone.desktop_capabilities

    def marked_capabilities(*args, **kwargs):
        body = capabilities(*args, **kwargs)
        for module in ("personal_notes_sync", "personal_tasks_sync"):
            versions = body["items"][module]["versions"]
            body["items"][module]["versions"] = sorted(set(versions + [personal.AUTO_CONNECTION_VERSION]))
        return body

    if gate != "local_marker":
        monkeypatch.setattr(phone, "desktop_capabilities", marked_capabilities)
    if gate != "remote_marker":
        peer["capabilities"] = marked_capabilities()
        service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
        service.store.save_peers()
    peer_id, public = peer["device_id"], peer["static_public"]
    service.connection_transports[peer_id] = "wifi"
    mode = "wifi" if gate == "mode" else "connection"
    agreed = service.store.change_shared_setting(peer_id, public, "auto_mode", mode)
    remote = shared.merge(shared.create(peer_id), agreed, peer_id, service.store.identity["device_id"])
    service._payload(peer, channel, message(remote))
    assert service.shared_settings_ready(peer_id)
    manifest = scope.create(["phone-note"], ["phone-task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    assert channel.sent[-1]["status"] == "accepted"

    service.connection_transports[peer_id] = transport
    if gate == "settings_echo":
        service.store.change_shared_setting(peer_id, public, "auto_mode", "manual")
        service.store.change_shared_setting(peer_id, public, "auto_mode", "connection")
        assert not service.shared_settings_ready(peer_id)
    elif gate == "grant":
        peer["local_grants"]["grants"]["personal_tasks_sync"] = False
        service.store.save_peers()
    elif gate == "reader":
        service.connections[peer_id] = Channel()
    channel.last_capabilities = phone.desktop_capabilities(service.store.next_revision("capabilities.update"))
    return service, peer, channel, remote, manifest


def reconnect_automation_fixture(service, peer, original, remote, manifest):
    replacement = Channel()
    # Simulate an unchanged advertised session id, but a new native reader.
    replacement.sid = original.sid
    replacement.reader_nonce = uuid.uuid4().bytes + uuid.uuid4().bytes
    replacement.last_capabilities = copy.deepcopy(original.last_capabilities)
    service.connections[peer["device_id"]] = replacement
    service.note_controls[replacement] = copy.deepcopy(service.note_controls[original])
    service._payload(peer, replacement, message(remote))
    assert service.shared_settings_ready(peer["device_id"])
    service._payload(peer, replacement, frame(scope.chunks(manifest)[0]))
    assert replacement.sent[-1]["status"] == "accepted"
    return replacement


def test_grouped_connection_reply_never_uses_ordinary_outbox_policy(tmp_path, monkeypatch):
    service, peer, channel, _, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    peer_id = peer["device_id"]
    run = str(uuid.uuid4())
    request = {"format": 3, "run_id": run, "trigger": personal.AUTO_CONNECTION_TRIGGER, "modules": ["notes", "tasks"]}
    service._payload(peer, channel, dict(message(scope.wrap("personal_sync.request", request, manifest)), kind=scope.DATA_KIND))
    assert channel.sent[-1]["status"] == "accepted"
    reply = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
             "reply": True, "records": [], "records_hash": personal.records_hash([])}
    before_frames = copy.deepcopy(channel.sent)
    with pytest.raises(PermissionError, match="requires the protected batch reply"):
        service.send_personal_sync_run(peer_id, request, [reply], [], request["trigger"])
    assert channel.sent == before_frames
    with sqlite3.connect(service.store.database_path) as db:
        assert not db.execute("SELECT 1 FROM outbox WHERE peer_id=? AND kind='personal_sync.batch'", (peer_id,)).fetchone()


def test_grouped_connection_start_waits_for_original_request_ack(tmp_path, monkeypatch):
    service, peer, reader, remote, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    peer_id = peer["device_id"]
    run_id = str(uuid.uuid4())
    request = {"format": 3, "run_id": run_id, "trigger": personal.AUTO_CONNECTION_TRIGGER,
               "modules": ["notes", "tasks"]}
    batch = {"format": 3, "run_id": run_id, "batch_id": str(uuid.uuid4()), "sequence": 0,
             "last": True, "reply": False, "records": [], "records_hash": personal.records_hash([])}

    def frames(channel):
        return [item for item in channel.sent if item.get("kind") == scope.DATA_KIND]

    reader.sent.clear()
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("CREATE TRIGGER connection_start_failure BEFORE INSERT ON outbox "
                   "WHEN NEW.kind='personal_sync.batch' AND NEW.transport_policy GLOB 'connection_only:*' "
                   "BEGIN SELECT RAISE(ABORT, 'synthetic initial batch failure'); END")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="synthetic initial batch failure"):
            service.send_personal_sync_run(peer_id, request, [batch], [], request["trigger"])
        assert not frames(reader)
        assert not service.store.personal_run(peer_id, run_id)
        assert service.store.scoped_run_reference(peer_id, peer["static_public"], run_id) is None
        with sqlite3.connect(service.store.database_path) as db:
            assert not db.execute("SELECT 1 FROM outbox WHERE transport_policy GLOB 'connection_only:*'").fetchone()
    finally:
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("DROP TRIGGER connection_start_failure")
    service.send_personal_sync_run(peer_id, request, [batch], [], request["trigger"])
    assert service.store.personal_run(peer_id, run_id) == request
    assert service.store.run_policy(peer_id, run_id) == "connection_only"
    start, = frames(reader)
    assert start["body"] == scope.wrap("personal_sync.request", request, manifest)
    assert service.store.active_auto_run(peer_id) == ""

    def ack(status, error):
        return {"type": "ack", "message_id": start["message_id"], "status": status, "error": error}

    service._payload(peer, reader, ack("rejected", "temporary_failure"))
    assert frames(reader) == [start]
    replacement = reconnect_automation_fixture(service, peer, reader, remote, manifest)
    with pytest.raises(ValueError, match="violates current connection policy"):
        service._payload(peer, replacement, ack("accepted", "none"))
    assert not frames(replacement)
    assert service.store.outbox_message(peer_id, start["message_id"]) is not None

    service.connections[peer_id] = reader
    service._payload(peer, reader, ack("accepted", "none"))
    sent_request, sent_batch = frames(reader)
    assert sent_request == start
    assert sent_batch["body"] == scope.wrap("personal_sync.batch", batch, manifest)


@pytest.mark.parametrize("change", ["reader", "restore", "stale_save", "manifest", "advertisement", "other_initiator", "none"])
def test_gui_connection_start_rechecks_original_reader_and_saved_book(tmp_path, monkeypatch, change):
    peer_id = ("00000000-0000-4000-8000-000000000000" if change == "other_initiator"
               else "ffffffff-ffff-4fff-bfff-ffffffffffff")
    service, peer, reader, remote, manifest = connection_automation_fixture(tmp_path, monkeypatch, "wifi", peer_id=peer_id)
    peer_id = peer["device_id"]
    source = "a" * 64
    before = {"book_source": source, "sequence": 1, "sha256": "b" * 64}
    current = dict(before)
    service.native_actor_book_source = lambda: current["book_source"]
    service.native_actor_saved_book = lambda: dict(current)
    fingerprint = phone.fingerprint(phone.unb64(peer["static_public"], 32))
    advertised = reader.last_capabilities
    reader.last_capabilities = None
    with pytest.raises(PermissionError, match="not been advertised"):
        service.prepare_gui_connection_start(peer_id, fingerprint)
    reader.last_capabilities = advertised
    if change == "other_initiator":
        assert not service.gui_connection_start_ready(peer_id)
        with pytest.raises(PermissionError, match="elected initiator"):
            service.prepare_gui_connection_start(peer_id, fingerprint)
        return
    plan = service.prepare_gui_connection_start(peer_id, fingerprint)
    assert plan["scope"] == manifest
    assert plan["transport"] == "wifi"
    assert service.prepare_gui_connection_start(peer_id, fingerprint) == plan
    request = {"format": plan["format"], "run_id": plan["run_id"], "trigger": personal.AUTO_CONNECTION_TRIGGER,
               "modules": ["notes", "tasks"]}
    batch = {"format": plan["format"], "run_id": plan["run_id"], "batch_id": str(uuid.uuid4()), "sequence": 0,
             "last": True, "reply": False, "records": [], "records_hash": personal.records_hash([])}
    current.update(sequence=2, sha256="c" * 64)
    if change == "reader":
        reconnect_automation_fixture(service, peer, reader, remote, manifest)
    elif change == "restore":
        current["book_source"] = "d" * 64
    elif change == "manifest":
        updated = scope.create(["phone-note", "new-note"], ["phone-task"],
                               revision=manifest["revision"] + 1)
        service._payload(peer, reader, frame(scope.chunks(updated)[0]))
        assert reader.sent[-1]["status"] == "accepted"
    elif change == "advertisement":
        reader.last_capabilities["revision"] += 1
    claimed = before["sha256"] if change == "stale_save" else current["sha256"]
    reader.sent.clear()
    if change == "none":
        service.start_gui_connection_run(peer_id, plan["token"], claimed, request, [batch], [])
        assert reader.sent[-1]["body"] == scope.wrap("personal_sync.request", request, manifest)
        with pytest.raises(PermissionError):
            service.start_gui_connection_run(peer_id, plan["token"], claimed, request, [batch], [])
    else:
        with pytest.raises(PermissionError):
            service.start_gui_connection_run(peer_id, plan["token"], claimed, request, [batch], [])
        assert not reader.sent
        assert service.store.personal_run(peer_id, request["run_id"]) == {}


def test_expired_connection_run_never_creates_an_unbound_report_or_clears_legacy_reservation(tmp_path, monkeypatch):
    service, peer, channel, _, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    peer_id = peer["device_id"]
    run_id = str(uuid.uuid4())
    request = {"format": 3, "run_id": run_id, "trigger": personal.AUTO_CONNECTION_TRIGGER, "modules": ["notes", "tasks"]}
    payload = dict(message(scope.wrap("personal_sync.request", request, manifest)), kind=scope.DATA_KIND)
    service._payload(peer, channel, payload)
    assert channel.sent[-1]["status"] == "accepted"
    wlan_run = str(uuid.uuid4())
    service.store.set_active_auto_run(peer_id, wlan_run)
    monkeypatch.setattr(phone, "now_ms", lambda: payload["expires_ms"] + 1)

    service.store.cleanup()
    with sqlite3.connect(service.store.database_path) as db:
        assert not db.execute("SELECT 1 FROM outbox WHERE peer_id=? AND kind='personal_sync.report'", (peer_id,)).fetchone()
        assert not db.execute("SELECT 1 FROM meta WHERE key=?", (f"personal_scope:{peer_id}:{run_id}",)).fetchone()
    assert service.store.active_auto_run(peer_id) == wlan_run
    assert not service.store.personal_run(peer_id, run_id)


@pytest.mark.parametrize("transport, gate", [
    ("wifi", None),
    ("bluetooth", None),
    ("wifi", "local_marker"),
    ("bluetooth", "remote_marker"),
    ("bluetooth", "mode"),
    ("bluetooth", "settings_echo"),
    ("bluetooth", "grant"),
    ("bluetooth", "reader"),
    ("bluetooth", "higher_uuid"),
    ("bluetooth", "equal_uuid"),
    ("unavailable", "transport"),
])
def test_connection_automation_requires_current_negotiated_authority(tmp_path, monkeypatch, transport, gate):
    higher_peer = "ffffffff-ffff-4fff-bfff-ffffffffffff" if gate == "higher_uuid" else None
    service, peer, channel, remote, manifest = connection_automation_fixture(
        tmp_path, monkeypatch, transport, gate, peer_id=higher_peer)
    peer_id, public = peer["device_id"], peer["static_public"]
    if gate == "equal_uuid":
        monkeypatch.setitem(service.store.identity, "device_id", peer_id)
    run = str(uuid.uuid4())
    request = {"format": 3, "run_id": run, "trigger": personal.AUTO_CONNECTION_TRIGGER, "modules": ["notes", "tasks"]}
    # Keep the peer's frame independent of the local encoder, so the baseline
    # reaches the same receiving entry point even when the codec is absent.
    wrapped = {"format": scope.VERSION, "scope": scope.reference(manifest),
               "kind": "personal_sync.request", "body": request}
    packet = dict(message(wrapped), kind=scope.DATA_KIND)
    service._payload(peer, channel, packet)
    ack = next(item for item in reversed(channel.sent) if item.get("message_id") == packet["message_id"])
    if gate is None:
        assert ack["status"] == "accepted", ack
        assert service.store.personal_run(peer_id, run) == request
        assert service.store.scoped_run_reference(peer_id, public, run) == wrapped["scope"]
        authority = service._connection_automation_authority(peer, channel, request)
        assert service.store.active_auto_run(peer_id, connection_authority=authority) == run
        assert service.store.run_policy(peer_id, run) == "connection_only"
        service._payload(peer, channel, packet)
        assert channel.sent[-1]["status"] == "duplicate"
        other_request = dict(request, run_id=str(uuid.uuid4()))
        competing = dict(message(dict(wrapped, body=other_request)), kind=scope.DATA_KIND)
        service._payload(peer, channel, competing)
        assert (channel.sent[-1]["status"], channel.sent[-1]["error"]) == ("rejected", "not_granted")
        assert not service.store.personal_run(peer_id, other_request["run_id"])
        # Reconnection may negotiate the same settings and content, but it
        # must not resurrect the earlier run or its accepted request receipt.
        replacement = reconnect_automation_fixture(service, peer, channel, remote, manifest)
        service._payload(peer, replacement, packet)
        replay_ack = next(item for item in reversed(replacement.sent) if item.get("message_id") == packet["message_id"])
        assert (replay_ack["status"], replay_ack["error"]) == ("rejected", "not_granted"), replay_ack
        assert service.store.personal_run(peer_id, run) == request
        service._payload(peer, replacement, competing)
        assert replacement.sent[-1]["status"] == "accepted"
        assert service.store.personal_run(peer_id, other_request["run_id"]) == other_request
    else:
        assert not service.store.personal_run(peer_id, run)
        assert service.store.scoped_run_reference(peer_id, public, run) is None
        assert not service.store.active_auto_run(peer_id)
        if gate in {"higher_uuid", "equal_uuid"}:
            assert service.store.dedupe_result(peer_id, packet["message_id"]) is None
        expected_error = "temporary_failure" if gate == "settings_echo" else "not_granted"
        assert (ack["status"], ack["error"]) == ("rejected", expected_error), ack


@pytest.mark.parametrize("change", ["repackaged", "completed", "capability_revision"])
def test_connection_reader_accepts_only_one_automatic_request(tmp_path, monkeypatch, change):
    service, peer, reader, remote, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    peer_id = peer["device_id"]
    run_id = str(uuid.uuid4())
    request = {"format": 3, "run_id": run_id, "trigger": personal.AUTO_CONNECTION_TRIGGER, "modules": ["notes", "tasks"]}
    packet = dict(message(scope.wrap("personal_sync.request", request, manifest)), kind=scope.DATA_KIND)
    service._payload(peer, reader, packet)
    assert reader.sent[-1]["status"] == "accepted"
    if change == "completed":
        service.store.finish_auto_run(peer_id, run_id)
    if change == "capability_revision":
        reader.last_capabilities = phone.desktop_capabilities(service.store.next_revision("capabilities.update"))
    else:
        service._payload(peer, reader, packet)
        assert reader.sent[-1]["status"] == "duplicate"
    competing = dict(request, run_id=str(uuid.uuid4())) if change != "repackaged" else request
    retry = dict(message(scope.wrap("personal_sync.request", competing, manifest)), kind=scope.DATA_KIND)
    service._payload(peer, reader, retry)
    assert (reader.sent[-1]["status"], reader.sent[-1]["error"]) == ("rejected", "not_granted")
    assert service.store.dedupe_result(peer_id, retry["message_id"]) is None
    if change != "repackaged":
        assert service.store.personal_run(peer_id, competing["run_id"]) == {}
    replacement = reconnect_automation_fixture(service, peer, reader, remote, manifest)
    fresh = dict(request, run_id=str(uuid.uuid4()))
    service._payload(peer, replacement, dict(message(scope.wrap("personal_sync.request", fresh, manifest)), kind=scope.DATA_KIND))
    assert replacement.sent[-1]["status"] == "accepted"


def test_connection_request_requires_current_capability_sent_on_the_original_reader(tmp_path, monkeypatch):
    service, peer, original, remote, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    peer_id, public = peer["device_id"], peer["static_public"]
    run_id = str(uuid.uuid4())
    request = {"format": 3, "run_id": run_id, "trigger": personal.AUTO_CONNECTION_TRIGGER, "modules": ["notes", "tasks"]}
    packet = dict(message(scope.wrap("personal_sync.request", request, manifest)), kind=scope.DATA_KIND)
    outbound_key, outbound_prefix = b"k" * 32, b"p" * 4
    desktop_socket, phone_socket = socket.socketpair()
    with desktop_socket, phone_socket:
        phone_socket.settimeout(2)
        channel = phone.SecureChannel(desktop_socket, original.sid, outbound_key, outbound_prefix, b"r" * 32, b"q" * 4)
        service.connections[peer_id] = channel
        service.note_controls[channel] = copy.deepcopy(service.note_controls[original])

        def receive():
            secured = phone.receive_frame(phone_socket, 1 << 20)
            header = {key: value for key, value in secured.items() if key != "ciphertext"}
            nonce = outbound_prefix + header["seq"].to_bytes(8, "big")
            return json.loads(AESGCM(outbound_key).decrypt(
                nonce, base64.b64decode(secured["ciphertext"]), phone.canonical(header)))

        # Receive the shared choice and phone membership through the same reader.
        service._payload(peer, channel, message(remote))
        service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
        assert service.shared_settings_ready(peer_id)
        for _ in range(channel.send_seq):
            receive()

        def send_advertisement(capabilities):
            wire = dict(message(capabilities), kind="capabilities.update")
            channel.send(wire)
            assert receive() == wire and channel.last_capabilities == capabilities

        def require_rejected():
            service._payload(peer, channel, packet)
            ack = receive()
            assert (ack["status"], ack["error"]) == ("rejected", "not_granted")
            assert service.store.personal_run(peer_id, run_id) == {}
            assert service.store.scoped_run_reference(peer_id, public, run_id) is None
            assert service.store.dedupe_result(peer_id, packet["message_id"]) is None

        require_rejected()
        stale = original.last_capabilities
        missing_format = phone.desktop_capabilities(service.store.next_revision("capabilities.update"))
        missing_format["items"]["personal_tasks_sync"]["versions"].remove(3)
        send_advertisement(stale)
        require_rejected()
        send_advertisement(missing_format)
        require_rejected()
        current = phone.desktop_capabilities(service.store.next_revision("capabilities.update"))
        send_advertisement(current)
        service._payload(peer, channel, packet)
        assert receive()["status"] == "accepted"
        assert service.store.personal_run(peer_id, run_id) == request
        stored = service.store._personal_run_record(peer_id, run_id)
        latest = phone.desktop_capabilities(service.store.next_revision("capabilities.update"))
        with pytest.raises(PermissionError, match="not been advertised"):
            service._connection_run_authority(peer, channel, stored)
        send_advertisement(latest)
        with pytest.raises(PermissionError, match="reader changed"):
            service._connection_run_authority(peer, channel, stored)


def test_current_phone_membership_arrives_only_after_complete_bound_manifest(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["note-%03d" % n for n in range(100)], ["task"])
    parts = scope.chunks(manifest, 32)
    packet = frame(parts[-1]); service._payload(peer, channel, packet)
    assert channel.sent[-1]["status"] == "accepted"
    with pytest.raises(PermissionError):
        service.current_content_scope(peer["device_id"], peer["static_public"], scope.reference(manifest))
    for part in parts[:-1]:
        service._payload(peer, channel, frame(part))
    assert service.current_content_scope(peer["device_id"], peer["static_public"], scope.reference(manifest)) == manifest
    service._payload(peer, channel, packet)
    assert channel.sent[-1]["status"] == "accepted"
    service.connections[peer["device_id"]] = Channel()
    with pytest.raises(PermissionError):
        service.current_content_scope(peer["device_id"], peer["static_public"], scope.reference(manifest))


@pytest.mark.parametrize("change", ["mode", "grants", "task_grant", "key", "capability", "expired", "altered"])
def test_scope_cannot_bypass_current_choice_session_or_message_identity(tmp_path, monkeypatch, change):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["mobile-note"], [])
    packet = frame(scope.chunks(manifest)[0])
    if change == "mode":
        service.store.change_shared_setting(peer["device_id"], peer["static_public"], "content_mode", "two_way")
    elif change == "grants": service.note_controls[channel].pop("grants.update")
    elif change == "task_grant": peer["local_grants"]["grants"]["personal_tasks_sync"] = False
    elif change == "key":
        previous = copy.deepcopy(peer); peer["static_public"] = phone.b64(b"n" * 32); peer = previous
    elif change == "capability": peer["capabilities"]["items"]["personal_tasks_sync"]["versions"].remove(scope.VERSION)
    elif change == "expired": packet["created_ms"] -= 120000; packet["expires_ms"] -= 120000
    elif change == "altered":
        service._payload(peer, channel, packet)
        packet = copy.deepcopy(packet); packet["body"] = scope.chunks(scope.advance(manifest, ["other-note"], []))[0]
    service._payload(peer, channel, packet)
    assert channel.sent[-1]["status"] == "rejected"


def test_scoped_transfer_requires_current_capabilities_on_both_sides():
    items = phone.desktop_capabilities()["items"]
    assert scope.supported(items, items)
    legacy = copy.deepcopy(items)
    for item in legacy.values():
        item["versions"] = [version for version in item["versions"] if version < 9]
    assert not scope.supported(items, legacy)


def test_manual_single_note_uses_existing_transfer_even_without_phone_membership(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    import magnolie_personal_sync as personal
    value = {"title": "Selected", "text": "Send again", "html": "", "notebook_id": "", "symbol": "note",
             "created_ms": 1, "modified_ms": 2, "attachments": []}
    record = {"kind": "note", "id": "organizer-note", "state": "live", "clock": [{"actor_id": str(uuid.uuid4()), "counter": 1}],
              "hash": personal.projection_hash(value), "modified_ms": 2, "value": value}
    for _ in range(2):
        run = str(uuid.uuid4())
        request = {"format": 3, "run_id": run, "trigger": "manual", "modules": ["notes"],
                   "send_item": {"kind": "note", "id": "organizer-note"}}
        batch = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
                 "reply": False, "records": [record], "records_hash": personal.records_hash([record])}
        service.send_personal_sync_run(peer["device_id"], request, [batch], [])
        outgoing = [item for item in channel.sent if item.get("body", {}).get("run_id") == run]
        assert [item["kind"] for item in outgoing] == ["personal_sync.request", "personal_sync.batch"]
        assert outgoing[-1]["body"]["records"] == [record]


@pytest.mark.parametrize("kind", ["note", "task"])
def test_phone_single_send_requires_scope_and_stages_only_the_selected_entry(tmp_path, monkeypatch, kind):
    import magnolie_personal_sync as personal
    service, peer, channel = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(phone, "PERSONAL_COMMIT_SECONDS", 0)
    manifest = scope.create(["mobile-note", "other-note"], ["mobile-task", "other-task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    selected = {"kind": kind, "id": "mobile-" + kind}
    request = {"format": 14, "run_id": str(uuid.uuid4()), "trigger": "manual",
               "modules": ["notes" if kind == "note" else "tasks"], "send_item": selected}
    naked = dict(message(request), kind="personal_sync.request")
    service._payload(peer, channel, naked)
    assert channel.sent[-1]["status"] == "rejected"
    assert service.store.personal_run(peer["device_id"], request["run_id"]) == {}
    wrapped = dict(message(scope.wrap("personal_sync.request", request, manifest)), kind=scope.DATA_KIND)
    service._payload(peer, channel, wrapped)
    assert channel.sent[-1]["status"] == "accepted"
    value = {"title": "Chosen entry", "created_ms": 1, "modified_ms": 2, "origin_app": "notes"}
    if kind == "note":
        value.update(text="Chosen text", html="", notebook_id="", symbol="note", attachments=[])
    else:
        value.update(note="Chosen task", due="", priority=2, completed=False, remind=False,
                     lead_days=0, reminder_minute=480, uid="mobile-task-uid", parent_uid="", order=0)
    record = {"kind": kind, "id": selected["id"], "state": "live",
              "clock": [{"actor_id": peer["device_id"], "counter": 1}], "hash": personal.projection_hash(value),
              "modified_ms": 2, "value": value}
    body = {"format": 14, "run_id": request["run_id"], "batch_id": str(uuid.uuid4()), "sequence": 0,
            "last": True, "reply": False, "records": [record], "records_hash": personal.records_hash([record])}
    foreign = copy.deepcopy(body); foreign["records"][0]["id"] = "other-" + kind
    foreign["records_hash"] = personal.records_hash(foreign["records"])
    with pytest.raises(ValueError, match="outside selected"):
        service.store.stage_personal_batch(peer["device_id"], dict(message(foreign), kind="personal_sync.batch"))
    events = []
    service.callback = lambda name, payload: events.append((name, payload))
    service._payload(peer, channel, dict(message(scope.wrap("personal_sync.batch", body, manifest)), kind=scope.DATA_KIND))
    emitted = [payload for name, payload in events if name == "personal_sync" and payload.get("kind") == "personal_sync.batch"]
    assert len(emitted) == 1
    assert emitted[0]["body"]["send_item"] == selected
    assert emitted[0]["body"]["records"] == [record]
    assert emitted[0]["content_scope"] == manifest


def test_settings_agreement_gap_is_retryable_without_raw_content_fallback(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["mobile-note"], ["task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    changed = service.store.change_shared_setting(peer["device_id"], peer["static_public"], "time_enabled", True)
    assert not service.shared_settings_ready(peer["device_id"])
    part = frame(scope.chunks(manifest)[0])
    request = {"format": 3, "run_id": str(uuid.uuid4()), "trigger": "manual", "modules": ["notes", "tasks"]}
    wrapped = message(scope.wrap("personal_sync.request", request, manifest)); wrapped["kind"] = scope.DATA_KIND
    for packet in (part, wrapped):
        service._payload(peer, channel, packet)
        assert channel.sent[-1]["status"] == "rejected" and channel.sent[-1]["error"] == "temporary_failure"
    assert service.store.personal_run(peer["device_id"], request["run_id"]) == {}
    raw = dict(message(request), kind="personal_sync.request", body=dict(request, run_id=str(uuid.uuid4())))
    service._payload(peer, channel, raw)
    assert channel.sent[-1]["error"] == "not_granted"
    assert service.store.personal_run(peer["device_id"], raw["body"]["run_id"]) == {}
    legacy = dict(request, run_id=str(uuid.uuid4()))
    service.store.remember_personal_run(peer["device_id"], legacy, phone.now_ms() + 60000)
    outgoing = service.store.queue(peer["device_id"], "personal_sync.request", legacy, 60000)
    count = len(channel.sent)
    assert service._send_message(channel, peer["device_id"], outgoing) is False
    assert len(channel.sent) == count
    service._payload(peer, channel, message(changed))
    assert service.shared_settings_ready(peer["device_id"])
    for packet in (part, wrapped):
        service._payload(peer, channel, packet)
        assert channel.sent[-1]["status"] in {"accepted", "duplicate"}
    assert service.current_content_scope(peer["device_id"], peer["static_public"], scope.reference(manifest)) == manifest


def test_persisted_scope_choice_survives_capability_downgrade_without_raw_fallback(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    for name in ("personal_notes_sync", "personal_tasks_sync"):
        peer["capabilities"]["items"][name]["versions"].remove(shared.VERSION)
    request = {"format": 3, "run_id": str(uuid.uuid4()), "trigger": "manual", "modules": ["notes", "tasks"]}
    service._payload(peer, channel, dict(message(request), kind="personal_sync.request"))
    assert channel.sent[-1]["status"] == "rejected" and channel.sent[-1]["error"] == "not_granted"
    assert service.store.personal_run(peer["device_id"], request["run_id"]) == {}


def test_scoped_data_dispatch_persists_run_and_never_accepts_unwrapped_reuse(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["mobile-note"], ["task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    request = {"format": 3, "run_id": str(uuid.uuid4()), "trigger": "manual", "modules": ["notes", "tasks"]}
    wrapped = message(scope.wrap("personal_sync.request", request, manifest)); wrapped["kind"] = scope.DATA_KIND
    service._payload(peer, channel, wrapped)
    assert channel.sent[-1]["status"] == "accepted"
    assert service.store.scoped_run_reference(peer["device_id"], peer["static_public"], request["run_id"]) == scope.reference(manifest)
    naked = dict(wrapped, kind="personal_sync.request", body=request)
    service._payload(peer, channel, naked)
    assert channel.sent[-1]["status"] == "rejected"
    service._payload(peer, channel, wrapped)
    assert channel.sent[-1]["status"] in {"accepted", "duplicate"}
    altered = copy.deepcopy(wrapped); altered["body"]["body"]["run_id"] = str(uuid.uuid4())
    service._payload(peer, channel, altered)
    assert channel.sent[-1]["status"] == "rejected"
    assert service.store.personal_run(peer["device_id"], altered["body"]["body"]["run_id"]) == {}
    fresh_naked = dict(naked, message_id=str(uuid.uuid4()), body=dict(request, run_id=str(uuid.uuid4())))
    service._payload(peer, channel, fresh_naked)
    assert channel.sent[-1]["status"] == "rejected"
    assert service.store.personal_run(peer["device_id"], fresh_naked["body"]["run_id"]) == {}


def test_outgoing_scoped_data_wraps_current_member_and_blocks_other_notes(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["mobile-note"], ["task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    run_id = str(uuid.uuid4()); request = {"format": 3, "run_id": run_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service.store.remember_scoped_run(peer["device_id"], peer["static_public"], request, scope.reference(manifest), phone.now_ms() + 60000)
    import magnolie_personal_sync as personal
    value = {"title": "Shared", "text": "Organizer addition", "html": "", "notebook_id": "", "symbol": "note",
             "created_ms": 1, "modified_ms": 2, "attachments": []}
    record = {"kind": "note", "id": "mobile-note", "state": "live", "clock": [{"actor_id": str(uuid.uuid4()), "counter": 1}],
              "hash": personal.projection_hash(value), "modified_ms": 2, "value": value}
    body = {"format": 3, "run_id": run_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
            "reply": True, "records": [record], "records_hash": personal.records_hash([record])}
    service.send_personal_sync(peer["device_id"], "personal_sync.batch", body)
    sent = channel.sent[-1]
    assert sent["kind"] == scope.DATA_KIND
    assert scope.unwrap(sent["body"], manifest) == ("personal_sync.batch", body)
    foreign = copy.deepcopy(body); foreign["records"][0]["id"] = "organizer-only"
    foreign["records_hash"] = personal.records_hash(foreign["records"])
    before = len(channel.sent)
    with pytest.raises(PermissionError):
        service.send_personal_sync(peer["device_id"], "personal_sync.batch", foreign)
    assert len(channel.sent) == before
    removed = scope.advance(manifest, [], [])
    service._payload(peer, channel, frame(scope.chunks(removed)[0]))
    with pytest.raises(ValueError):
        service._payload(peer, channel, {"type": "ack", "message_id": sent["message_id"], "status": "accepted", "error": "none"})
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT count(*) FROM outbox WHERE peer_id=? AND message_id=?",
                          (peer["device_id"], sent["message_id"])).fetchone()[0] == 1
    with pytest.raises((PermissionError, ValueError)):
        service.send_personal_sync(peer["device_id"], "personal_sync.batch", body)


@pytest.mark.parametrize("trigger, reader_lost", [
    ("manual", None),
    (personal.AUTO_CONNECTION_TRIGGER, None),
    (personal.AUTO_CONNECTION_TRIGGER, "before_staging"),
    (personal.AUTO_CONNECTION_TRIGGER, "before_commit"),
])
def test_complete_phone_batch_reaches_gui_with_scope_and_exact_commit_guard(tmp_path, monkeypatch, trigger, reader_lost):
    remote = None
    if trigger == personal.AUTO_CONNECTION_TRIGGER:
        service, peer, channel, remote, manifest = connection_automation_fixture(tmp_path, monkeypatch, "bluetooth")
    else:
        service, peer, channel = fixture(tmp_path, monkeypatch)
        manifest = scope.create(["mobile-note"], ["task"])
        service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    run_id = str(uuid.uuid4()); request = {"format": 3, "run_id": run_id, "trigger": trigger, "modules": ["notes", "tasks"]}
    request_message = message(scope.wrap("personal_sync.request", request, manifest)); request_message["kind"] = scope.DATA_KIND
    service._payload(peer, channel, request_message)
    assert channel.sent[-1]["status"] == "accepted"
    value = {"title": "Mobile", "text": "Phone edit", "html": "", "notebook_id": "", "symbol": "note",
             "created_ms": 1, "modified_ms": 2, "attachments": []}
    record = {"kind": "note", "id": manifest["members"]["notes"][0], "state": "live", "clock": [{"actor_id": peer["device_id"], "counter": 1}],
              "hash": personal.projection_hash(value), "modified_ms": 2, "value": value}
    body = {"format": 3, "run_id": run_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
            "reply": False, "records": [record], "records_hash": personal.records_hash([record])}
    deliveries = []
    def applied(event, payload):
        if event != "personal_sync": return
        deliveries.append(payload)
        if trigger == personal.AUTO_CONNECTION_TRIGGER:
            assert payload["body"]["trigger"] == trigger
            assert payload["transport"] == "bluetooth"
        assert payload["content_scope"] == manifest
        assert payload["body"]["records"] == [record]
        message_id, token = payload["pending_message_id"], payload["commit_token"]
        if reader_lost == "before_commit":
            reconnect_automation_fixture(service, peer, channel, remote, manifest)
            assert not service.commit_personal_sync(peer["device_id"], message_id, token, True)
            assert service.store.has_personal_batch(peer["device_id"], message_id, token)
            assert service.commit_personal_sync(peer["device_id"], message_id, token, False)
        elif trigger == personal.AUTO_CONNECTION_TRIGGER:
            assert not service.commit_personal_sync(peer["device_id"], message_id, token, True)
            assert service.commit_personal_sync(peer["device_id"], message_id, token, False)
        else:
            assert service.commit_personal_sync(peer["device_id"], message_id, token, True)
    service.callback = applied
    batch_message = message(scope.wrap("personal_sync.batch", body, manifest)); batch_message["kind"] = scope.DATA_KIND
    if reader_lost == "before_staging":
        replacement = reconnect_automation_fixture(service, peer, channel, remote, manifest)
        service._payload(peer, replacement, batch_message)
        assert replacement.sent[-1]["error"] == "not_granted"
        assert not service.store.dedupe_result(peer["device_id"], batch_message["message_id"])
        assert deliveries == []
        return
    service._payload(peer, channel, batch_message)
    assert len(deliveries) == 1
    if reader_lost == "before_commit":
        replacement = service.connections[peer["device_id"]]
        service.replay_personal_sync()
        service._payload(peer, replacement, batch_message)
        assert replacement.sent[-1]["error"] == "not_granted"
    elif trigger == "manual":
        service._payload(peer, channel, batch_message)
    else:
        assert service.store.has_personal_batch(peer["device_id"], batch_message["message_id"], deliveries[0]["commit_token"])
    assert len(deliveries) == 1
