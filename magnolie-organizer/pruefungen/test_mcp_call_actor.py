"""Owner-bound command orchestration through the existing native call handlers."""
import copy
import threading
from uuid import uuid4

import pytest
from test_mcp_call_context import fixture, event, read
from test_time_sync_runtime import message
import magnolie_telefon as phone
import magnolie_hintergrund as background
from test_mcp_phone import FakeBackend


def reserve(service, peer, command="dial", call=None, proxy=None):
    context = read(service, peer)["callContext"]
    request = dict(action="call_actor_create", peerId=peer["device_id"], fingerprint=context["fingerprint"],
        sourceRevision=context["source_revision"], operationId=str(uuid4()), command=command,
        destination="+49301234567" if command == "dial" else "", callRef=call["call_ref"] if call else "",
        callRevision=str(call["revision"]) if call else "")
    created = (proxy.mcp_action if proxy else service.mcp_action)(request)
    assert created["ok"], created
    return request, created["callActorHandle"]


def owner_request(service, request, handle, action):
    return service.mcp_action(dict(action=action, peerId=request["peerId"], fingerprint=request["fingerprint"],
        actorId=handle["actor_id"], ownerToken=handle["owner_token"]))


def test_reservation_and_cancel_have_no_call_or_command_write(tmp_path, monkeypatch):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    request, handle = reserve(service, peer)
    assert not channel.sent and not events and not service.store.command_state(request["operationId"])
    cancelled = owner_request(service, request, handle, "call_actor_cancel")
    assert cancelled["ok"] and cancelled["callActor"]["phase"] == "cancelled"
    assert not cancelled["callActor"]["dispatch_started"] and not cancelled["callActor"]["remote_recall_confirmed"]
    assert not owner_request(service, request, handle, "call_actor_start")["ok"]
    assert not channel.sent and not service.store.command_state(request["operationId"])


@pytest.mark.parametrize("command", ["dial", "answer", "end"])
def test_native_start_requires_actual_correlated_phone_result_outside_source_guard(tmp_path, monkeypatch, command):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    call = None
    if command != "dial":
        call = event()
        if command == "end": call.update(state="offhook", offhook_ms=call["started_ms"])
        service._payload(peer, channel, message("incoming_call_state.event", call))
        channel.sent.clear(); events.clear()
    request, handle = reserve(service, peer, command, call)
    sent = threading.Event(); wires = []
    def send(wire):
        channel.sent.append(copy.deepcopy(wire))
        if wire.get("kind") not in ("dial_request.command", "answer_call.command", "end_call.command"):
            return
        assert not service.lock._is_owned(), "Private command network send held the native source guard"
        wires.append(copy.deepcopy(wire)); sent.set()
    channel.send = send
    started = owner_request(service, request, handle, "call_actor_start")
    assert started["ok"] and sent.wait(3), started
    status = owner_request(service, request, handle, "call_actor_status")["callActor"]
    assert status["phase"] == "awaiting_phone" and status["dispatch_started"] and status["receipt_persisted"]
    assert not status["phone_result_received"] and status["phone_result"] is None
    # A transport ACK cannot satisfy a call command.
    service._payload(peer, channel, dict(type="ack", message_id=wires[0]["message_id"], status="accepted", error="none"))
    assert not owner_request(service, request, handle, "call_actor_status")["callActor"]["phone_result_received"]
    body = dict(state="submitted", error="none", occurred_ms=phone.now_ms())
    if command == "dial": body["client_ref"] = request["operationId"]
    else: body.update(command_ref=request["operationId"], call_ref=call["call_ref"])
    service._payload(peer, channel, message(wires[0]["kind"].replace(".command", ".result"), body))
    reported = owner_request(service, request, handle, "call_actor_status")["callActor"]
    assert reported["phase"] == "reported" and reported["phone_result_received"] and reported["phone_result"] == body
    assert service.store.command_origin(peer["device_id"], request["operationId"]) == "mcp"
    assert not any(kind in ("dial_status", "answer_status", "end_status") for kind, _ in events)
    assert len(wires) == 1


def test_foreign_owner_and_replaced_source_cannot_dispatch_reserved_command(tmp_path, monkeypatch):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    request, handle = reserve(service, peer)
    wrong = dict(handle, owner_token="0" * 64)
    assert owner_request(service, request, wrong, "call_actor_start") == {"ok": False, "code": "not_found"}
    service.connections.pop(peer["device_id"])
    assert not owner_request(service, request, handle, "call_actor_start")["ok"]
    assert not channel.sent and not events and not service.store.command_state(request["operationId"])


def test_cancel_after_dispatch_ignores_late_result_and_never_replays_to_gui(tmp_path, monkeypatch):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    request, handle = reserve(service, peer)
    sent = threading.Event(); wires = []
    def send(wire):
        channel.sent.append(copy.deepcopy(wire))
        if wire.get("kind") == "dial_request.command": wires.append(copy.deepcopy(wire)); sent.set()
    channel.send = send
    assert owner_request(service, request, handle, "call_actor_start")["ok"] and sent.wait(3)
    cancelled = owner_request(service, request, handle, "call_actor_cancel")["callActor"]
    assert cancelled["phase"] == "cancelled" and cancelled["native_outcome_unknown"] and not cancelled["remote_recall_confirmed"]
    result = dict(client_ref=request["operationId"], state="submitted", error="none", occurred_ms=phone.now_ms())
    service._payload(peer, channel, message("dial_request.result", result))
    assert owner_request(service, request, handle, "call_actor_status")["callActor"]["phone_result"] is None
    service._send_message(channel, peer["device_id"], wires[0])
    assert len(wires) == 1 and not any(kind == "dial_status" for kind, _ in events)


