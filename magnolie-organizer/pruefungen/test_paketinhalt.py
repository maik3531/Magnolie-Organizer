#!/usr/bin/env python3
"""Static release-version and source-package policy checks."""

from pathlib import Path
import base64
import hashlib
import re
import sys
import tarfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT / "werkzeuge"))
from png_pruefen import pruefen as png_pruefen
WINDOWS = WORKSPACE / "magnolie-organizer-windows"
HANDBOOK = WORKSPACE / "magnolie-handbuch"
NOTES = WORKSPACE / "magnolie-notes"
VERSION = re.match(r"magnolie-organizer \(([^)]+)\)",
                   (ROOT / "debian/changelog").read_text(encoding="utf-8")).group(1)
from release_gate import BOOTSTRAP_VERSION as PUBLISHED_VERSION
INTERNAL_NOTE = re.compile(
    r"(REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|ANALYSE|PLAN|AUDIT).*\.md$", re.I)
PRIVATE_KEY = re.compile(
    rb"-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY)-----[\s\S]*?-----END \1-----")
KEY_FILE = re.compile(
    r"(?:^|[._-])(?:private[-_.]?key|release[-_.]?key|signing[-_.]?key)(?:[._-]|$)"
    r"|\.(?:key|pem|p12|pfx|secret|token)$|^\.env(?:\.|$)", re.I)
IGNORED_SOURCE_PARTS = {
    ".git", ".pytest_cache", ".kotlin", ".gradle", "__pycache__", "bau", "build",
    ".private-testing", ".claude", "node_modules",
}


def text(path):
    return path.read_text(encoding="utf-8")


for source_path in ROOT.rglob("*"):
    relative = source_path.relative_to(ROOT)
    if source_path.name == "an-claude.md" or any(part in IGNORED_SOURCE_PARTS for part in relative.parts):
        continue
    assert not KEY_FILE.search(source_path.name), \
        f"Schlüssel-/Secret-Datei im Quellbaum: {relative}"
    if source_path.is_file() and not source_path.is_symlink():
        assert not PRIVATE_KEY.search(source_path.read_bytes()), \
            f"privater Schlüssel im Quellbaum: {relative}"

notes_metadata = NOTES / "app/build.gradle.kts"
notes_version = re.search(r'versionName\s*=\s*"(\d+\.\d+\.\d+)"', text(notes_metadata)).group(1) if notes_metadata.is_file() else "unavailable"
staged_apk = WORKSPACE / f"Magnolie-Notes-{notes_version}.apk"
built_apk = NOTES / "app/build/outputs/apk/release/app-release.apk"
source_archive = WORKSPACE / f"magnolie-notes_{notes_version}.tar.xz"
if NOTES.exists() and all(path.is_file() for path in (
        staged_apk, built_apk, source_archive)):
    assert hashlib.sha256(staged_apk.read_bytes()).digest() == \
        hashlib.sha256(built_apk.read_bytes()).digest()
    excluded = {".gradle", ".kotlin", "build"}
    source_files = {
        path.relative_to(WORKSPACE).as_posix(): path
        for path in NOTES.rglob("*")
        if path.is_file() and not path.is_symlink() and
        not any(part in excluded for part in path.relative_to(NOTES).parts) and
        path.name not in {"local.properties", "schluessel.properties"}
    }
    with tarfile.open(source_archive, "r:xz") as archive:
        archived_files = {member.name: member for member in archive.getmembers()
                          if member.isfile()}
        assert set(archived_files) == set(source_files)
        for name, path in source_files.items():
            stream = archive.extractfile(archived_files[name])
            assert stream is not None and stream.read() == path.read_bytes(), name


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
for readme_name in ("README.md", "README.DE.md"):
    readme_path = WORKSPACE / readme_name
    if readme_path.exists():
        readme = text(readme_path)
        # Public download links continue to name the published release until promotion.
        readme_version = re.search(r"/Magnolie-Organizer-(\d+\.\d+\.\d+)-x86_64\.flatpak", readme).group(1)
        assert readme_version in {PUBLISHED_VERSION, VERSION}
        assert f"/Magnolie-Organizer-{readme_version}-x86_64.flatpak" in readme
        assert f"/Magnolie-Organizer-{readme_version}-x86_64.AppImage" in readme
        assert f"/magnolie-organizer_{readme_version}_all.deb" in readme
        assert f"/Magnolie-Organizer-Windows-{readme_version}-Setup-x64.exe" in readme
        assert f"/Magnolie-Organizer-Windows-{readme_version}-x64.zip" in readme
        assert f"/magnolie-handbuch_{readme_version}_all.deb" in readme
        desktop_download_versions = re.findall(
            r"/Magnolie-Organizer(?:-Windows)?-(\d+\.\d+\.\d+)-"
            r"|/magnolie-(?:organizer|handbuch)_(\d+\.\d+\.\d+)_", readme)
        assert desktop_download_versions
        assert all(readme_version in match for match in desktop_download_versions)
