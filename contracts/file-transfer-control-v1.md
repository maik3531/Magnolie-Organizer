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
Up to 64 receipts are held for at least a monotonic 60 seconds and until their
original command envelope has expired. Failure evidence is recorded
before the UI call, so lost replies/native UI exceptions cannot cause the same
command to prompt again. Monotonic or observed wall-clock rollback fences the ledger. No personal store or
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
Source-index/runtime cleanup must wait for actual preparation quiescence. The
worker now connects to native runtime preparation and quiescent close ownership,
but not a remote run command. No timer, retry, implicit scan, quota cleanup or
discovery advertisement is activated by the class.

Five distinct focused cases pass: four ownership/error/cancellation cases and
one actual native workflow/provider/read-only-PFD/encrypted-index integration
case. The real preparation runs off the main thread; after its I/O end the
protected cache job remains held until explicit native retirement, and changing
the live source does not alter the frozen chunk. No permission prompt or source
mutation is introduced. These are synthetic/Robolectric checks, not a physical
phone or end-to-end transfer acceptance. Runtime-close evidence is recorded below.

### Nonblocking revocation and quiescent native cleanup (#332)

Two focused regressions first confirmed that UI close waited behind an actual
album-provider query and a blocked encrypted control-frame write. Both used
bounded, unchanged 500-ms guards and released their native I/O cleanly afterwards.
Runtime operations now use a separate nonwaiting single-operation gate, not the
short ownership monitor used by UI cleanup. Native revocation flags are permanent
and checked before/after lookups and actual writes; close does not wait on an
adapter's frame-write monitor or the session's native lookup monitor.

Native configuration tickets remain bounded in memory for exact finally cleanup
under their ordinary monitor. Closing does not clear that map concurrently; a
revoked ticket authorizes nothing and still cannot be consumed twice. No further
native metadata/key lookup is needed to reject closed authority.

The runtime retains its source index, permission workflow and exact connection
owner until both command/provider/control I/O and source preparation are truly
quiescent. It then posts final UI cleanup and reports native ownership release
once. Actual worker end is serialized with callback registration to avoid losing
the completion race. Cancellation does not retire reserved/sealed cache quota or
claim complete synchronization END.

All 28 affected control/session/channel/runtime/native-provider/reconnect cases
pass. They include the unchanged UI responsiveness guards, blocked native lookup,
blocked PFD source preparation, direct/connection pending close, normal completion,
exact one-shot cleanup, held cache evidence and unchanged source bytes. These are
synthetic/Robolectric/source-host checks, not physical phone, native installed UI,
power-loss or complete file-transfer acceptance. #330's remote run/data handlers,
desktop activation/preferences/UI and full recovery/baseline integration remain
open, with discovery 21 unadvertised and no package publication.

### Permission response transport is not UI work (#333)

A further actual-dispatch regression confirmed that the permission-result frame
write itself could block Main (unchanged 500-ms guard). The native UI operation
now prepares attempt metadata only. A bounded connection-owned background task
independently acquires a fresh configuration ticket and checks current negotiated
source authority, exact protected policy version and the original command deadline
before/after actual response output. Serialized result fields never grant that
authority. Control echoes also run on the background task, not Main.

The permission queue stays occupied through actual response/control I/O end.
Close revokes immediately but retains the native connection until that task ends;
final UI cleanup is posted before reporting task completion. A queued action after
close cannot run. Four focused cases pass: the extended actual-dispatch/reconnect
case with its unchanged response-write guard, cancel-before-UI, blocked background
ownership through close, and expired/changed-version/revoked versus unchanged
native send authority. Existing unchanged permission-ledger evidence is retained.
This is synthetic/Robolectric evidence, not physical phone acceptance or completed
synchronization. No package, discovery advertisement or automatic run is enabled.

### Native whole-run identity and offer output (not remote-activated)

The native runtime now retains one whole-run handle separately from its source
preparation slot. `snapshot_ready`, source I/O end and successful offer output do
not release it. A second whole run or separate preparation is rejected while it
is held. Native handle identity, not a supplied ID string, selects the run.

Offer output restores the actual protected frozen source under current native
authority, builds the complete immutable offer and rechecks source authority
after actual output. Failed output does not create an output receipt. A stored
offered-manifest hash is only historical output evidence, not remote acceptance,
publication or synchronization success. Explicit cancellation holds the slot
until preparation I/O really ends; native stopped-run end does not retire quota
and cannot report successful synchronization. No success/end-from-totals API or
remote run/data handler is introduced.

The extended actual provider/runtime test passes for blocked direct/connection
close and normal completion, including frozen source restoration, failed offer
output, a real encrypted offer frame with native manifest readback, rejected
overlap/foreign handles, cancellation and one-shot stopped-run end. Reserved or
sealed quota and source bytes remain preserved. This is one targeted method with
three native modes, not three separate tests or physical/end-to-end acceptance.

### Explicit remote source-run preparation (partial data integration)

Source commands additionally accept `run` with exactly `format`, `operation`,
`expected_version`, `catalog_id`, `album_id`, Boolean `desktop_choice`; and
`run_status`/`cancel_run` with exactly `format`, `operation`, `expected_version`,
`run_id`. IDs are canonical UUID-v4 native mapping keys, never path or READ claims.
Start resolves a live native catalog/selection under current source authority;
the original command authority/deadline is rechecked after selection before
starting actual source I/O. Status/cancellation access an already native-owned
whole run using a fresh metadata ticket and exact protected version.

`file_transfer.sources.run_result` contains exactly `format: 1`, `request_id`,
`operation`, `version`, `run_id`, `state`, Boolean `source_io_ended`. Source states
are `preparing`, `snapshot_ready`, `cancel_pending`, `canceled_held`, `failed_held`.
Neither successful preparation nor cancellation conveys complete sync END,
destination publication, saved receipt or quota retirement. A stopped run remains
held; no remote success/retire/end command is introduced.

A bounded 64-entry process-local start ledger with a minimum monotonic-60-second
retention and an original-envelope-expiry guard is shared by
the actual transport owner. Exact repeats on the same native runtime return the
same native handle without another scan. Modified bytes with the same request ID,
failed attempts and adoption by a new runtime fail closed. It is not a restart
recovery database or source-consent record. No disk reset or implicit rescan on
reconnect occurs. Linux/Windows strict metadata codecs correlate operation,
request/policy/run identity and source-I/O-state consistency, rejecting fabricated
success/publication/quota claims.

