"""Real native planner ODS bytes are written/read back without an office launcher."""
import hashlib
import io
from pathlib import Path
import tempfile
import zipfile

from modul_laden import quellmodul_laden


def test_native_planner_document_export_year_month_and_target_guards(monkeypatch):
    product = quellmodul_laden("owned_planner_export", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    with tempfile.TemporaryDirectory(prefix="magnolie-planner-export-", dir="/tmp/opencode") as root:
        profile = Path(root) / "owned-profile.json"; profile.write_text('{"owned":true}')
        monkeypatch.setattr(product, "daten_datei", lambda: str(profile))
        class Window:
            _gesperrt = False
            def __init__(self): self.replies = []
            def antwort(self, callback, payload): self.replies.append((callback, payload))
        window = Window()
        def export(layout, target, **extra):
            columns = 12 if layout == "year" else 8
            message = {"cmd": "planer_ods", "requestId": "owned-planner", "pfad": str(target), "jahr": 2030, "layout": layout,
                "monat": 2 if layout == "month" else 0, "titel": "Owned planner", "spalten": ["Owned column"] * columns,
                "zeilen": [["Owned entry"] * columns], "stile": [[""] * columns],
                "inhalte": [[{"datum": "1", "eintraege": [{"text": "Owned entry", "farbe": "#112233", "art": "termin"}]} for _ in range(columns)]], **extra}
            product.Fenster._ods_datei_exportieren(window, message)
            callback, payload = window.replies.pop()
            assert callback == "App.documentExportErgebnis" and payload["requestId"] == "owned-planner"
            return payload
        for layout in ("year", "month"):
            target = Path(root) / (layout + ".ods")
            result = export(layout, target)
            assert result["ok"], result
            actual = target.read_bytes()
            assert result["bytes"] == len(actual) and result["sha256"] == hashlib.sha256(actual).hexdigest()
            with zipfile.ZipFile(io.BytesIO(actual)) as archive:
                assert archive.read("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet"
                assert b"Owned entry" in archive.read("content.xml")
            assert not export(layout, target)["ok"] and target.read_bytes() == actual
            assert export(layout, target, overwrite=True)["ok"]
        assert not export("year", profile, overwrite=True)["ok"] and profile.read_text() == '{"owned":true}'
        link = Path(root) / "owned-link.ods"; link.symlink_to(profile)
        assert not export("year", link, overwrite=True)["ok"] and link.is_symlink()
        window._gesperrt = True
        assert not export("year", Path(root) / "locked.ods")["ok"]
