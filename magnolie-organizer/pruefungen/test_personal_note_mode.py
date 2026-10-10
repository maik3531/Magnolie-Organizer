"""Issue #76: direction contract and fresh-connection fences, not runtime acceptance."""
from pathlib import Path
import sys
import copy
import uuid
import tempfile
import sqlite3

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_personal_sync as sync
import magnolie_telefon as phone
from test_personal_sync import _personal_service


def test_reconnect_and_policy_changes_require_current_echoes():
    local, remote = sync.note_settings(), sync.note_settings("phone_import")
    local, remote = sync.note_settings_echo(local, remote), sync.note_settings_echo(remote, local)
    session = sync.PersonalNoteSession()
    assert not session.ready(local, remote)
    session.sent = dict(local)
    assert not session.ready(local, remote)
    session.received = dict(remote)
    assert session.ready(local, remote)
    assert not sync.PersonalNoteSession().ready(local, remote)
    changed = sync.note_settings("phone_import", 2, remote["epoch"])
    assert not session.ready(changed, remote)
    session.sent = changed
    assert not session.ready(changed, remote)
    remote = sync.note_settings_echo(remote, changed)
    session.received = remote
    assert session.ready(changed, remote)


def test_policy_replay_and_equivocation():
    policy = sync.note_settings()
    echoed = sync.note_settings_echo(policy, sync.note_settings())
    assert sync.accept_note_settings(policy, echoed) == echoed
    for invalid in (dict(policy, revision=0), dict(policy, mode="two_way"),
                    dict(policy, revision=2), dict(policy, epoch=sync.note_settings()["epoch"])):
        with pytest.raises(ValueError):
            sync.accept_note_settings(policy, invalid)
    newer = sync.note_settings("phone_import", 2)
    assert sync.accept_note_settings(policy, newer) == newer
    with pytest.raises(ValueError):
        sync.accept_note_settings(newer, policy)


@pytest.mark.parametrize("role,outgoing,forward", [
    ("phone", True, True), ("desktop", False, True),
    ("desktop", True, False), ("phone", False, False),
])
def test_import_direction_preserves_tasks_and_never_deletes_notes(role, outgoing, forward):
    def allowed(kind, body, decision_kinds=None):
        return sync.note_direction_allowed(role, outgoing, "personal_sync." + kind,
                                           body, True, decision_kinds)
    assert allowed("batch", {"records": [{"kind": "note"}]}) == forward
    assert allowed("batch", {"records": [{"kind": "task"}, {"kind": "notebook"}]}) == forward
    assert allowed("batch", {"records": [{"kind": "task"}]})
    assert allowed("batch", {"records": []})
    assert allowed("attachment_chunk", {}) == forward
    assert allowed("attachment_request", {}) != forward
    for kind in ("note", "notebook", "attachment"):
        assert not allowed("deletion_proposals", {"proposals": [{"kind": kind}]})
        assert not allowed("deletion_decision", {"decisions": [{}]}, [kind])
    assert allowed("deletion_proposals", {"proposals": [{"kind": "task"}]})
    assert allowed("deletion_decision", {"decisions": [{}]}, ["task"])
    assert not allowed("deletion_decision", {"decisions": [{}]})
    assert not allowed("deletion_decision", {"decisions": [{}, {}]}, ["task"])


def test_task_only_traffic_does_not_wait_for_note_consent():
    assert not sync.note_message_uses_notes("personal_sync.request", {"modules": ["tasks"]})
    assert sync.note_message_uses_notes("personal_sync.request", {"modules": ["tasks", "notes"]})
    assert not sync.note_message_uses_notes("personal_sync.batch", {"records": [{"kind": "task"}]})
    assert sync.note_message_uses_notes("personal_sync.batch", {"records": [{"kind": "notebook"}]})
    assert sync.note_message_uses_notes("personal_sync.deletion_decision", {})
    assert not sync.note_message_uses_notes("personal_sync.deletion_decision", {}, ["task"])


