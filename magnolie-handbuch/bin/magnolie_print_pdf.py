"""Semantic handbook PDF rendering and print-sheet composition (Refs #236).

Run rendering in a separate, cancellable process. Resources are restricted to
the canonical handbook asset policy; shaping and the visible text stay intact.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit, urlunsplit


MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_HTML_BYTES = 8_000_000


class EmptyPrintSelection(ValueError):
    """GTK treats a valid range/sheet filter selecting nothing as cancellation."""


def verify_runtime(directory=None):
    """Verify the packaged dependency tree against its canonical lock and hashes."""
    directory = Path(directory) if directory is not None else Path(__file__).resolve().parent / "pdf-runtime"
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("The packaged handbook PDF runtime is unavailable")
    lock_bytes = Path(__file__).with_name("pdf-runtime-lock.json").read_bytes()
    lock = json.loads(lock_bytes)
    manifest_path = directory / "runtime-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 1024 * 1024:
        raise RuntimeError("The packaged PDF runtime manifest is unavailable")
    manifest = json.loads(manifest_path.read_bytes())
    packages = [{key: item[key] for key in ("name", "version", "filename", "sha256")} for item in manifest["packages"]]
    if (manifest.get("schema") != 1 or manifest.get("lock_sha256") != hashlib.sha256(lock_bytes).hexdigest() or
            packages != lock["packages"]):
        raise RuntimeError("The packaged PDF runtime differs from its dependency lock")
    for name, expected in manifest["files"].items():
        path = directory / name
        if (not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink() or not path.is_file() or
                path.stat().st_size > 64 * 1024 * 1024 or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise RuntimeError("The packaged PDF runtime is incomplete or changed")
    return directory.resolve()


def activate_runtime(directory=None):
    """Load only the packaged lock-matching PDF runtime, never download at run time."""
    import sys
    sys.path.insert(0, str(verify_runtime(directory)))


def selected_pages(count, options):
    """Expand logical ranges; GTK sheet filters/order apply after n-up grouping."""
    if type(count) is not int or not 1 <= count <= 2000:
        raise ValueError("Invalid document page count")
    allowed = {"ranges", "page_set", "reverse", "copies", "collate", "number_up",
               "number_up_layout", "scale", "paper_width_mm", "paper_height_mm", "margins_mm", "orientation_reverse", "paper_landscape"}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError("Invalid print options")
    ranges = options.get("ranges")
    if ranges is None:
        pages = list(range(count))
    else:
        if not isinstance(ranges, list) or not 1 <= len(ranges) <= 2000:
            raise ValueError("Invalid page ranges")
        pages = []
        for pair in ranges:
            if (not isinstance(pair, list) or len(pair) != 2 or
                    any(type(value) is not int for value in pair) or
                    not 0 <= pair[0] <= 2 ** 31 - 1 or
                    not (pair[1] == -1 or pair[0] <= pair[1] <= 2 ** 31 - 1)):
                raise ValueError("Invalid page range")
            end = count - 1 if pair[1] == -1 else min(pair[1], count - 1)
            if pair[0] >= count:
                continue
            if len(pages) + end - pair[0] + 1 > 32000:
                raise ValueError("Print selection contains too many logical pages")
            pages.extend(range(pair[0], end + 1))
    page_set = options.get("page_set", "all")
    if page_set not in ("all", "even", "odd"):
        raise ValueError("Invalid page set")
    reverse = options.get("reverse", False)
    collate = options.get("collate", True)
    if type(reverse) is not bool or type(collate) is not bool:
        raise ValueError("Invalid print order")
    copies = options.get("copies", 1)
    if type(copies) is not int or not 1 <= copies <= 100:
        raise ValueError("Invalid copy count")
    if not pages:
        raise EmptyPrintSelection("The selected page set is empty")
    return pages, copies, collate


def sheet_positions(number_up, layout, landscape=True):
    """GTK NumberUpLayout order expressed as (column, top-to-bottom row)."""
    if type(number_up) is not int or number_up not in (1, 2, 4, 6, 9, 16):
        raise ValueError("Invalid pages per sheet")
    if type(layout) is not int or not 0 <= layout <= 7:
        raise ValueError("Invalid page layout")
    columns = math.ceil(math.sqrt(number_up))
    rows = number_up // columns
    if landscape:
        columns, rows = rows, columns
    xs, ys = list(range(columns)), list(range(rows))
    if layout in (2, 3, 5, 7):
        xs.reverse()
    if layout in (1, 3, 6, 7):
        ys.reverse()
    positions = ([(x, y) for y in ys for x in xs] if layout < 4 else
                 [(x, y) for x in xs for y in ys])
    if number_up in (2, 6):
        # GTK rotates these logical page grids by 90 degrees on the sheet.
        return rows, columns, [(y, columns - 1 - x) for x, y in positions]
    return columns, rows, positions


def compose_pdf(source, target, options):
    """Apply print options as vector PDF operations, retaining ActualText."""
    from pypdf import PdfReader, PdfWriter, Transformation

    reader = PdfReader(source)
    pages, copies, collate = selected_pages(len(reader.pages), options)
    number_up = options.get("number_up", 1)
    scale = options.get("scale", 100)
    if type(scale) not in (int, float) or not math.isfinite(scale) or not 1 <= scale <= 1000:
        raise ValueError("Invalid print scale")
    width = options.get("paper_width_mm", 297)
    height = options.get("paper_height_mm", 210)
    if any(type(value) not in (int, float) or not math.isfinite(value) or
           not 20 <= value <= 2000 for value in (width, height)):
        raise ValueError("Invalid paper dimensions")
    width, height = width * 72 / 25.4, height * 72 / 25.4
    landscape = options.get("paper_landscape", width >= height)
    if type(landscape) is not bool:
        raise ValueError("Invalid paper orientation")
    columns, rows, positions = sheet_positions(number_up, options.get("number_up_layout", 0), landscape)
    margins = options.get("margins_mm", [0, 0, 0, 0])
    if (not isinstance(margins, list) or len(margins) != 4 or
            any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in margins)):
        raise ValueError("Invalid print margins")
    top, right, bottom, left = [value * 72 / 25.4 for value in margins]
    content_width, content_height = width - left - right, height - top - bottom
    if content_width <= 0 or content_height <= 0:
        raise ValueError("Print margins leave no printable area")
    orientation_reverse = options.get("orientation_reverse", False)
    if type(orientation_reverse) is not bool:
        raise ValueError("Invalid paper orientation")
    sheets = [pages[index:index + number_up] for index in range(0, len(pages), number_up)]
    page_set = options.get("page_set", "all")
    if page_set != "all":
        sheets = [sheet for index, sheet in enumerate(sheets) if (index + 1) % 2 == (page_set == "odd")]
    if options.get("reverse", False):
        sheets.reverse()
    if not sheets:
        raise EmptyPrintSelection("The selected sheet set is empty")
    # Copies apply to physical sheets, not individual logical pages on a sheet.
    sheets = sheets * copies if collate else [sheet for sheet in sheets for _ in range(copies)]
    if len(sheets) > 2000:
        raise ValueError("Print job contains too many sheets")
    original_size = all(abs(float(page.mediabox.width) - width) < 0.05 and
                        abs(float(page.mediabox.height) - height) < 0.05 for page in reader.pages)
    passthrough = (sheets == [[index] for index in range(len(reader.pages))] and
                   number_up == 1 and scale == 100 and original_size and not any(margins) and not orientation_reverse)
    with open(target, "xb") as output:
        if passthrough:
            with open(source, "rb") as stream:
                shutil.copyfileobj(stream, output)
        else:
            writer = PdfWriter()
            for selected in sheets:
                if number_up == 1 and scale == 100 and original_size and not any(margins) and not orientation_reverse:
                    writer.add_page(reader.pages[selected[0]])
                    continue
                sheet = writer.add_blank_page(width=width, height=height)
                rotate = number_up in (2, 6)
                dimensions = []
                for index in selected:
                    page = reader.pages[index]
                    if page.rotation:
                        page.transfer_rotation_to_content()
                    box = page.mediabox
                    dimensions.append((float(box.height), float(box.width)) if rotate else
                                      (float(box.width), float(box.height)))
                slot_width = max(item[0] for item in dimensions)
                slot_height = max(item[1] for item in dimensions)
                factor = min(content_width / (columns * slot_width), content_height / (rows * slot_height)) * scale / 100
                block_left = left + (content_width - columns * slot_width * factor) / 2
                block_bottom = bottom + (content_height - rows * slot_height * factor) / 2
                for slot, index in enumerate(selected):
                    page = reader.pages[index]
                    box = page.mediabox
                    column, row = positions[slot]
                    placed_width, placed_height = dimensions[slot]
                    x = block_left + (column * slot_width + (slot_width - placed_width) / 2) * factor
                    y = block_bottom + ((rows - row - 1) * slot_height + (slot_height - placed_height) / 2) * factor
                    transform = Transformation().translate(-float(box.left), -float(box.bottom))
                    if rotate:
                        transform = transform.rotate(90)
                        x += float(box.height) * factor
                    transform = transform.scale(factor).translate(x, y)
                    sheet.merge_transformed_page(page, transform, over=True, expand=False)
                if orientation_reverse:
                    sheet.rotate(180)
            writer.write(output)
        output.flush()
        if output.tell() > MAX_PDF_BYTES:
            raise ValueError("Print PDF exceeds the size limit")
        os.fsync(output.fileno())
    return {"source_pages": len(reader.pages), "sheets": len(sheets), "passthrough": passthrough}


def render_pdf(markup, web_root, target, options):
    """Render original text once, then apply the selected print-sheet options."""
    if not isinstance(markup, str) or not 1 <= len(markup.encode("utf-8")) <= MAX_HTML_BYTES:
        raise ValueError("Invalid print HTML")
    import pydyf
    import weasyprint
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher, URLFetcherResponse, FatalURLFetchingError
    import weasyprint.draw.text as drawing
    from magnolie_asset import read_handbook_request

    if weasyprint.__version__ != "70.0":
        raise RuntimeError("The pinned handbook PDF renderer is unavailable")
    web_root = str(Path(web_root).resolve(strict=True))

    class HandbookFetcher(URLFetcher):
        def __init__(self):
            super().__init__(timeout=1, allowed_protocols={"data"}, allow_redirects=False, fail_on_errors=True)

        def fetch(self, url, headers=None):
            parsed = urlsplit(url)
            if len(url) > MAX_PDF_BYTES:
                raise FatalURLFetchingError("Print resource exceeds the size limit")
            if parsed.scheme == "data":
                return super().fetch(url, headers)
            if parsed.scheme == "https" and parsed.netloc == "magnolie.invalid" and parsed.path.startswith("/book/"):
                request = urlunsplit(("magnolie-handbuch", "app", parsed.path[len("/book"):], parsed.query, parsed.fragment))
            elif parsed.scheme == "magnolie-handbuch" and parsed.netloc == "app":
                request = url
            else:
                raise FatalURLFetchingError("Resource outside the handbook")
            resource = read_handbook_request(request, web_root)
            if resource is None:
                raise FatalURLFetchingError("Handbook resource is unavailable")
            content, mime = resource
            if len(content) > 32 * 1024 * 1024:
                raise FatalURLFetchingError("Print resource exceeds the size limit")
            return URLFetcherResponse(url, content, {"Content-Type": mime})

    original = drawing.draw_first_line

    def draw_original_text(stream, textbox, text_overflow, block_ellipsis, matrix):
        if text_overflow == "ellipsis" or block_ellipsis != "none":
            raise ValueError("Truncated text requires a separate original-text mapping")
        if not textbox.text.strip() or textbox.style["font_size"] < 1e-6:
            return original(stream, textbox, text_overflow, block_ellipsis, matrix)
        stream.begin_marked_content("Span", pydyf.Dictionary({"ActualText": pydyf.String(textbox.text)}))
        try:
            return original(stream, textbox, text_overflow, block_ellipsis, matrix)
        finally:
            stream.end_marked_content()

    with tempfile.TemporaryDirectory(prefix=".magnolie-print-", dir=Path(target).parent) as temporary:
        source = Path(temporary) / "original.pdf"
        drawing.draw_first_line = draw_original_text
        try:
            # urllib's relative-URL resolution does not recognize custom schemes.
            # This virtual origin is handled locally above and never reaches HTTP.
            markup = re.sub(r"<base\b[^>]*>", "", markup, flags=re.IGNORECASE)
            HTML(string=markup, base_url="https://magnolie.invalid/book/", url_fetcher=HandbookFetcher()).write_pdf(source)
        finally:
            drawing.draw_first_line = original
        if source.stat().st_size > MAX_PDF_BYTES:
            raise ValueError("Print PDF exceeds the size limit")
        return compose_pdf(source, target, options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("web_root", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_PDF_BYTES, MAX_PDF_BYTES))
    activate_runtime(args.runtime)
    import sys
    payload = sys.stdin.buffer.read(MAX_HTML_BYTES + 1)
    if len(payload) > MAX_HTML_BYTES:
        raise ValueError("Print request exceeds the size limit")
    request = json.loads(payload)
    if not isinstance(request, dict) or set(request) != {"html", "options"}:
        raise ValueError("Invalid print request")
    try:
        result = render_pdf(request["html"], args.web_root, args.target, request["options"])
    except EmptyPrintSelection:
        print(json.dumps({"ok": False, "cancelled": True}))
        return
    print(json.dumps({"ok": True, **result}))


if __name__ == "__main__":
    main()
