# Windows Background Fixes

Implementation unit for F01-F15 in the independent background audit. Production
release artifacts, signing, installation, real profiles, real Run entries and real
radio state were not used for validation. Setup UI/import choices, recurrence
algorithms, document export, runtime catalogs and Android/Linux backends were not
edited by this unit. The only Linux application changes are SMS JavaScript.

## Fixed IDs

| ID | Implementation |
| --- | --- |
| F01 | `BaumReceipt` implements versioned HKDF/HMAC receipts bound to the exact reserved encrypted envelope, counter and pinned peer key. Receivers durably cache receipts, recover inbox-before-state writes and replay cached acknowledgements without applying content twice. Senders persist uncertainty before transmission and retain unverified/old ambiguous reservations. |
| F02 | Both SMS schedulers use the existing `nachDauerhaftemSpeichern` callback before native dispatch and recheck item identity, lock state and phone availability. `SmsSubmissionJournal` records an uncertain intent before native transmission and never resends an existing reference. |
| F03 | `DeadlineHttp` keeps a deadline and disposal cancellation alive through response-body consumption. Baum, mailbox, DAV, updater and bridge-owned providers use it. Provider command queues are separated from the save/commit lane; synchronization has linked cancellation and no longer holds the mutation gate during HTTP work. |
| F04 | All three restore routes fence phone work, stop/drain connections, quarantine protocol data, invalidate old outbox/staging/commit records and persist a new epoch while preserving pairing/grants. An unsettled frontend personal-sync application blocks restore rather than allowing an old asynchronous apply across the restore. |
| F05 | Unlock schedules tracked optional-service startup/replay after releasing the command lane. Phone status is emitted before replay. Commit waits and network responses no longer require a lane held by Unlock. |
| F06 | Paired records retain their bounded authenticated completion receipt until the original pairing deadline, allowing a lost final response to be replayed after reopening. |
| F07 | Login startup requires explicit tray/autostart consent; reminder activation alone cannot enable it. Reminder registration failures are returned in the existing status callback. Failed tray saves do not replace the in-memory preference. |
| F08 | `CloudBackupWorker` independently checks due backups, consumes immutable successfully saved snapshots off the UI thread, serializes execution, persists success separately, and backs off failures. |
| F09 | Phone removal, session loss and shutdown release only app-owned radio holds. Phone workers and RFCOMM sockets are drained; RFCOMM startup has cancellation/deadlines. |
| F10 | Runtime/password reminder projection preserves validated structured task alarms. Reminder shutdown also drains active checks. |
| F11 | Close-to-tray applies only to user closes. The installer requests the registered terminal-exit message. Saved shutdown and UI script waits are bounded; session shutdown does not take the hide-to-tray branch. |
| F12 | Optional services are initialized behind independent failure boundaries rather than in the bridge constructor. A damaged optional backend does not own application startup. Partially allocated KDE listener resources are released on construction failure. |
| F13 | Program holds an exclusive profile file lease across setup and the complete main-window lifetime, in addition to the existing same-session mutex. The setup classifier ignores this ownership marker. |
| F14 | Scheduled SMS and history preserve `queued`, `submitted` and `uncertain`; native acceptance is not promoted to `sent`. Normalization and status labels preserve these states in both JS targets. |
| F15 | Uninstall removes the Run value only if it exactly matches one of the two application-generated commands for that installation path. |

## Receipt Handoff

The normative shared specification is `../contracts/baum-1-receipt-v1.md`.
Portable vectors are in `../contracts/baum-1-receipt-v1-vectors.json` and are checked
independently by .NET and JavaScript crypto implementations.

This is a symmetric authenticated receipt (HMAC), not a new asymmetric signature
scheme. It reuses the pinned-peer shared key with domain-separated HKDF-SHA256 and
HMAC-SHA256. The direct legacy request/encrypted envelope is unchanged. FS1 and the
existing authenticated Nextcloud mailbox receipt format are unchanged.

An HTTP 200 response without the receipt is NOT delivery proof. An uncertain
message stays in the queue and does not automatically retry or change transport.
Only a definite DNS failure/TCP connection refusal may use normal retry/fallback.
Old reserved envelopes without the new local receipt marker are conservatively
held. Receipt caches are bounded to 64 per peer and 256 per profile. Linux/Android
counterparts must implement the shared specification before normal authenticated
direct-legacy completion is available with those peers.

The SMS journal deliberately does not evict identities. At 10,000 entries it refuses
new submissions instead of making a late replay send twice. It proves at-most-once
submission attempts under the new implementation, not carrier delivery and not
unknown transmissions made before the journal existed. Preserve it across organizer
restore. No automated resubmission of an uncertain reference is provided.

