"""V7 service routing and session fences with capture-only authenticated channels."""
import copy
from uuid import uuid4
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
