import importlib.machinery
import importlib.util
import io
import os
import re
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


@pytest.fixture
def schema23_regression_db(tmp_path):
    pfad = tmp_path / "local.sqlite"
    db = sqlite3.connect(pfad)
    db.execute("CREATE TABLE cal_calendar_schema_version (version INTEGER)")
    db.execute("INSERT INTO cal_calendar_schema_version VALUES (23)")
    db.execute("""CREATE TABLE cal_events (
        cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, privacy TEXT,
        ical_status TEXT, flags INTEGER, event_start INTEGER, event_start_tz TEXT,
        event_end INTEGER, event_end_tz TEXT, recurrence_id INTEGER,
        recurrence_id_tz TEXT)""")
    db.execute("""CREATE TABLE cal_recurrence (
        cal_id TEXT, item_id TEXT, recurrence_id INTEGER,
        recurrence_id_tz TEXT, icalString TEXT)""")
    db.execute("""CREATE TABLE cal_properties (
        cal_id TEXT, item_id TEXT, recurrence_id INTEGER,
        recurrence_id_tz TEXT, key TEXT, value TEXT)""")
    db.executemany("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        ("familie", "gottfried-serie", native(2026, 1, 1), "Gottfried *65",
         "PUBLIC", "CONFIRMED", 8 | 16, native(1965, 8, 5), "floating",
         native(1965, 8, 6), "floating", None, None),
        ("arbeit", "defekte-zeile", native(2026, 1, 2), "Kaputt", "PUBLIC",
         "CONFIRMED", "kein-integer", native(2026, 8, 2, 9), "UTC",
         native(2026, 8, 2, 10), "UTC", None, None),
        ("arbeit", "eiermann-serie", native(2026, 1, 3), "Eiermann", "PUBLIC",
         "CONFIRMED", 16, native(2026, 8, 3, 9), "floating",
         native(2026, 8, 3, 10), "floating", None, None),
    ))
    db.executemany("INSERT INTO cal_recurrence VALUES (?,?,?,?,?)", (
        ("familie", "gottfried-serie", None, None, "RRULE:FREQ=YEARLY"),
        ("arbeit", "eiermann-serie", None, None,
         "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"),
    ))
    db.executemany("INSERT INTO cal_properties VALUES (?,?,?,?,?,?)", (
        ("familie", "gottfried-serie", None, None, "CATEGORIES", "Birthday"),
        ("familie", "gottfried-serie", None, None, "X-MAGNOLIE-TYPE-ID", "birthday")))
    db.commit()
    db.close()
    return pfad


def test_schema23_regression_serienidentitaet_und_fehlerzeile(
        schema23_regression_db):
    ergebnis = m._tb_normalisierte_kalenderdaten(str(schema23_regression_db))

    assert ergebnis["uebersprungen"] == 1
    assert len(ergebnis["jahrestage"]) == 1
    gottfried = ergebnis["jahrestage"][0]
    assert gottfried["name"] == "Gottfried *65"
    assert gottfried["uid"] == "gottfried-serie"
    assert gottfried["icsSerienUid"] == "gottfried-serie"

    kopie = dict(gottfried, uid="gottfried-serie-magnolie-instanz-kopie")
    nutzlast = {"termine": [], "jahrestage": [gottfried, kopie]}
    m._lokale_kalender_dubletten_bereinigen(nutzlast)
    assert len(nutzlast["jahrestage"]) == 1

    assert len(ergebnis["termine"]) == 1
    eiermann = ergebnis["termine"][0]
    assert eiermann["titel"] == "Eiermann"
    assert eiermann["wiederholung"]["art"] == "weekly"
    assert eiermann["wiederholung"]["intervall"] == 2


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
    db.executemany("INSERT INTO cal_recurrence VALUES (?,?,?,?,?)", (
        ("c", "serie", None, None, "RRULE:FREQ=WEEKLY;BYDAY=MO"),
        ("c", "serie", None, None, "EXDATE:20260817T090000Z"),
        ("c", "serie", None, None, "RDATE:20260824T150000Z")))
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
    assert "EXDATE:20260817T090000Z" in master_import["icsRoundtrip"]
    assert master_import["icsKomplex"]
    assert master_import["wiederholung"]["art"] == "weekly"
    assert master_import["icsAusnahmen"] == ["2026-08-17", "2026-08-10"]
    assert master_import["icsZusatzDaten"] == ["2026-08-24"]
    assert master_import["icsZusatzTermine"] == [
        {"datum": "2026-08-24", "zeit": "17:00"}]
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

    export = m.ics_schreiben_termine([master_import, ausnahme_import])
    assert "EXDATE:20260817T090000Z" in export
    assert "EXDATE;TZID=" in export and ":20260810T090000" in export


