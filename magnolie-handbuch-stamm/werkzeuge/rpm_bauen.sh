#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NAME=magnolie-handbuch
QUELLNAME=$(basename "$WURZEL")
FASSUNG=$(sed -n 's/^Version:[[:space:]]*//p' "$WURZEL/rpm/$NAME.spec")
[ -n "$FASSUNG" ] || { printf '%s\n' 'Version fehlt in der RPM-Spec.' >&2; exit 2; }
DISTRO=
TOPBASE=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --distro)
            [ "$#" -ge 2 ] || { printf '%s\n' '--distro benoetigt einen Wert.' >&2; exit 2; }
            DISTRO=$2
            shift 2 ;;
        -* )
            printf 'Aufruf: %s --distro PROFIL [TOPDIR]\n' "$0" >&2
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

QUELLLISTE=$(mktemp)
trap 'rm -f "$QUELLLISTE"' EXIT
trap 'exit 1' HUP INT TERM
python3 "$WURZEL/werkzeuge/source_selection.py" "$WURZEL" > "$QUELLLISTE"
mkdir -p "$TOPDIR/BUILD" "$TOPDIR/BUILDROOT" "$TOPDIR/RPMS" \
    "$TOPDIR/SOURCES" "$TOPDIR/SPECS" "$TOPDIR/SRPMS"
tar --sort=name --mtime="@$EPOCH" --clamp-mtime \
    --owner=0 --group=0 --numeric-owner --mode='u+rwX,go+rX,go-w' \
    --pax-option=delete=atime,delete=ctime \
    --exclude='web/i18n/*.js' \
    --transform="s,^,$NAME-$FASSUNG/," \
    -C "$WURZEL" --null --verbatim-files-from --no-recursion \
    -cJf "$ARCHIV" --files-from="$QUELLLISTE"

sed "s/@MAGNOLIE_DISTRO@/$DISTRO/g" "$WURZEL/rpm/$NAME.spec" \
    > "$TOPDIR/SPECS/$NAME.spec"
printf 'Source0: %s\n' "$ARCHIV"
command -v rpmbuild >/dev/null 2>&1 || {
    printf '%s\n' 'rpmbuild fehlt; das normalisierte Source0 wurde dennoch erzeugt.' >&2
    exit 127
}
rpmbuild -ba --define "_topdir $TOPDIR" "$TOPDIR/SPECS/$NAME.spec"
