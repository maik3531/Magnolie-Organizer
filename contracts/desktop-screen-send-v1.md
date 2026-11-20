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
own monotonic clock once at original intake, capped by its existing local
deadline. The native dialog and sender use that same request-bound deadline;
a later wall-clock correction cannot renew or shorten it. Only an
already active attempt can continue past setup expiry; no later message can
extend that initial budget. The default phone action requests 27 seconds,
leaving headroom for a small positive phone clock offset without relaxing the
desktop's 30-second admission ceiling. Neither peer adjusts or renews the
original timestamp in response to later messages.

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

The isolated Linux and Android adapters wrap a body in exactly `type` and
`body` (`type` is `desktop_screen_draft`). This wrapper is not a registered
message kind or a capability. The adapters use the existing encrypted writers
only on the original WLAN streams. Their write-edge callback runs after writer
admission and encryption, before consuming a sequence. Android admits one
matching OFFER and delivers it only after the request write returns. It releases
a single matching SEND receipt only after the PREPARED write returns. A matching
STOP retires the original control owner. The isolated Linux attempt joins one
local portal/reader/encoder owner and one data listener bound to the original
TCP interface and peer address. It opens that listener only after a complete
local JPEG exists, and the data worker rechecks local media and the parent
throughout proof and sending. A single latest-frame slot feeds the worker;
heartbeats do not replace local readiness. The Linux authenticated reader can
feed an explicit, in-process attachment bound to one activated WLAN parent,
authenticated peer key, store and service generation. Without that attachment
the reserved wrapper is silently dropped; it is never replayed, acknowledged
or routed through ordinary messages. The attachment is not capture consent.
The native caller must retain the slot through cleanup and fence handoff with
both its consent and the attachment's live guard. The private GTK admission
arms only for an explicitly selected peer and exact local mode. A matching
request still needs an explicit native confirmation, naming the paired peer
and the mode, before the separate portal can begin. Denial is the default.
The confirmation shares the original setup deadline and desktop lock lease;
unlocking never revives it. The dialog offers Stop after confirmation; owner
exit or revocation also retires the attempt. Unknown cleanup holds the slot
closed to replacement. Once a `VIRTUAL` Start was submitted, the local result
records a possible additional output even if no target reached the reader.
A successful portal Close does not release this slot: the draft has no
compositor witness for the original output's removal yet. Ordinary mirroring
does not acquire that restriction. No product UI, IPC or capability registers
an attachment or opens this dialog.

### KDE/KWin output identity (unwired draft)

The generic ScreenCast v6 contract does not guarantee a compositor connector
identity. `pipewire-serial` identifies only the media node; an output added
near the same time, or one with the expected geometry, is not proof. The KDE
portal's `createVirtualOutputStream` sets `mapping_id` to the KWin output name
(`Virtual-` plus the unique KDE virtual-screen name for that application).
See [the KDE portal source](https://github.com/KDE/xdg-desktop-portal-kde/blob/ea33694e88596e000e800eb31accb0cf102e8cc0/src/screencasting.cpp)
and [KWin's virtual stream lifetime](https://github.com/KDE/kwin/blob/1026613ce8344b1e9191b78e1a1bbe976ba9246f/src/plugins/screencast/screencastmanager.cpp).

The private witness correlates that exact mapping with one new output instance
on an original Wayland registry observed before portal Start. It can establish
removal only for the previously bound instance, not from a connector label,
changed registry, inferred topology, or a new instance reusing the name. This
requires a verified KDE backend route and a complete, ordered native display
observer. An isolated libwayland prototype takes only a supplied connected
descriptor, settles the initial `wl_output` v4 names before becoming ready,
and reports exact registry additions and removals. Its socketpair test uses
the real libwayland client and server, but no actual desktop compositor. EOF
or invalid records retire the observation. The current product neither verifies
that route nor starts the observer; it does not release the virtual-output slot
on that basis. Real placement, window movement, and compositor cleanup must
still be observed independently of media cleanup.

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
The isolated Android attempt joins that viewer to the original encrypted
control channel and opens its data socket only on the native approval click.
When the viewer closes, the attempt can report one terminal STOP on the still
current parent; this write cannot reopen the viewer or grant media authority.
Drain includes that control worker. The Notes reader can deliver draft frames
only from the original authenticated, established WLAN session to a single
attempt started by an explicit in-process native action. A replacement
connection cannot acquire its request or viewer. Before establishment and
without an attempt, frames are discarded without acknowledgment or durable
processing. No product UI calls the private action and no capability is
advertised.

Cancel, lock, viewer closure, source or geometry change, lost control parent,
revocation or disconnect retire the original session. Stop first prevents future
frame handoff and interrupts owned I/O. After a completely written OFFER, the
retired Linux sender may report one terminal STOP on its still-current parent
even if local consent is already gone. It neither echoes a received STOP nor
retries a failed terminal write. The local owner waits for the exact sender and
reader, portal close, encoder exit, and, for extended mode, observes removal of
the original extra output. A missing cleanup acknowledgment is not successful
drain. Do not stop the ordinary Notes connection unless its own transport failed.

The local reader/encoder and portal tests do not validate this wire contract.
An opt-in Python/Kotlin loopback test exercises both draft adapters and the
Linux attempt over two TCP sockets with preconfigured test keys: encrypted
request through STOP, mutual proof, a synthetic JPEG and the sender's timed
heartbeat. Ordinary traffic continues on the same control connection after
STOP. A separate Robolectric variant drives the Android approval dialog,
decodes the synthetic JPEG into the view, and pauses the Activity to clear the
image and stop the session. Another opt-in variant runs both product session
readers with disposable pinned peer stores, including the authenticated FS1
handshake and normal setup exchange. Only an explicit test action attaches
the Linux and Android draft owners; after Android Pause, the same authenticated
connection completes an ordinary ping/pong. These tests substitute the local
compositor run. A second case sends desktop STOP while the phone's approval
dialog is still pending: the dialog is removed, a stale click cannot reopen
it, and there is no PREPARED or echoed STOP. The same parent still answers.
An additional desktop STOP case clears an already displayed image. The test
does not close the control parent until the Android owner has drained, so a
parent disconnect cannot account for the image clearing. These checks do not
exercise pairing, discovery, a real portal or a physical phone, or enable a
product entry point.
The Kotlin media lane checks JPEG headers before handoff; decoding and display
are separate.
Before allocation or advertising, check independent vectors and incompatible
direction/mode/session rejection, data-before-SEND, stop during blocked I/O, and
the real native phone viewer. Extended mode additionally needs the compositor
to show a separate output, move a window onto it and remove only that output
on stop. Remote input needs its own native authority and acceptance.
