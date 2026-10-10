import copy
import sys
import uuid
import sqlite3
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


def test_scoped_data_dispatch_persists_run_and_never_accepts_unwrapped_reuse(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["mobile-note"], ["task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    request = {"format": 3, "run_id": str(uuid.uuid4()), "trigger": "manual", "modules": ["notes", "tasks"]}
    wrapped = message(scope.wrap("personal_sync.request", request, manifest)); wrapped["kind"] = scope.DATA_KIND
    service._payload(peer, channel, wrapped)
    assert channel.sent[-1]["status"] == "accepted"
    assert service.store.scoped_run_reference(peer["device_id"], peer["static_public"], request["run_id"]) == scope.reference(manifest)
    naked = dict(wrapped, kind="personal_sync.request", body=request)
    service._payload(peer, channel, naked)
    assert channel.sent[-1]["status"] == "rejected"
    service._payload(peer, channel, wrapped)
    assert channel.sent[-1]["status"] in {"accepted", "duplicate"}
    altered = copy.deepcopy(wrapped); altered["body"]["body"]["run_id"] = str(uuid.uuid4())
    service._payload(peer, channel, altered)
    assert channel.sent[-1]["status"] == "rejected"
    assert service.store.personal_run(peer["device_id"], altered["body"]["body"]["run_id"]) == {}
    fresh_naked = dict(naked, message_id=str(uuid.uuid4()), body=dict(request, run_id=str(uuid.uuid4())))
    service._payload(peer, channel, fresh_naked)
    assert channel.sent[-1]["status"] == "rejected"
    assert service.store.personal_run(peer["device_id"], fresh_naked["body"]["run_id"]) == {}


def test_outgoing_scoped_data_wraps_current_member_and_blocks_other_notes(tmp_path, monkeypatch):
    service, peer, channel = fixture(tmp_path, monkeypatch)
    manifest = scope.create(["mobile-note"], ["task"])
    service._payload(peer, channel, frame(scope.chunks(manifest)[0]))
    run_id = str(uuid.uuid4()); request = {"format": 3, "run_id": run_id, "trigger": "manual", "modules": ["notes", "tasks"]}
    service.store.remember_scoped_run(peer["device_id"], peer["static_public"], request, scope.reference(manifest), phone.now_ms() + 60000)
    import magnolie_personal_sync as personal
    value = {"title": "Shared", "text": "Organizer addition", "html": "", "notebook_id": "", "symbol": "note",
             "created_ms": 1, "modified_ms": 2, "attachments": []}
    record = {"kind": "note", "id": "mobile-note", "state": "live", "clock": [{"actor_id": str(uuid.uuid4()), "counter": 1}],
              "hash": personal.projection_hash(value), "modified_ms": 2, "value": value}
    body = {"format": 3, "run_id": run_id, "batch_id": str(uuid.uuid4()), "sequence": 0, "last": True,
            "reply": True, "records": [record], "records_hash": personal.records_hash([record])}
    service.send_personal_sync(peer["device_id"], "personal_sync.batch", body)
    sent = channel.sent[-1]
    assert sent["kind"] == scope.DATA_KIND
    assert scope.unwrap(sent["body"], manifest) == ("personal_sync.batch", body)
    foreign = copy.deepcopy(body); foreign["records"][0]["id"] = "organizer-only"
    foreign["records_hash"] = personal.records_hash(foreign["records"])
    before = len(channel.sent)
    with pytest.raises(PermissionError):
        service.send_personal_sync(peer["device_id"], "personal_sync.batch", foreign)
    assert len(channel.sent) == before
    removed = scope.advance(manifest, [], [])
    service._payload(peer, channel, frame(scope.chunks(removed)[0]))
    with pytest.raises(ValueError):
        service._payload(peer, channel, {"type": "ack", "message_id": sent["message_id"], "status": "accepted", "error": "none"})
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT count(*) FROM outbox WHERE peer_id=? AND message_id=?",
                          (peer["device_id"], sent["message_id"])).fetchone()[0] == 1
    with pytest.raises((PermissionError, ValueError)):
        service.send_personal_sync(peer["device_id"], "personal_sync.batch", body)
