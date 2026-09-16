"""Native regressions for the September 2026 import/scheduler review."""

import importlib.machinery
import importlib.util
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

PROGRAM = Path(__file__).parents[1] / "bin" / "magnolie-organizer"
loader = importlib.machinery.SourceFileLoader("native_import_regressions", str(PROGRAM))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


@pytest.fixture(autouse=True)
def regional(monkeypatch):
    monkeypatch.setitem(m._REGIONAL, "timeZone", "Europe/Berlin")


def test_anonymous_tasks_do_not_resolve_an_empty_parent():
    tasks = [{"titel": "First"}, {"titel": "Second", "icsElternUid": "external-parent"}]
    with mock.patch.object(m, "_aufgaben_externe_uid", wraps=m._aufgaben_externe_uid) as identity:
        exported = m._aufgaben_export_daten(tasks)
    assert identity.call_count == len(tasks)
    assert [a["_icsExportParent"] for a in exported] == ["", "external-parent"]
    assert tasks == [{"titel": "First"}, {"titel": "Second", "icsElternUid": "external-parent"}]


def test_valid_environment_timezone_needs_no_system_file_reads(monkeypatch):
    monkeypatch.setitem(m._REGIONAL, "timeZone", "system")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    with mock.patch("builtins.open", side_effect=AssertionError("unnecessary timezone read")), \
            mock.patch.object(m.os.path, "realpath", side_effect=AssertionError("unnecessary symlink walk")):
        assert m._zeitzonenname() == "Europe/Berlin"
        monkeypatch.setenv("TZ", "America/New_York")
        assert m._zeitzonenname() == "America/New_York"


@pytest.mark.parametrize("value,form", [
    ("2024-02-29", "%Y-%m-%d"), ("2023-02-29", "%Y-%m-%d"),
    ("2024-2-9", "%Y-%m-%d"), ("20240229", "%Y%m%d"),
    ("20240229T235959", "%Y%m%dT%H%M%S"), ("20240229T2359", "%Y%m%dT%H%M"),
    ("20240229T2359", "%Y%m%dT%H%M%S"), ("20240229T235959Z", "%Y%m%dT%H%M%SZ"),
    ("2024-02-29T23:59:59", "%Y-%m-%dT%H:%M:%S"),
    ("2024-02-29T23:59", "%Y-%m-%dT%H:%M"),
    ("2024-02-29 23:59", "%Y-%m-%d %H:%M"),
    ("23:59", "%H:%M"), ("24:00", "%H:%M"), ("9:05", "%H:%M"),
    ("23:59:59", "%H:%M:%S"), ("23:59:60", "%H:%M:%S"),
    ("2024-02-29\n", "%Y-%m-%d"),
])
def test_numeric_calendar_parser_preserves_strptime_semantics(value, form):
    try:
        expected = datetime.strptime(value, form)
    except ValueError:
        with pytest.raises(ValueError):
            m._kalender_strptime(value, form)
    else:
        assert m._kalender_strptime(value, form) == expected


def test_scheduler_timezone_snapshot_resets_after_failure(monkeypatch):
    from zoneinfo import ZoneInfo
    monkeypatch.setitem(m._REGIONAL, "timeZone", "Europe/Berlin")

    @m._mit_lauf_zeitzone
    def scan():
        monkeypatch.setitem(m._REGIONAL, "timeZone", "America/New_York")
        assert m._organizer_zeitzone() == ZoneInfo("Europe/Berlin")
        raise ValueError("test failure")

    with pytest.raises(ValueError, match="test failure"):
        scan()
    assert m._organizer_zeitzone() == ZoneInfo("America/New_York")
    assert m._LAUF_ZEITZONE.get() is None


def test_vcard_header_cache_does_not_share_mutable_parameters():
    @m._mit_vcard_kopf_cache
    def parse():
        first = m._prop_zerlegen("TEL;TYPE=HOME:123456")
        first[1]["TYPE"] = "changed"
        assert m._prop_zerlegen("TEL;TYPE=HOME:654321") == ("TEL", {"TYPE": "HOME"}, "654321")
        assert m._prop_zerlegen('TEL;X-LABEL="a:b;c":123456') == (
            "TEL", {"X-LABEL": "a:b;c"}, "123456")
    parse()
    assert m._VCARD_KOPF_CACHE.get() is None


