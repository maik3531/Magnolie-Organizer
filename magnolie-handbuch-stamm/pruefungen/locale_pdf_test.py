#!/usr/bin/env python3
"""Native WebKit PDF probes for all handbook locales, in an isolated output directory.

Run under xvfb-run; this writes test PDFs, never prints to a physical printer.
Text extraction and geometry checks are not a native-speaker or visual certification.
"""
import argparse
import gettext
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def normalized(text):
    return "".join(char for char in unicodedata.normalize("NFKC", text)
                   if not char.isspace() and unicodedata.category(char) != "Cf")


def title_present(text, title, rtl=False):
    visible = normalized(text)
    forms = [title]
    if rtl:
        # pdftotext can return bidi-isolated Arabic words in visual order.
        # Keep every character: this must not hide missing-glyph mappings.
        forms.extend([title[::-1], " ".join(reversed(title.split()))])
    return any(normalized(form) in visible for form in forms)


def test_title_extraction_preserves_letters_and_respects_rtl():
    assert title_present("\u202bالرسائل\u202c \u202bكتابة\u202c", "كتابة الرسائل", True)
    assert not title_present("الرسائل كتا", "كتابة الرسائل", True)
    assert not title_present("letters Writing", "Writing letters")
    assert not title_present("प लखना", "पत्र लिखना")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reuse-current", action="store_true",
                        help="Recheck existing test PDFs only if newer than every web input")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    languages = ["en", *(ROOT / "po/LINGUAS").read_text().split()]
    results = []
    extraction_failures = []
    latest_input = max(path.stat().st_mtime_ns for path in (ROOT / "web").rglob("*") if path.is_file())
    for language in languages:
        pdf = args.output / (language + ".pdf")
        if not (args.reuse_current and pdf.is_file() and pdf.stat().st_mtime_ns >= latest_input):
            run = subprocess.run([sys.executable, "-B", str(ROOT / "pruefungen/druck_pdf.py"), str(pdf)],
                                 env=dict(os.environ, MAGNOLIE_HANDBUCH_TEST_LANGUAGE=language,
                                          PYTHONDONTWRITEBYTECODE="1"),
                                 capture_output=True, text=True, timeout=180)
            if run.returncode:
                raise AssertionError((language, run.stdout, run.stderr))
        info = subprocess.check_output(["pdfinfo", str(pdf)], text=True)
        geometry = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", info)
        assert geometry and abs(float(geometry[1]) - 842) < 2 and abs(float(geometry[2]) - 595) < 2, (language, info)
        pages = int(re.search(r"Pages:\s+(\d+)", info)[1])
        assert pages >= 82, (language, pages)
        text = subprocess.check_output(["pdftotext", "-raw", str(pdf), "-"], text=True)
        physical = text.split("\f")
        if not physical[-1].strip():
            physical.pop()
        assert len(physical) == pages and all(page.strip() for page in physical), language
        assert len(text) > 10000, language
        assert "DIN" in text and "5008" in text, language
        translation = gettext.NullTranslations() if language == "en" else gettext.translation(
            "magnolie-handbuch", localedir=str(ROOT / "locale"), languages=[language])
        title = translation.gettext("Writing letters")
        visible = normalized(text)
        title_extractable = title_present(text, title, language == "ar")
        if not title_extractable:
            extraction_failures.append(language)
        if language == "en":
            assert "SupportMagnoliewithacoffee" in visible
            assert "EineE-Mail-Adressebleibtfreiwillig" not in visible
        result = {"locale": language, "pages": pages, "width": float(geometry[1]),
                  "height": float(geometry[2]), "textCharacters": len(text),
                  "letterTitleExtractable": title_extractable, "path": str(pdf)}
        results.append(result)
        print(json.dumps(result), flush=True)
        (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    assert not extraction_failures, "PDF title text extraction failed: " + ", ".join(extraction_failures)
    print("ALL 20 NATIVE HANDBOOK PDF PROBES PASSED", flush=True)


if __name__ == "__main__":
    main()
