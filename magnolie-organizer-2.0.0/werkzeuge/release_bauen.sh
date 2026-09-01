#!/bin/sh
set -eu

AUTOPKGTESTS=1
FEDORA_TESTS=1
case "${1:-}" in
    "") ;;
    --skip-autopkgtest) AUTOPKGTESTS=0 ;;
    --skip-system-package-tests) AUTOPKGTESTS=0; FEDORA_TESTS=0 ;;
    *) printf 'Aufruf: %s [--skip-autopkgtest|--skip-system-package-tests]\n' "$0" >&2; exit 2 ;;
esac

LIVE_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LIVE_ROOT=$(dirname "$LIVE_SOURCE")
LIVE_HANDBUCH="$LIVE_ROOT/magnolie-handbuch-stamm"
UPDATE_SIGNATUR_SCHLUESSEL='8eJWsygSF9wsF22cuf+sChUUV5RtXEZt38Ngcugn/1Y='
MAGNOLIE_UPDATE_SIGNING_KEY=${MAGNOLIE_UPDATE_SIGNING_KEY:-${HOME:-}/.local/share/magnolie-release/update-ed25519.pem}
python3 "$LIVE_SOURCE/werkzeuge/update_signieren.py" --check-key \
    "$MAGNOLIE_UPDATE_SIGNING_KEY" "$UPDATE_SIGNATUR_SCHLUESSEL"
FASSUNG=$(dpkg-parsechangelog -l"$LIVE_SOURCE/debian/changelog" -SVersion)
SOURCE_NAME="magnolie-organizer-$FASSUNG"
LIVE_SOURCE_NAME=$(basename "$LIVE_SOURCE")
LIVE_WINDOWS=${MAGNOLIE_WINDOWS_ROOT:-"$LIVE_ROOT/Magnolie-Organizer-Windows-2.0.0"}
WINDOWS_INSTALLER="$LIVE_WINDOWS/Magnolie-Organizer-Windows-$FASSUNG-Setup-x64.exe"
WINDOWS_ZIP="$LIVE_WINDOWS/Magnolie-Organizer-Windows-$FASSUNG-x64.zip"
WINDOWS_PRUEFSUMMEN="$LIVE_WINDOWS/Magnolie-Organizer-Windows-$FASSUNG-PRUEFSUMMEN.sha256"
CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
[ "${#CONTRIBUTOR_HASH}" -eq 64 ] || {
    printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH fehlt oder ist ungueltig.' >&2; exit 2;
}
case "$CONTRIBUTOR_HASH" in
    *[!0-9a-fA-F]*) printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH fehlt oder ist ungueltig.' >&2; exit 2 ;;
esac
MAGNOLIE_CONTRIBUTOR_HASH=$(printf '%s' "$CONTRIBUTOR_HASH" | tr A-F a-f)
export MAGNOLIE_CONTRIBUTOR_HASH
LAEUFER=$(command -v node || command -v nodejs || command -v bun)
LASTDATEI=${MAGNOLIE_LASTDATEI:-/tmp/lotus-gross.csv}
for datei in "$WINDOWS_INSTALLER" "$WINDOWS_ZIP" "$WINDOWS_PRUEFSUMMEN"; do
    test -s "$datei" || {
        printf '%s\n' "Windows-Freigabeartefakt fehlt: $datei" >&2
        exit 1
    }
done
(cd "$LIVE_WINDOWS" && sha256sum -c "$(basename "$WINDOWS_PRUEFSUMMEN")")
if command -v unzip >/dev/null 2>&1 && \
        unzip -Z1 "$WINDOWS_ZIP" | grep -Fxq 'WINDOWS-RUNTIME-UNVERIFIED.txt'; then
    printf '%s\n' \
        'WARNUNG: Windows-Artefakte sind markierte, nicht laufzeitvalidierte Cross-Builds.' >&2
fi
command -v flock >/dev/null 2>&1 || {
    printf '%s\n' 'flock fehlt; Freigabe abgebrochen.' >&2; exit 1;
}
LOCK="$LIVE_ROOT/.magnolie-desktop-release.lock"
exec 9>"$LOCK"
flock -n 9 || {
    printf '%s\n' 'Eine Desktop-Freigabe laeuft bereits; Freigabe abgebrochen.' >&2
    exit 1
}
STAGE=$(mktemp -d "$LIVE_ROOT/.magnolie-desktop-release.XXXXXX")
WURZEL="$STAGE/$SOURCE_NAME"
BACKUP="$STAGE/.rollback"
VEROEFFENTLICHEN=0
PUBLISH_PATHS=

