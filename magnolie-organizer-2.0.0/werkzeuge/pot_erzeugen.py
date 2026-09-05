#!/usr/bin/env python3
"""Erzeugt die englische POT-Vorlage reproduzierbar aus den Quellen."""

import os
import subprocess
import argparse
import shutil
import sys
import re


WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def paket_version(wurzel=WURZEL):
    with open(os.path.join(wurzel, "debian", "changelog"),
              "r", encoding="utf-8") as datei:
        erste = datei.readline()
    treffer = re.match(r"^[^(]+\(([^)]+)\)", erste)
    if not treffer:
        raise ValueError("debian/changelog")
    return treffer.group(1).strip()


def quellen_finden(wurzel=WURZEL,
                   installierter_start="/usr/bin/magnolie-organizer"):
    web = os.path.join(wurzel, "web")
    start = os.path.join(wurzel, "bin", "magnolie-organizer")
    if not os.path.isfile(start):
        start = installierter_start
    hintergrund = os.path.join(wurzel, "bin", "magnolie_hintergrund.py")
    if not os.path.isfile(hintergrund):
        hintergrund = os.path.join(os.path.dirname(start), "magnolie_hintergrund.py")
    setup_ui = os.path.join(wurzel, "bin", "magnolie_setup_ui.py")
    if not os.path.isfile(setup_ui):
        setup_ui = os.path.join(os.path.dirname(start), "magnolie_setup_ui.py")
    quellen = [os.path.join(web, "i18n-markers.js"),
               os.path.join(web, "anwendung.js"), start, hintergrund, setup_ui]
    fehlend = [pfad for pfad in quellen if not os.path.isfile(pfad)]
    if fehlend:
        raise FileNotFoundError(", ".join(fehlend))
    return quellen


def haupt(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=os.path.join(
        WURZEL, "po", "magnolie-organizer.pot"))
    argumente = parser.parse_args(argv)
    ziel = os.path.abspath(argumente.output)
    if not shutil.which("xgettext"):
        raise FileNotFoundError("xgettext")
    marken, javascript, start, hintergrund, setup_ui = quellen_finden()
    version = paket_version()
    os.makedirs(os.path.dirname(ziel), exist_ok=True)

    subprocess.run([
        "xgettext", "--language=JavaScript", "--from-code=UTF-8",
        "--keyword=_", "--keyword=customText", "--keyword=msgid", "--keyword=uebersetzt", "--keyword=uebersetztMehrzahl:1,2",
        "--keyword=gettext",
        "--keyword=ngettext:1,2", "--keyword=pgettext:1c,2",
        "--no-location", "--sort-output",
        "--package-name=Magnolie Organizer", "--package-version=" + version,
        "--msgid-bugs-address=maik3531@gmail.com", "--output=" + ziel,
        marken, javascript
    ], check=True)

    subprocess.run([
        "xgettext", "--join-existing", "--language=Python", "--from-code=UTF-8",
        "--keyword=_", "--keyword=N_", "--keyword=tr:1", "--keyword=bind:2",
        "--keyword=label:1", "--keyword=check:1", "--keyword=radio:2",
        "--keyword=entry:1", "--keyword=field:3",
        "--keyword=page:1", "--keyword=section:2",
        "--no-location", "--sort-output",
        "--package-name=Magnolie Organizer", "--package-version=" + version,
        "--msgid-bugs-address=maik3531@gmail.com",
        "--output=" + ziel, start, hintergrund, setup_ui
    ], check=True)
    with open(ziel, "r", encoding="utf-8") as datei:
        inhalt = datei.read()
    inhalt = re.sub(r'"POT-Creation-Date: [^"\\n]*\\n"',
                    lambda _treffer:
                    '"POT-Creation-Date: YEAR-MO-DA HO:MI+ZONE\\n"', inhalt)
    with open(ziel, "w", encoding="utf-8", newline="\n") as datei:
        datei.write(inhalt)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(haupt())
    except (OSError, subprocess.SubprocessError) as fehler:
        sys.stderr.write(str(fehler) + "\n")
        sys.exit(1)
