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

## Linux native consent dialog and bridge (#618, intermediate)

The Linux `kontakt_originalquellen_freigabe` bridge command now discovers its
catalog through the actual native account store/client and returns to GTK's main
thread for the explicit modal session decision. IPC supplies only a request ID,
not choices, credentials, rights or selected sources. The default-empty native
scope retains Cancel, treats Apply with no selection as revocation, and rejects
book/account/revocation changes before or during the decision. A revoke arriving
during discovery prevents the delayed dialog from reopening stale intent.
`kontakt_originalquellen_widerrufen` revokes the scope immediately.

The actual GTK dialog is modal, has Cancel as the default action, uses plain text
labels and defaults unchecked unless a current session already selected a source.
Six opt-in actual GTK modal cases pass under the existing isolated Xvfb, including
default-OFF/Cancel/empty Apply/selected Apply/changed selection/close. Thirteen
controlled actual dispatcher/native-discovery cases pass with synthetic network
transport and decision callbacks; the combined affected factory/manifest run
passes 98 cases. The actual modal probe leaves no Xvfb or test process running.
No Organizer window/profile, private originals, live provider or installation is
used for these probes.

The settings button/frontend SaveACK scheduling, Linux update command/controller,
WLAN lifecycle and safe frontend result adoption remain unconnected. This native
consent command alone neither starts source updates nor grants EDS/Akonadi or
persistent consent. New consent strings currently use normal catalog fallback.

The native WLAN observation is independent of NetworkManager, D-Bus, Gio and
external commands. Read-only local `NETLINK_ROUTE` lookups resolve representative
IPv4/IPv6 routes through the kernel (no network packets to the lookup addresses).
Every routable family must resolve to a sysfs-observed WLAN interface with an UP
link and carrier; routes are rechecked after link inspection. An UP but unused
wireless adapter does not authorize Ethernet/mobile/tunnel egress. Unknown states
hold. Thirty-three controlled gate/netlink-parser cases cover daemonless operation,
dual stack, route changes and malformed/error replies; this is not physical
network-manager or device acceptance.

## Linux native update command and frontend-save offer (#618, intermediate)

The Linux native update command now captures the actual saved book, requires its
expected raw SaveACK hash and explicit native session approvals, and connects the
WLAN/book/deadline guards to every bound factory request. It owns a separate
operation flag: manual sync and phone-actor delivery hold during the run without
invalidating the contact operation's own saved snapshot. Recovery protection uses
the exact existing journal once per run; source errors remain isolated, while
book change, cancellation and loss of WLAN abort the operation.

Results are opaque, one-use native offers, not immediate writes to local data.
The ordinary save bridge can consume such an offer but cannot create one. It must
submit the entire exact native proposal: serialization order/whitespace may vary,
but extra edits, identity/domain changes, stale books, unknown/reused tokens and
mixed proofs hold. After validation, the invocation binds that exact submitted
raw text to the actual writer; confirmation still distinguishes raw SaveACK hash
from canonical book-content hash. Revocation clears pending offers.

Fifty-five additional controlled cases cover the daemon-independent WLAN gate,
actual native update command and actual save-bridge offer claims. The final
affected run passes 255 cases, including all twelve historical actual GUI-source
writer regressions with existing explicit Node paths (no skips). A separate
isolated read-only host kernel-route probe works with Gio/GLib absent; it changes
no network settings and sends no remote traffic. No old runtime, network manager,
tool installation or distribution-specific service requirement was introduced.

The full frontend settings/SaveACK scheduler and result-adoption path are still
not connected on Linux. Native-controller and bridge acceptance is not installed
frontend, physical device, persistent-consent or autonomous retry acceptance.

## Linux actual frontend/SaveACK connection (#618, intermediate)

The Linux settings UI now exposes native source consent/revocation when the
native status advertises support. Status counts, imported mappings and saved
document flags cannot enable automatic delivery. After explicit native consent,
planning starts only from an actual completed SaveACK with no unsaved edits,
active editor, pending save or other synchronization. Newer edits, book reload,
revocation, wrong replies/identities/hashes/tokens and unknown save outcomes hold.
Only a native result-commit token confirmed by the real writer releases the
frontend's result-save state; no automatic retry is inferred from a timeout.

