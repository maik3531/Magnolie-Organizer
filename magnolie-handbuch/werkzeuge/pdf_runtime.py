#!/usr/bin/env python3
"""Prepare the locked, licensed pure-Python PDF dependencies at build time."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
from urllib.parse import urlsplit
import zipfile


MAX_WHEEL = 16 * 1024 * 1024


def _get(url, limit):
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in {"pypi.org", "files.pythonhosted.org"}:
        raise ValueError("Unexpected dependency host")
    with urllib.request.urlopen(url, timeout=60) as response:
        if urlsplit(response.url).hostname not in {"pypi.org", "files.pythonhosted.org"}:
            raise ValueError("Unexpected dependency redirect")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Dependency exceeds the size limit")
    return data


def _owned_runtime(directory):
    manifest_path = directory / "runtime-manifest.json"
    if directory.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Existing PDF runtime is not a verified generated tree")
    manifest = json.loads(manifest_path.read_bytes())
    expected = manifest.get("files")
    if manifest.get("schema") != 1 or not isinstance(expected, dict) or not expected:
        raise ValueError("Existing PDF runtime manifest is invalid")
    expected_dirs = {parent.as_posix() for name in expected for parent in PurePosixPath(name).parents if parent.as_posix() != "."}
    actual = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Existing PDF runtime contains an unexpected symlink")
        if path.is_dir() and path.relative_to(directory).as_posix() not in expected_dirs:
            raise ValueError("Existing PDF runtime contains changed or additional directories")
        if path.is_file() and path != manifest_path:
            actual[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("Existing PDF runtime contains changed or additional files")


def prepare(lock_path, cache, destination, offline=False, update=False):
    lock_path, cache, destination = Path(lock_path), Path(cache), Path(destination)
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    if lock.get("schema") != 1 or not isinstance(lock.get("packages"), list):
        raise ValueError("Unsupported PDF dependency lock")
    existing = destination.exists() or destination.is_symlink()
    if existing and not update:
        raise ValueError("PDF dependency destination already exists")
    if existing:
        _owned_runtime(destination)
    if cache.is_symlink() or not cache.is_dir() or not destination.parent.is_dir():
        raise ValueError("PDF dependency parent/cache directory is unavailable")
    with tempfile.TemporaryDirectory(prefix=".pdf-runtime-", dir=destination.parent) as temporary:
        target = Path(temporary) / "runtime"
        target.mkdir()
        inventory, records = {}, []
        for package in lock["packages"]:
            name, version, filename, expected = (package[key] for key in ("name", "version", "filename", "sha256"))
            if (PurePosixPath(filename).name != filename or not filename.endswith("-py3-none-any.whl") or
                    len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected)):
                raise ValueError("Invalid locked wheel identity")
            wheel = cache / filename
            if wheel.is_symlink():
                raise ValueError("Wheel cache entry is a symlink")
            if not wheel.exists():
                if offline:
                    raise ValueError("Locked PDF dependency is absent from the offline cache")
                metadata = json.loads(_get("https://pypi.org/pypi/" + name + "/" + version + "/json", 2 * 1024 * 1024))
                candidates = [item for item in metadata["urls"] if item["filename"] == filename and item["digests"]["sha256"] == expected]
                if len(candidates) != 1 or not 0 < candidates[0]["size"] <= MAX_WHEEL:
                    raise ValueError("Locked wheel is unavailable")
                data = _get(candidates[0]["url"], MAX_WHEEL)
                if len(data) != candidates[0]["size"] or hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError("Downloaded PDF dependency differs from the lock")
                with open(wheel, "xb") as stream:
                    stream.write(data)
            data = wheel.read_bytes()
            if len(data) > MAX_WHEEL or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Cached PDF dependency differs from the lock")
            with zipfile.ZipFile(wheel) as archive:
                entries = archive.infolist()
                if sum(entry.file_size for entry in entries) > 64 * 1024 * 1024:
                    raise ValueError("Extracted PDF dependency exceeds the size limit")
                licenses = []
                for entry in entries:
                    path = PurePosixPath(entry.filename)
                    mode = stat.S_IFMT(entry.external_attr >> 16)
                    if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename or
                            mode not in (0, stat.S_IFREG, stat.S_IFDIR) or
                            path.suffix.lower() in {".so", ".pyd", ".dll", ".dylib", ".exe", ".pyc"}):
                        raise ValueError("Non-pure or unsafe PDF dependency entry")
                    if entry.is_dir():
                        continue
                    relative = path.as_posix()
                    if relative in inventory:
                        raise ValueError("Overlapping PDF dependency files")
                    content = archive.read(entry)
                    output = target.joinpath(*path.parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(content)
                    output.chmod(0o644)
                    inventory[relative] = hashlib.sha256(content).hexdigest()
                    if ".dist-info" in relative and any(word in path.name.lower() for word in ("license", "copying")):
                        licenses.append(relative)
                if not licenses:
                    raise ValueError("PDF dependency has no included license")
                records.append({**package, "licenses": sorted(licenses)})
        record = {"schema": 1, "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
                  "packages": records, "files": dict(sorted(inventory.items()))}
        manifest_path = target / "runtime-manifest.json"
        manifest_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        manifest_path.chmod(0o644)
        # Build/signing processes may have a private umask. The installed source
        # runtime must still be readable by the user of a root-owned package.
        for directory in (target, *(path for path in target.rglob("*") if path.is_dir())):
            directory.chmod(0o755)
        if existing:
            # Recheck immediately before replacement. Preserve any user changes
            # made while dependencies were being downloaded or extracted.
            _owned_runtime(destination)
            backup = Path(temporary) / "previous"
            os.rename(destination, backup)
            try:
                os.rename(target, destination)
            except BaseException:
                os.rename(backup, destination)
                raise
            shutil.rmtree(backup)
        else:
            os.rename(target, destination)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--lock", type=Path, default=Path(__file__).resolve().parents[1] / "bin/pdf-runtime-lock.json")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--update", action="store_true", help="Replace only a verified, unchanged generated runtime")
    args = parser.parse_args()
    result = prepare(args.lock, args.cache, args.destination, args.offline, args.update)
    print(json.dumps({"packages": [item["name"] + "=" + item["version"] for item in result["packages"]],
                      "files": len(result["files"]), "licenses_included": True}))


if __name__ == "__main__":
    main()
