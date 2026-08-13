#!/usr/bin/env python3
"""Signiert update.xml mit einem extern verwahrten Ed25519-Privatschlüssel."""

import base64
import hashlib
import os
import sys
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def signatur_nachricht(version, paket, pruefsumme,
                       appimage_paket="", appimage_pruefsumme="",
                       manual_version="", manual_linux="", manual_linux_sha="",
                       manual_windows="", manual_windows_sha="",
                       windows_version="", windows_url="", windows_sha=""):
    return ("Magnolie Organizer Update\nversion=%s\ndeb=%s\nsha256=%s\n"
            "appimage=%s\nappimageSha256=%s\nmanualVersion=%s\n"
            "manualLinux=%s\nmanualLinuxSha256=%s\nmanualWindows=%s\n"
            "manualWindowsSha256=%s\nwindowsVersion=%s\nwindows=%s\n"
            "windowsSha256=%s\n" %
            (version.strip(), paket.strip(), pruefsumme.lower(),
             appimage_paket.strip(), appimage_pruefsumme.lower(), manual_version.strip(),
             manual_linux.strip(), manual_linux_sha.lower(), manual_windows.strip(),
             manual_windows_sha.lower(), windows_version.strip(), windows_url.strip(),
             windows_sha.lower())).encode("utf-8")


def haupt(argumente):
    if len(argumente) not in (4, 5):
        raise SystemExit(
            "Aufruf: update_signieren.py PRIVATER-SCHLUESSEL.pem update.xml PAKET.deb [PAKET.AppImage]")
    schluessel_pfad, xml_pfad, paket_pfad = argumente[1:4]
    appimage_pfad = argumente[4] if len(argumente) == 5 else ""
    if os.stat(schluessel_pfad).st_mode & 0o077:
        raise SystemExit("Der private Schlüssel muss ausschließlich für den Eigentümer lesbar sein (0600).")
    with open(schluessel_pfad, "rb") as datei:
        schluessel = serialization.load_pem_private_key(datei.read(), password=None)
    if not isinstance(schluessel, Ed25519PrivateKey):
        raise SystemExit("Der private Schlüssel ist kein Ed25519-Schlüssel.")
    with open(xml_pfad, "rb") as datei:
        wurzel = ET.fromstring(datei.read())
    version = (wurzel.findtext("./version") or "").strip()
    paket = (wurzel.findtext("./deb") or "").strip()
    if not version or not paket or os.path.basename(paket) != os.path.basename(paket_pfad):
        raise SystemExit("Version, Paketdatei oder Paketadresse passen nicht zusammen.")
    def datei_summe(pfad):
        hasher = hashlib.sha256()
        with open(pfad, "rb") as datei:
            for block in iter(lambda: datei.read(1024 * 1024), b""):
                hasher.update(block)
        return hasher.hexdigest()

    pruefsumme = datei_summe(paket_pfad)
    pruefsummen_element = wurzel.find("./sha256")
    if pruefsummen_element is None:
        pruefsummen_element = ET.SubElement(wurzel, "sha256")
    pruefsummen_element.text = pruefsumme
    appimage_paket = ""
    appimage_pruefsumme = ""
    appimage_knoten = wurzel.find("./appimage")
    if appimage_pfad:
        if appimage_knoten is None:
            raise SystemExit("Im Manifest fehlt der AppImage-Abschnitt.")
        appimage_paket = (appimage_knoten.findtext("./url") or "").strip()
        if os.path.basename(appimage_paket) != os.path.basename(appimage_pfad):
            raise SystemExit("AppImage-Datei und AppImage-Adresse passen nicht zusammen.")
        appimage_pruefsumme = datei_summe(appimage_pfad)
        appimage_summe_element = appimage_knoten.find("./sha256")
        if appimage_summe_element is None:
            appimage_summe_element = ET.SubElement(appimage_knoten, "sha256")
        appimage_summe_element.text = appimage_pruefsumme
    elif appimage_knoten is not None:
        appimage_paket = (appimage_knoten.findtext("./url") or "").strip()
        appimage_pruefsumme = (appimage_knoten.findtext("./sha256") or "").strip().lower()
    signatur_element = wurzel.find("./signature")
    if signatur_element is None:
        signatur_element = ET.SubElement(wurzel, "signature")
    manual = wurzel.find("./manual")
    windows = wurzel.find("./windows")
    signatur_element.text = base64.b64encode(schluessel.sign(signatur_nachricht(
        version, paket, pruefsumme, appimage_paket, appimage_pruefsumme,
        (manual.findtext("./version") or "") if manual is not None else "",
        (manual.findtext("./linux/deb") or "") if manual is not None else "",
        (manual.findtext("./linux/sha256") or "") if manual is not None else "",
        (manual.findtext("./windows/url") or "") if manual is not None else "",
        (manual.findtext("./windows/sha256") or "") if manual is not None else "",
        (windows.findtext("./version") or "") if windows is not None else "",
        (windows.findtext("./url") or "") if windows is not None else "",
        (windows.findtext("./sha256") or "") if windows is not None else ""))).decode("ascii")
    ET.indent(wurzel, space="  ")
    ET.ElementTree(wurzel).write(xml_pfad, encoding="UTF-8", xml_declaration=True)
    print("Signiert: %s" % xml_pfad)
    print("SHA-256: %s" % pruefsumme)
    if appimage_pruefsumme:
        print("AppImage-SHA-256: %s" % appimage_pruefsumme)
    oeffentlich = schluessel.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print("Öffentlicher Schlüssel: %s" % base64.b64encode(oeffentlich).decode("ascii"))


if __name__ == "__main__":
    haupt(sys.argv)