The full Linux wire exposed a real schema boundary missed by the earlier
schema-7 component fixture: the frontend saves schema 6, while normal archives
migrate to schema 7. Exact protection now preserves the original pre-migration
book, and an explicitly exact read validates/returns that original. Normal
export/restore migration remains enabled by default. Exact snapshots retain
their original payload when rekeyed; existing ordinary/legacy snapshot rekey
migration remains unchanged. Integrity/token/schema validation is not bypassed.
Windows transferability is a separate unconfirmed check in #619, not a claimed
Windows archive fix.

The actual Linux frontend -> two actual encrypted source SaveACKs -> native
consent/controller -> one synthetic original DAV conditional PUT/readback -> exact
encrypted recovery readback -> native offer -> actual encrypted result save ->
third native SaveACK wire passes. The native decision/WLAN/provider observations
in this wire are controlled; actual GTK modal and kernel probes are separate.
Fourteen full-frontend cases pass for each Linux and Windows source edition, and
the affected native/journal/manifest run passes 265 cases without historical skips.

This connects the session-local DAV path, not the full #618 remainder: persistent
consent, Windows WLAN-return retry, EDS/Akonadi/current provider authority,
broader accounts and full Notes scalar/postal return remain. Installed WebKit/
WebView, physical device/media and package/install acceptance are not claimed.

## Linux authorized WLAN-return continuation (#618, intermediate)

The Linux native session now starts a topology-only monitor after explicit source
approval. A GLib timer schedules at most one bounded worker; route/account/book
checks do not block GTK's main thread and never perform provider IO. Revocation,
lock/book/account loss, shutdown and stale monitor generations stop or discard
probes. Missing optional timer APIs in headless hosts do not become a service
dependency. The monitor still requires neither NetworkManager nor Gio/D-Bus.

Frontend continuation requires a prior terminal native `wlan_required` reply,
existing explicit approval and all actual SaveACK/no-editor/no-pending-edit guards.
Known positive topology can repeat so a previously busy frontend can resume once
idle; it neither grants permission nor retries clean, active or unknown-outcome
runs. Native fresh read/CAS/conflict checks remain mandatory on continuation.

Thirteen controlled monitor lifecycle cases and nine full-frontend continuation
cases pass. Three actual encrypted frontend/native wires pass: immediate WLAN,
initial WLAN hold, and WLAN loss after the provider committed a PUT but before
readback. The initial held attempt performs no provider request. In the uncertain
post-write case, continuation performs a fresh source REPORT and recognizes the
already committed value without issuing a second PUT. Each wire has exactly one
PUT, exact encrypted protection and three actual encrypted SaveACKs. Revocation
or lock during a topology probe is rechecked before any notification.
The previous fourteen frontend cases still pass. Test timers/WLAN/provider
observations are controlled and all owned workers are joined; this is not a
physical network-return or Windows retry claim.

## Non-interactive account access (#620 / #618 prerequisite)

Automatic native DAV scope/factory access, read-only account status, selected DAV
sync and background mailbox/outbox reads now explicitly request non-interactive
credentials. The existing manual account-enrollment path remains separate.
`SecretServiceStore.lookup_noninteractive` opens the existing service/session and
searches with `ALL | LOAD_SECRETS`, never `UNLOCK`, Prompt or the interactive
password-lookup helper. Only a unique already-unlocked item is accepted, with a
lock recheck after reading. A three-second cancellable deadline and cleaned timer
bound the normal SDK operation. Custom native backends must explicitly support
quiet lookup; absence does not silently fall back to an interactive method.

Locked, ambiguous or unavailable account access is held with a waiting/setup
status instead of reporting that a stored password was lost. Empty approval
scopes and unavailable books do not query credentials. Initial automatic scope
capture runs in the native worker, not GTK's main thread. Existing account
transactions, actual credential-bound opaque revisions and CAS/readback guards
remain unchanged; no secret enters renderer/status output.

Twenty-six controlled SDK/backend/native-entry cases and the affected 296-case
native/account/DAV/manifest run pass. The three actual encrypted frontend/native
wires still pass with controlled observations. No real keyring/OS dialog or
service installation was exercised, and no Windows credential-backend fix is
claimed. This removes a dialog-capable background lookup, but does not by itself
implement the still-pending durable native approval required for once-configured
automation across application restarts.

