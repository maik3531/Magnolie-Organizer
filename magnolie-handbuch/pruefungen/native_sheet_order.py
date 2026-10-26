#!/usr/bin/env python3
"""Compare semantic-PDF sheet ordering with GTK's own print operation (#236)."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

temporary = tempfile.TemporaryDirectory(prefix="magnolie-sheet-order-", dir="/tmp/opencode")
for variable, name in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                       ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
    directory = Path(temporary.name) / name
    directory.mkdir(mode=0o700)
    os.environ[variable] = str(directory)
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
os.environ["GTK_PRINT_BACKENDS"] = "file"
os.environ["GTK_USE_PORTAL"] = "0"
os.environ["GIO_USE_VFS"] = "local"
os.environ["NO_AT_BRIDGE"] = "1"
os.environ["GSETTINGS_BACKEND"] = "memory"

import gi
gi.require_version("Gtk", "3.0")
gi.require_foreign("cairo")
from gi.repository import Gtk, GLib

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "bin"))
from magnolie_print_pdf import render_pdf, compose_pdf

Gtk.init([])
COUNT = 6
source = Path(temporary.name) / "source.pdf"
markup = ('<style>@page{size:A4 landscape;margin:0}p{break-after:page}p:last-child{break-after:auto}</style>' +
          "".join("<p>index-" + str(index) + "</p>" for index in range(COUNT)))
render_pdf(markup, root / "web", source, {})


def reference(target, options):
    settings = Gtk.PrintSettings()
    settings.set_printer("Print to File")
    settings.set("output-file-format", "pdf")
    settings.set("output-uri", target.as_uri())
    settings.set_number_up(options.get("number_up", 1))
    settings.set_number_up_layout(Gtk.NumberUpLayout(options.get("number_up_layout", 0)))
    settings.set_reverse(options.get("reverse", False))
    settings.set_n_copies(options.get("copies", 1))
    settings.set_collate(options.get("collate", True))
    settings.set_page_set({"all": Gtk.PageSet.ALL, "even": Gtk.PageSet.EVEN, "odd": Gtk.PageSet.ODD}[options.get("page_set", "all")])
    if "ranges" in options:
        ranges = []
        for start, end in options["ranges"]:
            item = Gtk.PageRange()
            item.start, item.end = start, end
            ranges.append(item)
        settings.set_print_pages(Gtk.PrintPages.RANGES)
        settings.set_page_ranges(ranges)
    setup = Gtk.PageSetup()
    setup.set_paper_size(Gtk.PaperSize.new("iso_a4"))
    setup.set_orientation(Gtk.PageOrientation.LANDSCAPE)
    for edge in ("top", "bottom", "left", "right"):
        getattr(setup, "set_" + edge + "_margin")(0, Gtk.Unit.MM)
    operation = Gtk.PrintOperation()
    operation.set_job_name("Owned native sheet comparison")
    operation.set_print_settings(settings)
    operation.set_default_page_setup(setup)
    operation.set_n_pages(COUNT)
    operation.set_show_progress(False)
    def draw(_operation, context, page):
        cairo = context.get_cairo_context()
        cairo.set_font_size(14)
        cairo.move_to(20, 40)
        cairo.show_text("index-" + str(page))
    operation.connect("draw-page", draw)
    state = {"accepted": False, "timed_out": False}
    def accept():
        for dialog in Gtk.Window.list_toplevels():
            if dialog.__gtype__.name != "GtkPrintUnixDialog":
                continue
            printer = dialog.get_property("selected-printer")
            current = dialog.get_property("print-settings")
            if (printer is not None and printer.get_property("is-virtual") and
                    current.get("output-uri") == target.as_uri()):
                state["accepted"] = True
                dialog.response(Gtk.ResponseType.OK)
                return False
        return True
    def abort():
        state["timed_out"] = True
        operation.cancel()
        for dialog in Gtk.Window.list_toplevels():
            if dialog.__gtype__.name == "GtkPrintUnixDialog":
                dialog.response(Gtk.ResponseType.CANCEL)
        return False
    accepted = GLib.timeout_add(500, accept)
    deadline = GLib.timeout_add_seconds(10, abort)
    result = operation.run(Gtk.PrintOperationAction.PRINT_DIALOG, None)
    if not state["accepted"]:
        GLib.source_remove(accepted)
    if not state["timed_out"]:
        GLib.source_remove(deadline)
    assert result == Gtk.PrintOperationResult.APPLY, result
    assert target.is_file()
    # Compare the settings the native chooser actually accepted. Some GTK
    # versions normalize an unavailable layout preference back to LRTB.
    return {**options, "number_up_layout": int(operation.get_print_settings().get_number_up_layout())}


def sheet_texts(path):
    text = subprocess.check_output(["pdftotext", "-raw", str(path), "-"], text=True)
    pages = text.split("\f")
    if not pages[-1].strip():
        pages.pop()
    return [[int(index) for index in re.findall(r"index-(\d+)", page)] for page in pages]


def sheet_geometry(path, number_up):
    """Read actual painted text direction/cell locations with independent Poppler."""
    xml = ET.fromstring(subprocess.check_output(["pdftotext", "-bbox", str(path), "-"], stderr=subprocess.PIPE))
    columns = math.ceil(math.sqrt(number_up))
    rows = number_up // columns
    result = []
    for page in (element for element in xml.iter() if element.tag.rsplit('}', 1)[-1] == 'page'):
        width, height = float(page.attrib['width']), float(page.attrib['height'])
        cells = []
        for word in page.iter():
            if word.tag.rsplit('}', 1)[-1] != 'word':
                continue
            match = re.fullmatch(r'index-(\d+)', ''.join(word.itertext()))
            if not match:
                continue
            left, right, top, bottom = [float(word.attrib[name]) for name in ('xMin', 'xMax', 'yMin', 'yMax')]
            cells.append((int(match[1]), bottom - top > right - left,
                          int((left + right) / 2 / width * columns), int((top + bottom) / 2 / height * rows)))
        result.append(sorted(cells))
    return result


cases = [
    {"number_up": 2, "reverse": True},
    {"number_up": 2, "page_set": "even"},
    {"ranges": [[1, 4]], "number_up": 2, "page_set": "odd", "reverse": True},
    {"ranges": [[0, 999]], "number_up": 2},
    {"ranges": [[2, 2], [0, 0], [2, 2]]},
    {"number_up": 2, "page_set": "even", "copies": 2, "collate": False},
    {"number_up": 6},
    {"number_up": 6, "number_up_layout": 7},
]
failures = []
for index, options in enumerate(cases):
    native = Path(temporary.name) / (str(index) + "-gtk.pdf")
    composed = Path(temporary.name) / (str(index) + "-semantic.pdf")
    accepted_options = reference(native, options)
    expected = sheet_texts(native)
    try:
        compose_pdf(source, composed, accepted_options)
        actual = sheet_texts(composed)
        geometry = sheet_geometry(composed, options.get('number_up', 1))
    except Exception as error:
        actual = str(error)
        geometry = None
    expected_geometry = sheet_geometry(native, options.get('number_up', 1))
    result = {"requestedOptions": options, "acceptedOptions": accepted_options, "gtkSheets": expected, "semanticSheets": actual,
              "equal": actual == expected, "gtkCells": expected_geometry, "semanticCells": geometry,
              "geometryEqual": expected_geometry == geometry}
    print(json.dumps(result), flush=True)
    if actual != expected or expected_geometry != geometry:
        failures.append(result)
temporary.cleanup()
assert not failures, "Semantic sheet selection differs from the native GTK reference"
print("NATIVE GTK SHEET ORDER PASS: reverse, odd/even, ranges, copies, n-up", flush=True)
