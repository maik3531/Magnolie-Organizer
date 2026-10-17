"""Existing native exchange codecs write and verify owned explicit export files."""
import hashlib
from pathlib import Path
import tempfile

from modul_laden import quellmodul_laden


def test_all_native_exchange_exports_read_back_bytes_and_protect_targets(monkeypatch):
    product = quellmodul_laden("owned_records_export", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    with tempfile.TemporaryDirectory(prefix="magnolie-record-export-", dir="/tmp/opencode") as root:
        profile = Path(root) / "owned-profile.json"; profile.write_text('{"owned":"preserved"}')
        monkeypatch.setattr(product, "daten_datei", lambda: str(profile))
        class Window:
            _gesperrt = False
            def __init__(self): self.replies = []
            def _datei_speichern(self, *_args): raise AssertionError("MCP export opened a GUI file dialog")
            def antwort(self, callback, payload): self.replies.append((callback, payload))
        window = Window()
        appointment = {"id": "owned-event", "titel": "Owned 🌸 export", "datum": "2030-01-02", "zeit": "09:00", "endZeit": "10:00"}
        cases = {
            "ics-termine": [appointment], "csv-termine": [appointment],
            "ics-aufgaben": [{"id": "owned-task", "titel": "Owned task", "faellig": "2030-01-02"}],
            "ics-jahrestage": [{"id": "owned-anniversary", "name": "Owned anniversary", "datum": "2000-01-02", "typ": "birthday"}],
            "vcf-adressen": [{"id": "owned-contact", "vorname": "Owned", "nachname": "Export", "email": "owned@example.invalid"}],
            "ldif-adressen": [{"id": "owned-contact", "vorname": "Owned", "nachname": "Export", "email": "owned@example.invalid"}]}
        def export(format, path, **extras):
            product.Fenster.bei_export(window, {"art": format, "daten": cases.get(format, []), "pfad": str(path), "requestId": "owned-export", **extras})
            callback, payload = window.replies.pop()
            assert callback == "App.exportErgebnis" and payload["requestId"] == "owned-export"
            return payload
        for format in cases:
            target = Path(root) / (format + ".owned")
            result = export(format, target)
            assert result["ok"] and result["anzahl"] == 1, result
            actual = target.read_bytes()
            assert result["bytes"] == len(actual) and result["sha256"] == hashlib.sha256(actual).hexdigest()
            assert actual.startswith(b"\xef\xbb\xbf") == (format == "csv-termine")
            assert not export(format, target)["ok"] and target.read_bytes() == actual
            assert export(format, target, overwrite=True)["ok"]
        assert not export("vcf-adressen", profile, overwrite=True)["ok"]
        assert profile.read_text() == '{"owned":"preserved"}'
        link = Path(root) / "owned-link.vcf"; link.symlink_to(profile)
        assert not export("vcf-adressen", link, overwrite=True)["ok"] and link.is_symlink()
        window._gesperrt = True
        denied = Path(root) / "owned-denied.vcf"
        assert not export("vcf-adressen", denied)["ok"] and not denied.exists()
        assert export("arbitrary-format", denied)["code"] == "unsupported_feature"
