"""Show four synthetic priority cases through both actual CSV readers.

Build tests/native-import/NativeImportProbe.csproj from the same source checkout
first. The native project references CoreTests' actual ExchangeCodec source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--dotnet", type=Path, required=True)
args = parser.parse_args()
source = args.source.resolve()
sys.path.insert(0, str(source / "magnolie-organizer/pruefungen"))
from modul_laden import quellmodul_laden

native = quellmodul_laden("hn_csv_real_source", source / "magnolie-organizer/bin/magnolie-organizer")
probe = source / "magnolie-organizer-windows/tests/native-import/bin/Debug/net8.0/NativeImportProbe.dll"
cases = [("H", 1), ("N", 3), ("Normal", 2), ("Not set", 2)]
csv = "\r\n".join([
    "BESCHREIBUNG;FAELLIGKEITSDATUM;PRIORITAET;ERLEDIGT",
    *(f"Case {index};31.05.2026;{value};Nein" for index, (value, _) in enumerate(cases)),
    "",
])
print("source_commit=" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip())
print("TZ=" + os.environ.get("TZ", "<unset>"))
for name in ["magnolie-organizer/bin/magnolie-organizer", "magnolie-organizer-windows/ExchangeCodec.cs",
             "contracts/lotus-task-csv-vectors.json", "magnolie-organizer-windows/tests/bin/Debug/net8.0/CoreTests.dll"]:
    print("sha256=" + hashlib.sha256((source / name).read_bytes()).hexdigest() + "  " + name)
request = {"operation": "parse", "art": "lotus", "file": "synthetic-tasks.csv", "text": csv}
result = subprocess.run([str(args.dotnet), str(probe)], input=json.dumps(request),
                        text=True, capture_output=True, check=True)
windows = json.loads(result.stdout)
linux = native.lotus_csv_lesen(csv.encode("utf-8-sig"))
failures = 0
for port, imported, key, skipped in [
    ("Linux", linux, "aufgaben", "uebersprungen"),
    ("Windows-source", windows, "Aufgaben", "Uebersprungen"),
]:
    assert imported[skipped] == 0 and len(imported[key]) == len(cases), imported
    for index, ((value, expected), task) in enumerate(zip(cases, imported[key])):
        ok = task["prio"] == expected
        assert task["titel"] == f"Case {index}" and task["faellig"] == "2026-05-31" and task["erledigt"] is False, task
        print(f"{port}: value={value!r} expected={expected} actual={task['prio']} {'PASS' if ok else 'FAIL'}")
        failures += not ok
print(f"RESULT: {8 - failures}/8 cases passed; {failures} failed")
raise SystemExit(1 if failures else 0)
