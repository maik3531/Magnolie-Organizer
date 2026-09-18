#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Aufruf: %s /pfad/zu/Windows-11.iso [/pfad/zu/Test.iso]\n' "$0" >&2
    exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
windows_iso="$(realpath "$1")"
test_iso="$(realpath "${2:-$root/vm/Magnolie-Windows-Test.iso}")"
disk="$(realpath -m "${MAGNOLIE_VM_DISK:-$root/vm/Magnolie-Windows11.qcow2}")"
results="$(realpath -m "${MAGNOLIE_VM_RESULTS_IMAGE:-$root/vm/Magnolie-Windows-Results.img}")"
name="${MAGNOLIE_VM_NAME:-magnolie-win11-test}"

[[ -f "$windows_iso" ]] || { printf 'Windows-ISO nicht gefunden: %s\n' "$windows_iso" >&2; exit 1; }
[[ -f "$test_iso" ]] || { printf 'Zuerst vm/Create-TestMedia.sh ausführen.\n' >&2; exit 1; }
[[ "$disk" != "$results" ]] || { printf 'VM- und Ergebnisdatenträger müssen verschieden sein.\n' >&2; exit 1; }
for path in "$disk" "$results" "$test_iso"; do
    [[ "$path" != *,* ]] || { printf 'Datenträgerpfade dürfen kein Komma enthalten: %s\n' "$path" >&2; exit 1; }
done
command -v mkfs.vfat >/dev/null || { printf 'mkfs.vfat fehlt.\n' >&2; exit 1; }
command -v mcopy >/dev/null || { printf 'mcopy fehlt.\n' >&2; exit 1; }
command -v parted >/dev/null || { printf 'parted fehlt.\n' >&2; exit 1; }
if virsh dominfo "$name" >/dev/null 2>&1; then
    printf 'Die VM %s ist bereits vorhanden.\n' "$name" >&2
    exit 1
fi
[[ ! -e "$disk" ]] || { printf 'Der VM-Datenträger ist bereits vorhanden: %s\n' "$disk" >&2; exit 1; }
[[ ! -e "$results" ]] || { printf 'Der Ergebnisdatenträger ist bereits vorhanden: %s\n' "$results" >&2; exit 1; }

setfacl -m u:libvirt-qemu:x "$HOME"
setfacl -m u:libvirt-qemu:r "$windows_iso" "$test_iso"
qemu-img create -f qcow2 "$disk" 80G
truncate -s 64M "$results"
results_partition_sector=2048
results_partition_offset="$((results_partition_sector * 512))"
parted --script "$results" mklabel msdos mkpart primary fat32 1MiB 100%
mkfs.vfat -F 32 -h "$results_partition_sector" -n MAGNOLIE \
    --offset="$results_partition_sector" "$results" >/dev/null
marker="$(mktemp)"
trap 'rm -f "$marker"' EXIT
: >"$marker"
mcopy -i "$results@@$results_partition_offset" "$marker" ::MAGNOLIE_RESULTS
setfacl -m u:libvirt-qemu:rw "$disk"
setfacl -m u:libvirt-qemu:rw "$results"

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
    --disk path="$results",format=raw,bus=sata \
    --cdrom "$windows_iso" \
    --disk path="$test_iso",device=cdrom,bus=sata \
    --network network=default,model=e1000e \
    --graphics vnc,listen=127.0.0.1 \
    --video qxl \
    --noautoconsole

virsh set-lifecycle-action "$name" reboot restart --live --config
printf 'VNC-Anzeige: %s\n' "$(virsh domdisplay "$name")"
