#!/usr/bin/env python3
"""Render one PDF page through native Poppler tools, without modifying the PDF."""
import base64
import os
import re
import shutil
import struct
import subprocess

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 2200


def render_page(data, page=1):
    if not isinstance(data, bytes) or not data.startswith(b"%PDF-") or len(data) > MAX_BYTES:
        raise ValueError("invalid PDF input")
    if type(page) is not int or not 1 <= page <= 1000:
        raise ValueError("invalid PDF page")
    tools = {name: shutil.which(name) for name in ("pdfinfo", "pdftoppm")}
    if not all(tools.values()):
        raise RuntimeError("PDF rendering is unavailable")
    environment = dict(os.environ, LC_ALL="C")
    info = subprocess.run([tools["pdfinfo"], "-"], input=data, capture_output=True,
                          timeout=15, env=environment, check=True)
    match = re.search(rb"^Pages:\s*(\d+)\s*$", info.stdout, re.M)
    pages = int(match[1]) if match else 0
    if not 1 <= pages <= 1000 or page > pages:
        raise ValueError("invalid PDF page count")
    result = subprocess.run([tools["pdftoppm"], "-f", str(page), "-l", str(page),
        "-scale-to", str(MAX_SIDE), "-singlefile", "-png", "-"], input=data,
        capture_output=True, timeout=20, env=environment, check=True)
    png = result.stdout
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or not 24 <= len(png) <= MAX_BYTES:
        raise ValueError("invalid PDF preview")
    width, height = struct.unpack(">II", png[16:24])
    if not 1 <= width <= MAX_SIDE or not 1 <= height <= MAX_SIDE:
        raise ValueError("invalid PDF preview dimensions")
    return {"pages": pages, "page": page,
            "data": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}
