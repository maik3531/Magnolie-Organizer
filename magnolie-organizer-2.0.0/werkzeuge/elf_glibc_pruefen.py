#!/usr/bin/env python3
"""Begrenzt die von ELF-Dateien verlangte glibc-Symbolfassung."""

import os
import re
import subprocess
import sys


GLIBC_FASSUNG = re.compile(r"GLIBC_(\d+)\.(\d+)")


def verlangte_fassungen(text):
    return {(int(haupt), int(neben))
            for haupt, neben in GLIBC_FASSUNG.findall(text)}


def pruefen(wurzel, hoechstens):
    grenze = tuple(int(teil) for teil in hoechstens.split("."))
    if len(grenze) != 2:
        raise ValueError("Die glibc-Grenze muss aus Haupt- und Nebenfassung bestehen.")
    fehler = []
    maximum = (0, 0)
    for ordner, _unterordner, dateien in os.walk(wurzel):
        for name in dateien:
            pfad = os.path.join(ordner, name)
            try:
                with open(pfad, "rb") as datei:
                    if datei.read(4) != b"\x7fELF":
                        continue
                ausgabe = subprocess.run(
                    ["readelf", "--version-info", pfad], check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True).stdout
            except (OSError, subprocess.CalledProcessError) as ausnahme:
                fehler.append((pfad, "nicht pruefbar: %s" % ausnahme))
                continue
            fassungen = verlangte_fassungen(ausgabe)
            verlangt = max(fassungen, default=(0, 0))
            maximum = max(maximum, verlangt)
            if verlangt > grenze:
                fehler.append((pfad, "GLIBC_%d.%d" % verlangt))
    if fehler:
        for pfad, grund in fehler:
            print("%s: %s" % (os.path.relpath(pfad, wurzel), grund), file=sys.stderr)
        raise SystemExit("AppImage-Nutzlast ueberschreitet GLIBC_%s." % hoechstens)
    print("Hoechste verlangte glibc-Symbolfassung: GLIBC_%d.%d" % maximum)


def haupt(argumente):
    if len(argumente) != 3:
        raise SystemExit("Aufruf: elf_glibc_pruefen.py APPDIR HOECHSTE_GLIBC")
    pruefen(argumente[1], argumente[2])


if __name__ == "__main__":
    haupt(sys.argv)
