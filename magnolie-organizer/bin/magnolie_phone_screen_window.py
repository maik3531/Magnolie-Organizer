"""Native, view-only GTK window for one phone-to-desktop mirror session (#245)."""

from threading import Lock, current_thread, main_thread

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk


class PhoneScreenWindow:
    """One-shot window owned by the native viewing session, not the main window.

    `is_current` is a nonblocking GTK-thread check on the original viewing
    authority, including lock, disconnection and revocation. `request_stop`
    signals that exact capture owner; it must not block on a worker or claim
    that capture has drained. The session owner, not the window, joins capture.
    `offer_rgb` is for the original decoder worker only, never for a bridge or
    wire handler. Frames are immutable, already oriented, packed RGB888.
    Construction neither shows the window nor starts capture or grants consent.
    """

    def __init__(self, title, *, is_current, request_stop):
        self._require_gtk_thread()
        gi.require_foreign("cairo")
        self._is_current = is_current
        self._request_stop = request_stop
        self._lock = Lock()
        self._pending = None
        self._terminal = False
        self._picture = None
        self.failure = None
        self.stop_error = None
        self._window = Gtk.Window(title=title)
        self._window.set_default_size(480, 640)
        self._canvas = Gtk.DrawingArea()
        self._canvas.connect("draw", self._draw)
        self._window.add(self._canvas)
        self._window.connect("destroy", self._destroyed)
        self._timer = GLib.timeout_add(33, self._tick)

    @staticmethod
    def _require_gtk_thread():
        if current_thread() is not main_thread():
            raise RuntimeError("phone screen window requires the GTK main thread")

    def offer_rgb(self, width, height, pixels):
        # Reject before allocating/copying; keep one newest pending frame.
        if (type(width) is not int or type(height) is not int or
                not 1 <= width <= 4096 or not 1 <= height <= 4096 or
                width * height > 4096 * 2160 or type(pixels) is not bytes or
                len(pixels) != width * height * 3):
            return False
        with self._lock:
            if self._terminal:
                return False
            self._pending = (width, height, pixels)
            return True

    def show(self):
        """Show/raise only this existing session; does not resume or replace it."""
        self._require_gtk_thread()
        if self._window is None or not self._check_current():
            self.stop()
            return False
        self._window.show_all()
        self._window.present()
        return True

    def stop(self):
        """Terminal; shared by exit, privacy lock and the future tray Stop action."""
        self._require_gtk_thread()
        self._retire(destroy=True)

    def _check_current(self):
        try:
            return self._is_current() is True and not self._terminal
        except Exception as error:
            self.failure = error
            return False

    def _retire(self, *, destroy):
        with self._lock:
            if self._terminal:
                return
            self._terminal = True
            self._pending = None
        self._picture = None
        window, self._window = self._window, None
        source, self._timer = self._timer, 0
        try:
            if source:
                GLib.source_remove(source)
            if destroy:
                window.destroy()
        finally:
            try:
                self._request_stop()
            except Exception as error:
                self.stop_error = error

    def _destroyed(self, _window):
        self._retire(destroy=False)

    def _tick(self):
        if not self._check_current():
            self.stop()
            return GLib.SOURCE_REMOVE
        with self._lock:
            frame, self._pending = self._pending, None
        if frame is not None:
            try:
                width, height, pixels = frame
                self._picture = GdkPixbuf.Pixbuf.new_from_bytes(
                    GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB,
                    False, 8, width, height, width * 3)
                self._canvas.queue_draw()
            except Exception as error:
                self.failure = error
                self.stop()
                return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _draw(self, canvas, ctx):
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        if self._terminal or not self._check_current():
            return False
        picture = self._picture
        if picture is not None:
            width, height = picture.get_width(), picture.get_height()
            available_width, available_height = canvas.get_allocated_width(), canvas.get_allocated_height()
            scale = min(available_width / width, available_height / height)
            ctx.translate((available_width - width * scale) / 2, (available_height - height * scale) / 2)
            ctx.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(ctx, picture, 0, 0)
            # Interpolation samples the nearest edge pixel, not transparent
            # pixels outside the image. The rectangle still clips to the frame.
            ctx.get_source().set_extend(cairo.EXTEND_PAD)
            ctx.rectangle(0, 0, width, height)
            ctx.fill()
        return False
