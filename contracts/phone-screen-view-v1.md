# Phone screen viewing, JPEG data lane (#245)

This is the binary **phone-to-desktop, view-only** lane. It neither opens a
listener nor confers permission. The product control path must bind a fresh
random 128-bit session ID and independent 256-bit secret to the exact current
authenticated control connection and its original user action, and negotiate
the exact viewport (each side 2–1920; at most 2,073,600 pixels). The producer
requires genuine Android MediaProjection consent and an active, independently
checked SEND decision before emitting any bytes. The consumer must recheck
the same live lease before reading, decoding and displaying. No settings,
pairing files, history, resume, webcam key or consent may supply this context.
Control messages, capability ID and integration remain separate work.

`context` is ASCII `magnolie-phone-screen-view/1`, NUL, `phone_to_desktop`,
NUL, followed by the 16 raw session bytes and two big-endian uint16 values
(width, height). Apply RFC 5869 HKDF-SHA256 with salt = raw session ID,
IKM = secret, info = context, and 36 bytes of output. The first 32 bytes
form the AES-256-GCM key, the last four the nonce prefix.

Before activating the record lane, the desktop sends one fresh random 16-byte
challenge on the accepted socket; the phone answers with the 32-byte
HMAC-SHA256 of ASCII `magnolie-phone-screen-proof/1`, NUL, `context`, and
the challenge, keyed by the session secret. Both steps have a single shared
two-second deadline per side and no retry. The phone only answers on the
socket for an original session with live consent; the desktop verifies the
proof before it can authorize SEND on the authenticated control connection.
The proof binds the original secret to this data socket, not screen consent
or viewing/control permission by itself. Record helpers below are used only
after this step and the independent SEND exchange.

Each record starts with ciphertext length (big-endian uint32, includes the
16-byte tag) and ordinal (big-endian uint64, starts at 0, consecutive, below
2^63−1). The nonce is the prefix followed by the ordinal. Associated data is
`context || header`. The plaintext is one independent 8-bit baseline RGB
JPEG at the agreed dimensions, capped at 1,048,576 bytes, or empty for an
authenticated heartbeat (ciphertext length exactly 16). The sender emits a
heartbeat after 750 ms without a JPEG so that a static screen need not produce
new pixels to stay connected. Heartbeats require the same live SEND guard,
consume one ordinal, and never draw or grant any authority. No fragments,
codec fallback, cursor/input data, audio or replay. Frames may be discarded
*before* building a record; the ordinal counts transmitted frames only.

One direction and one owned socket per lane, with a two-second deadline for
each complete record. Check the original guard on every socket step and
once more before returning the frame. EOF, bad lengths/tags, wrong ordinal,
timeout or guard loss are terminal. Socket close may interrupt pending IO;
no retry takes place in this lane. A future product caller must use the exact
original peer/control context and bound any pre-attach wait separately.
A valid tag does not itself grant permission.

## Pending control integration

The first product implementation should reserve a separate `device_status`
marker (26, after existing 21–25); do not advertise it until the complete
native route is ready. Older Notes peers already use the full status list:
follow its compatible desktop-advertisement/phone-probe pattern rather than
adding a permanent Notes status-list entry. Use the authenticated channel's
ephemeral controls, never its persistent queue, ACK history or replay files.

The v26 control bodies share `version` (integer 26), canonical UUIDv4
`request_id`, lowercase 64-hex `nonce` and `op`. Phone-to-desktop requests
carry `probe` (no additional fields) or `prepared` (32-hex `session`).
Desktop-to-phone reports carry `offer` (`session`, 64-hex `secret`, `port`,
`width`, `height`, `density`) or `send` (`session`). Either direction may
emit terminal `stop` (`session`) or `error` (`session` and a fixed `reason`
code). No offered address, unknown fields, audio options or input capability.
The normal authenticated message envelope is limited to 4096 bytes and a
maximum lifetime of 60 seconds. Each endpoint also maintains a local setup
deadline from its original probe; active viewing always needs live guards.

1. After seeing this desktop's feature marker on the live paired WLAN
   connection, a supported, visible Notes Activity may report a fresh probe.
   A probe only means the phone can be asked; it never starts capture.