## Durable native approval core (#618)

The Linux `magnolie_contact_source_authority.py` helper now seals an explicit
typed native source decision in separate private files. It binds the known full
book content and native book/account-slot identity, rotates its dedicated key on
approval/revocation, refuses partial/insecure state and re-observes actual quiet
credentials on use. Passwords and password-derived verifiers are never stored;
normal credential renewal retains human intent but invalidates an old in-flight
witness. Book/account callbacks run outside the file lock. Operation-local
witnesses also reject a newer save, even when its content is unchanged.

Eighty controlled core cases and 191 combined core/account/factory/manifest cases
pass, including simulated fresh process revisions, lock/resume, record replay
after key rotation and pre/post-replacement failures. The helper is listed in all
four Linux manifests; no package was built or installed. Its key is a local
private-file boundary, not protection against a hostile same-user process or a
rollback of the entire private key/state directory. It must not be imported with
document settings or archives.

## Signed save advancement and primary recovery (#618)

The core now records a separately signed native before-save intent, advances the
known book hash only after a confirmed native save, and recovers only its known
old/new outcome. An already advanced record cannot be recovered backwards. These
operations retain the same approved sources/account identity and do not consult
credentials. A pending or corrupt intent cannot release usable permission.

The actual Linux serial writer has hooks for a native approval store: prepare
before saved-witness invalidation, confirm after the actual write and all repair
checks. Sidecar failures hold source authority without making an ordinary book
save fail. Existing committed/repair-pending semantics remain unchanged.
An authenticated primary-file observer reads/fsyncs/rechecks the actual primary
and authenticates encrypted content with the cached DEK. It never constructs a
saved witness from loaded JSON or grants source permission. Known primary
recovery can precede the first real post-restart SaveACK.

Fifty-four additional controlled save/primary/actual encrypted writer cases and
352 combined cases pass, including the existing three frontend/native wires and
12 actual historical-writer cases. Writer-store injection and restart outcomes
are synthetic; no installed application or live provider was exercised.

The initial 352-case checkpoint used injected writer stores. Application
integration was completed subsequently on Linux as described below; this
checkpoint alone was not a user-visible persistent feature. No corresponding
Windows persistence is claimed.

The native DAV scope can now restore only a current typed stored approval for its
exact actual saved book and fresh account revision. Restored source guards retain
the durable witness check; a new save, signed pending write, durable revocation or
credential outage invalidates old in-flight scope grants. Volatile pause/revoke
does not erase stored intent, and a fresh native witness can restore it without a
new decision callback. Seventeen controlled scope cases and 135 affected cases
pass, including actual bound DAV factory/CAS/readback with synthetic transport and
revocation before mutation. Application integration follows below.

## Linux once-configured application integration (#618)

The actual window now constructs the native private store without creating files
or accessing credentials by default. Only the genuine native catalog/dialog
decision is persisted, on a worker. Cancel preserves existing intent; an explicit
empty selection or Settings revoke rotates the native key. Losing the account
context after a nonempty selection is never mistaken for an explicit empty
selection. Volatile pause/lock/result uncertainty remains separate from durable
revocation. Failed durable revocation is reported as failure and holds the current
process; it is not advertised as a successfully persisted revoke.

The writer advances signed intent across ordinary saves and the first actual
post-restart save, including frontend normalization. Restoration runs outside the
writer data lock with fresh quiet credentials and a current typed saved witness.
A separate native positive notice carries the actual SaveACK ID/raw hash. The
frontend requires that same accepted committed/unrepaired SaveACK, exact current
book and local generation before scheduling. Discovery counts and imported flags
cannot substitute. Pending/newer edits, reload, lock and revoke reject stale
notices; result-save restoration does not create an automatic retry loop.

The native monitor retains recognized signed human intent while quiet account
access is unavailable and restores usable permission after access returns, with
no new dialog. Setup that was already persisted can report waiting without
erasing the decision. Genuine book/account identity changes, corrupt/unknown
state and rights/conflicts still hold; original-source update-only, UID/href/ETag,
CAS/readback, protection, WLAN-first and Notes priority are unchanged.

