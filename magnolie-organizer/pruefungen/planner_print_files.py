#!/usr/bin/env python3
"""Verify actual native ODS bytes and optionally render them with existing LibreOffice.

Only the four pure export functions and ODS limits are compiled from the specified
launcher. No application/profile/service initialization is executed.
"""
import argparse
import ast
import atexit
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("evidence", type=Path)
parser.add_argument("--program", type=Path, required=True)
parser.add_argument("--pdf", action="store_true")
parser.add_argument("--output", type=Path, help="New evidence directory; inputs are never overwritten")
parser.add_argument("--reference", type=Path, help="Prior synthetic evidence for noncrowded PDF parity")
parser.add_argument("--peer", type=Path, help="Other desktop JS evidence; require identical HTML and ODS payloads")
args = parser.parse_args()
assert args.evidence.resolve().is_relative_to("/tmp/opencode")
assert not args.peer or args.peer.resolve().is_relative_to("/tmp/opencode")
output_root = args.output or Path(tempfile.mkdtemp(prefix="planner-pdf-", dir="/tmp/opencode"))
assert output_root.resolve().is_relative_to("/tmp/opencode")
if args.output:
    output_root.mkdir()
print("EVIDENCE", output_root, flush=True)
source = args.program.read_bytes()
tree = ast.parse(source)
names = {"_ods_xml_text", "adressen_ods_pruefen", "planer_ods_inhalte_pruefen", "adressen_ods_bytes"}
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names or
         isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith("ODS_") for t in node.targets)]
assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == names
scope = {"re": re, "io": io, "zipfile": zipfile, "ET": ET, "_": lambda text: text}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(args.program), "exec"), scope)
ns = {key: "urn:oasis:names:tc:opendocument:xmlns:" + value for key, value in
      {"table": "table:1.0", "text": "text:1.0", "style": "style:1.0", "fo": "xsl-fo-compatible:1.0"}.items()}
attr = lambda key: "{" + ns[key.split(":")[0]] + "}" + key.split(":")[1]
report = {"program": str(args.program), "sha256": hashlib.sha256(source).hexdigest(),
          "input_evidence": str(args.evidence), "peer_evidence": str(args.peer) if args.peer else None,
          "ok": False, "files": [], "pdf": [], "noncrowded_parity": []}
atexit.register(lambda: (output_root / "native-print-results.json").write_text(json.dumps(report, indent=2)))
artifacts = {}
for path in sorted(args.evidence.glob("*-*.json")):
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or "ods" not in payload:
        continue
    ods = payload["ods"]
    if args.peer:
        assert ods == json.loads((args.peer / path.name).read_text())["ods"], (path.name, "desktop ODS parity")
        assert path.with_suffix(".html").read_bytes() == (args.peer / path.with_suffix(".html").name).read_bytes(), (path.name, "desktop HTML parity")
    artifacts[path.stem] = payload
    raw = scope["adressen_ods_bytes"](ods["titel"], ods["spalten"], ods["zeilen"], logo_pfad="",
        zellstile=ods["stile"], kompakt=True, kalenderinhalte=ods["inhalte"])
    output = output_root / path.with_suffix(".ods").name
    output.write_bytes(raw)
    (output_root / path.with_suffix(".html").name).write_bytes(path.with_suffix(".html").read_bytes())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet"
        root = ET.fromstring(archive.read("content.xml"))
        styles = {s.get(attr("style:name")): s for s in root.findall(".//style:style", ns)}
        rows = root.findall(".//table:table/table:table-row", ns)[1:]
        assert len(rows) == len(ods["inhalte"])
        for row, expected in zip(rows, ods["inhalte"]):
            cells = row.findall("table:table-cell", ns)
            assert len(cells) == len(expected)
            for cell, content in zip(cells, expected):
                paragraphs = cell.findall("text:p", ns)
                labels = ["".join(p.itertext()) for p in paragraphs]
                first = content["datum"] + "".join(" " + m["text"] for m in content.get("marker", []))
                entries = content["eintraege"]
                expected_labels = [first] + [("\u258c " if ods["layout"] == "month" else "") + e["text"] for e in entries]
                if content.get("mehr"):
                    expected_labels.append("+" + str(content["mehr"]))
                assert labels == expected_labels, (path.name, labels, expected_labels)
                if ods["layout"] == "month":
                    for paragraph, entry in zip(paragraphs[1:], entries):
                        bar = paragraph.find("text:span", ns)
                        style = styles[bar.get(attr("text:style-name"))]
                        assert style.find("style:text-properties", ns).get(attr("fo:color")) == entry["farbe"]
                    for marker, expected_marker in zip(paragraphs[0].findall("text:span", ns)[1:], content.get("marker", [])):
                        style = styles[marker.get(attr("text:style-name"))]
                        assert style.find("style:text-properties", ns).get(attr("fo:color")) == expected_marker["farbe"]
    report["files"].append({"name": output.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "cells": sum(map(len, ods["inhalte"]))})
