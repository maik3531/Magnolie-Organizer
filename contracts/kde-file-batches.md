# Reviewed incoming KDE file lists (#246)

## Linux receiver

An incoming multi-file announcement is collected for the selected paired device
and its exact authenticated control connection. KDE's `numberOfFiles` and
`totalPayloadSize` are collection hints, **not** a grant or a unique batch ID.
The receiver never treats equal aggregate values as permission to save a later
file. Consecutive completed lists receive independent local offer identities.

Only a complete staged list with the exact advertised byte sum is offered.
The dialog displays all member names and sizes in a scrollable list. One
confirmation and, when enabled, one destination selection apply to that sealed
list. The native background notification also carries the member list and uses
one destination chooser. No file is opened automatically.

Every staged member has a size and SHA-256 witness. Publication checks the
reviewed bytes, the configuration generation, selected device, paired
certificate, original connection and offer deadline again. In particular,
revocation during an integrity read prevents the subsequent publication.

The receiver stages at most 128 members per list and reserves at most 400 MiB
across open multi-file collections/offers. Existing 50 MiB per-file and eight
pending-offer bounds remain. Growth updates may increase an unsealed collection
within these limits; shrinking/invalid metadata cancels that collection.
Incomplete, interrupted or expired collections are not proposed.

Existing destination files are never overwritten. Name collisions receive
numbered alternatives. A destination on another filesystem uses a private
temporary copy, an integrity readback and a no-replace publication operation.
If publication fails part way through, successful members remain saved; only
the unsaved members remain in the original offer for a retry at the same
destination. Rejecting or expiring the remaining offer does not remove saved
destination files. Errors are reported rather than silently accepting the rest.

## Protocol boundaries and remaining work

KDE does not supply a unique immutable batch identity in these packets. An
interleaved sender on one connection cannot be assigned to original Android
share intents solely from equal counts/totals. Consent is therefore bound to
the actual complete displayed file list, not to an inferred intent or unknown
future members. No late extension can widen an already reviewed list.

A job which initially announces a single file and later adds files after that
file has already been offered is not covered by a previous confirmation.
General resumable transfers need a separately negotiated immutable manifest,
file identities, offsets and final integrity receipts. This receiver does not
claim that general resume protocol, Windows parity, an Android SAF photo-folder
selection or completed physical-device acceptance. Those remain in #246.

This source change is not an installed test package or a public release.
