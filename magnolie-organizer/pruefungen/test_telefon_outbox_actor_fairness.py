"""Refs #128: a live sender may pass bounded pages of unadmitted actor frames."""
import copy
import sqlite3
import uuid

import pytest

from test_mcp_phone import owned_service
from test_personal_actor_transport import owned_transport
import magnolie_personal_actor as actor
import magnolie_telefon as phone


class Channel:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(copy.deepcopy(message))


def held_frames(service, peer, count, run=None):
    run = run or str(uuid.uuid4())
    request = {"format": 3, "run_id": run, "trigger": "manual", "modules": ["notes", "tasks"]}
    service.store.remember_personal_run(actor.storage_peer(run), request)
    result = []
    for sequence in range(count):
        body = {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": sequence,
                "last": sequence == count - 1, "reply": False, "records_hash": phone.records_hash([]), "records": []}
        result.append(service.store.queue(peer["device_id"], "personal_sync.batch", body, 60000, actor_run_id=run))
    return result


def status_request(service, peer):
    return service.store.queue(peer["device_id"], "device_status.request", {"request_id": str(uuid.uuid4())}, 60000)


def attempts(service, message):
    with sqlite3.connect(service.store.database_path) as db:
        return db.execute("SELECT attempts FROM outbox WHERE message_id=?", (message["message_id"],)).fetchone()[0]


def owned_actor_pump(tmp_path, monkeypatch):
    fixture = owned_transport(tmp_path, monkeypatch)
    service, peer, _, _, _, _ = fixture
    # The fixture already negotiated this choice. Clear the queued echo so
    # its ordinary write isn't treated as an actor write by the fixture.
    service.store.remove_kind(peer["device_id"], phone.shared_sync_contract.KIND)
    return fixture