def test_native_policy_storage_is_durable_and_defensive(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    local, remote = sync.note_settings("phone_import"), sync.note_settings()
    service.store.set_note_settings(peer_id, local)
    service.store.set_note_settings(peer_id, remote, remote=True)
    reopened = phone.PhoneStore(str(tmp_path / "phone"), "Test")
    assert reopened.note_settings(peer_id) == {"local": local, "remote": remote}
    returned = reopened.note_settings(peer_id)
    returned["local"]["mode"] = "two_way"
    assert reopened.note_settings(peer_id)["local"]["mode"] == "phone_import"
    with pytest.raises(ValueError):
        reopened.set_note_settings(peer_id, dict(local, mode="two_way"))
    with pytest.raises(RuntimeError):
        reopened.set_note_settings("unknown-peer", remote)


def test_native_policy_save_failure_fences_until_successful_retry(tmp_path, monkeypatch):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    original = sync.note_settings()
    service.store.set_note_settings(peer_id, original)
    changed = sync.note_settings("phone_import", 2)
    save = service.store.save_peers
    def fail():
        raise OSError("synthetic write failure")
    monkeypatch.setattr(service.store, "save_peers", fail)
    with pytest.raises(OSError):
        service.store.set_note_settings(peer_id, changed)
    with pytest.raises(RuntimeError):
        service.store.note_settings(peer_id)
    assert phone.PhoneStore(str(tmp_path / "phone"), "Test").note_settings(peer_id)["local"] == original
    monkeypatch.setattr(service.store, "save_peers", save)
    service.store.set_note_settings(peer_id, changed)
    assert service.store.note_settings(peer_id)["local"] == changed


def test_native_policy_queue_replaces_old_echo_and_precedes_data(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    for _ in range(33):
        service.store.queue(peer_id, "personal_sync.batch", {}, phone.DAY_MS)
    local = sync.note_settings()
    old = service.store.queue(peer_id, sync.NOTE_MODE_KIND, local, phone.DAY_MS)
    echoed = sync.note_settings_echo(local, sync.note_settings())
    current = service.store.queue(peer_id, sync.NOTE_MODE_KIND, echoed, phone.DAY_MS)
    pending = service.store.pending(peer_id)
    assert pending[0] == current
    assert old["message_id"] not in {message["message_id"] for message in pending}
    with pytest.raises(ValueError):
        service.store.queue(peer_id, sync.NOTE_MODE_KIND, echoed, phone.DAY_MS + 1)


class NoteChannel:
    def __init__(self):
        self.sent = []

    def send(self, value):
        self.sent.append(copy.deepcopy(value))


def note_packet(kind, body):
    now = phone.now_ms()
    return dict(type="message", v=1, message_id=str(uuid.uuid4()), kind=kind,
                created_ms=now, expires_ms=now + 60_000, body=body)


def v5_service(tmp_path, monkeypatch):
    original = phone.desktop_capabilities
    def capabilities(*args, **kwargs):
        value = original(*args, **kwargs)
        if 5 not in value["items"]["personal_notes_sync"]["versions"]:
            value["items"]["personal_notes_sync"]["versions"].append(5)
        return value
    monkeypatch.setattr(phone, "desktop_capabilities", capabilities)
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id)
    peer["capabilities"] = capabilities()
    service.store.save_peers()
    channel = NoteChannel()
    service.connections[peer_id] = channel
    controls = [note_packet("capabilities.update", capabilities(2)),
                note_packet("grants.update", dict(peer["grants"], revision=2)),
                note_packet("personal_sync.settings", {"format": 1, "own_device": True})]
    for packet in controls:
        service._payload(peer, channel, packet)
        assert channel.sent[-1]["status"] == "accepted"
    return service, peer_id, channel, controls


def test_native_policy_handshake_reconnect_ack_loss_and_import(tmp_path, monkeypatch):
    service, peer_id, channel, controls = v5_service(tmp_path, monkeypatch)
    peer = service.store.peer(peer_id)
    local = service.store.note_settings(peer_id)["local"]
    assert not service._note_ready(peer_id)
    remote = sync.note_settings("phone_import", peer_epoch=local["epoch"])
    packet = note_packet(sync.NOTE_MODE_KIND, remote)
    service._payload(peer, channel, packet)
    assert channel.sent[-1]["status"] == "accepted"
    assert service._note_ready(peer_id)
    assert service.note_status(peer_id)["importing"]
    assert not service._note_direction_allowed(peer_id, "personal_sync.batch", {"records": [{"kind": "note"}]}, True)
    assert service._note_direction_allowed(peer_id, "personal_sync.batch", {"records": [{"kind": "note"}]}, False)
    reconnect = NoteChannel()
    service.connections[peer_id] = reconnect
    assert not service._note_ready(peer_id)
    for control in controls:
        service._payload(peer, reconnect, control)
        assert reconnect.sent[-1]["status"] == "duplicate"
    assert not service._note_ready(peer_id)
    service._payload(peer, reconnect, packet)
    assert reconnect.sent[-1]["status"] == "accepted"
    assert service._note_ready(peer_id)
    # A reused message identity must not acknowledge a different policy echo.
    changed = copy.deepcopy(packet)
    changed["body"]["peer_epoch"] = ""
    service._payload(peer, reconnect, changed)
    assert reconnect.sent[-1]["error"] == "invalid_schema"
    assert service.store.note_settings(peer_id)["remote"] == remote


def test_native_notes_wait_but_tasks_remain_independent(tmp_path, monkeypatch):
    service, peer_id, channel, _ = v5_service(tmp_path, monkeypatch)
    notes = {"format": 1, "run_id": str(uuid.uuid4()), "trigger": "manual", "modules": ["notes"]}
    message = service.store.queue(peer_id, "personal_sync.request", notes, 60_000)
    before = len(channel.sent)
    assert not service._send_message(channel, peer_id, message)
    assert len(channel.sent) == before
    assert service._note_policy_error(peer_id, "personal_sync.batch", {"records": [{"kind": "task"}]}, True) is None
    service.set_note_mode(peer_id, "two_way")
    local = service.store.note_settings(peer_id)["local"]
    service._payload(service.store.peer(peer_id), channel,
        note_packet(sync.NOTE_MODE_KIND, sync.note_settings("two_way", peer_epoch=local["epoch"])))
    assert service._note_ready(peer_id)
    service.set_note_mode(peer_id, "phone_import")
    assert not service._note_ready(peer_id)
    assert service._note_policy_error(peer_id, "personal_sync.attachment_chunk", {}, True) == "temporary_failure"
    # Previously captured note bytes cannot be queued after the mode change.
    assert not service._note_direction_allowed(peer_id, "personal_sync.attachment_chunk", {}, True)


def test_direction_choice_reaches_daemon_through_real_ipc(tmp_path, monkeypatch):
    import magnolie_hintergrund as background
    from test_hintergrunddienst import FakeBackend
    service, peer_id, _, _ = v5_service(tmp_path, monkeypatch)
    with tempfile.TemporaryDirectory(prefix="note-mode-ipc-") as root:
        socket = str(Path(root) / "background.sock")
        server = background.IPCServer(FakeBackend(), socket, phone_backend=service).start()
        try:
            proxy = background.PhoneServiceProxy(socket)
            initial = copy.deepcopy(service.store.note_settings(peer_id)["local"])
            proxy.set_note_mode(peer_id, "phone_import")
            assert service.store.note_settings(peer_id)["local"]["mode"] == "phone_import"
            assert service.store.note_settings(peer_id)["local"] == initial
            proxy.set_note_mode(peer_id, "two_way")
            assert service.store.note_settings(peer_id)["local"]["revision"] == initial["revision"] + 1
            for peer, mode in ((peer_id, True), (peer_id, "unknown"), ("unknown-peer", "phone_import")):
                with pytest.raises(background.IPCError):
                    proxy.set_note_mode(peer, mode)
        finally:
            server.close()


def test_task_decision_proofs_bind_peer_direction_clock_and_expire(tmp_path, monkeypatch):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    proposal = {"proposal_id": str(uuid.uuid4()), "kind": "task", "id": "task", "parent_id": "",
                "clock": [{"actor_id": str(uuid.uuid4()), "counter": 1}], "prior_hash": "a" * 64,
                "deleted_ms": 1, "label": "Task"}
    body = {"format": 1, "run_id": str(uuid.uuid4()), "proposal_batch_id": str(uuid.uuid4()),
            "sequence": 0, "last": True, "proposals": [proposal]}
    now = phone.now_ms()
    monkeypatch.setattr(phone, "now_ms", lambda: now)
    service.store.remember_personal_proposal_kinds(peer_id, body, True)
    decision = {"decisions": [{"proposal_id": proposal["proposal_id"], "decision": "delete", "expected_clock": proposal["clock"]}]}
    assert service.store.personal_decision_kinds(peer_id, decision, False) == ["task"]
    assert service.store.personal_decision_kinds(peer_id, decision, True) is None
    assert service.store.personal_decision_kinds(str(uuid.uuid4()), decision, False) is None
    wrong = copy.deepcopy(decision); wrong["decisions"][0]["expected_clock"][0]["counter"] = 2
    assert service.store.personal_decision_kinds(peer_id, wrong, False) is None
    monkeypatch.setattr(phone, "now_ms", lambda: now + phone.DAY_MS)
    service.store.remember_personal_proposal_kinds(peer_id, body, True)
    monkeypatch.setattr(phone, "now_ms", lambda: now + 30 * phone.DAY_MS + 1)
    assert service.store.personal_decision_kinds(peer_id, decision, False) is None
    service.store.cleanup()
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_proposal_kind:%'").fetchone()[0] == 0


def test_cached_v5_capability_does_not_send_new_control_to_downgraded_peer(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id)
    peer["capabilities"] = phone.desktop_capabilities()
    service.store.save_peers()
    channel = NoteChannel(); service.connections[peer_id] = channel
    service._queue_note_settings(peer_id, channel, force=True)
    assert channel.sent == [] and service.store.note_settings(peer_id) == {}
    legacy = phone.desktop_capabilities(2)
    legacy["items"]["personal_notes_sync"]["versions"] = [1, 2, 3]
    service._payload(peer, channel, note_packet("capabilities.update", legacy))
    assert not any(message.get("kind") == sync.NOTE_MODE_KIND for message in channel.sent)
    assert service._note_policy_error(peer_id, "personal_sync.batch", {"records": [{"kind": "note"}]}, True, channel) is None
