#!/usr/bin/env python3
"""Traegt Debian-Paket und AppImage atomar in ein Release-Manifest ein."""

import hashlib
import os
import sys
import tempfile
import xml.etree.ElementTree as ET


def datei_summe(pfad):
    hasher = hashlib.sha256()
    with open(pfad, "rb") as datei:
        for block in iter(lambda: datei.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def text_setzen(knoten, name, text):
    element = knoten.find("./" + name)
    if element is None:
        element = ET.SubElement(knoten, name)
    element.text = text


def manifest_schreiben(pfad, deb_pfad, appimage_pfad):
    baum = ET.parse(pfad)
    wurzel = baum.getroot()
    version = (wurzel.findtext("./version") or "").strip()
    deb_url = (wurzel.findtext("./deb") or "").strip()
    if not version or not deb_url:
        raise RuntimeError("Manifest ohne Version oder Debian-Adresse: " + pfad)
    deb_name = "magnolie-organizer_%s_all.deb" % version
    appimage_name = "Magnolie-Organizer-%s-x86_64.AppImage" % version
    if os.path.basename(deb_pfad) != deb_name:
        raise RuntimeError("Debian-Paket passt nicht zur Manifestversion.")
    if os.path.basename(appimage_pfad) != appimage_name:
        raise RuntimeError("AppImage passt nicht zur Manifestversion.")
    if os.path.basename(deb_url) != deb_name:
        raise RuntimeError("Debian-Adresse passt nicht zur Manifestversion.")
    for signatur in wurzel.findall("./signature"):
        wurzel.remove(signatur)

    basis = deb_url.rsplit("/", 1)[0] + "/"
    text_setzen(wurzel, "sha256", datei_summe(deb_pfad))
    text_setzen(wurzel, "source", basis + "magnolie-organizer_%s.tar.xz" % version)
    appimage = wurzel.find("./appimage")
    if appimage is None:
        appimage = ET.SubElement(wurzel, "appimage")
    text_setzen(appimage, "architecture", "x86_64")
    text_setzen(appimage, "url", basis + appimage_name)
    text_setzen(appimage, "sha256", datei_summe(appimage_pfad))

    ET.indent(wurzel, space="  ")
    ordner = os.path.dirname(os.path.abspath(pfad))
    fd, tmp = tempfile.mkstemp(prefix=".update-", suffix=".xml", dir=ordner)
    try:
        with os.fdopen(fd, "wb") as datei:
            baum.write(datei, encoding="UTF-8", xml_declaration=True)
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(tmp, pfad)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def haupt(argumente):
    if len(argumente) < 4:
        raise SystemExit(
            "Aufruf: release_manifest.py PAKET.deb PAKET.AppImage update.xml [update.xml ...]")
    deb_pfad, appimage_pfad = argumente[1:3]
    for manifest in argumente[3:]:
        manifest_schreiben(manifest, deb_pfad, appimage_pfad)
        print("Manifest aktualisiert: %s" % manifest)


if __name__ == "__main__":
    haupt(sys.argv)
