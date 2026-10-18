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
