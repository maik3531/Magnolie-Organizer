# Call Alerts and Actions

This extends the existing call-state v2 lifecycle without changing pairing, file
approval, SMS, contacts synchronization, or HFP routing.

## Direction and Consent

- An explicit desktop dial intention owns its `client_ref` / `call_ref` throughout
  ringing, off-hook and idle. The historical wire state `ringing` can describe an
  outgoing dial attempt; it does not by itself mean an incoming call.
- Only `direction=incoming` together with `state=ringing` may raise an incoming
  alert. An initially observed off-hook call remains `unknown`, not incoming.
- Local call settings govern a ready GUI, including a hidden/tray GUI. The Linux
  daemon uses the independent background call-notification opt-in when no ready
  GUI is attached. Neither path auto-enables incoming answer permission.
- A call ID cannot change direction or return from idle to ringing. Older
  revisions and older call timestamps are rejected.

## Rejection Version 2

`end_call` capability version 1 retains off-hook termination. Android advertises
versions `[1, 2]`; version 2 additionally accepts:

```json
{
  "command_ref": "33333333-3333-4333-8333-333333333333",
  "call_ref": "22222222-2222-4222-8222-222222222222",
  "expected_revision": 1,
  "expected_state": "ringing"
}
```

The command TTL remains at most ten seconds. A ringing rejection is offered only
when the peer advertises version 2 and both sides grant the relevant controls.
The existing result schema is unchanged. Submitted means a request was submitted,
not that the OS has confirmed an answered or disconnected call.

## Notification Tickets

- Each action gets a cryptographically random 256-bit token, valid for at most
  sixty seconds. Only process memory holds its peer identity, connection object,
  call ID, revision, action and deadline. Tokens are not backup/profile records.
- Consumption rechecks the paired identity, live connection, ringing direction,
  revision, capability and current bilateral grants. The ticket and its sibling
  action are consumed before sending. Reconnect, restart, grant changes and stale
  IDs fail closed. A click cannot turn into a command for the next observed call.
- Linux cold activation uses `--call-action TOKEN` and the existing same-UID,
  owner-protected Unix IPC. Hidden GUI readiness is distinct from window visibility.
  The live owner consumes/revalidates the token before launching the GUI; the GUI
  launch carries no call request and cannot replay it after startup or reconnect.
- Windows system actions use a per-user `magnolie-call:` protocol handler and a
  current-user-only, session-specific named pipe. The launcher loads no profile.
  Elevated activation is rejected. No Windows service or elevated registration is
  installed; a living tray/application host is required for new notifications.
  Successful system-action activation restores that existing GUI. An expired
  host/session cannot be recreated from a notification token.
- Numbers, contact names and photos never appear in tickets or activation
  arguments. Contact enrichment is local, unambiguous and tied to the authorized
  call number; remote photo URLs are not fetched.

## Linux Alert Handoff

GUI document readiness is not a delivery acknowledgement. A daemon-forwarded
ringing event includes a separate opaque `call_delivery` token. The existing
`phone_event` IPC ticket only retrieves the event; it does not acknowledge display.
The native GUI reads loaded call settings and can present before `App.init` or
`telefonStand` has run. A later phone-status refresh retries a retained live event.

The same-user `phone_call_alert` operation accepts `claim`, `shown`, `failed`, or
`current`, bound to that delivery token. The GUI claims immediately before native
presentation; GTK acknowledges its map event, and a system notification acknowledges
native API acceptance. Unclaimed/unacknowledged delivery falls back after two
seconds only with background call-notification consent. A fallback winner refuses
late GUI claims. Without background consent the daemon does not display; a late
GUI can still claim within the bounded live-call lifetime using its own settings.
Call updates invalidate outstanding delivery tokens before GLib callback dispatch.
Presentation and withdrawal also recheck the actual phone state and grants.

The GUI always attempts its compact Magnolie call surface, independently of the
reminder style. Answer/reject symbols retain accessible labels and are disabled
individually when the native authority cannot issue their tickets. Silence only
dismisses this desktop alert. System notifications are the unsupported-surface or
absent-GUI fallback. Their buttons require the system's actual action support.

Linux observations are bound to the authenticated channel that supplied them.
Replacement sessions invalidate old action tickets and old observations. A call
received during the initial authenticated control handshake is presented again
after that same channel becomes active. Older callbacks cannot invalidate the
newer daemon delivery or overwrite the GUI's current call snapshot. Both desktop
frontends also reject decreasing revisions, direction changes within a call ID,
and resurrection of a terminal call.

This is not an OS receipt or exactly-once proof across process death between native
display and IPC acknowledgement. Native notification policy can suppress display;
a process crash after system-notification acceptance but before acknowledgement
can still create an ambiguous handoff. No caller data is added to activation
arguments, and display acknowledgement is separate from one-shot action tickets.

## Native Limits

- Android answering requires `ANSWER_PHONE_CALLS`, `READ_PHONE_STATE`, the app's
  call-control opt-in, and a usable Telecom service. Rejection via `endCall` also
  requires API 28 or newer. Answering explicitly requests audio only.
- Both Telecom APIs are deprecated, but remain permission-gated public APIs.
  They do not grant general control over self-managed VoIP or emergency calls.
  OEM restrictions are surfaced as failures, not successful phone effects.
  An interrupted effect marker without a durable result is not evidence of an
  answered/ended call. Duplicate attempts in this state fail closed. The pending
  desktop origin is installed before entering Telecom so an immediate synchronous
  OFFHOOK callback retains the correct origin; failures clear that pending intent.
- Telephony callbacks expose aggregate state, not an atomic per-call Telecom
  handle. ID/revision and live-state checks protect the observed lifecycle; they
  are not a platform guarantee against unobserved simultaneous-call/OS races.
  An `InCallService` implementation with an explicitly granted suitable role
  would be a separate extension. No additional role is requested automatically.
- Android 31+ callbacks do not expose the caller number in this implementation;
  no call-log fallback is added. Caller identity may therefore remain unknown.
- Silence dismisses only the desktop alert. `silenceRinger` requires a dialer
  role or privileged permission and is intentionally not called. No microphone
  or HFP mute is simulated.
- GTK uses the actual selected GDK backend, including native Wayland. Placement,
  focus and always-on-top cannot be guaranteed by a Wayland client. A failed or
  unmapped compact surface falls back to system notification support. System
  notification visibility and action support remain OS/desktop policy decisions.

API reference checked against AOSP `TelecomManager.java`, public `endCall`,
`acceptRingingCall(int)` and `silenceRinger` documentation:
https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/master/telecomm/java/android/telecom/TelecomManager.java
