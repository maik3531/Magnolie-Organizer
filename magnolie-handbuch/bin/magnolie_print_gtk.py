"""GTK Unix print-job adapter which submits the original semantic PDF (#236)."""
import ctypes


class PageRange(ctypes.Structure):
    _fields_ = [("start", ctypes.c_int), ("end", ctypes.c_int)]


class NativeError(ctypes.Structure):
    _fields_ = [("domain", ctypes.c_uint), ("code", ctypes.c_int), ("message", ctypes.c_char_p)]


_COMPLETE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(NativeError))
_ACTIVE_JOBS = {}


def _pointer(obj):
    if type(obj) is int:
        return obj
    # PyGObject explicitly exposes the wrapped GObject as a PyCapsule.
    get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
    get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    get_pointer.restype = ctypes.c_void_p
    return get_pointer(obj.__gpointer__, None)


class UnixPrintJob:
    """Own one GTK job until its completion callback has released its PDF."""

    def __init__(self, title, printer, settings, page_setup):
        self._library = ctypes.CDLL("libgtk-3.so.0")
        self._gobject = ctypes.CDLL("libgobject-2.0.so.0")
        self._glib = ctypes.CDLL("libglib-2.0.so.0")
        self._job = None
        self._sending = False
        self._callback = None
        # Retain the PyGObject wrappers as well as GTK's own job references.
        self._objects = (printer, settings, page_setup)
        self._job = self._api("gtk_print_job_new", ctypes.c_void_p,
            [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])(
                title.encode("utf-8"), _pointer(printer), _pointer(settings), _pointer(page_setup))
        if not self._job:
            raise RuntimeError("GTK did not create the print job")

    @classmethod
    def virtual_file(cls, title, settings, page_setup):
        """Use GTK's file backend to normalize portal settings, as GTK itself does."""
        gtk = ctypes.CDLL("libgtk-3.so.0")
        gobject = ctypes.CDLL("libgobject-2.0.so.0")
        def api(library, name, result, arguments):
            function = getattr(library, name)
            function.restype, function.argtypes = result, arguments
            return function
        pointer = ctypes.c_void_p
        is_virtual = api(gtk, "gtk_printer_is_virtual", ctypes.c_int, [pointer])
        backend = api(gtk, "gtk_printer_get_backend", pointer, [pointer])
        type_name = api(gobject, "g_type_name_from_instance", ctypes.c_char_p, [pointer])
        retain = api(gobject, "g_object_ref", pointer, [pointer])
        release = api(gobject, "g_object_unref", None, [pointer])
        callback_type = ctypes.CFUNCTYPE(ctypes.c_int, pointer, pointer)
        selected = []
        @callback_type
        def printer(value, _data):
            if is_virtual(value) and type_name(backend(value)) == b"GtkPrintBackendFile":
                selected.append(retain(value))
                return 1
            return 0
        api(gtk, "gtk_enumerate_printers", None, [callback_type, pointer, pointer, ctypes.c_int])(
            printer, None, None, True)
        if len(selected) != 1:
            raise RuntimeError("The native PDF file-print backend is unavailable")
        try:
            return cls(title, selected[0], settings, page_setup)
        finally:
            release(selected[0])

    def _api(self, name, result, arguments):
        function = getattr(self._library, name)
        function.restype, function.argtypes = result, arguments
        return function

    def _get(self, name, result=ctypes.c_int):
        if self._job is None:
            raise RuntimeError("Print job is closed")
        return self._api("gtk_print_job_get_" + name, result, [ctypes.c_void_p])(self._job)

    def render_options(self):
        """Ask the selected backend which options the application must apply.

        In particular, copies already handled by printer hardware must not be
        multiplied again in the PDF. This is the GtkPrintOperation contract.
        """
        from gi.repository import Gtk
        setup = self._objects[2]
        options = {
            "copies": self._get("num_copies"), "collate": bool(self._get("collate")),
            "reverse": bool(self._get("reverse")), "scale": self._get("scale", ctypes.c_double) * 100,
            "number_up": self._get("n_up", ctypes.c_uint), "number_up_layout": self._get("n_up_layout"),
            "paper_width_mm": setup.get_paper_width(Gtk.Unit.MM),
            "paper_height_mm": setup.get_paper_height(Gtk.Unit.MM),
            "margins_mm": [getattr(setup, "get_" + edge + "_margin")(Gtk.Unit.MM)
                           for edge in ("top", "right", "bottom", "left")],
            "orientation_reverse": setup.get_orientation() in
                (Gtk.PageOrientation.REVERSE_PORTRAIT, Gtk.PageOrientation.REVERSE_LANDSCAPE),
            "paper_landscape": setup.get_orientation() in
                (Gtk.PageOrientation.LANDSCAPE, Gtk.PageOrientation.REVERSE_LANDSCAPE),
        }
        page_set = self._get("page_set")
        names = {int(Gtk.PageSet.ALL): "all", int(Gtk.PageSet.EVEN): "even", int(Gtk.PageSet.ODD): "odd"}
        if page_set not in names:
            raise ValueError("Unsupported GTK page set")
        options["page_set"] = names[page_set]
        pages = self._get("pages")
        if pages == int(Gtk.PrintPages.RANGES):
            count = ctypes.c_int()
            ranges = self._api("gtk_print_job_get_page_ranges", ctypes.POINTER(PageRange),
                [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)])(self._job, ctypes.byref(count))
            if not 1 <= count.value <= 2000 or not ranges:
                raise ValueError("Invalid GTK page ranges")
            options["ranges"] = [[ranges[index].start, ranges[index].end] for index in range(count.value)]
        elif pages != int(Gtk.PrintPages.ALL):
            # The handbook has no current-page or selection-only print mode.
            raise ValueError("Unsupported GTK page selection")
        return options

    def send(self, path, complete):
        """Submit one PDF; completion is the native result, not queue admission."""
        if self._sending or self._job is None:
            raise RuntimeError("Print job has already been submitted or closed")
        error = ctypes.POINTER(NativeError)()
        accepted = self._api("gtk_print_job_set_source_file", ctypes.c_int,
            [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.POINTER(NativeError))])(
                self._job, str(path).encode("utf-8"), ctypes.byref(error))
        if not accepted:
            try:
                message = error.contents.message.decode("utf-8", "replace") if error else "Print source was rejected"
            finally:
                if error:
                    free = self._glib.g_error_free
                    free.argtypes, free.restype = [ctypes.POINTER(NativeError)], None
                    free(error)
            raise RuntimeError(message)

        @_COMPLETE
        def sent(_job, _data, native_error):
            message = native_error.contents.message.decode("utf-8", "replace") if native_error else None
            self._sending = False
            try:
                complete(message is None, message)
            finally:
                self.close()
                # The ctypes callback must outlive the native call stack which
                # invoked it; release its retained owner on the next main turn.
                from gi.repository import GLib
                def release_callback():
                    _ACTIVE_JOBS.pop(_job, None)
                    self._callback = None
                    return False
                GLib.idle_add(release_callback)

        self._callback = sent
        self._sending = True
        _ACTIVE_JOBS[self._job] = self
        self._api("gtk_print_job_send", None,
            [ctypes.c_void_p, _COMPLETE, ctypes.c_void_p, ctypes.c_void_p])(self._job, sent, None, None)

    def close(self):
        if self._sending:
            return
        if self._job is not None:
            release = self._gobject.g_object_unref
            release.argtypes, release.restype = [ctypes.c_void_p], None
            release(self._job)
            self._job = None
        self._objects = ()

    def __del__(self):
        if getattr(self, "_job", None) is not None:
            self.close()
