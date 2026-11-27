#!/usr/bin/env python3
"""Narrow compatibility proof for the prepared ten-part review on 1a578534."""
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

OLD = "f8ad956ec4c9a71cd4d857c3218177c481407c85"
NEW = "1a578534d4136cbee07ff2040324a5528a5cebd5"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "old-combined", "nine-patches", "notes-patch", "assets", "node", "node-path", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    for key, value in vars(args).items():
        setattr(args, key, value.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    commands = []

    def git(*parts, env=None, raw=False):
        command = ["git", "-C", str(args.repo), *map(str, parts)]
        result = subprocess.run(command, env=env, capture_output=True, check=True)
        commands.append({"argv": command, "temporary_index": bool((env or {}).get("GIT_INDEX_FILE")), "exit_code": result.returncode})
        return result.stdout if raw else result.stdout.decode().strip()

    assert git("rev-parse", "HEAD") == NEW
    assert not git("diff", "--name-only")
    git("diff", "--check", "--cached")
    base_tree, result_tree = git("rev-parse", "HEAD^{tree}"), git("write-tree")
    manifest = json.loads((args.nine_patches / "manifest.json").read_text())
    series = [args.nine_patches / item["path"] for item in manifest["series"]] + [args.notes_patch]
    for item in manifest["series"]:
        assert sha(args.nine_patches / item["path"]) == item["sha256"]
    assert sha(args.old_combined) == "52985a9c4d2e5a1e6b328cb1116503db7c3984f8671ce00f07d24a04483a5e68"
    replay = []
    with tempfile.TemporaryDirectory(prefix="latest-review-index-") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "previous"))
        git("read-tree", OLD, env=env)
        git("apply", "--cached", args.old_combined, env=env)
        previous_tree = git("write-tree", env=env)
        assert previous_tree == "3b5b94fd3256b01a3a775f39bfdae4d661f9d6b8"
        for mode, parts in (("combined", [args.old_combined]), ("nine_plus_notes", series)):
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / mode))
            git("read-tree", NEW, env=env)
            for part in parts:
                git("apply", "--cached", "--check", part, env=env)
                git("apply", "--cached", part, env=env)
            forward = git("write-tree", env=env)
            assert forward == result_tree
            for part in reversed(parts):
                git("apply", "--cached", "--reverse", "--check", part, env=env)
                git("apply", "--cached", "--reverse", part, env=env)
            reverse = git("write-tree", env=env)
            assert reverse == base_tree
            replay.append({"mode": mode, "parts": len(parts), "forward_tree": forward, "reverse_tree": reverse, "passed": True})

    def tree(revision):
        values = {}
        for row in git("ls-tree", "-rz", revision, raw=True).decode().split("\0"):
            if row:
                meta, path = row.split("\t", 1)
                values[path] = meta.split()
        return values

    old, new, old_base, new_base = map(tree, (previous_tree, result_tree, OLD, NEW))
    paths = sorted(set(old) | set(new))
    changed = [path for path in paths if old.get(path) != new.get(path)]
    upstream = [path for path in sorted(set(old_base) | set(new_base)) if old_base.get(path) != new_base.get(path)]
    assert changed == upstream and len(changed) == 8

    def diff_segments(left, right):
        left, right = left.splitlines(keepends=True), right.splitlines(keepends=True)
        return [(tag, left[a:b], right[c:d]) for tag, a, b, c, d in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes() if tag != "equal"]

    differences, delta = [], []
    for path in changed:
        before, after, original_before, original_after = [git("show", value + ":" + path, raw=True).decode() for value in (previous_tree, result_tree, OLD, NEW)]
        assert diff_segments(before, after) == diff_segments(original_before, original_after), path
        differences.append({"path": path, "old_blob": old[path], "new_blob": new[path], "exact_upstream_delta_preserved": True})
        delta.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="f8-plus-review/" + path, tofile="1a-plus-review/" + path))
    delta_path = args.output / "preserved-upstream.diff"
    delta_path.write_text("".join(delta))
    patch = args.output / "complete-review-after-1a578534.patch"
    patch.write_bytes(git("diff", "--cached", "--binary", "--full-index", raw=True))
    with tempfile.TemporaryDirectory(prefix="latest-fresh-index-") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        git("read-tree", NEW, env=env)
        git("apply", "--cached", patch, env=env)
        assert git("write-tree", env=env) == result_tree
        git("apply", "--cached", "--reverse", patch, env=env)
        assert git("write-tree", env=env) == base_tree

    generated = args.repo / "magnolie-organizer/web/normative-timezones.js"
    original = args.assets / "magnolie-organizer/web/normative-timezones.js"
    added = not generated.exists()
    try:
        if added:
            shutil.copy2(original, generated)
        assert sha(generated) == sha(original)
        program = args.repo / "magnolie-organizer/pruefungen/media-source-choice-ui.cjs"
        input_paths = [program, generated] + [args.repo / "magnolie-organizer/web" / name for name in ("index.html", "i18n.js", "zeichenblatt.js", "anwendung.js")]
        inputs = [{"path": str(path.relative_to(args.repo)), "sha256": sha(path)} for path in input_paths]
        command = [str(args.node), str(program)]
        environment = dict(os.environ, NODE_PATH=str(args.node_path))
        started = time.monotonic()
        process = subprocess.run(command, cwd=args.repo, env=environment, text=True, capture_output=True, timeout=60)
        elapsed = round(time.monotonic() - started, 3)
        log = args.output / "linux-media-source-choice-ui.log"
        log.write_text(process.stdout + process.stderr)
        runtime = {"argv": command, "exit_code": process.returncode, "seconds": elapsed, "log": log.name, "log_sha256": sha(log), "inputs": inputs, "node_version": subprocess.check_output([str(args.node), "--version"], text=True).strip(), "jsdom_version": json.loads((args.node_path / "jsdom/package.json").read_text())["version"]}
        print(process.stdout + process.stderr, flush=True)
    finally:
        if added:
            generated.unlink()
    assert git("write-tree") == result_tree
    assert not git("diff", "--name-only")
    result = {"date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "previous_base": OLD, "current_base": NEW, "base_tree": base_tree, "previous_result_tree": previous_tree, "result_tree": result_tree, "tracked_paths_compared": len(paths), "unchanged_tracked_paths": len(paths) - len(changed), "differences": differences, "replay": replay, "patch": {"name": patch.name, "sha256": sha(patch), "bytes": patch.stat().st_size}, "preserved_upstream_diff": {"name": delta_path.name, "sha256": sha(delta_path)}, "runtime": runtime, "commands": commands, "passed": runtime["exit_code"] == 0, "upstream_native_846": {"status": "closed; complete standalone Windows source-archive gate passed upstream", "source": "https://github.com/maik3531/Magnolie-Organizer/issues/846#issuecomment-7227651086", "workflow": "https://github.com/maik3531/Magnolie-Organizer/actions/runs/46058642735", "executed_here": False}, "limits": "One focused Linux media DOM program executed. No new broad suite, native archive build, device test, installed package, real Internet proof, merge, or release. All eight changes from the prior prepared review are exactly preserved upstream edits; all other blobs and modes match the previously proven integration."}
    (args.output / "compatibility.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    assert result["passed"]


if __name__ == "__main__":
    main()
