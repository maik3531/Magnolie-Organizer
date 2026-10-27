# Correlated own-Notes content start (#170, in progress)

This extension is **not yet advertised or connected to public MCP tools**.
The existing v9 shared-start GUI path remains unchanged. Actor-scoped native
staging, typed decisions, save/commit and late-reply isolation must be connected
before this capability is enabled.

## Start contract

Both peers must advertise marker **12** for both `personal_notes_sync` and
`personal_tasks_sync`, in addition to their existing v9 shared-settings support.
Declared support alone is not authorization: actual handlers must require current
paired identity, both own-device confirmations, both content grants, fresh controls
on the exact verified connection and current shared-settings agreement.

New kind: `personal_sync.actor_start`, maximum lifetime 60 seconds. Exact body:

```json
{"format":12,"run_id":"11111111-1111-4111-8111-111111111111","trigger":"manual"}
```

The caller creates a canonical lowercase UUIDv4 before dispatch and pins the
actor to the selected peer key/connection. The message ID must equal `run_id`.
The phone carries that ID through its existing normal or scoped-content
initialization, rather than generating a different run ID. Scope membership,
snapshot selection, note/task grants, attachment handling and merge behavior
continue to use the existing Notes engines. This start covers notes/tasks;
independent time/custom policy and timer actions are separate contracts.

## Explicit actor data envelope

New wire kind: `personal_sync.actor_data`. Its body has exactly four fields:
`format: 12`, the canonical actor `run_id`, the original `kind` and original
`body`. The enclosing message keeps the original message ID and creation/expiry
times. Unwrapping reconstructs those same headers, changing only kind/body back
to the semantic original. It cannot extend lifetime or change ACK identity.

Allowed inner kinds are the existing request, batch, report, attachment request/
chunk/result, deletion proposals/decision and `personal_sync.scoped_data`.
Controls/settings, nested actor envelopes and starts are excluded. Existing
record validators remain authoritative. Scoped data retains its complete format10
membership reference and is validated by the existing content-scope contract.
The inner (or scoped inner) run ID must equal the actor ID. Any existing trigger
field must remain `manual`. The complete actor body is bounded to 256 KiB, matching
the existing Personal Sync packet budget. Current bounded snapshot chunks fit
without enlarging the secure transport frame.
The complete wire message, including its original headers and actor wrapper, is
also limited to 256 KiB before queue insertion. The portable boundary fixture
retains the common **192 KiB (196608 bytes, inclusive)** canonical UTF-8
`personal_sync.batch` body policy while allowing actor/header overhead within
the full packet budget. This applies to formats 1, 2, 3 and 14, inside or outside
an actor/scoped envelope. Python's former 256 KiB batch acceptance was reduced
in #188 to match the existing C#/Kotlin receivers and GUI senders. No receiver
limit was enlarged. Attachment chunks keep their separate 256 KiB body budget;
the complete wire-frame check still includes every wrapper and header.

`personal-sync-batch-boundaries.json` in Notes test resources and the identical
Windows standalone test resources supplies 16 independently generated, hashed
canonical UTF-8 bodies: 196607, 196608, 196609 and 240000 bytes for all four
formats. Individual record/value hashes and format-2+ aggregate hashes are valid;
non-ASCII text distinguishes bytes from character counts. All three validators
accept the first two sizes and reject the latter two, including actor wrapping.
The 240000-byte case documents rejection of the former Python-only input, not
a successful actor-wire overflow through a now-invalid inner batch.

Contract wrap/unwrap helpers preserve original record/scoped bodies. They do not
authorize membership, stage a message, apply records or acknowledge persistence.
Actual current identity, grants, ownership, scope and receipt checks remain at the
native runtime boundary.

## Actor-marked acknowledgements

New reserved wire kind: `personal_sync.actor_ack`. Exact body:

```json
{"format":12,"run_id":"11111111-1111-4111-8111-111111111111","message_id":"22222222-2222-4222-8222-222222222222","status":"accepted","error":"none"}
```

The body `message_id` refers to the original acknowledged actor frame; the outer
message has its own ID and a maximum 60-second lifetime. `run_id` remains present
even after the original outbox row expires or is removed. Status/error rules
reuse the existing strict acknowledgement schema: accepted/duplicate require
`none`, rejected requires a known non-`none` error. ACK frames cannot be nested as
actor data and do not receive an ACK of their own. An acknowledgement must not be
interpreted as book persistence or complete synchronization without the actual
corresponding stage/save/commit proof. This marker is still reserved/inactive;
authorization, durable phase bookkeeping and actual dispatch remain runtime gates.

