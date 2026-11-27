#!/usr/bin/env python3
"""Verify the prepared review series against a later audited main checkout.

This operates on disposable Git indexes and runtime-only web copies. The
provided --current worktree must already hold the complete patch in its index.
No branch is moved and no product installation or GitHub mutation occurs.
"""
import argparse
import datetime
import difflib
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("current", "base", "previous", "patches", "node", "node-path", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    for name in ("current", "base", "previous", "patches", "node", "node_path", "output"):
        setattr(args, name, getattr(args, name).resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.patches / "manifest.json").read_text())
    combined = args.patches / manifest["combined_patch"]["path"]
    assert sha(combined) == manifest["combined_patch"]["sha256"]
    assert all(sha(args.patches / part["path"]) == part["sha256"] for part in manifest["series"])
    commands = []

    def git(repo, *parts, env=None, binary=False):
        command = ["git", "-C", str(repo), *map(str, parts)]
        completed = subprocess.run(command, env=env, capture_output=True, check=True)
        commands.append({"argv": command, "index": (env or {}).get("GIT_INDEX_FILE"), "exit_code": completed.returncode})
        return completed.stdout if binary else completed.stdout.decode().strip()

    base_commit = git(args.base, "rev-parse", "HEAD")
    assert base_commit == "f8ad956ec4c9a71cd4d857c3218177c481407c85"
    assert git(args.current, "rev-parse", "HEAD") == base_commit
    assert not git(args.base, "status", "--porcelain")
    assert not git(args.previous, "status", "--porcelain")
    # A reviewer can reconstruct the historical tree with the published patch;
    # their own commit need not reproduce the original author/time metadata.
    previous_actual_commit = git(args.previous, "rev-parse", "HEAD")
    assert git(args.previous, "rev-parse", "HEAD^{tree}") == manifest["result_tree"]
    assert not git(args.current, "diff", "--name-only")
    base_tree = git(args.current, "rev-parse", "HEAD^{tree}")
    result_tree = git(args.current, "write-tree")
    replay = []
    with tempfile.TemporaryDirectory(prefix="review-index-") as temp:
        for mode in ("combined", "series"):
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / mode))
            git(args.current, "read-tree", "HEAD", env=env)
            patches = [combined] if mode == "combined" else [args.patches / part["path"] for part in manifest["series"]]
            for patch in patches:
                git(args.current, "apply", "--cached", "--check", patch, env=env)
                git(args.current, "apply", "--cached", patch, env=env)
            applied = git(args.current, "write-tree", env=env)
            assert applied == result_tree
            for patch in reversed(patches):
                git(args.current, "apply", "--cached", "--reverse", "--check", patch, env=env)
                git(args.current, "apply", "--cached", "--reverse", patch, env=env)
            restored = git(args.current, "write-tree", env=env)
            assert restored == base_tree
            replay.append({"mode": mode, "patches": len(patches), "result_tree": applied, "restored_tree": restored, "passed": True})

    def tree(repo, revision):
        result = {}
        for row in git(repo, "ls-tree", "-r", "-z", revision, binary=True).decode().split("\0"):
            if row:
                meta, path = row.split("\t", 1)
                mode, kind, oid = meta.split()
                result[path] = [mode, kind, oid]
        return result

    old_tree = tree(args.previous, "HEAD")
    new_tree = tree(args.current, result_tree)
    old_base_tree = tree(args.previous, manifest["base_commit"])
    new_base_tree = tree(args.base, base_commit)
    all_paths = sorted(set(old_tree) | set(new_tree))
    changed = [path for path in all_paths if old_tree.get(path) != new_tree.get(path)]
    upstream_changed = [path for path in sorted(set(old_base_tree) | set(new_base_tree)) if old_base_tree.get(path) != new_base_tree.get(path)]
    assert changed == upstream_changed
    expected = {"ARBEITSSTAND.md", "magnolie-organizer/web/anwendung.js", "magnolie-organizer-windows/app/web/anwendung.js", "magnolie-organizer-windows/tests/mcp-import-review.js"}
    assert set(changed) == expected

    def delta(a, b):
        a = a.splitlines(keepends=True)
        b = b.splitlines(keepends=True)
        return [(tag, a[i:j], b[k:l]) for tag, i, j, k, l in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal"]

    deltas = []
    patches = []
    for path in changed:
        old = git(args.previous, "show", "HEAD:" + path, binary=True).decode()
        new = (args.current / path).read_text()
        old_base = git(args.previous, "show", manifest["base_commit"] + ":" + path, binary=True).decode()
        new_base = (args.base / path).read_text()
        assert delta(old, new) == delta(old_base, new_base), path
        deltas.append({"path": path, "old_blob": old_tree[path], "new_blob": new_tree[path], "exact_upstream_delta_preserved": True})
        patches.extend(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile="f3ea/" + path, tofile="f8-plus-series/" + path))
    diff_path = args.output / "only-preserved-upstream.diff"
    diff_path.write_text("".join(patches))
    fresh_patch = args.output / "all-after-f8ad956e.patch"
    fresh_patch.write_bytes(git(args.current, "diff", "--cached", "--binary", "--full-index", binary=True))
    with tempfile.TemporaryDirectory(prefix="review-refreshed-index-") as temp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / "index"))
        git(args.current, "read-tree", "HEAD", env=env)
        git(args.current, "apply", "--cached", fresh_patch, env=env)
        assert git(args.current, "write-tree", env=env) == result_tree
        git(args.current, "apply", "--cached", "--reverse", fresh_patch, env=env)
        assert git(args.current, "write-tree", env=env) == base_tree

    runtime_files = ["index.html", "i18n.js", "zeichenblatt.js", "appearance.js", "normative-timezones.js", "anwendung.js", "mcp-protocol.js"]
    runs = []
    prior_file = args.output / "replay-and-tests.json"
    prior = json.loads(prior_file.read_text()) if prior_file.exists() else {}
    if prior and not prior.get("passed"):
        setup = args.output / "initial-setup"
        setup.mkdir(exist_ok=True)
        shutil.copy2(prior_file, setup / prior_file.name)
        for row in prior.get("runs", []):
            if row["exit_code"]:
                shutil.copy2(args.output / row["log"], setup / row["log"])
    with tempfile.TemporaryDirectory(prefix="review-web-") as temp:
        for edition, web in [("windows", "magnolie-organizer-windows/app/web"), ("linux", "magnolie-organizer/web")]:
            overlay = Path(temp) / edition
            overlay.mkdir()
            inputs = []
            for name in runtime_files:
                source = args.current / web / name
                if name == "appearance.js" and not source.exists():
                    continue
                generated = not source.exists() and name == "normative-timezones.js"
                if generated:
                    source = args.previous / web / name
                assert source.is_file(), source
                shutil.copy2(source, overlay / name)
                assert sha(source) == sha(overlay / name)
                inputs.append({"path": web + "/" + name, "sha256": sha(source), "from_previous_generated_asset": generated})
            env = dict(os.environ, NODE_PATH=str(args.node_path), MAGNOLIE_WEB=str(overlay))
            for name in ("mcp-import-review.js", "calendar-colour-remainders.js"):
                program = args.current / "magnolie-organizer-windows/tests" / name
                previous_run = next((row for row in prior.get("runs", []) if row["edition"] == edition and row["program"] == str(program.relative_to(args.current)) and row["exit_code"] == 0), None)
                if previous_run and prior.get("result_tree") == result_tree and previous_run["program_sha256"] == sha(program) and previous_run["inputs"] == inputs and sha(args.output / previous_run["log"]) == previous_run["log_sha256"]:
                    runs.append(dict(previous_run, reused_unchanged_success=True))
                    continue
                command = [str(args.node), str(program)]
                started = time.monotonic()
                result = subprocess.run(command, env=env, cwd=args.current / "magnolie-organizer-windows", text=True, capture_output=True, timeout=90)
                elapsed = round(time.monotonic() - started, 3)
                log = args.output / (edition + "-" + name + ".log")
                log.write_text(result.stdout + result.stderr)
                row = {"edition": edition, "program": str(program.relative_to(args.current)), "program_sha256": sha(program), "argv": command, "exit_code": result.returncode, "seconds": elapsed, "log": log.name, "log_sha256": sha(log), "inputs": inputs}
                runs.append(row)
                print(json.dumps({key: row[key] for key in ("edition", "program", "exit_code", "seconds")}), flush=True)
    # The alias runner deliberately uses both canonical roots and its own codec
    # harness. Supply only its missing generated asset in each disposable root.
    generated = []
    generated_inputs = []
    try:
        for web in ("magnolie-organizer-windows/app/web", "magnolie-organizer/web"):
            target = args.current / web / "normative-timezones.js"
            source = args.previous / web / "normative-timezones.js"
            if not target.exists():
                shutil.copy2(source, target)
                generated.append(target)
            assert sha(target) == sha(source)
            generated_inputs.append({"path": web + "/normative-timezones.js", "sha256": sha(target), "from_previous_generated_asset": True})
        program = args.current / "magnolie-organizer-windows/tests/legacy-android-instance-ui.js"
        command = [str(args.node), str(program)]
        previous_run = next((row for row in prior.get("runs", []) if row["edition"] == "both" and row["program"] == str(program.relative_to(args.current)) and row["exit_code"] == 0), None)
        if previous_run and prior.get("result_tree") == result_tree and previous_run["program_sha256"] == sha(program) and previous_run["inputs"] == generated_inputs and sha(args.output / previous_run["log"]) == previous_run["log_sha256"]:
            row = dict(previous_run, reused_unchanged_success=True)
        else:
            env = dict(os.environ, NODE_PATH=str(args.node_path), PYTHONDONTWRITEBYTECODE="1")
            started = time.monotonic()
            completed = subprocess.run(command, env=env, cwd=args.current / "magnolie-organizer-windows", text=True, capture_output=True, timeout=90)
            log = args.output / "both-legacy-android-instance-ui.js.log"
            log.write_text(completed.stdout + completed.stderr)
            row = {"edition": "both", "program": str(program.relative_to(args.current)), "program_sha256": sha(program), "argv": command, "exit_code": completed.returncode, "seconds": round(time.monotonic() - started, 3), "log": log.name, "log_sha256": sha(log), "inputs": generated_inputs}
        runs.append(row)
        print(json.dumps({key: row[key] for key in ("edition", "program", "exit_code", "seconds")}), flush=True)
    finally:
        for target in generated:
            target.unlink()
    assert git(args.current, "write-tree") == result_tree
    assert not git(args.current, "diff", "--name-only")
    result = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "previous_base": manifest["base_commit"], "previous_tested_head": manifest["head"], "previous_actual_commit": previous_actual_commit,
        "current_base": base_commit, "base_tree": base_tree, "result_tree": result_tree,
        "original_combined_patch": {"name": combined.name, "sha256": sha(combined), "bytes": combined.stat().st_size},
        "fresh_combined_patch": {"name": fresh_patch.name, "sha256": sha(fresh_patch), "bytes": fresh_patch.stat().st_size},
        "tracked_paths_compared": len(all_paths), "unchanged_tracked_paths": len(all_paths) - len(changed),
        "differences_from_previous_tested_tree": deltas, "preserved_upstream_diff": {"path": diff_path.name, "sha256": sha(diff_path)},
        "replay": replay, "commands": commands,
        "node_version": subprocess.check_output([str(args.node), "--version"], text=True).strip(),
        "jsdom_version": json.loads((args.node_path / "jsdom/package.json").read_text())["version"],
        "runs": runs, "passed": all(row["exit_code"] == 0 for row in runs),
        "boundary": "Targeted Node/JSDOM regression only. No new C#/Python/native/package/device/internet acceptance. All other source tree blobs equal the previously tested integration. Existing f8 #846 normalizers and stronger test remain intact; earlier alias guard is defensive redundancy, not a replacement.",
    }
    (args.output / "replay-and-tests.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    assert result["passed"], "Targeted regression failed; inspect preserved logs"


if __name__ == "__main__":
    main()