if HANDBOOK.exists():
    handbook_rules = text(HANDBOOK / "debian/rules")
    assert "override_dh_auto_test:" in handbook_rules
    assert "werkzeuge/katalog_pruefen.py" in handbook_rules
    assert "pruefungen/handbuch_test.js" in handbook_rules
    assert "pruefungen/druck_test.py --cli-only" in handbook_rules

organizer_update = ET.parse(ROOT / "update.xml").getroot()
for manifest in (organizer_update,):
    manifest_version = manifest.findtext("version")
    assert manifest_version in {PUBLISHED_VERSION, VERSION}
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
    assert manual.findtext("version") == manifest_version
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
appimage_builder = text(ROOT / "werkzeuge/appimage_bauen.sh")
assert appimage_builder.startswith("#!/bin/sh\nset -eu\numask 022\n")
assert "phonenumbers-9.0.38-py2.py3-none-any.whl" in appimage_builder
assert "f3cbeb1a42bf226060c60fc6277f5431755d325eddc23fbf2c72ef7e156113c6" in appimage_builder
assert "Das phonenumbers-Wheel ist ungueltig." in appimage_builder
assert "phonenumbers-copyright" in appimage_builder
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
akonadi_spec = text(ROOT / "native" / "akonadi-helper" / "magnolie-organizer-kde.spec")
assert "KPim6::AkonadiCore" in akonadi_cmake and "KPim5::AkonadiCore" in akonadi_cmake
assert "${CMAKE_INSTALL_LIBEXECDIR}/magnolie-organizer" in akonadi_cmake
assert f"VERSION {VERSION}" in akonadi_cmake
assert all(('command == QLatin1String("%s")' % command) in akonadi_source
           for command in ("status", "snapshot", "create", "modify", "delete", "exists"))
assert "Package: magnolie-organizer-kde" in akonadi_control
assert akonadi_control.count("\nPackage:") == 1
for relation in ("Provides: magnolie-organizer-akonadi (= ${binary:Version})",
                 "Breaks: magnolie-organizer-akonadi (<< ${binary:Version})",
                 "Replaces: magnolie-organizer-akonadi (<< ${binary:Version})"):
    assert relation in akonadi_control
assert f"magnolie-organizer-kde ({VERSION})" in akonadi_changelog.splitlines()[0]
assert "Suggests: akonadi-server, kdepim-runtime" in akonadi_control
assert text(ROOT / "native" / "akonadi-helper" / "debian" / "source" / "format").strip() == "3.0 (native)"
assert "magnolie-organizer (>= 2.0.18)" in akonadi_control
assert "magnolie-organizer-kde" in debian_control
organizer_binary_control = debian_control.split("Package: magnolie-organizer\n", 1)[1]
organizer_hard_dependencies = organizer_binary_control.split("Recommends:", 1)[0].lower()
assert all(name not in organizer_hard_dependencies
           for name in ("akonadi", "kdepim", "libkf", "qt5", "qt6"))
assert "Suggests:" in organizer_binary_control
assert "magnolie-organizer-kde" in organizer_binary_control.split("Suggests:", 1)[1]
akonadi_rules = text(ROOT / "native" / "akonadi-helper" / "debian" / "rules")
native_kde_builder = text(ROOT / "native/akonadi-helper/build.py")
assert "-DCMAKE_DISABLE_FIND_PACKAGE_KPim6Akonadi=ON" in native_kde_builder
assert "python3 build.py --payload build/payload" in akonadi_rules
assert "override_dh_clean:" in akonadi_rules
assert "rm -rf build" in akonadi_rules and "dh_clean" in akonadi_rules
assert "override_dh_shlibdeps:" in akonadi_rules
assert 'run("dpkg-shlibdeps", "-O"' in native_kde_builder
assert "MAGNOLIE_SHLIBS_LOCAL" not in akonadi_rules
assert "dh $@ --buildsystem=none" in akonadi_rules
assert '"-DCMAKE_REQUIRE_FIND_PACKAGE_" + name + "=ON"' in native_kde_builder
assert '("KPim6Akonadi", "KF6CalendarCore", "KF6Contacts")' in native_kde_builder
assert "%cmake -DCMAKE_BUILD_TYPE=Release" not in akonadi_spec
for metadata in (f"Version:        {VERSION}", "Source0:        %{name}-%{version}.tar.xz",
                  "Requires:       magnolie-organizer >= 2.0.18",
                  "Provides:       magnolie-organizer-akonadi",
                  "Obsoletes:      magnolie-organizer-akonadi",
                  "%license debian/copyright", "%dir %{_libexecdir}/magnolie-organizer"):
    assert metadata in akonadi_spec