## Actor cancellation intent

Reserved wire kind `personal_sync.actor_cancel`, maximum lifetime 60 seconds,
has exactly `{"format":12,"run_id":"11111111-1111-4111-8111-111111111111"}`.
It is a control intent, never nested content. Its own outer message ID is the
target of the actor-marked acknowledgement. An authorized native handler must
bind it to the original source identity and actor, stop further protocol work
and release that actor's pending run without deleting ordinary book records.
Cancellation must not assert recall, rollback or retraction of a save/transfer
already dispatched. A lost cancellation acknowledgement leaves an unknown remote
outcome. The schema is reserved/inactive until the native server journal and
owner/source-bound cancellation adapter are connected; generic receive ignores
it rather than falling through to ordinary synchronization.

## Storage integration status

The existing single-message encrypted outbox writers now accept an internal
explicit actor run ID, persist the complete actor wire envelope and retain the
original semantic queue kind for ordering/purge rules. Queue reload must return
that envelope unchanged, without consulting volatile actor ownership. The Kotlin
queue verifies a valid actor envelope before comparing its semantic kind with
the stored queue kind. Ordinary callers keep the existing unwrapped format;
control injection and mismatched actor run IDs are rejected before insertion.
Explicit semantic inspection for policy/decision ACK metadata does not replace
the wire envelope. Temporary receipts retain the same actor frame; an accepted
receipt removes only its original message ID. The existing decision identity is
recovered from the validated inner body rather than from the actor wrapper.
Generic transport loops retain these reserved actor frames instead of forwarding
or consuming them as ordinary synchronization. They require a separate authorized
actor route; the internal store parameter itself is not an authorization token.
The unadmitted receive boundary currently ignores reserved actor messages before
ordinary validation/staging/callbacks and ignores generic ACKs referring to stored
actor frames. It emits no success receipt and makes no document change. Ordinary
heartbeat/control traffic remains usable. This closed boundary must be replaced
by the explicitly authorized actor route, not removed in favor of legacy receive.

The existing batch/domain stagers can be reused under a private storage peer
identity `@mcp-actor-<canonical-run-UUIDv4>`. This is not a paired peer ID and is
not an authorization credential. Ordinary GUI replay explicitly excludes that
namespace while the durable staged records remain available to the actor path.
No second merge or batch-staging engine is introduced. The actual source peer,
key, live role/grants/scope and session owner must still be checked by the actor
adapter before reading, adopting or committing such data; the private storage ID
must never replace the real source identity for those checks. A raw actor-wire
inbox/binding and the authorized adapter are still required before activation.

The Linux and Windows reference raw-inbox stores now seal actor bindings and
complete wire packets with the existing native profile storage key. Each private handle binds a
random owner token to a native owner epoch and the selected peer/fingerprint/
current-source revision. Raw reads recheck both ownership and the native source
callback; source revocation blocks reads while owner cancellation can still
retire the context. A different native epoch cannot silently inherit an old
handle. The callback's keyed revision must bind the current book/profile scope,
exact live channel and key, fresh controls, both ownership/grant choices and
current content scope; a display fingerprint or a caller-provided string is not
authority. A book/profile switch must invalidate that revision and its owner lease.
Conflicting duplicate frames, plaintext lease tampering and live-context
capacity overflow are rejected. Owner leases also use a protected monotonic
deadline, so a wall-clock rollback cannot extend them. Storage quotas count actual
sealed bytes rather than trusting plaintext size hints. Raw reads recheck the
source again after decrypting, before returning data. No successful transport
receipt, GUI callback or record adoption is produced by this store.

These references are not yet wired into the phone coordinators, advertised or
exposed to MCP.
Notes server-journal parity, authenticated source-snapshot callbacks, lifecycle
cleanup/recovery and the full transport/adoption adapters remain completion gates.

Notes run authentication now carries an immutable actor classification inside
the existing sealed run envelope. Ordinary run serialization omits this field;
an older ordinary reader cannot reinterpret an actor envelope as a normal run.
The existing shared writer uses that protected classification to wrap every
subsequent data frame, including later attachment/decision output, before sealing
it. A classified run with invalid authentication, a changed restore epoch or an
expired/stopped state cannot produce a plain frame. Explicit actor writes also
reject a missing classification. Snapshot and scoped-run preparation carry it
through the existing atomic queue path. A run cannot be changed between actor
and ordinary classification, and unwrapped ordinary/scoped input referring to an
actor run is excluded from the ordinary receive route.

