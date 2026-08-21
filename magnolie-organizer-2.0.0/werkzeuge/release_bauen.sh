#!/bin/sh
set -eu

SYSTEM_PAKETTESTS=1
case "${1:-}" in
    "") ;;
    --skip-system-package-tests) SYSTEM_PAKETTESTS=0 ;;
    *) printf 'Aufruf: %s [--skip-system-package-tests]\n' "$0" >&2; exit 2 ;;
esac

LIVE_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LIVE_ROOT=$(dirname "$LIVE_SOURCE")
UPDATE_SIGNATUR_SCHLUESSEL='8eJWsygSF9wsF22cuf+sChUUV5RtXEZt38Ngcugn/1Y='
MAGNOLIE_UPDATE_SIGNING_KEY=${MAGNOLIE_UPDATE_SIGNING_KEY:-${HOME:-}/.local/share/magnolie-release/update-ed25519.pem}
python3 "$LIVE_SOURCE/werkzeuge/update_signieren.py" --check-key \
    "$MAGNOLIE_UPDATE_SIGNING_KEY" "$UPDATE_SIGNATUR_SCHLUESSEL"
FASSUNG=$(dpkg-parsechangelog -l"$LIVE_SOURCE/debian/changelog" -SVersion)
SOURCE_NAME="magnolie-organizer-$FASSUNG"
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

cp -a "$LIVE_SOURCE" "$WURZEL"
cp "$LIVE_ROOT/update.xml" "$STAGE/update.xml"
rm -rf "$WURZEL/.git" "$WURZEL/bau" "$WURZEL/.pytest_cache" "$WURZEL/.kotlin" \
    "$WURZEL/.gradle" "$WURZEL/build"
find "$WURZEL" -type d \( -name __pycache__ -o -name .pytest_cache \
    -o -name .kotlin -o -name .gradle \) -prune -exec rm -rf {} +

cd "$WURZEL"
debian/rules build
python3 -m pytest -q pruefungen/test_locale_completeness.py
DISPLAY= WAYLAND_DISPLAY= XDG_DATA_HOME="$STAGE/test-data" \
XDG_CONFIG_HOME="$STAGE/test-config" TZ=Europe/Berlin \
    python3 pruefungen/test_parser.py
python3 -m pytest -q pruefungen/test_kdeconnect.py
python3 -m pytest -q pruefungen/test_personal_sync.py
TZ=Europe/Berlin python3 pruefungen/test_import_export_vertrag.py
TZ=Europe/Berlin python3 pruefungen/test_gesamtarchiv.py
TZ=Europe/Berlin python3 pruefungen/test_telefon.py
TZ=Europe/Berlin python3 pruefungen/test_eds_adressbuch_sync.py
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

SOURCE_DATE_EPOCH=$epoch werkzeuge/appimage_bauen.sh "$APPIMAGE"
pruefungen/test_appimage.sh "$APPIMAGE"
APPIMAGE_VERGLEICH=$(mktemp "$STAGE/appimage-compare.XXXXXX")
cp "$APPIMAGE" "$APPIMAGE_VERGLEICH"
SOURCE_DATE_EPOCH=$epoch werkzeuge/appimage_bauen.sh "$APPIMAGE"
cmp -s "$APPIMAGE_VERGLEICH" "$APPIMAGE"
rm -f "$APPIMAGE_VERGLEICH"

python3 werkzeuge/release_manifest.py \
    "$DEB" "$APPIMAGE" "$WURZEL/update.xml" "$STAGE/update.xml"
python3 werkzeuge/update_signieren.py \
    "$MAGNOLIE_UPDATE_SIGNING_KEY" "$WURZEL/update.xml" "$DEB" "$APPIMAGE"
python3 werkzeuge/update_signieren.py \
    "$MAGNOLIE_UPDATE_SIGNING_KEY" "$STAGE/update.xml" "$DEB" "$APPIMAGE"
cmp "$WURZEL/update.xml" "$STAGE/update.xml"
python3 werkzeuge/update_signieren.py --verify "$UPDATE_SIGNATUR_SCHLUESSEL" \
    "$WURZEL/update.xml" "$DEB" "$APPIMAGE"
