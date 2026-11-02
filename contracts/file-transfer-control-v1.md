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

### Pairing identity in lower source authorities

The native gallery permission ticket, gallery lease and SAF picker/lease authority
comparisons also include the local pairing generation. A generation change is
not masked by equal receiver ID/key, channel-owner reference, permission epoch or
source epoch. SAF preferences use inner format 2 only when an explicit native
picker selection supplies a pairing association. Legacy format 1 remains in its
original protection namespace without read-time migration. An associated state
cannot be downgraded to an unassociated record; a different pairing must make a
fresh explicit selection, initially off, before enabling that source. This does
not release shared Android URI grants.

Protected source-job context and frozen-snapshot domain hashes include pairing
identity when present. Its absence preserves the exact legacy domain calculation;
an existing source cache is not silently adopted by a new pairing with otherwise
identical legacy scope fields. The actual dispatcher/fallback/UI integration
remains separate and unadvertised.

The eight affected permission/source/preference/snapshot/index/native inventory
classes pass 85 cases. These include explicit SAF re-selection for a new pairing,
unchanged legacy ciphertext, protected association downgrade rejection and actual
read-only-PFD frozen-cache restore denial when only native pairing identity
changes. The earlier attempt failed test compilation only because a fixture's
anonymous-store property was not exported; using its actual read/CAS interface
fixed setup without weakening production checks or assertions.

### Early Activity permission host, late native workflow attachment

`GalleryPhotoPermissionHost` registers the genuine ActivityResult launcher before
STARTED and allows a native workflow to attach after the Activity is resumed.
Construction/attachment does not prompt, create stores or recreate the Activity.
Pending system requests cannot be reassigned to a replacement workflow; detached
owners' results are dropped. Replacement/detachment rotates native access proofs,
and closing an old workflow cannot detach its replacement. The shared host is
Activity-owned, not closed as if it belonged to the old source workflow.

The three new host cases and affected launcher/runtime/gallery/policy classes
pass 45 cases. They exercise actual AndroidX registration/result routing under
Robolectric, preserved unsaved EditText contents, late resumed attachment,
selected-only OS readback despite success booleans, pending-result ownership and
old-owner close. These are not physical Android dialog/phone acceptance. The
actual MainActivity/service/notification command connections remain open.

MainActivity now registers this passive host in its real `onCreate` before
STARTED and unregisters the exact owner in `onDestroy`. The native foreground
route can attach an already existing runtime without creating a phone store,
service, grant or source. It holds the Activity weakly, rejects a competing
runtime and uses an exact opaque native owner handle. An old Activity's cleanup
cannot remove its replacement. All four affected runtime cases pass, including
genuine AndroidX Activity lifecycle routing; MainActivity production sources
compile. This is not installed MainActivity/phone acceptance. Explicit permission
action/notification-tap and actual command dispatcher connections remain open.

### Bound foreground permission actions and user-tap intents

Permission-UI actions use a bounded process-local opaque token, exact native
foreground owner and a snapshot of policy/kinds, receiver owner/ID/key,
permission epoch and pairing generation. They expire monotonically after 60
seconds; repeated requests do not extend the deadline. Native uncertainty,
source/owner change or expiry invalidates the old action. A successful native
launcher call consumes it once; foreground/host/dialog-pending errors may retain
it only until its original deadline. This action permits a UI request, **not**
media READ, file sending, source selection or a saved receipt.

The explicit MainActivity intent carries only that opaque token in a strictly
bounded canonical URI. PendingIntent identity differs per token and uses
IMMUTABLE + ONE_SHOT, never UPDATE_CURRENT to turn an old source's tap into a new
one. MainActivity accepts only a currently registered native action, does not
restore tickets from saved Bundles, keeps the existing draft-save path and
dispatches only after RESUMED. Invalid file-action intents do not fall through to
editor/custom/QR navigation. No background Activity or full-screen intent is
started. Optional private notification posting reports unavailable notification
permission rather than claiming a delivered dialog or prompting for POST rights.

The first 13 action/intent/runtime cases pass (6 pure native-scope cases, 3 actual
Android intent/PendingIntent cases and 4 protected runtime cases). Real OS
permission readback still belongs to the existing permission launcher/controller;
the intent's token or callback booleans do not grant access. The command dispatcher
that creates these actions from actual Organizer requests remains unregistered,
and no synchronization worker/discovery advertisement/package is activated.

