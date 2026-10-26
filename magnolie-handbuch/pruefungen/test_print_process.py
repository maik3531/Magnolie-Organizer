"""Run the real worker, including cancellation before any native submission."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_print_process import RenderProcess
from gi.repository import GLib
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("MAGNOLIE_PDF_TEST_RUNTIME", ROOT / "bin/pdf-runtime"))


def run(markup, cancel=False, options=None):
    loop = GLib.MainLoop()
    results = []
    def completed(ok, result):
        results.append((ok, result))
        loop.quit()
    process = RenderProcess(markup, ROOT / "web", options or {}, completed, RUNTIME).start()
    timer = GLib.timeout_add_seconds(15, lambda: (loop.quit(), False)[1])
    if cancel:
        process.cancel()
    loop.run()
    GLib.source_remove(timer)
    assert len(results) == 1, results
    assert process._worker.poll() is not None, "A completed worker must have been reaped"
    return process, results[0]


def test_real_worker_activates_locked_runtime_and_delivers_a_completed_pdf():
    process, (ok, result) = run('<style>@page{size:A4 landscape}</style><p>पत्र लिखना की 页面</p>')
    try:
        assert ok is True, result
        assert result["sheets"] == 1
        assert len(PdfReader(process.path).pages) == 1
        assert process.cancel() is False, "A delivered PDF must remain available until native completion"
        assert process.path.is_file()
    finally:
        process.close()
    assert not process.path.parent.exists()


def test_cancelled_worker_is_reaped_removes_partial_output_and_never_delivers_success():
    process, (ok, result) = run('<p>Owned cancellation fixture</p>', cancel=True)
    assert ok is False and result == "cancelled"
    assert not process.path.parent.exists()


def test_empty_native_sheet_filter_cancels_without_an_error_or_output():
    process, (ok, result) = run('<p>Owned one-sheet fixture</p>', options={"page_set": "even"})
    assert ok is False and result == "cancelled"
    assert not process.path.parent.exists()


def test_resource_denial_is_a_real_worker_failure_not_a_successful_empty_pdf():
    process, (ok, result) = run('<img src="https://example.org/forbidden.png">')
    assert ok is False
    assert "FatalURLFetchingError" in result
    assert not process.path.parent.exists()


def test_window_shutdown_reaps_worker_without_requiring_another_main_loop_turn():
    results = []
    process = RenderProcess("<p>Owned window teardown fixture</p>", ROOT / "web", {},
                            lambda ok, result: results.append((ok, result)), RUNTIME).start()
    process.shutdown()
    assert process._worker.poll() is not None
    assert not process._thread.is_alive()
    assert not process.path.parent.exists()
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)
    assert results == [(False, "cancelled")]
