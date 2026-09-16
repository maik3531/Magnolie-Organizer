# Private Candidate Preparation

These commands are for the operator **after review and the main source freeze**.
They do not authorize publication or manufacture native/user acceptance. Do not
run whole product builds merely because the read-only preflight succeeds.
FREIGABE.md allows unchanged personal v1 approval or explicit delegated-conditional
v2 authorization with private original instructions and a post-test operator record.
A valid delegation requires no further personal stop; no build creates that record.
Further Claude execution is waived for this assignment, not required technical tests.

## Read-Only Preflight

From the canonical release root:

```sh
python3 -B magnolie-organizer-2.0.0/werkzeuge/package_preflight.py --root "$PWD"
```

Exit 1 means that prerequisites or candidate inputs remain incomplete. The JSON
separates actual executable paths, Python dependency visibility, local dependency
roots, GI typelibs, Flatpak runtime files, KDE rootfs metadata and native gates not
executed. It never opens signing properties/keystores: those paths are stat'ed
only. It does not invoke Gradle, private-key signing, an installer, a product or
promotion. Complete Notes inputs trigger read-only `aapt`/`apksigner verify` checks.
Use `--android-sdk`, `--notes-inputs` and `--windows-inputs` for explicit locations.
Presence of an SDK directory alone is not proof of platform 35 or build-tools.
Autodiscovery checks `$XDG_DATA_HOME/android-sdk` and
`$HOME/.local/share/android-sdk` as well as the other listed local locations. It
prefers a complete compile SDK over an earlier adb-only installation. Explicit
`--android-sdk`, `ANDROID_SDK_ROOT` and `ANDROID_HOME` selections are honored in
that order, even when partial; missing components are reported without silently
switching SDKs. Candidate order breaks ties between complete SDKs deterministically.

The existing complete SDK on this machine is `$HOME/.local/share/android-sdk`.
Compile API 35 (`platforms/android-35/android.jar`) is independent of AVD runtime
images: the installed API 34 image is usable for its runtime checks, whereas an
API 35 AVD configuration alone does not install an API 35 system image. The
preflight reports emulator/image presence separately and does not start an AVD.

The current explicit DEB/RPM/Flatpak/AppImage helper lists must equal the current
`bin/magnolie_*.py` inventory. New helpers cannot silently disappear. POT scanning
uses that same installed application's bin prefix and scans all matching modules.
The AppImage includes xgettext and its linuxdeploy ELF closure; RPM requires it;
Flatpak checks its actual GNOME Platform runtime, not only the SDK. The handbook
ships `handbook_data.js`, 19 translated runtime catalogs plus `i18n/en.js` generated
from the five-entry `po/english/protected.po`, and its existing bundled font policy.

## Test Boundaries

Normal Linux source builds run the isolated public background suite, receipt
goldens, phone setup/invitation/Bluetooth/session tests and pure DIN exporter tests.
They do not require .NET, a Windows sibling or LibreOffice rendering. Missing
dependencies and skipped selected background tests are errors. Process-start
budgets cover cold dependency imports; IPC protocol/lease/shutdown deadlines are
not relaxed.

Explicit cross gates remain available and fail if their prerequisites are missing:

```sh
python3 -B magnolie-organizer-2.0.0/pruefungen/run_background_reliability.py --cross-windows
python3 -B -m pytest -q magnolie-organizer-2.0.0/pruefungen/letter_cross_platform.py
python3 -B -m pytest -q magnolie-organizer-2.0.0/pruefungen/pot_cross_platform.py
```

The first requires `MAGNOLIE_DOTNET` and a freshly compiled `MAGNOLIE_RECEIPT_PROBE`
from `pruefungen/receipt-native/ReceiptProbe.csproj` (including its explicit
`BouncyCastlePath` dependency). Rendered letters require `LETTER_DOTNET`, matching
Windows source, LibreOffice, pdftotext and pdftoppm. These are not passed by running
only the public suite. Source archives retain all harnesses, JSON/Markdown contracts
and immutable goldens; binary payloads never include those fixtures.

