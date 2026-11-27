#!/usr/bin/env python3
"""Refs #785: the unchanged Swift Process bridge and the actual signed app helper.

Run after build_dev.py on a native Mac. This creates no application profile,
does not change or re-sign the app, and never falls back to a system Python.
"""
import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time

import candidate_sources


BETA = Path(__file__).resolve().parents[1]
REPO = BETA.parent
PROCESS_SOURCE = BETA / "Sources/MacBeta/FileImportProcess.swift"
PROBE_SOURCE = BETA / "tools/native_file_import_probe.swift"
CONTRACT = REPO / "contracts/or6-native-fixtures.json"
MAXIMUM_INPUT_BYTES = 32 * 1024 * 1024
HOSTILE_KEYS = ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP",
                "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__", "PYTHONTZPATH")
EXPECTED_CHECKS = {"selectedRegularFileRead", "originalSwiftProcessWithBundledRuntime",
                   "knownOR6FieldsPreserved", "hostileParentPythonEnvironment",
                   "structuredHelperErrorRejected", "selectedSymlinkRejected",
                   "emptySelectedFileRejected", "oversizedSelectedFileRejected",
                   "selectedFixtureUnchanged"}
SCOPE_FLAGS = ("pickerExercised", "editorExercised", "profileSaveExercised",
               "systemPermissionsExercised", "nativeAcceptance", "productionRelease")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Required regular proof/build file is missing or linked: " + path.name)
    return path


def stop_group(process):
    # start_new_session gives this driver an exclusively owned process group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def bounded_run(arguments, *, cwd, environment, seconds=30, maximum_bytes=1024 * 1024):
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([str(value) for value in arguments], cwd=cwd, env=environment,
            stdin=subprocess.DEVNULL, stdout=output, stderr=errors, start_new_session=True)
        deadline = time.monotonic() + seconds
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Native probe command exceeded its deadline: " + Path(arguments[0]).name)
                if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > maximum_bytes:
                    raise RuntimeError("Native probe command exceeded its output bound: " + Path(arguments[0]).name)
                time.sleep(0.05)
            if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > maximum_bytes:
                raise RuntimeError("Native probe command exceeded its output bound: " + Path(arguments[0]).name)
            output.seek(0); errors.seek(0)
            stdout, stderr = output.read(maximum_bytes + 1), errors.read(maximum_bytes + 1)
            if process.returncode:
                detail = stderr.decode("utf-8", errors="replace")[-4096:]
                raise RuntimeError("Native probe command failed: " + Path(arguments[0]).name + ": " + detail)
            # A successful probe must leave no live helper behind. Cleanup on
            # this branch is also limited to the process group owned above.
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return stdout
            raise RuntimeError("Native probe command left a descendant process running.")
        finally:
            stop_group(process)


def source_bindings(proof):
    sources = [PROCESS_SOURCE, PROBE_SOURCE, Path(__file__).resolve(), CONTRACT,
               BETA / "Package.swift", BETA / "tools/import_python_main.c",
               BETA / "ImportHelper/helper.py", BETA / "Resources/ImportPython.json"]
    sources += sorted((BETA / "Sources/BetaCore").rglob("*.swift"))
    bindings = {}
    for path in sources:
        relative = str(path.relative_to(REPO))
        actual = digest(regular(path))
        if proof["sourceFiles"].get(relative, {}).get("sha256") != actual:
            raise ValueError("Native probe source is not bound to the candidate: " + relative)
        bindings[relative] = actual
    return bindings


def package_bindings(app, sources, architecture):
    contents = app / "Contents"
    paths = {
        "buildManifest": contents / "Resources/Magnolie Organizer macOS Beta-build.json",
        "runtimeManifest": contents / "Resources/ImportPython/runtime.json",
        "helperManifest": contents / "Resources/ImportHelper/manifest.json",
        "helperSource": contents / "Resources/ImportHelper/helper.py",
        "interpreter": contents / "Helpers/ImportPython.app/Contents/MacOS/python3.15",
        "helperCodeResources": contents / "Helpers/ImportPython.app/Contents/_CodeSignature/CodeResources",
        "outerCodeResources": contents / "_CodeSignature/CodeResources",
        "appExecutable": contents / "MacOS/Magnolie Organizer macOS Beta",
    }
    hashes = {name: digest(regular(path)) for name, path in paths.items()}
    build = json.loads(paths["buildManifest"].read_text())
    if (build.get("configuration") != "debug" or build.get("architecture") != architecture
            or build.get("minimumSystemVersion") != "12.7" or build.get("swiftTestsPassed") is not True):
        raise ValueError("The selected app is not the matching checked native debug build.")
    compiled = [str(PROCESS_SOURCE.relative_to(REPO)), str((BETA / "Package.swift").relative_to(REPO))]
    compiled += [name for name in sources if name.startswith("Magnolie-Organizer-macOS-Beta/Sources/BetaCore/")]
    if any(build.get("sourceInputs", {}).get(name) != sources[name] for name in compiled):
        raise ValueError("The app build and linked Swift sources have different source bindings.")
    pin = json.loads((BETA / "Resources/ImportPython.json").read_text())
    runtime = json.loads(paths["runtimeManifest"].read_text())
    if (runtime.get("schema") != 2 or runtime.get("architecture") != architecture or runtime.get("pin") != pin
            or runtime.get("files", {}).get("Contents/MacOS/python3.15") != hashes["interpreter"]
            or runtime.get("launcher", {}).get("sourceSHA256") != sources["Magnolie-Organizer-macOS-Beta/tools/import_python_main.c"]):
        raise ValueError("The actual app interpreter is not bound to the reviewed runtime.")
    manifest = json.loads(paths["helperManifest"].read_text())
    if (manifest.get("maximumInputBytes") != MAXIMUM_INPUT_BYTES
            or "Europe/Berlin" not in manifest.get("timezones", [])
            or "Magnolie-Probe/Unavailable" in manifest.get("timezones", [])
            or hashes["helperSource"] != sources["Magnolie-Organizer-macOS-Beta/ImportHelper/helper.py"]
            or manifest.get("generated", {}).get("helper.py", {}).get("sha256") != hashes["helperSource"]):
        raise ValueError("The actual app parser helper or fixture context differs.")
    return hashes


