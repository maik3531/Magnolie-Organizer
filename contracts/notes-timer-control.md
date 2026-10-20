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

## Remaining integration gate

This native execution boundary alone does not advertise timer-control capability
or register MCP actions. A separate strictly typed negotiated request/report
contract, native source-bound transport, cancellation/late-result handling and
the desktop MCP tools must be connected and tested before remote control is
offered. A queue or ordinary transport acknowledgement is not a successful timer
save. Existing unsupported peers must remain explicitly unsupported.
