"""Synthetic v4 privacy tests. No hardware or existing user profile is queried."""
import copy
import ast
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import tempfile
import uuid
from types import MethodType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_telefon as phone


class Channel:
    def __init__(self): self.sent = []
    def send(self, value): self.sent.append(value)


@pytest.fixture
def setup(tmp_path):
    events = []
    service = phone.PhoneService(str(tmp_path / "telefon"), "Synthetic desktop", lambda e, p: events.append((e, p)))
    peer = {"device_id": str(uuid.uuid4()), "display_name": "Fixture", "static_public": phone.b64(os.urandom(32)),
        "state": "paired", "capabilities": phone.desktop_capabilities(), "grants": phone.desktop_grants(),
        "local_grants": phone.desktop_grants(), "last_contact_ms": 0,
        "personal_sync": {"own_device": True, "remote_own_device": True, "auto_wifi": False}}
    service.store.peers.append(peer); service.store.save_peers()
    channel = Channel(); service.connections[peer["device_id"]] = channel
    return service, peer, channel, events


def response(request_id):
    body = json.loads((ROOT / "pruefungen/telefon-control-contract.json").read_text())["device_status_v3"]
    body.update(request_id=request_id, version=4, captured_ms=phone.now_ms(), identifiers={
        "phone_number": {"status": "permission_missing", "value": ""},
        "serial": {"status": "os_restricted", "value": ""},
        "imei": {"status": "available", "value": "000000000000001"}})
    now = phone.now_ms()
    return {"type": "message", "v": 1, "message_id": str(uuid.uuid4()), "kind": "device_status.report",
        "created_ms": now, "expires_ms": now + 60000, "body": body}


@pytest.mark.parametrize("proxy", [False, True])
@pytest.mark.parametrize("change", ["valid", "revoked", "new-request", "new-report", "old-response", "duplicate-response", "expired", "disconnected", "locked", "resolver-failed"])
def test_native_ui_queue_rechecks_identifiers_at_dispatch(setup, monkeypatch, change, proxy, request):
    service, peer, channel, events = setup
    transport = service
    if proxy:
        import magnolie_hintergrund as background
        directory = tempfile.TemporaryDirectory(prefix="id-ui-")
        request.addfinalizer(directory.cleanup)
        path = str(Path(directory.name) / "runtime/background.sock")
        server = background.IPCServer(SimpleNamespace(), path, phone_backend=service).start()
        request.addfinalizer(server.close)
        transport = background.PhoneServiceProxy(path=path)
    request_id = str(uuid.uuid4())
    assert transport.request_status(peer["device_id"], request_id=request_id) == request_id
    assert channel.sent[-1]["body"]["request_id"] == request_id
    service._payload(peer, channel, response(request_id))
    payload = events[-1][1]
    tree = ast.parse((ROOT / "bin/magnolie-organizer").read_text())
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Fenster")
    names = {"antwort", "sende_js", "_telefon_ereignis"}
    nodes = [node for node in window.body if isinstance(node, ast.FunctionDef) and node.name in names]
    nodes += [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "js_zeichenkette"]
    queued, scripts = [], []
    namespace = dict(json=json, GLib=SimpleNamespace(idle_add=lambda callback: queued.append(callback)),
                     without_device_identifiers=phone.without_device_identifiers)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "native-identifier-ui", "exec"), namespace)
    owner = SimpleNamespace(_telefon=transport, _gesperrt=False, _chromium=None,
        _organizer_vertraut=lambda: True, _telefon_stand_melden=lambda: None,
        ansicht=SimpleNamespace(evaluate_javascript=lambda script, *_: scripts.append(script)))
    for name in names: setattr(owner, name, MethodType(namespace[name], owner))
    owner._telefon_ereignis("device_status", payload)
    assert queued and not scripts
    if change == "revoked": service.set_personal_sync(peer["device_id"], False)
    elif change in ("new-request", "new-report", "old-response", "duplicate-response"):
        next_request = str(uuid.uuid4())
        transport.request_status(peer["device_id"], request_id=next_request)
        if change in ("new-report", "duplicate-response"):
            service._payload(peer, channel, response(next_request))
        if change in ("old-response", "duplicate-response"):
            service._payload(peer, channel, response(request_id if change == "old-response" else next_request))
            assert channel.sent[-1]["status"] == "rejected"
    elif change == "expired":
        expired = service.transient_identifiers[peer["device_id"]][5] + 1
        monkeypatch.setattr(phone.time, "monotonic", lambda: expired)
    elif change == "disconnected": service.connections.clear()
    elif change == "locked": owner._gesperrt = True
    elif change == "resolver-failed":
        def unavailable(_): raise RuntimeError("synthetic resolver failure")
        monkeypatch.setattr(transport, "current_identifier_event", unavailable)
    while queued: queued.pop(0)()
    assert bool(scripts) and any("000000000000001" in script for script in scripts) is (change == "valid")
    if change in ("new-request", "new-report", "old-response", "duplicate-response"):
        if change in ("new-request", "old-response"):
            assert service.identifier_requests.get(peer["device_id"], (None,))[0] == next_request
            service._payload(peer, channel, response(next_request))
            assert channel.sent[-1]["status"] == "accepted"
        assert service.transient_identifiers.get(peer["device_id"], (None, None, None))[2] == next_request
        owner._telefon_ereignis("device_status", events[-1][1])
        while queued: queued.pop(0)()
        assert "000000000000001" in scripts[-1] and next_request in scripts[-1]


