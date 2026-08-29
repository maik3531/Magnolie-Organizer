#!/usr/bin/env bash
set -euo pipefail

projekt="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
testdaten="$(mktemp -d)"
trap 'rm -rf "$testdaten"' EXIT

passwort='nur-test-passwort'
produktions_keystore="$testdaten/produktion.jks"
debug_keystore="$testdaten/debug.jks"

keytool -genkeypair -keystore "$produktions_keystore" -storepass "$passwort" \
    -alias produktion -keypass "$passwort" -dname 'CN=Magnolie Release Test,O=Magnolie,C=DE' \
    -keyalg RSA -validity 1 >/dev/null 2>&1
keytool -genkeypair -keystore "$debug_keystore" -storepass "$passwort" \
    -alias androiddebugkey -keypass "$passwort" -dname 'CN=Android Debug,O=Android,C=US' \
    -keyalg RSA -validity 1 >/dev/null 2>&1

schreibe_properties() {
    local ziel="$1"
    local keystore="$2"
    local alias="$3"
    printf 'storeFile=%s\nstorePassword=%s\nkeyAlias=%s\nkeyPassword=%s\n' \
        "$keystore" "$passwort" "$alias" "$passwort" > "$ziel"
}

erwarte_ablehnung() {
    local properties="$1"
    local protokoll="$testdaten/abweisung.log"
    if MAGNOLIE_SCHLUESSEL_PROPERTIES="$properties" \
        "$projekt/werkzeuge/release-gate.sh" --signing-only >"$protokoll" 2>&1; then
        printf '%s\n' 'Signing-Gate hat eine ungueltige Konfiguration akzeptiert.' >&2
        exit 1
    fi
    if grep -Fq "$passwort" "$protokoll"; then
        printf '%s\n' 'Signing-Gate hat Zugangsdaten ausgegeben.' >&2
        exit 1
    fi
}

produktion_properties="$testdaten/produktion.properties"
schreibe_properties "$produktion_properties" "$produktions_keystore" produktion
MAGNOLIE_SCHLUESSEL_PROPERTIES="$produktion_properties" \
    "$projekt/werkzeuge/release-gate.sh" --signing-only >/dev/null

erwarte_ablehnung "$testdaten/nicht-vorhanden.properties"

fehlender_keystore_properties="$testdaten/fehlender-keystore.properties"
schreibe_properties "$fehlender_keystore_properties" "$testdaten/nicht-vorhanden.jks" produktion
erwarte_ablehnung "$fehlender_keystore_properties"

debug_properties="$testdaten/debug.properties"
schreibe_properties "$debug_properties" "$debug_keystore" androiddebugkey
erwarte_ablehnung "$debug_properties"

printf '%s\n' 'Release-Signing-Gate: Positiv- und Negativtests erfolgreich.'
