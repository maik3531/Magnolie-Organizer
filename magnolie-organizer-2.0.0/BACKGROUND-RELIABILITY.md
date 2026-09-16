# Linux Background Reliability Fixes

Canonical Linux source changes, 2026-09-09. No release artifacts, catalogs,
Android files, Windows application files, setup UI, import implementation,
letter code, or recurrence algorithms were changed by this work.

## Fixed IDs

| Review ID | Implementation |
| --- | --- |
| 1: Busy IPC duplicate owner | `FileLease` uses nonblocking kernel `flock`, a persistent 0600 regular file and inode validation. The lock file is never unlinked. Socket removal requires the owning process and matching socket inode. A failed ping while the lease is held is reported as an unavailable/starting owner, not a stopped service. A duplicate cannot rewrite freshness state before claiming ownership. |
| 2: Mandatory KDE failure | KDE initialization/start failure produces `kde_transport_error=transport_unavailable` while the daemon and opted-in phone listener remain available. A missing backend returns unavailable status rather than aborting independent services. Reminders remain a separate process. |
| 3: Clock rollback | Startup establishes a current wall-clock cutoff without discarding persisted event identities. A running service detects a backward discontinuity exceeding one second relative to monotonic time and begins a new cutoff epoch at correction time. Dated history before that cutoff and timestamps more than 60 seconds ahead are suppressed. Identity retention remains bounded. |
| 4: Backup/shutdown drain | The save queue task and busy flag now cover backup creation, verification, retention and result delivery. Confirmed shutdown polls for actual completion. Cancellation cancels shutdown, not an already-started backup; request generations prevent stale timeout callbacks from cancelling later shutdown requests. Final destruction joins the save worker. Worker result errors prevent silent exit. |
| 5: Reminder PID ownership | Reminder instances hold a lifetime kernel lease independent of the advisory PID text. Cleanup checks process, inode and PID content before removing the marker. The CLI requires successful acquisition, and both fallback and real GLib loops handle termination. |
| 6: Phone stop/restart | Stop interrupts pending and established sockets, cancels pairing, drains tracked handlers and listener/Bluetooth workers, and refuses restart while an old generation remains alive. Bluetooth connect receives the cancellation event. A daemon shutdown whose phone workers fail to drain reports failure, not success. |
| Baum-1 receipt v1 | Direct legacy responses implement the shared `contracts/baum-1-receipt-v1.md` exactly: existing partner key, HKDF-SHA256 receipt domain, canonical complete envelope hash and HMAC-SHA256 receipt. Only an authenticated matching receipt permits outbox removal. |

The completed daemon setup-session UID/PID/token checks, operation shapes,
live connected-state validation, and borrowed-owner implementation in
`magnolie_setup_state.py` were preserved. The headless CLI test now explicitly
writes its own completed setup marker; the real fresh-profile gate was not bypassed.

## Receipt Persistence

- New legacy reservations persist their exact ciphertext/counter and `receiptProtocol:1` before transmission. The GUI and maintenance paths persist the outgoing counter before sending.
- Direct attempts persist `receiptAttempted:true` and `unsicher:true` before bytes are sent.
- Bare HTTP success, unsigned/invalid receipts, resets, timeouts, cancellation and HTTP error responses leave the item uncertain and stop automatic retransmission/transport fallback.
- Only DNS failure or connection refusal can clear those flags and use backoff or another delivery transport.
- Old reserved envelopes without protocol 1 are uncertain, including after an FS1 upgrade. They are not converted into new messages or silently acknowledged.
- Receivers store the effect before receipt/counter persistence. Inbox records include `directEnvelopeHash` to recover an inbox-before-state crash without reapplying content. Exact cached receipts survive restart; unknown stale counters are rejected.
- Receipt caches are bounded to 64 per peer and 256 per profile, evicting oldest entries from the largest peer cache.
- FS1 cryptography and the authenticated Nextcloud mailbox receipt format are unchanged. Direct uncertainty never triggers mailbox fallback.

## Permanent Tests

- `pruefungen/test_background_reliability.py`: busy eight-handler duplicate ownership, second-process kernel contention, socket inode cleanup, real private GLib daemon and phone listener, crash restart, degraded KDE, clock rollback, independent reminder leases, actual alarm CLI duplicate/SIGTERM, backup completion/cancel tracking and phone draining.
- `pruefungen/test_baum_receipts.py`: shared byte vectors and rejected mutations, durable receiver restart/replay, inbox-before-state recovery, uncertain delivery across all relevant failure classes, old reservations, persistence failure, cache bounds and private Linux HTTP delivery.
- `pruefungen/receipt-native/`: a fresh-source C# test peer linking the canonical Windows `MagnolienbaumCrypto.cs` and `BaumReceipt.cs`, not a copy of those algorithms. Tests cover the public vectors and a fresh X25519 Linux/Windows pair exchanging encrypted envelopes and authenticated receipts in both directions over private loopback HTTP.
- `pruefungen/run_background_reliability.py`: isolates HOME and XDG directories before loading the test suites, disables source-tree bytecode/cache writes, blocks discovery, fixed-port binds, external connections and desktop/system subprocesses, and uses nonexistent private D-Bus addresses. Temporary test profiles are removed at the end.
- Existing daemon, phone, invitation, setup, backup, journal and Nextcloud tests remain part of the focused run. Legacy Baum test expectations were changed from boolean HTTP acknowledgments/retries to durable reservations and authenticated receipts.

