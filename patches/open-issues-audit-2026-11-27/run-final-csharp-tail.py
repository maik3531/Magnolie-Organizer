#!/usr/bin/env python3
"""Rebuild and check the bounded #845 C# tail; reuse unchanged Python/UI proof.

Run beside the delivered evidence directories, for example:
  python3 run-final-csharp-tail.py --checkout /path/to/checkout \
    --tools /path/to/prepared-tools --output /path/to/fresh-evidence \
    --previous-head 32ff7d88af51c7e52275b3a0be348dae913c8598

The output directory must be empty and outside the source checkout. Existing
evidence is read only. This runner does not execute Python or DOM tests; the
separate 48-case codec/storage pipeline must use the newly built assembly.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ALLOWED_CHANGES = {
    "magnolie-organizer-windows/ExchangeCodec.cs",
    "magnolie-organizer-windows/tests/NextcloudIcsBirthdayTests.cs",
}
GROUPS = [
    ("csv", "CSV", 2),
    ("restore-identity", "Additive restore", 1),
    ("recovery-journal", "Wiederherstellungsjournal", 1),
    ("exchange", "ICS / VCF / LDIF / Claws / Lotus / Thunderbird", 1),
    ("import-file", "Import file / native readers", 1),
    ("record-export", "Record export / native codecs", 1),
    ("category-colors", "Category colors", 3),
    ("encoding", "UTF-16 import", 1),
    ("or6", "OR6 import / native fixtures", 1),
    ("or6-extension", "OR6 extension / original recurring", 1),
    ("thunderbird", "Thunderbird local.sqlite Schema 23", 1),
    ("nextcloud-birthday", "Nextcloud ICS birthdays", 1),
    ("nextcloud-dav", "Nextcloud CalDAV", 1),
    ("dav-etag", "DAV wildcard ETag", 1),
]
PREVIOUS_EVIDENCE = [
    ("validation/final-current/manifest.json", "inputs", "head", {"python"}),
    ("import-export/final-current/manifest.json", "inputs", "source_head",
     {"python-file-contract", "python-semantics"}),
    ("desktop/evidence/final-current/manifest.json", "source_inputs", "head", None),
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return digest(path.read_bytes())


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def git_text(root, *args):
    return git(root, *args).decode().strip()


def inspect_checkout(root, previous_ref):
    require(Path(git_text(root, "rev-parse", "--show-toplevel")).resolve() == root,
            "--checkout must name the repository/worktree root")
    status = git_text(root, "status", "--porcelain=v1", "--untracked-files=all")
    require(not status, "Source worktree must be clean, including untracked files: " + status)
    previous = git_text(root, "rev-parse", "--verify", previous_ref + "^{commit}")
    head = git_text(root, "rev-parse", "HEAD")
    require(subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                            previous, head], check=False).returncode == 0,
            "--previous-head must be an ancestor of HEAD")
    changes = git_text(root, "diff", "--name-status", "--no-renames", previous, head)
    rows = [line.split("\t") for line in changes.splitlines()]
    require(all(len(row) == 2 and row[0] == "M" for row in rows)
            and {row[1] for row in rows} == ALLOWED_CHANGES,
            "Expected only modifications to ExchangeCodec.cs and "
            "tests/NextcloudIcsBirthdayTests.cs; actual diff: " + changes)
    return {
        "head": head, "tree": git_text(root, "rev-parse", "HEAD^{tree}"),
        "previous_head": previous,
        "previous_tree": git_text(root, "rev-parse", previous + "^{tree}"),
        "status_before": status, "previous_is_ancestor": True,
        "allowed_changes": sorted(ALLOWED_CHANGES),
        "source_changes": [
            {"path": path, "status": status,
             "previous_sha256": digest(git(root, "show", previous + ":" + path)),
             "head_sha256": file_sha(root / path)}
            for status, path in rows
        ],
        "other_tracked_paths_unchanged": True,
    }


def bind_previous_evidence(root, here, previous):
    """Copy no old success claim for C#; verify the unchanged Python/UI subset."""
    bindings = []
    integration_path = here / "integration-final-current/manifest.json"
    integration = json.loads(integration_path.read_text())
    require(integration.get("head") == previous
            and integration.get("required_passed") is True
            and integration.get("tree") == git_text(root, "rev-parse", previous + "^{tree}"),
            "Previous integration evidence must be green and bound to --previous-head")
    for relative, input_key, head_key, selected_names in PREVIOUS_EVIDENCE:
        path = here / relative
        data = json.loads(path.read_text())
        require(data.get(head_key) == previous and data.get("passed") is True
                and data.get("inputs_unchanged") is True,
                "Previous evidence is not green on the requested head: " + relative)
        require(not data.get("status_after", data.get("worktree_status",
                    data.get("worktree_status_after", ""))),
                "Previous evidence records a dirty worktree: " + relative)
        refs = [row for row in integration["runs"] if row.get("manifest") == relative]
        require(len(refs) == 1 and refs[0].get("manifest_sha256") == file_sha(path),
                "Previous integration manifest does not bind this evidence: " + relative)
        inputs = data[input_key]
        selected_inputs = (inputs if selected_names is None else
                           {name: sha for name, sha in inputs.items()
                            if name.startswith(("magnolie-organizer/", "contracts/"))})
        require(bool(selected_inputs), "No reusable inputs in " + relative)
        for name, sha in selected_inputs.items():
            require(file_sha(root / name) == sha
                    and digest(git(root, "show", previous + ":" + name)) == sha,
                    "Previous/current input mismatch: " + name)
        assets = data.get("generated_assets", {})
        for name, sha in assets.items():
            require(file_sha(root / name) == sha, "Generated UI asset mismatch: " + name)
        runs = [row for row in data["runs"]
                if selected_names is None or row["name"] in selected_names]
        require(bool(runs) and (selected_names is None
                or {row["name"] for row in runs} == selected_names),
                "Expected prior test runs are missing: " + relative)
        logs = []
        for row in runs:
            log = path.parent / row["log"]
            require(row["exit_code"] == 0 and file_sha(log) == row["sha256"],
                    "Previous test log is missing, changed or failed: " + str(log))
            logs.append({"name": row["name"], "path": str(log.relative_to(here)),
                         "sha256": row["sha256"], "exit_code": 0,
                         **{key: row[key] for key in ("pytest_counts", "assertion_checks")
                            if key in row}})
        bindings.append({
            "manifest": relative, "manifest_sha256": file_sha(path),
            "source_head": previous, "reexecuted_by_this_runner": False,
            "inputs": selected_inputs, "generated_assets": assets,
            "all_selected_inputs_equal": True, "logs": logs,
            "python_counts": data.get("python_counts"),
            "excluded_csharp_manifest_inputs": sorted(set(inputs) - set(selected_inputs)),
            "boundary": ("Only the listed unchanged Python/UI results are reused. "
                         "Old C# assembly/results and the combined codec/storage pipeline "
                         "are not carried forward by this binding."),
        })
    return {
        "integration_manifest": "integration-final-current/manifest.json",
        "integration_manifest_sha256": file_sha(integration_path),
        "bindings": bindings,
    }


