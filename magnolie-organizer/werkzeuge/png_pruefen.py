#!/usr/bin/env python3
"""Validate a PNG structurally and optionally decode its QR payload."""

import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path


SIGNATURE = b"\x89PNG\r\n\x1a\n"


def pruefen(path):
    data = Path(path).read_bytes()
    if not data.startswith(SIGNATURE):
        raise ValueError("ungueltige PNG-Signatur")
    offset = len(SIGNATURE)
    chunks = []
    width = height = None
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("abgeschnittener PNG-Chunk")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("abgeschnittene PNG-Nutzlast")
        payload = data[offset + 8:offset + 8 + length]
        expected = struct.unpack(">I", data[offset + 8 + length:end])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected:
            raise ValueError("ungueltige PNG-CRC")
        chunks.append(kind)
        if kind == b"IHDR":
            if len(chunks) != 1 or length != 13:
                raise ValueError("ungueltiger IHDR-Chunk")
            width, height = struct.unpack(">II", payload[:8])
            if not width or not height:
                raise ValueError("ungueltige PNG-Abmessungen")
        offset = end
        if kind == b"IEND":
            break
    if offset != len(data) or chunks.count(b"IHDR") != 1 or b"IDAT" not in chunks or chunks[-1] != b"IEND":
        raise ValueError("unvollstaendige PNG-Struktur")
    return width, height


def haupt(argv):
    if len(argv) != 2:
        raise SystemExit("Aufruf: png_pruefen.py DATEI.png")
    width, height = pruefen(argv[1])
    decoder = shutil.which("zbarimg")
    if decoder:
        result = subprocess.run(
            [decoder, "--quiet", "--raw", argv[1]], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not result.stdout.strip():
            raise RuntimeError("QR-Code enthaelt keine dekodierbare Nutzlast")
    print(f"PNG {width}x{height}: ok")


if __name__ == "__main__":
    haupt(sys.argv)
