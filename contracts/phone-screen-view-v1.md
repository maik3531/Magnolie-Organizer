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
JPEG at the agreed dimensions, capped at 1,048,576 bytes. No fragments,
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
