# Explicit media inventory request (reserved device status 23)

This supplements `media-preferences-v23.md`; capability 23 remains unadvertised
until the complete required media runtime is available. It does not extend
personal synchronization or confer filesystem, native media or OS permissions.

## Current-channel request

`file_transfer.sync_request` uses the existing authenticated message envelope,
a fresh UUIDv4 message ID, and a maximum TTL of 60 seconds. Its exact body is:

```json
{"format":1,"settings":{"format":1,"settings":{"…":"all eight current registers"}}}
```

`settings` is the entire exact persisted and bilaterally confirmed media snapshot,
including actor clocks. Partial settings, paths, album IDs, extra keys or local
permission claims are rejected. Both peers must currently support 23, the master
and at least one domain must be on, and native metadata must be current. A request
does not change any preference, request OS access, or enable automatic operation.

The independent registers are `enabled`, `photos_enabled`, `videos_enabled`,
`collection_mode`, `auto_mode`, `direction`, `skip_deletions`, and `photos_only`.
The metadata filter register defaults to false; adding its codec is not proof
that metadata filtering or the full shared runtime is implemented. Concurrent
equal-clock filter choices resolve to true (the narrower inventory).
The Android outgoing gallery inventory now evaluates this filter using actual
native READ bytes: an EXIF camera make or model plus a valid original capture
timestamp. A filename, extension, camera-named directory or modification time
alone never qualifies. Missing, redacted, invalid or unsupported EXIF is excluded;
this is a selection criterion, not proof that metadata has never been edited.
EXIF inspection is bounded to 1 MiB, uses existing READ without requesting
unredacted location access, and revalidates the source even for excluded members.
Video inventory is unaffected. Exclusion does not attest deletion. Android new-row
publication also enforces the matched filter on original verified incoming bytes
before making the row visible. Rejected entries remain pending with their verified
bytes and journal intact; they are not published, deleted or acknowledged as saved.
Historical published-row readback retains its independent original-proof rules
rather than applying today's selection filter retroactively. The Linux mapped-PC
source also checks the matched filter against its original owned file descriptor
before creating a frozen sending cache or returning a source observation. Its
bounded standard-library reader recognizes JPEG EXIF, TIFF and PNG eXIf; other
formats are excluded while filtering. It preserves original bytes and mappings,
and still requires separate current sending consent, intent and saved-book proof.
Windows source/filter integration and the complete productive shared runtime
remain unfinished. These components do not enable the reserved runtime or expose
the unfinished cross-platform filter control.
Only authenticated protected stored records with exactly the previous seven
registers may be projected to eight by adding local `photos_only=false` at clock
zero. This projection does not write on read or alter any existing register.
Other incomplete stored records remain invalid. Wire requests are never repaired
by this storage migration and still require the entire current snapshot.

The phone sends once on its current secure channel, without a durable outbox or
reconnection replay. One pending explicit request per phone channel is allowed.
The PC authenticates and records the incoming ID before the secure ACK, then
schedules its tracked native worker only after successful ACK output. An exact
duplicate never schedules another worker. ACK means receipt, not completion.
Failure or disconnection never turns into automatic retry on a new channel.

The worker additionally requires the independent local PC receiving right,
the current durably saved book, a current exact agreed snapshot, native destination
ownership and real file-control/data ACKs. It shares the existing exclusive worker
lane and real cancel/Saved/END cleanup. The request remains bound to its original
connection and unchanged register snapshot throughout admission and IO.

## Correlated result

After the actual owned content pass and cleanup, the PC sends once on the same
channel, with maximum envelope TTL 60 seconds:

```json
{"format":1,"request_id":"UUIDv4 of request","state":"content_pass"}
```

The only states are `content_pass`, `review`, and `held`. `content_pass` describes
that content phase only: it is **not** proof of complete two-way synchronization,
deletion propagation, backup maintenance, authoritative absence or recovery upload.
`review` indicates incomplete coverage or explicit source choices still required.
`held` reports failure or withdrawn authority without discarding original bytes
or history. No result grants permission or starts another run.

The phone accepts a result only for its pending request ID, the same in-process
agreement owner and exact still-matched snapshot. Edits, metadata withdrawal,
off/on, channel closure, rejected request ACK or a failed request write withdraw
the pending action; old results cannot revive it. Pending UI ownership is bounded
to two hours. Neither endpoint stores the result for cross-channel replay.
