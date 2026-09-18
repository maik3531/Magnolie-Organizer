# Magnolie Organizer Android Tablet Beta 2.0.18Beta

Development snapshot of the debug beta, **not a production release**.
Development is paused. The source is retained here so work can resume from one
documented state, tracked in [issue #9](https://github.com/maik3531/Magnolie-Organizer/issues/9).

Basic startup and restart have been exercised in an emulator. Layout, input
handling and complete Android runtime verification remain unfinished. There has
been no physical-device acceptance or production release. The offline build
produces debug-only candidates; source changes mark `artifacts/candidate.json`
stale. A successful source projection does not establish release readiness.

## Canonical Ownership

This directory is the tablet project's only canonical directory. Nothing in
Notes, desktop, Windows, or the shared contracts is edited by the tablet build.

- Application ID: `io.gitlab.maik3531.magnolieorganizer.tablet.beta`.
- Launcher/activity label: `Magnolie Organizer Android Tablet Beta 2.0.18Beta`.
- Android version name/code: `2.0.18Beta` / `20018`.
- Candidate: `artifacts/Magnolie-Organizer-Android-Tablet-Beta-2.0.18Beta-debug.apk`.
- Android private data, notifications, Keystore alias, debug signing key, and
  application sandbox are separate from the phone Notes profile.
- Minimum Android 8/API 26; compile/target API 35; JDK 17.

`tools/project-web.cjs` reads the **current** `../magnolie-organizer/web`
tree on every build. It generates assets under `app/build/generated/projection`,
never a manually maintained desktop fork. Its only core transformation exposes
the existing editor guard and durable-action queue as `MagnolieTabletActions`.
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

Notes' `DatenDateiKrypto.kt` and `DateiDauerhaft.kt` are compiled by source reference
using Kotlin's explicit include filter. No Notes UI, profile, transport or crypto
fork is bundled. The web core owns organizer serialization/normalization and
custom-module behavior; the native store preserves the JSON instead of creating
a second organizer model. Shared custom identity/consent vectors are executed
against the projected core and through the existing shared desktop test runner.

## MVP Scope

| Area | Implementation | Acceptance Boundary |
| --- | --- | --- |
| Binder UI | Real desktop leather/paper/rings/tabs and full web modules | jsdom plus native screenshots/basic geometry observed; complete touch navigation gate blocked |
| Calendar, tasks, contacts, notes | Local canonical web editing and native JSON persistence | No Android system calendar/contact provider |
| Planner, health, custom tabs | Canonical web sections retained, including custom items and consent | Not a claim that their external integrations work |
| Landscape | Two simultaneous binder pages | Native screenshots/basic geometry passed; complete interaction acceptance pending |
| Portrait | Pages stacked vertically, scrollable binder | Small-screen, large-text and IME acceptance pending |
| Input/accessibility | Native WebView input, keyboard guard/shortcuts, focus outlines, touch targets, reduced motion, pinch zoom | TalkBack, RTL, stylus and keyboard hardware not exercised |
| Private persistence | AES-256-GCM, Android Keystore, synchronized file write, atomic rename, directory fsync before save ACK | Native basic save/readback, non-exportable key and process restart passed; crash/failure durability acceptance remains open |
| Import | SAF JSON: raw canonical version-6 state or this beta's encrypted JSON envelope | Rejects invalid/lossy rows rather than silently dropping them; no ICS/VCF/CSV or desktop complete-archive importer |
| Import replacement | Shared normalizer, explicit replacement confirmation, encrypted pre-import snapshot | Replaces the whole profile, not a merge; backup is internal, recovery UI not yet implemented |
| Export | SAF password-encrypted JSON, PBKDF2-HMAC-SHA256 + referenced AES-GCM primitive | Beta-specific envelope, not Notes backup or desktop complete-archive format |
| PDF/printing | Canonical print HTML into a separate script/bridge-free native print WebView | Android Print dialog includes Save as PDF; no automatic completion ACK; runtime/spooler validation pending |
| Reminders | Persisted one-off calendar/task/custom alarms, global and separate custom consent, inexact AlarmManager wakeup, boot/package restart receiver, delivery receipts | No recurrence/anniversary/health/SMS scheduling, exact alarm SLA, foreground service or force-stop bypass |
| Localization | Existing 20-language catalogs; two small manual beta strings in all 20 locales | Native locale follows Android, web locale follows organizer settings; linguistic review not claimed |
| Setup/holidays | Current canonical setup logic/catalogs and local country/region/cached-holiday display filter | No Android desktop setup wizard or OpenHolidays network backend; retrieval and period controls disabled |
| Text editing | Current canonical context menu, Undo/Redo and accessible Tab-key help | Key/help catalogs checked in all 20 locales; actual WebView editing history/IME acceptance pending |

Unsupported bridge operations reject; they never return invented success or empty
provider data. Desktop integration tabs/actions are disabled or replaced by beta
panels. Other unsupported calls show a localized unavailable message with the
command identifier. Main statuses are visible and accessible, not console-only.

Contact SMS/call buttons, their context-planning actions, mail/map/letter/social
launchers and corresponding external-integration settings are disabled. Local
contact phone/email/address editing remains available. The bridge rejects attempted
outgoing SMS/call/holiday commands without handing them to Android.

There is **no** EDS/Akonadi, Android account integration, Nextcloud/cloud backup,
Magnolienbaum/phone pairing, SMS/calls, Bluetooth/WLAN sync, medication/weather
lookup, desktop spelling service, LibreOffice/ODS/letter export, update service,
or desktop password-lock emulation. There is no INTERNET permission, system
contacts/calendar permission, shared UID, or account manager permission.
New file attachments via the WebView file picker are not implemented. Existing
embedded note data is retained by the shared core subject to its validation.

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
notification settings, imports and reminder delivery with saves.

Native random sessions/revisions now fence saves and restore confirmations.
Initialization must be acknowledged before writes are enabled. Uncertain
publication and committed-readback failures leave the old page non-writable;
only verified disk reload and a fresh page acknowledgment can reopen writes.
The selected native import bytes, not a frontend-supplied replacement body, are
committed and read back. Reminder follow-up failure cannot undo that commit.
SAF request codes are one-use and page/session-bound, with the next code retained
across Activity recreation. Late results do not consume a newer picker; background
import/export completions retain the original page authority. Destruction and
renderer loss invalidate queued work and callbacks.

`before-import.enc` is an encrypted internal pre-import snapshot. Each confirmed
import replaces it after syncing it, then replaces the main vault. Imported
notification permissions are **not** trusted: global and custom native consent
are reset, and the alarm schedule is empty until the web core reprojects it.
Custom module/item consent remains necessary in addition to native custom consent.

Export passwords are 8-1024 characters. The portable envelope is JSON with
`format: Magnolie-Organizer-Android-Tablet-Beta-1`, fixed 210000 PBKDF2 iterations,
random 32-byte salt, and authenticated encrypted JSON. Wrong passwords,
unsupported parameters and tampering reject. Keep the password separately:
Keystore data cannot be recovered after app uninstall; exported data can be
reopened with its password. There is no plaintext export switch in this MVP.

JSON state is limited to 16 MiB, incoming files/bridge envelopes to 32 MiB and
nesting to 64. SAF provider write, flush and close failures are surfaced; provider
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

The inspected environment has JDK 17, Android SDK under
`~/.local/share/android-sdk`, Gradle 8.13 cached under `~/.gradle`, and Bun (no
system Node executable). Install the small private web test dependency once:

```sh
bun install --frozen-lockfile
bash tools/build-beta.sh --readiness
bash tools/build-beta.sh
```

`MAGNOLIE_JS_RUNTIME=node` is supported on hosts with Node; otherwise Bun is the
default. `JAVA_HOME`, `ANDROID_HOME`, `GRADLE_USER_HOME` can be overridden.
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

### Owned emulator lifecycle (later, only with main permission)

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
does not constitute permission by itself. User test authorization already exists;
main's resource grant is deferred until the Windows native phase is finished.

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
text/RTL/TalkBack and Notes coexistence remain additional native acceptance work.

## Test Proof

After a successful complete gate:

- `artifacts/candidate.json`: exact APK identity/hash, source hash and unaccepted status.
- `artifacts/projection.json`: source inputs and generated-output hashes.
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

## Later Acceptance

The main session coordinates one emulator/VM at a time after the Windows native
phase. The prepared suite command above has not been executed in this invocation.

1. Install alongside Notes and verify both labels, application IDs and independent data.
2. Test 1280x800 landscape, portrait, large text, RTL, TalkBack, stylus, external keyboard and IME insets.
3. Create/edit calendar entries, tasks, contacts, notes and custom modules; background, kill and reopen.
4. Exercise real Keystore encryption, missing-key/corrupt-file fail-closed startup, fsync/rename fault boundaries and data recovery.
5. Import raw/valid encrypted JSON, reject invalid/tampered/oversized documents, cancel at each SAF/password/confirmation stage, and verify pre-import recovery data.
6. Export through local and remote SAF providers, simulate denial/full storage/cancellation, and round-trip encrypted data.
7. Print actual calendar, planner, contact and note selections to PDF; inspect multipage output, wrapping, images, cancellation and printer failure.
8. Exercise notification denial/revocation, custom consent/revocation, edits/deletions, background/Doze/reboot, batching and stable receipts. Verify unsupported recurrence is clearly understood.
9. Test origin/frame navigation attacks, print HTML injection, new-window/file requests and process recreation during pending operations.
10. Refresh the live projection, rerun all gates and record the exact candidate hash before making any acceptance decision.

Desktop artwork/fonts and code retain their existing licenses; see the parent
`LICENSE.md`, `PROTECTED-ASSETS-LICENSE.txt` and canonical font license. This beta
does not decrypt or bypass protected desktop assets/contributor controls.