Fourteen distinct affected Android cases pass across the parser, replay ledger,
actual encrypted source-run/blocked-PFD path, native whole-run/offer lifecycle
and actual permission-dispatch/reconnect guard. The final source-run test also
proves an expired command cannot start photo I/O after selection. Linux passes 25
targeted codec cases (24 run cases and the unchanged configure golden after its
builder change); the Windows source-settings group passes with zero warnings or
errors. These remain source-host/Robolectric/synthetic-channel checks. Desktop
activation/UI, accepted-offer/chunk/resume/receipt handlers and full recovery/photo
baseline integration remain open. Discovery 21 stays unadvertised; no automatic
synchronization or package publication is enabled.

### Replay retention across clock skew/rollback (#334)

A focused parser/native-ledger regression confirmed that a future-dated command
allowed by the existing general header clock-skew tolerance could outlive a
receipt retained for only sixty seconds after receipt and prompt twice. Dedicated
permission/run start histories now prune an entry only after **both** its minimum
monotonic retention and original wall-clock envelope deadline have passed.
Capacity stays bounded at 64; live fences are not evicted to make space. Observed
wall-clock rollback permanently fences that process-local history, including
after an earlier pruning, rather than allowing an expired command to revive.
The general message clock-skew rules, wire codecs and grant defaults are unchanged.

Fourteen affected Android cases pass: permission history seven, run history five,
actual permission-dispatch/reconnect one and actual encrypted source-run one.
They include the original future-command replay failure, rollback after pruning,
capacity held beyond sixty seconds and safe capacity reuse only after both bounds.
No physical phone/UI or completed synchronization acceptance is implied.

### Exact offer acceptance, distinct from local destination receipt

`file_transfer.accept` uses the strict ordinary envelope with maximum 8192 bytes,
60-second TTL and strict expiry. Inner format 1 has exactly `offer_id` (UUID-v4),
`transfer_id` (32 lowercase hex), `manifest_sha256`, `acceptance_sha256`,
`permission_epoch`, `destination_token` (each hash/token 64 lowercase hex).
There are no target paths, per-file partial acceptances, OS READ assertions or
saved-destination claims. The acceptance fingerprint binds the receiver's native
immutable accepted description; the opaque destination token identifies its
native destination binding, not a path supplied to the phone.

The phone records exact offer output only after actual secure output and source
revalidation. The actual message dispatcher reserves acceptance frames before
personal staging. A current noncancelled native run must already have output the
exact offer ID/transfer/full-manifest hash, and current native permission epoch
must match. The protected frozen source is restored and validated independently;
offer/acceptance deadlines are checked again after that native work before binding.
An identical acceptance replay is harmless; replacement bytes or another target
token cannot silently rebind it. No new offer replaces an accepted run.

On Linux `NativeFileReceiveOperation.acceptance_message` exports this metadata
only after actual native catalog reservation, exclusive receive lease and staging
admission, in receiving phase and with fresh original destination/binding checks.
Building a message is not send completion or publication. Windows currently has
only the strict acceptance decoder, not native receiver admission/transport.
Neither parsed acceptance nor a destination token substitutes for native grants
on either endpoint; it is not a file/book SaveACK or cache-retirement receipt.

Five distinct Android cases pass (strict codec two, shared golden one, actual
provider/runtime/offer/acceptance lifecycle one, actual-Werk reconnect one).
Fourteen Python cases pass, including actual receiver admission, binding/expiry
fences and the golden. The Windows acceptance source-host group passes. The
shared canonical acceptance vector is 624 bytes, SHA-256
`ac032b156bba0bd7ba63602d5d27dd72563dfaa2901c3f1b6fe5f1234c119c1d`.
This does not yet activate chunk/resume/receipt data handlers, desktop UI or a
published capability. Physical phone/installed UI/full synchronization acceptance
remain outstanding, with discovery 21 unadvertised.

### Accepted-source chunk request/output (partial receiver integration)

`file_transfer.chunk.request` uses a strict maximum-8192-byte envelope with at
most 60 seconds TTL and strict expiry. Inner format 1 has exactly `transfer_id`,
`manifest_sha256`, `acceptance_sha256`, `permission_epoch`, `destination_token`,
`file_id`, integer `chunk_index`. Transfer/member IDs are 32 lowercase hex; the
hashes/token are 64 lowercase hex. No path, range extension, late manifest member,
OS grant, progress total or publication claim is accepted.

The actual phone dispatcher resolves only the currently native-owned noncancelled
whole run and its immutable acceptance. Every binding must match. The protected
frozen source is restored under current native source authority and the requested
exact member/chunk is read from it. Deadline/native authority is checked again
after the actual read and around actual secure output. The temporary raw chunk
buffer is cleared on completion/failure. No source quota or whole-run slot is
released by chunk output.

`file_transfer.chunk` returns all request fields plus `request_id`, canonical
`data_base64`, `data_sha256`. Data is at most 65536 bytes; the complete application
envelope uses the existing 262144-byte budget, not the smaller metadata budget.
The phone reserves unexpected inbound chunk data before personal staging and
rejects it on this source-only route. The response is source bytes, not a durable
checkpoint, accepted publication, saved receipt or synchronization END.

Linux's native receive operation can build a request from the actual accepted
transfer and consume a response only with exact original request correlation,
full accepted manifest/native binding, expected member/index/length, canonical
base64 and actual data digest. Those checks precede native staging; the existing
durable encrypted-stage/readback/resume-ledger operation then records it. A fresh
response header does not revive an expired original request. Windows currently
provides pure strict chunk preflight only, not native receive admission or writes.

The targeted Linux chunk run passes 23 cases, including real stage/readback/
checkpoint, 65536-byte and final-partial chunks, duplicate no-recount, different
duplicate rejection, revoked binding and no implicit publication or quota release.
Four affected Android cases pass: strict request/complete chunk budget two,
actual native protected-source→encrypted chunk→decrypted byte readback and lifecycle
one, and actual-Werk permission/reconnect one. The Windows chunk source-host group
passes with zero build warnings/errors. These are synthetic/Robolectric/source-host
checks, not physical phone or installed native Windows receiver acceptance.
Desktop transport/UI activation,
resume/receipt data handlers and complete recovery/photo baselines remain open;
discovery 21 stays unadvertised and no automatic run/package is enabled.

