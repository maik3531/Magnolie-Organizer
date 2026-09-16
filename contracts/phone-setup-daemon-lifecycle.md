# Phone setup ownership and startup lifecycle

This unit completes the daemon-owned setup path and startup-consent handoff. It
does not replace telephone authentication, change KDE selected-device pairing, or
implement WhatsApp. The broader background-services audit is a separate review.

## Linux IPC contract

All operations use the existing private per-user Unix socket. Its parent remains
mode 0700 and its socket mode 0600. The server checks kernel SO_PEERCRED against
its UID before dispatch. Setup requests additionally bind a random 256-bit token
to that observed UID and PID. The setup client also checks the server's UID.
Caller-supplied UID/PID fields are not accepted.

| Operation | Exact arguments |
|---|---|
| `phone_setup_begin` | `{}` |
| `phone_setup_list` | `{session}` |
| `phone_setup_connect` | `{session, transport}` |
| `phone_setup_status` | `{session}` |
| `phone_setup_confirm` | `{session, prompt, answer}` |
| `phone_setup_commit` | `{session, transports}` |
| `phone_setup_cancel` | `{session}` |

Transport IDs remain `wifi`, `bluetooth`, `kdeconnect`. Setup arguments are limited
to 4096 encoded bytes and exact schemas; unknown fields, malformed tokens, unknown
IDs and duplicate startup IDs are rejected. Sessions last at most 600 seconds,
without poll-based extension. Connection attempts and pending prompts are capped
at 120 seconds. There is one setup lease at a time, and no overlapping connection
attempts. Prompt IDs are independent random 128-bit values and are consumed once.
Prompts contain at most 32 devices, bounded IDs/names and a bounded code. Selection
answers must be from that prompt's device list; `accept-own` is permitted only on
the actual application confirmation prompt that offers the checkbox.

The same-UID boundary is intentional: existing regular IPC APIs already authorize
that user to control their services. These tokens separate GUI sessions and stale
requests; they are not a sandbox against malicious code with the same account's
full access. A daemon restart invalidates every setup token. Tokens are not sent
to phones, stored in setup markers, or forwarded on the ordinary event bus.

## Ownership and authentication

`PhoneSetupSessions` borrows the daemon's actual PhoneService/KDE backend and runs
the existing SetupPhoneServices WLAN/Bluetooth/KDE adapters. No GUI-side fallback
listener is created when a daemon owns the service, including when an older or
starting daemon cannot yet service the new request. Such failures are reported,
not used as permission to take ports.

Only pairing-code events matching the adapter's owned telephone pairing token,
attempt and target go to its setup prompt. Other phone events, including ordinary
call events, continue through PhoneDaemonEvents. Owned KDE pairing events likewise
stay with their setup prompt. Global pairing-decision permissions are not enabled.
Conflicting regular pairing mutations are rejected while setup is connecting;
ordinary call/data operations are not put behind that setup mutation lock.

Discovery results, start acknowledgements and answer acknowledgements never mean
connected. The broker checks the adapter's authenticated result against its
selected identity, connected-ID map and current authenticated online status. All
telephone matching-code and confirmation/finish proofs still run in the existing
protocol implementations. Own-phone state is changed only by the existing adapter
after authenticated success and explicit `accept-own` consent.

Cancellation signals the worker and closes only setup-owned pending requests.
Cleanup runs outside the broker lock, drains the worker, and keeps the lease in
closing state until ownership is released. The cancel reply includes `released`.
A pre-existing daemon listener is not stopped. If setup temporarily started a
previously stopped phone backend, it is released unless approved normal startup
has adopted it. A previously open normal pairing window is restored with a fresh
public token after the setup worker drains. Completed relationships are retained.

## Finish and startup consent

Both final pages retain default-off phone startup controls, shown only for an
authenticated connection. Finish revalidates live connections. Skip/Cancel do not
commit startup. Service IDs are persisted in the setup selection; Linux also
records `phone_setup_services` in background settings for inspection on restart.

`wifi` and `bluetooth` map to the **same existing phone monitor**, not two processes
or exclusive transport policies. `kdeconnect` maps to the existing KDE service.
Only required permissions are added, preserving other service permissions. These
IDs do not authorize contacts, microphone, notifications or personal-data grants.

Linux writes the completed setup marker before starting a new daemon, preserving
the existing pending-setup bootstrap guard. It then persists approved settings and
the actual XDG autostart entry, releases local setup listeners before daemon
startup, or applies settings through the already-running owner. Startup failure
restores prior settings/autostart state and returns the marker to pending. Corrupt
settings and obstructing user paths are rejected, not deleted or repaired in
place. A failed newly spawned bootstrap child is terminated by its owned process
handle, never by looking up or killing the user's existing daemon.

Windows setup runtime enablement is now in-memory: connecting does not persist
`TelefonStore.Enabled`. `FirstRunPhoneFinish` saves the completed marker, then
commits actual tray/autostart and phone-enabled preferences. Failure rolls back
the prior tray record, exact registry value/type and phone preference, and returns
the marker to pending. A pre-existing approved reminder/tray command is retained.
The registry interface is injectable; tests never write the user's HKCU.