Android public unit tasks explicitly exclude the four cross-platform test classes
TelefonWlanInvitationTest, TelefonBluetoothSetupTest, BaumReceiptInteropTest and
LiveprobeTest. The same task with `-PmagnolieCrossTests=true` runs those classes
separately. Both selections fail on skipped tests or empty execution. The official
Android release gate runs both selections before installed tests. Instrumentation
and validation runners reject ignored tests, failed assumptions and empty method
execution. Validation application IDs/classes remain forbidden in production APKs.

## Local Tool Environment

```sh
ROOT=/home/maik3531/Downloads/Magnolie-GPT/magnolie-organizer-veroeffentlicht
export DOTNET_ROOT=/tmp/opencode/dotnet-8.0.408
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export ANDROID_SDK_ROOT="$HOME/.local/share/android-sdk"
export PATH="$JAVA_HOME/bin:$DOTNET_ROOT:/home/maik3531/.bun/bin:/tmp/opencode/nsis-root/usr/bin:$PATH"
export NSISDIR=/tmp/opencode/nsis-root/usr/share/nsis
export MAGNOLIE_PYTHON="$(command -v python3)"
export PYTHONPATH="/tmp/opencode/astra-test-python:/tmp/opencode/setup-wlan-python${PYTHONPATH:+:$PYTHONPATH}"
```

The two Python roots above are existing local dependency directories, not bundled
product files. Native distribution builds still require the declared distro
packages. Configure a **complete** `ANDROID_SDK_ROOT` containing platform 35,
apksigner, zipalign and aapt. JDK 17 is required. The operator supplies externally:
`MAGNOLIE_CONTRIBUTOR_HASH`, `MAGNOLIE_SCHLUESSEL_PROPERTIES` and the known public
`MAGNOLIE_RELEASE_CERT_SHA256`. No credential values belong in this document.

## Private Windows Candidate

```sh
WINDOWS_CANDIDATE=$(mktemp -d /tmp/opencode/magnolie-windows-candidate.XXXXXX)
/tmp/opencode/powershell-7.4.13/pwsh -NoProfile \
  -File "$ROOT/Magnolie-Organizer-Windows-2.0.0/build/Build.ps1" \
  -CrossCompile -Destination "$WINDOWS_CANDIDATE"
export MAGNOLIE_WINDOWS_ARTIFACTS="$WINDOWS_CANDIDATE"
```

`-Destination` requires an empty external directory and makes it private. Source
ZIP, ZIP, installer, buildrecord, provenance and flat checksums stay together there;
the existing historical candidate files need not be overwritten. The current
CoreTests program registers 42 groups; the canonical build runs it without a group
filter. No final manifest or release-root checksum is changed by this command.

## Fresh Cross-Test Hosts

When the Android cross gate is required, prepare its test-only hosts from frozen
canonical source, with outputs outside the product source:

```sh
NATIVE_TESTS=$(mktemp -d /tmp/opencode/magnolie-cross-hosts.XXXXXX)
dotnet restore "$ROOT/Magnolie-Organizer-Windows-2.0.0/tests/CoreTests.csproj" \
  --locked-mode -p:BaseIntermediateOutputPath="$NATIVE_TESTS/core-obj/"
dotnet build "$ROOT/Magnolie-Organizer-Windows-2.0.0/tests/CoreTests.csproj" \
  --no-restore -c Release -o "$NATIVE_TESTS/core" \
  -p:BaseIntermediateOutputPath="$NATIVE_TESTS/core-obj/"
dotnet build "$ROOT/magnolie-notes-1.0.13/werkzeuge/ReceiptHost.csproj" \
  -c Release -o "$NATIVE_TESTS/receipt" \
  -p:BaseIntermediateOutputPath="$NATIVE_TESTS/receipt-obj/"
export MAGNOLIE_DOTNET="$DOTNET_ROOT/dotnet"
export PHONE_TEST_DOTNET="$MAGNOLIE_DOTNET"
export PHONE_TEST_WINDOWS_DLL="$NATIVE_TESTS/core/CoreTests.dll"
export MAGNOLIE_RECEIPT_HOST="$NATIVE_TESTS/receipt/ReceiptHost.dll"
export MAGNOLIE_ORGANIZER_QUELLE="$ROOT/magnolie-organizer-2.0.0/bin/magnolie-organizer"
export MAGNOLIE_WLAN_INTEGRATION=1
export MAGNOLIE_BLUETOOTH_INTEGRATION=1
export MAGNOLIE_RECEIPT_INTEROP=1
export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=/tmp/opencode"
unset PHONE_TEST_WINDOWS_REMOTE
```

