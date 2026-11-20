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

Before either side transfers the local stream to an owner, the daemon
offers `MGSVL001`, a fresh 16-byte nonce, and two big-endian uint16
dimensions. The original GUI replies with `MGSVACK1` and the nonce only
after its native view is attached. Both sides validate kernel peer PID/UID
and keep the separately admitted native lease and original setup deadline
throughout. The reply does not authorize Android capture or phone SEND.
Once setup is complete the socket carries only the one-way record stream
described above. Failure retires this socket, not the general daemon proxy.
