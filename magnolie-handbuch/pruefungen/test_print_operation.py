"""Run under Xvfb: native GUI coordinator, real worker, cancel and window teardown."""
import os
from pathlib import Path
import sys
import tempfile

temporary = tempfile.TemporaryDirectory(prefix="magnolie-print-operation-", dir="/tmp/opencode")
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

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from magnolie_print_gtk import UnixPrintJob, _ACTIVE_JOBS
from magnolie_print_operation import PdfPrintOperation


@pytest.fixture(scope="session", autouse=True)
def display():
    # GTK can flush its recent-file manager during a later module's main loop.
    # Keep the isolated HOME alive for the whole process, not just these cases.
    assert Gtk.init_check()[0], "Native print-operation tests require a display or xvfb-run"
    yield
    temporary.cleanup()


TEXT = ["पत्र लिखना की", "写信 页面 门 贝"]
MARKUP = ('<style>@page{size:A4 landscape}p{break-after:page}p:last-child{break-after:auto}</style>' +
          "".join("<p>" + text + "</p>" for text in TEXT))


def operation(tmp_path, action):
    window = Gtk.Window()
    window.show_all()
    output = tmp_path / "output.pdf"
    loop, results = GLib.MainLoop(), []
    def completed(ok, result):
        results.append((ok, result))
        GLib.timeout_add(50, lambda: (loop.quit(), False)[1])
    op = PdfPrintOperation(window, "Owned native fixture", MARKUP, ROOT / "web", completed, lambda text: text,
        runtime_dir=Path(os.environ["MAGNOLIE_PDF_TEST_RUNTIME"]))
    settings = op.get_print_settings()
    settings.set("output-file-format", "pdf")
    settings.set("output-uri", output.as_uri())
    settings.set_n_copies(2)
    settings.set_number_up(2)
    settings.set_reverse(True)
    normalizer = UnixPrintJob.virtual_file("Owned file printer reference", settings, op.get_page_setup())
    try:
        op.set_printer(normalizer._objects[0])
        op.print_()
    finally:
        normalizer.close()
    if action == "cancel":
        GLib.idle_add(lambda: (op._progress.response(Gtk.ResponseType.CANCEL), False)[1])
    elif action == "close":
        GLib.idle_add(lambda: (window.destroy(), False)[1])
    timeout = GLib.timeout_add_seconds(15, lambda: (loop.quit(), False)[1])
    loop.run()
    GLib.source_remove(timeout)
    try:
        assert len(results) == 1, results
        assert op._worker._worker.poll() is not None
        assert not op._worker.path.parent.exists()
        assert not _ACTIVE_JOBS, "No native callback owner should remain after completion"
    finally:
        window.destroy()
    return output, results[0]


def test_native_operation_keeps_original_text_and_applies_sheet_options(tmp_path):
    output, (ok, result) = operation(tmp_path, "print")
    assert ok is True, result
    reader = PdfReader(output)
    assert len(reader.pages) == 2
    for page in reader.pages:
        spans = [str(operands[1]["/ActualText"]) for operands, operator in ContentStream(page.get_contents(), reader).operations
                 if operator == b"BDC" and len(operands) == 2 and hasattr(operands[1], "get") and operands[1].get("/ActualText") is not None]
        assert "".join("".join(spans).split()) == "".join((TEXT[0] + TEXT[1]).split())


@pytest.mark.parametrize("action", ["cancel", "close"])
def test_cancel_or_close_reaps_worker_and_never_submits_a_pdf(tmp_path, action):
    output, (ok, result) = operation(tmp_path, action)
    assert ok is False and result == "cancelled"
    assert not output.exists()


def test_portal_parent_identifier_uses_real_x11_window_without_extra_gir():
    from magnolie_print_portal import PortalPrint
    window = Gtk.Window()
    window.show_all()
    portal = PortalPrint(window, "Owned parent identifier", connection=object())
    identifiers = []
    try:
        portal._parent_identifier(identifiers.append)
        assert len(identifiers) == 1 and identifiers[0].startswith("x11:")
        assert int(identifiers[0][4:], 16) > 0
    finally:
        portal.close()
        window.destroy()
