"""Native exact-file/content preconditions use the existing MCP book hash convention."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from modul_laden import quellmodul_laden


def test_native_password_state_and_conflict_guards_preserve_primary(monkeypatch):
    product = quellmodul_laden("owned_password_state", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    with tempfile.TemporaryDirectory(prefix="magnolie-password-state-", dir="/tmp/opencode") as root:
        primary = Path(root) / "owned.json"
        plain = '{"owned":"🌸é\\n"}'
        primary.write_text(plain)
        monkeypatch.setattr(product, "daten_datei", lambda: str(primary))
        class Window:
            _kennwort = ""
            _daten_sperre = threading.RLock()
            _baum_sperre = threading.RLock()
            def __init__(self):
                self.replies = []
            def antwort(self, callback, payload):
                self.replies.append((callback, payload))
        window = Window()
        def inspect():
            product.Fenster._kennwort_status_arbeit(window, {"requestId": "owned-state-request"})
            callback, payload = window.replies.pop()
            assert callback == "App.passwordStand" and payload["requestId"] == "owned-state-request"
            return payload
        initial = inspect()["state"]
        assert not initial["encrypted"]
        assert initial["state_revision"] == hashlib.sha256(plain.encode()).hexdigest()
        assert initial["book_revision"] == "e8ee8f96c8396a7489b1c6575214023125205dc4ae474c0be57d535df8859f1e"
        product.Fenster._kennwort_setzen(window, "owned-new-password", "", request_id="owned-write",
            expected_revision=initial["state_revision"], expected_book_revision="0" * 64)
        assert window.replies.pop()[1]["code"] == "conflict" and primary.read_text() == plain
        product.Fenster._kennwort_entfernen(window, request_id="owned-remove", expected_revision="0" * 64,
            expected_book_revision=initial["book_revision"])
        assert window.replies.pop()[1]["code"] == "conflict" and primary.read_text() == plain
        window._kennwort = "owned-stored-password"
        primary.write_text(product.verschluesseln(plain, window._kennwort))
        encrypted = inspect()["state"]
        assert encrypted["encrypted"] and encrypted["book_revision"] == initial["book_revision"]
        primary.write_text(product.verschluesseln(plain, window._kennwort))
        rewrapped = inspect()["state"]
        assert rewrapped["state_revision"] != encrypted["state_revision"] and rewrapped["book_revision"] == initial["book_revision"]
        window._kennwort = ""
        failure = inspect()
        assert not failure["ok"] and "owned-stored-password" not in json.dumps(failure) and "🌸" not in json.dumps(failure)
