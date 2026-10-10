# Shared function preferences (capability 9, implementation in progress)

Refs #130; content membership #131 and explicit desktop admission #132.

The codec, encrypted stores and message handlers are being implemented. Capability
9 is **not advertised** until the preference application, Notes-content protocol
and UI are integrated and verified. Recognizing a message schema is not permission
to accept it from an older or unnegotiated peer.

## User-facing behavior

One setting applies to the paired Notes/Organizer relationship and can be changed
at either end. The other end displays the same effective setting. A second local
switch must not be required to repeat that choice.

The default content mode is the **Notes collection**, comprising notes and tasks:

- Entries present in Notes synchronize in both directions with the Organizer.
- Organizer-only entries stay off the phone.
- Removing an entry from Notes removes that phone membership; its Organizer copy
  remains until separately deleted there. Old updates cannot recreate the phone copy.
- An Organizer context-menu action explicitly adds a selected note/task to Notes
  and thereafter keeps it synchronized.
- A new Organizer note also has an initially **unchecked** admission checkbox.
  Its state is not remembered as the default for the next new note.
- The optional full-collection mode also includes Organizer-only notes/tasks.
  The context-menu admission action and new-note checkbox are hidden in that mode.

Time-tracking synchronization is separate. Changing content mode does not change
the time direction or copy notes as a side effect of a time-only synchronization.

## Capability and envelope

Both available `personal_notes_sync` and `personal_tasks_sync` capabilities must
include marker `9` on both implementations. This is a feature marker, not a new
record format; existing record formats remain 1–3.

Message kind: `personal_sync.shared_settings`. Maximum lifetime: one day.
The ordinary authenticated phone message envelope is used. The body has exactly:

```json
{
  "format": 9,
  "settings": {
    "content_mode": {
      "11111111-1111-4111-8111-111111111111": {
        "counter": 1,
        "value": "phone_scope"
      }
    }
  }
}
```

Each field is a register with at most two entries, keyed by the actual paired
device actors. An actor is a canonical UUIDv4. Unknown actors are rejected.
Counters are integers in `[0, 9007199254740991]`; booleans and floating-point
representations are not counters. Unknown fields, types or modes are rejected.

| Field | Values | Default |
| --- | --- | --- |
| `content_mode` | `phone_scope`, `two_way`, legacy `phone_import` | `phone_scope` |
| `auto_mode` | `manual`, `wifi`, `connection` | `manual` |
| `skip_deletions` | boolean | `true` |
| `custom_enabled` | boolean | `false` |
| `time_enabled` | boolean | `false` |
| `time_mode` | `phone_import`, `two_way` | `phone_import` |

`two_way` in `content_mode` means the optional full collection. `phone_scope` is
also bidirectional, but only for the admitted collection. Legacy `phone_import`
retains its original one-way meaning and must not be silently reinterpreted in
old queues, saved policies or sessions.

## Merge and persistence

An explicit edit uses one greater than the highest counter observed for that
field. Initial migration uses counter zero. Receipt/echo never increments a
counter. Fields merge independently; an offline edit to time direction cannot
overwrite an unrelated edit to content mode.

For each origin, a lower counter is an old replay and is ignored. An equal counter
with a different value is a protocol conflict. An incoming local-actor entry may
only echo an already known local edit; a higher or unknown local edit is rejected.
The complete message is validated before any change is committed.

The greatest counter determines the effective value. Equal counters from distinct
actors are concurrent edits and converge deterministically:

- Content: legacy import, then Notes collection, then full collection.
- Time direction: phone import before two-way.
- Enabled switches: false before true.
- Skip deletions: true before false.
- Automation: manual, then Wi-Fi, then any negotiated connection. For initial
  counter-zero migration only, preserve an existing Wi-Fi opt-in ahead of a
  default manual value; never broaden it to arbitrary transports.

A subsequent explicit choice at either end receives a greater counter and can
change the converged result without repeating the choice on the other device.

Metadata is encrypted and bound to the paired device ID and public key. Preview
reads must not initialize preferences or grant access. Unpair removes metadata;
restoring application content must not roll back preference revision evidence.
Saved preference metadata does not itself authorize any transfer.

## Current-connection evidence

Receipt requires the current authenticated peer/key/session, freshly exchanged
capabilities, grants and own-device controls, plus bilateral capability support.
Content recovery barriers remain in force. The controller must explicitly
initialize the existing preference values before the connection sends or merges
settings; connecting must not replace choices with guessed defaults.

Only a successfully sent, current stored snapshot is remembered as sent evidence.
The received snapshot must still equal the current merged stored snapshot before
the connection reports agreement. Old queued snapshots cannot overwrite newer
choices. Duplicate delivery re-establishes evidence on the current connection
without reapplying an edit or causing an echo loop. A changed payload using an
existing message ID is rejected.

Applying these preferences to the actual content, custom and time controllers is
a distinct integration step. The preference codec must never be treated as an
implicit OS permission, new pairing or grant to another computer.
