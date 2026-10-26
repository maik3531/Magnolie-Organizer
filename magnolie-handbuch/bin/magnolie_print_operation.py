"""Native chooser, cancellable rendering and original-PDF submission (#236)."""
from magnolie_print_gtk import UnixPrintJob
from magnolie_print_process import RenderProcess


class PdfPrintOperation:
    def __init__(self, parent, title, markup, web_root, complete, translate, runtime_dir=None):
        from gi.repository import Gtk
        self.parent, self.title = parent, title
        self._markup, self._web_root = markup, web_root
        self._complete, self._translate = complete, translate
        self._runtime = runtime_dir
        self._settings = Gtk.PrintSettings()
        self._setup = Gtk.PageSetup()
        self._setup.set_paper_size(Gtk.PaperSize.new("iso_a4"))
        self._setup.set_orientation(Gtk.PageOrientation.LANDSCAPE)
        for edge in ("top", "bottom", "left", "right"):
            getattr(self._setup, "set_" + edge + "_margin")(0, Gtk.Unit.MM)
        self._printer = self._job = self._worker = self._portal = self._progress = None
        self._finished = self._closing = self._submitted = False
        self.started = False
        self._parent_signal = parent.connect("destroy", self.shutdown)

    def get_print_settings(self):
        return self._settings

    def set_print_settings(self, settings):
        self._settings = settings

    def get_page_setup(self):
        return self._setup

    def set_page_setup(self, setup):
        self._setup = setup

    def set_printer(self, printer):
        self._printer = printer

    def print_(self):
        if self.started or self._finished:
            raise RuntimeError("Print operation already started or closed")
        self.started = True
        try:
            if self._printer is None:
                raise RuntimeError("No native printer was selected")
            self._job = UnixPrintJob(self.title, self._printer, self._settings, self._setup)
            self._start_render(self._job.render_options())
        except Exception as error:
            self._finish(False, str(error)[:2000])

    def run_dialog(self, _parent):
        """Sandbox path: obtain portal settings, then submit the original PDF FD."""
        from magnolie_print_portal import PortalPrint
        if self.started or self._finished:
            raise RuntimeError("Print operation already started or closed")
        self.started = True
        try:
            self._portal = PortalPrint(self.parent, self.title)
            self._portal.prepare(self._settings, self._setup, self._portal_prepared)
        except Exception as error:
            self._finish(False, str(error)[:2000])

    def _portal_prepared(self, ok, result):
        if self._finished:
            return
        if not ok:
            self._finish(False, result)
            return
        try:
            self._settings, self._setup = result["settings"], result["page_setup"]
            job = UnixPrintJob.virtual_file(self.title, self._settings, self._setup)
            try:
                options = job.render_options()
            finally:
                job.close()
            self._start_render(options)
        except Exception as error:
            self._finish(False, str(error)[:2000])

    def _start_render(self, options):
        from gi.repository import Gtk
        progress = Gtk.Dialog(title=self._translate("Printing"), transient_for=self.parent, modal=True)
        progress.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        progress.get_content_area().set_border_width(18)
        spinner = Gtk.Spinner()
        spinner.start()
        progress.get_content_area().pack_start(spinner, True, True, 8)
        progress.get_content_area().pack_start(Gtk.Label(label=self._translate("Printing")), False, False, 8)
        progress.connect("response", lambda *_: self.cancel())
        progress.connect("delete-event", lambda *_: (self.cancel(), True)[1])
        self._progress = progress
        progress.show_all()
        self._worker = RenderProcess(self._markup, self._web_root, options, self._rendered, self._runtime).start()
        self._markup = ""

    def _hide_progress(self):
        if self._progress is not None:
            progress, self._progress = self._progress, None
            progress.destroy()

    def _rendered(self, ok, result):
        if self._finished:
            return
        if not ok:
            self._finish(False, result)
            return
        try:
            self._hide_progress()
            if self._closing:
                self._finish(False, "cancelled")
            elif self._portal is not None:
                self._portal.send(self._worker.path, self._finish)
                self._submitted = True
            else:
                self._job.send(self._worker.path, self._finish)
                self._submitted = True
        except Exception as error:
            self._finish(False, str(error)[:2000])

    def cancel(self):
        if self._finished or self._submitted:
            return False
        if self._worker is not None:
            if self._progress is not None:
                self._progress.set_sensitive(False)
            self._worker.cancel()
        elif self._portal is not None:
            self._portal.cancel()
        else:
            self._finish(False, "cancelled")
        return True

    def shutdown(self, *_args):
        if self._finished:
            return
        self._closing = True
        if self._submitted:
            # The spooler already owns the request. Keep the source until its
            # native completion callback; never unlink a file GTK is consuming.
            return
        if self._worker is not None:
            self._worker.shutdown()
        if self._portal is not None:
            self._portal.cancel()
        self._finish(False, "cancelled")

    def _finish(self, ok, result):
        if self._finished:
            return
        self._finished = True
        self._hide_progress()
        if self._job is not None:
            self._job.close()
        if self._portal is not None:
            self._portal.close()
        if self._worker is not None:
            self._worker.close()
        if self._parent_signal is not None:
            if self.parent.handler_is_connected(self._parent_signal):
                self.parent.disconnect(self._parent_signal)
            self._parent_signal = None
        self._markup = ""
        self._complete(ok, result)

    def close(self):
        if not self.started:
            self._finish(False, "cancelled")