def test_bulk_escape_cache_is_scoped_and_rejects_invalid_text():
    contacts = [{"vorname": "Repeated", "nachname": "Name", "notiz": "a;b\nc"},
                {"vorname": "Repeated", "nachname": "Name", "notiz": "a;b\nc"},
                {"vorname": "bad\x00name"}]
    blocks, skipped = m._vcf_bloecke(contacts)
    assert len(blocks) == 2 and skipped == 1
    assert all("NOTE:a\\;b\\nc" in block for block in blocks)
    assert m._VCARD_ESCAPE_CACHE.get() is None
    for invalid in ("x\x00", "x\x7f", "x\ud800"):
        with pytest.raises(ValueError):
            m._vcard_escape(invalid)


def test_omitting_unconsulted_legacy_keys_keeps_reminder_times_and_ids():
    appointment = {"datum": "2026-09-10", "zeit": "09:00", "individuelleErinnerungTage": 1}
    start = datetime(2026, 9, 10, 9)
    old = m._termin_meldungen(appointment, "same", start, 15, absolut_rechnen=True)
    new = m._termin_meldungen(appointment, "same", start, 15, absolut_rechnen=True, legacy=False)
    assert [item[:4] for item in old] == [item[:4] for item in new]
    assert all(not item[4] for item in new)


@pytest.mark.parametrize("text", ["", "A" * 75, "A" * 76, "abc" * 100,
    "\u00e4\u20ac\U0001f338" * 80, "a" * 74 + "\U0001f338" + "b" * 150])
def test_utf8_folding_matches_character_reference(text):
    lines, line, width, limit = [], "", 0, 75
    for char in text:
        size = len(char.encode("utf-8"))
        if line and width + size > limit:
            lines.append(line)
            line, width, limit = "", 0, 74
        line += char
        width += size
    lines.append(line)
    folded = m._falte(text)
    assert folded == "\r\n ".join(lines)
    assert folded.replace("\r\n ", "") == text
    assert all(len(line.encode("utf-8")) <= 75 for line in folded.split("\r\n"))


def event(rule="", start="20260907T090000", extra="", uid="series"):
    return m.ics_lesen("BEGIN:VEVENT\r\nUID:" + uid + "\r\nSUMMARY:Test\r\n"
        "DTSTART:" + start + "\r\n" + ("RRULE:" + rule + "\r\n" if rule else "") +
        extra + "END:VEVENT\r\n")["termine"][0]


@pytest.mark.parametrize("name,first,last", [
    ("N:;Anna Maria;;;\r\nFN:Anna Maria", "Anna Maria", ""),
    ("N:Van Dame;;;;\r\nFN:Van Dame", "", "Van Dame"),
    ("FN:Van Dame", "", ""),
    ("N:Smith,Jones;Anna,Maria;Louise;Dr.;Jr.\r\nFN:Doctor A", "Anna Maria", "Smith Jones"),
    (r"N:Smith\,Jones;Anna\,Maria;Louise;Dr.;Jr." + "\r\nFN:Doctor B", "Anna,Maria", "Smith,Jones"),
])
def test_names_are_not_guessed_and_structure_roundtrips(name, first, last):
    text = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:person\r\n" + name + "\r\nEND:VCARD\r\n"
    contact = m.vcf_lesen(text)["kontakte"][0]
    assert (contact["vorname"], contact["nachname"]) == (first, last)
    exported = m.vcard_text(contact)
    if "N:" in name:
        assert name.split("\r\n")[0] + "\r\n" in exported
    assert "FN:" + name.split("FN:")[-1] + "\r\n" in exported
    ldif = m.ldif_schreiben([contact])
    if not last:
        assert "\r\nsn:" not in ldif and "objectClass: person\r\n" not in ldif
    reread = m.ldif_lesen(ldif)["kontakte"][0]
    assert (reread["vorname"], reread["nachname"], reread["anzeigename"]) == (
        first, last, contact["anzeigename"])
    if "N:" in name:
        assert name.split("\r\n")[0] + "\r\n" in m.vcard_text(reread)


