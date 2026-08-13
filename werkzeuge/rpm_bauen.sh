#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NAME=magnolie-organizer
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
TOPDIR=${1:-"$WURZEL/bau/rpm"}
ARCHIV="$TOPDIR/SOURCES/$NAME-$FASSUNG.tar.xz"
EPOCH=${SOURCE_DATE_EPOCH:-1786320000}

mkdir -p "$TOPDIR/BUILD" "$TOPDIR/BUILDROOT" "$TOPDIR/RPMS" \
    "$TOPDIR/SOURCES" "$TOPDIR/SPECS" "$TOPDIR/SRPMS"

# Generierte Kataloge, der Klang und lokale Debian-Baureste gehören nicht in
# Source0. rpmbuild erzeugt sie ausschließlich aus den eigentlichen Quellen.
tar --sort=name --mtime="@$EPOCH" --clamp-mtime \
    --owner=0 --group=0 --numeric-owner --mode='u+rwX,go+rX,go-w' \
    --pax-option=delete=atime,delete=ctime \
    --exclude="$NAME-1.31.7/.git" \
    --exclude="$NAME-1.31.7/bau" \
    --exclude="$NAME-1.31.7/**/__pycache__" \
    --exclude="$NAME-1.31.7/**/*.pyc" \
    --exclude="$NAME-1.31.7/locale" \
    --exclude="$NAME-1.31.7/klang/erinnerung.wav" \
    --exclude="$NAME-1.31.7/web/i18n/*.js" \
    --exclude="$NAME-1.31.7/debian/.debhelper" \
    --exclude="$NAME-1.31.7/debian/$NAME" \
    --exclude="$NAME-1.31.7/debian/debhelper-build-stamp" \
    --exclude="$NAME-1.31.7/debian/files" \
    --exclude="$NAME-1.31.7/debian/*.substvars" \
    --exclude="$NAME-1.31.7/REVIEW*.md" \
    --exclude="$NAME-1.31.7/ENTWURF*.md" \
    --exclude="$NAME-1.31.7/OFFENE-PUNKTE*.md" \
    --exclude="$NAME-1.31.7/*ANALYSE*.md" \
    --exclude="$NAME-1.31.7/*PLAN*.md" \
    --exclude="$NAME-1.31.7/*AUDIT*.md" \
    --transform="s,^$NAME-1\.31\.7,$NAME-$FASSUNG," \
    -C "$(dirname "$WURZEL")" -cJf "$ARCHIV" "$(basename "$WURZEL")"

cp "$WURZEL/rpm/$NAME.spec" "$TOPDIR/SPECS/"
printf 'Source0: %s\n' "$ARCHIV"

if ! command -v rpmbuild >/dev/null 2>&1; then
    printf '%s\n' 'rpmbuild fehlt; das normalisierte Source0 wurde dennoch erzeugt.' >&2
    exit 127
fi

CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
set -- -ba --define "_topdir $TOPDIR"
if [ -n "$CONTRIBUTOR_HASH" ]; then
    [ "${#CONTRIBUTOR_HASH}" -eq 64 ] || exit 2
    case "$CONTRIBUTOR_HASH" in *[!0-9a-fA-F]*) exit 2;; esac
    set -- "$@" --define "magnolie_contributor_hash $CONTRIBUTOR_HASH"
fi
rpmbuild "$@" "$TOPDIR/SPECS/$NAME.spec"
