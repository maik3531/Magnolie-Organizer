# Dedicated own-peer file controls (integration in #330)

### Independent incoming configuration bootstrap (Refs #338; receive default closed)

#### Explicit local Android receive consent (Refs #338; not runtime enablement)

Android has a separate foreground positive-button selection for receiving photos
or videos from the current own PC. It requires the current document instance,
unchanged successfully saved/unlocked book and resumed native activity. Cancel,
pause, expiry, book/profile change or changed incoming configurer retires the
selection. It is one-use consent for protected policy CAS on the serialized IO
lane, not Android OS permission or authority to insert/publish a MediaStore row.

Protected policy format 5 retains independent photo/video receive choices and
their epoch/revision alongside existing source/video choices. Receive changes
advance the common file-grant revision; source/video configuration preserves
these choices and re-pairing cannot inherit them. Protected membership rejects
receive-policy downgrade and changes without a permission revision. Local
decrease requires a current saved book but no online PC; absent settings remain
absent. Interrupted publication or exhausted counters hold the current owner
without pretending a stored positive choice was successfully switched off.

The native grant projection additionally requires explicitly supplied real
receive-handler readiness, default false. Stored local consent alone cannot
activate existing source-only factories. Even a tested positive consent change
needs fresh actual data-control agreement. No receive dispatcher, MediaStore
publication, Saved receipt, bidirectional UI or capability is enabled here.
The new question is translated in all 20 catalogs without changing existing
resources. Robolectric dialog/control/protected-policy tests are not physical
Android provider/network/package acceptance.

#### Native incoming pending-row journal (Refs #338; still no data receiver)

The native incoming row owner separately checks current incoming file-control
agreement, exact peer/pairing ownership, saved book, protected per-kind local
consent and the same matched two-way intent token. It has a bounded native
lifetime and retires permanently on observed turnover. Index guards check only
the local book/token/retirement witness; full control/peer/policy checks occur
outside index locks. Existing source-only factories remain closed to receiving.

New incoming lineage is sealed into bounded existing native index metadata and
its exact membership aggregate, without changing the schema, key, source-job
quota or previous records. Reads create nothing. A record binds original
manifest/source/transfer/file identities, authenticated binding, pairing, media
kind, MIME, size/hash and display name. It progresses through planned, inserting,
inserted, copying, copy_verified, publishing and published; none is a network
Saved receipt or file-write permission. Lifetime
capacity is 4096 records; exhaustion holds rather than deleting old lineage.

Before a new MediaStore insertion, the inserting intent is durable. Actual
native insertion creates only an app-owned pending row on mounted primary
external storage, in Pictures/Magnolie or Movies/Magnolie. Typed single-row
readback pins exact URI, provider namespace, member/date/generation, app owner,
path, MIME, display name and empty/pending/untrashed state before journaling it.
An inserted record can only re-inspect that exact unchanged row. An uncertain
inserting record never causes another insertion, name-based adoption, overwrite
or deletion. Missing-volume preflight stays retryable before insertion admission.

The original-byte copy lane now seals copying intent before opening the exact
new empty pending row for its first and only write. It enforces immutable
manifest/chunk size bounds, computes the original SHA-256, syncs the descriptor
and freshly reads back exact original bytes without format conversion. Owned
chunk/readback buffers are cleared. Row identity, namespace, owner, metadata and
size are checked again before recording copy_verified in the protected journal.

After any interruption a copying head is never reopened for write. An explicitly
reselected complete original can only advance after fresh read-only hash/row
verification; partial/corrupt copies hold without rewriting them. Even a stored
copy_verified head is freshly verified rather than trusted as cached success.
No copying state can mark a row visible, remove data or produce Saved output.

The separate native media-inspection primitive admits image MIME and bounded
dimensions only from Android's bounds-only decoder, without pixel allocation.
Video inspection requires matching native container MIME, video metadata and
an actual video track among at most 16 tracks. It uses a read-only regular held
descriptor with exact size and stable identity/timestamps; missing/unsupported
metadata, native owner withdrawal or a claimed MIME mismatch holds admission.
Its observation is neither publication permission nor a Saved receipt.
Image tests use the native decoder on synthetic PNG/JPEG files; video parser
metadata/tracks and descriptor stat adaptation are explicitly test fixtures,
not physical Android syscall or MP4 parser acceptance.

The native publisher now joins fresh original-byte SHA verification, this native
media probe and a second original-byte SHA verification with stable row metadata.
It journals publishing before a conditional pending-to-visible update, guarded
by exact id/date/generations/app owner/path/MIME/name/size and untrashed state.
Fresh visible-row, original-byte and media checks must succeed before committing
the published native-row association. No original is replaced, removed or linked.

A lost update reply or owner withdrawal after visibility changes leaves publishing
without a success assertion. A fresh permitted retry verifies that same row
read-only and does not insert, copy or update visibility a second time. Published
history is also rechecked; it is not renewed consent or automatic network Saved.
These tests include actual native PNG parsing with fixture PFD bytes and a
simulated conditional provider, not physical Android provider acceptance.

#### Explicit incoming secure-transfer worker lane (Refs #338; runtime still closed)

An explicitly prepared native incoming transfer now binds the actual offer,
manifest and exact authenticated secure channel to current native receive
ownership. It seals original acceptance intent and per-file planned lineage
before sending accept; historical acceptance does not prove actual output or
renew permission. Original acceptance metadata is bounded to 128 retained
records in existing exact index membership, without changing source-job quota.

Only successful actual encrypted acceptance output admits chunk requests.
There is one outstanding correlated request and at most one owned bounded chunk.
Actual secure request-send completion gates even a response arriving during the
send. Responses must match request, transfer, manifest, acceptance, permission,
destination, file, chunk, exact canonical base64 length/hash and original expiry.
Native close retires ownership, clears bytes and wakes outstanding waits without
closing the shared transport socket. No index lock spans network IO or waiting.

The caller-owned IO lane copies and publishes each exact member through the
native checks above. Only the complete ordered manifest with durable published
associations can produce Saved, using their protected native fingerprints as
receipt hashes and the original acceptance/binding. ActualSavedOutput is marked
only after the synchronous encrypted write returns and ownership remains current.
Failed output preserves published originals but returns no completion. This is
not peer acknowledgement, quota/END retirement or bilateral sync completion.

The transfer itself starts no thread. The explicit native incoming runtime
factory now joins a single caller-started receiver worker, actual control and
chunk dispatch, cancellation and cleanup. Existing source-only factories retain
receive-handler readiness false. Source, local recovery and incoming IO share
one exact process owner; requesting cancellation does not release that owner.
New positive source work holds while receiving, while control observations and
chunk responses remain independent of the whole worker operation lock. Actual
control withdrawal cancels pending receiving; native cleanup retains the index
until both source and receiver IO have really ended, including a blocked provider.
Video additionally requires actual joined video handlers and native peer video
capability, never image fallback. The runtime seam is not a production Werk/UI
dispatcher rollout or a substitute for local foreground consent.

The native runtime also joins foreground receive-configuration authority to the
real positive dialog's protected policy transaction. Both ticket preparation and
positive policy CAS use the serialized IO lane and exact process media admission;
another source/recovery job starting while the dialog is open holds the grant.
The freshly checked control authority is frozen only during that transaction;
index guards use revocable local ticket/peer snapshots, never transport monitors.
UI cancellation cannot finish another ticket. Wrong-thread grant rejection occurs
before consuming approval, and completed/failed attempts close their selection.
Actual data still requires a new control ACK/echo after consent changes. Explicit
saved-book decrease works without an online PC and preserves source choices and
epoch; uncertain/exhausted updates hold readiness without inventing stored OFF.

Native incoming owners now enforce the exact matched collection mode before any
acceptance, chunk request or row reservation. `phone_inventory` requires an
original reference for every incoming manifest member, matched against protected
native known-phone history for the same phone, PC identity/key and media kind.
Missing, forged, foreign and duplicate original references hold. Explicit
`entire_collection` admits unknown files without inventing history; supplied
references still must be valid. Historical pairing proof is not current consent:
fresh same-key re-pair consent may correlate retained original history, but does
not inherit old rights. Changed PC bytes remain independently verified new-file
input, not overwrite/deletion authority. Arbitrary-image fixtures explicitly
choose the entire collection. Forty-three targeted native history/row/transfer/
runtime cases pass; no physical acceptance is implied.

New native incoming acceptances use protected format 2 with an exact ordered
scope fingerprint. New publication journals retain that fingerprint, collection
mode and original known-phone ID (or explicit null for unknown entire-collection
input) through all publication states. The protected writer verifies referenced
native history against the actual phone, PC key and media kind. The Saved receipt
hash includes this lineage and the new row witness. No old Gallery URI is reused.
Legacy format-1 journals remain readable as history, without invented scope or
references. Publication identity stays stable across formats: attempting to adopt
a legacy row or change its scope holds on immutable-field comparison, rather than
creating another row. Forty-four targeted journal/row/transfer/runtime cases pass;
the original-reference state-transition fixture simulates row observations and
does not constitute physical Android copy/publication acceptance.

Linux PC original references can now be projected from an exact authenticated
Saved mapping version or a completed protected local restoration journal.
Prepared restorations, invented operations, wrong protected versions and revoked
native local owners hold. This projection opens no media file and remains purely
historical even when the current target is edited or missing. It is not a source
READ grant, current-presence assertion or proof that the phone retained matching
native history. Seven targeted native mapping/restore groups pass. Actual PC
positive-send consent, owned-file validation, source cache and upload remain
separate requirements; no source owner is manufactured from a restored mapping.

The Linux protected policy now separately stores explicit native photo/video
sending choices with their own pairing witness. Native action/CAS, expiry,
replay and strict codec checks apply. Source choice updates preserve receiving
destinations, choices and their old pairing binding; a fresh sending choice after
re-pair cannot revive receiving rights. Receiving/behavior updates preserve the
stored source choices. Permission changes require a new control revision/echo;
absent OFF is inert. Thirty-seven distinct policy/mapping/restore cases pass.
These are protected local choices only: native SEND remains false until actual
source ownership, shared intent, cache, upload and production consent UI join.

Linux mapped-source inspection now requires an explicit native action, separate
current-pair sending consent, exact protected policy and actual matched two-way
media intent. The existing saved-book witness and exclusive OS media-I/O lane
remain held until real reads end, including cancellation during a blocked read.
Original root/parent/file identities, owner, regular type, single link and full
content signatures are checked around bounded original-byte reads. Replacement
files, symlinks and hardlinks hold; same-inode PC edits can yield a new content
hash while retaining the original historical reference. Seven targeted native
source cases pass. The returned observation grants no future READ, source-cache,
Saved, complete-inventory or deletion authority. No sender backend is enabled.

The Linux source owner can now build one bounded private encrypted cache while
the same actual source FD, book/action/consent/intent guards and OS lane remain
held. Durable planned and copying records precede payload; original chunks are
synced, authenticated and independently reread before the sealed manifest.
Inode-bound AEAD, ordered cipher membership and original-byte hashes protect
the snapshot without hardlinks or transcoding. Private source stages are
recursively excluded. Existing stages always hold, including completed ones:
there is no overwrite, restart adoption, automatic cleanup or retirement API.
Nine targeted cache/ownership cases pass. The frozen metadata grants no future
cache READ, sender, Saved or deletion authority.

Private source-cache format 2 additionally binds the original actual saved-book
witness. Local cache READ now requires the actual in-process completed source
preparation, its original live action/consent/policy/intent and a new exclusive
OS lease for that exact book. A copied frozen object, another source owner or a
sealed filename cannot recreate permission. Read-only descriptor, inode-bound
AEAD, manifest/member/layout checks apply before and throughout bounded reads;
the owner thread revalidates all members before successful lease completion.
Book/rights withdrawal or read failure retires that preparation without deleting
its bytes. Cancellation retains descriptors and OS admission until actual reads
end. Seven reader and five affected cache cases pass. This local READ lease is
not a network send grant, restart adoption or source-job retirement. A durable
native source-job and live transfer-control lifecycle remain required before
any outbound offer or payload.

The Linux cache writer now persists a separate protected native source-job
record in the existing phone database: a random nonce binds durable intent to
`cache_planned` before payload, and an exact-version transactional compare and
swap advances to `cache_ready` only after sealed-cache readback. The ready
record binds database/root/parent ownership, original book, policy/pairing,
manifest, proof and original references. Creation/advance requires the actual
live writer; lookup is historical and grants neither READ nor Saved status.
Local prepared-cache reads additionally require the exact protected ready
cipher version and native nonce before and throughout access. Missing, changed
or corrupt records hold without reconstruction or repair. Eight new journal
cases, seven affected reader cases and five affected cache cases pass. There
is still no restart adoption, production source-control composition, retirement
or general sender readiness. Existing complete/partial stages remain held.