The subsequent targeted notification/launcher roundtrip also passes all five
cases (four intent cases after the bounded-URI change and one new protected
runtime integration case), giving 15 distinct cases across retained evidence.
It verifies permitted private notification posting without starting an Activity,
denial of an unregistered action at the guarded native API, actual encrypted
handshake→protected policy→AndroidX permission request→OS readback, one-shot
consumption and invalidation of an old intent on source-policy change. This is
Robolectric/synthetic native integration, **not** a physical notification tap,
installed MainActivity, Android system-dialog or phone end-to-end acceptance.

### Existing-key-only native peer authority

A targeted synthetic-keystore regression confirmed that the new file bootstrap
was still reaching the normal phone loader's key-creation path when its existing
key was missing. That path is now separated: file authority reads only an existing
key and a bounded, no-follow original peer ciphertext snapshot. Compatibility
parsing and completed-pairing trust produce a read-only native view; reading does
not save migrations, defaults, ownership flags or identities.

Explicit relationship initialization updates only the selected peer's epoch in
the original raw JSON. Other peers/preferences and legacy fields are preserved.
The native serialized publication checks exact ciphertext/file witnesses and
authorization again, uses existing-key-only encryption and unique CREATE_NEW
private staging, then syncs and reads back. Old generic `.new` artifacts are not
overwritten. Held native staging is bounded and preserved rather than deleted.
The ordinary phone initialization crypto/key-creation methods remain unchanged.

The original failing case recorded one unwanted synthetic key generation; all
11 affected authority/bootstrap cases now pass with zero generation in file
authority paths. They also cover missing/replaced keys, unchanged legacy cipher
on read, raw other-peer/settings preservation, reentrant native changes, staging
evidence and the actual synthetic channel guards. This does not establish native
Android Keystore, power-loss or physical phone acceptance.

The local file identity is projected from the public phone identity already
authenticated by the transport and captured at actual active-channel binding.
The exact current channel/generation lookup uses this cache and read-only native
peer authority; it never reloads or creates an identity/private key. Authentication
loop cleanup removes the channel entry. Both new focused cases pass, including
lookup while the synthetic identity file is temporarily absent and stale-channel/
generation rejection. These are source/synthetic-channel checks, not physical
authentication acceptance.

`TelefonWerk.openNativeGalleryFileConnection` now constructs a dedicated gallery
runtime only from the current cached authenticated identity, pinned native peer,
existing Android phone key and a private native-derived directory. No path or
identity comes from a request body. A single ownership slot stays occupied until
actual UI cleanup; another channel cannot overwrite it. Construction and cleanup
run outside the Werk monitor to avoid callback lock inversion. Actual transport
finally cleanup revokes control after I/O ends and schedules the required UI
close, retaining ownership until it completes. Two new targeted synthetic native
factory cases pass: missing identity/disabled handlers, identity-file absence,
initial OFF actual encrypted write, competing connection rejection, unrelated
channel end isolation, bounded worker-thread end/UI cleanup and preserved metadata
reopen. The factory is not yet invoked by a registered remote source dispatcher;
discovery 21 and data workers remain inactive.

### Source status/configuration messages (partial dispatcher integration)

`file_transfer.sources.request` uses the ordinary strict application envelope,
at most 8192 canonical UTF-8 bytes and at most 60 seconds TTL; a command is expired
at its deadline. Inner format 1 has exactly:

* Status: `format`, `operation: "status"`.
* Configure: `format`, `operation: "configure"`, `expected_version` (the exact
  protected policy ciphertext-version hash from status), Boolean `enabled`, and
  sorted unique `kinds` (`camera`, `downloads`, `screenshots`,
  `whatsapp_received`). Enabling requires at least one kind.

No paths, native owners, OS permission claims, file grants, deletion/automatic
settings or run commands are accepted in these messages. Status does not create
an OFF policy record. Both operations require a fresh bilateral native metadata
ticket and remote receive consent, including when local send consent is OFF.
The configure ticket's deadline is also checked through the actual protected CAS
callbacks, not only before entering the transaction.

`file_transfer.sources.result` contains exactly inner `format: 1`, `request_id`,
`operation`, `version`, `revision` (0 for absent policy), `enabled`, `associated`,
`repair_pending` and sorted `kinds`. `enabled` describes saved settings;
`associated` separately states whether the policy belongs to this native pairing.
Neither field promises OS READ or currently negotiated sending. The reply is
metadata, not a file/book SaveACK, transfer checkpoint or destination receipt.

