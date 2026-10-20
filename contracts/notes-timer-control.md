# Native Notes timer control (#191)

The running timer belongs to Notes. The desktop completed-record editor is not
a remote start/pause/resume/finish API, and a TimeSync batch is not a command.

## Native execution boundary

`ZeitSteuerung` validates a bounded command and calls the same
`ZeiterfassungStand.start/pause/resume/finish` handlers as the Notes UI. Native
time and zone determine execution; commands cannot supply a timer timestamp or
an arbitrary vector clock. Start uses its operation UUID as the durable entry
identity. Other actions require the exact active entry UUID. Disabled tracking,
multiple active entries, stale state revisions and reopening completed/removed
identities are rejected.

The state revision is server-generated from the current native timer state. It
is a compare-and-swap input, not authorization. A transport adapter must still
verify the actual paired key, exact current channel, fresh capabilities and
grants, both own-device decisions and the applicable time settings.

Each successful mutation stores a bounded local receipt in the same encrypted
book write as the timer change. It binds operation UUID, native peer-key hash,
request hash, actual restore epoch, action, entry UUID and resulting clock. Exact
retries return the prior operation receipt without repeating the change; another
key, epoch or payload cannot reuse it. Receipts are local metadata and do not
enter the TimeSync record projection. Evicted operation identities cannot reopen
an existing completed or locally removed entry.

`Ablage.steuereZeiterfassung` checks the actual book restore epoch and uses the
existing `aendereZeiterfassung` encrypted atomic writer. State and receipt become
visible only after that writer returns. A failed write publishes neither. The
initial empty native restore epoch is valid only when it is the actual current
book epoch; a restored/different epoch is rejected before mutation.

## Negotiated transport

The separate `time_tracking.control_request` and `time_tracking.control_report`
messages use version 13 of `personal_tasks_sync`. Shared strict vectors are in
`time-control-v13.json`. A full application message is bounded to 192 KiB and a
60-second lifetime. Reads carry no mutation fields; commands carry an operation
UUID, state revision, restore epoch and, except for start, the active entry UUID.
There are no caller-controlled execution timestamps or vector clocks.

The Notes receiver checks the current paired key, channel, generation, enabled
service, fresh controls, both own-device confirmations, both version-13
capabilities and current enabled time policies. A shared `phone_import` policy
denies mutations. The ordinary capabilities receiver preserves negotiated
version 13. It does not advertise local support on its own.

Python and Windows controllers bind ephemeral requests to the actual profile,
peer/key, exact connection and current permissions/settings. They bound pending
requests to eight, retain at most 128 active/retired request identities and wait
at most 15 seconds. Reports must match the request and operation UUID, current
source and lifetime. They do not enter the ordinary outbox, GUI event stream or
status cache. Owner-bound cancellation stops waiting; it does not recall an
already dispatched command. Late replies cannot complete a replacement request.

An ordinary acknowledgement is not a successful timer save. Only the correlated
native command report can claim `persisted=true`, after the existing encrypted
book writer returned or an exact durable command receipt was replayed. Read
reports use `persisted=false`; denied reports expose no timer state. The
`runtime_request` field distinguishes `none`, `requested` and `failed` for the
existing alarm/service hooks; it does not assert that an OS service is running.

## Remaining integration gate

Production capabilities still omit version 13. Private native MCP source/query/
cancel adapters exist; public desktop MCP tools, their output schemas, catalog
and localized documentation remain to be connected before offering control.
Existing unsupported peers remain explicitly unsupported.
