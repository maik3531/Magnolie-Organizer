"""Native waste-calendar file handling feeds preview, never the appointment store."""
from pathlib import Path
import hashlib
import json
import pytest
from test_startup_read_failure import native, Host


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = next(p for p in (ROOT.parent / "contracts/waste-calendar-v1.json", ROOT / "contracts/waste-calendar-v1.json") if p.is_file())
ICAL = json.loads(FIXTURE.read_text(encoding="utf-8"))["ics"].encode("utf-8")


def test_calendar_keeps_dates_uid_locations_and_original_time_notes(native):
    parsed = native.muell_import_lesen(ICAL, "waste.ics")
    assert parsed["muellFormat"] == "ics" and len(parsed["termine"]) == 7
    assert parsed["muellName"] == "Example waste calendar"
    assert parsed["muellQuelle"] == "waste:ics:" + hashlib.sha256(b"magnolie-waste-fixture").hexdigest()
    assert native.muell_import_lesen(ICAL, "waste (2).ics")["muellQuelle"] == parsed["muellQuelle"]
    first = parsed["termine"][0]
    assert first["datum"] == "2026-01-12" and first.get("endDatum", "") in ("", "2026-01-12")
    hazardous = [t for t in parsed["termine"] if t["titel"] == "Schadstoffe"]
    assert len(hazardous) == 2 and all(t["zeit"] == "" for t in hazardous)
    assert {t["ort"] for t in hazardous} == {"First collection point", "Second collection point"}
    assert "14:30" in hazardous[0]["notiz"]
    assert parsed["termine"][-1]["datum"] == "2026-12-31"


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_csv_supports_delimiters_bom_quotes_and_multiline_notes(native, delimiter):
    raw = delimiter.join(["Datum", "Abfallart", "Beschreibung"]) + "\r\n" + delimiter.join(
        ['"12.01.2026"', '"Biotonne"', '"First line\nSecond, line; with ""quotes"""']) + "\r\n"
    parsed = native.muell_import_lesen(("\ufeff" + raw).encode(), "waste.csv")
    assert parsed["muellFormat"] == "csv"
    assert parsed["zeilen"][1] == ["12.01.2026", "Biotonne", 'First line\nSecond, line; with "quotes"']


@pytest.mark.parametrize("raw", [b"", b"\x00", b'Datum;Abfallart\n"12.01.2026;Biotonne', b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:invalid\nEND:VEVENT\nEND:VCALENDAR"])
def test_malformed_files_are_rejected_without_partial_preview(native, raw):
    with pytest.raises((ValueError, native.csv.Error)):
        native.muell_import_lesen(raw, "bad.csv")


def test_native_file_dialog_route_echoes_preview_token_on_success_and_cancel(native, monkeypatch, tmp_path):
    path = tmp_path / "waste.ics"
    path.write_bytes(ICAL)
    host = Host(native)
    monkeypatch.setattr(host, "_datei_oeffnen", lambda *_: str(path))
    host.bei_import({"art": "muell", "muellToken": "owned-request"})
    callback, payload = host.responses[-1]
    assert callback == "App.importErgebnis" and payload["muellToken"] == "owned-request"
    assert len(payload["termine"]) == 7
    monkeypatch.setattr(host, "_datei_oeffnen", lambda *_: None)
    host.bei_import({"art": "muell", "muellToken": "cancel-request"})
    assert host.responses[-1][1] == {"art": "muell", "abgebrochen": True, "muellToken": "cancel-request"}
