import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_hintergrund as background
import magnolie_telefon as telephone
from magnolie_setup_state import SetupPhoneServices, PhoneSetupSessions, write_state, classify


@pytest.fixture
def owner(tmp_path, monkeypatch):
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        folder = tmp_path / key
        folder.mkdir(mode=0o700)
        monkeypatch.setenv(key, str(folder))
    monkeypatch.setattr(telephone, "PORT", 0)
    class Radio:
        def availability(self): return False, "no_hardware"
        def paired_devices(self): return []
    normal = []
    phone = telephone.PhoneService(str(tmp_path / "phone"), "Fixture", bluetooth_backend=Radio())
    phone._publish = lambda: None
    phone.enabled = True
    settings = background.normalize_settings({"enabled": True, "permissions": {"phone_monitor": True, "phone_call_notifications": True}})
    # pytest's descriptive paths can exceed sockaddr_un.sun_path in a sandbox.
    with tempfile.TemporaryDirectory(prefix="mo-setup-", dir="/tmp") as runtime:
        server = background.IPCServer(None, str(Path(runtime) / "control.sock"), phone_backend=phone,
            settings_getter=lambda: copy.deepcopy(settings), settings_setter=lambda value: settings.update(value) or copy.deepcopy(settings))
        phone.callback = lambda event, payload: server.setup_sessions.phone_event(event, payload) or normal.append((event, payload))
        def request(op, **args): return background.ipc_request(op, args, path=server.path)
        try:
            assert phone.start()
            server.start()
            yield phone, server, request, normal, settings
        finally:
            server.close(); phone.stop()


def wait_for(request, token, predicate):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        result = request("phone_setup_status", session=token)
        if predicate(result): return result
        time.sleep(.02)
    raise AssertionError("Setup state did not arrive")


def test_showing_transports_does_not_reserve_setup_session(tmp_path):
    calls = []
    adapter = SetupPhoneServices(lambda: str(tmp_path), lambda: "Fixture",
        daemon_active=lambda: True, ipc=lambda *args: calls.append(args))
    assert {item["transport"] for item in adapter.capabilities()} == {"wifi", "bluetooth", "kdeconnect"}
    assert calls == [] and adapter.remote_session is None


def test_failed_optional_connection_does_not_block_finish(tmp_path):
    calls = []
    def request(op, args):
        calls.append(op)
        raise background.IPCError("Another phone setup session is active.")
    adapter = SetupPhoneServices(lambda: str(tmp_path), lambda: "Fixture",
        daemon_active=lambda: True, ipc=request)
    with pytest.raises(background.IPCError, match="active"):
        adapter.connect("wifi", lambda prompt: None)
    marker = tmp_path / "setup.json"
    selection = {"phoneBackgroundServices": [], "address": {"city": "Fixture"}}
    result = adapter.finish_setup(lambda status, values: write_state(status, values, str(marker)), selection)
    assert classify(str(marker)) == "ready"
    assert result["address"] == selection["address"] and result["_phoneForeground"] is False
    assert calls == ["phone_setup_begin"]


def test_expired_optional_session_does_not_block_finish_or_start_services(tmp_path):
    def request(op, args):
        raise background.IPCError("The phone setup session expired. Reopen phone setup and try again.")
    adapter = SetupPhoneServices(lambda: str(tmp_path), lambda: "Fixture", ipc=request)
    adapter.remote_session = "a" * 64
    adapter.connected_ids["wifi"] = "previously-connected-fixture"
    writes = []
    result = adapter.finish_setup(lambda *args: writes.append(args), {"phoneBackgroundServices": []})
    assert result["_phoneForeground"] is False and writes[0][0] == "complete"
    with pytest.raises(background.IPCError, match="expired"):
        adapter.finish_setup(lambda *args: writes.append(args), {"phoneBackgroundServices": ["wifi"]})
    assert len(writes) == 1


@pytest.mark.skipif(not hasattr(os, "pidfd_open"), reason="Kernel process handles unavailable")
def test_dead_setup_client_is_reclaimed_without_waiting_for_ttl(owner):
    _phone, server, request, *_ = owner
    code = """import sys
sys.path.insert(0, sys.argv[1])
from magnolie_hintergrund import ipc_request
print(ipc_request('phone_setup_begin', path=sys.argv[2])['session'])
"""
    old = subprocess.check_output([sys.executable, "-c", code, str(ROOT / "bin"), server.path], text=True).strip()
    assert server.setup_sessions.current["token"] == old
    assert server.setup_sessions.current["owner_fd"] is not None
    new = request("phone_setup_begin")["session"]
    assert new != old
    assert request("phone_setup_status", session=new)["connected"] == []


