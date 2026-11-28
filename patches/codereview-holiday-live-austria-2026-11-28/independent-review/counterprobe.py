#!/usr/bin/env python3
"""The 36-case independent countercheck executed for the final #856 Linux fix.

This is the same case/Assertion loop as the observed review execution, with
portable CLI path selection and a source-binding guard added for reproduction.
It imports the existing product-function host; it does not rebuild the algorithm.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy


parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
args = parser.parse_args()
repo = args.repo.resolve()
manifest = json.loads(Path(__file__).with_name("SOURCE-MANIFEST.json").read_text())
for source in manifest["probe_inputs"]:
    actual = hashlib.sha256((repo / source["path"]).read_bytes()).hexdigest()
    if actual != source["sha256"]:
        raise SystemExit("The recorded countercheck input differs: " + source["path"])

os.environ["MAGNOLIE_HOLIDAY_SOURCE"] = str(repo / "magnolie-organizer/bin/magnolie-organizer")
m = runpy.run_path(str(repo / "magnolie-organizer/pruefungen/test_holiday_fetch_coverage.py"))
T = m["HolidayCoverageTests"]
verified = 0
bad_scopes = [["WI"], ["9"], ["AT"], ["AT-9-UNKNOWN"], ["AT-WI-UNKNOWN"],
              ["AT-WI", "WI"], ["AT-WI", "DE-SN"], ["AT-WI", "AT-9-UNKNOWN"]]
for selected in ["", "AT-9"]:
    for nationwide in [False, True]:
        for scopes in bad_scopes:
            t = T()
            t.setUp()
            row = m["row"](nationwide=nationwide, subdivisions=[{"code": c} for c in scopes])
            out = t.fetch(lambda *_: [row], land="AT", region=selected, ferien=False)
            assert out["abrufbereiche"] == [], (selected, nationwide, scopes, out["abrufbereiche"])
            verified += 1
for selected in ["", "AT-9"]:
    for nationwide in [False, True]:
        t = T()
        t.setUp()
        out = t.fetch(lambda *_: [m["row"](nationwide=nationwide,
            subdivisions=[{"code": "AT-WI"}])], land="AT", region=selected, ferien=False)
        assert len(out["abrufbereiche"]) == 1
        assert out["feiertage"][0]["regions"] == ["AT-9"]
        verified += 1
print(json.dumps({"independent_linux_counterchecks": verified,
    "negative_combinations": 32, "positive_controls": 4, "all_passed": True}, indent=2))
