#!/usr/bin/env python3
"""Native XTest probe confined to a fresh xvfb-run display and one Gtk window."""
import ctypes
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_kde_input import InputTarget
from magnolie_kde_input_x11 import X11Input


def main():
    assert len(sys.argv) == 3 and sys.argv[1] == '--isolated-xvfb'
    assert '/xvfb-run.' in os.environ.get('XAUTHORITY', ''), 'Fresh xvfb-run display required'
    assert os.environ.get('DISPLAY') != os.environ.get('MAGNOLIE_INPUT_PARENT_DISPLAY'), 'User display is forbidden'
    library = Path(sys.argv[2]).resolve(strict=True)
    assert library.is_file()
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk
    window = Gtk.Window(title='Magnolie isolated remote-input fixture')
    window.set_default_size(400, 200); window.move(100, 100)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
    box.set_border_width(20)
    entry = Gtk.Entry(); entry.set_text('Synthetic fixture')
    box.pack_start(entry, False, False, 0); window.add(box)
    keys = []
    window.connect('key-press-event', lambda _, event: keys.append(event.keyval) or False)
    window.show_all()
    deadline = time.monotonic() + 12

    def pump(predicate):
        while time.monotonic() < deadline:
            while Gtk.events_pending(): Gtk.main_iteration_do(False)
            if predicate(): return
            time.sleep(0.01)
        raise TimeoutError('Native fixture event timeout')

    sink = X11Input(fakekey_library=str(library))
    target = InputTarget(sink)
    owner, token, permitted = object(), str(uuid.uuid4()), [True]
    try:
        pump(lambda: window.get_window() is not None)
        assert sink.status()['keyboard'] is True
        target.arm(owner, token, lambda: permitted[0])
        origin = window.get_window().get_origin()
        allocation = entry.get_allocation()
        target.accept(owner, {'x': origin[-2] + allocation.x + 30, 'y': origin[-1] + allocation.y + 10})
        target.accept(owner, {'singleclick': True})
        pump(entry.has_focus)
        target.accept(owner, {'key': 'a', 'ctrl': True})
        target.accept(owner, {'key': 'ä😀'})
        pump(lambda: entry.get_text() == 'ä😀')
        target.accept(owner, {'specialKey': 25})
        target.accept(owner, {'specialKey': 9})
        pump(lambda: Gdk.KEY_F5 in keys and Gdk.KEY_Page_Down in keys)
        x = sink.x
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]; x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            *([ctypes.POINTER(ctypes.c_int)] * 4), ctypes.POINTER(ctypes.c_uint)]
        x.XQueryPointer.restype = ctypes.c_int

        def held():
            root, child = ctypes.c_ulong(), ctypes.c_ulong()
            axes = [ctypes.c_int() for _ in range(4)]; mask = ctypes.c_uint()
            assert x.XQueryPointer(sink.display, x.XDefaultRootWindow(sink.display),
                ctypes.byref(root), ctypes.byref(child), *(ctypes.byref(value) for value in axes), ctypes.byref(mask))
            return bool(mask.value & (1 << 8))

        target.accept(owner, {'singlehold': True}); pump(held)
        permitted[0] = False
        assert target.expire(), 'Expired GUI target not released without another input packet'
        pump(lambda: not held())
        assert not target.accept(owner, {'key': 'stale'}) and entry.get_text() == 'ä😀'
        print('PASS: isolated native X11/XTest/libfakekey pointer/click/Ctrl+A/Unicode/F5/PageDown/drag release on target expiry')
    finally:
        target.disarm(); sink.close(); window.destroy()


if __name__ == '__main__':
    main()
