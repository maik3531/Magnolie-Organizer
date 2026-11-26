#!/usr/bin/env python3
"""Refs #779: actual desktop JSON paths followed by the projected Mac reimport."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from project_ui import REPO, inputs, inventory, project
from project_import_helper import canonical_temporary_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--js-runtime", required=True)
    args = parser.parse_args()
    snapshot = inputs()
    with tempfile.TemporaryDirectory(prefix="macOS-Beta-reminder-desktop-") as temporary:
        target = canonical_temporary_root(temporary) / "UI"
        project(snapshot, target)
        environment = dict(os.environ, MACOS_BETA_REVIEW_UI=str(target))
        command = [args.js_runtime]
        if Path(args.js_runtime).name == "deno":
            command += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
        command += [str(REPO / "magnolie-organizer-windows/tests/native-reminder-provenance.js")]
        subprocess.run(command, cwd=REPO, env=environment, check=True, timeout=120)
    if inventory(inputs()) != inventory(snapshot):
        raise RuntimeError("Source inputs changed during the desktop/Mac roundtrip check.")


if __name__ == "__main__":
    main()
