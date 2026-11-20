#!/usr/bin/env python3
"""Reject new release packages, LFS pointers and large Git blobs (Refs #698).

The trusted base must be an ancestor of head. Every newly reachable commit is
inspected, including merge parents and files deleted again before head. Existing
base entries are grandfathered only at the same path, mode and object ID. This
checks Git objects, never worktree files or symlink targets.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


MAX_BLOB_BYTES = 5 * 1024 * 1024
PACKAGE_SUFFIXES = (
    ".apk", ".aab", ".apks", ".xapk", ".deb", ".udeb", ".rpm",
    ".appimage", ".flatpak", ".oxt",
    ".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle",
    ".dmg", ".pkg", ".ipa", ".iso", ".img", ".zip", ".7z", ".rar",
    ".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".tzst",
)
# All single tar compression extensions are denied. Checksums/signatures such
# as archive.tar.gz.sha256 and small .flatpakref metadata remain source files.
TAR_SUFFIX = re.compile(r"\.tar\.[^./]+$", re.IGNORECASE)
LFS_HEADERS = (
    b"version https://git-lfs.github.com/spec/v1",
    b"version https://hawser.github.com/spec/v1",
)
OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


class GuardError(RuntimeError):
    """The requested range could not be proven safe."""


@dataclass(frozen=True)
class Entry:
    mode: str
    oid: str
    path: bytes


@dataclass(frozen=True)
class Violation:
    commit: str
    path: str
    object_id: str
    reason: str


@dataclass(frozen=True)
class Result:
    base: str
    head: str
    commits_checked: int
    entries_checked: int
    violations: tuple[Violation, ...]


class Git:
    def __init__(self, repo: Path):
        self.command = ["git", "-C", str(repo)]
        self.env = os.environ.copy()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                     "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                     "GIT_NAMESPACE", "GIT_SHALLOW_FILE"):
            self.env.pop(name, None)
        # A local replace ref or graft must not hide commits in the range.
        self.env["GIT_NO_REPLACE_OBJECTS"] = "1"
        self.env["GIT_GRAFT_FILE"] = os.devnull
        self.env["GIT_TERMINAL_PROMPT"] = "0"

    def run(self, *args: str, input_bytes: bytes | None = None,
            accepted: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [*self.command, *args], input=input_bytes, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=self.env, check=False,
        )
        if result.returncode not in accepted:
            # Do not print raw Git diagnostics: refs and paths may contain control
            # characters, and CI logs interpret some unescaped line prefixes.
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise GuardError(f"git {args[0]} failed: {detail!r}")
        return result

    def commit(self, ref: str) -> str:
        if not ref or ref.startswith("-") or "\x00" in ref:
            raise GuardError("A nonempty commit/ref is required; options are not refs")
        oid = self.run("rev-parse", "--verify", "--end-of-options",
                       ref + "^{commit}").stdout.decode("ascii").strip()
        if not OBJECT_ID.fullmatch(oid):
            raise GuardError("Git returned an invalid commit object ID")
        return oid

    def baseline(self, commit: str) -> set[Entry]:
        entries = set()
        raw = self.run("ls-tree", "-r", "-z", "--full-tree", commit).stdout
        for record in raw.split(b"\x00"):
            if record:
                metadata, path = record.split(b"\t", 1)
                mode, _kind, oid = metadata.decode("ascii").split(" ")
                entries.add(Entry(mode, oid, path))
        return entries

    def changed_entries(self, commit: str) -> set[Entry]:
        # -m checks each merge parent; --root includes new unrelated roots that
        # were merged in. With renames disabled, moves are deletion + addition.
        raw = self.run(
            "diff-tree", "--root", "-r", "-m", "--no-commit-id", "--raw",
            "-z", "--no-abbrev", "--no-renames", "--no-ext-diff",
            "--diff-filter=AMT", commit, "--",
        ).stdout
        records = raw.split(b"\x00")
        if records[-1] != b"" or len(records) % 2 != 1:
            raise GuardError("Unexpected NUL-delimited Git diff")
        entries = set()
        for index in range(0, len(records) - 1, 2):
            header, path = records[index:index + 2]
            fields = header.decode("ascii").split()
            if len(fields) != 5 or not fields[0].startswith(":"):
                raise GuardError("Unexpected Git diff entry")
            _old_mode, mode, _old_oid, oid, status = fields
            if status not in {"A", "M", "T"} or not OBJECT_ID.fullmatch(oid):
                raise GuardError("Unexpected Git diff status or object ID")
            if mode not in {"100644", "100755", "120000", "160000"}:
                raise GuardError("Unexpected Git file mode")
            entries.add(Entry(mode, oid, path))
        return entries

    def blob_info(self, oids: Iterable[str]) -> dict[str, tuple[int, bool]]:
        """Read object sizes first; valid LFS pointers fit within 1024 bytes.

        https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md#the-pointer
        Oversized blobs are rejected without reading their potentially huge
        contents into the guard process.
        """
        unique = sorted(set(oids))
        if not unique:
            return {}
        metadata = self.run("cat-file", "--batch-check", input_bytes=(
            "\n".join(unique) + "\n").encode("ascii")).stdout.splitlines()
        if len(metadata) != len(unique):
            raise GuardError("Incomplete Git object metadata")
        info = {}
        for oid, line in zip(unique, metadata):
            fields = line.split()
            if len(fields) != 3 or fields[0].decode("ascii") != oid or fields[1] != b"blob":
                raise GuardError("Missing or non-blob object in Git file entry")
            size = int(fields[2])
            if size < 0:
                raise GuardError("Invalid Git blob size")
            info[oid] = (size, False)
        with subprocess.Popen(
            [*self.command, "cat-file", "--batch"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self.env,
        ) as process:
            assert process.stdin is not None and process.stdout is not None
            try:
                for oid in unique:
                    if info[oid][0] > 1024:
                        continue
                    process.stdin.write(oid.encode("ascii") + b"\n")
                    process.stdin.flush()
                    header = process.stdout.readline().split()
                    if len(header) != 3 or header[0].decode("ascii") != oid or header[1] != b"blob":
                        raise GuardError("Missing or non-blob object in Git file entry")
                    size = int(header[2])
                    if size != info[oid][0]:
                        raise GuardError("Git blob size changed while checking")
                    prefix = process.stdout.read(min(size, 1024))
                    remaining = size - len(prefix)
                    while remaining:
                        chunk = process.stdout.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise GuardError("Truncated Git blob")
                        remaining -= len(chunk)
                    if process.stdout.read(1) != b"\n":
                        raise GuardError("Invalid Git object framing")
                    first_line = prefix.split(b"\n", 1)[0].rstrip(b"\r")
                    info[oid] = (size, first_line in LFS_HEADERS)
            except BaseException:
                process.kill()
                raise
            finally:
                process.stdin.close()
            if process.wait() != 0:
                raise GuardError("Git could not read all new blobs")
        return info


def is_package_path(path: bytes) -> bool:
    # Win32 ignores trailing dots/spaces in a filename; do not let those spellings
    # turn an installer path into an apparently harmless source path.
    name = os.fsdecode(path).casefold().rstrip(" .")
    return name.endswith(PACKAGE_SUFFIXES) or TAR_SUFFIX.search(name) is not None


def check_range(repo: Path, base: str, head: str) -> Result:
    git = Git(repo)
    if git.run("rev-parse", "--is-shallow-repository").stdout.strip() != b"false":
        raise GuardError("Full history is required; a shallow repository cannot be checked")
    base_oid, head_oid = git.commit(base), git.commit(head)
    ancestor = git.run("merge-base", "--is-ancestor", base_oid, head_oid, accepted=(0, 1))
    if ancestor.returncode:
        raise GuardError("Trusted base is not an ancestor of head; refresh the branch first")
    commits = git.run("rev-list", "--reverse", "--topo-order", head_oid,
                      "^" + base_oid, "--").stdout.decode("ascii").splitlines()
    baseline = git.baseline(base_oid)
    changed = []
    for commit in commits:
        for entry in sorted(git.changed_entries(commit) - baseline,
                            key=lambda item: (item.path, item.mode, item.oid)):
            changed.append((commit, entry))
    blobs = git.blob_info(entry.oid for _, entry in changed if entry.mode != "160000")
    violations = []
    for commit, entry in changed:
        reasons = []
        if is_package_path(entry.path):
            reasons.append("release package/archive path must use the package registry")
        if entry.mode != "160000":
            size, lfs_pointer = blobs[entry.oid]
            if lfs_pointer:
                reasons.append("new Git LFS pointer is forbidden")
            if size > MAX_BLOB_BYTES:
                reasons.append(f"Git blob is {size} bytes; maximum is {MAX_BLOB_BYTES}")
        for reason in reasons:
            violations.append(Violation(commit, os.fsdecode(entry.path), entry.oid, reason))
    return Result(base_oid, head_oid, len(commits), len(changed), tuple(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--base", required=True, help="trusted ancestor commit/ref")
    parser.add_argument("--head", required=True, help="candidate commit/ref")
    args = parser.parse_args(argv)
    try:
        result = check_range(args.repo, args.base, args.head)
    except (GuardError, OSError, ValueError) as exc:
        print(json.dumps({"safe": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps({"safe": not result.violations, **asdict(result)},
                     ensure_ascii=True, sort_keys=True))
    return 1 if result.violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
