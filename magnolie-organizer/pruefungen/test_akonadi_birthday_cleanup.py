"""Real Akonadi adapter/orchestrator with an isolated revision-aware helper."""
import copy
import json

import pytest
from test_eds_calendar_dedup import m
from test_calendar_birthday_dedup import event, local
import magnolie_akonadi as ak


SOURCE = "akonadi-calendar:7"
KEY = "akonadi:" + SOURCE


def fixture(monkeypatch, tmp_path, *, legacy=False, readonly=False, restore=False):
    remote = {uid: {"id": index + 70, "revision": 2, "gid": uid,
        "content": "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + event(uid,
            created="20200101T000000Z" if uid == "original" else "20260101T000000Z") + "END:VCALENDAR\r\n"}
        for index, uid in enumerate(("original", "copy"))}
    calls, writes = [], []
    control = {"crash": False, "conflict": False, "fail_snapshot": False, "downgrade": False}
    archive = m.kalender_dubletten.CleanupArchive(tmp_path, KEY + '\0epoch\0' + json.dumps([3, "default"], separators=(",", ":")), lambda: b"a" * 32)

    def helper(request, *_args):
        calls.append(request["command"])
        assert (request["collection"], request["generation"], request["instance"]) == (7, 3, "default")
        if request["command"] == "capabilities":
            if legacy:
                raise ak.AkonadiError("unsupported command")
            return {"ok": True, "revisionGuardedDelete": True}
        if request["command"] == "snapshot":
            if control["fail_snapshot"]:
                raise ak.AkonadiError("snapshot disconnected")
            return {"ok": True, "complete": True, "items": copy.deepcopy(list(remote.values()))}
        if request["command"] == "delete-guarded":
            if control["downgrade"]:
                raise ak.AkonadiError("unsupported guarded command")
            assert archive.load()["operations"]["copy"]["phase"] == "prepared"
            assert request["id"] == remote["copy"]["id"] and request["revision"] == remote["copy"]["revision"]
            if control["conflict"]:
                raise ak.AkonadiError("revision conflict")
            del remote["copy"]
            writes.append("copy")
            if control["crash"]:
                raise ak.AkonadiError("lost response after deletion")
            return {"ok": True}
        raise AssertionError("Unexpected helper operation: " + request["command"])

    monkeypatch.setattr(ak, "helper_request", helper)
    monkeypatch.setattr(m, "eds_laden", lambda: False)
    monkeypatch.setattr(m, "akonadi_quellen_status", lambda: {
        "verfuegbar": True, "fehler": "", "adressbuecher": [], "kalender": [{
            "uid": SOURCE, "name": "Synthetic", "rights": ["read"] if readonly else ["read", "create", "change", "delete"],
            "generation": 3, "instance": "default"}]})
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    monkeypatch.setattr(m, "_sync_transaktionsschluessel", lambda: b"a" * 32)
    items = []
    for uid in remote:
        item = local(uid, source=SOURCE)
        item["icsQuelleId"] = KEY
        item["syncQuellen"] = {KEY: {"id": uid, "eigen": False}, "eds:other": {"id": "preserve-" + uid}}
        items.append(item)
    state = {"jahrestage": items, "syncEpoch": "epoch", "syncMetadaten": {"ersteSyncLoeschungsfrei": restore}}

    def run():
        result = m.Fenster._sync_ausfuehren(object(), {"daten": copy.deepcopy(state), "wahl": {
            "kalenderUid": SOURCE, "kalenderUids": [SOURCE]}}, antworten=False, snapshot=False)
        state.update(result)
        return result

    return remote, writes, calls, control, state, run, archive


def test_current_helper_cleans_once_and_keeps_aliases_on_replay(monkeypatch, tmp_path):
    remote, writes, calls, _, state, run, _ = fixture(monkeypatch, tmp_path)
    assert run()["ok"] and writes == ["copy"] and set(remote) == {"original"}
    assert all(item["uid"] == "original" for item in state["jahrestage"])
    assert run()["ok"] and writes == ["copy"]
    assert "delete" not in calls and "create" not in calls


@pytest.mark.parametrize("option", ["legacy", "readonly", "restore"])
def test_old_helpers_and_deletion_barriers_do_not_mutate(monkeypatch, tmp_path, option):
    remote, writes, calls, _, _, run, archive = fixture(monkeypatch, tmp_path, **{option: True})
    assert run()["ok"] and len(remote) == 2 and writes == [] and not archive.exists()
    assert "delete-guarded" not in calls


def test_lost_delete_response_recovers_without_second_delete(monkeypatch, tmp_path):
    remote, writes, _, control, state, run, archive = fixture(monkeypatch, tmp_path)
    control["crash"] = True
    with pytest.raises(ak.AkonadiError, match="lost response"):
        run()
    assert archive.load()["operations"]["copy"]["phase"] == "prepared"
    assert state["jahrestage"][1]["uid"] == "copy"
    control["crash"] = False
    assert run()["ok"] and set(remote) == {"original"} and writes == ["copy"]


def test_revision_conflict_does_not_rebind_or_delete(monkeypatch, tmp_path):
    remote, writes, _, control, state, run, _ = fixture(monkeypatch, tmp_path)
    before = copy.deepcopy(state)
    control["conflict"] = True
    with pytest.raises(ak.AkonadiError, match="revision conflict"):
        run()
    assert state == before and len(remote) == 2 and writes == []


def test_failed_fresh_snapshot_is_not_absence(monkeypatch, tmp_path):
    _, _, _, control, _, _, _ = fixture(monkeypatch, tmp_path)
    client = ak.AkonadiClient("calendar", SOURCE, generation=3, instance="default")
    client.event_texts()
    control["fail_snapshot"] = True
    with pytest.raises(ak.AkonadiError, match="snapshot disconnected"):
        client.current_event_text("copy")


def test_helper_downgrade_after_capability_never_falls_back(monkeypatch, tmp_path):
    remote, writes, calls, control, _, run, _ = fixture(monkeypatch, tmp_path)
    control["downgrade"] = True
    with pytest.raises(ak.AkonadiError, match="unsupported guarded"):
        run()
    assert len(remote) == 2 and writes == [] and "delete" not in calls


@pytest.mark.parametrize("generation,instance,epoch", [(4, "default", "epoch"), (3, "other", "epoch"), (3, "default", "restored")])
def test_foreign_database_or_restore_epoch_does_not_adopt_recovery(monkeypatch, tmp_path, generation, instance, epoch):
    remote, writes, _, control, state, run, _ = fixture(monkeypatch, tmp_path)
    control["crash"] = True
    with pytest.raises(ak.AkonadiError, match="lost response"):
        run()
    items = copy.deepcopy(state["jahrestage"])
    client = ak.AkonadiClient("calendar", SOURCE, generation=generation, instance=instance)
    result = m.akonadi_geburtstagsdubletten_bereinigen(client, SOURCE, KEY, items,
        [item["content"] for item in remote.values()], epoch)
    assert result == {"removed": 0, "recovered": 0}
    assert items[1]["uid"] == "copy" and writes == ["copy"]