2. An explicit Organizer action consumes that original probe and creates one
   request. Offer the fresh session, secret, TCP port and fixed viewport to
   that same authenticated peer. Socket addressing comes from the actual
   authenticated WLAN socket, never an offered host name or a UI address.
3. Notes asks Android for MediaProjection. A new foreground service may
   acknowledge readiness only after its exact capture handle is active. This
   handle also guards the data socket proof. Do not treat an Activity result,
   a started service, a paired identity, or a probe as actual capture.
4. The desktop must have the original independent window attached and fresh
   socket proof verified before it issues SEND. Notes checks the original
   authenticated SEND and the exact active capture before frame production
   can reach the socket. Late phases cannot resume or replace a session.
5. Cancel, stop, lock, revoke, disconnect or shutdown disables authorization
   first, closes the original provisional/active sockets, stops the original
   capture and window, then waits on both actual native drains. An uncertain
   drain cannot release the local slot or authorize a replacement.

Keep this first mode viewing-only. It does not advertise remote input,
desktop-to-phone capture or a virtual second monitor, and does not treat
any of those modes as a fallback.

### Linux display and background ownership

The GTK owner must hold both the exact WLAN parent and a live local desktop
session lease. The logind observer resolves the Organizer process's own
session without starting logind. Unknown or inactive sessions are unavailable.
Lock, inactivity and owner loss retire the original display lease; unlocking
does not recreate that view or reuse its approval. This is separate from
Organizer profile lock and from hiding the window in the tray.

The disabled foreground-only integration is not a daemon migration. When
the background service owns the phone connection, keep the existing owner,
pairing and settings. A future native local rendezvous must bind the exact GUI
process, desktop lease and daemon's original parent, transfer only an owned
bounded viewing lane, and stop/drain on either endpoint's loss. Do not route
pixels or session secrets through the regular JSON proxy/event history, or
treat its ordinary same-user subscriber identifier as fresh viewing consent.

The dedicated local relay accepts only an already admitted, connected Linux
Unix stream with exact kernel peer PID and UID. This check supplements, but
does not establish, the native GUI and daemon ownership. The daemon forwards
only authenticated, live-SEND JPEG/heartbeat records, each prefixed by a
big-endian uint32 length (0 for heartbeat, otherwise at most 1 MiB). No host,
session key, consent, control message, or input is carried by this stream.
Reverse bytes, EOF, record timeout, or original guard loss stop the owner;
the GUI decodes only after bounding the agreed image dimensions. No buffer
queue or retry spans the two owners. The pre-record wait on the GUI is bound
by the original setup deadline, not by a new grant. Neither endpoint is
registered as a public proxy operation.

Before the daemon starts its viewing owner, it offers `MGSVL001`, a fresh
16-byte nonce, and two big-endian uint16
dimensions. The original GUI replies with `MGSVACK1` and the nonce only
after its native view is attached. Both sides validate kernel peer PID/UID
and hold the kernel peer pidfd of that exact connected socket. An inherited
descriptor cannot keep a view authorized after its original peer exits.
Missing peer-pidfd support leaves this daemon path unavailable, not unlocked.
Both sides also keep the separately admitted native lease and original setup deadline
throughout. The reply does not authorize Android capture or phone SEND.
Once setup is complete the socket carries only the one-way record stream
described above. Failure retires this socket, not the general daemon proxy.

The private daemon entry uses the existing 0600 Unix listener but switches
to a separate fixed-size binary exchange before JSON parsing. One dedicated
setup worker is allowed; it does not occupy a general IPC handler during
the native dialog. The request carries the selected phone's UUID, then the
daemon returns a fresh nonce and the original monotonic deadline (capped at
30 seconds). The GUI only echoes the nonce after an explicit native dialog;
the daemon consumes the exact probe selected before that dialog. After GTK
confirms attachment, it starts that probe's native WLAN/data owner; it does
not select a new probe on expiry, reconnect, or failure. The ordinary phone
report can expose only the currently eligible paired device IDs, never the
capability witness, nonce, socket, approval or phone data secret.

On daemon shutdown, revoke admission before interrupting the exact setup
socket and stopping the resulting owner. Report a completed drain only after
both the provisional worker and (if it was created) the original view owner
have actually drained. The screen shutdown path does not close the original
phone control connection; the daemon's normal phone lifecycle owns that.

