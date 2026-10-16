"""Actual owned journal/profile writes around restore commit and repair failures."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import uuid

import pytest

from modul_laden import quellmodul_laden


@pytest.mark.parametrize("failure", [None, "before-write", "after-rename", "projection"])
def test_restore_reports_actual_commit_state(failure):
    source = Path(__file__).parents[1] / "bin/magnolie-organizer"
    product = quellmodul_laden("owned_restore_commit_" + uuid.uuid4().hex, str(source))
    with tempfile.TemporaryDirectory(prefix="magnolie-restore-commit-", dir="/tmp/opencode") as directory:
        data_file = Path(directory) / "daten.json"
        data = {"version": 6, "notizen": [{"id": "owned-note", "titel": "Owned", "text": "snapshot"}],
            "termine": [], "aufgaben": [], "kontakte": [], "jahrestage": [], "papierkorb": [],
            "tombstones": [], "einstellungen": {"sync": {}, "allgemein": {}}}
        target = product.journal_snapshot_erzeugen(data, "manual", basis=directory)
        reader = product.journal_snapshot_lesen
        product.journal_snapshot_lesen = lambda id, password, **kwargs: reader(id, password, basis=directory, **kwargs)
        product.daten_datei = lambda: str(data_file)
        writer = product.atomar_text_schreiben

        class Window:
            _daten_sperre = threading.RLock()
            _kennwort = ""
            _telefon = None
            _operation_laeuft = False
            _sync_laeuft = False

            def __init__(self):
                self._aktuelle_daten = copy.deepcopy(data)
                self._aktuelle_daten["notizen"][0]["text"] = "current"
                self.replies = []
                self.previous = None

            def _journal_snapshot(self, reason):
                self.previous = product.journal_snapshot_erzeugen(self._aktuelle_daten, reason, basis=directory)
                return self.previous

            def _vielleicht_verschluesseln(self, text):
                return text

            def _erinnerungsprojektion_aktualisieren(self):
                if failure == "projection":
                    raise OSError("Owned projection write failure")

            def _journal_stand_melden(self):
                pass

            def antwort(self, callback, payload):
                self.replies.append((callback, payload))

        window = Window()
        writer(str(data_file), json.dumps(window._aktuelle_daten))

        def write(path, text):
            if path == str(data_file) and failure == "before-write":
                raise OSError("Owned pre-commit failure")
            writer(path, text)
            if path == str(data_file) and failure == "after-rename":
                raise OSError("Owned post-rename failure")

        product.atomar_text_schreiben = write
        product.Fenster._journal_wiederherstellen(window, target["snapshotId"], ["notes"], "replace")
        result = next(value for callback, value in window.replies if callback == "App.journalWiederhergestellt")
        written = json.loads(data_file.read_text())
        committed = failure != "before-write"
        assert result["ok"] is committed and result["committed"] is committed
        assert written["notizen"][0]["text"] == ("snapshot" if committed else "current")
        assert window._aktuelle_daten["notizen"][0]["text"] == written["notizen"][0]["text"]
        if committed:
            assert result["daten"] == written
            assert result["repairPending"] is (failure is not None)
        _, previous = reader(window.previous["snapshotId"], basis=directory)
        assert previous["daten"]["notizen"][0]["text"] == "current"
        assert any(callback == "App.syncFehler" for callback, _value in window.replies) is (failure in ("projection", "after-rename"))
