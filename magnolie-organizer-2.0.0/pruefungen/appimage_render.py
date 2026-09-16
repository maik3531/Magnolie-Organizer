"""Require a real WebKit web process, JavaScript and laid-out content."""
import sys
import os
from pathlib import Path
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, WebKit2

window = Gtk.Window()
window.set_default_size(640, 480)
view = WebKit2.WebView()
window.add(view)
passed = False


def snapshot_finished(webview, result, unused):
    global passed
    try:
        surface = webview.get_snapshot_finish(result)
        surface.flush()
        offset = 100 * surface.get_stride() + 290 * 4
        pixel = bytes(surface.get_data())[offset:offset + 4]
        painted = pixel == bytes((56, 34, 12, 255))
        passed = passed and painted
        print('APPIMAGE WEBKIT WAYLAND SNAPSHOT PIXEL', painted, list(pixel), flush=True)
    except Exception as error:
        passed = False
        print('APPIMAGE WEBKIT SNAPSHOT ERROR', error, flush=True)
    finally:
        Gtk.main_quit()


def finished(webview, result, unused):
    global passed
    snapshot_pending = False
    try:
        passed = webview.evaluate_javascript_finish(result).to_boolean()
        processes = {}
        for path in Path('/proc').glob('[0-9]*/status'):
            try:
                status = dict(line.split(':', 1) for line in path.read_text().splitlines())
                processes[int(path.parent.name)] = status
            except (OSError, ValueError):
                continue
        sandboxed = False
        for pid, status in processes.items():
            if not status.get('Name', '').strip().startswith('WebKitWebProces'):
                continue
            parent = int(status['PPid'])
            seen = set()
            while parent in processes and parent not in seen and parent != os.getpid():
                seen.add(parent)
                parent = int(processes[parent]['PPid'])
            if parent == os.getpid():
                sandboxed |= (status.get('NoNewPrivs', '').strip() == '1' and
                              status.get('Seccomp', '').strip() == '2' and
                              len(status.get('NSpid', '').split()) > 1)
        passed = passed and sandboxed
        print('APPIMAGE WEB PROCESS SANDBOX', sandboxed, flush=True)
        if Gdk.Display.get_default().__gtype__.name == 'GdkWaylandDisplay':
            # Wayland disallows reading a window through the X11-style Gdk API.
            webview.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE,
                                 None, snapshot_finished, None)
            snapshot_pending = True
            return
        # Sample the solid background, away from the foreground text glyphs.
        pixels = Gdk.pixbuf_get_from_window(view.get_window(), 290, 100, 1, 1)
        painted = pixels is not None and bytes(pixels.get_pixels())[:3] == bytes((12, 34, 56))
        passed = passed and painted
        print('APPIMAGE WEBKIT PAINTED PIXEL', painted,
              list(pixels.get_pixels()) if pixels is not None else None, flush=True)
    finally:
        if not snapshot_pending:
            Gtk.main_quit()


def loaded(webview, event):
    if event == WebKit2.LoadEvent.FINISHED:
        GLib.timeout_add(1000, measure, webview)


def measure(webview):
    webview.evaluate_javascript(
            "document.querySelector('#render').getBoundingClientRect().width === 320 && "
            "document.querySelector('#render').getBoundingClientRect().height === 120 && "
            "getComputedStyle(document.querySelector('#render')).backgroundColor === 'rgb(12, 34, 56)'",
            -1, None, None, None, finished, None)
    return False


view.connect("load-changed", loaded)
view.connect("web-process-terminated", lambda *args: Gtk.main_quit())
window.show_all()
view.load_html('<!doctype html><div id="render" style="width:320px;height:120px;'
               'background:rgb(12,34,56)">AppImage WebKit render</div>', "https://appimage.test/")
GLib.timeout_add_seconds(30, lambda: (Gtk.main_quit(), False)[1])
Gtk.main()
window.destroy()
print("APPIMAGE WEBKIT RENDER " + ("PASS" if passed else "FAIL"), flush=True)
sys.exit(0 if passed else 1)
