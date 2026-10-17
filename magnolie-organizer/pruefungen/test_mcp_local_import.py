"""Actual local SQLite/ICS readers and correlated semantic snapshot revisions."""
import copy
import json
import sqlite3

import pytest
from test_startup_read_failure import native, Host


def make_profile(base):
    profile = base / ".thunderbird" / "owned.default"
    (profile / "calendar-data").mkdir(parents=True)
    (profile.parent / "profiles.ini").write_text("[Profile0]\nIsRelative=1\nPath=owned.default\n", encoding="utf-8")
    with sqlite3.connect(profile / "abook.sqlite") as db:
        db.execute("CREATE TABLE properties (card TEXT, name TEXT, value TEXT)")
        db.executemany("INSERT INTO properties VALUES ('owned-card',?,?)", [
            ("FirstName", "Owned"), ("LastName", "Local"), ("PrimaryEmail", "owned@example.invalid"), ("Notes", "Local 🌸 note")])
    with sqlite3.connect(profile / "calendar-data" / "local.sqlite") as db:
        db.execute("CREATE TABLE owned_events (ical TEXT)")
        db.execute("INSERT INTO owned_events VALUES (?)", ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:owned-local-event\r\nDTSTART:20300204T090000Z\r\nSUMMARY:Owned local appointment\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",))
    return profile


def test_actual_local_read_is_stable_across_generated_ids_and_detects_changes(native, tmp_path):
    base = tmp_path / "owned-home"
    profile = make_profile(base)
    first = native.lokal_scannen(str(base), False, "thunderbird")
    assert len(first["kontakte"]) == 1 and len(first["termine"]) == 1
    native.lokal_import_snapshot(first, "thunderbird", "all")
    second = native.lokal_scannen(str(base), False, "thunderbird")
    native.lokal_import_snapshot(second, "thunderbird", "all", first["revision"])
    assert first["revision"] == second["revision"]
    changed_ids = copy.deepcopy(second)
    for name in ("kontakte", "termine"):
        for record in changed_ids[name]: record["id"] = "owned-different-import-id"
    native.lokal_import_snapshot(changed_ids, "thunderbird", "all", first["revision"])
    with pytest.raises(ValueError, match="mcp_conflict"):
        native.lokal_import_snapshot(copy.deepcopy(second), "thunderbird", "contacts", first["revision"])
    with sqlite3.connect(profile / "abook.sqlite") as db:
        db.execute("UPDATE properties SET value='Owned corrected note' WHERE name='Notes'")
    changed = native.lokal_scannen(str(base), False, "thunderbird")
    with pytest.raises(ValueError, match="mcp_conflict"):
        native.lokal_import_snapshot(changed, "thunderbird", "all", first["revision"])
    contacts_only = native.lokal_scannen(str(base), True, "thunderbird")
    assert len(contacts_only["kontakte"]) == 1 and not contacts_only["termine"] and not contacts_only["geburtstage"]
    evolution = native.lokal_scannen(str(base), False, "evolution")
    assert not evolution["kontakte"] and not evolution["termine"], "Explicit source selection broadened to Thunderbird"


def test_correlated_worker_uses_real_reader_and_never_opens_gui_on_failure(native, monkeypatch, tmp_path):
    base = tmp_path / "owned-home"
    profile = make_profile(base)
    scan = native.lokal_scannen
    monkeypatch.setattr(native, "lokal_scannen", lambda **kwargs: scan(basis=str(base), **kwargs))
    host = Host(native); host._gesperrt = False; host._mcp_lokal_aktiv = True
    host._import_lokal_arbeit(True, "thunderbird", "owned-request")
    callback, result = host.responses[-1]
    assert callback == "App.importErgebnis" and result["ok"] and result["requestId"] == "owned-request"
    assert result["source"] == "thunderbird" and result["scope"] == "contacts" and len(result["kontakte"]) == 1
    assert not host._mcp_lokal_aktiv and "pfad" not in result and "bytes" not in result
    with sqlite3.connect(profile / "abook.sqlite") as db:
        db.execute("UPDATE properties SET value='Changed' WHERE name='Notes'")
    host._import_lokal_arbeit(True, "thunderbird", "owned-stale", result["revision"])
    assert host.responses[-1][1]["code"] == "conflict" and "fehler" not in host.responses[-1][1]
    host._import_lokal_arbeit(False, "windows_contacts", "owned-unsupported")
    assert host.responses[-1][1]["code"] == "unsupported_feature"
    monkeypatch.setattr(native, "lokal_scannen", lambda **kwargs: (_ for _ in ()).throw(AssertionError("Locked or busy source must not be read")))
    host._gesperrt = True
    host._import_lokal_arbeit(False, "thunderbird", "owned-locked")
    assert host.responses[-1][1]["ok"] is False and "fehler" not in host.responses[-1][1]
    host._mcp_lokal_aktiv = True
    host.bei_nachricht(json.dumps({"cmd": "import_lokal", "bereich": "alle", "quelle": "thunderbird", "requestId": "owned-busy"}))
    assert host.responses[-1][1]["code"] == "native_busy"
    host.bei_nachricht(json.dumps({"cmd": "import_lokal", "bereich": "unknown", "quelle": "thunderbird", "requestId": "owned-invalid-scope"}))
    assert host.responses[-1][1]["code"] == "native_operation_failed" and "fehler" not in host.responses[-1][1]