The protected stop marker is irreversible and distinct from a completion report:
reported runs may still produce valid late attachment work, while stopped runs
cannot enqueue more data and their queued frames are excluded from due work.
Stopping retains the already sealed frames; it cannot recall dispatched data.

This classification is still only a storage/transport marker. It does not
authorize a caller, implement the authenticated server journal, admit a wire
frame or activate a capability. The native actor adapter must supply the actual
source and ownership checks and actor-marked receipts before it is enabled.
Its cleanup must retire pending producers before removing run classification;
an absent run row alone is not an actor tombstone for ordinary queue callers.

The inactive Notes server-journal primitive uses the existing phone database and
payload encryption. Its sealed bindings include the actual peer public key,
native owner epoch/token hash, restore/book epoch, source revision and both wall
and monotonic leases. Same-database work requires native source checks before
and after the transaction body; a failed post-check rolls back that database
work. It retains at most 32 bindings and permits four active contexts. Native
retirement remains available after source revocation or lease expiry, without
granting content access. Tokens are absent from its status and default string
representation. Its raw inbox seals the complete actor data/ACK wire frame under
the peer/run/message identity, rejects conflicting duplicates and never normalizes
the stored marker. Raw put/read use the same pre/post authorization transaction.
Per-actor retention is bounded to 4096 packets/50 MiB sealed bytes and also obeys
the existing shared phone-meta capacity (8192 rows/50 MiB). Persisting a raw frame
is neither domain staging nor authority to emit a successful receipt. This
primitive does not yet dispatch incoming frames; transport integration remains
an activation gate.

Notes now also derives a native source revision from the exact active secure
channel and its private session nonce, pairing/lifecycle generations, actual
paired key, local profile, restore epoch and fully acknowledged current scope.
It reuses the fresh shared-control, bilateral ownership/grant and writable-store
checks. The revision is keyed with a runtime-only HMAC key and also binds the
current settings, control revisions and supported capability versions. An
unacknowledged/stale scope, changed connection/key/generation or revoked grant
cannot produce a source revision. Actor capability 12 is required by this check
and remains unadvertised in production. The native queue factory connects the
journal to that callback and acquires service/book locks before SQLite, matching
the existing snapshot path. A book's initial empty native tree-sync epoch remains
a valid bound value, as in the existing queue; it is never replaced with a caller
epoch.

The native manual-actor adapter now creates an owner handle before scheduling
the existing scoped snapshot producer. Actor snapshots require that same active
journal handle before source preparation and before/after the existing queue
transaction; an unavailable
owner never falls back to ordinary production. Native cancellation stops the
journal and current classified queue run atomically and removes a pending
snapshot intent. Stopped sealed outbox rows are retained but removed from due
eligibility, including its bounded query window. Connection teardown and native
maintenance retire invalid owners; failed storage retirement retains the owner
for retry while source checks already prevent further work. These internal
adapters neither admit an actor wire frame nor recall dispatched data, merge a
record or claim a saved book. Public routing remains disabled until the remaining
transport, staging, review and save/commit gates pass.

Source preparation retains the existing encrypted-book reconcile operation. Its
protocol bookkeeping is outside the phone SQLite transaction and may already be
persisted if later queueing is rejected. Cancellation does not undo that tracking
state; it prevents further actor production without changing user content.

Native maintenance and new actor preparation reap bindings from a previous
native owner epoch or expired wall/monotonic leases. Current authenticated actor
queue work is stopped before the private binding/raw inbox is removed, in the
same SQLite transaction. Live owners are never evicted to admit another request;
cancelled current-epoch bindings retain their normal lease/status window.

The Linux phone-service source adapter reuses the actual fresh shared controls,
bilateral grants, exact current connection and completed connection-local scope.
Each connection receives a private random nonce rather than relying on object-ID
reuse. It also requires a callable native book-owner source and checks that
source before/after deriving its keyed revision; a digest supplied in MCP JSON
cannot replace this callback. Reading a source neither queues a packet nor
publishes GUI events. The actual GTK/daemon book-owner binding and source-lock
factory remain integration gates before this adapter can authorize runtime work.

The Windows coordinator/connection adapter applies the same native-book callback
requirement, fresh bilateral controls, active connection and complete scope. Its
revision also binds sealed native local-control revisions, so a revoke/regrant
cannot inherit an earlier actor source. Both desktop scope-reference getters
inspect already validated private session state without copying or hashing the
whole membership for each actor authorization check. These adapters still need
the actual host book-owner/controller and guarded actor-store factory wiring.

