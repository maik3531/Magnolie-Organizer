#!/usr/bin/env python3
"""Static release-version and source-package policy checks."""

from pathlib import Path
import base64
import re
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT / "werkzeuge"))
from png_pruefen import pruefen as png_pruefen
WINDOWS = WORKSPACE / "Magnolie-Organizer-Windows-2.0.0"
HANDBOOK = WORKSPACE / "magnolie-handbuch-stamm"
VERSION = "2.0.16"
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
    assert manifest.findtext("version") == VERSION
    signatur = manifest.findtext("signature")
    pruefsummen = [manifest.findtext(pfad) for pfad in (
        "sha256", "appimage/sha256", "manual/linux/sha256",
        "manual/windows/sha256", "windows/sha256")]
    if signatur is None:
        assert all(wert is None for wert in pruefsummen)
    else:
        assert len(base64.b64decode(signatur, validate=True)) == 64
        assert all(re.fullmatch(r"[0-9a-f]{64}", wert or "")
                   for wert in pruefsummen)
    manual = manifest.find("manual")
    assert manual is not None
    assert [child.tag for child in manual] == ["version", "linux", "windows"]
    assert manual.findtext("version") == VERSION
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
assert "web/kaffee-qr.mga" in install_manifest
assert "web/kaffee-qr.png" not in install_manifest
helper = "bin/magnolie_personal_sync.py"
assert (ROOT / helper).is_file()
assert f"{helper}          usr/bin" in install_manifest
assert f"{helper}          usr/lib/magnolie-organizer" in install_manifest
assert "bin/magnolie_nextcloud.py              usr/bin" in install_manifest
assert "bin/magnolie_cloud_backup.py           usr/bin" in install_manifest
assert "bin/magnolie_akonadi.py                usr/bin" in install_manifest
assert (ROOT / "web/kaffee-qr.mga").read_bytes().startswith(b"MGA1")
assert '"/kaffee-qr.png": ("kaffee-qr.mga", "image/png")' in text(
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
assert "bin/magnolie_cloud_backup.py %{buildroot}%{_bindir}/magnolie_cloud_backup.py" in rpm_spec
assert "%{_bindir}/magnolie_cloud_backup.py" in rpm_spec
assert "bin/magnolie_akonadi.py %{buildroot}%{_bindir}/magnolie_akonadi.py" in rpm_spec
assert "%{_bindir}/magnolie_akonadi.py" in rpm_spec
assert "web/kaffee-qr.mga" in rpm_spec
assert '%{buildroot}%{_datadir}/%{name}/web/kaffee-qr.mga' in rpm_spec
assert 'root = pathlib.Path(r"%{buildroot}")' in rpm_spec
assert "import magnolie_personal_sync" in rpm_spec
assert "magnolie_telefon.validate_personal_sync_body" in rpm_spec
assert "pruefungen/test_asset_container.py" in rpm_spec
assert '%{buildroot}%{_datadir}/%{name}/web/index.html' in rpm_spec
assert '${MAGNOLIE_CONTRIBUTOR_HASH:-}' in rpm_spec
assert 'build-config.json' in rpm_spec
installed_test = text(ROOT / "debian/tests/installed")
assert "ENTWURF-MAGNOLIENBAUM" not in installed_test
assert "/usr/share/magnolie-organizer/web/kaffee-qr.mga" in installed_test
for marker in ("function oeffneSuche", "syncMetadaten", "nextcloud:"):
    assert marker in installed_test
    assert marker in text(ROOT / "web/anwendung.js")
assert "/usr/share/doc/magnolie-organizer/INTERNATIONALISIERUNG.md" in installed_test
appimage_builder = text(ROOT / "werkzeuge/appimage_bauen.sh")
jammy_builder = text(ROOT / "werkzeuge/appimage_jammy_bauen.sh")
launcher = text(ROOT / "bin/magnolie-organizer")
assert launcher.index("_grafik_kompatibilitaet_einrichten()") < launcher.index("import gi")
web_script = text(ROOT / "web/anwendung.js")
web_style = text(ROOT / "web/stil.css")
assert '"blaettern-vor", "blaettern-zurueck"' in web_script
assert '#seiten.blaettern-vor .seite.rechts' in web_style
assert 'rotateY(-62deg)' in web_style and 'rotateY(62deg)' in web_style
assert 'animation: puls' not in web_style
assert '@keyframes puls' not in web_style
assert 'bin/magnolie_personal_sync.py" "$APPDIR/usr/bin/magnolie_personal_sync.py"' in appimage_builder
assert 'bin/magnolie_nextcloud.py" "$APPDIR/usr/bin/magnolie_nextcloud.py"' in appimage_builder
assert 'bin/magnolie_cloud_backup.py" "$APPDIR/usr/bin/magnolie_cloud_backup.py"' in appimage_builder
assert 'bin/magnolie_akonadi.py" "$APPDIR/usr/bin/magnolie_akonadi.py"' in appimage_builder

akonadi_cmake = (ROOT / "native" / "akonadi-helper" / "CMakeLists.txt").read_text(
    encoding="utf-8")
akonadi_source = (ROOT / "native" / "akonadi-helper" / "main.cpp").read_text(
    encoding="utf-8")
akonadi_control = (ROOT / "native" / "akonadi-helper" / "debian" / "control").read_text(
    encoding="utf-8")
akonadi_changelog = text(ROOT / "native" / "akonadi-helper" / "debian" / "changelog")
akonadi_spec = text(ROOT / "native" / "akonadi-helper" / "magnolie-organizer-akonadi.spec")
assert "KPim6::AkonadiCore" in akonadi_cmake and "KPim5::AkonadiCore" in akonadi_cmake
assert "${CMAKE_INSTALL_LIBEXECDIR}/magnolie-organizer" in akonadi_cmake
assert "VERSION 1.0.0" in akonadi_cmake
assert all(('command == QLatin1String("%s")' % command) in akonadi_source
           for command in ("status", "snapshot", "create", "modify", "delete", "exists"))
assert "Package: magnolie-organizer-akonadi" in akonadi_control
assert "magnolie-organizer-akonadi (1.0.0)" in akonadi_changelog.splitlines()[0]
assert text(ROOT / "native" / "akonadi-helper" / "debian" / "source" / "format").strip() == "3.0 (native)"
assert "magnolie-organizer (>= 2.0.16)" in akonadi_control
assert "magnolie-organizer-akonadi" in debian_control
akonadi_rules = text(ROOT / "native" / "akonadi-helper" / "debian" / "rules")
assert "-DCMAKE_DISABLE_FIND_PACKAGE_KPim6Akonadi=ON" in akonadi_rules
assert "-DCMAKE_INSTALL_LIBEXECDIR=libexec" in akonadi_rules
assert "override_dh_clean:" in akonadi_rules
assert "rm -rf obj-*" in akonadi_rules
assert "rm -f debian/files debian/*.substvars" in akonadi_rules
assert "override_dh_shlibdeps:" in akonadi_rules
assert 'test -n "$$MAGNOLIE_SHLIBS_LOCAL"' in akonadi_rules
assert 'dh_shlibdeps -- -L"$$MAGNOLIE_SHLIBS_LOCAL"' in akonadi_rules
assert re.search(r"else \\\n\s*dh_shlibdeps;", akonadi_rules)
assert "%cmake -DCMAKE_BUILD_TYPE=Release" not in akonadi_spec
for metadata in ("Version:        1.0.0", "Source0:        %{name}-%{version}.tar.xz",
                 "Requires:       magnolie-organizer >= 2.0.16",
                 "%license debian/copyright", "%dir %{_libexecdir}/magnolie-organizer"):
    assert metadata in akonadi_spec
assert "Suggests:       magnolie-organizer-akonadi" in rpm_spec
assert ': "${MAGNOLIE_GRAPHICS_COMPAT:=0}"' in appimage_builder
assert ': "${WEBKIT_DISABLE_DMABUF_RENDERER:=1}"' not in appimage_builder
assert "WEBKIT_DISABLE_COMPOSITING_MODE" not in appimage_builder
assert ': "${GDK_BACKEND:=x11}"' not in appimage_builder
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
assert "Acquire::Retries=2" in jammy_builder
assert "Acquire::https::Timeout=30" in jammy_builder
assert 'timeout --foreground "$zeitlimit"' in jammy_builder
assert 'for pause in 0 15 45' in jammy_builder
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
               "werkzeuge/flatpak_bauen.sh", "test_flatpak.py", "FLATPAK_VERGLEICH",
               "MAGNOLIE_VOLLPRUEFUNG=1", "test_debian_koinstallation.sh",
               "test_naechster_weckzeitpunkt.py"):
    assert gate in release_builder, gate
