"""Exercise the real EDS sync orchestrator using an isolated provider and encrypted journal."""
import copy
import pytest
from test_eds_calendar_dedup import m
from test_calendar_birthday_dedup import event, local


def fixture(monkeypatch, tmp_path, *, readonly=False, initial=False):
    remote = {"original": event("original"), "copy": event("copy", created="20260101T000000Z")}
    writes = []
    class Component:
        def __init__(self, text): self.text = text
        def as_ical_string(self): return self.text
    class Client:
        def is_readonly(self): return readonly
        def is_online(self): return True
        def get_object_sync(self, uid, rid, cancel):
            if uid not in remote: raise LookupError("synthetic missing object")
            return True, Component(remote[uid])
    client = Client()
    monkeypatch.setattr(m, "eds_laden", lambda: True)
    monkeypatch.setattr(m, "eds_registry", lambda: object())
    monkeypatch.setattr(m, "_sync_quellenname", lambda *args: "Synthetic calendar")
    monkeypatch.setattr(m, "eds_kalender_client", lambda *args: client)
    monkeypatch.setattr(m, "eds_events_lesen", lambda _: list(remote.values()))
    monkeypatch.setattr(m, "eds_event_fehlend_bestaetigt", lambda _, uid: uid not in remote)
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    monkeypatch.setattr(m, "_sync_transaktionsschluessel", lambda: bytes([17]) * 32)
    def remove(_, uid):
        assert uid == "copy"
        archive = m.kalender_dubletten.CleanupArchive(tmp_path, "eds:calendar\0epoch", lambda: bytes([17])*32)
        saved = archive.load()
        assert saved["operations"][uid]["phase"] == "prepared"
        assert saved["operations"][uid]["removeText"] == remote[uid]
        writes.append(("delete", uid)); del remote[uid]
    monkeypatch.setattr(m, "eds_event_loeschen_abgesichert", remove)
    monkeypatch.setattr(m, "eds_event_anlegen", lambda *_: (_ for _ in ()).throw(AssertionError("Unexpected creation")))
    monkeypatch.setattr(m, "eds_event_aendern", lambda *_: (_ for _ in ()).throw(AssertionError("Unexpected update")))
    state = {"termine": [], "kontakte": [], "aufgaben": [], "jahrestage": [local("original"), local("copy")],
        "syncEpoch": "epoch", "syncMetadaten": {"ersteSyncLoeschungsfrei": initial}, "geloescht": {}}
    def run():
        result = m.Fenster._sync_ausfuehren(object(), {"daten": copy.deepcopy(state), "wahl": {
            "kalenderUid": "calendar", "kalenderUids": ["calendar"]}}, antworten=False, snapshot=False)
        state.update(result)
        return result
    return remote, writes, state, run


def test_sync_removes_confirmed_duplicate_rebinds_uid_and_replays_without_new_event(monkeypatch, tmp_path):
    remote, writes, state, run = fixture(monkeypatch, tmp_path)
    result = run()
    assert result["ok"] and set(remote) == {"original"} and writes == [("delete", "copy")]
    assert len(result["jahrestage"]) == 1 and result["jahrestage"][0]["uid"] == "original"
    assert result["jahrestage"][0]["syncQuellen"]["eds:calendar"]["id"] == "original"
    assert run()["ok"] and writes == [("delete", "copy")]


@pytest.mark.parametrize("readonly,initial", [(True, False), (False, True)])
def test_readonly_and_first_sync_deletion_barrier_preserve_both_remote_copies(monkeypatch, tmp_path, readonly, initial):
    remote, writes, _, run = fixture(monkeypatch, tmp_path, readonly=readonly, initial=initial)
    assert run()["ok"]
    assert set(remote) == {"original", "copy"} and writes == []


def test_strict_eds_delete_uses_conflict_fail_and_checks_online_state(monkeypatch):
    calls = []
    class Client:
        online = True
        def is_online(self): return self.online
        def remove_object_sync(self, *args): calls.append(args); return True
    fake = type("ECal", (), {"OperationFlags": type("Flags", (), {"CONFLICT_FAIL": 8, "DISABLE_ITIP_MESSAGE": 16}),
                             "ObjModType": type("Mod", (), {"ALL": 3})})
    monkeypatch.setitem(m._EDS, "ECal", fake)
    client = Client(); m.eds_event_loeschen_abgesichert(client, "copy")
    assert calls[0][:4] == ("copy", None, 3, 24)
    client.online = False
    with pytest.raises(RuntimeError): m.eds_event_loeschen_abgesichert(client, "other")
    assert len(calls) == 1
