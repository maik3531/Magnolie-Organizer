#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(perl -ne 'print $1 if /<Version>([0-9]+\.[0-9]+\.[0-9]+)<\/Version>/' "$root/Directory.Build.props")"
installer="$root/Magnolie-Organizer-Windows-$version-Setup-x64.exe"
output="${1:-$root/vm/Magnolie-Installer-Test.iso}"

[[ -f "$installer" ]] || { printf 'Installer fehlt: %s\n' "$installer" >&2; exit 1; }
xorriso -as mkisofs -iso-level 3 -J -R -V MAGNOLIE_TEST -o "$output" -graft-points \
  "Autounattend.xml=$root/vm/Autounattend.xml" \
  "StartTest.ps1=$root/vm/TestInstallerUpdate.ps1" \
  "RunInstallerTest.cmd=$root/vm/RunInstallerTest.cmd" \
  "Magnolie.Test=$root/vm/Magnolie.Test" \
  "Magnolie-Organizer-Windows-$version-Setup-x64.exe=$installer"
sha256sum "$output"
