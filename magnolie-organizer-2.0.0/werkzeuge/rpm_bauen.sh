#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NAME=magnolie-organizer
QUELLNAME=$(basename "$WURZEL")
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
TOPDIR=${1:-"$WURZEL/bau/rpm"}
MODUS=${2:-}
if [ "${1:-}" = --source-only ]; then
    TOPDIR="$WURZEL/bau/rpm"
    MODUS=--source-only
elif [ "$MODUS" != "" ] && [ "$MODUS" != --source-only ]; then
    printf 'Aufruf: %s [TOPDIR] [--source-only]\n' "$0" >&2
    exit 2
fi
ARCHIV="$TOPDIR/SOURCES/$NAME-$FASSUNG.tar.xz"
EPOCH=${SOURCE_DATE_EPOCH:-1786320000}

if [ -z "$MODUS" ]; then
    CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
    [ "${#CONTRIBUTOR_HASH}" -eq 64 ] || {
        printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH fehlt oder ist ungueltig.' >&2
        exit 2
    }
    case "$CONTRIBUTOR_HASH" in
        *[!0-9a-fA-F]*)
            printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH fehlt oder ist ungueltig.' >&2
            exit 2 ;;
    esac
    MAGNOLIE_CONTRIBUTOR_HASH=$(printf '%s' "$CONTRIBUTOR_HASH" | tr A-F a-f)
    export MAGNOLIE_CONTRIBUTOR_HASH
fi

mkdir -p "$TOPDIR/BUILD" "$TOPDIR/BUILDROOT" "$TOPDIR/RPMS" \
    "$TOPDIR/SOURCES" "$TOPDIR/SPECS" "$TOPDIR/SRPMS"

# Generierte Kataloge, der Klang und lokale Debian-Baureste gehören nicht in
# Source0. rpmbuild erzeugt sie ausschließlich aus den eigentlichen Quellen.
tar --sort=name --mtime="@$EPOCH" --clamp-mtime \
    --owner=0 --group=0 --numeric-owner --mode='u+rwX,go+rX,go-w' \
    --pax-option=delete=atime,delete=ctime \
    --exclude="$QUELLNAME/.git" \
    --exclude="$QUELLNAME/bau" \
    --exclude="$QUELLNAME/build" \
    --exclude="$QUELLNAME/app/build" \
    --exclude="$QUELLNAME/.pytest_cache" \
    --exclude="$QUELLNAME/**/.pytest_cache" \
    --exclude="$QUELLNAME/.kotlin" \
    --exclude="$QUELLNAME/**/.kotlin" \
    --exclude="$QUELLNAME/.gradle" \
    --exclude="$QUELLNAME/**/.gradle" \
    --exclude="$QUELLNAME/**/__pycache__" \
    --exclude="$QUELLNAME/**/*.pyc" \
    --exclude="$QUELLNAME/locale" \
    --exclude="$QUELLNAME/klang/erinnerung.wav" \
    --exclude="$QUELLNAME/web/i18n/*.js" \
    --exclude="$QUELLNAME/debian/.debhelper" \
    --exclude="$QUELLNAME/debian/$NAME" \
    --exclude="$QUELLNAME/debian/debhelper-build-stamp" \
    --exclude="$QUELLNAME/debian/files" \
    --exclude="$QUELLNAME/debian/*.substvars" \
    --exclude="$QUELLNAME/REVIEW*.md" \
    --exclude="$QUELLNAME/ENTWURF*.md" \
    --exclude="$QUELLNAME/OFFENE-PUNKTE*.md" \
    --exclude="$QUELLNAME/*ANALYSE*.md" \
    --exclude="$QUELLNAME/*PLAN*.md" \
    --exclude="$QUELLNAME/*AUDIT*.md" \
    --exclude="$QUELLNAME/*.tar.*" \
    --exclude="$QUELLNAME/*.zip" \
    --exclude="$QUELLNAME/*.rpm" \
    --exclude="$QUELLNAME/*.deb" \
    --exclude="$QUELLNAME/*.AppImage" \
    --transform="s,^$QUELLNAME,$NAME-$FASSUNG," \
    -C "$(dirname "$WURZEL")" -cJf "$ARCHIV" "$(basename "$WURZEL")"

cp "$WURZEL/rpm/$NAME.spec" "$TOPDIR/SPECS/"
printf 'Source0: %s\n' "$ARCHIV"

if ! command -v rpmbuild >/dev/null 2>&1; then
    printf '%s\n' 'rpmbuild fehlt; das normalisierte Source0 wurde dennoch erzeugt.' >&2
    exit 127
fi

BAUART=-ba
[ -z "$MODUS" ] || BAUART=-bs
set -- "$BAUART" --define "_topdir $TOPDIR"
rpmbuild "$@" "$TOPDIR/SPECS/$NAME.spec"
