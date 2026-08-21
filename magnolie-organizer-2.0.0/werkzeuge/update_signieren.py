#!/usr/bin/env python3
"""Signiert update.xml mit einem extern verwahrten Ed25519-Privatschlüssel."""

import base64
import hashlib
import os
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)


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


def privater_schluessel_laden(pfad):
    try:
        fd = os.open(pfad, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as fehler:
        raise SystemExit("Privater Release-Schlüssel fehlt: %s" % pfad) from fehler
    with os.fdopen(fd, "rb") as datei:
        status = os.fstat(datei.fileno())
        if not stat.S_ISREG(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o600:
            raise SystemExit(
                "Der private Schlüssel muss eine reguläre Datei mit Rechten 0600 sein.")
        pem = datei.read()
    if not pem.startswith(b"-----BEGIN PRIVATE KEY-----\n"):
        raise SystemExit("Der private Schlüssel muss als PKCS8-PEM vorliegen.")
    try:
        schluessel = serialization.load_pem_private_key(pem, password=None)
    except (TypeError, ValueError) as fehler:
        raise SystemExit("Der private Schlüssel ist kein gültiger PKCS8-Schlüssel.") from fehler
    if not isinstance(schluessel, Ed25519PrivateKey):
        raise SystemExit("Der private Schlüssel ist kein Ed25519-Schlüssel.")
    return schluessel


def oeffentlicher_text(schluessel):
    roh = schluessel.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(roh).decode("ascii")


def manifest_felder(wurzel):
    appimage = wurzel.find("./appimage")
    manual = wurzel.find("./manual")
    windows = wurzel.find("./windows")
    return (
        (wurzel.findtext("./version") or "").strip(),
        (wurzel.findtext("./deb") or "").strip(),
        (wurzel.findtext("./sha256") or "").strip(),
        (appimage.findtext("./url") or "").strip() if appimage is not None else "",
        (appimage.findtext("./sha256") or "").strip() if appimage is not None else "",
        (manual.findtext("./version") or "") if manual is not None else "",
        (manual.findtext("./linux/deb") or "") if manual is not None else "",
        (manual.findtext("./linux/sha256") or "") if manual is not None else "",
        (manual.findtext("./windows/url") or "") if manual is not None else "",
        (manual.findtext("./windows/sha256") or "") if manual is not None else "",
        (windows.findtext("./version") or "") if windows is not None else "",
        (windows.findtext("./url") or "") if windows is not None else "",
        (windows.findtext("./sha256") or "") if windows is not None else "")


def datei_summe(pfad):
    hasher = hashlib.sha256()
    with open(pfad, "rb") as datei:
        for block in iter(lambda: datei.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def manifest_verifizieren(oeffentlicher_schluessel, xml_pfad, paket_pfad,
                          appimage_pfad=""):
    try:
        roh = base64.b64decode(oeffentlicher_schluessel, validate=True)
        schluessel = Ed25519PublicKey.from_public_bytes(roh)
        wurzel = ET.parse(xml_pfad).getroot()
        felder = manifest_felder(wurzel)
        signatur = base64.b64decode(
            (wurzel.findtext("./signature") or "").strip(), validate=True)
    except Exception as fehler:
        raise SystemExit("Manifest oder öffentlicher Schlüssel ist ungültig.") from fehler
    if os.path.basename(felder[1]) != os.path.basename(paket_pfad):
        raise SystemExit("Debian-Paket und Manifest passen nicht zusammen.")
    if felder[2].lower() != datei_summe(paket_pfad):
        raise SystemExit("Debian-Prüfsumme im Manifest ist ungültig.")
    if appimage_pfad:
        if os.path.basename(felder[3]) != os.path.basename(appimage_pfad):
            raise SystemExit("AppImage und Manifest passen nicht zusammen.")
        if felder[4].lower() != datei_summe(appimage_pfad):
            raise SystemExit("AppImage-Prüfsumme im Manifest ist ungültig.")
    try:
        schluessel.verify(signatur, signatur_nachricht(*felder))
    except Exception as fehler:
        raise SystemExit("Manifest-Signatur ist ungültig.") from fehler


def haupt(argumente):
    if len(argumente) == 4 and argumente[1] == "--check-key":
        schluessel = privater_schluessel_laden(argumente[2])
        if oeffentlicher_text(schluessel) != argumente[3].strip():
            raise SystemExit("Privater Release-Schlüssel passt nicht zum eingebetteten Schlüssel.")
        return
    if len(argumente) in (5, 6) and argumente[1] == "--verify":
        manifest_verifizieren(argumente[2], argumente[3], argumente[4],
                              argumente[5] if len(argumente) == 6 else "")
        print("Verifiziert: %s" % argumente[3])
        return
    if len(argumente) not in (4, 5):
        raise SystemExit(
            "Aufruf: update_signieren.py PRIVATER-SCHLUESSEL.pem update.xml PAKET.deb [PAKET.AppImage]")
    schluessel_pfad, xml_pfad, paket_pfad = argumente[1:4]
    appimage_pfad = argumente[4] if len(argumente) == 5 else ""
    schluessel = privater_schluessel_laden(schluessel_pfad)
    with open(xml_pfad, "rb") as datei:
        wurzel = ET.fromstring(datei.read())
    version = (wurzel.findtext("./version") or "").strip()
    paket = (wurzel.findtext("./deb") or "").strip()
    if not version or not paket or os.path.basename(paket) != os.path.basename(paket_pfad):
        raise SystemExit("Version, Paketdatei oder Paketadresse passen nicht zusammen.")
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
    felder = manifest_felder(wurzel)
    signatur_element.text = base64.b64encode(
        schluessel.sign(signatur_nachricht(*felder))).decode("ascii")
    ET.indent(wurzel, space="  ")
    ordner = os.path.dirname(os.path.abspath(xml_pfad))
    fd, tmp = tempfile.mkstemp(prefix=".update-signiert-", suffix=".xml", dir=ordner)
    try:
        with os.fdopen(fd, "wb") as datei:
            ET.ElementTree(wurzel).write(
                datei, encoding="UTF-8", xml_declaration=True)
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(tmp, xml_pfad)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print("Signiert: %s" % xml_pfad)
    print("SHA-256: %s" % pruefsumme)
    if appimage_pruefsumme:
        print("AppImage-SHA-256: %s" % appimage_pruefsumme)
    print("Öffentlicher Schlüssel: %s" % oeffentlicher_text(schluessel))


if __name__ == "__main__":
    haupt(sys.argv)
