#!/usr/bin/env python3
"""One-time deterministic MGA v1 packer; package builds must not invoke it."""

import hashlib
import hmac
import os
import struct
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
MAGIC = b"MGA1"
VERSION = 1
KEY_PARTS = (b"Magnolie/native-personal-assets/", b"2026/", b"MGA-v1")
EXPECTED = {
    "coffee": "223be6adfc2aa5e6332e9802f395d66e03f01c6b0c850d46e38dfbfc1c714925",
    "portrait": "835a69e450c7ba1d5ae6aa59bc61b6fd5613563cfff19449b2839b53dda77fe6",
}


def key():
    return hashlib.sha256(b"".join(KEY_PARTS)).digest()


def pack(source, destination, asset_id, mime_id, expected_digest):
    with open(source, "rb") as stream:
        plaintext = stream.read(1_048_577)
    if len(plaintext) > 1_048_576:
        raise ValueError("asset exceeds the 1 MiB plaintext limit")
    digest = hashlib.sha256(plaintext).digest()
    if not hmac.compare_digest(digest.hex(), expected_digest):
        raise ValueError("source asset digest does not match the reviewed input")
    nonce = hmac.new(key(), b"MGA-v1-nonce\0" + bytes((asset_id, mime_id)) + digest,
                     hashlib.sha256).digest()[:12]
    ciphertext_length = len(plaintext) + 16
    header = MAGIC + bytes((VERSION, asset_id, mime_id, 0)) + nonce + struct.pack(">I", ciphertext_length)
    container = header + AESGCM(key()).encrypt(nonce, plaintext, header)
    temporary = destination + ".new"
    with open(temporary, "wb") as stream:
        stream.write(container)
    os.replace(temporary, destination)


def main():
    if sys.argv[1:] != ["--from-reviewed-plaintext"]:
        raise SystemExit("usage: pack_personal_assets.py --from-reviewed-plaintext")
    organizer = os.path.join(ROOT, "magnolie-organizer", "web")
    windows = os.path.join(ROOT, "magnolie-organizer-windows")
    handbook = os.path.join(ROOT, "magnolie-handbuch", "web")
    shared = os.path.join(windows, "shared", "magnolie-handbuch", "web")
    jobs = [
        (os.path.join(organizer, "kaffee-qr.png"), os.path.join(organizer, "kaffee-qr.mga"), 1, 1, EXPECTED["coffee"]),
        (os.path.join(windows, "app", "web", "kaffee-qr.png"), os.path.join(windows, "app", "web", "kaffee-qr.mga"), 1, 1, EXPECTED["coffee"]),
        (os.path.join(handbook, "kaffee-qr.png"), os.path.join(handbook, "kaffee-qr.mga"), 1, 1, EXPECTED["coffee"]),
        (os.path.join(handbook, "maik-walter.jpg"), os.path.join(handbook, "maik-walter.mga"), 2, 2, EXPECTED["portrait"]),
        (os.path.join(shared, "kaffee-qr.png"), os.path.join(shared, "kaffee-qr.mga"), 1, 1, EXPECTED["coffee"]),
        (os.path.join(shared, "maik-walter.jpg"), os.path.join(shared, "maik-walter.mga"), 2, 2, EXPECTED["portrait"]),
    ]
    for job in jobs:
        pack(*job)


if __name__ == "__main__":
    main()
