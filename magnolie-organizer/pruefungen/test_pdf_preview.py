"""Exercise actual Poppler page selection and bounded raster output."""
import base64
import io
from pathlib import Path
import shutil
import struct
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_pdf import render_page, MAX_SIDE


def scanned_pdf():
    cairo = pytest.importorskip("cairo")
    output = io.BytesIO()
    surface = cairo.PDFSurface(output, 240, 120)
    context = cairo.Context(surface)
    for color in ((1, 0, 0), (0, 0, 1)):
        context.set_source_rgb(*color); context.paint(); context.show_page()
    surface.finish()
    return output.getvalue()


def test_real_pdf_pages_are_distinct_drawable_pngs():
    if not all(shutil.which(name) for name in ("pdfinfo", "pdftoppm")):
        pytest.skip("native Poppler tools not installed")
    pdf = scanned_pdf()
    first, second = render_page(pdf, 1), render_page(pdf, 2)
    assert first["pages"] == second["pages"] == 2
    assert first["page"] == 1 and second["page"] == 2
    assert first["data"] != second["data"]
    png = base64.b64decode(first["data"].split(",", 1)[1], validate=True)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (MAX_SIDE, MAX_SIDE // 2)
    with pytest.raises(ValueError, match="page count"):
        render_page(pdf, 3)


@pytest.mark.parametrize("page", [True, False, 0, -1, 1001, 1.5, "1"])
def test_invalid_page_never_starts_a_renderer(page):
    with pytest.raises(ValueError, match="page"):
        render_page(b"%PDF-synthetic", page)


@pytest.mark.parametrize("data", [b"", b"not a PDF", "data:application/pdf;base64,AAA"])
def test_non_pdf_input_is_rejected(data):
    with pytest.raises(ValueError, match="input"):
        render_page(data)
