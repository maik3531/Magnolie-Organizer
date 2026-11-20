# Desktop screen to phone: proposed media contract (#245)

This is a draft for the **desktop-to-phone** direction. No capability number is
allocated or advertised. It must not be dispatched as a reverse v26 lane.
Viewing an existing desktop surface and extending the desktop are separate
capabilities and approvals. Neither grants input, webcam access or audio.

## Admission

1. A visible phone viewer and the desktop approve the same mode on the original
   authenticated WLAN connection. The desktop uses the native chooser and
   verifies the exact selected source type. Extended mode requires a genuinely
   new output. It cannot use a monitor or window as fallback.
2. The private offer binds the exact mode, viewport and original peer to a new
   16-byte random session ID and 32-byte random secret. The desktop listens on
   the local address of that control connection; the phone connects to its
   observed desktop address, never a supplied host name or redirect. The offer
   may carry the session's ephemeral port. No values are saved for reconnect.
3. The phone attaches its original, independently approved viewer. The endpoints
   prove the original secret to each other on the data socket as below. The
   phone sends a distinct PREPARED message on the original control channel only
   after verifying the desktop's proof and writing its own. PREPARED binds the
   same challenge pair and cannot start the sender.
4. The desktop requires a complete local JPEG under the original setup deadline,
   the same live source and lifecycle guard, the exact accepted socket, and
   authenticated PREPARED matching that socket's challenge pair. Only after
   completing the separate SEND control write on the original connection can
   it emit records on that socket. The phone must
   not decode or display until it has verified proof and received SEND. Neither
   endpoint can transfer either approval to a replacement socket or peer.

## Proposed proof and records

- `context` is ASCII `magnolie-desktop-screen-send/1`, NUL, ASCII
  `desktop_to_phone`, NUL, the 16 raw session bytes, a one-byte mode (`1` for
  existing surface, `2` for extended output), then two big-endian uint16 values
  for width and height. Each dimension is 16–1920, with at most 2,073,600 pixels.
- In order, the phone writes its random 16-byte challenge, the desktop writes
  its own random 16-byte challenge followed by its 32-byte proof, then the phone
  verifies it and writes its 32-byte proof. A proof is HMAC-SHA256 with the
  session secret over ASCII `magnolie-desktop-screen-proof/1`, NUL, a one-byte
  role (`1` desktop or `2` phone), `context`, the raw phone challenge and the
  raw desktop challenge. Each side uses one two-second deadline across all
  proof I/O. PREPARED includes the SHA-256 of `context` followed by those two
  challenges in the same order, checked against the accepted socket before
  SEND. A failed proof ends this attempt. Neither proof nor the digest grants
  consent, and a valid proof for one role is not valid for the other.
- Derive 36 bytes using HKDF-SHA256 with salt = session ID, IKM = session secret,
  and info = `context`. Use the first 32 bytes as AES-256-GCM key and the last
  four as nonce prefix. A record consists of a big-endian uint32 ciphertext
  length (including the 16-byte tag), a big-endian uint64 ordinal, and the
  ciphertext. Nonce = prefix followed by the wire ordinal. Associated data =
  `context` followed by the entire 12-byte record header. Ordinals start at 0,
  are consecutive, and must stay below 2^63−1.
- The plaintext is one independent three-component 8-bit baseline JPEG at the
  exact viewport, at most 1,048,576 bytes, or an empty authenticated heartbeat.
  Heartbeat after 750 ms without a JPEG; it is not a frame and cannot establish
  readiness. A frame can be dropped before encoding a record; do not retry or
  replace a partially written record. Each full record has a bounded two-second
  deadline and checks the live guard before and during I/O. Never relay input or
  clipboard data through this lane.

## Draft control bodies

These bodies are not registered as product messages. A future adapter must
receive them only from the already authenticated original WLAN reader, reject
ambiguous framing and duplicate keys, and never put them into durable queues.
Before each nominated write, the original writer checks the same live guard.

Every body has `draft` = `desktop-screen-control/1`, `op`, `request` (16 random
bytes as lower-case hex), `mode` (1 or 2), and `setup_until_ms` (positive exact
JSON integer, at most 2^53−1). The phone chooses the request ID after a local
action. All later messages echo the request, mode and absolute setup deadline
without changes. The desktop converts a budget of at most 30 seconds to its
own monotonic clock once, capped by its existing local deadline. Only an
already active attempt can continue past setup expiry; no later message can
extend that initial budget.

| Operation | Origin | Additional exact fields |
| --- | --- | --- |
| `request` | phone | none |
| `offer` | desktop | `session`, `secret` (16/32 bytes as lower-case hex), `port` (1024–65535), `width`, `height` |
| `prepared` | phone | `session`, `transcript` (32 bytes as lower-case hex) |
| `send` | desktop | the same `session` and `transcript` |
| `stop` | either | `session` |

No message can supply an address, input flags, a replacement session or a
fallback mode. A PREPARED received at the OFFER write edge may be retained,
but does not allow SEND before the guarded OFFER write returns successfully.
The SEND writer checks the transcript against the proven socket, local media
readiness and the original channel again. Revocation during the write cannot
turn a completed write into live media authority. STOP retires only its owner.
See [shared draft vectors](desktop-screen-control-draft-v1-vectors.json).

## Retirement and acceptance

The Android viewer is a one-shot dialog attached to the original resumed
Activity. Its explicit approval names the paired desktop and distinguishes the
ordinary view from the extra display. It never requests Android screen-capture
permission and is not a substitute for SEND. The native decoder checks the
agreed dimensions again before allocation and before offering the bitmap.
Only the latest undisplayed bitmap is retained; heartbeats do not redraw.
Pausing the Activity, locking the phone or dismissing the viewer retires it.
No image slot, window or approval survives a replacement Activity.
The draft Android owner starts its receiver only on the native approval click.
It binds SEND to the exact control parent and proof transcript, and never
consumes media before the PREPARED write returns. Stop closes its data socket;
drain also requires the receiver worker to exit and the dialog to be removed.
This composition is not registered with the product WLAN dispatcher.

Cancel, lock, viewer closure, source or geometry change, lost control parent,
revocation or disconnect retire the original session. Stop first prevents future
frame handoff and interrupts owned I/O. It then waits for the exact sender and
reader, portal close, encoder exit, and, for extended mode, observes removal of
the original extra output. A missing cleanup acknowledgment is not successful
drain. Do not stop the ordinary Notes connection unless its own transport failed.

The local reader/encoder and portal tests do not validate this wire contract.
The isolated Linux draft writer implements the socket proof and records, but
does not own discovery, authenticated control dispatch, heartbeat scheduling,
or any Android viewer. Its trusted caller must bind the original accepted
socket and PREPARED receipt and perform the guarded SEND control write. The
separate Kotlin draft reader authenticates proof and records on its socket but
requires the original caller to supply the authenticated SEND receipt. It
rejects oversized or mismatched baseline JPEG headers before handing off
the authenticated bytes. The lane itself does not decode or display images.
The loopback interoperability test uses a controlled control handoff, not the
application protocol or a phone viewer.
Before allocation or advertising, check independent vectors and incompatible
direction/mode/session rejection, data-before-SEND, stop during blocked I/O, and
the real native phone viewer. Extended mode additionally needs the compositor
to show a separate output, move a window onto it and remove only that output
on stop. Remote input needs its own native authority and acceptance.
