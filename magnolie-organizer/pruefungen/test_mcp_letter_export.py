"""Actual flat OpenDocument letter generation through the explicit native export path."""
import hashlib
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from modul_laden import quellmodul_laden


def test_native_letter_export_uses_existing_layout_and_readback(monkeypatch):
    product = quellmodul_laden("owned_letter_export", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    with tempfile.TemporaryDirectory(prefix="magnolie-letter-export-", dir="/tmp/opencode") as root:
        profile = Path(root) / "owned-profile.json"; profile.write_text('{"owned":true}')
        monkeypatch.setattr(product, "daten_datei", lambda: str(profile))
        class Window:
            _gesperrt = False
            def __init__(self): self.replies = []
            def antwort(self, callback, payload): self.replies.append((callback, payload))
        window = Window()
        for layout in ("din5008-b", "din5008-a", "compact", "din5008"):
            target = Path(root) / (layout + ".fodt")
            message = {"cmd": "brief", "requestId": "owned-letter", "pfad": str(target), "layout": layout,
                "kontakt": {"vorname": "Owned", "nachname": "Recipient", "strasse": "Owned Street 1", "plz": "10115", "ort": "Owned town"},
                "absender": "Owned sender\nOwn Street 2"}
            product.Fenster._dokument_datei_exportieren(window, message)
            callback, result = window.replies.pop()
            assert callback == "App.documentExportErgebnis" and result["requestId"] == "owned-letter" and result["ok"], result
            actual = target.read_bytes(); document = ET.fromstring(actual)
            assert result["format"] == "fodt" and result["bytes"] == len(actual) and result["sha256"] == hashlib.sha256(actual).hexdigest()
            assert "Owned Recipient" in "".join(document.itertext()) and "Owned Street 1" in "".join(document.itertext())
            product.Fenster._dokument_datei_exportieren(window, message)
            assert not window.replies.pop()[1]["ok"] and target.read_bytes() == actual
        for executable, accepted in (("/usr/bin/true", True), ("/usr/bin/false", False)):
            monkeypatch.setattr(product.shutil, "which", lambda _name, executable=executable: executable)
            target = Path(root) / ("launcher-" + str(accepted) + ".fodt")
            product.Fenster._dokument_datei_exportieren(window, {**message, "pfad": str(target), "open_with_registered_app": True})
            result = window.replies.pop()[1]
            assert result["ok"] and result["launcherAccepted"] is accepted
            assert result["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
