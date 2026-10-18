"""Existing KDE integration snapshots, without a second listener or activation."""
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_kdeconnect as kde


def test_direct_snapshot_does_not_use_starting_status_path_or_payloads(tmp_path, monkeypatch):
    backend = kde.KDEConnectSMSBackend(str(tmp_path / "kde"), "Owned KDE desktop", clock=lambda: 10.0)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Metadata read started or probed a transport")
    monkeypatch.setattr(backend, "start", forbidden)
    monkeypatch.setattr(backend, "status", forbidden)
    backend._receive_pending["owned-private"] = {"text": "owned-private-clipboard"}
    initial = backend.mcp_status()
    assert initial["revision"] == backend.mcp_status()["revision"] and initial["listening"] is False and backend._service_thread is None
    assert initial["local_id"] == backend.store.device_id and len(initial["local_fingerprint"]) == 64
    assert "owned-private" not in json.dumps(initial) and "PRIVATE KEY" not in json.dumps(initial)
    device_id = "11111111111111111111111111111111"
    device = kde.DiscoveredDevice("127.0.0.1", 1716, {"deviceId": device_id, "deviceName": "Owned candidate", "deviceType": "phone"})
    backend._devices[device_id] = (device, 10.0, 310.0)
    discovered = backend.mcp_status()
    assert discovered["revision"] != initial["revision"] and discovered["candidates"][0]["fingerprint"] is None
    token = discovered["candidates"][0]["source_token"]
    backend._devices[device_id] = (device, 11.0, 311.0)
    assert backend.mcp_status()["revision"] == discovered["revision"]
    changed = kde.DiscoveredDevice("127.0.0.2", 1716, device.identity)
    backend._devices[device_id] = (changed, 11.0, 311.0)
    assert backend.mcp_status()["candidates"][0]["source_token"] != token


def test_system_snapshot_uses_current_dbus_owner_and_keeps_native_limits(monkeypatch):
    backend = kde.KDEConnectNativeBackend(None, None, None)
    owner = [":owned.1"]
    monkeypatch.setattr(backend, "_owner", lambda: owner[0])
    monkeypatch.setattr(backend, "_devices", lambda _owner, include_desktops=False: [{"device_id": "11111111111111111111111111111111", "device_name": "Owned native phone", "reachable": True, "device_type": "phone"}])
    monkeypatch.setattr(backend, "_contact_fingerprint", lambda _device: "a" * 64)
    monkeypatch.setattr(backend, "start", lambda: pytest.fail("Read activated the system integration"))
    monkeypatch.setattr(backend, "status", lambda *_args: pytest.fail("Read used the broad GUI status path"))
    initial = backend.mcp_status()
    assert initial["integration"] == "system" and initial["running"] and initial["listening"] is None and initial["local_id"] is None
    assert initial["capabilities"] == {"refresh": True, "pairing": False, "remove": False, "receive_preferences": False}
    assert initial["revision"] == backend.mcp_status()["revision"]
    owner[0] = ":owned.2"
    assert backend.mcp_status()["revision"] != initial["revision"]
    monkeypatch.setattr(backend, "_contact_fingerprint", lambda _device: (_ for _ in ()).throw(OSError("owned-private-path")))
    unavailable = backend.mcp_status()
    assert unavailable["error_present"] and unavailable["peers"][0]["fingerprint"] is None and "owned-private" not in json.dumps(unavailable)


def test_system_snapshot_rejects_owner_change_during_read(monkeypatch):
    backend = kde.KDEConnectNativeBackend(None, None, None)
    owners = iter((":owned.1", ":owned.2"))
    monkeypatch.setattr(backend, "_owner", lambda: next(owners))
    monkeypatch.setattr(backend, "_devices", lambda *_args, **_kwargs: [])
    with pytest.raises(kde.ProtocolError, match="source_changed"):
        backend.mcp_status()


def owned_encrypted_link(tmp_path):
    events = []
    backend = kde.KDEConnectSMSBackend(str(tmp_path / "local"), "Owned local", callback=lambda *args: events.append(args))
    remote = kde.IdentityStore(str(tmp_path / "remote"), "Owned remote")
    identity = {"deviceId": remote.device_id, "deviceName": remote.device_name, "deviceType": "phone"}
    class Worker:
        def __init__(self): self.identity = identity; self.stopped = threading.Event(); self.sent = []; self.enabled = False
        def send(self, packet): self.sent.append(packet)
        def enable_sms(self): self.enabled = True
        def close(self, **_kwargs): self.stopped.set()
    worker = Worker()
    backend._connections[remote.device_id] = {"worker": worker, "connection": None, "certificate": remote.certificate, "identity": identity, "address": "127.0.0.1", "port": 1716, "generation": 1}
    return backend, remote, worker, events


def test_existing_complete_and_confirm_handlers_wait_for_remote_then_verify_store(tmp_path):
    backend, remote, worker, events = owned_encrypted_link(tmp_path)
    initial = backend.mcp_status(); candidate = initial["candidates"][0]
    begun = backend.mcp_action({"action": "pairing_complete", "expectedRevision": initial["revision"], "candidateId": candidate["id"], "sourceToken": candidate["source_token"]})
    assert begun["ok"] and not begun["persisted"] and not begun["pairedVerified"]
    pending = begun["status"]["pending"][0]
    wrong = backend.mcp_action({"action": "pairing_confirm", "expectedRevision": begun["status"]["revision"], "peerId": remote.device_id, "attemptId": "stale-attempt", "fingerprint": pending["fingerprint"], "accept": True})
    assert not wrong["ok"] and wrong["code"] == "conflict"
    accepted = backend.mcp_action({"action": "pairing_confirm", "expectedRevision": begun["status"]["revision"], "peerId": remote.device_id, "attemptId": pending["attempt_id"], "fingerprint": pending["fingerprint"], "accept": True})
    assert accepted["ok"] and not accepted["persisted"] and not accepted["pairedVerified"] and not backend.store._load_peers()
    backend._pair_packet(worker, kde.network_packet("kdeconnect.pair", {"pair": True}))
    stored = backend.store._load_peers()[remote.device_id]
    assert stored["paired"] and backend.mcp_status()["peers"][0]["fingerprint"] == pending["fingerprint"]
    assert worker.enabled and not events, "MCP-owned late pairing replies opened the legacy GUI verification/paired prompt"


def test_mcp_cancel_does_not_turn_late_rejection_into_gui_feedback(tmp_path):
    backend, remote, worker, events = owned_encrypted_link(tmp_path)
    initial = backend.mcp_status(); candidate = initial["candidates"][0]
    begun = backend.mcp_action({"action": "pairing_complete", "expectedRevision": initial["revision"], "candidateId": candidate["id"], "sourceToken": candidate["source_token"]})
    pending = begun["status"]["pending"][0]
    result = backend.mcp_action({"action": "pairing_cancel", "expectedRevision": begun["status"]["revision"], "peerId": remote.device_id, "attemptId": pending["attempt_id"], "fingerprint": pending["fingerprint"]})
    assert result["ok"] and not result["persisted"] and not backend.pairing
    backend._pair_packet(worker, kde.network_packet("kdeconnect.pair", {"pair": False}))
    assert not events and not backend.store._load_peers()