def build_input_paths(root):
    paths = git(root, "ls-files", "-z").decode().rstrip("\0").split("\0")
    return [name for name in paths if
            (name.startswith("magnolie-organizer-windows/")
             and (name.endswith((".cs", ".csproj", ".props", ".targets", ".json"))
                  or name.startswith(("magnolie-organizer-windows/tests/fixtures/",
                                      "magnolie-organizer-windows/tests/resources/"))))
            or name.startswith(("contracts/", "port-adapters/timezones/"))
            or (name.startswith("magnolie-notes/app/src/test/resources/notes-actor-")
                and name.endswith(".json"))
            or Path(name).name.lower() in {
                "global.json", "nuget.config", "directory.build.props", "directory.build.targets",
                "directory.packages.props", "directory.packages.targets"}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-head", required=True)
    args = parser.parse_args()
    root, tools, out = args.checkout.resolve(), args.tools.resolve(), args.output.resolve()
    here = Path(__file__).resolve().parent
    require(not out.is_relative_to(root), "Evidence output must be outside the source checkout")
    require(not out.exists() or (out.is_dir() and not any(out.iterdir())),
            "Use a fresh empty --output directory; existing evidence will not be overwritten")
    out.mkdir(parents=True, exist_ok=True)
    win = root / "magnolie-organizer-windows"
    dotnet = tools / "dotnet/dotnet"
    dll = win / "tests/bin/Debug/net8.0/CoreTests.dll"
    environment = {
        "TZ": "Europe/Berlin", "MAGNOLIE_TEST_SOURCE_ROOT": str(win),
        "DOTNET_CLI_HOME": str(tools / "dotnet-state"),
        "NUGET_PACKAGES": str(tools / "nuget"), "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
    }
    env = dict(os.environ, **environment)
    manifest = {
        "runner_sha256": file_sha(Path(__file__)), "checkout": str(root), "tools": str(tools),
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "environment": environment,
        "runs": [], "build_executed_by_runner": False, "build_exit_code": None,
        "expected_filters": len(GROUPS), "expected_groups": sum(row[2] for row in GROUPS),
        "passed": False, "python_or_dom_tests_executed_by_runner": False,
        "limits": ("Actual C# codecs/host tests with synthetic data on Linux. No installed "
                   "Windows UI, live DAV account, device, package or long-term acceptance. "
                   "The separate 48-case codec/save/reopen pipeline must use this new DLL."),
    }

    def save():
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    def run(name, command, expected=None, timeout=300):
        command = list(map(str, command))
        log = out / (name + ".log")
        started = time.monotonic()
        row = {"name": name, "command": command, "cwd": str(win),
               "exit_code": None, "log": log.name}
        try:
            with log.open("wb") as stream:
                result = subprocess.run(command, cwd=win, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=timeout)
            row["exit_code"] = result.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            row["error"] = type(error).__name__ + ": " + str(error)
        row.update(seconds=round(time.monotonic() - started, 3), sha256=file_sha(log))
        row["passed"] = row["exit_code"] == 0
        if expected is not None:
            content = log.read_text(errors="replace")
            headers = re.findall(r"^Magnolie CoreTests: (\d+) Gruppen\s*$", content, re.M)
            results = re.findall(r"^CoreTests: (\d+)/(\d+) Gruppen bestanden\.\s*$", content, re.M)
            row.update(expected_groups=expected,
                       selected_groups=int(headers[0]) if len(headers) == 1 else None,
                       passed_groups=int(results[0][0]) if len(results) == 1 else None,
                       total_groups=int(results[0][1]) if len(results) == 1 else None)
            row["group_count_matches"] = (expected > 0 and row["selected_groups"]
                == row["passed_groups"] == row["total_groups"] == expected)
            row["passed"] = row["passed"] and row["group_count_matches"]
        manifest["runs"].append(row)
        save()
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row

    try:
        manifest.update(inspect_checkout(root, args.previous_head))
        manifest["reused_python_ui_evidence"] = bind_previous_evidence(root, here, manifest["previous_head"])
        patch = git(root, "diff", "--binary", "--full-index", manifest["previous_head"], manifest["head"])
        (out / "source-changes.patch").write_bytes(patch)
        manifest["source_diff"] = {"path": "source-changes.patch", "sha256": digest(patch)}
        manifest["tracked_build_and_fixture_inputs"] = {
            name: file_sha(root / name) for name in build_input_paths(root)}
        require(dotnet.is_file(), "Prepared .NET SDK not found: " + str(dotnet))
        manifest["dotnet_version"] = subprocess.check_output(
            [str(dotnet), "--version"], cwd=win, env=env, text=True).strip()
        manifest["build_executed_by_runner"] = True
        build = run("core-build", [dotnet, "build", "tests/CoreTests.csproj", "--nologo",
                    "--verbosity", "quiet", "-t:Rebuild", "-p:RestoreLockedMode=true"], timeout=600)
        manifest["build_exit_code"] = build["exit_code"]
        require(build["passed"], "Fresh locked CoreTests build failed; inspect core-build.log")
        manifest["assembly_sha256"] = file_sha(dll)
        manifest["assembly_path"] = str(dll.relative_to(root))
        for name, term, count in GROUPS:
            run(name, [dotnet, dll, term], count)
        manifest["all_groups_completed"] = len(manifest["runs"]) == len(GROUPS) + 1
        manifest["passed_groups"] = sum(row.get("passed_groups") or 0 for row in manifest["runs"])
        manifest["test_runs_passed"] = (manifest["all_groups_completed"]
                                        and all(row["passed"] for row in manifest["runs"]))
    except Exception as error:
        manifest["error"] = type(error).__name__ + ": " + str(error)
        print(manifest["error"], file=sys.stderr, flush=True)
    finally:
        try:
            manifest["head_unchanged"] = git_text(root, "rev-parse", "HEAD") == manifest.get("head")
            manifest["tree_unchanged"] = git_text(root, "rev-parse", "HEAD^{tree}") == manifest.get("tree")
            manifest["status_after"] = git_text(root, "status", "--porcelain=v1", "--untracked-files=all")
            inputs = dict(manifest.get("tracked_build_and_fixture_inputs", {}))
            for binding in manifest.get("reused_python_ui_evidence", {}).get("bindings", []):
                inputs.update(binding["inputs"])
                inputs.update(binding["generated_assets"])
            manifest["inputs_unchanged"] = bool(inputs) and all(
                (root / name).is_file() and file_sha(root / name) == sha for name, sha in inputs.items())
            manifest["assembly_unchanged_during_tests"] = (dll.is_file()
                and file_sha(dll) == manifest.get("assembly_sha256"))
            manifest["passed"] = (not manifest.get("error") and manifest.get("test_runs_passed", False)
                and manifest["head_unchanged"] and manifest["tree_unchanged"]
                and not manifest["status_after"] and manifest["inputs_unchanged"]
                and manifest["assembly_unchanged_during_tests"])
        except Exception as error:
            manifest["final_binding_error"] = type(error).__name__ + ": " + str(error)
            manifest["passed"] = False
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({"manifest": str(out / "manifest.json"), "head": manifest.get("head"),
                      "passed": manifest["passed"], "passed_groups": manifest.get("passed_groups")}))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
