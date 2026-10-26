"""Prepare and submit an original PDF through the desktop print portal (#236)."""
import ctypes
import os
import uuid


BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
INTERFACE = "org.freedesktop.portal.Print"
REQUEST = "org.freedesktop.portal.Request"
_EXPORTED = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p)
_DESTROY = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
_ACTIVE_EXPORTS = {}


def _vardict(value):
    return {entry.get_child_value(0).get_string(): entry.get_child_value(1).get_variant()
            for entry in (value.get_child_value(index) for index in range(value.n_children()))}


class PortalPrint:
    def __init__(self, parent, title, connection=None):
        from gi.repository import Gio
        self._connection = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._parent = parent
        self._title = title
        self._parent_id = ""
        self._exported = None
        self._request = None
        self._subscription = None
        self._response = None
        self._token = None
        self._closed = False
        self._export_callback = self._export_destroy = None
        self._gdk = None

    def _parent_identifier(self, ready):
        window = self._parent.get_window() if self._parent is not None else None
        if window is None:
            ready("")
            return
        from gi.repository import GObject
        from magnolie_print_gtk import _pointer
        name = GObject.type_name(window.__gtype__)
        self._gdk = ctypes.CDLL("libgdk-3.so.0")
        if "X11" in name:
            xid = self._gdk.gdk_x11_window_get_xid
            xid.argtypes, xid.restype = [ctypes.c_void_p], ctypes.c_ulong
            ready("x11:" + format(xid(_pointer(window)), "x"))
        elif "Wayland" in name:
            # GTK3's public Wayland export API has no GdkWayland-3.0 GIR on
            # supported distributions. Use that API directly, as for Unix print.
            from gi.repository import GLib
            @_EXPORTED
            def exported(_window, handle, _data):
                try:
                    if not self._closed:
                        ready("wayland:" + handle.decode("utf-8"))
                except Exception as error:
                    self._finish(False, str(error)[:2000])
            @_DESTROY
            def destroyed(_data):
                self._exported = None
                def release():
                    _ACTIVE_EXPORTS.pop(id(self), None)
                    self._export_callback = self._export_destroy = None
                    return False
                GLib.idle_add(release)
            self._exported = window
            self._export_callback, self._export_destroy = exported, destroyed
            _ACTIVE_EXPORTS[id(self)] = self
            export = self._gdk.gdk_wayland_window_export_handle
            export.argtypes, export.restype = [ctypes.c_void_p, _EXPORTED, ctypes.c_void_p, _DESTROY], ctypes.c_int
            if not export(_pointer(window), exported, id(self), destroyed):
                self._exported = None
                _ACTIVE_EXPORTS.pop(id(self), None)
                self._export_callback = self._export_destroy = None
                ready("")
        else:
            ready("")

    def _unexport(self):
        if self._exported is not None:
            from magnolie_print_gtk import _pointer
            window, self._exported = self._exported, None
            unexport = self._gdk.gdk_wayland_window_unexport_handle
            unexport.argtypes, unexport.restype = [ctypes.c_void_p], None
            unexport(_pointer(window))

    def prepare(self, settings, page_setup, complete):
        if self._closed:
            raise RuntimeError("Print portal is closed")
        self._response = complete
        def identified(parent_id):
            if self._closed:
                return
            self._parent_id = parent_id
            self._call("PreparePrint", (parent_id, self._title, _vardict(settings.to_gvariant()),
                _vardict(page_setup.to_gvariant())), complete)
        try:
            self._parent_identifier(identified)
        except Exception as error:
            self._finish(False, str(error)[:2000])

    def send(self, path, complete):
        from gi.repository import Gio
        if self._token is None or self._closed:
            raise RuntimeError("Print portal settings are unavailable or cancelled")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            descriptors = Gio.UnixFDList.new()
            index = descriptors.append(descriptor)
        finally:
            os.close(descriptor)
        self._call("Print", (self._parent_id, self._title, index), complete, descriptors)

    def _call(self, method, arguments, complete, descriptors=None):
        from gi.repository import Gio, GLib
        if self._request is not None or self._closed:
            raise RuntimeError("Print portal already has an active or closed request")
        token = "magnolie_" + uuid.uuid4().hex
        sender = self._connection.get_unique_name().lstrip(":").replace(".", "_")
        request = "/org/freedesktop/portal/desktop/request/" + sender + "/" + token
        self._request, self._response = request, complete
        self._subscription = self._connection.signal_subscribe(BUS, REQUEST, "Response", request, None,
            Gio.DBusSignalFlags.NONE, self._received, method)
        options = {"handle_token": GLib.Variant("s", token), "modal": GLib.Variant("b", True),
                   "supported_output_file_formats": GLib.Variant("as", ["pdf"])}
        if method == "PreparePrint":
            options.update(has_current_page=GLib.Variant("b", False), has_selected_pages=GLib.Variant("b", False))
            parameters = GLib.Variant("(ssa{sv}a{sv}a{sv})", (*arguments, options))
        else:
            options["token"] = GLib.Variant("u", self._token)
            parameters = GLib.Variant("(ssha{sv})", (*arguments, options))

        def called(connection, result, _data):
            try:
                response = (connection.call_finish(result) if descriptors is None else
                            connection.call_with_unix_fd_list_finish(result)[0])
                if self._closed or self._request != request:
                    return
                if response.unpack()[0] != request:
                    raise RuntimeError("Unexpected print portal request handle")
            except Exception as error:
                if not self._closed and self._request == request:
                    self._finish(False, str(error)[:2000])

        if descriptors is None:
            self._connection.call(BUS, PATH, INTERFACE, method, parameters, GLib.VariantType.new("(o)"),
                Gio.DBusCallFlags.NONE, 30_000, None, called, None)
        else:
            self._connection.call_with_unix_fd_list(BUS, PATH, INTERFACE, method, parameters,
                GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 30_000, descriptors, None, called, None)

    def _received(self, _connection, _sender, path, _interface, _signal, parameters, method):
        if self._closed or path != self._request:
            return
        try:
            response = parameters.get_child_value(0).get_uint32()
            if response != 0:
                self._finish(False, "cancelled" if response == 1 else "The print portal rejected the request")
                return
            if method == "PreparePrint":
                from gi.repository import GLib, Gtk
                result = parameters.get_child_value(1)
                settings = result.lookup_value("settings", GLib.VariantType.new("a{sv}"))
                setup = result.lookup_value("page-setup", GLib.VariantType.new("a{sv}"))
                token = result.lookup_value("token", GLib.VariantType.new("u"))
                if settings is None or setup is None or token is None or token.get_uint32() == 0:
                    raise RuntimeError("Incomplete print portal settings")
                self._token = token.get_uint32()
                self._finish(True, {"settings": Gtk.PrintSettings.new_from_gvariant(settings),
                    "page_setup": Gtk.PageSetup.new_from_gvariant(setup)})
            else:
                self._finish(True, {"stage": "portal_accepted"})
        except Exception as error:
            self._finish(False, str(error)[:2000])

    def _finish(self, ok, result):
        callback = self._response
        if self._subscription is not None:
            self._connection.signal_unsubscribe(self._subscription)
        self._subscription, self._request, self._response = None, None, None
        if callback is not None:
            callback(ok, result)

    def cancel(self):
        from gi.repository import Gio
        self._closed = True
        if self._request is not None:
            self._connection.call(BUS, self._request, REQUEST, "Close", None, None,
                Gio.DBusCallFlags.NONE, 1000, None, None, None)
        self._finish(False, "cancelled")
        self._unexport()

    def close(self):
        if self._request is not None:
            self.cancel()
        self._closed = True
        self._unexport()
