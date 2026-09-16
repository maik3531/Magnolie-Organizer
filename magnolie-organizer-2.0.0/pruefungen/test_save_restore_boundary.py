"""Production save worker/restore with synthetic files; no desktop or user profile."""
import copy
import json
import queue
import threading
from pathlib import Path

import pytest

from modul_laden import quellmodul_laden


@pytest.fixture
def native(monkeypatch, tmp_path):
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        target = tmp_path / key
        target.mkdir()
        monkeypatch.setenv(key, str(target))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent-save-test-bus")
    m = quellmodul_laden("magnolie_save_boundary", Path(__file__).resolve().parents[1] / "bin/magnolie-organizer")
    monkeypatch.setattr(m, "daten_datei", lambda: str(tmp_path / "daten.json"))
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    return m


def fixture_data(label):
    return {"version": 6, "syncEpoch": "before", "syncMetadaten": {"syncEpoch": "before"},
        "notizen": [{"id": "note", "text": label, "html": label,
            "anhaenge": [{"id": "attachment", "daten": "data:text/plain;base64,c3ludGhldGlj"}]}],
        "termine": [{"id": "event", "titel": label}], "kontakte": [{"id": "contact"}],
        "aufgaben": [{"id": "task"}], "smsPlanung": [{"id": "sms", "status": "planned"}],
        "smsVerlauf": [{"text": "synthetic SMS"}], "customOrganizer": {"modules": [{"id": "custom"}]},
        "einstellungen": {"sync": {}, "allgemein": {}}, "personalSync": {"actor_id": "synthetic-actor"}}


class Probe:
    def __init__(self, m, data):
        self.m = m
        self._aktuelle_daten = copy.deepcopy(data)
        self._daten_sperre = threading.RLock()
        self._speicher_auftraege = queue.Queue()
        self._kennwort = ""
        self._operation_laeuft = self._sync_laeuft = False
        self.responses = []

    def _vielleicht_verschluesseln(self, text): return text
    def _journal_stand_melden(self): pass
    def _erinnerungsprojektion_aktualisieren(self, kennwort=None):
        return self.m.Fenster._erinnerungsprojektion_aktualisieren(self, kennwort)
    def _journal_snapshot(self, reason):
        return self.m.journal_snapshot_erzeugen(self._aktuelle_daten, reason, basis=self.m.daten_verzeichnis())
    def antwort(self, name, payload): self.responses.append((name, payload))
    def save(self, serial, data):
        self._speicher_auftraege.put((serial, json.dumps(data)))
        self._speicher_auftraege.put(None)
        self.m.Fenster._speicher_lauf(self)
        return next(value for name, value in reversed(self.responses) if name == "App.gespeichert")


def test_native_failed_save_restore_late_old_save_and_restart(native, monkeypatch):
    m = native
    old = fixture_data("old failed content")
    restored = fixture_data("restored full content")
    initial = fixture_data("committed before failed edit")
    probe = Probe(m, initial)
    m.speichere_text(json.dumps(initial))
    snapshot = m.journal_snapshot_erzeugen(restored, "manual", basis=m.daten_verzeichnis())
    write = m.speichere_text
    monkeypatch.setattr(m, "speichere_text", lambda text: (_ for _ in ()).throw(OSError("synthetic disk error")))
    assert not probe.save(41, old)["ok"]
    monkeypatch.setattr(m, "speichere_text", write)
    m.Fenster._journal_wiederherstellen(probe, snapshot["snapshotId"])
    assert probe.responses[-1][1]["ok"]
    durable = json.loads(Path(m.daten_datei()).read_text())
    assert durable["syncEpoch"] != old["syncEpoch"]
    for field in ("notizen", "smsVerlauf", "customOrganizer", "termine", "kontakte"):
        assert durable[field] == restored[field]
    assert durable["smsPlanung"] == [{"id": "sms", "status": "paused"}]
    assert not probe.save(42, old)["ok"], "post-restore old full-text save must be rejected inside native lock"
    assert json.loads(Path(m.daten_datei()).read_text()) == durable
    restarted = Probe(m, json.loads(Path(m.daten_datei()).read_text()))
    assert not restarted.save(1, old)["ok"], "persisted restore epoch also guards a restarted worker"
    edited = copy.deepcopy(durable)
    edited["notizen"][0]["text"] = "current edit"
    assert restarted.save(2, edited)["ok"]
    assert json.loads(Path(m.daten_datei()).read_text()) == edited


def test_native_queued_save_checks_generation_at_execution(native):
    m = native
    old = fixture_data("queued")
    probe = Probe(m, old)
    m.speichere_text(json.dumps(old))
    probe._speicher_auftraege.put((71, json.dumps(old)))
    snapshot = m.journal_snapshot_erzeugen(fixture_data("restored"), "manual", basis=m.daten_verzeichnis())
    m.Fenster._journal_wiederherstellen(probe, snapshot["snapshotId"])
    durable = Path(m.daten_datei()).read_text()
    probe._speicher_auftraege.put(None)
    m.Fenster._speicher_lauf(probe)
    assert probe.responses[-1][1] == {"id": 71, "ok": False,
        "fehler": probe.responses[-1][1]["fehler"]}
    assert Path(m.daten_datei()).read_text() == durable


def test_native_archive_restore_publishes_generation_before_next_save(native):
    m = native
    old = fixture_data("old")
    probe = Probe(m, old)
    m.speichere_text(json.dumps(old))
    archive = Path(m.daten_verzeichnis()) / "synthetic.magnolie"
    archive.write_text(m.gesamtarchiv_erzeugen(fixture_data("archive restored")))
    m.Fenster._gesamtarchiv_importieren(probe, str(archive), "", "vollstaendig-ersetzen")
    assert probe.responses[-1][1]["ok"], probe.responses[-1]
    durable = json.loads(Path(m.daten_datei()).read_text())
    assert probe._aktuelle_daten == durable, "native live generation must match the committed archive before releasing the lock"
    assert not probe.save(81, old)["ok"]
    durable["notizen"][0]["text"] = "edited after archive restore"
    assert probe.save(82, durable)["ok"]
    assert json.loads(Path(m.daten_datei()).read_text()) == durable