def test_backend_reminders_observe_series_exceptions_and_additions():
    serie = {"uid": "wecker-serie", "datum": "2026-08-03", "zeit": "09:00",
             "titel": "Wochenserie", "wiederholung": {"art": "weekly"},
             "icsAusnahmen": ["2026-08-03", "2026-08-10"],
             "icsZusatzDaten": ["2026-09-01"]}

    first = m.termine_mit_wiederholungen(
        {"termine": [serie]}, datetime(2026, 8, 3, 9), 0, 0)
    deleted = m.termine_mit_wiederholungen(
        {"termine": [serie]}, datetime(2026, 8, 10, 9), 0, 0)
    added = m.termine_mit_wiederholungen(
        {"termine": [serie]}, datetime(2026, 9, 1, 9), 0, 0)

    assert first == [] and deleted == []
    assert [item["datum"] for item in added] == ["2026-09-01"]
    zustand = {"gemeldet": {}, "letzter_lauf": ""}
    geloeschter_alarm = m.faellige_erinnerungen(
        {"termine": [serie]}, datetime(2026, 8, 10, 8, 45), zustand)
    zusatz_alarm = m.faellige_erinnerungen(
        {"termine": [serie]}, datetime(2026, 9, 1, 8, 45), zustand)
    assert geloeschter_alarm["faellig"] == []
    assert [item["datum"] for item in zusatz_alarm["faellig"]] == ["2026-09-01"]
    assert m.naechster_weckzeitpunkt(
        {"termine": [serie]}, datetime(2026, 8, 9, 12)) == \
        datetime(2026, 8, 17, 8, 45)


def test_unsupported_monthly_and_yearly_intervals_fail_closed():
    for art, start, candidate in (
            ("monthly", "2026-01-15", datetime(2026, 3, 15)),
            ("yearly", "2026-06-01", datetime(2028, 6, 1))):
        termin = {"datum": start, "wiederholung": {"art": art, "intervall": 2}}
        assert not m.wiederholung_trifft(termin, candidate)


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
        assert str(fehler)


def test_fehlerhafte_aufgabe_verwirft_nicht_die_folgenden(tmp_path):
    pfad = tmp_path / "aufgaben.sqlite"
    db = sqlite3.connect(pfad)
    db.execute("""CREATE TABLE cal_todos (
        cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, priority TEXT,
        ical_status TEXT, todo_due INTEGER, todo_due_tz TEXT,
        percent_complete TEXT)""")
    db.executemany("INSERT INTO cal_todos VALUES (?,?,?,?,?,?,?,?,?)", (
        ("c", "kaputt", 1, "Kaputt", "hoch", "NEEDS-ACTION", "kein-datum", "UTC", "offen"),
        ("c", "gueltig", 2, "Bleibt erhalten", "1", "NEEDS-ACTION", native(2026, 9, 2), "UTC", "0")))
    db.commit()
    db.close()

    ergebnis = m._tb_normalisierte_kalenderdaten(str(pfad))
    assert [aufgabe["uid"] for aufgabe in ergebnis["aufgaben"]] == ["gueltig"]
    assert ergebnis["uebersprungen"] == 1


