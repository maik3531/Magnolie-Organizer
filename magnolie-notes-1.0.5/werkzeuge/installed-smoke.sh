#!/usr/bin/env bash
set -euo pipefail

projekt="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sdk="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
adb="$sdk/platform-tools/adb"
emulator="$sdk/emulator/emulator"
paket="io.gitlab.maik3531.magnolienotes"
tmp="$projekt/app/build/tmp/installed-smoke"
release="$projekt/app/build/outputs/apk/release/app-release.apk"
fixture="$projekt/app/build/outputs/apk/fixture/app-fixture.apk"
android_test="$projekt/app/build/outputs/apk/androidTest/release/app-release-androidTest.apk"

[[ -x "$adb" ]] || { printf 'Installed-Smoke: adb fehlt.\n' >&2; exit 1; }
[[ -s "$release" && -s "$fixture" && -s "$android_test" ]] || {
    printf 'Installed-Smoke: Release-, Fixture- oder Release-Instrumentation-APK fehlt.\n' >&2; exit 1;
}

serial="${MAGNOLIE_ANDROID_TEST_SERIAL:-}"
emulator_pid=""
dediziert=0
if [[ -z "$serial" && -n "${MAGNOLIE_ANDROID_TEST_AVD:-}" ]]; then
    avd="$MAGNOLIE_ANDROID_TEST_AVD"
    "$emulator" -list-avds | grep -Fxq "$avd" || {
        printf 'Installed-Smoke: dediziertes AVD nicht vorhanden.\n' >&2; exit 1;
    }
    port="${MAGNOLIE_ANDROID_TEST_EMULATOR_PORT:-5580}"
    "$emulator" -avd "$avd" -port "$port" -no-snapshot-save -no-window >"$projekt/app/build/tmp/emulator.log" 2>&1 &
    emulator_pid=$!
    serial="emulator-$port"
    dediziert=1
elif [[ -z "$serial" ]]; then
    printf 'Installed-Smoke: MAGNOLIE_ANDROID_TEST_SERIAL oder MAGNOLIE_ANDROID_TEST_AVD ist erforderlich.\n' >&2
    exit 1
elif [[ "${MAGNOLIE_ANDROID_TEST_DEVICE_CONFIRMED:-0}" != 1 ]]; then
    printf 'Installed-Smoke: ein physisches/externes Geraet wird nur mit MAGNOLIE_ANDROID_TEST_DEVICE_CONFIRMED=1 veraendert.\n' >&2
    exit 1
