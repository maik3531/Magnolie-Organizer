#!/usr/bin/env python3
"""Test live projected editor records; optionally feed the same records to actual Swift core tests."""
import argparse
import json
import os
import re
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
from project_ui import BETA, inputs, inventory, project


def technical_swift_tail(output):
    lines = []
    for line in output.splitlines():
        match = re.search(r"Test (?:Case|Suite) '[A-Za-z0-9_. +\[\]-]+' (?:started|passed|failed)(?: \([0-9.]+ seconds\))?", line)
        if match:
            lines.append(match.group())
        phase = re.search(r'Native print phase: (?:starting|fixture|loading|layout|appkit-print|appkit-returned|unknown)\b', line)
        if phase:
            lines.append(phase.group())
    return '\n'.join(lines[-24:])[-4096:]


def run_swift(command, env):
    # The outer host collection has an unchanged 300-second budget. Keep
    # bounded cleanup of this exact Swift process group inside that budget.
    with tempfile.TemporaryFile(mode='w+b') as output:
        child = subprocess.Popen(command, cwd=BETA, env=env, stdout=output,
                                 stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            code = child.wait(timeout=270)
        except subprocess.TimeoutExpired as timeout:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)  # Session/group created above; never a name lookup.
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                # Still signal the created group after its leader exits: an
                # owned WebKit/test grandchild must not survive an early TERM.
            output.flush(); output.seek(0, os.SEEK_END)
            output.seek(max(0,output.tell()-65536))
            print('SWIFT_TEST_TIMEOUT_TECHNICAL\n'+technical_swift_tail(output.read(65536).decode('utf-8',errors='replace')), flush=True)
            raise subprocess.TimeoutExpired(command, 270) from timeout
        output.seek(0)
        print(output.read().decode('utf-8',errors='replace'), end='', flush=True)
        if code:
            raise subprocess.CalledProcessError(code, command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--js-runtime", required=True)
    parser.add_argument("--swift")
    parser.add_argument("--probe", action="store_true", help="Report original behavior without reminder assertions")
    args = parser.parse_args()
    snapshot = inputs()
    with tempfile.TemporaryDirectory(prefix="macOS-Beta-editor-") as temp:
        root = Path(temp)
        project(snapshot, root / "UI")
        command = [args.js_runtime]
        if Path(args.js_runtime).name == "deno":
            command += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
        command += ["tests/editor_regressions.mjs", str(root / "UI")]
        if args.probe:
            command += ["--probe"]
        result = subprocess.run(command, cwd=BETA, capture_output=True, text=True, timeout=120)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.returncode:
            raise SystemExit(result.returncode)
        records = json.loads(result.stdout)
        fixture = root / "editor-records.json"
        fixture.write_text(json.dumps(records) + "\n")
        summary = {"appointments": len(records["cases"]), "tasks": len(records["tasks"])}
        summary.update({"earlyOnlyCallbacks": records["earlyOnlyCallbacks"]} if args.probe else {"checks": records["checks"]})
        print("Actual current editor: " + json.dumps(summary), flush=True)
        if args.swift:
            env = dict(os.environ, MACOS_BETA_EDITOR_FIXTURES=str(fixture), MACOS_BETA_UI_PATH=str(root / "UI"))
            run_swift([args.swift, "test", "--scratch-path", str(root / "swift-build"), "--jobs", "2"], env)
        if inventory(inputs()) != inventory(snapshot):
            raise RuntimeError("Desktop sources changed during the editor tests; rerun against current sources.")


if __name__ == "__main__":
    main()