## New Visible Msgids

Exactly these four new gettext message IDs require the main owner's manual updates
to the 19 non-English catalogs. No catalogs were edited here:

```text
The server response is too large.
The SMS submission journal is full. No message was sent.
The profile could not be locked. It may already be open in another session.
Wait for personal synchronization to finish before restoring.
```

Existing keys such as `Delivery status uncertain`, `Queued`, `Submitted`,
`Restore failed.` and `The background settings could not be saved.` were reused.
Protocol/storage status identifiers are not new gettext message IDs.

## Validation

- New SMS regression was first observed failing because dispatch preceded saving;
  the task-alarm regression was first observed failing because projection lost it.
  The previous audit's API reproducers also established the other runtime defects.
- `tests/background-sms.js`: both current Windows and Linux SMS targets pass durable
  dispatch, removed/restored-item protection, unavailable-phone protection and
  submission-not-sent checks. Standalone Windows source explicitly skips an absent
  Linux target; both targets were present and executed in this checkout.
- `tests/background-receipt-vectors.js`: independent HKDF/HMAC/vector check passes.
- `BackgroundLifecycleTests`: actual API coverage includes callback draining,
  same-profile ownership exclusion/reacquisition, SMS crash-journal reopening,
  final pairing acknowledgement replay, wrong-key/direction/envelope/extra-field
  rejection, durable receiver receipt replay, unsigned sender response retention,
  restore fencing/quarantine/token invalidation, preserved pairing, owned-radio
  cleanup with a fake radio, periodic cloud recurrence without another save,
  immutable snapshots, restart deduplication, and loopback HTTP deadline/disposal.
- Full Core suite on Linux with SDK 8.0.408: **38/42 groups pass**. Four failures are
  reproduced with the pre-change audit binary: LDIF yearless birthdays (two groups),
  contact REV/ETag conflict handling, and setup camelCase selection expectations.
  Those unrelated owners' implementations/expectations were not changed to make
  this unit green. A transient fixed-port setup-test failure during concurrent
  testing disappeared when rerun; no real process was stopped.
- Windows application project compilation: **0 warnings, 0 errors**.
- Native SSH host exactly `windows`, user `maik3`, Windows build 26200.9445, .NET
  8.0.31: **4/4 selected groups pass** (background lifecycle, phone/personal sync,
  current setup lifecycle, KDE synthetic TLS integration). The focused group also
  runs real DPAPI identity reopening and verified encrypted backup creation in a
  generated private profile. Actual radios and actual HKCU Run entries are not used.
- NSIS transaction fixtures pass. The current NSIS source compiles against a
  synthetic non-application payload into a private temporary fixture only. The
  fixture was not executed or published.

Commands and captured outputs are under `/tmp/opencode/background-fixes/`:

```sh
bun /tmp/opencode/background-fixes/run.mjs test
bun /tmp/opencode/background-fixes/run.mjs app
bun tests/background-sms.js
bun tests/background-receipt-vectors.js
bun tests/nsis-installer-fixture.js
bun /tmp/opencode/background-fixes/nsis.mjs
bun /tmp/opencode/background-fixes/run.mjs publish
bun /tmp/opencode/background-fixes/native.mjs
```

`publish` above publishes ONLY the temporary CoreTests harness, not the application.
Native harness files live in `C:\Users\maik3\AppData\Local\Temp\magnolie-background-fixes-b7a31`.
Relevant logs are `test-full.log`, `app-latest.log`, `native-results.log` and `nsis.log`.

## Proof Limits

Native Core tests exercise Windows DPAPI, SQLite, sockets and Schannel, not the full
WinForms/WebView application. Wiring tests for UI close reasons, autostart error
propagation, optional initialization and installer registration cleanup supplement
the API tests; they are not native HKCU/UI/session-shutdown execution proof.

WinRT/RFCOMM code was Windows-target compiled, but real Bluetooth hardware/radio
changes were not exercised. No Windows 10, ARM64/x86, all-edition/policy, actual
multi-session, suspend/resume, power-cut or unavailable-SMB-driver validation was
performed. Managed cancellation cannot promise interruption of every blocked native
filesystem operation. On OS-forced shutdown the last durably saved state is the
boundary; this does not promise recovery of unsaved renderer keystrokes.

An unfinished personal-sync frontend callback intentionally prevents restore in
that window. A failed callback may require reopening the organizer; it is not
safe to discard this barrier and allow an older asynchronous application to cross
the restore. Queue quarantines are retained as recovery evidence, not replayed.

These results do not certify all Windows 10/11 variants or a production release.
