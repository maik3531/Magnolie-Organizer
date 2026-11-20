"""GTK/Xvfb component checks. Frames here are test pixels, not phone capture."""

import ast
import json
import sys
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import pytest

pytest.importorskip("gi")
pytest.importorskip("cairo")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_phone_screen_window import Gdk, GLib, Gtk, PhoneScreenWindow


@pytest.fixture(autouse=True)
def display():
    if not Gtk.init_check()[0]:
        pytest.skip("GTK display required (run with xvfb-run)")


def wait_for(condition):
    context = GLib.MainContext.default()
    deadline = monotonic() + 3
    while monotonic() < deadline:
        while context.pending() and monotonic() < deadline:
            context.iteration(False)
        if condition():
            return
        sleep(.005)
    assert condition(), "GTK condition timed out"


def pixel(widget, x, y):
    pixbuf = Gdk.pixbuf_get_from_window(widget.get_window(), x, y, 1, 1)
    return tuple(pixbuf.get_pixels()[:3]) if pixbuf else None


def test_independent_window_letterbox_latest_frames_and_show_again():
    stops = []
    main = Gtk.Window(title="Test Organizer")
    view = PhoneScreenWindow("Test phone view", is_current=lambda: True,
                             request_stop=lambda: stops.append("original"))
    window = view._window
    try:
        main.show_all()
        assert not window.get_visible()
        assert window.get_transient_for() is None and view.show()
        assert view.offer_rgb(4, 3, b"\xff\x00\x00" * 12)
        assert view.offer_rgb(4, 3, b"\x00\xff\x00" * 12)
        wait_for(lambda: pixel(window, 240, 320) == (0, 255, 0))
        assert pixel(window, 240, 16) == (0, 0, 0)

        main.hide()  # Same visibility change as hide-to-tray, not shutdown.
        assert not main.get_visible() and window.get_visible()
        # New aspect (already oriented by the sender/decoder) and new pixels.
        assert view.offer_rgb(2, 5, b"\x00\x00\xff" * 10)
        wait_for(lambda: pixel(window, 240, 16) == (0, 0, 255))
        assert pixel(window, 16, 320) == (0, 0, 0)
        window.hide()
        assert view.show() and view._window is window
        assert window.get_visible() and stops == []
        window.close()
        wait_for(lambda: stops == ["original"])
        assert not view.show() and not window.get_visible()
    finally:
        view.stop()
        main.destroy()


@pytest.mark.parametrize("reason", ["disconnect", "revocation", "lock", "exit"])
def test_terminal_stop_rejects_late_frames_and_never_reopens(reason):
    active = True
    stops = []
    view = PhoneScreenWindow("Test phone view", is_current=lambda: active,
                             request_stop=lambda: stops.append("original"))
    window = view._window
    try:
        assert view.show()
        assert view.offer_rgb(1, 1, b"rgb")
        if reason in ("lock", "exit"):
            view.stop()
        else:
            active = False
        wait_for(lambda: stops == ["original"])
        late = []
        worker = Thread(target=lambda: late.append(view.offer_rgb(1, 1, b"rgb")))
        worker.start()
        worker.join(1)
        assert late == [False] and not window.get_visible()
        assert view._picture is None and view._pending is None and view._timer == 0
        active = True
        assert not view.show() and stops == ["original"]
    finally:
        view.stop()


def test_invalid_frame_and_failed_stop_do_not_revive_the_window():
    requested = []
    failure = OSError("controlled failure requesting capture stop")

    def stop_owner():
        requested.append("original")
        view.stop()  # Reentrant stop must not recurse or signal twice.
        raise failure

    view = PhoneScreenWindow("Test phone view", is_current=lambda: True, request_stop=stop_owner)
    try:
        for width, height, pixels in ((0, 1, b""), (1, 4097, b""), (4096, 4096, b""),
                                      (True, 1, b"rgb"), (1, 1, b"ab"), (1, 1, bytearray(b"rgb"))):
            assert not view.offer_rgb(width, height, pixels)
        view.stop()
        assert requested == ["original"] and view.stop_error is failure
        assert not view.show()
    finally:
        view.stop()


def organizer_hooks():
    # Execute the exact Fenster methods without loading a profile, bridge,
    # phone or desktop service. The menu items and view are actual GTK widgets.
    source = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
    code = ast.parse(source.read_text())
    window = next(node for node in code.body if isinstance(node, ast.ClassDef) and node.name == "Fenster")
    names = {"_phone_screen_attach", "_phone_screen_stop", "_phone_screen_drained",
             "_tray_telefone_aktualisieren", "_beenden_endgueltig"}
    hooks = ast.Module(body=[node for node in window.body if isinstance(node, ast.FunctionDef) and node.name in names],
                       type_ignores=[])
    namespace = {"Gtk": Gtk, "GLib": GLib, "_": lambda text: text}
    exec(compile(hooks, str(source), "exec"), namespace)
    return type("OrganizerHooks", (), {name: namespace[name] for name in names})()


def test_actual_organizer_menu_and_exit_use_exact_window_and_wait_for_join():
    app = organizer_hooks()
    app._gesperrt = app._wirklich_beenden = app._beenden_angefragt = False
    app._telefon = None
    app._tray_telefone = Gtk.MenuItem(label="Phones")
    requested = []
    current = True

    def attach():
        return app._phone_screen_attach(is_current=lambda: current, request_stop=requested.append)

    def actions():
        return {child.get_label(): child for child in app._tray_telefone.get_submenu().get_children()}

    first = attach()
    second = None
    try:
        assert set(actions()) == {"Show phone screen", "Stop screen mirroring"}
        assert app._tray_telefone.get_visible()
        first._window.hide()
        actions()["Show phone screen"].activate()
        assert first._window.get_visible()
        old_menu = app._tray_telefone.get_submenu()
        stale_stop = actions()["Stop screen mirroring"]
        stale_stop.activate()
        assert requested == [first] and not first.available
        assert app._beenden_endgueltig() is True and not app._wirklich_beenden
        with pytest.raises(PermissionError):
            attach()
        wait_for(lambda: not actions() and not app._tray_telefone.get_visible())

        app._phone_screen_drained(first)
        second = attach()
        app._phone_screen_drained(first)
        stale_stop.activate()
        assert old_menu is not app._tray_telefone.get_submenu()
        assert second.available and requested == [first]
        app._gesperrt = True
        wait_for(lambda: requested == [first, second])
        assert not second.available
        app._phone_screen_drained(second)
        with pytest.raises(PermissionError):
            attach()
    finally:
        app._phone_screen_stop()
        app._tray_telefone.destroy()


def test_viewer_source_is_in_linux_package_recipes():
    root = Path(__file__).resolve().parents[1]
    for name in ("debian/install", "rpm/magnolie-organizer.spec", "werkzeuge/appimage_bauen.sh"):
        assert "magnolie_phone_screen_window.py" in (root / name).read_text(), name
    flatpak = json.loads((root / "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json").read_text())
    assert any("magnolie_phone_screen_window.py" in command for module in flatpak["modules"] if isinstance(module, dict)
               for command in module.get("build-commands", []))