def test_real_unix_uid_pid_token_and_restart_boundaries(owner):
    phone, server, request, normal, settings = owner
    token = request("phone_setup_begin")["session"]
    assert len(token) == 64
    assert request("phone_setup_list", session=token)["connected"] == []
    for value in ("0" * 64, "f" * 64):
        with pytest.raises(background.IPCError, match="expired"):
            request("phone_setup_status", session=value)
    code = """import sys
sys.path.insert(0, sys.argv[1])
from magnolie_hintergrund import ipc_request, IPCError
try:
    ipc_request('phone_setup_status', {'session': sys.argv[3]}, path=sys.argv[2])
except IPCError as error:
    assert 'another client' in str(error)
else:
    raise AssertionError('another PID used the session')
try:
    ipc_request('phone_setup_begin', path=sys.argv[2])
except IPCError as error:
    assert 'active' in str(error)
else:
    raise AssertionError('second owner allocated a session')
"""
    subprocess.run([sys.executable, "-c", code, str(ROOT / "bin"), server.path, token], check=True)
    server._owner_uid = os.getuid() + 1
    with pytest.raises(background.IPCError, match="different user"):
        request("phone_setup_status", session=token)
    server._owner_uid = os.getuid()
    # The real kernel credentials are read; only the fixture's expected UID differs.
    assert server.setup_sessions.current["token"] == token
    request("phone_setup_cancel", session=token)
    server.setup_sessions.wait_closed()
    assert phone.server is not None and phone.enabled
    assert settings["permissions"]["phone_call_notifications"]
    replacement = PhoneSetupSessions(lambda create: phone, lambda: None, lambda: "unused", lambda: "Fixture")
    server.setup_sessions = replacement
    with pytest.raises(background.IPCError, match="expired"):
        request("phone_setup_status", session=token)


@pytest.mark.parametrize("op,args", [
    ("phone_setup_begin", {"uid": 0}), ("phone_setup_status", {}),
    ("phone_setup_status", {"session": "x"}),
    ("phone_setup_connect", {"session": "a" * 64, "transport": "http://127.0.0.1"}),
    ("phone_setup_confirm", {"session": "a" * 64, "prompt": "a" * 32, "answer": True}),
    ("phone_setup_commit", {"session": "a" * 64, "transports": ["wifi", "wifi"]}),
    ("phone_setup_commit", {"session": "a" * 64, "transports": ["microphone"]}),
])
def test_server_exact_shapes_reject_raw_unix_requests(owner, op, args):
    phone, server, request, *_ = owner
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(server.path)
        client.sendall(json.dumps({"op": op, "args": args}).encode() + b"\n")
        assert background._read_message(client)["ok"] is False
    assert server.setup_sessions.current is None and phone.server is not None


def test_prompt_target_replay_expiry_and_no_trust_from_ack(owner, monkeypatch):
    phone, server, request, normal, _settings = owner
    target = str(uuid.uuid4())
    def fixture(adapter, prompt, deadline):
        selected = prompt({"kind": "select", "devices": [{"uid": target, "name": "Fixture"}]})
        if selected is None: raise RuntimeError("cancelled")
        answer = prompt({"kind": "confirm", "devices": [{"uid": target, "name": "Fixture"}], "code": "123 456", "canMarkOwn": False})
        return {"transport": "wifi", "deviceId": target, "name": "Fixture", "authenticated": answer == "accept"}
    monkeypatch.setattr(SetupPhoneServices, "_connect_wifi", fixture)
    token = request("phone_setup_begin")["session"]
    started = request("phone_setup_connect", session=token, transport="wifi")
    assert started == {"started": True}
    state = wait_for(request, token, lambda s: s["prompt"] is not None)
    first = state["prompt"]["id"]
    with pytest.raises(background.IPCError): request("phone_setup_connect", session=token, transport="bluetooth")
    with pytest.raises(background.IPCError): request("phone_open_pairing")
    with pytest.raises(background.IPCError): request("phone_setup_confirm", session=token, prompt=first, answer="wrong target")
    request("phone_setup_confirm", session=token, prompt=first, answer=target)
    with pytest.raises(background.IPCError): request("phone_setup_confirm", session=token, prompt=first, answer=target)
    state = wait_for(request, token, lambda s: s["prompt"] is not None)
    assert state["target"] == target and state["connected"] == []
    second = state["prompt"]["id"]
    with pytest.raises(background.IPCError): request("phone_setup_confirm", session=token, prompt=second, answer="accept-own")
    request("phone_setup_confirm", session=token, prompt=second, answer="accept")
    assert wait_for(request, token, lambda s: s["state"] == "failed")["connected"] == []
    assert phone.store.peers == []  # A claimed ACK never substituted for live authenticated state.
    phone.callback("incoming_call", {"call_ref": "owned-normal-call"})
    assert normal[-1][0] == "incoming_call"
    server.setup_sessions.current["expires"] = time.monotonic() - 1
    with pytest.raises(background.IPCError, match="expired"): request("phone_setup_status", session=token)
    server.setup_sessions.wait_closed()
    assert phone.server is not None and phone.enabled