fi
trap '[[ -z "$emulator_pid" ]] || kill "$emulator_pid" 2>/dev/null || true' EXIT
"$adb" -s "$serial" wait-for-device
for _ in {1..120}; do
    [[ "$("$adb" -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]] && break
    sleep 1
done
[[ "$("$adb" -s "$serial" shell getprop sys.boot_completed | tr -d '\r')" == 1 ]] || {
    printf 'Installed-Smoke: Testgeraet wurde nicht bereit.\n' >&2; exit 1;
}
mkdir -p "$tmp"

apksigner="$(printf '%s\n' "$sdk"/build-tools/*/apksigner | sort -V | tail -n 1)"
debug_store="${HOME}/.android/debug.keystore"
[[ -s "$debug_store" ]] || { printf 'Installed-Smoke: lokaler Debug-Keystore fehlt.\n' >&2; exit 1; }
test_release="$tmp/app-release-test-signed.apk"
debug_android_test="$tmp/app-release-androidTest-debug-signed.apk"
"$apksigner" sign --ks "$debug_store" --ks-pass pass:android --key-pass pass:android \
    --ks-key-alias androiddebugkey --out "$test_release" "$release"
"$apksigner" sign --ks "$debug_store" --ks-pass pass:android --key-pass pass:android \
    --ks-key-alias androiddebugkey --out "$debug_android_test" "$android_test"

smoke_start() {
    local name="$1"
    "$adb" -s "$serial" shell pm grant "$paket" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
    "$adb" -s "$serial" shell am force-stop "$paket"
    "$adb" -s "$serial" logcat -c
    local startzeit uid pid
    startzeit="$(date --iso-8601=ns)"
    uid="$("$adb" -s "$serial" shell dumpsys package "$paket" | sed -n 's/^[[:space:]]*appId=\([0-9]*\).*/\1/p' | head -n 1 | tr -d '\r')"
    "$adb" -s "$serial" shell monkey -p "$paket" -c android.intent.category.LAUNCHER 1 >/dev/null
    sleep 5
    pid="$("$adb" -s "$serial" shell pidof "$paket" | tr -d '\r')"
    [[ "$pid" =~ ^[0-9]+$ && "$uid" =~ ^[0-9]+$ ]]
    printf 'start=%s\npid=%s\nuid=%s\nserial=%s\n' "$startzeit" "$pid" "$uid" "$serial" >"$tmp/$name-process.txt"
    "$adb" -s "$serial" logcat --pid="$pid" -d >"$tmp/$name-logcat.txt"
    ! grep -Eiq 'FATAL EXCEPTION|ANR in io[.]gitlab[.]maik3531[.]magnolienotes' "$tmp/$name-logcat.txt"
    "$adb" -s "$serial" shell dumpsys activity activities >"$tmp/$name-activity.txt"
    grep -Eq 'mResumedActivity.*io[.]gitlab[.]maik3531[.]magnolienotes/[.]MainActivity|topResumedActivity=.*io[.]gitlab[.]maik3531[.]magnolienotes/[.]MainActivity' "$tmp/$name-activity.txt"
    "$adb" -s "$serial" shell dumpsys package "$paket" >"$tmp/$name-package.txt"
    grep -Fq "appId=$uid" "$tmp/$name-package.txt"
}

instrumentiere() {
    local name="$1"
    local test_apk="$2"
    "$adb" -s "$serial" uninstall "$paket.test" >/dev/null 2>&1 || true
    "$adb" -s "$serial" install -r "$test_apk" >/dev/null
    "$adb" -s "$serial" logcat -c
    "$adb" -s "$serial" shell am instrument -r -w \
        "$paket.test/$paket.MagnolieTestRunner" >"$tmp/$name-instrumentation.txt"
    "$adb" -s "$serial" logcat -d >"$tmp/$name-instrumentation-logcat.txt"
    grep -Fq 'INSTRUMENTATION_RESULT: failures=0' "$tmp/$name-instrumentation.txt"
    grep -Fq 'INSTRUMENTATION_RESULT: numtests=8' "$tmp/$name-instrumentation.txt"
}

# Ein dediziertes AVD darf verwaltet werden; externe/physische Geraete wurden oben bestaetigt.
"$adb" -s "$serial" uninstall "$paket.test" >/dev/null 2>&1 || true
"$adb" -s "$serial" uninstall "$paket" >/dev/null 2>&1 || true
sleep 2
"$adb" -s "$serial" install "$release" >/dev/null
smoke_start frisch

"$adb" -s "$serial" uninstall "$paket" >/dev/null
sleep 2
if [[ -n "${MAGNOLIE_PREDECESSOR_APK:-}" ]]; then
    "$adb" -s "$serial" install "$MAGNOLIE_PREDECESSOR_APK" >/dev/null
    smoke_start vorgaenger
    "$adb" -s "$serial" install -r "$release" >/dev/null
    upgrade_test="$android_test"
else
    "$adb" -s "$serial" install "$fixture" >/dev/null
    smoke_start vorgaenger-fixture
    "$adb" -s "$serial" install -r "$test_release" >/dev/null
    upgrade_test="$debug_android_test"
fi
smoke_start upgrade
instrumentiere upgrade "$upgrade_test"

"$adb" -s "$serial" uninstall "$paket" >/dev/null
sleep 2
"$adb" -s "$serial" install "$release" >/dev/null
smoke_start r8
"$adb" -s "$serial" uninstall "$paket.test" >/dev/null 2>&1 || true
ANDROID_SERIAL="$serial" ./gradlew --offline --no-daemon --dependency-verification strict connectedReleaseAndroidTest \
    >"$tmp/connectedReleaseAndroidTest.txt"
grep -Eq 'BUILD SUCCESSFUL' "$tmp/connectedReleaseAndroidTest.txt"

printf 'Installed-Smoke erfolgreich; Protokolle: %s (AVD=%s)\n' "$tmp" "$dediziert"
