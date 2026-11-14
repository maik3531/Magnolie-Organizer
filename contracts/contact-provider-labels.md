# Native contact provider labels (#576)

Current #618 scope: Windows now connects an explicit native session-consent
dialog, native WLAN-first update commands and SaveACK-gated frontend scheduling
for eligible collections in its currently configured Nextcloud/generic-DAV
account. Default is OFF; no imported list or discovery result grants access.
Controlled full-frontend/native-controller/encrypted-save tests are distinct
from installed native dialog, real WLAN detection and live-provider acceptance.
Other provider types, additional account management, Linux and the full Notes
scalar/postal return path remain outside this connected Windows path.

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
tests. This entry point alone did not connect the automatic caller or consent
authority; subsequent Windows integration is described below. Linux and the full
Notes scalar/postal return path remain open. This is not an all-provider delivery
or installed-package acceptance claim.

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
continues under #618 after the partial scope of #582.

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
or installed-package acceptance. This factory alone grants no permission;
session consent and the Windows caller are described below. Persistent
cross-session consent is not implemented.

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
does not persist consent across application restarts. The authority itself does
not implement a dialog; the Windows caller below supplies it. Discovery is never
an affirmative decision.

Sixteen controlled authority scenarios check these decisions and lifecycle
boundaries. The factory scenarios additionally consume approvals captured from
this authority before actual controlled DAV IO. Native decision callbacks are
synthetic test decisions, not acceptance of installed consent UI or automatic
frontend-to-provider delivery. Linux and persistent cross-session approval
management remain separate outstanding integration work.

## Saved-book DAV orchestration (#618, intermediate)

`ContactSourceSavedDavRun` connects native saved-book capture, separately captured
native approvals, current-account resolution, the per-source DAV factory and the
update-only coordinator. Invalid saved/restore state is rejected before discovery.
Approvals alone do not trigger IO: a source must also have a dirty, existing
original contact binding. Missing approvals, unbound contacts and already clean
sources cause no provider IO. Duplicate source approvals reject the run.

Unavailable/revoked/unknown/non-writable sources are held with source-local error
counts while another independently admitted source may proceed. Cancellation or
an exact native saved-book change still aborts globally. Each factory shares that
native book/lifetime guard and must complete the mandatory protection callback
before mutation. All opened factories are disposed, including failed runs.

Nineteen controlled orchestration scenarios combine real atomic synthetic book
writes/native save witnesses, two separate provider accounts and original UIDs,
session-scope approvals, actual DAV adapters and synthetic pre-contact snapshot
files. They check permission/discovery failures, revocation, account misrouting,
restore/save/context fences, failed/revoked/cancelled protection and changed
readback. A separately persisted synthetic result is clean on the next run with
no redundant discovery/content IO. Returning a result itself does not save any
baseline or advance a cursor. One scenario additionally passes actual provider
readback results through the native one-use result-save authority and actual
`SaveAsync` source in the existing controlled encrypted native save host. This
does not itself test the frontend or native dialog. Subsequent caller checks
are described below; Linux and the full Notes return path remain outstanding.

## Exact native result-save authority (#618, intermediate)

`ContactSourceSavedCommit` stages contacts only for the exact native original
saved book and retains every other document domain unchanged. A one-use native
token authorizes only that exact candidate under the existing native writer's
mutation gate. The Windows `SaveAsync` path accepts the optional result token,
rejects forged/stale/mixed-source saves and uses its existing snapshot,
encryption, atomic writer and save-witness hooks. It does not add a second data
writer or skip recovery/snapshot handling. Result completion is acknowledged
only after the same native book has the next successful save sequence and the
exact payload hash. Failure, an unconfirmed write or a reused token does not
acknowledge delivery. Ordinary saves still work but do not claim a result commit.

Fourteen controlled authority cases cover identity, exact candidate/context,
proof reuse/replacement, failed writes and absent/wrong native witnesses. Eight
additional cases execute the actual extracted `SaveAsync` source with encrypted
atomic files: success/replay, forged token, mixed content/tree proof, changed or
locked book, post-primary-replacement failure and an ordinary unclaimed save.
The GUI/reminder/cloud endpoints of that existing save host are test endpoints;
these checks do not claim installed GUI or automatic frontend delivery acceptance.
This authority alone does not schedule updates; the connected caller follows.

## Connected Windows session caller (#618)

The synchronization settings expose **Original contact sources** and **Revoke**
only when the native host advertises this command capability. Configuring sources
first waits for the actual document SaveACK, then opens a native modal checklist.
The dialog defaults to no new selections, shows the collection URI and explicitly
limits consent to this session, existing contact bindings and WLAN-only automatic
updates. Closing/cancelling is not affirmative consent. Unsupported provider types
are not routed through the configured DAV account.

`ContactSourceNativeSession` supplies the actual native command implementation:
fresh account/discovery validation, exact saved-hash fencing, revocable approvals,
WLAN checks around each provider admission and one mandatory native PreContact
snapshot per original book/run under the existing mutation gate. Unknown network
state holds the run. Native revocation invalidates pending result authority and
cancels its own active run without waiting behind that network command. The
production dispatcher uses its existing background/network lifecycle and sync
lane; the dialog is marshalled to the native UI thread and is cancellable.