These are test hosts, not published binaries. Do not substitute an old cached
Debug/CoreTests.dll or include these hosts in the application payload. The WLAN
gate uses owned discovery fixtures; arrange its isolated test network explicitly.

## Private Notes Input

Only after the main coordinator freezes the corrected canonical sources and
explicitly authorizes a production Notes build, with SDK/cache/signing prerequisites
established. The following command **compiles and signs** through canonical Gradle;
it is not part of read-only preflight and must not run while sources are changing.
Use a new directory under an existing private external parent, not a correction copy:

```sh
: "${NOTES_PARENT:?Existing private directory outside canonical source}"
: "${MAGNOLIE_RELEASE_CERT_SHA256:?Independently established public production certificate pin}"
python3 -B "$ROOT/magnolie-organizer-2.0.0/werkzeuge/notes_candidate.py" \
  --root "$ROOT" --android-sdk "$ANDROID_SDK_ROOT" \
  --build-production --gradle "$ROOT/magnolie-notes-1.0.13/gradlew" \
  --destination "$NOTES_PARENT/input"
export MAGNOLIE_NOTES_ARTIFACTS="$NOTES_PARENT/input"
python3 -B "$ROOT/magnolie-organizer-2.0.0/werkzeuge/release_gate.py" notes-inputs \
  --root "$ROOT" --candidate "$MAGNOLIE_NOTES_ARTIFACTS"
```

The runner measures the complete selected Notes source and shared contracts
(SHA-256 and modes) before and after the build. It runs canonical Gradle `clean`,
requires the previous release APK and release unit reports to be absent, then runs
`--offline --dependency-verification strict --no-daemon --no-build-cache --rerun-tasks
:app:testReleaseUnitTest :app:assembleRelease`. It rejects failures, missing/empty
reports and skips. No source overlays, arbitrary commands or supplied APK paths
are accepted in this build mode. The standard canonical output is
`app/build/outputs/apk/release/app-release.apk`. The release lock prevents another
cooperating release runner; the operator must stop editors and other Gradle builds.

Only after successful execution and unchanged measured inputs does the runner
create `Magnolie-Notes-VERSION-provenance.json` beside the unchanged APK and source
archive in a new 0700 directory. Its mandatory fields bind the measured inventory,
fixed build configuration/command, Gradle/JVM version output, Gradle/aapt/apksigner
executable hashes, zero build exit statuses, executed unit-case identities/counts,
APK SHA-256 and externally pinned production certificate. Test stdout and Gradle
environment properties are not copied into the public record. Review the record
before eventual publication, as it travels with the candidate artifacts.

This is measured canonical-build provenance on a trusted host, not a hermetic or
independently reproducible build, and not authentication against a dishonest local
operator. Trust includes the Gradle/JDK/SDK installations, verified dependency
cache, user Gradle configuration and signing environment. Do not use init scripts,
environment overrides or excluded local files to alter source/build configuration.
Signing properties and keystores must remain external; never copy or hash private
keys into a record. The selected canonical Gradle scripts, lockfiles and dependency
verification metadata remain in the measured source archive. Before/after equality
detects persistent drift, not a hostile temporary edit reverted between measurements.

Packaging an already built APK requires `--apk PATH --build-record PATH` from this
runner; it cannot create a retrospective build claim for the old 1.0.14 candidate.
Without `--destination`, `--apk PATH` remains a read-only metadata/signature/payload
audit and makes no provenance claim. `notes-inputs`, `seal`, `inspect`, `verify` and
`promote` all require the record, independently compare every archive member's
content and mode to the frozen Notes/contracts projection, and re-audit the exact
APK package/version/code, signer, debug/test flags and product payload boundaries.
Checksums must cover APK, source archive and provenance, with no missing members.
The certificate pin must be supplied externally at every gate, never learned from
the build record being checked. Use `ANDROID_SDK_ROOT` for these aggregate gates.

