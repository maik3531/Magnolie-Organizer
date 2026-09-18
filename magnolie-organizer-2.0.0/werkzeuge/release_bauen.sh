#!/bin/sh
set -eu

LIVE_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LIVE_ROOT=$(dirname "$LIVE_SOURCE")
python3 "$LIVE_ROOT/tools/sync_mobile_downloads.py" --check
if [ "${1:-}" = --promote ]; then
    [ "$#" -eq 4 ] || { printf '%s\n' 'Usage: release_bauen.sh --promote CANDIDATE APPROVAL ACCEPTED_CANDIDATE_SHA256' >&2; exit 2; }
    exec python3 "$LIVE_SOURCE/werkzeuge/release_gate.py" promote --root "$LIVE_ROOT" \
        --candidate "$2" --approval "$3" --accept-candidate "$4"
fi
AUTOPKGTESTS=1
FEDORA_TESTS=1
case "${1:-}" in
    "") ;;
    --skip-autopkgtest) AUTOPKGTESTS=0 ;;
    --skip-system-package-tests) AUTOPKGTESTS=0; FEDORA_TESTS=0 ;;
    *) printf 'Aufruf: %s [--skip-autopkgtest|--skip-system-package-tests]\n' "$0" >&2; exit 2 ;;
esac

LIVE_HANDBUCH="$LIVE_ROOT/magnolie-handbuch-stamm"
python3 "$LIVE_SOURCE/werkzeuge/release_gate.py" bootstrap --root "$LIVE_ROOT"
python3 -B -m pytest -q "$LIVE_ROOT/tools/test_prepare_notes_alias.py"
[ -z "${MAGNOLIE_SHLIBS_LOCAL:-}" ] || {
    printf '%s\n' 'Release candidates reject MAGNOLIE_SHLIBS_LOCAL; use package-managed dependencies.' >&2
    exit 2
}
FASSUNG=$(dpkg-parsechangelog -l"$LIVE_SOURCE/debian/changelog" -SVersion)
organizer_epoch=$(dpkg-parsechangelog -l"$LIVE_SOURCE/debian/changelog" -STimestamp)
handbuch_epoch_live=$(dpkg-parsechangelog -l"$LIVE_HANDBUCH/debian/changelog" -STimestamp)
jetzt=$(date +%s)
[ "$organizer_epoch" -le "$jetzt" ] && [ "$handbuch_epoch_live" -le "$jetzt" ] || {
    printf '%s\n' 'Ein Release-Changelog-Zeitstempel liegt in der Zukunft.' >&2
    exit 1
}
SOURCE_NAME="magnolie-organizer-$FASSUNG"
AKONADI_VERSION=$(dpkg-parsechangelog \
    -l"$LIVE_SOURCE/native/akonadi-helper/debian/changelog" -SVersion)
[ "$AKONADI_VERSION" = "$FASSUNG" ] || {
    printf '%s\n' 'Akonadi-Helfer und Organizer haben unterschiedliche Versionen.' >&2; exit 1;
}
LIVE_SOURCE_NAME=$(basename "$LIVE_SOURCE")
LIVE_WINDOWS=${MAGNOLIE_WINDOWS_ROOT:-"$LIVE_ROOT/Magnolie-Organizer-Windows-2.0.0"}
WINDOWS_INPUT=${MAGNOLIE_WINDOWS_ARTIFACTS:-"$LIVE_WINDOWS"}
WINDOWS_INSTALLER="$WINDOWS_INPUT/Magnolie-Organizer-Windows-$FASSUNG-Setup-x64.exe"
WINDOWS_ZIP="$WINDOWS_INPUT/Magnolie-Organizer-Windows-$FASSUNG-x64.zip"
WINDOWS_PRUEFSUMMEN="$WINDOWS_INPUT/Magnolie-Organizer-Windows-$FASSUNG-PRUEFSUMMEN.sha256"
WINDOWS_BUILDRECORD="$WINDOWS_INSTALLER.build.json"
WINDOWS_SOURCE="$WINDOWS_INPUT/Magnolie-Organizer-Windows-$FASSUNG-Source.zip"
WINDOWS_PROVENANCE="$WINDOWS_INPUT/Magnolie-Organizer-Windows-$FASSUNG-provenance.json"
VEROEFFENTLICHTE_FASSUNG=$(python3 - "$LIVE_ROOT/update.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET

print((ET.parse(sys.argv[1]).getroot().findtext("version") or "").strip())
PY
)
ALTER_ORGANIZER="$LIVE_ROOT/magnolie-organizer_${VEROEFFENTLICHTE_FASSUNG}_all.deb"
ALTES_HANDBUCH="$LIVE_ROOT/magnolie-handbuch_${VEROEFFENTLICHTE_FASSUNG}_all.deb"
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
PWSH=${MAGNOLIE_PWSH:-/tmp/opencode/powershell-7.4.13/pwsh}
NOTES_INPUT=${MAGNOLIE_NOTES_ARTIFACTS:-"$LIVE_ROOT"}
python3 "$LIVE_SOURCE/werkzeuge/release_gate.py" notes-inputs --root "$LIVE_ROOT" --candidate "$NOTES_INPUT"
for datei in "$WINDOWS_INSTALLER" "$WINDOWS_BUILDRECORD" "$WINDOWS_SOURCE" "$WINDOWS_ZIP" "$WINDOWS_PRUEFSUMMEN" "$WINDOWS_PROVENANCE"; do
    test -s "$datei" || {
        printf '%s\n' "Windows-Freigabeartefakt fehlt: $datei" >&2
        exit 1
    }
