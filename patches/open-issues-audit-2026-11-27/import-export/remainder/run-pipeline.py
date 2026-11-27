#!/usr/bin/env python3
"""Synthetic actual codec → desktop save → native disk reopen → export pipeline.

No installation, native GUI, provider account or device is used. Builds are
explicitly recorded; --skip-core-build reuses an already verified assembly.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


parser = argparse.ArgumentParser()
parser.add_argument("--checkout", type=Path, required=True)
parser.add_argument("--tools", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--skip-core-build", action="store_true")
args = parser.parse_args()
root, tools, output = args.checkout.resolve(), args.tools.resolve(), args.output.resolve()
here = Path(__file__).resolve().parent
output.mkdir(parents=True, exist_ok=True)
dotnet = tools / "dotnet/dotnet"
python = tools / "python/bin/python"
windows = root / "magnolie-organizer-windows"
assembly = windows / "tests/bin/Debug/net8.0/CoreTests.dll"
contract = root / "contracts/calendar-color-remainders.json"
vectors = json.loads(contract.read_text())
environment = dict(os.environ, DOTNET_CLI_HOME=str(tools / "dotnet-state"),
    NUGET_PACKAGES=str(tools / "nuget"), DOTNET_CLI_TELEMETRY_OPTOUT="1",
    DOTNET_GENERATE_ASPNET_CERTIFICATE="false", TZ="Europe/Berlin",
    MAGNOLIE_TEST_SOURCE_ROOT=str(root), NODE_PATH=str(tools / "js/node_modules"),
    PYTHONDONTWRITEBYTECODE="1")
manifest = {"checkout": str(root), "head_at_execution": subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "commands": [],
    "build_executed_by_runner": not args.skip_core_build, "build_exit_code": None,
    "boundary": "Actual synthetic codecs, real native disk writers/readers and JSDOM frontends; no native GUI, package or provider-device acceptance."}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(label, command, cwd=root, extra=None):
    log = output / (label + ".log")
    with log.open("w") as stream:
        result = subprocess.run([str(value) for value in command], cwd=cwd,
            env={**environment, **(extra or {})}, stdout=stream, stderr=subprocess.STDOUT)
    manifest["commands"].append({"label": label, "command": [str(value) for value in command],
        "cwd": str(cwd), "exit_code": result.returncode, "log": log.name, "log_sha256": sha(log)})
    print(label, "exit", result.returncode, flush=True)
    if result.returncode:
        raise RuntimeError(label + " failed; see " + str(log))


try:
    if not args.skip_core_build:
        run("core-build", [dotnet, "build", "tests/CoreTests.csproj", "--nologo", "--verbosity", "quiet", "-p:RestoreLockedMode=true"], windows)
        manifest["build_exit_code"] = 0
    manifest["assembly_sha256"] = sha(assembly)
    run("probe-build", [dotnet, "build", here / "codec-runner/CalendarCodecProbe.csproj", "--nologo", "--verbosity", "quiet"])
    probe = here / "codec-runner/bin/Debug/net8.0/CalendarCodecProbe.dll"
    manifest["probe_assembly_sha256"] = sha(probe)
    results = []
    for runtime in ("python", "csharp"):
        imported = output / (runtime + "-import.json")
        if runtime == "python":
            run(runtime + "-import", [python, here / "calendar-book-probe.py", "--checkout", root, "--input", contract, "--output", imported])
        else:
            run(runtime + "-import", [dotnet, probe, assembly, contract, imported, "import"])
        ui = output / (runtime + "-ui")
        run(runtime + "-ui", ["node", windows / "tests/calendar-colour-remainders.js"], extra={
            "MAGNOLIE_COLOR_NATIVE_INPUT": str(imported), "MAGNOLIE_COLOR_UI_OUTPUT": str(ui)})
        for edition in ("linux", "windows"):
            exported = output / (runtime + "-" + edition + "-stored-export.json")
            data = ui / (edition + ".json")
            if runtime == "python":
                run(runtime + "-" + edition + "-stored-export", [python, here / "calendar-book-probe.py", "--checkout", root,
                    "--input", data, "--output", exported, "--mode", "store-export"])
            else:
                run(runtime + "-" + edition + "-stored-export", [dotnet, probe, assembly, data, exported, "store-export"])
            for vector, actual in zip(vectors, json.loads(exported.read_text()), strict=True):
                assert actual["id"] == vector["id"]
                section = vector["section"]
                payload = actual["exports"][section]["reimport"]
                entry = payload[section][0]
                assert actual["storage"]["book_reopened_equal"]
                assert entry.get("akzentFarbe", "") == vector["expected_accent"], (runtime, edition, vector["id"], "accent")
                if section == "jahrestage":
                    assert not payload["termine"]
                    assert entry["datum"] == vector["expected_date"]
                    assert entry["typ"] == vector["expected_type"]
                if vector["preserve_line"]:
                    assert vector["preserve_line"] in actual["exports"][section]["text"].splitlines()
                results.append({"runtime": runtime, "edition": edition, "id": vector["id"], "passed": True})
    manifest["results"] = results
    manifest["passed"] = len(results)
    manifest["source_hashes"] = {name: sha(root / name) for name in [
        "magnolie-organizer/bin/magnolie-organizer", "magnolie-organizer/web/anwendung.js",
        "magnolie-organizer-windows/ExchangeCodec.cs", "magnolie-organizer-windows/AtomicStore.cs",
        "magnolie-organizer-windows/app/web/anwendung.js", "contracts/calendar-color-remainders.json",
        "magnolie-organizer-windows/tests/calendar-colour-remainders.js"]}
except Exception as error:
    manifest["error"] = str(error)
    if manifest["build_executed_by_runner"] and manifest["build_exit_code"] is None:
        builds = [entry for entry in manifest["commands"] if entry["label"] == "core-build"]
        if builds:
            manifest["build_exit_code"] = builds[-1]["exit_code"]
    raise
finally:
    (output / "pipeline-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
