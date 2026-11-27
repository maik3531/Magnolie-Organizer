#!/usr/bin/env python3
"""Two concrete #845 review boundaries, using actual product codecs only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument("--checkout", type=Path, required=True)
p.add_argument("--fixtures", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
args = p.parse_args()
sys.path.insert(0, str(args.checkout / "magnolie-organizer/pruefungen"))
sys.modules["gi"] = None
from modul_laden import quellmodul_laden

source = args.checkout / "magnolie-organizer/bin/magnolie-organizer"
m = quellmodul_laden("independent_845_boundaries", source)
base = next(case["ics"] for case in json.loads(args.fixtures.read_text())["cases"] if case["id"] == "known")
results = []

exception = "\r\n".join([
    "BEGIN:VEVENT", "UID:synthetic-known", "RECURRENCE-ID;VALUE=DATE:20261203",
    "DTSTART;VALUE=DATE:20261204", "DTEND;VALUE=DATE:20261205",
    "SUMMARY:Moved birthday exception", "END:VEVENT", "",
])
raw = base.replace("END:VCALENDAR\r\n", exception + "END:VCALENDAR\r\n")
case = {"id": "separate-recurrence-exception", "input": raw}
try:
    parsed = m.ics_lesen(raw)
    case["payload"] = parsed
    assert not parsed["jahrestage"], "Complex master was promoted despite its separate exception"
    exported = m.ics_schreiben_termine(parsed["termine"])
    case["exported"] = exported
    assert "RECURRENCE-ID;VALUE=DATE:20261203" in m._entfalte_zeilen(exported)
    again = m.ics_lesen(exported)
    assert not again["jahrestage"]
    assert any(item["datum"] == "2026-12-04" for item in again["termine"])
    case["passed"] = True
except Exception as error:
    case["passed"] = False
    case["error"] = str(error)
results.append(case)

case = {"id": "explicit-type-edit-removes-stale-bday", "input": base}
try:
    item = m.ics_lesen(base)["jahrestage"][0]
    item["typ"] = "wedding-anniversary"
    exported = m.ics_schreiben_jahrestage([item])
    case["exported"] = exported
    lines = m._entfalte_zeilen(exported)
    assert not any(line.startswith("X-NEXTCLOUD-BC-") for line in lines), "Edited wedding still exported old Nextcloud birthday metadata"
    assert "X-SYNTHETIC-PRESERVE:keep" in lines
    assert "COLOR:red" in lines and "TRIGGER;VALUE=DURATION:PT9H" in lines
    again = m.ics_lesen(exported)["jahrestage"][0]
    assert again["typ"] == "wedding-anniversary" and again["uid"] == item["uid"]
    assert again["datum"] == item["datum"] and again["akzentFarbe"] == item["akzentFarbe"]
    conflicting = base.replace("X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "X-MAGNOLIE-TYPE-ID:wedding-anniversary\r\nX-NEXTCLOUD-BC-FIELD-TYPE:BDAY")
    assert m.ics_lesen(conflicting)["jahrestage"][0]["typ"] == "wedding-anniversary"
    case["passed"] = True
except Exception as error:
    case["passed"] = False
    case["error"] = str(error)
results.append(case)

report = {
    "checkout": str(args.checkout),
    "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.checkout, text=True).strip(),
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "fixtures_sha256": hashlib.sha256(args.fixtures.read_bytes()).hexdigest(),
    "cases": results,
    "passed": sum(case["passed"] for case in results),
    "boundary_de": "Zwei konkrete unabhängige Python-Codec-Regressionsfälle. Keine C#-, native GUI-, Server- oder Geräteausführung durch diese Probe.",
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
for case in results:
    print(json.dumps({key: case[key] for key in ("id", "passed", "error") if key in case}))
sys.exit(0 if report["passed"] == len(results) else 1)