Evidence: 18 new actual bridge/encrypted-writer/native lifecycle cases, 17 new
full-frontend cases, three additional final-context scope guards, and a new
restarted full frontend/native/DAV/encrypted protection/result-save wire. The
restarted wire uses a new native book owner, fresh process-style credential
revision and a new frontend process: one original PUT, no second setup request,
two actual encrypted saves, exact protection, original UID and baseline readback.
The three earlier immediate/WLAN-return/uncertain-PUT wires remain passing.
The broad affected run passed 386 cases; subsequent final-context changes passed
155 affected cases, and the final application race/failure pass has 18 cases.
Six actual isolated GTK modal cases verify the durable wording/default-OFF and
explicit selection. Linux original frontend14/WLAN9 and unchanged Windows
frontend14 plus desktop/MCP/custom-save regressions pass. These matrices overlap.

Credentials, provider transports, WLAN and decision observations remain
synthetic, apart from the explicitly isolated native GTK dialog. No installed
application, live provider, hardware, VM, package build, installation or public
release acceptance is claimed. Windows durable consent/WLAN return and its
interactive modal acceptance continue in #621. Broader provider authority and
complete Notes names/scalar/postal return beyond Resource19 continue in #622.
Resource19 remains phone/email-only. #618 was closed as a documented partial
completion with these explicit linked remainders, not an all-platform completion.

## Windows native account prerequisite (#621, not persistent approval)

`NextcloudMailboxSettingsStore.ReadContactSourceAccount` now authenticates the
actual current protected credential before returning a nonsecret native account/
credential-slot identity and fresh operation revision. `ReadSnapshot` alone is
still metadata, not proof that credential protection is available. Re-reading
after unprotect rejects concurrent account changes; credential buffers are zeroed
on both success and failure. Password renewal keeps stable human-account identity
but changes the operation revision. No password, password verifier, Authorization
header or process-local revision is included in the durable identity.

Sixteen controlled native-account cases pass through the existing actual-source
Core group, including absent/inactive/corrupt/unavailable credentials, slot/account
changes, renewal, concurrent mutation and buffer cleanup. They also pass on the
actual Windows runner. One additional actual Windows DPAPI case protects, reads,
renews, corrupts and removes only a synthetic credential in its own temporary
directory: mere file presence cannot survive authenticated DPAPI corruption as
usable access. Core and actual Windows product BASE source builds pass without
warnings. The seventeen Windows cases overlap the sixteen host cases; no real
account, provider, OS dialog or installed app was exercised. Subsequent sealed
store, saved-content and scope connections are described below.

The dedicated `ContactSourcePrivateFiles` boundary is also prepared: private
current-user-owned Windows directory/files, nonblocking exclusive native lock,
fixed leaf names, bounded strict UTF-8 and existing atomic writes. It rejects
reparse roots/ancestors, shared-access state, directory impostors and hardlinked
key/state/lock files. No account/book callbacks run in this boundary, and default
reads create nothing, including an empty existing root. Unix execution requires
an explicit controlled-test switch; there is no Unix production fallback.

Seventeen controlled-host file cases and eighteen actual Windows file cases pass
(overlapping matrices), including native ACL/junction/hardlink counterexamples.
The first Windows run exposed a newly created lock whose default owner was not
the required current user. The implementation now sets the owner only on its own
new lock/replacement files; it does not relax owner checks or repair untrusted
pre-existing files. Core and actual Windows BASE product builds remain clean.
These private-file primitives alone do not create approval authority. The
subsequent sealed core is described below; application integration remains #621.

## Windows sealed native approval core (#621, not application integration)

`ContactSourceApprovalStore` now persists a strict, MAC-sealed native source
decision with its own independently DPAPI-protected random signing key and
generation. Explicit approval/revocation rotates that key; old signed records
cannot be replayed against the current key. A pending marker precedes publication,
unknown/corrupt state holds, and no old backup is used as permission. The private
state contains only selected source identity, native book binding/known complete
content hash and nonsecret account-slot identity tag: no password verifier,
process-local account revision, book owner or document admission flags.

