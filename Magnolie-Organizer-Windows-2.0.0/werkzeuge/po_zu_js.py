#!/usr/bin/env python3
"""Kompiliert einen geprüften PO-Katalog deterministisch für WebKit."""

import gettext
import json
import os
import subprocess
import sys
import tempfile


def katalog_lesen(po_pfad):
    with tempfile.TemporaryDirectory(prefix="magnolie-po-") as ordner:
        mo_pfad = os.path.join(ordner, "katalog.mo")
        subprocess.run([os.environ.get("MAGNOLIE_MSGFMT", "msgfmt"), "--check", "--check-format", "-o", mo_pfad,
                        po_pfad], check=True)
        with open(mo_pfad, "rb") as datei:
            uebersetzung = gettext.GNUTranslations(datei)
    nachrichten = {}
    plurale = {}
    for schluessel, wert in uebersetzung._catalog.items():
        if schluessel == "":
            continue
        if isinstance(schluessel, tuple):
            msgid, index = schluessel
            plurale.setdefault(msgid, {})[int(index)] = wert
        elif isinstance(wert, str):
            nachrichten[schluessel] = wert
    for msgid, formen in plurale.items():
        nachrichten[msgid] = [formen[i] for i in sorted(formen)]
    return {
        "pluralForms": uebersetzung._info.get("plural-forms", ""),
        "messages": nachrichten,
    }


def haupt(argv):
    if len(argv) != 4:
        raise SystemExit("Aufruf: po_zu_js.py SPRACHE QUELLE.po ZIEL.js")
    sprache, quelle, ziel = argv[1:]
    daten = katalog_lesen(quelle)
    os.makedirs(os.path.dirname(os.path.abspath(ziel)), exist_ok=True)
    text = "window.MagnolieI18n.registerCatalog(%s, %s);\n" % (
        json.dumps(sprache, ensure_ascii=False),
        json.dumps(daten, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    with open(ziel, "w", encoding="utf-8", newline="\n") as datei:
        datei.write(text)


if __name__ == "__main__":
    haupt(sys.argv)
