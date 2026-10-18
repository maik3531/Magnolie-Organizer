"""Fresh correlated status reads with synthetic peers; no phone/listener/hardware."""
import copy
import ast
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid
from types import SimpleNamespace, MethodType

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
from test_telefon import _complete_peer, FakeBluetooth
from test_device_identifiers import Channel, response as identifier_report
import magnolie_hintergrund as background
from test_hintergrunddienst import FakeBackend


@pytest.fixture
def owned(tmp_path, monkeypatch):
    events = []
    service = phone.PhoneService(str(tmp_path / "owned-phone"), "Owned desktop", callback=lambda *args: events.append(args), bluetooth_backend=FakeBluetooth())
    peer = _complete_peer("11111111-1111-4111-8111-111111111111")
    peer["capabilities"] = phone.desktop_capabilities()
    peer["capabilities"]["items"]["device_status"] = {"available": True, "versions": [1, 2, 3, 4]}
    peer["grants"]["grants"]["device_status"] = True
    peer["local_grants"]["grants"]["device_status"] = True
    peer["personal_sync"].update(own_device=True, remote_own_device=True)
    service.store.peers = [peer]; service.store.save_peers(); service.enabled = True
    channel = Channel(); service.connections[peer["device_id"]] = channel; service.connection_transports[peer["device_id"]] = "wifi"
    service.note_controls[channel] = {"capabilities.update": copy.deepcopy(peer["capabilities"]), "grants.update": copy.deepcopy(peer["grants"]),
        "personal_sync.settings": {"format": 1, "own_device": True}}
    service.store.status(peer["device_id"])
    def forbidden(*_args, **_kwargs):
        raise AssertionError("A scoped MCP read must not persist/replay status or alter GUI identifiers")
    for name in ("queue", "cache_status", "register_status_request"):
        monkeypatch.setattr(service.store, name, forbidden)
    monkeypatch.setattr(service, "_purge_identifiers", forbidden)
    return service, peer, channel, events


def start_read(owned, include=False):
    service, peer, channel, _events = owned
    request = str(uuid.uuid4()); outcome = {}
    def run():
        try:
            outcome["token"] = service.read_device_status(peer["device_id"], phone.fingerprint(phone.unb64(peer["static_public"], 32)), include, request,
                expected_revision=service.mcp_status(include_bluetooth=False)["revision"])
        except BaseException as error:
            outcome["error"] = error
    thread = threading.Thread(target=run, daemon=True); thread.start()
    deadline = time.monotonic() + 3
    while not any(value.get("kind") == "device_status.request" for value in channel.sent) and thread.is_alive():
        assert time.monotonic() < deadline
        time.sleep(0.005)
    return request, thread, outcome


def report(request, identifiers=False):
    if identifiers:
        return identifier_report(request)
    body = json.loads((Path(__file__).parent / "telefon-control-contract.json").read_text())["device_status_v3"]
    body.update(request_id=request, captured_ms=phone.now_ms())
    now = phone.now_ms()
    return {"type": "message", "v": 1, "message_id": str(uuid.uuid4()), "kind": "device_status.report",
        "created_ms": now, "expires_ms": now + 60000, "body": body}


def finish(owned, request, thread, outcome, identifiers=False):
    service, peer, channel, _events = owned
    service._payload(peer, channel, report(request, identifiers)); thread.join(3)
    assert not thread.is_alive() and "error" not in outcome, outcome
    return service.current_mcp_device_status(outcome["token"])


def test_default_query_does_not_inherit_gui_identifier_permission_or_touch_status_cache(owned):
    service, peer, channel, events = owned
    request, thread, outcome = start_read(owned)
    assert channel.sent[0]["body"] == {"request_id": request, "version": 3}
    value = finish(owned, request, thread, outcome)
    assert value["source_verified"] is True and value["request_correlated"] is True and value["persisted"] is False
    assert value["include_identifiers"] is False and "identifiers" not in value["report"] and not events
    assert service.store.status(peer["device_id"]) == {} and not service.transient_identifiers and not service.identifier_requests
    with sqlite3.connect(service.store.database_path) as database:
        assert database.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'status_request:%'").fetchone()[0] == 0
    service._payload(peer, channel, report(request))
    assert channel.sent[-1]["status"] == "rejected" and not events


