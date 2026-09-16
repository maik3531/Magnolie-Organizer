# Explicit outgoing call scope — dial_request version 2

Windows and Notes negotiate this behavior through the existing `dial_request`
capability's `versions: [1, 2]`. Both sides must advertise version 2. There are no
new capability/grant map keys, message kinds, message envelope versions, or call
body fields. The existing `telefon-control-contract.json` remains a version-1
dial compatibility fixture. `incoming_call_state` remains version 2 and
`end_call` version 1 still means off-hook termination (version 2 ringing rejection
is a separate, globally authorized incoming action).

## Authority

An explicit local dial creates a runtime-only pending record for the sole paired
phone: its device ID, public key, and the fresh UUIDv4 `client_ref`. That reference
is also the outgoing `call_ref`. A durable command record, queue entry, startup,
unsolicited result, or incoming call cannot create scope. Windows arms the record
at the actual serialized write, with failure invalidation. Thus a matching event
may arrive before `dial_request.result`, but not before the request was sent.

Notes creates its matching runtime scope only while executing that authenticated,
unexpired, permitted dial command for the current peer. An existing effect marker
prevents a second dial and cannot mint scope after a restart. Global
`incoming_call_state`, `incoming_call_number`, `answer_call`, and `end_call` grants
are never enabled by this feature.

The scope authorizes only `direction=outgoing`, `control_origin=desktop`, and the
exact `call_ref`. Once observed, the start timestamp is fixed. Normal monotonic
revision/direction/terminal checks still apply. Caller-number sharing retains its
separate bilateral checks; the frontend may retain the number it explicitly dialed
locally. A scoped outgoing event never creates an incoming-call notification.

## Control and termination

Only a matching current off-hook call can be ended: exact peer/key, call reference,
revision, expected state and a separately recorded fresh `command_ref`. Windows
revalidates immediately at the serialized write; Notes revalidates the tracked
call and live OS state before invoking Telecom. Scope grants no incoming answer
or ringing rejection. Missing Android `ANSWER_PHONE_CALLS`, unsupported API, or
unavailable Telecom remains unavailable/failure; no permission or dialer role is
requested implicitly. `submitted` reports only the OS request, never an invented
connected/ended callback.

Android's real `CALL_STATE_RINGING` is incoming-only. It retires any ambiguous
outgoing association before a subsequent off-hook observation could inherit the
outgoing token. With incoming listening disabled, that new incoming/unknown OS
call is not tracked for desktop control. The outgoing wire `ringing` start remains
a synthetic dial-attempt event, not an incoming OS observation. Retiring this
association does not invoke an OS hangup or assert that an incoming call ended.

Windows pending-without-events expires after 60 seconds. The observed outgoing
scope is bounded to four hours. Notes' existing unobserved outgoing tracker timeout
is 30 seconds; its scope is bounded to four hours. Terminal capture allows a
60-second drain of already queued lifecycle messages; terminal state never permits
another end command or resurrection. Late dial results do not reopen terminal UI.
Ordinary tracker `idle` finishes the note exactly once through the existing save
path, including a minimized call dialog.

Android lifecycle publishing may reconnect its transport. Scope therefore remains
bound to the same paired public key and call across that transient reconnect;
an end command still requires a current online connection. Unpair/rekey, service
shutdown/restore, dial permission/grant revocation and expiry invalidate scope.
Explicit Windows withdrawal of call-state/end authorization cancels its outgoing
scope as well. Revoking and re-enabling consent cannot restore an old scope.
Capture and send filters are both checked in Notes; the final send is ordered with
revocation/unpair. Windows' final command write is ordered with its revocation.

## Compatibility and boundaries

A version-1 peer keeps the exact old body/grant dialect. Windows still dials it
without changing global grants; lifecycle/control then requires the existing
explicit global permissions. Updated Notes does not send unsolicited scoped
lifecycle to an old desktop. No Linux source or grant policy is changed here.
Default Windows HFP remains `unsupported`; this is a control/lifecycle contract,
not call-audio implementation.

## Reproducible synthetic checks

From the canonical root, using existing offline caches/toolchains:

```sh
python3 -B magnolie-notes-1.0.13/werkzeuge/call_fixture_gate.py --variant release --output /tmp/opencode/asr04-final-android
python3 -B Magnolie-Organizer-Windows-2.0.0/tests/callstate/outgoing.py --trace /tmp/opencode/asr04-final-android/trace/scoped-wire-messages.json
```

The Android fixture executes the tracker, protocol receiver, encrypted queue,
send filter and secure-channel writer with captured Telecom effects. The C# probe
uses those captured messages in the actual Windows coordinator/connection/store
path, then passes authorized callbacks to the actual JS call dialog and note-save
functions with an inert DOM and bridge. Envelope clocks are refreshed for replay;
captured call timestamps and identities are retained. This is a cross-language
contract check, not a real phone call, native Windows UI run, or hardware/audio
acceptance. The release-variant unit task excludes the production signing check
because it produces no APK and reads no signing key. No manifest permissions are
added.
