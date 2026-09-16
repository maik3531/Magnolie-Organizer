#!/usr/bin/env python3
"""Gezielte Prüfungen für die fail-closed Release-Signaturkette."""

import base64
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
SIGNIERER = ROOT / "werkzeuge/update_signieren.py"
MANIFEST_WERKZEUG = ROOT / "werkzeuge/release_manifest.py"
SCHLUESSEL_RE = re.compile(
    r'^UPDATE_SIGNATUR_SCHLUESSEL = "([A-Za-z0-9+/]+={0,2})"$', re.M)
PRIVATE_KEY_RE = re.compile(
    rb"-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY)-----[\s\S]*?-----END \1-----")
KEY_FILE_RE = re.compile(
    r"(?:^|[._-])(?:private[-_.]?key|release[-_.]?key|signing[-_.]?key)(?:[._-]|$)"
    r"|\.(?:key|pem|p12|pfx|secret|token)$|^\.env(?:\.|$)", re.I)


def eingebetteter_schluessel():
    programm = (ROOT / "bin/magnolie-organizer").read_text(encoding="utf-8")
    treffer = SCHLUESSEL_RE.search(programm)
    assert treffer
    assert len(base64.b64decode(treffer.group(1), validate=True)) == 32
    return treffer.group(1)


@pytest.fixture
def testschluessel(tmp_path):
    privat = Ed25519PrivateKey.generate()
    pfad = tmp_path / "synthetic-ed25519.pem"
    pfad.write_bytes(privat.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pfad.chmod(0o600)
    roh = privat.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pfad, base64.b64encode(roh).decode("ascii")


def test_externer_schluessel_preflight(testschluessel):
    pfad, public = testschluessel
    subprocess.run([sys.executable, SIGNIERER, "--check-key", pfad, public], check=True)
    assert subprocess.run([sys.executable, SIGNIERER, "--check-key", pfad,
                           eingebetteter_schluessel()], capture_output=True).returncode != 0


def test_manifest_signiert_und_tamper_wird_abgelehnt(tmp_path, testschluessel):
    deb = tmp_path / "magnolie-organizer_9.8.7_all.deb"
    appimage = tmp_path / "Magnolie-Organizer-9.8.7-x86_64.AppImage"
    handbuch = tmp_path / "magnolie-handbuch_9.8.7_all.deb"
    windows = tmp_path / "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe"
    manifest = tmp_path / "update.xml"
    deb.write_bytes(b"deb-testinhalt")
    appimage.write_bytes(b"appimage-testinhalt")
    handbuch.write_bytes(b"handbuch-testinhalt")
    windows.write_bytes(b"windows-testinhalt")
    manifest.write_text(
        "<update><version>9.8.6</version>"
        "<deb>https://example.invalid/magnolie-organizer_9.8.6_all.deb</deb>"
        "<signature>alte-signatur</signature><appimage><architecture>x86_64</architecture>"
        "<url>https://example.invalid/Magnolie-Organizer-9.8.6-x86_64.AppImage</url>"
        "</appimage><manual><version>9.8.6</version><linux>"
        "<deb>https://example.invalid/magnolie-handbuch_9.8.6_all.deb</deb>"
        "</linux><windows><url>https://example.invalid/"
        "Magnolie-Organizer-Windows-9.8.6-Setup-x64.exe</url></windows></manual>"
        "<windows><version>9.8.6</version><url>https://example.invalid/"
        "Magnolie-Organizer-Windows-9.8.6-Setup-x64.exe</url></windows></update>",
        encoding="utf-8")

    ohne_freigabe = subprocess.run(
        [sys.executable, MANIFEST_WERKZEUG, deb, appimage, handbuch, windows, manifest],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert ohne_freigabe.returncode != 0
    subprocess.run([sys.executable, MANIFEST_WERKZEUG, "--allow-unsigned",
                    deb, appimage, handbuch,
                    windows, manifest],
                   check=True, stdout=subprocess.DEVNULL)
    assert ET.parse(manifest).getroot().find("signature") is None
    root = ET.parse(manifest).getroot()
    assert root.findtext("./version") == "9.8.7"
    assert root.findtext("./deb").endswith("magnolie-organizer_9.8.7_all.deb")
    assert root.findtext("./manual/version") == "9.8.7"
    assert root.findtext("./windows/version") == "9.8.7"
    assert root.findtext("./manual/linux/deb").endswith(
        "magnolie-handbuch_9.8.7_all.deb")
    assert root.findtext("./manual/windows/url").endswith(
        "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe")
    assert root.findtext("./manual/linux/sha256") == __import__("hashlib").sha256(
        handbuch.read_bytes()).hexdigest()
    assert root.findtext("./manual/windows/sha256") == __import__("hashlib").sha256(
        windows.read_bytes()).hexdigest()
    assert root.findtext("./windows/sha256") == root.findtext(
        "./manual/windows/sha256")
    key, public = testschluessel
    subprocess.run([sys.executable, SIGNIERER, key, manifest, deb, appimage],
                   check=True, stdout=subprocess.DEVNULL)
    signiert = manifest.read_bytes()
    subprocess.run([sys.executable, SIGNIERER, key, manifest, deb, appimage],
                   check=True, stdout=subprocess.DEVNULL)
    assert manifest.read_bytes() == signiert
    pruefen = [sys.executable, SIGNIERER, "--verify", public,
               manifest, deb, appimage]
    subprocess.run(pruefen, check=True, stdout=subprocess.DEVNULL)

    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        "<version>9.8.7</version>", "<version>9.8.8</version>"), encoding="utf-8")
    assert subprocess.run(pruefen, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0


def test_source_tar_enthaelt_keinen_privatschluessel(tmp_path):
    sys.path.insert(0, str(ROOT / "werkzeuge"))
    from release_sources import source_files
    archiv = tmp_path / "quelle.tar.xz"
    with tarfile.open(archiv, "w:xz") as tar:
        for relativ, source_path in source_files(ROOT):
            tar.add(source_path, arcname="magnolie-organizer/" + str(relativ))
    with tarfile.open(archiv) as tar:
        for member in tar.getmembers():
            assert not KEY_FILE_RE.search(Path(member.name).name), member.name
            if member.isfile():
                assert not PRIVATE_KEY_RE.search(tar.extractfile(member).read()), member.name


def test_signierer_ohne_schluessel_bricht_ab(tmp_path):
    fehlend = tmp_path / "fehlt.pem"
    ergebnis = subprocess.run([sys.executable, SIGNIERER, "--check-key",
                              fehlend, eingebetteter_schluessel()], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert ergebnis.returncode != 0
    assert "Release-Schlüssel fehlt" in ergebnis.stderr