def test_explicit_identifiers_are_ephemeral_and_current_result_is_consumed_once(owned):
    service, peer, channel, events = owned
    request, thread, outcome = start_read(owned, True)
    assert channel.sent[0]["body"] == {"request_id": request, "version": 4, "include_identifiers": True}
    value = finish(owned, request, thread, outcome, True)
    assert value["report"]["identifiers"]["imei"]["value"] == "000000000000001"
    assert phone.now_ms() < value["expires_ms"] <= phone.now_ms() + 60000 and not events
    with pytest.raises(PermissionError): service.current_mcp_device_status(request)
    assert not service.transient_identifiers and not service.identifier_requests
    service._payload(peer, channel, report(request, True))
    assert channel.sent[-1]["status"] == "rejected" and not events and service.store.status(peer["device_id"]) == {}


@pytest.mark.parametrize("change", ["own_off", "remote_off", "grant_off", "channel_changed", "peer_changed", "expired"])
def test_identifier_permission_and_source_rechecked_when_dispatching_result(owned, change):
    service, peer, channel, events = owned
    request, thread, outcome = start_read(owned, True)
    service._payload(peer, channel, report(request, True)); thread.join(3)
    assert not thread.is_alive() and "token" in outcome, outcome
    if change == "own_off": peer["personal_sync"]["own_device"] = False
    elif change == "remote_off": peer["personal_sync"]["remote_own_device"] = False
    elif change == "grant_off": peer["grants"]["grants"]["device_status"] = False
    elif change == "channel_changed": service.connections[peer["device_id"]] = Channel()
    elif change == "peer_changed": peer["static_public"] = phone.b64(b"n" * 32)
    else: service.mcp_status_results[request]["deadline"] = time.monotonic() - 1
    with pytest.raises(PermissionError): service.current_mcp_device_status(request)
    assert not service.mcp_status_results and not events


def test_cancelled_query_rejects_late_identifiers_without_legacy_gui_callbacks(owned):
    service, peer, channel, events = owned
    request, thread, outcome = start_read(owned, True)
    assert service.cancel_device_status(peer["device_id"], phone.fingerprint(phone.unb64(peer["static_public"], 32)), request)
    thread.join(3)
    assert not thread.is_alive() and isinstance(outcome.get("error"), PermissionError)
    service._payload(peer, channel, report(request, True))
    assert channel.sent[-1]["status"] == "rejected" and not events and not service.mcp_status_results


def test_basic_status_does_not_require_own_device_but_identifiers_do(owned):
    service, peer, channel, events = owned
    peer["personal_sync"].update(own_device=False, remote_own_device=False)
    request, thread, outcome = start_read(owned)
    assert finish(owned, request, thread, outcome)["include_identifiers"] is False
    with pytest.raises(PermissionError):
        service.read_device_status(peer["device_id"], phone.fingerprint(phone.unb64(peer["static_public"], 32)), True)
    assert not events


def control_request(service, peer, query, include=True):
    return {"action": "device_status_query", "expectedRevision": service.mcp_status(include_bluetooth=False)["revision"],
        "peerId": peer["device_id"], "fingerprint": phone.fingerprint(phone.unb64(peer["static_public"], 32)),
        "queryId": query, "includeIdentifiers": include}


def wait_request(channel, worker):
    deadline = time.monotonic() + 3
    while not any(value.get("kind") == "device_status.request" for value in channel.sent) and worker.is_alive():
        assert time.monotonic() < deadline
        time.sleep(0.005)


def proxy_query(proxy, request, result):
    try:
        result.update(proxy.mcp_action(request))
    except BaseException as error:
        result["error"] = error


