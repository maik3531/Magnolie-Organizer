#!/bin/sh
set -eu

APPIMAGE=$(readlink -f "${1:?Aufruf: pruefungen/test_appimage_arch.sh DATEI.AppImage}")
WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ARBEIT="$WURZEL/bau/appimage-arch-test"
ARCHIV="$ARBEIT/archlinux-bootstrap-2026.08.01-x86_64.tar.zst"
URL=https://archive.archlinux.org/iso/2026.08.01/archlinux-bootstrap-2026.08.01-x86_64.tar.zst
SUMME=9600cef264af08899eff8f8b9bb2dd141c748a0038b651256d335e489a8dd2f6
PROOT_WURZEL="${APPIMAGE_JAMMY_DIR:-$WURZEL/bau/appimage-jammy}/proot"
PROOT="$PROOT_WURZEL/usr/bin/proot"

for befehl in curl sha256sum tar; do
    command -v "$befehl" >/dev/null || {
        printf '%s\n' "Fehlendes Arch-Pruefwerkzeug: $befehl" >&2
        exit 1
    }
done
[ -x "$PROOT" ] || {
    printf '%s\n' 'Zuerst werkzeuge/appimage_jammy_bauen.sh ausfuehren.' >&2
    exit 1
}
mkdir -p "$ARBEIT"
cleanup() {
    for pfad in "$ARBEIT/root.x86_64" "$ARBEIT/squashfs-root"; do
        [ ! -d "$pfad" ] || chmod -R u+rwX "$pfad" 2>/dev/null || true
        rm -rf "$pfad"
    done
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
if [ ! -f "$ARCHIV" ] || [ "$(sha256sum "$ARCHIV" | cut -d' ' -f1)" != "$SUMME" ]; then
    rm -f "$ARCHIV"
    curl -L --fail --retry 3 -o "$ARCHIV" "$URL"
fi
printf '%s  %s\n' "$SUMME" "$ARCHIV" | sha256sum -c -
if [ ! -x "$ARBEIT/root.x86_64/bin/sh" ]; then
    rm -rf "$ARBEIT/root.x86_64"
    tar --no-same-owner --delay-directory-restore --zstd -xf "$ARCHIV" -C "$ARBEIT"
fi
rm -rf "$ARBEIT/squashfs-root"
(cd "$ARBEIT" && "$APPIMAGE" --appimage-extract >/dev/null)

export LD_LIBRARY_PATH="$PROOT_WURZEL/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
ausgabe=$("$PROOT" -0 -r "$ARBEIT/root.x86_64" -b /dev -b /proc -b "$ARBEIT" \
    -w "$ARBEIT/squashfs-root" /usr/bin/env -u LD_LIBRARY_PATH \
    "$ARBEIT/squashfs-root/AppRun" --language en --help 2>&1)
printf '%s\n' "$ausgabe" | grep -q '^Usage:'
if printf '%s\n' "$ausgabe" | grep -Eq 'Failed to load shared library|cannot open shared object'; then
    printf '%s\n' "$ausgabe" >&2
    exit 1
fi
printf '%s\n' 'AppImage startet mit seiner gebuendelten Laufzeit unter Arch Linux.'
