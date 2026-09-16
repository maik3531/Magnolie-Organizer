# Native Call Audio

## Scope

`bin/magnolie-organizer` uses the shared `AnrufBluetooth` implementation in
`bin/magnolie_anruf_audio.py`. Its lifetime belongs to `PhoneService`, whether
that service is owned by the foreground app or the existing background daemon.
The GUI cannot start routing by replaying an incoming-call event or supplying
an arbitrary HFP address. Phone identifiers, device-status models, call
direction, control origin, and answer/reject action tickets remain separate.

The host `call_audio` snapshot is separate from phone protocol capabilities and
the Magnolie Bluetooth RFCOMM data transport. An online RFCOMM session is never
evidence of an HFP audio route.

## Linux Runtime

The runtime uses the installed BlueZ D-Bus API and `pactl` JSON interface to
PulseAudio or PipeWire's PulseAudio server. It does not implement an HFP stack,
install audio software, enable WirePlumber roles, register an alternative
profile, or change system configuration.

- The phone must be the single locally confirmed own phone, with a bound
  Bluetooth address and an existing connected, paired, trusted BlueZ Device1.
- BlueZ must advertise remote AG UUID `111f` and local HF UUID `111e`. Device
  aliases and friendly names are not identities. RFCOMM-only and A2DP-only
  devices are rejected.
- Card addresses, profiles, endpoint addresses, roles, indices, and server
  cookies are read from actual metadata. `headset-head-unit` is the wrong role.
  PipeWire's `audio-gateway` card profile still needs actual HF duplex endpoints;
  its name alone does not prove HFP audio support.
- The current default PC microphone and sink must be physical ALSA-backed
  endpoints, not a monitor or the phone itself. Defaults are read, never changed.
- Before any profile or microphone operation, the router refreshes the same
  authenticated phone identity/session, call reference/revision and consent.
  Initial call observations older than 15 seconds, replaced sessions and retired
  calls cannot start audio. Ringing and dialing never open the microphone.
- Current local and remote call-state grants and version 2 call-state support
  are required. Audio preference grants no additional call permission and never
  answers a call.
- Only two uniquely tagged, immovable `module-loopback` routes are created:
  phone downlink to the PC sink, and PC microphone to the phone uplink. Existing
  application streams are never moved. A phone endpoint already in use is not
  taken over.
- `active` requires observing both owned loopbacks, their actual stream endpoints,
  uncorked/unmuted streams, and running native endpoints. A successful command
  or an existing Bluetooth connection is not sufficient.
- Idle, disabled preference/ownership/consent, changed peer/session/revision and
  service shutdown release owned loopbacks. `ConnectProfile(111f)` requests the
  installed native HF stack, not an exclusive connection lease. BlueZ explicitly
  has no per-client profile connection tracking, so cleanup never calls either
  `DisconnectProfile` or the all-profile `Device1.Disconnect`. The shared
  OS-managed HFP connection remains with the OS. An unchanged owned card profile
  can be restored; foreign adoption, recreated cards, changed profiles and changed
  server identity are not overwritten. Selecting the phone's audio manually may
  still be necessary if the phone retains its Bluetooth audio selection.
- Tool calls have a three-second deadline and JSON output has a one-MiB limit.
  Route observation waits and retry frequency are bounded. Failed cleanup keeps
  ownership for retry and never advertises active audio. If the audio server or
  its permissions disappear, successful physical cleanup cannot be guaranteed
  until access returns; this is not reported as verified audio or verified release.

Unavailable tools, sandbox access, HF roles, bonds or usable audio endpoints
produce an unavailable capability/route and a localized phone/manual-audio
fallback explanation. No new Flatpak permissions were added: the existing
PulseAudio socket and BlueZ system-bus name remain the only relevant grants.

## Preference Migration

`preferPcAudio` is independent of `computerTelefonie` (call controls). New call
settings default to true. A new own-phone confirmation supplies the backend
default without changing call grants. Backend `call_audio.prefer_pc` persists
explicit false across restart, ownership reconfirmation and background handoff.
Routine GUI synchronization adopts a persisted backend opt-out instead of
overwriting it with a default; only an explicit settings save re-enables it.
Old peers without this preference remain fail-closed until settings migration.

Both desktop normalizers preserve an explicit `preferPcAudio: false`. Legacy
empty/invalid `hfpAdresse` selections stay disabled; nonempty valid selections
are retained, but Linux only uses them if they match the bound peer address.
The arbitrary HFP-device dropdown is replaced with the bound device address.
Removing that address from the phone binding makes routing unavailable; the
router does not guess another OS-paired phone.

## Windows Limit

The shipped Win32 deployment reports `unsupported`, even when its Bluetooth
radio and Magnolie RFCOMM transport work. The read-only runtime probe checks
`PhoneLineTransportDevice`, `CallsPhoneContract` version 6, and package identity.
It neither registers a transport nor requests access. API presence is not
permission: this deployment has no approved restricted
`phoneLineTransportManagement` capability and no packaged routing adapter.

Automatic call-audio settings are disabled with a localized explanation.
Existing manual native system audio remains untouched. Automatic radio powering
for calls is also gated off. A future packaged native adapter would require
method-specific access checks, separate implementation and validation; this change does not pretend that it
exists and does not add restricted capabilities or system roles.

The 2026-09-14 research follow-up records the user's explicit Windows hands-free
request in [windows-handsfree-feature-request.md](windows-handsfree-feature-request.md).
Store approval is not a universal sideloading prerequisite for restricted
capabilities; identity, declaration, actual access and an implemented adapter are
distinct requirements. `AudioRoutingStatus` additionally documents `phoneCall`.
This clarification does not enable the currently unsupported runtime path.

## Verification Boundary

`pruefungen/test_call_audio.py` exercises the real router with fake BlueZ and
Pulse JSON, authenticated call-event handling, peer/consent/revision changes,
late IPC snapshots, ownership cleanup, bounded subprocess parsing, packaging,
and all 20 manually authored/reused desktop localizations.
`tests/call-audio-regressions.js` exercises both desktop normalizers and status
presentation, plus the Windows no-registration/no-prompt source boundary.

These tests do not exercise a real phone, microphone, speaker, SCO transport or
Windows device. Observed software routing is not proof of audible bidirectional
hardware audio. Real Linux HFP interoperability and Windows runtime execution
remain hardware/platform validation work, not claims made by this implementation.
