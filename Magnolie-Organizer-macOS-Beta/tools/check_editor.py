#!/usr/bin/env python3
"""Test live projected editor records; optionally feed the same records to actual Swift core tests."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from project_ui import BETA, inputs, inventory, project


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
            subprocess.run([args.swift, "test", "--scratch-path", str(root / "swift-build"), "--jobs", "2"],
                           cwd=BETA, env=env, check=True, timeout=300)
        if inventory(inputs()) != inventory(snapshot):
            raise RuntimeError("Desktop sources changed during the editor tests; rerun against current sources.")


if __name__ == "__main__":
    main()
