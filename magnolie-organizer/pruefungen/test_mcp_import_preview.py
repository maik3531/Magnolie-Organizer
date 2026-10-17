"""Actual import parsers inspect owned files without committing data or opening dialogs."""
import hashlib
from pathlib import Path
import tempfile
import zipfile

from modul_laden import quellmodul_laden


def test_native_import_preview_formats_source_cas_archives_and_limits():
    product = quellmodul_laden("owned_import_preview", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    with tempfile.TemporaryDirectory(prefix="magnolie-import-preview-", dir="/tmp/opencode") as root:
        class Window:
            _gesperrt = False
            def __init__(self): self.replies = []
            def _datei_oeffnen(self, *_args): raise AssertionError("MCP import opened a GUI file dialog")
            def antwort(self, callback, payload): self.replies.append((callback, payload))
        window = Window()
        event = {"id": "owned-event", "titel": "Owned preview", "datum": "2030-01-02", "zeit": "09:00"}
        contact = {"id": "owned-contact", "vorname": "Owned", "nachname": "Preview", "email": "owned@example.invalid"}
        cases = {
            "ics": ("owned.ics", product.ics_schreiben_termine([event]), "termine"),
            "lotus": ("owned.csv", product.lotus_csv_schreiben([event]), "termine"),
            "vcf": ("owned.vcf", product.vcf_schreiben([contact]), "kontakte"),
            "ldif": ("owned.ldif", product.ldif_schreiben([contact]), "kontakte"),
            "claws": ("owned.xml", '<?xml version="1.0"?><address-book><person uid="owned" first-name="Owned" last-name="Preview"><address-list><address email="owned@example.invalid"/></address-list></person></address-book>', "kontakte")}
        def inspect(format, path, **extras):
            product.Fenster.bei_import(window, {"requestId": "owned-preview", "art": format, "pfad": str(path), **extras})
            callback, payload = window.replies.pop()
            assert callback == "App.importErgebnis" and payload["requestId"] == "owned-preview"
            return payload
        for format, (name, text, collection) in cases.items():
            path = Path(root) / name; path.write_text(text)
            original = path.read_bytes()
            result = inspect(format, path)
            assert result["ok"] and len(result[collection]) == 1, result
            assert result["bytes"] == len(original) and result["sha256"] == hashlib.sha256(original).hexdigest()
            assert len(result["revision"]) == 64 and inspect(format, path, expectedRevision=result["revision"])["ok"]
            path.write_text(text + "\n")
            stale = inspect(format, path, expectedRevision=result["revision"])
            assert not stale["ok"] and stale["code"] == "conflict"
            assert path.read_bytes() == original + b"\n"
        archive = Path(root) / "owned.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as writer:
            writer.writestr("one.ics", cases["ics"][1])
            writer.writestr("two.ics", cases["ics"][1].replace("owned-event", "owned-event-two"))
        assert len(inspect("ics", archive)["termine"]) == 2
        oversized = Path(root) / "oversized.ics"
        with oversized.open("wb") as writer: writer.truncate(product.IMPORT_DATEI_MAX + 1)
        assert not inspect("ics", oversized)["ok"]
        window._gesperrt = True
        assert not inspect("ics", Path(root) / "owned.ics")["ok"]