Accepted remote Own decisions carry a connection-local decision generation:
revocation followed by regrant cannot recover an earlier actor source even if
the final boolean is identical. An unchanged accepted replay preserves that
generation. Source checks require the actual accepted Own decision and matching
current control revisions, rather than only a cached readiness flag.

Native host book-source providers now have their own lifecycle fence, separate
from document reconciliation. The Windows dispatcher publishes availability only
through actual native initialization/unlock state; ordinary saves preserve its
owner source, reload/lock and restore fences invalidate it. MainForm binds that
provider to its coordinator. The GTK foreground provider reads actual native
lock/load/operation fields, profile path, key identity and native sync epoch,
with synchronous readiness invalidation before asynchronous background notices.
Neither provider accepts a book identity from MCP JSON. Foreground wiring alone
does not complete the Linux runtime path.

The foreground/native store factories use those configured host providers rather
than accepting a source callback from a wire request. Linux acquires its native
service guard before opening SQLite; Windows acquires its existing note-policy
gate and coordinator guard before actor-store work. Source checks are reentrant
inside those guards, and no network/GUI wait belongs in the guarded store action.
Book-owner loss prevents raw access while owner-bound retirement remains possible.

The Linux proxy now publishes the configured native host provider through its
existing private GUI subscription. The daemon binds source authority to that
exact live, visible, ready subscriber and native book source, not aggregate
any-GUI readiness. Book changes, subscriber loss/expiry and readiness/visibility
withdrawal invalidate the owner generation. The proxy checks its actual host
provider again after the source RPC; it does not start a listener or replay work
to manufacture readiness. Optional metadata incompatibility cannot suppress
ordinary phone events. The private IPC registry now creates contexts from this
native source, binds every handle to its exact subscriber/book owner and supports
owner status, raw read and retirement. Native proxy handles hide tokens/book
sources in their default representation; those tokens must never enter public
MCP results. Raw reads recheck the actual host book before/after IPC, and book
loss during creation retires the newly created context. Source invalidation
retires inactive daemon contexts without returning raw content. Private registry
creation/persistence is still not transport dispatch, domain adoption or a saved
book; those runtime gates remain outstanding.

The Notes native actor route now admits a strict actor start only through its
actual source/capability/channel gates, seals the admitted start as a correlated
receipt and acknowledges exact duplicate starts from that receipt. Explicit
transport admission is separate from private snapshot preparation. The dedicated
sender claims only that owner's marked outbox frames, preserves the existing
request-receipt gate before batches and performs network writes outside service,
book and SQLite guards. Only a marked ACK matching the admitted run/peer/channel
and original marked message can advance the existing queue handler; ordinary or
wrong-run ACKs cannot consume it. Native actor cancellation retires production.
This currently covers start, phone snapshot dispatch, marked ACK and cancellation;
incoming record adoption/attachments and desktop transport completion still need
their corresponding gates. Production capability 12 remains unadvertised.

Both desktop native adapters now claim an admitted owner before sending an actor
start, retain the same correlated start for retries and send outside their native
source/policy guards. Their reserved receiver requires the exact admitted peer
key/channel and current native source. Actor request/batch/report frames retain
their full marker in the raw inbox; request/batch data additionally use existing
Personal Sync stagers under the private actor namespace. Current scope membership
is checked before raw persistence, and a marked success receipt follows actual
private staging and a source post-check. Marked ACKs cannot acknowledge another
run's outbound messages or enter ordinary queue handling. Native cancellation
retires locally before attempting its explicit wire control. These paths neither
publish GUI replay nor adopt records into a book. Attachment/deletion adapters,
typed review, native checkpoint/SaveACK/commit and the remaining cross-runtime
acceptance gates remain required before production activation.

Owned encrypted TCP fixtures now exercise the actual Notes runtime against both
desktop adapters, using synthetic established-session keys. They verify a phone
note/task snapshot in the existing private core stagers, GUI adoption isolation
and native cancellation. The Python fixture additionally drops a marked batch
receipt and verifies replay of the same message through native deduplication.
Notes retains the remote actor capability in its validated peer metadata; its
production local capability advertisement remains unchanged. These fixtures do
not prove handset operation or book persistence.

