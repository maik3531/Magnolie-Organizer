"""GTK/Xvfb component checks. Frames here are test pixels, not phone capture."""

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
