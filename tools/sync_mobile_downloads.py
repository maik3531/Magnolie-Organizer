#!/usr/bin/env python3
"""Generate/check all phone download constants and QR assets from one definition.

No Android version input, network access, package build or release mutation.
"""
import argparse
import io
import json
from pathlib import Path
import re
import sys

import qrcode
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "magnolie-handbuch-stamm"
WINDOWS = ROOT / "magnolie-organizer-windows"
sys.path.insert(0, str(HANDBOOK / "werkzeuge"))
from mobile_downloads_erzeugen import render


def outputs():
    source = HANDBOOK / "web/mobile-downloads.json"
    values = json.loads(source.read_text())
    notes = values["notes"]
    if set(notes) != {"filename", "url"} or notes["filename"] != "Magnolie-Notes.apk" or not notes["url"].endswith("/" + notes["filename"]):
        raise ValueError("Notes must use the version-independent APK alias")
    shared = WINDOWS / "shared/magnolie-handbuch-stamm/web"
    result = {shared / source.name: source.read_bytes()}
    for web in (HANDBOOK / "web", shared):
        result[web / "mobile-downloads.js"] = render(values).encode()
    # Inline generated constants preserve standalone source/package layouts.
    for path, entries in (
        (ROOT / "magnolie-organizer/bin/magnolie_setup_ui.py", (
            (r'^MAGNOLIE_NOTES_URL = .*?(?=\nKDE_CONNECT_URL)', 'MAGNOLIE_NOTES_URL = ' + json.dumps(notes["url"])),
            (r'^KDE_CONNECT_URL = .*?(?=\n\n)', 'KDE_CONNECT_URL = ' + json.dumps(values["kdeConnect"]["url"])))),
        (WINDOWS / "FirstRunSetupForm.cs", (
            (r'(?<=internal const string MagnolieNotesUrl = )[^;]+', json.dumps(notes["url"])),
            (r'(?<=internal const string KdeConnectUrl = )[^;]+', json.dumps(values["kdeConnect"]["url"]))))):
        text = path.read_text()
        for pattern, replacement in entries:
            text, count = re.subn(pattern, lambda _: replacement, text, flags=re.M | re.S)
            if count != 1:
                raise ValueError(f"Download constant anchor changed: {path}")
        result[path] = text.encode()
    for key, name in (("notes", "phone-notes-qr.png"), ("kdeConnect", "phone-kde-connect-qr.png")):
        output = io.BytesIO()
        qrcode.make(values[key]["url"], box_size=5, border=3).save(output, format="PNG", optimize=False)
        result[WINDOWS / "app/symbole" / name] = output.getvalue()
    return result


def matches(path, content):
    if not path.is_file():
        return False
    if path.suffix != ".png":
        return path.read_bytes() == content
    # PNG compression and metadata may vary; every rendered pixel must agree.
    try:
        with Image.open(path) as actual, Image.open(io.BytesIO(content)) as expected:
            return actual.size == expected.size and actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, content in outputs().items():
        if not matches(path, content):
            stale.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.write_bytes(content)
    if args.check and stale:
        sys.exit("Stale mobile downloads; run tools/sync_mobile_downloads.py: " + ", ".join(stale))


if __name__ == "__main__":
    main()
