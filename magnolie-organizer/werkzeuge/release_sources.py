#!/usr/bin/env python3
"""Source selection shared by candidate provenance and Linux source packaging."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from source_selection import ARCHIVE, SECRET, PRIVATE_KEY, private_path, source_files


def file_stamp(status):
    return (status.st_dev, status.st_ino, status.st_size, status.st_mode,
            status.st_mtime_ns, status.st_ctime_ns)


def digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Non-regular hash input")
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
        after = os.fstat(stream.fileno())
    if file_stamp(before) != file_stamp(after) or file_stamp(after) != file_stamp(Path(path).stat()):
        raise ValueError("File changed while hashing")
    return value.hexdigest()


def source_identity(path):
    before = Path(path).stat()
    value = digest(path)
    if file_stamp(before) != file_stamp(Path(path).stat()):
        raise ValueError("Source changed while recording mode")
    return {"sha256": value, "mode": stat.S_IMODE(before.st_mode)}


def sync_contracts(root):
    root = Path(root).resolve()
    shared = root.parent / "contracts"
    local = root / "contracts"
    source = shared if shared.is_dir() else local
    files = list(source_files(source))
    if not files or any(relative.suffix not in {".json", ".md"} for relative, _ in files):
        raise ValueError("Shared JSON/Markdown contracts are missing or invalid")
    for relative, path in files:
        if relative.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif not path.read_text(encoding="utf-8").strip():
            raise ValueError("Empty contract documentation")
    if source == local:
        return
    local.mkdir(exist_ok=True)
    for relative, path in files:
        target = local / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError("Contract target is a symlink")
        shutil.copy2(path, target)


def inventory(root):
    root = Path(root).resolve()
    result = {}
    components = ["magnolie-organizer", "magnolie-organizer-windows",
                  "magnolie-handbuch-stamm", "contracts", ".github", "tools"]
    components += sorted(path.name for path in root.glob("magnolie-notes*") if path.is_dir())
    for component in components:
        folder = root / component
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError("Canonical source component is missing")
        for relative, path in source_files(folder):
            result[f"{component}/{relative.as_posix()}"] = source_identity(path)
    for path in sorted(root.iterdir()):
        name = path.name
        if path.is_dir() or private_path(Path(name)) or ARCHIVE.search(name) or \
                "PRUEFSUMMEN" in name or name.startswith(".magnolie-") or name.endswith((".exe.build.json", "-provenance.json")):
            continue
        if SECRET.search(name) or name == "build-config.json":
            raise ValueError("Secret in canonical release metadata")
        if path.is_symlink():
            raise ValueError("Canonical metadata is a symlink")
        result[name] = source_identity(path)
    return dict(sorted(result.items()))


def inventory_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_projection(record, component, destination):
    prefix = component + "/"
    expected = {name[len(prefix):]: value for name, value in record.items() if name.startswith(prefix)}
    if component == "magnolie-organizer":
        expected.update({name: value for name, value in record.items() if name.startswith("contracts/")})
    actual = {relative.as_posix(): source_identity(path) for relative, path in source_files(destination)}
    if not expected or actual != expected:
        raise ValueError("Source projection differs from recorded canonical inputs")


def audit_binary(root):
    root = Path(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            relative = path.relative_to(root)
            if private_path(relative) or SECRET.search(name) or any(
                    part in {"tests", "pruefungen", "fixtures", "contracts"} for part in relative.parts):
                raise ValueError("Test/private material in product payload")
            if path.is_symlink():
                raise ValueError("Symlink in product data payload")
            if path.is_file() and PRIVATE_KEY.search(path.read_bytes()):
                raise ValueError("Private key in product payload")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("contracts", "copy", "inventory", "binary", "verify-copy"))
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", nargs="?", type=Path)
    parser.add_argument("--component")
    args = parser.parse_args()
    if args.operation == "contracts":
        sync_contracts(args.root)
    elif args.operation == "binary":
        audit_binary(args.root)
    elif args.operation == "verify-copy":
        if args.destination is None or not args.component:
            raise ValueError("Source record, destination and component are required")
        verify_projection(json.loads(args.root.read_text(encoding="utf-8")), args.component, args.destination)
    elif args.operation == "inventory":
        print(json.dumps(inventory(args.root), sort_keys=True))
    else:
        if args.destination is None or args.destination.resolve().is_relative_to(args.root.resolve()):
            raise ValueError("Source projection must be outside its input tree")
        files = list(source_files(args.root))
        for relative, path in files:
            target = args.destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError("Source projection target already exists")
            shutil.copy2(path, target)


if __name__ == "__main__":
    main()
