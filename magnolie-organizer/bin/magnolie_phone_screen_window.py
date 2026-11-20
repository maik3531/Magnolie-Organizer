"""Native, view-only GTK window for one phone-to-desktop mirror session (#245)."""

from threading import Lock, current_thread, main_thread

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk


class PhoneScreenSessionLock:
    """Observe this desktop's own logind session without starting any service.

    Unknown state is unavailable. Once a lease has observed lock/session loss,
    unlocking cannot make that original mirror lease current again.
    """

    _SERVICE = 'org.freedesktop.login1'
    _SESSION = 'org.freedesktop.login1.Session'

    def __init__(self):
        self._lease = None
        self._proxy = None
        self._signals = ()
        self._closed = False
        self._lock_signalled = False
        self._cancel = Gio.Cancellable()

    def start(self):
        Gio.bus_get(Gio.BusType.SYSTEM, self._cancel, self._got_bus)
        return self

    def _got_bus(self, _bus, result):
        if self._closed:
            return
        try:
            bus = Gio.bus_get_finish(result)
            if bus is None:
                return
            import os
            bus.call(self._SERVICE, '/org/freedesktop/login1', 'org.freedesktop.login1.Manager', 'GetSessionByPID',
                     GLib.Variant('(u)', (os.getpid(),)), GLib.VariantType.new('(o)'), Gio.DBusCallFlags.NO_AUTO_START,
                     500, self._cancel, self._got_session)
        except GLib.Error:
            pass

    def _got_session(self, bus, result):
        if self._closed:
            return
        try:
            path, = bus.call_finish(result).unpack()
            Gio.DBusProxy.new(bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                             self._SERVICE, path, self._SESSION, self._cancel, self._got_proxy)
        except GLib.Error:
            pass

    def _got_proxy(self, _proxy, result):
        if self._closed:
            return
        try:
            proxy = Gio.DBusProxy.new_finish(result)
        except GLib.Error:
            return
        self._proxy = proxy
        self._signals = (proxy.connect('g-properties-changed', self._properties),
                         proxy.connect('notify::g-name-owner', self._owner_changed),
                         proxy.connect('g-signal', self._signal),
                         proxy.get_connection().connect('closed', self._bus_closed))
        self._update(proxy)

    def _properties(self, proxy, changes, _invalidated):
        if proxy is self._proxy and changes.lookup_value('LockedHint', None) is not None:
            self._lock_signalled = changes.lookup_value('LockedHint', None).unpack() is not False
        self._update(proxy)

    def _owner_changed(self, proxy, *_):
        self._lease = None
        self._lock_signalled = False
        self._update(proxy)

    def _signal(self, proxy, sender, name, _parameters):
        # Lock and Unlock are requests to the session manager. Lock may
        # revoke immediately; only a fresh LockedHint can clear that latch.
        if proxy is self._proxy and sender == proxy.get_name_owner() and name == 'Lock':
            self._lock_signalled = True
            self._lease = None

    def _bus_closed(self, *_):
        self._lease = None

    def _update(self, proxy):
        if self._closed or self._lock_signalled or proxy is not self._proxy or proxy.get_name_owner() is None:
            self._lease = None
            return
        lock, active = (proxy.get_cached_property(key) for key in ('LockedHint', 'Active'))
        if lock is not None and lock.unpack() is False and active is not None and active.unpack() is True:
            if self._lease is None:
                self._lease = object()
        else:
            self._lease = None

    def claim(self):
        lease = self._lease
        if lease is None:
            raise PermissionError('phone_screen_desktop_lock_state_unavailable')

        def current():
            if self._lease is not lease:
                raise PermissionError('phone_screen_desktop_session_locked_or_replaced')
        return current

    @property
    def available(self):
        return self._lease is not None

    def close(self):
        self._closed = True
        self._lease = None
        self._cancel.cancel()
        proxy, self._proxy = self._proxy, None
        if proxy is not None:
            for identifier in self._signals[:3]:
                proxy.disconnect(identifier)
            proxy.get_connection().disconnect(self._signals[3])


class PhoneScreenJpegReceiver:
    """Synchronous decoder for one original, authenticated viewing worker.

    Receives already authenticated payloads at its agreed dimensions. This is
    not an entry point for direct packet, browser, or file input. No queue,
    persistence, auto-rotation from JPEG metadata, or alternate codec.
    """

    MAX_BYTES = 1_048_576

    def __init__(self, width, height, *, is_current, offer_rgb):
        if (type(width) is not int or type(height) is not int or
                not 2 <= width <= 1920 or not 2 <= height <= 1920 or width * height > 1920 * 1080):
            raise ValueError("phone_screen_jpeg_dimensions")
        self._size = (width, height)
        self._is_current = is_current
        self._offer_rgb = offer_rgb

    def _require_current(self):
        if self._is_current() is not True:
            raise PermissionError("phone_screen_jpeg_not_current")

    def _validate_header(self, data):
        if (type(data) is not bytes or not 14 <= len(data) <= self.MAX_BYTES or
                not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9")):
            raise ValueError("phone_screen_jpeg_envelope")
        # Check the advertised shape *before* presenting bytes to libjpeg.
        # The Android sender emits 8-bit, three-component baseline JPEGs.
        at, found = 2, False
        while at < len(data) - 4:
            if data[at] != 0xff:
                break
            at += 1
            while at < len(data) and data[at] == 0xff:
                at += 1
            if at + 3 > len(data) - 2:
                break
            marker = data[at]
            length = int.from_bytes(data[at + 1:at + 3], "big")
            end = at + 1 + length
            if length < 2 or end > len(data) - 2:
                break
            if marker == 0xc0:
                if found or length != 17 or data[at + 3] != 8 or data[at + 8] != 3:
                    break
                height = int.from_bytes(data[at + 4:at + 6], "big")
                width = int.from_bytes(data[at + 6:at + 8], "big")
                if (width, height) != self._size:
                    break
                found = True
            elif marker == 0xda:  # First baseline scan.
                if found and length == 12 and data[at + 3] == 3 and end < len(data) - 2:
                    return
                break
            elif marker not in (0xc4, 0xdb, 0xdd, 0xfe) and not 0xe0 <= marker <= 0xef:
                break
            at = end
        raise ValueError("phone_screen_jpeg_header")

    def receive(self, data):
        self._require_current()
        self._validate_header(data)
        loader = GdkPixbuf.PixbufLoader.new_with_type("jpeg")
        expected = self._size
        native_mismatch = False

        def size_prepared(source, width, height):
            nonlocal native_mismatch
            if (width, height) != expected:
                native_mismatch = True
                source.set_size(1, 1)

        loader.connect("size-prepared", size_prepared)
        try:
            loader.write(data)
        except Exception:
            try:
                loader.close()
            except GLib.Error:
                pass
            raise
        loader.close()
        picture = loader.get_pixbuf()
        if (native_mismatch or picture is None or (picture.get_width(), picture.get_height()) != expected or
                picture.get_n_channels() != 3 or picture.get_bits_per_sample() != 8):
            raise ValueError("phone_screen_jpeg_decode_shape")
        width, height = expected
        data, stride = picture.get_pixels(), picture.get_rowstride()
        rgb = data if stride == width * 3 else b"".join(data[y * stride:y * stride + width * 3] for y in range(height))
        self._require_current()
        return self._offer_rgb(width, height, rgb)


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

    @property
    def available(self):
        self._require_gtk_thread()
        return self._window is not None and self._check_current()

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
