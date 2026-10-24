#!/usr/bin/env python3
"""Compare both actual native OR6 readers without building or starting a VM."""
import argparse
import base64
import gzip
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "magnolie-organizer/bin"))
from magnolie_or6 import read_or6

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dotnet", required=True)
parser.add_argument("--core", required=True)
args = parser.parse_args()
contract = json.loads((root / "contracts/or6-native-fixtures.json").read_text())
raw = gzip.decompress(base64.b64decode(contract["files"]["known-values.or6"]["gzip_base64"]))
linux = read_or6(raw)
windows = json.loads(subprocess.check_output([args.dotnet, args.core, "--or6-json"], cwd=root, text=True, timeout=30))
for key in ("kontakte", "termine", "aufgaben", "notizen", "jahrestage", "geburtstage", "uebersprungen", "wiederholend"):
    if linux[key] != windows[key]:
        raise SystemExit("OR6 native parity failed: " + key)
print("OR6 CROSS PLATFORM PASS: exact records, Unicode, RTF text, dates, priorities, stable identities and omission counts")