The Linux receive operation also exposes a single explicit native coordinator
step, `next_chunk_request_message`. It selects the first missing member/chunk
only from its actual verified ledger. Reopening already authenticates the
checkpoint and reads back every claimed staged chunk; corrupt evidence prevents
admission rather than being trusted as progress. Returning no next request means
only that no source bytes are missing, never publication, local save, quota
retirement or synchronization END. Six new targeted native cases pass, including
reopen/next exact chunk, multiple manifest members, empty file, corrupt staged
member retained/fenced, native revocation/close/publication and exclusive receiver
ownership. This API starts no timer or background loop and is not a physical
restart/end-to-end phone acceptance.

### Historical local-save confirmation, not synchronization END

`file_transfer.saved` projects a complete set of protected receiver-local saved
receipts. Its strict envelope has at most 60 seconds TTL, strict expiry and the
existing complete-application budget (262144 bytes). Inner format 1 has exactly
`transfer_id`, `manifest_sha256`, `acceptance_sha256`, `permission_epoch`,
`destination_token`, `receipts`. Every manifest member appears once in manifest
order, with exactly `file_id`, integer `size`, `sha256`, `receipt_sha256` (the
protected local record hash). Full manifest hashes/sizes/IDs must match; a partial
or duplicate set, path, native file key, grant, quota or sync-success claim fails.

Linux `saved_receipt_message` reads the actual protected index receipts afresh,
including their native DB/directory durability checks, under current native
destination/binding authority. Verified chunk totals and physically published but
unreceipted files cannot produce this message. Receipt construction/publication
is a separate explicit local operation. Reopened historical receipts can be
projected without repeating publication or overwriting later PC edits. Partial
receipt commit/recovery remains held, never represented as a complete set.

The phone independently binds the remote historical assertion to its exact
noncancelled native run, immutable acceptance, current permission epoch and actual
protected frozen-source manifest. Deadlines are checked again after native work.
Identical content is idempotent; a different receipt set cannot silently rebind it.
The immutable remote metadata is **not** a native phone saved receipt, evidence of
current destination presence, photo-baseline commit, source quota retirement or
whole synchronization success. The native whole-run slot and cached source stay
held. Phone restart recovery and explicit baseline/quota completion remain open.

Four Android cases pass (strict full-128-member codec two, actual runtime lifecycle
one, actual-Werk reconnect one); Linux passes 14 targeted real saved-receipt/
protected-readback/history/partial-commit cases. The Windows pure saved-confirmation
group passes, without implying native receiver admission or publication support.
These source-host/Robolectric/synthetic checks are not physical phone, installed
GUI, real power-loss or full end-to-end synchronization acceptance. Desktop
coordinator/activation/Pictures preferences/advanced UI, complete recovery/photo
baselines and native quota completion remain outstanding. No package, automatic
run or discovery 21 advertisement is enabled.

### Read-only desktop native authority preparation

Linux can read the fixed existing native `peers.json` storage object through the
already-existing-key protection adapter, using its fixed native storage AAD.
It never constructs `PhoneStore`, calls its migrating/defaulting peer loader,
loads `identity.key`, opens the personal queue DB or accepts a path/object domain
from a request. Regular-file/owner/mode/no-link/bounded-size and before/after
descriptor/name/crypto checks reject changes while reading. Missing/corrupt data
is preserved and fails closed; no key, identity or peer defaults are generated.

The pure authenticated-public-identity projection needs the native desktop role.
It is not authentication by itself: only the future actual channel/generation
cache may supply it as a controller identity. Native peer snapshots require one
exact pinned ID/key and an existing complete own-device pairing epoch. Legacy,
pending, ambiguous or non-own records grant nothing. Discovery metadata remains
separate from handler readiness and file consent. This helper is not yet the
actual desktop transport/activation controller.

Python and Windows native control-peer scopes can carry the persistent pairing
epoch independently of wire grants. A changed epoch or a differently bound native
peer invalidates the session; restoring old fields does not revive it. The field
is not serialized and does not change existing control/permission golden bytes.
Forty-three affected Python cases pass (17 native authority and 26 control cases),
including actual native AEAD readback, no store/key creation, blocked legacy
normalization, peer change during decryption and same-key re-pair isolation. The
Windows control source-host group passes. No installed Windows/native GUI, physical
phone or completed desktop transport acceptance is implied.

The actual Linux `PhoneService._session` now captures the public desktop identity,
pinned peer, native store owner and service generation used by its authenticated
handshake. Exact channel binding caches that public projection only after native
activation; finally cleanup removes it. Lookup never reloads the identity or
private key, selects by device label/IP, or fabricates a missing channel entry.
Stale generation/store/channel ownership is rejected. Ordinary transport activation
without this captured native binding does not create file authority.

An explicit native authority factory opens only the captured existing native
directory/key and read-only pinned peer. Its metadata/key work happens outside the
service ownership monitor. Active-channel, generation, pairing and root/key checks
surround actual reads. Replacement, removal, read failure or revocation permanently
ends that owner; restoring old values cannot revive it. UI revocation is a
nonwaiting native signal; final descriptor close belongs to the I/O owner after
actual work ends. Construction starts no worker/listener/source scan and creates
no file consent, preference record, receiver job or native pairing default.

Eleven targeted Python cases pass, including native factory/no-identity-reload/
no-key-replacement, channel replacement, blocked peer I/O with immediate revocation,
service-monitor exclusion and existing call/transport activation behavior. A bounded
local socket-pair fixture exercises actual session MAC, directional encrypted
Ready frames, captured public identity and end cleanup; a generation change during
that handshake creates no file binding. Unrelated personal outbox producers are
inert in that focused crypto fixture. This is not installed GUI, physical phone,
full personal-sync/control-handshake or desktop file-controller acceptance. The
desktop source/receiver dispatcher/preferences/activation UI remains unconnected,
with discovery 21 still absent.

### Explicit native photo-destination choice (UI/persistence join pending)

The Linux native folder controller is inert on construction. Only an exact
process-local owner-bound, monotonic-60-second, one-shot action can choose/create
the default subfolder. It rechecks the native paired authority and action deadline
around actual folder work; expired/rolled-back/closed/foreign/serialized actions
cannot revive or create a folder. Closing this folder UI owner revokes its actions,
not the shared file-authority owner or a running synchronization.