@pytest.mark.parametrize("value,params,expected", [
    ("--0229", "", "--02-29"), ("--06-07", "", "--06-07"),
    ("1604-02-29", ";X-APPLE-OMIT-YEAR=1604", "--02-29"),
    ("16040229", ";X-APPLE-OMIT-YEAR=1604", "--02-29"),
    ("1604-02-29", "", "1604-02-29"),
])
def test_partial_contact_dates_survive_vcard_and_ldif(value, params, expected):
    contact = m.vcf_lesen("BEGIN:VCARD\r\nFN:Date\r\nBDAY" + params + ":" + value +
        "\r\nANNIVERSARY" + params + ":" + value + "\r\nEND:VCARD\r\n")["kontakte"][0]
    assert contact["geburtstag"] == contact["jubilaeum"] == expected
    assert contact["geburtstagJahrUnbekannt"] == expected.startswith("--")
    for write, read in ((m.vcf_schreiben, m.vcf_lesen), (m.ldif_schreiben, m.ldif_lesen)):
        result = read(write([contact]))["kontakte"][0]
        assert result["geburtstag"] == result["jubilaeum"] == expected
    # Canonical fields remain authoritative even without import-only metadata.
    contact["vcardRoundtrip"] = ["ANNIVERSARY:1900-01-01"]
    output = m.vcard_text(contact)
    wire_date = "--" + expected[2:].replace("-", "") if expected.startswith("--") else expected.replace("-", "")
    assert "VERSION:4.0\r\n" in output
    assert output.count("ANNIVERSARY:") == 1 and "ANNIVERSARY:" + wire_date + "\r\n" in output


def test_thunderbird_escaped_photo_uri_retains_image_bytes():
    photo = "data:image/png;base64,iVBORw0KGgo="
    text = "BEGIN:VCARD\r\nVERSION:4.0\r\nN:Van Dame;;;;\r\nFN:Club\r\nPHOTO:" + photo.replace(",", "\\,") + "\r\nEND:VCARD\r\n"
    contact = m.vcf_lesen(text)["kontakte"][0]
    assert contact["foto"] == photo
    for write, read in ((m.vcf_schreiben, m.vcf_lesen), (m.ldif_schreiben, m.ldif_lesen)):
        assert read(write([contact]))["kontakte"][0]["foto"] == photo


def test_modern_thunderbird_vcard_is_base_not_legacy_properties(tmp_path):
    book = tmp_path / "abook.sqlite"
    text = ("BEGIN:VCARD\r\nVERSION:4.0\r\nN:Van Dame;;Middle;Dr.;Jr.\r\nFN:Doctor Van Dame\r\n"
        "ORG:Modern Org\r\nBDAY;X-APPLE-OMIT-YEAR=1604:1604-02-29\r\nANNIVERSARY:--06-07\r\n"
        "TITLE:Chief\r\nURL:https://example.org\r\nADR;TYPE=HOME:;;Road;Town;Region;12345;Country\r\nEND:VCARD\r\n")
    with sqlite3.connect(book) as db:
        db.execute("CREATE TABLE properties(card TEXT, name TEXT, value TEXT)")
        db.executemany("INSERT INTO properties VALUES(?,?,?)", [
            ("card", "_vCard", text), ("card", "Company", "Stale Org"),
            ("card", "FirstName", "Wrong Guess"), ("card", "Notes", "Supplement")])
    contact = m.vcf_lesen(m._tb_karten_vcards(str(book))[0])["kontakte"][0]
    assert (contact["nachname"], contact["vorname"], contact["firma"]) == ("Van Dame", "", "Modern Org")
    assert contact["notiz"] == "Supplement"
    output = m.vcard_text(contact)
    for field in ("TITLE:Chief", "URL:https://example.org", "N:Van Dame;;Middle;Dr.;Jr.",
                  "FN:Doctor Van Dame", ";Town;Region;12345;Country", "VERSION:4.0", "BDAY:--0229", "ANNIVERSARY:--0607"):
        assert field in output


