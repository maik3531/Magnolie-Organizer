#!/usr/bin/env python3
"""Static release-version and source-package policy checks."""

from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT / "werkzeuge"))
from png_pruefen import pruefen as png_pruefen
WINDOWS = WORKSPACE / "Magnolie-Organizer-Windows-2.0.0"
HANDBOOK = WORKSPACE / "magnolie-handbuch-stamm"
VERSION = "2.0.9"
MANIFEST_VERSION = VERSION
INTERNAL_NOTE = re.compile(
    r"(REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|ANALYSE|PLAN|AUDIT).*\.md$", re.I)
PRIVATE_KEY = re.compile(
    rb"-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY)-----[\s\S]*?-----END \1-----")
KEY_FILE = re.compile(
    r"(?:^|[._-])(?:private[-_.]?key|release[-_.]?key|signing[-_.]?key)(?:[._-]|$)"
    r"|\.(?:key|pem|p12|pfx|secret|token)$|^\.env(?:\.|$)", re.I)
IGNORED_SOURCE_PARTS = {
    ".git", ".pytest_cache", ".kotlin", ".gradle", "__pycache__", "bau", "build",
}


def text(path):
    return path.read_text(encoding="utf-8")


for source_path in ROOT.rglob("*"):
    relative = source_path.relative_to(ROOT)
    if any(part in IGNORED_SOURCE_PARTS for part in relative.parts):
        continue
    assert not KEY_FILE.search(source_path.name), \
        f"Schlüssel-/Secret-Datei im Quellbaum: {relative}"
    if source_path.is_file() and not source_path.is_symlink():
        assert not PRIVATE_KEY.search(source_path.read_bytes()), \
            f"privater Schlüssel im Quellbaum: {relative}"


assert f'PROGRAMM_FASSUNG = "{VERSION}"' in text(ROOT / "bin/magnolie-organizer")
version_lock = WORKSPACE / "DESKTOP_VERSION"
if version_lock.exists():
    assert text(version_lock).strip() == VERSION
assert f"magnolie-organizer ({VERSION})" in text(ROOT / "debian/changelog").splitlines()[0]
assert f"Version:        {VERSION}" in text(ROOT / "rpm/magnolie-organizer.spec")
if HANDBOOK.exists():
    assert f"magnolie-handbuch ({VERSION})" in text(
        HANDBOOK / "debian/changelog").splitlines()[0]
if WINDOWS.exists():
    assert f"<Version>{VERSION}</Version>" in text(
        WINDOWS / "Directory.Build.props")
    installer = text(WINDOWS / "installer/MagnolieOrganizer.nsi")
    assert "!ifndef PRODUCT_VERSION" in installer
    assert '-DPRODUCT_VERSION="$version"' in text(WINDOWS / "installer/BuildInstaller.sh")
    assert "CreateShortcut \"$SMPROGRAMS\\$StartMenuFolder\\Magnolie Organizer deinstallieren.lnk\"" not in installer
    assert "Delete \"$SMPROGRAMS\\$StartMenuFolder\\Magnolie Organizer deinstallieren.lnk\"" in installer
    windows_build = text(WINDOWS / "build/Build.ps1")
    windows_common = text(WINDOWS / "build/Release.Common.ps1")
    assert "New-DeterministicZip" in windows_build
    assert "Compression.ZipArchive" in windows_common
    assert "Compress-Archive" not in windows_build
if HANDBOOK.exists():
    handbook_rules = text(HANDBOOK / "debian/rules")
    assert "override_dh_auto_test:" in handbook_rules
    assert "werkzeuge/katalog_pruefen.py" in handbook_rules
    assert "pruefungen/handbuch_test.js" in handbook_rules
    assert "pruefungen/druck_test.py --cli-only" in handbook_rules

organizer_update = ET.parse(ROOT / "update.xml").getroot()
for manifest in (organizer_update,):
    manual = manifest.find("manual")
    assert manual is not None
    assert [child.tag for child in manual] == ["version", "linux", "windows"]
    assert re.fullmatch(r"[0-9a-f]{64}", manual.findtext("linux/sha256") or "")
    assert re.fullmatch(r"[0-9a-f]{64}", manual.findtext("windows/sha256") or "")
