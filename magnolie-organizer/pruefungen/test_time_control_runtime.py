import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import pytest
from test_time_sync_runtime import ready, message
import magnolie_telefon as phone
import magnolie_time_control as control

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "contracts/time-control-v13.json").read_text())


def runtime(tmp_path, monkeypatch):
    service, peer_id, channel, _, events = ready(tmp_path, monkeypatch)
    service.enabled = True
    capabilities = phone.desktop_capabilities()
    capabilities["items"]["personal_tasks_sync"]["versions"].append(13)
    monkeypatch.setattr(phone, "desktop_capabilities", lambda: copy.deepcopy(capabilities))
    peer = service.store.peer(peer_id); peer["capabilities"] = copy.deepcopy(capabilities)
    service._observe_note_control(peer, channel, "capabilities.update", peer["capabilities"])
    channel.sent.clear(); events.clear()
    return service, peer, channel, phone.fingerprint(phone.unb64(peer["static_public"], 32)), events


def report(body):
    value = copy.deepcopy(VECTORS["reports"][0]); value["request_id"] = body["request_id"]; value["operation_id"] = body["operation_id"]
    if body["operation_id"]:
        value.update(operation_applied=True, persisted=True, applied_entry_id=body["operation_id"],
            applied_clock={"44444444-4444-4444-8444-444444444444": 1}, runtime_request="requested")
    return message(control.REPORT, value)


def test_correlated_native_report_is_ephemeral_not_gui_or_outbox_data(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, events = runtime(tmp_path, monkeypatch)
    def send(wire):
        assert not service.lock._is_owned()
        channel.sent.append(copy.deepcopy(wire))
        service._payload(peer, channel, report(wire["body"]))
    channel.send = send
    body = control.request(str(uuid4()))
    source = service.mcp_action({"action": "time_control_source", "peerId": peer["device_id"], "fingerprint": fingerprint})
    assert source["ok"]
    response = service.mcp_action({"action": "time_control_query", "peerId": peer["device_id"], "fingerprint": fingerprint,
        "sourceRevision": source["sourceRevision"], "body": body})
    assert response["ok"]; result = response["timeControl"]
    assert result["report"]["request_id"] == body["request_id"] and result["dispatch_started"]
    assert not result["report"]["persisted"] and len(result["source_revision"]) == 64
    assert not service.time_control_requests and not service.store.pending(peer["device_id"]) and not events
    service._payload(peer, channel, report(body))
    assert not events and not service.time_control_requests
    with pytest.raises(PermissionError): service.request_time_control(peer["device_id"], fingerprint, body)


def test_command_save_fact_requires_a_correlated_report_not_an_ordinary_ack(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, events = runtime(tmp_path, monkeypatch)
    sent = threading.Event()
    channel.send = lambda wire: (channel.sent.append(copy.deepcopy(wire)), sent.set())
    body = control.request(str(uuid4()), "start", operation_id=str(uuid4()), expected_revision="a" * 64, restore_epoch="native-book")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.request_time_control, peer["device_id"], fingerprint, body)
        assert sent.wait(3)
        wire = channel.sent[-1]
        service._payload(peer, channel, {"type": "ack", "message_id": wire["message_id"], "status": "accepted", "error": "none"})
        assert not future.done()
        wrong = report(body); wrong["body"]["operation_id"] = str(uuid4())
        service._payload(peer, channel, wrong); assert not future.done()
        service._payload(peer, channel, report(body))
        assert future.result(timeout=3)["report"]["persisted"]
    assert not events and not service.store.pending(peer["device_id"])


def test_cancel_and_wrong_owner_do_not_recall_or_publish_late_timer_data(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, events = runtime(tmp_path, monkeypatch)
    sent = threading.Event()
    channel.send = lambda wire: sent.set()
    body = control.request(str(uuid4()))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.request_time_control, peer["device_id"], fingerprint, body)
        assert sent.wait(3)
        assert not service.cancel_time_control(str(uuid4()), fingerprint, body["request_id"])["cancel_requested"]
        assert not future.done()
        cancelled = service.cancel_time_control(peer["device_id"], fingerprint, body["request_id"])
        assert cancelled["cancel_requested"] and not cancelled["remote_recall_confirmed"]
        with pytest.raises(PermissionError): future.result(timeout=3)
    service._payload(peer, channel, report(body))
    assert not events and not service.time_control_requests


def test_unnegotiated_or_withdrawn_source_never_dispatches_timer_requests(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, events = runtime(tmp_path, monkeypatch)
    peer["personal_sync"]["remote_own_device"] = False
    with pytest.raises(PermissionError): service.request_time_control(peer["device_id"], fingerprint, control.request(str(uuid4())))
    assert not channel.sent and not events
    peer["personal_sync"]["remote_own_device"] = True
    peer["capabilities"]["items"]["personal_tasks_sync"]["versions"].remove(13)
    assert service.mcp_action({"action": "time_control_source", "peerId": peer["device_id"], "fingerprint": fingerprint})["code"] == "unsupported_feature"
    with pytest.raises(PermissionError): service.request_time_control(peer["device_id"], fingerprint, control.request(str(uuid4())))
    assert not channel.sent
