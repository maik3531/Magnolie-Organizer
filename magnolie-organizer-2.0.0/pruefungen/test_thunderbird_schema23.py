import importlib.machinery
import importlib.util
import io
import os
import sqlite3
import zipfile
from datetime import datetime, timezone

import pytest


PROGRAMM = os.path.join(os.path.dirname(__file__), "..", "bin", "magnolie-organizer")
lader = importlib.machinery.SourceFileLoader("magnolie_tb23", PROGRAMM)
spec = importlib.util.spec_from_loader("magnolie_tb23", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


def native(jahr, monat, tag, stunde=0):
    return int(datetime(jahr, monat, tag, stunde, tzinfo=timezone.utc).timestamp() * 1000000)


def test_schema23_serienausnahme_und_zusatztabellen(tmp_path):
    pfad = tmp_path / "local.sqlite"
    db = sqlite3.connect(pfad)
    db.execute("""CREATE TABLE cal_events (
        cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, privacy TEXT,
        ical_status TEXT, flags INTEGER, event_start INTEGER, event_start_tz TEXT,
        event_end INTEGER, event_end_tz TEXT, recurrence_id INTEGER,
        recurrence_id_tz TEXT)""")
    db.execute("""CREATE TABLE cal_properties (
        cal_id TEXT, item_id TEXT, recurrence_id INTEGER, recurrence_id_tz TEXT,
        key TEXT, value BLOB)""")
    db.execute("""CREATE TABLE cal_parameters (
        cal_id TEXT, item_id TEXT, recurrence_id INTEGER, recurrence_id_tz TEXT,
        key1 TEXT, key2 TEXT, value BLOB)""")
    for tabelle in ("cal_recurrence", "cal_alarms", "cal_attendees",
                    "cal_attachments", "cal_relations"):
        db.execute("""CREATE TABLE %s (
            cal_id TEXT, item_id TEXT, recurrence_id INTEGER,
            recurrence_id_tz TEXT, icalString TEXT)""" % tabelle)

    master = ("c", "serie", native(2026, 1, 1), "Wochenserie", "PUBLIC",
              "CONFIRMED", 16 | 32, native(2026, 8, 3, 9), "UTC",
              native(2026, 8, 3, 10), "UTC", None, None)
    ausnahme_id = native(2026, 8, 10, 9)
    ausnahme = ("c", "serie", native(2026, 1, 2), "Verschoben", "PRIVATE",
                "TENTATIVE", 0, native(2026, 8, 10, 11), "UTC",
                native(2026, 8, 10, 12), "UTC", ausnahme_id, "UTC")
    db.executemany("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (master, ausnahme))
    db.executemany("INSERT INTO cal_properties VALUES (?,?,?,?,?,?)", (
        ("c", "serie", None, None, "DESCRIPTION", "Master-Notiz"),
        ("c", "serie", ausnahme_id, "UTC", "DESCRIPTION", "Ausnahme-Notiz"),
        ("c", "serie", ausnahme_id, "UTC", "LOCATION", "Raum 1"),
        ("c", "serie", ausnahme_id, "UTC", "LOCATION", "Raum 2"),
        ("c", "serie", ausnahme_id, "UTC", "ORGANIZER", "mailto:orga@example.org"),
        ("c", "serie", ausnahme_id, "UTC", "ATTENDEE", "mailto:mia@example.org"),
        ("c", "serie", ausnahme_id, "UTC", "ATTENDEE", "mailto:tom@example.org"),
        ("c", "serie", ausnahme_id, "UTC", "ATTACH", "file:///tmp/lokal.pdf")))
    db.executemany("INSERT INTO cal_parameters VALUES (?,?,?,?,?,?,?)", (
        ("c", "serie", ausnahme_id, "UTC", "ATTENDEE", "CN", "Mia Muster"),
        ("c", "serie", ausnahme_id, "UTC", "ATTENDEE", "CN", "Tom Test")))
    db.execute("INSERT INTO cal_recurrence VALUES (?,?,?,?,?)",
               ("c", "serie", None, None, "RRULE:FREQ=WEEKLY;BYDAY=MO"))
    db.execute("INSERT INTO cal_alarms VALUES (?,?,?,?,?)", ("c", "serie", ausnahme_id,
               "UTC", "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM"))
    db.execute("INSERT INTO cal_attendees VALUES (?,?,?,?,?)", ("c", "serie", ausnahme_id,
               "UTC", "ATTENDEE;ROLE=REQ-PARTICIPANT:mailto:max@example.org"))
    db.execute("INSERT INTO cal_attachments VALUES (?,?,?,?,?)", ("c", "serie", ausnahme_id,
               "UTC", "ATTACH;FMTTYPE=application/pdf:https://example.org/a.pdf"))
    db.commit()
    db.close()

    ergebnis = m._tb_normalisierte_kalenderdaten(str(pfad))
    assert len(ergebnis["termine"]) == 2
    master_import = next(e for e in ergebnis["termine"] if e["titel"] == "Wochenserie")
    ausnahme_import = next(e for e in ergebnis["termine"] if e["titel"] == "Verschoben")
    assert master_import["notiz"] == "Master-Notiz"
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO" in master_import["icsRoundtrip"]
    assert ausnahme_import["notiz"] == "Ausnahme-Notiz"
    assert ausnahme_import["uid"].startswith("serie-magnolie-instanz-")
    assert ausnahme_import["icsSerienUid"] == "serie" and ausnahme_import["icsKomplex"]
    assert "RECURRENCE-ID:20260810T090000Z" in ausnahme_import["icsRoundtrip"]
    assert "ATTENDEE;CN=Mia Muster:mailto:mia@example.org" in ausnahme_import["icsRoundtrip"]
    assert "ATTENDEE;CN=Tom Test:mailto:tom@example.org" in ausnahme_import["icsRoundtrip"]
    assert ausnahme_import["icsRoundtrip"].count("LOCATION:Raum 1") == 1
    assert ausnahme_import["icsRoundtrip"].count("LOCATION:Raum 2") == 1
    assert "ORGANIZER:mailto:orga@example.org" in ausnahme_import["icsRoundtrip"]
    assert "ATTACH:file:///tmp/lokal.pdf" in ausnahme_import["icsRoundtrip"]
    assert "TRIGGER:-PT15M" in ausnahme_import["icsRoundtrip"]
    assert "ATTACH;FMTTYPE=application/pdf:https://example.org/a.pdf" in ausnahme_import["icsRoundtrip"]
    assert ausnahme_import["icsQuelleId"] == "thunderbird:c"
    assert ausnahme_import["icsQuelleName"] == "Thunderbird: c"


def test_takeout_zip_und_google_csv_werden_begrenzt_gelesen():
    kalender = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Arbeit\r\nBEGIN:VEVENT\r\n"
                 b"UID:z1\r\nDTSTART;VALUE=DATE:20260817\r\nSUMMARY:Takeout\r\n"
                 b"END:VEVENT\r\nEND:VCALENDAR\r\n")
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr("../../Takeout/Calendar/Kalender.ics", kalender)
        archiv.writestr("Takeout/Calendar/Privat.ics", kalender.replace(
            b"UID:z1", b"UID:z2").replace(b"X-WR-CALNAME:Arbeit\r\n", b""))
        archiv.writestr("Takeout/README.html", b"ignorieren")
    importiert = m.import_rohdaten_lesen("ics", puffer.getvalue(), "takeout.zip")
    assert len(importiert["termine"]) == 2
    nach_uid = {item["uid"]: item for item in importiert["termine"]}
    assert nach_uid["z1"]["icsQuelleName"] == "Arbeit"
    assert nach_uid["z2"]["icsQuelleName"] == "Takeout/Calendar/Privat.ics"
    assert ".." not in nach_uid["z1"]["icsQuelleName"]
    wiederholt = m.import_rohdaten_lesen("ics", puffer.getvalue(), "takeout.zip")
    assert [t["icsQuelleId"] for t in wiederholt["termine"]] == [
        t["icsQuelleId"] for t in importiert["termine"]]
    assert nach_uid["z1"]["icsQuelleId"] != nach_uid["z2"]["icsQuelleId"]

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr("Takeout/Contacts/contacts.csv",
                        "Given Name,Family Name,E-mail 1 - Value,Phone 1 - Value\r\nMia,Muster,mia@example.org,+49170\r\n")
    kontakte = m.import_rohdaten_lesen("vcf", puffer.getvalue(), "takeout.zip")["kontakte"]
    assert kontakte[0]["vorname"] == "Mia" and kontakte[0]["nachname"] == "Muster"

    bombe = io.BytesIO()
    with zipfile.ZipFile(bombe, "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr("Takeout/Calendar/bombe.ics", b"0" * 100000)
    try:
        m.import_rohdaten_lesen("ics", bombe.getvalue(), "bombe.zip")
        assert False, "hohes Kompressionsverhaeltnis wurde angenommen"
    except ValueError as fehler:
        assert "compression ratio" in str(fehler)


def test_thunderbird_zusatzgrenze_bricht_geschlossen_ab(tmp_path):
    pfad = tmp_path / "zu-viele.sqlite"
    db = sqlite3.connect(pfad)
    db.execute("""CREATE TABLE cal_events (
        cal_id TEXT, id TEXT, title TEXT, flags INTEGER,
        event_start INTEGER, event_end INTEGER)""")
    db.execute("""CREATE TABLE cal_properties (
        cal_id TEXT, item_id TEXT, key TEXT, value TEXT)""")
    db.execute("INSERT INTO cal_events VALUES (?,?,?,?,?,?)", (
        "quelle", "voll", "Voll", 0, native(2026, 8, 18, 9),
        native(2026, 8, 18, 10)))
    db.executemany("INSERT INTO cal_properties VALUES (?,?,?,?)", [
        ("quelle", "voll", "LOCATION", "Raum %d" % nummer)
        for nummer in range(m.TB_ROUNDTRIP_ZEILEN_MAX + 1)])
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="too many additional lines"):
        m._tb_normalisierte_kalenderdaten(str(pfad))


def test_attach_provider_matrix_bleibt_ohne_auswertung_opak():
    werte = [
        "https://drive.google.com/file/d/abc?x=1",
        "https://onedrive.live.com/?cid=abc&id=42",
        "https://www.dropbox.com/s/abc/a.pdf?dl=0",
        "https://cloud.example/remote.php/dav/files/user/a.pdf",
        "https://example.org/a.pdf", "http://example.org/a.pdf",
        "file:///home/user/Dokument.pdf", "web+sonder:opaque/value?x=1#anker",
    ]
    attach = "\r\n".join("ATTACH:%s" % wert for wert in werte)
    text = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:provider\r\nDTSTART;VALUE=DATE:20260818\r\nSUMMARY:Provider\r\n"
            "%s\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n" % attach)
    termin = m.ics_lesen(text)["termine"][0]
    export = m.ics_schreiben_termine([termin])
    for wert in werte:
        assert "ATTACH:%s\r\n" % wert in export


def test_remote_sieg_nimmt_ics_begleitfelder_ausserhalb_des_fachvergleichs_mit():
    lokal = [{"uid": "gleich", "datum": "2026-08-18", "titel": "Alt",
              "geaendert": 10, "sync": True, "icsRoundtrip": ["LOCATION:Alt"],
              "icsKomplex": False, "icsSerienUid": "alt"}]
    fern = {"gleich": {"uid": "gleich", "datum": "2026-08-19", "titel": "Neu",
                       "geaendert": 20, "icsRoundtrip": ["ATTACH:custom:opak"],
                       "icsKomplex": True, "icsSerienUid": "serie"}}
    gemischt, _anlegen, _aendern, _loeschen, _zaehler = m.sync_merge(
        lokal, fern, [], 0, m.TERMIN_FELDER)
    assert gemischt[0]["icsRoundtrip"] == ["ATTACH:custom:opak"]
    assert gemischt[0]["icsKomplex"] is True
    assert gemischt[0]["icsSerienUid"] == "serie"
    assert all(feld not in m.TERMIN_FELDER for feld in (
        "icsRoundtrip", "icsKomplex", "icsSerienUid"))
