#!/usr/bin/env python3
"""Generate deterministic handbook download metadata and inline QR images."""

import base64
import io
import json
import os
import sys
from urllib.parse import urlparse

import qrcode
from qrcode.image.svg import SvgPathImage


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "web", "mobile-downloads.json")
TARGET = os.path.join(ROOT, "web", "mobile-downloads.js")


def qr_data(url):
    image = qrcode.make(url, image_factory=SvgPathImage, box_size=4, border=2)
    output = io.BytesIO()
    image.save(output)
    return "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def render(values):
    values = {key: dict(item) for key, item in values.items()}
    for item in values.values():
        url = item.get("url", "")
        if urlparse(url).scheme != "https" or not urlparse(url).netloc:
            raise ValueError("Download addresses must use HTTPS")
        item["qr"] = qr_data(url)
    return "window.MAGNOLIE_MOBILE_DOWNLOADS = Object.freeze(" + json.dumps(
        values, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + ");\n"


def main(source=SOURCE, target=TARGET):
    with open(source, encoding="utf-8") as stream:
        text = render(json.load(stream))
    with open(target, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


if __name__ == "__main__":
    main(*(sys.argv[1:3]))
