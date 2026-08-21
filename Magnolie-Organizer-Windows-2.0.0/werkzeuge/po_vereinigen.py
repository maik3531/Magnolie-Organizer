#!/usr/bin/env python3
"""Vereinigt bestehende PO- und generierte Kataloge deterministisch mit einem POT."""

import gettext
import json
import os
import re
import subprocess
import sys
import tempfile

ERGÄNZUNGEN = {
    "Operating system": {
        "ar": "نظام التشغيل", "be": "Аперацыйная сістэма", "cs": "Operační systém",
        "da": "Operativsystem", "de": "Betriebssystem", "es": "Sistema operativo",
        "fr": "Système d’exploitation", "hi": "ऑपरेटिंग सिस्टम", "hsb": "Dźěłowy system",
        "it": "Sistema operativo", "ja": "オペレーティングシステム", "nb": "Operativsystem",
        "nl": "Besturingssysteem", "pl": "System operacyjny", "pt": "Sistema operativo",
        "ru": "Операционная система", "tr": "İşletim sistemi", "uk": "Операційна система",
        "zh_CN": "操作系统",
    },
}


def po_katalog(pfad):
    with tempfile.TemporaryDirectory(prefix="magnolie-po-merge-") as ordner:
        mo = os.path.join(ordner, "catalog.mo")
        subprocess.run([os.environ.get("MAGNOLIE_MSGFMT", "msgfmt"), "-o", mo, pfad],
                       check=True)
        with open(mo, "rb") as datei:
            return dict(gettext.GNUTranslations(datei)._catalog)


def js_katalog(pfad):
    text = open(pfad, encoding="utf-8").read()
    treffer = re.fullmatch(r'window\.MagnolieI18n\.registerCatalog\((".*?"),\s*(\{.*\})\);\s*',
                           text, re.DOTALL)
    if not treffer:
        raise ValueError("Ungültiger generierter Webkatalog: " + pfad)
    return json.loads(treffer.group(2))["messages"]


def feld(block, name):
    treffer = re.search(r"^" + name + r' (".*")$', block, re.MULTILINE)
    if not treffer:
        return None
    wert = json.loads(treffer.group(1))
    position = treffer.end()
    while position < len(block):
        folge = re.match(r'\n(".*")', block[position:])
        if not folge:
            break
        wert += json.loads(folge.group(1))
        position += len(folge.group(0))
    return wert


def quoted(name, wert):
    return name + " " + json.dumps(wert, ensure_ascii=False)


def haupt(argv):
    if len(argv) != 7:
        raise SystemExit("Aufruf: po_vereinigen.py VORLAGE.pot AKTUELL.po ALT.js ALT-NATIV.json SPRACHE ZIEL.po")
    vorlage, aktuell, alt, alt_nativ, sprache, ziel = argv[1:]
    aktuelle = po_katalog(aktuell)
    alte = js_katalog(alt)
    with open(alt_nativ, encoding="utf-8") as datei:
        alte.update(json.load(datei)["locales"][sprache])
    bloecke = open(vorlage, encoding="utf-8").read().split("\n\n")
    ausgabe = []
    for block in bloecke:
        msgid = feld(block, "msgid")
        if msgid is None:
            ausgabe.append(block)
            continue
        if msgid == "":
            kopf = aktuelle.get("", "")
            ausgabe.append(re.sub(r'^msgstr ""(?:\n".*")*', lambda _: quoted("msgstr", kopf),
                                  block.replace("#, fuzzy\n", ""), count=1, flags=re.MULTILINE))
            continue
        context = feld(block, "msgctxt")
        key = (context + "\x04" + msgid) if context else msgid
        plural = feld(block, "msgid_plural")
        if plural is None:
            wert = alte.get(key) or aktuelle.get(key) or ERGÄNZUNGEN.get(key, {}).get(sprache)
            if not isinstance(wert, str) or not wert:
                raise ValueError("Übersetzung fehlt: " + key)
            ersetzt = re.sub(r'^msgstr ""(?:\n".*")*', lambda _: quoted("msgstr", wert), block,
                             count=1, flags=re.MULTILINE)
        else:
            altwerte = alte.get(key, [])
            zeilen = []
            index = 0
            while (key, index) in aktuelle or index < len(altwerte):
                wert = (altwerte[index] if index < len(altwerte) else "") or aktuelle.get((key, index))
                if not wert:
                    raise ValueError("Pluralübersetzung fehlt: " + key)
                zeilen.append(quoted("msgstr[%d]" % index, wert))
                index += 1
            ersetzt = re.sub(r'^msgstr\[0\] ""(?:\nmsgstr\[\d+\] "")*', lambda _: "\n".join(zeilen),
                             block, count=1, flags=re.MULTILINE)
        ausgabe.append(ersetzt)
    with open(ziel, "w", encoding="utf-8", newline="\n") as datei:
        datei.write("\n\n".join(ausgabe).rstrip() + "\n")


if __name__ == "__main__":
    haupt(sys.argv)
