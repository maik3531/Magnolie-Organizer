#!/usr/bin/env python3
"""Refs #783: current shared UI fixes with the existing Mac capability boundary."""
import argparse
import json
import re
from pathlib import Path
import subprocess
import tempfile

from project_ui import BETA, commands, digest, inputs, inventory, project
from project_import_helper import canonical_temporary_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--js-runtime", required=True)
    args = parser.parse_args()
    snapshot = inputs()
    app = snapshot["magnolie-organizer/web/anwendung.js"].decode()
    windows = snapshot["magnolie-organizer-windows/BridgeDispatcherContract.cs"].decode()
    desktop = set(re.findall(r'\bcmd\s*:\s*["\']([a-z][a-z0-9_]+)["\']', app))
    desktop.update(re.findall(r'\["([a-z][a-z0-9_]+)"\]\s*=\s*S\(', windows))
    native = set(commands(snapshot))
    with tempfile.TemporaryDirectory(prefix="macOS-current-source-") as temporary:
        root = canonical_temporary_root(temporary)
        project(snapshot, root / "UI")
        contract = root / "contract.json"
        contract.write_text(json.dumps({"allowed": sorted(native), "unavailable": sorted(desktop - native)}))
        runtime = [args.js_runtime]
        if Path(args.js_runtime).name == "deno":
            runtime += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
        subprocess.run(runtime + [str(BETA / "tests/current_source_contract.mjs"), str(root / "UI"), str(contract)],
                       cwd=BETA, check=True, timeout=120)
    if inventory(inputs()) != inventory(snapshot):
        raise RuntimeError("Source inputs changed during the current-source check.")
    print("Current canonical frontend SHA-256: " + digest(app.encode()) + "; native execution not performed.")


if __name__ == "__main__":
    main()
