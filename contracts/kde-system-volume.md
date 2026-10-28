# KDE Connect system output volume

Issue: #262.

The KDE Connect **Devices** audio view controls output devices separately from
MPRIS players. Changing a player's volume is not an operation on the system's
mute state. Magnolie's native KDE backend therefore implements the separate
`kdeconnect.systemvolume.request` / `kdeconnect.systemvolume` packet pair.

## Wire operations

- `{"requestSinks":true}` reads the current output list. It must not change
  volume, mute, the default output, or player state.
- `{"name":"native-output-id","muted":false}` explicitly unmutes that output
  without changing its volume. `true` explicitly mutes it.
- `{"name":"native-output-id","volume":65}` changes system output volume
  and unmutes the output, matching KDE's system-volume interaction.
- An explicit `muted` value in the same packet takes precedence. In particular,
  `volume` plus `muted:true` must not briefly unmute before muting again.
- `{"name":"native-output-id","enabled":true}` selects the default output.
  `enabled:false` does not select a replacement output.

Volume commands use integer percentages from 0 through 100 inclusive. Booleans
are not volume integers. Extra fields, malformed values and unknown output IDs
are rejected before invoking a native operation.

Responses contain a `sinkList` array with `name`, `description`, `volume`,
`maxVolume:100`, `muted` and `enabled`. The output list and command responses
come from actual native readback, not the requested values or queue acceptance.
Linux can report an existing native amplified volume above the nominal maximum.
Polling and initial announcements are read-only; changed native state is
published approximately every two seconds while an eligible peer is connected.

## Native implementations

- Linux: PulseAudio / PipeWire's PulseAudio interface through `pactl`. Only a
  currently listed native numeric sink index becomes a command argument.
  Scaling volume preserves the existing channel-balance vector. DEB and RPM
  recommend the native client; AppImage includes it through the existing
  linuxdeploy dependency-closure process. The capability is absent when the
  native adapter cannot be initialized.
- Windows: Core Audio render endpoints and `IAudioEndpointVolume`, separate
  from WinRT player sessions. Stable native endpoint IDs select the output;
  master scalar volume preserves channel balance. Default-output selection
  uses the Windows policy interface. COM objects are used and released on the
  operation's worker thread.

Each native write rechecks the current confirmed connection, pinned
certificate, negotiated capability and shutdown/cancellation state. A stale
connection cannot use the paired peer's replacement connection. No failed
volume/mute operation is automatically replayed. Errors in this optional
module do not terminate SMS, contact reads, input or player control.

## Reference and verification

The upstream KDE protocol reference is
[`systemvolumeplugin-pulse.cpp`](https://github.com/KDE/kdeconnect-kde/blob/a07eace946bb6d12827c19c098c08d0e38166923/plugins/systemvolume/systemvolumeplugin-pulse.cpp).
The Windows implementation uses the same system-output packet semantics.

Targeted tests cover read-only mute preservation, explicit mute/unmute,
volume-triggered unmute, explicit-mute precedence, channel balance, native
readback, malformed input, unavailable outputs and revoked sources. The Windows
controller also has a pinned TLS loopback with and without negotiated system
volume support. Native Linux verification uses a temporary inaudible null sink
and removes it after the check. Native Windows verification reports endpoint
readback and reapplies only the just-read mute value; it does not choose a new
default output or change the user's volume for the probe.

Component tests and native probes do not replace the final installation/start
checks for the actual release artifacts.
