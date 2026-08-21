#!/usr/bin/env python3
"""Regenerate the English gettext template from handbook sources."""

import json
import os
import subprocess
import argparse
import shutil
import sys
import re


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "web", "inhalt.js")
MARKERS = os.path.join(ROOT, "web", "i18n-markers.js")


def package_version(root=ROOT):
    with open(os.path.join(root, "debian", "changelog"), encoding="utf-8") as changelog:
        match = re.match(r"^[^(]+\(([^)]+)\)", changelog.readline())
    if not match:
        raise ValueError("debian/changelog")
    return match.group(1).strip()


def handbook_messages(content=CONTENT):
    with open(content, encoding="utf-8") as content_file:
        text = content_file.read()
    pages = json.loads(text[text.index("["):text.index("];") + 1])
    marker = "window.HANDBUCH_SEITEN.push("
    if marker in text:
        start = text.index(marker) + len(marker)
        end = text.index("\n);", start)
        pages.extend(json.loads("[" + text[start:end] + "]"))
    for page in pages:
        for key in ("kapitel", "titel", "inhalt"):
            if page.get(key):
                yield page[key]


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


def quellen_finden(root=ROOT,
                   installed_launcher="/usr/bin/magnolie-handbuch"):
    web = os.path.join(root, "web")
    start = os.path.join(root, "bin", "magnolie-handbuch")
    quellbaum = os.path.isfile(start)
    if not quellbaum:
        start = installed_launcher
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
    argumente = parser.parse_args(argv)
    ziel = os.path.abspath(argumente.output)
    if not shutil.which("xgettext"):
        raise FileNotFoundError("xgettext")
    markers, handbuch, start, quellbaum = quellen_finden()
    if quellbaum:
        marker_erzeugen()
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
    return 0


if __name__ == "__main__":
    try:
        sys.exit(haupt())
    except (OSError, subprocess.SubprocessError) as fehler:
        sys.stderr.write(str(fehler) + "\n")
        sys.exit(1)