done
for datei in "$ALTER_ORGANIZER" "$ALTES_HANDBUCH"; do
    test -s "$datei" || {
        printf '%s\n' "Vorgaengerpaket fuer den Upgrade-Test fehlt: $datei" >&2
        exit 1
    }
done
(cd "$WINDOWS_INPUT" && sha256sum -c "$(basename "$WINDOWS_PRUEFSUMMEN")")
"$PWSH" -NoProfile -File "$LIVE_WINDOWS/build/AssertCandidate.ps1" \
    -Root "$LIVE_WINDOWS" -Directory "$WINDOWS_INPUT"
if command -v unzip >/dev/null 2>&1 && \
        unzip -Z1 "$WINDOWS_ZIP" | grep -Fxq 'WINDOWS-RUNTIME-UNVERIFIED.txt'; then
    printf '%s\n' \
        'Windows transport candidate: native evidence and personal or delegated authorization remain mandatory.' >&2
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
STAGE=$(mktemp -d /tmp/opencode/magnolie-desktop-build.XXXXXX)
WURZEL="$STAGE/$SOURCE_NAME"
LASTDATEI="$STAGE/lotus-gross.csv"

cleanup() {
    status=$?
    trap - EXIT
    trap '' HUP INT TERM
    rm -rf "$STAGE"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

mkdir -p "$WURZEL" "$STAGE/magnolie-handbuch-stamm" "$STAGE/windows-release"
python3 "$LIVE_SOURCE/werkzeuge/release_sources.py" inventory "$LIVE_ROOT" > "$STAGE/source-record.json"
cp "$WINDOWS_INSTALLER" "$WINDOWS_BUILDRECORD" "$WINDOWS_ZIP" "$WINDOWS_PRUEFSUMMEN" "$WINDOWS_SOURCE" "$WINDOWS_PROVENANCE" \
    "$STAGE/windows-release/"
WINDOWS_INSTALLER="$STAGE/windows-release/$(basename "$WINDOWS_INSTALLER")"
WINDOWS_BUILDRECORD="$STAGE/windows-release/$(basename "$WINDOWS_BUILDRECORD")"
WINDOWS_ZIP="$STAGE/windows-release/$(basename "$WINDOWS_ZIP")"
WINDOWS_PRUEFSUMMEN="$STAGE/windows-release/$(basename "$WINDOWS_PRUEFSUMMEN")"
WINDOWS_SOURCE="$STAGE/windows-release/$(basename "$WINDOWS_SOURCE")"
WINDOWS_PROVENANCE="$STAGE/windows-release/$(basename "$WINDOWS_PROVENANCE")"
(cd "$STAGE/windows-release" && sha256sum -c "$(basename "$WINDOWS_PRUEFSUMMEN")")
python3 "$LIVE_SOURCE/werkzeuge/release_sources.py" copy "$LIVE_SOURCE" "$WURZEL"
python3 "$LIVE_SOURCE/werkzeuge/release_sources.py" copy "$LIVE_HANDBUCH" "$STAGE/magnolie-handbuch-stamm"
python3 "$LIVE_SOURCE/werkzeuge/release_sources.py" copy "$LIVE_ROOT/contracts" "$STAGE/contracts"
python3 "$WURZEL/werkzeuge/release_sources.py" contracts "$WURZEL"
python3 "$LIVE_SOURCE/werkzeuge/release_sources.py" verify-copy "$STAGE/source-record.json" "$STAGE/contracts" --component contracts
python3 "$LIVE_SOURCE/werkzeuge/release_sources.py" verify-copy "$STAGE/source-record.json" "$WURZEL" --component magnolie-organizer-2.0.0
python3 "$LIVE_SOURCE/werkzeuge/release_sources.py" verify-copy "$STAGE/source-record.json" "$STAGE/magnolie-handbuch-stamm" --component magnolie-handbuch-stamm
MAGNOLIE_LINUX_SOURCE="$WURZEL" "$LAEUFER" "$LIVE_WINDOWS/tests/linux-live-parity.js"
cp "$LIVE_ROOT/update.xml" "$STAGE/update.xml"
cp "$LIVE_ROOT/.gitignore" "$STAGE/"
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
find "$WURZEL/native/akonadi-helper" -type d \
    \( -name build -o -name bau -o -name 'obj-*' -o -name .debhelper \) \
    -prune -exec rm -rf {} +
rm -f "$WURZEL/native/akonadi-helper/debian/files" \
    "$WURZEL/native/akonadi-helper"/debian/*.substvars

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
    pruefungen/test_update_security.py pruefungen/test_thunderbird_contacts.py \
    pruefungen/test_release_packaging.py pruefungen/test_release_authorization.py pruefungen/test_notes_provenance.py pruefungen/test_feature_packaging.py \
    pruefungen/test_native_import_regressions.py
TZ=Europe/Berlin python3 -m pytest -q pruefungen/test_recurrence.py \
    pruefungen/test_recurrence_oracle.py pruefungen/test_recurrence_integration.py \
    pruefungen/test_recurrence_timezones.py pruefungen/test_runtime_packaging.py
  MAGNOLIE_VOLLPRUEFUNG=1 python3 -m pytest -q pruefungen/test_crash_reports.py pruefungen/test_setup_phone_failure.py pruefungen/test_weather_fallback.py
TZ=Europe/Berlin python3 -B pruefungen/run_background_reliability.py
TZ=Europe/Berlin python3 -B -m pytest -q pruefungen/test_letter_layout.py pruefungen/test_pot_source_coverage.py
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
python3 -I -B werkzeuge/runtime_pruefen.py "$PAKET_TEST/usr/bin"
test "$(cat "$PAKET_TEST/usr/share/magnolie-organizer/build-config.json")" = \
    "{\"contributorHash\":\"$MAGNOLIE_CONTRIBUTOR_HASH\"}"
xvfb-run -a -s "-screen 0 1280x800x24" env \
    MAGNOLIE_TEST_PROGRAMM="$PAKET_TEST/usr/bin/magnolie-organizer" \
    MAGNOLIE_TEST_WEB="$PAKET_TEST/usr/share/magnolie-organizer/web" \
    python3 debian/tests/gtk-webkit.py
rm -rf "$PAKET_TEST"

KDE_STAGE="$STAGE/kde-component"
python3 "$WURZEL/werkzeuge/kde_deb_bauen.py" "$KDE_STAGE"
cp "$KDE_STAGE/"* "$STAGE/"

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
    "$ALTER_ORGANIZER" "$ALTES_HANDBUCH"
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

# Source archives retain the last published bootstrap manifest. They must not
# change after native testing and personal or delegated authorization of the candidate bytes.
cmp "$WURZEL/update.xml" "$STAGE/update.xml"
rm -f Magnolie-Organizer-PRUEFSUMMEN.sha256
debian/rules clean
find native/akonadi-helper -type d -name 'obj-*' -prune -exec rm -rf {} +
rm -f native/akonadi-helper/debian/files \
    native/akonadi-helper/debian/*.substvars
find . -exec touch -h -d "@$epoch" {} +
DEB_BUILD_OPTIONS=nocheck SOURCE_DATE_EPOCH=$epoch \
    dpkg-buildpackage -S -d -us -uc
for datei in "$DSC" "$SOURCE_TAR"; do
    test -s "$datei" || {
        printf '%s\n' "Quellpaketartefakt fehlt: $datei" >&2
        exit 1
    }
done
ARCHIV_MANIFEST=$(mktemp "$STAGE/source-manifest.XXXXXX")
tar -xOf "$SOURCE_TAR" \
    "$SOURCE_NAME/update.xml" > "$ARCHIV_MANIFEST"
cmp "$WURZEL/update.xml" "$ARCHIV_MANIFEST"
rm -f "$ARCHIV_MANIFEST"

pruefe_quellarchiv() {
    archiv=$1
    prefix=$2
    pflicht=${3:-"update.xml contracts/thunderbird-addressbook-fixture.json pruefungen/test_thunderbird_contacts.py pruefungen/test_paketinhalt.py pruefungen/test_flatpak.py werkzeuge/png_pruefen.py werkzeuge/flatpak_bauen.sh flatpak/io.gitlab.maik3531.MagnolieOrganizer.json flatpak/python3-dependencies.json native/akonadi-helper/CMakeLists.txt native/akonadi-helper/main.cpp native/akonadi-helper/debian/control native/akonadi-helper/debian/source/format native/akonadi-helper/magnolie-organizer-kde.spec"}
    if [ "$#" -lt 3 ]; then
        pflicht="$pflicht werkzeuge/source_selection.py werkzeuge/desktop_pot_merge.py contracts/baum-1-receipt-v1-vectors.json contracts/baum-1-receipt-v1.md contracts/phone-bluetooth-first-pair.md contracts/phone-setup-daemon-lifecycle.md contracts/phone-wlan-invitation.md pruefungen/run_background_reliability.py pruefungen/background_cross_platform.py pruefungen/letter_cross_platform.py pruefungen/letter-layout/LetterProbe.csproj pruefungen/letter-layout/Program.cs pruefungen/letter-layout/web.js pruefungen/receipt-native/ReceiptProbe.csproj pruefungen/receipt-native/cross_receipt.py"
        pflicht="$pflicht bin/magnolie_recurrence.py contracts/recurrence-integration.json contracts/recurrence-timezones.json pruefungen/fixtures/recurrence-rfc-oracle.json pruefungen/test_recurrence.py pruefungen/test_recurrence_oracle.py pruefungen/test_recurrence_integration.py pruefungen/test_recurrence_timezones.py pruefungen/test_runtime_packaging.py pruefungen/recurrence_dateutil_oracle.py pruefungen/recurrence_cross_platform.py pruefungen/requirements-recurrence-oracle.txt werkzeuge/runtime_pruefen.py"
    fi
    liste=$(mktemp "$STAGE/archive-list.XXXXXX")
    tar -tf "$archiv" > "$liste"
    for pfad in $pflicht; do
        grep -Fxq "$prefix/$pfad" "$liste" || {
            printf '%s\n' "Pflichtdatei fehlt im Quellarchiv: $prefix/$pfad" >&2
            exit 1
        }
    done
    ! grep -Eq '(^|/)Magnolie-Organizer-PRUEFSUMMEN[.]sha256$' "$liste"
    ! grep -Eq '(^|/)([.]git|[.]pytest_cache|[.]kotlin|[.]gradle|__pycache__|bau|build|obj-[^/]*)(/|$)|(^|/)debian/(files|[^/]*[.]substvars)$|[.](tar[.](xz|gz)|zip|rpm|deb|AppImage|flatpak)$' "$liste"
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
pruefe_quellarchiv "$STAGE/magnolie-organizer-kde_${AKONADI_VERSION}.tar.xz" \
    "akonadi-helper" \
    "CMakeLists.txt main.cpp serialization-test.cpp build.py profiles.py launcher.py tests/test_launcher.py debian/rules debian/control debian/source/format magnolie-organizer-kde.spec"
pruefe_quellarchiv "$HANDBUCH_SOURCE_TAR" "magnolie-handbuch-stamm" \
    "bin/magnolie-handbuch web/handbuch.js debian/control"

RPM_PAKET=
RPM_QUELLE=
HANDBUCH_RPM_PAKET=
HANDBUCH_RPM_QUELLE=
AKONADI_RPM_PAKET=
AKONADI_RPM_QUELLE=
if [ "$AUTOPKGTESTS" -eq 1 ]; then
    command -v autopkgtest >/dev/null 2>&1 || {
        printf '%s\n' 'autopkgtest fehlt; Freigabe abgebrochen.' >&2; exit 1;
    }
    test -n "${MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE:-}" || {
        printf '%s\n' 'MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE fehlt; Freigabe abgebrochen.' >&2; exit 1;
    }
    autopkgtest -U "$DSC" -- qemu --cpus=2 --ram-size=4096 \
        --qemu-options='-cpu host' "$MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE"
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
    RPM_FEDORA_ARBEIT=${RPM_FEDORA_DIR:-"$STAGE/rpm-fedora"}
    RPM_FEDORA_DIR="$RPM_FEDORA_ARBEIT" \
        werkzeuge/rpm_fedora_bauen.sh

    set -- "$RPM_FEDORA_ARBEIT"/rpm/fedora/RPMS/noarch/magnolie-organizer-"$FASSUNG"-*.noarch.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein binaeres Organizer-RPM wurde erwartet.' >&2; exit 1;
    }
    RPM_PAKET="$WURZEL/bau/rpm/fedora/RPMS/noarch/$(basename "$1")"
    mkdir -p "$(dirname "$RPM_PAKET")"
    cp "$1" "$RPM_PAKET"
    set -- "$RPM_FEDORA_ARBEIT"/rpm/fedora/SRPMS/magnolie-organizer-"$FASSUNG"-*.src.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein Organizer-SRPM wurde erwartet.' >&2; exit 1;
    }
    RPM_QUELLE="$WURZEL/bau/rpm/fedora/SRPMS/$(basename "$1")"
    mkdir -p "$(dirname "$RPM_QUELLE")"
    cp "$1" "$RPM_QUELLE"
    pruefe_quellarchiv "$RPM_FEDORA_ARBEIT/rpm/fedora/SOURCES/magnolie-organizer-$FASSUNG.tar.xz" \
        "magnolie-organizer-$FASSUNG"

    set -- "$RPM_FEDORA_ARBEIT"/handbuch-rpm/fedora/RPMS/noarch/magnolie-handbuch-"$FASSUNG"-*.noarch.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein binaeres Handbuch-RPM wurde erwartet.' >&2; exit 1;
    }
    HANDBUCH_RPM_PAKET="$STAGE/magnolie-handbuch-stamm/bau/rpm/fedora/RPMS/noarch/$(basename "$1")"
    mkdir -p "$(dirname "$HANDBUCH_RPM_PAKET")"
    cp "$1" "$HANDBUCH_RPM_PAKET"
    set -- "$RPM_FEDORA_ARBEIT"/handbuch-rpm/fedora/SRPMS/magnolie-handbuch-"$FASSUNG"-*.src.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein Handbuch-SRPM wurde erwartet.' >&2; exit 1;
    }
    HANDBUCH_RPM_QUELLE="$STAGE/magnolie-handbuch-stamm/bau/rpm/fedora/SRPMS/$(basename "$1")"
    mkdir -p "$(dirname "$HANDBUCH_RPM_QUELLE")"
    cp "$1" "$HANDBUCH_RPM_QUELLE"
    pruefe_quellarchiv \
        "$RPM_FEDORA_ARBEIT/handbuch-rpm/fedora/SOURCES/magnolie-handbuch-$FASSUNG.tar.xz" \
        "magnolie-handbuch-$FASSUNG" \
        "bin/magnolie-handbuch web/handbuch.js rpm/magnolie-handbuch.spec"

    set -- "$RPM_FEDORA_ARBEIT"/akonadi-rpm/RPMS/*/magnolie-organizer-kde-"$AKONADI_VERSION"-*.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein binaeres Akonadi-Helfer-RPM wurde erwartet.' >&2; exit 1;
    }
    AKONADI_RPM_PAKET="$WURZEL/bau/rpm/fedora/RPMS/$(basename "$1")"
    mkdir -p "$(dirname "$AKONADI_RPM_PAKET")"
    cp "$1" "$AKONADI_RPM_PAKET"
    set -- "$RPM_FEDORA_ARBEIT"/akonadi-rpm/SRPMS/magnolie-organizer-kde-"$AKONADI_VERSION"-*.src.rpm
    [ "$#" -eq 1 ] && [ -f "$1" ] || {
        printf '%s\n' 'Genau ein Akonadi-Helfer-SRPM wurde erwartet.' >&2; exit 1;
    }
    AKONADI_RPM_QUELLE="$WURZEL/bau/rpm/fedora/SRPMS/$(basename "$1")"
    mkdir -p "$(dirname "$AKONADI_RPM_QUELLE")"
    cp "$1" "$AKONADI_RPM_QUELLE"
    pruefe_quellarchiv \
        "$RPM_FEDORA_ARBEIT/akonadi-rpm/SOURCES/magnolie-organizer-kde-$AKONADI_VERSION.tar.xz" \
        "magnolie-organizer-kde-$AKONADI_VERSION" \
        "CMakeLists.txt main.cpp debian/copyright magnolie-organizer-kde.spec"
