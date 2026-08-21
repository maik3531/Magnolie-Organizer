#!/usr/bin/env bash
set -euo pipefail

projekt="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$projekt"

if [[ $# -gt 1 || (${1:-} != "" && ${1:-} != "--signing-only") ]]; then
    printf 'Aufruf: %s [--signing-only]\n' "$0" >&2
    exit 2
fi

pruefe_hash() {
    local erwartet="$1"
    local datei="$2"

    if [[ ! -f "$datei" ]]; then
        printf 'Release abgewiesen: %s fehlt.\n' "$datei" >&2
        exit 1
    fi

    local aktuell
    aktuell="$(sha256sum "$datei" | cut -d ' ' -f 1)"
    if [[ "$aktuell" != "$erwartet" ]]; then
        printf 'Release abgewiesen: %s wurde gegenueber dem freigegebenen Stand geaendert.\n' "$datei" >&2
        exit 1
    fi
}

pruefe_hash "3b6b8df392b92f86332d907707f3d952a32c8d6e1fedabafe2b5ec3d933a78c4" "gradle/wrapper/gradle-wrapper.properties"
pruefe_hash "b3c9e04f900034d812ec871ca04ebff3db7794016305588d6ee21b11a0c6a681" "gradle/verification-metadata.xml"
pruefe_hash "e58bb2ed80db9f829601a658d7c33b9802eb7d2191c31e79c28e01f14c225926" "settings-gradle.lockfile"
pruefe_hash "b843e0bc23b5249f36479a179a185dfbd532661a49ba03a71f21a5655b1a0e2c" "app/gradle.lockfile"

if grep -Eiq '=[[:space:]]*"[^" ]*(latest|snapshot|\+|\*|[.]x|\[|\]|\(|\))([^" ]*)"' "gradle/libs.versions.toml"; then
    printf 'Release abgewiesen: Der Versionskatalog enthaelt eine dynamische Version.\n' >&2
    exit 1
fi

if grep -Eiq '"[^" ]+:[^" ]+:[^" ]*(latest|snapshot|\+|\*|[.]x|\[|\]|\(|\))[^" ]*"' \
    "build.gradle.kts" "settings.gradle.kts" "app/build.gradle.kts"; then
    printf 'Release abgewiesen: Ein Gradle-Skript enthaelt eine dynamische Version.\n' >&2
    exit 1
fi

gradle_parameter=(
    --offline
    --no-daemon
    --dependency-verification strict
)

# Diese separate Phase muss erfolgreich sein, bevor irgendein Release-Build startet.
./gradlew "${gradle_parameter[@]}" pruefeReleaseSigningKonfiguration
if [[ ${1:-} == "--signing-only" ]]; then
    exit 0
fi

./gradlew \
    "${gradle_parameter[@]}" \
    clean testReleaseUnitTest lintRelease \
    assembleDebug assembleRelease assembleReleaseAndroidTest assembleFixture

sdk="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
apksigner="$(printf '%s\n' "$sdk"/build-tools/*/apksigner | sort -V | tail -n 1)"
release_apk="app/build/outputs/apk/release/app-release.apk"
if [[ -z "${MAGNOLIE_RELEASE_CERT_SHA256:-}" ]]; then
    printf 'Release abgewiesen: MAGNOLIE_RELEASE_CERT_SHA256 fehlt.\n' >&2
    exit 1
fi
fingerprint() {
    "$apksigner" verify --print-certs "$1" |
        sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | head -n 1
}
[[ "$(fingerprint "$release_apk")" == "${MAGNOLIE_RELEASE_CERT_SHA256,,}" ]] || {
    printf 'Release abgewiesen: unerwarteter Produktionsfingerabdruck.\n' >&2; exit 1;
}
if [[ -n "${MAGNOLIE_PREDECESSOR_APK:-}" ]]; then
    [[ -n "${MAGNOLIE_PREDECESSOR_CERT_SHA256:-}" ]] || {
        printf 'Vorgaenger-APK angegeben, aber MAGNOLIE_PREDECESSOR_CERT_SHA256 fehlt.\n' >&2; exit 1;
    }
    [[ -s "$MAGNOLIE_PREDECESSOR_APK" ]] || { printf 'Vorgaenger-APK fehlt.\n' >&2; exit 1; }
    [[ "$(fingerprint "$MAGNOLIE_PREDECESSOR_APK")" == "${MAGNOLIE_PREDECESSOR_CERT_SHA256,,}" ]] || {
        printf 'Vorgaenger-APK hat nicht den zwingend angegebenen Fingerabdruck.\n' >&2; exit 1;
    }
    [[ "${MAGNOLIE_PREDECESSOR_CERT_SHA256,,}" == "$(fingerprint "$release_apk")" ]] || {
        printf 'Vorgaenger-APK hat nicht denselben Produktionsfingerabdruck.\n' >&2; exit 1;
    }
fi
./werkzeuge/installed-smoke.sh