for gate in ("AKONADI_ARCH=$(dpkg-architecture -qDEB_HOST_ARCH)",
             "magnolie-organizer-akonadi_${AKONADI_VERSION}_${AKONADI_ARCH}.deb",
             "AKONADI_DSC", "AKONADI_SOURCE_TAR", "AKONADI_VERGLEICH",
             "unsupported-smoke", "native/akonadi-helper/debian/source/format",
             "AKONADI_RPM_PAKET", "AKONADI_RPM_QUELLE"):
    assert gate in release_builder, gate
release_smoke = release_builder[release_builder.index(
    'if printf \'%s\' \'{"command":"unsupported-smoke"}\''):
    release_builder.index('rm -rf "$AKONADI_TEST"')]
assert 'akonadi_status=$?' in release_smoke
assert '[ "$akonadi_status" -eq 1 ]' in release_smoke
assert release_smoke.index('[ "$akonadi_status" -eq 1 ]') < release_smoke.index(
    'python3 - "$AKONADI_TEST/response.json"')
assert "autopkgtest fehlt; Freigabe abgebrochen" in release_builder
assert release_builder.index("werkzeuge/rpm_fedora_bauen.sh") < release_builder.rindex(
    "VEROEFFENTLICHEN=1")
fedora_builder = text(ROOT / "werkzeuge/rpm_fedora_bauen.sh")
for gate in ("Fedora-WSL-Base-42-1.1.x86_64.tar.xz", "BASIS_SHA=", "bwrap",
              "--unshare-user", "gpgcheck=1", "rpm -V",
              "magnolie-organizer", "magnolie-handbuch", "rpm -qf",
              "dnf -y remove magnolie-handbuch"):
    assert gate in fedora_builder, gate
