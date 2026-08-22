#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NAME=magnolie-handbuch
QUELLNAME=$(basename "$WURZEL")
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
TOPDIR=${1:-"$WURZEL/bau/rpm"}
ARCHIV="$TOPDIR/SOURCES/$NAME-$FASSUNG.tar.xz"
EPOCH=${SOURCE_DATE_EPOCH:-1786320000}

mkdir -p "$TOPDIR/BUILD" "$TOPDIR/BUILDROOT" "$TOPDIR/RPMS" \
    "$TOPDIR/SOURCES" "$TOPDIR/SPECS" "$TOPDIR/SRPMS"
tar --sort=name --mtime="@$EPOCH" --clamp-mtime \
    --owner=0 --group=0 --numeric-owner --mode='u+rwX,go+rX,go-w' \
    --pax-option=delete=atime,delete=ctime \
    --exclude="$QUELLNAME/.git" \
    --exclude="$QUELLNAME/bau" \
    --exclude="$QUELLNAME/.pytest_cache" \
    --exclude="$QUELLNAME/**/.pytest_cache" \
    --exclude="$QUELLNAME/**/__pycache__" \
    --exclude="$QUELLNAME/**/*.pyc" \
    --exclude="$QUELLNAME/locale" \
    --exclude="$QUELLNAME/web/i18n/*.js" \
    --exclude="$QUELLNAME/debian/.debhelper" \
    --exclude="$QUELLNAME/debian/$NAME" \
    --exclude="$QUELLNAME/debian/files" \
    --exclude="$QUELLNAME/debian/*.substvars" \
    --exclude="$QUELLNAME/*.tar.*" \
    --exclude="$QUELLNAME/*.rpm" \
    --exclude="$QUELLNAME/*.deb" \
    --transform="s,^$QUELLNAME,$NAME-$FASSUNG," \
    -C "$(dirname "$WURZEL")" -cJf "$ARCHIV" "$QUELLNAME"

cp "$WURZEL/rpm/$NAME.spec" "$TOPDIR/SPECS/"
printf 'Source0: %s\n' "$ARCHIV"
command -v rpmbuild >/dev/null 2>&1 || {
    printf '%s\n' 'rpmbuild fehlt; das normalisierte Source0 wurde dennoch erzeugt.' >&2
    exit 127
}
rpmbuild -ba --define "_topdir $TOPDIR" "$TOPDIR/SPECS/$NAME.spec"
