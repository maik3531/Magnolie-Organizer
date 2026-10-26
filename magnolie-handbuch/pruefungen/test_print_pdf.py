"""Unicode and settings contracts for the native semantic PDF path (#236)."""
import hashlib
from pathlib import Path
import subprocess
import sys
import unicodedata

import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_print_pdf import compose_pdf, render_pdf, selected_pages, sheet_positions


TEXT = ["पत्र लिखना कि की क्षि", "写信 联系人 页面 门 贝", "office affine ffi fi fl"]


def original_text(path):
    reader = PdfReader(path)
    return [[str(operands[1]["/ActualText"]) for operands, operator in ContentStream(page.get_contents(), reader).operations
             if operator == b"BDC" and len(operands) == 2 and hasattr(operands[1], "get") and operands[1].get("/ActualText") is not None]
            for page in reader.pages]


def clean(value):
    return "".join(char for char in unicodedata.normalize("NFC", value) if not char.isspace())


@pytest.fixture(scope="module")
def original(tmp_path_factory):
    source = tmp_path_factory.mktemp("native-print") / "original.pdf"
    markup = ('<!doctype html><meta charset="utf-8"><style>@page{size:A4 landscape;margin:10mm}'
              'p{break-after:page;font:20pt sans-serif}p:last-child{break-after:auto}</style>' +
              "".join("<p>" + text + "</p>" for text in TEXT))
    result = render_pdf(markup, Path(__file__).resolve().parents[1] / "web", source, {})
    assert result["source_pages"] == result["sheets"] == 3
    assert result["passthrough"] is True
    assert [clean("".join(page)) for page in original_text(source)] == list(map(clean, TEXT))
    extracted = subprocess.check_output(["pdftotext", "-raw", str(source), "-"], text=True)
    assert all(clean(text) in clean(extracted) for text in TEXT)
    return source


def test_default_print_is_byte_identical(original, tmp_path):
    target = tmp_path / "unchanged.pdf"
    assert compose_pdf(original, target, {})["passthrough"] is True
    assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()


def test_native_page_ranges_remove_unselected_pages_without_losing_unicode(original, tmp_path):
    target = tmp_path / "selected.pdf"
    result = compose_pdf(original, target, {"ranges": [[0, 1]], "reverse": True})
    assert result["sheets"] == 2
    assert [clean("".join(page)) for page in original_text(target)] == [clean(TEXT[1]), clean(TEXT[0])]
    text = subprocess.check_output(["pdftotext", "-raw", str(target), "-"], text=True)
    assert clean(TEXT[2]) not in clean(text)
    assert all(clean(text_part) in clean(text) for text_part in TEXT[:2])


@pytest.mark.parametrize("collate,expected", [(True, [[0, 1], [2], [0, 1], [2]]), (False, [[0, 1], [0, 1], [2], [2]])])
def test_copies_apply_to_whole_sheets_and_preserve_original_clusters(original, tmp_path, collate, expected):
    target = tmp_path / "copies.pdf"
    compose_pdf(original, target, {"copies": 2, "collate": collate, "number_up": 2})
    actual = [clean("".join(page)) for page in original_text(target)]
    assert actual == [clean("".join(TEXT[index] for index in page)) for page in expected]


