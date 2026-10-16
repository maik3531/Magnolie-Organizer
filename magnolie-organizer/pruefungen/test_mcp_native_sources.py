"""Exercise the actual native source aggregation method with owned backend fixtures."""
import ast
from pathlib import Path
import re
import tempfile
import threading


def test_attachment_open_rejects_failed_launcher_and_locked_profile(monkeypatch):
    import base64
    from modul_laden import quellmodul_laden
    source = Path(__file__).parents[1] / "bin/magnolie-organizer"
    product = quellmodul_laden("owned_mcp_attachment_open", str(source))
    with tempfile.TemporaryDirectory(prefix="magnolie-mcp-open-", dir="/tmp/opencode") as root:
        class Window:
            _gesperrt = False
            _daten_sperre = threading.RLock()
            _notiz_anhang_temp = root
            def __init__(self):
                self.replies = []
            def antwort(self, callback, payload):
                self.replies.append((callback, payload))
        window = Window()
        monkeypatch.setattr(product.shutil, "which", lambda _name: "/usr/bin/false")
        args = {"id": 1, "requestId": "owned-launch-request", "aktion": "open", "name": "owned.pdf",
            "daten": "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\nowned fixture\n").decode()}
        product.Fenster.bei_notiz_anhang_datei(window, args)
        callback, reply = window.replies.pop()
        assert callback == "App.notizAnhangDateiErgebnis" and reply["requestId"] == args["requestId"]
        assert not reply["ok"] and not reply.get("launched")
        files = list(Path(root).iterdir())
        assert len(files) == 1
        window._gesperrt = True
        product.Fenster.bei_notiz_anhang_datei(window, args)
        assert not window.replies.pop()[1]["ok"] and list(Path(root).iterdir()) == files


def test_parallel_dictionary_workers_preserve_both_persistent_additions(monkeypatch):
    from modul_laden import quellmodul_laden
    source = Path(__file__).parents[1] / "bin/magnolie-organizer"
    product = quellmodul_laden("owned_mcp_dictionary_workers", str(source))
    with tempfile.TemporaryDirectory(prefix="magnolie-mcp-dictionary-", dir="/tmp/opencode") as root:
        dictionary_file = Path(root) / "owned-words.txt"
        dictionary_file.write_text("")
        first_entered = threading.Event()
        release_first = threading.Event()
        overlaps = []
        replies = []
        class Dictionary:
            def add(self, word):
                if word == "ownedtwo" and not release_first.is_set():
                    overlaps.append(word)
                words = set(dictionary_file.read_text().splitlines())
                if word == "ownedone":
                    first_entered.set()
                    assert release_first.wait(3)
                words.add(word)
                dictionary_file.write_text("\n".join(sorted(words)) + "\n")
        class Window:
            def antwort(self, callback, payload):
                replies.append((callback, payload))
        dictionary = Dictionary()
        monkeypatch.setattr(product, "woerterbuch_laden", lambda _language: dictionary)
        window = Window()
        first = threading.Thread(target=product.Fenster._wort_merken_arbeit, args=(window, {"wort": "ownedone", "requestId": "owned-one"}))
        first.start()
        assert first_entered.wait(2)
        timer = threading.Timer(0.5, release_first.set)
        timer.start()
        try:
            product.Fenster._wort_merken_arbeit(window, {"wort": "ownedtwo", "requestId": "owned-two"})
        finally:
            release_first.set(); timer.cancel(); first.join(timeout=3)
        assert not first.is_alive() and overlaps == []
        assert set(dictionary_file.read_text().splitlines()) == {"ownedone", "ownedtwo"}
        assert {value["requestId"] for _callback, value in replies} == {"owned-one", "owned-two"}
        assert all(value["ok"] for _callback, value in replies)


