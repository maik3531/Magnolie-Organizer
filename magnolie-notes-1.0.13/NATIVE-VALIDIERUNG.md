# Native Validation for 1.0.14

Version stays 1.0.14 / code 14. This document describes private validation, not a
production release approval.

## Safety Boundary

- The native runner requires the exact application ID
  `io.gitlab.maik3531.magnolienotes.validation` and emulator hardware `ranchu` or
  `goldfish`. It refuses the production package and physical-device hardware.
- `src/validation` is an opt-in source overlay. It is not part of normal debug or
  release builds. Its account authenticator and SAF proxy exist only to exercise
  native APIs with synthetic data.
- The account fixture owns a fresh account and disables aggregation with unrelated
  contacts. Reads are account-scoped; cleanup addresses only the created raw IDs
  with matching account name/type. No real account credentials are used.
- The SAF proxy accepts only its exact newly generated UUID-named Documents folder.
  It refuses other returned folder URIs before passing them to automatic backup.
- The production release gate, production signing and canonical dependency locks
  remain unchanged. The validation APK is debuggable, test-signed and not an
  install/upgrade candidate for a production installation.

## Local Environment

Read-only inventory found no connected device initially. Existing AVDs:

- `magnolie`: installed API 34 Google APIs x86_64 image, used for this validation.
- `magnolie-api35`: configured, but its referenced API 35 system image was absent.
  No system image was downloaded or installed.

The test AVD was started on port 5584 with `-read-only -no-snapshot
-no-snapshot-save -no-window`. No userdata wipe was performed. Guest Wi-Fi and
mobile data were disabled during validation; these tests do not validate a cloud
provider or background network scheduling.

## Reproduction

Local harnesses are under `/tmp/opencode/android-fixes-20260907/`:

- `gradle.sh`: isolated HOME/XDG/Android/Gradle settings, installed SDK/JDK,
  offline resolution, strict dependency verification, no build cache.
- `native-gradle.sh` and `native.init.gradle`: separate build output and Gradle
  project cache, validation application ID, opt-in source overlay, debug native
  runner, separate temporary dependency lock; release tasks are forbidden.
- `lint_summary.py`: aggregates lint issue IDs and severities without reading
  credentials or signing material.

Build native fixtures with the local wrapper:

```sh
bash /tmp/opencode/android-fixes-20260907/native-gradle.sh :app:assembleDebug :app:assembleDebugAndroidTest --rerun-tasks --console=plain
```

Only after verifying the dedicated AVD identity and APK application IDs, install
the validation packages, not the production package. The runner component is:

```text
io.gitlab.maik3531.magnolienotes.validation.test/io.gitlab.maik3531.magnolienotes.ValidationTestRunner
```

Run `am instrument -r -w -e phase core` for Keystore, SAF, isolated contacts,
authenticated pairing and editor Back checks. `phase seed` enters an actual editor
draft, rotates the activity and backgrounds it. Force-stop only the validation
package, then run `phase restart`; it checks a different PID and the recovered
encrypted draft. `phase editor` and `phase saf` isolate the respective UI checks.

For the completed SAF gate, run `phase saf-host` with `saf-approve.py` driving
the observed DocumentsUI folder confirmation and explicit permission dialog.
After success, force-stop only the validation package and run `phase saf-restart`.
The restart phase checks retained grants in a different PID, re-enables periodic
backup, authenticates the new archive and deletes the exact owned fixture folder.

Read `INSTRUMENTATION_RESULT: failures` and each named result. An adb process exit
code of zero is not proof that instrumentation passed. The runner reports failures
without dumping passwords, keys or complete assertion payloads.

## Evidence and Remaining Gates

The current canonical JVM run completed 351 tests with zero failures and zero
skips, including the live Organizer probe and two SAF MIME/retention regressions.
The native results below include the earlier core/editor phases and the final
successful SAF phases after the verified provider-MIME fix:

| Native check | Result |
|---|---|
| startupAndKeystore | PASS: actual non-exportable Keystore key, IV generation, tamper rejection, automatic-backup password setup/reload |
| contactsInIsolatedAccount | PASS: actual ContactsProvider, scoped synthetic account, names and separate yearless birthday/anniversary events |
| authenticatedUpgradeAndReplay | PASS: same-key upgrade, retained live FS session, durable replay and legacy duplicate handling |
| editorBackSaves | PASS: actual editor input, system Back and labeled toolbar Back |
| safAutomaticBackup | PASS: explicit DocumentsUI consent, persisted read/write grants, actual periodic worker, encrypted archive and authenticated full Bestand equality |
| safBackupAfterRestart | PASS: different PID, retained URI grants, re-enabled periodic worker creates another archive, authenticated full Bestand equality and owned-folder cleanup |
| seedDraftAndRotate | PASS: actual text survives landscape recreation and lifecycle flushing |
| verifyDraftAfterProcessDeath | PASS: a different process restores and displays the encrypted draft; backup password configuration remains present |

