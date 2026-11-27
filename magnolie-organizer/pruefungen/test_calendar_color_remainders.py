"""Colour remainders after #844: annual entries, native storage and raw parameters."""
import json
import os
from pathlib import Path

import pytest
from modul_laden import quellmodul_laden


ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "contracts/calendar-color-remainders.json").read_text())


@pytest.fixture
def codec(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "gi", None)
    source = Path(os.environ.get("MAGNOLIE_TEST_SOURCE_ROOT", ROOT))
    return quellmodul_laden("calendar_colour_remainders", source / "magnolie-organizer/bin/magnolie-organizer")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_colours_survive_native_book_reopen_and_export(codec, monkeypatch, tmp_path, case):
    section = case["section"]
    book = codec.ics_lesen(case["input"])
    path = tmp_path / "book.json"
    monkeypatch.setattr(codec, "daten_datei", lambda: str(path))
    codec.speichere_daten(book)
    codec._DATEN_ZWISCHENSPEICHER = {"stand": None, "daten": None}
    reopened = codec.daten_lesen_gepuffert(str(path))
    item = reopened[section][0]
    assert item.get("akzentFarbe", "") == case["expected_accent"]
    if section == "jahrestage":
        assert item["datum"] == case["expected_date"] and item["typ"] == case["expected_type"]
        assert not reopened["termine"]
    write = getattr(codec, "ics_schreiben_" + section)
    text = write([item])
    assert "X-OWNED:keep" in text
    if case["preserve_line"]:
        assert case["preserve_line"] in text.splitlines()
    again = codec.ics_lesen(text)
    assert again[section][0].get("akzentFarbe", "") == case["expected_accent"]
    if section == "jahrestage":
        assert again[section][0]["datum"] == case["expected_date"]
        assert again[section][0]["typ"] == case["expected_type"]
        assert not again["termine"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_actual_colour_edit_and_clear_do_not_restore_old_colour(codec, case):
    section = case["section"]
    item = codec.ics_lesen(case["input"])[section][0]
    write = getattr(codec, "ics_schreiben_" + section)
    for accent in ("#123456", ""):
        item["akzentFarbe"] = accent
        text = write([item])
        assert codec.ics_lesen(text)[section][0].get("akzentFarbe", "") == accent
        assert "X-OWNED:keep" in text
        if case["preserve_line"].startswith("COLOR;X-SOURCE"):
            assert case["preserve_line"] not in text.splitlines()
        if case["preserve_line"] == "COLOR:future-colour":
            assert case["preserve_line"] in text.splitlines()


def test_mixed_anniversary_calendars_do_not_share_a_colour(codec):
    coloured = next(case for case in CASES if case["id"] == "birthday-calendar")
    other = coloured["input"].replace("COLOR:turquoise\r\n", "").replace("birthday-calendar", "uncoloured")
    items = codec.ics_lesen(coloured["input"] + other)["jahrestage"]
    text = codec.ics_schreiben_jahrestage(items)
    assert "COLOR:turquoise" not in text.split("BEGIN:VEVENT", 1)[0]
    assert [item.get("akzentFarbe", "") for item in codec.ics_lesen(text)["jahrestage"]] == ["#40e0d0", ""]


def test_incomplete_calendar_uses_localized_validation_error(codec, monkeypatch):
    monkeypatch.setattr(codec, "_", lambda message: f"translated: {message}")
    with pytest.raises(ValueError, match="translated: The selected iCalendar file is incomplete"):
        codec.ics_lesen("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:incomplete\r\n")