Default Pictures comes from `GLib.get_user_special_dir(DIRECTORY_PICTURES)`, never
a guessed localized path or HOME fallback. The bound native peer's display name
is NFC-normalized and reduced to one bounded safe component before adding
`-Fotos`. Root/ancestor witnesses, native owner/mode checks, directory-relative
creation and no-follow checks prevent adopting a linked/replaced default folder.
Existing files/folders are never cleared or overwritten. A custom choice captures
an explicitly selected native existing directory; no wire action can select paths.
Choice tokens/witnesses remain metadata, not receive consent or write authority.
The Windows path projection uses `Environment.SpecialFolder.MyPictures` and the
same bounded safe-name policy; it creates no folder itself.

Seventeen focused Linux cases pass, including inert construction, native GLib API
selection (stubbed native provider), no folder after expired/slow/closed/revoked
actions, wire/foreign action rejection, custom choice, preserved PC edits and
symlink rejection. The Windows path-projection source-host group passes. These
are not real native folder-dialog/installed GUI/Windows-profile acceptance. Actual
protected photo preferences, desktop activation/controller integration and the
Organizer advanced-controls caller remain open. No background synchronization,
consent defaults, deletion propagation or discovery advertisement is introduced.

### Protected native photo preferences (controller/UI join pending)

Linux now has a separate existing-key-encrypted photo-policy store under the
captured native telephone root. Its constructor and absent reads create no
directory/database, identity, key, pairing or personal-store defaults. An absent
policy is manual, receive/send off and both deletion directions off. Only an
exact owner-bound one-shot native action can configure it. A native destination
choice is still not consent; enabled receive additionally needs an associated
saved policy, a currently available original destination and ready native handlers.
Send permission is always off. Reverse deletion is explicitly unavailable.

The dedicated SQLite owner/policy records bind native root/database/lock inode
witnesses, exact public identity scope, persistent pairing generation, revision,
destination witness/token and policy ciphertext hash. Ciphertext compare-and-swap
rejects stale settings; each explicit update creates a fresh consent epoch.
Re-pairing the same ID/key leaves the old policy preserved but unassociated/off.
Schema, protected-record, missing-owner/policy and observed revision rollback
fail closed without resetting data. A lost destination closes receive permission
but does not prevent an explicit disable while preserving its historical witness.

Nonwaiting operation/flock gates distinguish a competing live transaction from
corrupt metadata. Native action deadlines are checked before commit and readback;
transaction failure rolls back, while uncertain commit/durability/readback never
reports success and requires reopening. Close immediately blocks new lookups,
retains descriptors through actual active work, then releases them at I/O end.
Interrupted initialization stays preserved and closed rather than being defaulted.

Twenty-five targeted native Python cases pass, covering actual existing-key AEAD
policy/readback, defaults, pairing isolation, CAS/action replay, unavailable target,
missing key, partial-open lock retry, concurrent transaction, crypto/expiry failure,
post-commit durability uncertainty, corrupt/missing metadata and close during
blocked encryption. These fixture/source-host checks are not real power-loss,
native dialog, installed GUI or physical synchronization acceptance. No scheduler,
worker, desktop dispatcher or advanced-controls caller is connected by this
store; discovery 21, automatic runs and package publication remain disabled.

### Actual desktop reserved control dispatch (data readiness remains OFF)

An explicit native `PhoneService.open_native_file_connection` can now attach one
file-control owner to the exact captured authenticated channel/generation. Native
authority/preference reads happen outside the service monitor. A foreign output
channel, second owner, replaced channel or stale key/generation cannot adopt it.
The constructor starts no worker, sends nothing and creates no preference store.

The actual desktop `_payload` reserves the entire `file_transfer.*` namespace
before personal defaults, deduplication, staging or legacy acknowledgement logic.
Without an admitted native owner it fails closed. The present owner supports only
strict file-control packets and their actual secure echo completion. Unsupported
offers/data/source metadata fail closed rather than falling through. Legacy
outbound/global-grant/outbox paths also reject the reserved namespace; only the
dedicated owner performs guarded control writes. A failed or expired actual write
is never marked sent. Control callbacks do not run under the service monitor.

Transport end/replacement removes cached file authority before revoking the native
control owner. Revocation is nonwaiting; an active control write retains native
resources until actual I/O end and cannot mark late completion or enable a new
owner on that ended channel. Even an associated enabled/automatic saved policy
announces send/receive OFF here: full desktop data handlers, source-command
authority, recovery/baseline union and private advanced UI are not yet ready.
Control echo is not permission to scan, transfer, publish or synchronize.

Thirty-seven targeted Python cases pass across actual reserved dispatch/native
control ownership, factory/authenticated socketpair lifecycle, transport/call
replacement, outbound namespace fencing and affected personal actor/time/MCP-call
paths. Fixtures forbid legacy peer/defaulting, dedupe, persistence and outbox calls
on reserved file routes. Blocked-write close, lost-output/expiry and foreign native
channel cases are included. This is not installed/native-dialog or physical phone
acceptance. No frontend activation, data worker, scheduler, new package, automatic
run or discovery 21 advertisement is enabled.

The bounded authenticated socketpair fixture additionally exercises this actual
reserved control route, not only an in-memory channel double: real session MAC,
directional AEAD Ready, explicit native owner attachment, encrypted outbound
control, encrypted inbound peer control through `_session`/`_payload`, actual
encrypted echo output and native resource cleanup at channel end. All three
fixture modes (normal, generation changed, file control) pass; the added mode is
one new case, not three new feature checks. No photo policy directory or data
grant is created. Unrelated personal outbox producers remain inert in the fixture;
no physical device, installed GUI or complete source/data/recovery handshake is
claimed.

### Guarded native desktop receive coordinator (release gate still OFF)

The desktop owner now joins offer admission, the existing native receive operation
and real reserved-message dispatch behind its private native data-readiness gate.
The production gate remains **false**: no discovery advertisement, automatic run,
frontend activation or released receive capability follows from this implementation.
An offer is first frozen as detached metadata under the exact current consent,
destination token and bilateral control binding. It creates no reservation or
destination data. A fresh exact native one-shot action and offer ID admit one
whole native run; changed policy, destination or binding cannot rebind a pending
offer. Admission reserves the native catalog job and claims the actual staging
lease before secure acceptance output. Lost output keeps the exact admitted job
and acceptance message for explicit retry, never another reservation.