def test_native_source_reply_preserves_request_identity_and_aggregated_sources():
    source = Path(__file__).parents[1] / "bin/magnolie-organizer"
    tree = ast.parse(source.read_text())
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Fenster")
    method = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == "_eds_status_arbeit")
    namespace = {"re": re, "EDS_PAKETE": ["owned-fixture"], "eds_laden": lambda: False,
        "_EDS": {"fehler": "Owned offline registry"}, "fehler_deutsch": str,
        "nextcloud_status": lambda: {"kalender": [{"uid": "owned-calendar"}], "adressbuecher": []},
        "akonadi_quellen_status": lambda: {"kalender": [], "adressbuecher": [{"uid": "owned-addressbook"}]}}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    replies = []
    class Window:
        def antwort(self, callback, value):
            replies.append((callback, value))
    request_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    namespace["_eds_status_arbeit"](Window(), request_id)
    callback, payload = replies.pop()
    assert callback == "App.edsStatus" and payload["requestId"] == request_id
    assert payload["alleKalender"] == [{"uid": "owned-calendar", "quelle": "nextcloud"}]
    assert payload["alleAdressbuecher"] == [{"uid": "owned-addressbook", "quelle": "akonadi"}]
    # Existing UI callers remain valid and do not acquire an unrelated request ID.
    namespace["_eds_status_arbeit"](Window())
    assert "requestId" not in replies.pop()[1]


def test_native_recovery_status_correlates_success_and_failure_without_breaking_ui_callers():
    source = Path(__file__).parents[1] / "bin/magnolie-organizer"
    tree = ast.parse(source.read_text())
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Fenster")
    method = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == "_journal_stand_melden")
    namespace = {"journal_liste": lambda **_args: [], "_journal_aufbewahrung": lambda _value: ("count", 20, 14),
        "JOURNAL_INTERVALLE": {"manual": 0, "weekly": 604800}, "_": lambda value: value,
        "fehler_deutsch": lambda error, _context: str(error)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    replies = []
    class Window:
        _kennwort = ""
        _aktuelle_daten = {"einstellungen": {"allgemein": {"wiederherstellungsintervall": "manual"}}}
        def antwort(self, callback, value):
            replies.append((callback, value))
    request_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    namespace["_journal_stand_melden"](Window(), request_id)
    callback, payload = replies.pop()
    assert callback == "App.journalStand" and payload["requestId"] == request_id and payload["ok"]
    assert payload["interval"] == "manual" and payload["snapshots"] == []
    namespace["_journal_stand_melden"](Window())
    assert replies.pop()[1].get("requestId") is None
    def fail(**_args):
        raise RuntimeError("Owned journal failure")
    namespace["journal_liste"] = fail
    namespace["_journal_stand_melden"](Window(), request_id)
    callback, payload = replies.pop()
    assert callback == "App.journalStand" and payload["requestId"] == request_id and not payload["ok"]


def test_recovery_delete_checks_all_selected_revisions_before_any_removal():
    from modul_laden import quellmodul_laden
    import copy
    from collections import namedtuple
    source = Path(__file__).parents[1] / "bin/magnolie-organizer"
    product = quellmodul_laden("owned_mcp_recovery_revision", str(source))
    disk = namedtuple("Disk", "total used free")(100 * 1024 ** 3, 0, 10 * 1024 ** 3)
    with tempfile.TemporaryDirectory(prefix="magnolie-mcp-recovery-revisions-", dir="/tmp/opencode") as root:
        data = {"version": 6, "notizen": [{"id": "owned", "text": "First"}], "einstellungen": {}}
        first = product.journal_snapshot_erzeugen(data, "manual", basis=root, disk_usage=lambda _path: disk)
        data = copy.deepcopy(data)
        data["notizen"][0]["text"] = "Second"
        second = product.journal_snapshot_erzeugen(data, "manual", basis=root, disk_usage=lambda _path: disk)
        ids = [first["snapshotId"], second["snapshotId"]]
        assert len(set(ids)) == 2
        expected = {id: product.journal_snapshot_revision(id, root) for id in ids}
        assert product.journal_snapshot_lesen(ids[0], basis=root, expected_revision=expected[ids[0]])[0]["snapshotId"] == ids[0]
        payload = Path(second["path"]) / second["payload"].get("file", "payload.magnolie")
        with payload.open("ab") as stream:
            stream.write(b"owned tamper")
        try:
            product.journal_snapshot_lesen(ids[1], basis=root, expected_revision=expected[ids[1]])
            assert False, "A stale restore revision read a changed snapshot"
        except RuntimeError as error:
            assert str(error) == "snapshot_conflict"
        try:
            product.journal_snapshots_loeschen(ids, root, expected)
            assert False, "Stale revisions were accepted"
        except RuntimeError as error:
            assert str(error) == "snapshot_conflict"
        assert all(Path(snapshot["path"]).is_dir() for snapshot in (first, second))
        current = {id: product.journal_snapshot_revision(id, root) for id in ids}
        assert current[ids[1]] != expected[ids[1]]
        assert product.journal_snapshots_loeschen(ids, root, current) == 2