assert "install fakeroot" in fedora_builder
assert fedora_builder.count("/usr/bin/fakeroot /usr/bin/dnf") == 3
assert fedora_builder.count("chmod -R u+rwX") == 2
for gate in ("AKONADI_TOPDIR", '--bind "$AKONADI_TOPDIR" "$AKONADI_TOPDIR"',
             "magnolie-organizer-akonadi-$AKONADI_VERSION.tar.xz",
             "rpmbuild -ba", "magnolie-organizer-akonadi", "unsupported-smoke"):
    assert gate in fedora_builder, gate
fedora_smoke_start = fedora_builder.index(
    "if fedora /bin/sh -c", fedora_builder.index("AKONADI_ANTWORT="))
fedora_smoke = fedora_builder[fedora_smoke_start:fedora_builder.index(
    "if [ -n \"$CONTRIBUTOR_HASH\" ]", fedora_smoke_start)]
assert 'akonadi_status=$?' in fedora_smoke
assert '[ "$akonadi_status" -eq 1 ]' in fedora_smoke
assert fedora_smoke.index('[ "$akonadi_status" -eq 1 ]') < fedora_smoke.index(
    'python3 - "$AKONADI_ANTWORT"')
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
assert release_builder.count("dpkg-buildpackage -b -d -us -uc") == 6
assert release_builder.count("DEB_BUILD_OPTIONS=nocheck") == 9
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
for excluded in ("native/akonadi-helper/obj-*",
                 "native/akonadi-helper/debian/files",
                 "native/akonadi-helper/debian/*.substvars"):
    assert excluded in release_builder
    assert excluded in rpm_builder
assert "--exclude='./obj-*'" in fedora_builder
assert "obj-[^/]*" in release_builder
assert "debian/(files|[^/]*[.]substvars)" in release_builder

readme = text(ROOT / "LIESMICH.md")
assert "sudo apt install native/magnolie-organizer-akonadi_1.0.0_" in readme
assert "sudo apt install ../native/magnolie-organizer-akonadi_1.0.0_" not in readme
if (WORKSPACE / ".gitignore").is_file():
    workspace_ignore = text(WORKSPACE / ".gitignore")
    assert "*.buildinfo" in workspace_ignore and "*.changes" in workspace_ignore
    release_notes = text(WORKSPACE / "HINWEIS.txt")
    assert "Akonadi-Helfers" in release_notes
    assert "Akonadi helper" in release_notes
    release_guide = text(WORKSPACE / "FREIGABE.md")
    assert "MAGNOLIE_SHLIBS_LOCAL=/pfad/zu/lokalen.shlibs" in release_guide
    assert "nicht für normale Paketbauten gesetzt" in release_guide

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


print("Paketinhalt und Linux-Version 2.0.16: ok")
