#!/usr/bin/env python3
"""Gezielte Prüfungen für die fail-closed Release-Signaturkette."""

import base64
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
SIGNIERER = ROOT / "werkzeuge/update_signieren.py"
MANIFEST_WERKZEUG = ROOT / "werkzeuge/release_manifest.py"
RELEASE = ROOT / "werkzeuge/release_bauen.sh"
PRIVATER_STANDARDPFAD = (
    Path.home() / ".local/share/magnolie-release/update-ed25519.pem")
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


def test_externer_schluessel_stimmt_mit_eingebettetem_ueberein():
    pfad = Path(os.environ.get("MAGNOLIE_UPDATE_SIGNING_KEY", PRIVATER_STANDARDPFAD))
    assert pfad.is_file()
    assert pfad.stat().st_mode & 0o777 == 0o600
    privat = serialization.load_pem_private_key(pfad.read_bytes(), password=None)
    assert isinstance(privat, Ed25519PrivateKey)
    roh = privat.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert base64.b64encode(roh).decode("ascii") == eingebetteter_schluessel()


def test_manifest_signiert_und_tamper_wird_abgelehnt(tmp_path):
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
        "<update><version>9.8.7</version>"
        "<deb>https://example.invalid/magnolie-organizer_9.8.7_all.deb</deb>"
        "<signature>alte-signatur</signature><appimage><architecture>x86_64</architecture>"
        "<url>https://example.invalid/Magnolie-Organizer-9.8.7-x86_64.AppImage</url>"
        "</appimage><manual><version>9.8.7</version><linux>"
        "<deb>https://example.invalid/magnolie-handbuch_9.8.7_all.deb</deb>"
        "</linux><windows><url>https://example.invalid/"
        "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe</url></windows></manual>"
        "<windows><version>9.8.7</version><url>https://example.invalid/"
        "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe</url></windows></update>",
        encoding="utf-8")

    subprocess.run([sys.executable, MANIFEST_WERKZEUG, deb, appimage, handbuch,
                    windows, manifest],
                   check=True, stdout=subprocess.DEVNULL)
    assert ET.parse(manifest).getroot().find("signature") is None
    root = ET.parse(manifest).getroot()
    assert root.findtext("./manual/linux/sha256") == __import__("hashlib").sha256(
        handbuch.read_bytes()).hexdigest()
    assert root.findtext("./manual/windows/sha256") == __import__("hashlib").sha256(
        windows.read_bytes()).hexdigest()
    assert root.findtext("./windows/sha256") == root.findtext(
        "./manual/windows/sha256")
    key = Path(os.environ.get("MAGNOLIE_UPDATE_SIGNING_KEY", PRIVATER_STANDARDPFAD))
    subprocess.run([sys.executable, SIGNIERER, key, manifest, deb, appimage],
                   check=True, stdout=subprocess.DEVNULL)
    signiert = manifest.read_bytes()
    subprocess.run([sys.executable, SIGNIERER, key, manifest, deb, appimage],
                   check=True, stdout=subprocess.DEVNULL)
    assert manifest.read_bytes() == signiert
    pruefen = [sys.executable, SIGNIERER, "--verify", eingebetteter_schluessel(),
               manifest, deb, appimage]
    subprocess.run(pruefen, check=True, stdout=subprocess.DEVNULL)

    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        "<version>9.8.7</version>", "<version>9.8.8</version>"), encoding="utf-8")
    assert subprocess.run(pruefen, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0


def test_source_tar_enthaelt_keinen_privatschluessel(tmp_path):
    archiv = tmp_path / "quelle.tar.xz"
    with tarfile.open(archiv, "w:xz") as tar:
        for source_path in ROOT.rglob("*"):
            relativ = source_path.relative_to(ROOT)
            if any(part in {".git", ".pytest_cache", ".kotlin", ".gradle",
                            "__pycache__", "bau", "build"}
                   for part in relativ.parts):
                continue
            if source_path.is_file() and not source_path.is_symlink():
                tar.add(source_path, arcname="magnolie-organizer/" + str(relativ))
    with tarfile.open(archiv) as tar:
        for member in tar.getmembers():
            assert not KEY_FILE_RE.search(Path(member.name).name), member.name
            if member.isfile():
                assert not PRIVATE_KEY_RE.search(tar.extractfile(member).read()), member.name


def test_release_ohne_schluessel_bricht_vor_veroeffentlichung_ab(tmp_path):
    fehlend = tmp_path / "fehlt.pem"
    umgebung = os.environ.copy()
    umgebung["MAGNOLIE_UPDATE_SIGNING_KEY"] = str(fehlend)
    umgebung["MAGNOLIE_CONTRIBUTOR_HASH"] = "0" * 64
    ergebnis = subprocess.run(["sh", RELEASE, "--skip-system-package-tests"],
                              cwd=ROOT, env=umgebung, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert ergebnis.returncode != 0
    assert "Release-Schlüssel fehlt" in ergebnis.stderr
    regeln = RELEASE.read_text(encoding="utf-8")
    assert regeln.index("--check-key") < regeln.index("STAGE=$(mktemp")
    assert regeln.index("--verify") < regeln.rindex("VEROEFFENTLICHEN=1")
