#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    printf 'Aufruf: %s VM Text\n' "$0" >&2
    exit 2
fi

vm="$1"
text="$2"
for ((index = 0; index < ${#text}; index++)); do
    character="${text:index:1}"
    case "$character" in
        y) key="z" ;;
        z) key="y" ;;
        Y) key="shift-z" ;;
        Z) key="shift-y" ;;
        [a-z0-9]) key="$character" ;;
        [A-Z]) key="shift-${character,,}" ;;
        :) key="shift-dot" ;;
        /) key="shift-7" ;;
        '"') key="shift-2" ;;
        .) key="dot" ;;
        -) key="slash" ;;
        ' ') key="spc" ;;
        *) printf 'Nicht unterstütztes Zeichen: %s\n' "$character" >&2; exit 1 ;;
    esac
    virsh qemu-monitor-command "$vm" --hmp "sendkey $key" >/dev/null
    sleep 0.08
done
