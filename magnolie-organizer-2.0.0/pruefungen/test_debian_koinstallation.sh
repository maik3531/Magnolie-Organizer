#!/bin/sh
set -eu

[ "$#" -eq 4 ] || {
    printf 'Aufruf: %s ORGANIZER.deb HANDBUCH.deb ALTER_ORGANIZER.deb ALTES_HANDBUCH.deb\n' "$0" >&2
    exit 2
}
ORGANIZER=$(realpath "$1")
HANDBUCH=$(realpath "$2")
ALTER_ORGANIZER=$(realpath "$3")
ALTES_HANDBUCH=$(realpath "$4")
ARBEIT=$(mktemp -d)
trap 'rm -rf "$ARBEIT"' EXIT HUP INT TERM

ORGANIZER_VERSION=$(dpkg-deb -f "$ORGANIZER" Version)
HANDBUCH_VERSION=$(dpkg-deb -f "$HANDBUCH" Version)
ALTE_ORGANIZER_VERSION=$(dpkg-deb -f "$ALTER_ORGANIZER" Version)
ALTE_HANDBUCH_VERSION=$(dpkg-deb -f "$ALTES_HANDBUCH" Version)
test "$ORGANIZER_VERSION" = "$HANDBUCH_VERSION"
test "$ALTE_ORGANIZER_VERSION" = "$ALTE_HANDBUCH_VERSION"
dpkg --compare-versions "$ORGANIZER_VERSION" gt "$ALTE_ORGANIZER_VERSION"

legacy="$ARBEIT/magnolie-handbuch-alt"
mkdir -p "$legacy/DEBIAN" "$legacy/usr/bin"
cat > "$legacy/DEBIAN/control" <<'EOF'
Package: magnolie-handbuch
Version: 1.0.0
Architecture: all
Maintainer: Magnolie package test <noreply@example.invalid>
Description: Legacy collision fixture
EOF
printf '%s\n' '# legacy reporter collision' > "$legacy/usr/bin/magnolie_crash.py"
dpkg-deb --build --root-owner-group "$legacy" "$ARBEIT/magnolie-handbuch_alt_all.deb" >/dev/null

entpacke() {
    root=$1
    shift
    mkdir -p "$root/var/lib/dpkg" "$root/var/log"
    : > "$root/var/lib/dpkg/status"
    dpkg --force-not-root --root="$root" --log="$root/var/log/dpkg.log" --unpack "$@" >/dev/null
}

pruefe_installation() {
    root=$1
    status=$(dpkg-query --admindir="$root/var/lib/dpkg" -W \
        -f='${Package} ${Version} ${db:Status-Status}\n' \
        magnolie-organizer magnolie-handbuch)
    test "$status" = "magnolie-handbuch $HANDBUCH_VERSION unpacked
magnolie-organizer $ORGANIZER_VERSION unpacked"
    dpkg-query --admindir="$root/var/lib/dpkg" -S /usr/bin/magnolie_crash.py | \
        grep -q '^magnolie-organizer:'
    dpkg-query --admindir="$root/var/lib/dpkg" \
        -S /usr/lib/magnolie-handbuch/magnolie_crash.py | \
        grep -q '^magnolie-handbuch:'
    test -x "$root/usr/bin/magnolie-organizer"
    test -x "$root/usr/bin/magnolie-handbuch"
    "$root/usr/bin/magnolie-organizer" --help >/dev/null
    test "$("$root/usr/bin/magnolie-handbuch" --version)" = "$HANDBUCH_VERSION"
}

entpacke "$ARBEIT/organizer-zuerst" "$ORGANIZER" "$HANDBUCH"
pruefe_installation "$ARBEIT/organizer-zuerst"
entpacke "$ARBEIT/handbuch-zuerst" "$HANDBUCH" "$ORGANIZER"
pruefe_installation "$ARBEIT/handbuch-zuerst"

upgrade_organizer_zuerst="$ARBEIT/upgrade-organizer-zuerst"
entpacke "$upgrade_organizer_zuerst" "$ALTER_ORGANIZER" "$ALTES_HANDBUCH"
entpacke "$upgrade_organizer_zuerst" "$ORGANIZER" "$HANDBUCH"
pruefe_installation "$upgrade_organizer_zuerst"

upgrade_handbuch_zuerst="$ARBEIT/upgrade-handbuch-zuerst"
entpacke "$upgrade_handbuch_zuerst" "$ALTER_ORGANIZER" "$ALTES_HANDBUCH"
entpacke "$upgrade_handbuch_zuerst" "$HANDBUCH" "$ORGANIZER"
pruefe_installation "$upgrade_handbuch_zuerst"

legacy_upgrade="$ARBEIT/upgrade-kollision"
entpacke "$legacy_upgrade" "$ARBEIT/magnolie-handbuch_alt_all.deb" "$ORGANIZER" "$HANDBUCH"
pruefe_installation "$legacy_upgrade"

printf '%s\n' \
    "Debian-Koinstallation und Upgrade $ALTE_ORGANIZER_VERSION -> $ORGANIZER_VERSION in beiden Reihenfolgen: ok"
