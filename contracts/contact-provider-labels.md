# Native contact provider labels (#576)

Telephone, email and postal-address values are compared separately from their
provider labels, types and roles. A metadata-only difference does not require a
value-conflict decision. Existing exact source hashes and baseline formats are
unchanged; this classification is not a weaker write authorization.

When both content times are usable and the original remote source revision has
actually changed, a newer incoming content version supplies the canonical labels.
Otherwise the existing canonical representation remains. A timestamp resulting
from our own acknowledged provider write is not a newer user edit. Unknown or
implausibly future times do not establish newer content. Equivalent Home/Privat
representations do not require repeated writes.

Older writable sources receive the canonical representation through their existing
source-specific write path. Read-only sources are not written. A planned Linux
write is not a successful provider acknowledgment: actual handlers retain their
ETag/readback bookkeeping. Windows write failures retain the original baseline.
Real value differences, group changes, photos and opaque metadata are not labels.

Checked scope: native Linux planner with controlled DAV books and actual vCard
writer/parser roundtrips, EDS planning, and native Windows engine tests with
controlled remotes plus the existing Windows contact/Graph regression group.
These are not physical provider/phone delivery tests or installable-package
acceptance. General all-source fanout and the full Notes postal/scalar write path
are separate from this correction (#575).

## Source-local failures (#581)

Linux DAV and EDS/Akonadi contact handlers do not change the contact's global
`sync` marker because one source write or EDS readback failed. The failed source
does not advance its acknowledged content baseline or successful source cursor.
Other original source mappings remain intact. In particular, an EDS baseline
recorded while planning is restored to its prior state on failed/uncertain
delivery. Retrying reads the provider again before making a new decision; a
successful second provider does not acknowledge the failed first provider.

This is checked with complete native handlers and controlled source adapters,
including creation, updates, label-only updates and failed readback. It does not
itself add an automatic scheduler for every provider or prove physical delivery.

## Original source identities (#583)

The regular Linux contact planner resolves an existing EDS/Akonadi source binding
by its original record UID and a DAV binding by its exact stored resource href.
It does not substitute a new identity based on a name or matching phone number.
Updates serialize the original source UID; the canonical local contact UID remains
unchanged. Readback and source baseline acknowledgment use the original source
record, including when a second provider has a different UID for the same person.
Ambiguous bindings or a colliding canonical UID in that source refuse planning.
Deletion uses the bound source UID and retains canonical tombstone identity on
failure; existing revision checks still apply.

Windows CardDAV already preserves `remote.Data.uid` in its outgoing copy. That
existing protection was not a new Windows bug. The new Linux correction is checked
with controlled whole EDS/DAV handlers and planner guards, not live accounts or
automatic permission to synchronize additional providers.

## Saved-book boundary for original-source updates (#582)

The Windows update-only coordinator now has a native saved-book entry point.
It captures contacts from the existing `NativeActorBookSnapshot` durable-save
witness, not contact JSON or a "saved" flag supplied by a renderer. The native
book source, successful-save sequence and exact saved hash must still match
before source IO and before returning the result. Locking, an unconfirmed save,
changed content or an invalidated book stops execution. Pending initial/restore
reconciliation also holds automatic updates.

Source admissions remain a separate trusted native input: neither source
mappings nor an imported source list grants access. Without admissions there is
no provider content IO. This boundary does not create or delete contacts, enable
accounts, add a default-addressbook fallback or advance a global success cursor.
It returns a bound result; it does not silently persist returned baselines.

Checked with real atomic synthetic file writes and the existing native save
witness, controlled two-provider DAV adapters and original provider UIDs/ETags,
including failed-after-replacement saves, lock/content/context changes, restore,
and a document claiming additional source grants. These are not live-provider
tests. The actual automatic frontend/native dispatcher caller, explicit native
source-approval storage and provider factory still need integration; the Linux
equivalent and full Notes scalar/postal return path remain open. This is not an
automatic all-source delivery or installed-package acceptance claim.

## Native provider identity on readback (#617)

The Windows update-only coordinator separately verifies the native provider UID
observed **before** writing against the actual source readback. Resource ID,
ETag and content hash alone do not witness identity: contact content hashes
intentionally exclude UID, and the adapter receipt may project the canonical
local UID rather than the provider's original UID. Changed or missing native
identity does not acknowledge that source's baseline; another independently
admitted source may continue. Canonical local identity and original revisions
remain unchanged, and unknown delivery is not blindly retried as a new create.

Controlled native DAV tests reproduce the previous false acknowledgment with an
unchanged resource/ETag/content but changed source UID and verify the correction.
The existing complete Linux EDS handler already checks that original written
UIDs occur in its complete readback; separate changed/missing UID regression
cases verify its failed-source baseline and independent second-source behavior.
No new Linux product fix, generic DAV readback acceptance or live-provider
delivery is claimed by that EDS check. The automatic multi-source integration
under #582 remains open.

## Native DAV factory boundary (#582, intermediate)

`ContactSourceDavFactory` opens one dedicated client for one separately approved
original source. Its native input binds the exact source ID, collection URI and
current account/credential revision to a revocable approval callback. Discovery,
contact mappings and imported settings do not produce that approval. Only
Nextcloud and generic DAV account types are admitted; Thunderbird and unrelated
account/source combinations are rejected rather than routed to a default book.

The factory rechecks native approval and book context around fresh discovery,
requires the exact collection with explicit `CanUpdate == true`, and installs
an obligatory pre-mutation protection callback. After that asynchronous callback
it checks approval, account revision, book and actual privilege again before PUT.
Protection failure prevents writing. The update-only coordinator retains its
original-resource/CAS/readback guards. A caller must isolate failure to open one
source from other sources, but propagate cancellation and invalidated book
context globally. The factory and run must share the caller's cancellation
lifetime. Disposing a factory does not dispose an injected shared HTTP transport.

Sixteen controlled factory scenarios run through actual DAV discovery/adapters
and the update-only coordinator, including independent-source continuation,
denied/unknown privileges, wrong account/URI/provider, revocation, credential
change, failed protection, cancellation, book invalidation and changes across
an asynchronous protection callback. Successful delivery is read back and a
second run is idempotent. These are synthetic transport tests, not live-provider
or installed-package acceptance. Persistent native explicit-approval management,
the automatic frontend/dispatcher caller and durable result integration remain
unimplemented; this factory alone enables no automatic delivery or permission.

## Native session approval authority (#582, intermediate)

`ContactSourceApprovalScope` starts empty and has no document/JSON import path.
It offers only eligible native DAV catalog entries to an explicit native
user-decision callback. A cancelled decision retains existing approvals; an
explicit empty selection revokes them. Duplicate, unknown or stale selections
cannot grant access. Changing book/save/account context or revoking while the
decision is pending prevents that pending answer from granting access.

Captured factory approvals remain valid across ordinary durable saves of the
same native book, but not across explicit revocation, locking, book identity
change, account/credential revision change or account deactivation. Previously
captured callbacks are fenced by an approval generation, including revocation
and subsequent reapproval. This authority is intentionally session-local: it
does not persist consent across application restarts or claim to implement a
native dialog. A real native settings decision UI and automatic dispatcher
caller still need connecting; discovery is never an affirmative decision.

Sixteen controlled authority scenarios check these decisions and lifecycle
boundaries. The factory scenarios additionally consume approvals captured from
this authority before actual controlled DAV IO. Native decision callbacks are
synthetic test decisions, not acceptance of installed consent UI or automatic
frontend-to-provider delivery. Linux and persistent cross-session approval
management remain separate outstanding integration work.