def object_bindings(binaries):
    directory = binaries / "BetaCore.build"
    mapping_path = regular(directory / "output-file-map.json")
    mapping = json.loads(mapping_path.read_text())
    expected_sources = {path.resolve() for path in (BETA / "Sources/BetaCore").rglob("*.swift")}
    mapped_sources, objects = set(), set()
    for name, outputs in mapping.items():
        if not name:
            continue
        source = Path(name)
        source = (source if source.is_absolute() else BETA / source).resolve()
        if source not in expected_sources or "object" not in outputs:
            raise ValueError("Unexpected BetaCore object-map source.")
        obj = Path(outputs["object"])
        obj = (obj if obj.is_absolute() else BETA / obj).resolve()
        if obj.parent != directory or obj.suffix != ".o":
            raise ValueError("BetaCore object escaped its actual build directory.")
        regular(obj); mapped_sources.add(source); objects.add(obj)
    if mapped_sources != expected_sources or len(objects) != len(expected_sources):
        raise ValueError("The BetaCore object map does not cover the exact current sources.")
    actual_objects = set(directory.glob("*.o"))
    if actual_objects - objects - {directory / "BetaCore.swiftmodule.o"} or not objects <= actual_objects:
        raise ValueError("Unexpected or missing BetaCore object files.")
    module = regular(binaries / "Modules/BetaCore.swiftmodule")
    objects = sorted(actual_objects)
    proof = {str(path.relative_to(binaries)): digest(regular(path)) for path in objects}
    proof[str(mapping_path.relative_to(binaries))] = digest(mapping_path)
    proof[str(module.relative_to(binaries))] = digest(module)
    return objects, proof