Every subsequently acknowledged user save may plan dirty authorized original
sources. Status/discovery and imported settings cannot enable this scheduler.
An outstanding run is not retried on a timer or assumed failed after a timeout.
The frontend accepts a result only for the unchanged book reference, exact
acknowledged text/hash and request generation, with no newer edit/editor or
pending save; original contact IDs/UIDs must match. Only the exact result candidate
carries the native one-use save proof. A matching native result SaveACK completes
that adoption without immediately retrying held sources. A failed/unknown result
save revokes the automatic session and preserves user data instead of declaring
delivery or blindly retrying. Stale/revoked/reloaded-book results cannot overwrite
newer edits. Later ordinary saves remain available.

Fifteen controlled native-session cases check consent, cancellation, restore and
saved-book fences, WLAN loss and protection failure/revocation. Fourteen actual
full-frontend cases check SaveACK gating, source-local failure preservation,
stale/foreign/revoked results and failed/unknown result saves. A bounded host
roundtrip connects the actual frontend through actual encrypted `SaveAsync`
ACKs to the shared production native session/controller, two controlled original
DAV collections with different native UIDs, provider PUT/readback, one pre-contact
protection file and the actual encrypted result save/commit ACK. Those two
collections share one configured account: this is not a two-account GUI test.

The native dialog decision and WLAN predicate in controlled tests are synthetic
native callbacks, not installed modal-UI or physical network acceptance. The
product dialog/dispatcher are source-built; real dialog/queue/WLAN/device and
live-provider acceptance are not claimed. Pending offline sources remain pending
until another acknowledged edit or explicit configuration attempt; autonomous
WLAN-return retry, broader providers/accounts, durable cross-session consent,
Linux and full Notes scalar/postal return remain follow-up work under #618.
New consent messages may fall back to English until their catalog integration;
localized installed-dialog acceptance is not claimed by these source tests.
An opt-in native modal probe uses only a blank owner and synthetic catalog, with
no profiles or provider IO. The available noninteractive Windows runner refused
`ShowDialog`; an approved interactive session is required. The production consent
dialog is not relaxed into a service notification to work around that boundary.

## Independent Linux contact saved-book witness (#618, intermediate)

The Linux native save worker now records `NativeContactSourceBook` independently
of the phone actor's owner. The existing GUI readiness/lock lifecycle controls its
native identity. Before the actual writer touches snapshots, encryption or
storage it clears the old contact witness without resetting the successful-save
sequence. Only the existing writer's confirmed, unrepaired completion records a
new witness. No document `saved` flag, source list or claimed revision can do so.

Linux's raw-text SaveACK hash and the parsed native book's canonical fingerprint
remain separate. Fresh capture checks both native observations and exact current
content, including legitimate fractional drawing coordinates. Changed, locked,
unavailable or unconfirmed books are held. Phone-actor sync/operation fences are
not relaxed to make contact capture succeed.

The general writer's existing post-rename readback and repair semantics are not
changed: it may acknowledge a committed document with `repairPending`. Such a
state still has no contact-update witness until a later unrepaired native save.
An epoch rejection or rejected historical job never reaches the native writer
and does not manufacture a new witness. Existing encryption, recovery snapshots,
retention and reminder handling remain in the same writer.

Twenty-four controlled cases include actual encrypted/atomic worker writes,
pre-write invalidation, post-rename uncertainty/readback repair, reminder repair,
lock/readiness/context changes and source manifest coverage. Ninety-two affected
native save/restore/phone-actor regressions and thirty-two isolated source/runtime
manifest tests pass. Debian, RPM, AppImage and Flatpak source manifests include
the new helper; no package build, installation or live-provider test is implied.
This is only the Linux saved-book boundary: no automatic source scheduler,
source approval, update-only provider coordinator, result commit or full Notes
return path has been connected on Linux by this step.

## Linux native DAV approval/factory boundary (#618, intermediate)

`NativeDavApprovalScope` starts empty and accepts only an explicit native
user-decision callback over a native catalog. Imported source lists, `eigen`, a
document `saved` flag and current capability discovery do not grant updates.
Consent binds the native book identity and current opaque account/credential
revision; cancellation retains existing consent, an explicit empty selection
revokes it. Unknown/duplicate selections and decisions overtaken by book/account
change or revocation cannot grant access. Captured approvals are generation-bound
and cannot revive after revocation/reapproval. This is session-local, not a
persistent grant store or an implemented Linux consent dialog.

`NativeBoundDavFactory` uses `NextcloudSettingsStore.checked_client` to pin the
actual account/credential context. It requires an exact native approval and
native-bound original resource set, current book/lifetime callbacks, strict native
codec observation and an obligatory pre-mutation protection callback. It matches
the account type, source ID, origin and exact collection and discovers explicit
`canUpdate is True` afresh. Unknown/non-writable sources hold. It rechecks after
protection and at each credentialed request, including same-origin redirects.
The new optional native request hook defaults to `None` for existing manual DAV
clients and is not populated by configuration or IPC JSON.

