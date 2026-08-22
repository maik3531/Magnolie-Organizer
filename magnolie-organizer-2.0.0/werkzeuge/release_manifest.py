#!/usr/bin/env python3
"""Traegt alle installierbaren Artefakte atomar in ein Release-Manifest ein."""

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


def manifest_schreiben(pfad, deb_pfad, appimage_pfad, handbuch_pfad,
                       windows_pfad):
    baum = ET.parse(pfad)
    wurzel = baum.getroot()
    version = (wurzel.findtext("./version") or "").strip()
    deb_url = (wurzel.findtext("./deb") or "").strip()
    if not version or not deb_url:
        raise RuntimeError("Manifest ohne Version oder Debian-Adresse: " + pfad)
    deb_name = "magnolie-organizer_%s_all.deb" % version
    appimage_name = "Magnolie-Organizer-%s-x86_64.AppImage" % version
    handbuch_name = "magnolie-handbuch_%s_all.deb" % version
    windows_name = "Magnolie-Organizer-Windows-%s-Setup-x64.exe" % version
    if os.path.basename(deb_pfad) != deb_name:
        raise RuntimeError("Debian-Paket passt nicht zur Manifestversion.")
    if os.path.basename(appimage_pfad) != appimage_name:
        raise RuntimeError("AppImage passt nicht zur Manifestversion.")
    if os.path.basename(handbuch_pfad) != handbuch_name:
        raise RuntimeError("Handbuch-Paket passt nicht zur Manifestversion.")
    if os.path.basename(windows_pfad) != windows_name:
        raise RuntimeError("Windows-Installer passt nicht zur Manifestversion.")
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
    handbuch = wurzel.find("./manual")
    handbuch_linux = wurzel.find("./manual/linux")
    handbuch_windows = wurzel.find("./manual/windows")
    windows = wurzel.find("./windows")
    if any(knoten is None for knoten in
           (handbuch, handbuch_linux, handbuch_windows, windows)):
        raise RuntimeError("Manifest ohne vollständige Handbuch-/Windows-Angaben: " + pfad)
    if (handbuch.findtext("./version") or "").strip() != version:
        raise RuntimeError("Handbuchversion passt nicht zur Manifestversion.")
    if (windows.findtext("./version") or "").strip() != version:
        raise RuntimeError("Windows-Version passt nicht zur Manifestversion.")
    for knoten, name, feld in ((handbuch_linux, handbuch_name, "deb"),
                               (handbuch_windows, windows_name, "url"),
                               (windows, windows_name, "url")):
        if os.path.basename((knoten.findtext("./" + feld) or "").strip()) != name:
            raise RuntimeError("Manifest-Adresse passt nicht zur Manifestversion.")
    text_setzen(handbuch_linux, "sha256", datei_summe(handbuch_pfad))
    windows_summe = datei_summe(windows_pfad)
    text_setzen(handbuch_windows, "sha256", windows_summe)
    text_setzen(windows, "sha256", windows_summe)

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
    if len(argumente) < 6:
        raise SystemExit(
            "Aufruf: release_manifest.py ORGANIZER.deb PAKET.AppImage "
            "HANDBUCH.deb WINDOWS.exe update.xml [update.xml ...]")
    deb_pfad, appimage_pfad, handbuch_pfad, windows_pfad = argumente[1:5]
    for manifest in argumente[5:]:
        manifest_schreiben(manifest, deb_pfad, appimage_pfad, handbuch_pfad,
                           windows_pfad)
        print("Manifest aktualisiert: %s" % manifest)


if __name__ == "__main__":
    haupt(sys.argv)
