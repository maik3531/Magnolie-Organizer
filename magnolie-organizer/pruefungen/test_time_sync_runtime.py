"""V7 service routing and session fences with capture-only authenticated channels."""
import copy
import sqlite3
from uuid import uuid4
import pytest
from test_personal_sync import _personal_service
from test_time_sync import record
import magnolie_telefon as phone
import magnolie_time_sync as time


class Channel:
    def __init__(self): self.sent = []
    def send(self, value): self.sent.append(copy.deepcopy(value))


def message(kind, body):
    now = phone.now_ms()
    return dict(type="message", v=1, message_id=str(uuid4()), kind=kind,
                created_ms=now, expires_ms=now + 60000, body=body)


def connect(service, peer_id):
    channel = Channel()
    service.connections[peer_id] = channel
    service.connection_transports[peer_id] = "wifi"
    peer = service.store.peer(peer_id)
    for kind, body in (("capabilities.update", peer["capabilities"]), ("grants.update", peer["grants"]),
                       ("personal_sync.settings", dict(format=1, own_device=True))):
        service._observe_note_control(peer, channel, kind, body)
    return channel


def ready(tmp_path, monkeypatch):
    capabilities = phone.desktop_capabilities()
    capabilities["items"]["personal_tasks_sync"]["versions"] = sorted(set(capabilities["items"]["personal_tasks_sync"]["versions"] + [7]))
    monkeypatch.setattr(phone, "desktop_capabilities", lambda: copy.deepcopy(capabilities))
    events = []
    service, peer_id = _personal_service(tmp_path, lambda kind, value: events.append((kind, value)))
    service.store.peer(peer_id)["capabilities"] = copy.deepcopy(capabilities)
    channel = connect(service, peer_id)
    service.set_time_sync(peer_id, True)
    remote = time.new_settings(True)
    service._payload(service.store.peer(peer_id), channel, message(time.SETTINGS, remote))
    policies = service.store.time_settings(peer_id)
    incoming = message(time.BATCH, dict(time.request_body(remote, policies["local"]), entries=[record()]))
    channel.sent.clear(); events.clear()
    return service, peer_id, channel, incoming, events


def test_runtime_ack_is_after_document_commit_and_replay_does_not_apply_twice(tmp_path, monkeypatch):
    service, peer, channel, incoming, events = ready(tmp_path, monkeypatch)
    service._payload(service.store.peer(peer), channel, incoming)
    assert channel.sent == []
    assert service.store.dedupe_result(peer, incoming["message_id"]) is None
    kind, staged = events.pop()
    assert kind == "personal_time_batch"
    assert not service.commit_time_sync(peer, incoming["message_id"], staged["commit_token"], False)
    assert service.commit_time_sync(peer, incoming["message_id"], staged["commit_token"], True)
    assert channel.sent[-1]["status"] == "accepted"
    service._payload(service.store.peer(peer), channel, incoming)
    assert not any(kind == "personal_time_batch" for kind, _ in events)
    changed = copy.deepcopy(incoming); changed["body"]["entries"][0]["note"] = "Conflicting replay"
    service._payload(service.store.peer(peer), channel, changed)
    assert channel.sent[-1]["error"] == "invalid_schema"


def test_reconnect_requires_fresh_policy_and_old_channel_cannot_commit(tmp_path, monkeypatch):
    service, peer, channel, incoming, events = ready(tmp_path, monkeypatch)
    service._payload(service.store.peer(peer), channel, incoming)
    staged = events[-1][1]
    new_channel = connect(service, peer)
    assert not service.commit_time_sync(peer, incoming["message_id"], staged["commit_token"], True)
    service._payload(service.store.peer(peer), channel, incoming)
    assert channel.sent[-1]["error"] == "not_granted"
    service._payload(service.store.peer(peer), new_channel, incoming)
    assert new_channel.sent[-1]["error"] == "not_granted"
    policy = service.store.time_settings(peer)["remote"]
    service._payload(service.store.peer(peer), new_channel, message(time.SETTINGS, policy))
    assert service.commit_time_sync(peer, incoming["message_id"], staged["commit_token"], True)


