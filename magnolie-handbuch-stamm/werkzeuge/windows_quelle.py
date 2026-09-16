#!/usr/bin/env python3
"""Refresh the Windows source projection, not a build or release directory."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT.parent / "Magnolie-Organizer-Windows-2.0.0/shared/magnolie-handbuch-stamm/web"


def main():
    source = ROOT / "web"
    if not TARGET.is_dir() or source.resolve() == TARGET.resolve():
        raise ValueError("canonical Windows source projection is missing")
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part.startswith(".") for part in relative.parts) or path.suffix not in {
                ".js", ".json", ".html", ".css", ".png", ".jpg", ".mga", ".ttf", ".txt"}:
            raise ValueError("unexpected handbook payload: " + str(relative))
        target = TARGET / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    print("Windows handbook source projection updated from canonical web/")


if __name__ == "__main__":
    main()
