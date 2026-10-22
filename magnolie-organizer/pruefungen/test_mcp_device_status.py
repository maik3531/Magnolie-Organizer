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


def start_read(owned, include=False, time_zone=False):
    service, peer, channel, _events = owned
    request = str(uuid.uuid4()); outcome = {}
    def run():
        try:
            outcome["token"] = service.read_device_status(peer["device_id"], phone.fingerprint(phone.unb64(peer["static_public"], 32)), include, request,
                expected_revision=service.mcp_status(include_bluetooth=False)["revision"], time_zone=time_zone)
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


def timezone_peer(owned, transport="wifi"):
    service, peer, channel, _events = owned
    peer["capabilities"]["items"]["device_status"]["versions"].append(12)
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    service.connection_transports[peer["device_id"]] = transport
    return service, peer, channel


def timezone_report(request, zone="Asia/Tokyo"):
    packet = report(request)
    packet["body"] = {"version": 12, "request_id": request, "state": "available" if zone else "unavailable", "time_zone": zone, "captured_ms": phone.now_ms()}
    return packet


@pytest.mark.parametrize("transport", ["wifi", "bluetooth"])
def test_own_timezone_read_is_correlated_readonly_and_has_actual_transport(owned, transport):
    service, peer, channel = timezone_peer(owned, transport)
    request, worker, outcome = start_read(owned, time_zone=True)
    assert channel.sent[0]["body"] == {"request_id": request, "version": 12}
    service._payload(peer, channel, timezone_report(request)); worker.join(3)
    assert not worker.is_alive() and "error" not in outcome, outcome
    result = service.current_mcp_device_status(outcome["token"])
    assert result["protocol_version"] == 12 and result["transport"] == transport
    assert result["report"]["time_zone"] == "Asia/Tokyo" and len(result["report"]) == 5
    assert result["include_identifiers"] is False and result["persisted"] is False and not owned[3]
    assert service.store.status(peer["device_id"]) == {}
    if transport == "bluetooth":
        assert service._mcp_status_peer(peer["device_id"]) is None, "Timezone support must not widen ordinary WiFi-only MCP status access"
    service._payload(peer, channel, timezone_report(request))
    assert channel.sent[-1]["status"] == "rejected" and not owned[3]


@pytest.mark.parametrize("change", ["own_off", "remote_off", "no_fresh_own", "legacy"])
def test_unowned_stale_or_legacy_phone_is_not_queried_for_timezone(owned, change):
    service, peer, channel = timezone_peer(owned)
    if change == "own_off": peer["personal_sync"]["own_device"] = False
    elif change == "remote_off": peer["personal_sync"]["remote_own_device"] = False
    elif change == "no_fresh_own": service.note_controls[channel].pop("personal_sync.settings")
    else:
        peer["capabilities"]["items"]["device_status"]["versions"].remove(12)
        service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    assert service.read_own_time_zone() is None and channel.sent == []


def test_timezone_ownership_is_rechecked_after_native_receipt(owned):
    service, peer, channel = timezone_peer(owned)
    request, worker, outcome = start_read(owned, time_zone=True)
    service._payload(peer, channel, timezone_report(request)); worker.join(3)
    assert not worker.is_alive() and "token" in outcome
    peer["personal_sync"]["own_device"] = False
    with pytest.raises(PermissionError): service.current_mcp_device_status(outcome["token"])
    assert not service.mcp_status_results and not owned[3]


def test_daemon_timezone_read_does_not_start_subscriber_or_persist_status(owned, tmp_path):
    service, peer, channel = timezone_peer(owned, "bluetooth")
    path = str(tmp_path / "runtime" / "timezone.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path=path)
    outcome = {}
    def read():
        try: outcome["result"] = proxy.read_own_time_zone()
        except BaseException as error: outcome["error"] = error
    worker = threading.Thread(target=read, daemon=True)
    try:
        worker.start(); wait_request(channel, worker)
        request = next(value for value in channel.sent if value.get("kind") == "device_status.request")["body"]["request_id"]
        service._payload(peer, channel, timezone_report(request)); worker.join(3)
        assert not worker.is_alive() and "error" not in outcome, outcome
        assert outcome["result"]["zone"] == "Asia/Tokyo" and proxy._event_thread is None and service.server is None
        assert not service.mcp_status_results and service.store.status(peer["device_id"]) == {} and not owned[3]
        with sqlite3.connect(service.store.database_path) as database:
            for table in ("inbox", "outbox"):
                assert database.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
    finally:
        worker.join(3); server.close()


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
