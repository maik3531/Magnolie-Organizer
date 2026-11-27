#!/usr/bin/env python3
"""Verify this evidence package and replay without modifying the caller's index."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--repo", required=True, type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())
for line in (root / "SHA256SUMS").read_text().splitlines():
    expected, name = line.split("  ", 1)
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name

with tempfile.TemporaryDirectory(prefix="magnolie-128-replay-") as temporary:
    env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"))
    def git(*arguments):
        result = subprocess.run(["git", "-C", str(args.repo), *arguments], env=env, check=True, capture_output=True)
        return result.stdout.decode().strip()
    patch = str(root / manifest["patch"])
    git("read-tree", manifest["basis"])
    assert git("write-tree") == manifest["basis_tree"]
    git("apply", "--cached", "--check", patch)
    git("apply", "--cached", patch)
    after = git("write-tree")
    assert after == manifest["result_tree"], after
    git("apply", "--cached", "--reverse", "--check", patch)
    git("apply", "--cached", "--reverse", patch)
    before = git("write-tree")
    assert before == manifest["basis_tree"], before
print(json.dumps({"checksums": "passed", "forward_tree": after, "reverse_tree": before}, indent=2))
