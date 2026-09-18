import importlib.machinery
import importlib.util
import os


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