Explicit native I/O-lane steps select missing chunks only from the authenticated
ledger, retain one correlated outstanding request and record actual durable stage/
readback/checkpoint results. Unrequested or mismatched responses fail before writes;
duplicates do not recount bytes. A response that arrives before an actual outgoing
write returns waits on the bounded native I/O gate rather than being discarded as
busy. This is not UI-thread waiting. Revocation remains nonwaiting and descriptors/
the native owner remain held through real I/O end. Cleanup uncertainty stays closed
and is not treated as successful release; other resources are still closed.

No missing bytes is not a save or synchronization END. A separate exact native
publication action uses the guarded publisher, never overwrites existing targets,
commits protected local saved receipts and sends their pathless historical
projection only after readback. A later confirmation retry does not republish or
overwrite subsequent PC edits. Whole-run/cache/quota ownership is not retired by
chunk completion, publication or the remote confirmation.

Existing-job discovery creates nothing. Explicit resume requires a fresh current
offer, exact full manifest, original native binding/destination and a selected
protected native job. It reopens the real exclusive lease and authenticated staged
checkpoint, never trusts progress totals and never reserves a second job. Corrupt
claimed bytes fence admission without reset. Resumed publication remains
repair-pending: its old publication authority is not recreated automatically.
Existing complete local receipts can still be projected historically without
modifying later PC edits. This does not renew phone OS READ proof after restart.

The joined targeted Python run passes 63 cases: native coordinator 21, existing
desktop control/default-OFF fences 25, actual crypto-session modes 3 and accepted-
message cases 14. The crypto fixture then passes all four modes including one new
actual encrypted receive case, giving 64 distinct affected cases. That new mode
exercises real session MAC/directional Ready, native policy/control binding, secure
offer dispatch, actual acceptance/request output, encrypted chunk input, durable
staging/readback, explicit publication, protected saved-confirmation output and
transport-end cleanup. Its source is an isolated authenticated fixture, not a real
Android Gallery source or physical phone. Readiness is overridden only inside the
tests. Installed GUI, real power loss, full conflict/baseline/tombstone/quota union
and physical phone acceptance remain outstanding.

Architecture boundary: this protocol's current Android counterpart is the Notes
app's native telephone/Gallery runtime. Notes-content synchronization need not be
enabled, but stock KDE Connect alone does not implement these source/manifest/
acceptance/chunk/receipt handlers. Notes-dependent desktop controls belong under
Organizer → Magnolie Notes phone connection → Advanced functions; KDE-Connect-only
functions remain under KDE Connect. The earlier common KDE placement is superseded
by the user's explicit backend-specific UI requirement.

Both desktop frontends now have separate backend-labelled cards and an independent
`telefon-erweiterte-funktionen` details section owned by the Notes card. The existing
`kde-erweiterte-funktionen` keeps KDE input and player controls. Clear translated
prerequisite hints state that Notes functions require Notes on Android but not KDE
Connect, and vice versa. Notes' unfinished additional features remain unavailable;
opening the details starts no native command or grants. Twelve isolated full-UI
source-host cases pass across Linux/Windows: Notes-only, KDE-only, both, neither,
loading and German labels. Existing data/explicit phone selection stays unchanged.
All 38 desktop PO catalogs preserve previous translations and add exactly the two
new hints; the existing Linux PO/POT/JS/MO gates and Windows localization-completeness
gate pass. These are not installed GUI or native profile acceptance.

The German/English Notes Fastlane short and full package descriptions also state
its optional phone-counterpart role, independent of note synchronization and KDE
Connect. Existing optional access purposes and GitHub version-check privacy are
retained. Prepared image-read access is explicitly development-only/not enabled,
not advertised as working full photo synchronization. Notes' F-Droid/readme docs
require metadata, manifest, actual APK and enabled feature paths to agree before
submission; no camera/microphone or mirroring availability is claimed. Six source
metadata checks pass, including 80/4000-character limits and existing image-only
manifest scope. This is no F-Droid approval/scanner, APK build, signing or submission
evidence, and no Android permission was added or enabled by the text changes.

### Native desktop receiver-command authority and source dispatch

Visibility correction (supersedes the earlier always-rendered Notes placeholder):
the user requires the Notes advanced section to be absent when the connection is
disabled, only Organizer was upgraded, or the counterpart/device/system does not
support it. There is currently no released native advanced-feature availability
projection, so both frontends omit the unfinished section entirely, including
loading and bridge-unavailable paths. Connection enablement, pairing and claimed
device-status version 21 cannot expose it. Future visibility requires actual native
handler/system/counterpart readiness, not a synthetic frontend capability flag.
KDE controls remain independent. Twenty full-frontend source-host cases pass across
Linux/Windows, including status transitions, disabled-but-paired, old counterpart,
unsupported-system and claimed-capability fixtures, with stored data unchanged.
Deterministic Linux POT extraction also passes. No installed/native GUI acceptance
or positive supported-feature activation is claimed by these checks.

The Linux control session now issues one exact process-local receiver-command
ticket only after native own receive consent and completed bilateral actual
control echo. Remote source send may still be OFF: this is the source-policy
bootstrap, not an Android READ proof or file-data permission. The ticket binds
the original local permission bytes/native peer owner and remote session, with a
maximum monotonic 60-second lifetime. Source send-policy changes during that exact
configuration are allowed; local consent, lifecycle, pairing, manifest support,
policy-pending state, observed clock rollback or I/O uncertainty fence the attempt
without revival. Foreign/copied tickets cannot adopt it, and close does not remove
its outstanding attempt before actual I/O-finally cleanup.

Behind the unchanged private readiness-OFF gate, the actual desktop owner can
explicitly send status/configure/discover/catalog-page/request-read and
run/run-status/cancel-run commands, using a native one-shot action rather than a
personal queue. It keeps one exact correlated outstanding attempt. Lost output
retains the original command/ticket for exact retry, never silently starts a new
scan. Both original wall-clock command expiry and native ticket authority are
rechecked around actual output and result parsing. Immediate responses wait on
the native I/O lane. Close revokes now but retains ticket/resources until actual
work ends. Serialized permission-attempt results do not grant OS READ.