def test_vtodo_independent_start_due_and_scheduler():
    task = m.ics_lesen("BEGIN:VTODO\r\nUID:task\r\nSUMMARY:Task\r\n"
        "DTSTART:20260901T090000\r\nDUE:20260907T170000\r\n"
        "X-MAGNOLIE-ERINNERUNG-AM-TAG:1\r\nEND:VTODO\r\n")["aufgaben"][0]
    for candidate in (task, m.ics_lesen(m.ics_schreiben_aufgaben([task]))["aufgaben"][0]):
        assert (candidate["startDatum"], candidate["startZeit"], candidate["faellig"], candidate["faelligZeit"]) == (
            "2026-09-01", "09:00", "2026-09-07", "17:00")
        assert not m.faellige_aufgaben({"aufgaben": [candidate]}, datetime(2026, 9, 7, 8))["faellig"]
        assert m.faellige_aufgaben({"aufgaben": [candidate]}, datetime(2026, 9, 7, 17))["faellig"]
    only_start = dict(task, faellig="", faelligZeit="", startZeit="")
    assert "DTSTART;VALUE=DATE:20260901" in m.ics_schreiben_aufgaben([only_start])
    assert "DUE" not in m.ics_schreiben_aufgaben([only_start])


@pytest.mark.parametrize("start,duration,end_date,end_time", [
    ("20260907", "P3D", "2026-09-09", ""),
    ("20260907", "P2W", "2026-09-20", ""),
    ("20260907T230000", "PT3H", "2026-09-08", "02:00"),
    ("20260907T090000", "P1DT2H", "2026-09-08", "11:00"),
])
def test_duration_projects_actual_span_and_exports_exclusive_end(start, duration, end_date, end_time):
    item = event(start=start, extra="DURATION:" + duration + "\r\n")
    assert (item["endDatum"], item["endZeit"]) == (end_date, end_time)
    output = m.ics_schreiben_termine([item])
    assert "DURATION:" + duration in output and "DTEND" not in output
    result = m.ics_lesen(output)["termine"][0]
    assert (result["endDatum"], result["endZeit"]) == (end_date, end_time)
    conflict = event(start=start, extra="DURATION:P9D\r\nDTEND;VALUE=DATE:20260910\r\n")
    output = m.ics_schreiben_termine([conflict])
    assert "DTEND" in output and "DURATION" not in output


def test_timed_rdates_keep_multiple_times_duration_and_reminders():
    item = event(extra="DTEND:20260907T100000\r\nRDATE:20260908T150000,20260908T180000\r\n")
    items = m.termine_mit_wiederholungen({"termine": [item]}, datetime(2026, 9, 8), 0, 1)
    assert [(entry["zeit"], entry["endZeit"]) for entry in items] == [("15:00", "16:00"), ("18:00", "19:00")]
    assert len({entry["id"] for entry in items}) == 2
    assert m.naechster_weckzeitpunkt({"termine": [item]}, datetime(2026, 9, 8, 10)) == datetime(2026, 9, 8, 14, 45)
    assert m.faellige_erinnerungen({"termine": [item]}, datetime(2026, 9, 8, 14, 45), {})["faellig"][0]["zeit"] == "15:00"