Only a freshly read, existing bound resource can enter the factory's update
phase. That phase requires its exact strong ETag in `If-Match`; create/delete,
unbound/retargeted requests, ambiguous bindings and unsafe path aliases are held.
The outgoing native UID must equal the pre-write observed UID. Actual readback
must have the same original resource/UID, receipt ETag and desired content hash;
missing/changed identity cannot be hidden by a content hash that excludes UID.
Failed reads or uncertain attempts invalidate cached writable receipts. Returning
verified native source data does not save a local contact baseline or cursor.

The strict automatic-update vCard observer reuses the existing native lexer/parser
and contact hash but rejects multiple/missing/padded native UIDs or multiple cards.
It does not change the tolerant manual-import parser or normalize stored contact
identities. Mandatory native callbacks are not renderer flags.

Fifty-three controlled factory/approval cases use actual native account snapshots,
DAV discovery/conditional PUT/readback, native vCard codec/hash and atomic synthetic
book/protection files. They cover both DAV account types, denial/unknown rights,
revocation/credential changes across redirects or protection, malformed identities,
strong revision guards, request routing and non-reusable failed reads. The 111
existing Nextcloud regressions and 32 isolated runtime/source manifest cases pass;
source manifests include the helper without building or installing packages.

This remains a native component boundary, not a Linux all-source scheduler:
the coordinator must derive dirty bindings from the exact saved snapshot, apply
source-local revision/conflict/Notes-priority decisions and isolate provider
failures while aborting globally on changed book/cancellation. Native consent UI,
dispatcher/frontend and durable result commit are still unconnected. EDS/Akonadi,
broader accounts/providers and full Notes scalar/postal return are not granted or
claimed by this DAV factory.

## Linux saved-contact update planning and orchestration (#618, intermediate)

The native `kontakt_quellen_update_bindungen` selector derives only dirty,
sync-enabled, existing original mappings from an exact native saved snapshot.
Timestamp-only/unknown baselines, unbound contacts and default-book exports are
not admitted. Duplicate bindings remain ambiguous even if one copy disables sync.
`kontakt_quellen_update_plan` runs the existing pure merge policy for exactly one
bound native card, rejecting any create/delete, identity or source-mapping change.
The outgoing UID comes from that original card, not the canonical contact UID.
Changed content behind an unchanged ETag holds. Label/content-time/provider
conflicts reuse existing policy rather than guessing a new last-write rule.

`kontakt_quellen_updates_vorbereiten` connects that planner to native session
approvals and the bound DAV factory. It rechecks the exact native snapshot and
cancellation after source errors and between operations; unavailable/revoked or
conflicting sources do not disable other original books. Only successful actual
readback advances that source's proposed baseline; failures retain its old one.
Source-specific conflicts stay on the canonical entry. All results remain an
**unsaved proposal**, not an adoption/save ACK or renderer permission.

The native protection callback `_kontakt_quellen_schutz` uses the existing journal
writer and actual archive readback, verifying full exact current-book coverage.
The journal writer's new opt-in `exakt=True` prevents content-only deduplication
from reusing a snapshot with older metadata/settings. Existing periodic/manual
journal behavior is unchanged by default. A changed book, failed protection or
non-exact readback prevents delivery; archive migrations are not silently accepted
as exact current-book coverage.

Forty-one new controlled selector/planner/coordinator/protection cases pass,
including two original books with isolated failure/revocation/conflict/uncertain
write and actual encrypted/plain journal roundtrips. The combined affected run
passes 193 tests plus the existing journal modules' import-time assertions. This
is not installed UI acceptance: Linux consent UI/dispatcher/frontend, one-use
result-save authorization and actual result commit remain to be connected.

## Linux native one-use result writer (#618, intermediate)

`NativeContactSourceResultCommit` now binds the exact proposed JSON to the current
native saved snapshot and native run/session callback. It preserves contact
identities and other book domains, consumes itself on any attempted invocation
and cannot authorize a differently serialized payload, a stale/later-saved book,
or a renderer-issued object. The native-only queue helper invokes the existing
real serial save worker, encryption, atomic writer, reminders and saved witnesses.
Its non-renderer request ID cannot acknowledge a renderer save request.

Confirmation requires the actual writer ACK, no pending repairs, exact payload
hash and the newly observed native book/save sequence. The existing general
`committed=true, repairPending=true` behavior remains unchanged, but cannot confirm
this contact result. Failed or uncertain attempts cannot reuse the invocation.
The historical writer path and ordinary saves keep their separate fences.

Twenty controlled cases pass, including a connected synthetic DAV plan/conditional
PUT/readback -> exact encrypted recovery archive -> native-only queue -> actual
encrypted result writer -> new native saved witness. Changed/revoked inputs,
impostors, mixed proofs, payload mismatch, unknown outcome, repair states and reuse
are held. The affected combined run passes 182 cases; its 12 historical GUI-source
cases initially skipped for missing Node selection and then pass with the existing
explicit Node/Python paths (no dependency installation). Native consent dialog,
dispatcher/frontend SaveACK planning and safe result adoption are still unconnected;
this is not installed UI or autonomous synchronization acceptance.