def test_revocation_and_wifi_policy_are_rechecked_at_commit(tmp_path, monkeypatch):
    service, peer, channel, incoming, events = ready(tmp_path, monkeypatch)
    incoming["body"]["trigger"] = "auto_wifi"
    service._payload(service.store.peer(peer), channel, incoming)
    staged = events[-1][1]
    service.connection_transports[peer] = "bluetooth"
    assert not service.commit_time_sync(peer, incoming["message_id"], staged["commit_token"], True)
    service.connection_transports[peer] = "wifi"
    service.set_time_sync(peer, False)
    assert not service.commit_time_sync(peer, incoming["message_id"], staged["commit_token"], True)
    service.set_time_sync(peer, True)
    service._payload(service.store.peer(peer), channel, incoming)
    assert channel.sent[-1]["error"] == "not_granted"


def test_outgoing_snapshot_respects_count_and_utf8_limits(tmp_path, monkeypatch):
    service, peer, channel, incoming, events = ready(tmp_path, monkeypatch)
    records = [dict(record(), note="😀" * 10000) for _ in range(35)]
    ids = service.send_time_records(peer, records)
    assert len([value for value in channel.sent if value.get("kind") == time.BATCH]) == 1
    for message_id in ids:
        service._payload(service.store.peer(peer), channel,
            dict(type="ack", message_id=message_id, status="accepted", error="none"))
        for queued in service.store.pending(peer): service._send_message(channel, peer, queued)
    packets = [value for value in channel.sent if value.get("kind") == time.BATCH]
    assert len(ids) == len(packets) > 1
    assert [item for packet in packets for item in packet["body"]["entries"]] == records
    for packet in packets:
        assert len(packet["body"]["entries"]) <= 32
        time.validate(time.BATCH, packet["body"], True)


def test_manual_bluetooth_snapshot_supersedes_queued_wifi_work(tmp_path, monkeypatch):
    service, peer, channel, incoming, events = ready(tmp_path, monkeypatch)
    automatic = service.send_time_records(peer, [record()], trigger="auto_wifi")
    assert service.store.outbox_policy(peer, automatic[0]) == "wifi_only"
    service.connection_transports[peer] = "bluetooth"
    latest = dict(record(), note="Latest manual snapshot")
    manual = service.send_time_records(peer, [latest], trigger="manual")
    assert service.store.outbox_policy(peer, automatic[0]) is None
    assert channel.sent[-1]["message_id"] == manual[0]
    assert channel.sent[-1]["body"]["entries"] == [latest]


def test_failed_consent_can_be_retried_but_remote_controls_cannot_reopen_it(tmp_path, monkeypatch):
    import pytest
    service, peer, channel, incoming, events = ready(tmp_path, monkeypatch)
    save = service.store.save_peers
    def fail(): raise OSError("synthetic consent persistence failure")
    monkeypatch.setattr(service.store, "save_peers", fail)
    with pytest.raises(OSError): service.set_time_sync(peer, False)
    assert service.time_status(peer)["local"]["enabled"] is True
    assert service.time_status(peer)["ready"] is False
    monkeypatch.setattr(service.store, "save_peers", save)
    remote = service.store.time_settings(peer, allow_failed=True)["remote"]
    service._payload(service.store.peer(peer), channel, message(time.SETTINGS, remote))
    assert channel.sent[-1]["error"] == "not_granted"
    assert service.time_status(peer)["ready"] is False
    service.set_time_sync(peer, False)
    assert service.time_status(peer)["local"]["enabled"] is False
    assert peer not in service.store.time_policy_failed


def test_delayed_ui_packet_cannot_borrow_a_new_consent_epoch(tmp_path, monkeypatch):
    import pytest
    service, peer, channel, incoming, events = ready(tmp_path, monkeypatch)
    policies = service.store.time_settings(peer)
    old = time.batches(policies["local"], policies["remote"], [record()])[0]
    service.set_time_sync(peer, False); service.set_time_sync(peer, True)
    count = len(channel.sent)
    with pytest.raises(PermissionError): service.send_personal_sync(peer, time.BATCH, old)
    assert len(channel.sent) == count


