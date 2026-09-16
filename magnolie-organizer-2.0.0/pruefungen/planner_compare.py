#!/usr/bin/env python3
"""Compare paired native evidence, never infer compatibility from speed alone."""
import argparse
import json
from pathlib import Path
import statistics
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("published", type=Path)
parser.add_argument("current", type=Path)
args = parser.parse_args()
old, new = args.published, args.current
manifests = [json.loads((path / "manifest.json").read_text()) for path in (old, new)]
assert manifests[0]["synthetic_payload_sha256"] == manifests[1]["synthetic_payload_sha256"], "Different raw fixtures"
assert manifests[0]["published_version"] == "2.0.17", "Not the published baseline"
reports = [json.loads((path / "results.json").read_text()) for path in (old, new)]
assert all(m["source_unchanged"] and m["deb_unchanged"] for m in manifests)
assert all(m["gpu_devices_hidden"] and not m["profile"] for m in manifests)
assert manifests[0]["cpus"] == manifests[1]["cpus"]
out = {"payload": manifests[0]["synthetic_payload_sha256"], "tier": manifests[0]["tier"], "timing": {}}
for name in ("responseMs", "handlerMs"):
    values = [[sample[direction][name] for sample in r["events"] if sample.get("probe") == "sample"
               for direction in ("entered", "left")] for r in reports]
    if not values[0]:
        continue
    assert len(values[0]) == len(values[1])
    for label, fn in (("median", statistics.median), ("p95", lambda v: sorted(v)[int(len(v)*.95)]), ("max", max)):
        a, b = map(fn, values)
        out["timing"][name + "-" + label] = {"published_ms": a, "current_ms": b,
            "latency_reduction_percent": round(100*(a-b)/a, 2) if a else None}
out["summaries"] = [r["summary"] for r in reports]
visible = [next((e for e in r["events"] if e.get("probe") == "normal-visible"), None) for r in reports]
if all(visible):
    out["visible_normal"] = {"ordinary_dots": [v["ordinaryDots"] for v in visible],
        "special_marks": [len(v["marks"]) for v in visible],
        "special_dates_and_titles_equal": [[(m["date"], m["title"]) for m in v["marks"]] for v in visible][0] ==
                                         [[(m["date"], m["title"]) for m in v["marks"]] for v in visible][1]}
out["prints"] = []
for file in sorted(old.glob("*-*.json")):
    payload = json.loads(file.read_text())
    if not isinstance(payload, dict) or "ods" not in payload:
        continue
    other = json.loads((new / file.name).read_text())
    equal_ods = payload["ods"] == other["ods"]
    equal_html = file.with_suffix(".html").read_bytes() == (new / file.with_suffix(".html").name).read_bytes()
    artifact = {"name": file.stem, "ods_payload_equal": equal_ods, "html_equal": equal_html}
    for part in ("content.xml", "styles.xml"):
        if file.with_suffix(".ods").exists() and (new / file.with_suffix(".ods").name).exists():
            with zipfile.ZipFile(file.with_suffix(".ods")) as a, zipfile.ZipFile(new / file.with_suffix(".ods").name) as b:
                artifact[part + "_equal"] = a.read(part) == b.read(part)
    out["prints"].append(artifact)
out["semantics"] = [[e for e in r["events"] if e.get("probe") == "recurrence-compatibility"] for r in reports]
out["compatible"] = bool(all(out["semantics"]) and all(e["ok"] for group in out["semantics"] for e in group))
if out["compatible"]:
    assert all(all(value for key, value in artifact.items() if key != "name") for artifact in out["prints"]), "Compatible fixture print regression"
print(json.dumps(out, indent=2))
