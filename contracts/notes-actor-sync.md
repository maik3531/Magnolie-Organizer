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

Contract wrap/unwrap helpers preserve original record/scoped bodies. They do not
authorize membership, stage a message, apply records or acknowledge persistence.
Actual current identity, grants, ownership, scope and receipt checks remain at the
native runtime boundary.

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

The common malformed/valid start and data vectors are kept in the Notes test
resources and are shared by the Kotlin, Python and C# contract tests.
