#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
APP_ID=io.gitlab.maik3531.MagnolieOrganizer
ZWEIG=stable
MANIFEST="$WURZEL/flatpak/$APP_ID.json"
AUSGABE=${1:-"$WURZEL/../Magnolie-Organizer-$FASSUNG-x86_64.flatpak"}
ARBEIT=${FLATPAK_BUILD_DIR:-"$WURZEL/bau/flatpak"}
BAUM="$ARBEIT/build"
REPO="$ARBEIT/repo"
BAU_MANIFEST="$WURZEL/flatpak/.$APP_ID.build.json"
CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
SOURCE_EPOCH=${SOURCE_DATE_EPOCH:-$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -STimestamp)}

for befehl in dpkg-parsechangelog flatpak python3 sha256sum; do
    command -v "$befehl" >/dev/null || {
        printf '%s\n' "Fehlendes Flatpak-Bauwerkzeug: $befehl" >&2
        exit 1
    }
done
trap 'rm -f "$BAU_MANIFEST"' EXIT HUP INT TERM
if [ -n "$CONTRIBUTOR_HASH" ]; then
    [ "${#CONTRIBUTOR_HASH}" -eq 64 ] || {
        printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2
        exit 2
    }
    case "$CONTRIBUTOR_HASH" in
        *[!0-9a-fA-F]*) printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2; exit 2 ;;
    esac
    CONTRIBUTOR_HASH=$(printf '%s' "$CONTRIBUTOR_HASH" | tr A-F a-f)
fi
flatpak info --user org.gnome.Sdk//49 >/dev/null 2>&1 || {
    printf '%s\n' 'Das GNOME-SDK 49 fehlt in der Benutzerinstallation.' >&2
    printf '%s\n' 'Installation: flatpak install --user flathub org.gnome.Sdk//49' >&2
    exit 1
}
flatpak info --user org.flatpak.Builder >/dev/null 2>&1 || {
    printf '%s\n' 'Der Flatpak Builder fehlt in der Benutzerinstallation.' >&2
    printf '%s\n' 'Installation: flatpak install --user flathub org.flatpak.Builder' >&2
    exit 1
}

rm -rf "$BAUM" "$REPO"
mkdir -p "$ARBEIT" "$(dirname -- "$AUSGABE")"
python3 - "$MANIFEST" "$BAU_MANIFEST" "$CONTRIBUTOR_HASH" <<'PY'
import json
import pathlib
import sys

source, target, contributor_hash = sys.argv[1:]
manifest = json.loads(pathlib.Path(source).read_text(encoding="utf-8"))
module = manifest["modules"][-1]
if contributor_hash:
    module["build-commands"].append(
        "printf '{\"contributorHash\":\"%s\"}\\n' > "
        "/app/share/magnolie-organizer/build-config.json" % contributor_hash)
pathlib.Path(target).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY
flatpak run --user --filesystem="$WURZEL" org.flatpak.Builder \
    --user --force-clean --default-branch="$ZWEIG" --override-source-date-epoch="$SOURCE_EPOCH" \
    --state-dir="$ARBEIT/state" \
    --repo="$REPO" "$BAUM" "$BAU_MANIFEST"
flatpak run --user --filesystem="$WURZEL" org.flatpak.Builder \
    --run "$BAUM" "$BAU_MANIFEST" \
    magnolie-organizer --language en --help | grep -q 'Usage:'
rm -f "$AUSGABE"
flatpak build-bundle --arch=x86_64 \
    --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo \
    "$REPO" "$AUSGABE" "$APP_ID" "$ZWEIG"
test -s "$AUSGABE"
rm -f "$BAU_MANIFEST"
trap - EXIT HUP INT TERM
printf '%s\n' "Flatpak gebaut: $AUSGABE"
sha256sum "$AUSGABE"
