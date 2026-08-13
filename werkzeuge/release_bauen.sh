#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
ELTERN=$(dirname "$WURZEL")
LAEUFER=$(command -v node || command -v nodejs || command -v bun)
LASTDATEI=${MAGNOLIE_LASTDATEI:-/tmp/lotus-gross.csv}
APPIMAGE="$ELTERN/Magnolie-Organizer-$FASSUNG-x86_64.AppImage"

cd "$WURZEL"
debian/rules build
DISPLAY= WAYLAND_DISPLAY= XDG_DATA_HOME=/tmp/magnolie-release-data \
XDG_CONFIG_HOME=/tmp/magnolie-release-config TZ=Europe/Berlin \
    python3 pruefungen/test_parser.py
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
DISPLAY= WAYLAND_DISPLAY= TZ=Europe/Berlin SOURCE_DATE_EPOCH=$epoch \
    dpkg-buildpackage -d -us -uc
PAKET_TEST=$(mktemp -d)
trap 'rm -rf "$PAKET_TEST"' EXIT HUP INT TERM
dpkg-deb -x "$ELTERN/magnolie-organizer_${FASSUNG}_all.deb" "$PAKET_TEST"
xvfb-run -a -s "-screen 0 1280x800x24" env \
    MAGNOLIE_TEST_PROGRAMM="$PAKET_TEST/usr/bin/magnolie-organizer" \
    MAGNOLIE_TEST_WEB="$PAKET_TEST/usr/share/magnolie-organizer/web" \
    python3 debian/tests/gtk-webkit.py
rm -rf "$PAKET_TEST"
trap - EXIT HUP INT TERM
SOURCE_DATE_EPOCH=$epoch werkzeuge/appimage_bauen.sh "$APPIMAGE"
pruefungen/test_appimage.sh "$APPIMAGE"
APPIMAGE_VERGLEICH=$(mktemp)
cp "$APPIMAGE" "$APPIMAGE_VERGLEICH"
SOURCE_DATE_EPOCH=$epoch werkzeuge/appimage_bauen.sh "$APPIMAGE"
cmp -s "$APPIMAGE_VERGLEICH" "$APPIMAGE"
rm -f "$APPIMAGE_VERGLEICH"
python3 werkzeuge/release_manifest.py \
    "$ELTERN/magnolie-organizer_${FASSUNG}_all.deb" "$APPIMAGE" \
    "$WURZEL/update.xml" "$ELTERN/update.xml"

# update.xml gehoert zum nativen Quellpaket. Nach den finalen Pruefsummen wird
# deshalb die Quelle noch einmal gebaut; das nicht installierte Manifest darf
# den Inhalt des bereits geprueften Debian-Pakets nicht veraendern.
debian/rules clean
find . -exec touch -h -d "@$epoch" {} +
DISPLAY= WAYLAND_DISPLAY= TZ=Europe/Berlin SOURCE_DATE_EPOCH=$epoch \
    dpkg-buildpackage -d -us -uc
test "$(sha256sum "$ELTERN/magnolie-organizer_${FASSUNG}_all.deb" | cut -d' ' -f1)" = \
    "$(python3 -c 'import sys, xml.etree.ElementTree as E; print(E.parse(sys.argv[1]).findtext("./sha256"))' "$WURZEL/update.xml")"

sha256sum "$ELTERN/magnolie-organizer_${FASSUNG}_all.deb" \
    "$ELTERN/magnolie-organizer_${FASSUNG}.tar.xz" "$APPIMAGE"