assert report["files"], "No print artifacts found"
if args.pdf:
    isolated = Path(tempfile.mkdtemp(prefix="planner-lo-", dir="/tmp/opencode"))
    env = dict(os.environ, SAL_USE_VCLPLUGIN="svp", LIBGL_ALWAYS_SOFTWARE="1", GDK_BACKEND="x11", LC_ALL="C.UTF-8", LANG="C.UTF-8",
               GSETTINGS_BACKEND="memory", WEBKIT_DISABLE_DMABUF_RENDERER="1", NO_AT_BRIDGE="1")
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        directory = isolated / name.lower()
        directory.mkdir(mode=0o700)
        env[name] = str(directory)
    os.environ.clear()
    os.environ.update(env)
    assert env.get("DISPLAY"), "Run PDF checks under xvfb-run"
    assert not Path("/dev/dri").exists(), "Run with GPU devices hidden"
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, GLib, WebKit2
    from PIL import Image
    Gtk.Settings.get_default().set_property("gtk-print-backends", "file")
    context = WebKit2.WebContext.new_ephemeral()

    def html_pdf(html, pdf, orientation):
        view = WebKit2.WebView(web_context=context)
        view.get_settings().set_enable_javascript(False)
        view.get_settings().set_print_backgrounds(True)
        view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
        window = Gtk.OffscreenWindow()
        window.add(view)
        window.show_all()
        loop, errors, operations = GLib.MainLoop(), [], []
        def loaded(_view, event):
            if event != WebKit2.LoadEvent.FINISHED or operations:
                return
            operation = WebKit2.PrintOperation.new(view)
            operations.append(operation)
            settings = Gtk.PrintSettings.new()
            settings.set_printer("Print to File")
            settings.set("output-file-format", "pdf")
            settings.set("output-uri", pdf.as_uri())
            page = Gtk.PageSetup.new()
            page.set_paper_size(Gtk.PaperSize.new("iso_a4"))
            page.set_orientation(Gtk.PageOrientation.LANDSCAPE if orientation == "landscape" else Gtk.PageOrientation.PORTRAIT)
            settings.set_orientation(page.get_orientation())
            for side in ("top", "bottom", "left", "right"):
                getattr(page, "set_" + side + "_margin")(8, Gtk.Unit.MM)
            operation.set_page_setup(page)
            operation.set_print_settings(settings)
            operation.connect("failed", lambda _op, error: errors.append(str(error)))
            operation.connect("finished", lambda _op: loop.quit())
            operation.print_()
        handler = view.connect("load-changed", loaded)
        timer = GLib.timeout_add_seconds(30, lambda: (errors.append("WebKit print timeout"), loop.quit(), False)[-1])
        view.load_html(html, "file:///tmp/opencode/")
        loop.run()
        GLib.source_remove(timer)
        view.disconnect(handler)
        window.destroy()
        assert not errors and pdf.is_file(), errors

    def words(pdf, one_page=True):
        bbox = subprocess.check_output(["pdftotext", "-bbox", str(pdf), "-"], text=True, env=env)
        (output_root / (pdf.stem + ".bbox.html")).write_text(bbox)
        pages = ET.fromstring(bbox).findall(".//{*}page")
        assert not one_page or len(pages) == 1, (pdf.name, "page count", len(pages))
        pages[0].set("pages", str(len(pages)))
        return pages[0], [{"text": w.text or "", "page": index, **{k: float(v) for k, v in w.attrib.items()}}
                          for index, page in enumerate(pages) for w in page.findall(".//{*}word")]

    def check_pdf(pdf, payload, orientation):
        ods, model = payload["ods"], payload["model"]
        # The unchanged year HTML is a parity control, not the one-page month grid.
        page, boxes = words(pdf, one_page=ods["layout"] == "month")
        width, height = float(page.get("width")), float(page.get("height"))
        assert (width > height) == (orientation == "landscape"), (pdf.name, width, height)
        expected_more = Counter("+" + str(cell["mehr"]) for row in ods["inhalte"] for cell in row if cell.get("mehr"))
        found_more = Counter(w["text"] for w in boxes if re.fullmatch(r"\+\d+", w["text"]))
        assert found_more == expected_more, (pdf.name, "overflow labels", found_more, expected_more)
        markers = []
        if ods["layout"] == "month":
            dates = []
            for r, week in enumerate(model["wochen"]):
                for c, day in enumerate(week["tage"]):
                    if day["imMonat"]:
                        candidates = [w for w in boxes if w["text"] == str(day["tag"]) and w["xMin"] > width*.05]
                        assert candidates, (pdf.name, "missing day", day["iso"])
                        dates.append((r, c, day, max(candidates, key=lambda w: w["yMax"]-w["yMin"])))
            lefts = [statistics.median(w["xMin"] for _, c, _, w in dates if c == col) for col in range(7)]
            tops = {r: min(w["yMin"] for row, _, _, w in dates if row == r) for r in set(d[0] for d in dates)}
            row_height = statistics.median((tops[b]-tops[a])/(b-a) for a, b in zip(sorted(tops), sorted(tops)[1:]))
            col_width = statistics.median(b-a for a, b in zip(lefts, lefts[1:]))
            subprocess.run(["pdftoppm", "-singlefile", "-r", "144", "-png", str(pdf), str(pdf.with_suffix(""))],
                           env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            image = Image.open(pdf.with_suffix(".png")).convert("RGB")
            for r, c, day, date in dates:
                inside = [w for w in boxes if lefts[c]-.5 <= w["xMin"] < lefts[c]+col_width-2 and
                          date["yMax"]-.5 <= w["yMin"] < tops[r]+row_height-2]
                prefixes = Counter(next((p for p in e["text"].split() if re.search("[A-Za-z]", p)), e["text"].split()[0])
                                   for e in day["eintraege"][:5])
                for prefix, count in prefixes.items():
                    visible = [w for w in inside if w["xMax"] < lefts[c]+col_width-1 and
                               (w["text"] == prefix or w["text"].endswith("\u2026") and
                                len(w["text"]) >= 4 and prefix.startswith(w["text"][:-1]))]
                    assert len(visible) >= count, (pdf.name, day["iso"], "invisible entry prefix", prefix, count)
                    for box in visible[:count]:
                        assert box["yMax"] < tops[r]+row_height-2, (pdf.name, "entry clipped vertically", prefix)
                        crop = image.crop(tuple(round(box[k]*2) for k in ("xMin", "yMin", "xMax", "yMax")))
                        assert sum(max(pixel) < 150 for pixel in crop.getdata()) > 12, (pdf.name, "entry has no visible ink", prefix)
                more = max(0, len(day["eintraege"])-5)
                if more:
                    label = "+" + str(more)
                    matching = [w for w in inside if w["text"] == label]
                    assert len(matching) == 1, (pdf.name, day["iso"], "misplaced summary", label)
                    box = matching[0]
                    assert box["yMax"] < tops[r]+row_height-2 and box["xMax"] < lefts[c]+col_width-2
                    crop = image.crop(tuple(round(box[k]*2) for k in ("xMin", "yMin", "xMax", "yMax")))
                    ink = sum(max(pixel)-min(pixel) < 80 and max(pixel) < 150 for pixel in crop.getdata())
                    assert ink > 12, (pdf.name, "summary has no visible ink", box)
                    markers.append({"date": day["iso"], "label": label, "box": box, "ink_pixels": ink})
        report["pdf"].append({"name": pdf.name, "pages": int(page.get("pages")), "orientation": orientation,
                              "markers": markers, "overflow_complete": True})
        return boxes

    for name in ("month-all", "month-none", "month-without-muell", "month-without-termine",
                 "month-dense-all", "month-dense-none", "month-dense-selected", "month-dense-without-muell", "year-7"):
        for orientation in ("landscape", "portrait"):
            file = output_root / (name + "-" + orientation + ".ods")
            with zipfile.ZipFile(output_root / (name + ".ods")) as source_zip, zipfile.ZipFile(file, "w") as target:
                for info in source_zip.infolist():
                    raw = source_zip.read(info.filename)
                    if orientation == "portrait" and info.filename == "styles.xml":
                        raw = raw.replace(b'fo:page-width="29.7cm"', b'fo:page-width="21cm"').replace(
                            b'fo:page-height="21cm"', b'fo:page-height="29.7cm"').replace(b'print-orientation="landscape"', b'print-orientation="portrait"')
                    target.writestr(info, raw)
            subprocess.run(["libreoffice", "-env:UserInstallation=" + (isolated / "office").as_uri(),
                "--headless", "--convert-to", "pdf", "--outdir", str(output_root), str(file)],
                env=env, check=True, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            lo_boxes = check_pdf(file.with_suffix(".pdf"), artifacts[name], orientation)
            html_path = output_root / (name + "-html-" + orientation + ".pdf")
            html_pdf((output_root / (name + ".html")).read_text(), html_path, orientation)
            html_boxes = check_pdf(html_path, artifacts[name], orientation)
            if args.reference and orientation == "landscape" and name in ("month-without-termine", "year-7"):
                assert args.reference.resolve().is_relative_to("/tmp/opencode")
                _, old_boxes = words(args.reference / (name + ".pdf"))
                assert lo_boxes == old_boxes, (name, "noncrowded LibreOffice parity")
                reference_pdf = output_root / (name + "-reference-html.pdf")
                html_pdf((args.reference / (name + ".html")).read_text(), reference_pdf, orientation)
                _, old_html_boxes = words(reference_pdf, one_page=False)
                assert Counter((w["text"], round(w["yMax"]-w["yMin"], 2)) for w in html_boxes) == Counter(
                    (w["text"], round(w["yMax"]-w["yMin"], 2)) for w in old_html_boxes), (name, "noncrowded HTML text/font/count parity")
                report["noncrowded_parity"].append({"name": name, "ods_word_boxes": True, "html_text_font_counts": True})
assert args.program.read_bytes() == source
report["ok"] = True
print(json.dumps({"files": len(report["files"]), "pdfs": len(report["pdf"]),
                  "visible_summaries": sum(len(pdf["markers"]) for pdf in report["pdf"]), "ok": True}))
