"""Correlated native dialog lifecycle, including load timeout and late FINISHED."""
from pathlib import Path
from types import SimpleNamespace

from modul_laden import quellmodul_laden


def test_print_receipt_waits_for_real_dialog_and_timeout_blocks_late_dialog(monkeypatch, tmp_path):
    product = quellmodul_laden("owned_print_test", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    views, timers, replies, dialogs = [], [], [], []
    class View:
        def __init__(self):
            self.handlers = {}; views.append(self)
        def get_settings(self): return SimpleNamespace(set_enable_javascript=lambda value: None)
        def connect(self, name, callback): self.handlers[name] = callback
        def load_uri(self, uri): self.uri = uri
        def stop_loading(self): self.stopped = True
    class PrintOperation:
        @staticmethod
        def new(view):
            return SimpleNamespace(run_dialog=lambda parent: dialogs.append(view) or "cancel")
    monkeypatch.setattr(product, "WebKit2", SimpleNamespace(WebView=View, LoadEvent=SimpleNamespace(FINISHED="finished"),
        PrintOperation=PrintOperation, PrintOperationResponse=SimpleNamespace(PRINT="print")))
    monkeypatch.setattr(product, "WEBKIT_OK", True)
    monkeypatch.setattr(product, "anzeige_bereit", lambda: True)
    monkeypatch.setattr(product.GLib, "timeout_add_seconds", lambda seconds, callback: timers.append(callback))
    result = product.drucken("<html>Owned print fixture</html>", ordner=str(tmp_path), rueckmeldung=replies.append)
    assert result["ok"] and not replies and not dialogs
    view = views[-1]
    view.handlers["load-changed"](view, "finished")
    assert replies == [{"ok": True, "stage": "dialog_returned", "dialogAction": "cancel"}] and dialogs == [view]
    view.handlers["load-changed"](view, "finished")
    assert len(replies) == 1 and len(dialogs) == 1
    timers[-1](); assert len(replies) == 1
    replies.clear()
    product.drucken("<html>Owned stalled fixture</html>", ordner=str(tmp_path), rueckmeldung=replies.append)
    late = views[-1]; timers[-1]()
    late.handlers["load-changed"](late, "finished")
    assert late.stopped and replies == [{"ok": False, "code": "native_timeout"}] and len(dialogs) == 1
    replies.clear()
    product.drucken("<html>Owned failed fixture</html>", ordner=str(tmp_path), rueckmeldung=replies.append)
    failed = views[-1]
    failed.handlers["load-failed"](failed, "started", "owned-uri", "owned-private-error")
    failed.handlers["load-changed"](failed, "finished")
    assert replies == [{"ok": False, "code": "native_operation_failed"}] and len(dialogs) == 1
    monkeypatch.setattr(product, "WEBKIT_OK", False)
    monkeypatch.setattr(product.shutil, "which", lambda _name: (_ for _ in ()).throw(AssertionError("No viewer fallback for correlated print")))
    assert product.drucken("<html>Owned unavailable fixture</html>", ordner=str(tmp_path), rueckmeldung=replies.append) == {"ok": False, "code": "native_unavailable"}


def test_native_print_request_has_bounded_input_and_does_not_start_second_dialog(monkeypatch):
    product = quellmodul_laden("owned_print_window_test", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    class Window:
        def __init__(self): self.replies = []
        def antwort(self, callback, value): self.replies.append((callback, value))
    window = Window(); pending = []
    monkeypatch.setattr(product, "drucken", lambda html, **kwargs: pending.append(kwargs["rueckmeldung"]) or {"ok": True, "ansicht": object()})
    product.Fenster._drucken(window, "🌸" * 190000, "oversized")
    assert not pending and window.replies[-1][1]["code"] == "invalid_settings"
    product.Fenster._drucken(window, "<html>Owned fixture</html>", "first")
    assert len(pending) == 1 and window._mcp_druck_aktiv
    product.Fenster._drucken(window, "<html>Owned fixture</html>", "second")
    assert len(pending) == 1 and window.replies[-1][1]["code"] == "native_busy" and window._mcp_druck_aktiv
    pending[0]({"ok": True, "stage": "dialog_returned", "dialogAction": "cancel"})
    assert not window._mcp_druck_aktiv and window.replies[-1][0] == "App.printErgebnis" and window.replies[-1][1]["requestId"] == "first"