This is a same-UID application boundary, not a defence against arbitrary
code running as the desktop user. Neither the PID nor a nonce is proof of
human interaction outside the cooperating native GUI. The phone must still
request and verify its own genuine system consent. The daemon and GUI gates
stay off until the actual product, device and desktop lock paths are checked.

## Platform prerequisites for the separate desktop-to-phone functions

This section defines acceptance boundaries, not additional v26 operations.
Desktop viewing, control and a virtual monitor each require their own capability
and user approval. Success in one mode must not advertise another. A mirror of
an existing monitor does not count as a second monitor.

- **Linux desktop viewing:** Query the running session's
  [ScreenCast portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)
  before offering capture of an existing monitor or window. The portal must
  present the real source chooser and return a PipeWire stream for that exact
  session. Neither a running portal service nor the Screenshot interface
  establishes ScreenCast support. Do not persist or restore the approval.
- **Linux second monitor:** Require the portal's `AvailableSourceTypes` to
  include `VIRTUAL` (`4`), and an interface that can report the actual stream
  type (ScreenCast v3 or newer). Request only `VIRTUAL`. Missing or different
  `source_type` in the returned stream is a failure, not an invitation to try
  `MONITOR` or `WINDOW`. Acceptance requires observing a new, separately
  positioned compositor output, moving a window onto it while leaving the
  primary output unchanged, and seeing it removed after closing or losing the
  session. A virtual bit indicates a candidate backend, not a usable monitor.
- **Linux control:** The
  [RemoteDesktop portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
  must separately grant the requested device types. Apply absolute input only
  to the original approved stream with matching current geometry. Rotation or
  a geometry change invalidates the old coordinate mapping; unconfirmed input
  must not reach a different surface or fall through to global KDE input.
- **Windows second monitor:** A viewing window or a desktop capture API cannot
  create a display target. A verified provider using the
  [Indirect Display Driver model](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/indirect-display-driver-model-overview)
  is a separate candidate. Its presence, ability to add exactly one owned
  extended target, data handoff and removal must be checked independently of
  the Windows viewing feature. Discovery must not install or change a driver.

Any of these modes must stop on loss of its exact native session, authenticated
peer, approval or unlocked desktop. A disconnected output is not drained until
its original producer and stream have ended and the output is gone.

The passive Linux provider probe pins the portal's unique bus owner throughout
the bounded property queries and does not auto-start it. It reports candidates
only; it is not wired to the current v26 viewer or to any capture/input action.

The separate desktop-to-phone ScreenCast owner subscribes to the exact predicted
request before each call; neither its method return nor an early `Response`
alone can advance setup. It checks the original UI/session guard and one setup
deadline throughout `CreateSession` → `SelectSources` → `Start`. It accepts a
single stream with the exact requested source type, and requires the PipeWire
serial when the portal exposes ScreenCast v6 or later. Selection alone neither
opens PipeWire nor reports a live capture. The exact selected target permits
one bounded `OpenPipeWireRemote`, still within the original setup deadline.
Only the original portal's single returned descriptor is accepted; there is no
default PipeWire connection or descriptor transfer over renderer IPC. Stop
invalidates the local borrowed descriptor and accounts for any late reply
before reporting portal cleanup. That result is not proof of compositor output
removal or that a separate media consumer has drained.

The local Linux reader claims one duplicate of that original descriptor for
the exact selected target. This reader requires a PipeWire serial even if an
older portal returned only a node ID; it does not fall back to a node ID or a
default connection. It exposes only the newest complete frame at a bounded
size and rate. An incomplete frame does not establish readiness. Readiness is
local only, not permission to send, proof of an extended output, or a claim
that the first pixels represent nonblank desktop content. Portal revocation
makes the frame slot unavailable immediately; reader drain additionally
requires that the owned child has exited and its descriptors have closed.

The local session owner joins the portal and reader without promoting either
to network SEND. It rechecks the exact selection before exposing readiness or
a frame. Portal retirement stops the reader, and reader exit closes the portal.
The terminal result reports the two cleanup outcomes separately and is not
delivered while either side still has work outstanding. Compositor output
removal remains a separate acceptance check.
