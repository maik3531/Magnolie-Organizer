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
claim that general resume protocol, accepted Windows delivery, an Android SAF photo-folder
selection or completed physical-device acceptance. Those remain in #246.

This source change is not an installed test package or a public release.

## Windows receiver source and acceptance boundaries

`KdeShareProtocol` now reads strictly bounded standard file payload envelopes
and metadata-only growth updates. Extra envelope fields remain forbidden for
other packet types. Windows file-name validation also rejects device names,
alternate streams, path separators and unsafe Unicode controls.

`KdeIncomingFileBatch` supplies the corresponding native, connection-bound
staging/manifest object. It requires fresh device/certificate/generation/clock
observations, an exact private staging directory, actual size/SHA-256 reads,
and a complete sealed list before review or handoff. Returning a preview does
not expose staging paths or widen the internal list. Cleanup touches only
staging files adopted by that object, not files handed to an accepted offer.

The manifest objects themselves do not start a listener or authorize receiving.
They are connected through the backend and bridge described below, not through
peer-supplied authority callbacks. Source-host tests are not evidence of a
Windows GUI or physical phone transfer.

The Windows payload transport separately checks a private IP, permitted KDE
port, pinned certificate and peer identity using mutual TLS. It writes only to
an already-owned staging stream, checks the exact advertised byte count and
EOF, reports actual written-byte progress, and returns a size/SHA-256 witness.
Source revocation, cancellation, extra or missing bytes produce no successful
receipt. A payload receipt is neither consent nor a completed destination save.

`KdeIncomingFileOffer` then owns exactly the handed-off staging list. Its
destination publisher checks the copied byte witness and executes each atomic
no-overwrite move through a native publication gate, rechecking source and
cancellation inside that gate. The backend must serialize the gate with source
and permission changes; IPC cannot provide that callback or invent a staging
list. Saved members are recorded at the actual move, before later cleanup or
acknowledgement can fail. Retrying a partial operation retains the same target
directory and does not republish completed members. Cleanup never removes saved
destination files. An IPC caller cannot directly supply a publisher, staging
list or native authority callback.

The native Windows backend now connects these parts behind an explicit
selected-paired-device opt-in. Its bounded worker stages the actual pinned-TLS
payloads, produces one complete offer, and accepts/rejects only native offer
IDs. Configuration, connection, source and deadline changes revoke the lease;
in-flight operations retain their reservation until cleanup has finished.
Partial retries keep the originally selected destination and saved events are
deduplicated. The existing discovery/expiry loop and tracked shutdown are used.
Unknown files in an owned cache directory are preserved and reported rather
than recursively removed. Disabling file reception does not replace the device
identity or terminate the ordinary control connection.

Capabilities remain disabled by default. The Windows settings panel now exposes
file-only opt-in for a selected paired device. The bridge captures a native book
owner token and requires ready/unlocked/not-restoring state; ordinary saves do
not change that owner or revoke an unchanged receive configuration. Lock,
restore or owner changes invalidate the captured permission.

Each queued offer is checked again by its native ID before displaying the full
file list. Acceptance invokes exactly one native folder chooser; a partial
retry uses the already bound destination without asking again. The frontend
cannot supply a target path. Cross-platform saved folder/clipboard preferences
are preserved but are not applied as Windows destinations or clipboard support.
Copying runs outside the bridge command lane, participates in restore fencing,
and rechecks the native owner before starting. Expired/rejected dialogs cannot
be resurrected by late validation responses. Intentional disabling/rejection
is not reported as a transfer failure.

Genuine control-and-payload loopback TLS tests cover the backend. A bounded host
compiles the actual receive bridge partial, substituting only the native modal,
scheduler and service boundaries; DOM tests use the actual Windows frontend.
These checks and a Windows-targeted compilation do not replace the outstanding
installed Windows GUI and physical-phone acceptance. No new installer is
delivered or approved by these source changes.
