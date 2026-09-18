"""The real assistant must finish after an optional, failed phone connection."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_setup_ui as ui
from magnolie_setup_state import SetupPhoneServices, classify, write_state
from magnolie_hintergrund import IPCError


def descendants(widget):
    yield widget
    if hasattr(widget, "get_children"):
        for child in widget.get_children():
            yield from descendants(child)


@pytest.mark.parametrize("language", ["de", "en"])
def test_connect_error_then_start_organizer(tmp_path, monkeypatch, language):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
    assert Gtk.init_check()[0], "Requires isolated Xvfb"
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(key, str(tmp_path))
    monkeypatch.setattr(ui, "_read_language", lambda: language)
    monkeypatch.setattr(ui, "_play_welcome_chime", lambda *_: None)
    monkeypatch.setattr(ui, "_persist_language", lambda *_: None)
    tr = ui._translation(language, str(ROOT / "bin"))
    calls, errors, writes = [], [], []
    state = {"attempted": False, "errorSeen": False}
    marker = tmp_path / "setup-state.json"

    def request(op, arguments):
        calls.append(op)
        raise IPCError("Another phone setup session is active.")

    phones = SetupPhoneServices(lambda: str(tmp_path), lambda: "Fixture",
        daemon_active=lambda: True, translate=tr, ipc=request)

    def save(status, selections):
        writes.append(status)
        write_state(status, selections, str(marker))

    deadline = time.monotonic() + 10
    def drive():
        windows = [window for window in Gtk.Window.list_toplevels() if window.get_visible()]
        try:
            assert time.monotonic() < deadline, "Assistant stayed blocked after the phone error"
            message = next((window for window in windows if isinstance(window, Gtk.MessageDialog)), None)
            if message is not None:
                assert message.get_property("text") == tr("Phone connection failed.")
                assert message.get_property("secondary-text") == tr("Another phone setup session is active.")
                state["errorSeen"] = True
                message.response(Gtk.ResponseType.CLOSE)
                return True
            dialog = next(window for window in windows if isinstance(window, Gtk.Dialog))
            widgets = list(descendants(dialog))
            stack = next(widget for widget in widgets if isinstance(widget, Gtk.Stack))
            if stack.get_visible_child_name() == "page-3" and not state["attempted"]:
                state["attempted"] = True
                next(widget for widget in widgets if isinstance(widget, Gtk.Button) and
                     widget.get_label() == tr("Connect phone via WLAN")).clicked()
                return True
            if state["attempted"] and not state["errorSeen"]:
                return True
            button = next(widget for widget in widgets if isinstance(widget, Gtk.Button) and
                          widget.get_label() in (tr("Next"), tr("Start Magnolie")))
            if button.get_sensitive():
                button.clicked()
            return True
        except BaseException as error:
            errors.append(error)
            for window in windows:
                if isinstance(window, Gtk.Dialog):
                    window.response(Gtk.ResponseType.CANCEL)
            return False

    timer = GLib.timeout_add(20, drive)
    try:
        result = ui.run_setup(Gtk, Gdk, tr, save, str(ROOT / "bin"), phone_services=phones)
    finally:
        if not errors:
            GLib.source_remove(timer)
        phones.close()
    if errors:
        raise errors[0]
    assert state == {"attempted": True, "errorSeen": True}
    assert result is not None and result["_phoneForeground"] is False
    assert result["phoneBackgroundServices"] == []
    assert writes == ["complete"] and classify(str(marker)) == "ready"
    assert calls == ["phone_setup_begin"]
