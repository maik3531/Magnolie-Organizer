#!/usr/bin/env python3
"""Run existing regression groups for the #566/#823 audit patch.
Baseline: --phase before --reuse-python-log after the documented red Python run.
Patched: --phase after. No native GUI or release-package acceptance is implied.
"""
import argparse, hashlib, json, os, re, subprocess, time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--checkout", required=True, type=Path)
parser.add_argument("--tools", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--phase", required=True, choices=("before", "after"))
parser.add_argument("--reuse-python-log", action="store_true")
parser.add_argument("--base-commit", default="3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f")
args = parser.parse_args()
root, prepared, out = args.checkout.resolve(), args.tools.resolve(), args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
Path("/tmp/opencode").mkdir(parents=True, exist_ok=True)
python = prepared / "python/bin/python"
dotnet = prepared / "dotnet/dotnet"
windows = root / "magnolie-organizer-windows"
env_values = {
    "TZ": "Europe/Berlin",
    "MAGNOLIE_TEST_SOURCE_ROOT": str(root),
    "DOTNET_CLI_HOME": str(prepared / "dotnet-state"),
    "NUGET_PACKAGES": str(prepared / "nuget"),
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
}
env = dict(os.environ, **env_values)
tests = [
    "magnolie-organizer/pruefungen/test_lotus_task_csv.py",
    "magnolie-organizer/pruefungen/test_lotus_csv_contact_fields.py",
    "magnolie-organizer/pruefungen/test_restore_identity.py",
]
if args.phase == "after":
    tests += [
        "magnolie-organizer/pruefungen/test_save_restore_boundary.py",
        "magnolie-organizer/pruefungen/test_restore_commit_result.py",
        "magnolie-organizer/pruefungen/test_backup_profile_validation.py",
    ]
paths = tests + [
    "magnolie-organizer/bin/magnolie-organizer",
    "magnolie-organizer-windows/ExchangeCodec.cs",
    "magnolie-organizer-windows/RestoreSelection.cs",
    "magnolie-organizer-windows/tests/Program.cs",
    "magnolie-organizer-windows/tests/LotusCsvContactFieldTests.cs",
    "magnolie-organizer-windows/tests/RestoreSelectionIdentityTests.cs",
    "magnolie-organizer-windows/tests/CoreTests.csproj",
    "magnolie-organizer-windows/tests/packages.lock.json",
    "contracts/lotus-csv-contact-fields.json",
    "contracts/restore-additive-identity-vectors.json",
]
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def git(*values):
    return subprocess.check_output(["git", *values], cwd=root).decode().strip()
manifest = {
    "base_commit": args.base_commit,
    "phase": args.phase, "head": git("rev-parse", "HEAD"),
    "status_before": git("status", "--porcelain"),
    "inputs": {p: sha(root / p) for p in paths},
    "environment": env_values, "runs": [],
    "scope": "Actual Python and .NET 8 C# sources on Linux; synthetic fixtures only; no native Windows UI, provider, device or release-package acceptance.",
}
def run(name, command, cwd, expected_groups=None):
    command = list(map(str, command))
    log = out / (name + ".log")
    started = time.monotonic()
    with log.open("wb") as output:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=output,
                                stderr=subprocess.STDOUT, timeout=300)
    content = log.read_text()
    row = {"name": name, "command": command, "cwd": str(cwd),
           "exit_code": result.returncode, "seconds": round(time.monotonic()-started,3),
           "log": log.name, "sha256": sha(log)}
    if expected_groups is not None:
        match = re.search(r"CoreTests: (\d+)/(\d+) Gruppen bestanden", content)
        row["passed_groups"] = int(match[1]) if match else None
        row["total_groups"] = int(match[2]) if match else None
        row["expected_groups"] = expected_groups
    manifest["runs"].append(row)
    print(json.dumps(row), flush=True)
    return result.returncode

if args.reuse_python_log:
    assert args.phase == "before"
    content = (out / "python.log").read_text()
    assert "7 failed, 110 passed" in content
    manifest["runs"].append({
        "name":"python", "command":[str(python), "-m", "pytest", "-q", *tests],
        "cwd": str(root), "exit_code":1, "log":"python.log",
        "sha256":sha(out/"python.log"),
        "captured_before_runner":True,
    })
else:
    run("python", [python, "-m", "pytest", "-q", *tests], root)
content = (out/"python.log").read_text()
manifest["python_counts"] = {kind:int(n) for n,kind in re.findall(r"(\d+) (passed|failed|skipped|errors?)", content)}
build = run("core-build", [dotnet, "build", "tests/CoreTests.csproj", "--nologo",
            "--verbosity", "quiet", "-p:RestoreLockedMode=true"], windows)
if build == 0:
    dll = windows / "tests/bin/Debug/net8.0/CoreTests.dll"
    manifest["assembly_sha256"] = sha(dll)
    filters = [("csv", "CSV", 2), ("restore-identity", "Additive restore", 1)]
    if args.phase == "after":
        filters += [("recovery-journal", "Wiederherstellungsjournal", 1),
                    ("exchange", "ICS / VCF / LDIF / Claws / Lotus / Thunderbird", 1),
                    ("import-file", "Import file / native readers", 1)]
    for name, value, count in filters:
        run(name, [dotnet, dll, value], windows, count)
manifest["inputs_unchanged"] = all(sha(root/p)==value for p,value in manifest["inputs"].items())
manifest["status_after"] = git("status", "--porcelain")
manifest["passed"] = all(row["exit_code"] == 0 and row.get("passed_groups",0) == row.get("expected_groups",0) for row in manifest["runs"])
(out/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
assert manifest["inputs_unchanged"], "A bound input changed during validation"
raise SystemExit(0 if manifest["passed"] else 1)

