#!/usr/bin/env python3
"""Kompiliert die PO-Kataloge deterministisch fuer die native C#-Oberflaeche."""

import gettext
import json
import os
import subprocess
import sys
import tempfile


def katalog_lesen(po_pfad):
    with tempfile.TemporaryDirectory(prefix="magnolie-native-po-") as ordner:
        mo_pfad = os.path.join(ordner, "katalog.mo")
        subprocess.run([os.environ.get("MAGNOLIE_MSGFMT", "msgfmt"), "--check", "--check-format", "-o", mo_pfad, po_pfad], check=True)
        with open(mo_pfad, "rb") as datei:
            uebersetzung = gettext.GNUTranslations(datei)
    return {
        schluessel: wert
        for schluessel, wert in uebersetzung._catalog.items()
        if isinstance(schluessel, str) and schluessel and isinstance(wert, str)
    }


def haupt(argv):
    if len(argv) < 4 or len(argv[2:]) % 2:
        raise SystemExit("Aufruf: po_zu_native.py ZIEL.json SPRACHE QUELLE.po [...]")
    ziel = argv[1]
    kataloge = {}
    for index in range(2, len(argv), 2):
        sprache, quelle = argv[index:index + 2]
        kataloge[sprache] = katalog_lesen(quelle)
    os.makedirs(os.path.dirname(os.path.abspath(ziel)), exist_ok=True)
    text = json.dumps({"locales": kataloge}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"
    with open(ziel, "w", encoding="utf-8", newline="\n") as datei:
        datei.write(text)


if __name__ == "__main__":
    haupt(sys.argv)