The separate rotation and process-restart phases validate the encrypted draft in
the rendered editor, not only an in-memory model. See the final instrumentation
results for their individual phase outcomes; do not infer success from adb exit.
The owned read-only emulator session was stopped after these checks; no original
AVD userdata wipe, production-package replacement or production signing occurred.

The native runs established working Keystore password wrapping and protected
password reload, isolated-account contact names/yearless dates/anniversaries,
same-key file upgrade and exact replay, system/toolbar Back saves, rotation and
draft recovery after process death. The early-entry startup signal race found
during these runs has a failing-before/passing-after JVM regression.

The completed SAF gate supersedes the earlier picker-automation failure. Actual
ExternalStorageProvider metadata then exposed a product defect: it preserves the
generated `.magnolie` filename but returns `application/octet-stream` instead of
the requested custom MIME. `AutoSicherungKern.kt` now accepts either MIME only
with the strict generated filename pattern; creation still requires the exact
requested name and authenticated readback. Retention authenticates candidates
before deletion, leaves invalid archives untouched and reports a retention error.
No visible strings were added by this fix.

Final evidence under `/tmp/opencode/android-fixes-20260907/`:

- `native-saf-final.log`: startupAndKeystore and safAutomaticBackup PASS,
  `failures=0`, `numtests=2`, `INSTRUMENTATION_CODE: -1`.
- `native-saf-restart.log`: safBackupAfterRestart PASS, `failures=0`,
  `numtests=1`, `INSTRUMENTATION_CODE: -1`.
- `native-saf-ui.log`: observed folder confirmation and explicit permission grant.
- `saf-folder.png` and `saf-permission.png`: synthetic DocumentsUI evidence.

Both SAF phases use the real periodic WorkManager job and await successful
completion plus a future scheduled execution. This validates initial executions,
including re-enabling backup after process restart, not an elapsed weekly interval
or uninterrupted scheduling through force-stop. Archive IO uses SAF, not a direct
filesystem bypass. The restart test also asserts deletion of its generated files
and exact UUID folder after cancelling fixture work.

Full readback means the portable `Bestand`: notes, notebooks, tasks, trash and
attachments. The synthetic contact-v2 JSON is stored as note content and preserves
names, `anzeigename`, `vcardName`, yearless dates and photo bytes. This does not
claim backup or restore of Android system contacts. A temporary test-only race
from launching manual and periodic work together was removed by awaiting one
periodic worker; it was not an encryption defect.

Real API 26 and API 35 execution, physical-device behavior, spoken TalkBack,
all-language large-font/RTL layouts, sustained long calls/proximity behavior,
real Bluetooth/LAN faults, cloud-provider scheduling, production R8/signing and
in-place production upgrade remain separate release gates.

## Lint Classification

The original report had 60 warnings and 2 informational items. Three warning
classes were addressed without suppressions: explicit foreground API guarding,
an early receiver-action allowlist, and a safety timeout for the proximity wake
lock. Current canonical lint has zero errors, 57 warnings and 2 informational
items:

| Issue | Count | Classification |
|---|---:|---|
| ApplySharedPref | 13 | Deliberate synchronous persistence of control/consent settings; do not replace with asynchronous writes just to silence lint. |
| StaticFieldLeak | 5 | Process singletons retain application contexts, not Activity instances. |
| UsableSpace | 4 | Conservative prechecks; actual IO failures remain handled. Cache eviction/allocation APIs are a separate optimization. |
| UnusedResources | 27 | Resource housekeeping, not a demonstrated runtime failure. |
| Typos | 5 | Norwegian capitalization, Turkish reduplications and German word separation require linguistic context; no mechanical corrections. |
| PluralsCandidate | 1 | Existing multi-count preview wording remains a presentation follow-up. |
| UnusedAttribute | 1 | App-locale metadata is intentionally used by newer Android versions. |
| ObsoleteSdkInt | 1 | Adaptive-icon resource directory can be simplified; behavior is valid. |
| AutoboxingStateCreation | 2 information | Small state-allocation optimization, not a correctness blocker. |

Touch targets and actionable semantics were also improved. Android accessibility
trees may expose a label as a descendant of the clickable Material surface;
the native probe follows that relationship rather than falsely requiring both
properties on the same node.
