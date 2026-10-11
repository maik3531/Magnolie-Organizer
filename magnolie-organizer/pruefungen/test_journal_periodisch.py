import importlib.machinery
import importlib.util
import os
import threading
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace


PROGRAM = os.path.join(os.path.dirname(__file__), "..", "bin", "magnolie-organizer")
LOADER = importlib.machinery.SourceFileLoader("magnolie_journal_periodisch", PROGRAM)
SPEC = importlib.util.spec_from_loader("magnolie_journal_periodisch", LOADER)
m = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(m)


def test_periodic_maintenance_expires_old_snapshots_without_new_snapshot(monkeypatch):
    old = {"snapshotId": "old", "reason": "pre-sync",
           "createdAt": "2026-01-01T00:00:00Z"}
    calls = []
    lists = iter(([old], []))
    monkeypatch.setattr(m, "journal_liste", lambda **_kwargs: list(next(lists)))
    monkeypatch.setattr(m, "journal_retention", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(m, "journal_faellig", lambda *_args: False)

    class Probe:
        _gesperrt = False
        _operation_laeuft = False
        _sync_laeuft = False
        _aktuelle_daten = {"einstellungen": {"allgemein": {
            "wiederherstellungsintervall": "off",
            "wiederherstellungsaufbewahrung": "days",
            "wiederherstellungstage": 14}}}

        def _journal_stand_melden(self):
            calls.append("reported")

    assert m.Fenster._journal_periodisch(Probe()) is True
    assert calls == [{"maximum": None, "tage": 14}, "reported"]


def test_changed_documents_share_interval_snapshot_but_manual_and_restore_do_not(monkeypatch):
    now = datetime(2026, 10, 11, 10, tzinfo=timezone.utc)
    snapshots = []
    original_time = m._journal_zeit
    monkeypatch.setattr(m, "_journal_zeit", lambda value=None: now if value is None else original_time(value))
    monkeypatch.setattr(m, "journal_liste", lambda **_kwargs: list(reversed(snapshots)))
    checked = []
    monkeypatch.setattr(m, "journal_snapshot_lesen", lambda ident, _password: checked.append(ident))
    def create(data, reason, _password, **_kwargs):
        item = {"snapshotId": str(len(snapshots)), "reason": reason, "createdAt": now.isoformat(), "title": data["title"]}
        snapshots.append(item); return item
    monkeypatch.setattr(m, "journal_snapshot_erzeugen", create)
    host = SimpleNamespace(_daten_sperre=threading.RLock(), _kennwort="", _aktuelle_daten={"title": "Before",
        "einstellungen": {"allgemein": {"wiederherstellungsmodus": "interval", "wiederherstellungsminuten": 30}}})
    first = m.Fenster._journal_snapshot(host, "pre-change")
    host._aktuelle_daten["title"] = "Changed"; now += timedelta(minutes=10)
    assert m.Fenster._journal_snapshot(host, "pre-contact") == first
    assert checked == [first["snapshotId"]]
    assert m.Fenster._journal_snapshot(host, "manual")["reason"] == "manual"
    assert m.Fenster._journal_snapshot(host, "pre-restore")["reason"] == "pre-restore"
    now += timedelta(minutes=21)
    assert m.Fenster._journal_snapshot(host, "pre-change")["snapshotId"] != first["snapshotId"]
    host._aktuelle_daten["einstellungen"]["allgemein"]["wiederherstellungsmodus"] = "change"
    host._aktuelle_daten["title"] = "Every changed document"
    assert m.Fenster._journal_snapshot(host, "pre-contact")["title"] == "Every changed document"
