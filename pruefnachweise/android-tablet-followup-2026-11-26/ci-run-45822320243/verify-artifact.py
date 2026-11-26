#!/usr/bin/env python3
"""Reproduce CI101 artifact, APK/source, JUnit and native provider verification.

Uses only the Python standard library. Reads the original ZIP and optionally
the full original joblog. No build, emulator, network or provider action.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
HEAD = "7a7d90b04796cf338b98f0fdbb87e8da1c967043"
TREE = "06c1a8cf6f115908dc21252682c2a358246f2cb7"
PROJECTION = "dbe502cf4ad4661be79dca584c120d8623676cf8be5c3ff0d61eba840b676c09"
ZIP_SHA = "094747195afdd58a42fc3f83ef77046fef7e579d9daeedabc537eb9d6b585b72"
ZIP_SIZE = 12393742


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative(name):
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts, "Unsafe path")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--job-log", type=Path, help="Optional full original job139917463400 log")
    parser.add_argument("--output", type=Path, help="Explicit JSON report destination; otherwise stdout")
    args = parser.parse_args()
    raw = args.artifact_zip.read_bytes()
    require(len(raw) == ZIP_SIZE and sha(raw) == ZIP_SHA, "Original ZIP size/digest mismatch")
    index = json.loads((ROOT / "evidence-index.json").read_text())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP member")
        for name in names:
            relative(name)
        require(sum(item.file_size for item in archive.infolist()) < 500_000_000, "Oversized ZIP")

        def read_json(name):
            return json.loads(archive.read(name))

        def one(suffix):
            matches = [name for name in names if name.endswith(suffix)]
            require(len(matches) == 1, "Expected one member: " + suffix)
            return matches[0]

        copies = []
        for item in index["copies"]:
            data = (ROOT / relative(item["path"])).read_bytes()
            require(len(data) == item["bytes"] and sha(data) == item["sha256"], "Copy hash mismatch")
            if item["origin"]["kind"] == "artifact-member":
                require(data == archive.read(item["origin"]["member"]), "Copy differs from ZIP member")
            copies.append({"path": item["path"], "bytes": len(data), "sha256": sha(data), "verified": True})

        sources_raw = archive.read("artifacts/sources.json")
        sources = json.loads(sources_raw)
        checkout = read_json("artifacts/source-checkout.json")
        selected = json.loads((ROOT / "source-binding-selection.json").read_text())
        require(selected["kind"] == "selection; not the original complete record", "Unlabelled selection")
        require(selected["originalSha256"] == sha(sources_raw) and selected["originalBytes"] == len(sources_raw),
                "Source selection original hash mismatch")
        require(selected["selected"] == {k: v for k, v in sources.items() if k != "inputs"} and
                selected["omittedInputRecords"] == len(sources["inputs"]), "Source selection differs")
        run = json.loads((ROOT / "run-record-selection.json").read_text())["selected"]
        require(run["run"]["id"] == 45822320243 and run["run"]["run_attempt"] == 1 and
                run["run"]["head_sha"] == HEAD and run["run"]["conclusion"] == "success", "Run binding mismatch")
        require(run["job"]["id"] == 139917463400 and run["job"]["conclusion"] == "success", "Job mismatch")
        require(run["observedCommit"] == {"sha": HEAD, "tree": TREE}, "Observed Git tree mismatch")
        for record in [sources, checkout]:
            require(record["sourceMode"] == "current-checkout" and record["portCommit"] == record["desktopCommit"] == HEAD,
                    "Current-checkout source mismatch")
            require(record["gitTree"] == TREE and record["nativeAcceptance"] is False and
                    record["productionRelease"] is False, "Source scope mismatch")
        require(sources["inputSetSha256"] == checkout["inputSetSha256"], "Input set mismatch")
        require(sources["generatedCatalogsVerified"] is True, "Catalog proof missing")
        require(sources["componentSuite"] == "system-records" and sources["systemProviderOnly"] is True and
                sources["runtimeApi"] == 34 and sources["systemImage"] == "google_apis" and
                sources["componentOnly"] is True and sources["googleAcceptance"] is False, "Runtime scope mismatch")
        candidate_raw = archive.read("artifacts/candidate.json")
        candidate = json.loads(candidate_raw)
        require(sha(candidate_raw) == sources["candidateManifestSha256"], "Candidate manifest mismatch")
        require(candidate["stale"] is False and candidate["apkAssetsVerified"] is True and
                candidate["signing"] == "debug only" and candidate["instrumentationTestOnly"] is True, "Candidate scope mismatch")
        apks = []
        for name_key, hash_key, bound_key in [("name", "sha256", "apkSha256"),
                                             ("testApk", "testApkSha256", "testApkSha256")]:
            name = candidate[name_key]
            require(PurePosixPath(name).name == name and name.endswith(".apk"), "Unsafe APK filename")
            data = archive.read("artifacts/" + name)
            require(sha(data) == candidate[hash_key] == sources[bound_key], "APK digest mismatch")
            apks.append({"name": name, "bytes": len(data), "sha256": sha(data)})
        with zipfile.ZipFile(io.BytesIO(archive.read("artifacts/" + candidate["name"]))) as app:
            packed = app.read("assets/projection.json")
        require(sha(packed) == sources["projectionManifestSha256"], "Packaged projection manifest mismatch")
        web = read_json("artifacts/web-test-proof.json")
        provider_member = one("/system-records-receipt.json")
        stage_member = one("/system-records.json")
        provider = read_json(provider_member)
        stage = read_json(stage_member)
        require(json.loads(packed)["sourceHash"] == candidate["sourceHash"] == sources["projectionSourceHash"] ==
                web["sourceHash"] == stage["sourceHash"] == PROJECTION, "Projection hashes differ")

        junit = []
        totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        for name in sorted(names):
            if not (name.startswith("app/build/test-results/testDebugUnitTest/TEST-") and name.endswith(".xml")):
                continue
            data = archive.read(name)
            suite = ET.fromstring(data)
            require(suite.tag == "testsuite", "Unexpected JUnit root")
            counts = {key: int(suite.attrib.get(key, "0")) for key in totals}
            require(counts["tests"] == len(suite.findall("testcase")) and
                    counts["failures"] == len(suite.findall("testcase/failure")) and
                    counts["errors"] == len(suite.findall("testcase/error")) and
                    counts["skipped"] == len(suite.findall("testcase/skipped")), "JUnit count mismatch")
            target = ROOT / "junit" / PurePosixPath(name).name
            require(target.read_bytes() == data, "JUnit copy differs")
            for key in totals:
                totals[key] += counts[key]
            junit.append({"artifactMember": name, "path": str(target.relative_to(ROOT)), "class": suite.attrib["name"],
                          "bytes": len(data), "sha256": sha(data), **counts})
        require(len(junit) == 42 and totals == {"tests": 303, "failures": 0, "errors": 0, "skipped": 0}, "JUnit totals differ")
        require(candidate["unitTests"] == totals["tests"], "Candidate test count mismatch")

        require(provider["passed"] is True and stage["passed"] is True and stage["error"] is None and
                provider["sdk"] == stage["sdk"] == 34, "Provider stage did not pass")
        require(any(check.get("detail") == provider for check in stage["checks"]), "Stage does not include the exact provider receipt")
        require(len(provider["checks"]) == 11 and provider["checks"][-1].startswith("owned fixture IDs removed"), "Provider group count differs")
        permissions = provider["productPermissionChecks"]
        require(len(permissions) == 19 and all(row["dropShellPermissionIdentityCompleted"] is True and
                not row["fixtureScopeActive"] and not row["writeContacts"] and not row["writeCalendar"]
                for row in permissions), "Product call had fixture WRITE privileges")
        for operation in ("cancelled-contacts", "cancelled-events"):
            rows = [row for row in permissions if row["operation"] == operation]
            require(len(rows) == 1 and rows[0]["readContacts"] and rows[0]["readCalendar"], "Cancellation path not reached with READ granted")
        require("Android CancellationSignal rejects both reads before querying" in provider["checks"], "Cancellation result missing")
        cleanup = {"requestedRawRows": 2, "requestedCalendars": 2, "remainingOwnedRawRows": 0,
                   "remainingOwnedCalendars": 0, "shellIdentityDropped": True, "writePermissionsDenied": True}
        require(provider["cleanup"] == cleanup, "Cleanup proof differs")
        recurrence = provider["recurringException"]
        require(recurrence["linkage"] == "synthetic-sync-adapter" and recurrence["beforeCount"] == recurrence["afterCount"] == 2 and
                len(recurrence["before"]) == len(recurrence["after"]) == 2, "Recurrence count differs")
        before = {row["date"]: row for row in recurrence["before"]}
        after = {row["date"]: row for row in recurrence["after"]}
        require(set(before) == set(after) == {"2030-04-01", "2030-04-02"}, "Unexpected recurrence dates")
        require(before["2030-04-01"]["recordId"] == after["2030-04-01"]["recordId"] and
                before["2030-04-01"]["time"] == "09:00" and after["2030-04-01"]["time"] == "12:00" and
                before["2030-04-02"] == after["2030-04-02"], "Original recurrence identity changed")
        require(all(row["identityKind"] == "recurring-instance" for row in recurrence["before"] + recurrence["after"]), "Wrong recurrence identity kind")
        rows = recurrence["providerEvents"]
        require(len(rows) == 2, "Expected parent and exception provider rows")
        parents = [row for row in rows if row["original_id"] is None]
        exceptions = [row for row in rows if row["original_id"] is not None]
        require(len(parents) == len(exceptions) == 1, "Unexpected parent/exception shape")
        parent, exception = parents[0], exceptions[0]
        require(exception["original_id"] == parent["_id"] and exception["original_sync_id"] == parent["_sync_id"] and
                exception["originalInstanceTime"] == parent["dtstart"], "Provider linkage differs")
        require(provider["recurrenceFixtureUsesSyncMetadata"] is True and
                provider["unsyncedLocalRecurrenceExceptionsTested"] is False and
                provider["contactsSourceIsolationTested"] is False and provider["calendarSourceIsolationTested"] is True,
                "Coverage scope differs")
        for key in ("permissionDialogsTested", "livePermissionRevocationTested", "saveAckTested", "inFlightCancellationTested"):
            require(provider[key] is False, "Unexpected wider coverage claim")

    log_verified = False
    if args.job_log:
        data = args.job_log.read_bytes()
        require(len(data) == index["omittedJobLog"]["bytes"] and sha(data) == index["omittedJobLog"]["sha256"], "Full log digest mismatch")
        for item in index["copies"]:
            if item["origin"]["kind"] == "verbatim-job-log-excerpt":
                require((ROOT / item["path"]).read_bytes() in data, "Excerpt is not a verbatim log substring")
        log_verified = True
    report = {
        "schema": 1, "verifierSha256": sha(Path(__file__).read_bytes()), "runId": 45822320243, "attempt": 1,
        "jobId": 139917463400, "artifactId": 15117579862, "headSha": HEAD, "gitTree": TREE,
        "conclusion": "success", "buildGate": "success", "providerSuite": "success", "projectionSourceHash": PROJECTION,
        "artifact": {"bytes": ZIP_SIZE, "sha256": ZIP_SHA}, "sourceInputSetSha256": sources["inputSetSha256"],
        "apkSourceBindingVerified": True, "candidateManifestDigestVerified": True,
        "packagedProjectionManifestDigestVerified": True, "generatedCatalogsVerified": True, "apks": apks,
        "junit": {"reportCount": len(junit), "xmlBytes": sum(row["bytes"] for row in junit), **totals, "reports": junit},
        "provider": {"checkGroups": 11, "domainGroups": 10, "productPermissionChecksWithoutWrite": 19,
                     "recurrenceBeforeCount": 2, "recurrenceAfterCount": 2, "movedOriginalIdentityPreserved": True,
                     "unmovedSecondInstancePreserved": True, "cancellationContactsPassed": True,
                     "cancellationEventsPassed": True, "cleanup": cleanup,
                     "contactsSourceIsolationTested": False, "calendarSourceIsolationTested": True,
                     "recurrenceFixtureUsesSyncMetadata": True, "unsyncedLocalRecurrenceExceptionsTested": False,
                     "permissionDialogsTested": False, "livePermissionRevocationTested": False,
                     "inFlightCancellationTested": False, "saveAckTested": False},
        "scope": {"systemProviderOnly": True, "nativeAcceptance": False, "productionRelease": False, "googleAcceptance": False},
        "copies": copies, "omittedJobLog": {**index["omittedJobLog"], "completeOriginalReverified": log_verified},
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
        print(json.dumps({"output": str(args.output), "sha256": sha(text.encode()), "copiesVerified": len(copies),
                          "junit": totals, "providerGroups": 11, "productCallsWithoutWrite": 19, "result": "verified"}))
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