### Results

Final permanent-runner execution: **267 passed, 0 failed, 0 skipped**, in 46.72 seconds.
This includes **26 new parameterized test cases**, of which two are the explicit
fresh Windows-source interoperability/vector tests. The focused phone setup-session
suite contributes all 18 existing cases; none was bypassed.

Fresh C# probe build: **0 warnings, 0 errors**. Python syntax compilation and
`git diff --check` for the touched tracked source/test paths passed.

Earlier failures were investigated rather than counted as passes: obsolete
boolean-ACK/retry assertions were updated to the public receipt contract; the
Bluetooth fixture now accepts the existing backend's cancellation argument;
the test runner's IPv6-only rewrite was corrected to support private IPv4-mapped
phone clients. The final run has no pending failure or skip from these cases.

### Running

From the canonical Linux directory:

```sh
python3 -B pruefungen/run_background_reliability.py
```

The default selection includes the focused Python suites, not the explicit .NET
probe. To include the probe, build `pruefungen/receipt-native/ReceiptProbe.csproj`
with an existing .NET 8 SDK and cached BouncyCastle assembly. Set
`BouncyCastlePath`, `BaseIntermediateOutputPath`, and `OutputPath` to private
temporary locations. Use an empty local `RestoreSources` directory and
`NuGetAudit=false` for the first restore, then `--no-restore`; no package download
is needed. Set private HOME/XDG and `DOTNET_CLI_HOME` for the build, and set
`DOTNET_GENERATE_ASPNET_CERTIFICATE=false` and `DOTNET_CLI_TELEMETRY_OPTOUT=1`.

The verified build used `/tmp/opencode/dotnet-8.0.408/dotnet`, the cached
`/tmp/opencode/background-fixes/native/BouncyCastle.Cryptography.dll`, and output
under `/tmp/opencode/linux-bg-fixes`. Only the dependency assembly is reused;
the Windows cryptography and receipt sources are compiled fresh.

Then run with `MAGNOLIE_DOTNET` and `MAGNOLIE_RECEIPT_PROBE` pointing to that SDK
and freshly built `ReceiptProbe.dll`:

```sh
python3 -B pruefungen/run_background_reliability.py \
  test_background_reliability.py test_baum_receipts.py \
  receipt-native/cross_receipt.py test_hintergrunddienst.py \
  test_phone_setup_sessions.py test_automatic_cloud_backup.py \
  test_journal_periodisch.py test_wiederherstellungsjournal.py \
  test_setup_services.py test_naechster_weckzeitpunkt.py \
  test_phone_bluetooth_setup.py test_phone_invitation.py test_telefon.py \
  test_native_sync_safety.py test_nextcloud.py
```

The explicit cross-platform test fails when its build/environment prerequisites
are absent; it does not silently skip or report success.

## Visible Strings

Exact handoff: `pruefungen/background-visible-msgids.txt`.

Main domain (`magnolie-organizer`):

- `KDE Connect is unavailable; other background services remain active.`
- `Delivery status uncertain`
- `The phone service did not finish stopping.`

Manual/handbook domain: **no new msgids**. Translation handoff covers all 19
catalog locales: `ar be cs da de es fr hi hsb it ja nb nl pl pt ru tr uk zh_CN`.
No catalogs were edited or regenerated; untranslated strings currently fall
back to their source text.

## Warnings and Gaps

- Tests never stopped a real user process/service or invoked the user's systemd, keyring or D-Bus services. All signalled processes were test children. No app installation, update, publication or network discovery was performed.
- The initial .NET SDK first-use build emitted its development-certificate initialization notice inside the private temporary HOME. Subsequent builds disable certificate generation. No user certificate store or credentials were accessed intentionally.
- Actual login/logout, suspend/resume, RTC wake permissions, real desktop notifications/clipboard and compositor behavior are not proven by these tests.
- Physical WLAN/BlueZ/KDE phone interoperability was not exercised. The existing invitation/Bluetooth protocol tests and daemon setup-session tests passed against their private fixtures; this is not a real radio/Android acceptance test.
- The Windows loopback probe links the real current Windows cryptography/receipt implementations, but its HTTP wrapper is a test host. It is not a Windows desktop run or an end-to-end test of the full Windows coordinator's persistence/lifecycle.
- The monolithic `test_parser.py` suite was not executed: it contains fixed-port and discovery scenarios outside the isolated runner's allowed operations. The touched test file was syntax-checked; dedicated permanent tests cover the changed receipt and lifecycle paths. No monolithic-suite pass is claimed.
- Real power loss, full disks, blocked network filesystems and a locked/unresponsive Secret Service are not simulated. An unresponsive backup must finish or fail before final GUI exit; cancellation of a shutdown request does not forcibly terminate archive writing.
- A phone worker that does not drain within five seconds keeps same-process restart disabled; daemon exit reports the incomplete stop. This is fail-closed behavior, not an assertion that arbitrary third-party backend code can always be cancelled immediately.
- No automatic crash supervisor was added. Explicit process restart and stale-socket recovery are tested; real login/autostart behavior remains an integration gap.
- Undated event handling retains the existing live-event policy. Clock tests prove dated-history filtering and persistent identity deduplication, not the ability to identify previously unseen undated history from a remote peer.