@pytest.mark.parametrize("request_id", ["", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_bad_ui_request_identity_never_sends_or_reserves(setup, request_id):
    service, peer, channel, _ = setup
    with pytest.raises(ValueError): service.request_status(peer["device_id"], request_id=request_id)
    assert not channel.sent and not service.identifier_requests


def test_matching_encrypted_transport_and_no_persistent_ids(setup):
    service, peer, channel, events = setup
    request = service.request_status(peer["device_id"])
    assert channel.sent[-1]["body"] == {"request_id": request, "version": 4, "include_identifiers": True}
    assert not service.store.pending(peer["device_id"])
    message = response(request)
    service._payload(peer, channel, message)
    assert channel.sent[-1]["status"] == "accepted"
    assert events[-1][1]["status"]["identifiers"]["imei"]["value"].startswith("0")
    assert "identifiers" not in service.store.status(peer["device_id"])
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    # Even direct callers of the durable storage boundary cannot retain the extension.
    service.store.remember_message(peer["device_id"], message, "accepted", "none")
    with sqlite3.connect(service.store.database_path) as db:
        raw = db.execute("SELECT payload FROM inbox").fetchone()[0]
    assert "identifiers" not in phone.strict_json(service.store._decrypt(raw, "inbox", message["message_id"]))["body"]
    with pytest.raises(ValueError): service.store.queue(peer["device_id"], "device_status.report", message["body"], 60000)
    # The real channel encrypts all v4 bodies; no plaintext serial/number exception.
    class Socket:
        def sendall(self, value): self.value = value
    sock = Socket()
    secure = phone.SecureChannel(sock, b"s" * 16, b"k" * 32, b"p" * 4, b"r" * 32, b"q" * 4)
    secure.send(message)
    assert b'"identifiers"' not in sock.value


@pytest.mark.parametrize("change", ["unsolicited", "wrong_request", "late", "own_off", "remote_off", "grant_off", "sharing_off", "peer_changed", "channel_changed"])
def test_late_or_unconsented_reports_are_rejected(setup, change):
    service, peer, channel, events = setup
    request = str(uuid.uuid4()) if change == "unsolicited" else service.request_status(peer["device_id"])
    message = response(request)
    if change == "wrong_request": message["body"]["request_id"] = str(uuid.uuid4())
    if change == "late":
        ticket = service.identifier_requests[peer["device_id"]]
        service.identifier_requests[peer["device_id"]] = (*ticket[:3], time.monotonic() - 1, ticket[4])
    if change == "own_off": service._set_personal_sync(peer["device_id"], False); service._set_personal_sync(peer["device_id"], True)
    if change == "remote_off": peer["personal_sync"]["remote_own_device"] = False
    if change == "grant_off": peer["grants"]["grants"]["device_status"] = False
    if change == "sharing_off": peer["capabilities"]["items"]["device_status"]["versions"] = [1, 2, 3]
    if change == "peer_changed": peer = dict(peer, static_public=phone.b64(os.urandom(32)))
    if change == "channel_changed": service.connections[peer["device_id"]] = Channel()
    events.clear(); service._payload(peer, channel, message)
    assert channel.sent[-1]["status"] == "rejected"
    assert not service.transient_identifiers
    assert not any(e == "device_status" for e, _ in events)


def test_exact_fields_and_independent_statuses(setup):
    body = response(str(uuid.uuid4()))["body"]
    phone.validate_device_status(body)
    for key, value in [("imei", {"status": "available", "value": 1}), ("serial", {"status": "unavailable", "value": "bad"}),
                       ("phone_number", {"status": "available", "value": "a" * 65})]:
        invalid = copy.deepcopy(body); invalid["identifiers"][key] = value
        with pytest.raises(ValueError): phone.validate_device_status(invalid)
    invalid = copy.deepcopy(body); invalid["identifiers"]["extra"] = {}
    with pytest.raises(ValueError): phone.validate_device_status(invalid)
    invalid = copy.deepcopy(body); del invalid["version"]
    with pytest.raises(ValueError): phone.validate_device_status(invalid)


def test_delayed_background_event_rechecks_consent(setup):
    service, peer, channel, events = setup
    service._payload(peer, channel, response(service.request_status(peer["device_id"])))
    value = events[-1][1]
    assert "identifiers" in service.current_identifier_event(value)["status"]
    peer["personal_sync"]["own_device"] = False
    assert "identifiers" not in service.current_identifier_event(value)["status"]


def test_false_request_never_accepts_identifier_values(setup):
    service, peer, channel, events = setup
    service._payload(peer, channel, response(service.request_status(peer["device_id"], False)))
    assert channel.sent[-1]["status"] == "rejected"
    report = response(service.request_status(peer["device_id"], False))
    report["body"]["identifiers"] = {name: {"status": "not_shared", "value": ""} for name in ("phone_number", "serial", "imei")}
    service._payload(peer, channel, report)
    assert channel.sent[-1]["status"] == "accepted"