The real Android `TelefonWerk.receiveMessage` reserves control/source messages
before personal-store staging. Dispatch requires an already explicitly opened
exact native connection, does not create it from the request, and executes
outside the Werk monitor. Native authority is rechecked around the actual secure
reply, and changed source grants need fresh control echoes. Unexpected inbound
source results fail closed on the source-only phone path. Shared desktop codecs,
actual Organizer activation, permission-action invocation, album discovery/run
workers and complete data handlers remain open; discovery 21 stays unadvertised.

The first nine affected Android codec/runtime/actual-Werk-dispatch cases pass,
including decrypting real synthetic-channel replies and new-grant echoes. Linux
provides strict request builders/parsers and correlated immutable result metadata
with 27 focused cases passing. The Windows pure codec source-host group passes
with zero build warnings/errors. These desktop codecs do not yet register the
desktop transport or Organizer controls. The shared configure-envelope vector is
347 bytes, SHA-256
`5aaac403bb8fe387973221adb1a47fa5a3c63395167f5e9c6ede47b7a924ef5a`.
No physical phone/installed GUI/OS dialog or completed photo synchronization is
implied by these source-host and synthetic-channel checks.

Three additional targeted Android cases pass: the shared canonical vector,
command expiry reaching the native configurer before policy publication, and
failed reply output retaining the already committed policy without claiming
delivery or reapplying a stale expected version. Together with the retained
nine-case run this is 12 distinct Android cases; unchanged passing cases were
not rerun for these test-only additions.