Approval requires the actual saved-book witness, fresh actual account access and
a private concrete decision witness minted only by the native approval scope.
That witness binds exact Source/Collection/OriginalString/account revision and
scope generation. Cloning a record cannot retarget its fields, substitute a fake
token or bypass revocation with a replacement callback; legitimate native
cancellation/WLAN wrappers remain possible. Total state size is checked before
any private file changes, preserving existing intent on oversized selections.
Native book/account callbacks run outside persistent file locks. Load/use requires
fresh actual native book and account observations plus a final sealed-state/key
recheck; temporary credential failure does not erase existing human intent.

Fifty-four controlled-host core cases and fifty-five actual Windows core cases
pass (overlapping), including new native-owner restoration, changed book/account,
renewal, revocation/replay, callback lock order, concurrent newer approval,
unconfirmed writes, malformed signed JSON, pending save-intent holds and minted
decision field binding. The additional Windows case uses actual DPAPI for both
synthetic account and dedicated consent key; account ciphertext cannot substitute
for the consent-key domain. The existing eighteen native private-file and
seventeen native account cases continue passing, and Core/actual BASE product
builds are clean. No live provider, real account, modal UI or installed app proof
is claimed.

The later save/primary/scope/writer and application checkpoints below extend this
core. Native setup, durable revocation, frontend restoration and quiet WLAN/account
return are now connected in source; interactive product acceptance remains #625
and exact Windows original-book protection remains #619. No installed persistent
automatic feature or released package is claimed here. Whole private-key
directory rollback or a hostile same-user/admin process is not defended here.

A controlled native-only Linux record-copy retarget was separately confirmed and
tracked in #623; no external Bridge/MCP/document route was established. The current
Linux controller forwards native scope captures unchanged. The Windows private
decision witness above is the concrete reference for that later Linux hardening,
not a claimed Linux fix. #621 remains active; #623 precedes provider expansion #622.

### Windows signed save-chain helper (#621)

`ContactSourceApprovalSave` adds a separate authenticated before-save intent and
confirmed saved-content advancement without accessing account credentials. It
preserves the existing human selection/key/generation. Pending intent grants no
permission; confirmation requires a new actual saved-book witness from the same
native owner and a later sequence, with matching signed old/new content and
operation token. Recovery accepts only known old/new saved outcomes, never an
unrelated edit or rollback of an already advanced record. The signed intent stays
until the updated sealed record has been read back. Default-OFF creates no files
and observes neither account nor book; all book callbacks stay outside file locks.

Thirty additional controlled cases pass on both host and actual Windows,
including token reuse, changed context/revocation, unavailable credentials,
concurrent intent, failed prepare/advance, known-outcome recovery and rollback
rejection. Existing core/file/account cases still pass; Core and actual BASE
product builds are clean. These are overlapping native helper matrices, not an
application save/restart acceptance by themselves; subsequent connections follow.

### Windows authenticated primary observation (#621)

`ContactSourcePrimaryBook` now provides a private-constructor observation from
the actual bounded native primary path, never from supplied document JSON.
Encrypted files must authenticate with the already unlocked native session; no
prompt/unlock fallback. Active encrypted sessions reject substituted plaintext.
Reparse paths, missing files, changed readiness/session and changed disk content
hold. This observation is deliberately not a `NativeActorBookSnapshot` and cannot
grant permission. It enables known old/new signed-intent recovery and preparation
for the first post-restart save while no actual saved witness exists. Only that
later separately confirmed native save can restore usable authority.

Nineteen new primary-path cases pass on host and actual Windows, including actual
synthetic encrypted-file reads, wrong keys/tampering, locked/missing/substituted
files, changed observations, known/unknown outcomes, plaintext compatibility and
callback lock order. The save helper now also requires a privately minted
operation witness binding its exact previous saved/primary input, so record
copies cannot substitute a primary observation to bypass the later-save rule;
thirty-two save-chain cases pass on both systems. Existing core/file/account
cases pass; Core and actual BASE product builds are clean. Matrices overlap.
Subsequent scope/writer connections follow. No installed/live-provider or
publication acceptance is implied.

### Windows typed durable scope restoration (#621)

