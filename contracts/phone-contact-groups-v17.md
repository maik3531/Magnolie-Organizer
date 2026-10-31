# Live Notes contact-group writes (device-status version 17, #252)

This resource is separate from read-only contact version 5 and tree contact-sync
version 4. It requires an own-device pairing, current read authorization,
separate group-write setting (enabled by default), Android READ_CONTACTS and WRITE_CONTACTS,
and negotiated device-status version 17. Version 16 does not contain the account
binding and must not be advertised or accepted as an equivalent write resource.

The per-computer/key setting remembers an explicit disable independently of
Android permission availability or contact-read availability. A temporary missing
permission must not silently change the user's setting; it still suppresses the
write capability and all native writes. Enabling the setting never bypasses an
Android runtime permission request.

Requests use the authenticated `device_status.request` transport. Prepare has
exactly `version: 17`, UUIDv4 `request_id`, `action: "prepare"` and exact native
contact `uid`. Apply has the same fields with `action: "apply"`, plus UUIDv4
`token` and `groups`. Names are bounded to 100 distinct nonblank names of at most
256 Unicode scalar values, without controls or unpaired surrogates. Reports are
bounded to 128 KiB.

Both reports contain exactly `version`, `request_id`, `action`, `uid`, `token`,
`state`, `groups`, `catalog`, and `account`. The account has exactly string fields
`name`, `type`, `data_set` (each at most 256 scalar values, without controls or
unpaired surrogates). Empty account fields represent a local provider account;
they do not authorize selecting an unrelated account. For an aggregate with
linked raw contacts, a unique account owning an editable group catalog can be
selected; all reads, assertions and writes are then scoped to that account's raw
rows. Group-less messaging overlays are preserved. Multiple group-owning accounts
remain ambiguous and are rejected rather than guessing the first raw account.

Prepare returns `state: "prepared"`, actual editable memberships, and the
account-bound editable catalog (at most 1000 names). Native tickets bind the
exact contact snapshot, raw-contact versions, catalog assertions, account and
live authenticated session. At most eight tickets exist for 30 seconds. Desktop
preparations expire after 25 seconds. A reconnect, grant removal or key/channel
change cannot reuse them. They are transient and never enter a persistent outbox.

Apply consumes the ticket before provider I/O. Membership replacement uses the
existing atomic provider batch and its contact/catalog assertions. Automatic and
favourite memberships, other contacts and global groups are preserved. The reply
has `state: "saved"`, an empty `catalog`, the same token/account, and memberships
read back from the provider. Transport acceptance is not a saved receipt. This
receipt establishes Android-provider state, not completion of cloud replication.

The desktop retains an explicit local edit and its previously observed common
source baseline. Editor save starts a live write only after durable local save
and only for a unique exact Notes source/key/UID binding with write availability.
An unknown historical baseline stays pending during automatic sending. A new
explicit local edit may adopt its actually observed source as a comparison
baseline. Explicitly saving the contact editor also confirms an already retained
pre-baseline group selection, even when its selected names have not changed.
This does not authorize adopting an observed source during an automatic retry or
phone read, and does not replace an already established common baseline.
Prepare must still match that
baseline; otherwise its actual groups become the observed remote change and no
apply is sent. Existing provider labels are reused through the established UI
alias mapping; ambiguous catalog aliases abort rather than create duplicates.
Book/epoch changes, editing, locking, source changes, removal and concurrent local
group edits invalidate the operation. Pending intent clears only after an actual
matching source readback; all callback identities and the saved token/account
are checked. Group edits participate automatically after local save, peer
availability updates and completion of a normal synchronization run. There is
no separate Send button. A background thumbnail scan yields to the pending write;
its late replies cannot change the captured group intent. Retry is throttled and
always starts a fresh prepare, never replays a persisted apply ticket.
