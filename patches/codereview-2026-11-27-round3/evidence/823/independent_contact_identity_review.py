#!/usr/bin/env python3
"""Independent #823 permutation checks against the actual native selector."""
from pathlib import Path
import copy
import hashlib
import itertools
import json
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "magnolie-organizer/pruefungen"))
from modul_laden import quellmodul_laden

source = root / "magnolie-organizer/bin/magnolie-organizer"
native = quellmodul_laden("independent_restore_identity_review", source)
results = []
current_contacts = [
    {"id": "left", "uid": "new-left", "notiz": "",
     "syncQuellen": {"live-left": {"id": "left.vcf"}},
     "telefonWerteAenderung": {"requestId": "live-left"}, "opaqueLive": {"keep": "left"}},
    {"id": "right", "uid": "old-left", "notiz": "",
     "syncQuellen": {"live-right": {"id": "right.vcf"}}, "opaqueLive": {"keep": "right"}},
]
snapshot_contacts = [
    {"id": "left", "uid": "old-left", "notiz": "left detail",
     "davHref": "/archived-left.vcf", "opaqueOld": {"grant": "never"}},
    {"id": "right", "uid": "new-left", "notiz": "right detail",
     "syncQuellen": {"archived": {}}, "opaqueOld": {"grant": "never"}},
]
for current_order in itertools.permutations(current_contacts):
    for snapshot_order in itertools.permutations(snapshot_contacts):
        current = {"kontakte": copy.deepcopy(list(current_order))}
        snapshot = {"kontakte": copy.deepcopy(list(snapshot_order))}
        untouched = copy.deepcopy((current, snapshot))
        result = native.journal_restore_daten(snapshot, current, ["contacts"], "additive")
        by_id = {item["id"]: item for item in result["kontakte"]}
        assert len(result["kontakte"]) == 2
        for original in current_contacts:
            expected = {**original, "notiz": original["id"] + " detail"}
            assert by_id[original["id"]] == expected
        assert (current, snapshot) == untouched
        repeated = native.journal_restore_daten(snapshot, result, ["contacts"], "additive")
        assert repeated["kontakte"] == result["kontakte"]
        results.append({"case": "swapped UID collision", "current_order": [x["id"] for x in current_order],
                        "snapshot_order": [x["id"] for x in snapshot_order], "passed": True})

ambiguous = [{"id": "same", "uid": "one", "notiz": "first"},
             {"id": "same", "uid": "two", "notiz": "second"}]
for snapshot_order in itertools.permutations(ambiguous):
    current = {"kontakte": [{"id": "same", "uid": "live", "notiz": ""}]}
    untouched = copy.deepcopy(current)
    try:
        native.journal_restore_daten({"kontakte": list(snapshot_order)}, current, ["contacts"], "additive")
    except ValueError:
        pass
    else:
        raise AssertionError("Ambiguous snapshot local IDs must reject the restore")
    assert current == untouched
    results.append({"case": "ambiguous snapshot rejects", "snapshot_order": [x["uid"] for x in snapshot_order],
                    "passed": True})

print(json.dumps({
    "reviewed_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "independent_cases": len(results), "passed": len(results), "results": results,
    "scope": "Actual Python restore selection; input immutability, idempotence, stable local ID precedence, current transport and unknown metadata preservation, ambiguity rejection; no GUI or native Windows claim."
}, indent=2) + "\n")
