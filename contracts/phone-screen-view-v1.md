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
