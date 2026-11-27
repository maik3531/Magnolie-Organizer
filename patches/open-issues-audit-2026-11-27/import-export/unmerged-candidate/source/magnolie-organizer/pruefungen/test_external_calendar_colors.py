"""Actual ICS codecs, exact CSS3 values and durable colour baselines (#844)."""
import copy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from modul_laden import quellmodul_laden

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "contracts/calendar-external-colors.json").read_text())


@pytest.fixture(scope="module")
def codec():
    source_root = Path(os.environ.get("MAGNOLIE_CALENDAR_TEST_SOURCE_ROOT", ROOT))
    with patch.dict(sys.modules, {"gi": None}):
        yield quellmodul_laden("external_calendar_colors", source_root / "magnolie-organizer/bin/magnolie-organizer")


def wire(kind, properties, calendar="", uid="owned-color"):
    component = "VTODO" if kind == "aufgaben" else "VEVENT"
    parts = ["BEGIN:VCALENDAR", "VERSION:2.0"] + ([calendar] if calendar else [])
    parts += ["BEGIN:" + component, "UID:" + uid, "SUMMARY:Owned color",
              ("DUE" if kind == "aufgaben" else "DTSTART") + ";VALUE=DATE:20261205"]
    if kind == "jahrestage":
        parts += ["RRULE:FREQ=YEARLY", "X-MAGNOLIE-TYPE-ID:birthday"]
    return "\r\n".join(parts + properties + ["END:" + component, "END:VCALENDAR", ""])


def read(codec, text):
    return codec.import_rohdaten_lesen("ics", text.encode(), "owned.ics")


def export(codec, kind, values):
    return getattr(codec, "ics_schreiben_" + kind)(values)


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_shared_semantics(codec, case):
    expected = case["expected"]; kind = expected["kind"]
    parsed = read(codec, case["input"])
    text = export(codec, kind, parsed[kind])
    for result in (parsed, read(codec, text)):
        assert len(result[kind]) == 1
        assert sum(len(result[key]) for key in ("termine", "aufgaben", "jahrestage")) == 1
        item = result[kind][0]
        for key in ("typ", "datum"):
            if key in expected: assert item[key] == expected[key]
        if "accent" in expected: assert item.get("akzentFarbe", "") == expected["accent"]
        if "recurrence" in expected: assert item["wiederholung"]["art"] == expected["recurrence"]
        for line in expected.get("opaque", []): assert line in item["icsRoundtrip"]


@pytest.mark.parametrize("name,hex_value", VECTORS["css3_names"].items())
def test_all_css3_names_are_exact_and_case_insensitive(codec, name, hex_value):
    item = read(codec, wire("termine", ["COLOR:" + name.upper()]))["termine"][0]
    assert item["akzentFarbe"] == hex_value
    assert read(codec, export(codec, "termine", [item]))["termine"][0]["akzentFarbe"] == hex_value


@pytest.mark.parametrize("kind", ["termine", "aufgaben", "jahrestage"])
@pytest.mark.parametrize("value", ["#123456", ""])
def test_edit_or_clear_does_not_restore_the_original_color(codec, kind, value):
    item = read(codec, wire(kind, ["COLOR:turquoise"]))[kind][0]
    item["akzentFarbe"] = value
    text = export(codec, kind, [item])
    assert "COLOR:turquoise" not in text
    assert read(codec, text)[kind][0].get("akzentFarbe", "") == value
    assert not any(line.startswith("COLOR:#") for line in text.splitlines()), "Arbitrary hex is not an RFC7986 color name"


@pytest.mark.parametrize("kind", ["termine", "aufgaben", "jahrestage"])
def test_legacy_empty_accent_keeps_opaque_standard_color(codec, kind):
    item = read(codec, wire(kind, ["COLOR:turquoise"]))[kind][0]
    item.pop("icsAkzentFarbeBasis", None); item["akzentFarbe"] = ""
    stored = json.loads(json.dumps(item))
    assert "COLOR:turquoise" in export(codec, kind, [stored])


@pytest.mark.parametrize("kind", ["termine", "aufgaben", "jahrestage"])
def test_own_override_preserves_unchanged_parameterized_standard_color(codec, kind):
    original = "COLOR;X-SOURCE=owned:red"
    item = read(codec, wire(kind, [original, "X-MAGNOLIE-ACCENT-COLOR:#112233"]))[kind][0]
    text = export(codec, kind, [item])
    assert original in text
    assert read(codec, text)[kind][0]["akzentFarbe"] == "#112233"
    item["akzentFarbe"] = ""
    with pytest.raises(RuntimeError): export(codec, kind, [item])


def test_calendar_defaults_do_not_leak_between_objects_or_combined_export(codec):
    raw = wire("termine", [], "COLOR:red", "red") + wire("termine", [], "X-APPLE-CALENDAR-COLOR:#0000FF", "blue") + wire("termine", [], uid="plain")
    items = read(codec, raw)["termine"]
    expected = {"red": "#ff0000", "blue": "#0000ff", "plain": ""}
    assert {i["uid"]: i["akzentFarbe"] for i in items} == expected
    text = export(codec, "termine", items)
    assert "X-APPLE-CALENDAR-COLOR:" not in text
    assert {i["uid"]: i["akzentFarbe"] for i in read(codec, text)["termine"]} == expected


@pytest.mark.parametrize("kind", ["termine", "aufgaben", "jahrestage"])
def test_native_book_write_and_reopen_preserve_the_import_baseline(codec, kind, tmp_path, monkeypatch):
    data = read(codec, wire(kind, ["COLOR:turquoise"]))
    filename = tmp_path / "owned-book.json"
    monkeypatch.setattr(codec, "daten_datei", lambda: str(filename))
    codec.speichere_daten(data)
    codec._DATEN_ZWISCHENSPEICHER.update(stand=None, daten=None)
    reopened = codec.daten_lesen_gepuffert(str(filename))
    assert reopened[kind][0]["icsAkzentFarbeBasis"] == "#40e0d0"
    reopened[kind][0]["akzentFarbe"] = ""
    assert "COLOR:turquoise" not in export(codec, kind, reopened[kind])
