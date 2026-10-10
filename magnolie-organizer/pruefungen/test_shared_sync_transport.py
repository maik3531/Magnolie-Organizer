"""Exercise real phone receive/queue dispatch with synthetic authenticated session controls."""
import copy
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_shared_sync as shared
import magnolie_telefon as phone
from test_personal_sync import _personal_service


class Channel:
    def __init__(self):
        self.sent = []
    def send(self, payload):
        self.sent.append(copy.deepcopy(payload))


def fixture(tmp_path, monkeypatch, negotiated=True):
    original = phone.desktop_capabilities
    def capabilities(*args, **kwargs):
        value = original(*args, **kwargs)
        if negotiated:
            for name in ("personal_notes_sync", "personal_tasks_sync"):
                value["items"][name]["versions"].append(shared.VERSION)
        return value
    monkeypatch.setattr(phone, "desktop_capabilities", capabilities)
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id)
    peer["capabilities"] = capabilities()
    service.store.save_peers()
    channel = Channel(); service.connections[peer_id] = channel
    service.connection_transports[peer_id] = "wifi"
    service.note_controls[channel] = {
        "capabilities.update": copy.deepcopy(peer["capabilities"]),
        "grants.update": copy.deepcopy(peer["grants"]),
        "personal_sync.settings": {"format": 1, "own_device": True}}
    service.personal_sync_available = lambda: True
    body = service.store.change_shared_setting(peer_id, peer["static_public"], "content_mode", "phone_scope")
    return service, peer, channel, body


def message(body):
    now = phone.now_ms()
    return {"type": "message", "v": 1, "message_id": str(uuid.uuid4()), "kind": shared.KIND,
            "created_ms": now, "expires_ms": now + 60000, "body": body}


def test_same_current_choice_is_exchanged_without_changing_existing_grants(tmp_path, monkeypatch):
    service, peer, channel, body = fixture(tmp_path, monkeypatch)
    before = copy.deepcopy(peer)
    actor = service.store.identity["device_id"]
    remote = shared.merge(shared.create(peer["device_id"]), body, peer["device_id"], actor)
    remote = shared.change(remote, peer["device_id"], actor, "content_mode", "two_way")
    payload = message(remote)
    service._payload(peer, channel, payload)
    assert channel.sent[-1]["status"] == "accepted"
    assert service.shared_settings_ready(peer["device_id"])
    assert shared.effective(service.store.shared_settings(peer["device_id"], peer["static_public"]))["content_mode"] == "two_way"
    assert peer == before, "Preference exchange must not silently rewrite legacy grants/policies"
    sent = len([item for item in channel.sent if item.get("kind") == shared.KIND])
    service._payload(peer, channel, payload)
    assert channel.sent[-1]["status"] == "accepted"
    assert len([item for item in channel.sent if item.get("kind") == shared.KIND]) == sent
    replacement = Channel(); service.connections[peer["device_id"]] = replacement
    assert not service.shared_settings_ready(peer["device_id"]), "Saved state is not fresh connection evidence"


@pytest.mark.parametrize("gate", ["capabilities", "grants", "own", "channel", "key", "unavailable", "unnegotiated"])
def test_missing_or_changed_current_connection_evidence_rejects_shared_updates(tmp_path, monkeypatch, gate):
    service, peer, channel, before = fixture(tmp_path, monkeypatch, negotiated=gate != "unnegotiated")
    incoming = shared.change(shared.create(peer["device_id"]), peer["device_id"], service.store.identity["device_id"], "auto_mode", "connection")
    if gate == "capabilities": service.note_controls[channel].pop("capabilities.update")
    elif gate == "grants": service.note_controls[channel].pop("grants.update")
    elif gate == "own": service.note_controls[channel].pop("personal_sync.settings")
    elif gate == "channel": service.connections[peer["device_id"]] = Channel()
    elif gate == "key":
        old = copy.deepcopy(peer); peer["static_public"] = phone.b64(b"k" * 32); peer = old
    elif gate == "unavailable": service.personal_sync_available = lambda: False
    service._payload(peer, channel, message(incoming))
    assert channel.sent[-1]["status"] == "rejected" and channel.sent[-1]["error"] == "not_granted"
    if gate != "key":
        assert service.store.shared_settings(peer["device_id"], peer["static_public"]) == before


def test_outgoing_old_snapshot_and_altered_replay_never_replace_new_choice(tmp_path, monkeypatch):
    service, peer, channel, body = fixture(tmp_path, monkeypatch)
    queued = service.store.queue(peer["device_id"], shared.KIND, body, 60000)
    updated = service.store.change_shared_setting(peer["device_id"], peer["static_public"], "auto_mode", "connection")
    assert not service._send_message(channel, peer["device_id"], queued)
    assert channel.sent == []
    remote = shared.merge(shared.create(peer["device_id"]), updated, peer["device_id"], service.store.identity["device_id"])
    payload = message(remote); service._payload(peer, channel, payload)
    accepted = service.store.shared_settings(peer["device_id"], peer["static_public"])
    altered = copy.deepcopy(payload)
    altered["body"] = shared.change(remote, peer["device_id"], service.store.identity["device_id"], "content_mode", "two_way")
    service._payload(peer, channel, altered)
    assert channel.sent[-1]["error"] == "invalid_schema"
    assert service.store.shared_settings(peer["device_id"], peer["static_public"]) == accepted


def test_public_capabilities_still_do_not_announce_unfinished_feature():
    capabilities = phone.desktop_capabilities()["items"]
    assert not shared.supported(capabilities, capabilities)