def test_thunderbird_registry_erlaubt_nur_aktive_netz_caches(tmp_path):
    (tmp_path / "prefs.js").write_text("\n".join((
        'user_pref("calendar.registry.google.type", "gdata");',
        'user_pref("calendar.registry.google.uri", "googleapi://konto/");',
        'user_pref("calendar.registry.google.name", "Familie \\u0026 Freunde");',
        'user_pref("calendar.registry.caldav.type", "caldav");',
        'user_pref("calendar.registry.caldav.uri", "https://example.org/dav/");',
        'user_pref("calendar.registry.caldav.cache.enabled", true);',
        'user_pref("calendar.registry.aus.type", "caldav");',
        'user_pref("calendar.registry.aus.uri", "https://example.org/aus/");',
        'user_pref("calendar.registry.aus.cache.enabled", true);',
        'user_pref("calendar.registry.aus.disabled", true);',
        'user_pref("calendar.registry.lokal.type", "storage");',
        'user_pref("calendar.registry.lokal.uri", "moz-storage-calendar://");',
        'user_pref("calendar.registry.lokal.cache.enabled", true);',
        'user_pref("calendar.registry.ohnecache.type", "caldav");',
        'user_pref("calendar.registry.ohnecache.uri", "https://example.org/alt/");',
        'user_pref("calendar.registry.ohnecache.cache.enabled", false);',
        'user_pref("calendar.registry.boesartig.name", function(){});')),
        encoding="utf-8")

    kalender = m._tb_cache_kalender(str(tmp_path))
    assert set(kalender) == {"google", "caldav"}
    assert kalender["google"]["name"] == "Familie & Freunde"


def test_thunderbird_registry_ersetzt_ungueltiges_utf8(tmp_path):
    (tmp_path / "prefs.js").write_bytes(
        b'user_pref("calendar.registry.c.type", "caldav");\n'
        b'user_pref("calendar.registry.c.uri", "https://example.org/\xff");\n'
        b'user_pref("calendar.registry.c.cache.enabled", true);\n')

    assert m._tb_cache_kalender(str(tmp_path))["c"]["type"] == "caldav"


def test_cache_import_filtert_tombstones_fremde_kalender_und_waisen(tmp_path):
    pfad = tmp_path / "cache.sqlite"
    db = sqlite3.connect(pfad)
    db.execute("""CREATE TABLE cal_events (
        cal_id TEXT, id TEXT, title TEXT, flags INTEGER,
        event_start INTEGER, event_end INTEGER, recurrence_id INTEGER,
        recurrence_id_tz TEXT, offline_journal INTEGER)""")
    db.execute("""CREATE TABLE cal_todos (
        cal_id TEXT, id TEXT, title TEXT, todo_due INTEGER,
        percent_complete INTEGER, recurrence_id INTEGER,
        offline_journal INTEGER)""")
    start = native(2026, 9, 7, 9)
    ende = native(2026, 9, 7, 10)
    db.executemany("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?)", (
        ("aktiv", "normal", "Normal", 0, start, ende, None, None, None),
        ("aktiv", "neu", "Offline neu", 0, start, ende, None, None, 1),
        ("aktiv", "geaendert", "Offline geändert", 0, start, ende, None, None, 2),
        ("aktiv", "geloescht", "Gelöscht", 0, start, ende, None, None, 4),
        ("fremd", "fremd", "Fremd", 0, start, ende, None, None, None),
        ("aktiv", "serie", "Master gelöscht", 16, start, ende, None, None, 4),
        ("aktiv", "serie", "Verwaiste Ausnahme", 0, start, ende,
         start, "UTC", None)))
    db.executemany("INSERT INTO cal_todos VALUES (?,?,?,?,?,?,?)", (
        ("aktiv", "aufgabe", "Bleibt", start, 0, None, None),
        ("aktiv", "aufgabe-aus", "Gelöscht", start, 0, None, 4),
        ("fremd", "aufgabe-fremd", "Fremd", start, 0, None, None)))
    db.commit()
    db.close()

    ergebnis = m._tb_normalisierte_kalenderdaten(
        str(pfad), {"aktiv": {"name": "Google"}}, cache=True)
    assert {termin["uid"] for termin in ergebnis["termine"]} == {
        "normal", "neu", "geaendert"}
    assert [aufgabe["uid"] for aufgabe in ergebnis["aufgaben"]] == ["aufgabe"]
    assert all(eintrag["icsQuelleName"] == "Thunderbird: Google"
               for eintrag in ergebnis["termine"] + ergebnis["aufgaben"])
    assert ergebnis["uebersprungen"] == 1


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

    meldung = m._("The Thunderbird calendar entry contains too many additional lines.")
    with pytest.raises(RuntimeError, match=re.escape(meldung)):
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
              "icsKomplex": False, "icsSerienUid": "alt",
              "icsAusnahmen": ["2026-08-20"],
              "icsZusatzDaten": ["2026-08-21"]}]
    fern = {"gleich": {"uid": "gleich", "datum": "2026-08-19", "titel": "Neu",
                        "geaendert": 20, "icsRoundtrip": ["ATTACH:custom:opak"],
                        "icsKomplex": True, "icsSerienUid": "serie",
                        "icsAusnahmen": ["2026-08-22"],
                        "icsZusatzDaten": ["2026-08-23"],
                        "icsZusatzTermine": [{"datum": "2026-08-23", "zeit": "15:00"}]}}
    gemischt, _anlegen, _aendern, _loeschen, _zaehler = m.sync_merge(
        lokal, fern, [], 0, m.TERMIN_FELDER)
    assert gemischt[0]["icsRoundtrip"] == ["ATTACH:custom:opak"]
    assert gemischt[0]["icsKomplex"] is True
    assert gemischt[0]["icsSerienUid"] == "serie"
    assert gemischt[0]["icsAusnahmen"] == ["2026-08-22"]
    assert gemischt[0]["icsZusatzDaten"] == ["2026-08-23"]
    assert gemischt[0]["icsZusatzTermine"] == [
        {"datum": "2026-08-23", "zeit": "15:00"}]
    assert all(feld not in m.TERMIN_FELDER for feld in (
        "icsRoundtrip", "icsKomplex", "icsSerienUid", "icsAusnahmen",
        "icsZusatzDaten", "icsZusatzTermine"))


