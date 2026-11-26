#!/usr/bin/env python3
"""Refs #783: bind a Mac candidate to its unchanged, selected Git checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    "magnolie-organizer", "magnolie-organizer-windows", "magnolie-handbuch",
    "magnolie-notes", "contracts", "port-adapters", "Magnolie-Organizer-macOS-Beta",
    ".github/workflows/ports-2.0.30.yml", "PROTECTED-ASSETS-LICENSE.txt",
)
REFERENCE_DESKTOP_COMMIT = "067c38934b539943d8e1720abafd8a80b401d797"


def git(repo, *arguments):
    return subprocess.check_output(["git", "--no-optional-locks", *arguments], cwd=repo)


def capture(repo, expected_commit):
    """Read only; never restore a tag, generate assets, or bless a mixed tree."""
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    if head != expected_commit:
        raise ValueError("The checked-out commit differs from the selected candidate commit.")
    object_format = git(repo, "rev-parse", "--show-object-format").decode().strip()
    if object_format not in {"sha1", "sha256"}:
        raise ValueError("Unsupported Git object format.")
    paths = list(SOURCE_PATHS)
    notice = "LICENSE.md" if (repo / "LICENSE.md").is_file() else "LICENSING.md"
    paths.append(notice)
    for name in paths:
        if not (repo / name).exists():
            raise ValueError("A required candidate source path is missing: " + name)
    # Inspect tracked and non-ignored untracked inputs. Generated catalogs and
    # build output have their own exact SourceFreeze/ProjectionManifest checks.
    if git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths):
        raise ValueError("Candidate sources differ from the selected checkout; refusing a mixed source build.")
    files = {}
    for entry in git(repo, "ls-tree", "-r", "-z", "HEAD", "--", *paths).split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("Non-file candidate source refused.")
        relative = name.decode("utf-8")
        file = repo / relative
        if file.is_symlink() or not file.is_file():
            raise ValueError("Changed candidate source type refused.")
        data = file.read_bytes()
        # Git status can intentionally ignore assume-unchanged/skip-worktree
        # entries. Bind actual bytes directly to the committed object instead.
        actual_blob = hashlib.new(object_format, b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual_blob != blob or bool(file.stat().st_mode & 0o111) != (mode == "100755"):
            raise ValueError("Candidate source bytes or mode differ from their committed Git blob.")
        files[relative] = {"gitBlob": blob, "gitMode": mode, "sha256": hashlib.sha256(data).hexdigest()}
    if not files:
        raise ValueError("Candidate source inventory is empty.")
    # Detect an edit or checkout change during the inventory as well.
    if (git(repo, "rev-parse", "HEAD").decode().strip() != head or
            git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)):
        raise ValueError("Candidate sources changed while their inventory was recorded.")
    return {
        "format": 2, "sourcePolicy": "current-checkout", "gitObjectFormat": object_format,
        "portCommit": head, "desktopCommit": head,
        "referenceDesktopTag": "v2.0.30", "referenceDesktopCommit": REFERENCE_DESKTOP_COMMIT,
        "sourceFiles": files,
        "nativeAcceptance": False, "productionRelease": False,
    }


def verify(repo, expected_commit, proof):
    if proof != capture(repo, expected_commit):
        raise ValueError("Candidate source proof no longer matches the selected checkout.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["record", "verify"])
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--proof", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "record":
        proof = capture(REPO, args.expected_commit)
        # The workflow puts this in its private runner output, outside sources.
        with args.proof.open("x", encoding="utf-8") as output:
            output.write(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    else:
        proof = json.loads(args.proof.read_text())
        verify(REPO, args.expected_commit, proof)
    print("Current-checkout Mac source proof: " + args.expected_commit +
          "; " + str(len(proof["sourceFiles"])) + " tracked files; no native acceptance claim.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("macOS candidate source check blocked: " + str(error), file=sys.stderr)
        sys.exit(1)
