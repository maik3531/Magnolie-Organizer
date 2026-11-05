# Explicit media inventory request (reserved device status 23)

This supplements `media-preferences-v23.md`; capability 23 remains unadvertised
until the complete required media runtime is available. It does not extend
personal synchronization or confer filesystem, native media or OS permissions.

## Current-channel request

`file_transfer.sync_request` uses the existing authenticated message envelope,
a fresh UUIDv4 message ID, and a maximum TTL of 60 seconds. Its exact body is:

```json
{"format":1,"settings":{"format":1,"settings":{"…":"all seven current registers"}}}
```

`settings` is the entire exact persisted and bilaterally confirmed media snapshot,
including actor clocks. Partial settings, paths, album IDs, extra keys or local
permission claims are rejected. Both peers must currently support 23, the master
and at least one domain must be on, and native metadata must be current. A request
does not change any preference, request OS access, or enable automatic operation.

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