assert "Suggests:       magnolie-organizer-kde" in rpm_spec
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
promotion_gate = text(ROOT / "werkzeuge/release_gate.py")
for gate in ("--skip-autopkgtest", "--skip-system-package-tests",
              "MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE",
               "autopkgtest", "werkzeuge/rpm_fedora_bauen.sh", "RPM_FEDORA_DIR",
               "HANDBUCH_RPM_PAKET", "HANDBUCH_RPM_QUELLE",
               "WINDOWS-RUNTIME-UNVERIFIED.txt", "HANDBUCH_DEB",
               "Magnolie-Organizer-PRUEFSUMMEN.sha256", "sha256sum -c",
               "werkzeuge/flatpak_bauen.sh", "test_flatpak.py", "FLATPAK_VERGLEICH",
               "MAGNOLIE_VOLLPRUEFUNG=1", "test_debian_koinstallation.sh",
               "test_naechster_weckzeitpunkt.py"):
    assert gate in release_builder or gate in promotion_gate, gate
for gate in ('KDE_STAGE="$STAGE/kde-component"',
             'werkzeuge/kde_deb_bauen.py" "$KDE_STAGE"',
             "AKONADI_RPM_PAKET", "AKONADI_RPM_QUELLE",
              'kde-"${AKONADI_VERSION}"-provenance.json'):
    assert gate in release_builder, gate
kde_builder = text(ROOT / "werkzeuge/kde_deb_bauen.py")
kde_profiles = text(ROOT / "native/akonadi-helper/profiles.py")
assert '"native/akonadi-helper/build.py"' in kde_builder
for target in ("ubuntu24.04", "debian13", "ubuntu26.04"):
    assert target in kde_profiles
for gate in ('"--unshare-all"', '"--ro-bind", str(rootfs), "/"',
              'run("dpkg-checkbuilddeps")', '["dpkg-buildpackage", "-b", "-us", "-uc", "--jobs=2"]',
              'hashes[0] == hashes[1]', '["dpkg-buildpackage", "-S", "-us", "-uc"]',
             '"unsupported-smoke"', 'probe.returncode == 1', 'reply["ok"] is False',
              'error in reply["error"]', 'for target, profile in PROFILES.items()',
              'records[target]["sameArtifactCheck"] = hashes[0]'):
    assert gate in native_kde_builder, gate
assert "MAGNOLIE_SHLIBS_LOCAL" not in native_kde_builder
assert "autopkgtest fehlt; Freigabe abgebrochen" in release_builder
assert release_builder.index("werkzeuge/rpm_fedora_bauen.sh") < release_builder.rindex(
    'release_gate.py" seal')
fedora_builder = text(ROOT / "werkzeuge/rpm_fedora_bauen.sh")
for gate in ("Fedora-WSL-Base-42-1.1.x86_64.tar.xz", "BASIS_SHA=", "bwrap",
              "--unshare-user", "gpgcheck=1", "rpm -V",
              "magnolie-organizer", "magnolie-handbuch", "rpm -qf",
              "dnf -y remove magnolie-handbuch",
              "dnf -y remove \\\n    gtk3 libnotify"):
    assert gate in fedora_builder, gate
assert "install fakeroot" in fedora_builder
assert fedora_builder.count("/usr/bin/fakeroot /usr/bin/dnf") == 4
assert fedora_builder.count("chmod -R u+rwX") == 2
for gate in ("AKONADI_TOPDIR", '--bind "$AKONADI_TOPDIR" "$AKONADI_TOPDIR"',
             "magnolie-organizer-kde-$AKONADI_VERSION.tar.xz",
             "rpmbuild -ba", "magnolie-organizer-kde", "unsupported-smoke"):
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
assert "MAGNOLIE_UPDATE_SIGNING_KEY" in promotion_gate
assert "update_signieren.py" not in release_builder
assert promotion_gate.index('verify(root, directory, approval, accepted_id, bindings=bindings)') < promotion_gate.index('"--check-key"')
assert "VEROEFFENTLICHTE_FASSUNG=" in release_builder
assert '"$ALTER_ORGANIZER" "$ALTES_HANDBUCH"' in release_builder
assert "Vorgaengerpaket fuer den Upgrade-Test fehlt" in release_builder
assert "magnolie-organizer_2.0.14_all.deb" not in release_builder
assert "Ein Release-Changelog-Zeitstempel liegt in der Zukunft." in release_builder
assert release_builder.index("handbuch_epoch_live=") < release_builder.index("STAGE=$(mktemp")
assert promotion_gate.index('"--verify"') < promotion_gate.index('publish_files(root, stage, ordered, precondition, postcondition)', promotion_gate.index('def promote('))
for key_kind in ("PRIVATE KEY", "[A-Z0-9]+ ", "release[-_.]?key", "p12|pfx"):
    assert key_kind in release_builder
