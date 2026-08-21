#!/usr/bin/env python3
"""Prüft Syntax, Vollständigkeit und Fuzzy-Freiheit eines PO-Katalogs."""

import subprocess
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