@pytest.mark.parametrize("rule,start,lower,upper,expected", [
    ("FREQ=DAILY;INTERVAL=3;COUNT=4", "20260901T090000", "2026-09-01", "2026-09-15", ["01", "04", "07", "10"]),
    ("FREQ=WEEKLY;INTERVAL=2;COUNT=5;BYDAY=MO,WE,FR", "20260831T090000", "2026-09-01", "2026-09-30", ["02", "04", "14", "16"]),
    ("FREQ=MONTHLY;COUNT=4", "20260131T090000", "2026-02-01", "2026-07-31", ["03-31", "05-31", "07-31"]),
    ("FREQ=MONTHLY;INTERVAL=2;COUNT=4;BYDAY=-1MO", "20260126T090000", "2026-02-01", "2026-08-31", ["03-30", "05-25", "07-27"]),
    ("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=3", "20260130T090000", "2026-02-01", "2026-04-30", ["02-27", "03-31"]),
    ("FREQ=YEARLY;COUNT=3", "20200229T090000", "2021-01-01", "2030-12-31", ["2024-02-29", "2028-02-29"]),
    ("FREQ=YEARLY;INTERVAL=2;COUNT=3", "20210607T090000", "2022-01-01", "2027-12-31", ["2023-06-07", "2025-06-07"]),
])
def test_rfc_recurrence_window(rule, start, lower, upper, expected):
    item = event(rule, start, "DURATION:PT1H\r\n")
    values = m._ics_vorkommen(item, datetime.fromisoformat(lower), datetime.fromisoformat(upper).replace(hour=23))
    assert values is not None
    width = len(expected[0])
    assert [value["datum"][-width:] for value in values] == expected


def test_ancient_recurrence_seeks_without_history_scan():
    for start in ("19980105T090000", "20210104T090000"):
        item = event("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE", start, "DURATION:PT1H\r\n")
        original = m.IcsRule._dates
        with mock.patch.object(m.IcsRule, "_dates", autospec=True, side_effect=original) as dates:
            assert m._ics_vorkommen(item, datetime(2026, 9, 1), datetime(2026, 9, 30))
            assert dates.call_count <= 4


def test_overrides_exclusions_and_source_isolation():
    master = event("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO", "19980105T090000", "DURATION:PT1H\r\n")
    override = event(start="20260907T110000", extra="RECURRENCE-ID:20260907T090000\r\nDURATION:PT1H\r\n")
    other = dict(master, icsQuelleId="other", uid="series", id="other")
    data = {"termine": [master, override, other]}
    values = m.termine_mit_wiederholungen(data, datetime(2026, 9, 7), 0, 1)
    assert sorted(value["zeit"] for value in values) == ["09:00", "11:00"]
    assert not any(line.startswith("EXDATE") for line in master["icsRoundtrip"])
    item = event(extra="RDATE:20260908T150000,20260908T180000\r\nEXDATE:20260908T150000\r\n")
    assert [v["zeit"] for v in m._ics_vorkommen(item, datetime(2026, 9, 8), datetime(2026, 9, 9))] == ["18:00"]


def test_locked_reminder_projection_retains_only_scheduling_metadata():
    item = event("FREQ=DAILY;COUNT=3", extra="ATTENDEE:mailto:private@example.org\r\n")
    data = {"termine": [item], "einstellungen": {"sicherheit": {"erinnernTrotzKennwort": True}}}
    projected = m.erinnerungsdaten_auswaehlen(data)
    assert not any("ATTENDEE" in line for line in projected["termine"][0]["icsRoundtrip"])
    assert len(m.termine_mit_wiederholungen(projected, datetime(2026, 9, 7), 0, 3)) == 3


@pytest.mark.parametrize("locale,language", [("zh_CN.UTF-8", "zh_CN"), ("zh-CN.utf8@desktop", "zh_CN"), ("de_DE.UTF-8@euro", "de"), ("fr_FR@euro", "fr")])
def test_posix_locale_suffixes(locale, language):
    assert m.normalisiere_sprache(locale) == language


@pytest.mark.parametrize("value,expected", [(0, 0), ("0", 0), (None, 15), ("bad", 15), (15, 15)])
def test_zero_minute_lead_is_valid(value, expected):
    assert m._erinnerung_vorlauf(value) == expected


def test_calendar_source_is_profile_namespaced(tmp_path):
    assert m._tb_quelle("same", profil=str(tmp_path / "profile1"))[1] != m._tb_quelle("same", profil=str(tmp_path / "profile2"))[1]


