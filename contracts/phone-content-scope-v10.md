# Notes collection membership (capability 10, implementation in progress)

Refs #131; shared preferences #130; explicit Organizer admission #132.

Capability 10 is not advertised until content-run binding, preference application
and the UI are integrated. Current implementations include membership codecs,
current-connection assembly, optional snapshot filtering, a Notes commit-boundary
recheck, and the membership control sender/receivers. These components alone do
not constitute an activated end-to-end scoped synchronization feature.

## Meaning

The default `phone_scope` content preference covers **notes and tasks together**.
It is bidirectional for that collection. It is not the old one-way `phone_import`
mode. The collection consists of physically present, eligible personal entries
in Notes, resolved through existing stable wire-ID mappings.

An Organizer modification of a member is allowed back to its Notes copy. An
Organizer-only entry is excluded unless the user explicitly admits it via the
context menu or the initially unchecked new-note checkbox. Removing the Notes
copy removes membership, not the Organizer's copy. Delayed responses must not
recreate the removed Notes copy. Time synchronization remains separate.

The optional full-collection preference does not use the restricted-membership
admission UI. A full-collection switch must be a shared explicit setting, not an
implicit consequence of an empty manifest, a reconnect, or time synchronization.

## Membership manifest

The manifest has exactly these fields:

```json
{
  "format": 10,
  "epoch": "44444444-4444-4444-8444-444444444444",
  "revision": 7,
  "scope_hash": "589f36e8c7d673b4e24e3bebc8a020441d9e313a465f2f8f011b9cebb596fdc2",
  "members": {
    "notes": ["mobile-note", "", "😀"],
    "tasks": ["mobile-task"]
  }
}
```

IDs are existing canonical wire IDs: nonempty, trimmed, without NUL, at most
160 UTF-8 bytes. Each list is unique and sorted by UTF-8 bytes, not UTF-16 code
units. At most 50,000 combined member IDs are accepted. Foreign/shared-tree data
is subject to the existing personal-content eligibility checks.

`epoch` is a UUIDv4. `revision` is an integer from 1 through 9007199254740991.
`scope_hash` is SHA-256 of canonical JSON for the `members` object. The example
above is a common Python/C#/Kotlin Unicode golden. Physical membership changes
increment the revision and rotate the epoch; unchanged membership does neither.

Live physical data determines membership. Old metadata entities, archived
tombstones, cached labels and name/content similarity do not authorize membership.

## Bounded transport

Notes sends `personal_sync.content_scope` controls over the current authenticated
phone connection, with at most 60 seconds wire lifetime per message. Each body has
the manifest's `format`, `epoch`, `revision`, `scope_hash`, plus:

- `part`: zero-based index.
- `parts`: total part count, at most 1563.
- `members`: at most 256 `{ "kind": "note"|"task", "id": "…" }` objects.

The combined ordered entries put notes before tasks and use UTF-8 ID order within
each kind. Individual messages are limited to 192 KiB. Chunk-size selection is
between 32 and 256 entries; an empty collection is one part with no members.

Parts can arrive out of order. An identical duplicate is harmless. Conflicting
duplicates, mixed generations, invalid ordering, duplicate IDs, excess aggregate
membership or a final hash mismatch fail the assembly. A newer partial generation
immediately closes the old ready gate. Old reordered generations never replace
the current one. A failed assembly cannot become ready until a fresh connection.

## Authorization and lifetime

Both available personal-notes and personal-tasks capabilities must advertise
marker 10 at both ends. The connection must also have:

- Current peer ID and pinned public key, with current connection ownership.
- Fresh capability, grant and bilateral own-device controls.
- Bilateral notes and tasks grants for the combined collection.
- Current shared preference snapshots sent and received, agreeing on `phone_scope`.
- No application recovery barrier.

Persisted membership is not current-connection evidence. A reconnect starts with
an unready scope. Receiving some parts or a transport ACK is not permission to
apply unscoped content.

The Notes sender associates part acknowledgments with the current session's
message IDs. Temporary rejection retains the same queued control for bounded
retry; terminal rejection closes that scope session rather than generating an
unbounded sequence of new messages. Old/foreign acknowledgments do not mark a
new session's parts accepted.

## Data selection and commit

A scope reference consists of `scope_epoch`, `scope_revision`, and `scope_hash`.
All three must match current complete membership. The eventual run controller
must persist this exact reference with the run and apply it to replies, attachments,
retry/ACK processing and final application, rather than accepting a loose list of
IDs from the UI.

The scoped data codec uses a distinct `personal_sync.scoped_data` message body
with exactly `format: 10`, `scope` (that reference), `kind` (the inner kind), and
`body` (the unchanged inner data body). Request, batch and report bodies use
record format 3; attachment request/chunk/result bodies keep format 2. The complete
wrapper is limited to 256 KiB. Legacy record schemas are not relaxed to accept
arbitrary extra fields. Controls, recursively wrapped messages and deletion
proposals/decisions are not allowed inner kinds. The codec alone does not permit
dispatch: current scope and immutable durable run binding remain required.

Snapshots filter member IDs **before** materializing or hashing unrelated note
contents and attachments. Notebooks are included only when needed by selected
notes. Task parent/child relationships must remain valid without silently admitting
all other tasks. A scoped empty collection must never mean the whole collection.

Immediately before committing on Notes, under its existing storage lock, recheck
the actual live collection. Removed or unrelated incoming note/task IDs and
unnecessary notebook records are rejected. Content changes and the applied-batch
receipt are written together. This gate is distinct from transport authentication;
the caller must still validate the current peer, settings and scope reference.

Explicit desktop admission needs a separate idempotent intent and receipt. It
must not be implemented by allowing arbitrary missing IDs through the update-only
commit gate. A background retry cannot revive a Notes entry that was subsequently
removed; a new explicit user admission may do so.
