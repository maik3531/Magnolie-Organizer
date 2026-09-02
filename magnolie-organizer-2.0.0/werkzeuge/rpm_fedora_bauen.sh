#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ARBEITSBAUM=$(dirname "$WURZEL")
HANDBUCH="$ARBEITSBAUM/magnolie-handbuch-stamm"
ARBEIT=${RPM_FEDORA_DIR:-"$WURZEL/bau/rpm-fedora"}
ROOTFS="$ARBEIT/rootfs"
TOPDIR="$ARBEIT/rpm"
HANDBUCH_TOPDIR="$ARBEIT/handbuch-rpm"
AKONADI_TOPDIR="$ARBEIT/akonadi-rpm"
AKONADI_QUELLE="$WURZEL/native/akonadi-helper"
AKONADI_VERSION=1.0.0
BASIS="$ARBEIT/Fedora-WSL-Base-42-1.1.x86_64.tar.xz"
BASIS_URL=https://download.fedoraproject.org/pub/fedora/linux/releases/42/Container/x86_64/images/Fedora-WSL-Base-42-1.1.x86_64.tar.xz
BASIS_SHA=99fb3d05d78ca17c6815bb03cf528da8ef82ebc6260407f2b09461e0da8a1b8d
BASIS_STAND="$BASIS_SHA-bwrap-readable-fakeroot-release"
MARKER="$ROOTFS/.magnolie-fedora-basis"
CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
EPOCH=${SOURCE_DATE_EPOCH:-1786320000}

for befehl in bwrap curl sha256sum tar; do
    command -v "$befehl" >/dev/null || {
        printf '%s\n' "Fehlendes Werkzeug fuer den rootlosen Fedora-Bau: $befehl" >&2
        exit 1
    }
done
[ "$(uname -m)" = x86_64 ] || {
    printf '%s\n' 'Die Fedora-Bauumgebung ist fuer x86_64 festgeschrieben.' >&2
    exit 1
}
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
    CONTRIBUTOR_HASH=$(printf '%s' "$CONTRIBUTOR_HASH" | tr A-F a-f)
fi

mkdir -p "$ARBEIT" "$TOPDIR" "$HANDBUCH_TOPDIR" "$AKONADI_TOPDIR"
if [ ! -f "$BASIS" ] || [ "$(sha256sum "$BASIS" | cut -d' ' -f1)" != "$BASIS_SHA" ]; then
    rm -f "$BASIS"
    curl -L --fail --retry 3 -o "$BASIS" "$BASIS_URL"
fi
printf '%s  %s\n' "$BASIS_SHA" "$BASIS" | sha256sum -c -

fedora() {
    bwrap --unshare-user --uid 0 --gid 0 --bind "$ROOTFS" / \
        --dev /dev --proc /proc --ro-bind /sys /sys --tmpfs /run \
        --bind "$ARBEITSBAUM" "$ARBEITSBAUM" \
        --bind "$TOPDIR" "$TOPDIR" --bind "$HANDBUCH_TOPDIR" "$HANDBUCH_TOPDIR" \
        --bind "$AKONADI_TOPDIR" "$AKONADI_TOPDIR" \
        --chdir "$WURZEL" "$@"
}

if [ ! -f "$MARKER" ] || [ "$(command cat "$MARKER")" != "$BASIS_STAND" ]; then
    [ ! -d "$ROOTFS" ] || chmod -R u+rwX "$ROOTFS"
    rm -rf "$ROOTFS"
    mkdir -p "$ROOTFS"
    tar --no-same-owner -xJf "$BASIS" -C "$ROOTFS"
    chmod -R u+rwX "$ROOTFS"
    rm -f "$ROOTFS/etc/resolv.conf"
    cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
    mkdir -p "$ROOTFS$ARBEITSBAUM"
    rm -f "$ROOTFS/etc/yum.repos.d/"*.repo
    printf '%s\n' \
        '[fedora]' \
        'name=Fedora 42 - x86_64' \
        'baseurl=https://download.fedoraproject.org/pub/fedora/linux/releases/42/Everything/x86_64/os/' \
        'enabled=1' \
        'gpgcheck=1' \
        'gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-42-x86_64' \
        > "$ROOTFS/etc/yum.repos.d/magnolie-fedora.repo"
    printf '%s\n' "$BASIS_STAND" > "$MARKER"
