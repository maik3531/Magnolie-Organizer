import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

import pytest


PROGRAM = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
LOADER = importlib.machinery.SourceFileLoader("magnolie_akonadi_sync", str(PROGRAM))
SPEC = importlib.util.spec_from_loader("magnolie_akonadi_sync", LOADER)
m = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(m)


EVENT = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:event-1\r\n"
         "DTSTART:20260902T100000Z\r\nDTEND:20260902T110000Z\r\n"
         "SUMMARY:KDE appointment\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
CARD = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-1\r\nN:Example;Klara;;;\r\n"
        "FN:Klara Example\r\nEMAIL:klara@example.test\r\nEND:VCARD\r\n")


def fake_helper(tmp_path):
    path = tmp_path / "magnolie-akonadi-helper"
    log = tmp_path / "requests.jsonl"
    path.write_text("""#!/usr/bin/env python3
import json, sys
request = json.load(sys.stdin)
with open(%r, "a", encoding="utf-8") as stream:
    stream.write(json.dumps(request) + "\\n")
command = request["command"]
kind = request.get("kind")
if command == "status":
    response = {"ok": True,
        "calendars": [{"collection": 7, "name": "KDE / Work",
            "rights": ["read", "create", "change", "delete"], "generation": 3,
            "instance": "default"}],
        "addressbooks": [{"collection": 8, "name": "KDE / People",
            "rights": ["read", "create", "change", "delete"], "generation": 3,
            "instance": "default"}]}
elif command == "snapshot" and kind == "calendar":
    response = {"ok": True, "complete": True, "items": [
        {"id": 70, "revision": 2, "gid": "event-1", "content": %r}]}
elif command == "snapshot":
    response = {"ok": True, "complete": True, "items": [
        {"id": 80, "revision": 4, "gid": "contact-1", "content": %r}]}
elif command == "modify":
    response = {"ok": True, "item": {"id": request["id"],
        "revision": request["revision"] + 1, "gid": "event-1",
        "content": request["content"]}}
elif command == "exists":
    response = {"ok": True, "exists": True}
else:
    response = {"ok": False, "error": "unexpected command"}
json.dump(response, sys.stdout)
""" % (str(log), EVENT, CARD), encoding="utf-8")
    path.chmod(0o755)
    return path, log


class Probe:
    def antwort(self, name, payload):
        self.name = name
        self.payload = payload


def request_data(termine=None, kontakte=None, last_sync=0, metadata=None):
    return {"wahl": {"kalenderUid": "akonadi-calendar:7",
                     "kalenderUids": ["akonadi-calendar:7"],
                     "adressbuchUid": "akonadi-addressbook:8"},
            "daten": {"termine": termine or [], "kontakte": kontakte or [],
                      "jahrestage": [],
                      "geloescht": {"termine": [], "kontakte": []},
                      "letzterSync": last_sync, "letzteSyncs": {"kalender": {}},
                      "syncMetadaten": metadata or {}}}


def test_akonadi_sources_join_system_account_status(tmp_path, monkeypatch):
    helper, _log = fake_helper(tmp_path)
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", str(helper))
    status = m.akonadi_quellen_status()
    assert status["verfuegbar"] and not status["fehler"]
    assert status["kalender"][0]["uid"] == "akonadi-calendar:7"
    assert status["adressbuecher"][0]["uid"] == "akonadi-addressbook:8"


def test_akonadi_status_error_stays_provider_local(monkeypatch):
    monkeypatch.setattr(m, "eds_laden", lambda: False)
    monkeypatch.setitem(m._EDS, "fehler", "EDS unavailable")
    monkeypatch.setattr(m, "nextcloud_status", lambda: {
        "kalender": [], "adressbuecher": [], "fehler": ""})
    monkeypatch.setattr(m, "akonadi_quellen_status", lambda: {
        "verfuegbar": True, "kalender": [], "adressbuecher": [],
        "fehler": "Akonadi is not running"})
    probe = Probe()
    m.Fenster._eds_status_arbeit(probe)
    assert probe.payload["fehler"] == "EDS unavailable"
    assert probe.payload["akonadi"]["fehler"] == "Akonadi is not running"


def test_akonadi_calendar_and_addressbook_use_existing_resources(tmp_path, monkeypatch):
    helper, log = fake_helper(tmp_path)
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", str(helper))
    probe = Probe()
    first = m.Fenster._sync_ausfuehren(probe, request_data(), snapshot=False)
    assert probe.name == "App.syncFertig" and first["ok"]
    assert first["termine"][0]["uid"] == "event-1"
    assert first["termine"][0]["kalenderQuelle"]["anbieter"] == "KDE/Akonadi"
    assert "akonadi:akonadi-calendar:7" in first["termine"][0]["syncQuellen"]
    assert first["kontakte"][0]["uid"] == "contact-1"
    assert first["kontaktVorschau"]["modus"] == "erstimport"
    commands = [json.loads(line)["command"] for line in
                log.read_text(encoding="utf-8").splitlines()]
    assert commands == ["status", "snapshot", "snapshot"]

    changed = dict(first["termine"][0], titel="Locally changed",
                   geaendert=first["letzterSync"] + 1000)
    second_request = request_data([changed], first["kontakte"],
                                  first["letzterSync"], first["syncMetadaten"])
    second_request["daten"]["letzteSyncs"] = first["letzteSyncs"]
    second = m.Fenster._sync_ausfuehren(Probe(), second_request, snapshot=False)
    assert second["ok"]
    requests = [json.loads(line) for line in
                log.read_text(encoding="utf-8").splitlines()]
    modify = next(request for request in requests if request["command"] == "modify")
    assert modify["id"] == 70 and modify["revision"] == 2
    assert "BEGIN:VCALENDAR" in modify["content"] and "Locally changed" in modify["content"]