Incoming desktop actor attachment chunks now require their matching completed
private aggregate (run, reply, records hash, attachment hash) and current scope
membership before raw persistence. They reuse the native encrypted attachment
stores and native size/hash/MIME verification. Notes handles actor-bound
attachment requests/results under the active owner through the same chunk
producer used by ordinary synchronization; exact request replay cannot enqueue
another set of chunks. Both owned TCP fixtures include a phone snapshot image
and verify its bytes through the desktop integrity reader. Chunk receipts only
acknowledge private staging, not book adoption.

Both desktop adapters schedule marked attachment requests in their existing
encrypted outbox, retaining its native retry/message identity. Only the admitted
owner/peer/key/channel can claim those due frames; network writes occur after the
source/policy guards have been released. Ordinary receipts cannot consume them.
Exact marked receipts complete only the correlated actor's queued control, and
native cancellation removes its retained outbound controls. The C# outbox binds
marked messages to their private core run namespace rather than a GUI run.
The Python TCP fixture drops the initial attachment request before framing and
requires the native retry of its original message ID.

Attachment requests use deterministic windows of at most eight chunks per hash,
matching the existing Notes producer's per-request bound. Window identity includes
reply, records hash, attachment hash and range; replay does not schedule another
copy. The retained outbound identity limit remains 4096. Both TCP fixtures transfer
a ten-chunk image through multiple native request windows and verify all bytes.

Notes also stages incoming actor reply attachments under the private actor peer
alias, using its existing authenticated transfer metadata and encrypted chunk
store. A complete private reply aggregate and current content-scope membership
must declare the hash before raw chunk persistence. Native requests use bounded
eight-chunk windows in the actual peer's marked outbox. Only native size/hash/MIME
verification produces a transfer-complete result; authenticated completion state
prevents another result for exact or different-message-ID chunk replay. Raw
deduplication, private staging and queued controls share the active journal
transaction. Cancellation purges these private files without adopting the reply
into the book. Native book-derived reply-file production remains an activation gate.

Desktop actor request/result routes require a matching complete private reply
aggregate and current scope before raw persistence. Every requested hash must be
declared and its ranges must fit the declared file. Existing native outgoing-file
readers supply bounded chunks to the admitted peer's encrypted marked outbox;
request-ID/hash/index tracking prevents duplicate queue production on exact
request replay. Network dispatch remains outside source guards. Marked completion
results update only private outgoing transfer metadata. Both owned TCP fixtures
send a modified ten-chunk reply image back to Notes, where its native integrity
reader verifies every byte before the desktop receives the correlated result and
cancels the run. The reply itself is still fixture-generated, not book-derived.

Notes deletion proposals/decisions require both deletion grants, the current
shared skip-deletions choice to be false, a protected active actor run and current
note/task scope (attachment proposals bind their parent note). Decisions also
require a retained native outgoing proposal with the exact expected clock.
They stage review intents in the existing encrypted inbox under the private actor
alias; the sealed envelope binds peer, run, direction and full semantic message.
Copying a row to another alias does not authorize a prior proposal. Raw journal
deduplication and intent staging share one owner transaction, and cancellation
purges both incoming intents and retained outgoing proposals. No success receipt,
book deletion, automatic conflict resolution or GUI replay follows intent staging.
Native proposal production and typed review/commit remain activation gates.

The desktop snapshot engine can now run against an explicit private book object.
The ordinary GUI wrapper still captures its current editor snapshot and calls
that same engine. The explicit-book path does not capture GUI drafts or rebind
global book state; note/notebook IDs, attachment aliases and tracking changes
remain attached to the supplied book across asynchronous hashing. Existing
scope/removal rules and guarded completion apply to both paths. This is a shared
engine prerequisite for book-derived actor replies, not a native owner admission,
review commit or publication of actor tools.

The same existing merge engine now accepts an explicit private book for scoped
format-3 review. This path requires an explicit selection and captures no editor
draft. Note/book/attachment lookup, alias reconciliation, task updates and
deterministic conflict copies stay inside that book. Ordinary GUI import and
legacy paths retain their wrapper and handlers. Hash/scope validation precedes
application and the supplied owner guard is rechecked at completion. These
primitives do not authorize native staging access or save the reviewed book;
owner-bound review jobs, checkpoint/SaveACK/commit and reply production remain
integration gates.

