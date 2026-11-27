#!/usr/bin/env python3
"""Verify published bytes and optionally replay each pinned patch route in a private Git index."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def git(repository, arguments, environment):
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments], env=environment, stderr=subprocess.PIPE
    ).decode().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, help="Existing checkout containing the pinned base commits")
    options = parser.parse_args()
    directory = Path(__file__).resolve().parent
    manifest = json.loads((directory / "manifest.json").read_text())
    expected_paths = set(manifest["files"])
    # Nested manifests are payload; only this root manifest is self-excluded.
    actual_paths = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path != directory / "manifest.json"
    }
    if actual_paths != expected_paths:
        raise SystemExit(f"File-set mismatch: missing={sorted(expected_paths-actual_paths)}, extra={sorted(actual_paths-expected_paths)}")
    for relative, expected in manifest["files"].items():
        data = (directory / relative).read_bytes()
        actual = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        }
        if actual != expected:
            raise SystemExit(f"Content mismatch: {relative}")
    print(f"Verified {len(expected_paths)} payload files; root manifest is self-excluded.")
    if options.repository is None:
        return
    repository = options.repository.resolve()
    for name, route in manifest["patch_routes"].items():
        replay = json.loads((directory / route["replay_json"]).read_text())
        for mode in ("combined", "series"):
            paths = [replay["combined"]["path"]] if mode == "combined" else [step["path"] for step in replay["series"]]
            with tempfile.TemporaryDirectory(prefix="magnolie-round3-index-") as temporary:
                environment = os.environ.copy()
                environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
                git(repository, ["read-tree", replay["base"]], environment)
                for relative in paths:
                    patch = str(directory / relative)
                    git(repository, ["apply", "--cached", "--check", "--whitespace=error", patch], environment)
                    git(repository, ["apply", "--cached", "--whitespace=error", patch], environment)
                if git(repository, ["write-tree"], environment) != replay["source_tree"]:
                    raise SystemExit(f"Forward tree mismatch: {name}/{mode}")
                for relative in reversed(paths):
                    git(repository, ["apply", "--cached", "--reverse", "--whitespace=error", str(directory / relative)], environment)
                if git(repository, ["write-tree"], environment) != replay["base_tree"]:
                    raise SystemExit(f"Reverse tree mismatch: {name}/{mode}")
                print(f"Exact forward and reverse trees: {name}/{mode}")


if __name__ == "__main__":
    main()
