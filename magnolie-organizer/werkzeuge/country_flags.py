#!/usr/bin/env python3
"""Build the local ISO-country flag atlas from the pinned MIT flag-icons source."""
import argparse
import hashlib
import io
from pathlib import Path
import re
import sys
import tarfile

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "magnolie-organizer/bin"))
from magnolie_phone_region import ISO_ALPHA2

ARCHIVE_SHA256 = "e6718c0e6cb97362c33c086f8083e46d0e770d644cf046b3bbf8988408ef7250"
CELL = (64, 48)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.read_bytes()
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit("The flag-icons v7.6.0 archive does not match its pinned digest.")
    atlas = Image.new("RGBA", (26 * CELL[0], 26 * CELL[1]), (0, 0, 0, 0))
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        members = {member.name: member for member in package.getmembers()}
        if len(members) > 5000:
            raise SystemExit("Unexpected flag source archive.")
        entries = {name.rsplit("/", 1)[-1][:-4].upper(): member for name, member in members.items()
                   if re.search(r"/flags/4x3/[a-z]{2}\.svg$", name)}
        if not set(ISO_ALPHA2).issubset(entries):
            raise SystemExit("Missing ISO flag sources: " + ", ".join(sorted(set(ISO_ALPHA2) - entries.keys())))
        for code in sorted(ISO_ALPHA2):
            source = package.extractfile(entries[code])
            if source is None:
                raise SystemExit("Unreadable flag source: " + code)
            svg = source.read(1024 * 1024 + 1)
            if len(svg) > 1024 * 1024 or re.search(rb"<!DOCTYPE|<script|(?:href|xlink:href)\s*=\s*['\"](?:https?:|//|file:)", svg, re.I):
                raise SystemExit("Unexpected active or external SVG content: " + code)
            png = cairosvg.svg2png(bytestring=svg, output_width=CELL[0], output_height=CELL[1])
            with Image.open(io.BytesIO(png)) as flag:
                if not flag.getbbox():
                    raise SystemExit("Empty rendered flag: " + code)
                atlas.alpha_composite(flag.convert("RGBA"), ((ord(code[1]) - 65) * CELL[0], (ord(code[0]) - 65) * CELL[1]))
    output = io.BytesIO(); atlas.save(output, format="PNG", optimize=True)
    data = output.getvalue()
    for target in (ROOT / "magnolie-organizer/web/country-flags.png", ROOT / "magnolie-organizer-windows/app/web/country-flags.png"):
        target.write_bytes(data)
    print("ISO country flags:", len(ISO_ALPHA2), "local images in one atlas;", len(data), "bytes; SHA256", hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