Configuration metadata alone does not make the next command safe: the phone
writes its changed native controls after its policy reply. The PC therefore waits
for an advanced native remote-control witness and the actual completed new echo
before issuing the next command. Returned policy versions/revisions cannot roll
back; album selection and paging use only the exact native returned catalog/IDs/
cursor. Duplicate album IDs across pages are rejected. Native source run ID and
whole-run ownership remain held after snapshot-ready, failure or cancellation;
later metadata cannot revive canceled/failed runs or undo source-I/O end.

The joined targeted run passes 101 Python cases (source dispatch 12, native ticket
13, control 26, native receive/resume 21, default-OFF desktop controls 25, actual
crypto modes 4). A further source-state fence extends/replaces the 12 source cases
with 14 passing cases, including legitimate failed-held→canceled-held cleanup
without revival, for 103 distinct current affected cases. Windows/Android
wire schemas are unchanged in this step; no source offer-trigger operation or
full app-to-app photo synchronization is claimed. Actual offer-request correlation,
native advanced UI bridge, baseline/conflict/tombstone/quota union, phone restart
READ renewal and physical acceptance remain outstanding. No timer, automatic
worker, discovery 21 or package is enabled.

### Explicit immutable native run offer request (integration still gated)

`file_transfer.sources.request` operation `offer_run` accepts exactly format,
operation, expected_version and the original native run_id. Android requires the
held whole run, ended source preparation, current native Gallery read authority
and its protected frozen manifest. Before actual output it retains one immutable
offer envelope plus exact request ID/full canonical command digest. Failed offer
or result writes may retry only that same attempt; differing command bodies or
new request IDs cannot replace it. Original wall expiry, observed wall/monotonic
rollback and a bounded native monotonic deadline permanently fence the attempt.
No cache/provider reopen scan, whole-run release or quota retirement is implied.

Actual output is `file_transfer.offer` followed by the correlated sources.run_result
with operation `offer_run`, snapshot_ready, source_io_ended=true, offer_id and
manifest_sha256. Only this result operation accepts those two extra fields.
Result and offer deadlines cannot exceed the original command deadline. Offer
output, result output, acceptance, durable checkpoint, save and whole-run completion
remain separate events. An earlier native offer output cannot authorize acceptance
after an unresolved wire attempt has retained a different offer envelope.

Python and C# strict codecs match these fields and reject non-ready states, missing
or aliased IDs/hashes, extra authority, wrong policy/run/request and expired results.
The PC controller permits an explicit offer request only for its exact known
snapshot-ready source run. It retains the received immutable offer but cannot
accept/resume it until a result names that exact offer ID and full manifest hash.
Metadata arriving without the offer cannot complete the command. Cancellation,
changed native policy/binding or outstanding commands prevent acceptance. Pending
offers cannot be replaced by retry metadata. Existing unsolicited native-only
receive admission remains separate when no source run is held.

Evidence so far: eleven Android source-host/Robolectric cases pass (parser 7,
bounded attempt 3, actual Gallery/runtime encrypted lifecycle 1); Python source
codec 43, source-controller 22 and native receive/resume 21 cases pass, including
targeted final fixture-clock/admission and changed-source-policy checks. C# source-host core
source-codec group passes 1/1 after compilation. The initial C# invocation passed
a build flag to the application filter and ran no tests; invoking the already-built
DLL with the exact group filter then passed. These are not physical Android or
installed Windows receiver/DPAPI, full synchronization or release acceptance.
Production readiness and discovery 21 remain OFF. The actual Android Gallery
lifecycle case also passes after adding post-source-read acceptance attempt
revalidation, replacing that case's earlier evidence rather than counting it twice.

One additional actual encrypted socketpair case passes: authenticated native
session → dedicated control echo/receive consent → source status/discovery/run/
offer_run commands over directional AEAD → actual offer retained with early
acceptance denied → exact encrypted result correlation → native acceptance/chunk
request/chunk stage/readback/checkpoint → explicit publication/protected saved
projection → transport end/native descriptor cleanup. The phone source metadata
and bytes here are a bounded fixture, not an installed Android Gallery/OS grant
or physical synchronization test. This adds one distinct case (87 affected Python
cases including the previous codec/controller/receive evidence), not five repeats
of the pre-existing crypto modes. It neither retires quota nor commits a baseline.

### Current desktop target observation for conflict planning

The Linux native receiver now reads a saved photo's current destination bytes
through original-root/parent descriptor witnesses and a freshly authenticated
local save receipt. The protected index is re-read after native target I/O; a
constructed UI/remote receipt cannot enter the receiver API. Historical save and
current file presence/content remain distinct. An unchanged original inode with
new bytes is a managed local edit, and the existing phone→PC planner preserves
it when the phone content is unchanged. Equal bytes in a replacement inode do
not adopt that file as managed. Symlinks, FIFOs, unsafe permissions, replaced
parents, oversized files and observed read races produce no usable content
witness. A missing file/album returns unconfirmed missing, never deleted.

The observation is read-only and grants no mutation/CAS authority, accepted
baseline, tombstone, receipt update, source READ renewal or quota retirement. Native
root/consent revocation is propagated, not disguised as valid conflict metadata.
The actual desktop connection owns this operation on its existing native I/O lane;
close revokes immediately but holds descriptors/resources until the read ends.
The targeted joined run passes 64 Python cases (new target observations plus
affected saved-receipt and desktop receive cases); a further actual blocked-read
close case passes, for 65 distinct affected cases. No Android, Windows native
receiver or installed GUI support is inferred from this Linux evidence.

### Optional video scope (Refs #335, integration not released)

The user additionally requires an explicit, initially-OFF “Also synchronize videos”
choice and a destination independent from photos: native Videos/My Videos →
`<phone name>-Videos`, or an explicitly chosen native folder. The phone name has
priority, never the account/user name; a user name may only be a fallback when no
usable phone name is available. Existing custom targets are never renamed.

Linux native folder choice now has a separate video controller/choice type and
uses GLib DIRECTORY_VIDEOS, not Pictures or a localized/home guess. Photo and video
actions, owner checks and tokens remain independent; a video choice cannot enter
the photo destination field or vice versa. Windows read-only path projection uses
SpecialFolder.MyVideos and the same safe phone-name-first component policy. These
projections alone do not authorize target writes, media reads or synchronization.

