# Magnolie Organizer Android Tablet Beta 2.0.30Beta

Development sources for the standalone Android organizer, **not a production release**.
The beta identity remains 2.0.30Beta; its interface and contracts come from the
same current checkout as the tablet adapter. The old desktop release tag is only
an independent regression reference. Current port work is tracked in [issue #121](https://github.com/maik3531/Magnolie-Organizer/issues/121);
[issue #9](https://github.com/maik3531/Magnolie-Organizer/issues/9) retains the historical checkpoint.

The [26 November 2026 audit](../contracts/android-tablet-audit-2026-11-26.md)
records the current source work and each remaining issue. The new direct Android
copies, adaptive layout, HTTPS attachment handoff and build provenance are review
patches. Their host/browser/JVM checks and Android source compilation do not
constitute an assembled or accepted APK. Historical native evidence includes
API34 services/SAF in [#456](https://github.com/maik3531/Magnolie-Organizer/issues/456),
Keystore/epoch checks in [#454](https://github.com/maik3531/Magnolie-Organizer/issues/454)
and a 19.838-second cold start in [#479](https://github.com/maik3531/Magnolie-Organizer/issues/479).
The later drawing attempt stopped at an accessibility-window binding failure
([#463](https://github.com/maik3531/Magnolie-Organizer/issues/463)); the complete
touch gate, current APK matrix and physical-device acceptance remain open.
The offline build produces debug-only candidates; later source changes mark
`artifacts/candidate.json` stale.

Neither the Magnolie Notes app nor KDE Connect is required. Local organizer notes
remain available. Android contacts and calendar access uses the public on-device
providers with separate explicit permissions and source selection. Sharing two
existing storage helper source files and the Gradle wrapper does not install,
pair with or build the Notes application.

## Canonical Ownership

This directory is the tablet project's only canonical directory. Nothing in
Notes, desktop, Windows, or the shared contracts is edited by the tablet build.

- Application ID: `io.gitlab.maik3531.magnolieorganizer.tablet.beta`.
- Launcher/activity label: `Magnolie Organizer Android Tablet Beta 2.0.30Beta`.
- Android version name/code: `2.0.30Beta` / `20030`.
- Candidate: `artifacts/Magnolie-Organizer-Android-Tablet-Beta-2.0.30Beta-debug.apk`.
- Android private data, notifications, Keystore alias, debug signing key, and
  application sandbox are separate from the phone Notes profile.
- Minimum Android 8/API 26; compile API 37.2, behavior target API 35.
- Build toolchain: JDK 21, verified Gradle 9.6.0 wrapper, AGP 9.5.1 with built-in
  Kotlin 2.4.21, Android build-tools 36.0.0; Java/Kotlin bytecode target 17.

`tools/project-web.cjs` reads the **current** `../magnolie-organizer/web`
tree on every build. It generates assets under `app/build/generated/projection`,
never a manually maintained desktop fork. Its marked core transformations expose
the existing editor guard and durable-action queue as `MagnolieTabletActions`
and add the narrow Android-copy operations using the canonical normalizer and
timezone conversion. Reversibility checks remove only those documented blocks.
Entry-point scripts, beta identity, localization aggregation and tablet CSS are
explicit build transformations recorded in `projection.json`.

The projection also reads the live Windows `app/web/stil.css` font-face rules and
`app/web/schriften` assets/licenses. Noto Serif, DejaVu Sans, Noto Sans, DejaVu Sans
Mono and the handwriting face are bundled rather than relying on Android system
font names. Duplicate Linux/Windows font assets must have identical bytes.

The manifest hashes all source inputs, output assets/resources, the referenced
Notes crypto sources/wrapper, and shared contracts. A mid-projection edit fails
the projection. The final `--check` rejects a candidate if live sources have
changed during compilation. **A snapshot APK cannot track later UI edits:**
rerun the entire gate after desktop corrections, do not freeze or manually patch
generated assets. A changing source tree can legitimately require another build.

Notes' `DatenDateiKrypto.kt` and `DateiDauerhaft.kt` are copied by an exact two-file
Gradle `Sync` task into generated Kotlin sources. No Notes UI, profile, transport or crypto
fork is bundled. The web core owns organizer serialization/normalization and
custom-module behavior; the native store preserves the JSON instead of creating
a second organizer model. Shared custom identity/consent vectors are executed
against the projected core and through the existing shared desktop test runner.

## MVP Scope

| Area | Implementation | Acceptance Boundary |
| --- | --- | --- |
| Binder UI | Real desktop leather/paper/rings/tabs and full web modules | Current real-Chromium geometry and touch-tap checks; complete Android touch navigation gate pending |
| Calendar, tasks, contacts, notes | Local canonical web editing and native JSON persistence | Explicit Android contact/calendar copies added; no standard Android task provider |
| Planner, health, custom tabs | Canonical web sections retained, including custom items and consent | Not a claim that their external integrations work |
| Wide windows | Two simultaneous binder pages above 1100 CSS pixels, including wide portrait windows | Current browser checks; Android window resizing pending |
| Compact windows | Stacked pages, horizontal tabs and bounded scrollable dialogs regardless of orientation | Ten browser scenarios cover narrow/short windows, RTL and enlarged text; native IME acceptance pending |
| Input/accessibility | Native WebView input, keyboard guard/shortcuts, focus outlines, minimum 48 CSS-pixel action targets, reduced motion, pinch zoom | Browser touch taps and geometry tested; Android dp scaling, TalkBack, stylus and hardware keyboard pending |
| Private persistence | AES-256-GCM, Android Keystore, synchronized file write, atomic rename, directory fsync before save ACK | Native basic save/readback, non-exportable key and process restart passed; crash/failure durability acceptance remains open |
| Import | SAF ICS merges calendar appointments, tasks and anniversaries through the shared importer; SAF JSON accepts raw version-6 state or this beta's encrypted envelope | ICS source metadata and records share one durable book save; no VCF/CSV or desktop complete-archive importer; historic SAF proof in #456, current candidate acceptance pending |
| Android source copies | Explicit selected-source contacts or calendar instances for 1–366 inclusive calendar days, through native workers and the canonical book save | Append new identities only; existing entries remain unchanged; provider writes and ongoing synchronization are unavailable |
| Calendar attachments | Exact saved HTTPS attachment opened with Android ACTION_VIEW; existing explicit native clipboard command retained | JVM policy and host save-guard checks; actual Android handler/clipboard/form/reopen acceptance in #682 remains open |
| JSON replacement | Shared normalizer, explicit replacement confirmation, encrypted pre-import snapshot | Replaces the whole profile, not a merge; backup is internal, recovery UI not yet implemented |
| Export | SAF standard ICS for appointments, tasks and anniversaries; password-encrypted JSON for the complete book | ICS is unencrypted and collection-specific; historic SAF proof in #456, current candidate acceptance pending. JSON uses the beta envelope, not Notes backup or desktop complete-archive format |
| PDF/printing | Canonical print HTML into a separate script/bridge-free native print WebView | Android Print dialog includes Save as PDF; no automatic completion ACK; runtime/spooler validation pending |
| Reminders | Persisted one-off calendar/task/custom alarms, global and separate custom consent, inexact AlarmManager wakeup, boot/package restart receiver, delivery receipts | No recurrence/anniversary/health/SMS scheduling, exact alarm SLA, foreground service or force-stop bypass |
| Localization | Existing 20-language catalogs plus beta and Android-copy messages in all 20 locales | Native locale follows Android, web locale follows organizer settings; linguistic review not claimed |
| Setup/holidays | Current canonical setup logic/catalogs and local country/region/cached-holiday display filter | Native bounded HTTPS public/school holiday retrieval; no Android desktop setup wizard; native integration validation pending |
| DAV account setup | Canonical account form, revision-bound configuration, Android Keystore credentials and explicit collection discovery | Setup/discovery only; actual record synchronization remains disabled; real-server acceptance pending |
| Text editing | Current canonical context menu, Undo/Redo and accessible Tab-key help | Key/help catalogs checked in all 20 locales; actual WebView editing history/IME acceptance pending |

Unsupported bridge operations reject; they never return invented success or empty
provider data. Desktop integration tabs/actions are disabled or replaced by beta
panels. Other unsupported calls show a localized unavailable message with the
command identifier. Main statuses are visible and accessible, not console-only.

Contact SMS/call buttons, their context-planning actions, mail/map/letter/social
launchers and corresponding external-integration settings are disabled. The
specific saved HTTPS calendar-attachment action has its own native handoff. Local
contact phone/email/address editing remains available. The bridge rejects attempted
outgoing SMS/call commands without handing them to Android.

There is **no** EDS/Akonadi, automatic Android-account synchronization, complete Nextcloud synchronization/cloud backup,
Magnolienbaum/phone pairing, SMS/calls, Bluetooth/WLAN sync, medication/weather
lookup, desktop spelling service, LibreOffice/ODS/letter export, update service,
or desktop password-lock emulation. INTERNET permits the native HTTPS service; the WebView still rejects external resources. There is no system
shared UID or account-manager permission. READ_CONTACTS and READ_CALENDAR are
requested separately only after an explicit action; neither is required for
ordinary local editing.
New file attachments via the WebView file picker are not implemented. Existing
embedded note data is retained by the shared core subject to its validation.

## Local language and regional settings

The shared **Language and regional display** form now saves its local choices
through the existing canonical normalizer and native encrypted document save.
The save waits for any edited record first and reports success only after the
native save acknowledgment. Failed saves retain the visible changes for retry.
Native desktop time-zone management/detection is unavailable and its management
button is disabled; local timezone selection remains available. These local
preferences do not configure Android system settings or desktop account services.

## Storage and Security

Only `https://appassets.androidplatform.net` can access the web-message bridge,
and only its main frame is accepted. Top-level navigation is restricted to the
generated entry page. WebViewAssetLoader serves bundled assets; other requests
receive 403. SSL errors are canceled; file/content access, universal file access,
DOM/database storage, cookies, mixed content, debug inspection and automatic
windows are disabled. The desktop CSP is retained. The print WebView has no
bridge, JavaScript or network-resource access. Private-screen protection is set.

The native vault is `noBackupFilesDir/tablet-vault.enc`. No plaintext fallback is
provided. A missing Keystore key, authentication failure, incomplete first write
or invalid vault blocks startup rather than initializing an empty organizer.
Save acknowledgments contain the desktop request ID and are sent only after
file fsync, atomic rename and directory fsync. The serial executor also orders
notification settings, JSON replacement and reminder delivery with saves.

Native random sessions/revisions now fence saves and restore confirmations.
Initialization must be acknowledged before writes are enabled. Uncertain
publication and committed-readback failures leave the old page non-writable;
only verified disk reload and a fresh page acknowledgment can reopen writes.
For JSON replacement, the selected native import bytes, not a frontend-supplied
replacement body, are committed and read back. Reminder follow-up failure cannot
undo that commit. ICS follows a separate merge route: native bounded file reading
and decoding run off the UI and book-save executor, then the shared web importer
merges the complete candidate. Its calendar properties and source SHA-256 metadata
are persisted with the imported records in the same ordinary atomic book save.
Cancellation or a decoding/metadata error applies no candidate; a failed book save
retains the unsaved complete merge for explicit retry and never reports success.
SAF request codes are one-use and page/session-bound, with the next code retained
across Activity recreation. Late results do not consume a newer picker; background
import/export completions retain the original page authority. Destruction and
renderer loss invalidate queued work and callbacks.

`before-import.enc` is an encrypted internal pre-import snapshot for JSON
replacement. Each confirmed JSON replacement replaces it after syncing it, then replaces the main vault. Imported
notification permissions are **not** trusted: global and custom native consent
are reset, and the alarm schedule is empty until the web core reprojects it.
Custom module/item consent remains necessary in addition to native custom consent.

The three canonical ICS export actions each select the entire appointments, tasks
or anniversaries collection; they have no frontend record filter. After the
shared editor/durable-save guard, native code reads the authoritative saved book,
validates the selected collection and encodes the complete ICS file off the UI and
book IO executor. Only then does the Android create-document picker open with
`text/calendar` and an `.ics` filename. No ICS body or record array crosses back
through WebView. ICS has no password dialog and is explicitly labeled unencrypted;
use encrypted JSON for a complete book backup. Unsupported kinds, invalid records
and an empty collection reject before the picker. Picker results and queued writes
are bound to their original page, revision and one-use request. A cancellation or
write/flush/close failure never produces a successful export acknowledgement.
The provider can leave a partial file after an error; SAF writes are not claimed
atomic. The pure export codec bounds the complete output to 32 MiB. Native Android
compile and SAF interaction remain required before accepting this route.

JSON export passwords are 8-1024 characters. The portable envelope is JSON with
`format: Magnolie-Organizer-Android-Tablet-Beta-1`, fixed 210000 PBKDF2 iterations,
random 32-byte salt, and authenticated encrypted JSON. Wrong passwords,
unsupported parameters and tampering reject. Keep the password separately:
Keystore data cannot be recovered after app uninstall; exported data can be
reopened with its password. There is no plaintext export switch in this MVP.

JSON state is limited to 16 MiB, incoming files/bridge envelopes to 32 MiB and
nesting to 64. ICS files are limited to 32 MiB; their serialized decoded candidate
is limited to 8 MiB and 5000 records before delivery to the UI. The completed
message is serialized on the background worker, and the candidate plus current
book must fit the 16 MiB preflight bound; native whole-book validation remains
authoritative. New pickers, cancellation, reload and restore invalidate old ICS
work; a normal book save during decoding rejects that candidate and releases its
picker for retry. Duplicate/no-op imports also consume their picker exactly once. SAF provider write, flush and close failures are surfaced; provider
durability and atomicity are not promised. An interrupted provider export may
leave an incomplete encrypted destination document and must be retried.

Reminders can be delayed by Android/Doze/OEM policies; due alarms are caught up
for at most 24 hours, in bounded batches. Stable notification IDs prevent duplicate
cards after a crash between notification posting and receipt persistence.
Notification content is private on the lock screen. Opening a notification opens
the binder, not yet the exact item. Reopen the organizer after changing time zone
to regenerate future timestamps. Force-stop suppresses alarms until reopening.

One-off task notifications honor the independent early-day and due-date controls,
including early-only with the due checkbox off. Early days use source calendar
days across DST, resolved by the current shared timezone code. Source UTC/TZID
is preserved. Recurrence and malformed temporal ICS remain unsupported, not
reinterpreted as one-off events. Existing due-alarm receipt IDs remain valid.

## Build and Coordination

### Bounded offline checks (current workflow)

From this directory, run lightweight checks first. The second invocation adds
only the offline JVM unit task:

```sh
systemd-run --user --wait --pipe --collect \
  --setenv="MAGNOLIE_JS_RUNTIME=$HOME/.bun/bin/bun" \
  -p MemoryMax=6G -p CPUQuota=200% -p RuntimeMaxSec=570 \
  -p TimeoutStopSec=10 -p KillMode=control-group \
   --working-directory="$PWD" python3 -B tools/offline-checks.py </dev/null

# After light checks pass and the shared slot is available:
systemd-run --user --wait --pipe --collect \
  --setenv="MAGNOLIE_JS_RUNTIME=$HOME/.bun/bin/bun" \
  -p MemoryMax=6G -p CPUQuota=200% -p RuntimeMaxSec=570 \
  -p TimeoutStopSec=10 -p KillMode=control-group \
   --working-directory="$PWD" python3 -B tools/offline-checks.py --jvm </dev/null
```

The script verifies the cgroup limits, pins itself/children to two allowed logical
CPUs on different physical cores where possible (avoiding SMT siblings), acquires
both sole-VM locks plus Android-build/native-layout locks nonblockingly, and checks
for noncooperating VM/compiler processes. Missing/busy coordination roots refuse
the run. Gradle uses `--offline --no-daemon --max-workers=1`; Kotlin stays in-process,
Gradle heap is 1536 MiB, test heap 512 MiB. Each JVM test has a 30-second deadline;
the Gradle command has 300 seconds, the whole script 540 seconds plus bounded
cleanup. Timestamped progress is emitted at least every 30 seconds. The containing
service also bounds and cleans up any Gradle descendants on exit.

Before validating amid shared-source edits, run `bun tools/project-web.cjs --check`
to record staleness. The tests then generate a fresh hash-recorded projection and
require a matching final source check. A matching snapshot is only current at
that check; the historical APK stays stale until a separately coordinated rebuild.

### Complete bounded offline debug artifact gate

The gate requires a complete JDK 21 (including `javac`), Android platform 37.2 and
build-tools 36.0.0. The default SDK is `~/.local/share/android-sdk`; Gradle 9.6.0 is
selected by the existing checksum-verified wrapper. Use Bun or set
`MAGNOLIE_JS_RUNTIME=node`. Install the small private web test dependency once:

```sh
bun install --frozen-lockfile
bash tools/build-beta.sh --readiness
bash tools/build-beta.sh
```

`MAGNOLIE_JS_RUNTIME=node` is supported on hosts with Node; otherwise Bun is the
default. `JAVA_HOME`, `ANDROID_HOME`, `GRADLE_USER_HOME` can be overridden. `ANDROID_SDK_ROOT`
may identify the same SDK; conflicting SDK paths fail before execution.

For an empty, isolated CI cache, `bash tools/build-beta.sh --online` allows Gradle
dependency downloads. The default remains offline. This option retains the same
systemd resource limits, five coordination locks, deadlines, source checks, unit
tests and artifact verification; it does not start an emulator or authorize release
Gradle tasks. Direct JVM-only gate invocations may use `--jvm --online` within the
same required resource-limited user service. A cloud host without that service and
cgroup support cannot run the complete APK gate.

The dedicated [`ports-2.0.30.yml`](../.github/workflows/ports-2.0.30.yml) workflow
prepares that service on a fresh Ubuntu runner. The tablet job retains the exact
current checkout, captures its Git/file provenance before generating catalogs,
and invokes `--online` inside the same bounded build gate. The published desktop
tag `v2.0.30` at commit `067c38934b539943d8e1720abafd8a80b401d797` remains only an
independent codec oracle; it is never restored over tablet build inputs. After
the existing APK verification, `tools/source-proof.py bind` checks the unchanged
Git inputs, reproduced catalogs, projection inputs/outputs and candidate bytes
and records their relationship. The Mac job retains its separate existing policy.
For a complete build without native execution, dispatch this workflow on the
intended review branch with **`target: tablet-build-only`**. Its single `build`
matrix entry runs the same complete debug APK gate and provenance binding. It
does not prepare a runtime image, access KVM, start an emulator, run native suites
or collect native evidence. The job/artifact name includes
`build-only-no-native-acceptance`; `sources.json` records `buildOnly:true`, null
runtime image/API/component fields and `componentOnly:false`. Native and release
acceptance remain false. This is an explicit build target, not a shortened or
alternative Gradle path. All existing targets, including `all`, retain their
original native suites and coordination limits.

To exercise the device contact/calendar readers with actual Android providers,
dispatch **`target: tablet-system-records`**. This separate API 34/google_apis job
runs the complete APK gate first, then the single `system-records` stage on its
owned disposable emulator. It creates and removes only its own synthetic raw
contacts and calendars. Fixture writes temporarily adopt the two write
permissions; every product read runs after that identity is dropped and with
ordinary runtime read permissions. The application manifest is unchanged.
The eleven check groups cover denied reads, discovery, contact fields and stable
source identity, calendar selection/window/recurrence identity, pre-cancellation
and cleanup. Two real calendars test calendar-source isolation. The single local
contact source does **not** prove contact-source isolation; the receipt records
`contactsSourceIsolationTested:false` and `calendarSourceIsolationTested:true`.
This stage does not open an Activity or exercise permission dialogs, live
revocation, WebView import/save ACKs, in-flight cancellation or tablet UI input.
Its job/artifact name says `API34-provider-only`, and the source metadata records
`systemProviderOnly:true`; full native/Google-runtime acceptance remains false.
Existing targets and resource/owner gates retain their prior behavior.

For the existing native targets, the owned emulator suites test the exact
hash-checked app/test pair. Candidate metadata, checksums and applicable runtime
evidence are retained as Actions artifacts for 14 days, including diagnostics
when a stage fails. This workflow is manual or runs on the dedicated
`codex/ports-2.0.30` branch; it does not publish a production release. Check the
job outcome and native evidence before treating an APK as tested. A debug key
generated on a fresh runner is not a stable update-signing identity.

The gate reuses Notes' verified wrapper with `-p` pointing **here**. It does not
configure/build Notes. Release-named Gradle tasks are intentionally refused.

The gate now delegates to `tools/offline-checks.py --build` in a user service:
6 GiB memory, no swap, 200% CPU, 870-second owner deadline, 890-second service
deadline plus at most 10 seconds for cgroup cleanup (15 minutes total). It uses
EOF stdin, private temporary test resources and all five nonblocking locks listed
below. Existing runner/web/reminder tests and cross-desktop setup-holiday tests
run before the forced JVM unit task (300 seconds maximum), then debug app/test APK
assembly (600 seconds maximum within the remaining total budget). Progress is
emitted every 30 seconds. Source/APK hashes, package/version/label, debug signatures,
test-only instrumentation target and native permission boundaries are verified.

Gradle uses `--offline --no-daemon --max-workers=1`, in-process Kotlin compilation,
two JVM processors and 1536 MiB heap (512 MiB test heap). It refuses a JVM
compiler/test process that bypassed the common lock. **The main session and any
Notes agent must use the same flock for
all Android builds and tests, including cache-writing tasks.** Example wrapper:

```sh
flock /tmp/opencode/android-build.lock bash path/to/other-android-test-script.sh
```

Do not wrap this beta's own build script with that command: it already acquires
the lock. Do not run competing Android compilers. The readiness operation checks
tooling and the lock but does not compile, install or start an emulator.

### Owned emulator lifecycle

`tools/emulator-session.py` owns its cooperative leases for the entire run
and cleanup; callers must not wrap it in another acquisition of those locks.
Defaults reuse these existing paths:

- `../../Test-VMs-20260912/sole-vm.lock`, relative to this project.
- `$SESS/sole-vm.lock`, defaulting to
  `~/.local/share/magnolie-testing/vms/rebuild-20260912/sole-vm.lock`.
- `/tmp/opencode/android-build.lock` and `/tmp/opencode/native-layout.lock`.
- `/tmp/opencode/magnolie-global-heavy.lock`, the additional global lease added
  for the main-granted native UI phase; the four older leases remain in force.

`--vm-root` and `--session-root` select existing coordinated roots. `run` requires
`--main-slot-granted` **after** main has explicitly granted the sole slot. A flag
does not constitute a resource grant by itself. Use the actual current assignment
of the shared test slot. Historical pause comments, including the closed #423,
do not establish a continuing general ban on Android tests.

Runtime defaults/caps are 1200 seconds total and 180 seconds to boot; every native
stage/ADB command defaults to 120 seconds. Progress defaults to 30 seconds and
cannot exceed 60. Native tests select the existing instrumentation's individual
stage names (`basics`, `restart`, `layout`, `time`, `navigation`, `saf`, `fault`,
`print`, `notifications`, `seed-reboot`, `verify-reboot`) via `--test` or `test`.
Their actual JSON result and instrumentation exit code must both indicate success.
Failure/timeout of an external test requests cleanup from the verified owner.

SIGINT, SIGTERM, boot failure, stage failure, timeout and natural exit all enter
bounded cleanup. Only PID identities created by this owner are signalled, using
Linux boot/start-time/UID plus pidfds to avoid PID reuse. TERM is followed by a
5-second wait, exact-identity KILL only if needed, and another 5-second wait.
Zombies are reaped with wait; they are not treated as killable running processes.
ADB listens only at 127.0.0.1:5039 as a foreground direct child; its listening inode
and process identity are verified. No port-only/global `kill-server` is used.
The owner records UTC progress, elapsed time, reason, actual child exit codes and
its own exit status in `artifacts/emulator-session.json`; legacy PID-only state
cannot authorize any signal or ADB operation.

For the exact later command, see the continuation report. `tools/native-checks.py`
uses this same owner, locks, pidfds and exact ADB port/serial checks. Each invocation
validates the current candidate, creates a private disposable AVD, installs only
the hash-checked app/test APK pair, runs one suite, collects evidence and cleans up.
Suite `ui`: basics (editors/keyboard/persistence), restart,
layout (including all 40 touch-tab switches), time. The navigation stress assertions
are preserved in their own existing 120-second stage budget.
Suite `storage`: basics, SAF, fault, print. Suite `notifications`: notifications.
There is a full stop/resource recheck between suites. Reboot/Doze, portrait/large
text/RTL/TalkBack remain additional native acceptance work. Optional coexistence
testing with an installed Notes app does not make Notes a runtime prerequisite.

## Test Proof

After a successful complete gate:

- `artifacts/candidate.json`: exact APK identity/hash, source hash and unaccepted status.
- `artifacts/projection.json`: source inputs and generated-output hashes.
- `artifacts/source-checkout.json`: current Git commit, tracked input blobs and
  file hashes, captured only from a clean relevant checkout.
- `artifacts/sources.json`: checkout-to-projection-to-verified-APK binding
  produced by the tablet CI job, not a substitute for native acceptance.
- `artifacts/web-test-proof.json`: jsdom/shared-contract gate count and source hash.
- `artifacts/a3-editor-vectors.json`: current editor-generated records and alarm matrix, also consumed by native JVM tests.
- `app/build/test-results/testDebugUnitTest/`: JUnit XML, no emulator required.
- `app/build/reports/tests/testDebugUnitTest/index.html`: Gradle unit report.

Current source tests cover encrypted round trips, fresh IVs, wrong keys and
tampering, all three persistence checkpoints, interrupted initial creation,
pre-import backup and consent reset, password exports, JSON/UTF-8 bounds,
background consent/receipt/expiry, binder startup/modules/save/reload,
lossy-import rejection and shared custom identity/revocation vectors.

These are **not** Android instrumentation, real renderer, accessibility, SAF,
Keystore, reboot, Doze or printer proofs. Do not rename this candidate to a final
or accepted APK based on compilation/unit tests alone.

Additional checks introduced with the 26 November review patches:

```sh
python3 -B tests/test_source_proof.py
node tools/project-web.cjs
node tests/web.test.cjs
node tests/system-import.test.cjs
# Requires Playwright and an explicitly available Chromium executable:
MAGNOLIE_CHROMIUM=/path/to/chromium node tests/tablet-layout-browser.cjs
MAGNOLIE_CHROMIUM=/path/to/chromium node tests/system-import-browser.cjs
node tools/project-web.cjs --check
```

The Android-copy integration check is part of the bounded offline gate. It uses
the actual generated organizer with a synthetic native bridge, tests save ACKs,
failed-save retry, cancellation, stale replies, selected sources, date windows,
contact birthdays and reopen stability. The separate browser test uses a real
Chromium renderer and touchscreen taps; its bridge is also synthetic. Neither
test exercises Android permissions, the device providers or an Android WebView.

The follow-up checks are separate, specifically bounded proofs:

| Check | Recorded result | Limit |
| --- | --- | --- |
| Source provenance and workflow selection | 22 tests passed | Includes the explicit build-only target, unchanged existing matrix/native guards and truthful artifact metadata; not a Gradle/APK execution |
| Native window-ownership diagnosis | 9 JVM tests passed, including 432 ownership-state combinations | The accepted ownership predicate is unchanged; no Android accessibility runtime was exercised |
| Native import/source/attachment policies | 46 JVM tests passed | Native Kotlin rules executed on the host JVM; not real provider, permission-dialog or Intent execution |
| Import-form focus, interaction, localization and visible status | 167 real-Chromium checks passed | Synthetic native bridge; includes the real identity-conflict path and unobstructed status after scrolling in three window sizes; no Android WebView, IME or TalkBack acceptance |
| Generated shared web surface | 194 checks passed | Host execution of the actual generated application |
| Copy/attachment integration | 46 checks passed | Actual generated application and canonical normalizer with synthetic provider/storage |
| Tablet layout | 150/150 checks passed in ten cases | Chromium geometry, touch target and hit checks |

The final web/browser checks use projection
`7a0c31a550761badd32e07f4bdaee6b016fd158a769a64017c7525332bb70416`.
Twenty-language key coverage is checked; this does not claim a complete
linguistic review. These counts do not form a combined native acceptance result.
The original failures, intermediate stages and final raw evidence are preserved
under `pruefnachweise/android-tablet-followup-2026-11-26/` at the repository root.
The import status now stays inside the settings dialog in a persistent live
region ([#801](https://github.com/maik3531/Magnolie-Organizer/issues/801)).

The first complete build-only attempt (Actions run 45806941029, #790) passed
checkout, provenance, preparation, readiness and the 194/46 web/integration
checks, then stopped before Gradle: the shared desktop setup test expected a
generated timezone cache absent from a fresh checkout. That test now builds
the existing verified timezone bootstrap in memory from the checked-in sources.
All 88 cross-desktop setup cases in 20 languages pass; stale desktop caches are
not read, and corrupt normative data still fails. The resulting projection is
`3dcf2073c46012e193900fce971a5bab91cefd5194f433bac7169e7f98917907`;
all 83 generated runtime files are byte-identical to the tested projection above.
The next build-only attempt (Actions run 45809316206) confirmed the setup fix:
22 provenance tests, 194 web checks, 46 integration checks and all 88 setup cases
passed. Gradle compiled product Kotlin, manifest and resources, then stopped at
five unsupported `JSONObject.similar` calls in JVM tests ([#805](https://github.com/maik3531/Magnolie-Organizer/issues/805)).
The comparison now uses the available Android JSON API, preserving all fields,
types, array order and exact number distinctions. All 42 targeted JVM tests pass
against the real Android 37.2 API; no product source was changed by that fix.
Neither failed CI attempt produced an APK. The two original CI failures and
targeted corrections are recorded in `ci-run-45806941029/`,
`ci-run-45809316206/` and `issue-805/` in the evidence folder.

The new provider stage has passed 24 source/workflow checks and four targeted
owner-contract checks. The final instrumentation sources compile against the
real Android API using all 38 unchanged product Kotlin sources. The final two
receipt-scope literals were recompiled separately after the host checks; the
original and final hashes and actual commands are in `system-records/`.
These preparation records contain no provider/emulator execution. The subsequent
actual Actions runs below bind their own checkout and APK/runtime results.

The following actual run, [Actions 45817099578 / attempt 2](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45817099578/attempts/2),
passed the complete APK gate on head `92e2c645cf0a8075325874f335087412e7f79c79`:
303 JUnit tests in 42 reports, zero failures/errors/skips, verified app and
instrumentation bytes and source/projection bindings. Attempt 1 separately failed
on an external Maven Central HTTP429 dependency download. The API34 provider run
passed eight functional groups and cleanup, then failed its expected two-instance
count after creating a recurrence exception; the original actual count was not
recorded. Cancellation was not reached. Both attempts remain distinct in
`ci-run-45817099578/`; successful APK construction is not native suite acceptance.

The follow-up fixture correction ([#807](https://github.com/maik3531/Magnolie-Organizer/issues/807))
uses complete synthetic sync-adapter linkage for the series and exception, adds
direct readback of its own Events rows and bounded before/after slot evidence,
and retains every two-instance, original-identity, moved-time and second-slot
assertion. Product readers and permissions are unchanged. Its receipt explicitly
records `recurrenceFixtureUsesSyncMetadata:true` and
`unsyncedLocalRecurrenceExceptionsTested:false`; unsynced local recurrence
exceptions are outside this corrected fixture's proof. At the time patch 11 was
prepared, a fresh real provider run for this correction was still pending.

The subsequent [Actions 45822320243 / attempt 1](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243)
passed both the full APK gate and the actual API34/google_apis provider stage on
head `7a7d90b04796cf338b98f0fdbb87e8da1c967043`, tree
`06c1a8cf6f115908dc21252682c2a358246f2cb7`, projection
`dbe502cf4ad4661be79dca584c120d8623676cf8be5c3ff0d61eba840b676c09`.
All 42 original JUnit reports again contain 303 tests with zero failures/errors/skips.
The native receipt has ten functional groups plus cleanup. The recurrence fixture
has exactly two instances before and after the exception; its first slot moves
09:00 to 12:00 with unchanged original identity, while the second day and identity
remain unchanged. Both pre-cancelled reads are reached. All 19 recorded product/
readback checks run without fixture identity or WRITE permissions; both owned
RawContacts and both calendars are removed, with zero remaining owned IDs.
Original receipts, APK hashes, JUnit reports and the executed artifact verifier
are in `ci-run-45822320243/` in the evidence folder. The final documentation/evidence
update does not change executable sources; the tested APK head stays explicit above.

## Later Acceptance

Coordinate one emulator/VM at a time using the existing resource gates. The
corrected head identified above has passed the complete APK gate and its bounded
native provider suite. Unsynced local recurrence exceptions, a second contact
source and the full tablet UI/device matrix remain open. The provider result does
not establish permission-dialog/live-revocation, in-flight cancellation or UI/save-ACK acceptance.

1. Install the standalone tablet app and verify its identity and independent data; also check coexistence if Notes happens to be installed.
2. Test 1280x800 landscape, portrait, large text, RTL, TalkBack, stylus, external keyboard and IME insets.
3. Create/edit calendar entries, tasks, contacts, notes and custom modules; background, kill and reopen.
4. Exercise real Keystore encryption, missing-key/corrupt-file fail-closed startup, fsync/rename fault boundaries and data recovery.
5. Import raw/valid encrypted JSON, reject invalid/tampered/oversized documents, cancel at each SAF/password/confirmation stage, and verify pre-import recovery data.
6. Export through local and remote SAF providers, simulate denial/full storage/cancellation, and round-trip encrypted data.
7. Print actual calendar, planner, contact and note selections to PDF; inspect multipage output, wrapping, images, cancellation and printer failure.
8. Exercise notification denial/revocation, custom consent/revocation, edits/deletions, background/Doze/reboot, batching and stable receipts. Verify unsupported recurrence is clearly understood.
9. Test origin/frame navigation attacks, print HTML injection, new-window/file requests and process recreation during pending operations.
10. Refresh the live projection, rerun all gates and record the exact candidate hash before making any acceptance decision.
11. Grant, deny and revoke contacts/calendar permissions separately; select actual sources; copy records, cancel/rotate/recreate during a query, repeat a copy and reopen the saved book. Check all-day dates, recurrence windows, DST and unchanged existing entries.
12. Open a saved HTTPS attachment and explicitly copy its link; test missing handlers, local-only records, return to the organizer and save/reopen on the same current APK.

Desktop artwork/fonts and code retain their existing licenses; see the parent
`LICENSE.md`, `PROTECTED-ASSETS-LICENSE.txt` and canonical font license. This beta
does not decrypt or bypass protected desktop assets/contributor controls.

The separate `domains` component stage uses shared real settings and form bindings
to create and edit vital signs, glucose and medication-plan rows, custom appointment,
task and text blocks, and a drawing sheet. It checks invalid-value rejection,
discard, native trusted touchscreen strokes, actual Undo/Redo pixels and vector
data, encrypted save and complete-book reopen integrity. It does not replace the
original UI acceptance suite and retains the existing 120-second stage limit.
Before save, every book field must match native disk structurally. On renderer
reopen only the canonical health normalizer's absent optional `vital.sauerstoff`
field may acquire its zero default; changed or missing existing values still fail.
The standard host gate runs the health/custom forms and negative integrity cases;
canvas, Android Keystore and native persistence require the actual device stage.
Medication online lookup, drawing file import/PDF, physical stylus behavior,
TalkBack and IME are outside this component proof. Native success must be recorded
for the exact APK; host checks alone do not establish that acceptance.

The ownership guard now distinguishes missing or failed accessibility evidence
from a positively observed foreign package/window and from the app's own unready
state ([#463](https://github.com/maik3531/Magnolie-Organizer/issues/463)). The known
focused-app case with both window IDs at `-1` and an empty active package is
`input-ownership-unverified`, not proof of an external blocker. Bounded service
flags/capabilities and root-presence metadata are read for diagnosis only. The
original ownership predicate, service flags and 420 ms gesture remain unchanged;
no retry or prewarming is introduced. This corrects classification; it neither
explains nor fixes the missing binding and does not permit an unverified gesture.

## Direct Android contacts and appointments

Android system-source discovery uses public CalendarContract calendar metadata and
ContactsContract Settings/RawContacts account metadata. Separate explicit buttons
request READ_CALENDAR or READ_CONTACTS; startup and refresh never prompt. The
user then selects a source and deliberately copies its contacts or calendar
instances. No GET_ACCOUNTS, credentials or private provider databases are used.
Android's general AccountManager visibility rules cannot expose
every device account, so the source list represents accounts actually exposed by
the calendar/contacts providers. Tasks/VTODO have no standard CalendarContract
provider and remain unsupported. Source selection does not enable synchronization
or writes; cached DAV collections keep their separate IDs. No Notes/KDE pairing
is involved. A provider can withhold work-profile or protected OEM data even
when ordinary contacts permission has been granted.
Queries run on a separate worker with native cancellation, a 15-second deadline,
a 1,000-source limit and 20,000 contacts-metadata row limit. Denial, provider error
or exceeded bounds do not clear saved selections or report truncated lists as
complete. Pure request/discovery/merge fixtures and host permission UI tests are
not proof of real Android account access: OS dialogs and actual provider accounts
still need native acceptance. The minimum SDK remains API26.

The record-copy worker has separate limits: 5,000 records, 50,000 provider rows,
4 MiB response, 64 KiB per field and a 15-second deadline. Queries are cancellable
and bound to the original page session, book revision, request and selected
source. Contacts validate raw-contact identities/versions before and after
reading; calendar instances are compared across two bounded reads. A changed,
revoked, missing, oversized or timed-out source rejects the candidate without
claiming a complete result. These checks do not claim an atomic provider snapshot.

The copy response and stored provenance now use **identity schema 2**
([#799](https://github.com/maik3531/Magnolie-Organizer/issues/799),
[#800](https://github.com/maik3531/Magnolie-Organizer/issues/800)). Contact identity
prefers the provider's source ID, then backup ID; the fallback binds a raw row to
the Android device/user/signing scope. A separate hashed row binding detects
conflicting contact identity changes. The raw device identifier is not sent to
the renderer. One-off event identity excludes its editable start/end times;
recurring instances use the series and original slot, including moved exceptions.
Provider IDs are still scoped to the selected source. This does not establish
universal identity across provider resets or every device migration.

An incompatible response schema or conflicting row binding causes rejection.
Existing older experimental provenance from that source blocks a copy containing
records. The code does not infer cross-device equivalence from an unscoped row
number, name or phone number, silently convert old provenance, or deduplicate the
whole book. Existing local edits remain protected;
provider edits and deletions are not synchronized back into those copies.

Contacts copy names, phone/email/address entries, company, notes and supported
birthday/anniversary dates; this is not a complete vCard/photo/group importer.
Calendar selection covers 1–366 inclusive dates in the organizer's selected
display zone. Timed entries preserve their exact UTC ICS instants; all-day
entries use explicit UTC date boundaries and Android's exclusive end date.
Recurring appointments are copied as instances in that window; recurrence rules,
later provider edits and deletions are not synchronized. Imported appointments
follow the existing local organizer reminder preferences.

Only new stable provider identities are appended. Repeating a copy skips already
copied identities, including locally edited entries. Passive origin metadata
grants no provider or DAV write rights. The shared normalizer derives linked
contact birthdays; if a copy would modify existing anniversaries or collapse
identities on reopen, it is rejected as a conflict. Existing records are not
replaced. The existing editor/save guard runs before the query and application;
success appears only after the encrypted native book save is acknowledged.
A failed save retains the complete unsaved copy for an explicit retry. Cancelled,
late or stale responses are ignored, never applied to a different book.

The source panel preserves focus across its asynchronous redraws only when focus
was already inside it ([#798](https://github.com/maik3531/Magnolie-Organizer/issues/798)).
A disabled initiating control moves focus to the available cancel action or the
group; completion returns to the relevant control, and successful permission
confirmation leads to its source selector. A callback does not reclaim focus from
another control or an editor/modal. Import labels and statuses use the same
20-locale set as the tablet UI. Real Android permission-dialog focus, IME and
TalkBack behavior remain separate native acceptance items.

## Saved HTTPS calendar attachments

The native handler accepts only the exact HTTPS URI of an attachment already
present in the authoritative saved appointment/task book, with `localOnly:false`
and a supported web/cloud provider. It rejects credentials, unsupported schemes,
invalid ports, control characters, unknown/local-only providers and mismatched
page authority. URI percent escapes are preserved. Android receives an explicit
ACTION_VIEW/CATEGORY_BROWSABLE handoff; success means only that Android accepted
the handoff, not that a browser loaded the page. Other contact/social launchers
remain outside this route. The existing deliberate clipboard command is separate.

Permission-dialog recreation retains only a non-authorizing code/kind quarantine
and a process marker, never an old page request or reply authority. A same-process
recreation blocks another dialog until the matching OS result (discarded for the
old document) or an already-granted permission clears that slot. After process
death the obsolete quarantine is discarded, while the saved increasing request
code prevents an old result from completing a new request. These transitions have
pure negative fixtures; actual Android recreation/dialog behavior still needs
native verification.

Calendar codec timezone rules now come from the single SHA-verified shared
TZif/POSIX database, including full history and unlimited tails; ThreeTen remains
for Gregorian arithmetic only. See [timezone provenance and limits](third-party/README.md).
The confirmed Gaza2074 codec regression has a production-codec test: 12:30 local
resolves to 09:30Z, and the old contradictory 10:30Z projection rejects export.
Shared JavaScript reminder projection and actual Android resource/device
acceptance are separate checks; this codec change does not establish them.

Recurrence-instance identity hashes use explicit canonical JSON string quoting,
matching the published Python contract for slashes, escapes and Unicode. This
fixes Android's platform-dependent slash escaping ([#456](https://github.com/maik3531/Magnolie-Organizer/issues/456)); it does not automatically repair
previously stored incorrect instance UIDs.