A separate private Linux source-only composition now implements the first
native wire lifecycle (#400); it is not installed in the normal desktop
connection or production dispatcher. Only the exact in-process prepared owner,
original positive sending consent/shared intent and original-book/cache lease
can derive its local source grant. Its actual encrypted control output and peer
echo precede an offer. A separate protected exchange journal persists offer
intent before secure output and records successful output only afterwards.
The matching authenticated acceptance binds offer/transfer/manifest, current
permission epoch and receiver destination token before chunk requests can read.
Each requested response is journaled before output and completed only after
the actual encrypted write drains and all current native guards pass. Incoming
replies serialize behind actual output; they cannot turn an unfinished write
into success. Partner Saved requires all chunks' actual output and exact
acceptance correlation, and remains only a remote assertion: never a native PC
Saved receipt, backup proof or retirement permit. Interrupted/missing attempts
hold without adoption or repair. Seventeen encrypted socket-pair cases cover
positive and multichunk output, immediate replies, foreign/mismatched input,
withdrawal, missing history, failed output and cancellation with retained OS
ownership. Existing production SEND, capability 23 and runtime-ready gates stay
closed. Outbound-version backup/pinning, retirement/restart, original-reference
and MIME dispatcher joins, platform parity and physical acceptance remain
required before production composition.

Prepared Linux PC versions now also have a native local backup path (#401),
separate from phone Saved mappings and partner Saved assertions. The exact
in-process preparation retains its authenticated original mapping only as
history; the backup records its own source manifest/job/nonce/ready/proof/book
provenance without rewriting that mapping's old size/hash/receipt. The existing
owned catalog, hash/size-addressed objects, native default/alternative storage
and immutable version references are reused without schema migration. Durable
source-version intent precedes a registered new inode and payload; full readonly
reopen/hash verification precedes completed-version publication. Identical bytes
share an existing verified object, including genuine phone-origin backups.
Completed and independently verified interrupted source copies can restore
offline into new empty files, without a live peer, source file or source cache.
Partial copies cannot become recovery selections. Source-version references
pin shared objects against compression/retirement pending a separate lifecycle.
Seven new source-backup and seven affected catalog/preparation/reader/sender
cases pass. The catalog explicitly refuses to project a source version as a
Saved mapping. Source-version recovery UI/publication lineage, source-slot
retirement/restart/global catalog and platform/production joins are still open;
no production source or package readiness is implied.

The existing Linux native recovery API and no-replace restore owner now also
publish selected source versions (#402). Their optional protected source-version
snapshot remains separate from old Saved-only events; the original mapping hash
and bytes stay historical, while restored size/hash come from the exact current
source manifest. Journal validation binds the full source snapshot to the
selected protected version hash, prepared inode and final no-replace name.
Reopening/resuming preserves that exact lineage and inode. Only a completed
restore exports the original phone reference; history remains no READ/Saved
grant. Six new and nine affected restore/recovery/source-backup cases pass,
including offline recovery, collisions and correctly resealed but semantically
changed history. This is API/fixture evidence, not physical desktop-dialog
acceptance. Native source admission for the newly restored inode and the
remaining global catalog/retirement, platform and production joins are pending.

Fresh inspection of a completed restored inode is now available through the
actual native restore owner (#403), not by changing an old Saved mapping. Its
record digest selects the exact completed protected event and its new file and
parent identity. The restore journal must have the exact stable native
PC/phone/media scope derived from the current authenticated preferences; merely
sharing a local key/root is insufficient. Original positive source consent,
actual shared two-way agreement, explicit action and live saved-book lease
remain mandatory before/during descriptor reads. Candidate observations grant
no READ or Saved rights. Ten restored-source and five affected original-source/
cache/reader/sender cases pass. This admits inspection only, not restored-source
cache freezing, new outbound backup provenance or a production send path.

The same completed-restore lease can now explicitly freeze restored source
bytes (#404). Intent and actual in-process preparation preserve the distinct
new destination/path/inode/parent/event identity, while retaining the original
Saved mapping unchanged as phone-reference history. Source backup provenance
optionally binds that bounded restored-source identity instead of embedding
recursive full restore chains; its selected data owner is the actual restored
destination, never the original Saved destination. Existing owned objects,
separate retained catalogs, independent readback and source pins still apply.
Five new and seven affected native cases cover restore/freeze/read/backup/
offline-recovery, actual private encrypted output, wrong target ownership,
stale selection and interrupted cache HOLD. Existing complete/partial source
stages still cannot be overwritten, adopted, deleted or reused. Durable global
source membership/retirement/restart and remaining production/platform/physical
acceptance are still required; no general sender readiness is enabled.

Native incoming journals also fence stable original-transfer identity across
renewed permission/pairing bindings: the same static device keys and source/
transfer/file IDs cannot obtain a second publication ID or mutate another row.
Both pending and published historical collisions hold before reservation and
provider insertion; changed content under reused IDs also holds. Existing exact
same-binding retries and explicitly new source/transfer IDs remain distinct.
History grants no old-row adoption or renewed write authority. The reproduced
second-insert attempt after real revoke/regrant is covered by 47 passing native
journal/row/transfer/runtime cases (#399). Read-only recovery of an older
published row across renewed bindings remains separate; no physical Android or
complete production acceptance is implied.

Production foreground/Werk/UI wiring, returned-media Gallery classification/new
phone source identity and PC reference transport/source ownership/upload, plus full
native acceptance remain required. Tests use real protected index/control/consent paths with a
Robolectric MediaStore provider, not physical Android provider/package proof.
They encrypt and decrypt actual transfer frames; they are not physical network
or Android video-parser acceptance. No capability or production receiver is
enabled from this helper alone.

The native Android control session has a separate incoming-configuration ticket
and authority type. It requires the current authenticated own-PC relationship,
an actual native pairing epoch, the PC's positively acknowledged send-files
consent and an explicit native receive-handler readiness callback. That callback
defaults to false; existing source-only runtime construction cannot bootstrap
incoming configuration merely because its source handlers work.

Source and incoming tickets cannot be exchanged. The incoming authority uses an
independent domain-bound session/peer/permission identity, has a short native
lifetime and retires on observed clock rollback, handler loss/failure, grant or
relationship turnover. Returning to the same visible settings does not revive
the old ticket. Finishing/closing the original ticket remains exact and bounded.

This type only permits a future explicit native local-consent transaction. It
does not enable receive-files, request Android permissions, accept an offer,
write a Gallery row or manufacture a local archive-restoration session. Even an
actual local grant change must complete the ordinary fresh data-control ACK/echo
before a transfer binding exists. Existing source configuration and wire shapes
are unchanged; no incoming handler, bidirectional UI or capability is enabled by
this step. Native local write consent, protected MediaStore receive/publication,
PC source ownership/inventory/upload and both-direction safeguards remain required.

### Supported desktop video UI and native destination choice (Refs #330, #335)

The existing Linux native media frontend now exposes **Also synchronize videos**
only inside Notes phone connection → Advanced functions and only with current
native `video_supported` readiness. It starts OFF, retains separate photo/video
album selections, uses only native destination/status metadata, blocks overlapping
positive actions, and still permits explicit OFF while stopping an active worker.
No pairing/status/rendering operation enables videos, requests permission or starts
a transfer. KDE Connect and Notes content-sync grants remain separate.

The destination picker is an explicit native GTK operation while video scope is
OFF. JavaScript can request the picker with peer/fingerprint only, never submit a
path. The native callback uses a separate private local IPC method; the public
sync-action schema rejects both destination actions and path injection. The native
owner then verifies current pairing/capability, protected preference CAS and an
actual native directory choice. First custom selection stays OFF and does not
change photo grants or destinations. Cancel/lock writes nothing. Re-selecting the
exact original keeps its token; another historical root remains HOLD pending the
explicit reassociation/journal flow, never an implicit move or overwrite.

The two new labels are translated in all nineteen existing Linux catalogs and
validated with the canonical catalog generator. Tests cover English/German UI,
no rendering side effects, typed actions without paths, separate selections,
escaping native album names, busy/OFF/capability boundaries, and actual GTK callback
→ private IPC → protected choice/real session/worker bytes. They do not replace
installed native chooser or physical Notes acceptance.

Windows still omits these media controls: its current source has codec/control,
resume-ledger, plan/schedule and native folder-projection primitives, but no joined
coordinator/receiver/session/bridge path. The Linux frontend is not copied over to
pretend that native implementation exists. This remains part of #330/#335 before
claiming cross-platform completion. Production gates remain OFF.

User sequencing: finish video synchronization, then perform native installed tests
and the requested local Organizer/Notes-APK/Windows-EXE handoff using the existing
release procedure; camera/microphone and mirroring remain postponed until after
that native-test stage. A local handoff is not a public release.

### Native desktop video session (Refs #330; production gates OFF)

The existing local native action lane accepts explicit video enable/disable,
discover, permission-request and album-sync actions. It retains a saved custom
video destination or chooses the native Videos/`<phone>-Videos` default only on
explicit first enable. An already enabled/associated photo transport is required;
video actions never bootstrap absent/off photo consent. Video preference changes
do not rotate photo grants, tokens, destinations or historical jobs.

Every video discover/sync first proves CURRENT protected video consent/root and
the actual acknowledged data binding, then sends a fresh positive native video
configuration even when saved source status says ON. Metadata-only control
agreement cannot substitute for the source data grant. Enabling queries actual
coverage without prompting or downloading; permission is requested only by its
explicit typed action and the following native coverage query, not its reply,
determines availability. Construction/status inspection starts no I/O.

The session retains separate image/video album lists and refreshes the actual
single native catalog when switching media. Manual video sync and the existing
automatic mode share one native schedule/action/worker lane. Automatic mode runs
photos then enabled/available videos serially, with a fresh video handshake, and
is not enabled by a video toggle. Unsupported native video controls are omitted
using the CURRENT acknowledged capability/private gate, not cached session flags.

Disable during I/O stops the worker and waits for real drain/close/source END;
then local protected video consent closes before remote disable output. A remote
failure remains HOLD with local consent OFF, not a claimed remote OFF ACK. Jobs,
checkpoints and quota remain governed by existing receipt/END rules.

Native action/source-host proofs cover default/custom destinations, current
handshake, manual chunks/Saved/repeat with retained local edits, explicit native
permission without READ fallback, stop/disable while a chunk is outstanding,
metadata-only/no-source-data refusal, disable failure, current capability loss,
and actual sequential IMAGE/VIDEO workers under the explicit automatic mode.
The supported Linux UI is joined as above; Windows integration and installed/
physical acceptance remain unfinished. Source tests do not enable production gates
or publish packages.

### Explicit typed desktop album worker (Refs #330; production gates OFF)

The existing native album worker now accepts an explicit `media_type: video`
action under the private data gate and current video consent/root/capability.
It rejects mismatched current catalogs; no inferred type or image fallback is
allowed. Start, batched continuation, source status/cancel/END, original-job lookup
and dedicated resume retain this immutable media scope. New-member selection is
also typed and pins the current video preference revision through output/retry.
Original resume-candidate destination checks use the actual per-media root.

Actual worker tests cover two video batches through chunks/publication/Saved and
source END, repeat without download preserving a local video edit, cancellation
and original-job resume without redownloading its drained chunk, mixed known/new
membership selecting only the new video, and no photo-root writes. IMAGE workers
remain independent when video preferences are enabled but the video data gate is
off. Existing IMAGE worker tests pass. These are native desktop/source-host tests,
not an installed Android/desktop end-to-end claim.

The native session/schedule must
establish the native owner's fresh positive configuration after data ACK before
starting this worker, from the CURRENT protected video choice only. All production
gates remain OFF; adding this private worker entry never starts anything from
pairing, construction or status inspection.

### Video decrease at exhausted counters and fresh native owner (Refs #376, #377)

An exact current authenticated video-decrease command that cannot advance its
global/video revision now HOLDs the existing native policy controller before
returning `*_revision_exhausted`. Stale snapshots cannot acquire this authority;
unchanged idempotent commands remain unchanged. No counter rolls over or resets,
and protected policy, photo grants and jobs are not rewritten or released. This
owner-local HOLD is **not** a successful persisted OFF choice.

Actual protected-index/controller tests reproduce the former continuing READ,
verify the HOLD and stale/idempotent boundaries, and distinguish decrease-write
errors before and after the existing durable repair fence. A first-write failure
before that fence preserves the old enabled preference; it cannot be described as
a persisted OFF choice. Errors after the fence hold new controllers too.

Saved preference alone no longer activates VIDEO READ in a new native controller
or runtime. An explicit, successful current `configure_videos(enabled=true)` must
arm that owner with the already acknowledged native data receiver and exact video
epoch. An unchanged positive command can do this without rewriting policy, epochs,
grants or jobs. Metadata configuration before data ACK does not silently become
READ when the ACK later arrives: another current positive command is required.
An exact authenticated decrease clears the volatile activation even if its first
policy write fails. A changed receiver owner/permission scope cannot inherit it.
Photos keep their separate existing behavior.

Tests include protected-index reopen, failed first-write/new-controller HOLD,
explicit fresh rearm and two actual runtimes over the same protected storage with
separate dedicated control handshakes. This is not durable OFF persistence and
does not auto-retry or manufacture successful revocation. The still-unjoined desktop
video session/worker must send the fresh positive command only from CURRENT native
enabled video preferences after data ACK, never from old job/catalog history or a
queued command invalidated by a decrease. That integration and installed/physical
acceptance remain in #330; production gates remain OFF.

### Original desktop video resume (Refs #330, production gates OFF)

Dedicated video resume now follows the explicit original-job lookup and current
native video catalog, then correlates resumed pages/offer with the exact original
manifest and protected media association before reopening the original stage.
An ordinary source run cannot substitute for this flow, and changed source epochs
HOLD before stage reopen. Current video scope authorizes positive data operations;
history supplies neither READ nor an old-policy-epoch override.

Exact resumed status/cancel/END uses a separate configuration-only comparison of
current base controls and the original current video destination. It never becomes
a data callback or widens checkpoint authority. Saved END uses the exact native
metadata lease and protected mapping receipt, not renewed READ after withdrawal.
The local receive owner captures its resume source ID; closing/retiring its cache
is refused until the exact source END confirmation has arrived. This ordering is
also enforced for existing dedicated image resume, not merely left to the worker.

Actual native-stage tests cover original video chunks/Saved, END-before-retirement,
three withdrawal modes with real cancel/drain/checkpoint/close, saved END after
capability withdrawal, exact uncertain-END retry, explicit typed attempt abandonment
without job/cache release, and changed-epoch rejection. Existing image resume/stop
paths remain green. Public UI and installed/physical acceptance remain
separate unfinished work; all production gates remain OFF.

### Explicit original-video history lookup (Refs #330, resume data still pending)

The native original-job action may explicitly select `media_type: video` for
lookup. It requires current enabled native video status, private data readiness,
ACKed capability, local video consent and the current original video root/token.
Protected original job metadata is inspected inertly to confirm its video type;
no historical binding callback or recovered source epoch supplies READ. The
selected job/root/binding and policy version are rechecked before command output.

Lookup replies must echo video scope and the exact original manifest tuple. Local
OFF/ON or withdrawal invalidates pending positive lookup; omitted image-shaped
replies cannot be relabeled. Seven video cases and fourteen existing image lookup
cases verify no stage admission/reopen by lookup itself. The dedicated video resume
join is described above; a new ordinary run cannot substitute for that workflow.
Existing native source-epoch rejection
after video OFF/ON remains mandatory.

### Ordinary desktop video receive and owned stop (Refs #330, partial join)

The private-gated ordinary desktop video path now joins typed source ownership,
complete media/offer correlation, explicit native mapping/catalog bootstrap and
the original independent video root/token to the real encrypted receive stage.
Native publication commits video mapping/Saved evidence and emits the existing
protected Saved envelope. Cache retirement requires that actual saved evidence;
an unsaved stop keeps the original job, stage and reservation. Original video
resume through a new ordinary source run remains explicitly refused; its separate
dedicated original-owner join is described above. No video worker/session/UI or production gate is
enabled by this partial path.

After video capability, local video consent or private readiness withdrawal,
positive data operations remain closed. Stop waits for an outstanding request's
actual ordered source-cancel barrier before checkpoint/close. Only that exact
local owner, on the gate-held checkpoint/close thread, may derive current base
control authority with the current protected original video token/root. The old
accepted binding is compared, never returned as authority. The narrow checkpoint
context is removed in `finally`; another thread and ordinary READ cannot use it.
Uncertain checkpoint/close retains a failed owner and its full reservation.

Source-host tests cover actual video chunk bytes, encrypted stage, custom and
native Videos/`<Telefonname>-Videos` destinations, publication, Saved mapping,
local retirement and typed source END. Three withdrawal modes retain the exact
unsaved job after real drain/close without Saved output. Further cases verify
checkpoint-thread isolation, failure holds, independent photo reception while
video data stays OFF, and no generic video-resume fallback. A real saved-video
case performs local/source video OFF/ON metadata, then supplies a fresh typed
source epoch: known native IDs HOLD before another reservation or chunk, while
the user's PC edit/inode and original saved job remain unchanged. These are
desktop/native-sourcehost proofs, not installed Android/R8 or physical acceptance.

### Typed desktop video source owner (Refs #330, worker integration pending)

Under the still-OFF private video-data gate, the desktop source lane now joins
typed ordinary/batch starts and their media/offer/status/cancel/END commands.
Follow-up scope derives from the correlated source owner, not a filename or an
incoming token. An explicit conflicting scope is rejected before output. Active
source and receive owners must agree on media type; the local receive owner
captures its media scope independently of later source-owner retirement.

The actual offer observer resolves video through the independent current video
token/root, never the photo fallback. Positive commands recheck private readiness,
current capability and consent; exact already-owned video status/cancel/END can
finish after video capability, local consent or private readiness withdrawal
under unchanged base configuration authority. No new local READ is authorized
by these closing commands. Ordinary receive admission is described above;
original video resume and video worker/UI remain unjoined.

Source-owner tests cover typed pages/offers and mandatory storage-bootstrap
refusal before reservation, correct video binding, three withdrawal directions, conflicting
image cancellation, post-withdrawal END, pending-command gate withdrawal and
invalid scope aliases. Existing native photo receive/source and original-stage
stop/resume/Saved-END paths remain green. These desktop protocol fixtures are not
new Android/physical-device acceptance or complete video synchronization.

### Independent native desktop video binding (Refs #330, admission still closed)

The native binding resolver now accepts an explicit media scope. Video resolves
only the protected original video directory and its distinct video token under
current consent/capability witnesses, with a separate data-readiness gate default
OFF. It rechecks directory and policy after control binding. The existing photo
binding keeps its default behavior and grant epoch; no incoming filename or
historical binding selects a video root.

Seven native binding cases cover default refusal, original root/token, unchanged
photo grants, lower-level accepted-destination verification, video withdrawal,
local OFF, missing/replaced roots and withdrawal during root verification. The
23 existing actual photo receiver cases still pass. These are binding checks,
not video worker acceptance: positive source/receive paths require the private
gate, and the ordinary receiver proof is documented separately above.

### Live desktop video metadata commands (Refs #330, production gates OFF)

The actual reserved desktop lane can now issue separate `configure_videos` and
typed video discovery/catalog-page/permission attempts. Positive video commands
require current-channel ACKed availability, explicit protected local video scope
and the original native video-directory witness. Their pending command pins the
local policy version, so local off/on cannot silently resume an old command.
Unsent refused operations allocate no command ticket or output.

Negotiated status parsing checks independent video revision rollback and
same-revision mutation as well as the existing global policy witness. Dedicated
video configuration does not wait for a changed photo FileControl echo; its
successful metadata reply alone still grants no READ. Explicit video OFF can
complete after capability withdrawal with the native legacy-shaped reply.
Video catalogs cannot be used by image run selection. Original video resume and
worker/session/UI integration remain closed; ordinary receive is described above.

### Video history across renewed source epochs (Refs #330, inert guard)

Protected desktop job-history inspection now holds overlapping native video IDs
when an earlier accepted video anchor has a different source epoch. Video off/on
must not make those files look new or permit a second reservation. Version-parent
hints cannot bypass this hold. Same-epoch conflicts retain the existing reconcile
guard; unrelated IDs and the separate image namespace are unchanged.

The guard reads protected original metadata with no historical binding callback
that grants READ, no accepted-target renewal, no stage reopen and no publication.
Five native-index cases verify unchanged protected bytes/jobs and no source sends;
eleven affected image-history cases remain green. This is not yet full saved-video
worker/off-on acceptance or explicit historical reassociation; those remain open.

### Windows native metadata-command ownership (Refs #330, #335, partial join)

`NativeFileControlSession` admits one native receiver metadata command only after
the current bilateral file-control echoes agree and local receive permission is
present. The nonserializable ticket captures its remote control position and a
bounded monotonic lifetime. Foreign, overlapping, expired, withdrawn or replaced
owners cannot use it; exact cleanup remains possible after session disposal.
Source send may remain OFF for configuration metadata, or change during that
exact command. Neither a ticket nor a control-position witness is a data grant
or transport ACK: `Binding()` still requires the actual current data-policy echo.

Two native-source test groups cover bootstrap without data authority, exact
ownership, policy transition, withdrawal, clock failure/rollback/expiry and cleanup;
the existing file-control regression group also passes. The native control
transport below now connects this foundation to secure output, but receiver,
protected destinations and media UI remain unjoined. Production gates stay OFF.

The optional `DeviceFileConnectionMetadata` partial now hooks the actual Windows
metadata receive/secure-ACK path, separately from the existing `fresh*` flags.
It invalidates the affected receipt before processing; positive evidence is
recorded only after successful secure ACK output and exact current durable
capability/grant metadata, peer key and native pairing epoch checks. Failed ACKs,
rejected callbacks and superseded duplicates supply no current witness. A fresh
matching capability/grant duplicate can finish an uncertain ACK, but an older
own-device positive duplicate cannot undo withdrawal; a validated withdrawal
holds even if its ACK fails. Observed channel/key/pairing replacement permanently
revokes that connection's witness. Base marker 21 and video marker 22 remain
independent of file consent and data readiness.

Five native-source groups exercise the actual receive and encrypted writer,
including failed ACKs for all three metadata kinds, current/superseded duplicates,
video-only withdrawal, own-device replay, protected changes and replacement during
ACK output. Existing shared-control, actor-source and accepted-report-ACK tests
also pass. Unconfigured project evaluation excludes this partial with the other
`DeviceFile*.cs` implementations; absent partial hooks supply no fallback media
implementation. This remains a read-only metadata witness, not a joined transfer.

### Windows dedicated native control transport (Refs #330, #335, partial join)

`DeviceFileConnectionTransport` attaches exactly one native control owner to the
current metadata-confirmed connection. Its local grant provider is a native object
callback, not a web/wire policy. Opening requires the existing protected local
identity: the new read-only reader verifies public/private key correspondence,
never creates keys or refreshes the saved display name, and clears temporary
private key bytes after verification.

Controls use the actual encrypted writer directly, serialized with other secure
output and with native control handling. Only successful output followed by fresh
scope validation calls `MarkSent`; queue acceptance is not enough. Uncertain
output, owner/pairing/key changes or a failed identity read revoke the native
route. Disposed native sessions no longer invoke protected callbacks. Restoring
an old identity cannot revive a failed owner on the same channel.

The reserved `file_transfer.*` route cannot fall through to the generic Notes
inbox, dedupe or outbox. Only control packets are joined so far; unsupported data
holds the native route. Control envelopes require exact fields/types, bounded
size/TTL and an unexpired timestamp, without legacy expired-message grace.
Absent optional implementations simply omit the partial handlers; project
evaluation confirms all `DeviceFile*.cs` files are excluded in unconfigured builds.

Five new native-source groups exercise actual encrypted frame output/decryption,
bilateral echoes with matching native bindings, OFF handlers, no generic inbox
receipt, strict envelopes, uncertainty/withdrawal during output and protected
identity loss/restoration. Existing metadata, command-ticket, base control,
shared-control and actor-source groups also pass. The positive test grant provider
is a synthetic native fixture, **not** proof of a production receiver or protected
destination. The runtime still needs its protected preference/receiver owner,
source-command/session, staging/publication/history and UI integration before
actual photo/video availability or native installed acceptance can be claimed.

### Windows bounded native source status (Refs #330, #335, no READ)

`ReadNativeFileSourceStatusAsync` now sends an actual encrypted, correlated
`status` command using the current native receiver-command ticket. Admission
requires the dedicated bilateral echo and native local receive scope, but source
SEND may be OFF. This API has no operation selector: it cannot configure consent,
request Android READ or start a source job. The native result remains read-only
metadata and does not enable a worker, change grants or create a Saved receipt.

Exactly one command owns its request ID, captured control witness and bounded
monotonic ticket. Both output and reply check current scope; a result is accepted
only after confirmed secure output and exact request/operation/schema correlation.
The receive lane is released while awaiting the reply. Cancellation, native route
closure, actual timeout and observed metadata/control-session withdrawal retire
only the owned pending command and allow its exact ticket cleanup after disposal.
Late or unsolicited results cannot fall through to generic storage or revive it.
There is no ordinary outbox retry substituting for an original native command.

Five initial native-source groups pass for secure SEND-OFF status, correlation,
cancellation, closure and a real 60-second timeout; two further groups cover
uncertain secure output and prompt metadata/control-session withdrawal. Tests use
the actual secure writer and reply dispatcher, with synthetic native local grants.
Production UI/receiver routing and run/resume transport remain pending; explicit
configuration/catalog/permission APIs are now joined below. Unsupported data is held, not parsed as image
authority or presented as ready. Gates stay OFF.

### Windows native configuration, catalog and permission commands (Refs #330, #335)

Separate typed native APIs now send actual encrypted `configure`,
`configure_videos`, `discover`, `catalog_page` and `request_read` commands. The
status API remains status-only. Each new command uses the same current native
receiver-ticket discipline, actual secure writer/output confirmation and exact
request/op/version/media-scoped reply decoding. Only one command, including the
status API, can own a receiver ticket. No generic inbox/outbox or ACK retry is used.
The receive lane is released while awaiting a reply; close, cancellation,
metadata/control withdrawal and the bounded deadline retire the exact pending
owner. Current saved native choice, original protected root and existing actual
DPAPI key are checked around I/O; a saved enabled flag is not sufficient.

Video requires a successful positive native `configure_videos` after the current
bilateral **data** ACK, not just metadata availability or a saved/status `enabled`
flag. Activation is volatile and bound to the exact owner, saved choice/root,
source policy version, remote session and actual data-permission binding. A new
data ACK cannot inherit the old activation. Observed key loss clears activation;
returning old key bytes cannot revive a captured binding. An overlapping newer
video choice invalidates the earlier attempt even if the earlier positive reply
arrives late. Capture of a receive binding permanently holds that witness after
observed withdrawal. Image/video catalogs and permission replies remain distinct;
permission `foreground_required`/`requested` is never interpreted as OS READ.

Eight new native command groups now have physical Windows proofs: seven current
guard/operation cases plus one real 60.24-second no-reply timeout. They cover
configuration, catalog, foreground permission, saved-OFF rejection without output,
mid-write choice loss, actual fresh video configuration, key loss/no revival,
wrong request/close, cancellation/stale reply, superseded positive completion and
video configuration only after actual data ACK (including rejection after a
changed data-permission ACK). Six existing source-status groups also pass after
the dispatcher/metadata hooks changed. The older unchanged status timeout is not
rerun as a substitute for the new command's actual timeout. These are synthetic
source replies through the real Windows native secure writer/dispatcher, not a
physical Android provider or installed Organizer GUI acceptance.

Run/batch/END, original-source lookup and the explicit wire receive operation are
joined below. Still unjoined: operative album/worker/UI. No new background worker, startup READ,
Android permission dialog, native public bridge action or production gate is
introduced by these explicit native APIs.

### Windows explicit video metadata codecs (Refs #330, #335, partial join)

The Windows codec now parses the optional `videos: {enabled, revision}` status
extension only with explicit opt-in. The actual pending native status command
captures opt-in from the current acknowledged marker-21/22 metadata and rechecks
it before output and reply. Video-only withdrawal aborts the old pending command;
a fresh base-only status still works. No status flag grants source READ, changes
local consent or starts work.

`configure_videos` is a separate pure metadata command with only its exact version
and boolean choice, never an image-kind selection. Explicit `media_type: video`
commands for discovery/catalog, permission UI, ordinary run/control and media-page
metadata retain their type. Typed catalog/permission/run/page decoders require
matching outer scope; a video media page also requires the matching inner page
type. Image commands cannot consume these replies. Legacy image wire bytes and
the non-authoritative unbound media inspection API remain unchanged.

Six new native-source groups cover strict configuration/status fields, current
channel opt-in/withdrawal and typed command/result separation. Five shared
Python/Notes command vectors now match exact canonical bytes and SHA-256 values
(configuration, discover, ordinary run, original resume and media page). Original
resume requires its exact original-job ID/version; an ordinary run cannot carry
or silently discard that intent. Original-job resumed-run/abandonment transport
and completion metadata remain to be joined
on Windows together with the protected receiver, native preferences/destinations
and worker. The runtime API added so far sends only `status`; no positive video
configuration or READ action is exposed by these codec changes.

### Windows protected native media intent (Refs #330, #335, no receiver grant)

`DeviceFileStorePreferences` persists explicit native photo/video/manual-versus-WiFi
choices as authenticated ciphertext in a dedicated SQLite table. Reads and an
unchanged all-OFF choice do not create the table or write defaults. Both media
choices initially remain OFF, automatic WiFi is OFF, and content direction stays
phone inventory only. Both deletion directions default OFF but are independently
selectable by explicit native choice; they are not permanently disabled. The
intended UI is the same single “Löschungen auslassen” choice as Notes, not two
additional direction switches. `SetNativeMediaSyncMode` checks the saved version,
preserves photo/video selection and sets both internal deletion directions from
that one choice: checked skips both, unchecked includes both. A historical mixed
policy has no unambiguous checkbox value until explicitly resolved.
This store has no bridge/wire registration and loading positive intent never
constructs a local file grant or arms a receiver on a new connection.

Each saved row binds the phone ID/key, pairing epoch and existing local identity.
Changed bindings require explicit historical reassociation, not silent reset or
replacement. Exact version compare-and-set in an immediate SQLite transaction
protects choices from concurrent native store owners. Revisions cannot wrap;
unchanged choices retain the same version and ciphertext. Authentication/schema
failure holds the record without repairing or discarding historical bytes.
The dedicated table survives generic Notes metadata cleanup; a profile restore
fence blocks access, and actual restore-abort cleanup retains the original row.

Nine native-source groups pass for defaults/no bootstrap, protected persistence,
independent media choices, stale/concurrent owners, all identity binding changes,
authenticated corruption, strict schema/revision exhaustion and the actual
restore fence/abort path, preserved deletion choices and the Notes-style common
skip-deletions setting including stale/mixed-policy handling.
These are storage proofs, not Windows installed tests.
Native destination ownership and filesystem staging/publication are implemented
below; durable transfer history and the joined receiver remain missing. No UI,
automatic worker or production gate is enabled.

### Windows protected destinations and native filesystem receive operations (Refs #330, #335)

`DeviceFileNativeDirectory` opens an existing local-drive directory via
`NtCreateFile` with `OBJ_DONT_REPARSE` and directory/open-only options. It owns a
non-inheritable handle, denies delete sharing on that root, rejects a
non-directory/reparse attribute and reads its volume plus 128-bit file identity.
It checks the current final native path and volume-GUID path as well as the file
identity. Receive access is distinct from an ordinary read-only directory owner.
Unsupported UNC/device/ADS/ambiguous path syntax holds rather than normalizing to
another historical root. There is no bridge or production caller yet.

The receive partial creates new child directories/files through the held parent
handle and `FILE_CREATE`, never by a path-based overwrite/open-or-create fallback.
New objects receive protected ACLs allowing only the current Windows user and
SYSTEM; a permissive parent Pictures/Videos ACL is not inherited for uncommitted
media. A staged file has no write/delete sharing. Chunks must be sequential,
bounded by the existing chunk/file limits and reread from that actual held file
for complete size/SHA-256 verification. Publication uses handle-relative NT
`FileRenameInformation` with replacement disabled. Its volume, file ID, native
owner and target readback are checked; an uncertain successful rename is retained,
not rolled back, replayed or deleted. Disposing an owner does not discard files.

Directory handles allow WRITE sharing but still deny DELETE sharing. A real
Windows test first reproduced a sharing violation with the earlier no-WRITE-share
directory handles: they blocked the receiver's own NT rename. This is a targeted
compatibility correction, not permission to overwrite children. Original root
identity/path/reparse checks and the stage file's own no-WRITE/no-DELETE sharing
remain enforced. The now-real reparse tests accept either NT traversal rejection
or explicit reparse-attribute rejection; neither follows a reparse target.

`Read/SetNativeMediaDestination` persists separate photo/video root identity and
tokens under the existing local/peer keys and pairing epoch. Initial reads create
no table or destination. Only an actual native receive-directory owner supplies a
new choice. Exact-version CAS, no-op ciphertext/token preservation, independent
media tokens and volume-GUID-path nonoverlap checks apply. Changed keys/pairing,
unpairing, corrupt ciphertext and replacement directories HOLD. A saved destination
is not receive consent. Existing roots cannot be reassigned without the still
missing history/migration flow. The dedicated encrypted table survives generic
Notes metadata cleanup; saving a destination enables neither photos nor videos.

Eleven groups pass on actual physical Windows: three root/grammar/reparse groups,
four staging/publication/private-ACL/hash/uncertain-completion groups and four
protected-destination groups. These include real NT operations, root rename
exclusion, existing user-file collision, reparse targets, independent owner
readback, rejected nested/identical roots, original-inode reopen and five
key/pairing/identity/unpair/tamper boundaries. The current build has no warnings or
errors. Linux grammar/non-Windows rejection is separately tested and is not
substituted for those native Windows proofs.

The native receive-job owner below now joins protected stage/publication history.
Original-job resumed receiving and receipt-driven retirement are joined below;
working media UI remains unjoined. These filesystem/storage APIs alone are not a
complete user-facing sync. No installed Organizer acceptance, package delivery, new APK/EXE or
production gate activation is claimed.

### Windows protected native receive jobs (Refs #330, #335)

`BeginNativeMediaReceiveJob` now joins the actual protected destination, existing
saved native photo/video selection, fresh native data binding and filesystem
staging/publication. It never constructs a file grant from stored metadata. The
peer/local keys, pairing, actual destination and existing current-user DPAPI
storage-key record are checked during I/O. Observed key/scope/choice withdrawal
permanently holds that owner, including when an old key file later returns.

The dedicated AEAD job table commits and reads back an original reservation before
creating the stage, records the stage and file identities before receiving chunks,
and commits/reads back each exact prepared publication before its NT rename. Real
file chunk readback feeds the existing resume-ledger verifier; full size/hash is
checked again at publication. Each published file keeps its original identity in
the protected job. Partial publication preserves both already-visible files and
unpublished payloads, with its uncertain original intent held. Dispose never
deletes payloads or history. A newly occupied user slot fails before reservation;
a later collision never replaces it. Missing history around an existing stage
blocks a new ordinary job rather than inventing empty history or another owner.

The native media batch remains bounded to 16 flat gallery members. Held jobs
reserve at most 32 active jobs / 1 GiB, with a separate 128-job historical ceiling;
all reserved bytes count even before they arrive. Published jobs retain their
active budget until the local Saved proof, confirmed Saved output and actual
stopped-source END are joined as described below. No
quota is widened and no old job is evicted. Ordinary creation cannot substitute
for original-job recovery or reuse a historical target slot. Native media DB
opens now use existing-only read/write mode: missing `phone.db` is not recreated
by preferences, destinations or receive-history inspection.

The current physical Windows run passes 27 groups: the prior filesystem/root
groups, six actual receive-job groups, the missing-DB guard and all nine existing
protected-preference groups. Receive-job cases start with the actual encrypted
bilateral control exchange, then pass bytes through the real ledger, held files,
encrypted history and NT publication. They cover duplicate/changed chunks,
incomplete completion, interrupted-job preservation, withdrawn receive scope,
two-file partial publication, lost history/unknown stage, key removal/no revival,
corrupt ciphertext and actual 32-job / 1 GiB reservation exhaustion. The staged
bytes in these tests are supplied to the explicit native API, not yet incoming
encrypted file-data envelopes; this is not a network sync or installed GUI proof.

The explicit wire operation below joins original resume/END and earned active
budget retirement. Still missing: album-layout/mapping orchestration
and operational media UI. No new automatic worker or production gate is enabled.

### Windows owned batch, media metadata, END and original-source lookup (Refs #330, #335)

`StartNativeMediaBatchAsync` now sends a real encrypted `batch_run` and retains a
native source lease only from its fully correlated, validated reply while the
original command ticket is still live. Only one current run/ended album cursor
may be owned. Typed status/cancel/offer/end APIs address that exact reference, run
ID, source version, media type, control owner and remote session. A source lease
has no READ authority and cannot be fabricated from a copied JSON/run ID. A
remote-session change permanently invalidates retained leases.

Status/cancel/END use a separate bounded metadata cleanup ticket for a registered
original run. They do not demand positive saved receive/video choice, current
data binding, handler readiness or manifest availability after withdrawal. They
still require the current authenticated relationship/control session. Cleanup
cannot create another source lease, issue an offer or authorize new media READ.
`source_io_ended` means snapshot work has stopped; it is **not** `run_ended`.
Actual `end_run`/`end_album` replies require `canceled_held`, `source_io_ended=true`
and `run_ended=true`. No receive-job history, cache or quota is retired by these
source-controller metadata operations.

END of a batch retains its album provenance/cursor until a validated `next_batch`
or `end_album`. Advancement requires positive current data/read scope again and
a different run ID; only then is the previous lease released. `empty_ready` is
accepted only with an explicit final-batch flag. Snapshot/batch/terminal state
rollback, reused run IDs, unconfirmed END and a normal new batch while original
ownership remains are refused. Cancel/timeout does not silently erase a retained
original run; native inspection can retrieve that owned reference.

Typed `media_page` requests advance the exact owned cursor and reject duplicate
file/photo IDs, altered manifest/count, changed source epoch/media/insertion
witness, and more than 16 members in a native batch. Album scope survives batch
advancement. An incomplete media-page sequence blocks offer; a correlated offer
must match the collected manifest fingerprint. These metadata pages grant no
deletion authority and do not constitute a completed receiver/album mapping.

Original source lookup starts from an exact-version selection of a protected
existing desktop job, not a browser-supplied new manifest or guessed phone job
ID. A real encrypted `resume_lookup` correlates request, version, original
source/transfer/fingerprint, media and reply deadline. Typed source history
strictly checks job/version, phase and optional attempt tokens. The phone's
original job ID/version are committed and read back in the **same** protected
desktop job without changing its manifest, stage identities, phase or bytes.
Later replies cannot replace those original source IDs. Stale local versions,
another source manifest, wrong request/media, extended reply lifetime or missing
attempt tokens HOLD. Historical selection/remote Saved hints grant neither
resume nor current file access. This does not yet reopen/recover staged files or
start `resume_run`; the native checkpoint/source-resume join below adds those
explicit operations without replacing the original job. Receipt-driven END
retirement remains unjoined.

Current physical Windows proof: ten new lifecycle groups (including pure grammar
and cleanup-lease boundaries), seven changed shared-command guard regressions and
three receive/publication/key-corruption regressions all pass. They exercise real
encrypted Windows control output/dispatch, native synthetic job bytes and actual
protected history commits. Android source replies remain synthetic; this is not
a physical phone provider or installed application acceptance. Existing unchanged
quota and real no-reply timeout proofs are retained, not rerun. Build: zero
warnings/errors. Source/video golden and pure lifecycle tests also pass on Linux.

Native checkpoint/source-resume and wire operations are added below. Still missing: native
album/mapping/worker/UI join and Android recoverable trash/restore. No APK/EXE,
installed-system update or gate activation is claimed by this source change.

### Windows durable original-stage recovery and resumed source commands (Refs #330, #335)

Native receiving now flushes each verified chunk to its actual held file before
committing and reading back a bounded `{size, sha256}` prefix checkpoint in that
same original file member. Exact duplicate chunks do not rotate the job version.
The live prefix digest is incremental; recovery rereads the actual held prefix,
not a sender buffer or serialized hash state. A write/checkpoint commit failure
holds the owner and preserves bytes. This adds no per-chunk unbounded history or
larger job/cache quotas.

`RecoverNativeMediaReceiveJob` requires exact protected original history,
correlated saved phone job identity, current native choice/data binding and the
original destination. It opens the recorded stage/file identities via the held
parent handles using **open-only**, not create/truncate. Inventory, plain-file
link count, original file IDs, exact checkpoint size and actual prefix SHA-256
must all match. Only those authenticated held bytes rebuild the original ledger;
new chunks continue at its missing offset in the same job. A changed prefix,
uncommitted tail, replacement file, unknown child or missing member HOLD without
deleting, trimming, adopting or recreating files. Legacy uncheckpointed jobs and
uncertain partially published jobs are conservatively held, not auto-migrated.

`StartNativeMediaResumeAsync` requires that actual live recovered owner and its
exact original lookup selection; a disposed/unrecovered/new ordinary job is not
a substitute. It sends the phone's correlated original job ID/version in
`resume_run`, and retains source ownership only after a validated reply. Resumed
metadata/offer/status/cancel/END use their dedicated operation names. Complete
resumed media pages must correlate with the original manifest's file IDs/count
and fingerprint before offer. Status/cancel/END retain the metadata-only cleanup
path after receive withdrawal. Actual source END still does not retire local
bytes, historical jobs or cache reservations.

Physical Windows proof: the combined run passes 23 groups (13 lifecycle, seven
shared-command regressions, three receive/publication/key regressions). After the
additional original-manifest media guard, the three affected recovery groups
pass again: actual 64-KiB interrupted-prefix reopen/duplicate/new chunk/original
publication; five byte/identity/inventory mutation HOLDs preserving every file
and history version; actual original-source resume command/media/offer followed
by post-withdrawal dedicated cancel/END, including rejection of a wrong resumed
file ID. The current build has zero warnings/errors. The tests use real Windows
file handles, DPAPI and encrypted control output/dispatch with synthetic source
replies; local resumed chunks enter the explicit native API, not yet a wired
incoming Android data route. No full phone sync/installed GUI proof is claimed.

The explicit receive operation below adds wire chunks/Saved/END and local active
budget retirement. Still missing: legacy/uncertain publication recovery UI, native
album/mapping/worker/UI and Android recoverable trash/restore. Gates stay OFF;
no APK/EXE, installed-system update or public release is produced by these APIs.

### Windows incoming source-offer ordering (Refs #330, #335)

The Android source sends the sealed file offer **before** its correlated
`offer_run`/`offer_resume` result. Windows now retains exactly one bounded early
offer while that actual confirmed-output command owns the slot. Current data
binding and request operation, native sender/receiver, envelope/manifest limits,
strict current expiry (no historical grace) and the original command deadline
are checked. Nothing is accepted, staged or inserted in receive history at this
point. The later typed run result must identify that exact offer ID/fingerprint,
and the completed media pages must correlate to the offered manifest. Only then
is the offered manifest retained on the owned source run, with its ID/expiry.
A newer offer attempt clears that earlier in-memory offer witness.

Two native Windows groups pass for actual encrypted offer-before-result dispatch
and for wrong result ID, duplicate offer, expired offer and unsolicited offer.
The valid ordering does not finish the pending command early or emit acceptance;
every failed case leaves destination and receive history untouched. This is an
incoming source-offer **preflight**; the wire acceptance/chunk/Saved receiver is
joined below. Production gates, installed programs and delivery artifacts are unchanged.

### Windows explicit wire receive, local Saved proof and stopped-source END (Refs #330, #335)

`ReceiveNativeMediaRunAsync` now joins the owned source offer to one explicit native
receive operation: protected original admission, actual encrypted acceptance and
single-chunk requests, incoming chunk response dispatch, held-file readback/flushed
checkpoints, no-replace publication, local durable Saved receipts, actual Saved
output, acknowledged source stop and correlated source END. A packet ID, remote
Saved assertion or saved preference cannot construct this owner. Resumed runs use
the actual recovered original job and request only its missing chunks.

The Windows-local acceptance context binds the original job, manifest, current
native binding, 128-bit destination identity, target paths and correlated source
epoch/media/photo IDs. It is committed/read back before outgoing acceptance.
Windows-local receipt digests bind those accepted targets to the verified native
published file/parent identities, full flushed prefix checkpoints and publication
proof. They are committed/read back before outgoing `file_transfer.saved`. These
private Windows representations do not pretend to be POSIX destination keys and
do not add/change public wire fields: the existing opaque acceptance/receipt
SHA-256 fields carry their proofs. A remote Saved parser is only wire preflight,
never the source of a local receipt or native write grant.

Each requested chunk has an exact request/transfer/manifest/acceptance/epoch/token/
file/index binding and a bounded wallclock/monotonic deadline. Wrong/unsolicited
replies cannot enter the book inbox. Cancellation drains the actual I/O lane
before closing native handles. At most one exact in-flight retired response may
be consumed and zeroed without writing, ACKing, recreating grants or destroying
the metadata cleanup channel. Source cancellation and END do not by themselves
retire interrupted data. The same protected original can be selected, looked up,
reopened and renewed under `resume_run` without another reservation or a new job.

The actual Android runtime requires `cancelRequested` before `end_run` and
`end_resume`. The complete Windows Saved path therefore performs and validates
`cancel_run`/`cancel_resume` first, then END. The native END API also refuses a
merely finished snapshot that has not acknowledged its stop. The initial source
fixtures had allowed direct END; they were corrected against the Android runtime,
not treated as proof that the real phone accepted that sequence.

Only a confirmed secure Saved write plus an actual matching stopped-source END
records the durable original `source_end` marker and frees that job's active
reservation. History and file/version proofs remain intact: 32 active jobs / 1 GiB
and 128 historical jobs are not widened or evicted. Publication, local Saved alone,
an uncertain Saved write, cancellation or a false END keep the active budget.
Metadata-only END after receive/handler/choice withdrawal can complete the exact
already-saved original without reviving data permission.

Current physical Windows proof: six complete-operation groups pass: two real native
files across multiple incoming chunks through the production dispatcher and local
Saved/stop/END; four invalid chunk bindings retaining the original stage; Saved
END after receive withdrawal; actual stop/drain/old-response discard and original
wire resume skipping the verified 64-KiB prefix; failed Saved output/false END
retaining published bytes and budget; independently positively activated video
using only its separate native destination. Thirteen affected lifecycle groups
also pass after the Android stop-before-END correction. The tests use actual
Windows handles, DPAPI, SQLite and encrypted outgoing frames, with synthetic source
messages injected after the existing secure decoder. They are not a physical
Android-provider, real media-decoder or installed GUI acceptance. Existing unchanged
quota/60-second proofs are retained rather than repeated. Current build: zero
warnings/errors.

Still missing for user-facing media sync: managed album layout/mappings, three-way
incremental reconciliation and recoverable replacement/deletion adapters, retention,
operative coordinator/worker/UI, Android recoverable trash/restore and native package
acceptance/delivery. No automatic startup READ or production gate is enabled here.

### Explicit deletion synchronization requires recoverable trash (Refs #330, #335)

User clarification: targeted photo/video deletions must propagate in both
directions when “Löschungen auslassen” is unchecked, with a recoverable trash entry, not a permanent
import-only restriction. OFF is the initial choice, not an implementation limit.
Deletion consent is separate from reverse content replacement: a phone-inventory
content direction does not block an explicitly selected desktop-to-phone trash
operation. Changing photo/video selection preserves existing deletion choices.

Both pure desktop comparison implementations now propose `trash_phone` only with
genuine native `TrashPhone`/`trash_phone` support, and `trash_managed_desktop` with
desktop trash support. A permanent-delete adapter cannot substitute for phone
trash. These proposals explicitly require a trash entry; they are neither a
completed entry nor mutation authority. Changed content, unknown identity, missing
baseline or incomplete/absent scan evidence still holds/conflicts instead of
deleting. The shared vectors cover reverse-trash consent independently of content
direction, default OFF, missing adapter, permanent-delete rejection and identity
uncertainty.

Counterpart execution remains unjoined: it must durably retain recoverable bytes/native trash
identity plus original phone/media/destination association, content witness and
deletion operation/version, and record counterpart completion before any
retirement. Restore needs exact no-replace checks and a newer recorded restore
state so the old deletion cannot replay. No unconfigured phone trash API may fall
back to permanent deletion. The separate existing explicitly-disabled-trash flow
must retain “Papierkorb deaktiviert: Die ausgewählten Einträge endgültig löschen?”;
these changes do not bypass that confirmation or execute such a deletion.

Current proof is protected intent plus pure planning only: 9 Windows preference
groups, the shared Windows comparison group and 32 Python comparison tests pass.
The Linux native local journal/restore below now joins actual local file moves;
there is still no counterpart propagation or physical phone
trash proof, so no actual cross-device deletion success is claimed.

### Linux native local photo/video trash and restore (Refs #330, #335)

`ProtectedMediaTrash` creates actual recoverable local entries only from explicit
native actions and the original protected saved-mapping store. A separate
existing-key-encrypted, append-only journal retains every operation and mapping,
including original parent/file identities, destination, media type, content hash
and historical save receipts. It never turns missing scan members into deletion
evidence and is not registered as a wire command or browser-path action.

Before any move, `prepared` is committed and synced. The original private file is
moved with descriptor-relative Linux `renameat2(RENAME_NOREPLACE)` to a random
hidden trash-payload name in its original parent, preserving the inode and bytes
on the same filesystem. This is an application-owned recoverable payload, not a
claim that a freedesktop/Windows/Android system-trash API has run. Local retention
cleanup is described below; no pathname unlink is used. Original roots/parents, private regular-file identity and exact
size/hash are checked around I/O; symlinks, edits and collisions HOLD. A raced
candidate is preserved; any rollback is also no-replace and forbidden after
native revocation. Parent sync and a committed `trashed` event precede local
completion. A retained payload is not a counterpart deletion ACK.

Restoring first commits `restore_prepared`, permanently disarming the old delete
operation, then moves the exact payload back without replacing a newly created
user file. `restored` is appended only after readback/sync. Restart can recover
only the exact original operation and witnessed inode/bytes after an uncertain
move. An explicit cancellation is allowed only for a proven not-yet-moved
original; it appends `canceled`, never erases history or hides a post-move payload.

A separate authenticated anchor under the existing native telephone root binds
the original journal directory/database/lock inode identities. Missing journal,
missing anchor, replaced directory or damaged history HOLD instead of creating an
empty replacement. The history is bounded to 128 retained operations, with up to
four lifecycle events reserved per operation; a full history blocks a new delete,
never evicts earlier entries or prevents already-reserved restore transitions.

The actual `NativeDesktopFileConnection` owns this resource lazily and serializes
native inspect/prepare/move/restore/cancel actions on its existing I/O lane. Live
receiver/source/album work or unavailable production data handlers block mutation.
Connection closure revokes authority before closing the journal. No worker starts
on construction/read, and unconfigured package composition omits the new module.

Twenty-five targeted source-host cases pass using actual saved JPG files and the
actual typed video worker/mappings/Saved/END path. They cover move/restore and old
delete replay, five interruption boundaries, conflicts, revoked authority, racing
replacement, encrypted history corruption, history limits, same-size edits,
symlinks, missing/replaced journal anchors and cancellation. A real video rescan
while trashed holds the existing missing-target conflict without downloading or
resurrecting the file; after restore it is recognized unchanged without another
download. Twenty optional-composition tests also pass.

Still open: durable counterpart propagation and restore reconciliation, Android
native trash consent/proof and the Windows backend. Offline local restore and the
source Organizer trash UI are now implemented below; installed/native GUI
acceptance is still missing. The existing Linux skip-deletions preference
must still be joined to actual counterpart actions; local explicit trash is not
that propagation. Production gates remain OFF and no installed test or complete
bidirectional deletion synchronization is claimed.

### Local recovery authority independent of phone connectivity (Refs #330, #335)

`NativeLocalMediaTrashAuthority` authenticates the original opaque anchor scope
using only the existing private native telephone root/key. It creates no keys,
identity, pairing or directory, needs no channel and never reads a phone grant.
The original encrypted journal supplies its historical pairing namespace only
after authentication; this remains usable after disconnect or unpairing for local
restoration. The captured anchor/root identities and existing key are rechecked.
Observed key withdrawal permanently revokes that instance, even if the old bytes
are restored. Missing/replaced history is held, not defaulted or repaired.

This authority exposes no channel or control-peer/grant conversion. The ordinary
photo preference and mapping-store constructors continue to require the actual
authenticated transport authority and reject it. Only the trash subclass reuses
the underlying protected-store initialization with its authenticated historical
subject. New trash/prepare operations are explicitly forbidden in recovery-only
mode; local read, exact restore and proven pre-move cancellation remain possible
under a one-shot native action. Local restore is never a counterpart ACK or phone
undelete permission. There is no browser-provided-root factory; the source UI
caller below supplies only its own native telephone root.

Six new source-host cases pass, including actual file restoration after both
disconnect and unpair without a phone message, absent-root/key/anchor no-bootstrap,
key withdrawal/no revival and observed-history loss. Forty-one existing protected
photo-preference/direction cases and five targeted online trash/video/anchor
regressions also pass. The original journal/anchor format is unchanged; no
historical store migration or pairing modification is performed by recovery.

### Organizer media trash view and native offline restore (Refs #330, #335)

The Linux source frontend now projects these external entries into a separate
“Photos and videos” group inside the existing Settings → Security → Recycle bin
section. It does **not** copy them into `DATEN.papierkorb`, book saves or the
bounded Notes trash list. The same retention days apply through native maintenance
rather than list eviction. Emptying the other entries does not purge media;
the group now offers explicit confirmed permanent removal per media entry.
Restore, pre-move cancellation, explicit refresh and bounded page loading use
only scope/operation/version tokens. Filenames are displayed as text, and all
four new labels have authored translations in every existing desktop locale.

`NativeMediaTrashUi` strictly validates requests, scans only the known existing
native telephone root and returns basename/type/state plus opaque IDs, never
destination paths, keys or receipt blobs. It creates no root, storage key,
PhoneService or listener. Pagination does not evict history. A verified operation
completion is independent of a separate overview refresh, so an unrelated damaged
scope cannot make a completed restore look failed. Prepared crash recovery may
confirm an **already moved** original payload and restore it; it cannot turn an
unmoved prepared entry into a new trash move under a restore request.

The actual GTK handler admits one bounded native UI worker, checks the trusted
unlocked frame, uses `daten_verzeichnis()/telefon` rather than a browser path,
and rechecks UI lock/root/deadline during native I/O. A callable reply is checked
again on actual UI delivery, and window destruction revokes the request. The
implementation is loaded dynamically only after optional-build admission, just
like the existing optional phone loader; omitted implementations are not static
dependencies of unconfigured builds. Unsupported Windows controls remain absent.

The frontend binds every reply to its exact pending request/action. Failed,
foreign or malformed completions do not remove rows; only verified native
completion does. A separate metadata refresh updates other row versions. The
overview checks both original anchor and journal names; either missing half is
held, not reported as empty. It projects the authenticated scope set as well:
loss of a previously displayed scope preserves cached rows with an error rather
than claiming those entries disappeared. Unknown/error counts do not display a
false empty-bin message. Lock or
book initialization clears private cached entries/timers and rejects late replies.
No media action changes Notes contents/grants or manufactures a book-save ACK.

Source proofs: 21 native facade/actual-handler cases, two additional prepared
offline recovery boundaries, eight frontend/locale cases including Windows
absence, 20 optional-composition cases and the full existing Linux UI suite pass.
The exact handler is exercised through the established source/AST harness,
including actual offline file restoration and late-lock response rejection; this
is not a real installed GTK/WebKit acceptance claim. All catalog checks pass;
the 19 tracked Windows catalogs add only these four keys with old values intact.

The new view is local recovery, **not** completed phone deletion synchronization.
Counterpart trash/restore transport, native Android consent/receipts and Windows
receiver integration remain open; gates stay OFF. The one Notes-style
“Löschungen auslassen” choice remains the intended propagation control, not two
new direction switches, and the existing disabled-trash confirmation is unchanged.

### Shared saved-book retention and bounded native maintenance (Refs #330, #335)

Local media trash follows the saved book's `einstellungen.papierkorb.tage`:
0 means never automatically release recoverable bytes; 7/30/90/365 use exact
elapsed days since the authenticated local `trashed` event. Old undated history
is preserved rather than dated from filesystem/peer timestamps. Restored and
canceled operations cannot expire or replay a deletion.

Expiry commits `purge_prepared` before moving the verified original payload into
an owned private same-filesystem capsule. The exact held original inode is
truncated and synced, never unlinked by pathname. Hash, private ownership,
single-link identity, destination and current policy are rechecked. Raced
replacements, edited bytes, hardlinks, unknown capsule contents or withdrawn
policy HOLD. An authenticated `purged` tombstone and zero-byte completion marker
remain to prevent reimport/replay; original history quotas are unchanged.
Interrupted cleanup can resume exactly, or restore the intact original before
byte release. Both alternatives fit the existing four lifecycle slots.

`NativeMediaRetention` uses only the existing private `phone.db`/`meta` and
existing storage key, with separate AEAD framing; it never constructs PhoneStore,
creates keys/pairings or accepts browser-provided retention days. The actual native
save worker durably pauses cleanup before saving a book. Only successful native
commit publishes the new days under the exact pause token. Postcommit derived
failure reports repair pending, not a failed book save, and leaves cleanup paused.
SQLite's cross-process writer lease serializes a destructive operation against
policy changes. The authenticated policy also records the saved book's private
file identity/signature: other replacement/restore/encryption writers cannot
silently inherit old cached days.

The real manual/video/automatic sync session runs bounded local maintenance before
new source discovery, and the native trash overview performs the same maintenance
on its first page. No new scheduler, READ request, socket or background worker is
created. Each invocation admits at most 16 operations / 400 MiB, retains every
tombstone and stops on uncertain scope/policy. UI lock/stop/deadline checks remain
in force. Missing/paused policy is not a default cleanup permission.

First adoption reads the actual fixed private `daten.json`, not the in-memory UI
book or independently supplied days. An unattended automatic run can adopt a
plain saved book. The native startup/unlock path supplies the existing native
decoder for encrypted books; no background password prompt or key creation is
introduced. A changed file during adoption HOLDs. Already-paused policy is never
revived by first adoption, and already-present policy is not silently reassigned
to an externally changed book. First adoption is bounded to a 64 MiB book read;
larger books HOLD until an ordinary native save publishes policy without that read.

Source proofs: 13 retention-core cases, 33 ordinary move/offline regressions,
20 saved-policy/runtime/bound/adoption cases, 46 native view/save/composition
regressions and eight frontend cases. The current 20+46 run passes all 66 cases.
Runtime cases include
the actual save worker (postcommit failure stays committed), actual automatic
session ordering, native first-page expiry without phone messages, never/manual,
failed save, tampering, key withdrawal, changed book and concurrent policy owner,
initial automatic 0/7-day adoption without another save, a raced book during
adoption, preserving a paused policy and actual native load/unlock helper calls
for both plain and encrypted saved books despite conflicting in-memory UI days.

Manual removal is now implemented for individual media entries, including 0/never
and legacy undated trash. It uses an exact scope/operation/version plus explicit
confirmation, a native one-shot action and current unlocked UI guard. It has no
browser paths or retention-day override and does not edit the saved policy. The
same verified inode/capsule byte-release path is used, with an authenticated
manual/zero-day marker distinguishing explicit removal from automatic expiry.
Unmoved `prepared` originals are not purgeable. Interrupted manual cleanup needs
a fresh current native confirmation to resume while bytes remain; automatic
maintenance under 0 cannot inherit the earlier confirmation and release them.
Restoration before byte release and retained terminal tombstones remain intact.

The frontend requires confirmation identifying the selected filename, discards
late confirmation after lock or overview replacement and removes a row only on
the exact verified `purged` completion. Cancellation, errors and foreign completion
keep the row; there is no manufactured book save or phone deletion ACK. A shared
retention/manual-removal help message is translated into all 19 existing locales.
The ordinary disabled-trash confirmation is unchanged. Bulk media emptying is not
implemented; manual media removal is per entry.

Current manual proof: nine native manual cases plus 13 automatic-retention core
cases pass, including three manual crash boundaries, stale version, native guard
withdrawal, no automatic inheritance under 0, unchanged newly created user file,
strict manual journal shape and legacy undated trash. The current joined run
passes 70 cases (nine manual, 20 policy/runtime/adoption, 21 native UI, 20 optional
composition). Ten frontend/locale cases pass, including confirmation cancel,
failure/foreign completion, overview replacement and late-lock confirmation. The
19 tracked Windows runtime catalogs add only the one intended help key; existing
messages/metadata remain unchanged. These are source proofs, not installed tests.

An externally changed book currently HOLDs
until a new native save publishes matching policy. Counterpart propagation,
Android native trash receipts, Windows receiver and installed/native acceptance
remain open. This source checkpoint is not complete media synchronization,
an installed test, a package delivery or a public release; production gates stay OFF.

### Current-channel video capability witness (Refs #330, no READ grant)

Desktop authority exposes read-only video availability separately from the base
photo control peer. It defaults false without an explicit native witness and
requires protected base marker 21 plus video marker 22. The actual PhoneService
witness verifies current channel/generation/identity and exact ACKed capability,
grant and own-device metadata against the current peer. It is checked before and
after protected peer I/O; that I/O does not hold the service monitor. Losing video
support alone leaves base photo authority intact.

Failed metadata ACK invalidates its previous witness. Superseded capability or
grant receipts cannot replace current metadata; a duplicate may finish a newer
revision's failed ACK only when it still matches current peer metadata. The
stricter own-device withdrawal/reconsent rules remain unchanged. Tests exercise
the real payload/secure-ACK failure path, withdrawal, superseded positive replay,
fresh ACK retry, reconnect and revocation during protected I/O. Availability is
neither video consent nor OS READ, and does not advertise production readiness.

### Desktop typed source codec (Refs #330, no video admission yet)

The desktop codec now supports explicit video commands and correlated catalog,
permission, run, original-resume and abandonment replies. A pending image command
cannot consume a video reply; video requires the explicit outer scope and matching
inner media-page scope. The actual receiver passes its pending command's media
type before collecting pages or admitting offers. Legacy image command/reply
shapes remain unchanged. The unbound media inspection API retains its historical
metadata-only behavior and is not receiver authority.

`configure_videos` remains separate metadata. Video policy-status extensions need
explicit negotiated parser opt-in, with strict booleans/counters and no inferred
READ grant. Five shared native/Python canonical command vectors pin exact bytes
and SHA-256 values. Codec and existing receiver/resume/batch integration tests
do not enable desktop video destinations, worker admission or production gates.

### Independent protected desktop video scope metadata (Refs #330, partial join)

The desktop preference owner now has a separate explicit native video-scope CAS.
It requires an existing associated photo policy and an exact typed native video
destination choice for initial enablement. The protected metadata revision may
advance while photo file-grant revision/epoch, photo destination/token, mapping
and catalog witnesses, scheduling and historical receipts remain unchanged.
Choosing a video destination is neither an OS READ grant nor a worker start.

The video token must differ from the photo token, including when the user
explicitly chooses the same directory for both. Re-selecting the original video
directory retains its original token and can be idempotent only with a current
native action. A different directory or replacement inode requires separate
historical reassociation; this API cannot migrate/adopt an old target. Video OFF
retains original metadata and remains possible with a missing video folder or
disabled base photo policy. Video enablement verifies the actual directory and
cannot re-enable missing/replaced roots from history alone.

Source-host preference cases cover exact photo-grant preservation, protected
CAS/readback/reopen, stale/replayed/expired actions, wrong choice/authority types,
token alias rejection, missing/replaced roots and uncertain writes. A real saved
photo job case verifies original protected mapping receipt, mapping/catalog
state, native binding and user-edited file bytes/inode after video metadata
change, without a new control packet or source request. The codec/current binding
and ordinary receiver join are documented above; original video resume and
session/worker/UI remain pending. Video controls remain absent and production
readiness remains OFF.

### Typed authenticated video runs and original-job continuation (Refs #330)

The native authenticated source-command lane now binds ordinary/video-batch,
subset and original-resume commands to the exact native catalog/run media type.
This check applies before mutation or READ and after idempotent start lookup.
Image commands cannot adopt, cancel, select, continue or end a video owner.
Source replies carry `media_type: video` only for video; legacy image reply
shapes remain unchanged. Video lookup/abandonment uses the current video policy
epoch, never an old epoch recovered from history.

Positive video READ still needs current local/peer support and actual dedicated
control acknowledgement. Capability withdrawal permits only exact-owner status,
cancellation and END under current base configuration authority; no new media
READ is granted. Completed normal/resumed END retains the exact command/reply
for bounded retry after uncertain output. Changing the media type of an END
retry cannot retire another job or substitute an image owner. Only actual Saved
proof permits the existing guarded cache retirement; unsaved END retains the
original protected job/cache/receipts. Explicit attempt abandonment after actual
END preserves the full original head and its protected abandonment history.

Native source-host cases exercise actual MediaStore video PFDs and encrypted
snapshots through wire run/media/offer, transfer-dispatch acceptance/chunk/Saved,
stop, fresh video lookup/catalog, original-job resume and lost-END exact retry.
They include modern Android READ, capability withdrawal, cross-media rejection,
two batches across the unchanged sixteen-file working boundary, album-scan END
without opening remaining media and native subset selection. Source epoch
guards are unchanged: video disable/re-enable does not implicitly reassociate
an old accepted job. Desktop original-video-resume/worker/UI and all
installed/physical-device acceptance remain separate work; production gates
remain OFF.

### Video negotiation and scoped command codec (Refs #330, partial join)

Discovery marker 22 is reserved for video handlers alongside required base-file
marker 21. It is emitted only when both local handler gates are true; production
gates remain OFF. The authenticated native peer projection keeps video support
separate from base file support. Removing video support need not rotate pairing
or photo file grants. The runtime supplies a live local/peer video-availability
veto to the workflow, in addition to the existing acknowledged data authority.

The strict native command codec accepts an optional `media_type` (`images` or
`video`) for scoped catalog, READ, run and resume operations. Omission retains
legacy images. `configure_videos` is a separate metadata-only operation with
`expected_version` and `enabled`, not a photo configuration or an OS READ grant.
Legacy status/configure shapes reject media extensions; existing canonical
image command vectors are unchanged.

The runtime now joins video metadata configuration, discovery/catalog paging and
permission requests to separate native video scopes. Every video READ/catalog
request requires current local/peer video support and acknowledged native data
authority; no image fallback is allowed. Positive video configuration rechecks
feature availability throughout its protected CAS. Permission output echoes the
video media type and rechecks live authority independently of UI preparation.
Image responses omit the media field. Status/configuration replies contain a
`videos` object (`enabled`, `revision`) only with current negotiated video support;
old image-only status shapes are unchanged.

Native image/video catalogs are separate and reject each other's IDs. Video-only
metadata changes retain photo file-grant bytes without waiting for a new photo
control packet. A lost metadata reply leaves actual committed state available
through fresh status, not a replay of stale configuration. Scope changes cannot
interleave with an actual source owner. Capability loss/uncertain CAS permits no
positive READ, and explicit video decrease remains possible after withdrawal.

Discovery alone opens no media PFD and creates no job. The typed native run join
is described above; desktop ordinary target/receive is partially joined above,
while original video resume and worker/UI integration remain absent.
These native joins alone are not usable desktop video synchronization and do
not activate production readiness.

Direct native run entry points and normal offer/acceptance/chunk/Saved validation
now derive their activation from the selected catalog's native media type rather
than defaulting to images. Source-host checks exercise a real owned video run
through encrypted snapshot, offer, acceptance, actual chunk bytes and protected
Saved proof. Capability withdrawal blocks further owned video chunks while image
activation remains available; native cancel and actual quiescent END still work.
Direct native END calls alone retire no cache or quota; the separate guarded
wire-END path uses actual Saved proof before cache retirement as described above.

### Typed native foreground owners and permission taps (Refs #330)

The passive foreground route now retains separate image/video hosts, owners and
process-local action ledgers. MainActivity registers both hosts before STARTED,
without opening a store, starting a service or requesting OS permission. Every
tap remains tied to its native media type, owner, current request and expiry;
equal identities/epochs cannot reassign an image action to video. Closing the
runtime invalidates both routes. A live video-capability withdrawal invalidates
video actions without cancelling an unrelated photo action or rekeying grants.

Video and photo notifications use separate IDs/channels and correctly typed
labels, retaining private immutable one-shot intents and no background activity
launch. One actually pending OS dialog still excludes the other media domain.
An image wire request while only a video dialog is pending reports foreground
interaction required, not image permission requested. Actual native typed-tap
tests exercise legacy and modern Android permission hosts and notification
coexistence. This native route alone does not expose complete desktop video
synchronization or constitute physical acceptance.

### Native independent video consent and typed READ workflow (Refs #330)

The native policy has an optional strict format 4 with a separately disabled-by-
default video policy and retained photo file-grant revision. Older policy formats
keep their original shape. Explicit video policy CAS uses its own bounded epoch/
revision without changing acknowledged photo file-grant bytes, pairing or existing
jobs. Native index checks reject permission-counter rollback, changed base consent
at an unchanged grant revision, and erasure/downgrade of existing video metadata.
Policy uncertainty still holds READ rather than fabricating defaults or retiring
cache/history.

The native workflow can now discover, freeze and read the actual video collection
only through its explicit video activation and typed OS READ observations. Video
background access, activity bindings and early permission hosts are distinct from
images. Android 13+ requests the declared `READ_MEDIA_VIDEO`, never image READ as
a fallback. Callback Boolean maps are not permission authority; actual OS flags,
native owner, media type, policy and deadline remain checked. One pending media
dialog excludes another. Native permission-result/selection notifications revoke
old READ observations in both media domains without rekeying their file grants.
Video withdrawal blocks further cache reads while preserving the original cache,
job and phone bytes. GIFs remain in the image domain.

Source-host tests include actual protected-policy/index operations, native
permission hosts and MediaStore/PFD/encrypted-cache workflow on legacy and modern
Android runtimes, plus merged-manifest permission inspection. They do not prove
physical permission dialogs or an installed phone transfer. The independent
desktop original video resume and complete worker/UI integration remain absent.
No video control or new production readiness is advertised from these native
workflow checks alone.

### Native camera-album classification for future photo grouping (Refs #330)

Future grouping of camera photos now uses the actual selected native album kind.
The pending native source command pins that kind from the validated catalog at
run start; the correlated reply attaches it to the same owner. Subset selection
and following batches retain this classification, while actual run/album END
and policy-generation changes clear it. Rediscovery, an album display name or a
path containing `Camera` cannot reclassify an active source. A missing kind with
camera grouping enabled is HOLD, not an inferred classification or READ permit.

New camera-photo targets can use `Eigene Aufnahmen/`, combined deterministically
with the animation folder when selected. Downloads, screenshots and received
WhatsApp media keep their own ordinary/animation target routing. Existing
accepted targets, version chains and original resume targets remain authoritative.
Both future-only layout options require explicit `keep_existing`; neither moves
historical files or changes grants, storage witnesses, pairings or paused
scheduling. The native idle gate, strict local GTK/IPC action and existing Notes
advanced-functions area apply to this separate camera-photo checkbox as well.
It does not advertise live phone-camera capture or video synchronization.

Actual source-host cases cover all four album kinds with misleading names/paths,
multiple batches, classification retained across subset selection and later
discovery, combined animation/camera routing, historical targets and PC edits,
original stopped-job resume, explicit GTK/IPC choices and automatic sync. These
remain source-host checks, not installed/physical-device acceptance.

### Future-only animation grouping with explicit historical choice (Refs #330)

The actual album worker now supports the existing native animation target route
for newly admitted photo identities. The Notes advanced-functions checkbox
explicitly selects `keep_existing`: existing files keep their original folders.
No historical move/copy option is exposed, and no migration is inferred from a
boolean. GIF/animation members remain photos; ordinary images are not routed to
the animation folder. Original accepted targets and protected historical mapping
heads always take precedence, including after stop, layout change and resume.

Layout changes use protected preference CAS while retaining exact file-grant
revision/epoch, destination token, pairing, mapping/catalog witnesses and old
receipts. Actual workers, receivers, offers and source commands exclude a layout
change. An idempotent request still requires a live explicit native action.
Changing the future layout starts no scan/transfer/migration and does not unpause
automatic synchronization. The frontend exposes it only for native support and
disables it while the action lane is busy. Both new labels are localized in all
nineteen desktop catalogs.

Source-host tests cover actual GTK/IPC changes, mixed animation/image publication,
preserved original PC edits, disabling grouping without moving already grouped
files, repeated sync without chunks, original stopped-job resume at its old
target, invalid/implicit historical choices and in-flight exclusion. Video
routing, historical destination reassociation and journaled no-replace
migration remain separate unimplemented joins; these checks
grant no installed/physical-device or production acceptance.

### Explicit Organizer recovery overview and historical receipts (Refs #330)

The existing Notes advanced-functions area exposes a bounded native recovery
overview only when the actual desktop implementation is available. Inspecting
it creates no transfer job and opens no source, stage, publisher or destination
file. Original protected catalog/index/mapping evidence distinguishes historical
Saved confirmation, an independently completable post-mapping receipt, a cleanly
closed pending job requiring a fresh album scan, and HOLD. Corrupt, missing or
uncertain evidence stays HOLD; the overview grants no recovery authority.

Local GTK/IPC actions select one original native owner, never a caller-supplied
path or proof. Historical confirmation and receipt completion remain separate
explicit actions and revalidate the original protected evidence. Neither
recreates a deleted PC file, republishes content, creates mappings or frees job
quota. A confirmation result means only that the historical message was sent,
not that the phone acknowledged a new transfer. Pending offers, source commands,
actual source owners and live receivers exclude these actions. The native action
lane stays busy until actual output ends, even after a UI stop request. Recovery
inspection/repair/confirmation cannot resume paused automatic synchronization.

Source-host tests exercise the actual GTK/Unix-IPC actions with deleted targets,
missing post-mapping receipts, stale IDs, malformed selections, corrupt history,
real source-owner exclusion and blocked historical ACK output. Frontend tests
cover inert rendering, separate original-job actions, escaped labels, exclusion
from KDE/unsupported connections and disabled overlapping controls. New messages
are localized in all nineteen desktop catalogs. No installed or physical-device
acceptance or production readiness is implied.

### Native clean-END proof and one-use publication renewal (Refs #330)

A native receiver which actually closes before its publisher ever entered a
publication attempt can now record a positive unpublished-END proof. Publisher,
journal and stage I/O end first; the exact owned index lease closes last. The
proof pins the original acceptance, checkpoint hash and index/database/stage/
journal/publication-cache identities. Orderly teardown may record this metadata
after revocation; doing so grants no READ, file write, Saved acknowledgement or
new consent. Corruption/uncertainty never creates a substitute proof and must not
prevent resource closure.

The existing bounded catalog-membership database atomically records protected
`closed`/`consumed` chains alongside its authenticated job membership. Its optional
schema is upgraded only while recording an actual native END, never from missing
history during resume. Original reservations, receipts and earlier attempts stay
intact. The existing database/page, allocation and historical-job limits are not
enlarged. New END entries reserve room for consumption; exhausted history holds
rather than discarding a consumed proof. Exact head-cipher CAS protects concurrent
membership changes.

Explicit resume revalidates current native consent, the verified original stage,
the exact END/checkpoint and the pinned, empty original publication cache. It
durably consumes the proof before enabling the original journal and reopening
that cache. A transient native owner/thread permit is not serializable and cannot
be replayed after the factory returns. A second clean owner END needs a new proof.
Abrupt death after consumption, failed/attempted publication, missing consumed
records, replaced roots and uncertain durability remain HOLD. Target absence or
an empty journal alone still cannot recreate a deleted PC file.

Actual source-host tests cover a stopped version job through verified resume,
publication, Saved and cache retirement; fresh native channel ownership;
missing-byte-only continuation; repeated clean stops; both sides of the link
boundary and a deleted target; abrupt descriptor termination; consumed-proof
replay; root replacement; revocation; postcommit failure; concurrent metadata CAS;
history exhaustion; forged permits; and corrupted-index teardown. These native
adapter tests are now joined to the Organizer's actual album worker: a fresh
complete matching album offer selects at most one original pending job, releases
the never-accepted preview/scan, performs the source's original-job lookup and
renewal, validates fresh original media, and resumes only missing chunks. Changed,
partial, ambiguous or unproven membership remains HOLD. Selection metadata itself
grants no READ or publication authority.

Successful resume ends the source while the exact original receiver still owns
its durable Saved mapping receipt; only then may local cache retirement change
the catalog job. Unsaved stop requests perform no caller-thread I/O: the worker
drains, checkpoints and actually closes before source END and guarded attempt
abandonment. Only a genuine Saved original and actual quiescent END allow Notes
to reuse its existing guarded cache-retirement path; END alone never does.
Transient dispatcher gate contention is retried only at the pre-entry busy
boundary, not after failed or uncertain I/O. Actual GTK/IPC stop/restart, source
END, repeat without downloads, stop during resume and negative proof cases are
covered by source-host tests. They are not an installed/physical-device
acceptance. Production readiness and installed/physical-device acceptance remain
separate gates; no package or capture readiness follows from these checks.

### Changed phone versions without replacing earlier files (Refs #330)

The real album worker may now transfer a changed phone version when the native
source proves stable insertion identity and the previous saved PC version is
unchanged. The original accepted target is never overwritten or renamed. The new
content is published through the existing no-replace publisher under a visible
`Versionen` subdirectory, with deterministic association/content-based targets.
An existing file at that target is not adopted, even if its bytes happen to match.
PC-only edits remain local; edit/edit, missing targets, weak source identity and
concurrent PC edits remain conflicts/HOLD rather than overwrite permission.

The mapping store keeps the original encrypted row and all version records
immutable. A separately protected head points to the newest saved record, whose
authenticated predecessor chain must reach the original. The existing aggregate
owner covers the extra rows without replacing the database/schema or loosening
quotas. Historical SavedMappingReceipts continue to resolve their exact original
records, not whatever record the current head selects. A repeated already-saved
phone content version requests no duplicate chunks and preserves PC crops.

Local protected NativeMediaHistory format 3 pins each version's prior mapping
record together with the original job/destination/store witnesses. It is not a
wire capability or renewed Android READ. Admission rechecks current native review,
the selected frozen subset and fully saved earlier jobs; publication rechecks the
old target before storing the new file. Mixed new/version batches use the same
real source selection and worker. Missing history, corrupted/cyclic predecessor
chains and moved roots fail closed. A lost post-mapping receipt may be repaired
only from existing original save evidence, without re-publication.

Actual source-host checks include two successive phone changes, repeat/no-download,
old/new PC crop preservation, mixed batches, target collision, concurrent PC edit,
encrypted history restart, retained original receipts, malformed/version-chain
metadata and lost-receipt repair. Stop/resume retains the exact version job and
verified staged bytes. **Restart publication remains HOLD without positive native
proof that publication never began**; an empty journal or verified checkpoint is
not that proof. This remaining #330 acceptance boundary is not weakened here.
Installed/physical-phone acceptance, historical target re-association, deletion
directions and grouping remain open. Production readiness is still OFF.

### Own-PC withdrawal and superseded receipt replay (Refs #373, #330)

Both native file-authority adapters now retain the raw channel-scoped Own-PC
decision separately from legacy personal-sync normalization. An authenticated,
validated withdrawal revokes file authority before ACK output and still revokes
if that output fails. Positive evidence requires successful secure ACK output.
An exact current retry is harmless; a superseded positive receipt cannot undo a
later withdrawal. Only a new valid acknowledged decision can restore consent.
Expired, altered and replaced-channel messages cannot restore it. No stored peer,
pairing epoch, key, personal grant, source cache or save-history reset is involved.

The failures were reproduced independently through the actual Notes dispatcher
and desktop payload path before correction. Tests also cover a live Notes Gallery
runtime refusing further controls after withdrawal, failed ACK output, current
retry, older positive replay, altered/expired receipts and replaced channels.
These are source-host tests, not installed physical-phone acceptance.

### Integrated Organizer activation and native background READ (Refs #330)

The Organizer's Notes-only advanced photo controls now call the daemon-owned
native desktop session through the existing GTK bridge and Unix IPC. Availability
requires compiled handlers, the current authenticated own-PC channel and fresh
capabilities/grants/own-PC metadata observed after successful encrypted ACK writes.
Persisted capabilities, failed ACKs, personal-content consent and KDE identity are
not substitutes. Raw own-PC withdrawal closes file authority even where legacy
personal metadata normalization would otherwise retain an own-device flag.

Explicit activation of an existing pairing may add only its closed file epoch,
using the original native ciphertext, existing key, pinned staging descriptor,
consent rechecks and durable readback. It must not reconstruct PhoneStore, rotate
identity, rewrite unrelated peer preferences or remove unfamiliar staging files.
Only subsequent explicit file policy activation binds the protected destination,
mapping and job stores. Native Pictures defaults preserve existing custom targets.

The actual action lane joins controls, source configuration, native phone
permission notification, coverage-based album discovery and the real bounded
album worker. A permission reply itself never proves OS READ. Manual is the
default; mode-only writes preserve native grants, destination and baseline
bindings. A switch to Manual during active I/O stops future repetitions immediately
but commits protected mode only after real worker END. An idle scheduler is not
tray synchronization activity; actual grouped runs are. Repeated unchanged phone
media requests no duplicate chunks and preserves PC crops. Changed-phone conflicts
remain HOLD/conflicts, not a claim that version synchronization is complete.

Automatic reconnection reads existing protected policy without defaults, legacy
bootstrap or permission prompting. It waits for fresh current-channel ACK evidence
and resumes only an associated, enabled Automatic policy with existing destination
and storage witnesses. Revoked phone source consent is not re-enabled. Manual,
disabled and absent profiles start no photo session on reconnection.

Notes may create fresh background read leases from its existing app-wide OS READ
and current dedicated native file policy, without retaining an Activity. A live UI
binding takes precedence; attach/detach and native permission lifecycle changes
invalidate old access epochs. Permission requests remain Activity-bound. Lack of
access and incomplete/selected-only coverage never prove deletion. R8 retains the
private readiness field as well as the native runtime roots; discovery version 21
is advertised only when actual native readiness is enabled, never by branding.

Source-host evidence includes the extracted real GTK handler through real Unix
IPC, native metadata/control/source paths, actual file publication, repeat and PC
crop preservation; blocked-I/O automatic/manual transition; reconnection profiles;
whole existing JS UI suite; native background READ/Activity lifecycle tests; and
fresh F-Droid R8 DEX retention. These are not installed-package, physical-phone,
camera, microphone or mirroring acceptance. Production readiness stays OFF. Safe
phone-edit version execution, conflicts/deletions/grouping and platform/native
acceptance remain open under #330; camera/mirroring remain #244/#245.

### Notes dispatcher activation of the actual native Gallery runtime (Refs #330)

The Notes file dispatcher now calls the native runtime factory for a first valid
authenticated receiver control, instead of requiring a connection opened by a
test/controller beforehand. This path still has a private production-acceptance
gate which remains off; it is independent of ContributorKey and does not exclude
any Notes code from the APK. Source/status/data messages, malformed controls,
missing receive intent or missing authenticated identity cannot bootstrap it.

Explicit activation initializes only the existing relationship's closed file
metadata. It does not enable a source policy, Notes-content grants, Android READ,
scanning or synchronization. Configuration and fresh dedicated control echoes
remain necessary before the existing permission-notification path is usable.
The socket lane queues native UI construction outside the Werk monitor and
waits boundedly. Interrupted/late activation is revoked and cleaned up on the UI
lane; queued work rechecks exact transport ownership and handler readiness.
Control response writes stay encrypted on the socket lane, outside that monitor.

18 distinct Robolectric cases pass, including actual dispatcher activation,
legacy-metadata preservation, configuration/control echoes/permission notification,
interrupted and stale queued activation, and background-to-UI-to-encrypted-reply
thread ownership. These checks compile actual Notes sources; they are not an
installed APK, physical Android permission-dialog or phone/desktop acceptance.
Organizer production activation/UI and safe changed-phone versions remain open.

Notes' R8 rules now explicitly retain the native file/Gallery entrypoints and
their implementation, including in the unsigned F-Droid configuration. This
prevents currently closed production branches from stripping the required phone
components. The actual F-Droid minifyReleaseWithR8 task succeeds without a
signing-key environment or ContributorKey. Inspection of the resulting DEX finds
all 18 checked native entry classes and 168 native file/Gallery class definitions.
This is actual minified-code inclusion evidence, not APK packaging, installation,
runtime readiness, media consent or physical-phone acceptance.

### Native worker activity and book tray (Refs #330)

The actual native connection now always observes its album worker independently
of any frontend observer. PhoneService retains exact active worker owners until
their real worker END, including drain after a stop request. Foreign or repeated
END callbacks cannot hide a different active worker. Construction, pairing and
connection alone do not report synchronization activity. The daemon's existing
ticket path carries an opaque refresh event; GTK reads current native status
instead of trusting a delayed activity payload.
Ordinary phone-status refreshes also reread this state, so replacement of a
stopped daemon cannot leave the old worker's icon permanently active.

The existing book tray now draws circular synchronization arrows on its cover
and has a separate camera-in-book mark which can coexist with the arrows.
All three tray backends retain their notification labels/tooltips; icon-render
failure does not suppress those existing indicators. The camera producer remains
false: no native camera/audio/OBS integration is claimed by rendering its mark.
Tests include actual SVG decoding at tray size, native worker chunk-drain/END,
observer failure isolation and the daemon-ticket/frontend refresh path. These
are host/source integration checks, not installed tray/phone acceptance. Production
handler readiness remains off and no automatic or unsolicited run is enabled.

### Desktop build composition and private Linux Python layout (Refs #330)

Unconfigured Linux desktop source builds now omit the optional photo implementation
from their actual payload, not merely from visible controls. Prepared distribution
configuration and explicitly selected desktop composition are separate from the
user's runtime Contributor-Key: that user key remains branding-only and grants no
file, camera or microphone authority. Notes/APK composition is independent and must
retain the components needed by F-Droid distributions. No public activation recipe
is provided for optional desktop source-build features.

The always-present core blocks reserved file frames from personal staging/replay
without importing optional modules. Native factories and authenticated transport
bindings remain closed when the desktop composition excludes the implementation.
Composition rejects malformed profiles, unfamiliar payload edits, directory aliases
and stale compiled files instead of overwriting or silently shipping them.

Following Debian Python Policy §5.3, private pure-Python implementation files and
the actual application main now live under /usr/share/magnolie-organizer/python.
Only the small public starter remains in /usr/bin. Web/assets, locale and icon
locations retain their standard shared-data layout. The existing Debian helper
sequence now uses dh_python3 for private-module dependency/bytecode maintenance;
the package does not ship precompiled private bytecode. Personal account, pairing,
permission, draft and media locations are unchanged. CLI, resource finders and
background/autostart references resolve the same installation's public command.

75 distinct host cases pass: exact selected module closures and import origins for
all four Linux package layouts, real staged wrapper help/version, installed flag/
OR6 readers, prefix-local resources and service paths, prepared/default/explicit
Flatpak manifest ordering, source-archive replay, unknown-code preservation,
reserved-message isolation and affected native authenticated photo workers.
These checks use actual staged source bytes, not a newly installed native package.
Windows now also excludes its dedicated file/photo sources by default in an
unconfigured application build. Four actual MSBuild composition evaluations pass,
including malformed-profile rejection. The existing native Core host builds with
zero warnings/errors and passes eight dedicated-file, two photo-plan/schedule and
one destination test groups. Relationship-identity hashing is retained separately
and remains byte-compatible, so omitting optional implementations does not discard
stored pairing metadata. Compile-time camera selection is separate; it grants no
capture readiness or microphone permission. This is source-selection/Core-host
evidence, not a newly built/installed Windows application or native GUI result.
Final package/GUI/physical-phone acceptance remains separate work. No production,
automatic/UI/release gate is enabled.

References: Debian Python Policy, Programs Shipping Private Modules (§5.3),
https://www.debian.org/doc/packaging-manuals/python-policy/ ; dh_python3 private-dir
and maintainer-script handling, https://manpages.debian.org/trixie/dh-python/dh_python3.1.en.html .

### Explicit real desktop album worker (Refs #330)

An explicitly started native desktop worker now drives the full single-album
batch lifecycle through the existing authenticated dispatcher: source preparation,
media/offer correlation, real saved-target review, NEW-only subset selection when
needed, native Chunk receive/publication/mapping/Saved, verified cache retirement,
source cancel/END and exact next-batch continuation. Only one worker can own a
connection. Import, construction, pairing and passive status reads start nothing.
Unimplemented requested directions, deletion, video or grouping operations are
rejected rather than silently ignored. Unresolved changes are reported as conflicts,
not as a successful complete synchronization.

Activity callbacks identify the exact real worker owner and remain active until
its actual I/O ends, including cancellation. A UI stop sets a cancellation request;
checkpoint/readback/descriptor close run on an I/O lane, not on the UI caller.
An attempted Chunk must drain or reach its ordered source-cancel barrier before
receiver release. Cancellation preserves incomplete jobs and quota. Closing the
connection wakes a waiting worker; unknown command output is HOLD, not an implicit
retry or successful completion. An explicitly ended scan with unknown batch-end
metadata may be aborted but cannot be continued.

182 distinct host cases pass (seven new, 175 affected): actual worker first sync
over two batches, second scan with zero downloads and preserved PC crop/inode/
historical mappings, real Chunk-drain cancellation and retained quota, no duplicate
worker, empty album, truthful phone-change conflicts, connection-close cleanup,
unready-production rejection, unknown-end abort and affected receiver/source/stop/
batch behavior. These are actual desktop-worker host results, not an installed
GUI, automatic-scheduler or physical-phone acceptance claim. Production registration,
UI/tray wiring, platform acceptance and safe changed-phone-version execution remain
unfinished. Production/automatic/UI/release gates remain OFF.

### Native whole-album batch ownership and desktop continuation (Refs #330)

The explicit batch source path now uses the actual existing single source worker.
It prepares smaller 16-member working batches within the unchanged 128-file/
400-MiB manifest limits, retaining a native scan position across separately frozen
source/transfer/run identities. A correlated batch_end field distinguishes a
current-end observation from an incomplete batch; neither is deletion evidence.
An empty batch creates no fake manifest, stage or Saved receipt.

Continuation requires the exact preceding native run's real stopped-I/O END and
actual source-cache retirement. An accepted-but-unsaved batch remains held;
metadata END alone cannot advance it. Explicit new-photo subset selection retains
the same album position, and only the selected source's complete authenticated
Saved/END permits the next batch. Lost command/output retries retain the same
new source worker owner. Separate source/resume starts cannot interleave while
the batch scan is owned. Explicit album stop releases only the ended scan, never
unconfirmed caches, original photos or save history; its held reply can be retried
without stopping a newer scan.

The desktop now preserves batch identity and source namespace across confirmed
END/continuation, requires a fresh native action/current policy for continuation,
and rejects reused owners, missing batch metadata or substituted media scopes.
Actual native download/publication/mapping/cache-retirement paths are reused for
new files; known photos and PC edits remain at their historical mapped targets.

196 distinct host cases pass (12 new, 184 affected), including real 16/1 native
sources, selected-source offer/acceptance/Chunk/Saved/END and next source, unsaved
cache hold, empty source, explicit stop and lost-output replay, actual desktop
known/mixed/new batches with immutable old PC edits and zero completed-cache
reservation, plus affected source/worker/runtime/review/selection/history tests.
These are native host integration results, NOT installed GUI or physical-phone
acceptance. Production registration, the UI-driven whole-album worker, complete
changed-photo handling and platform acceptance remain unfinished. Production,
automatic/UI and release gates are unchanged OFF.

### Explicit bounded native album inventory batches (Refs #330)

The Gallery reader offers an explicit in-process batch API in addition to its
unchanged all-or-fail whole-inventory API. Each batch obeys the existing 128-file,
400-MiB, provider-page and query-time bounds. A reader/exact-native-lease-bound
keyset continuation points after the last INCLUDED row; a size/count lookahead
does not consume the next member. Every continuation rechecks native authority,
permissions, cancellation, album/provider metadata and ordering. Neither reaching
the current end nor an empty batch proves deletion: MediaStore is a live source,
not an atomic full-album snapshot.

The native workflow can freeze consecutive batches into actual separately reserved,
encrypted and read-back source jobs. Its preceding source must be explicitly
retired before it prepares another. Empty batches allocate no transfer job; errors
after potentially committed I/O do not implicitly retry reservations. Scan close
requests cancellation without waiting for blocked provider I/O or pretending that
I/O ownership ended, and never deletes photos or private caches itself.

16 distinct host cases pass (six new, ten affected), including 300 exact members
across 128/128/44 inventories, byte-boundary lookahead, foreign/revoked/canceled
continuations, actual encrypted 128/2 native sources with prior-cache admission
guard, empty inventory, blocked-provider cancellation and affected original
inventory/workflow/frozen-selection behavior. Production run commands, desktop
whole-album iteration and installed phone/UI acceptance are NOT connected by this
step; their readiness/automatic/UI/release gates remain OFF.

### Completed-cache capacity without dropping save history (Refs #330)

An explicit native finish can now retire only a fully saved receiver's exact owned
publication/staging caches after complete post-mapping receipts and checkpoint
readback. An immutable catalog receipt binds the original job record, accepted
context, saved-mapping hash and actual native cache identities. Both original cache
locations must be absent before protected membership commits a zero active byte
reservation. Unknown entries, reappeared caches, missing receipts or commit failures
remain HOLD, not successful quota release. Original job records, index checkpoints,
save/mapping history and public photo inode/bytes are retained.

Historical metadata is bounded separately at 128 jobs within the existing metadata
byte ceiling; the configured active-job and active-byte limits are unchanged. A
historical retired job cannot reopen a receiver stage, but current native authority
can still read its historical receipts and review the real saved target. Phone END
can dispose of an exact stopped source cache once its complete authenticated Saved
proof exists (or if it was never accepted), never original phone media.

102 distinct host cases pass (six new, 96 affected): real publication/cache absence/
fresh catalog read, original receipt/history and next unchanged review, a single
active slot reused without dropping historical jobs, foreign cache preservation,
missing/reappeared proof rejection, failed membership commit, actual phone Saved→
cache cleanup and affected catalog/receiver/review/selection behavior. This is not
an automatic global sync-completion claim or a physical phone/UI acceptance result.
Album batching and actual runtime/UI/platform integration remain unfinished; gates
for production/automatic/UI/releases are unchanged OFF.

### Mixed ordinary album: explicit frozen-member selection (Refs #330)

select_run binds an exact unaccepted current preview run/manifest to a bounded,
sorted, distinct list of its opaque member IDs. A new actual single-worker source
copies only those protected frozen bytes into a separately reserved/read-back native
snapshot with new source/transfer/run identities, preserving original photo origins
and content hashes. No provider reopen, old accepted-head mutation or PC-file adoption
occurs. Only the never-accepted preview cache is retired after the selected snapshot
commits; accepted jobs and original phone photos remain untouched. Held command replay
returns the same new owner after lost output, never another selection worker.

The desktop derives that selection from a fresh native review's NEW photos only.
Selected results must use a new owner; subsequent media/photo IDs, source namespace,
media kinds and exact subset manifest must match the original selection before
ordinary native admission. Known PC edits remain at their original mapped targets.
165 distinct host cases pass (seven new, 158 affected): real native frozen-member
copy/next offer/acceptance/Chunk with provider reopen forbidden and lost-reply replay,
strict ID lists, actual mixed desktop publication of only the new photo, existing
PC crop/inode/mapping preservation, next full scan without downloads, and foreign
member/photo/owner rejection plus existing codec/source/review compatibility.
Large-album batching, changed-photo execution and actual UI/phone/platform integration
remain unfinished. No capability/readiness/automatic/UI/release gate is enabled here.

### Ordinary repeated-photo review and normal source completion (Refs #330)

The native desktop now compares the fresh phone manifest with the ORIGINAL protected
save/mapping receipts and current descriptor-bound target bytes before considering
another download. Known unchanged photos and local PC edits require no image data;
missing/unmanaged/replaced targets and competing/unproven changes remain explicit
non-writing decisions. Matching bytes alone never adopt an unknown target. Review
opens no receive stage, reserves no new receiver job and changes no baseline/mapping.

A fully saved local receiver can close only after complete post-mapping evidence
and checkpoint readback; its original job/receipts/quota remain available. The exact
stopped ordinary source owner can end with a correlated end_run result and immutable
bounded output retry. Only that owner's never-accepted disposable scan cache is
retired; accepted jobs and original phone photos remain untouched. Source END is not
a remote Saved acknowledgment. An unchanged scan can therefore finish and a third
scan start without duplicate PC files or accumulating unaccepted scan caches.

192 distinct host cases pass (nine new, 183 affected): actual first native publication,
second/third unchanged scans with ZERO new Chunk requests or stage allocation,
current target inode/bytes/mapping/original-job preservation, PC edits/missing/
replacement and phone/edit conflicts, exact normal END result types and native
never-accepted-cache cleanup with lost-response retry while a new owner exists.
This is a tested native controller path, not installed GUI/phone interoperability.
Mixed known/new-photo selection, changed-photo execution, album batching, automatic
controller/UI and platform acceptance are not completed by these review decisions.
Production/automatic/UI/release gates remain OFF pending the actual integration.

### Explicit ended-owner abandonment and new attempt (Refs #372, #330)

The connected native repair path now requires the desktop's actual receiver-stop/
checkpoint/close record, correlated source-END confirmation, fresh exact original
lookup and a new native action. Tokens or expired messages alone cannot request it.
The phone requires its actual ended-owner job/head/run record, current native peer/
policy/original binding, no Saved proof and true worker quiescence with no active
normal/resume owner. A bounded immutable protected abandonment ledger retains the
complete old head and exact command before reply. Transactions/readback and exact
head CAS precede replacement; lost output retries the same command/receipt.

Only an explicitly new native source/attempt can replace an exactly archived head;
the original manifest/acceptance/job/checkpoint/media history/quota is unchanged.
Eight historical receipts per job are retained without eviction; full or uncertain
history HOLD. A source run ID already ended on the desktop cannot be revived as a
new owner. Stop/abandonment receipts are not READ/Saved/baseline grants.

275 distinct host cases pass (15 new, 260 affected), including real native commit/
fresh-read/next-offer/acceptance/Chunk, rollback/sync loss, active-owner rejection,
desktop stop/END/receipt/new-owner/original-checkpoint join, false receipt fields,
lost output and existing membership/attempt/source/lookup compatibility. This is
the proven same-runtime ended-owner path, NOT recovery from lost native stop/END
proof after restart or from arbitrary pre-receiver pending heads; those remain HOLD
under #330. Physical phone testing, ordinary repeat-sync/UI/platform integration
remain separate acceptance work. No readiness or release gate is enabled here.

### Local resumed-receiver stop/checkpoint/close (Refs #371, #337)

An explicit native action can mark only the actual resumed receiver for local stop
without waiting behind socket or stage I/O. New output/publication/request admission
is blocked; already admitted work retains its native resources until actual return.
An attempted outstanding request must drain through its correlated Chunk or an
ordered, correlated canceled_held/source-I/O-ended reply before local closure.
Uncertain socket output is not treated as an unsent request or silently discarded.

After quiescence the runtime commits/reads back the actual receiver checkpoint and
closes descriptors before releasing the local receiver owner. Failed checkpoint,
revocation or uncertain/prior close keeps failed ownership rather than manufacturing
successful cleanup. Stop metadata grants neither Saved, baseline, repair nor quota
retirement; the source owner and original job/history/quota remain held. A late
duplicate is discarded without reopening the stage only after strict correlation,
current native binding and equality with the previously accepted Chunk hash.

100 distinct host cases pass (13 new, 87 affected): blocked actual stage/socket I/O,
pending drain/cancel barrier, checkpoint-before-close-before-owner-release, output
preflight stop, uncertain cleanup, revocation, changed/foreign duplicates and normal
versus resumed ownership, plus existing receive/source/lookup/END compatibility.
These native host fixtures do not establish physical phone/network acceptance.
Coordinated pending-head abandonment/receipt/CAS, overall convergence, UI/platform
acceptance and production readiness remain unfinished; all release gates stay OFF.

### Opaque exact pending-head identity, not repair authority (Refs #370, #337)

Authorized historical lookup now includes an existing attempt's exact native UUID
and domain-separated canonical protected-record hash alongside its phase. Both
tokens are null when no head exists; neither identity is inferred from a receiver,
clock or row enumeration. The hash is stable on fresh reads and changes with actual
protected phase content. No new persisted row or original consent/version rewrite
is introduced. Tokens reveal no native paths, read grants, keys or cipher witnesses.

Linux requires both typed tokens for pending history. Older no-head metadata can
remain non-granting history; older pending history without exact tokens stays HOLD.
All prepared/sent/accepted heads still block a new source attempt regardless of
tokens. 146 distinct host cases pass (nine new, 137 affected): actual phase commits/
fresh-read identity/no-run adoption, privacy/no-head fields, strict token combinations
and original desktop lookup/source/END compatibility. This does NOT abandon/delete/
repair a head or grant READ/run/data authority; explicit peer-coordinated quiescent
repair with durable receipt/CAS is still required. Production/UI/releases stay OFF.

### Exact remaining monotonic negotiation/media TTL (Refs #369, #337)

Three native reproductions confirmed that short or partly elapsed offer/media
lifetimes retained a full 60-second monotonic window if wall time stopped. This
included an actual renewed native source with durable prepared head allowing short
offer output past its intended monotonic expiry. No file-data disclosure or loss
claim is established by the offer/metadata reproduction.

Resume attempt, wire attempt and media attempt now bind only the first remaining
message lifetime, capped at the existing maximum. Retries cannot extend that deadline;
expiry/rollback stays sticky. Negative/exhausted wall origins reject. Original
acceptance/offer records are not rewritten, and accepted data runs still use fresh
request lifetimes instead of an expired negotiation message as their authority.
82 distinct host cases pass (four new, 78 affected), including actual protected
native output prohibition, short/partly elapsed frozen-wall boundaries, immutable
retry, default TTLs, wire/media/native source/offer/data/END ownership compatibility.
Pending-head repair and overall UI/platform/physical acceptance remain unfinished;
all production/automatic/UI/release gates remain OFF.

### Explicit stopped resume-source END, not job retirement (Refs #368, #337)

end_resume now releases only the exact stopped native source owner after actual
worker quiescence and preparation I/O END. The bounded exact end command/result is
held before owner release; lost reply retries that immutable metadata receipt rather
than ending another run. Foreign/changed/stale commands, pending provider I/O and
expiry reject. run_ended=true is valid only for this exact end result, never for
ordinary status/cancel or as Saved/baseline/quota retirement.

Linux releases its private source owner only after the correlated end confirmation,
keeps the protected original job/stage/checkpoint/quota, clears only pending source
metadata and requires a fresh original lookup for another resume. Late old resume
offers cannot fall back to standalone admission after END. An active receiver stage
is not implicitly closed by a source-END action.
160 distinct host cases pass (13 new, 147 affected): actual blocked native PFD END,
same-receipt retry while another owner is active, expiry/clock fences, Linux lost
command/result/strict end-state behavior, original job preservation, active-stage
refusal, canonical shared end vector and existing source/ownership compatibility.
Safe pending-attempt repair, receiver data-stop/normal source-END integration, UI,
Windows/Apple and physical acceptance remain unfinished. Production gates stay OFF.

### Linux native resume source/history/receiver join (Refs #367, #337)

An explicit resume_run can now use only the bound original native lookup selection,
current album choice and a sealed, unsaved phone history with NO persisted attempt
head. Prepared/sent/accepted unknown heads remain HOLD, not expired/adopted. The
original protected desktop media/mapping anchor is required before sending new
source work; missing legacy history cannot be reconstructed from fresh pages.

The desktop holds a private resume-source owner and separates resume status/cancel/
media/offer from normal commands. Fresh media pages must match the original native
manifest; only explicitly requested resume offers with that exact manifest correlate.
Before original stage resume, existing protected history/source namespace/photo IDs/
media kinds, mapping store, destination and accepted binding are verified again.
Original acceptance fingerprint, job/quota and history are not replaced or reserved
anew. This joins existing native receiver restore rather than bypassing it.

80 distinct host cases pass (16 new, 64 affected): actual protected catalog reconnect,
lookup/source/media/new-offer through original checkpoint restore, only missing-file
requests, same acceptance on lost-output retry, foreign media/manifests, normal-path
fallback rejection, cancel rollback, legacy missing anchors and saved/retired/pending
head HOLD, plus normal source/media/lookup compatibility. Host service/channel
fixtures are not physical Android/Linux interoperability acceptance. Safe pending-
head repair, UI, Windows/Apple parity, baseline/conflict convergence, migration/
classification and physical acceptance remain unfinished. All production/auto/UI/
release gates remain OFF.

### Current native resume media pages (Refs #366, #337)

resume_media_page now requires the exact active native resume owner, real completed
source renewal and current READ/index/control authority. A shared normal/renewed
projection reads only frozen original manifest/origins and protected animation bytes;
stable photo/source namespace and media kinds are unchanged. No MediaStore/PFD scan,
new source job or source/destination mutation is performed. Pages hold at most eight
entries and exact run/cursor/request correlation; failed output retains its metadata
attempt, while observed clock/expiry/revocation prevents late success or revival.

Linux command/result codecs require explicit expected resume operation and reject
cross-normal replies. A sixth canonical shared vector covers the request. This is
metadata for original-association reconciliation, not camera/semantic classification,
READ authority, stage resume, Saved or deletion proof.
224 distinct host cases pass (14 new, 210 affected): exact original-versus-renewed
page comparison, no new provider access, nine original files across bounded pages,
lost-reply retry, changed/foreign/cursor/lifecycle rejection, shared codecs and normal
native video/animation/source/offer/data behavior. Desktop source-resume/history/
receiver join, pending-head repair, UI/platform/physical acceptance remain open.
Production/automatic/UI/releases remain OFF.

### Linux native original-job lookup action (Refs #365, #337)

A separate explicit native lookup action now selects an existing protected receiver
job, verifies current binding/destination/policy/catalog and source control echo,
and derives the phone lookup request from that original manifest. It creates no
catalog/job/stage and excludes active receive/source owners. The immutable pending
request and ticket precede actual output; retries revalidate the same native job.
Replies require exact request/policy/manifest and original-job ownership before
projecting historical hints. Wrong/replayed/expired/unsolicited replies HOLD.

92 distinct host cases pass (14 new, 78 affected): actual native service/catalog
reconnect ownership, original manifest request, no stage resume/allocation, exact
lost-send retry, foreign/deadline/authority/replay rejection, expired output, changed
original job and active/foreign action guards, plus normal source/connection/receive
paths. The original catalog record/quota and existing publication-journal identities
are retained. Test channels are native-owner fixtures, not physical network/phone
acceptance. Generic incomplete lookup emission stays blocked; historical projection
does NOT open a resume run, accept an offer, read data or retire quota. Resume-source/
fresh-media reconciliation, pending-head repair, desktop UI/Windows and physical
acceptance remain unfinished. Production/automatic/UI/releases remain OFF.

### Exact original-manifest historical lookup (Refs #364, #337)

Android's private source-job ID is independently generated, not the manifest source
ID. A guarded resume_lookup can now correlate the exact original source/transfer/
manifest hashes to one authenticated historical job/version under the current native
sender, receiver identity, nonmissing pairing, permission and policy epoch. Unknown,
ambiguous, legacy or foreign bindings HOLD. Lookup opens no cache, MediaStore/PFD or
permission host and creates no reservation/run/attempt/READ authority.

Its bounded reply carries only original job/version/phase and historical saved/
attempt-phase hints. Even accepted/retired metadata is NOT readiness or adoption
authority. Private paths, read tokens, keys and cipher witnesses are not transmitted.
Linux strict lookup/result codecs correlate those fields; a fifth shared canonical
Android/Linux vector covers lookup. NativeDesktopFileConnection remains unjoined
and refuses incomplete native lookup/resume emission rather than granting rights.

142 distinct host cases pass (25 new, 117 affected): actual authenticated Android
lookup without photo READ/host/cache, foreign original/source/peer/pairing/permission/
policy rejection, accepted-head and retired-history no-adoption, shared vectors,
Linux strict history/extra-authority rejection and source runtime/parser compatibility.
This is not desktop receiver/source-run reconciliation or safe pending-head repair.
UI, Windows parity, global convergence and physical acceptance remain unfinished;
production/automatic/UI/releases remain OFF.

### Linux resume source metadata codecs and shared vectors (Refs #362, #337)

Linux source codecs now encode/decode the same four explicit resume commands and
strictly correlated run results as Android. Exact original job ID/version and opaque
catalog/album or run identities remain metadata, not READ/Chunk/Saved grants. Extra
authority/path fields, wrong types, unused builder options, cross-normal/resume
operation responses, stale results and inconsistent I/O states reject. The shared
four canonical command/hash vectors are verified by both Linux and Android.

99 distinct host cases pass (34 new, 65 affected): strict codec vectors/type/expiry/
correlation cases, actual existing Linux source runtime compatibility and explicit
refusal to emit unfinished native resume commands, plus Android shared-vector
validation. NativeDesktopFileConnection and its readiness gate are unchanged; this
codec step does NOT implement desktop receiver resume/acceptance/reconciliation,
Windows parity, UI or physical acceptance. The separate general Python UUID None-type
defect was confirmed and fixed in #363: non-string values reject before UUID
construction. 224 targeted host cases pass (15 new, 209 affected), including missing/
non-string IDs, canonical/version rules and protocol/source/offer/acceptance/native-
authority/media/history callers. No data-loss or privilege-escalation claim is
established by this validation fix.
Production/automatic/UI/releases remain OFF.

### Current-owner native transfer dispatch (Refs #361, #337)

The existing authenticated TelefonWerk file lane now forwards acceptance/Chunk/
Saved messages to one runtime dispatcher. Under its existing single operation gate,
the dispatcher selects ONLY an already-owned resume run or the existing normal-run
path. Neither packet IDs nor historical accepted heads create/select/adopt a run.
Missing, preparing, canceled, revoked or exited owners reject through the same
strict native handlers. Direct normal APIs remain normal-only. Shared normal/resume
handler bodies execute once under the runtime gate, never under the Werk monitor.
Existing native current-channel/peer/generation checks remain before dispatch.

TelefonWerk also retains the bounded resume-start replay ledger beside the normal
ledger across native runtime ownership changes, rather than creating it from wire
or disk metadata. No discovery/readiness/automatic/UI gate is enabled.
58 distinct host cases pass (three new, 55 affected): actual native controls and
source commands through new offer/acceptance/Chunk/Saved dispatcher flow, encrypted
bytes and durable historical proof, normal dispatch compatibility, accepted disk
history without a run, preparing/stopped/revoked ownership and affected native
offer/data/source/permission paths. TelefonWerk wiring is compiled against these
native APIs; full installed TelefonWerk/network/phone lifecycle acceptance is NOT
established by the runtime fixtures. Desktop counterpart, pending-head repair,
baseline/conflict convergence/migration/classification, UI and physical acceptance
remain unfinished. Production/automatic/UI/releases remain OFF.

### Guarded immutable resume offer command (Refs #360, #337)

offer_resume now addresses only the exact active native resume run. Its complete
command envelope/request ID/digest is held before durable offer preparation; lost
offer or result output can retry only that same command and offer. Another request,
changed envelope, wire-to-native fallback or native-to-wire adoption cannot rebind
the attempt. A new offer is bounded by remaining command lifetime, not historical
negotiation TTL. Real prepared/sent metadata and current configuration/peer/source/
clock checks still surround actual encrypted output and the metadata result.

Observed rollback/expiry stays sticky even if response authority/output fails first;
restoring wall time cannot revive acceptance. Transport failure alone preserves
exact retry. Result output is not acceptance, Saved, quota retirement or readiness.
73 distinct host cases pass (five new, 68 affected): TTL clamping, real encrypted
offer/result ordering, lost offer/reply retry, request rebinding/fallback rejection,
reply rollback/exit/expiry and preparing/canceled owners, plus affected native
attempt/offer/Chunk/Saved/source/parser/normal ownership cases. Normal handlers
remain separate. Generic resume acceptance/Chunk/Saved transport dispatch, desktop/
UI, pending-head repair, convergence and physical/platform acceptance remain open.
Production/automatic/UI/releases remain OFF.

### Explicit resume source start/status/cancel commands (Refs #359, #337)

The guarded source-command parser/runtime now accepts resume_run with exact
original_job_id/version plus a current native catalog/album selection, and
resume_status/cancel_resume with exact active run ID. Configuration ticket,
protected policy CAS, current peer/pairing and command expiry guard actual responses.
Unknown original jobs, saved history and untyped/path/READ-claim fields cannot launch
provider work. The existing single worker still performs real native source checks.

A separate bounded process-local replay ledger records start intent before launch;
lost replies repeat the same runtime-owned run, not a new worker/job. Changed request
contents, foreign owners, failed prior starts and clock rollback reject. Expired
requests do not poison independent valid future commands. Cancel reports pending
versus real I/O-ended held state; neither response releases quota or claims whole
sync success. An ended/stopped run cannot be silently recreated by replay.

30 distinct host cases pass (six new, 24 affected), including actual protected
controls/native discovery/encrypted replies, lost reply/replay, blocked-PFD cancel,
invalid original/type/path fields, reply expiry/exit, foreign/failed starts, bounded
64-entry ledger/clock fences, parser/normal-run compatibility and native direct
offer/ownership fixtures. Resume offer/acceptance/Chunk/Saved are NOT dispatched by
these commands; source-command transport registration, desktop/UI, pending-head
repair, convergence and physical acceptance remain separate unfinished work.
Production/automatic/UI/releases remain OFF.

### Durable native resume Saved observation (Refs #358, #337)

An explicit native Saved API now validates the actual accepted resume run/source,
current READ/peer/lifecycle and exact durable child acceptance before accepting a
fresh complete saved envelope. The new negotiation command digest does NOT replace
the original acceptance. The historical saved record retains original accepted
job/context/offer/command bindings after checking the real child acceptance, and is
committed with membership before its RAM result. Same proof repeats are immutable;
different receipts/bindings reject. Only this Saved path allows an already-saved
original for idempotence; offer and Chunk paths remain blocked by saved history.

No automatic run END, cache cleanup/quota retirement, baseline or ACK follows.
Transaction failure rolls back without success; lost sync or exit/expiry after commit
can leave a readable historical proof but no run success or adoption authority.
21 distinct host cases pass (six new, 15 affected): actual encrypted Chunk then Saved,
original versus new command digest preservation, exact proof-before-RAM inspection,
idempotence/conflicts, foreign/binding/receipt/expiry rejection, transaction retry,
postcommit sync loss and during/after-commit exit/expiry, plus existing offer/Chunk
ownership and normal runtime routes. Jobs/ciphertext/original consent/quotas stay
held. Wire/source-command/UI, pending-head repair, convergence and physical/platform
acceptance remain unfinished. Production/automatic/UI/releases remain OFF.

### Explicit native accepted resume Chunk output (Refs #357, #337)

A separate native-only Chunk API now requires the exact active resume run and its
in-process acceptance projection, actual renewed source, and matching durable
accepted attempt ID/envelope. Historical acceptance is decoded only at its original
protected observation time to compare that binding, not to create current authority.
A stored head or standalone projection without active runtime binding grants no
data output. Normal incoming routes still do not dispatch to resume runs.

Each Chunk request supplies its own fresh bounded lifetime and exact original
transfer/manifest/acceptance/permission/destination/member binding. Current native
READ/peer/lifecycle/index and accepted-head checks surround protected cache reading
and actual output; request wall rollback, monotonic rollback/expiry and cancellation
reject success. The accepted run is not extended by rewriting old offer/acceptance
TTLs, nor incorrectly stopped merely because those negotiation messages expired.
The plaintext byte buffer is cleared in finally. Output already handed to transport
is irretractable and remains neither Saved, baseline nor a quota-retirement receipt.

Eight distinct host cases pass (seven new, one affected actual normal runtime route),
including encrypted original frozen bytes after negotiation TTL, standalone/foreign
projection rejection, binding/member/expiry failures, output-time cancel/exit/expiry/
wall rollback, pre-output expiry, damaged cache/lost accepted head and complete
historical Saved HOLD. Original jobs/proofs/ciphertext/quotas remain held. Resume
Saved commit, wire/source-command/UI registration, pending-head repair, convergence
and physical acceptance remain unfinished. Production/auto/UI/releases remain OFF.

### Actual native resume-run offer/acceptance handoff (Refs #356, #337)

The exact active resume run now keeps one native attempt before durable preparation
or output. Actual renewed source ownership, original index identity, completed I/O
and worker quiescence are required; known complete remote-saved history rejects
before allocating an attempt. Failed preparation/output retries that same attempt
and envelope, never a stored or newly generated replacement. Native preparation,
sent and accepted commits precede their corresponding runtime projections.

Acceptance is stored on the exact run only after durable accepted commit and
post-I/O native source/lifecycle/expiry revalidation. Foreign, preparing, stopped,
expired and exited runs cannot publish success. A durable accepted head left after
exit/expiry remains historical and non-granting, not an automatically adopted run.
Normal acceptance/Chunk/Saved routes still require normal sync ownership; no packet
silently creates or selects a resume run. Original jobs/proofs/ciphertext/consent,
historical TTLs and quotas remain unchanged.

40 distinct host cases pass (seven new, 33 affected), including actual native
configuration/control/permission host, original encrypted offer and acceptance then
stop BEFORE Saved, genuine PFD/cache renewal, encrypted resume output and exact lost
output retry, transaction rollback, postcommit exit/expiry with no run projection,
foreign/preparing/canceled owners, known-saved HOLD and normal runtime/worker paths.
The projection still explicitly allows NO Chunk output. Resume Chunk/Saved ownership,
source-command/wire/UI registration, pending-head repair, global convergence and
physical acceptance remain unfinished. Production/UI/automatic/release gates OFF.

### Whole native resume preparation ownership (Refs #355, #337)

An explicit native resume run now owns the actual original-job preparation through
the SAME single source worker used by normal freezes. The worker can return an
actual renewed local source without reserving/freezing a new job. Pending I/O never
publishes that handle. Cancel/close requests do not clear its slot; only real prepare
return with descriptor cleanup marks I/O END and releases worker ownership.

Normal sync, resume and standalone preparation are mutually excluded by the native
runtime. Whole resume ownership remains held after worker completion until the exact
run is explicitly stopped and its real I/O is quiescent. Foreign/stale owners and
historical recovery while a run is held reject. Exit/revocation retains source index
ownership until blocked provider I/O actually ends; no late readable handle appears.
Failed preparation neither finishes a sync nor removes originals/proofs/quota.

33 distinct host cases pass (two new, 31 affected), including real blocked PFD worker
renewal/close, actual native runtime cancellation, completion-held ownership, failed
live-byte validation, foreign/invalid original job, both overlap directions, stopped
END checks and deferred connection release during blocked resume. Normal worker,
runtime/control/offer fixtures also pass. No resume offer/acceptance/Chunk/Saved or
source-command/wire/UI handoff is added by this owner component. Those integrations,
pending-attempt repair and global convergence/physical acceptance remain unfinished;
all production/UI/automatic/release gates remain OFF.

### Durable bounded resume-attempt phases (Refs #354, #337)

The native metadata attempt now MUST prepare a protected immutable offer head
before any output. Separate prepared/sent/accepted phases mean respectively no
output proof, actual callback completion plus revalidation, and a fresh correlated
acceptance. Each stage commits with aggregate membership in the same SQL transaction
and sync/readback before its RAM success. No original job/acceptance/cipher/consent
or quota is rewritten. One bounded attempt row per actual original job is allowed.

Same live native attempt/base is idempotent. Another generated attempt identity
cannot adopt a persisted head, even after expiry; historical JSON read creates no
live owner/clock/READ/Chunk grant. A pending/uncertain old attempt remains HOLD for
separate explicit repair. Missing/damaged rows remain integrity failures. Proven
final cache retirement deletes original proofs, resume head and job together;
rollback preserves them and the retired quota reservation together.

184 distinct host cases pass (eight new, 176 affected), including all three phases'
SQL/Sync failure and permission/expiry boundaries, fresh historical inspection with
no adoption, output prohibition without durable preparation, immutable retry,
typed/context/phase-bypass rejection, and final retirement rollback. Earlier native
offer fixtures now explicitly perform real native durable preparation, not a guard
override. Accepted proof/projection still explicitly grants NO Chunk output. Whole
resume-run/worker/Chunk/Saved ownership and runtime/wire/UI integration remain
unfinished, as do global convergence and physical acceptance. Production gates OFF.

### Separate bounded resume-offer metadata attempt (Refs #353, #337)

A new explicit native component prepares ONE immutable fresh offer from an actual
renewed local source. It does not renew the historical offer/acceptance. Lost output
can retry only that exact envelope; observed expiry, wall/elapsed rollback, cancellation
or source revocation is sticky. Output ownership is nonreentrant and cancellation
does not wait for a blocked write. Post-output validation prevents a late success;
bytes already handed to transport cannot be retracted.

A fresh acceptance must correlate to the new offer while retaining EXACT original
transfer/manifest/acceptance-hash/permission/destination bindings. Changed fields,
historical offer IDs and alternative acceptance envelopes cannot silently rebind.
The returned projection explicitly grants NO Chunk output. Durable attempt CAS is
now enforced as described above; whole run ownership, Chunk/Saved/baseline handling,
runtime/wire/UI registration and automatic scheduling remain absent and mandatory
before production use. It never writes original job/proof/ciphertext/quota.

Nine distinct host cases pass (eight new, one affected workflow): actual native
renewed sources, historical TTL expired before a NEW offer, exact failed-write
retry, original binding conflicts, clock/expiry stickiness, output revocation/cancel,
blocked-write/reentrancy/cancellation fences, invalid native clocks and unchanged
original metadata/ciphertext. These are native metadata-component fixtures, not
complete resume or installed/physical acceptance. Production/auto/UI/releases OFF.

### Explicit local-only renewed cache read (Refs #352, #337)

After complete fresh native PFD/identity inspection, an explicit selection may now
reopen the original encrypted source cache for local READ only. The authenticated
historical source context supplies the original cipher associated-data namespace,
not permissions. The gate retains the ACTUAL fresh native Gallery lease/scope,
current workflow binding and exact original index/job/acceptance evidence. No old
lease/owner object is deserialized and no original job, consent, ciphertext, key,
epoch, proof or quota is rewritten. Normal restore/withSealedHead remains strict.

Original root/file witnesses, exact entry inventory, encrypted owner/manifest and
all original plaintext hashes are read back before returning a handle. Creation is
monotonic-bounded; subsequent local reads require current native permission/lifecycle
and original metadata. Missing/corrupt/unknown cache contents HOLD without repair.
Revocation/exit prevents further reads. These remain frozen historical bytes, not
a current-live-file-presence claim; later live edits are never overwritten.

The distinct read-only handle has NO offer/acceptance/wire/publication/retirement
API and explicitly permits no offer output. It does not start/resume a sync run or
rebind original acceptance/offer TTLs. 77 distinct host cases pass (five new, 72
affected), including actual fresh workflow/off-main inspection then separate local
renewal, unchanged original ciphertext/job/proof, normal restore still rejecting
old context, altered live bytes, cache loss/corruption/unknown entries, revocation,
exit and preparation expiry/clock rollback; normal snapshot/index paths also pass.
Fresh bounded resume-offer/acceptance attempts, runtime/wire/UI ownership and global
convergence/platform acceptance remain unfinished. Production/auto/UI/releases OFF.

### Native live-source resume inspection, not renewal (Refs #351, #337)

An explicit fresh native album selection can now inspect the original sealed job
against actual current READ-only source PFDs. Original job/acceptance/context proof
is checked before enumeration and repeatedly during inspection. Current sender,
peer identity/pairing/permission/policy/source key must match; original photo IDs
and native members, paths, sizes and every original byte hash must match. Renames
are conservatively HOLD pending reconciliation, not copied to a new path. Unknown
or rebuilt media namespaces, selected-only coverage, missing/changed original bytes,
revocation/cancellation and expiry cannot yield a matching inspection.

This bounded off-UI inspection writes no cache/job/proof/quota, does not open the
old cache, and never treats a scan as deletion evidence. Metadata/index locks are
not held over provider reads; original membership and live source freshness are
rechecked at read boundaries. The returned point-in-time comparison explicitly
allows no Chunk output and proves no deletion. It is NOT a renewed source lease,
fresh offer/acceptance attempt, baseline or production readiness.

Nine new host cases pass, including fresh workflow/owner/lifecycle and explicit
selection with the old cache unavailable, actual off-main PFD verification, original
proof preflight before enumeration, unchanged quota, real byte edits, missing/renamed
members, unknown/rebuilt namespaces, selected-only visibility, pairing/local identity,
expiry and cancellation/revocation. Actual restart cache-READ ownership, bounded
resume-offer/acceptance attempts and global convergence remain separate unfinished
work; all production/UI/automatic/release gates stay OFF.

### Explicit historical confirmation recovery after fresh open (Refs #350, #337)

A one-use, monotonic-bounded native action selects an exact original sealed job
with complete original format-2 acceptance/context proof. Its current authenticated
receiver must match original identity, nonmissing pairing and permission epoch;
channel-owner changes, expiry/clock rollback, revocation, retired/stale jobs and
foreign action owners reject. Actual native runtime issuance/recovery excludes an
active sync/source run. An incoming message alone cannot issue this action.

Only a fresh complete correlated saved envelope can then be committed/read back
through the existing proof/membership transaction. No source lease, permission-host,
MediaStore/PFD/cache/stage/offer/Chunk access is opened or renewed. No ACK, baseline,
deletion or quota retirement is emitted. Same historical proof remains immutable;
conflicts and lost original evidence HOLD. Sync loss reports no success; an exact
fresh inspection/action can subsequently observe the actual committed proof.

154 distinct host cases pass (nine new, 145 affected). These include new proof commit
after fresh index opening with the cache unavailable and live source disabled;
actual fresh runtime/control agreement without a permission host then idempotent
historical replay with the cache unavailable; one-use/identity/pairing/channel-owner,
expiry, permission loss during transaction, rollback/sync loss, conflicts and exit.
The runtime API is not registered as a wire handler or exposed in the UI. This does
not resume source READ/unfinished chunks or complete global convergence/platform
acceptance. All production/UI/automatic/release gates remain OFF.

### Inspectable original native source identity (Refs #349, #337)

New acceptance-format-2 proofs retain the actual native source context fields,
including original peer identity, optional pairing epoch, permission epoch, source
version/policy epoch and read token. Their exact canonical hash must equal the
source-context hash ALREADY protected by the original job. The shared canonical
encoding remains byte-for-byte compatible; no job identity or consent is rewritten.
Original native lease checks still precede capture. A parsed historical context
is not a native lease and cannot manufacture its live owner object or READ rights.

Older acceptance-format-1 remains historically readable with no invented context
witness; native rebind/output/new-saved operations require separate repair instead
of silently upgrading it. Typed/hash/context/pairing inconsistencies reject, and
new-format metadata cannot be disguised as old format by changing one format field.
145 distinct host cases pass (two new, 143 affected), including actual Gallery
peer/pairing/permission binding before chunk output and absent-pairing SAF history.
This only supplies verifiable original identity fields for future native recovery;
restart READ renewal/post-restart incoming ownership and platform acceptance remain
unfinished, with production/UI/automatic/release gates OFF.

### Durable original Android acceptance before output (Refs #348, #337)

The actual native acceptance path now commits/readbacks original sealed job/source
identity, the actually sent correlated offer and validated acceptance/command digest
before exposing RAM acceptance. Chunk output requires that exact durable binding;
remote-saved commit requires the same original acceptance. Both record kinds are
bounded by actual job membership and atomically covered by the aggregate head.
Identical acceptance repeats are immutable; changed offer/destination/context cannot
rebind a source job. Expiry/revocation during the transaction rolls back; lost
postcommit sync returns no success and fences the old source owner.

Fresh metadata inspection is historical only. It never restores run/offer ownership,
READ, chunk output or permission epochs. Prior valid historical saved records without
the new acceptance proof stay readable and unchanged; they require separate explicit
repair rather than fabricating an earlier acceptance. Final proven retirement removes
both proof kinds and the job under one transaction, not upon remote confirmation.

143 distinct source-host cases pass (seven new, 136 affected), including actual
native acceptance inspection before the first chunk, unchanged source/permission
runtime paths, immutable original bindings, absent/lost acceptance, typed/context
rejection, transaction/permission/Sync boundaries and valid prior-format history
without invented adoption. Restart READ renewal and post-restart incoming ownership,
global baseline/conflict/migration and installed/physical acceptance remain open.
Production/UI/automatic/release gates remain OFF.

### Durable Android historical remote-saved evidence (Refs #347, #337)

The actual native `observeRemoteSaved` path now commits a protected historical
record before publishing its RAM result. Original sealed job identity/hash,
source context/root, manifest, validated acceptance fields/command digest and
the original complete saved envelope are bound. The receipt row and aggregate
membership head commit in one existing SQLite transaction, with sync/readback.
Same acceptance/result repeats are immutable; changed receipt/context stays HOLD.
No incoming packet can replace missing source ownership or recreate lost proof.

Fresh index inspection reads historical evidence without source/cache/live media
access or renewed READ/acceptance grants. It does not report current PC presence,
baseline convergence, whole-run success or quota retirement. Failed cleanup keeps
the original proof and retired job/quota; final proven retirement removes the proof
and job together under the membership transaction. Deleted proof rows do not become
absence/defaults under an unchanged membership head.

136 distinct source-host cases pass (eight new, 128 affected): metadata-only fresh
inspection with the source cache temporarily unavailable, actual runtime persistence
before its RAM result, immutable conflicts, missing proof, typed/context corruption,
transaction rollback, permission loss during head protection, postcommit sync loss
with no returned success, and atomic final retirement rollback/retry. This is not
restart READ renewal, post-restart
incoming confirmation handling, baseline/conflict convergence or physical acceptance.
Those remaining #337 boundaries and all production/UI/automatic/release gates stay
unfinished/OFF; full consistent private-backup rollback needs monotonic anchoring.

### Android source membership integrity (Refs #345, #337)

The native source index now requires an authenticated aggregate for new header-v2
stores: original root/database identities, revision, exact protected job membership,
counts and reserved plain/cipher quotas, plus format/policy/repair-fence metadata.
Each native SQL mutation advances that head in the same transaction under an exact
thread/transaction/head-hash lease. Sync/readback failure reports no success and
fences the old owner; fresh opening authenticates the actual committed state.
Missing or additional rows, missing heads, copied/replaced databases and unknown
schema objects cannot become an empty inventory or adopted membership. Schema
validation enumerates every object, including SQLite-lookalike trigger names.

Observed integrity loss does not revive old byte readers after the old head is
restored. Native pending/readiness projection preserves protected consent/version;
legacy header-v1 remains metadata-readable but cannot reserve, read source bytes,
mutate policy or retire caches without separate explicit completeness repair.
Selectable discovery and freeze require membership readiness before enumeration.

124 distinct source-host cases pass (12 new, 112 affected), including two additional
original-location/policy-loss cases. These are bounded Android host tests, not
physical-device, installed-platform or crash/power-loss acceptance. Entire consistent
backup rollback still needs external monotonic anchoring. Remote saved ownership,
READ renewal, baseline/conflict convergence and UI/release gates remain unfinished.
The separate cleanup absence/permission defect was confirmed and addressed in
#346 as described below; membership integrity alone is not quota-retirement proof.

### Cache absence proof before quota retirement (Refs #346, #337)

A native reproduction removed the private parent's search permission immediately
after retirement commit. The cache remained, but `Files.exists(false)` was treated
as absence and the original job/quota was removed. Retirement now reads no-follow
attributes and accepts only `NoSuchFileException`, bracketed by original parent
identity/private-mode/search-access checks. Access and other I/O failures remain
errors, not absence. Existing cache roots must be original directories before
cleanup. Absence is checked again inside the final membership/job transaction,
after the cleanup boundary; reappearing entries cannot silently release quota.

39 distinct affected/new native host cases pass (four new, 35 affected): lost
search permission before/after cleanup, explicit retry after restored access,
reappearing cache and empty replacement parent, plus original source/policy-backed
snapshot retirement and same-thread reentrant index ownership. Original files,
retired job identity and quota remain held on failure. This bounded fix does not
establish global concurrency/power-loss or physical-device retirement acceptance.

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
Send permission is always off. The existing Linux preference/controller path
still rejects reverse deletion until the native trash journal/restore path is
joined. This is an implementation gap, not the intended permanent restriction;
the user's Notes-style skip-deletions requirement above also applies to Linux.

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

The coordinator now performs passive historical lookup before both fresh native
admission and explicit reservation resume. Known source associations require
reconciliation/HOLD before target capture or a new catalog reservation, including
when the original local file was edited, replaced or deleted. A populated mapping
store cannot be bypassed with an offer lacking correlated media pages; previous
pairing ownership requires explicit reassociation. Bounded lookups must observe
the same protected store snapshot. No target file is read, moved or recreated by
this admission check.

Admission evidence: 71 affected coordinator/media/source/receiver cases and 45
mapping-store/control-owner cases passed. The ten new admission cases cover
original/edited/deleted/replaced local files for both accept and resume, corrupt
historical rows preserved, and missing-media bypass rejection. Native construction
remains inert and transport replacement closes the mapping owner before protection
release. These source-host cases do not establish physical phone acceptance.

Native media-aware publication now commits mappings from the held receiver's
protected original media history and complete fresh protected save receipts before
any saved socket confirmation. The current media-page cache cannot supply or alter
these original associations. Saved-confirmation retry performs the same idempotent
metadata commit/readback, never publication. Pre-commit protection failures and
ambiguous post-commit sync failures send no saved confirmation. An uncertain store
stays fenced until explicit native recovery; tests reopen the exact original store,
not a reset or a production restart-recovery API.

Ninety-five affected cases pass, including seven new actual coordinator-save cases
for mapping-before-wire order, changed/cleared caches, failed protection with retry
after PC edits/deletions/replacement, and lost post-commit sync without re-publication.
Standalone store fixtures intentionally stop after real native publication and
receipt readback, before coordinator mapping/ACK, to inject metadata failures.

These bounded joins are not the complete concurrent publication/recovery union. Before release,
missing mapping metadata after restart must not be mistaken for first use:
the optional expected-store/job-history anchors below still need mandatory native
bootstrap, legacy repair and complete recovery integration.
Whole consistent private-backup rollback without a trusted external monotonic
anchor is not claimed prevented by the in-process revision fence. These open recovery
and migration requirements keep production readiness, UI and automatic runs OFF.

### Immutable per-job media history (Refs #337)

Media-aware native admission now captures the exact accepted transfer fingerprint,
whole manifest hash, original source version/run/epoch/type, insertion metadata,
original page request IDs/counts and ordered opaque member associations. The
protected job index stores this immutable history in owner context format 3 during
initial index creation, before staged chunks or first media publication. The
SQLite schema/checkpoint/receipt formats stay unchanged; old context formats 1/2
remain readable and have no invented media anchor. Native receiver admission checks
a supplied typed history against the exact accepted context before reserving a job.

Reopen may authenticate format 3 through existing format-1/2 caller contexts, but
must retain the original exact accepted destination/targets, not merely matching
manifest and peer binding. History parsing checks full order, unique IDs, original
bounded page attempts and type consistency. This is historical identity metadata,
not renewed Android READ, current presence, publication authority, a save receipt
or completed baseline. No expired source request is reconstructed or resent from it.

The initial new tests incorrectly expected an empty destination directory after
native admission, overlooking its existing private publication workspace. The
fixture now checks that exact original workspace and absence of all media targets;
no production guard was relaxed or workspace removed. Fourteen corrected history
cases and 42 native index/receiver regressions pass. A further 68 owner-union cases
pass, including two additional history boundary/accepted-target cases; 47 affected
receipt/source and 14 saved-wire cases also pass. One fresh-process case reads the
actual protected native history with the existing key and no live binding or seal
callback. In total these are 17 new history cases and 169 affected existing cases.
This is source-host evidence, not physical phone, power-loss or native Windows
receiver acceptance. The later post-save join above still does not complete expected
mandatory global mapping-store bootstrap, missing-store recovery or convergence.

Resume now reads the original protected media history before opening the receiving
stage or emitting acceptance. Freshly correlated pages must preserve source epoch,
media type and ordered opaque member associations/kinds. New exact page request
UUIDs may differ; they never replace the original historical attempts. An anchored
job without fresh media, or a legacy job with fresh media but no original anchor,
is held for explicit repair rather than assigned guessed identities. The native
reader rechecks current accepted binding and does not renew revoked authority.
Seven new resume cases and 23 existing native receiver cases pass. This still
does not implement Android restart READ renewal or the missing-store recovery union.

### Expected original mapping-store witness (Refs #337)

An explicit native mapping bootstrap can now capture the original protected store
scope and root/database/lock device/inode witnesses. A native same-authority choice
may anchor that value in the protected photo policy using its existing action/CAS
and encrypted readback. Legacy policies omit the optional field unchanged; passive
lookup never bootstraps a store. Once present, the original witness is preserved
across ordinary setting changes and cannot be rebound to an explicitly created
replacement empty store through the configuration API.

For an anchored policy, the coordinator verifies the expected original store before
admission, native publication mutations and saved metadata/confirmation retry.
Missing, replaced or corrupt original metadata fails closed without creation or
normalization, including after the metadata owner is reopened. A witness is not a
source/file grant, current file presence or trusted external monotonic anchor.
No whole-private-backup anti-rollback guarantee is added.

Thirteen new witness/bootstrap/coordinator cases and 152 affected existing cases
pass. Tests retain original missing root/database/lock objects by renaming them;
no original metadata is deleted. Lost store validation before policy commit rolls
the policy back; loss after commit/readback reports failure and retains the durable
expected marker for explicit repair, never returns success. Policy-choice validation
checks the original store again before commit and after encrypted readback.

This optional foundation is not a completed native UI bootstrap/legacy repair
flow. Legacy policies without the expectation remain limited groundwork; release
still requires mandatory truthful bootstrap/availability, durable post-mapping
receipts and the complete concurrent publication/restart recovery
union. Readiness, discovery 21, automatic runs, advanced UI and releases stay OFF.

### Per-job original mapping-store minimum (Refs #337)

Marked media jobs now capture the actual original mapping-store witness and
protected owner-ciphertext SHA/revision/count in immutable history before receiver
admission/index creation or publication. Inner media-history format 2 carries the
optional checkpoint; old format 1 remains exactly unchanged and has no invented
store expectation. Even an empty store records its actual protected owner hash,
not the public absent-store preference-CAS sentinel.

Marked admission requires this native checkpoint. Resume, publication and saved
mapping/confirmation verify the original store and at least the observed revision
and count; the same revision requires exactly the original protected version/count.
Later legitimate native commits may advance the store without rewriting the old
job history. The mapping transaction also checks the original minimum before any
row insertion and fences an observed mismatch. Fresh page request IDs remain
independent from the historical mapping-store minimum.

Eight new checkpoint cases and 110 affected existing cases pass. They cover actual
marked pre-chunk capture, malformed/new-format absence, later native advancement,
same-revision changed ciphertext after metadata-owner reopen, an older consistent
metadata replay against an actually observed newer minimum, direct saved-commit
fencing before insertion, and marked legacy/admission/resume boundaries. Saved
files and displaced metadata are preserved. This is source-host metadata evidence,
not physical restart/power-loss/Windows acceptance.

A pre-publication minimum does NOT prove protection from later post-save whole
private-backup rollback. Durable post-mapping receipts, trusted external monotonic
anchoring where required, legacy/native bootstrap/availability and the complete
concurrent reconciliation/restart union remain open. No readiness/release gate changes.

### Native metadata availability during held save I/O (Refs #337)

For marked policies, a missing/corrupt/busy original mapping store now makes the
native local projection policy-unready. The protected FileGrantState consent,
revision and epoch are not rewritten at the same revision; the strict native
equivocation guard is unchanged. An unready projection cannot produce a current
receiver binding or claim packet/receive readiness.
The grant and its exact mapping expectation use one fresh protected policy read,
not an extra per-chunk preference sync or a cached readiness Boolean.

Actual mapping insertion holds the protected metadata gate/OS lock across native
receipt validation. Its exact current thread therefore receives a scoped internal
validation lease only after authenticating the original store and associated owner.
The lease binds original descriptor witnesses and the still-valid native one-shot
action, rechecks live native authority, and ends in `finally` before actual gate
release. Other threads remain busy/unready. This is not a serialized authority,
Boolean readiness cache, new consent or renewed Android source READ.

Six new native availability cases and 240 affected existing cases pass. Coverage
includes missing/corrupt store without consent equivocation, one fresh policy read
per projection, same-thread held-I/O validation versus another thread's busy state,
expired metadata action without saved output, edit-preserving retry without
publication, and actual connection close/revocation with descriptors/protection held
until blocked I/O ends. Test threads join; no native VM/physical-phone acceptance
is claimed. Full-store validation throughput at the maximum mapping size and the
complete cancellation/recovery union still require acceptance, not a Boolean cache.

The global production data-readiness gate, advanced UI, discovery 21, automatic
runs and releases remain OFF; native UI/bootstrap and recovery union are not done.

### Existing job history before a new media reservation (Refs #337)

After protected mapping lookup, native admission now inspects only an already
existing authenticated job catalog, bounded by its original limits (32 jobs by
default, at most 128). Original protected job media history is read without target
verification, binding renewal, stage ownership, source access or sealing. A known
same-peer source epoch/photo ID/media type requires reconciliation, even if the
mapping commit has not happened or an unmarked mapping store is missing. Unknown
legacy job media identity, missing current media pages or a damaged/missing known
index are HOLD/repair states, not empty history. No filename/hash deduplication is
performed. An explicit resume may exempt only its own native job, then still must
pass all exact original manifest/binding/target/history/minimum/stage checks.

Catalog history inspection is read-only under its native gate/OS lock; nested
reservation is forbidden. The authenticated job tuple becomes the reservation CAS
input. A new reservation appearing between history lookup and native admission
fences the operation before another cache or acceptance is created, including a
previously empty catalog. An exit during a historical scan stops before new target
capture while preserving protection/descriptors until the actual read ends.

Seventeen new catalog/history cases and 156 affected cases pass, including actual
staged/unreceipted/PC-edited/deleted/missing-map gaps, legacy/no-page bypass fences,
offline history with missing original target and binding/seal callbacks forbidden,
reservation-list races and close during blocked index read. Two affected cases use
actual encrypted socketpairs with a fixture phone; this is not physical-phone or
installed/native Windows acceptance.

This protects known existing catalogs, not a fresh process's inability to distinguish
a completely missing unanchored catalog from first use. Mandatory native bootstrap
must anchor the original catalog as well as the mapping store. Do not reconstruct
orphan indexes from guessed fresh offers or reset metadata. Durable post-mapping
receipts, retirement/baselines and the full missing-metadata/concurrent recovery
union remain open. Production readiness, discovery 21, UI, automatic runs and releases stay OFF.

### Original catalog bootstrap expectation (Refs #337)

Protected photo policies can now additionally retain an optional original catalog
bootstrap witness: local identity, root/lock/owner-file device/inode and protected
immutable-owner hash. The choice must come from the actual native catalog under
the same native parent and bound existing-key protection. Existing expectations
cannot be rebound to an empty replacement root. Legacy policy wire shape stays
unchanged; no passive bootstrap occurs. Choice validation repeats before policy
commit and after encrypted readback.

Marked native readiness and catalog opening verify this expectation before any
creation. A missing whole expected catalog is not first use after metadata-owner
reopen. An owner-only observer verifies the immutable protected bootstrap without
creation, job enumeration, reservation or OS-lock acquisition. Live-catalog
verification uses a nonwaiting reentrant instance gate, avoiding an additional
flock inside the current native reservation's own binding validation. Missing or
corrupt expectations fence this connection; ordinary busy state remains transient.

Eighteen new catalog-expectation cases and 318 affected cases pass. A focused
blocked-owner-read test first reproduced a stale ready projection after exit in
the prepared code. Final native close/authority revalidation now fences both exit
and revocation after observation; protection stays held through actual I/O end.
Affected native control/source and encrypted-socketpair cases also pass after that
fix. The witness tests preserve displaced roots and reject both empty-root rebinding
and policy-commit/readback success when the original catalog disappears.

This witness covers the original immutable bootstrap, not complete job-membership
integrity, retirement, post-mapping receipts or full private-backup anti-rollback.
Mandatory joint native bootstrap/legacy repair, those recovery/convergence unions
and native platform/physical acceptance remain open. All release/readiness/UI gates stay OFF.

### Durable catalog membership for newly created catalogs (Refs #337)

A focused source-host test reproduced a missing reservation becoming an empty
catalog after close/reopen. Newly created catalogs now use immutable owner format 2
with the original membership-database identity and a separate protected SQLite
head. That head binds the original root/database/owner hash, revision, job count,
reserved bytes and the digest of every actual protected member record.

Native reservation first durably writes its original signed member, then commits,
syncs and reads back the matching encrypted membership head under the existing
catalog lock. A failure before the head commit preserves the unmatched member as
repair-pending; a lost post-commit sync reports no success and a fresh authenticated
reopen re-establishes durability. Missing members, missing/corrupt heads/databases
and unowned journal/WAL/SHM sidecars cannot become empty defaults or be adopted by
SQLite recovery. No target files are written by this bookkeeping.

Existing owner-format-1 catalogs remain unchanged/readable; no automatic registry
adoption or reset occurs. A new bootstrap choice from an unupgraded legacy catalog
requires explicit native upgrade/repair. Complete consistent private-backup replay
still needs separate monotonic anchoring; this membership head is not that claim.

Fourteen new membership cases and 247 affected cases pass. The initial missing-job
reproduction failed before the change; three additional authenticated Boolean/int
counter confusions were also reproduced and fixed by comparing exact canonical
expected head bytes. Signed member/head corruption, missing databases, dangling
sidecar links, uncertain commit recovery and unchanged legacy handling preserve
the originals. Actual native receive/source/close paths and two encrypted fixture
socketpair cases pass; this is not physical-phone or installed-platform acceptance.

### Durable post-mapping evidence before saved output (Refs #337)

The native media receive coordinator now joins the original authenticated media
history, every protected local file-save receipt, every original protected mapping
record and the actual mapping-store checkpoint. A bounded immutable historical
receipt binds their exact ordered identities and hashes, accepted transfer and job
owner. It is not evidence of current target presence, write/delete authority, a
book SaveACK, remote confirmation, baseline convergence or quota retirement.

The owned native job-index worker explicitly upgrades receipt schema 2 to 3 in
one FULL SQLite transaction: the encrypted mapping receipt, owner context format 4
with its protected receipt hash, and schema version commit together. DB/directory
sync and protected readback precede native saved socket output. Historical reads
do not create/upgrade tables. Older owner contexts remain readable; a missing or
damaged new receipt or downgraded schema cannot become absent/default metadata.
Transaction or post-commit sync failures emit no saved confirmation and preserve
actual files and metadata for authenticated reopen, not destructive reconstruction.

A retry with a durable receipt only looks up the original mappings, checks their
protected hashes and original store checkpoint and re-reads the receipt. It does
not create mappings, republish targets, replace later PC edits or release quotas.
Complete consistent private-backup rollback still needs separate monotonic anchoring.

201 distinct affected/new source-host cases pass (24 new, 177 affected): transaction
rollback, loss/corruption, fresh index reopen, original history, revocation and
immutable receipt-only retry, plus native control/receive paths and two encrypted
socketpair fixture cases. These checks are not installed GUI, physical phone,
OS-dialog or power-loss acceptance. Full restart/recovery ownership, legacy repair,
baseline/conflict convergence and release/readiness/UI gates remain unfinished/OFF.

The explicit native `recover_saved_confirmation` path can now repeat that complete
historical media confirmation after a fresh desktop connection/index/catalog open.
It consumes a fresh bounded native action and requires the exact original reserved
job, current binding/destination, protected index history/save receipts/post-mapping
receipt and original mapping hashes/checkpoint. Catalog membership and the exact
index lock remain held through output. No receive worker, source command, stage,
cache, publication journal, target read/write, new mapping or quota release is
started. Incomplete/legacy jobs without the complete original receipt remain HOLD;
there is no inferred or unattended reconstruction.

Thirteen additional native source-host recovery cases pass, including actual
fresh reconnect with both original-root witnesses, deleted cache and unchanged,
edited/deleted/replaced PC targets; missing complete proof, unknown job, active
receiver, one-use action and revocation/exit around actual blocked output. Exit
retains descriptors until actual I/O ends and cannot return late success. Bytes
already handed to transport before revocation cannot be retracted; the historical
confirmation is not a current-presence claim. Android restart READ renewal, remote
confirmation ownership and full conflict/recovery/quota retirement are still open.

### Legacy catalog admission fence (Refs #339, #337)

A direct native reservation call reproduced an additional legacy hole: bootstrap
choice was fenced but owner-format-1 catalogs could still accept a new member
without a durable membership head. Reservation now stops with explicit membership
upgrade/repair required, before acceptance/binding verification or any member write.
Authenticated legacy inspection and existing job metadata remain unchanged. Empty
and populated legacy catalogs are both checked byte-for-byte; no registry adoption,
owner rewrite, record reconstruction or reset occurs. Fifty-one targeted membership,
catalog, root-witness and history cases pass, including both legacy variants. The
explicit legacy upgrade/repair workflow itself is not implemented by this fence.

### Explicit joint native storage bootstrap (Refs #340, #337)

`NativeMediaStorageBootstrap.prepare` consumes one bounded native user action,
checks the original paired authority and exact preference snapshot, authenticates
or explicitly creates both stores, and binds both original root witnesses through
one existing protected preference CAS/transaction. Sub-actions cannot renew the
original action's lifetime. Missing/replaced expected roots and legacy catalogs
are not reinitialized/adopted. Original metadata and unbound prepared roots remain
preserved on failure; a retry authenticates and reuses them rather than resetting.

Existing activation, schedule, direction, deletion choices, destinations, video
and grouping preferences are preserved. First-use policy remains disabled/manual,
phone-to-desktop and without deletion consent or destination. A new protected
permission epoch requires a fresh native control agreement; bootstrap sends no
controls/source commands, opens no transfer worker and publishes no target bytes.
SQL failure rolls both witness bindings back together; lost post-commit sync is
not reported as success. Fresh authenticated preference read exposes the actual
committed joint binding, never an invented default or half-success.

Fourteen new source-host cases pass: initial/default and existing-setting
preservation, stale snapshot, action expiry/close/revocation, missing and valid
replacement roots, legacy preservation, transaction rollback/retry, lost sync,
and actual native media save plus receipt-only recovery after fresh reconnect.
This explicit native API is not yet joined to the advanced UI. Both original-root
bindings are required by the media admission fence described below. Legacy completeness/repair, full recovery/convergence and
installed/physical acceptance remain in #337; production/UI/automatic gates stay OFF.

### Separate explicit repair of missing post-mapping evidence (Refs #341, #337)

`repair_saved_mapping_receipt` addresses a narrowly provable interrupted commit:
the original protected media history, every local save receipt and every matching
original protected mapping already exist, but the post-mapping receipt does not.
A fresh native action and exact original job/current binding/destination authorize
only metadata repair. Native index worker ownership, catalog membership inspection
and original mapping-store checkpoint protect the existing atomic receipt commit
and authenticated readback. The original action lifetime also fences index writes.

The repair performs no source/cache/stage/journal reopen, target read/write,
mapping creation/reconstruction, socket confirmation, baseline advancement or quota
release. Edited/deleted/replaced targets remain untouched. Missing mappings,
incomplete local saves, legacy jobs without original media history and changed
native mapping context stay HOLD; no defaults or new wire pages supply evidence.
Already complete original receipts remain immutable. A separate fresh historical
recovery action is needed to send a confirmation after repair.

Thirteen new native source-host cases pass: fresh repair and separate confirmation
with edited/deleted/replaced PC targets and removed cache; absent mappings, partial
save and legacy history; wrong job/receipt/target context; original action expiry,
exit/revocation during protection; lost post-commit sync with no returned success
and actual complete evidence on authenticated reopen. This is not full source
restart/READ renewal, arbitrary missing-metadata repair or platform/phone acceptance.

### Mandatory original storage bindings for media admission (Refs #342, #337)

Three actual native offers reproduced admission with no storage binding or only
one bound original root. The media admission/resume preflight now rejects those
states before mapping/history lookup, catalog opening or a new reservation. Both
protected original witnesses must already exist in the current native policy;
incoming media or source commands never invoke bootstrap or renew consent.

Positive media fixtures now explicitly prepare both roots through the actual
native bootstrap API and renew native control agreement BEFORE source commands.
The lower-level direct file fixture without a Gallery source run remains explicitly separate; it does
not prove production media readiness. Standalone mapping tests use the actual
coordinator's held-I/O owner/lease and explicit original-owner reopens rather than
a competing writer hidden from native availability validation. Expectations now
require the real prepublication root checkpoint and preserve empty authenticated
stores, not an absent default. Missing/corrupt bound roots fence native availability
even before historical admission and remain preserved, without new jobs or copies.

199 distinct scoped cases pass after the change (three new, 196 affected), including
unbound/half-bound accept and resume, actual protected source/offer/save ownership,
original history and root loss/corruption, post-mapping commit/repair and fresh
historical recovery. Earlier failed reproductions/fixture adaptations remain
separate evidence and are not counted as extra passing cases. Advanced UI, automatic
runs, production handlers and releases remain OFF pending the remaining complete
recovery/conflict/migration/source/platform acceptance in #337.

### No first-use Gallery history omission bypass (Refs #343, #337)

An actual first unbound Gallery run reproduced admission after a correlated
run/offer result without any media pages. The source-run preflight now requires
its original media history before mapping/history/catalog inspection or reservation,
even at first use. Bound and unbound omissions both HOLD for accept and resume;
there is no default identity inference or bootstrap from an incoming offer.

The positive source/offer fixture now uses real correlated media pages and both
native root bindings. The encrypted socketpair source-offer path explicitly binds
both roots before control negotiation and exchanges the actual bounded media page
before offer/accept/chunk/save, rather than treating a legacy offer as Gallery-ready.
73 distinct cases pass (two new, 71 affected), including the source/control/history
union and both encrypted fixture paths. Historical missing-page cases now fence
earlier without weakening preservation or admission checks. These are not physical
device/native installed-platform acceptance; all production/UI/auto/release gates
and the other remaining #337 recovery/classification/migration work remain OFF/open.

### Fresh animation target routing (Refs #344, #337)

For a new unassociated media admission with protected `separate_animations`, only
correlated original `animation` members receive the `Animationen/` prefix inside
the original photo destination. Static/other image members keep their exact source
paths. The native accepted transfer authenticates the complete final target map
before reservation; duplicate/tree-colliding routed targets fail without a new
job or target write. Missing correlated media cannot fall back to an unrouted legacy
target. Video and semantic photograph/graphic grouping remain separately unsupported.

Original association/job lookup still precedes path derivation. Changing this
preference later does not relocate existing files or download a second copy: known
associations remain reconcile/HOLD at their original location. No existing-file
merge/sort migration or special-folder removal is performed. The requested symmetric
Yes/No migration dialogue and durable no-replace move journal remain unfinished;
fresh routing does not complete the user-facing grouping feature or enable its UI.

50 distinct scoped cases pass (seven new, 43 affected), including consistent
two-frame GIF and static PNG bytes through native source/offer/chunk/save, protected
targets/mappings/post-mapping receipts, fresh historical recovery preserving newer
PC animation edits, route collisions, existing destination preservation and grouping
changes in both directions after an actual fresh native source owner. The no-overlap
guard and original quota remain intact. These fixtures prove transport/routing, not
a semantic classifier, native installed-platform/phone acceptance or a release.

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
