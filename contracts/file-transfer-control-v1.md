# Dedicated own-peer file controls (integration in #330)

These controls are separate from contacts, Notes/Organizer personal-sync grants,
book SaveACKs and Android media permissions. The native implementations are
present in Linux `magnolie_file_control`, Android `DeviceFileControl` and Windows
`DeviceFileControl`. They do not yet register a transport handler, advertise
support, create settings/keys, prompt for permission or start any worker.

## Compatibility and discovery

Existing applications validate the global capability/grant **key sets exactly**.
Adding a new global key would break older paired peers. Discovery version **21**
is therefore reserved in the existing `device_status.versions` metadata family,
following its established feature-discovery versions. It must remain absent
until the actual native file/control handlers and authority paths are ready.
The `device_status` grant itself is **never file consent**. A peer without this
negotiated discovery version must not be sent new file-control messages. No
existing capability/grant set, pairing or permission is migrated by this work.

## Dedicated body and bounds

Kind: `file_transfer.control`. Maximum complete application envelope: 8192 UTF-8
bytes; maximum lifetime: 60000 ms. The normal authenticated message header and
its exact native sender/receiver/channel checks remain mandatory. The body is:

```json
{
  "format": 1,
  "grant_revision": 3,
  "grant_epoch": "<64 lower-case hex>",
  "send_files": false,
  "receive_files": false,
  "manifest_versions": [1],
  "session_epoch": "<64 lower-case hex>",
  "sequence": 1,
  "echo": null
}
```

No unknown fields, Boolean/string integer aliases or coerced flags are accepted.
Grant revision and session sequence are positive safe JSON integers through
9007199254740991. Supported manifest versions are sorted, unique, 1..65535 and
limited to eight entries. Send/receive directions are independent and initially
off. Remote packet parsing returns wire metadata, **not** a native local grant.
Native local grants must come from protected own-computer policy and its current
native owner; a handler-ready flag is not accepted from the peer.

## Freshness without breaking genuine interrupted-transfer resume

`grant_epoch`/`grant_revision` belong to persistent native consent. Native source,
destination and actual OS access must still be checked independently. A fresh
random `session_epoch` and monotonic `sequence` belong only to the current
authenticated native channel/handler ownership. Native peer ID/public key,
paired/own-computer state on both sides, current owner reference and actual
negotiated handler support are checked outside the packet.

Challenge SHA-256 is over `magnolie-file-control-challenge-v1\0` followed by the
canonical JSON grant fields, `format` and `session_epoch`; sequence and echo are
excluded. `echo` returns the other side's challenge. Directional readiness
requires both a fresh remote echo of the current local challenge and an **exact
native send-completion ticket after actual guarded channel send** of the current
echo. Merely constructing, parsing or copying a packet is insufficient. Echoes
settle without an unbounded feedback loop. A stale echo from a previous channel
does not authorize the new channel.

Persistent permission epoch is SHA-256 over `magnolie-file-permission-v1\0`
followed by canonical, device-ID-sorted entries `[id, native-public-key-sha,
grant-permission-fields]`. Permission fields exclude capability-version lists;
the current negotiated operation remains manifest format 1. Ephemeral session
nonces/sequence/echo are excluded, so fresh genuine reconnection can resume an
unchanged accepted binding after new authenticated agreement. Consent changes
change its epoch. Compatible future manifest capability additions require fresh
echo but do not reset existing v1 consent; losing v1 support pauses it.

Native identity/channel/local-store owner replacement is not silently adopted.
Revision rollback, same-revision changed permission or same-sequence changed
packet fails closed. Same-packet duplication is idempotent. Offline/locked/
unpaired/not-own/unsupported state yields no active native file binding, never
deletion evidence or newly granted consent. Android's native photo-receiver
adapter additionally feeds the existing gallery/SAF source authorities: it does
not substitute for actual OS READ grants or enable a source policy by itself.

## Verified boundary and open work

### Native policy fence and explicit Android configuration

The actual Android code-confirmed pairing path now stores a local
`file_pairing_epoch`, domain-separated from its fresh authenticated transcript.
It survives ordinary protected peer copies and reconnects, but a new pairing
with the same device ID/public key obtains a different epoch. Pending/unverified
relationships expose no current epoch. Legacy peer records decode with an empty
epoch; merely reading them creates no generation or consent. Three focused
codec/native-state cases pass. This is relationship identity only, not file
consent: protected file-policy association and legacy explicit authorization must
still be connected before the epoch can govern real transfer handlers.