The existing-key protected desktop policy has an optional video subrecord. Absent
and existing legacy photo records remain video-OFF without passive migration or
rewriting. Video opt-in requires an exact own native video destination choice (or
its still-valid previously selected witness), explicit Boolean setting, protected
CAS and durable encrypted readback. Selecting a folder alone stays OFF. Ordinary
photo changes preserve independent video metadata. Main disable or re-pairing
does not silently renew the video scope; re-pairing preserves paths but resets video
selection unless explicitly opted in again. Missing video folders can still be
disabled without losing their witnesses. No Android video permission, source
handler, automatic worker, capability advertisement or frontend switch is enabled
by these preparations; unsupported advanced controls stay absent.

The targeted source-host evidence is 38 Python native destination cases (including
unchanged photo behavior and phone-name priority/fallback), 43 protected settings
cases (the re-pairing method subsequently rechecked after adding explicit video
consent fencing), and the Windows path-projection core group 1/1 after a bounded
build with zero warnings/errors. These are not a visible supported video switch,
Android video permission/provider, physical video transfer or native Windows
chooser/receiver acceptance. Those concrete #335 integration steps remain open.

The user's following clarification (#336) keeps animations such as GIF in the
photo domain, not the video destination, with an optional animations subfolder
beneath the chosen photo root. Existing files must not be silently moved/renamed.
The German/English Notes package descriptions now explicitly label video sync and
the animations subfolder as development-only, not available features. The F-Droid
documentation requires independent purpose/manifest/actual permission-path/native
checks before enabling video reads; existing image permissions do not become video
consent. Six source metadata checks pass with the unchanged package text limits.
No permission, APK, submission, scanner or F-Droid acceptance is implied by this
text correction; native animation routing and supported video activation remain
unimplemented behind the existing closed production gates.

### Native Android media-domain isolation (Refs #335, #336)

The native Gallery adapter now distinguishes IMAGE/VIDEO requests, access
observations, full/selected coverage, MediaStore collections, MIME predicates,
album selectors and source lease identity. Existing policy/workflow construction
still defaults to images; a photo-only or absent native request cannot query video
collections. READ_MEDIA_IMAGES never grants video reads. Legacy Android's broader
storage permission does not bypass the separate native video request. Selected
video access stays limited and invalidates an older full-read lease when changed.

Video scope uses its own source-key prefix/access stamp, read-only PFD validation,
generation/member checks and actual protected frozen snapshot/index lifecycle.
Image source keys/stamps retain their previous representation. Both inventory and
content reads reject cross-domain URIs/MIME and stale native scope. The private
Gallery origin mapping validates the matching media collection; raw IDs remain
private and no deletion/mutation identity is granted. Existing bounded file and
whole-inventory limits remain unchanged; oversized video inventories fail closed,
not as a silently successful subset.

Forty-five affected Android source-host/Robolectric cases pass, followed by two
additional cases (47 distinct): actual GIF PFD stays photo-side with no video
permission, and Android 14 selected-video visibility cannot revive full access.
The GIF case proves media-domain placement, not animation-frame detection. The
video provider bytes are a fixture, not a physical camera recording/codec or
Android OS permission-dialog acceptance. No production native video-policy path,
desktop video command, video permission request/manifest addition, video capability,
automatic worker, UI readiness or package release is enabled by this adapter unit.

The protected desktop photo policy also has an optional, initially-OFF
`separate_animations` selection. Legacy/absent records keep their exact previous
shape and bytes until an explicit native update. CAS/encrypted readback preserves
independent video settings and both destinations. A settings change creates no
animations folder, moves no old GIF and grants no write/read/transfer authority;
re-pairing does not silently renew the routing choice. Fifty-eight affected Python
settings cases pass (animation 15, video 18, existing photo 25). Native animation
recognition and immutable per-file destination routing remain required before
exposing or executing this option.

The native Android image snapshot now offers byte-bound GIF container inspection:
first verify the full manifest SHA-256 through bounded plaintext chunks, then
inspect bounded GIF records without bitmap/LZW decompression. Recognized single-
image containers are still; recognized multiple-image containers are animated.
Malformed/truncated/unsupported or over-limit input stays unknown, not video.
Extensions/filenames are not evidence. Returned plaintext chunks are cleared.
This is container inspection, not full codec validation or a parser for every
animated format. The result binds the manifest/file/content hash and grants no
target, mutation, baseline or receipt authority.

Only a live protected native image source can expose that observation. Native
source/index guards surround the actual reads; video leases are rejected and
classification never reopens the live media provider after freezing. Eight
targeted Android cases pass (six container/hash/chunk tests plus actual protected
image snapshot and video-scope rejection cases). The video case replaces its
earlier evidence rather than being counted again. This does not yet expose a
desktop animation flag as trusted provenance or change immutable destination
mapping/publication. APNG/WebP recognition and real animations-folder execution
still require their own integration/acceptance.

### Optional real-recording separation (Refs #337)

The user requests an initially-OFF recording separation selection for both photo
and video roots, with the proposed `Eigene Aufnahmen` child folder. Its optional
protected Boolean now follows the same exact native action/CAS/encrypted readback,
legacy-no-migration and re-pairing fences. It does not enable videos or overwrite
either destination/animation selection. Seventy-three affected Python settings
cases pass (capture 15, animation 15, video 18, photo 25); option updates alone
create no folder and move no existing file.

The user's subsequent clarification supersedes the earlier own-phone-only
interpretation: distinguish real photos/video recordings from memes, joke images
and graphics, regardless of which phone/camera captured them. Received real
recordings and captures from other cameras must not be excluded merely because of
origin. The internal persisted name `separate_own_recordings` remains a routing
choice only, not an own-camera restriction or provenance claim. Existing paired
own-device transport security is independent of the pictured media's capture origin.

Source folder, filename and EXIF camera model alone do not reliably distinguish
photographic content from memes/graphics. No semantic classifier or hidden cloud
image upload is implemented by this setting. Local classification with truthful
limits, immutable per-file mappings, interaction with animation routing and real
source/target acceptance remain open, so the prepared option is not exposed as an
available supported feature. Existing files remain unmoved and unrenamed.

### Opaque per-file media pages (Refs #330, #336)

Native `media_page` source requests accept exactly format/operation, saved policy
version, the original held native run UUID and an integer cursor. The phone checks
ended source I/O, noncanceled native run, live protected snapshot/read scope and
actual dedicated configuration authority. Pages contain at most eight opaque
file/photo IDs, image/animation/video/unknown-image labels, hashed stable media
namespace, insertion-witness metadata and the full immutable manifest fingerprint.
No native row IDs, provider URIs, source paths, capture-device ownership assertion
or source/target mutation grant is exposed. Image animation labels use the actual
protected-byte observation, not an extension or supplied flag.

