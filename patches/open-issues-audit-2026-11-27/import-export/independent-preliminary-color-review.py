#!/usr/bin/env python3
"""Narrow actual-codec review; no GUI, build, or native device claims."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument("--baseline", type=Path, required=True)
p.add_argument("--candidate", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
args = p.parse_args()
sys.path.insert(0, str(args.baseline / "magnolie-organizer/pruefungen"))
sys.modules["gi"] = None
from modul_laden import quellmodul_laden

relative = "magnolie-organizer/bin/magnolie-organizer"
old = quellmodul_laden("independent_844_baseline", args.baseline / relative)
new = quellmodul_laden("independent_844_candidate", args.candidate / relative)


def calendar(properties):
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:independent-844",
                        "SUMMARY:Independent synthetic color", "DTSTART;VALUE=DATE:20261205",
                        *properties, "END:VEVENT", "END:VCALENDAR", ""])


def parse(codec, raw):
    return codec.import_rohdaten_lesen("ics", raw.encode(), "independent-synthetic.ics")


def export(codec, payload):
    try:
        text = codec.ics_schreiben_termine(payload["termine"])
        return {"ok": True, "text": text, "reimport_accent": parse(codec, text)["termine"][0].get("akzentFarbe")}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


plain = calendar(["COLOR:turquoise"])
# This is the actual previous import persisted as JSON, not an invented legacy shape.
legacy = json.loads(json.dumps(parse(old, plain)))
raw = calendar(["COLOR;X-SOURCE=owned-synthetic:red", "X-MAGNOLIE-ACCENT-COLOR:#112233"])
cases = [
    {"id": "persisted-pre-patch-color", "input": plain, "persisted_payload": legacy,
     "baseline_export": export(old, legacy), "candidate_export": export(new, legacy)},
    {"id": "own-over-parameterized-color-unchanged", "input": raw,
     "baseline_import_export": export(old, parse(old, raw)),
     "candidate_import_export": export(new, parse(new, raw))},
]
report = {"boundary_de": "Tatsächliche Python-Parser/Exporter, ausschließlich synthetische Daten. Vorläufiger Review auf noch nicht festgeschriebenem Backend-Diff; keine native oder UI-Abnahme.",
          "sources": {str(root / relative): hashlib.sha256((root / relative).read_bytes()).hexdigest()
                      for root in (args.baseline, args.candidate)}, "cases": cases}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"cases": len(cases), "legacy_accent": legacy["termine"][0].get("akzentFarbe"),
                  "baseline_preserves_color": "COLOR:turquoise" in cases[0]["baseline_export"].get("text", ""),
                  "candidate_preserves_color": "COLOR:turquoise" in cases[0]["candidate_export"].get("text", ""),
                  "parameterized_export_before": cases[1]["baseline_import_export"]["ok"],
                  "parameterized_export_after": cases[1]["candidate_import_export"]["ok"]}))
