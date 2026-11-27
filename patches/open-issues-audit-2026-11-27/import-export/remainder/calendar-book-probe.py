#!/usr/bin/env python3
"""Read/write actual Linux calendar codecs; synthetic inputs only, no GUI claim."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--checkout", type=Path, required=True)
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--mode", choices=("import", "export", "store-export"), default="import")
args = parser.parse_args()
sys.path.insert(0, str(args.checkout / "magnolie-organizer/pruefungen"))
sys.modules["gi"] = None
from modul_laden import quellmodul_laden
source = args.checkout / "magnolie-organizer/bin/magnolie-organizer"
codec = quellmodul_laden("calendar_semantics_probe", source)
cases = json.loads(args.input.read_text())
results = []
for case in cases:
    result = {"id": case["id"]}
    if args.mode == "import":
        payload = codec.import_rohdaten_lesen("ics", case["input"].encode("utf-8"), case["id"] + ".ics")
        result["payload"] = payload
    else:
        payload = case["book"]
        if args.mode == "store-export":
            with tempfile.TemporaryDirectory(prefix="magnolie-colour-book-") as directory:
                book_path = Path(directory) / "book.json"
                codec.daten_datei = lambda: str(book_path)
                codec.speichere_daten(payload)
                codec._DATEN_ZWISCHENSPEICHER = {"stand": None, "daten": None}
                reopened = codec.daten_lesen_gepuffert(str(book_path))
                assert reopened == payload, case["id"] + ": real native book reopen changed JSON"
                result["storage"] = {"path": "speichere_daten → atomar_text_schreiben → daten_lesen_gepuffert", "book_reopened_equal": True,
                                     "file_sha256": hashlib.sha256(book_path.read_bytes()).hexdigest()}
                payload = reopened
    result["exports"] = {}
    for kind in ("termine", "aufgaben", "jahrestage"):
        values = payload.get(kind, [])
        if not values:
            continue
        raw = getattr(codec, "ics_schreiben_" + kind)(values)
        result["exports"][kind] = {"text": raw, "reimport": codec.import_rohdaten_lesen(
            "ics", raw.encode("utf-8"), case["id"] + ".ics")}
    results.append(result)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"runtime": "Python", "mode": args.mode, "cases": len(results),
                  "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "output": str(args.output)}))