fi

fedora /usr/bin/dnf -y --setopt=install_weak_deps=False install fakeroot
fedora /usr/bin/fakeroot /usr/bin/dnf -y --setopt=install_weak_deps=False install \
    appstream desktop-file-utils dpkg-dev gettext gtk3 libnotify nodejs \
    python3-cryptography python3-devel python3-gobject python3-pyOpenSSL \
    python3-pytest python3-qrcode python3-zeroconf rpm-build webkit2gtk4.1 xdg-utils \
    cmake gcc-c++ extra-cmake-modules akonadi-server-devel \
    kf6-kcalendarcore-devel kf6-kcontacts-devel

rm -rf "$TOPDIR" "$HANDBUCH_TOPDIR" "$AKONADI_TOPDIR"
mkdir -p "$TOPDIR" "$HANDBUCH_TOPDIR" \
    "$AKONADI_TOPDIR/SOURCES" "$AKONADI_TOPDIR/SPECS"
tar --sort=name --mtime="@$EPOCH" --owner=0 --group=0 --numeric-owner \
    --pax-option=delete=atime,delete=ctime \
    --exclude='./build' --exclude='./bau' --exclude='./obj-*' \
    --exclude='./debian/.debhelper' \
    --exclude='./debian/files' --exclude='./debian/*.substvars' \
    --transform="s,^\.,magnolie-organizer-akonadi-$AKONADI_VERSION," \
    -C "$AKONADI_QUELLE" -cJf \
    "$AKONADI_TOPDIR/SOURCES/magnolie-organizer-akonadi-$AKONADI_VERSION.tar.xz" .
cp "$AKONADI_QUELLE/magnolie-organizer-akonadi.spec" "$AKONADI_TOPDIR/SPECS/"
fedora /usr/bin/env MAGNOLIE_CONTRIBUTOR_HASH="$CONTRIBUTOR_HASH" \
    SOURCE_DATE_EPOCH="$EPOCH" \
    /bin/sh werkzeuge/rpm_bauen.sh --distro fedora "$TOPDIR"
fedora /usr/bin/env SOURCE_DATE_EPOCH="$EPOCH" \
    /bin/sh "$HANDBUCH/werkzeuge/rpm_bauen.sh" --distro fedora "$HANDBUCH_TOPDIR"
fedora /usr/bin/env SOURCE_DATE_EPOCH="$EPOCH" \
    /usr/bin/rpmbuild -ba --define "_topdir $AKONADI_TOPDIR" \
    "$AKONADI_TOPDIR/SPECS/magnolie-organizer-akonadi.spec"