def test_private_dial_does_not_enable_gui_call_monitoring_grants(tmp_path, monkeypatch):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    for name in ("incoming_call_state", "end_call"):
        peer["local_grants"]["grants"][name] = False
    before = copy.deepcopy(peer["local_grants"])
    request, handle = reserve(service, peer)
    sent = threading.Event()
    channel.send = lambda wire: sent.set() if wire.get("kind") == "dial_request.command" else None
    assert owner_request(service, request, handle, "call_actor_start")["ok"] and sent.wait(3)
    assert peer["local_grants"] == before and not events
    owner_request(service, request, handle, "call_actor_cancel")


def test_reservation_limits_and_expiry_release_active_capacity_without_dispatch(tmp_path, monkeypatch):
    import magnolie_call_actors as actors
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    reservations = [reserve(service, peer) for _ in range(4)]
    context = read(service, peer)["callContext"]
    extra = dict(reservations[0][0], operationId=str(uuid4()), sourceRevision=context["source_revision"])
    assert service.mcp_action(extra) == {"ok": False, "code": "native_busy"}
    now = actors.time.monotonic()
    monkeypatch.setattr(actors.time, "monotonic", lambda: now + 16)
    expired = owner_request(service, *reservations[0], "call_actor_status")["callActor"]
    assert expired["phase"] == "failed" and expired["error_code"] == "native_timeout"
    assert service.mcp_action(extra)["ok"]
    assert not channel.sent and not events and not service.store.command_state(reservations[0][0]["operationId"])


def test_daemon_actor_cancel_and_status_bypass_transport_setup_and_mutation_lock(tmp_path, monkeypatch):
    from types import SimpleNamespace
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    path = str(tmp_path / "runtime" / "background.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path=path); original_setup = server.setup_sessions
    sent = threading.Event(); channel.send = lambda wire: sent.set() if wire.get("kind") == "dial_request.command" else None
    try:
        request, handle = reserve(service, peer, proxy=proxy)
        command = dict(action="call_actor_start", peerId=request["peerId"], fingerprint=request["fingerprint"], actorId=handle["actor_id"], ownerToken=handle["owner_token"])
        assert proxy.mcp_action(command)["ok"] and sent.wait(3)
        assert server._mutation_lock.acquire(timeout=0.5)
        try:
            server.setup_sessions = SimpleNamespace(connecting_transport="wifi")
            status = background.ipc_request("phone_mcp_action", {"request": dict(command, action="call_actor_status")}, path, timeout=1)
            assert status["ok"] and status["callActor"]["phase"] == "awaiting_phone"
            cancelled = background.ipc_request("phone_mcp_action", {"request": dict(command, action="call_actor_cancel")}, path, timeout=1)
            assert cancelled["ok"] and cancelled["callActor"]["cancel_requested"]
        finally:
            server.setup_sessions = original_setup; server._mutation_lock.release()
        assert proxy._event_thread is None and service.server is None and not events
    finally:
        server.setup_sessions = original_setup; server.close()


@pytest.mark.parametrize("change", ["call_event", "grant_withdrawn"])
def test_result_reauthorization_accepts_real_call_progress_but_not_permission_changes(tmp_path, monkeypatch, change):
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    request, handle = reserve(service, peer)
    sent = threading.Event(); channel.send = lambda wire: sent.set() if wire.get("kind") == "dial_request.command" else None
    assert owner_request(service, request, handle, "call_actor_start")["ok"] and sent.wait(3)
    if change == "call_event":
        progressed = event(); progressed.update(call_ref=request["operationId"], state="offhook", direction="outgoing", offhook_ms=progressed["started_ms"])
        service._payload(peer, channel, message("incoming_call_state.event", progressed))
    else:
        peer["local_grants"]["grants"]["dial_request"] = False
    events.clear()
    body = dict(client_ref=request["operationId"], state="submitted", error="none", occurred_ms=phone.now_ms())
    service._payload(peer, channel, message("dial_request.result", body))
    status = owner_request(service, request, handle, "call_actor_status")["callActor"]
    if change == "call_event":
        assert status["phase"] == "reported" and status["phone_result"] == body
    else:
        assert status["phase"] == "failed" and status["error_code"] == "source_changed" and status["phone_result"] is None
        assert status["native_outcome_unknown"]
    assert not any(kind == "dial_status" for kind, _ in events)


def test_stale_creation_and_restart_cannot_adopt_an_existing_command_as_a_new_owner(tmp_path, monkeypatch):
    from magnolie_call_actors import NativeCallActors
    service, peer, channel, events = fixture(tmp_path, monkeypatch)
    request, handle = reserve(service, peer)
    stale = dict(request, sourceRevision="0" * 64, operationId=str(uuid4()))
    assert service.mcp_action(stale) == {"ok": False, "code": "source_changed"}
    assert not channel.sent and not service.store.command_state(stale["operationId"])
    sent = threading.Event(); channel.send = lambda wire: sent.set() if wire.get("kind") == "dial_request.command" else None
    assert owner_request(service, request, handle, "call_actor_start")["ok"] and sent.wait(3)
    # A new native owner registry must not adopt a retained effect row, even
    # when the caller repeats the same operation UUID and current source token.
    service.call_actors = NativeCallActors(service)
    service.private_call_result_observer = service.call_actors.receive
    repeated = dict(request, sourceRevision=read(service, peer)["callContext"]["source_revision"])
    assert service.mcp_action(repeated) == {"ok": False, "code": "conflict"}
    assert owner_request(service, request, handle, "call_actor_status") == {"ok": False, "code": "not_found"}
    assert not any(kind == "dial_status" for kind, _ in events)