The recorded task is the public release unit selection, not the separate four-class
cross selection, lint, instrumentation, R8 runtime or native acceptance. Run those
additional gates from the same frozen canonical tree, retaining their real evidence
for the exact recorded APK. Do not replace that APK with a later rebuild without
new provenance. API 26/35, production upgrade, real Bluetooth and interoperability
remain mandatory. Neither the record nor permission to fix code authorizes signing,
native/user approval or publication. Production and validation APKs are not
interchangeable evidence. Notes download links stay pending the main coordinator's
decision; do not update embedded links or historical versioned APK URLs here.

## Optional KDE Component

Use `python3 magnolie-organizer-2.0.0/werkzeuge/kde_deb_bauen.py OUTPUT` to build
only the single KDE DEB, its coherent DSC/source tar and build provenance. This
does not start a VM, build the production aggregate or publish anything. The native
component source is frozen independently of concurrent UI/JS work.

All three existing package-managed rootfs environments are required: Noble 24.04
(Qt5, core ABI 23.08), Debian 13 (Qt6, 24.12), Resolute 26.04 (Qt6, 25.12).
They need the development packages listed by `native/akonadi-helper/profiles.py`
and a configured `akonadi-server` plus a distro database backend, e.g.
`akonadi-backend-sqlite`. Install these only in the build rootfs, with its existing
`policy-rc.d` denying service starts. Do not install KDE build dependencies on the
host. Rootless apt may need `APT::Sandbox::User=root` inside the already isolated
user namespace; signed repository/package checks must remain enabled.

The builder itself mounts these rootfs read-only/offline and enforces sequential
builds, two CPUs, CPUQuota=200%, MemoryMax=6G and MemorySwapMax=0 in a user systemd
scope. Each backend retains genuine shlibdeps and full dependency audits; only the
launcher/base/Organizer baseline is unconditional in the DEB. See
[KDE requirements and upgrade policy](magnolie-organizer-2.0.0/native/akonadi-helper/DEB-TARGETS.md).
Native acceptance for all three systems must bind the same final single DEB.
The explicitly invoked live probe now requires `--version VERSION --artifact
/path/to/magnolie-organizer-kde_VERSION_amd64.deb --profile PROFILE`, checks the
installed payload against that exact DEB and records its hash. Unlike the build
and `--check`, this probe deliberately starts a private test KDE server. Do NOT
invoke it while the current instruction prohibits service/VM starts; no live
acceptance is implied by preparing its source.

## Private Linux Candidate

From the canonical release root, using the exact Windows and Notes directories:

```sh
export MAGNOLIE_AKONADI_BUILD_ROOTFS=/tmp/opencode/ubuntu-noble-akonadi-rootfs
: "${MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE:?Supply the reviewed QEMU image}"
python3 -B magnolie-organizer-2.0.0/werkzeuge/package_preflight.py --root "$PWD" \
  --android-sdk "$ANDROID_SDK_ROOT" --notes-inputs "$MAGNOLIE_NOTES_ARTIFACTS" \
  --windows-inputs "$MAGNOLIE_WINDOWS_ARTIFACTS"
magnolie-organizer-2.0.0/werkzeuge/release_bauen.sh
```

A missing QEMU image is not automatically an approved exception. Follow FREIGABE.md
for independently established unavailability. Candidate schema v2 and complete
source modes remain unchanged. Neither this sequence nor a successful test creates
a real approval record or authorizes `--promote`. Both live manifests remain at
2.0.17 until personally or conditionally delegated authorized publication. After
verified replacement, the current instruction removes all old download packages,
including 2.0.17; retain required upgrade inputs until those checks complete.

The delegated-authorization source/doc changes invalidate candidate
`d7f633a430c3945aa5417552a19a05c3afcf731422951023e4ced9b160bc0db7`.
The main coordinator must freeze the final source and rebuild the aggregate
candidate before approval. No source-inventory exemption or retrospective
resealing of old artifacts is allowed. Old VM-agent reports describe only their
exact tested components, not the new final candidate or unexecuted native checks.

The local x86-64 QEMU gate uses KVM with `-cpu host`, two virtual CPUs and 4096 MiB
RAM. The default Intel `kvm64` model of autopkgtest 5.55 hides modern CPU features
and exceeded the unchanged 300-second WebKit layout-matrix deadline on this host.
The same matrix passed with host CPU features. Do not compensate for an unsuitable
VM CPU model by increasing test deadlines or dropping languages/layout checks.
