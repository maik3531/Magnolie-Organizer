"""Owned calendar/task category and accent-color interchange fixtures (#183)."""
from pathlib import Path
import io
import zipfile

import pytest
from modul_laden import quellmodul_laden


@pytest.fixture
def codec(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "gi", None)
    return quellmodul_laden("category_colors_probe", Path(__file__).resolve().parents[1] / "bin/magnolie-organizer")


def test_task_categories_and_accent_survive_native_ics_roundtrip(codec):
    raw = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VTODO", "UID:owned-task", "SUMMARY:Owned task", "DUE;VALUE=DATE:20261018",
        "CATEGORIES:Arzt,Provider", "X-MAGNOLIE-ACCENT-COLOR:#3366AA", "X-OWNED:preserved", "END:VTODO", "END:VCALENDAR", ""])
    imported = codec.ics_lesen(raw)
    task = imported["aufgaben"][0]
    assert task["kategorien"] == "Arzt,Provider" and task["akzentFarbe"] == "#3366aa"
    exported = codec.ics_schreiben_aufgaben([task])
    assert "X-OWNED:preserved" in exported and exported.count("X-MAGNOLIE-ACCENT-COLOR:") == 1
    restored = codec.ics_lesen(exported)["aufgaben"][0]
    assert restored["kategorien"] == "Arzt,Provider" and restored["akzentFarbe"] == "#3366aa"


def test_changed_or_cleared_task_colors_replace_owned_raw_properties(codec):
    task = {"uid": "owned-task", "titel": "Owned task", "faellig": "2026-10-18", "kategorien": "Urlaub", "akzentFarbe": "#ff9900",
        "icsRoundtrip": ["CATEGORIES:Arzt", "X-MAGNOLIE-ACCENT-COLOR:#3366aa", "X-OWNED:preserved"]}
    result = codec.ics_lesen(codec.ics_schreiben_aufgaben([task]))["aufgaben"][0]
    assert result["kategorien"] == "Urlaub" and result["akzentFarbe"] == "#ff9900"
    task.update(kategorien="", akzentFarbe="")
    exported = codec.ics_schreiben_aufgaben([task])
    assert "CATEGORIES:" not in exported and "X-MAGNOLIE-ACCENT-COLOR:" not in exported and "X-OWNED:preserved" in exported


def test_event_categories_and_accent_native_roundtrip_and_clear(codec):
    raw = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:owned-event", "SUMMARY:Owned event",
        "DTSTART;VALUE=DATE:20261018", "CATEGORIES:Arzt,Provider", "X-MAGNOLIE-ACCENT-COLOR:#3366AA",
        "X-OWNED:preserved", "END:VEVENT", "END:VCALENDAR", ""])
    event = codec.ics_lesen(raw)["termine"][0]
    assert event["kategorien"] == "Arzt,Provider" and event["akzentFarbe"] == "#3366aa"
    event.update(kategorien="Urlaub", akzentFarbe="#ff9900")
    exported = codec.ics_schreiben_termine([event])
    restored = codec.ics_lesen(exported)["termine"][0]
    assert restored["kategorien"] == "Urlaub" and restored["akzentFarbe"] == "#ff9900"
    assert exported.count("X-MAGNOLIE-ACCENT-COLOR:") == 1 and "X-OWNED:preserved" in exported
    event.update(kategorien="", akzentFarbe="")
    exported = codec.ics_schreiben_termine([event])
    assert "CATEGORIES:" not in exported and "X-MAGNOLIE-ACCENT-COLOR:" not in exported