python3 werkzeuge/update_signieren.py --verify "$UPDATE_SIGNATUR_SCHLUESSEL" \
    "$STAGE/update.xml" "$DEB" "$APPIMAGE"
debian/rules clean
find . -exec touch -h -d "@$epoch" {} +
DEB_BUILD_OPTIONS=nocheck SOURCE_DATE_EPOCH=$epoch \
    dpkg-buildpackage -S -d -us -uc
for datei in "$DSC" "$SOURCE_TAR"; do test -s "$datei"; done
python3 - "$DEB" "$APPIMAGE" "$WURZEL/update.xml" <<'PY'
import hashlib
import pathlib
import sys
import xml.etree.ElementTree as ET

deb, appimage, manifest = map(pathlib.Path, sys.argv[1:])
root = ET.parse(manifest).getroot()
for artifact, xml_path in ((deb, "./sha256"),
                           (appimage, "./appimage/sha256")):
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
    liste=$(mktemp "$STAGE/archive-list.XXXXXX")
    tar -tf "$archiv" > "$liste"
    for pfad in update.xml pruefungen/test_paketinhalt.py werkzeuge/png_pruefen.py; do
        grep -Fxq "$prefix/$pfad" "$liste"
    done
    ! grep -Eq '(^|/)([.]git|[.]pytest_cache|[.]kotlin|[.]gradle|__pycache__|bau|build)(/|$)|[.](tar[.](xz|gz)|zip|rpm|deb|AppImage)$' "$liste"
    ! grep -Ei '(^|/)(REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|[^/]*(ANALYSE|PLAN|AUDIT)[^/]*)[.]md$' "$liste"
    ! grep -Eq '(^|/)build-config[.]json$' "$liste"
    python3 - "$archiv" "$MAGNOLIE_CONTRIBUTOR_HASH" <<'PY'
import sys
import tarfile
import re

archive, contributor_hash = sys.argv[1:]
needle = contributor_hash.encode("ascii")
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
        if needle in inhalt:
            raise SystemExit("Quellarchiv enthaelt den Contributor-Hash: %s" % member.name)
        if private_key.search(inhalt):
            raise SystemExit("Quellarchiv enthaelt einen privaten Schlüssel: %s" % member.name)
PY
    rm -f "$liste"
}
pruefe_quellarchiv "$SOURCE_TAR" "$SOURCE_NAME"

RPM_PAKET=
RPM_QUELLE=
if [ "$SYSTEM_PAKETTESTS" -eq 1 ]; then
    command -v autopkgtest >/dev/null 2>&1 || {
        printf '%s\n' 'autopkgtest fehlt; Freigabe abgebrochen.' >&2; exit 1;
    }
    test -n "${MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE:-}" || {
        printf '%s\n' 'MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE fehlt; Freigabe abgebrochen.' >&2; exit 1;
    }
    autopkgtest "$DSC" -- qemu "$MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE"

    command -v rpmbuild >/dev/null 2>&1 || {
        printf '%s\n' 'rpmbuild fehlt; SRPM konnte nicht erzeugt werden.' >&2; exit 1;
    }
    command -v mock >/dev/null 2>&1 || {
        printf '%s\n' 'mock fehlt; Fedora-Installationstest nicht gelaufen.' >&2; exit 1;
    }
    werkzeuge/rpm_bauen.sh --source-only
    set -- "$WURZEL"/bau/rpm/SRPMS/magnolie-organizer-"$FASSUNG"-*.src.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein SRPM wurde erwartet.' >&2; exit 1;
    }
    RPM_QUELLE=$1
    pruefe_quellarchiv "$WURZEL/bau/rpm/SOURCES/magnolie-organizer-$FASSUNG.tar.xz" \
        "magnolie-organizer-$FASSUNG"
    MOCK_KONFIG=${MAGNOLIE_MOCK_CONFIG:-fedora-42-x86_64}
    MOCK_RESULT="$STAGE/mock-result"
    if [ -f "$MOCK_KONFIG" ]; then
        MOCK_BASIS=$(readlink -f "$MOCK_KONFIG")
    elif [ -f "${HOME:-}/.config/mock/$MOCK_KONFIG.cfg" ]; then
        MOCK_BASIS=$(readlink -f "${HOME}/.config/mock/$MOCK_KONFIG.cfg")
    elif [ -f "/etc/mock/$MOCK_KONFIG.cfg" ]; then
        MOCK_BASIS="/etc/mock/$MOCK_KONFIG.cfg"
    else
        printf '%s\n' "Mock-Konfiguration nicht gefunden: $MOCK_KONFIG" >&2
        exit 1
    fi
    MOCK_BRANDING="$STAGE/mock-branding.cfg"
    python3 - "$MOCK_BASIS" "$MOCK_BRANDING" "$MAGNOLIE_CONTRIBUTOR_HASH" <<'PY'
