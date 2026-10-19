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
retains the existing 192 KiB inner-batch policy while allowing actor/header
overhead within the full packet budget. Python currently admits larger batches
than C#/Kotlin; its separate valid-input overflow case proves that body-only
budget checks cannot replace the complete wire check. Existing inner limits are
not relaxed by this extension; their cross-platform difference is tracked in #188.

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
requires the native retry of its original message ID. Incoming book adoption and
the remaining completion gates still apply.

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