@pytest.mark.parametrize("calendar_colour,component_colour,expected", [
    ("", "COLOR:turquoise", "#40e0d0"),
    ("", "COLOR:RED", "#ff0000"),
    ("COLOR:turquoise", "", "#40e0d0"),
    ("X-APPLE-CALENDAR-COLOR:#40E0D0", "", "#40e0d0"),
    ("X-APPLE-CALENDAR-COLOR:#40E0D0FF", "", "#40e0d0"),
    ("COLOR:turquoise", "COLOR:RED", "#ff0000"),
    ("COLOR:turquoise", "COLOR:RED\r\nX-MAGNOLIE-ACCENT-COLOR:#112233", "#112233"),
    ("", "COLOR:not-a-css-colour", ""),
])
@pytest.mark.parametrize("kind", ["VEVENT", "VTODO"])
def test_external_ics_colour_respects_component_and_calendar_scope(codec, kind, calendar_colour, component_colour, expected):
    date = "DTSTART" if kind == "VEVENT" else "DUE"
    section = "termine" if kind == "VEVENT" else "aufgaben"
    export = codec.ics_schreiben_termine if kind == "VEVENT" else codec.ics_schreiben_aufgaben
    raw = "\r\n".join(filter(None, (
        "BEGIN:VCALENDAR", "VERSION:2.0", calendar_colour, "BEGIN:" + kind, "UID:external-colour",
        "SUMMARY:External colour", date + ";VALUE=DATE:20261018", component_colour,
        "CATEGORIES:Provider", "X-OWNED:preserved", "END:" + kind, "END:VCALENDAR",
    )))
    item = codec.ics_lesen(raw)[section][0]
    assert item["akzentFarbe"] == expected
    assert item["kategorien"] == "Provider"
    saved = export([item])
    assert codec.ics_lesen(saved)[section][0]["akzentFarbe"] == expected
    if calendar_colour:
        assert calendar_colour in saved.split("BEGIN:" + kind, 1)[0]
    if component_colour == "COLOR:not-a-css-colour":
        assert component_colour in export([item])
    item["akzentFarbe"] = "#123456"
    assert codec.ics_lesen(export([item]))[section][0]["akzentFarbe"] == "#123456"
    item["akzentFarbe"] = ""
    cleared = export([item])
    assert "X-OWNED:preserved" in cleared
    assert codec.ics_lesen(cleared)[section][0]["akzentFarbe"] == ""


def test_calendar_colours_do_not_bleed_between_sources_on_export(codec):
    def calendar(uid, colour):
        return "\r\n".join(("BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:" + uid,
            "SUMMARY:" + uid, "DTSTART;VALUE=DATE:20261018", "END:VEVENT",
            *([colour] if colour else []), "END:VCALENDAR", ""))
    raw = calendar("first", "COLOR:DarkGrey") + calendar("second", "")
    imported = codec.ics_lesen(raw)["termine"]
    assert [(item["uid"], item["akzentFarbe"]) for item in imported] == [("first", "#a9a9a9"), ("second", "")]
    saved = codec.ics_schreiben_termine(imported)
    assert "COLOR:DarkGrey" not in saved
    assert [item["akzentFarbe"] for item in codec.ics_lesen(saved)["termine"]] == ["#a9a9a9", ""]
    legacy = dict(imported[1], icsRoundtrip=["COLOR:turquoise"])
    legacy.pop("icsCalendarColor")
    assert "COLOR:turquoise" in codec.ics_schreiben_termine([legacy])


def test_planner_accepts_task_accent_and_uses_contrasting_text(codec):
    columns = [str(index) for index in range(8)]
    rows = [[""] * 8]
    cells = [[{"datum": "18", "eintraege": [{"text": "Owned task", "art": "aufgabe", "farbe": "#112233", "akzent": True}]}] +
        [{"datum": "", "eintraege": []} for _ in range(7)]]
    checked = codec.planer_ods_inhalte_pruefen(cells, rows, columns)
    assert checked[0][0]["eintraege"][0]["akzent"] is True
    assert codec._kalender_akzent_textfarbe("#112233") == "#ffffff"
    assert codec._kalender_akzent_textfarbe("#ff0000") == "#000000"
    for width in (8, 12):
        columns = [str(index) for index in range(width)]
        contents = [cells[0] + [{"datum": "", "eintraege": []} for _ in range(width - 8)]]
        result = codec.adressen_ods_bytes("Owned planner", columns, [[""] * width], logo_pfad="", kompakt=True, kalenderinhalte=contents)
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            content = archive.read("content.xml").decode()
        assert 'fo:background-color="#112233"' in content and 'fo:color="#ffffff"' in content
        assert "Owned task" in content and "calendarEntry0" in content