Native desktop adapters now expose an owner-only private staging reader for the
existing incoming aggregate and deletion intents. It returns at most 65,536
raw bytes from a projection that also includes the current native content scope,
base64-encoded per call, with server-derived SHA-256, total bytes and
continuation offsets. Every nonzero continuation requires that same revision;
changed staging, retired handles, changed native book/source or another GUI owner
cannot continue the read. An expired protected core run cannot be read merely
because the outer owner lease is still alive. Native commit tokens come from existing core staging,
not caller metadata. Linux routes this through the existing private actor IPC
owner/subscriber/book-source checks, including proxy post-checks. `batch_ready`
only means that the record aggregate is complete: it does not certify attachment
availability, review completion or a saved book. An optional attachment SHA-256
selects a declared file from that incoming aggregate and always requires the
record-view revision. Before returning any file bytes, the existing native
integrity reader verifies the complete file's size, SHA-256 and MIME magic. The
same bounded offsets then address file bytes, with native hash/MIME metadata;
missing, incomplete or undeclared files are rejected. No parallel file cache is
created. Native frontend review-job wiring remains an integration gate.

The existing private native phone bridge now routes actor source/create/start/
status/read/cancel actions to those same controllers. Creation checks the opaque
source revision against the current native source inside the guarded factory;
Linux IPC performs that comparison at the actual daemon owner as well. The GTK
adapter supports its existing in-process and daemon-proxy modes. Handle tokens
and proxy book-source identifiers are private bridge data and must never appear
in public tool results. Start is separate from creation so an owning job can
retain its handle before network dispatch. These bridge actions do not register
public tools, enable marker 12 or implement review/save/commit.

The private frontend review worker now owns its native handle inside a
session-bound operation with 32 retained/four active slots, including in-flight
start reservations before book hashing. It validates contiguous native byte pages and
raw SHA-256, assembles verified attachments under the same native view revision,
and derives selection from the native content scope. Existing merge/snapshot
handlers run against a private copy of the actual book to prepare a review and
scoped reply batches/sources. The actual book is not saved or adopted during
preparation. Session close, cancellation, book/source changes and new drafts or
dialogs stop further preparation; a late creation result is retained only long
enough to cancel its native context. Status excludes owner tokens and private book
contents. Deletion intents are counted as unapplied and remain a commit gate.
Cancellation/failure after start dispatch reports an unknown native outcome;
retiring the local owner does not promise remote recall.
This worker is not registered as a public tool; native save/commit, reply dispatch
and Notes adoption still require their remaining completion proofs.

The existing native book writers now record a save sequence and raw saved-text
SHA-256 in the actual native book-owner scope, only after store commit succeeds.
Ordinary successful saves preserve that source while advancing its sequence,
including identical-content writes. Lock/readiness withdrawal, profile/binding
changes, restore and lost availability discard the observation. Native readback
also checks that the current native book cache still matches the observed saved
data. This observation is not a client-supplied save boolean and is not yet an
actor commit: a commit adapter must still bind a fresh observation to its private
review/owner and native core commit tokens.

Native commit preparation now binds an active owner to its unchanged staging
revision, verified declared files, planned raw book SHA-256, native book source
and prior actual save sequence. Unapplied deletion intents block this step. A
later core commit requires the private claim and a newer actual native writer
observation for that same book/source and planned hash; unchanged sequences,
wrong hashes, foreign claims and changed staging are rejected. Linux accepts its
save observation only through the exact private GUI/subscriber/book-source
bridge, whose adapter obtains it from native writer state, never request fields.
Only then does the existing private core batch commit consume its native token;
the native owner retains an idempotent local receipt without emitting a phone
book-success acknowledgement.

The private frontend commit job uses the existing recovery checkpoint and shared
save/SaveACK pipeline. It adopts only reviewed notes/notebooks/tasks/tracking,
keeps the native batch ledger through the shared helper, and forces a new actual
write for sequence proof even on identical content. Its pristine-editor option
rejects drafts rather than capturing them while queued. Only actual SaveACK sets
local book persistence, followed by native proof/core commit. Cancellation or
late save receipts do not modify a new draft; a save can already have happened
when a later stage fails. Phase `committed` is local only: reply delivery and Notes
book adoption remain gates, and phone persistence is not claimed.

After local core commit, the native reply adapter accepts the owning claim only
while the actual saved book still matches its native receipt. Existing record,
scope, aggregate-hash and attachment size/SHA/MIME validators check the prepared
reply. File metadata/chunks and the complete reply manifest stay in the private
actor namespace; marked frames use the actual admitted peer's encrypted outbox
and existing retry/pump. Exact payload replay reuses the queued reply; a different
payload cannot replace it. No network wait occurs under source guards. Queue
acceptance exposes neither delivery nor Notes-book persistence.

