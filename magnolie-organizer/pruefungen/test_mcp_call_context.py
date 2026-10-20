"""Native call provenance; an old book/store event is not a new phone query."""
import copy
import json
from uuid import uuid4

import pytest
from test_time_sync_runtime import ready, message, connect
import magnolie_telefon as phone
import magnolie_hintergrund as background
from test_mcp_phone import FakeBackend


def fixture(tmp_path, monkeypatch):
    service, peer_id, channel, _, events = ready(tmp_path, monkeypatch)
    service.enabled = True
    peer = service.store.peer(peer_id)
    for name in ("incoming_call_state", "incoming_call_number", "answer_call", "end_call"):
        peer["local_grants"]["grants"][name] = True
        peer["grants"]["grants"][name] = True
    service._observe_note_control(peer, channel, "grants.update", peer["grants"])
    events.clear(); channel.sent.clear()
    return service, peer, channel, events


def event():
    now = phone.now_ms()
    return dict(call_ref=str(uuid4()), revision=9007199254740993, state="ringing", direction="incoming",
        number="+49301234567", number_status="available", started_ms=now, offhook_ms=0, ended_ms=0,
        occurred_ms=now, spam_status="unknown", control_origin="phone", battery_percent=-1, battery_captured_ms=0)


def read(service, peer, fingerprint=None):
    return service.mcp_action(dict(action="call_context_read", peerId=peer["device_id"],
        fingerprint=fingerprint or phone.fingerprint(phone.unb64(peer["static_public"], 32))))


def test_call_context_uses_actual_session_event_without_exposing_phone_number(tmp_path, monkeypatch):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    before = read(service, peer); assert before["ok"] and before["callContext"]["call"] is None
    body = event(); service._payload(peer, channel, message("incoming_call_state.event", body))
    assert channel.sent[-1]["status"] == "accepted"
    events.clear(); channel.sent.clear()
    value = read(service, peer)["callContext"]
    assert value["call"]["call_ref"] == body["call_ref"]
    assert value["call"]["revision"] == "9007199254740993", "Call CAS must not lose precision in JavaScript"
    assert value["call"]["observation"] == "authenticated_session_event"
    assert value["call"]["native_received_ms"] >= body["occurred_ms"]
    assert value["permissions"]["incoming_call_state"] and value["permissions"]["answer_call"]
    assert not value["persisted"] and not value["phone_status_queried"] and not value["call"]["phone_status_queried"]
    assert body["number"] not in json.dumps(value) and "number_status" not in json.dumps(value)
    assert value["source_revision"] != before["callContext"]["source_revision"]
    assert not events and not channel.sent


def test_retained_call_object_without_native_receive_receipt_is_not_adopted(tmp_path, monkeypatch):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    service.incoming_calls[peer["device_id"]] = event()
    service.incoming_call_channels[peer["device_id"]] = channel
    assert read(service, peer)["callContext"]["call"] is None
    assert not events and not channel.sent


def test_reconnect_and_late_old_channel_cannot_relabel_retained_call_as_current(tmp_path, monkeypatch):
    service, peer, old_channel, events = fixture(tmp_path, monkeypatch)
    body = event(); service._payload(peer, old_channel, message("incoming_call_state.event", body))
    old = read(service, peer)["callContext"]
    fresh_channel = connect(service, peer["device_id"])
    current = read(service, peer)["callContext"]
    assert current["call"] is None and current["source_revision"] != old["source_revision"]
    late = copy.deepcopy(body); late["revision"] += 1
    service._payload(peer, old_channel, message("incoming_call_state.event", late))
    assert old_channel.sent[-1]["status"] == "rejected"
    assert read(service, peer)["callContext"]["call"] is None
    assert fresh_channel is service.connections[peer["device_id"]]


@pytest.mark.parametrize("change", ["offline", "key", "fingerprint", "missing_controls", "local_grant", "remote_grant"])
def test_call_context_rechecks_actual_identity_controls_and_grants(tmp_path, monkeypatch, change):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    service._payload(peer, channel, message("incoming_call_state.event", event()))
    events.clear(); channel.sent.clear()
    if change == "offline": service.connections.pop(peer["device_id"])
    if change == "key": peer["static_public"] = phone.b64(b"q" * 32)
    if change == "missing_controls": service.note_controls.pop(channel)
    if change == "local_grant": peer["local_grants"]["grants"]["incoming_call_state"] = False
    if change == "remote_grant": peer["grants"]["grants"]["incoming_call_state"] = False
    result = read(service, peer, "0000-1234-5678-90EF" if change == "fingerprint" else None)
    if change == "local_grant":
        assert result["ok"] and result["callContext"]["call"] is None
        assert not result["callContext"]["permissions"]["incoming_call_state"]
    else:
        assert result == {"ok": False, "code": "not_granted"}
    assert not events and not channel.sent


def test_private_daemon_call_read_does_not_take_mutation_lock_or_start_transport(tmp_path, monkeypatch):
    from types import SimpleNamespace
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    body = event(); service._payload(peer, channel, message("incoming_call_state.event", body))
    events.clear(); channel.sent.clear()
    path = str(tmp_path / "runtime" / "background.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    original_setup = server.setup_sessions
    try:
        assert server._mutation_lock.acquire(timeout=0.5)
        try:
            server.setup_sessions = SimpleNamespace(connecting_transport="wifi")
            value = background.ipc_request("phone_mcp_action", {"request": dict(action="call_context_read", peerId=peer["device_id"],
                fingerprint=phone.fingerprint(phone.unb64(peer["static_public"], 32)))}, path, timeout=1)
        finally:
            server.setup_sessions = original_setup; server._mutation_lock.release()
        assert value["ok"] and value["callContext"]["call"]["call_ref"] == body["call_ref"]
        assert value["callContext"]["call"]["revision"] == "9007199254740993"
        assert not events and not channel.sent and service.server is None
    finally:
        server.setup_sessions = original_setup; server.close()


def test_private_call_read_rejects_caller_provenance_and_unrelated_fields():
    request = dict(action="call_context_read", peerId=str(uuid4()), fingerprint="ABCD-1234-5678-90EF", native_received_ms=123)
    with pytest.raises(background.IPCError): background._request_shape("phone_mcp_action", {"request": request})