install_manifest = text(ROOT / "debian/install")
debian_control = text(ROOT / "debian/control")
recommends = debian_control.split("Recommends:", 1)[1].split("Suggests:", 1)[0]
suggests = debian_control.split("Suggests:", 1)[1].split("Description:", 1)[0]
for audio_server in ("pulseaudio,", "pipewire-pulse"):
    assert audio_server not in debian_control
for optional_desktop in ("bluez", "gnome-shell-extension-appindicator",
                         "libcanberra-gtk3-module"):
    assert optional_desktop not in recommends
    assert optional_desktop in suggests
for audio_client in ("pulseaudio-utils", "pipewire-bin", "alsa-utils"):
    assert audio_client in suggests
assert not INTERNAL_NOTE.search(install_manifest)
assert "web/kaffee-qr.png" in install_manifest
helper = "bin/magnolie_personal_sync.py"
assert (ROOT / helper).is_file()
assert f"{helper}          usr/bin" in install_manifest
assert f"{helper}          usr/lib/magnolie-organizer" in install_manifest
assert "bin/magnolie_nextcloud.py              usr/bin" in install_manifest
assert png_pruefen(ROOT / "web/kaffee-qr.png") == (266, 266)
assert '"/kaffee-qr.png": ("kaffee-qr.png", "image/png")' in text(
    ROOT / "bin/magnolie-organizer")
rpm_builder = text(ROOT / "werkzeuge/rpm_bauen.sh")
for marker in ("REVIEW", "ENTWURF", "OFFENE-PUNKTE", "ANALYSE", "PLAN", "AUDIT"):
    assert marker in rpm_builder
source_options = text(ROOT / "debian/source/options")
assert "magnolie_personal_sync.py" not in source_options
rpm_spec = text(ROOT / "rpm/magnolie-organizer.spec")
assert "bin/magnolie_personal_sync.py %{buildroot}%{_bindir}/magnolie_personal_sync.py" in rpm_spec
assert "%{_bindir}/magnolie_personal_sync.py" in rpm_spec
assert "bin/magnolie_nextcloud.py %{buildroot}%{_bindir}/magnolie_nextcloud.py" in rpm_spec
assert "%{_bindir}/magnolie_nextcloud.py" in rpm_spec
assert "web/kaffee-qr.png" in rpm_spec
assert '%{buildroot}%{_datadir}/%{name}/web/kaffee-qr.png' in rpm_spec
assert 'root = pathlib.Path(r"%{buildroot}")' in rpm_spec
assert "import magnolie_personal_sync" in rpm_spec
assert "magnolie_telefon.validate_personal_sync_body" in rpm_spec
assert "werkzeuge/png_pruefen.py" in rpm_spec
assert '%{buildroot}%{_datadir}/%{name}/web/index.html' in rpm_spec
assert '${MAGNOLIE_CONTRIBUTOR_HASH:-}' in rpm_spec
assert 'build-config.json' in rpm_spec
installed_test = text(ROOT / "debian/tests/installed")
assert "ENTWURF-MAGNOLIENBAUM" not in installed_test
assert "/usr/share/magnolie-organizer/web/kaffee-qr.png" in installed_test
for marker in ("function oeffneSuche", "syncMetadaten", "nextcloud:"):
    assert marker in installed_test
    assert marker in text(ROOT / "web/anwendung.js")
assert "/usr/share/doc/magnolie-organizer/INTERNATIONALISIERUNG.md" in installed_test
appimage_builder = text(ROOT / "werkzeuge/appimage_bauen.sh")
jammy_builder = text(ROOT / "werkzeuge/appimage_jammy_bauen.sh")
web_script = text(ROOT / "web/anwendung.js")
web_style = text(ROOT / "web/stil.css")
assert '"blaettern-vor", "blaettern-zurueck"' in web_script
assert '#seiten.blaettern-vor .seite.rechts' in web_style
assert 'rotateY(-62deg)' in web_style and 'rotateY(62deg)' in web_style
assert 'animation: puls' not in web_style
assert '@keyframes puls' not in web_style
assert 'bin/magnolie_personal_sync.py" "$APPDIR/usr/bin/magnolie_personal_sync.py"' in appimage_builder
assert 'bin/magnolie_nextcloud.py" "$APPDIR/usr/bin/magnolie_nextcloud.py"' in appimage_builder
assert ': "${WEBKIT_DISABLE_DMABUF_RENDERER:=1}"' in appimage_builder
assert "WEBKIT_DISABLE_COMPOSITING_MODE" not in appimage_builder
assert ': "${GDK_BACKEND:=x11}"' in appimage_builder
assert 'export GTK_DATA_PREFIX="$APPDIR/usr"' in appimage_builder
assert 'export FONTCONFIG_FILE="$FONTCONFIG_PATH/fonts.conf"' in appimage_builder
fontconfig = text(ROOT / "werkzeuge/appimage-fonts.conf")
assert '<include' not in fontconfig
for font_dir in ('<dir>/usr/share/fonts</dir>', '<dir>/usr/local/share/fonts</dir>',
                 '<dir prefix="xdg">fonts</dir>', '<dir>~/.fonts</dir>'):
    assert font_dir in fontconfig
