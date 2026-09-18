#!/usr/bin/env python3
"""Prepare an approved GitLab alias transaction, never upload or commit it.

Run only after separate publication authorization and versioned remote upload.
The existing candidate gate validates native/user evidence; no signing key read.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import urlopen
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "magnolie-organizer/werkzeuge"))
from release_gate import artifact_map, regular, require, stage_notes_alias, verify


def remote_hash(url, expected):
    require(urlsplit(url).scheme.lower() == "https", "Remote APK URL must use HTTPS")
    digest = hashlib.sha256()
    size = 0
    with urlopen(url, timeout=60) as response:
        require(response.status == 200 and urlsplit(response.url).scheme.lower() == "https", "Remote APK not available over HTTPS")
        while block := response.read(1024 * 1024):
            size += len(block)
            require(size <= expected["bytes"], "Remote APK exceeds approved size")
            digest.update(block)
    require(size == expected["bytes"] and digest.hexdigest() == expected["sha256"], "Remote APK differs from approved bytes")


def prepare(candidate, approval, identity, destination):
    record, identity, _ = verify(ROOT, candidate, approval, identity)
    name = f"Magnolie-Notes-{record['notesVersion']}.apk"
    expected = record["artifacts"][name]
    metadata = json.loads((ROOT / "magnolie-handbuch/web/mobile-downloads.json").read_text())["notes"]
    remote_hash(metadata["url"].rsplit("/", 1)[0] + "/" + name, expected)
    # Fresh output only: never replace a public tree or previously prepared set.
    require(destination.parent.is_dir() and not destination.exists() and not destination.is_symlink(), "Fresh private destination required")
    with tempfile.TemporaryDirectory(prefix=".notes-alias-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        shutil.copyfile(regular(candidate / name), stage / name)
        outputs = stage_notes_alias(ROOT, stage, record)
        verify(ROOT, candidate, approval, identity)
        require(artifact_map(stage, outputs) == outputs, "Alias changed during preparation")
        destination.mkdir(mode=0o700)
        try:
            for output in outputs:
                shutil.copyfile(stage / output, destination / output)
            require(artifact_map(destination, outputs) == outputs, "Prepared alias changed")
        except BaseException:
            shutil.rmtree(destination)
            raise
    print("Private alias prepared; no commit, upload or hosting activation performed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--accept-candidate", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.candidate.resolve(), args.approval.resolve(), args.accept_candidate, args.destination.absolute())
