"""Strict native reader for reviewed Magnolie personal assets."""

import hashlib
import os
import struct
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

MAX_CONTAINER = 2 * 1024 * 1024
MAX_PLAINTEXT = 1024 * 1024
_KEY_PARTS = (b"Magnolie/native-personal-assets/", b"2026/", b"MGA-v1")
_SIGNATURES = {1: b"\x89PNG\r\n\x1a\n", 2: b"\xff\xd8\xff"}
_HANDBOOK_ASSETS = {
    "/kaffee-qr.png": ("kaffee-qr.mga", 1, 1, "image/png"),
    "/maik-walter.jpg": ("maik-walter.mga", 2, 2, "image/jpeg"),
}
_STATIC_MIME = {
    ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
    ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
    ".ttf": "font/ttf", ".txt": "text/plain",
}


def read_asset(path, expected_id, expected_mime):
    if (expected_id, expected_mime) not in ((1, 1), (2, 2)):
        raise ValueError("asset request is not allowlisted")
    size = os.stat(path).st_size
    if size < 40 or size > MAX_CONTAINER:
        raise ValueError("invalid asset container size")
    with open(path, "rb") as stream:
        container = stream.read(MAX_CONTAINER + 1)
    if len(container) != size or len(container) > MAX_CONTAINER:
        raise ValueError("invalid asset container read")
    header = container[:24]
    if (header[:4] != b"MGA1" or header[4] != 1 or
            header[5] != expected_id or header[6] != expected_mime or header[7] != 0):
        raise ValueError("invalid asset container header")
    nonce = header[8:20]
    if len(nonce) != 12:
        raise ValueError("invalid asset nonce")
    ciphertext_length = struct.unpack(">I", header[20:24])[0]
    if ciphertext_length < 16 or ciphertext_length > MAX_PLAINTEXT + 16:
        raise ValueError("invalid asset ciphertext length")
    if len(container) != 24 + ciphertext_length:
        raise ValueError("truncated or trailing asset data")
    key = hashlib.sha256(b"".join(_KEY_PARTS)).digest()
    try:
        plaintext = AESGCM(key).decrypt(nonce, container[24:], header)
    except InvalidTag:
        raise ValueError("asset authentication failed") from None
    if len(plaintext) > MAX_PLAINTEXT or not plaintext.startswith(_SIGNATURES[expected_mime]):
        raise ValueError("invalid decrypted asset type")
    return plaintext


def read_handbook_request(uri, root):
    """Serve only normalized handbook files and exact protected logical names."""
    try:
        parsed = urlsplit(str(uri or ""))
    except ValueError:
        return None
    if (parsed.scheme != "magnolie-handbuch" or parsed.netloc != "app" or
            parsed.query or parsed.fragment or "%" in parsed.path or "\\" in parsed.path or
            ".." in parsed.path or not parsed.path.startswith("/")):
        return None
    protected = _HANDBOOK_ASSETS.get(parsed.path)
    if protected:
        path = os.path.join(root, protected[0])
        return read_asset(path, protected[1], protected[2]), protected[3]
    extension = os.path.splitext(parsed.path)[1].lower()
    mime = _STATIC_MIME.get(extension)
    if not mime:
        return None
    root = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root, parsed.path.lstrip("/")))
    try:
        if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
            return None
    except ValueError:
        return None
    size = os.stat(path).st_size
    if size < 1 or size > 8 * 1024 * 1024:
        return None
    with open(path, "rb") as stream:
        data = stream.read(8 * 1024 * 1024 + 1)
    return (data, mime) if len(data) == size else None
