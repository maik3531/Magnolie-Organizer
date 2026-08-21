#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Aufruf: %s /pfad/zu/Windows-11.iso\n' "$0" >&2
    exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
windows_iso="$(realpath "$1")"
test_iso="$root/vm/Magnolie-Windows-Test.iso"
disk="$root/vm/Magnolie-Windows11.qcow2"
name="magnolie-win11-test"

[[ -f "$windows_iso" ]] || { printf 'Windows-ISO nicht gefunden: %s\n' "$windows_iso" >&2; exit 1; }
[[ -f "$test_iso" ]] || { printf 'Zuerst vm/Create-TestMedia.sh ausführen.\n' >&2; exit 1; }
if virsh dominfo "$name" >/dev/null 2>&1; then
    printf 'Die VM %s ist bereits vorhanden.\n' "$name" >&2
    exit 1
fi
[[ ! -e "$disk" ]] || { printf 'Der VM-Datenträger ist bereits vorhanden: %s\n' "$disk" >&2; exit 1; }

setfacl -m u:libvirt-qemu:x "$HOME"
setfacl -m u:libvirt-qemu:r "$windows_iso" "$test_iso"
qemu-img create -f qcow2 "$disk" 80G
setfacl -m u:libvirt-qemu:rw "$disk"

virt-install --connect qemu:///system \
    --name "$name" \
    --memory 8192 \
    --vcpus 4 \
    --cpu host-passthrough \
    --machine q35 \
    --osinfo win11 \
    --boot uefi \
    --tpm backend.type=emulator,backend.version=2.0,model=tpm-crb \
    --disk path="$disk",format=qcow2,bus=sata \
    --cdrom "$windows_iso" \
    --disk path="$test_iso",device=cdrom,bus=sata \
    --network network=default,model=e1000e \
    --graphics vnc,listen=127.0.0.1 \
    --video qxl \
    --noautoconsole

virsh set-lifecycle-action "$name" reboot restart --live --config
printf 'VNC-Anzeige: %s\n' "$(virsh domdisplay "$name")"