### Pairing-associated native grant projection (not transport activation)

Linux likewise records its native file relationship epoch only in the actual
confirmed pairing path. Protected peer validation accepts the optional strictly
typed local field; old peer records stay absent, while a corrupt present field
fails instead of resetting. The read-only current-epoch helper requires paired
bilateral own-device state and does not construct a `PhoneStore`. Eighteen
focused Python cases pass, including existing pending-finish restart and known
legacy-key migration checks. This local metadata is not a new global wire grant.

Windows `SavePending` now records the same domain-separated local generation
from the actual pairing transcript; successful Finish retains it. Its native
peer codecs retain legacy absence, reject malformed present fields and preserve
the epoch across ordinary copies/reopen. Targeted source-host control/codec and
actual protected pending/Finish/renewal groups pass with zero build warnings or
errors. The renewal test verifies fresh generation for identical device ID/key
and rejection of the prior Finish transcript. This is not installed Windows GUI,
native DPAPI acceptance or physical phone pairing evidence.

Android `TelefonWerk.currentNativeFilePeer` now checks actual service/storage
enablement, exact active secure-channel owner, current pairing generation,
transport presence and pinned peer ID/key before invoking the native peer
builder. The builder additionally requires current local relationship generation,
remote discovery 21 and handler readiness, independent of contacts/Notes grants.
Its new targeted unit method passes; the actual physical channel path is not yet
accepted and no file session/handler is registered by this method. Existing
legacy pairing activation still requires an explicit protected bootstrap path;
the current native builder correctly remains closed without that generation.

Gallery inner format 3 adds `pairing_epoch` alongside its monotonic revision;
formats 1/2 and their original protection namespace remain readable unchanged.
An explicit authenticated configure action can associate/reassociate existing
selected sources with the current native pairing generation. This is a real CAS
change with a new revision/permission epoch, even if source settings are equal.
Loading a legacy policy does not migrate or enable it. The index rejects removal
of a previously stored pairing association.

`NativeGalleryFileGrantPolicy` projects the actual protected policy reader into
native send-only file grants. A missing native pairing generation yields no
authority; absent, legacy or mismatched policies yield closed initial consent
without saving fabricated defaults. Repair fences retain confirmed grant bytes
while blocking ordinary data/control I/O. Protected-read uncertainty or observed
pairing replacement fences the adapter; a new native owner must explicitly
reauthorize a mismatched policy. Source requests require the same native pairing
association. This is neither an Android READ grant nor automatic synchronization.
Dispatcher registration and physical channel/phone acceptance remain separate
work; native peer/control-channel adapters are described below.

### Actual secure-channel control writes (not dispatcher registration)

`NativeFileControlChannel` validates the bounded complete control envelope and
exact native channel owner. Send completion is recorded only after the actual
synchronous `TelefonSecureChannel.send` encrypted-frame write returns and native
scope is rechecked. Failed or stale writes close this file adapter's authority,
not the shared phone socket. Expired/oversized/wrong-kind/header-invalid envelopes
do not become control metadata. Four targeted cases pass, including decrypting
the actually written frame, bilateral echo, native write failure and owner change
during output. This is synthetic native channel I/O, not a physical phone test.
The adapter does not register a dispatcher, advertise discovery or start work.

`NativeGalleryFileRuntime` now explicitly joins the actual protected source index,
pairing-associated grant projection, secure control channel and native gallery
workflow. It uses existing supplied identity/protection, exact configuration
tickets and protected CAS, not a personal-store constructor or wire-derived
native grants. Two targeted integration cases pass: actual encrypted control
writes/echo → initial OFF → explicit associated policy → fresh send-grant echo;
same-pair restart and same-ID/key re-pair HOLD followed by explicit association;
and no-handshake/no-policy-default/no-remote-authority local disable. The runtime
does not register handlers, scan media, prompt for OS permission or start a
worker/timer. Physical phone/installed GUI/Android dialog acceptance, explicit
legacy bootstrap and dispatcher/foreground/UI connections remain open.

Android now also provides an explicit legacy relationship-metadata bootstrap:
`TelefonWerk.prepareNativeFileRelationshipForExplicitActivation` rechecks actual
channel/generation/transport/pinned peer/discovery and a live native handler
readiness callback. `TelefonAblage.initializeFilePairingEpoch` performs protected
expected-peer CAS/readback, preserving other preferences and rejecting stale or
reentrantly changed state. It creates relationship metadata only, not a source
policy, file grant or OS permission. Existing metadata is idempotent; lost
post-commit authority retains evidence rather than reverting it. A fresh control
handshake is still mandatory afterwards. Four protected-store cases and two
targeted actual `TelefonWerk` synthetic-channel cases pass. No listener/service
or physical phone was started, and the activation command dispatcher itself is
not registered by this API.

