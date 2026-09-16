#!/usr/bin/env python3
"""Prüft Syntax, Vollständigkeit und Fuzzy-Freiheit eines PO-Katalogs."""

import subprocess
import os
import sys


def eintraege(text):
    bloecke = [block for block in text.split("\n\n") if "msgid " in block]
    return max(0, len(bloecke) - 1)  # Der erste Block ist der Kopfeintrag.


def ausgabe(*argumente):
    return subprocess.check_output(argumente, text=True)


def haupt(argv):
    if len(argv) != 3:
        raise SystemExit("Aufruf: katalog_pruefen.py VORLAGE.pot SPRACHE.po")
    vorlage, katalog = argv[1:]
    sprache = os.path.splitext(os.path.basename(katalog))[0]
    with open(katalog, encoding="utf-8") as datei:
        kopf = datei.read().split("\n\n", 1)[0]
    pflichtfelder = {
        "Project-Id-Version": "Magnolie Organizer 2.0.18",
        "PO-Revision-Date": "2026-09-07 00:00+0200",
        "Last-Translator": "Magnolie translation team <maik3531@gmail.com>",
        "Language-Team": sprache,
        "Language": sprache,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    }
    for feld, wert in pflichtfelder.items():
        if ('"%s: %s\\n"' % (feld, wert)) not in kopf:
            raise SystemExit("Ungültiger %s-Kopfeintrag: %s" % (sprache, feld))
    subprocess.run(["msgfmt", "--check", "--check-format", "-o", "/dev/null",
                    katalog], check=True)
    subprocess.run(["msgcmp", "--use-fuzzy", katalog, vorlage], check=True)
    unuebersetzt = eintraege(ausgabe("msgattrib", "--untranslated",
                                    "--no-obsolete", katalog))
    unscharf = eintraege(ausgabe("msgattrib", "--only-fuzzy",
                                 "--no-obsolete", katalog))
    if unuebersetzt or unscharf:
        raise SystemExit("Katalog unvollständig: %d unübersetzt, %d unscharf" %
                         (unuebersetzt, unscharf))


if __name__ == "__main__":
    haupt(sys.argv)
