# One Optional KDE DEB

The single user-facing package is `magnolie-organizer-kde_2.0.18_amd64.deb`
for Debian, Ubuntu, Kubuntu and Linux Mint. The separate Fedora 42 package stays
`magnolie-organizer-kde-2.0.18-1.fc42.x86_64.rpm`; it is not embedded in the DEB.
No old-name transitional DEB is built or offered as a download.

## Dormant Native Requirements

The DEB contains one standard-library Python launcher and three small, mutually
incompatible native backends. It does not contain KDE libraries, a server,
accounts, D-Bus policy, autostart entries or additional KDE permissions.

| Internal profile | Existing stack | Required genuine core ABI Provide | Rootfs override |
| --- | --- | --- | --- |
| ubuntu24.04 | Ubuntu/Kubuntu 24.04, Mint 22, Qt5/KF5 | libkpim5akonadicore5-23.08 | MAGNOLIE_AKONADI_BUILD_ROOTFS |
| debian13 | Debian 13, Qt6/KF6 | libkpim6akonadicore6-24.12 | MAGNOLIE_AKONADI_DEBIAN13_ROOTFS |
| ubuntu26.04 | Ubuntu/Kubuntu 26.04, Qt6/KF6 | libkpim6akonadicore6-25.12 | MAGNOLIE_AKONADI_UBUNTU2604_ROOTFS |

Defaults and exact native development requirements are in `profiles.py`.
The launcher uses installed, fully configured dpkg records, actual versioned or
unversioned Provides, Debian version comparison, architecture, every generated
shlibdeps requirement, and the complete recursive Depends/Pre-Depends closure.
The two Qt6 core libraries having the same SONAME is deliberately insufficient.
No fake ABI Provides, shlibs overrides or foreign-library copies are used.

The existing server package is required before backend selection. A nonactivating
`--self-check` with immediate ELF relocation checks then verifies the actual native
library closure. `/usr/libexec/magnolie-organizer/magnolie-akonadi-helper --check`
only reports readiness and never opens a KDE session or starts a server.
Ordinary JSON requests retain the same entry path and protocol. A missing service
is rejected before a native job is created. Unsupported/missing/ambiguous stacks
return nonzero with `{"ok":false,"error":"..."}`, never a successful empty snapshot.
Existing configured KDE resources and calendar/contact serializer plugins remain
necessary for real data operations; load/payload failures are errors, not data.

Only Python, the base C library and Organizer's baseline are unconditional Depends.
KDE PIM is Suggests, not Depends or Recommends. This is a deliberate optional-plugin
packaging model, not a DEB with silently stripped dependencies: each backend retains
`manifest.json`, `build-audit.json` (real shlibdeps output, native library hashes and
package-owned dependency closure), and `build-packages.tsv` under
`/usr/libexec/magnolie-organizer/kde/PROFILE/`. The launcher enforces the requirements
before execution; the dependency manager does not install the dormant plugin stacks.

## Build And Source

From the Organizer source root:

```sh
python3 werkzeuge/kde_deb_bauen.py /tmp/opencode/kde-one-component
```

The build is sequential, affinity-limited to two CPUs, CPUQuota=200%, MemoryMax=6G,
MemorySwapMax=0, and low priority. It requires working user systemd scopes and bwrap.
Each rootfs is read-only, offline and namespace-isolated with a temporary HOME and
no host session bus. It must contain genuine configured distro development packages,
dpkg/shlibs metadata and the existing server package. `dpkg-checkbuilddeps` is run
inside every rootfs. No VM, production aggregate build or publication is involved.
Only this native component is frozen; concurrent JS/UI edits are unrelated.

Expected component output:

```text
magnolie-organizer-kde_2.0.18_amd64.deb
magnolie-organizer-kde_2.0.18.dsc
magnolie-organizer-kde_2.0.18.tar.xz
kde-2.0.18-provenance.json
```

One coherent `3.0 (native)` source contains `build.py`, `profiles.py`, the launcher,
CMake/C++ sources, tests and Debian rules. After `dpkg-source -x ...dsc`, run
`python3 build.py OUTPUT` with the three prepared rootfs overrides; alternatively
`dpkg-buildpackage -b -us -uc` uses the same `build.py --payload` recipe. The host
Build-Depends are orchestration tools, not a misleading union of incompatible KDE
development packages. Native development requirements are separately checked in
each rootfs. Both full builds must produce byte-identical single DEBs. The same
extracted final DEB is checked in all three rootfs environments. Provenance binds
the source (including recipe and tests), DSC/tar, DEB and all three audits.

These component checks are NOT installed/live KDE data acceptance. Release checks
`kdeUbuntu2404Mint22`, `kdeDebian13`, `kdeUbuntu2604` must all bind the SAME final DEB
SHA-256 and provide separate native installation, configured-resource and data logs.
Fresh aggregate provenance and user usability approval remain required for release.

## Upgrade Policy

Users with the released `magnolie-organizer-akonadi` 1.0.0 explicitly install the
new KDE package (`sudo apt install ./magnolie-organizer-kde_2.0.18_amd64.deb`).
Versioned Provides/Breaks/Replaces lets apt/dpkg remove the old package and transfer
the existing helper path. Without a transitional package/repository policy, do not
claim that `apt upgrade` alone discovers a package rename.

The previously distributed `2.0.18.ubuntu24.04`, `2.0.18.debian13` and
`2.0.18.ubuntu26.04` files were unreleased test candidates. Dpkg orders ALL of them
above unsuffixed `2.0.18`. Their replacement is therefore an explicit tester-approved
downgrade, never an automatic update. Inspect `dpkg-query -W magnolie-organizer-kde
magnolie-organizer-akonadi` first. A tester who chooses replacement can use
`sudo apt install --allow-downgrades ./magnolie-organizer-kde_2.0.18_amd64.deb`;
if a suffixed transitional package is installed, explicitly remove that transitional
package in the same apt transaction (`magnolie-organizer-akonadi-`). Review the apt
transaction before confirming. No builder or launcher executes these operations.
