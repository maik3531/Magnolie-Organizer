#!/usr/bin/env python3
"""Exercise actual projected calendar import/normalizer/save flow using synthetic native payloads."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from project_ui import BETA, inputs, inventory, project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--js-runtime", required=True)
    args = parser.parse_args()
    snapshot = inputs()
    with tempfile.TemporaryDirectory(prefix="macOS-Beta-system-calendar-") as temporary:
        root = Path(temporary) / "UI"
        project(snapshot, root)
        command = [args.js_runtime]
        if Path(args.js_runtime).name == "deno":
            command += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
        command += ["tests/system_calendar_import.mjs", str(root)]
        subprocess.run(command, cwd=BETA, check=True, timeout=120)
    if inventory(inputs()) != inventory(snapshot):
        raise RuntimeError("Sources changed during calendar-import checks; rerun against current sources.")


if __name__ == "__main__":
    main()
