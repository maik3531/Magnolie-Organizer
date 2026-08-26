#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
AUSGABE=${1:-"$WURZEL/../Magnolie-Organizer-$FASSUNG-x86_64.AppImage"}
ARBEIT=${APPIMAGE_JAMMY_DIR:-"$WURZEL/bau/appimage-jammy"}
ROOTFS="$ARBEIT/rootfs"
BAU="$ARBEIT/bau"
BASIS="$ARBEIT/ubuntu-base-22.04.5-base-amd64.tar.gz"
BASIS_URL=https://cdimage.ubuntu.com/ubuntu-base/releases/22.04/release/ubuntu-base-22.04.5-base-amd64.tar.gz
BASIS_SHA=242cd8898b33ea806ef5f13b1076ed7c76f9f989d18384452f7166692438ff1a
PROOT_DEB="$ARBEIT/proot_5.1.0-1.3_amd64.deb"
PROOT_URL=https://archive.ubuntu.com/ubuntu/pool/universe/p/proot/proot_5.1.0-1.3_amd64.deb
PROOT_SHA=01a5d27c4ac16e184bdb356c9e69fa7d494325ac653c4cd64fae4c3fc63cdbbb
TALLOC_DEB="$ARBEIT/libtalloc2_2.3.3-2build1_amd64.deb"
TALLOC_URL=https://archive.ubuntu.com/ubuntu/pool/main/t/talloc/libtalloc2_2.3.3-2build1_amd64.deb
TALLOC_SHA=0910059bb0329add8d13b502f5a10d18d5b3c5202fbbbe25ef4f6d58e7edfe6c
PROOT_WURZEL="$ARBEIT/proot"
PROOT="$PROOT_WURZEL/usr/bin/proot"
SNAPSHOT=20260820T000000Z
BASIS_STAND="$SNAPSHOT-qrcode1"

for befehl in curl dpkg-deb dpkg-parsechangelog sha256sum tar; do
    command -v "$befehl" >/dev/null || {
        printf '%s\n' "Fehlendes Werkzeug fuer den rootlosen AppImage-Bau: $befehl" >&2
        exit 1
    }
done
[ "$(uname -m)" = x86_64 ] || {
    printf '%s\n' 'Die Jammy-Bauumgebung ist fuer x86_64 festgeschrieben.' >&2
    exit 1
}

mkdir -p "$ARBEIT" "$BAU" "$(dirname -- "$AUSGABE")"
if [ ! -f "$BASIS" ] || [ "$(sha256sum "$BASIS" | cut -d' ' -f1)" != "$BASIS_SHA" ]; then
    rm -f "$BASIS"
    curl -L --fail --retry 3 -o "$BASIS" "$BASIS_URL"
fi
printf '%s  %s\n' "$BASIS_SHA" "$BASIS" | sha256sum -c -
for beschreibung in "$PROOT_DEB|$PROOT_URL|$PROOT_SHA" \
    "$TALLOC_DEB|$TALLOC_URL|$TALLOC_SHA"; do
    ziel=${beschreibung%%|*}
    rest=${beschreibung#*|}
    url=${rest%%|*}
    summe=${rest#*|}
    if [ ! -f "$ziel" ] || [ "$(sha256sum "$ziel" | cut -d' ' -f1)" != "$summe" ]; then
        rm -f "$ziel"
        curl -L --fail --retry 3 -o "$ziel" "$url"
    fi
    printf '%s  %s\n' "$summe" "$ziel" | sha256sum -c -
done
if [ ! -x "$PROOT" ]; then
    rm -rf "$PROOT_WURZEL"
    mkdir -p "$PROOT_WURZEL"
    dpkg-deb -x "$PROOT_DEB" "$PROOT_WURZEL"
    dpkg-deb -x "$TALLOC_DEB" "$PROOT_WURZEL"
fi
export LD_LIBRARY_PATH="$PROOT_WURZEL/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

MARKER="$ROOTFS/.magnolie-snapshot"
if [ ! -f "$MARKER" ] || [ "$(cat "$MARKER")" != "$BASIS_STAND" ]; then
    if [ ! -x "$ROOTFS/bin/sh" ]; then
        rm -rf "$ROOTFS"
        mkdir -p "$ROOTFS"
        tar --no-same-owner -xzf "$BASIS" -C "$ROOTFS"
    fi
    printf '%s\n' \
        "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/$SNAPSHOT jammy main universe" \
        "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/$SNAPSHOT jammy-updates main universe" \
        "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/$SNAPSHOT jammy-security main universe" \
        > "$ROOTFS/etc/apt/sources.list"
    rm -f "$ROOTFS/etc/resolv.conf"
    cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
    mkdir -p "$ROOTFS/etc/ssl/certs"
    cp /etc/ssl/certs/ca-certificates.crt "$ROOTFS/etc/ssl/certs/ca-certificates.crt"
    "$PROOT" -0 -r "$ROOTFS" -b /dev -b /proc -w / \
        /usr/bin/env DEBIAN_FRONTEND=noninteractive \
        /usr/bin/apt-get -o APT::Sandbox::User=root update
    "$PROOT" -0 -r "$ROOTFS" -b /dev -b /proc -w / \
        /usr/bin/env DEBIAN_FRONTEND=noninteractive \
        /usr/bin/apt-get -o APT::Sandbox::User=root install -y --no-install-recommends \
        binutils ca-certificates curl dpkg-dev file gcc gettext gir1.2-ayatanaappindicator3-0.1 \
        gir1.2-ecal-2.0 gir1.2-ebook-1.2 gir1.2-gstreamer-1.0 gir1.2-gtk-3.0 gir1.2-ical-3.0 \
        gir1.2-notify-0.7 gir1.2-webkit2-4.1 gir1.2-xapp-1.0 gobject-introspection \
        libayatana-appindicator3-1 libglib2.0-bin libgtk-3-0 libwebkit2gtk-4.1-0 \
        libxapp1 xapp python3 python3-cryptography python3-gi \
        python3-ifaddr python3-openssl \
        python3-qrcode python3-zeroconf
    printf '%s\n' "$BASIS_STAND" > "$MARKER"
fi

"$PROOT" -0 -r "$ROOTFS" -b /dev -b /proc -b "$WURZEL" \
    -b "$(dirname -- "$AUSGABE")" -w "$WURZEL" \
    /usr/bin/env MAGNOLIE_CONTRIBUTOR_HASH="${MAGNOLIE_CONTRIBUTOR_HASH:-}" \
    SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-}" APPIMAGE_BUILD_DIR="$BAU/appimage" \
    APPIMAGE_TOOL_DIR="$BAU/werkzeuge" /bin/sh werkzeuge/appimage_bauen.sh \
    "$AUSGABE"