The existing atomic Python format-2 run writer now supports that explicit actor
wire marker/private attachment namespace without changing ordinary callers. The
private large-reply IPC operation uses the existing 72-MiB large-operation budget.
Its client writer now applies that existing whitelist too (#189); ordinary
operations retain their 64-KiB wire limit. This does not enlarge actor/inner packet
budgets or relax native book-owner/saveproof checks.

The native completion phase now waits for every marked reply-batch receipt and
every declared outgoing file's authenticated completion metadata before queuing
its marked complete report. Only an exact marked receipt for that retained report
ID confirms `phone_persisted`; ordinary ACKs, batch ACKs and file integrity results
cannot do so. Native actor status exposes these phase facts without record data.

Notes accepts that report only for the active native owner, complete private
reply and verified files, with matching record counts and no unapplied deletion
intent. Its actual book reference captured after snapshot must still match.
Existing scoped merge preview must preserve the current live scope; a concurrent
phone edit or scope-widening conflict instead requires a fresh review. The native
recovery journal creates its checkpoint, then the existing encrypted atomic
book writer applies the scoped batch and durable replay ledger. Only afterward
does the protected run mark the reply applied and stop further production, and
the report receives its actor ACK. Duplicate reports require that native applied
mark and cannot rewrite the book. Phone-SQLite rollback never promises rollback
of a book write that already happened. Native owner/source monitoring remains
active until cancellation/expiry so lost acknowledgements stay retryable.

The frontend waits for that correlated native completion fact before phase
`completed` and phone persistence. Earlier local `committed`/queued states remain
distinct. Source/book/draft changes, cancellation and no-progress expiry still
stop further work; a terminal cleanup cannot recall an already saved book.

Typed deletion review can now reuse the existing desktop deletion/trash/restore
handlers on an explicit private book copy. Scope membership, canonical aliases,
prior hash and vector-clock checks still precede mutation. Restore bookkeeping
and attachment-parent lookup remain bound to that copy; private restores neither
wake automatic phone sync nor invalidate the actual GUI indexes. The private
entry points reject the actual active book. Incoming decisions validate the whole
set before application, reject duplicate proposal IDs, and retain parent IDs for
scoped attachment replay proofs. Preview approval remains domain review
preparation only. The native core commit below requires its own actual-save
receipt; scope-changing phone finalization and activation remain separately gated.

The private session-owned review operation also accepts bounded typed choices
against its current review revision. Proposal IDs and expected clocks must match
the retained native intents; choices are copied before asynchronous work. A changed
choice rebuilds from the original private review baseline, not an already deleted
preview, so revising delete to restore does not retain accidental trash or deletion
bookkeeping. The
shared deletion/restore handlers operate on another private copy, then the same
review/reply builder recomputes the projection and checks the native staging
revision again. Wrong owners, stale clocks/reviews and duplicate choices fail
before publication of a new review. Cancellation during the native recheck
discards the result without touching a new draft. Reviewed intent counts remain
distinct from native applied/consumed counts: the existing native terminal-save
and scope-changing deletion gates are not bypassed by preview approval.

### Native reviewed-intent core commit (#190)

Both desktop native controllers accept a private bounded deletion review only
when every retained native intent is identified by its exact message ID, kind and
opaque commit token. Every proposal needs one explicit delete/restore choice,
its exact expected clock and a Boolean conflict choice. Canonical normalization
does not alias caller data. Duplicate IDs, conflicting native proposal bodies,
missing/extra fields, changed tokens/clocks and unsupported notebook intents fail.
All Personal Sync body format fields are actual integers, not Boolean aliases.
The 28 independent cases in `notes-actor-deletion-review.json` are shared between
Python and C#.

Prepare and commit recheck bilateral deletion grants, effective skip-deletion
policy, current scoped membership and the existing native prior-proposal proof
for incoming decisions. The normalized review is bound to the staging revision,
planned after-book hash and native claim; an unchanged hash cannot substitute a
different decision on retry. Neither an IPC plan nor a client save assertion
substitutes for the current native writer observation.

After the existing source/owner/claim/save-sequence/hash checks, core consumption
of the saved incoming actor batch and exactly its reviewed intents shares one
SQLite transaction and the existing domain-commit engine. Missing, foreign,
expired, duplicate or changed references leave every batch/intent staged. A real
injected SQLite failure after the first intent also rolls back its receipt and
deduplication record. A reopened store retains only the complete committed result;
replay cannot apply it twice. This core commit sends no successful deletion ACK
and does not assert phone persistence.

This adds native reviewed-intent consumption while retaining the ordinary
unchanged-source guards. It does not authorize reads or replies after a membership
change. The private frontend still blocks intent commits until the narrowly bound
terminal scope-change/save/receipt path is connected on both desktops and Notes;
marker 12 and public actor tools remain unadvertised meanwhile.

After the native integrity reader verifies a complete private file, the desktop
queues its marked transfer result through the same owner-bound outbox. Exact
chunk replay cannot produce another result. Both TCP fixtures wait for the
correlated marked result receipt and verify that Notes has released its outgoing
attachment staging through the existing completion handler. An optional run
report is not a required transfer receipt. This completes file transfer into
private staging, not book adoption; the remaining completion gates still apply.

Desktop registry reaping retires a context before invoking existing private-domain
cleanup. Expired wall/monotonic leases and previous native process epochs reclaim
their raw inbox, private core staging and marked outbound controls; source loss
retains terminal owner status until lease expiry. Cleanup failure leaves the
context irreversibly inactive and retryable. Capacity checks sweep stale owners
before allocating another context, without evicting a live owner. Linux daemon
registries sharing one process epoch check source changes only for their exact
native GUI/book owner, preserving other active windows' contexts.
An internal sealed cleanup receipt avoids repeating completed domain cleanup on
each pump pass; public/private controller status still reports `cancelled`.
Restoring an earlier protected binding and staging cannot inherit a volatile
cleanup cache. The bound cancellation target remains available until expiry so
an explicit owner cancellation can still notify the same peer/key/channel after
local source retirement, without authorizing another data dispatch.

Desktop deletion proposals/decisions enter the existing private native intent
stagers only with both deletion grants, shared deletion consent and a live private
run. Proposals require current note/task membership (attachments bind their note
parent); decisions require the exact prior private outgoing proposal and expected
clock. Replays retain the native pending commit token. These intents produce no
success receipt or GUI replay before a native book commit.

Notes now validates incoming actor reply batches against the authenticated actor
run's existing request and current native content scope, retains the marked wire
in its owner journal and stages semantic records through the existing queue batch
stager under the private actor namespace. Ordinary replay callers continue to
select only the actual paired peer namespace. Stop/reaping purges private incoming
staging through the existing queue cleanup. Native data lifetimes remain enforced
by the protected journal rather than the shorter control-frame lifetime. Both
owned encrypted TCP fixtures send a changed desktop reply and verify private Notes
staging, unchanged book content and cancellation cleanup. Desktop reply production
from the real book and typed adoption/save/commit still need their completion gates.

This is not complete runtime activation. Bulk snapshot/attachment production,
actor-bound native send/receive, incoming staging/replay isolation, typed adoption
and save/commit still need their corresponding integration and acceptance gates.

## Required runtime completion gates

- No new listener, pairing, grant, ownership confirmation or arbitrary scope
  injection may occur as a side effect of this start.
- Register the selected actor before dispatch. Incoming matching runs must use
  actor-bound staging/receipts and must never fall back to normal GUI callbacks,
  dialogs or automatic adoption after cancellation, expiry or process restart.
- Correlation by `run_id` alone is insufficient after a process restart or
  tombstone expiry. Actor data needs an explicit wire marker/envelope which
  remains in persisted outgoing frames, so an unknown actor is always rejected
  or isolated rather than reinterpreted as ordinary GUI synchronization. A
  sender-side lookup used only at send time must not turn a retained actor frame
  into an ordinary frame when its lookup metadata expires or is removed.
- Preserve existing received-message validation, scoped manifest proofs,
  attachment integrity, checkpoints, native save acknowledgement and commit.
  Resolve conflicts/deletion proposals through typed decisions using the same
  product domain handlers.
- Bind persisted staging to the actor before replay becomes possible. Preserve
  the actor marker in incoming stored data as well as outgoing stored frames;
  semantic kind columns alone must not erase it. Unknown or retired actor data
  remains isolated, including after restart, reconnect or an older reader seeing
  a newer stored frame.
- A transport ACK proves request acceptance only. Track queued work, staged data,
  saved adoption and native commit separately. Timeout/cancellation after dispatch
  can have an unknown remote outcome and cannot promise rollback or recall.
- Keep the old GUI/legacy path for devices without this marker. Do not silently
  downgrade an actor-scoped MCP request into an uncorrelated GUI start.

The common malformed/valid start, data and acknowledgement vectors are kept in the Notes test
resources and are shared by the Kotlin, Python and C# contract tests.
