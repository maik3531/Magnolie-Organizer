# Shared media settings at the legacy capability limit (#330)

**Test-only draft. Do not advertise or send this from a product build.** A
full legacy `device_status.versions` list has 16 slots. Keep every advertised
legacy feature and the old schema intact. Shared-settings support must be
detectable independently from an image batch (25) or video support (22).

The draft uses one ordinary `message` envelope of kind `media_support.hello`
per direction. The body is exactly `{ "format": 1, "feature": "shared_settings" }`.
It uses an original UUIDv4 and at most 10 seconds on the wire. It contains no
settings, account, media, permission, path or file-manifest data. It must not
use the reserved `file_transfer.*` route: a legacy paired desktop without an
active file owner rejects that route before it can answer a capability probe.

On the receiving side, new implementations would handle this before ordinary
dispatch and without a durable queue. Authorize the probe only on the current
authenticated WLAN channel for the same explicitly selected own device, after
the required native control metadata and local handlers are ready. Confirm the
exact remote probe using the ordinary ACK shape, but consume it on the
attempt's original receipt path, not on the personal outbox. A matching
negative receipt (`unsupported` from old Linux/Android, or `invalid_schema`
from the Windows kind allowlist) ends just this probe. It must not trigger
re-pairing or a wider error override. A receipt must arrive on the same
channel; it does not by itself prove the remote side is proposing the feature.

- Use one original, non-renewable local setup deadline. Publish support only
  after the local probe completed its authenticated write, its exact positive
  receipt arrived, a valid opposite probe arrived, and its ACK was completely
  written. A retired or replaced channel, stale metadata or failed write cannot
  authorize a later attempt. An established support observation lasts at most
  as long as its original live prerequisites.
- A legacy receiver may store a normal negative deduplication receipt.
  It must not change its capabilities, grants, file policy or paired device.
  The draft does not retry a legacy rejection and must not be sent by a
  production peer before compatibility on all counterpart platforms is checked.
- Support is not agreement on settings and is not SEND/READ/RECV, Android
  consent or any file authority. It cannot mark an image batch or a video
  handler available. Existing original-batch bindings are unchanged.

## Integration checks before enabling the draft

- Reuse the existing same-peer, own-device and fresh legacy control checks.
  Local readiness here means that the settings handler can accept a message;
  it must not depend on a support observation or an already-open media batch.
- Both the settings UI and runtime routing need the same session-bound support
  observation. Audit them separately: Android currently checks version 23 in
  both `mediaSharedControlsReady` and the native gallery runtime selection.
  Substituting only the UI check would not select the negotiated runtime.
- The receive path may observe an ACK while the writer is still completing.
  Keep that receipt bound to the original attempt and do not publish support
  before the write succeeds. A write failure or retirement discards the
  receipt. Serialize establishment and withdrawal against the same owner;
  the test reference checks receipt-before-write-completion, write failure,
  withdrawal and expiry. This is not a production-dispatch concurrency proof.
- Withdrawal or lack of a current support observation is not an instruction to
  reset preferences, clear an opt-out or fall back to legacy transfer for
  an already-started batch. Verify withdrawal and restart with existing saved
  choices as well as a new, default-off pairing before candidate packaging.

`magnolie-organizer/pruefungen/test_media_support_draft.py` exercises the
reusable Linux support component and the actual protected settings store and
transport over encrypted local I/O. The full 16-marker legacy set remains
unchanged. Completed support on a different channel cannot open the store;
support on the correct channel does not itself create preferences, mark them
agreed or grant file access. The Linux tests also exercise the legacy reader
and continuing heartbeat after rejection. The Android Robolectric dispatch test verifies the current
pre-discovery receiver over a synthetic encrypted parent and continuing
capability traffic. The Windows Core test uses the actual pre-discovery
dispatcher and a paired synthetic store over encrypted loopback TCP; the
Windows kind allowlist rejects with `invalid_schema`, not `unsupported`, and
the parent heartbeat continues. Neither counterpart test is an installed
package or live-device check. Positive cross-platform discovery and selecting
the production transport remain open.

