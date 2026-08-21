#!/usr/bin/env bash
set -euo pipefail

[[ $# == 7 ]] || { printf 'PublishInstaller.sh erwartet root, Installer-/Record-Staging, Publishbaum, Name, JS-Laufzeit und Audit.\n' >&2; exit 2; }
root=$1
stage=$2
record_stage=$3
publish=$4
expected_name=$5
js_runtime=$6
audit_script=$7
live="$root/$expected_name"
record_live="$live.build.json"
quarantine="$(mktemp -d "$root/.installer-quarantine.XXXXXX")"
recovery="$(mktemp -d "$root/.installer-recovery.XXXXXX")"
declare -a old_sources=() old_names=()
installer_installed=0
record_installed=0

rollback() {
  local status=0 index source name saved
  if ((record_installed)) && [[ -e "$record_live" ]]; then rm -f -- "$record_live" || status=1; fi
  if ((installer_installed)) && [[ -e "$live" ]]; then rm -f -- "$live" || status=1; fi
  for ((index=${#old_sources[@]}-1; index>=0; index--)); do
    source=${old_sources[index]}
    name=${old_names[index]}
    saved="$quarantine/$name"
    [[ -e "$saved" ]] || saved="$recovery/$name"
    if [[ -e "$saved" && ! -e "$source" ]]; then mv -- "$saved" "$source" || status=1; fi
  done
  rm -rf -- "$quarantine" "$recovery" || status=1
  return "$status"
}

publish_transaction() {
  local old name
  [[ -s "$stage" && -s "$record_stage" ]] || return 1
  shopt -s nullglob nocaseglob
  old=("$live" "$record_live" "$root"/Magnolie-Organizer-Windows-*-Setup-x64-UNSIGNED.exe)
  shopt -u nocaseglob
  for old in "${old[@]}"; do
    [[ -e "$old" ]] || continue
    name=$(basename "$old")
    mv -- "$old" "$quarantine/$name" || return $?
    old_sources+=("$old")
    old_names+=("$name")
  done
  mv -- "$stage" "$live" || return $?
  installer_installed=1
  mv -- "$record_stage" "$record_live" || return $?
  record_installed=1
  "$js_runtime" "$audit_script" "$live" "$publish" "$expected_name" "$record_live" || return $?
  for name in "${old_names[@]}"; do cp -p -- "$quarantine/$name" "$recovery/$name" || return $?; done
  rm -rf -- "$quarantine" || return $?
  rm -rf -- "$recovery" || return $?
}

failure=0
publish_transaction || failure=$?
if ((failure)); then
  rollback || printf 'Installer-Rollback konnte nicht vollständig abgeschlossen werden.\n' >&2
  exit "$failure"
fi