def test_gleiche_serien_uid_vermischt_ausnahmen_nicht_zwischen_kalendern(tmp_path):
    pfad = tmp_path / "serien-kollision.sqlite"
    db = sqlite3.connect(pfad)
    db.execute("""CREATE TABLE cal_events (
        cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, flags INTEGER,
        event_start INTEGER, event_start_tz TEXT, event_end INTEGER,
        event_end_tz TEXT, recurrence_id INTEGER, recurrence_id_tz TEXT)""")
    db.execute("""CREATE TABLE cal_recurrence (
        cal_id TEXT, item_id TEXT, recurrence_id INTEGER,
        recurrence_id_tz TEXT, icalString TEXT)""")
    a_id = native(2026, 8, 10, 9)
    b_id = native(2026, 8, 11, 9)
    db.executemany("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
        ("a", "gleich", native(2026, 1, 1), "Serie A", 16 | 32,
         native(2026, 8, 3, 9), "UTC", native(2026, 8, 3, 10), "UTC", None, None),
        ("a", "gleich", native(2026, 1, 2), "Ausnahme A", 0,
         native(2026, 8, 10, 11), "UTC", native(2026, 8, 10, 12), "UTC", a_id, "UTC"),
        ("b", "gleich", native(2026, 1, 1), "Serie B", 16 | 32,
         native(2026, 8, 4, 9), "UTC", native(2026, 8, 4, 10), "UTC", None, None),
        ("b", "gleich", native(2026, 1, 2), "Ausnahme B", 0,
         native(2026, 8, 11, 11), "UTC", native(2026, 8, 11, 12), "UTC", b_id, "UTC")))
    db.executemany("INSERT INTO cal_recurrence VALUES (?,?,?,?,?)", (
        ("a", "gleich", None, None, "RRULE:FREQ=WEEKLY"),
        ("b", "gleich", None, None, "RRULE:FREQ=WEEKLY")))
    db.commit()
    db.close()

    ergebnis = m._tb_normalisierte_kalenderdaten(str(pfad))
    master_a = next(e for e in ergebnis["termine"] if e["titel"] == "Serie A")
    master_b = next(e for e in ergebnis["termine"] if e["titel"] == "Serie B")
    assert master_a["icsAusnahmen"] == ["2026-08-10"]
    assert master_b["icsAusnahmen"] == ["2026-08-11"]