Linux also exercises the actual native reader with an explicitly injected
private gate. The stock gate stays off. The authenticated Wi-Fi reader requires
its exact paired parent, a native pairing epoch and acknowledged capability,
grant and own-device metadata. It routes the original receipt outside the
personal outbox, retires the observation on metadata withdrawal, and does not
retry on that parent. A separately opened native connection can exchange
protected settings through this witness without allocating a file worker,
starting the scheduler or creating file grants. Delivery on Bluetooth cannot
produce this observation. An existing file owner is not rebuilt or replaced
to attach a late observation.

For this Linux/Notes draft, Notes initiates after warm-up; Linux only responds
from its active reader. Linux sends its capability and grant controls before
reading the Android controls. Notes' replies to those controls precede its
hello in the same ordered channel, so Linux can finish its control loop
before dispatching the hello. `NativeMediaSupportSessionTest` runs both actual
session loops with disposable pins over encrypted loopback, including the
ordinary control phase and a heartbeat after discovery on the same parent.
A second case opens a separate Linux settings owner on that parent and
checks protected settings, matching ACK and echo on the actual Notes reader.
The reconnect case retains the original pairing and protected choices but
starts with no agreement on the replacement channel. Both readers repeat the
fresh discovery and settings exchange, not an old attempt or a media batch.
Discovery alone opens no settings owner. The private Notes lane keeps its
receipt IDs in memory, never in the personal outbox, and does not select the
legacy gallery runtime. Actual dispatcher tests check loss of agreement on
withdrawal while the stored preferences and parent connection are retained.
A probe received by a pre-active reader may not be buffered or replayed. The
Android private reader tracks only fresh acknowledged controls of that
original transport, independently of legacy pre-write session flags. It does
not use this observation for file access or batch authority. Wiring this
agreement to explicit UI actions and native file acceptance remains separate.

The Windows Core loopback also tests the private answering reader once the
same paired parent has written its capability, grant and own-device ACKs.
Malformed, early and withdrawn probes do not acquire a settings or file
owner, and the ordinary heartbeat continues. The stock Windows gate stays
off and its old rejection is still covered separately. Reciprocal Notes
settings exchange with Windows and native Windows package acceptance are
not covered by the Core loopback.
The private Windows settings receiver uses the existing protected store and
does not set legacy media readiness. On hosts without native DPAPI it holds
without storing settings or closing the parent. The focused fixture also
contains a Windows-only positive arm with its own DPAPI key; it must be run
on Windows before claiming protected Windows agreement.

The private Android agreement can now supply the exact direction/type intent
to an independently opened native gallery owner. Without a matching ACK and
echo it supplies no intent, and withdrawal removes the intent from the same
owner without retrying its file action. The Linux private receiver permits an
explicit phone-to-PC run only with previously granted native receiver and
phone source controls. A loopback phone fixture exercises byte-identical JPEG
and MP4 reception over the encrypted reader, separate targets, and preservation
of an existing PC edit on an unchanged phone inventory. The private Linux
scheduler also exercises automatic phone-to-PC reception on that live WLAN
parent. It checks all selected receive bindings, the selected WLAN mode and
the same agreed intent, independently of the explicit start action. These are
not tests of a packaged Android sender. On reconnect, private Linux restores
only the protected previous one-way WLAN choice with a still-valid destination
policy. The replacement channel must first establish fresh support; it then
exchanges settings and file controls, which remain distinct. A test verifies
that settings agreement without a new phone SEND/control echo still cannot
start the scheduler. An actual automatic transfer after reconnect remains to
be verified with the native phone sender.
Outgoing/combined runs are held in this receiver composition rather than
running only part of the direction or substituting a legacy batch.
