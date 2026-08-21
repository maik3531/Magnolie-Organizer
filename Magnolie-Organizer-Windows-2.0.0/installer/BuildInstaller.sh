#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${MAGNOLIE_OFFICIAL_RELEASE:-}" != 1 ]] || { printf 'Cross-Installer verweigert die Official-Umgebung.\n' >&2; exit 1; }
for signing_name in MAGNOLIE_SIGNTOOL MAGNOLIE_SIGN_CERTIFICATE MAGNOLIE_SIGN_PASSWORD MAGNOLIE_SIGN_PUBLISHER MAGNOLIE_TIMESTAMP_URL; do
  [[ -z "${!signing_name:-}" ]] || { printf 'Cross-Installer verweigert Signierumgebung: %s\n' "$signing_name" >&2; exit 1; }
done
version="$(dotnet msbuild "$root/MagnolieOrganizer.Windows.csproj" -nologo -getProperty:Version | tr -d '\r' | tail -n 1)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf 'Ungültige MSBuild-Version: %s\n' "$version" >&2; exit 1; }
[[ -f "$root/Ausgabe/Magnolie Organizer.exe" ]] || { printf 'Zuerst die Windows-Ausgabe bauen.\n' >&2; exit 1; }
marker="$root/Ausgabe/WINDOWS-RUNTIME-UNVERIFIED.txt"
expected_marker=$'windowsRuntimeVerified=false\nwindowsVmValidationRequired=true\nartifactTrust=UNSIGNED\n'
[[ -f "$marker" && "$(cat "$marker"; printf x)" == "${expected_marker}x" ]] || { printf 'Ausgabe besitzt keinen exakten Cross-Runtime-Marker.\n' >&2; exit 1; }
[[ "${MAGNOLIE_CONTRIBUTOR_HASH:-}" =~ ^[0-9a-fA-F]{64}$ ]] || { printf 'MAGNOLIE_CONTRIBUTOR_HASH fehlt oder ist ungültig.\n' >&2; exit 1; }

if command -v node >/dev/null 2>&1; then js_runtime=node; elif command -v bun >/dev/null 2>&1; then js_runtime=bun; else
  printf 'Node.js oder Bun fehlt.\n' >&2; exit 1
fi
"$js_runtime" "$root/installer/VerifyBuildConfig.js" "$root/Ausgabe/build-config.json"

if [[ -n "${MAKENSIS:-}" ]]; then
  makensis="$MAKENSIS"
elif command -v makensis >/dev/null 2>&1; then
  makensis="$(command -v makensis)"
elif [[ -x /tmp/opencode/nsis-root/usr/bin/makensis ]]; then
  makensis=/tmp/opencode/nsis-root/usr/bin/makensis
  export NSISDIR="${NSISDIR:-/tmp/opencode/nsis-root/usr/share/nsis}"
else
  printf 'Lokales makensis wurde nicht gefunden.\n' >&2; exit 1
fi

installer_name="Magnolie-Organizer-Windows-$version-Setup-x64.exe"
live="$root/$installer_name"
stage="$root/.${installer_name}.staging-$$.exe"
record_stage="$root/.${installer_name}.staging-$$.build.json"
manifest_dir="$(mktemp -d)"
trap 'rm -f "$stage" "$record_stage"; rm -rf "$manifest_dir"' EXIT
"$js_runtime" "$root/installer/GenerateInstallManifests.js" "$root/Ausgabe" "$manifest_dir"
"$makensis" -V3 -DPRODUCT_VERSION="$version" -DPUBLISH_DIR="$root/Ausgabe" -DCORE_MANIFEST="$manifest_dir/core.manifest" -DHANDBOOK_MANIFEST="$manifest_dir/handbook.manifest" -DOUTPUT_FILE="$stage" -DINSTALLER_FILENAME="$installer_name" "$root/installer/MagnolieOrganizer.nsi"
[[ -s "$stage" ]] || { printf 'NSIS erzeugte keinen Installer.\n' >&2; exit 1; }
"$js_runtime" "$root/installer/CreateInstallerBuildRecord.js" "$stage" "$record_stage" "$installer_name"
"$js_runtime" "$root/installer/AuditInstaller.js" "$stage" "$root/Ausgabe" "$installer_name" "$record_stage"
bash "$root/installer/PublishInstaller.sh" "$root" "$stage" "$record_stage" "$root/Ausgabe" "$installer_name" "$js_runtime" "$root/installer/AuditInstaller.js"
checksum="$(sha256sum "$live")"
printf '%s  %s\nBuildrecord: %s\n' "${checksum%% *}" "$installer_name" "$(basename "$live.build.json")"