rollback() {
    for rel in $PUBLISH_PATHS; do
        ziel="$LIVE_ROOT/$rel"
        sicherung="$BACKUP/$rel"
        marker="$BACKUP/.moved/$rel"
        if [ -e "$sicherung" ]; then
            rm -f "$ziel"
            mkdir -p "$(dirname "$ziel")"
            mv "$sicherung" "$ziel"
        elif [ -e "$marker" ]; then
            rm -f "$ziel"
        fi
    done
}

cleanup() {
    status=$?
    trap - EXIT
    trap '' HUP INT TERM
    if [ "$VEROEFFENTLICHEN" -eq 1 ]; then rollback; fi
    rm -rf "$STAGE"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

mkdir -p "$WURZEL" "$STAGE/magnolie-handbuch-stamm"
tar -C "$LIVE_SOURCE" --exclude='./.git' --exclude='./bau' \
    --exclude='./.flatpak-builder' --exclude='./.pytest_cache' --exclude='./.kotlin' --exclude='./.gradle' \
    --exclude='./build' -cf - . | tar -C "$WURZEL" -xf -
tar -C "$LIVE_HANDBUCH" --exclude='./.git' --exclude='./bau' \
    --exclude='./.pytest_cache' -cf - . | \
    tar -C "$STAGE/magnolie-handbuch-stamm" -xf -
cp "$LIVE_ROOT/update.xml" "$STAGE/update.xml"
rm -rf "$WURZEL/.git" "$WURZEL/.flatpak-builder" "$WURZEL/bau" "$WURZEL/.pytest_cache" "$WURZEL/.kotlin" \
    "$WURZEL/.gradle" "$WURZEL/build" \
    "$WURZEL/debian/.debhelper" "$WURZEL/debian/debhelper-build-stamp" \
    "$WURZEL/debian/files" "$WURZEL"/debian/*.substvars \
    "$STAGE/magnolie-handbuch-stamm/.git" \
    "$STAGE/magnolie-handbuch-stamm/bau" \
    "$STAGE/magnolie-handbuch-stamm/.pytest_cache" \
    "$STAGE/magnolie-handbuch-stamm/debian/.debhelper" \
    "$STAGE/magnolie-handbuch-stamm/debian/debhelper-build-stamp" \
    "$STAGE/magnolie-handbuch-stamm/debian/files" \
    "$STAGE/magnolie-handbuch-stamm"/debian/*.substvars
find "$WURZEL" -type d \( -name __pycache__ -o -name .pytest_cache \
    -o -name .kotlin -o -name .gradle \) -prune -exec rm -rf {} +

cd "$WURZEL"
debian/rules build
python3 -m pytest -q pruefungen/test_locale_completeness.py
DISPLAY= WAYLAND_DISPLAY= XDG_DATA_HOME="$STAGE/test-data" \
XDG_CONFIG_HOME="$STAGE/test-config" TZ=Europe/Berlin \
    python3 pruefungen/test_parser.py
python3 -m pytest -q pruefungen/test_kdeconnect.py pruefungen/test_personal_sync.py \
    pruefungen/test_nextcloud.py pruefungen/test_hintergrunddienst.py \
    pruefungen/test_naechster_weckzeitpunkt.py pruefungen/test_eds_adressbuch_sync.py \
    pruefungen/test_chromium_fallback.py pruefungen/test_eds_calendar_dedup.py \
    pruefungen/test_elf_glibc.py pruefungen/test_release_signatur.py \
    pruefungen/test_restkorrekturen.py pruefungen/test_thunderbird_schema23.py \
    pruefungen/test_update_security.py
MAGNOLIE_VOLLPRUEFUNG=1 python3 -m pytest -q pruefungen/test_crash_reports.py
TZ=Europe/Berlin python3 pruefungen/test_import_export_vertrag.py
TZ=Europe/Berlin python3 pruefungen/test_gesamtarchiv.py
TZ=Europe/Berlin python3 pruefungen/test_telefon.py
TZ=Europe/Berlin python3 pruefungen/test_wiederherstellungsjournal.py
python3 pruefungen/test_paketinhalt.py
TZ=Europe/Berlin "$LAEUFER" pruefungen/test.js
python3 pruefungen/erzeuge_lotus.py 30000 "$LASTDATEI"
TZ=Europe/Berlin python3 pruefungen/last_test.py "$LASTDATEI"
TZ=Europe/Berlin "$LAEUFER" pruefungen/last_test.js

debian/rules clean
epoch=$(dpkg-parsechangelog -STimestamp)
find . -exec touch -h -d "@$epoch" {} +
DEB_BUILD_OPTIONS=nocheck DISPLAY= WAYLAND_DISPLAY= TZ=Europe/Berlin \
SOURCE_DATE_EPOCH=$epoch dpkg-buildpackage -b -d -us -uc

DEB="$STAGE/magnolie-organizer_${FASSUNG}_all.deb"
DSC="$STAGE/magnolie-organizer_${FASSUNG}.dsc"
SOURCE_TAR="$STAGE/magnolie-organizer_${FASSUNG}.tar.xz"
APPIMAGE="$STAGE/Magnolie-Organizer-$FASSUNG-x86_64.AppImage"
FLATPAK="$STAGE/Magnolie-Organizer-$FASSUNG-x86_64.flatpak"
HANDBUCH_DEB="$STAGE/magnolie-handbuch_${FASSUNG}_all.deb"
HANDBUCH_DSC="$STAGE/magnolie-handbuch_${FASSUNG}.dsc"
HANDBUCH_SOURCE_TAR="$STAGE/magnolie-handbuch_${FASSUNG}.tar.xz"
test -s "$DEB"

DEB_VERGLEICH=$(mktemp "$STAGE/deb-compare.XXXXXX")
cp "$DEB" "$DEB_VERGLEICH"
debian/rules clean
find . -exec touch -h -d "@$epoch" {} +
DEB_BUILD_OPTIONS=nocheck DISPLAY= WAYLAND_DISPLAY= TZ=Europe/Berlin \
SOURCE_DATE_EPOCH=$epoch dpkg-buildpackage -b -d -us -uc
cmp "$DEB_VERGLEICH" "$DEB" || {
    printf '%s\n' 'Debian-Paket ist nicht reproduzierbar:' >&2
    sha256sum "$DEB_VERGLEICH" "$DEB" >&2
    exit 1
}
rm -f "$DEB_VERGLEICH"

PAKET_TEST=$(mktemp -d "$STAGE/package-test.XXXXXX")
dpkg-deb -x "$DEB" "$PAKET_TEST"
test "$(cat "$PAKET_TEST/usr/share/magnolie-organizer/build-config.json")" = \
    "{\"contributorHash\":\"$MAGNOLIE_CONTRIBUTOR_HASH\"}"
xvfb-run -a -s "-screen 0 1280x800x24" env \
    MAGNOLIE_TEST_PROGRAMM="$PAKET_TEST/usr/bin/magnolie-organizer" \
    MAGNOLIE_TEST_WEB="$PAKET_TEST/usr/share/magnolie-organizer/web" \
    python3 debian/tests/gtk-webkit.py
rm -rf "$PAKET_TEST"

cd "$STAGE/magnolie-handbuch-stamm"
handbuch_epoch=$(dpkg-parsechangelog -STimestamp)
debian/rules clean
find . -exec touch -h -d "@$handbuch_epoch" {} +
DEB_BUILD_OPTIONS=nocheck SOURCE_DATE_EPOCH=$handbuch_epoch \
    dpkg-buildpackage -b -d -us -uc
HANDBUCH_VERGLEICH=$(mktemp "$STAGE/handbook-deb-compare.XXXXXX")
cp "$HANDBUCH_DEB" "$HANDBUCH_VERGLEICH"
debian/rules clean
find . -exec touch -h -d "@$handbuch_epoch" {} +
DEB_BUILD_OPTIONS=nocheck SOURCE_DATE_EPOCH=$handbuch_epoch \
    dpkg-buildpackage -b -d -us -uc
cmp "$HANDBUCH_VERGLEICH" "$HANDBUCH_DEB" || {
    printf '%s\n' 'Handbuch-Debian-Paket ist nicht reproduzierbar:' >&2
    sha256sum "$HANDBUCH_VERGLEICH" "$HANDBUCH_DEB" >&2
    exit 1
}
rm -f "$HANDBUCH_VERGLEICH"
debian/rules clean
find . -exec touch -h -d "@$handbuch_epoch" {} +
DEB_BUILD_OPTIONS=nocheck SOURCE_DATE_EPOCH=$handbuch_epoch \
    dpkg-buildpackage -S -d -us -uc
for datei in "$HANDBUCH_DEB" "$HANDBUCH_DSC" "$HANDBUCH_SOURCE_TAR"; do
    test -s "$datei"
done
"$LAEUFER" pruefungen/paket_inhalt_test.js "$HANDBUCH_DEB" "$HANDBUCH_SOURCE_TAR"
python3 - "$DEB" "$HANDBUCH_DEB" <<'PY'
import pathlib
import subprocess
import sys
import tempfile

def package_files(package, destination):
    subprocess.run(["dpkg-deb", "-x", package, destination], check=True)
    root = pathlib.Path(destination)
    return {str(path.relative_to(root)) for path in root.rglob("*")
            if not path.is_dir()}

with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    organizer = package_files(sys.argv[1], root / "organizer")
    handbook = package_files(sys.argv[2], root / "handbook")
    overlap = organizer & handbook
    if overlap:
        raise SystemExit("Debian-Pakete enthalten gemeinsame Pfade: " +
                         ", ".join(sorted(overlap)))
    if "usr/bin/magnolie_crash.py" not in organizer:
        raise SystemExit("Organizer-Crash-Reporter fehlt im Debian-Paket")
    if "usr/lib/magnolie-handbuch/magnolie_crash.py" not in handbook:
        raise SystemExit("Privater Handbuch-Crash-Reporter fehlt im Debian-Paket")
PY
sh "$WURZEL/pruefungen/test_debian_koinstallation.sh" \
    "$DEB" "$HANDBUCH_DEB" \
    "$LIVE_ROOT/magnolie-organizer_2.0.14_all.deb" \
    "$LIVE_ROOT/magnolie-handbuch_2.0.14_all.deb"
cd "$WURZEL"

SOURCE_DATE_EPOCH=$epoch werkzeuge/appimage_jammy_bauen.sh "$APPIMAGE"
pruefungen/test_appimage.sh "$APPIMAGE"
pruefungen/test_appimage_arch.sh "$APPIMAGE"
APPIMAGE_VERGLEICH=$(mktemp "$STAGE/appimage-compare.XXXXXX")
cp "$APPIMAGE" "$APPIMAGE_VERGLEICH"
SOURCE_DATE_EPOCH=$epoch werkzeuge/appimage_jammy_bauen.sh "$APPIMAGE"
cmp -s "$APPIMAGE_VERGLEICH" "$APPIMAGE"
rm -f "$APPIMAGE_VERGLEICH"

SOURCE_DATE_EPOCH=$epoch werkzeuge/flatpak_bauen.sh "$FLATPAK"
python3 pruefungen/test_flatpak.py "$FLATPAK"
FLATPAK_VERGLEICH=$(mktemp "$STAGE/flatpak-compare.XXXXXX")
cp "$FLATPAK" "$FLATPAK_VERGLEICH"
SOURCE_DATE_EPOCH=$epoch werkzeuge/flatpak_bauen.sh "$FLATPAK"
python3 pruefungen/test_flatpak.py "$FLATPAK_VERGLEICH" "$FLATPAK"
rm -f "$FLATPAK_VERGLEICH"

python3 werkzeuge/release_manifest.py --allow-unsigned \
    "$DEB" "$APPIMAGE" "$HANDBUCH_DEB" "$WINDOWS_INSTALLER" \
    "$WURZEL/update.xml" "$STAGE/update.xml"
python3 werkzeuge/update_signieren.py \
    "$MAGNOLIE_UPDATE_SIGNING_KEY" "$WURZEL/update.xml" "$DEB" "$APPIMAGE"
python3 werkzeuge/update_signieren.py \
    "$MAGNOLIE_UPDATE_SIGNING_KEY" "$STAGE/update.xml" "$DEB" "$APPIMAGE"
cmp "$WURZEL/update.xml" "$STAGE/update.xml"
python3 werkzeuge/update_signieren.py --verify "$UPDATE_SIGNATUR_SCHLUESSEL" \
    "$WURZEL/update.xml" "$DEB" "$APPIMAGE"
python3 werkzeuge/update_signieren.py --verify "$UPDATE_SIGNATUR_SCHLUESSEL" \
    "$STAGE/update.xml" "$DEB" "$APPIMAGE"
rm -f Magnolie-Organizer-PRUEFSUMMEN.sha256
debian/rules clean
find . -exec touch -h -d "@$epoch" {} +
DEB_BUILD_OPTIONS=nocheck SOURCE_DATE_EPOCH=$epoch \
    dpkg-buildpackage -S -d -us -uc
for datei in "$DSC" "$SOURCE_TAR"; do test -s "$datei"; done
python3 - "$DEB" "$APPIMAGE" "$HANDBUCH_DEB" "$WINDOWS_INSTALLER" \
    "$WURZEL/update.xml" <<'PY'
import hashlib
import pathlib
import sys
import xml.etree.ElementTree as ET

deb, appimage, handbuch, windows, manifest = map(pathlib.Path, sys.argv[1:])
root = ET.parse(manifest).getroot()
for artifact, xml_path in ((deb, "./sha256"),
                           (appimage, "./appimage/sha256"),
                           (handbuch, "./manual/linux/sha256"),
                           (windows, "./manual/windows/sha256"),
                           (windows, "./windows/sha256")):
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
    expected = (root.findtext(xml_path) or "").strip()
    if actual != expected:
        raise SystemExit("Manifest-Pruefsumme stimmt nicht: %s" % artifact)
PY
ARCHIV_MANIFEST=$(mktemp "$STAGE/source-manifest.XXXXXX")
tar -xOf "$SOURCE_TAR" \
    "$SOURCE_NAME/update.xml" > "$ARCHIV_MANIFEST"
cmp "$WURZEL/update.xml" "$ARCHIV_MANIFEST"
rm -f "$ARCHIV_MANIFEST"

pruefe_quellarchiv() {
    archiv=$1
    prefix=$2
    pflicht=${3:-"update.xml pruefungen/test_paketinhalt.py pruefungen/test_flatpak.py werkzeuge/png_pruefen.py werkzeuge/flatpak_bauen.sh flatpak/io.gitlab.maik3531.MagnolieOrganizer.json flatpak/python3-dependencies.json"}
    liste=$(mktemp "$STAGE/archive-list.XXXXXX")
    tar -tf "$archiv" > "$liste"
    for pfad in $pflicht; do
        grep -Fxq "$prefix/$pfad" "$liste"
    done
    ! grep -Eq '(^|/)Magnolie-Organizer-PRUEFSUMMEN[.]sha256$' "$liste"
    ! grep -Eq '(^|/)([.]git|[.]pytest_cache|[.]kotlin|[.]gradle|__pycache__|bau|build)(/|$)|[.](tar[.](xz|gz)|zip|rpm|deb|AppImage|flatpak)$' "$liste"
    ! grep -Ei '(^|/)(REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|[^/]*(ANALYSE|PLAN|AUDIT)[^/]*)[.]md$' "$liste"
    ! grep -Eq '(^|/)build-config[.]json$' "$liste"
    python3 - "$archiv" "$MAGNOLIE_CONTRIBUTOR_HASH" <<'PY'
import sys
import tarfile
import re

archive, contributor_hash = sys.argv[1:]
placeholder = "0" * 64
needle = None if contributor_hash == placeholder else contributor_hash.encode("ascii")
private_key = re.compile(
    rb"-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY)-----[\s\S]*?-----END \1-----")
key_file = re.compile(
    r"(?:^|[._-])(?:private[-_.]?key|release[-_.]?key|signing[-_.]?key)(?:[._-]|$)"
    r"|\.(?:key|pem|p12|pfx|secret|token)$|^\.env(?:\.|$)", re.I)
with tarfile.open(archive) as source:
    for member in source.getmembers():
        if key_file.search(member.name.rsplit("/", 1)[-1]):
            raise SystemExit("Quellarchiv enthaelt eine Schlüssel-/Secret-Datei: %s" % member.name)
        if not member.isfile():
            continue
        inhalt = source.extractfile(member).read()
        if needle is not None and needle in inhalt:
            raise SystemExit("Quellarchiv enthaelt den Contributor-Hash: %s" % member.name)
        if private_key.search(inhalt):
            raise SystemExit("Quellarchiv enthaelt einen privaten Schlüssel: %s" % member.name)
PY
    rm -f "$liste"
}
pruefe_quellarchiv "$SOURCE_TAR" "$SOURCE_NAME"
pruefe_quellarchiv "$HANDBUCH_SOURCE_TAR" "magnolie-handbuch-stamm" \
    "bin/magnolie-handbuch web/handbuch.js debian/control"

RPM_PAKET=
RPM_QUELLE=
HANDBUCH_RPM_PAKET=
HANDBUCH_RPM_QUELLE=
if [ "$AUTOPKGTESTS" -eq 1 ]; then
    command -v autopkgtest >/dev/null 2>&1 || {
        printf '%s\n' 'autopkgtest fehlt; Freigabe abgebrochen.' >&2; exit 1;
    }
    test -n "${MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE:-}" || {
        printf '%s\n' 'MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE fehlt; Freigabe abgebrochen.' >&2; exit 1;
    }
    autopkgtest "$DSC" -- qemu "$MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE"
else
    printf '%s\n' \
        'WARNUNG: externes QEMU-autopkgtest uebersprungen; diese Einschraenkung muss in den Release-Hinweisen stehen.' >&2
fi

if [ "$FEDORA_TESTS" -eq 1 ]; then
    test "$(dpkg-parsechangelog -l"$STAGE/magnolie-handbuch-stamm/debian/changelog" -SVersion)" = \
        "$FASSUNG" || {
        printf '%s\n' 'Organizer und Handbuch haben unterschiedliche Versionen.' >&2
        exit 1
    }
    RPM_FEDORA_DIR="$STAGE/rpm-fedora" \
        werkzeuge/rpm_fedora_bauen.sh

    set -- "$STAGE"/rpm-fedora/rpm/fedora/RPMS/noarch/magnolie-organizer-"$FASSUNG"-*.noarch.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein binaeres Organizer-RPM wurde erwartet.' >&2; exit 1;
    }
    RPM_PAKET="$WURZEL/bau/rpm/fedora/RPMS/noarch/$(basename "$1")"
    mkdir -p "$(dirname "$RPM_PAKET")"
    cp "$1" "$RPM_PAKET"
    set -- "$STAGE"/rpm-fedora/rpm/fedora/SRPMS/magnolie-organizer-"$FASSUNG"-*.src.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein Organizer-SRPM wurde erwartet.' >&2; exit 1;
    }
    RPM_QUELLE="$WURZEL/bau/rpm/fedora/SRPMS/$(basename "$1")"
    mkdir -p "$(dirname "$RPM_QUELLE")"
    cp "$1" "$RPM_QUELLE"
    pruefe_quellarchiv "$STAGE/rpm-fedora/rpm/fedora/SOURCES/magnolie-organizer-$FASSUNG.tar.xz" \
        "magnolie-organizer-$FASSUNG"

    set -- "$STAGE"/rpm-fedora/handbuch-rpm/fedora/RPMS/noarch/magnolie-handbuch-"$FASSUNG"-*.noarch.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein binaeres Handbuch-RPM wurde erwartet.' >&2; exit 1;
    }
    HANDBUCH_RPM_PAKET="$STAGE/magnolie-handbuch-stamm/bau/rpm/fedora/RPMS/noarch/$(basename "$1")"
    mkdir -p "$(dirname "$HANDBUCH_RPM_PAKET")"
    cp "$1" "$HANDBUCH_RPM_PAKET"
    set -- "$STAGE"/rpm-fedora/handbuch-rpm/fedora/SRPMS/magnolie-handbuch-"$FASSUNG"-*.src.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein Handbuch-SRPM wurde erwartet.' >&2; exit 1;
    }
    HANDBUCH_RPM_QUELLE="$STAGE/magnolie-handbuch-stamm/bau/rpm/fedora/SRPMS/$(basename "$1")"
    mkdir -p "$(dirname "$HANDBUCH_RPM_QUELLE")"
    cp "$1" "$HANDBUCH_RPM_QUELLE"
    pruefe_quellarchiv \
        "$STAGE/rpm-fedora/handbuch-rpm/fedora/SOURCES/magnolie-handbuch-$FASSUNG.tar.xz" \
        "magnolie-handbuch-$FASSUNG" \
        "bin/magnolie-handbuch web/handbuch.js rpm/magnolie-handbuch.spec"
else
    printf '%s\n' \
        'WARNUNG: Fedora-Bau und -Installationstest ausdruecklich uebersprungen; dieser Bau darf nicht veroeffentlicht werden.' >&2
fi

PRUEFSUMMEN="$WURZEL/Magnolie-Organizer-PRUEFSUMMEN.sha256"
set -- "../magnolie-organizer_${FASSUNG}_all.deb" \
    "../magnolie-organizer_${FASSUNG}.tar.xz" \
    "../Magnolie-Organizer-$FASSUNG-x86_64.AppImage" \
    "../Magnolie-Organizer-$FASSUNG-x86_64.flatpak" \
    "../magnolie-handbuch_${FASSUNG}_all.deb" \
    "../magnolie-handbuch_${FASSUNG}.tar.xz"
if [ -n "$RPM_PAKET" ]; then
    set -- "$@" "${RPM_PAKET#"$WURZEL/"}" "${RPM_QUELLE#"$WURZEL/"}" \
        "../magnolie-handbuch-stamm/${HANDBUCH_RPM_PAKET#"$STAGE/magnolie-handbuch-stamm/"}" \
        "../magnolie-handbuch-stamm/${HANDBUCH_RPM_QUELLE#"$STAGE/magnolie-handbuch-stamm/"}"
fi
(cd "$WURZEL" && sha256sum "$@") > "$PRUEFSUMMEN"
(cd "$WURZEL" && sha256sum -c "$PRUEFSUMMEN")

PUBLISH_PATHS="magnolie-organizer_${FASSUNG}_all.deb
magnolie-organizer_${FASSUNG}.dsc
magnolie-organizer_${FASSUNG}.tar.xz
magnolie-handbuch_${FASSUNG}_all.deb
magnolie-handbuch_${FASSUNG}.dsc
magnolie-handbuch_${FASSUNG}.tar.xz
Magnolie-Organizer-$FASSUNG-x86_64.AppImage
Magnolie-Organizer-$FASSUNG-x86_64.flatpak"
if [ -n "$RPM_PAKET" ]; then
    if [ "$LIVE_SOURCE_NAME" != "$SOURCE_NAME" ]; then
        mkdir -p "$STAGE/$LIVE_SOURCE_NAME/bau/rpm/fedora/RPMS/noarch" \
            "$STAGE/$LIVE_SOURCE_NAME/bau/rpm/fedora/SRPMS"
        cp "$RPM_PAKET" "$STAGE/$LIVE_SOURCE_NAME/${RPM_PAKET#"$WURZEL/"}"
        cp "$RPM_QUELLE" "$STAGE/$LIVE_SOURCE_NAME/${RPM_QUELLE#"$WURZEL/"}"
    fi
    PUBLISH_PATHS="$PUBLISH_PATHS
$LIVE_SOURCE_NAME/${RPM_PAKET#"$WURZEL/"}
$LIVE_SOURCE_NAME/${RPM_QUELLE#"$WURZEL/"}
magnolie-handbuch-stamm/${HANDBUCH_RPM_PAKET#"$STAGE/magnolie-handbuch-stamm/"}
magnolie-handbuch-stamm/${HANDBUCH_RPM_QUELLE#"$STAGE/magnolie-handbuch-stamm/"}"
fi
if [ "$LIVE_SOURCE_NAME" != "$SOURCE_NAME" ]; then
    mkdir -p "$STAGE/$LIVE_SOURCE_NAME"
    cp "$WURZEL/update.xml" "$STAGE/$LIVE_SOURCE_NAME/update.xml"
    cp "$PRUEFSUMMEN" "$STAGE/$LIVE_SOURCE_NAME/Magnolie-Organizer-PRUEFSUMMEN.sha256"
fi
PUBLISH_PATHS="$PUBLISH_PATHS
$LIVE_SOURCE_NAME/update.xml
$LIVE_SOURCE_NAME/Magnolie-Organizer-PRUEFSUMMEN.sha256
update.xml"
for rel in $PUBLISH_PATHS; do chmod 0644 "$STAGE/$rel"; done
chmod 0755 "$APPIMAGE"

# The checksum and update metadata are committed last, so consumers following
# them see one coherent group. Direct artifact readers can still observe a
# replacement; avoiding that would require versioned directory indirection.
VEROEFFENTLICHEN=1
for rel in $PUBLISH_PATHS; do
    ziel="$LIVE_ROOT/$rel"
    sicherung="$BACKUP/$rel"
    marker="$BACKUP/.moved/$rel"
    mkdir -p "$(dirname "$sicherung")" "$(dirname "$marker")" "$(dirname "$ziel")"
    if [ -e "$ziel" ]; then mv "$ziel" "$sicherung"; fi
    : > "$marker"
    mv "$STAGE/$rel" "$ziel"
done
sync
VEROEFFENTLICHEN=0
