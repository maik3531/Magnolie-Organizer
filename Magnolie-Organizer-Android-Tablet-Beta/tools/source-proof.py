#!/usr/bin/env python3
"""Bind a tablet candidate to unchanged inputs from its exact Git checkout (#790).

This records source provenance only. It grants no native acceptance or release.
Generated Linux catalogs are checked against the committed PO generator/inputs;
the existing projection and APK verifier retain their own stricter contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

TABLET = "Magnolie-Organizer-Android-Tablet-Beta"
REPO = Path(__file__).resolve().parents[2]
SCOPES = (
    TABLET, ".github/workflows/ports-2.0.30.yml",
    "magnolie-organizer/web", "magnolie-organizer/po",
    "magnolie-organizer/werkzeuge/po_zu_js.py",
    "magnolie-organizer-windows/app/web",
    "magnolie-organizer-windows/app/native-i18n.json",
    "magnolie-organizer-windows/tests/personal-custom-consent.js",
    "magnolie-organizer-windows/tests/setup-holidays.js",
    "port-adapters", "contracts", "LICENSE.md", "PROTECTED-ASSETS-LICENSE.txt",
    "magnolie-notes/gradlew", "magnolie-notes/gradle/wrapper",
    "magnolie-notes/gradle/libs.versions.toml",
    "magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/DatenDateiKrypto.kt",
    "magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/DateiDauerhaft.kt",
)
REQUIRED = (
    TABLET + "/tools/project-web.cjs",
    TABLET + "/app/build.gradle.kts",
    ".github/workflows/ports-2.0.30.yml",
    "magnolie-organizer/web/anwendung.js",
    "magnolie-notes/gradle/wrapper/gradle-wrapper.properties",
)
HEX64 = re.compile(r"[0-9a-f]{64}")
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 384 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args],
                                   stderr=subprocess.PIPE, timeout=30)


def safe_file(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or ".." in relative.parts or str(relative) != name:
        raise ValueError("Invalid source path: " + name)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink source is not accepted: " + name)
    if not current.is_file() or current.stat().st_size > MAX_FILE:
        raise ValueError("Missing or oversized source: " + name)
    return current


def snapshot(repo: Path, expected_commit: str) -> dict:
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected_commit) or head != expected_commit:
        raise ValueError("Checkout is not the expected current commit")
    # Includes staged changes and mode changes, not just worktree content.
    if git(repo, "diff", "--name-only", head, "--", *SCOPES).strip():
        raise ValueError("Tracked tablet build inputs differ from the checkout")
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "--", *SCOPES)
    if untracked.strip():
        raise ValueError("Uncommitted tablet build inputs are not accepted")
    entries = {}
    total = 0
    for item in git(repo, "ls-tree", "-r", "-z", head, "--", *SCOPES).split(b"\0"):
        if not item:
            continue
        meta, raw_name = item.split(b"\t", 1)
        mode, kind, blob = meta.decode("ascii").split()
        name = raw_name.decode("utf-8")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError("Unsupported Git source entry: " + name)
        data = safe_file(repo, name).read_bytes()
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError("Tablet source snapshot exceeds its bound")
        framed = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
        algorithm = hashlib.sha1 if len(blob) == 40 else hashlib.sha256
        if algorithm(framed).hexdigest() != blob:
            raise ValueError("Source bytes do not match their Git blob: " + name)
        entries[name] = dict(gitBlob=blob, mode=mode, bytes=len(data), sha256=digest(data))
    if any(name not in entries for name in REQUIRED):
        raise ValueError("Required tablet build inputs are missing from Git")
    if git(repo, "rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("Checkout changed while reading source inputs")
    entries = dict(sorted(entries.items()))
    return dict(schema=1, sourceMode="current-checkout", portCommit=head,
                desktopCommit=head, gitTree=git(repo, "rev-parse", head + "^{tree}").decode().strip(),
                inputs=entries, inputSetSha256=digest(encoded(entries)),
                nativeAcceptance=False, productionRelease=False)


def read_json(path: Path) -> dict:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate JSON key: " + key)
            obj[key] = value
        return obj
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def check_catalog(repo: Path, name: str, expected: str) -> None:
    match = re.fullmatch(r"magnolie-organizer/web/i18n/([A-Za-z_]+)\.js", name)
    if not match:
        raise ValueError("Uncommitted projection input is not a generated catalog: " + name)
    language = match.group(1)
    languages = safe_file(repo, "magnolie-organizer/po/LINGUAS").read_text().split()
    if language not in languages:
        raise ValueError("Generated catalog is not a committed language: " + language)
    generator = safe_file(repo, "magnolie-organizer/werkzeuge/po_zu_js.py")
    source = safe_file(repo, "magnolie-organizer/po/" + language + ".po")
    with tempfile.TemporaryDirectory(prefix="tablet-source-catalog-") as folder:
        output = Path(folder) / (language + ".js")
        subprocess.run([os.sys.executable, str(generator), language, str(source), str(output)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if not output.is_file() or digest(output.read_bytes()) != expected:
            raise ValueError("Generated catalog is not from the current PO input: " + name)


def bind(repo: Path, proof: dict, projection_path: Path, candidate_path: Path | None = None) -> dict:
    if proof.get("schema") != 1 or proof.get("sourceMode") != "current-checkout":
        raise ValueError("Unsupported or historical source proof")
    current = snapshot(repo, proof.get("portCommit", ""))
    if current != proof:
        raise ValueError("Source proof no longer matches this checkout")
    projection = read_json(projection_path)
    inputs = projection.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("Projection has no input hashes")
    if digest(encoded(inputs)) != projection.get("sourceHash"):
        raise ValueError("Projection source hash is inconsistent")
    for name, expected in inputs.items():
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ValueError("Invalid projection input hash")
        if digest(safe_file(repo, name).read_bytes()) != expected:
            raise ValueError("Projection uses changed source bytes: " + name)
        if name in current["inputs"]:
            if current["inputs"][name]["sha256"] != expected:
                raise ValueError("Projection is not from the checked-out source: " + name)
        else:
            check_catalog(repo, name, expected)
    projection_root = projection_path.parent.parent
    outputs = projection.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise ValueError("Projection has no output hashes")
    for name, expected in outputs.items():
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ValueError("Invalid projection output hash")
        if digest(safe_file(projection_root, name).read_bytes()) != expected:
            raise ValueError("Generated projection changed: " + name)
    result = dict(current, projectionSourceHash=projection["sourceHash"],
                  projectionManifestSha256=digest(projection_path.read_bytes()),
                  generatedCatalogsVerified=True)
    if candidate_path is not None:
        candidate = read_json(candidate_path)
        if candidate.get("stale") is not False or candidate.get("sourceHash") != projection["sourceHash"]:
            raise ValueError("APK candidate does not use this current projection")
        if candidate.get("apkAssetsVerified") is not True or candidate.get("instrumentationTestOnly") is not True:
            raise ValueError("Existing APK and instrumentation verification is required")
        for name_key, hash_key in (("name", "sha256"), ("testApk", "testApkSha256")):
            name = candidate.get(name_key, "")
            if "/" in name or "\\" in name or digest(safe_file(candidate_path.parent, name).read_bytes()) != candidate.get(hash_key):
                raise ValueError("Candidate bytes changed after verification")
        result.update(candidateManifestSha256=digest(candidate_path.read_bytes()),
                      apkSha256=candidate["sha256"], testApkSha256=candidate["testApkSha256"])
    # A concurrent edit at any point invalidates the complete proof.
    if snapshot(repo, current["portCommit"]) != current:
        raise ValueError("Source changed while binding the projection")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    sub = parser.add_subparsers(dest="action", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--expected-commit", required=True)
    capture.add_argument("--output", type=Path, required=True)
    finish = sub.add_parser("bind")
    finish.add_argument("--proof", type=Path, required=True)
    finish.add_argument("--projection", type=Path, required=True)
    finish.add_argument("--candidate", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        result = snapshot(repo, args.expected_commit) if args.action == "capture" else bind(
            repo, read_json(args.proof), args.projection, args.candidate)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Current-checkout tablet source proof: " + result["portCommit"])
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("Tablet source proof rejected: " + str(error), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