@pytest.mark.parametrize("transport,count", [("wifi", 65), ("bluetooth", 65), ("wifi", 96)])
def test_bounded_pages_pass_held_actors_without_grant_or_wire_changes(tmp_path, monkeypatch, transport, count):
    service, peer, events = owned_service(tmp_path)
    fixed = phone.now_ms()
    monkeypatch.setattr(phone, "now_ms", lambda: fixed)  # Every row has the same created_ms.
    held = held_frames(service, peer, count)
    ordinary = status_request(service, peer)
    channel = Channel()
    for _ in range(count // 32):
        service._pump_pending(channel, peer["device_id"], transport)
        assert channel.sent == []
        # The read/ACK API still starts at the head and cannot move the pump.
        assert service.store.pending(peer["device_id"], transport) == held[:32]
    service._pump_pending(channel, peer["device_id"], transport)
    assert channel.sent == [ordinary] and attempts(service, ordinary) == 1
    assert all(attempts(service, item) == 0 and service.store.outbox_message(peer["device_id"], item["message_id"]) == item for item in held)
    assert not events and service.server is None


def test_new_control_precedes_data_even_after_actor_cursor(tmp_path, monkeypatch):
    service, peer, _ = owned_service(tmp_path)
    fixed = phone.now_ms(); monkeypatch.setattr(phone, "now_ms", lambda: fixed)
    held_frames(service, peer, 64)
    ordinary = status_request(service, peer)
    channel = Channel()
    service._pump_pending(channel, peer["device_id"], "wifi")
    control = service.store.queue(peer["device_id"], "grants.update", copy.deepcopy(peer["local_grants"]), 60000)
    service._pump_pending(channel, peer["device_id"], "wifi")
    assert channel.sent == [control]
    service._pump_pending(channel, peer["device_id"], "wifi")
    assert channel.sent == [control, ordinary]


@pytest.mark.parametrize("kind", ["personal_sync.shared_start", "personal_sync.time_request"])
def test_ordinary_policy_waits_are_not_skipped_by_actor_cursor(tmp_path, kind):
    service, peer, _ = owned_service(tmp_path)
    for _ in range(32):
        body = ({"format": 9, "request_id": str(uuid.uuid4()), "trigger": "manual"}
                if kind.endswith("shared_start") else
                {"format": 7, "sender_epoch": str(uuid.uuid4()), "receiver_epoch": str(uuid.uuid4()),
                 "sender_revision": 1, "receiver_revision": 1, "trigger": "manual"})
        service.store.queue(peer["device_id"], kind, body, 60000)
    ordinary = status_request(service, peer)
    channel = Channel()
    for _ in range(3):
        service._pump_pending(channel, peer["device_id"], "wifi")
        assert channel not in service._outbox_actor_windows
    assert channel.sent == [] and attempts(service, ordinary) == 0


def test_new_channel_and_transport_do_not_inherit_cursor_and_end_wraps(tmp_path, monkeypatch):
    service, peer, _ = owned_service(tmp_path)
    fixed = phone.now_ms(); monkeypatch.setattr(phone, "now_ms", lambda: fixed)
    held = held_frames(service, peer, 32)
    ordinary = status_request(service, peer)
    first, second = Channel(), Channel()
    service._pump_pending(first, peer["device_id"], "wifi")
    service._pump_pending(second, peer["device_id"], "wifi")
    assert first.sent == second.sent == []
    service._pump_pending(second, peer["device_id"], "bluetooth")
    assert second.sent == []
    service._pump_pending(second, peer["device_id"], "bluetooth")
    assert second.sent == [ordinary]
    # Delete the inspected page and its successor, then add an earlier timestamp.
    for item in [*held, ordinary]:
        service.store.acknowledge(peer["device_id"], item["message_id"])
    monkeypatch.setattr(phone, "now_ms", lambda: fixed - 1000)
    replacement = status_request(service, peer)
    service._pump_pending(first, peer["device_id"], "wifi")  # Exhausted cursor wraps.
    assert first.sent == [] and first not in service._outbox_actor_windows
    service._pump_pending(first, peer["device_id"], "wifi")
    assert first.sent == [replacement]


def test_wifi_only_remains_filtered_before_any_pump_window(tmp_path):
    service, peer, _ = owned_service(tmp_path)
    held_frames(service, peer, 64)
    wifi = service.store.queue(peer["device_id"], "device_status.request", {"request_id": str(uuid.uuid4())}, 60000, "wifi_only")
    ordinary = status_request(service, peer)
    channel = Channel()
    for _ in range(3):
        service._pump_pending(channel, peer["device_id"], "bluetooth")
    assert channel.sent == [ordinary] and attempts(service, wifi) == 0


def test_genuinely_authorized_actor_send_does_not_advance_held_page_cursor(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_actor_pump(tmp_path, monkeypatch)
    service.start_personal_actor(registry, handle)
    channel.sent.clear()
    frames = held_frames(service, peer, 32, handle.actor_id)
    admission = service.personal_actor_admissions[handle.actor_id]
    # Transport fixture explicitly admits these exact retained IDs. The real
    # registry/source/channel/expiry checks and encrypted send path still run.
    admission["outbound"].update(item["message_id"] for item in frames)
    service._pump_pending(channel, peer["device_id"], "wifi")
    assert channel.sent == frames
    assert all(attempts(service, item) == 1 for item in frames)
    assert channel not in service._outbox_actor_windows and not events


@pytest.mark.parametrize("transition", ["before_query", "after_query"])
def test_new_actor_admission_resumes_at_head_not_behind_old_cursor(tmp_path, monkeypatch, transition):
    service, peer, channel, registry, handle, events = owned_actor_pump(tmp_path, monkeypatch)
    frames = held_frames(service, peer, 65, handle.actor_id)
    service._pump_pending(channel, peer["device_id"], "wifi")
    assert channel.sent == [] and channel in service._outbox_actor_windows

    def admit():
        service.start_personal_actor(registry, handle)
        service.personal_actor_admissions[handle.actor_id]["outbound"].update(item["message_id"] for item in frames)
        channel.sent.clear()

    original = service.store.pump_window
    if transition == "before_query":
        admit()
    else:
        def page_then_admit(*args, **kwargs):
            page = original(*args, **kwargs)
            admit()
            return page
        monkeypatch.setattr(service.store, "pump_window", page_then_admit)
    service._pump_pending(channel, peer["device_id"], "wifi")
    if transition == "after_query":
        assert channel.sent == [], "A late admission sent an actor from an advanced data page."
        monkeypatch.setattr(service.store, "pump_window", original)
        service._pump_pending(channel, peer["device_id"], "wifi")
    assert channel.sent == frames[:32]
    assert channel not in service._outbox_actor_windows and not events


def test_current_actor_wait_does_not_build_an_ordinary_sender_cursor(tmp_path, monkeypatch):
    service, peer, channel, registry, handle, events = owned_actor_pump(tmp_path, monkeypatch)
    service.start_personal_actor(registry, handle)
    channel.sent.clear()
    frames = held_frames(service, peer, 65, handle.actor_id)
    admission = service.personal_actor_admissions[handle.actor_id]
    admission["outbound"].update(item["message_id"] for item in frames)
    # The real actor send guard defers data while its native save is prepared.
    admission["historical_save_claim"] = object()
    service._pump_pending(channel, peer["device_id"], "wifi")
    assert channel.sent == [] and channel not in service._outbox_actor_windows
    admission.pop("historical_save_claim")
    service._pump_pending(channel, peer["device_id"], "wifi")
    assert channel.sent == frames[:32] and not events
