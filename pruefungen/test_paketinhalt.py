#!/usr/bin/env python3
"""Static release-version and source-package policy checks."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
WINDOWS = WORKSPACE / "magnolie-organizer-windows-1.0.0"
HANDBOOK = WORKSPACE / "magnolie-handbuch-1.9.5"
VERSION = "2.0.0"
INTERNAL_NOTE = re.compile(
    r"(REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|ANALYSE|PLAN|AUDIT).*\.md$", re.I)


def text(path):
    return path.read_text(encoding="utf-8")


assert f'PROGRAMM_FASSUNG = "{VERSION}"' in text(ROOT / "bin/magnolie-organizer")
version_lock = WORKSPACE / "DESKTOP_VERSION"
if version_lock.exists():
    assert text(version_lock).strip() == VERSION
assert f"magnolie-organizer ({VERSION})" in text(ROOT / "debian/changelog").splitlines()[0]
assert f"Version:        {VERSION}" in text(ROOT / "rpm/magnolie-organizer.spec")
if HANDBOOK.exists():
    assert f"magnolie-handbuch ({VERSION})" in text(HANDBOOK / "debian/changelog").splitlines()[0]
if WINDOWS.exists():
    assert f"<Version>{VERSION}</Version>" in text(WINDOWS / "MagnolieOrganizer.Windows.csproj")
    installer = text(WINDOWS / "installer/MagnolieOrganizer.nsi")
    assert f'!define PRODUCT_VERSION "{VERSION}"' in installer
    assert "CreateShortcut \"$SMPROGRAMS\\$StartMenuFolder\\Magnolie Organizer deinstallieren.lnk\"" not in installer
    assert "Delete \"$SMPROGRAMS\\$StartMenuFolder\\Magnolie Organizer deinstallieren.lnk\"" in installer
    windows_build = text(WINDOWS / "build/Build.ps1")
    assert "ZipFile]::CreateFromDirectory" in windows_build
    assert "$output, $archive" in windows_build and "$false" in windows_build
    assert "Compress-Archive" not in windows_build
if HANDBOOK.exists():
    handbook_rules = text(HANDBOOK / "debian/rules")
    assert "override_dh_auto_test:" in handbook_rules
    assert "werkzeuge/katalog_pruefen.py" in handbook_rules
    assert "pruefungen/handbuch_test.js" in handbook_rules
    assert "pruefungen/druck_test.py --cli-only" in handbook_rules

root_update = ET.parse(WORKSPACE / "update.xml").getroot()
organizer_update = ET.parse(ROOT / "update.xml").getroot()
for manifest in (root_update, organizer_update):
    manual = manifest.find("manual")
    assert manual is not None
    assert [child.tag for child in manual] == ["version", "linux", "windows"]
    assert manual.findtext("linux/sha256") == "UNVEROEFFENTLICHT"
    assert manual.findtext("windows/sha256") == "UNVEROEFFENTLICHT"
specification = text(WORKSPACE / "Entwicklungsnotizen/ENTWURF-MAGNOLIE-TELEFONVERBINDUNG.md")
assert '`available:false` und `reason:"os_restricted"`' in specification
assert "Fassung 1 bietet keinen HFP-Schalter" in specification

install_manifest = text(ROOT / "debian/install")
assert not INTERNAL_NOTE.search(install_manifest)
assert "web/kaffee-qr.png" in install_manifest
assert (ROOT / "web/kaffee-qr.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
assert '"/kaffee-qr.png": ("kaffee-qr.png", "image/png")' in text(
    ROOT / "bin/magnolie-organizer")
rpm_builder = text(ROOT / "werkzeuge/rpm_bauen.sh")
for marker in ("REVIEW", "ENTWURF", "OFFENE-PUNKTE", "ANALYSE", "PLAN", "AUDIT"):
    assert marker in rpm_builder

for source_root in (ROOT, WINDOWS, HANDBOOK):
    for path in source_root.glob("*.md"):
        assert not INTERNAL_NOTE.search(path.name), f"interne Arbeitsnotiz im Quellbaum: {path}"

current_files = [
    ROOT / "LIESMICH.md",
    ROOT / "update.xml",
]
if WINDOWS.exists():
    current_files += [WINDOWS / "LIESMICH.md", WINDOWS / "handbuch/inhalt.js"]
if HANDBOOK.exists():
    current_files += [HANDBOOK / "LIESMICH.md", HANDBOOK / "web/inhalt.js"]
for path in current_files:
    value = text(path)
    assert VERSION in value, f"2.0.0 fehlt: {path}"
    assert not re.search(r"Magnolie-Organizer-(1\.31|Windows-1\.0)", value), path

print("Paketinhalt und Desktop-Version 2.0.0: ok")
