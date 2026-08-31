import importlib.util
import os

import pytest
from cryptography.exceptions import InvalidTag

ROOT = os.path.dirname(os.path.dirname(__file__))
SPEC = importlib.util.spec_from_file_location(
    "magnolie_asset", os.path.join(ROOT, "bin", "magnolie_asset.py"))
asset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asset)
CONTAINER = os.path.join(ROOT, "web", "kaffee-qr.mga")


def test_reviewed_container_and_strict_rejections(tmp_path):
    plaintext = asset.read_asset(CONTAINER, 1, 1)
    assert plaintext.startswith(b"\x89PNG\r\n\x1a\n") and len(plaintext) < asset.MAX_PLAINTEXT
    original = bytearray(open(CONTAINER, "rb").read())
    mutations = []
    for offset in (0, 4, 5, 6, 7, 8, 23, len(original) - 1):
        changed = bytearray(original)
        changed[offset] ^= 1
        mutations.append(changed)
    mutations.extend((original[:-1], original + b"x"))
    for index, changed in enumerate(mutations):
        path = tmp_path / ("bad-%d.mga" % index)
        path.write_bytes(changed)
        with pytest.raises((ValueError, InvalidTag)):
            asset.read_asset(path, 1, 1)
    with pytest.raises(ValueError):
        asset.read_asset(CONTAINER, 2, 1)


def test_no_ordinary_personal_asset_in_web_tree():
    names = {name.lower() for name in os.listdir(os.path.join(ROOT, "web"))}
    assert "kaffee-qr.png" not in names
    assert "kaffee-qr.mga" in names