def test_cancel_pending_prompt_releases_only_setup_resources(owner, monkeypatch):
    phone, server, request, *_ = owner
    monkeypatch.setattr(telephone, "discover_setup_phones", lambda: [{"uid": "fixture", "name": "Fixture"}])
    token = request("phone_setup_begin")["session"]
    request("phone_setup_connect", session=token, transport="wifi")
    wait_for(request, token, lambda s: s["prompt"] is not None)
    descriptor = phone.server.fileno()
    request("phone_setup_cancel", session=token)
    server.setup_sessions.wait_closed()
    assert phone.server.fileno() == descriptor and phone.enabled
    with pytest.raises(background.IPCError): request("phone_setup_status", session=token)


def test_lazy_daemon_backend_is_borrowed_and_only_temporary_listener_is_released(owner, monkeypatch):
    phone, server, request, *_ = owner
    phone.stop(); phone.enabled = False
    server.phone_backend = None
    created = []
    def provider(create):
        if create:
            created.append(True)
            server.phone_backend = phone
        return server.phone_backend
    server.phone_provider = provider
    monkeypatch.setattr(telephone, "discover_setup_phones", lambda: [{"uid": "fixture", "name": "Fixture"}])
    token = request("phone_setup_begin")["session"]
    request("phone_setup_list", session=token)
    assert created == [] and phone.server is None
    request("phone_setup_connect", session=token, transport="wifi")
    wait_for(request, token, lambda s: s["prompt"] is not None)
    assert created == [True] and phone.server is not None and phone.enabled
    assert request("phone_setup_cancel", session=token)["released"]
    assert phone.server is None and not phone.enabled and phone.store.peers == []


def test_expired_prompt_and_unselected_startup_are_rejected(owner, monkeypatch):
    phone, server, request, *_ = owner
    monkeypatch.setattr(telephone, "discover_setup_phones", lambda: [{"uid": "fixture", "name": "Fixture"}])
    token = request("phone_setup_begin")["session"]
    request("phone_setup_connect", session=token, transport="wifi")
    state = wait_for(request, token, lambda s: s["prompt"] is not None)
    with server.setup_sessions.lock:
        server.setup_sessions.current["prompt"]["expires"] = time.monotonic() - 1
    with pytest.raises(background.IPCError, match="no longer current"):
        request("phone_setup_confirm", session=token, prompt=state["prompt"]["id"], answer="fixture")
    wait_for(request, token, lambda s: s["state"] == "failed")
    with pytest.raises(background.IPCError, match="no longer connected"):
        request("phone_setup_commit", session=token, transports=["wifi"])
    assert phone.store.peers == [] and phone.server is not None


def test_finish_startup_real_settings_autostart_and_failure_rollback(owner, monkeypatch, tmp_path):
    phone, server, request, *_ = owner
    # Standalone setup releases its own transport before invoking the start adapter.
    settings = background.normalize_settings({"permissions": {"phone_call_notifications": True}})
    background.write_settings(settings)
    phone.store.save_settings(False)
    adapter = SetupPhoneServices(lambda: str(tmp_path), lambda: "Fixture", phone=phone)
    adapter.connected = lambda: ["wifi"]
    marker = tmp_path / "setup.json"
    writes = lambda status, selections=None: write_state(status, selections, str(marker))
    writes("pending")
    starts = []
    monkeypatch.setattr(background, "daemon_available", lambda: False)
    def start():
        assert classify(str(marker)) == "ready"
        assert phone.server is None
        starts.append(background.read_settings())
        return True
    monkeypatch.setattr(background, "start_service", start)
    chosen = {"phoneBackgroundServices": ["wifi"]}
    result = adapter.finish_setup(writes, chosen)
    saved = background.read_settings()
    assert saved["autostart"] and saved["phone_setup_services"] == ["wifi"]
    assert saved["permissions"]["phone_monitor"] and saved["permissions"]["phone_call_notifications"]
    assert not saved["permissions"]["phone_pairing_decisions"]
    assert Path(background.autostart_path()).read_text().find("--hintergrunddienst") >= 0
    assert phone.store.settings()["enabled"] and len(starts) == 1
    assert result["_phoneForeground"] and "_phoneForeground" not in marker.read_text()
    # Restore only this fixture, then fail the actual start phase.
    background.write_settings(settings)
    phone.store.save_settings(False)
    writes("pending")
    monkeypatch.setattr(background, "start_service", lambda: False)
    with pytest.raises(RuntimeError, match="could not start"):
        adapter.finish_setup(writes, chosen)
    assert classify(str(marker)) == "pending"
    assert background.read_settings() == settings and not phone.store.settings()["enabled"]
    assert not Path(background.autostart_path()).exists()


