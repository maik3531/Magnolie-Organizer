#!/usr/bin/env python3
"""Generate deterministic phone-download QR images for the Windows assistant."""

import json
import os

import qrcode


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "..", "magnolie-handbuch-stamm", "web", "mobile-downloads.json")
if not os.path.isfile(SOURCE):
    SOURCE = os.path.join(ROOT, "shared", "magnolie-handbuch-stamm", "web", "mobile-downloads.json")
TARGET = os.path.join(ROOT, "app", "symbole")


def main():
    with open(SOURCE, encoding="utf-8") as stream:
        downloads = json.load(stream)
    for key, filename in (("notes", "phone-notes-qr.png"), ("kdeConnect", "phone-kde-connect-qr.png")):
        image = qrcode.make(downloads[key]["url"], box_size=5, border=3)
        image.save(os.path.join(TARGET, filename), optimize=False)


if __name__ == "__main__":
    main()