def test_komplexe_jaehrliche_geburtstagsserie_bleibt_termin(tmp_path):
    pfad = tmp_path / "komplexer-geburtstag.sqlite"
    db = sqlite3.connect(pfad)
    db.execute("""CREATE TABLE cal_events (
        cal_id TEXT, id TEXT, title TEXT, flags INTEGER,
        event_start INTEGER, event_start_tz TEXT, event_end INTEGER,
        event_end_tz TEXT)""")
    db.execute("""CREATE TABLE cal_recurrence (
        cal_id TEXT, item_id TEXT, icalString TEXT)""")
    db.execute("""CREATE TABLE cal_properties (
        cal_id TEXT, item_id TEXT, key TEXT, value TEXT)""")
    db.execute("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?)", (
        "c", "geburtstag", "Mia", 8 | 16, native(1990, 8, 12), "floating",
        native(1990, 8, 13), "floating"))
    db.executemany("INSERT INTO cal_recurrence VALUES (?,?,?)", (
        ("c", "geburtstag", "RRULE:FREQ=YEARLY"),
        ("c", "geburtstag", "RDATE;VALUE=DATE:20260813")))
    db.execute("INSERT INTO cal_properties VALUES (?,?,?,?)", (
        "c", "geburtstag", "CATEGORIES", "Birthday"))
    db.commit()
    db.close()

    ergebnis = m._tb_normalisierte_kalenderdaten(str(pfad))
    assert ergebnis["jahrestage"] == []
    assert len(ergebnis["termine"]) == 1
    assert ergebnis["termine"][0]["icsKomplex"] is True


def test_allgemeiner_ics_import_bewahrt_zeitgebundenes_rdate():
    text = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:rdate-serie\r\nDTSTART:20260817T090000\r\n"
            "DTEND:20260817T103000\r\nSUMMARY:Zusatztermin\r\n"
            "RRULE:FREQ=WEEKLY\r\n"
            "RDATE:20260819T150000,20260819T180000,20260824T150000\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")
    termin = m.ics_lesen(text)["termine"][0]
    assert termin["wiederholung"]["art"] == "weekly"
    assert termin["icsZusatzDaten"] == ["2026-08-19", "2026-08-24"]
    assert termin["icsZusatzTermine"] == [
        {"datum": "2026-08-19", "zeit": "15:00"},
        {"datum": "2026-08-19", "zeit": "18:00"},
        {"datum": "2026-08-24", "zeit": "15:00"}]
    export = m.ics_schreiben_termine([termin])
    ereignis = export.split("BEGIN:VEVENT\r\n", 1)[1].split("END:VEVENT", 1)[0]
    assert ereignis.count("DTSTART") == 1
    assert "RDATE:20260819T150000,20260819T180000,20260824T150000\r\n" in export


def test_lokale_dubletten_vereinigen_fachlich_gleiche_eintraege_aus_quellen():
    termine = [{"uid": "gleiche-uid", "datum": "2026-08-17", "zeit": "09:00",
                "endZeit": "10:00", "titel": " Café ",
                "icsQuelleId": "thunderbird:a"},
               {"uid": "gleiche-uid", "datum": "2026-08-17", "zeit": "09:00",
                "endZeit": "10:00", "titel": "Cafe\u0301",
                "icsQuelleId": "thunderbird:b"}]
    jahrestage = [{"uid": "gleich", "icsSerienUid": "gleich", "name": "Mia",
                   "datum": "1990-08-12", "icsQuelleId": "thunderbird:a"},
                  {"uid": "gleich", "icsSerienUid": "gleich", "name": "Mia",
                   "datum": "1990-08-12", "icsQuelleId": "thunderbird:b"}]
    nutzlast = {"termine": termine, "jahrestage": jahrestage}
    m._lokale_kalender_dubletten_bereinigen(nutzlast)
    assert len(nutzlast["termine"]) == 1
    assert set(nutzlast["termine"][0]["syncQuellen"]) == {
        "thunderbird:a", "thunderbird:b"}
    assert len(nutzlast["jahrestage"]) == 1
    assert set(nutzlast["jahrestage"][0]["syncQuellen"]) == {
        "thunderbird:a", "thunderbird:b"}