else
    printf '%s\n' \
        'WARNUNG: Fedora-Bau und -Installationstest ausdruecklich uebersprungen; dieser Bau darf nicht veroeffentlicht werden.' >&2
fi

if [ "$FEDORA_TESTS" -ne 1 ]; then
    printf '%s\n' 'Diagnostic build completed without Fedora; no release candidate can be approved.' >&2
    exit 1
fi
CANDIDATE=$(mktemp -d /tmp/opencode/magnolie-desktop-candidate.XXXXXX)
cp "$DEB" "$DSC" "$SOURCE_TAR" "$APPIMAGE" "$FLATPAK" \
    "$HANDBUCH_DEB" "$HANDBUCH_DSC" "$HANDBUCH_SOURCE_TAR" \
    "$STAGE"/magnolie-organizer-kde_"${AKONADI_VERSION}"_amd64.deb \
    "$STAGE"/magnolie-organizer-kde_"${AKONADI_VERSION}".dsc \
    "$STAGE"/magnolie-organizer-kde_"${AKONADI_VERSION}".tar.xz \
    "$STAGE"/kde-"${AKONADI_VERSION}"-provenance.json \
    "$RPM_PAKET" "$RPM_QUELLE" "$HANDBUCH_RPM_PAKET" "$HANDBUCH_RPM_QUELLE" \
    "$AKONADI_RPM_PAKET" "$AKONADI_RPM_QUELLE" \
    "$WINDOWS_INSTALLER" "$WINDOWS_BUILDRECORD" "$WINDOWS_ZIP" "$WINDOWS_PRUEFSUMMEN" \
    "$WINDOWS_SOURCE" "$WINDOWS_PROVENANCE" "$CANDIDATE/"
python3 - "$LIVE_ROOT" "$CANDIDATE" "$LIVE_SOURCE/werkzeuge" "$NOTES_INPUT" <<'PY'
import pathlib
import shutil
import sys
sys.path.insert(0, sys.argv[3])
from release_gate import notes_inputs
root, candidate = map(pathlib.Path, sys.argv[1:3])
notes_directory = pathlib.Path(sys.argv[4])
for name in notes_inputs(root, notes_directory):
    shutil.copyfile(notes_directory / name, candidate / name)
PY
"$PWSH" -NoProfile -File "$LIVE_WINDOWS/build/AssertCandidate.ps1" \
    -Root "$LIVE_WINDOWS" -Directory "$CANDIDATE"
qemu_result=passed
[ "$AUTOPKGTESTS" -eq 1 ] || qemu_result=unavailable
python3 "$LIVE_SOURCE/werkzeuge/release_gate.py" seal --root "$LIVE_ROOT" \
    --candidate "$CANDIDATE" --source-record "$STAGE/source-record.json" --autopkgtest "$qemu_result"
printf 'Private candidate: %s\nNo signing, manifest promotion or release-root replacement performed.\n' "$CANDIDATE"
