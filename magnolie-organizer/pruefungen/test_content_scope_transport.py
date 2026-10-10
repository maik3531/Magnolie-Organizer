import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_content_scope as scope
import magnolie_shared_sync as shared
import magnolie_telefon as phone
from test_shared_sync_transport import fixture as shared_fixture, Channel, message


def fixture(tmp_path, monkeypatch):
    service, peer, channel, body = shared_fixture(tmp_path, monkeypatch)
    original = phone.desktop_capabilities
    def capabilities(*args, **kwargs):
        result = original(*args, **kwargs)
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            result["items"][name]["versions"].append(scope.VERSION)
        return result
    monkeypatch.setattr(phone, "desktop_capabilities", capabilities)
    peer["capabilities"] = capabilities()
    peer["local_grants"]["grants"]["personal_tasks_sync"] = True
    peer["grants"]["grants"]["personal_tasks_sync"] = True
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    service.note_controls[channel]["grants.update"] = copy.deepcopy(peer["grants"])
    remote = shared.merge(shared.create(peer["device_id"]), body, peer["device_id"], service.store.identity["device_id"])
    service._payload(peer, channel, message(remote))
    assert service.shared_settings_ready(peer["device_id"])
    return service, peer, channel


def frame(part):
    value = message(part); value["kind"] = scope.KIND
    return value


def test_current_phone_membership_arrives_only_after_complete_bound_manifest(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["note-%03d" % n for n in range(100)], ["task"])
    parts = scope.chunks(manifest, 32)
    packet = frame(parts[-1]); service._payload(peer, channel, packet)
    assert channel.sent[-1]["status"] == "accepted"
    with pytest.raises(PermissionError):
        service.current_content_scope(peer["device_id"], peer["static_public"], scope.reference(manifest))
    for part in parts[:-1]:
        service._payload(peer, channel, frame(part))
    assert service.current_content_scope(peer["device_id"], peer["static_public"], scope.reference(manifest)) == manifest
    service._payload(peer, channel, packet)
    assert channel.sent[-1]["status"] == "accepted"
    service.connections[peer["device_id"]] = Channel()
    with pytest.raises(PermissionError):
        service.current_content_scope(peer["device_id"], peer["static_public"], scope.reference(manifest))


@pytest.mark.parametrize("change", ["mode", "grants", "task_grant", "key", "capability", "expired", "altered"])
def test_scope_cannot_bypass_current_choice_session_or_message_identity(tmp_path, monkeypatch, change):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["mobile-note"], [])
    packet = frame(scope.chunks(manifest)[0])
    if change == "mode":
        service.store.change_shared_setting(peer["device_id"], peer["static_public"], "content_mode", "two_way")
    elif change == "grants": service.note_controls[channel].pop("grants.update")
    elif change == "task_grant": peer["local_grants"]["grants"]["personal_tasks_sync"] = False
    elif change == "key":
        previous = copy.deepcopy(peer); peer["static_public"] = phone.b64(b"n" * 32); peer = previous
    elif change == "capability": peer["capabilities"]["items"]["personal_tasks_sync"]["versions"].remove(scope.VERSION)
    elif change == "expired": packet["created_ms"] -= 120000; packet["expires_ms"] -= 120000
    elif change == "altered":
        service._payload(peer, channel, packet)
        packet = copy.deepcopy(packet); packet["body"] = scope.chunks(scope.advance(manifest, ["other-note"], []))[0]
    service._payload(peer, channel, packet)
    assert channel.sent[-1]["status"] == "rejected"


def test_legacy_public_capabilities_do_not_enable_scoped_transfer():
    items = phone.desktop_capabilities()["items"]
    assert not scope.supported(items, items)