for binary_builder in (appimage_builder, rpm_builder, text(ROOT / "debian/rules")):
    assert "MAGNOLIE_CONTRIBUTOR_HASH" in binary_builder
    assert "tr A-F a-f" in binary_builder
    assert 'if [ -n "$' in binary_builder or 'if test -n "$hash"' in binary_builder
assert "ubuntu-base-22.04.5" in jammy_builder
assert "BASIS_SHA=" in jammy_builder and "SNAPSHOT=" in jammy_builder
assert "werkzeuge/appimage_jammy_bauen.sh" in text(ROOT / "werkzeuge/release_bauen.sh")
flatpak_manifest = text(ROOT / "flatpak/io.gitlab.maik3531.MagnolieOrganizer.json")
flatpak_builder = text(ROOT / "werkzeuge/flatpak_bauen.sh")
assert '"runtime-version": "49"' in flatpak_manifest
assert '"--socket=pulseaudio"' in flatpak_manifest
assert '"--device=dri"' not in flatpak_manifest
assert "org.flatpak.Builder" in flatpak_builder
assert "flatpak build-bundle" in flatpak_builder
assert 'MAGNOLIE_CONTRIBUTOR_HASH' in flatpak_builder
assert "0000000000000000000000000000000000000000000000000000000000000000" not in flatpak_manifest
assert "if contributor_hash:" in flatpak_builder
assert '--filesystem="$WURZEL"' in flatpak_builder
assert '--default-branch="$ZWEIG"' in flatpak_builder
assert '--override-source-date-epoch="$SOURCE_EPOCH"' in flatpak_builder
assert '--state-dir="$ARBEIT/state"' in flatpak_builder
release_builder = text(ROOT / "werkzeuge/release_bauen.sh")
for gate in ("--skip-autopkgtest", "--skip-system-package-tests",
              "MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE",
               "autopkgtest", "werkzeuge/rpm_fedora_bauen.sh", "RPM_FEDORA_DIR",
               "HANDBUCH_RPM_PAKET", "HANDBUCH_RPM_QUELLE",
               "WINDOWS-RUNTIME-UNVERIFIED.txt", "HANDBUCH_DEB",
               "Magnolie-Organizer-PRUEFSUMMEN.sha256", "sha256sum -c",
               "werkzeuge/flatpak_bauen.sh", "test_flatpak.py", "FLATPAK_VERGLEICH"):
    assert gate in release_builder, gate
assert "autopkgtest fehlt; Freigabe abgebrochen" in release_builder
assert release_builder.index("werkzeuge/rpm_fedora_bauen.sh") < release_builder.rindex(
    "VEROEFFENTLICHEN=1")
fedora_builder = text(ROOT / "werkzeuge/rpm_fedora_bauen.sh")
for gate in ("Fedora-WSL-Base-42-1.1.x86_64.tar.xz", "BASIS_SHA=", "bwrap",
             "--unshare-user", "gpgcheck=1", "fakeroot", "rpm -V",
             "magnolie-organizer", "magnolie-handbuch"):
    assert gate in fedora_builder, gate
