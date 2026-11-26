#!/usr/bin/env python3
"""Verify the two original CI99 artifacts and this compact evidence package.

Read-only: no build, emulator, provider access, network, or repository mutation.
The only optional output is the explicitly named JSON verification report.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parent
HEAD = "92e2c645cf0a8075325874f335087412e7f79c79"
TREE = "d7b912c6aba697da48ccf1919591a162a4a4a452"
PROJECTION = "6c0e5542020d04ffaf556ee1334bbe32c91fcfd0da81ff90749b64ca33a6fe8a"
EXPECTED_ARCHIVES = {
    "attempt-1": (41044, "91bb767247dce6d279c5c50250de82d020a81522bbfec21c83fd991c5f1bb08b"),
    "attempt-2": (12387207, "e1274e177b578bafd4ff4a10a37bf5a6f7e1cd8e1a78569c0f9c83e074cf0759"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def safe_relative(value):
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts, "Unsafe relative path")
    return path


def archive(path, attempt):
    content = path.read_bytes()
    size, expected = EXPECTED_ARCHIVES[attempt]
    require(len(content) == size and digest(content) == expected, attempt + " archive digest/size mismatch")
    result = zipfile.ZipFile(io.BytesIO(content))
    names = result.namelist()
    require(len(names) == len(set(names)), "Duplicate ZIP member")
    for name in names:
        safe_relative(name)
    require(sum(member.file_size for member in result.infolist()) < 500_000_000, "Oversized archive")
    return result


def json_member(archive_file, name):
    return json.loads(archive_file.read(name))


def unique_member(archive_file, suffix):
    names = [name for name in archive_file.namelist() if name.endswith(suffix)]
    require(len(names) == 1, "Expected one archive member: " + suffix)
    return names[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt-1-zip", type=Path, required=True)
    parser.add_argument("--attempt-2-zip", type=Path, required=True)
    parser.add_argument("--attempt-2-job-log", type=Path,
                        help="Optional original complete job139902186688 log; verifies its omitted-file hash and excerpt")
    parser.add_argument("--output", type=Path, help="Explicit destination for the verification JSON; otherwise stdout")
    args = parser.parse_args()
    index = json.loads((ROOT / "evidence-index.json").read_text())
    archives = {"attempt-1": archive(args.attempt_1_zip, "attempt-1"),
                "attempt-2": archive(args.attempt_2_zip, "attempt-2")}
    copied = []
    for entry in index["copies"]:
        path = ROOT / safe_relative(entry["path"])
        content = path.read_bytes()
        require(len(content) == entry["bytes"] and digest(content) == entry["sha256"],
                "Packaged copy digest mismatch: " + entry["path"])
        origin = entry["origin"]
        if origin["kind"] == "artifact-member":
            require(content == archives[origin["attempt"]].read(origin["member"]),
                    "Packaged bytes differ from original ZIP member: " + entry["path"])
        copied.append({"path": entry["path"], "bytes": len(content), "sha256": digest(content),
                       "matchesCapturedOriginalSha256": True,
                       "matchesOriginalZipMember": origin["kind"] == "artifact-member"})

    selections = []
    for entry in index["selections"]:
        wrapper = json.loads((ROOT / safe_relative(entry["path"])).read_text())
        require(wrapper["kind"] == "selection; not the original complete record", "Unlabelled selection")
        if entry["origin"]["kind"] == "artifact-member":
            origin = entry["origin"]
            content = archives[origin["attempt"]].read(origin["member"])
            require(digest(content) == wrapper["originalSha256"] and len(content) == wrapper["originalBytes"],
                    "Selection original digest mismatch")
            original = json.loads(content)
            require(wrapper["selected"] == {key: value for key, value in original.items() if key != "inputs"},
                    "Selection differs from its original source record")
            require(wrapper["omittedInputRecords"] == len(original["inputs"]), "Omitted input count mismatch")
        else:
            # The full saved API response is intentionally omitted. Its captured digest is
            # retained, and these immutable run/head/job/artifact identifiers are checked.
            selected = wrapper["selected"]
            require(selected["run"]["id"] == 45817099578 and selected["run"]["head_sha"] == HEAD,
                    "Unexpected selected run/head")
            require(selected["run"]["run_attempt"] == entry["origin"]["attemptNumber"], "Attempt mismatch")
            require(selected["observedCommit"] == {"sha": HEAD, "tree": TREE}, "Commit/tree mismatch")
        selections.append({"path": entry["path"], "originalBytes": wrapper["originalBytes"],
                           "originalSha256": wrapper["originalSha256"],
                           "completeOriginalReverifiedFromZip": entry["origin"]["kind"] == "artifact-member"})

    first, second = archives["attempt-1"], archives["attempt-2"]
    first_build = json_member(first, "artifacts/debug-build.json")
    require(first_build["exitCode"] == 1 and "Received status code 429" in first_build["output"],
            "First attempt does not prove Maven HTTP429")
    require((ROOT / "attempt-1/gradle-failure.txt").read_text() == first_build["output"],
            "Decoded first-attempt error differs from original artifact")
    require(not any(name.endswith(".apk") for name in first.namelist()), "Unexpected first-attempt APK")

    sources = json_member(second, "artifacts/sources.json")
    checkout = json_member(second, "artifacts/source-checkout.json")
    candidate_bytes = second.read("artifacts/candidate.json")
    candidate = json.loads(candidate_bytes)
    for source in [sources, checkout, json_member(first, "artifacts/source-checkout.json")]:
        require(source["sourceMode"] == "current-checkout" and source["portCommit"] == source["desktopCommit"] == HEAD,
                "Current-checkout binding mismatch")
        require(source["gitTree"] == TREE, "Git tree mismatch")
        require(source["nativeAcceptance"] is False and source["productionRelease"] is False,
                "Unexpected acceptance claim")
    require(sources["inputSetSha256"] == checkout["inputSetSha256"], "Source input set mismatch")
    require(digest(candidate_bytes) == sources["candidateManifestSha256"], "Candidate manifest digest mismatch")
    require(sources["generatedCatalogsVerified"] is True, "Catalog verification absent")
    require(sources["componentSuite"] == "system-records" and sources["systemProviderOnly"] is True,
            "Not provider-only evidence")
    require(sources["runtimeApi"] == 34 and sources["systemImage"] == "google_apis", "Runtime scope mismatch")
    require(sources["googleAcceptance"] is False and sources["componentOnly"] is True, "Acceptance scope mismatch")
    require(candidate["stale"] is False and candidate["apkAssetsVerified"] is True, "Unverified candidate")
    require(candidate["signing"] == "debug only" and candidate["instrumentationTestOnly"] is True,
            "Unexpected signing/instrumentation scope")
    apk_report = []
    for name_key, hash_key, bound_key in [("name", "sha256", "apkSha256"),
                                         ("testApk", "testApkSha256", "testApkSha256")]:
        name = candidate[name_key]
        require(PurePosixPath(name).name == name and name.endswith(".apk"), "Unsafe APK filename")
        data = second.read("artifacts/" + name)
        require(digest(data) == candidate[hash_key] == sources[bound_key], "APK digest mismatch")
        apk_report.append({"name": name, "bytes": len(data), "sha256": digest(data)})
    with zipfile.ZipFile(io.BytesIO(second.read("artifacts/" + candidate["name"]))) as app:
        packed_projection = app.read("assets/projection.json")
    require(digest(packed_projection) == sources["projectionManifestSha256"], "Packaged projection digest mismatch")
    web = json_member(second, "artifacts/web-test-proof.json")
    stage_member = unique_member(second, "/system-records.json")
    provider_member = unique_member(second, "/system-records-receipt.json")
    stage = json_member(second, stage_member)
    provider = json_member(second, provider_member)
    require(json.loads(packed_projection)["sourceHash"] == sources["projectionSourceHash"] ==
            candidate["sourceHash"] == web["sourceHash"] == stage["sourceHash"] == PROJECTION,
            "Projection source hashes differ")

    junit = []
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for name in sorted(second.namelist()):
        if not (name.startswith("app/build/test-results/testDebugUnitTest/TEST-") and name.endswith(".xml")):
            continue
        data = second.read(name)
        suite = ET.fromstring(data)
        require(suite.tag == "testsuite", "Unexpected JUnit XML root")
        counts = {key: int(suite.attrib.get(key, "0")) for key in totals}
        require(counts["tests"] == len(suite.findall("testcase")), "JUnit testcase count mismatch")
        require(counts["failures"] == len(suite.findall("testcase/failure")) and
                counts["errors"] == len(suite.findall("testcase/error")) and
                counts["skipped"] == len(suite.findall("testcase/skipped")), "JUnit outcome count mismatch")
        copied_path = ROOT / "attempt-2/junit" / PurePosixPath(name).name
        require(copied_path.read_bytes() == data, "Packaged XML differs from original artifact")
        for key in totals:
            totals[key] += counts[key]
        junit.append({"artifactMember": name, "path": str(copied_path.relative_to(ROOT)),
                      "class": suite.attrib["name"], "bytes": len(data), "sha256": digest(data), **counts})
    require(len(junit) == 42 and totals == {"tests": 303, "failures": 0, "errors": 0, "skipped": 0},
            "Unexpected JUnit total")
    require(candidate["unitTests"] == totals["tests"], "Candidate JUnit count mismatch")

    require(provider["passed"] is False and stage["passed"] is False and stage["sdk"] == provider["sdk"] == 34,
            "Unexpected native outcome")
    require("NativeSystemProviderSmoke.kt:185" in stage["error"] and
            "Provider must replace the original recurring slot, not duplicate it" in stage["error"],
            "Native assertion differs")
    require((ROOT / "attempt-2/native-error.txt").read_text() == stage["error"], "Native error stack differs")
    permissions = provider["productPermissionChecks"]
    require(len(permissions) == 16 and all(row["dropShellPermissionIdentityCompleted"] is True and
            not row["fixtureScopeActive"] and not row["writeContacts"] and not row["writeCalendar"]
            for row in permissions), "Product call carried fixture WRITE permissions")
    require(provider["cleanup"] == {"requestedRawRows": 2, "requestedCalendars": 2,
            "remainingOwnedRawRows": 0, "remainingOwnedCalendars": 0,
            "shellIdentityDropped": True, "writePermissionsDenied": True}, "Cleanup proof differs")
    require(len(provider["checks"]) == 9 and provider["checks"][-1].startswith("owned fixture IDs removed"),
            "Expected eight domain groups plus cleanup")
    require(not any(row["operation"].startswith("cancelled-") for row in permissions),
            "Unexpected claim of executed cancellation checks")
    require(provider["contactsSourceIsolationTested"] is False and provider["calendarSourceIsolationTested"] is True,
            "Source-isolation scope differs")

    full_log = index["omittedAttempt2JobLog"]
    log_verified = False
    if args.attempt_2_job_log:
        data = args.attempt_2_job_log.read_bytes()
        require(len(data) == full_log["bytes"] and digest(data) == full_log["sha256"], "Original joblog digest mismatch")
        require((ROOT / "attempt-2/native-failure.log").read_bytes() in data, "Native excerpt is not a verbatim log substring")
        log_verified = True
    report = {
        "schema": 1, "verifierSha256": digest(Path(__file__).read_bytes()),
        "runId": 45817099578, "headSha": HEAD, "gitTree": TREE, "projectionSourceHash": PROJECTION,
        "archives": {key: {"bytes": size, "sha256": checksum} for key, (size, checksum) in EXPECTED_ARCHIVES.items()},
        "attempt1": {"conclusion": "failure", "phase": "Gradle configuration", "httpStatus": 429, "apkPresent": False},
        "attempt2": {"conclusion": "failure", "buildGate": "success", "failedStep": 13,
                     "failureKind": "native smoke assertion", "actualSeriesCountRecorded": False,
                     "fixtureVersusProductCauseResolved": False, "providerSuitePassed": False},
        "apkSourceBindingVerified": True, "candidateManifestDigestVerified": True,
        "packagedProjectionManifestDigestVerified": True, "apks": apk_report,
        "sourceInputSetSha256": sources["inputSetSha256"],
        "junit": {"reportCount": len(junit), "xmlBytes": sum(row["bytes"] for row in junit), **totals, "reports": junit},
        "provider": {"completedDomainGroups": 8, "cleanupPassed": True, "productCallsWithoutWrite": 16,
                     "cleanup": provider["cleanup"], "cancellationChecksExecuted": False,
                     "contactsSourceIsolationTested": False, "calendarSourceIsolationTested": True,
                     "nativeAcceptance": False, "productionRelease": False},
        "copies": copied, "selections": selections,
        "omittedAttempt2JobLog": {**full_log, "completeOriginalReverified": log_verified},
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
        print(json.dumps({"output": str(args.output), "sha256": digest(text.encode()),
                          "copiedFilesVerified": len(copied), "junit": totals,
                          "apkSourceBindingVerified": True, "providerSuitePassed": False}))
    else:
        print(text, end="")
    for archive_file in archives.values():
        archive_file.close()


if __name__ == "__main__":
    main()
