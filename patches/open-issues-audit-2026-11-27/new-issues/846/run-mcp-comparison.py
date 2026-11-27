#!/usr/bin/env python3
"""Run the unchanged MCP review program against two read-only checkouts."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "final", "node", "node-path", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sources = [("baseline", args.baseline.resolve()), ("final", args.final.resolve())]
    program = "magnolie-organizer-windows/tests/mcp-import-review.js"
    harness = "magnolie-organizer-windows/tests/desktop-state-regressions.js"
    assert sha(sources[0][1] / program) == sha(sources[1][1] / program)
    assert sha(sources[0][1] / harness) == sha(sources[1][1] / harness)
    webroots = {"windows": "magnolie-organizer-windows/app/web", "linux": "magnolie-organizer/web"}
    runtime = subprocess.check_output([str(args.node), "--version"], text=True).strip()
    result = {"started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "node_version": runtime, "node_path": str(args.node_path.resolve()),
              "jsdom_version": json.loads((args.node_path / "jsdom/package.json").read_text())["version"],
              "bun_available_on_path": shutil.which("bun") is not None,
              "program_sha256": sha(sources[0][1] / program), "harness_sha256": sha(sources[0][1] / harness),
              "checkouts": [], "runs": []}
    for label, repo in sources:
        assert not git(repo, "status", "--porcelain"), str(repo)
        result["checkouts"].append({"label": label, "path": str(repo), "commit": git(repo, "rev-parse", "HEAD"),
                                    "clean_before": True})
    # Runtime-only copies avoid writing generated timezone assets into either checkout.
    # Every copied file is checked for byte identity with its recorded source.
    with tempfile.TemporaryDirectory(prefix="mcp-846-", dir=args.output) as temp:
        for label, repo in sources:
            for edition, relweb in webroots.items():
                original = repo / relweb
                overlay = Path(temp) / (label + "-" + edition)
                overlay.mkdir()
                files = []
                for name in ["index.html", "i18n.js", "zeichenblatt.js", "appearance.js",
                             "normative-timezones.js", "anwendung.js", "mcp-protocol.js"]:
                    source = original / name
                    if name == "appearance.js" and not source.exists():
                        continue
                    supplied_asset = name == "normative-timezones.js" and not source.exists()
                    if supplied_asset:
                        source = args.final.resolve() / relweb / name
                    assert source.is_file(), str(source)
                    destination = overlay / name
                    shutil.copy2(source, destination)
                    assert sha(source) == sha(destination)
                    files.append({"name": name, "source": str(source), "sha256": sha(source),
                                  "supplied_generated_asset": supplied_asset})
                env = dict(os.environ, NODE_PATH=str(args.node_path.resolve()), MAGNOLIE_WEB=str(overlay))
                argv = [str(args.node), str(repo / program)]
                start = time.monotonic()
                process = subprocess.run(argv, cwd=repo / "magnolie-organizer-windows", env=env,
                                         text=True, capture_output=True, timeout=45)
                elapsed = round(time.monotonic() - start, 3)
                log = args.output / (label + "-" + edition + ".log")
                log.write_text(process.stdout + process.stderr)
                result["runs"].append({"label": label, "edition": edition, "argv": argv,
                                       "cwd": str(repo / "magnolie-organizer-windows"),
                                       "env": {"NODE_PATH": env["NODE_PATH"], "MAGNOLIE_WEB": env["MAGNOLIE_WEB"]},
                                       "exit_code": process.returncode, "elapsed_s": elapsed,
                                       "log": log.name, "log_sha256": sha(log), "input_files": files,
                                       "operation_failed_at_reported_line": "operation_failed" in process.stderr and "mcp-import-review.js:221" in process.stderr,
                                       "program_pass": process.returncode == 0 and "MCP IMPORT REVIEW PASS:" in process.stdout})
                print(json.dumps({"label": label, "edition": edition, "exit_code": process.returncode,
                                  "elapsed_s": elapsed}), flush=True)
    for row, (_, repo) in zip(result["checkouts"], sources):
        row["clean_after"] = not git(repo, "status", "--porcelain")
        row["commit_after"] = git(repo, "rev-parse", "HEAD")
        assert row["clean_after"] and row["commit_after"] == row["commit"]
    (args.output / "execution-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