`ContactSourceApprovalScope.RestoreAsync` now accepts only a current typed native
stored approval. It checks the actual saved-book/account revision, concurrent
scope revocation and a final native application-context guard before assignment.
Restored decisions retain the durable lease: each actual decision guard rechecks
the current sealed store, actual book and credential access outside the scope
gate. Replacing a callback cannot detach that dependency from the private minted
decision witness. Cancel preserves it; a genuine new native selection replaces
it. Persistent human intent remains distinct from a volatile scope pause.

Twenty additional scope restoration cases pass on host and actual Windows,
including new native owners/saves, fresh versus stale credential renewal,
concurrent/final-guard revocation, cancellation, book changes and subsequent
durable revocation/access loss. Existing core/save/primary/file/account cases
remain passing; Core and actual BASE product builds are clean. This is a native
API, not yet actual application setup, frontend or WLAN wiring.

### Windows actual writer connection (#621, remaining application work open)

The actual `BridgeDispatcher.SaveAsync` now prepares the signed intent before
invalidating the native saved witness and touching the primary file. After the
existing encrypted/recoverable writer and derived updates succeed, it confirms
the actual new native saved witness. The store is constructed lazily from native
paths/account callbacks; default-OFF reads create no private files and observe no
account credential or book. First-save preparation after restart uses the actual
authenticated primary path, never loaded JSON as a saved witness.

Private-consent failure does not prevent ordinary user-data saves. It holds
automatic delivery instead, preserving pending/unknown state where applicable.
The actual SaveACK marks committed/unrepaired success and recognized durable
intent separately; that marker is NOT usable permission. A native scope restore
and matching positive frontend notice are still required before automatic IO.
Primary-write failure does not acknowledge successful consent or result delivery.

Fourteen new actual-source writer cases pass on host and actual Windows: encrypted
ordinary/same-content/restarted saves, credential loss without blocking autosave,
corrupt/failed sidecar, primary failure, changed binding, known old/new recovery,
unknown primary outcome and genuine one-use result-save confirmation/replay
rejection. The existing native writer body is compiled directly from the current
product source into the bounded test host; only GUI/derived notifications are
controlled. Four affected actual historical/ordinary SaveAsync regression groups
also pass on host. Existing native helper matrices remain passing. Core and actual
BASE product builds are clean; no package was installed or published.

The subsequent application integration connects setup, scope/frontend restore
and quiet WLAN/account return. This writer checkpoint alone was not that feature.

### Durable-capable native session API (#621)

`ContactSourceNativeSession` can now receive the native durable store explicitly.
Only a changed genuine native decision is persisted; Cancel preserves intent and
an explicit empty choice revokes it. The exact captured source IDs must match the
user selection, so lost runtime context cannot masquerade as an empty decision.
Durable revoke is separate from volatile pause. Typed restore requires the same
owned store and a current native application guard. Decision-generation checks
before/after the native dialog and during publication reject stale setup workers.

Fourteen controlled native session cases pass on both host and actual Windows.
They connect actual native catalog/decision, durable store, typed restoration,
original CAS/readback and actual encrypted writer/result SaveACK, including new
native owners after restart and clean-result no-IO repetition. Provider transport
and decision/protection callbacks remain synthetic; these are not interactive
modal or live-provider proofs. Existing helper/writer matrices pass and Core/BASE
product builds are clean. The real Bridge now opts into this API together with
the complete correlation/lifecycle connection below, not piecemeal with stale
session guards.

### Windows once-configured application connection (#621)

The actual native Bridge now connects its genuine setup dialog to the durable
session/store and the `ContactSourceAutomation` lifecycle coordinator. Cancel,
explicit empty selection, durable revoke and volatile pause remain distinct. A
failed durable revoke reports failure and blocks this process; Cancel cannot
quietly unblock it. The native dialog explains restart persistence, waiting and
revocation. No imported document settings or discovery counts create consent.

Only the actual successful writer records a native ACK correlation. After its
ACK and release of the writer mutation gate, current signed intent restores a
typed native scope and emits a separate positive ID/raw-hash-correlated notice.
The frontend requires that same accepted committed/unrepaired ACK, exact current
text/hash/generation and no newer pending save/dirty book/lock before scheduling.
Markers alone never grant IO. Result-save restoration does not repeat a clean
provider run. Default-OFF creates no consent files, observes no credentials and
starts no monitor. Consent errors preserve ordinary saves but clear usable grants.