assert "command -v flock" in release_builder and "flock -n 9" in release_builder
assert release_builder.index("flock -n 9") < release_builder.index("STAGE=$(mktemp")
assert "MAGNOLIE_UPDATE_SIGNING_KEY" in release_builder
assert release_builder.index("--check-key") < release_builder.index("STAGE=$(mktemp")
assert release_builder.count("werkzeuge/update_signieren.py") >= 5
assert release_builder.index("--verify") < release_builder.rindex("VEROEFFENTLICHEN=1")
for key_kind in ("PRIVATE KEY", "[A-Z0-9]+ ", "release[-_.]?key", "p12|pfx"):
    assert key_kind in release_builder
assert 'UPDATE_SIGNATUR_SCHLUESSEL = "8eJWsygSF9wsF22cuf+sChUUV5RtXEZt38Ngcugn/1Y="' in text(
    ROOT / "bin/magnolie-organizer")
assert 'chmod 0755 "$APPIMAGE"' in release_builder
assert "Magnolie-Organizer-$FASSUNG-x86_64.flatpak" in release_builder
assert "AppImage|flatpak" in release_builder
assert 'export MAGNOLIE_CONTRIBUTOR_HASH' in release_builder
assert 'build-config.json' in release_builder
assert 'MAGNOLIE_CONTRIBUTOR_HASH="$CONTRIBUTOR_HASH"' in fedora_builder
assert release_builder.count("dpkg-buildpackage -b -d -us -uc") == 4
assert release_builder.count("DEB_BUILD_OPTIONS=nocheck") == 6
assert "dpkg-buildpackage -S -d -us -uc" in release_builder
binary_compare = release_builder.index('cmp "$DEB_VERGLEICH" "$DEB"')
manifest_build = release_builder.index("python3 werkzeuge/release_manifest.py")
source_build = release_builder.rindex("dpkg-buildpackage -S -d -us -uc")
assert binary_compare < manifest_build < source_build
assert 'tar -xOf "$SOURCE_TAR"' in release_builder
assert '"$SOURCE_NAME/update.xml"' in release_builder
assert 'cmp "$WURZEL/update.xml" "$ARCHIV_MANIFEST"' in release_builder
assert "rm -f Magnolie-Organizer-PRUEFSUMMEN.sha256" in release_builder
assert "Magnolie-Organizer-PRUEFSUMMEN[.]sha256" in release_builder
assert "'(^|/)build-config[.]json$'" in release_builder
assert release_builder.index('cmp "$WURZEL/update.xml" "$ARCHIV_MANIFEST"') < release_builder.rindex(
    "VEROEFFENTLICHEN=1")
desktop_commit = release_builder[release_builder.rindex("VEROEFFENTLICHEN=1"):]
assert desktop_commit.index(': > "$marker"') < desktop_commit.index('mv "$STAGE/$rel" "$ziel"')
assert desktop_commit.index("sync") < desktop_commit.index("VEROEFFENTLICHEN=0")
publish_list = release_builder[release_builder.index('PUBLISH_PATHS="'):release_builder.rindex(
    "for rel in $PUBLISH_PATHS")]
assert publish_list.rindex("RPM_QUELLE") < publish_list.rindex("PRUEFSUMMEN.sha256")
assert publish_list.rindex("PRUEFSUMMEN.sha256") < publish_list.rindex("update.xml")
for excluded in (".pytest_cache", ".kotlin", "app/build", "*.tar.*"):
    assert excluded in text(ROOT / "werkzeuge/rpm_bauen.sh")

for source_root in (ROOT, WINDOWS, HANDBOOK):
    for path in source_root.glob("*.md"):
        assert not INTERNAL_NOTE.search(path.name), f"interne Arbeitsnotiz im Quellbaum: {path}"

current_files = [
    (ROOT / "LIESMICH.md", VERSION),
    (ROOT / "update.xml", MANIFEST_VERSION),
]
if WINDOWS.exists():
    current_files += [(WINDOWS / "LIESMICH.md", VERSION)]
if HANDBOOK.exists():
    current_files += [(HANDBOOK / "LIESMICH.md", VERSION),
                      (HANDBOOK / "web/inhalt.js", VERSION)]
for path, expected_version in current_files:
    value = text(path)
    assert expected_version in value, f"{expected_version} fehlt: {path}"
    assert not re.search(r"Magnolie-Organizer-(1\.31|Windows-1\.0)", value), path

def test_statische_paketpruefung():
    """Top-level assertions also run when this file is executed directly."""
    assert True


print("Paketinhalt und Linux-Version 2.0.9: ok")
