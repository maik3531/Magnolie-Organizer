#!/usr/bin/env python3
"""Native virtual-printer check: GTK settings -> semantic PDF -> GTK source send."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
temporary = tempfile.TemporaryDirectory(prefix="magnolie-native-pdf-", dir="/tmp/opencode")
for variable, name in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                       ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
    directory = Path(temporary.name) / name
    directory.mkdir(mode=0o700)
    os.environ[variable] = str(directory)
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
os.environ["GTK_PRINT_BACKENDS"] = "file"
os.environ["GIO_USE_VFS"] = "local"
os.environ["NO_AT_BRIDGE"] = "1"
os.environ["GSETTINGS_BACKEND"] = "memory"
sys.path.insert(0, str(root / "bin"))
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GObject, GLib
from magnolie_print_pdf import render_pdf, compose_pdf
from magnolie_print_gtk import UnixPrintJob
from pypdf import PdfReader
from pypdf.generic import ContentStream

library = ctypes.CDLL("libgtk-3.so.0")
register = library.gtk_print_unix_dialog_get_type
register.argtypes, register.restype = [], ctypes.c_size_t
register()
Gtk.init([])
window = Gtk.Window()
window.set_default_size(800, 600)
window.show_all()
source = Path(temporary.name) / "original.pdf"
prepared = Path(temporary.name) / "prepared.pdf"
output = Path(temporary.name) / "printed.pdf"
TEXT = ["पत्र लिखना कि की क्षि", "写信 联系人 页面 门 贝", "office affine ffi fi fl"]
markup = ('<!doctype html><meta charset="utf-8"><style>@page{size:A4 landscape;margin:10mm}'
          'p{break-after:page;font:20pt sans-serif}p:last-child{break-after:auto}</style>' +
          "".join("<p>" + text + "</p>" for text in TEXT))
render_pdf(markup, root / "web", source, {})
settings = Gtk.PrintSettings()
settings.set_printer("Print to File")
settings.set("output-file-format", "pdf")
settings.set("output-uri", output.as_uri())
settings.set_print_pages(Gtk.PrintPages.RANGES)
page_range = Gtk.PageRange()
page_range.start, page_range.end = 0, 1
settings.set_page_ranges([page_range])
settings.set_number_up(2)
settings.set_n_copies(2)
settings.set_reverse(True)
setup = Gtk.PageSetup()
setup.set_paper_size(Gtk.PaperSize.new("iso_a4"))
setup.set_orientation(Gtk.PageOrientation.LANDSCAPE)
for edge in ("top", "bottom", "left", "right"):
    getattr(setup, "set_" + edge + "_margin")(0, Gtk.Unit.MM)
dialog = GObject.new(GObject.type_from_name("GtkPrintUnixDialog"), title="Synthetic semantic PDF", transient_for=window, modal=True)
capabilities = type(dialog.get_property("manual-capabilities")).__flags_values__
names = {"GTK_PRINT_CAPABILITY_" + name for name in ("PAGE_SET", "COPIES", "COLLATE", "REVERSE", "SCALE", "GENERATE_PDF", "NUMBER_UP", "NUMBER_UP_LAYOUT")}
dialog.set_property("manual-capabilities", sum(value for value, flag in capabilities.items() if names.intersection(flag.value_names)))
dialog.set_property("print-settings", settings)
dialog.set_property("page-setup", setup)
dialog.set_property("embed-page-setup", True)

def accept_virtual_only():
    printer = dialog.get_property("selected-printer")
    if printer is None:
        return True
    assert printer.get_property("is-virtual") is True
    dialog.response(Gtk.ResponseType.OK)
    return False

# Let the native chooser finish mapping its printer/options pages before the
# synthetic response, just as an interactive Print press follows presentation.
GLib.timeout_add(500, accept_virtual_only)
GLib.timeout_add_seconds(10, lambda: (dialog.response(Gtk.ResponseType.CANCEL), False)[1])
assert dialog.run() == Gtk.ResponseType.OK
printer = dialog.get_property("selected-printer")
assert printer is not None and printer.get_property("is-virtual") is True
settings = dialog.get_property("print-settings")
settings.set("output-file-format", "pdf")
settings.set("output-uri", output.as_uri())
job = UnixPrintJob("Synthetic Unicode PDF", printer, settings, dialog.get_property("page-setup"))
options = job.render_options()
portal_normalizer = UnixPrintJob.virtual_file("Synthetic portal settings", settings, dialog.get_property("page-setup"))
assert portal_normalizer.render_options() == options
portal_normalizer.close()
dialog.destroy()
assert options["ranges"] == [[0, 1]], options
assert options["copies"] == 2 and options["number_up"] == 2 and options["reverse"] is True, options
composition = compose_pdf(source, prepared, options)
loop = GLib.MainLoop()
result = {}
def completed(ok, error):
    result.update(ok=ok, error=error)
    # Let the adapter release the callback after the native completion stack.
    GLib.timeout_add(50, lambda: (loop.quit(), False)[1])
job.send(prepared, completed)
GLib.timeout_add_seconds(20, lambda: (loop.quit(), False)[1])
loop.run()
window.destroy()
assert result.get("ok") is True, result
assert output.read_bytes() == prepared.read_bytes(), "GTK rewrote the semantic PDF"
reader = PdfReader(output)
assert len(reader.pages) == 2
original = []
for page in reader.pages:
    spans = [str(operands[1]["/ActualText"]) for operands, operator in ContentStream(page.get_contents(), reader).operations
             if operator == b"BDC" and len(operands) == 2 and hasattr(operands[1], "get") and operands[1].get("/ActualText") is not None]
    original.append("".join(spans))
normalize = lambda value: "".join(value.split())
assert all(normalize(page) == normalize(TEXT[0] + TEXT[1]) for page in original), original
print("NATIVE SEMANTIC PDF PASS", json.dumps({"virtualOnly": True, "options": options, **composition,
      "byteIdentical": True, "originalUnicode": True, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))
temporary.cleanup()
