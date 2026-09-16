#!/usr/bin/env python3
"""Regenerate the English gettext template from handbook sources."""

import json
import os
import subprocess
import argparse
import shutil
import sys
import re
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "web", "inhalt.js")
MARKERS = os.path.join(ROOT, "web", "i18n-markers.js")


def package_version(root=ROOT):
    with open(os.path.join(root, "web", "version.json"), encoding="utf-8") as source:
        metadata = json.load(source)
    version = metadata.get("version") if isinstance(metadata, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("web/version.json")
    return version


def handbook_data(content=CONTENT):
    runner = next((shutil.which(name) for name in ("node", "nodejs", "bun") if shutil.which(name)), None)
    if not runner:
        raise FileNotFoundError("node/nodejs/bun")
    result = subprocess.run([runner, os.path.join(ROOT, "werkzeuge", "handbook_data.js"),
                             os.path.dirname(content)], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def handbook_messages(content=CONTENT):
    data = handbook_data(content)
    for page in data["pages"]:
        for key in ("kapitel", "titel", "inhalt"):
            if page.get(key):
                yield page[key]
        if page.get("inhaltAnhang") and not page.get("inhaltAnhangNeutral"):
            yield page["inhaltAnhang"]["en"]
    for variant in data["variants"].values():
        yield variant["en"]


def marker_erzeugen(content=CONTENT, markers=MARKERS):
    messages = set(handbook_messages(content))
    messages.update([
        "Magnolie Organizer - Handbook", "Magnolie Organizer · Handbook",
        "Back one spread", "Forward one spread", "Ring binding", "Click to open",
        "Organizer · User Guide", "Click to open the book", "Contents", "Print / PDF",
        "Go to the table of contents", "Print the entire handbook or save it as a PDF",
        "Page", "and", "of", "Search", "Search handbook", "Close search",
        "No matching handbook pages.",
    ])
    with open(markers, "w", encoding="utf-8", newline="\n") as marker_file:
        marker_file.write("/* Generated extraction markers for handbook page data. */\n")
        for message in sorted(messages):
            marker_file.write("gettext(%s);\n" % json.dumps(message, ensure_ascii=False))


def quellen_finden(root=ROOT, installed_launcher=None):
    web = os.path.join(root, "web")
    start = os.path.join(root, "bin", "magnolie-handbuch")
    quellbaum = os.path.isfile(start)
    if not quellbaum:
        start = installed_launcher or os.path.abspath(os.path.join(root, "..", "..", "bin", "magnolie-handbuch"))
    markers = os.path.join(web, "i18n-markers.js")
    handbuch = os.path.join(web, "handbuch.js")
    fehlend = [pfad for pfad in (markers, handbuch, start)
               if not os.path.isfile(pfad)]
    if fehlend:
        raise FileNotFoundError(", ".join(fehlend))
    return markers, handbuch, start, quellbaum


def haupt(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=os.path.join(
        ROOT, "po", "magnolie-handbuch.pot"))
    parser.add_argument("--update-markers", action="store_true")
    argumente = parser.parse_args(argv)
    ziel = os.path.abspath(argumente.output)
    if not shutil.which("xgettext"):
        raise FileNotFoundError("xgettext")
    markers, handbuch, start, quellbaum = quellen_finden()
    if argumente.update_markers:
        if not quellbaum:
            raise ValueError("--update-markers requires a source tree")
        marker_erzeugen()
    temporary = tempfile.TemporaryDirectory(prefix="magnolie-handbook-pot-")
    if quellbaum:
        markers = os.path.join(temporary.name, "i18n-markers.js")
        marker_erzeugen(markers=markers)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    subprocess.run([
        "xgettext", "--language=JavaScript", "--from-code=UTF-8", "--keyword=gettext",
        "--keyword=_", "--flag=gettext:1:no-javascript-format",
        "--no-location", "--sort-output",
        "--package-name=Magnolie Handbook", "--package-version=" + package_version(),
        "--msgid-bugs-address=maik3531@gmail.com", "--output=" + ziel,
        markers, handbuch
    ], check=True)
    subprocess.run([
        "xgettext", "--join-existing", "--language=Python", "--from-code=UTF-8",
        "--keyword=_", "--no-location", "--sort-output",
        "--package-name=Magnolie Handbook", "--package-version=" + package_version(),
        "--msgid-bugs-address=maik3531@gmail.com", "--output=" + ziel, start
    ], check=True)
    with open(ziel, "r", encoding="utf-8") as template_file:
        template = template_file.read()
    template = re.sub(r'"POT-Creation-Date: [^"\\n]*\\n"',
                      lambda _match:
                      '"POT-Creation-Date: YEAR-MO-DA HO:MI+ZONE\\n"', template)
    with open(ziel, "w", encoding="utf-8", newline="\n") as template_file:
        template_file.write(template)
    temporary.cleanup()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(haupt())
    except (OSError, ValueError, subprocess.SubprocessError) as fehler:
        sys.stderr.write(str(fehler) + "\n")
        sys.exit(1)