Album discovery must enforce the same pairing-generation freshness as source
leases, including while an actual provider query is in progress. A focused
synthetic provider regression confirmed a missing comparison in this lower
metadata path (#331, linked from #330): a pairing-only change was incorrectly
allowed to return a catalog. The missing comparison is corrected; all nine
affected discovery cases pass, including entire-catalog rejection and cursor
closure for the injected pairing-only change. This does not imply any new
READ/send capability or deletion evidence from album metadata, nor physical
phone acceptance.

### Native selectable album snapshots (no wire/run activation)

The native workflow can project actual discovered albums into a short-lived
opaque catalog. Catalog and album IDs resolve only through that live native
mapping, for the exact workflow owner and actual discovered candidate instance.
Pages contain display labels, category and visible count, not technical
volume/bucket/path fields. Their canonical body budget is 6144 bytes, reserving
2048 bytes for a future complete correlated envelope. Every page explicitly
reports `proves_deletion: false`; neither a count nor empty/limited visibility
proves deletion.

The catalog lifetime is a fixed monotonic 60 seconds. Observed expiry, clock
rollback, host/OS/native-source revocation or close cannot be undone by replaying
matching IDs. Metadata freshness does not mint a source lease or stand in for
explicit desktop choice when an album is ambiguous. A native selection can enter
the existing actual read-only-PFD/frozen-snapshot workflow only after current
policy/OS/lease checks. The runtime exposes native discovery, not yet a remote
catalog/run command or automatic worker. Permission-command invocation, desktop
catalog rendering, actual run transport and end-to-end acceptance remain open.

Eight distinct focused cases pass: six native mapping/page/expiry cases plus
metadata-only source-scope freshness and actual discovery→opaque choice→read-only
PFD→protected frozen job→revocation/cleanup. After the native freshness callback
returns, the clock is checked again so a slow read cannot release expired
metadata. The five earlier catalog cases were rerun only for this changed clock
boundary; the two unchanged scope/workflow passes were retained. This remains
synthetic/Robolectric evidence, not physical phone acceptance.

### Discovery/page command connection

The request envelope now also accepts `discover` with exactly `format`,
`operation`, `expected_version`, and `catalog_page` with those fields plus
canonical UUID-v4 `catalog_id` and integer `after` in 0..128. Both use the exact
current protected policy version, a fresh native metadata ticket **and** current
negotiated source-send authority. Neither activates a policy, requests OS READ
nor opens image bytes. OS permission and the existing native permission host are
checked independently by the real workflow. A new discovery invalidates the
prior native catalog mapping; a page can only address an existing live mapping.

`file_transfer.sources.catalog` returns inner format 1 with `request_id`,
`operation`, `version`, `page`. The bounded page contains `format`, `catalog_id`,
`after`, nullable `next_cursor`, `coverage`, `proves_deletion: false`, and `albums`.
Album metadata has only opaque UUID-v4 `album_id`, `kind`, `display_name`,
`visible_images`, `needs_choice`. Paging cursors, IDs and visible counts are not
READ/delete authority or complete file inventories. Native freshness is checked
again at the actual secure send. Linux/Windows strict correlated page decoders
check request/operation/policy/catalog/cursor identity and reject deletion claims,
duplicate IDs, extra technical path fields and malformed metadata.

Nine affected Android cases pass, including actual MediaStore discovery through
the encrypted channel, stable paging, initial-OFF denial and old-ID rejection
after rediscovery without photo PFD opens or permission prompts. The targeted
Linux catalog run passes 25 cases (24 catalog checks plus the unchanged configure
golden after its builder change). The Windows source-settings group passes;
build warnings/errors are zero. Desktop transport/UI registration, explicit
permission-command invocation, native activation callers, run workers and full
transfer/recovery/baseline integration are still open. No discovery advertisement,
automatic synchronization, physical phone/installed GUI acceptance or release is
implied.

### Explicit native permission command connection

`request_read` is an explicit source command with exactly `format: 1`,
`operation: "request_read"`, `expected_version`. It does not carry an OS grant,
native owner, action token or notification-permission claim. Actual Android
dispatch queues at most one native permission operation on the main thread and
rechecks the whole command/deadline, protected version, native pairing, fresh
metadata ticket and current source-send authority before invoking the existing
bound foreground action. It never starts an Activity from the background.
Foreground execution uses the genuine launcher; otherwise the optional private
notification path or foreground-required state is used. Ending the native file
connection before the UI callback prevents it from running.

`file_transfer.sources.permission_result` has exactly inner `format: 1`,
`request_id`, `operation: "request_read"`, `version`, `state`. States are
`requested`, `notification_posted`, `foreground_required`, `failed`. These are UI
attempt metadata, **not** OS permission, a currently usable notification/action,
media READ or a transfer receipt. The real OS permission controller still owns
readback and permission epochs. A repeated response may describe a prior attempt
whose native action has since ended; a new explicit user attempt needs a new
request ID, not resurrection of an old native owner.

A bounded process-local command ledger is shared by the actual native transport
owner across file-runtime reconnects. Its key is authenticated local/peer identity
and pairing scope plus request ID; exact canonical command bytes must match.
Up to 64 receipts are held for a monotonic 60 seconds. Failure evidence is recorded
before the UI call, so lost replies/native UI exceptions cannot cause the same
command to prompt again. Clock rollback fences the ledger. No personal store or
persistent OS ticket is created. UI-queue failure closes only the file route
without inventing success or crashing the Activity; unrelated phone transport is
not deliberately closed by that callback. Desktop request/result codecs remain
metadata-only. This is not yet a complete Organizer activation/run UI or physical
phone/system-dialog acceptance.

Thirteen focused Android cases pass for this connection: strict command parsing,
bounded/replay-safe command receipts, genuine AndroidX request after denied OS
permission, actual native queued notification without starting an Activity, and
cancel-before-UI ownership. The single extended actual-Werk case also passes
after file-runtime close/reopen and fresh control epochs: the shared ledger
returns only the previous attempt metadata, does not recreate a foreground
owner, and leaves the original action invalid. The other twelve unchanged passes
were retained, not counted twice. Linux passes 23 targeted codec cases; the
Windows source-settings group passes with zero build warnings/errors. These are
synthetic/Robolectric/source-host checks, not a physical tap, installed UI or OS
system-dialog acceptance.

### Explicit source-preparation I/O owner (not activated)

The native source worker is inert on construction. An explicit native start owns
one preparation operation; cancellation/close only signals cancellation and does
not release a blocked provider or claim I/O end. The slot is released only after
the preparation function, including descriptor cleanup, has actually returned.
Native cancellation and completion callbacks execute outside its owner monitor.
Unexpected preparation errors remain held failures, not successful snapshots.

`snapshot_ready` is source-cache metadata only: it is not a sent/accepted offer,
published destination, retired quota, saved receipt or complete synchronization
END. The desktop's whole-run coordinator must remain active through actual data
transport/worker completion, independently of this source-preparation slot.
Source-index/runtime cleanup must wait for actual preparation quiescence. This
worker is not yet connected to runtime-close ownership or a remote run command;
no timer, retry, implicit scan, quota cleanup or discovery advertisement is
activated by the class.

Five distinct focused cases pass: four ownership/error/cancellation cases and
one actual native workflow/provider/read-only-PFD/encrypted-index integration
case. The real preparation runs off the main thread; after its I/O end the
protected cache job remains held until explicit native retirement, and changing
the live source does not alter the frozen chunk. No permission prompt or source
mutation is introduced. These are synthetic/Robolectric checks, not a physical
phone, runtime-close integration or end-to-end transfer acceptance.

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
