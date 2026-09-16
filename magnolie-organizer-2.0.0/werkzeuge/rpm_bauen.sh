#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NAME=magnolie-organizer
QUELLNAME=$(basename "$WURZEL")
FASSUNG=$(sed -n 's/^Version:[[:space:]]*//p' "$WURZEL/rpm/$NAME.spec")
[ -n "$FASSUNG" ] || { printf '%s\n' 'Version fehlt in der RPM-Spec.' >&2; exit 2; }
DISTRO=
TOPBASE=
MODUS=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --distro)
            [ "$#" -ge 2 ] || { printf '%s\n' '--distro benoetigt einen Wert.' >&2; exit 2; }
            DISTRO=$2
            shift 2 ;;
        --source-only)
            MODUS=--source-only
            shift ;;
        -* )
            printf 'Aufruf: %s --distro PROFIL [TOPDIR] [--source-only]\n' "$0" >&2
            exit 2 ;;
        *)
            [ -z "$TOPBASE" ] || { printf '%s\n' 'Nur ein TOPDIR ist erlaubt.' >&2; exit 2; }
            TOPBASE=$1
            shift ;;
    esac
done
[ -n "$DISTRO" ] || { printf '%s\n' '--distro ist erforderlich.' >&2; exit 2; }
case "$DISTRO" in
    fedora|opensuse|mageia|openmandriva|pclinuxos|rosa) ;;
    *)
        printf '%s\n' 'Unbekanntes RPM-Distributionsprofil.' >&2
        exit 2 ;;
esac
TOPBASE=${TOPBASE:-"$WURZEL/bau/rpm"}
TOPDIR="$TOPBASE/$DISTRO"
ARCHIV="$TOPDIR/SOURCES/$NAME-$FASSUNG.tar.xz"
EPOCH=${SOURCE_DATE_EPOCH:-1786320000}

if [ -z "$MODUS" ]; then
    CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
    if [ -n "$CONTRIBUTOR_HASH" ]; then
        [ "${#CONTRIBUTOR_HASH}" -eq 64 ] || {
            printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2
            exit 2
        }
        case "$CONTRIBUTOR_HASH" in
            *[!0-9a-fA-F]*)
                printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2
                exit 2 ;;
        esac
        MAGNOLIE_CONTRIBUTOR_HASH=$(printf '%s' "$CONTRIBUTOR_HASH" | tr A-F a-f)
        export MAGNOLIE_CONTRIBUTOR_HASH
    fi
fi

mkdir -p "$TOPDIR/BUILD" "$TOPDIR/BUILDROOT" "$TOPDIR/RPMS" \
    "$TOPDIR/SOURCES" "$TOPDIR/SPECS" "$TOPDIR/SRPMS"

# Generierte Kataloge, der Klang und lokale Debian-Baureste gehören nicht in
# Source0. rpmbuild erzeugt sie ausschließlich aus den eigentlichen Quellen.
SOURCE_WORK=$(mktemp -d /tmp/opencode/magnolie-rpm-source.XXXXXX)
trap 'rm -rf "$SOURCE_WORK"' EXIT HUP INT TERM
python3 "$WURZEL/werkzeuge/release_sources.py" copy "$WURZEL" "$SOURCE_WORK/$QUELLNAME"
if [ -d "$(dirname "$WURZEL")/contracts" ]; then
    python3 "$WURZEL/werkzeuge/release_sources.py" copy "$(dirname "$WURZEL")/contracts" "$SOURCE_WORK/contracts"
fi
python3 "$WURZEL/werkzeuge/release_sources.py" contracts "$SOURCE_WORK/$QUELLNAME"
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
    --exclude="$QUELLNAME/native/akonadi-helper/obj-*" \
    --exclude="$QUELLNAME/native/akonadi-helper/debian/files" \
    --exclude="$QUELLNAME/native/akonadi-helper/debian/*.substvars" \
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
    -C "$SOURCE_WORK" -cJf "$ARCHIV" "$QUELLNAME"

sed "s/@MAGNOLIE_DISTRO@/$DISTRO/g" "$WURZEL/rpm/$NAME.spec" \
    > "$TOPDIR/SPECS/$NAME.spec"
printf 'Source0: %s\n' "$ARCHIV"

if ! command -v rpmbuild >/dev/null 2>&1; then
    printf '%s\n' 'rpmbuild fehlt; das normalisierte Source0 wurde dennoch erzeugt.' >&2
    exit 127
fi

BAUART=-ba
[ -z "$MODUS" ] || BAUART=-bs
set -- "$BAUART" --define "_topdir $TOPDIR"
rpmbuild "$@" "$TOPDIR/SPECS/$NAME.spec"