def test_empty_or_cancelled_startup_never_touches_settings(owner, monkeypatch):
    phone, server, request, *_ = owner
    adapter = SetupPhoneServices(lambda: "unused", lambda: "Fixture", phone=phone, borrowed=True)
    monkeypatch.setattr(background, "write_settings", lambda *_a, **_kw: pytest.fail("Startup mutated without consent"))
    adapter.commit_startup([])
    adapter.close()
    assert phone.server is not None
    with pytest.raises(RuntimeError): adapter.commit_startup(["wifi"])


def test_corrupt_settings_are_not_repaired_or_overwritten_by_setup(owner):
    phone, server, request, *_ = owner
    adapter = SetupPhoneServices(lambda: "unused", lambda: "Fixture", phone=phone)
    adapter.connected = lambda: ["wifi"]
    path = Path(background.settings_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"enabled":"broken","permissions":{}}')
    before = path.read_bytes()
    with pytest.raises(ValueError): adapter.commit_startup(["wifi"])
    assert path.read_bytes() == before and not Path(background.autostart_path()).exists()


def test_failing_autostart_path_is_not_deleted_or_repaired(owner):
    phone, server, request, *_ = owner
    baseline = background.normalize_settings({})
    background.write_settings(baseline, update_autostart=False)
    phone.store.save_settings(False)
    path = Path(background.autostart_path())
    path.mkdir(parents=True)
    sentinel = path / "owned-by-user"
    sentinel.write_text("keep")
    adapter = SetupPhoneServices(lambda: "unused", lambda: "Fixture", phone=phone)
    adapter.connected = lambda: ["wifi"]
    with pytest.raises(OSError): adapter.commit_startup(["wifi"])
    assert sentinel.read_text() == "keep" and path.is_dir()
    assert background.read_settings() == baseline and not phone.store.settings()["enabled"]


def test_old_or_starting_owner_never_falls_back_to_local_listeners():
    def unavailable(*_args): raise background.IPCError("operation is not allowed")
    def forbidden(): raise AssertionError("Local owner was constructed")
    adapter = SetupPhoneServices(forbidden, lambda: "Fixture", daemon_active=lambda: True, ipc=unavailable)
    adapter.capabilities()
    with pytest.raises(RuntimeError, match="Restart the background service"):
        adapter.connect("wifi", lambda _: pytest.fail("No prompt before delegation"))
    assert adapter.phone is None


def test_daemon_kde_selection_waits_for_remote_confirmation_and_keeps_owner(owner):
    from types import SimpleNamespace
    phone, server, request, *_ = owner
    class Kde:
        def __init__(self):
            self.store = SimpleNamespace(peers=[])
            self.pairing = None; self.remote = self.local = False; self.stops = 0
            self._state_lock = threading.RLock()
        def discover(self, timeout): return [SimpleNamespace(identity={"deviceId": "selected-kde", "deviceName": "Fixture KDE"})]
        def begin_pairing(self, device_id, replace_stored):
            assert device_id == "selected-kde" and not replace_stored
            self.pairing = {"direction": "outgoing", "identity": {"deviceId": device_id}}
            return {"device_name": "Fixture KDE", "code": "123456"}
        def confirm_pairing(self, accepted):
            self.local = accepted
            if not accepted: self.pairing = None
        def status(self, timeout):
            ready = self.local and self.remote
            if ready:
                self.store.peers = [{"device_id": "selected-kde"}]; self.pairing = None
            return {"available": ready, "paired_count": int(ready), "device_id": "selected-kde", "peer_name": "Fixture KDE"}
        def stop(self): self.stops += 1
    kde = server.backend = Kde()
    token = request("phone_setup_begin")["session"]
    request("phone_setup_connect", session=token, transport="kdeconnect")
    state = wait_for(request, token, lambda s: s["prompt"] is not None)
    assert state["prompt"]["code"] == "123456"
    request("phone_setup_confirm", session=token, prompt=state["prompt"]["id"], answer="accept")
    assert request("phone_setup_status", session=token)["connected"] == []
    kde.remote = True
    result = wait_for(request, token, lambda s: s["state"] == "connected")
    assert result["result"]["deviceId"] == "selected-kde" and result["connected"] == ["kdeconnect"]
    assert request("phone_setup_cancel", session=token)["released"]
    assert kde.stops == 0 and kde.store.peers