Each run retains at most 128 exact bounded metadata command attempts, without
eviction on lost output. Same request-ID retries must preserve the entire canonical
command digest and original wall/monotonic deadlines. Observed clock rollback
fences the run's media attempts; expired attempts cannot be refreshed by retry.
The native command callback runs around protected reads and actual result output.
No scan, provider content reopen, new transfer worker or quota release is implied.

Python/C# strict immutable decoders enforce exact header/page/member shapes,
original policy/run/request/cursor, bounded entries, media-domain labels, no native
ID/path/permission claims, and unique opaque IDs. Whole-page correlation requires
every ordered original manifest member, unchanged namespace/type and full hash;
partial, repeated/out-of-order or mismatched pages never form a complete projection.
This remains metadata, not native ownership, READ, write, saved receipt or baseline.

Sixteen targeted Android cases pass (parser 9, bounded attempt 4, native protected
image/video/runtime encrypted page output 3). Python codec evidence is 88 distinct
cases including the old source codec tests and a new shared request golden;
the Windows source-codec core group passes 1/1 after a bounded zero-warning/error
build. New request golden: 358 canonical bytes, SHA-256
`52f27a005d191e20768d1c7254e564e125858ec51d964dfed9621d0045a20a7e`.
Existing configure/acceptance golden bytes are unchanged. The PC controller has
not yet joined these pages to admission/routing; production gates/visibility stay
closed. This is no physical synchronization or native Windows receiver acceptance.

The PC native owner now joins `media_page` commands/results to its exact native
receiver ticket, held snapshot-ready run, policy and returned page cursor. Pages
remain immutable and are fenced against changed namespace/type/insertion metadata,
counts, cross-page duplicate file/photo IDs and extended original deadlines. A
real full offer must match every page/member/hash before the owner records media
manifest correlation; metadata alone creates no reservation, target or data grant.
Partial pages cannot request an offer, and missing/unready/unsolicited results stay
inside the reserved namespace rather than entering personal actors/queues.

Sixty-three affected Python cases pass (new media-owner 15, existing source-owner
22, native receiver 23, three additional default-OFF/reserved-namespace cases).
This step deliberately does not silently execute selected but unjoined animation,
video or real-recording routing as an ordinary photo receive. Those options remain
unexposed/unavailable until native immutable destination and persistent historical
mapping/reconciliation are joined. Legacy limited photo admission remains separate.

The user's later #337 migration requirements are symmetric: enabling recording
separation asks whether existing files should be sorted; disabling asks whether
they should be merged back. Confirmed operations must safely move preserved files
and durably update their original associations, not delete and re-download/copy.
Declining leaves individual existing locations intact. Either path must prevent
later sync from creating another copy merely because a checkbox changed. No file
or edited/conflicting version may be discarded; only an empty, verified special
directory may be removed. Persistent mappings and restart-safe migration journals
are prerequisites, not an inference from current settings. These concrete migration
paths are not implemented by the prepared Boolean.

### Media direction preference (Refs #338)

Protected media preferences now retain an optional direction independently of the
manual/automatic schedule. Absent and legacy records mean `phone_to_desktop`;
their original wire shape is preserved without a passive migration. Explicit
`bidirectional` selection uses the existing native action/CAS/encrypted readback,
but is not a reverse write grant or deletion consent. Re-pairing does not renew
the old bidirectional choice. Both native file grants stay OFF for this currently
unsupported mode, rather than silently performing half of the requested sync.
The coordinator also rejects unavailable reverse handlers before offer admission.

The requested eventual UI is a direction dropdown like Notes, default caption
“Nur den Bestand auf dem Handy abgleichen”, with a separate schedule dropdown
(initially manual). Do not reuse the Notes-specific English gettext message
“Only the Notes collection” for media. No direction control is exposed until the
native feature availability and safe reverse handlers genuinely support it.

Evidence: 16 new direction cases and 73 existing protected settings cases passed.
The first joined run additionally exposed a test-fixture remote-grant equivocation:
it changed send consent at the same revision. The fixture now explicitly checks
local receive state without changing the original remote grant. Three affected
native negotiation/admission cases then passed, including the corrected OFF clamp.
This is not full-sync, GUI or physical-phone acceptance. Readiness stays OFF.

### Protected historical photo mapping index (Refs #337)

A separate existing-key SQLite/AEAD store now retains opaque source association →
original saved root/path/inode/parent witnesses and the actual protected local save
receipt/manifest/accepted-context hashes. It reuses the verified native descriptor,
locking, close and protection lifecycle under a distinct store/protection domain;
photo preferences remain separate. Constructor/passive absent lookup creates
nothing. A mapping is historical metadata, not current presence, a saved receipt,
READ/write/delete authority, accepted baseline or migration completion.

Insertion requires an exact native one-shot action, current native owned receiver,
matching peer/local identities, the complete freshly read protected save-receipt
set and exact whole-manifest media-page correlation. Owner digest authenticates all
row ciphertexts; original version CAS and durable encrypted readback are required.
Identical original-receipt retry is idempotent; a different mapping for a known
association requires reconciliation, never silently overwrites its original path.
No move/delete/update API exists in this index. Checkbox changes and later PC
edits/deletions do not erase historical associations or authorize file recreation.

Seventeen native filesystem/receiver mapping cases pass, plus 73 affected protected
settings cases after the minimal shared initial-owner/page-limit hooks. Coverage
includes incomplete receipts, action/CAS fences, encrypted reopen/idempotency,
corruption/unknown entries preserved, observed owner rollback, re-pairing without
normalizing old ownership, lost post-commit sync recovery, capacity without partial
rows and descriptor ownership through actual blocked I/O end. This is Linux
source-host evidence, not installed GUI/power-loss/Windows receiver acceptance.

Coordinator pre-admission lookup/post-save commit is still unjoined. Before release,
missing mapping metadata after restart must not be mistaken for first use: protected
expected-store witnesses and per-job media/history recovery anchors are still needed.
Whole consistent private-backup rollback without a trusted external monotonic
anchor is not claimed prevented by the in-process revision fence. These open recovery
and migration requirements keep production readiness, UI and automatic runs OFF.

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
