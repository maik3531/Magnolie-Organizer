#!/usr/bin/env python3
"""Refs #121 #783: read-only Mac/VM capability inventory, never a test-pass claim.

No installs, modules, machines, permissions, accounts or system settings change.
The report contains platform/tool facts, not usernames, network addresses,
credentials, personal files or account identities.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess


def text(path):
    try:
        return Path(path).read_text()
    except (OSError, UnicodeError):
        return ""


def command(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=10, check=False)
        return result.stdout.strip()[:4096] if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def report(name):
    system, machine = platform.system(), platform.machine()
    page_size = os.sysconf("SC_PAGE_SIZE")
    binaries = {tool: bool(shutil.which(tool)) for tool in
                ["swift", "xcrun", "codesign", "qemu-system-x86_64", "qemu-system-aarch64", "docker", "tart"]}
    capabilities, no_new_privileges, seccomp = None, None, None
    if system == "Linux":
        status = dict(line.split(":", 1) for line in text("/proc/self/status").splitlines() if ":" in line)
        capabilities = int(status["CapEff"].strip(), 16) if status.get("CapEff") else None
        no_new_privileges = status.get("NoNewPrivs", "").strip() or None
        seccomp = status.get("Seccomp", "").strip() or None
    cpu = text("/proc/cpuinfo").lower()
    features = set()
    for line in cpu.splitlines():
        if line.startswith(("flags", "features")) and ":" in line:
            features.update(line.split(":", 1)[1].split())
    memory_limit = text("/sys/fs/cgroup/memory.max").strip()
    memory_limit = int(memory_limit) if memory_limit.isdecimal() else None
    sys_module = bool(capabilities & (1 << 16)) if capabilities is not None else None
    modules_disabled = text("/proc/sys/kernel/modules_disabled").strip() or None
    xnu_blockers = []
    if system != "Linux": xnu_blockers.append("Linux host required")
    if machine not in ("aarch64", "arm64"): xnu_blockers.append("arm64 host required; this host is " + machine)
    if page_size != 4096: xnu_blockers.append("4 KiB Linux pages required")
    if machine in ("aarch64", "arm64") and not {"paca", "pacg"}.issubset(features):
        xnu_blockers.append("Required PAC features were not established")
    if system == "Linux" and sys_module is not True: xnu_blockers.append("No effective CAP_SYS_MODULE")
    if modules_disabled == "1": xnu_blockers.append("Kernel module loading disabled")
    if memory_limit is not None and memory_limit < 16 * 1024 ** 3:
        xnu_blockers.append("Container memory limit below the documented 16 GiB host requirement")
    frameworks = {}
    if system == "Darwin":
        for framework in ["AppKit", "WebKit", "EventKit", "Contacts", "Security"]:
            directory = Path("/System/Library/Frameworks", framework + ".framework")
            metadata = {}
            try:
                metadata = plistlib.loads((directory / "Resources/Info.plist").read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                pass
            frameworks[framework] = {"present": directory.is_dir(),
                "bundleVersion": metadata.get("CFBundleVersion"),
                "shortVersion": metadata.get("CFBundleShortVersionString")}
    sdk_version = command(["xcrun", "--sdk", "macosx", "--show-sdk-version"]) if system == "Darwin" else None
    swift_version = command(["swift", "--version"]) if binaries["swift"] else None
    native = system == "Darwin" and bool(sdk_version and swift_version) and all(binaries[name] for name in ["swift", "xcrun", "codesign"]) and all(
        frameworks.get(name, {}).get("present") for name in ["AppKit", "WebKit", "EventKit", "Contacts", "Security"])
    return {
        "schema": 1, "observedAtUTC": datetime.now(timezone.utc).isoformat(), "environment": name,
        "system": system, "architecture": machine, "kernelRelease": platform.release(), "pageBytes": page_size,
        "toolsAvailable": binaries,
        "linux": {"effectiveCapabilities": format(capabilities, "016x") if capabilities is not None else None,
                  "hasCAP_SYS_MODULE": sys_module, "noNewPrivileges": no_new_privileges, "seccompMode": seccomp,
                  "modulesDisabled": modules_disabled, "cgroupMemoryLimitBytes": memory_limit,
                  "kvmDevicePresent": Path("/dev/kvm").exists(),
                  "kvmDeviceReadWrite": os.access("/dev/kvm", os.R_OK | os.W_OK)},
        "apple": {"productVersion": command(["sw_vers", "-productVersion"]) if system == "Darwin" else None,
                  "productBuild": command(["sw_vers", "-buildVersion"]) if system == "Darwin" else None,
                  "sdkVersion": sdk_version,
                  "swiftVersion": swift_version,
                  "frameworks": frameworks, "nativeBuildPrerequisitesObserved": native},
        "xnulinux": {"reviewedCommit": "d9b9bcba651c2da505f535524e02e2d9d309835e",
                     "observedBlockers": xnu_blockers,
                     "remainingPrerequisites": ["Matching kernel headers and accepted module load policy", "Reserved contiguous memory",
                        "Matching macOS system disk and kernel collection", "Required build toolchain", "Boot, GUI and API probes"],
                     "bootAttempted": False},
        "nativeMagnolieTestsExecuted": False, "appleAccountsTested": False,
        "installationOrPermissionChangeAttempted": False,
        "meaning": "Observed prerequisites only. A VM, tool or framework being present is not a successful application test."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="Magnolie-Organizer einrichten")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-native-build", action="store_true")
    arguments = parser.parse_args()
    value = report(arguments.name)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        # Existing receipts must not silently become evidence of a new run.
        with arguments.output.open("x") as destination:
            destination.write(encoded)
    else:
        print(encoded, end="")
    if arguments.require_native_build and not value["apple"]["nativeBuildPrerequisitesObserved"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