def test_akonadi_generation_change_requires_reselection(tmp_path, monkeypatch):
    helper, _log = fake_helper(tmp_path)
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", str(helper))
    request = request_data(metadata={"akonadi": {"bindungen": {
        "akonadi-calendar:7": {"generation": 2, "instance": "default"},
        "akonadi-addressbook:8": {"generation": 2, "instance": "default"}}}})
    with pytest.raises(RuntimeError) as fehler:
        m.Fenster._sync_ausfuehren(Probe(), request, snapshot=False)
    assert str(fehler.value) == m._(
        "The KDE/Akonadi database was replaced. Select the source again in Settings.")


def test_read_only_akonadi_calendar_is_imported_without_remote_write(tmp_path, monkeypatch):
    helper, log = fake_helper(tmp_path)
    source = helper.read_text(encoding="utf-8").replace(
        '["read", "create", "change", "delete"]', '["read"]')
    helper.write_text(source, encoding="utf-8")
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", str(helper))
    local = m.ics_lesen(EVENT.replace("event-1", "local-1").replace(
        "KDE appointment", "Local only"), jahrestage_als_termine=True)["termine"][0]
    local.update(syncKalenderUid="akonadi-calendar:7", sync=False)
    result = m.Fenster._sync_ausfuehren(
        Probe(), request_data(termine=[local]), snapshot=False)
    event = next(item for item in result["termine"] if item["uid"] == "event-1")
    assert not result["ok"] and event["icsReadOnly"] and event["sync"] is True
    assert event["icsReadOnlyGrund"] == "Akonadi"
    pending = next(item for item in result["termine"] if item["uid"] == "local-1")
    assert not pending.get("icsReadOnly") and pending["syncKalenderUid"] == \
        "akonadi-calendar:7"
    assert pending["sync"] is False and result["fehler"]
    commands = [json.loads(line)["command"] for line in
                log.read_text(encoding="utf-8").splitlines()]
    assert commands == ["status", "snapshot", "snapshot"]


def test_akonadi_partial_rights_apply_per_operation(tmp_path, monkeypatch):
    helper, log = fake_helper(tmp_path)
    source = helper.read_text(encoding="utf-8").replace(
        '["read", "create", "change", "delete"]', '["read", "change"]', 1)
    helper.write_text(source, encoding="utf-8")
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", str(helper))
    first = m.Fenster._sync_ausfuehren(Probe(), request_data(), snapshot=False)
    changed = dict(first["termine"][0], titel="Allowed change",
                   geaendert=first["letzterSync"] + 1000)
    local = m.ics_lesen(EVENT.replace("event-1", "local-1").replace(
        "KDE appointment", "Pending create"), jahrestage_als_termine=True)["termine"][0]
    local.update(syncKalenderUid="akonadi-calendar:7", sync=False)
    request = request_data([changed, local], first["kontakte"],
                           first["letzterSync"], first["syncMetadaten"])
    request["daten"]["letzteSyncs"] = first["letzteSyncs"]
    result = m.Fenster._sync_ausfuehren(Probe(), request, snapshot=False)

    pending = next(item for item in result["termine"] if item["uid"] == "local-1")
    requests = [json.loads(line) for line in
                log.read_text(encoding="utf-8").splitlines()]
    assert any(item["command"] == "modify" for item in requests)
    assert not any(item["command"] == "create" for item in requests)
    assert pending["titel"] == "Pending create" and pending["sync"] is False
    assert pending["syncKalenderUid"] == "akonadi-calendar:7"
    assert result["ok"] is False


def test_akonadi_delete_policy_retains_pending_tombstone(tmp_path, monkeypatch):
    helper, log = fake_helper(tmp_path)
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", str(helper))
    request = request_data(last_sync=1000)
    request["daten"]["geloescht"]["termine"] = [{
        "uid": "event-1", "zeit": 2000,
        "syncKalenderUid": "akonadi-calendar:7"}]
    result = m.Fenster._sync_ausfuehren(Probe(), request, snapshot=False)
    assert result["ok"] is False
    assert not any(item["uid"] == "event-1" for item in result["termine"])
    assert result["geloescht"]["termine"] == [{
        "uid": "event-1", "zeit": 2000,
        "syncKalenderUid": "akonadi-calendar:7"}]
    assert result["fehler"] and result["bericht"]
    commands = [json.loads(line)["command"] for line in
                log.read_text(encoding="utf-8").splitlines()]
    assert "delete" not in commands
