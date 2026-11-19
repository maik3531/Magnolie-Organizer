#!/usr/bin/env python3
"""Build the reviewed #447 timezone bootstrap without Node or host timezone rules.

Canonical inputs live in port-adapters/timezones. Cold standalone sources carry
the same exact six inputs under werkzeuge/timezones; generated assets are not
another editable rule source. This recipe alone does not activate UI hooks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


INPUT_SHA256 = {
    "resolver.js": "052009fbe3fedeb3d59c937ddf6c8ac924f52d13c5992bc1b9d27fc355acf2da",
    "port-runtime.js": "7fe5e5f5c44c0c601579fff1e91038402ff1cd7866b5963cb84372df74bd7ac6",
    "bootstrap.template.js": "8600c43c7007aa701545c1145a30e54ac8da9bcf7805b47378abe5ad37131554",
    "provenance.json": "b6b926b73620b3ab9ba477195041e52925ee6b12376791e647f70beba6bcc2a0",
    "tzdb-2026egtz.json": "2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c",
    "LICENSE-tzdb.txt": "0613408568889f5739e5ae252b722a2659c02002839ad970a63dc5e9174b27cf",
}
ARCHIVE_SHA256 = "0f391ed721b54225189a1c5cac469fa24a07c1283e9e460650fd28155e19240d"


def reject_symlinks(path):
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ValueError("Symlinked timezone recipe path: " + str(entry))


def source_directory(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    for candidate in (root.parent / "port-adapters/timezones", root / "werkzeuge/timezones"):
        # A present but incomplete primary is an error, not permission to
        # silently select another source/provider/version.
        if candidate.exists() or candidate.is_symlink():
            return candidate
    raise FileNotFoundError("Reviewed timezone recipe inputs are missing")


def read_inputs(source):
    source = Path(source)
    reject_symlinks(source)
    if not source.is_dir():
        raise ValueError("Timezone recipe source is not a directory")
    result = {}
    for name in INPUT_SHA256:
        path = source / name
        reject_symlinks(path)
        if not path.is_file():
            raise FileNotFoundError("Timezone recipe input is missing: " + name)
        result[name] = path.read_bytes()
    return result


def build_assets(inputs):
    if set(inputs) != set(INPUT_SHA256):
        raise ValueError("Timezone recipe input set differs")
    for name, expected in INPUT_SHA256.items():
        if not isinstance(inputs[name], bytes) or hashlib.sha256(inputs[name]).hexdigest() != expected:
            raise ValueError("Reviewed timezone input differs: " + name)
    payload = inputs["tzdb-2026egtz.json"]
    manifest = json.loads(inputs["provenance.json"])
    model = json.loads(payload)
    if (manifest.get("schema") != 2 or manifest.get("tzdbVersion") != "2026egtz" or
            manifest.get("payloadSHA256") != INPUT_SHA256["tzdb-2026egtz.json"] or
            manifest.get("payloadBytes") != len(payload) or manifest.get("archiveSHA256") != ARCHIVE_SHA256 or
            manifest.get("licenseSHA256") != INPUT_SHA256["LICENSE-tzdb.txt"] or
            model.get("schema") != 2 or model.get("tzdbVersion") != "2026egtz" or
            model.get("sourceArchiveSHA256") != ARCHIVE_SHA256):
        raise ValueError("Timezone payload/provenance binding differs")
    bootstrap = inputs["bootstrap.template.js"].decode("utf-8")
    replacements = (
        ("/*NORMATIVE_TZDB_TEXT*/null", json.dumps(payload.decode("utf-8"), ensure_ascii=False, separators=(",", ":"))),
        ("/*NORMATIVE_TZDB_MANIFEST*/null", inputs["provenance.json"].decode("utf-8").strip()),
    )
    for marker, value in replacements:
        if bootstrap.count(marker) != 1:
            raise ValueError("Timezone bootstrap marker differs")
        bootstrap = bootstrap.replace(marker, value, 1)
    assets = {"normative-timezones.js": inputs["resolver.js"] + b"\n" + inputs["port-runtime.js"] + b"\n" + bootstrap.encode("utf-8")}
    for name in ("tzdb-2026egtz.json", "provenance.json", "LICENSE-tzdb.txt"):
        assets["timezones/" + name] = inputs[name]
    return assets


def generate(source, output):
    assets = build_assets(read_inputs(source))  # Validate every input before writing anything.
    output = Path(output)
    for name in assets:
        reject_symlinks(output / name)
    for name, data in assets.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".normative-timezone-", delete=False) as target:
                temporary = Path(target.name)
                target.write(data)
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return assets


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate all inputs without writing assets")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "web")
    args = parser.parse_args(argv)
    source = args.source if args.source is not None else source_directory()
    if args.check:
        build_assets(read_inputs(source))
    else:
        generate(source, args.output)


if __name__ == "__main__":
    main()
