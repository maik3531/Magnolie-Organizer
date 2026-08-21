#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(perl -ne 'print $1 if /<Version>([0-9]+\.[0-9]+\.[0-9]+)<\/Version>/' "$root/Directory.Build.props")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf 'Kanonische Version fehlt.\n' >&2; exit 1; }
js_runner="$(command -v node || command -v nodejs || command -v bun || true)"
[[ -n "$js_runner" ]] || { printf 'Node.js, nodejs oder Bun fehlt.\n' >&2; exit 1; }
case "${MAGNOLIE_VM_BRANDING:-}" in
  official)
    [[ "${MAGNOLIE_CONTRIBUTOR_HASH:-}" =~ ^[0-9a-fA-F]{64}$ ]] || { printf 'Offizieller VM-Test benötigt MAGNOLIE_CONTRIBUTOR_HASH.\n' >&2; exit 1; }
    "$js_runner" "$root/installer/VerifyBuildConfig.js" "$root/Ausgabe/build-config.json"
    ;;
  unbranded)
    [[ ! -e "$root/Ausgabe/build-config.json" ]] || { printf 'Unbranded-VM-Test verweigert vorhandene build-config.json.\n' >&2; exit 1; }
    ;;
  *) printf 'MAGNOLIE_VM_BRANDING muss official oder unbranded sein.\n' >&2; exit 1 ;;
esac
staging="${TMPDIR:-/tmp}/magnolie-windows-test-media"
output="${1:-$root/vm/Magnolie-Windows-Test.iso}"

rm -rf "$staging"
mkdir -p "$staging/App"
mkdir -p "$staging/TestFiles"
cp "$root/vm/Autounattend.xml" "$staging/Autounattend.xml"
cp "$root/vm/StartTest.ps1" "$staging/StartTest.ps1"
cp "$root/vm/RunTest.cmd" "$staging/RunTest.cmd"
cp -a "$root/Ausgabe/." "$staging/App/"
printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=' | base64 -d > "$staging/TestFiles/anhang.png"
printf '%s' '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EB//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EB//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EB//2Q==' | base64 -d > "$staging/TestFiles/anhang.jpg"
printf '%s' 'JVBERi0xLjQKMSAwIG9iajw8L1R5cGUvQ2F0YWxvZy9QYWdlcyAyIDAgUj4+ZW5kb2JqCjIgMCBvYmo8PC9UeXBlL1BhZ2VzL0NvdW50IDAvS2lkc1tdPj5lbmRvYmoKdHJhaWxlcjw8L1Jvb3QgMSAwIFI+PgolJUVPRgo=' | base64 -d > "$staging/TestFiles/anhang.pdf"
touch "$staging/Magnolie.Test"
printf '%s\n' "$version" > "$staging/Magnolie.Version"
printf '%s\n' "$MAGNOLIE_VM_BRANDING" > "$staging/Magnolie.Branding"

xorriso -as mkisofs -iso-level 3 -J -R -V MAGNOLIE_TEST -o "$output" "$staging"
sha256sum "$output"