def test_import_only_denies_desktop_records_but_preserves_calendar_and_phone_import(tmp_path, monkeypatch):
    service, peer_id, channel, incoming, events = ready(tmp_path, monkeypatch)
    peer = service.store.peer(peer_id)
    public = peer["static_public"]
    service.store.change_shared_setting(peer_id, public, "time_mode", "phone_import")
    policies = service.store.time_settings(peer_id)
    header = time.request_body(policies["local"], policies["remote"])
    record_batch = dict(header, entries=[record()])
    with pytest.raises(PermissionError):
        service.send_time_records(peer_id, record_batch["entries"])
    with pytest.raises(PermissionError):
        service.send_personal_sync(peer_id, time.BATCH, record_batch)
    assert not service.store.has_kind(peer_id, time.BATCH)
    # A pre-upgrade queue can contain an obsolete time batch already.
    old = service.store.queue(peer_id, time.BATCH, record_batch, phone.DAY_MS)
    calendar = dict(enabled=False, country="DE", regions=[], holidays=[])
    projected = service.send_personal_sync(peer_id, time.BATCH, dict(header, entries=[], calendar=calendar))
    assert service.store.outbox_policy(peer_id, old["message_id"]) is None
    assert channel.sent[-1]["message_id"] == projected
    assert channel.sent[-1]["body"]["calendar"] == calendar
    service._payload(peer, channel, dict(type="ack", message_id=projected, status="accepted", error="none"))
    request_id = service.send_personal_sync(peer_id, time.REQUEST, header)
    assert channel.sent[-1]["message_id"] == request_id
    service._payload(peer, channel, incoming)
    staged = next(value for kind, value in events if kind == "personal_time_batch")
    assert service.commit_time_sync(peer_id, incoming["message_id"], staged["commit_token"], True)


def test_direction_change_rolls_back_on_outbox_failure_without_purging_other_time_data(tmp_path, monkeypatch):
    service, peer_id, channel, incoming, events = ready(tmp_path, monkeypatch)
    peer = service.store.peer(peer_id)
    public = peer["static_public"]
    service.store.change_shared_setting(peer_id, public, "time_mode", "two_way")
    policies = service.store.time_settings(peer_id)
    header = time.request_body(policies["local"], policies["remote"])
    stale = service.store.queue(peer_id, time.BATCH, dict(header, entries=[record()]), phone.DAY_MS)
    empty = service.store.queue(peer_id, time.BATCH, dict(header, entries=[]), phone.DAY_MS)
    queued_request = service.store.queue(peer_id, time.REQUEST, header, phone.DAY_MS)
    service._payload(peer, channel, incoming)
    staged = next(value for kind, value in events if kind == "personal_time_batch")
    before = service.store.shared_settings(peer_id, public)
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("""CREATE TRIGGER fail_time_revoke BEFORE DELETE ON outbox
                      WHEN OLD.kind = 'personal_sync.time_batch'
                      BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        service.store.change_shared_setting(peer_id, public, "time_mode", "phone_import")
    assert service.store.shared_settings(peer_id, public) == before
    assert service.store.outbox_policy(peer_id, stale["message_id"]) == "any"
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("DROP TRIGGER fail_time_revoke")
    service.store.change_shared_setting(peer_id, public, "time_mode", "phone_import")
    assert service.store.outbox_policy(peer_id, stale["message_id"]) is None
    assert service.store.outbox_policy(peer_id, empty["message_id"]) == "any"
    assert service.store.outbox_policy(peer_id, queued_request["message_id"]) == "any"
    assert service.commit_time_sync(peer_id, incoming["message_id"], staged["commit_token"], True)
    service.store.change_shared_setting(peer_id, public, "time_mode", "two_way")
    assert not service._send_message(channel, peer_id, stale)
