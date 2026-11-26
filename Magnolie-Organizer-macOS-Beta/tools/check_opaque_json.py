#!/usr/bin/env python3
"""Extract actual projected Unicode JSON inputs; optionally execute the native guards."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from check_editor import run_swift
from project_ui import BETA, inputs, inventory, project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--js-runtime", required=True)
    parser.add_argument("--swift", help="Run the actual native Swift tests; omission means UI-only evidence")
    args = parser.parse_args()
    snapshot = inputs()
    with tempfile.TemporaryDirectory(prefix="macOS-Beta-opaque-json-") as temporary:
        root = Path(temporary)
        project(snapshot, root / "UI")
        command = [args.js_runtime]
        if Path(args.js_runtime).name == "deno":
            command += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-write=" + str(root), "--allow-env", "--allow-sys"]
        fixture = root / "projected-opaque-json.json"
        subprocess.run(command + ["tests/opaque_json_keys.mjs", str(root / "UI"), str(fixture)],
                       cwd=BETA, check=True, timeout=120)
        if args.swift:
            env = dict(os.environ, MACOS_BETA_OPAQUE_JSON_FIXTURE=str(fixture))
            run_swift([args.swift, "test", "--scratch-path", str(root / "swift-build"), "--jobs", "2",
                       "--filter", "DocumentOpaqueIdentityTests"], env)
    if inventory(inputs()) != inventory(snapshot):
        raise RuntimeError("Canonical/projection inputs changed during the Unicode JSON boundary check.")


if __name__ == "__main__":
    main()