def test_daemon_query_and_one_use_result_do_not_subscribe_replay_or_start_listener(owned, tmp_path):
    service, peer, channel, events = owned
    path = str(tmp_path / "runtime" / "background.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path=path)
    query, result = str(uuid.uuid4()), {}
    request = control_request(service, peer, query)
    worker = threading.Thread(target=proxy_query, args=(proxy, request, result), daemon=True)
    try:
        worker.start(); wait_request(channel, worker)
        service._payload(peer, channel, report(query, True)); worker.join(3)
        assert not worker.is_alive() and result.get("ok") is True and result["deviceStatusToken"] == query
        assert "000000000000001" not in json.dumps(result), "Raw identifiers must not be queued before dispatch-time revalidation"
        current = proxy.mcp_device_status_result(query)
        assert current["ok"] is True and current["deviceStatus"]["report"]["identifiers"]["imei"]["value"] == "000000000000001"
        assert proxy.mcp_device_status_result(query)["ok"] is False
        assert proxy._event_thread is None and service.server is None and not events
    finally:
        service.cancel_device_status(peer["device_id"], request["fingerprint"], query); worker.join(3); server.close()


def test_daemon_cancel_is_not_blocked_by_mutation_lock_or_transport_setup(owned, tmp_path):
    service, peer, channel, events = owned
    path = str(tmp_path / "runtime" / "background.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path=path)
    query, result = str(uuid.uuid4()), {}
    request = control_request(service, peer, query)
    worker = threading.Thread(target=proxy_query, args=(proxy, request, result), daemon=True)
    original_setup = server.setup_sessions
    try:
        worker.start(); wait_request(channel, worker)
        acquired = server._mutation_lock.acquire(timeout=0.5)
        assert acquired, "A read query must not occupy the transport mutation lock"
        try:
            server.setup_sessions = SimpleNamespace(connecting_transport="wifi")
            cancelled = background.ipc_request("phone_mcp_action", {"request": {**request, "action": "device_status_cancel"}}, path, timeout=1)
            assert cancelled["ok"] is True and cancelled["cancelled"] is True
        finally:
            server.setup_sessions = original_setup
            server._mutation_lock.release()
        worker.join(3)
        assert not worker.is_alive() and result == {"ok": False, "code": "cancelled"} and not events
        service._payload(peer, channel, report(query, True))
        assert channel.sent[-1]["status"] == "rejected" and not events
    finally:
        server.setup_sessions = original_setup
        service.cancel_device_status(peer["device_id"], request["fingerprint"], query); worker.join(3); server.close()


@pytest.mark.parametrize("change", ["valid", "own_revoked", "locked", "owner_changed", "expired"])
def test_native_window_queues_only_token_then_rechecks_identifiers_at_dispatch(owned, change):
    service, peer, channel, events = owned
    tree = ast.parse((Path(__file__).resolve().parents[1] / "bin/magnolie-organizer").read_text())
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Fenster")
    method = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == "_telefon_mcp")
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "owned-native-status-window", "exec"), namespace)
    queued = []
    owner = SimpleNamespace(_telefon=service, _gesperrt=False, _organizer_vertraut=lambda: True,
        _telefon_dienst_pflegen=lambda **_kwargs: None, antwort=lambda callback, value: queued.append((callback, value)))
    owner._telefon_mcp = MethodType(namespace["_telefon_mcp"], owner)
    query = str(uuid.uuid4()); request = control_request(service, peer, query)
    worker = threading.Thread(target=owner._telefon_mcp, args=({"requestId": str(uuid.uuid4()), "request": request},), daemon=True)
    try:
        worker.start(); wait_request(channel, worker)
        service._payload(peer, channel, report(query, True)); worker.join(3)
        assert not worker.is_alive() and len(queued) == 1 and callable(queued[0][1]), "Raw identifiers were queued instead of a dispatch-time resolver"
        if change == "own_revoked": peer["personal_sync"]["own_device"] = False
        elif change == "locked": owner._gesperrt = True
        elif change == "owner_changed": owner._telefon = SimpleNamespace()
        elif change == "expired": service.mcp_status_results[query]["deadline"] = time.monotonic() - 1
        value = queued[0][1]()
        assert value["ok"] is (change == "valid")
        assert ("000000000000001" in json.dumps(value)) is (change == "valid")
        assert not service.mcp_status_results and not events
    finally:
        service.cancel_device_status(peer["device_id"], request["fingerprint"], query); worker.join(3)
