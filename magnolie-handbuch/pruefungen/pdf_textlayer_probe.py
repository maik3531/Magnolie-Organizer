#!/usr/bin/env python3
"""Synthetic WebKit/Skia versus Pango/Cairo PDF text round trips.

Diagnostic only. Uses existing system fonts and an ephemeral WebKit context.
No font installation, browser fallback, invisible overlay or handbook modification.
Run under xvfb-run. Optional pypdf inspection is diagnostic, not a runtime dependency.
"""
import argparse
import gettext
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import unicodedata

FONTS = {
    "deva.ttf": "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "deva-serif.ttf": "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Regular.ttf",
    "cjk.ttc": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "droid.ttf": "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
}
HINDI = "पत्र लिखना नमस्ते क्षि त्र कि की"
CHINESE = "写信 联系人 设置 保存 地址 字体"
CASES = [
    ("hi-fallback", "hi", "Liberation Sans", HINDI, ""),
    ("hi-sans", "hi", "Noto Sans Devanagari", HINDI, ""),
    ("hi-serif", "hi", "Noto Serif Devanagari", HINDI, ""),
    ("hi-file", "hi", "ProbeDeva", HINDI, ""),
    ("hi-serif-file", "hi", "ProbeDevaSerif", HINDI, ""),
    ("zh-fallback", "zh-CN", "Liberation Sans", CHINESE, ""),
    ("zh-sc", "zh-CN", "Noto Sans CJK SC", CHINESE, ""),
    ("zh-jp", "zh-CN", "Noto Sans CJK JP", CHINESE, ""),
    ("zh-file", "zh-CN", "ProbeCJK", CHINESE, ""),
    # Diagnostic contrast only: disabling shaping is not a proposed fix.
    ("zh-no-locl", "zh-CN", "Noto Sans CJK SC", CHINESE, "font-feature-settings:'locl' 0;"),
    ("zh-droid", "zh-CN", "Droid Sans Fallback", CHINESE + " 页面 门 贝", ""),
    ("zh-droid-file", "zh-CN", "ProbeDroid", CHINESE + " 页面 门 贝", ""),
    ("zh-sc-alias", "zh-CN", "Noto Sans CJK SC", "页面 门 贝", ""),
    ("hi-unshaped-control", "hi", "Noto Sans Devanagari", "प त र ल ख न", ""),
    ("ja-control", "ja", "Noto Sans CJK JP", "手紙を書く 連絡先 設定 保存", ""),
    ("latin-control", "en", "Liberation Serif", "office affine ffi fi fl", ""),
]


def same_text(expected, actual):
    """Allow PDF line wrapping, but never fold CJK radicals into other characters."""
    def clean(value):
        return "".join(char for char in unicodedata.normalize("NFC", value) if not char.isspace())
    return clean(expected) == clean(actual)


