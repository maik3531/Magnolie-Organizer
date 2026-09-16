"""Internal build/ABI profiles, never separate download choices."""
PROFILES = {
    "ubuntu24.04": {"label": "KDE integration - Ubuntu 24.04 / Linux Mint 22 (Qt5/KF5)",
        "os": "ubuntu", "version": "24.04", "profile": "", "qt": 5,
        "abi": "libkpim5akonadicore5-23.08",
        "env": "MAGNOLIE_AKONADI_BUILD_ROOTFS",
        "rootfs": "/tmp/opencode/ubuntu-noble-akonadi-rootfs"},
    "debian13": {"label": "KDE integration - Debian 13 (Qt6/KF6)",
        "os": "debian", "version": "13", "profile": "pkg.magnolie.kf6", "qt": 6,
        "abi": "libkpim6akonadicore6-24.12",
        "env": "MAGNOLIE_AKONADI_DEBIAN13_ROOTFS",
        "rootfs": "/tmp/opencode/debian-trixie-akonadi-rootfs"},
    "ubuntu26.04": {"label": "KDE integration - Ubuntu / Kubuntu 26.04 (Qt6/KF6)",
        "os": "ubuntu", "version": "26.04", "profile": "pkg.magnolie.kf6", "qt": 6,
        "abi": "libkpim6akonadicore6-25.12",
        "env": "MAGNOLIE_AKONADI_UBUNTU2604_ROOTFS",
        "rootfs": "/tmp/opencode/ubuntu-resolute-akonadi-rootfs"},
}


def artifacts(version, arch="amd64"):
    return [f"magnolie-organizer-kde_{version}_{arch}.deb",
            f"magnolie-organizer-kde_{version}.dsc",
            f"magnolie-organizer-kde_{version}.tar.xz",
            f"kde-{version}-provenance.json"]


def build_depends(target):
    qt = PROFILES[target]["qt"]
    return ("cmake, g++, binutils, dpkg-dev, extra-cmake-modules, " +
            ("qtbase5-dev, libkf5akonadi-dev, libkf5calendarcore-dev, libkf5contacts-dev"
             if qt == 5 else "qt6-base-dev, libakonadi-dev, libkf6calendarcore-dev, libkf6contacts-dev"))