set -- "$TOPDIR"/fedora/RPMS/noarch/magnolie-organizer-*.noarch.rpm
[ "$#" -eq 1 ] && [ -f "$1" ] || {
    printf '%s\n' 'Genau ein binaeres Organizer-RPM wurde erwartet.' >&2
    exit 1
}
ORGANIZER_RPM=$1
set -- "$HANDBUCH_TOPDIR"/fedora/RPMS/noarch/magnolie-handbuch-*.noarch.rpm
[ "$#" -eq 1 ] && [ -f "$1" ] || {
    printf '%s\n' 'Genau ein binaeres Handbuch-RPM wurde erwartet.' >&2
    exit 1
}
HANDBUCH_RPM=$1
set -- "$AKONADI_TOPDIR"/RPMS/*/magnolie-organizer-akonadi-"$AKONADI_VERSION"-*.rpm
[ "$#" -eq 1 ] && [ -f "$1" ] || {
    printf '%s\n' 'Genau ein binaeres Akonadi-Helfer-RPM wurde erwartet.' >&2
    exit 1
}
AKONADI_RPM=$1
test "$(fedora /usr/bin/rpm -qp --qf '%{LICENSE}' "$AKONADI_RPM")" = \
    GPL-3.0-or-later
fedora /bin/sh -c \
    "/usr/bin/rpm -qp --requires '$AKONADI_RPM' | /usr/bin/grep -Fx 'magnolie-organizer >= 2.0.16'"
ORGANIZER_DATEILISTE="$ARBEIT/organizer-rpm-files.txt"
HANDBUCH_DATEILISTE="$ARBEIT/handbook-rpm-files.txt"
fedora /usr/bin/rpm -qp --qf '[%{FILENAMES}\t%{FILEMODES}\n]' \
    "$ORGANIZER_RPM" > "$ORGANIZER_DATEILISTE"
fedora /usr/bin/rpm -qp --qf '[%{FILENAMES}\t%{FILEMODES}\n]' \
    "$HANDBUCH_RPM" > "$HANDBUCH_DATEILISTE"
python3 - "$ORGANIZER_DATEILISTE" "$HANDBUCH_DATEILISTE" <<'PY'
import pathlib
import stat
import sys

def files(path):
    result = set()
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        name, mode = line.rsplit("\t", 1)
        if not stat.S_ISDIR(int(mode)):
            result.add(name)
    return result

overlap = files(sys.argv[1]) & files(sys.argv[2])
if overlap:
    raise SystemExit("RPM-Pakete enthalten gemeinsame Dateien: " +
                     ", ".join(sorted(overlap)))
PY
fedora /usr/bin/fakeroot /usr/bin/dnf -y --setopt=install_weak_deps=False install \
    "$ORGANIZER_RPM" "$HANDBUCH_RPM" "$AKONADI_RPM"
fedora /usr/bin/rpm -V magnolie-organizer magnolie-handbuch magnolie-organizer-akonadi
fedora /usr/bin/rpm -qf /usr/libexec/magnolie-organizer \
    /usr/libexec/magnolie-organizer/magnolie-akonadi-helper \
    /usr/share/licenses/magnolie-organizer-akonadi/copyright >/dev/null
AKONADI_ANTWORT="$AKONADI_TOPDIR/akonadi-response.json"
if fedora /bin/sh -c \
        "printf '%s' '{\"command\":\"unsupported-smoke\"}' | /usr/libexec/magnolie-organizer/magnolie-akonadi-helper > '$AKONADI_ANTWORT'"; then
    akonadi_status=0
else
    akonadi_status=$?
fi
[ "$akonadi_status" -eq 1 ] || {
    printf '%s\n' "Akonadi-Helfer lieferte Status $akonadi_status statt 1." >&2
    exit 1
}
python3 - "$AKONADI_ANTWORT" <<'PY'
import json
import pathlib
import sys

response = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert response["ok"] is False
assert "unsupported command" in response["error"]
PY
if [ -n "$CONTRIBUTOR_HASH" ]; then
    fedora /usr/bin/env MAGNOLIE_CONTRIBUTOR_HASH="$CONTRIBUTOR_HASH" \
        /usr/bin/python3 -c 'import json; assert json.load(open("/usr/share/magnolie-organizer/build-config.json"))["contributorHash"] == __import__("os").environ["MAGNOLIE_CONTRIBUTOR_HASH"]'
else
    fedora /usr/bin/test ! -e /usr/share/magnolie-organizer/build-config.json
fi
fedora /usr/bin/env DISPLAY= WAYLAND_DISPLAY= \
    /usr/bin/magnolie-organizer --language en --help >/dev/null
fedora /usr/bin/env DISPLAY= WAYLAND_DISPLAY= PYTHONDONTWRITEBYTECODE=1 \
    /usr/bin/magnolie-handbuch --language en --help >/dev/null
fedora /usr/bin/rpm -qf /usr/lib/magnolie-handbuch \
    /usr/lib/magnolie-handbuch/magnolie_crash.py >/dev/null
fedora /usr/bin/fakeroot /usr/bin/dnf -y remove magnolie-handbuch
if fedora /usr/bin/rpm -q magnolie-handbuch >/dev/null 2>&1; then
    printf '%s\n' 'Handbuch-RPM ist nach der Entfernung noch installiert.' >&2
    exit 1
fi
fedora /usr/bin/test ! -e /usr/bin/magnolie-handbuch
fedora /usr/bin/test ! -e /usr/lib/magnolie-handbuch/magnolie_crash.py
fedora /usr/bin/rpm -V magnolie-organizer
fedora /usr/bin/env DISPLAY= WAYLAND_DISPLAY= \
    /usr/bin/magnolie-organizer --language en --help >/dev/null

printf '%s\n' \
    "Fedora-RPM gebaut, installiert und geprueft: $ORGANIZER_RPM" \
    "Fedora-RPM gebaut, installiert und geprueft: $HANDBUCH_RPM" \
    "Fedora-RPM gebaut, installiert und geprueft: $AKONADI_RPM"
