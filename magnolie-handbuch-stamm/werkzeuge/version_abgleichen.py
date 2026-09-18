#!/usr/bin/env python3
"""Synchronize numeric release references without changing translated wording."""
import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-version", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = json.loads((root / "web/version.json").read_text())["version"]
    for version in (args.from_version, target):
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            parser.error("Expected a three-part numeric version")
    pattern = re.compile(r"(?<![\d.])" + re.escape(args.from_version) + r"(?![\d.])")
    # These files describe the current book, not historical release records.
    files = [root / "web/inhalt.js", root / "web/platform.js", root / "web/i18n-markers.js"]
    files += sorted((root / "po").glob("*.po")) + sorted((root / "po").glob("*.pot"))
    files += sorted((root / "man").rglob("*.1"))
    changed = 0
    for path in files:
        before = path.read_text(encoding="utf-8")
        after = pattern.sub(target, before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed += 1
    print(f"Handbook release references synchronized to {target}: {changed} files")


if __name__ == "__main__":
    main()