def test_paper_scale_and_nup_keep_vector_text_in_sheet_bounds(original, tmp_path):
    target = tmp_path / "letter.pdf"
    compose_pdf(original, target, {"number_up": 4, "scale": 75, "paper_width_mm": 215.9, "paper_height_mm": 279.4})
    reader = PdfReader(target)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(612, abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(792, abs=0.01)
    assert clean("".join(original_text(target)[0])) == clean("".join(TEXT))
    # Independent Poppler extraction must retain the original clusters after placement.
    text = subprocess.check_output(["pdftotext", "-raw", str(target), "-"], text=True)
    assert all(clean(part) in clean(text) for part in TEXT)


def test_custom_margins_and_reverse_orientation_keep_visible_ink_inside_sheet(original, tmp_path):
    from PIL import Image, ImageChops
    target = tmp_path / "margins.pdf"
    compose_pdf(original, target, {"ranges": [[0, 0]], "margins_mm": [20, 20, 20, 20], "orientation_reverse": True})
    assert PdfReader(target).pages[0].rotation == 180
    assert clean("".join(original_text(target)[0])) == clean(TEXT[0])
    image = tmp_path / "ink"
    subprocess.run(["pdftoppm", "-singlefile", "-scale-to", "842", "-png", str(target), str(image)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    with Image.open(image.with_suffix(".png")) as raster:
        rgb = raster.convert("RGB")
        bounds = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")).getbbox()
        assert bounds is not None
        safe = 20 * rgb.width / 297 - 1
        assert bounds[0] >= safe and bounds[1] >= safe
        assert bounds[2] <= rgb.width - safe and bounds[3] <= rgb.height - safe


@pytest.mark.parametrize("options", [{"margins_mm": [200, 200, 200, 200]}, {"margins_mm": [0, -1, 0, 0]},
    {"margins_mm": [True, 0, 0, 0]}, {"margins_mm": [0, 0]}, {"orientation_reverse": "yes"}])
def test_invalid_paper_area_is_not_silently_ignored(original, tmp_path, options):
    target = tmp_path / "invalid.pdf"
    with pytest.raises(ValueError):
        compose_pdf(original, target, options)
    assert not target.exists()


@pytest.mark.parametrize("options,expected", [
    ({"number_up": 2, "reverse": True}, [[2], [0, 1]]),
    ({"number_up": 2, "page_set": "even"}, [[2]]),
    ({"number_up": 2, "page_set": "odd"}, [[0, 1]]),
    ({"ranges": [[1, 999]]}, [[1], [2]]),
    ({"ranges": [[1, -1]]}, [[1], [2]]),
    ({"ranges": [[2, 2], [0, 0], [2, 2]]}, [[2], [0], [2]]),
])
def test_sheet_order_matches_gtk_range_nup_reverse_and_parity_contract(original, tmp_path, options, expected):
    target = tmp_path / "sheets.pdf"
    compose_pdf(original, target, options)
    assert [clean("".join(page)) for page in original_text(target)] == [
        clean("".join(TEXT[index] for index in sheet)) for sheet in expected]


def test_empty_sheet_filter_does_not_submit_an_empty_pdf(original, tmp_path):
    target = tmp_path / "empty.pdf"
    with pytest.raises(ValueError, match="sheet set is empty"):
        compose_pdf(original, target, {"ranges": [[0, 0]], "page_set": "even"})
    assert not target.exists()


@pytest.mark.parametrize("options", [
    {"ranges": [[-1, 1]]}, {"ranges": [[3, 3]]}, {"ranges": [[1, 0]]}, {"ranges": []},
    {"ranges": [[True, 1]]}, {"copies": 101}, {"copies": True}, {"page_set": "unknown"},
    {"reverse": 1}, {"collate": "yes"}, {"unknown": 1},
])
def test_invalid_or_empty_selection_is_rejected(options):
    with pytest.raises(ValueError):
        selected_pages(3, options)


@pytest.mark.parametrize("layout,expected", [(0, [(0, 0), (1, 0), (0, 1), (1, 1)]),
    (3, [(1, 1), (0, 1), (1, 0), (0, 0)]), (4, [(0, 0), (0, 1), (1, 0), (1, 1)]),
    (7, [(1, 1), (1, 0), (0, 1), (0, 0)])])
def test_gtk_layout_uses_physical_positions(layout, expected):
    assert sheet_positions(4, layout) == (2, 2, expected)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://example.org/private.png",
    "https://magnolie.invalid/book/../../etc/passwd", "https://magnolie.invalid:443/book/stil.css"])
def test_renderer_cannot_fetch_files_network_or_paths_outside_handbook(tmp_path, url):
    from weasyprint.urls import FatalURLFetchingError
    markup = '<style>@page{size:A4 landscape}</style><img src="' + url + '">'
    with pytest.raises(FatalURLFetchingError):
        render_pdf(markup, Path(__file__).resolve().parents[1] / "web", tmp_path / "blocked.pdf", {})
    assert not (tmp_path / "blocked.pdf").exists()
