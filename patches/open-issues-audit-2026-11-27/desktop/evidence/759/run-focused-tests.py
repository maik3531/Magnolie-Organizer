#!/usr/bin/env python3
"""Run only the four affected Windows media UI programs; no native build/run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--checkout", type=Path, required=True)
parser.add_argument("--tools", type=Path, required=True, help="Existing tool directory containing js/node_modules/jsdom")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--node", default=shutil.which("node") or "node")
args = parser.parse_args()
checkout, output = args.checkout.resolve(), args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, NODE_PATH=str(args.tools.resolve() / "js/node_modules"),
           MAGNOLIE_TEST_SOURCE_ROOT=str(checkout))
tests = ["phone-media-wait-ui.js", "phone-media-recovery-mount-ui.js",
         "phone-media-ui.js", "phone-media-source-choice-ui.js"]
def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()
def git(*arguments):
    return subprocess.check_output(["git", "-C", str(checkout), *arguments], text=True).strip()
results = []
for name in tests:
    relative = Path("magnolie-organizer-windows/tests") / name
    command = [args.node, str(relative)]
    result = subprocess.run(command, cwd=checkout, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log = output / (name + ".log")
    log.write_text(result.stdout)
    results.append({"test": str(relative), "test_sha256": sha(checkout / relative),
                    "command": command, "exit_code": result.returncode,
                    "log": log.name, "log_sha256": sha(log)})
    print(f"{name}: exit {result.returncode}\n{result.stdout}", flush=True)
inputs = ["magnolie-organizer-windows/app/web/phone-media.js",
          "magnolie-organizer-windows/app/web/index.html",
          "magnolie-organizer-windows/app/web/anwendung.js",
          "magnolie-organizer-windows/app/web/i18n.js",
          "magnolie-organizer-windows/app/web/i18n/de.js"]
manifest = {"source_head": git("rev-parse", "HEAD"), "source_tree": git("rev-parse", "HEAD^{tree}"),
            "worktree_status": git("status", "--short"),
            "node_version": subprocess.check_output([args.node, "--version"], text=True).strip(),
            "environment": "Actual UI modules in JSDOM; no installed Windows/Notes or native transfer test",
            "build_executed_by_runner": False, "build_exit_code": None,
            "inputs": {name: sha(checkout / name) for name in inputs}, "results": results,
            "passed_programs": sum(result["exit_code"] == 0 for result in results), "programs": len(results)}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
sys.exit(0 if all(result["exit_code"] == 0 for result in results) else 1)
