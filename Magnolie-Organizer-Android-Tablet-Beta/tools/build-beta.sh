#!/usr/bin/env bash
set -euo pipefail
ROOT="$(dirname "$(dirname "$(realpath "$0")")")"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
if [[ -n "${ANDROID_HOME:-}" && -n "${ANDROID_SDK_ROOT:-}" &&
      "$(realpath -m "$ANDROID_HOME")" != "$(realpath -m "$ANDROID_SDK_ROOT")" ]]; then
    printf '%s\n' 'ANDROID_HOME and ANDROID_SDK_ROOT must identify the same SDK' >&2; exit 2
fi
export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/.local/share/android-sdk}}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$HOME/.gradle}"
export MAGNOLIE_JS_RUNTIME="${MAGNOLIE_JS_RUNTIME:-$HOME/.bun/bin/bun}"
if [[ "${1:-}" == "--readiness" ]]; then
    test -x "$JAVA_HOME/bin/javac"
    test -d "$ANDROID_HOME/platforms/android-35"
    command -v "$MAGNOLIE_JS_RUNTIME"
    command -v flock
    flock -n /tmp/opencode/android-build.lock true
    printf '%s\n' 'Ready for a serialized debug compile. No emulator will be started.'
    exit 0
fi
network=()
if [[ "${1:-}" == "--online" && $# == 1 ]]; then network=(--online)
elif [[ $# != 0 ]]; then printf '%s\n' 'Usage: build-beta.sh [--readiness | --online]' >&2; exit 2
fi
# The Python owner holds all five nonblocking coordination leases and emits
# 30-second progress. The service also contains/reaps Gradle descendants.
exec systemd-run --user --wait --pipe --collect \
    --setenv="MAGNOLIE_JS_RUNTIME=$MAGNOLIE_JS_RUNTIME" \
    --setenv="ANDROID_HOME=$ANDROID_HOME" --setenv="ANDROID_SDK_ROOT=$ANDROID_SDK_ROOT" \
    --setenv="NODE_PATH=${NODE_PATH:-}" \
    --setenv="JAVA_HOME=$JAVA_HOME" --setenv="GRADLE_USER_HOME=$GRADLE_USER_HOME" \
    -p MemoryMax=6G -p MemorySwapMax=0 -p CPUQuota=200% -p RuntimeMaxSec=890 \
    -p TimeoutStopSec=10 -p KillMode=control-group -p UMask=0077 \
    --working-directory="$ROOT" python3 -B tools/offline-checks.py --build "${network[@]}" </dev/null
