"""Focused source/QR/transaction tests, no builds or public release access.

Requires pytest, qrcode, Pillow, cairosvg, numpy and opencv-python (or distro cv2).
"""
import ast
import base64
import io
import json
from pathlib import Path
import re
import sys

import cairosvg
import cv2
import numpy as np
import pytest
import qrcode
from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_mobile_downloads as sync
import prepare_notes_alias as promotion
import release_gate as gate

ROOT = sync.ROOT


def decode(data):
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    result, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    assert result, "QR could not be decoded"
    return result


def test_generated_outputs_and_entrypoints():
    for path, expected in sync.outputs().items():
        assert sync.matches(path, expected), str(path)
        if path.suffix == ".png":
            assert decode(path.read_bytes()) == decode(expected)
    values = json.loads((sync.HANDBOOK / "web/mobile-downloads.json").read_text())
    url = values["notes"]["url"]
    assert values["notes"]["filename"] == "Magnolie-Notes.apk"
    assert "version" not in values["notes"]
    linux = ROOT / "magnolie-organizer/bin/magnolie_setup_ui.py"
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(linux.read_text()).body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in {"MAGNOLIE_NOTES_URL", "KDE_CONNECT_URL"}}
    windows = (sync.WINDOWS / "FirstRunSetupForm.cs").read_text()
    assert constants["MAGNOLIE_NOTES_URL"] == url
    assert re.search(r'MagnolieNotesUrl = "([^"]+)"', windows)[1] == url
    assert 'PhoneDownload("Magnolie Notes", MagnolieNotesUrl, "phone-notes-qr.png")' in windows
    assert 'qrcode.make(url)' in linux.read_text()
    output = io.BytesIO()
    qrcode.make(constants["MAGNOLIE_NOTES_URL"]).save(output, format="PNG")
    assert decode(output.getvalue()) == url
    assert decode((sync.WINDOWS / "app/symbole/phone-notes-qr.png").read_bytes()) == url
    for web in (sync.HANDBOOK / "web", sync.WINDOWS / "shared/magnolie-handbuch-stamm/web"):
        source = (web / "mobile-downloads.js").read_text()
        downloads = json.loads(source.split("Object.freeze(", 1)[1][:-3])
        svg = base64.b64decode(downloads["notes"]["qr"].split(",", 1)[1])
        assert decode(cairosvg.svg2png(bytestring=svg, output_width=600, output_height=600,
                                      background_color="white")) == downloads["notes"]["url"] == url
        cards = (web / "inhalt.js").read_text()
        assert "href='${MOBILE_DOWNLOADS.notes.url}'" in cards
        assert "src='${MOBILE_DOWNLOADS.notes.qr}'" in cards
        assert "MOBILE_DOWNLOADS.notes.version" not in cards


def test_png_gate_preserves_pixels_not_compression(tmp_path):
    expected = next(value for path, value in sync.outputs().items() if path.suffix == ".png")
    path = tmp_path / "qr.png"
    with Image.open(io.BytesIO(expected)) as image:
        image = image.convert("RGBA")
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("generator", "synthetic alternative encoder")
        image.save(path, compress_level=0, pnginfo=metadata)
        assert path.read_bytes() != expected
        assert sync.matches(path, expected)
        assert decode(path.read_bytes()) == decode(expected)
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.save(path)
        assert not sync.matches(path, expected)
        image.resize((10, 10)).save(path)
        assert not sync.matches(path, expected)
    path.write_bytes(b"not a PNG")
    assert not sync.matches(path, expected)
    assert not sync.matches(tmp_path / "missing.png", expected)


@pytest.mark.parametrize("version", ["1.0.14", "1.0.99", "2.7.0"])
def test_future_versions_keep_desktop_outputs_and_retain_history(tmp_path, version):
    before = sync.outputs()
    name = f"Magnolie-Notes-{version}.apk"
    payload = b"SYNTHETIC APK " + version.encode()
    (tmp_path / name).write_bytes(payload)
    record = {"notesVersion": version, "artifacts": gate.artifact_map(tmp_path, [name])}
    result = gate.stage_notes_alias(ROOT, tmp_path, record)
    assert (tmp_path / "Magnolie-Notes.apk").read_bytes() == (tmp_path / name).read_bytes() == payload
    assert not (tmp_path / "Magnolie-Notes.apk").is_symlink()
    assert result["Magnolie-Notes.apk"] == record["artifacts"][name]
    assert sync.outputs() == before
    (tmp_path / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        gate.stage_notes_alias(ROOT, tmp_path, record)


def test_alias_preparation_requires_acceptance_before_network_or_output(tmp_path, monkeypatch):
    def rejected(*args):
        raise ValueError("No personal acceptance")
    monkeypatch.setattr(promotion, "verify", rejected)
    monkeypatch.setattr(promotion, "remote_hash", lambda *args: pytest.fail("Network before acceptance"))
    with pytest.raises(ValueError, match="acceptance"):
        promotion.prepare(tmp_path, tmp_path / "approval", None, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_remote_hash_rejects_html_partial_and_wrong_bytes(monkeypatch):
    class Response(io.BytesIO):
        status = 200
        url = "https://gitlab.com/synthetic.apk"
    for data in (b"<html>error</html>", b"", b"bad"):
        monkeypatch.setattr(promotion, "urlopen", lambda *args, **kwargs: Response(data))
        with pytest.raises(ValueError, match="Remote APK"):
            promotion.remote_hash(Response.url, {"bytes": 3, "sha256": "0" * 64})


def test_alias_transaction_rolls_back_partial_publication(tmp_path, monkeypatch):
    root, stage = tmp_path / "public", tmp_path / "stage"
    root.mkdir()
    stage.mkdir()
    names = ["Magnolie-Notes.apk", "Magnolie-Notes-latest-PRUEFSUMMEN.sha256"]
    for name in names:
        (root / name).write_bytes(b"previous approved")
        (stage / name).write_bytes(b"next approved")
    monkeypatch.setattr(gate.os, "sync", lambda: None)
    def failure():
        raise ValueError("postcondition failed")
    with pytest.raises(ValueError, match="postcondition"):
        gate.publish_files(root, stage, names, lambda: None, failure)
    assert all((root / name).read_bytes() == b"previous approved" for name in names)