Finish persists the verified phone connection preference on both platforms even
when background startup is unchecked. This is the same preference shown in Phone
Settings and consumed on the next application launch; it is not consent to create
a login entry or start a daemon. Skip/Cancel do not commit this preference. The
internal foreground handoff remains nonserialized, but is no longer the only way
to resume the connection after a successful Finish. Pairing keys and IDs survive.
A disposed coordinator cannot restart. Linux checks actual daemon listening status
before selecting a local owner. Windows Settings reads the same Bluetooth route
as reconnect and reports the actual transport, not WLAN for every online session.
Bluetooth availability does not erase or visually uncheck a saved preference.
Discovery aliases are deduplicated by device ID or OS Bluetooth address, never by
friendly/product name; independent Magnolie Notes and KDE identities stay separate.

## Changed entrypoints for reviewers

| Component | Entrypoints to review |
|---|---|
| Linux setup adapters/broker | `magnolie_setup_state.py`: SetupPhoneServices remote delegation, borrowed ownership, `finish_setup`, `_commit_startup_local`, `close`, `restore_borrowed_state`; PhoneSetupSessions |
| Linux existing IPC | `magnolie_hintergrund.py`: `_request_shape`, IPCServer setup dispatch, SO_PEERCRED checks, cancellation drain, `_setup_startup` |
| Linux daemon lifecycle | `daemon_main`: owner-provided phone factory, pairing-event routing, runtime adoption/revocation in `apply_settings`; `start_service` timeout cleanup |
| Linux setup UI/handoff | `magnolie_setup_ui.py`: final Finish callback; `magnolie-organizer`: setup phone owner detection and `_telefon_dienst_pflegen` foreground/owner selection |
| Windows startup transaction | `FirstRunPhoneStartup.cs`: IPhoneStartupPlatform, NativePhoneStartupPlatform, FirstRunPhoneStartup, FirstRunPhoneFinish |
| Windows settings adapter | TraySettingsService capture/restore of the app's own Run registration; TelefonStore strict enabled-state read |
| Windows runtime handoff | FirstRunSetupPhoneServices transient start; FirstRunSetupForm Finish; FirstRunSetupSelections internal foreground field; BridgeDispatcher telephone constructor; TelefonCoordinator transient enablement/disposed-start guard |

No main-window initialization guard, general data/sync algorithm, recurrence,
catalog, handbook, update or release code was changed for this unit.

## Verification

Final current-source results: 105 Android telephone tests passed with WLAN and
Bluetooth integration enabled; 154 focused Linux setup/phone/background tests
passed; all five C# telephone/lifecycle groups passed. Windows-target application
and CoreTests builds completed with zero warnings/errors. The Linux run reported
two existing GTK deprecation warnings. Scoped `git diff --check` passed, and no
isolated setup-daemon fixture processes remained running.

New focused tests:

- `test_phone_setup_sessions.py`: real Unix framing and kernel peer credentials,
  wrong expected UID policy, a separate client PID using another client's token,
  wrong/missing/expired tokens, exact schemas, stale/replayed prompts, selected
  target enforcement, no trust from a claimed ACK, concurrent mutation rejection,
  existing-owner preservation, lazy temporary-owner release, KDE confirmation,
  actual temporary XDG settings/autostart files, startup failure and corrupt-path
  refusal.
- `phone_setup_daemon_host.py`: a separate daemon_main process under a private
  dbus-run-session, HOME/XDG tree and Unix socket. Only OS discovery/bonding and
  notifications are fixture adapters; telephone crypto and IPC run unchanged.
- Android telephone integrations: actual WLAN and first-Bluetooth pairing through
  that daemon owner, explicit matching codes, authenticated sessions/reconnect;
  Finish persistence and real daemon restart with stale-token rejection.
- `PhoneStartupLifecycleTests.cs`: real temporary tray/phone files with a fake
  registry adapter; default-off, chosen service mappings, Finish, Skip, Cancel,
  exact rollback and idempotent/disposed runtime ownership.
- Windows phone integration host: dispose setup, recreate the runtime from stored
  routes, and authenticate again both with foreground-only intent and with
  persisted Finish startup consent.

The unit fixtures do not use the real daemon, real HKCU, systemd, production
phones, production signing keys or installed production APKs. No validation APK
was needed in this unit.

## Following background audit

The read-only broader audit should cover the existing background modules as well:
daemon permission normalization/apply_settings, KDE receive/notification paths,
PhoneDaemonEvents and DaemonEvents, GUI proxy subscriptions/freshness, native
notification actions, process/autostart launch wrappers, reminder/tray startup,
periodic backup/snapshot scheduling, shutdown/drain, sleep/resume and policy
revocation. Relevant existing suites include `test_hintergrunddienst.py`,
`test_ersteinrichtung.py`, C# tray/reminder/recovery tests and the telephone suites.
That audit is not represented here as a new implementation or a completed review
of every unrelated service.

Physical handset/radio behavior, actual desktop login activation and real Windows
registry/OS approval effects remain native-environment checks; they were not
mutated or certified by these isolated fixtures.

## New desktop gettext strings

- `Another phone setup session is active.`
- `The phone setup session expired. Reopen phone setup and try again.`
- `The phone setup session belongs to another client.`
- `The phone setup request is no longer current.`
- `Phone setup is unavailable in this background service. Restart the background service and try again.`
- `The background service could not start.`

Existing connection-failure/background-save messages are reused. Protocol-only
schema diagnostics are mapped to existing GUI failure text. There are no new
Android production strings in this unit; the earlier manual 20-locale Bluetooth
translations are unchanged. New C# sources are included by SDK source globbing
and explicitly linked into CoreTests. Linux helpers stay in already-installed
modules, so no package manifest or release/catalog update is needed.