The native host starts its bounded fifteen-second monitor only for recognized
signed intent. It reuses the existing tracked background-work lifecycle, permits
one probe at a time and stops/disposes on pause/shutdown. Probes perform no provider
HTTP requests: they validate current native book/credential access and the existing
Windows WLAN profile observation. Known account/WLAN waits resume without another
dialog; unknown mutation outcomes and source conflicts remain held rather than
blindly retried. No new driver, service, download or permission bypass is added.

Eighteen additional coordinator cases pass on host and actual Windows, including
restart, account loss/return, pause/revoke, corrupt/revoked state, failed durable
revoke followed by Cancel, disposal and stale restore. Five actual frontend/native/
encrypted-writer wires pass on host: existing session, durable setup, fresh native
owner/frontend restart with no second setup, account removal/return with an
intervening zero-count status, and WLAN return. Each updates exactly two bound
original books once, with one native protection callback and confirmed result
SaveACK. The restarted wire needs two actual save commands and no setup command;
the two waiting wires issue a second update command only after proven pre-IO wait.
Transport/decision/protection/WLAN observations remain synthetic. These are not
actual modal, physical WLAN or installed-product acceptance proofs.

Eighteen full-frontend cases pass (seventeen existing durable cases plus the
status/wait-return race), as do Windows original frontend14/WLAN9, affected
desktop/MCP/custom-save regressions and four historical/ordinary actual SaveAsync
groups. Existing native session14/writer14/scope20/primary19/save32/core54-or-55 and
native private-file/account matrices pass; these matrices overlap. Core/actual
BASE product builds are clean and output web bytes match the tested source.

The direct DAV factory now independently requires the scope-minted exact native
decision witness before and after every supplied approval callback. A controlled
native-only same-origin record-copy factory admission was reproduced before this
check; five new factory cases reject retargeting, missing/fake witnesses and
revoked callback replacement before discovery. No external Bridge/MCP/document
exploit was established. Linux transfer hardening remains #623.

A separate zero-count status race was confirmed on unchanged Linux in #624:
metadata could invalidate the durable ACK correlation before known account-wait
and return replies. Windows now clears usable counts without treating that
metadata as human revocation when an authenticated durable ACK exists; explicit
revoke/lock/reload/new-save fences remain. This is not yet a Linux fix.

Interactive Windows acceptance is blocked by the existing noninteractive runner
and continues in #625; #619 still owns exact original-book snapshot coverage.
No installed app, live provider, device/VM, package installation or publication
acceptance is claimed. After #621 source integration, #623 and #624 precede the
broader Notes/provider return #622.

## Linux exact native decision binding (#623)

Linux `NativeDavSourceApproval` now carries an immutable private scope-minted
decision witness binding exact source/href strings, current account revision and
scope generation. A dataclass copy may wrap a genuine native lifetime/cancellation
guard, but cannot retarget fields, remove/fake the witness or bypass revocation by
replacing that callback. Persistent approval and the direct native DAV factory
both require the witness independently before and after approval callbacks.
Durable scope restoration mints fresh bound witnesses only after its existing
current signed-store checks; a fake self-attesting store cannot supply a typed
restored lease. Account inputs must be the actual native settings-store type.

Twenty-nine new controlled cases pass, including copied same-origin targets,
normalization tricks, missing/fake tokens, account/book changes, callback bypass,
legitimate wrappers, restored decisions, immutable witnesses and forged store/
account objects. The affected 401-case native application matrix passes, including
the four existing frontend/native/DAV/encrypted-writer wires; six actual isolated
GTK modal cases pass. The matrices overlap. The original native-only copy/retarget
repro is now held without changing saved human intent or issuing provider IO.
No external Bridge/MCP/document exploit was established, and this is not a sandbox
against hostile Python code already executing in the same native process.

Native original binding, UID/href/ETag/CAS/readback, update-only, protection,
noninteractive credentials, save/restart semantics and Notes priority remain.
No installed-app, live-provider, device/VM, installation or release acceptance is
claimed. The separate Linux status/wait-return issue #624 is still open here;
Windows native acceptance #625/#619 and broader return #622 remain separate.