assert 'UPDATE_SIGNATUR_SCHLUESSEL = "8eJWsygSF9wsF22cuf+sChUUV5RtXEZt38Ngcugn/1Y="' in text(
    ROOT / "bin/magnolie-organizer")
assert '0o755 if name.endswith(".AppImage")' in promotion_gate
assert "Magnolie-Organizer-$FASSUNG-x86_64.flatpak" in release_builder
assert "AppImage|flatpak" in release_builder
assert 'export MAGNOLIE_CONTRIBUTOR_HASH' in release_builder
assert 'build-config.json' in release_builder
assert 'MAGNOLIE_CONTRIBUTOR_HASH="$CONTRIBUTOR_HASH"' in fedora_builder
assert 'require(profile["abi"] in deps' in native_kde_builder
assert "magnolie-organizer \\(>= 2[.]0[.]16\\)" not in release_builder
assert release_builder.count("dpkg-buildpackage -b -d -us -uc") == 4
assert release_builder.count("DEB_BUILD_OPTIONS=nocheck") == 6
assert release_builder.count("kde_deb_bauen.py") == 1
assert 'for _ in range(2):' in native_kde_builder
assert 'hashes[0] == hashes[1]' in native_kde_builder
assert "dpkg-buildpackage -S -d -us -uc" in release_builder
binary_compare = release_builder.index('cmp "$DEB_VERGLEICH" "$DEB"')
source_build = release_builder.rindex("dpkg-buildpackage -S -d -us -uc")
assert binary_compare < source_build < release_builder.index('release_gate.py" seal')
assert 'tar -xOf "$SOURCE_TAR"' in release_builder
assert '"$SOURCE_NAME/update.xml"' in release_builder
assert 'cmp "$WURZEL/update.xml" "$ARCHIV_MANIFEST"' in release_builder
assert "rm -f Magnolie-Organizer-PRUEFSUMMEN.sha256" in release_builder
assert "Magnolie-Organizer-PRUEFSUMMEN[.]sha256" in release_builder
assert "'(^|/)build-config[.]json$'" in release_builder
assert release_builder.index('cmp "$WURZEL/update.xml" "$ARCHIV_MANIFEST"') < release_builder.rindex(
    'release_gate.py" seal')
assert 'os.replace(target, saved)' in promotion_gate
assert 'for target, saved in reversed(backups)' in promotion_gate
assert 'ordered += [f"{LINUX}/update.xml", "update.xml", "PRUEFSUMMEN.sha256"]' in promotion_gate
for excluded in (".pytest_cache", ".kotlin", "app/build", "*.tar.*"):
    assert excluded in text(ROOT / "werkzeuge/rpm_bauen.sh")
for excluded in ("native/akonadi-helper/obj-*",
                 "native/akonadi-helper/debian/files",
                 "native/akonadi-helper/debian/*.substvars"):
    assert excluded in rpm_builder
assert 'release_sources.py" copy' in release_builder
assert "--exclude='./obj-*'" in fedora_builder
assert "obj-[^/]*" in release_builder
assert "debian/(files|[^/]*[.]substvars)" in release_builder

readme = text(ROOT / "LIESMICH.md")
assert f"magnolie-organizer-kde_{VERSION}_amd64.deb" in readme
for target in ("ubuntu24.04", "debian13", "ubuntu26.04"):
    assert f"magnolie-organizer-kde_{VERSION}.{target}_amd64.deb" not in readme
assert f"sudo apt install ../native/magnolie-organizer-kde_{VERSION}_" not in readme
if (WORKSPACE / ".gitignore").is_file():
    workspace_ignore = text(WORKSPACE / ".gitignore")
    assert "*.buildinfo" in workspace_ignore and "*.changes" in workspace_ignore
    assert not (WORKSPACE / "HINWEIS.txt").exists()
    assert not (WORKSPACE / "FREIGABE.md").exists()

for source_root in (ROOT, WINDOWS, HANDBOOK):
    for path in source_root.glob("*.md"):
        assert not INTERNAL_NOTE.search(path.name), f"interne Arbeitsnotiz im Quellbaum: {path}"

current_files = [
    (ROOT / "LIESMICH.md", VERSION),
    (ROOT / "update.xml", manifest_version),
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


print(f"Paketinhalt und Linux-Version {VERSION}: ok")
