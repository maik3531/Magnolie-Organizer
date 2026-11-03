#!/usr/bin/env python3
"""Check installed local-module resolution without starting the application."""

import argparse
import ast
from datetime import datetime
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import zoneinfo


def composition_policy(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('_desktop_phone_composition', root / 'bin/magnolie_optional_phone.py')
    policy = importlib.util.module_from_spec(spec); spec.loader.exec_module(policy)
    return policy


def package_modules(root, selected=None):
    root = Path(root)
    policy = composition_policy(root)
    selected = policy.composition({}) if selected is None else selected
    all_modules = {path.name for path in (root / 'bin').glob('*.py')}
    base = policy.selected_modules(all_modules, policy.composition({}))
    optional = policy.selected_modules(all_modules, selected) - base
    deb = (root / "debian/install").read_text()
    rpm = (root / "rpm/magnolie-organizer.spec").read_text()
    image = (root / "werkzeuge/appimage_bauen.sh").read_text()
    flatpak = json.loads((root / "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json").read_text())
    commands = [line for line in flatpak["modules"][-1]["build-commands"]
                if line.startswith("install -m 0644 bin/") and line.endswith(" /app/bin/")]
    installed = {
        "deb": set(re.findall(r"^bin/(magnolie_[\w]+\.py)\s+usr/bin$", deb, re.M)),
        "rpm": set(re.findall(r"^install -Dpm 0644 bin/(magnolie_[\w]+\.py) %\{buildroot\}%\{_bindir\}/\1$", rpm, re.M)),
        "appimage": set(re.findall(r'^install -m 0644 "\$WURZEL/bin/(magnolie_[\w]+\.py)" "\$APPDIR/usr/bin/\1"$', image, re.M)),
        "flatpak": set(re.findall(r"bin/(magnolie_[\w]+\.py)", "\n".join(commands))),
    }
    return {kind: modules | optional for kind, modules in installed.items()}


def pruefen(bindir, tzpath=None):
    bindir = Path(bindir).resolve(strict=True)
    public = bindir
    bindir = public.parent / 'share/magnolie-organizer/python'
    wrapper = public / 'magnolie-organizer'
    canonical_wrapper = Path(__file__).resolve().parent / 'program_wrapper.py'
    if (not bindir.is_dir() or bindir.is_symlink() or wrapper.is_symlink() or not wrapper.is_file()
            or wrapper.read_bytes() != canonical_wrapper.read_bytes()
            or any(public.glob('magnolie_*.py'))):
        raise ValueError('Installed public command/private Python layout is invalid')
    if tzpath is not None:
        zoneinfo.reset_tzpath([str(Path(tzpath).resolve(strict=True))])
        zoneinfo.ZoneInfo.clear_cache()
    pending = [bindir / "magnolie-organizer"]
    source_bin = Path(__file__).resolve().parents[1] / "bin"
    policy = composition_policy()
    selected = policy.read_composition(bindir.parent)
    expected = policy.selected_modules({path.name for path in source_bin.glob('*.py')}, selected)
    actual = {path.name for path in bindir.glob('*.py')}
    if actual != expected:
        raise ValueError('Installed module composition differs from the desktop build: missing=' +
            ','.join(sorted(expected - actual)[:8]) + '; unexpected=' + ','.join(sorted(actual - expected)[:8]))
    pending.extend(bindir / name for name in sorted(expected))
    checked = set()
    sys.path.insert(0, str(bindir))
    while pending:
        path = pending.pop()
        if path in checked:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("Installed local Python module is missing: " + path.name)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        checked.add(path)
        for node in ast.walk(tree):
            names = ([node.module] if isinstance(node, ast.ImportFrom) else
                     [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                if not name or not name.startswith("magnolie_"):
                    continue
                expected = bindir / (name + ".py")
                spec = importlib.util.find_spec(name)
                if spec is None or spec.origin != str(expected):
                    raise ValueError("Installed module resolved outside the payload: " + name)
                pending.append(expected)
    recurrence = importlib.import_module("magnolie_recurrence")
    if Path(recurrence.__file__) != bindir / "magnolie_recurrence.py":
        raise ValueError("Recurrence module resolved outside the payload")
    for name in ("UTC", "Europe/Berlin", "America/New_York", "Australia/Lord_Howe",
                 "Pacific/Apia", "Africa/Casablanca", "America/Santiago"):
        zoneinfo.ZoneInfo(name)
    start = datetime(2026, 9, 1, 9, tzinfo=zoneinfo.ZoneInfo("Europe/Berlin"))
    values = recurrence.Rule("FREQ=DAILY;COUNT=2", start).between(start, start.replace(day=4))
    if [value.day for value in values] != [1, 2]:
        raise ValueError("Installed recurrence smoke check failed")
    print("Installed local modules, recurrence import and IANA timezone data verified.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bindir", type=Path)
    parser.add_argument("--tzpath", type=Path)
    args = parser.parse_args()
    pruefen(args.bindir, args.tzpath)
