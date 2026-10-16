"""Exercise the actual native source aggregation method with owned backend fixtures."""
import ast
from pathlib import Path
import re


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