def cmap_summary(pdf):
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"inspected": False, "reason": "Optional diagnostic pypdf module unavailable"}
    reader = PdfReader(pdf)
    fonts, seen = [], set()
    for page in reader.pages:
        for ref in page["/Resources"].get("/Font", {}).values():
            if ref.idnum in seen:
                continue
            seen.add(ref.idnum)
            font = ref.get_object()
            descriptor = font.get("/FontDescriptor", {})
            descriptor = descriptor.get_object() if hasattr(descriptor, "get_object") else descriptor
            stream = font.get("/ToUnicode")
            cmap = stream.get_object().get_data().decode("latin1") if stream else ""
            fonts.append({"object": ref.idnum, "subtype": str(font.get("/Subtype")),
                          "name": str(font.get("/BaseFont") or descriptor.get("/FontName")),
                          "nullMappings": re.findall(r"<([0-9A-Fa-f]+)>\s*<0000>", cmap),
                          "unicodeSequences": re.findall(r"<[0-9A-Fa-f]+>\s*<([0-9A-Fa-f]{8,})>", cmap),
                          "cmap": cmap})
    return {"inspected": True, "producer": str(reader.metadata.get("/Producer")), "fonts": fonts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    missing = [path for path in FONTS.values() if not Path(path).is_file()]
    if missing:
        raise SystemExit("Existing font controls unavailable; nothing installed: " + ", ".join(missing))
    import gi
    gi.require_version("WebKit2", "4.1")
    gi.require_version("Gtk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import WebKit2, Gtk, GLib, Gio, Pango, PangoCairo
    import cairo
    versions = {"webkit": ".".join(str(f()) for f in (WebKit2.get_major_version, WebKit2.get_minor_version, WebKit2.get_micro_version)),
                "pango": Pango.version_string(), "cairo": cairo.cairo_version_string()}
    font_info = {name: {"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                 for name, path in FONTS.items()}
    css = """@font-face{font-family:ProbeDeva;src:url('deva.ttf')}
@font-face{font-family:ProbeDevaSerif;src:url('deva-serif.ttf')}
@font-face{font-family:ProbeCJK;src:url('cjk.ttc')}
@font-face{font-family:ProbeDroid;src:url('droid.ttf')}
@page{size:A4 landscape;margin:10mm}body{font-size:17pt}p{margin:8px 0}label{font:10pt monospace}
"""
    markup = '<!doctype html><html><meta charset="utf-8"><style>' + css + '</style><body>'
    for name, language, family, text, extra in CASES:
        markup += (f'<label>{name}</label><p id="{name}" lang="{language}" '
                   f'style="font-family:\'{family}\';{extra}">{html.escape(text)}</p>')
    markup += '</body></html>'
    (output / "sample.html").write_text(markup)
    loop = GLib.MainLoop()
    context = WebKit2.WebContext.new_ephemeral()

    def resource(request):
        name = request.get_uri().rsplit("/", 1)[-1]
        if name == "sample.html":
            data, mime = markup.encode(), "text/html"
        elif name in FONTS:
            data = Path(FONTS[name]).read_bytes()
            mime = "font/collection" if name.endswith(".ttc") else "font/ttf"
        else:
            data, mime = b"", "text/plain"
        request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data), mime)

    context.register_uri_scheme("fontprobe", resource)
    security = context.get_security_manager()
    for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure", "register_uri_scheme_as_cors_enabled"):
        getattr(security, method)("fontprobe")
    view = WebKit2.WebView.new_with_context(context)
    status = {"code": 1, "failed": False}

    def finish(code):
        status["code"] = code
        loop.quit()

    def print_now():
        operation = WebKit2.PrintOperation.new(view)
        page = Gtk.PageSetup()
        page.set_paper_size(Gtk.PaperSize.new("iso_a4"))
        page.set_orientation(Gtk.PageOrientation.LANDSCAPE)
        operation.set_page_setup(page)
        settings = Gtk.PrintSettings()
        settings.set_printer(gettext.dgettext("gtk30", "Print to File"))
        settings.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, "pdf")
        settings.set(Gtk.PRINT_SETTINGS_OUTPUT_URI, (output / "webkit.pdf").as_uri())
        operation.set_print_settings(settings)

        def failed(_, error):
            status["failed"] = True
            print(error)

        operation.connect("failed", failed)
        operation.connect("finished", lambda *_: finish(1 if status["failed"] else 0))
        operation.print_()

    def ready(_, result, _data):
        value = json.loads(view.evaluate_javascript_finish(result).to_string())
        if value["status"] != "loaded":
            GLib.timeout_add(100, check)
            return
        assert all(font["status"] == "loaded" for font in value["fonts"]), value
        assert [row["text"] for row in value["rows"]] == [case[3] for case in CASES]
        (output / "dom.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        print_now()

    def check():
        view.evaluate_javascript("JSON.stringify({status:document.fonts.status,fonts:Array.from(document.fonts,f=>({family:f.family,status:f.status})),rows:Array.from(document.querySelectorAll('p'),p=>({id:p.id,text:p.textContent,font:getComputedStyle(p).fontFamily}))})",
                                 -1, None, None, None, ready, None)
        return False

    view.connect("load-changed", lambda _, event: GLib.timeout_add(300, check) if event == WebKit2.LoadEvent.FINISHED else None)
    view.load_uri("fontprobe://app/sample.html")
    GLib.timeout_add_seconds(60, lambda: (finish(1), False)[1])
    loop.run()
    view.destroy()
    assert status["code"] == 0, "Native printing failed"

    # Control only, not a replacement for the handbook's HTML print layout.
    surface = cairo.PDFSurface(str(output / "pango-cairo.pdf"), 842, 595)
    cr = cairo.Context(surface)
    y, references = 25, []
    for name, language, family, text, _ in CASES:
        if name.endswith("-file") or name == "zh-no-locl":
            continue
        layout = PangoCairo.create_layout(cr)
        layout.get_context().set_language(Pango.Language.from_string(language))
        layout.set_font_description(Pango.FontDescription(family + " 17"))
        layout.set_text(text, -1)
        cr.move_to(25, y)
        PangoCairo.show_layout(cr, layout)
        references.append(text)
        y += 48
    surface.finish()
    extracted = {}
    for name in ("webkit", "pango-cairo"):
        extracted[name] = subprocess.check_output(["pdftotext", "-raw", str(output / (name + ".pdf")), "-"], text=True)
        (output / (name + ".txt")).write_text(extracted[name])
    results = []
    for index, (name, language, family, expected, _) in enumerate(CASES):
        part = extracted["webkit"].split(name + "\n", 1)[1]
        if index + 1 < len(CASES):
            part = part.split(CASES[index + 1][0] + "\n", 1)[0]
        actual = part.replace("\f", "").strip()
        result = {"case": name, "language": language, "font": family, "expected": expected,
                  "actual": actual, "nfcRoundTrip": same_text(expected, actual),
                  "exactIncludingSpaces": expected == actual}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    reference_ok = same_text("\n".join(references), extracted["pango-cairo"].replace("\f", ""))
    report = {"versions": versions, "fonts": font_info, "cases": results,
              "pangoCairoRoundTrip": reference_ok,
              "pdfs": {name: cmap_summary(output / (name + ".pdf")) for name in ("webkit", "pango-cairo")}}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    assert reference_ok, "The independent Pango/Cairo reference did not preserve the source text"
    assert all(result["nfcRoundTrip"] for result in results), "WebKit PDF lost or substituted source characters; see results.json"


if __name__ == "__main__":
    main()