def test_ldif_fn_only_ids_do_not_depend_on_export_order():
    contacts = [{"anzeigename": "Alice"}, {"anzeigename": "Bob"}]
    def identities(items):
        return {item["anzeigename"]: item["uid"] for item in m.ldif_lesen(m.ldif_schreiben(items))["kontakte"]}
    assert identities(contacts) == identities(list(reversed(contacts)))
    assert len(set(identities(contacts).values())) == 2
    contact = m.ldif_lesen("dn: cn=Test\ncn: Test\nmozillaBirthYear: 0\n"
                         "mozillaBirthMonth: 2\nmozillaBirthDay: 29\n\n")["kontakte"][0]
    assert contact["geburtstag"] == "--02-29" and contact["geburtstagJahrUnbekannt"]


def test_utc_recurrence_keeps_source_wall_time_across_dst():
    item = event("FREQ=WEEKLY;COUNT=3", "20261019T090000Z", "DURATION:PT1H\r\n")
    values = m._ics_vorkommen(item, datetime(2026, 10, 19), datetime(2026, 11, 3))
    assert [(entry["datum"], entry["zeit"]) for entry in values] == [
        ("2026-10-19", "11:00"), ("2026-10-26", "10:00"), ("2026-11-02", "10:00")]


def test_duration_uses_nominal_days_and_exact_hours_at_dst():
    from zoneinfo import ZoneInfo
    start = datetime(2026, 3, 28, 12, tzinfo=ZoneInfo("Europe/Berlin"))
    assert m.ics_duration_end(start, "P1D").hour == 12
    assert m.ics_duration_end(start, "PT24H").hour == 13


def test_cancelled_override_suppresses_only_its_original_occurrence():
    master = event("FREQ=DAILY;COUNT=3", extra="DURATION:PT1H\r\n")
    cancelled = event(start="20260908T090000", extra="RECURRENCE-ID:20260908T090000\r\nSTATUS:CANCELLED\r\n")
    values = m.termine_mit_wiederholungen({"termine": [master, cancelled]}, datetime(2026, 9, 7), 0, 3)
    assert [value["datum"] for value in values] == ["2026-09-07", "2026-09-09"]


def test_thunderbird_task_start_due_flags_and_midnight(tmp_path):
    book = tmp_path / "local.sqlite"
    with sqlite3.connect(book) as db:
        db.execute("CREATE TABLE cal_todos(cal_id TEXT, id TEXT, title TEXT, flags INTEGER, "
                   "todo_entry INTEGER, todo_entry_tz TEXT, todo_due INTEGER, todo_due_tz TEXT)")
        for flags in (0, 8, 16):
            db.execute("INSERT INTO cal_todos VALUES(?,?,?,?,?,?,?,?)", (
                "calendar", str(flags), "Task", flags,
                int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp() * 1000000), "floating",
                int(datetime(2026, 9, 7, 17, tzinfo=timezone.utc).timestamp() * 1000000), "floating"))
    tasks = {task["uid"]: task for task in m._tb_normalisierte_kalenderdaten(str(book))["aufgaben"]}
    assert all(task["startDatum"] == "2026-09-01" and task["faellig"] == "2026-09-07" for task in tasks.values())
    assert tasks["0"]["startZeit"] == "00:00" and tasks["0"]["faelligZeit"] == "17:00"
    assert tasks["8"]["startZeit"] == tasks["8"]["faelligZeit"] == ""
    assert tasks["16"]["faelligZeit"] == "17:00"  # HAS_RECURRENCE is not EVENT_ALLDAY.


def test_count_is_window_invariant_after_nonexistent_dst_time():
    item = event("FREQ=DAILY;COUNT=4", "20260327T023000", "DURATION:PT1H\r\n")
    values = m._ics_vorkommen(item, datetime(2026, 3, 30), datetime(2026, 4, 2))
    assert [entry["datum"] for entry in values] == ["2026-03-30", "2026-03-31"]
