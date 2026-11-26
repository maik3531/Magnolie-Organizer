#!/usr/bin/env python3
"""Check native-shaped alias transport against real projected UI; native Swift DTO is optional."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from check_calendar import canonical
import project_ui
from project_import_helper import canonical_temporary_root


def baseline_projection(reference, directory):
    """Keep the old projector and every tracked input in the same Git tree.

    The current fixture/runner deliberately exercise the historical UI. Ignored
    gettext assets are rebuilt with that tree's generator and PO files instead
    of borrowing catalogs or product sources from the current working copy.
    """
    commit = subprocess.check_output(["git", "rev-parse", "--verify", "--end-of-options",
        reference + "^{commit}"], cwd=project_ui.REPO, text=True).strip()
    archive = directory / "baseline.tar"
    with archive.open("wb") as output:
        subprocess.run(["git", "archive", "--format=tar", commit], cwd=project_ui.REPO,
            stdout=output, check=True)
    source = directory / "baseline"
    with tarfile.open(archive) as bundle:
        bundle.extractall(source, filter="data")
    archive.unlink()
    linux = source / "magnolie-organizer"
    for language in (linux / "po/LINGUAS").read_text().split():
        subprocess.run([sys.executable, str(linux / "werkzeuge/po_zu_js.py"), language,
            str(linux / "po" / (language + ".po")), str(linux / "web/i18n" / (language + ".js"))], check=True)
    path = source / "Magnolie-Organizer-macOS-Beta/tools/project_ui.py"
    namespace = {"__file__": str(path), "__name__": "legacy_alias_baseline_projection"}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    snapshot = namespace["inputs"]()
    print("Historical projection: " + commit + "; all tracked inputs from Git; "
          "gettext catalogs rebuilt from historical PO files; current regression fixture.", flush=True)
    return snapshot, namespace["project"]


def fixtures():
    module = canonical()
    path = project_ui.REPO / "Magnolie-Organizer-Android-Tablet-Beta/app/src/test/resources/calendar-import-v2.0.30.json"
    text = next(row["importSource"] for row in json.loads(path.read_text())["cases"] if row["name"] == "caldav-series-resource")
    source_name = "caldav-series-resource.ics"
    source = "ics:" + hashlib.sha256((source_name + "\nTeam Calendar").encode()).hexdigest()
    rid = "RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000"

    def response(value, params=None, source_id=source):
        params = {"TZID": "Europe/Berlin"} if params is None else params
        result = module.ics_lesen(value, quellenname=source_name, quellen_id=source_id)
        payload = {key: result[key] for key in ["termine", "aufgaben", "jahrestage"]}
        source_hash = hashlib.sha256(value.encode()).hexdigest()
        payload["icsImportMetadata"] = {"version": 1, "sourceSHA256": source_hash,
            "calendarProperties": ["VERSION:2.0", "PRODID:-//Example Corp//CalDAV 1.0//EN", "X-WR-CALNAME:Team Calendar"]}
        entries = []
        for index, row in enumerate(payload["termine"]):
            raw = next((line for line in row["icsRoundtrip"] if line.startswith("RECURRENCE-ID")), None)
            if raw is None:
                continue
            current = json.dumps([params, raw.split(":", 1)[1]], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            wire = row["icsSerienUid"]
            assert row["uid"] == wire + "-magnolie-instanz-" + hashlib.sha256(current.encode()).hexdigest()[:16]
            legacy = wire + "-magnolie-instanz-" + hashlib.sha256(current.replace("/", "\\/").encode()).hexdigest()[:16]
            entries.append({"appointmentIndex": index, "canonicalUID": row["uid"], "legacyUID": legacy,
                "sourceID": row["icsQuelleId"], "wireUID": wire, "recurrenceLine": raw})
        assert entries
        payload["legacyAndroidAliases"] = {"version": 1, "algorithm": "android-jsonobject-quote-v1",
            "sourceSHA256": source_hash, "appointmentCount": len(payload["termine"]), "entries": entries}
        return payload

    base = response(text)
    assert base["legacyAndroidAliases"]["entries"][0]["legacyUID"] == "caldav-series-1-magnolie-instanz-7f5e24178d89f683"
    variants = {
        "source": response(text, source_id="ics:" + "b" * 64),
        "wire": response(text.replace("UID:caldav-series-1", "UID:other-series-465")),
        "rid": response(text.replace(rid, rid.replace("20261102", "20261109"))),
        "tzid": response(text.replace(rid, rid.replace("Europe/Berlin", "Europe/Paris")), {"TZID": "Europe/Paris"}),
        "range": response(text.replace(rid, rid.replace("RECURRENCE-ID;", "RECURRENCE-ID;RANGE=THISANDFUTURE;")),
            {"RANGE": "THISANDFUTURE", "TZID": "Europe/Berlin"}),
        "value": response(text.replace(rid, rid.replace("RECURRENCE-ID;", "RECURRENCE-ID;VALUE=DATE-TIME;")),
            {"TZID": "Europe/Berlin", "VALUE": "DATE-TIME"})}
    return {"base": base, "variants": variants, "nativeEnvelope": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--js-runtime", required=True)
    parser.add_argument("--native-envelope", type=Path)
    parser.add_argument("--baseline-ref", help="Project an isolated committed tree with its own rebuilt gettext catalogs (requires msgfmt); current regression fixture, no working-copy changes")
    args = parser.parse_args()
    fixture = fixtures()
    if args.native_envelope:
        response = json.loads(args.native_envelope.read_text())
        assert response["legacyAndroidAliases"] == fixture["base"]["legacyAndroidAliases"]
        assert response["icsImportMetadata"]["sourceSHA256"] == fixture["base"]["icsImportMetadata"]["sourceSHA256"]
        fixture["base"] = response
        fixture["nativeEnvelope"] = True
    snapshot = project_ui.inputs()
    projector = project_ui.project
    with tempfile.TemporaryDirectory(prefix="macOS-Beta-calendar-alias-") as directory:
        root = canonical_temporary_root(directory)
        if args.baseline_ref:
            snapshot, projector = baseline_projection(args.baseline_ref, root)
        projector(snapshot, root / "UI")
        (root / "fixture.json").write_text(json.dumps(fixture))
        command = [args.js_runtime]
        if Path(args.js_runtime).name == "deno":
            command += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
        command += ["tests/legacy_calendar_aliases.mjs", str(root / "UI"), str(root / "fixture.json")]
        if args.baseline_ref:
            command.append("--probe")
        subprocess.run(command, cwd=project_ui.BETA, check=True, timeout=120)
    if not args.baseline_ref and project_ui.inventory(project_ui.inputs()) != project_ui.inventory(snapshot):
        raise RuntimeError("Sources changed during legacy calendar alias checks.")


if __name__ == "__main__":
    main()