def prepare_fixture(directory):
    contract = json.loads(CONTRACT.read_text())
    entry = contract["files"]["known-values.or6"]
    count = entry["bytes"]
    if type(count) is not int or not 65536 < count <= MAXIMUM_INPUT_BYTES:
        raise ValueError("The selected original OR6 fixture has an unexpected size.")
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(entry["gzip_base64"], validate=True))) as stream:
        data = stream.read(count + 1)
    if len(data) != count or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("The original OR6 fixture identity differs.")
    (directory / "known-values.or6").write_bytes(data)
    (directory / "selected-symlink.or6").symlink_to(directory / "known-values.or6")
    (directory / "empty.or6").write_bytes(b"")
    with (directory / "oversized.or6").open("xb") as stream:
        stream.truncate(MAXIMUM_INPUT_BYTES + 1)
    expected = {"bytes": count, "sourceSHA256": entry["sha256"], "expected": contract["expected"]}
    (directory / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, sort_keys=True) + "\n")
    for path in directory.iterdir():
        if not path.is_symlink():
            path.chmod(0o600)
    return {"contract": str(CONTRACT.relative_to(REPO)), "contractSHA256": digest(CONTRACT),
            "name": "known-values.or6", "bytes": count, "sha256": entry["sha256"],
            "expectedFields": sum(len(fields) for fields in contract["expected"].values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--expected-commit", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "x86_64"}:
        raise RuntimeError("Native ARM64 or Intel macOS is required; no simulated compile or system-Python fallback.")
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("Existing native process proof retained.")
    environment = dict(os.environ, MACOSX_DEPLOYMENT_TARGET="12.7")
    head = candidate_sources.git(REPO, "rev-parse", "HEAD").decode().strip()
    expected = args.expected_commit or head
    if not re.fullmatch(r"[0-9a-f]{40}", expected) or expected != head:
        raise ValueError("The native process probe requires the selected source commit.")
    source_proof_bytes = regular(args.sources).read_bytes()
    source_proof = json.loads(source_proof_bytes)
    candidate_sources.verify(REPO, expected, source_proof)
    sources = source_bindings(source_proof)
    app = args.bundle.resolve(strict=True)
    if not app.is_dir() or app.suffix != ".app":
        raise ValueError("An existing built application bundle is required.")
    if args.output.resolve().is_relative_to(app):
        raise ValueError("The native process proof must remain outside the signed app.")
    before = package_bindings(app, sources, platform.machine())
    with tempfile.TemporaryDirectory(prefix="magnolie-native-file-import-") as name:
        temporary = Path(name).resolve()  # Resolve our own /var alias, not selected fixture links.
        run = lambda command, **kw: bounded_run(command, cwd=BETA, environment=environment, **kw)
        run(["codesign", "--verify", "--strict", "--deep", app])
        binaries = Path(run(["swift", "build", "-c", "debug", "--show-bin-path"]).decode().strip()).resolve(strict=True)
        if not binaries.is_relative_to((BETA / ".build").resolve()):
            raise ValueError("The Swift build path is outside this checked package.")
        objects, linked = object_bindings(binaries)
        sdk = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).decode().strip()
        executable = temporary / "native-file-import-probe"
        run(["xcrun", "--sdk", "macosx", "swiftc", "-parse-as-library", "-swift-version", "5",
             "-target", platform.machine() + "-apple-macosx12.7", "-sdk", sdk,
             "-module-name", "NativeFileImportProcessProbe", "-I", binaries / "Modules",
             PROCESS_SOURCE, PROBE_SOURCE, *objects, "-o", executable], seconds=120)
        if run(["lipo", "-archs", executable]).decode().split() != [platform.machine()]:
            raise ValueError("The compiled process probe has the wrong architecture.")
        fixture_directory = temporary / "fixtures"; fixture_directory.mkdir(mode=0o700)
        fixture = prepare_fixture(fixture_directory)
        streams = temporary / "streams"; streams.mkdir(mode=0o700)
        hostile = dict(environment, TMPDIR=str(streams) + "/")
        hostile.update({key: str(temporary / "not-a-python-grant") for key in HOSTILE_KEYS})
        raw = bounded_run([executable, app, fixture_directory], cwd=temporary,
                          environment=hostile, seconds=150, maximum_bytes=65536)
        observed = json.loads(raw)
        checks = observed.get("checks", {})
        if (observed.get("ok") is not True or set(checks) != EXPECTED_CHECKS or any(value is not True for value in checks.values())
                or observed.get("sourceSHA256") != fixture["sha256"]
                or observed.get("knownFieldsVerified") != fixture["expectedFields"]
                or observed.get("knownCollectionsVerified") != 4
                or any(observed.get(flag) is not False for flag in SCOPE_FLAGS)):
            raise ValueError("The actual native process proof is incomplete or differs from the original fixture.")
        if list(streams.glob("magnolie-import-*")):
            raise ValueError("The native process left a named plaintext input stream behind.")
        run(["codesign", "--verify", "--strict", "--deep", app])
        if package_bindings(app, sources, platform.machine()) != before or object_bindings(binaries)[1] != linked:
            raise ValueError("The app or linked BetaCore inputs changed during the process probe.")
        candidate_sources.verify(REPO, expected, source_proof)
        if args.sources.read_bytes() != source_proof_bytes:
            raise ValueError("The candidate source proof changed during the native process probe.")
        proof = {
            "schema": 1, "kind": "native-swift-file-import-process", "passed": True,
            "observedAtUTC": datetime.now(timezone.utc).isoformat(), "sourceSHA": expected,
            "architecture": platform.machine(), "configuration": "debug", "system": platform.system(),
            "sourceProofSHA256": hashlib.sha256(source_proof_bytes).hexdigest(), "sourceFiles": sources,
            "linkedBetaCoreFiles": linked, "linkedBetaCoreObjectCount": len(objects),
            "compiledProbeSHA256": digest(executable), "packageFiles": before,
            "originalFixture": fixture, "nativeObservations": observed,
            "appSignaturesVerifiedBeforeAndAfter": True, "appBytesBoundBeforeAndAfter": True,
            "namedPlaintextStreamRetained": False, "processDeadlineSeconds": 150,
            "sourceUnchangedBeforeAndAfter": True,
            "scope": "Unmodified FileImportProcess.swift linked with the checked native BetaCore build; real signed app interpreter/helper; original public OR6 fixture and bounded rejection cases.",
            "pickerExercised": False, "editorExercised": False, "profileSaveExercised": False,
            "systemPermissionsExercised": False, "montereyRuntimeValidated": False,
            "nativeAcceptance": False, "productionRelease": False,
        }
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print("Native Swift-to-bundled-import process: 9 checks passed; 4 original OR6 collections; no UI/profile acceptance.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print("Native file import process probe blocked: " + str(error), file=sys.stderr)
        sys.exit(1)
