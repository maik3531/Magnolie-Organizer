import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
SPEC = importlib.util.spec_from_file_location(
    "handbook_asset", os.path.join(ROOT, "bin", "magnolie_asset.py"))
asset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asset)


@pytest.mark.parametrize("name,asset_id,mime,signature", [
    ("kaffee-qr.mga", 1, 1, b"\x89PNG\r\n\x1a\n"),
    ("maik-walter.mga", 2, 2, b"\xff\xd8\xff"),
])
def test_reviewed_assets_and_routing(name, asset_id, mime, signature):
    path = os.path.join(ROOT, "web", name)
    assert asset.read_asset(path, asset_id, mime).startswith(signature)
    logical = "kaffee-qr.png" if asset_id == 1 else "maik-walter.jpg"
    data, content_type = asset.read_handbook_request(
        "magnolie-handbuch://app/" + logical, os.path.join(ROOT, "web"))
    assert data.startswith(signature) and content_type.startswith("image/")
    for uri in ("magnolie-handbuch://app/" + name,
                "magnolie-handbuch://app/" + logical + "?x=1",
                "magnolie-handbuch://evil/" + logical,
                "magnolie-handbuch://app/%2e%2e/" + logical):
        assert asset.read_handbook_request(uri, os.path.join(ROOT, "web")) is None


def test_authentication_and_trailing_data_rejected(tmp_path):
    original = bytearray(open(os.path.join(ROOT, "web", "kaffee-qr.mga"), "rb").read())
    for index, changed in enumerate((original[:-1], original + b"x")):
        path = tmp_path / ("bad-%d.mga" % index)
        path.write_bytes(changed)
        with pytest.raises(ValueError):
            asset.read_asset(path, 1, 1)
    changed = bytearray(original)
    changed[-1] ^= 1
    path = tmp_path / "tampered.mga"
    path.write_bytes(changed)
    with pytest.raises(ValueError):
        asset.read_asset(path, 1, 1)


def test_plaintext_personal_assets_are_absent():
    web = os.path.join(ROOT, "web")
    assert not os.path.exists(os.path.join(web, "kaffee-qr.png"))
    assert not os.path.exists(os.path.join(web, "maik-walter.jpg"))
