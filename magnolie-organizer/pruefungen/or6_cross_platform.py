#!/usr/bin/env python3
"""Compare both actual native OR6 readers without building or starting a VM."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "magnolie-organizer/bin"))
from magnolie_or6 import read_or6

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dotnet", required=True)
parser.add_argument("--core", required=True)
parser.add_argument("--extensions-only", action="store_true")
args = parser.parse_args()
files = {}
contracts = ["or6-native-extensions.json"] if args.extensions_only else ["or6-native-fixtures.json", "or6-native-extensions.json"]
for name in contracts:
    files.update(json.loads((root / "contracts" / name).read_text())["files"])
with tempfile.TemporaryDirectory(prefix="magnolie-or6-parity-", dir="/tmp/opencode") as directory:
    for name, item in files.items():
        assert Path(name).name == name
        raw = gzip.decompress(base64.b64decode(item["gzip_base64"], validate=True))
        assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
        path = Path(directory) / name; path.write_bytes(raw)
        linux = read_or6(raw)
        windows = json.loads(subprocess.check_output([args.dotnet, args.core, "--or6-json", str(path)], cwd=root, text=True, timeout=30))
        for key in ("kontakte", "termine", "aufgaben", "notizen", "jahrestage", "geburtstage", "uebersprungen", "wiederholend"):
            if linux[key] != windows[key]:
                raise SystemExit("OR6 native parity failed: " + name + "/" + key)
        print("OR6 CROSS PLATFORM PASS: " + name)
print("OR6 CROSS PLATFORM PASS: exact records, recurrence sets/exceptions, category memberships, phone contexts and omission counts")