Runtime shutdown distinguishes immediate native control revocation from final
Activity/lifecycle cleanup. `revokeControl` synchronously closes file authority
on any thread. A worker-thread `close` revokes first, then rejects final UI cleanup
without marking ownership fully closed or releasing only half the resources.
The native owner must complete `close` on the UI thread; this is not a quota or
worker-END receipt. All three affected runtime cases pass, including an actual
bounded worker thread followed by final UI-thread cleanup. No asynchronous
background cleanup or automatic permission UI is started by this change.

The affected pairing-associated control/policy/source/index/snapshot suites pass
89 cases. This includes actual protected-index legacy association/reassociation,
same-ID/key re-pair fencing, no implicit default writes, pending-CAS grant-byte
retention and protected-read failure. It is not physical pairing/phone acceptance
or activation of handlers. A restarted adapter with no pre-CAS confirmed grant
must remain unavailable while repair is pending, rather than fabricating an off
grant at the pending policy's revision.
The three affected factory methods and this additional pending-restart method
also pass in a targeted four-case run (90 distinct associated-scope cases across
the retained evidence). No unrelated passing methods were repeated for this
adapter-only correction.

`policyReady` is native-only state, never a packet field. Pending policy CAS or
repair blocks ordinary control packet production/send completion and data
bindings without rewriting previously confirmed grants. A temporary fence does
not by itself change persistent consent epochs.

Android configuration uses a distinct exact one-shot native ticket, issued only
after fresh bilateral metadata echoes, actual native send completion and remote
receive consent. Local send consent may still be off. The ticket permits only
policy configuration, not media READ or file sending. It expires after 60 seconds
on a monotonic clock; observed expiry, remote consent/session replacement or
native scope loss invalidates it. Explicit completion consumes the ticket. Its
own local policy CAS fence/change does not invalidate the in-flight command.

`NativeGalleryConfigurer` and authenticated workflow/controller factories keep
configuration authority separate from source READ/send authority. Missing
configuration authority never falls back to an unrelated data receiver.
`disableLocally` is an explicit native decrease-only operation, not a remote
bypass, implicit default creation or Android URI-permission release.
Remote disable commands retain their exact live configurer checks throughout
policy CAS and readback, just like enable commands. Revocation at either the
fenced or published boundary leaves repair pending; it is not treated as an
authorized local decrease. The affected policy class passes all 15 cases,
including both injected revocation boundaries and subsequent explicit local
disable after authenticated repair.

Gallery policy inner format 2 adds a positive safe-integer revision. Legacy
format 1/revision 1 and its original protection namespace remain readable. The
first real controller change writes revision 2; unchanged settings preserve the
stored ciphertext, epoch and revision. The index rejects revision downgrade or
skipped new revisions. This is not a reset of existing grants or personal stores.

Current evidence: 25 Python cases; 74 unchanged passing Android cases plus the
two corrected fixture methods each passing in a targeted rerun; the Windows
source-host group passes with zero build warnings/errors. The Android integration
case exercises actual control→protected workflow configuration, fresh grant echo
and denied Android READ yielding no albums. No physical phone, prompt, transport,
installed GUI or end-to-end acceptance is implied.

The shared vector is 284 canonical body bytes, SHA-256
`4a607be40c5d2fc917158a1007334416882ecc14a0ea18ce1681cd4a9a5c633d`,
challenge `3f919e84648c52122aa9946d27a6cd265077739a41d19f6d9395934325e2c8a4`.
Both directions derive persistent permission epoch
`8cdc2f824872a22de57b19374617d1e94770eca5ca921ad79c8469556dfa5150`.

Twenty-four Python tests, eight Android unit cases and the targeted Windows
source-host group pass; Windows build has zero warnings/errors. These are native
control/codec/scope tests, **not** an authenticated physical phone, actual OS
permission prompt or end-to-end transfer acceptance. Protected local file-policy
controller/persistence, actual channel send/receive registration, source request/
selection, MainActivity/notification-tap wiring and Organizer-only controls remain
to connect. Discovery 21 is still not advertised. No extra phone settings or
automatic background action has been added.
