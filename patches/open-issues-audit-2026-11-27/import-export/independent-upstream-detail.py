#!/usr/bin/env python3
"""Focused actual Python codec review of upstream #844, with synthetic inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument("--checkout", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
args = p.parse_args()
sys.path.insert(0, str(args.checkout / "magnolie-organizer/pruefungen"))
sys.modules["gi"] = None
from modul_laden import quellmodul_laden
source = args.checkout / "magnolie-organizer/bin/magnolie-organizer"
codec = quellmodul_laden("independent_upstream_844", source)


def calendar(name, component=(), header=(), birthday=False):
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", *header, "BEGIN:VEVENT", "UID:" + name,
                        "SUMMARY:" + name, "DTSTART;VALUE=DATE:20000229",
                        *(["X-MAGNOLIE-TYPE-ID:birthday", "RRULE:FREQ=YEARLY"] if birthday else []),
                        *component, "END:VEVENT", "END:VCALENDAR", ""])


def parse(raw):
    return codec.import_rohdaten_lesen("ics", raw.encode(), "synthetic-844-review.ics")


def write(payload):
    result = {}
    for kind in ("termine", "aufgaben", "jahrestage"):
        if payload.get(kind):
            raw = getattr(codec, "ics_schreiben_" + kind)(payload[kind])
            result[kind] = {"text": raw, "reimport": parse(raw)}
    return result


rows = []
for name, component, header, expected in (
    ("birthday-standard", ["COLOR:turquoise"], [], "#40e0d0"),
    ("birthday-own", ["X-MAGNOLIE-ACCENT-COLOR:#112233"], [], "#112233"),
    ("birthday-calendar", [], ["COLOR:turquoise"], "#40e0d0"),
):
    raw = calendar(name, component, header, birthday=True)
    payload = parse(raw)
    entry = payload["jahrestage"][0]
    rows.append({"id": name, "input": raw, "expected_accent": expected, "payload": payload,
                 "accent_matches": entry.get("akzentFarbe") == expected,
                 "birthday_type_preserved": entry.get("typ") == "birthday",
                 "exports": write(payload)})

for name, component in (
    ("parameterized-standard-unchanged", ["COLOR;X-SOURCE=synthetic:red"]),
    ("parameterized-own-over-standard", ["COLOR;X-SOURCE=synthetic:red", "X-MAGNOLIE-ACCENT-COLOR:#112233"]),
    ("unknown-component-color", ["COLOR:synthetic-unknown", "X-SOURCE:synthetic"]),
):
    raw = calendar(name, component)
    payload = parse(raw)
    exports = write(json.loads(json.dumps(payload)))
    rows.append({"id": name, "input": raw, "payload": payload, "exports": exports,
                 "raw_color_preserved": component[0] in exports["termine"]["text"]})

raw = calendar("edited-and-cleared", ["COLOR:turquoise", "X-SOURCE:synthetic"], ["COLOR:blue"])
payload = json.loads(json.dumps(parse(raw)))
payload["termine"][0]["akzentFarbe"] = "#123456"
edited = write(payload)
payload["termine"][0]["akzentFarbe"] = ""
cleared = write(payload)
rows.append({"id": "edited-and-cleared", "input": raw, "edited": edited, "cleared": cleared,
             "edit_pass": edited["termine"]["reimport"]["termine"][0]["akzentFarbe"] == "#123456",
             "clear_pass": cleared["termine"]["reimport"]["termine"][0]["akzentFarbe"] == "",
             "unknown_metadata_preserved": "X-SOURCE:synthetic" in cleared["termine"]["text"]})
raw = calendar("with-default", [], ["COLOR:blue"]) + calendar("without-default")
payload = json.loads(json.dumps(parse(raw)))
exports = write(payload)
rows.append({"id": "two-calendar-roots", "input": raw, "payload": payload, "exports": exports,
             "scope_pass": [entry["akzentFarbe"] for entry in exports["termine"]["reimport"]["termine"]] == ["#0000ff", ""]})

report = {"checkout": str(args.checkout),
          "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.checkout, text=True).strip(),
          "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "cases": rows,
          "boundary_de": "Acht gezielte Diagnosefälle am tatsächlichen Python-Parser/Exporter. JSON-Speichern wird durch Serialisierung nachvollzogen; keine GUI-/native Speicherabnahme. Regulärer Skriptexit ist keine pauschale fachliche Freigabe."}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
for row in rows:
    print(json.dumps({key: value for key, value in row.items()
                      if key in ("id", "accent_matches", "birthday_type_preserved", "raw_color_preserved", "edit_pass", "clear_pass", "unknown_metadata_preserved", "scope_pass")}))