import pathlib
import sys

source, destination, contributor_hash = sys.argv[1:]
pathlib.Path(destination).write_text(
    "include(%r)\nconfig_opts['environment']['MAGNOLIE_CONTRIBUTOR_HASH'] = %r\n"
    % (source, contributor_hash), encoding="ascii")
PY
    mkdir "$MOCK_RESULT"
    mock -r "$MOCK_KONFIG" --clean
    mock -r "$MOCK_BRANDING" \
        --rebuild "$RPM_QUELLE" --resultdir "$MOCK_RESULT"
    set -- "$MOCK_RESULT"/magnolie-organizer-"$FASSUNG"-*.noarch.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein durch mock gebautes binaeres RPM wurde erwartet.' >&2; exit 1;
    }
    RPM_PAKET="$WURZEL/bau/rpm/RPMS/noarch/$(basename "$1")"
    mkdir -p "$(dirname "$RPM_PAKET")"
    cp "$1" "$RPM_PAKET"
    test "$(rpm -qpl "$RPM_PAKET" | grep -c '/build-config[.]json$')" -eq 1
    test "$(rpm2cpio "$RPM_PAKET" | cpio -i --to-stdout \
        ./usr/share/magnolie-organizer/build-config.json 2>/dev/null)" = \
        "{\"contributorHash\":\"$MAGNOLIE_CONTRIBUTOR_HASH\"}"
    mock -r "$MOCK_KONFIG" --install "$RPM_PAKET"
    mock -r "$MOCK_KONFIG" --chroot -- rpm -V magnolie-organizer
    mock -r "$MOCK_KONFIG" --chroot -- \
        env DISPLAY= WAYLAND_DISPLAY= magnolie-organizer --help
else
    printf '%s\n' \
        'WARNUNG: vollstaendiges autopkgtest und Fedora-Installationstest ausdruecklich uebersprungen.' >&2
fi

PRUEFSUMMEN="$WURZEL/Magnolie-Organizer-PRUEFSUMMEN.sha256"
set -- "../magnolie-organizer_${FASSUNG}_all.deb" \
    "../magnolie-organizer_${FASSUNG}.tar.xz" \
    "../Magnolie-Organizer-$FASSUNG-x86_64.AppImage"
if [ -n "$RPM_PAKET" ]; then
    set -- "$@" "${RPM_PAKET#"$WURZEL/"}" "${RPM_QUELLE#"$WURZEL/"}"
fi
(cd "$WURZEL" && sha256sum "$@") > "$PRUEFSUMMEN"
(cd "$WURZEL" && sha256sum -c "$PRUEFSUMMEN")

PUBLISH_PATHS="magnolie-organizer_${FASSUNG}_all.deb
magnolie-organizer_${FASSUNG}.dsc
magnolie-organizer_${FASSUNG}.tar.xz
Magnolie-Organizer-$FASSUNG-x86_64.AppImage"
if [ -n "$RPM_PAKET" ]; then
    PUBLISH_PATHS="$PUBLISH_PATHS
$SOURCE_NAME/${RPM_PAKET#"$WURZEL/"}
$SOURCE_NAME/${RPM_QUELLE#"$WURZEL/"}"
fi
PUBLISH_PATHS="$PUBLISH_PATHS
$SOURCE_NAME/update.xml
$SOURCE_NAME/Magnolie-Organizer-PRUEFSUMMEN.sha256
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
