# Full original-contact return: remaining lifecycle (#628, partial source work #622)

This is a source-boundary assessment, not an implemented capability or a source
grant. Issue #622 records the checked native partial source work; its actual
functional remainder continues in #628, not as an enabled automatic feature.
The completed DAV lifecycle work in #621/#623/#624 does not complete this
scope. No installed-app, physical device or live-provider acceptance is claimed.

## Android contact-journal sync metadata (#626)

New native captures use `Data.SYNC1` through `Data.SYNC4` (`data_sync1` through
`data_sync4`) for capture and restore, retaining four nullable slots. They record
`syncSpaltenVersion=1`. Older snapshots remain decodable with version 0, but their
native destructive restore is held even after conflict confirmation: omitted or
misidentified metadata cannot be recovered by inventing null values. Existing
encrypted snapshots are not rewritten. This is not a Linux/Windows provider fix.
Host synthetic-provider and strict SQLite roundtrips do not establish physical
device acceptance or previously observed user-data corruption.

## Notes: two different existing paths

The FS1 receiver prerequisite in #627 pins the peer and local public identity
from handshake to payload acceptance on Notes, Linux and Windows. An open
ephemeral channel is not relabelled as a newly pinned identity under the same
branch ID. Changed pins are rejected before dispatch, consuming/clearing the
session. Unchanged pins and cosmetic name changes still work. This channel check
does not itself grant source rights or supply a provider/baseline SaveACK.

For the pending Notes return lifecycle, the actual FS1 dispatch additionally
mints a private process-local origin proof after authenticated decryption. It
binds handshake peer/local pins, session ID, transport ID, canonical body hash
and session expiry. `Baumwerk` checks it under `Ablage.SCHREIBSPERRE` before
the real receive transaction and again inside its mutation. Reconstructed
proofs or changed payload/transport identities cannot pass that gate.
The handshake also captures server-stop and native transport/restore lifetime;
an already decrypted message waiting for native admission cannot acquire a new
lifetime after cancellation or restore, even with unchanged keys. This remains
a Notes-specific native admission seam, not an implemented Linux/Windows full
return counterpart or a new wire capability. Generic transport ACKs still do
not prove provider write or desktop baseline save. Unsupported appointments
retain their existing staged-but-unacknowledged behavior.

- `magnolie-notes/.../telefon/ContactValueWrite.kt` resource **19** accepts only
  `telefone` and `emailEintraege`. Preparation and apply receipts carry the exact
  selected field set and account tuple. `ContactValueWriteAndroid.kt` binds a
  short-lived ticket to its authenticated channel, original lookup/raw contact,
  provider version and native account. It is not a full-content resource.
- `magnolie-notes/.../baum/KontaktSync.kt` and `KONTAKT-PROTOKOLL.md` already carry
  the full v2 names/raw N/FN, scalar and postal model over authenticated transport.
  `Baumwerk.kontaktUebernehmen` currently stages that content in `kontaktEingang`.
  It does **not** automatically update the original Android contact.
- `Baumwerk.kontaktUebernahmeBestaetigen` performs explicit reviewed adoption.
  Its planning can select merge, replacement or creation. Its prior protection
  and `AndroidKontakte.uebernehmen` raw-version assertions are reusable building
  blocks, not authorization to call that whole manual flow automatically.
- `KontaktSpur` binds partner/share ID to lookup/raw ID and content hashes, but
  does not itself seal native account/source identity or grant automatic writes.
  `Partner.kontaktSync`, trust, authenticated capabilities and native Android
  READ/WRITE_CONTACTS permission are also not independently a per-source approval.

The full return must therefore have a distinct explicit admission. Do not widen
resource19's field set, relabel a share/cache update as delivery, infer permission
from tree settings, or allow the manual flow's create/replace choices to leak into
update-only automation. Whether reusing the full tree envelope or introducing a
separately negotiated phone resource, both receiving native source authority and
the desktop result-save correlation must be connected and tested before enabling
or advertising it. No new resource/version is allocated by this assessment.

## Existing provider boundaries

### Shared target-fingerprint interoperability (#629)

The new desktop adapters use the existing `KontaktSync.hash` projection, not a
sorted document/renderer hash. Shared synthetic vectors check legacy/V2/group
selection, fixed serializer field order, raw Unicode/control escapes, first-row
normalization, BMP decimal digits, NFC groups and UTF-16 ordering. String ROOT
casing also matters: .NET invariant simple lowercasing and Python Unicode
lowercasing are not interchangeable with the JVM ROOT word/cased context used
by the current Notes host oracle. Dotted I, final sigma, other-cased context,
number/punctuation boundaries and ignored format characters have explicit tests.
The desktop adapters implement that context locally without changing the
existing Notes hash or downgrading dependencies.

Sixteen shared vectors pass against the unchanged actual Notes hash source,
Linux and Windows; Linux also rejects eight malformed projections and Windows
checks its strict projection errors. Windows is checked both on the managed
host and with the existing bounded noninteractive Windows runner, alongside the
existing contact-contract group. Native Android runtime/device casing remains
an acceptance point in #628 under the existing device pauses: a JVM oracle is
not a physical Android/libcore acceptance claim. Other editions/renderers are
not presumed compatible merely because they calculate a SHA-256 value.

The external shared vector file is declared as a Gradle test input. A prior
UP-TO-DATE invocation after only editing that file was explicitly discarded as
new-case evidence; actual native re-execution exposed the Python cased-context
difference, and the corrected adapters were checked against the native result.
An initial Windows native probe lacked its fixture resources; only the existing
runner's opt-in resource bundle was corrected, then the actual group passed.
These helpers alone grant no source rights, send no packets and issue no SaveACK.

### Notes controller integration, production still disabled (#628)

Fresh apply authority owns the complete cloned target model, not only its
semantic `KontaktSync.hash` fingerprint (#631). Both planned and preprotected
entry points require target data; there is no hash-only fresh apply overload.
Structural retargeting with an identical legacy fingerprint is rejected before
provider access, consumes the one-use token and leaves its physical hold intact.
No-op detection uses the actual native plan, so a genuine Raw-FN-only change can
proceed even when its semantic fingerprint equals the before-image fingerprint.
Existing contact fingerprints and canonical request-body hashing are unchanged.

New private holds and verified records retain `target_exact_sha256`, computed
from the complete owned model. Receipt creation binds that evidence, and outgoing
results require it to match the actual current native model as well as the
existing revision/mapping/source checks. Legacy missing/null evidence remains
readable and held but cannot authorize a positive result; it is never rebuilt
from current provider data. Malformed evidence is rejected. The affected host
API28/API35 matrix passes 94 attempt and 38 actual FS1/controller cases.

Transfer assessment: Linux `NativeContactSourceResultCommit` owns and validates
the entire serialized book proposal; Windows `ContactSourceSavedCommit` compares
the actual proposal using `JsonNode.DeepEquals` and binds the saved payload.
Neither substitutes the semantic Notes contact hash for proposal authority.
This source assessment establishes no identical desktop fault or untested
cross-platform fix, and does not complete the pending/save-ACK lifecycle in #628.

`KontaktOriginalEmpfang` now joins actual FS1-origin admission, restored native
consent, private canonical/raw observation, sender-quoted basis, the shared
native plan, lazy actual original protection, atomic provider write/readback and
the durable verified outgoing result. `Baumwerk` routes this through its actual
receive transaction and persistent result outbox. The production controller is
absent by default and can currently only be injected by isolated native tests;
legacy/unproven-origin calls cannot enter it. No capability is advertised and
no installed automatic feature is enabled.

The dedicated draft request uses `kontakt_original_anfrage`, version 1, exact
fields `request_id`, `share_id`, `before_basis`, `target_sha256`, `ziel`, plus
`art`/`fassung`. `ziel` contains exactly the modeled names/raw N/FN, scalar and
postal fields. Phone/email/photo/group edits are not accepted through it. The
receiver verifies the desired full target hash while retaining those excluded
native fields unchanged. Existing strict `kontakt_sync`/capability DTOs and
resource19 remain unchanged. The draft result uses `kontakt_original_ergebnis`
and the exact eight native result-correlation fields documented below. Desktop
implementation and explicit negotiation remain outstanding; these draft kinds
are not sent to existing peers as an assumed supported capability.

An exact repeated request can load and enqueue the same verified receipt after
a lost response or fresh native owner, without another setup or provider batch.
A different request/hash/target cannot bypass the physical hold. Native
connection policy and origin lifetime are rechecked around protection and apply.
Missing consent rejects before provider observation or default private-state
creation. Invalid scope/budget rejects before original protection/reservation.
The generic FS1 receipt still does not settle the attempt or install its next map.

Host evidence covers 28 controller API28/API35 cases, including actual FS1 crypto,
real isolated `Baumwerk`/`Ablage` transaction/outbox, native synthetic provider,
encrypted protection and source restoration. An interruption after the actual
receive commit intent is recovered on restart and the exact result can be
re-emitted with one provider batch. The affected 64 origin/transport regression
cases also pass; the eight subsequently added controller cases were run alone,
retaining the earlier unchanged passing cases. No physical device/provider,
AndroidKeyStore, installed notebook, package or publication acceptance is claimed.

### Linux authenticated result-origin handoff (#628)

The actual Linux FS1 receiver can now pass a private, immutable origin proof to
an explicitly registered native full-result callback after authenticated open.
It binds handshake peer/local pins, body hash, transport ID, expiry, native tree
epoch and receiver-stop generation. A later saved-book action must recheck the
proof under its real book mutation gate, not reinterpret the body under current
keys. Copied JSON is not an origin or a saved-result acknowledgement.

That callback is limited to the dedicated draft full-result kind; ordinary notes
keep their existing inbox path. Without the native callback, a draft full result
is rejected rather than forwarded to renderer/inbox as authority. Callbacks may
schedule later book work but must not wait for the book data lock while holding
the receive lock. Revalidation after callback rejects changed body/pins/lifetime
before replay-state persistence and positive transport receipt. Session keys are
cleared on these rejected paths as well.

The changed-input Linux matrix passes 38 synthetic offline cases: 15 native
origin/callback cases plus 23 affected FS1 identity/pairing/receiver regressions.
This does not yet register a production result controller, save a result book,
mint a desktop SaveACK or establish Windows/native Android result integration.

### Linux pending/result to actual saved-book controller (#628)

`NativeNotesPendingResult` now joins a native-owned pending request and exact
saved-book/contact identity to actual authenticated FS1 result correlation and
`NativeContactSourceResultCommit`. The receive callback only stages the owned
result; later book work rechecks origin lifetime and native mapping guards under
the book mutation gate. It never waits for book work under the receive lock.
Request ID/body hash, share, before basis, target, native receipt/revision and
next basis must match; conflicts cannot replace an accepted result. Exact
duplicates retain the same one-use book invocation, not a second save.

The real encrypted/atomic Linux writer stores the already selected next basis
and result correlation on the same existing contact, retaining IDs/UIDs and all
other domains. Native revision is stored as decimal text to avoid JavaScript
precision loss. `confirmed_save()` requires that invocation's actual private
saved witness and rechecks current book generation, mapping and retained origin;
generic FS1 receipts and renderer booleans cannot substitute for it.

Twenty-two new synthetic controller cases cover the actual FS1 crypto/receiver
and real encrypted writer, including changed book/generation, revocation, stop,
repair/failure, duplicate and mismatched result fields. The first test invocation
had a fixture function named `setup` intercepted by pytest's legacy setup hook;
this was a test setup error, not product evidence. Renamed fixture execution
passed. The 53 affected origin/writer cases passed in that initial run and remain
valid; 11 subsequently strengthened new cases additionally assert that receive
does not invoke the native mapping/book guard.

This is still production-unregistered. The initial tests supply a synthetic
native mapping guard; the authenticated export/native-choice extension below
provides a bounded process-local issuer, not by itself durable setup. The separate
private choice/save-chain store below now supplies checked fresh-export restore.
Outstanding-result/ACK recovery, request sending/production ACK orchestration and the Windows
counterpart remain unfinished; the native Notes terminal phase is described below. A subsequent actual common frontend
init/normalize/save-message test confirms that `notesOriginalBasis` is already
retained by the existing contact object copy, including exact decimal Long text.
Imported permission-looking metadata triggers no native operation; no frontend
product change was needed for preservation. Strict protocol admission remains
native, and portable metadata is never a permission or SaveACK witness.
`confirmed_save()` exposes native correlation only, not a wire ACK or slot release.

### Authenticated native export and explicit local choice (#628)

The existing Notes native observed offer can now build a dedicated draft
`kontakt_original_export` frame containing exactly `art`, `fassung`, `share_id`,
`before_basis`, `setup_id`, `native_revision`, `content_sha256`, and the full `kontakt` model.
Content/revision/quote come from the same actual private grant/map observation;
source revocation and fabricated offers cannot build that frame. No production
sender or advertised capability is added by this method.

Linux's same authenticated-origin route accepts the export only for an explicitly
registered native callback; without it, exports and results both reject rather
than falling back to the renderer. Later `NativeNotesExportChoice` validates the
authenticated export and invokes a native choice callback over actual saved
contacts. It binds the chosen local ID/UID and native book owner, not imported
tags, names or a default contact. Native setup UI is not implemented; tests use
an explicit synthetic choice. Private fresh-owner restoration is described below.

The resulting pending request projects the selected saved contact's modeled
name/raw-N/FN/scalar/postal fields onto the authenticated full native before-model.
Native phone/email/photo/group content is retained, not reconstructed from the
desktop renderer. Native HOME/WORK/OTHER postal types map explicitly; changed
custom labels and unrepresented postal columns hold rather than silently map to
another kind. An unchanged custom label may retain its exact native row. This
bounded projection is not broader provider/custom-label support. Result revision
must advance beyond the actual exported native revision.

The extended Linux matrix passes 83 cases (30 pending/choice, 15 origin and 38
actual writer regressions), with a subsequently added export default-rejection
case passing alongside the existing result rejection. The common actual frontend
has three passive metadata roundtrip cases. Notes passes 66 mapping/export cases
on host API28/API35, including draft frame ownership and source revocation.
The full common frontend source was used unchanged; neither these host checks
nor synthetic counterpart frames are physical Android/libcore or installed
Windows acceptance. Native selection remains bounded by its original authenticated
session lifetime. Replacing it requires the private checked fresh-session restore
below, never reconstitution from the portable basis field.

The draft export now also carries the opaque UUID of the actual native setup
decision. It comes from the same checked source grant, not a renderer field or
portable permission. This is an explicitly unreleased draft-schema refinement,
not an advertised installed capability change. Linux rejects missing, malformed
or boolean setup IDs before invoking a native choice. Existing semantic contact
hashes and the exact request/result/ACK schemas are unchanged.

A fresh reserved ACK intent now additionally requires the genuine process-local
`NativeNotesExportChoice`, rather than merely an arbitrary native guard callback.
That proof binds peer/local pins, saved book owner, local ID/UID, quoted export,
native setup/revision and the full saved mutable target projection. A same-hash
but structurally changed target cannot be substituted. The authenticated setup
UUID is retained in the encrypted private ACK intent, not inferred from contact
metadata. Old intents missing it remain readable only as held history and cannot
be silently upgraded into fresh ACK authority. Native choice-owner cancellation
invalidates fresh requests and intents; it is not a portable restore API.

The changed Linux matrix passes 103 cases, followed by two new source-choice
retargeting cases. They include actual authenticated export/explicit selection
before the real encrypted writer and durable ACK intent, missing choice despite
a confirmed save, legacy missing-setup history, invalid setup values and native
choice revocation after durable intent. Notes' 66 affected host mapping/export
cases pass with the actual source decision UUID in the frame. These checks alone
do not authorize restart from portable IDs or history; the separate private store
below supplies the known-book chain. Native setup UI is still missing.

### Private Notes choice and actual native book-save restoration (#628)

`NativeNotesChoiceStore` now persists genuine authenticated choices under its own
nonportable consent key and AES-GCM domain, not DAV-account approval or the
independent ACK-outcome journal key. Only explicit native configuration from
actual `NativeNotesExportChoice` objects creates a consent key. Missing/default
reads, empty revocation and copied setup objects create none. The sealed record
binds native/desktop pins, share/setup UUID, selected existing local ID/UID, stable
native primary binding and exact known complete-book content fingerprint.
Duplicate source/local bindings are rejected rather than guessed. This bounded
store currently permits one Notes choice per local contact, not an unproved
multi-source metadata layout.

The mature ordinary-save/known-old-or-new-primary chain is factored into
`NativeContactBookSaveChain`. Existing DAV record/key/MAC formats and primary
witness imports remain compatible; source permission remains in independent
subclasses. A Notes store cannot masquerade as `NativeStoredContactApproval`.
Sharing save mechanics grants neither DAV account rights nor Notes mapping
authority. Native callbacks remain outside the private file lock.

The actual Linux encrypted/atomic writer records a Notes before-save intent and
advances it only after its real unrepaired saved observation. A new native owner
may recover a known old/new authenticated primary outcome, but that observation
is deliberately not a saved-writer witness. After the first actual ordinary save,
a fresh authenticated export with the same private pins/share/setup and unchanged
chosen ID/UID can restore the choice without invoking the user chooser again.
The encrypted-primary envelope hash and clear SaveACK payload hash are distinct
domains: their shared content fingerprint is compared, not those raw hashes.
Unknown primary contents, missing consent keys, changed pins/setup/binding and
unconfirmed transactions do not authorize restoration. No name/default-book or
portable-tag fallback exists.

Consent-sidecar failures hold automation, not the user's ordinary save. Known
post-advance or repair-pending outcomes can recover through the native chain;
unknown outcomes remain held. A failed setup publication quarantines its new
ephemeral choice. Revocation invalidates attached scopes but leaves independently
encrypted outcome history readable. Native startup registers only the default
no-files/no-keys reader and save-chain hook, not a chooser, receiver, sender or
advertised feature. The new required runtime helpers are declared in the existing
Debian/RPM/AppImage/Flatpak source manifests.

Evidence: 277 affected Linux cases passed after the shared-chain/writer change;
then 21 focused Notes cases passed after adding known old/new restart and uncertain
publication checks. The final startup/runtime source-fixture run passes 58 cases,
including the now 22 Notes cases. These matrices overlap. Existing DAV/private
primary/scope and actual writer cases retain their unchanged evidence. One early
repair fixture read the final reminder callback instead of `App.gespeichert`;
correcting that callback selection fixed the test, not a product save failure.
All keys, peers and encrypted primary files are synthetic and isolated. Runtime
source composition is not a package build, installation or native acceptance.

Already saved ACK recovery from a repeated authenticated result is now provided
by the separate historical context below. Native setup UI, actual default-off
receiver orchestration, request sending/production ACK orchestration and Windows counterpart
remain unfinished. No installed end-to-end automation or other-platform
restoration is claimed.

### Saved ACK recovery from a fresh repeated result (#628)

A restart with a native VERIFIED hold cannot wait for a new export: Notes may
correctly refuse to export until the old attempt settles. `reauthorize()` now
re-emits only an **existing sealed historical SaveACK** after receiving a fresh
actual FS1 result identical to the stored result. It does not create another
request, apply a target or fabricate a saved-writer witness from a primary read.

Positive recovery additionally requires the independent outcome journal key,
current private source consent and a recognized authenticated primary whose
complete content matches the native in-memory model and the private known-book
chain. The chosen local ID/UID must still exist. The original saved intent must
carry a private choice seal binding consent-key fingerprint/generation, native
primary-binding tag and selected source fingerprint. This prevents accepting a
different private book/decision merely because portable IDs match. Old intents
missing setup or that seal remain readable as held history, not automatically
upgraded from today's choice. A fresh ephemeral selection can still produce its
live ACK, but cannot stand in for this durable cross-restart proof.

The reconstructed native intent retains exactly the original ACK body and its
actual historical desktop saved-payload hash, including after later known local
saves. Primary observation does not call `record_saved`, advance a save sequence,
write the book or rewrite the journal. Body reads recheck private consent, both
key contexts, recognized primary content, selected identity and original native
origin lifetime. Changed result values/types, another authenticated peer, changed
UID, unknown primary/memory, revocation, key loss or a forged/copied context deny
recovery. Result equality uses exact canonical bytes, not Python's coercive
`True == 1` or `2.0 == 2` comparisons.

The affected Linux run passes 93 cases, followed by one new other-authenticated-
peer denial before primary inspection. Cases include actual encrypted book save,
sealed private consent/journal, fresh owner with **no saved-writer witness**, fresh
FS1 result, identical historical ACK, late revocation/unknown primary and explicit
negative legacy/source-seal cases. No native primary is laundered into a write
receipt, and book/journal ciphertext remains unchanged by recovery. Other
unchanged source/writer/packaging evidence is retained rather than rerun.

The read-only terminal-status reconciliation below now covers lost settlement
receipts. The dedicated draft negotiation and reserved ACK admission below are
checked but unregistered; controller orchestration, request sending, native setup
UI and the Windows counterpart remain unfinished and production-disabled.

### Read-only terminal status after a lost settlement receipt (#628)

An exact repeated original request may now return the private historical
`kontakt_original_abschlussstatus` instead of trying to reconstruct or reapply
its target against newer provider data. This unadvertised draft has exactly 12
fields: `art`, `fassung=1`, `phase`, the eight existing result correlation fields,
and `desktop_sha256`. `phase` is precisely `prepared` or `settled`, reflecting the
durable native archive, not a transport receipt. The original request hash,
UUID/share/before-basis/target and current genuine source/setup context must match.
The ordinary low-level old-UUID apply guard remains intact.

This query does not continue a prepared settlement, install mappings, mutate the
provider or release a physical slot. It remains historical truth after newer
provider edits or another request occupying the same physical slot. New native
setup or consent revocation cannot borrow old history. Actual Notes outbox kind
matches the result/status body. Linux routes status only to its explicit native
authenticated callback; absent that callback, no renderer/inbox fallback exists.

Desktop historical ACK recovery accepts only the exact canonical status echo
matching the existing independent sealed SaveACK and private choice/primary
context. Unknown phases, wrong desktop hash, extra fields and coerced numeric
types deny recovery. Prepared status can reauthorize that existing ACK but cannot
mark the outcome settled. A fresh settled status may atomically persist an
encrypted `native_terminal_sha256` marker with readback. This marker does not
write the primary book or create a saved witness. Its write makes the old proof
stale; a fresh checked reauthorization can idempotently confirm the same marker.
Marked history cannot emit another ACK body. Missing or uncertain writes remain
recoverable by a fresh authenticated status, never by inventing completion.

Evidence: 120 affected Linux cases passed, followed by 14 focused status cases
including five additional negative cases. Native API-28/API-35 run passed 230
cases and initially failed four new cases in fixture reconstruction of the old
request from an already changed binding. Keeping the actual original body fixed
the fixture; all four focused cases then passed. The product logic was unchanged
between those native runs. Native coverage includes unchanged map/journal bytes,
newer provider edits, new setup/revocation, changed request correlation, and old
history while a newer physical hold is active. Linux covers both phases, marker
write interruptions, stale proofs, exact encrypted readback/idempotence and fake
JSON denial. These overlapping runs are not additional physical/native-device
acceptance, packaging, installation or enabled production sending.

### Challenge-bound draft negotiation and reserved native ACK send (#628)

`NativeNotesProtocolNegotiation` owns a new random challenge for the exact paired
native/desktop pins. Its five-field request is `art=kontakt_original_aushandlung`,
`fassung=1`, `challenge` (canonical UUID), `antwort=false`, and
`profil=notes-original-return-draft1`. The corresponding response changes only
`antwort` to true. Only a fresh actual FS1 response with exact canonical body,
same challenge and pins can establish protocol support. Copied capabilities,
ordinary contact protocol versions, reflected requests, bool/numeric coercion,
unknown profiles, extra fields and another process's challenge do not qualify.
Expiry, native epoch changes or cancellation invalidate it. Protocol support
is neither consent, mapping authority, a saved witness nor a completion receipt.

The actual Notes authenticated receive transaction now answers this probe only
when the isolated native return controller has explicitly been injected, and the
peer is confirmed/trusted/contact-enabled with native connection policy open.
It never queries an original/provider or creates source consent to answer. The
ordinary production controller still rejects this draft; there is no startup
advertisement. Linux admits its response only to the explicit native authenticated
callback and has no default renderer fallback.

`baum_notes_saveack_senden` is a separate, unregistered native-only ACK lane.
It requires exact `NativeNotesSavedAckIntent` and negotiated-profile objects,
correlates their private historical peer/own pins, and reads current native state
and connection policy before network use. A connection initially held is quietly
left waiting. It rechecks consent, saved-intent history, profile origin, pins,
enabled/trusted/contact permission, FS1 protocol and native epoch around handshake,
envelope creation and receipt processing. It never degrades to legacy transport
or mailbox, and erases derived session keys even on rejection/failure. The real
FS1 receipt can report transport delivery only; it does not mark private history
settled. Lost connections or bad receipts retain the same durable intent.

The generic queue/send/direct-FS1 JSON paths still reject the identical ACK body.
Recovered historical intents can use this lane without inventing a new saved
witness. Marked terminal history, mismatched intent/profile pins and copied
objects are rejected before network access. Revocation/cancellation/epoch or
connection changes during IO are rechecked rather than hidden as delivery.

Evidence: all 80 actual Notes receive-controller host cases pass under API28/35,
including six new probe cases (echo without source IO/consent, malformed/reflected
probe rejection, default-off and held connection). Linux's affected run passes
100 cases: 31 actual authenticated-origin/negotiation cases, 18 reserved send
cases, and 51 existing pending/save/route cases. The sender tests use actual FS1
handshake/encryption/receipts with an isolated synthetic responder, not a physical
Notes counterpart or cross-language installed acceptance. Both original and
fresh-owner recovered ACKs are exercised; journal/book bytes remain unchanged.
An initial send-test run incorrectly expected PermissionError from the existing
generic RuntimeError blocker; only that fixture assertion changed.

Reserved request admission/retry is now checked below. Still missing: native
orchestration of initial probe delivery and its retained answer, genuine common
setup UI, actual receiving workflow integration and Windows counterpart. The protocol does not make those
missing pieces available, and no production registration, install or release is
included. Source consent remains independently mandatory at the native receiver.

### Initial typed protocol-probe delivery (#628)

`baum_notes_protokollprobe_senden` can deliver the native challenge before any
received profile exists. Only the exact owning `NativeNotesProtocolNegotiation`
object enters this reserved lane; current paired pins, trust/contact permission,
epoch, FS1 and native connection policy remain mandatory. Cancellation or native
context changes during the handshake deny payload transmission. Offline/held
connections retain the same challenge. Successful transport delivery is not a
negotiated profile: only the subsequent exact authenticated echo can establish
support, and no source consent is created in either step.

Generic send/queue/direct-FS1 helpers now reject probe JSON as well. A test exposed
that the generic send guard was also called by the actual FS1 receiver, blocking
the genuine echo. Probe/query receive admission is therefore separated only
after authenticated open and restricted to the existing explicit native callback;
absent that callback it still rejects without renderer fallback. Request/ACK
receive/send blockers and legacy transport remain unchanged. This does not enable
a generic receive bypass or claim a Windows receiver correction.

Evidence: 183 affected Linux cases pass (11 initial probe, 31 reserved request/
ACK/query, 33 authenticated origin/negotiation, 51 pending/save, 57 consent/history).
Probe tests include explicit transport-success-without-negotiation, later real
FS1 echo, copied/cancelled objects, current policy/pins, bad receipt and offline
waiting. An additional actual-origin query test checks the separated native
receive path. No native Notes sources changed here; unchanged host proofs are
retained. Native scheduling/retained-offer registry, setup UI and Windows workflow
remain unconnected and production-disabled.

### Private-choice-owned request sending (#628)

`baum_notes_anfrage_senden` shares the strict native FS1 transport gate with the
reserved ACK lane, but admits only an exact `NativeNotesPendingResult` owned by
a genuine authenticated `NativeNotesExportChoice` with a current private consent
seal. A manually constructed pending object's arbitrary mapping callback alone
is insufficient. The original recognized saved-book/source context and the
negotiated peer/own pins must remain current. The complete owned original request
is used unchanged: retry never substitutes a new UUID, basis or target.

Once that pending owner has staged a result, it cannot submit another provider
request through this lane. Changed books, missing private seals, lost choices,
revocation, copied request JSON and mismatched profile pins deny before IO.
Initially held native connection policy quietly leaves work waiting. The generic
queue/send/direct-FS1 guards now reserve request JSON as well as ACK JSON, including
messages disguised under a different outer kind. Neither transport delivery nor
retry creates a book save, outcome journal or saved ACK.

The affected Linux run passes 136 cases: 28 reserved ACK/request send cases,
51 pending/save/route cases and 57 private consent/terminal recovery cases.
The ten new request cases use actual private selection and real FS1 crypto with
a synthetic responder. Disconnection followed by repeated delivery preserves the
identical original request. No native Notes source changed for this slice, so its
unchanged host evidence is retained. This still does not register a production
scheduler or prove installed/native cross-language acceptance.

Historical lost-receipt reconciliation must not force an already saved pending
owner back through request submission. The explicitly read-only historical query
below supplies separate admission; native orchestration, initial negotiation/
send/receive setup lifecycle and Windows counterpart remain to be connected.

### Explicit target-free historical inquiry (#628)

`kontakt_original_statusanfrage` has exactly seven fields: `art`, `fassung=1`,
`request_id`, `request_sha256`, `share_id`, `before_basis`, `target_sha256`.
There is no `ziel`. The actual authenticated Notes controller validates the
current native source/setup and complete historical correlation, then reads an
existing prepared/settled archive or an existing VERIFIED attempt result. The
query has no prepare/apply/reconstruction path. An unknown/missing/unverified
attempt is held, never created or resumed merely because it was queried. Extra
target fields are rejected. Production remains disabled, including this kind.

`NativeNotesAckIntents.readonly_query` may create a distinct native-only
`NativeNotesHistoryQuery` from an existing genuine encrypted saved-ACK record and
its current independent private consent/recognized primary context. It does not
require a fresh result just to ask for one, and it does not issue an ACK. Source
choice seals, keys, selected identity and known complete primary/native-model
contents remain mandatory; no saved-writer witness is fabricated on restart.
The result/status subsequently received still needs the existing fresh native
origin checks before reauthorizing an ACK or confirming settlement.

The reserved query sender requires this exact type plus the fresh negotiated
profile and current native transport policy. Query JSON is blocked from generic
queue/send/direct-FS1 paths and has no default renderer fallback. It cannot be
passed as a saved-ACK intent. Source revocation blocks retained queries before
IO, and queries do not write the primary or independent journal.

Evidence: all 84 affected actual Notes controller cases pass on API28/35; six
focused cases with additional explicit-query setup/revocation/new-hold assertions
also pass (overlapping, not 90 distinct cases). Existing archives remain byte-
identical after inquiry, including later provider changes/new physical holds;
missing attempts cause no provider batch or reservation. Linux passes 171
affected cases: 31 reserved sends, 57 private consent/history, 51 pending/save,
32 authenticated origin/protocol/default-fallback cases. Historical query sending
works with a fresh owner and no current saved witness, using real FS1 crypto and
a synthetic responder. Missing private context/keys, wrong seals/identities and
unknown primary remain negative. No physical device or installed counterpart
acceptance, production registration, package build or installation is claimed.

### Bounded native owner registry and actual receive/writer hooks (#628)

`NativeNotesController` now joins the individually checked native pieces without
performing book/consent/journal IO inside FS1 receive. The callback retains only
an immutable authenticated frame/origin/transport reference for a registered
paired context. Defaults bound the registry to eight peers, eight queued frames
per peer and 256 KiB per frame. Unknown requests and unrelated pins are rejected;
exact queued duplicates do not consume additional slots or replace correlation.
An export arriving before its offer waits boundedly, rather than prompting or
creating a source grant. Ownership is exclusive for the private book/local ID.

The separate native worker enters the actual book gate only after leaving receive.
It accepts the owned offer, restores an existing private choice from a genuine
export, stages results only for an existing pending owner, and returns its exact
real writer invocation once. Conflicts hold that owner without replacing its
accepted result. Private cipher failures are held without rewriting unknown
records. Another independently selected source in the same book can still reach
its real save and ACK. The registry lock is never held across tree callbacks or
book/consent/journal IO. Concurrent real receive while the native book worker
waits for tree context is tested, not just sequential fake callbacks.

Native pending guards invalidate retained writer invocations after controller
stop or owner hold. `after_saved`/`finish_save` require the exact owned commit and
protocol plus its actual confirmed saved witness. A guessed request ID, copied
work/Boolean or uncompleted writer cannot issue an ACK. Fresh historical result/
status recovery retains its new checked ACK proof; settled history is durably
marked before the physical desktop owner is released. Restart recovery here is
only from an already genuine independently sealed SaveACK, never from a fabricated
saved witness or a portable tag.

The actual `Fenster` tree-service constructor registers a fail-closed native
callback: without an exact explicitly injected controller, or while locked/stopped,
it rejects draft traffic. Startup does not construct a controller or grant sources.
The native-only factory has no renderer/document switch. Its explicit worker step
queues the existing real commit in the actual serial writer; after actual writer
completion the private work/commit identity is checked before sealing an ACK.
Sidecar failure holds automation, not a successfully saved ordinary book. These
hooks do not start a scheduler, create keys, advertise a capability or enable
production. The helper is in the four existing Linux source manifests.

Evidence: the affected pipeline/startup/runtime run passes 230 cases; follow-up
transport/origin/controller and private-cipher/lock-order runs retain unchanged
passing matrices rather than rerunning them indiscriminately. Final controller
coverage is 23 cases, with 36 source-runtime composition cases also checked.
Tests use actual encrypted book writing and actual authenticated FS1 receive,
including the real window factory, callback, queue and save-completion hook.
They cover two private sources, pre-offer waiting, queue limits, duplicates,
conflicts, stopped/expired contexts, same-thread receive-IO spies, concurrent lock
ordering, corrupt private records and fresh-owner saved-history recovery. All
files, contacts, keys and peers are isolated synthetic fixtures; no sockets,
physical provider, package build/install or private original was used.

Important remaining boundary: the registry itself is process-local. The separate
durable pre-save intentions below now retain request/hold evidence, but a crash
after native VERIFIED and before durable desktop SaveACK still needs the full
safe restoration of that genuine private book/source authority. Saved-ACK history
must not be relabeled as an unconfirmed intention, nor a primary read converted
to a saved witness. The automatic
transport/worker pump, full native setup UI and Windows counterpart also remain
unconnected. Production stays default-OFF until those lifecycle pieces are checked.

### Distinct durable unconfirmed request intention (#628)

`NativeNotesRequestIntents` uses a separate AES-GCM domain/state and the existing
independent journal key, not a saved-ACK format or consent-key generator. Its
private record binds the full original export/request/hash, pins, local ID/UID,
private choice seal and before-book fingerprints; it does not store a whole book.
States are `request_pending` and `request_settled`. The actual authenticated
primary content must match the real saved snapshot before sealing and current
known saved content when the proof is used. Encrypted-envelope and clear saved-
payload hash domains are not confused.

A desktop physical slot is HMAC-bound to the stable native book binding and local
contact ID using the independent journal key, not the peer/setup/request UUID.
The complete physical reservation is written first, then an independent request
archive; both must read back before a fresh process-memory nonce can issue send
authority. Interruption at any phase retains a hold. A populated root missing its
journal identity or a changed/missing existing key is not adopted as empty state.
The native original-provider physical hold remains independently authoritative.

The reserved provider-request lane now requires that exact fresh durable proof,
its pending-owner identity, current private consent/book and negotiated pins.
Readback via `load_held` is history only: a reloaded store, copied stamp, same old
UUID, different UUID or another source decision cannot mint a fresh send proof
over a pending physical slot. Same-owner in-process retry remains byte-identical.
Controller ownership/stop guards are installed before sealing so cancellation
during disk IO cannot leave a new uncancelled mutation token. Forgetting process
proofs does not erase disk holds; late memory revocation is rechecked after IO.

Only an actual confirmed desktop save may add its intention link to the private
saved-ACK record. That optional private digest changes no wire ACK fields. Retiring
the lease requires a fresh authenticated settled status and an already durably
marked genuine saved-ACK record with exact request/source correlation. The settled
request archive precedes its released physical marker, with exact readback;
interrupted retirement resumes only from that real terminal proof. A duplicate
old terminal record cannot release a newer UUID's physical slot. Per-request
history remains after slot reuse.

Evidence: 327 affected Linux pipeline/consent/origin/transport/startup/source-runtime
cases passed; follow-up cancellation/retirement and exact-planning runs retain
unchanged evidence. The final affected request/controller/send/pending/consent run
passes 185 cases. Matrices overlap. Request coverage is 19 cases, including
missing/changing keys/root identity, actual primary
changes, GCM-domain separation from saved ACKs, fresh-vs-reloaded authority,
physical/archive/readback interruptions and genuine terminal release/slot reuse.
All use isolated synthetic data. No Notes source changed for this slice, so its
unchanged host evidence is retained; no package/device/install claim is made.

The source-only No-op finding #632 is also corrected here: a genuine unchanged
export is a typed successful planning outcome, not a generic held ValueError.
Both complete and omitted-empty-field DTOs are compared by their exact modeled
values before any owner/request reservation. Equal semantic hashes alone do not
skip literal changes: the display-name legacy-hash collision is a negative
counterexample. Three focused cases and the final affected run cover this. An
initial new test exposed the old No-op exception being classified as held; the
explicit successful type and controller handling correct that source behavior.
This is a Linux native-controller correction, not installed/device acceptance
or a claimed Windows counterpart fix; the exact-plan invariant must carry across
future platform implementations.

The explicit query and resumed local commit are now joined below. Automatic
scheduling/discovery, common native setup and Windows counterpart remain
unfinished and production-disabled.

### Unconfirmed query, real-save bootstrap and local commit resume (#628)

`NativeNotesUnconfirmedQuery` is a distinct native type backed by the private
pending-intention ciphertext/hash, current private consent and recognized actual
primary/native model. It can also read the authenticated physical-only record
left by a crash before the archive. Its seven-field target-free status inquiry
uses the already checked native query route, never provider-request replay. The
sender still requires fresh negotiated pins and current native transport policy.
No fresh send stamp, saved witness or ACK is minted by loading/querying history.

Only a new actual authenticated VERIFIED result with exact original request
correlation, strict types/receipt/revision and unchanged chosen mutable target can
resume a local metadata commit. Current known unrelated book edits are preserved;
changed targets, unknown primary/model, revocation or stale origin are held.
An explicit private recovered context supplies original source/setup authority,
not a counterfeit fresh export choice. The resulting pending object cannot enter
the provider-request sender. If the independent archive is missing after a
physical-first crash, recovery copies only the exact already authenticated
intention ciphertext, without issuing a mutation nonce.

A fresh owner with no native saved snapshot receives a typed real-save requirement.
The actual window worker now queues a one-use `NativeNotesBootstrapSave` through
the actual encrypted/atomic serial writer. It binds the complete known native
model, actual primary, source/owner lifetime and exact payload/hash; it cannot
silently adopt newer unsaved model data. Only the actual unrepaired writer and
new native saved observation confirm this bootstrap. No ACK exists at that point.
The next deferred worker step creates the normal real metadata commit from that
genuine snapshot; its actual second save supplies the saved witness before ACK
sealing. The first primary read never calls `record_saved` to fabricate evidence,
and no manual user save is required for this unconfirmed recovery path.

This also handles a crash after metadata reached the primary but before saved-ACK
sealing: existing metadata is not itself a witness; actual saves are performed
again without replaying provider mutation. Conversely, prepared/settled native
status with missing genuine local saved-ACK history is held, not converted into
a fabricated historical receipt/hash or saved witness.

Evidence: 361 affected Linux cases pass, including 41 intention/query/resume,
33 controller, 32 reserved send, 51 pending, 57 consent, 33 origin, 11 probe,
36 source-runtime and 67 startup/off-state cases. New cases exercise fresh owners
without saved observations, physical-only crashes, changed targets/models,
known later edits, stale/revoked proofs, actual window bootstrap/metadata queues,
fake completion Booleans, stop before write and metadata-already-written crashes.
All peers, keys and books are synthetic; no physical/installed counterpart or
package/device acceptance is claimed. Native Notes sources are unchanged.

### Regular fresh-export first-save bootstrap (#628)

A fresh authenticated export can now bootstrap the first real save after restart
without an unconfirmed request record. Its separate private export context checks
the exact existing consent selection, setup, pins, recognized primary, native model
and selected ID/UID. Schema validation alone grants no authority. No recovered
request, fresh choice or saved observation is fabricated. The actual serial writer
performs the bootstrap; only afterwards may the same export restore the private
choice and plan an exact no-op or seal a new request.

Multiple approved sources share one whole-book bootstrap rather than queueing
full-book copies per source. A failed bootstrap retires only its deferred export
and releases the transient bootstrap lease; other approved exports can proceed.
It never releases a durable provider-request hold. Stop, revocation, wrong setup,
bad export hash and unknown primary are negative cases.

Evidence: 190 controller/request/consent/pending cases passed before the final
failure-isolation addition; the final 123 controller/reserved-send/origin/runtime
cases passed, including the added two-source failed-bootstrap recovery case.
These matrices overlap and do not constitute separate platform acceptance.

Still outstanding: bounded automatic discovery/transport/worker pumping, genuine
common setup UI and Windows counterpart. The window hooks remain unregistered
as an active production controller; no source capability or scheduler is enabled.

### Private slot discovery (#633, continuation of #628)

The explicitly owned controller can now rediscover pending work from the current
private consent selection (at most 256 sources) and the exact HMAC-derived physical
slot for each selected native book/contact. It checks the known actual primary and
owned native model first, performs no directory enumeration and creates no missing
store or key. Discovery runs under the native book gate, never in FS1 receive.

An independently sealed genuine saved-ACK record takes priority over unconfirmed
recovery. Its exact request and intention link must match; corrupt/conflicting
saved history holds that source instead of falling back to a new metadata save.
Otherwise the typed unconfirmed read-only query is restored, including a
physical-only crash record. Neither route issues a provider-send nonce, writer
witness or ACK. Existing owners are not duplicated; per-peer admission is bounded,
one corrupt slot does not block other approved sources, and retired slots are
skipped. Fresh negotiated pins and current private source authority remain required.

Evidence: 153 affected controller/request/consent cases passed, including 13 new
discovery cases (restart, saved-ACK preference, physical-only, no request/store,
corrupt/conflicting saved history, changed key, revoked consent, unknown primary,
unnegotiated/stopped owner, bounded two-source admission and isolated corruption).
Directory enumeration is explicitly forbidden in the focused tests. Automatic
invocation/transport pumping, setup and Windows integration remain outstanding.

### Existing native post-worker transport pump (#633)

The existing native post tick now calls a bounded Notes pump after ordinary tree,
pairing and mailbox work has released its gates. It does nothing unless an exact
native controller has been explicitly injected and the window is unlocked. No
startup controller, extra timer, background scheduler or capability advertisement
is created. Native WLAN/connection policy gates all sends and is rechecked by the
reserved sender. Current tree state is copied under its short gate; book/source
checks and network calls run outside the tree gate. No native book gate is held
across networking.

The controller restores peers only from recognized private source consent, sends
typed profile probes, discovers read-only recovery after the actual authenticated
offer, and dispatches typed requests/queries/saved ACKs. One network plan is selected
per tick with a 30-second per-plan retry deadline, bounded state and fair selection
between active sources. A fresh pending request retains its exact UUID/body on
retry; loaded intentions remain query-only. Actual queued book work still goes
through the existing serial writer. Transport ACKs never establish negotiation,
confirm a book save, retire a physical slot or settle history. After a delivered
SaveACK, a target-free query can recover a lost terminal response; only the fresh
authenticated matching terminal status drives the durable completion path.

Evidence: 338 affected source/controller/requests/consent/reserved-send/probe/origin/
runtime/startup-off cases passed. Four new actual FS1 pump cases cover full restart
recovery, offline waiting, lost probe/retry deadline and stop. They use two actual
writer saves and deliberately drop the direct terminal response. A separate thread
can acquire both native gates during every network callback. Two existing-post-tick
cases verify default-OFF/no extra timer and explicit-controller dispatch; two-source
tests check fresh-request fairness and stable retry identities. No physical or
installed counterpart acceptance is claimed. Common native setup, Windows transport
integration and multi-source stale-book rebase remain outstanding.

### Multi-source stale-book recovery (#633)

A later real book save no longer strands unrelated pending sources on an old
whole-book snapshot. The exact owned stale pending retires only its in-memory
provider-send nonce and becomes an independently authenticated unconfirmed query.
The old pending object loses ownership; no snapshot is silently replaced and no
new provider request is issued. Only a fresh exact VERIFIED result can create a
new local commit using the existing recovery context and unchanged chosen target.
Known unrelated edits and the first source's metadata survive that commit.

The short local metadata-save lane waits until the preceding actual writer witness
has been independently sealed into ACK history, not merely until the write returns.
Other read-only/provider slots remain independent. A failed completed save holds
only its owner while retaining its durable physical request hold. Once another
real book save invalidates an earlier live witness, that owner queries its already
sealed genuine ACK history and obtains fresh authenticated reauthorization of the
original saved hash; it never fabricates a current witness or redoes provider work.

Evidence: the final 106 controller/request cases pass, including four new two-source
cases (queued results, query-before-result, changed chosen target, failed first save).
Unchanged consent/pending/reserved-send cases from the broader 246-case matrix are
retained. That initial matrix exposed one regression: a same-snapshot prepared
status prematurely invalidated the still-current original live ACK. The correction
invalidates that witness only after an actual later snapshot, outside registry
locks; the final full controller matrix passes. No Windows fix or physical/provider
acceptance is claimed; Windows requires the corresponding stale-owner and historical
ACK handling in its still-outstanding native integration. Common setup and Windows
transport integration remain outstanding, with production controller creation OFF.

### Expired native negotiation recovery (#634)

Actual FS1 origins are deliberately short-lived. The Linux pump previously kept
an expired offer and repeatedly planned request/ACK sends that the reserved sender
safely refused. Two synthetic tests using real handshakes and a bounded monotonic
clock advance reproduced that availability defect; no unauthorized write occurred.

For still-recognized private sources and the same exact pins, the native worker
now cancels the expired protocol and issues a new challenge. It invalidates old
peer frames/export leases and pending local invocations, retires only their owned
process send nonces, and retains all durable physical holds and independent history.
Genuine saved ACK history takes precedence; other owners become read-only
unconfirmed queries. No owner send is planned until the replacement's actual fresh
authenticated offer has been processed. Neither old origins nor their TTLs are
extended. Old challenges and queued old saves fail closed. Fresh VERIFIED results
resume only the already checked local recovery path, never provider replay.

Evidence: 209 affected controller/request/consent/reserved-send/probe cases pass,
including pending, independent saved-history and old-save-queued expiry cases.
They check a previously active fair-selection cursor, no send before the new offer,
rejection of old challenges, invalidation of the queued writer, original saved hash
reauthorization and retirement of process send stamps. Notes sources are unchanged.
Windows must use the same refresh/demotion approach in its future integration;
Windows and physical Android consequences remain unproved, not claimed fixed.

### Windows native draft-origin boundary (#633)

The actual Windows coordinator now has a separate, production-unregistered native
draft receive callback. Only its real decrypted FS1 path can issue the private
`NativeNotesOrigin`: exact handshake peer/desktop IDs and public keys, transport ID,
canonical body hash, original 30-second monotonic deadline and native receive
generation are retained. Stop invalidates the generation even without an active
listener; disposal/quarantine/current native peer permissions also fail closed.
Body/pins/transport/lifetime are checked before and after the staging-only callback.
No book lock, file/key callback, writer wait, renderer dispatch or network work is
allowed inside that callback. The bounded draft body limit is 256 KiB.

Only offer/export/result/terminal-status directions can reach an explicitly
injected native receiver. Request/SaveACK/query directions are not desktop receive
capabilities. All seven reserved draft kinds are rejected by generic inbox/legacy
receive, not stored as ordinary contact messages. No source grant, provider writer,
SavedWitness, consent key, controller or advertised capability is created here.

Evidence: 22 new synthetic actual-FS1 scenarios plus five existing identity cases
pass both on the managed host and in the existing noninteractive Windows runner.
Cases cover the four admitted directions, three rejected directions, default-OFF,
refusal/revocation during callback, changed body/transport/peer/desktop identity,
revocation, stop before/after receive, disposal, expired proof, size budget, fake
proof and all seven draft kinds through actual legacy encrypted receive. The
canonical Release CoreTests and BASE product source builds have zero warnings or
errors. An initial native runner used an older Release test assembly while the
new tests were built as Debug; that run is explicitly discarded as new evidence.
The corrected Release-bound run includes the new 22-case marker and assembly hash
binding. No installed Organizer, interactive Windows UI, live provider, Android
device or package publication was exercised.

Windows pending/result/actual-writer/ACK-history/restart/pump and common native
setup are still missing. These checks are an authenticated native origin boundary,
not full Windows return synchronization or permission to activate production.

Windows also now has a separate native `NotesOriginalNegotiation` with immutable
paired pins and a fresh challenge. Only the exact five-field native draft offer,
authenticated by the actual `NativeNotesOrigin`, establishes the protocol context.
Copied proofs, wrong challenge/profile/pins/transport, Boolean/float versions and
extra fields are rejected. A probe or transport receipt alone grants nothing;
cancel, Stop, revocation and the original actual FS1 deadline remain effective.
Private state locks never call native origin/book callbacks. This protocol context
is not source consent, a durable request-send nonce, a writer witness or a sender.

Evidence: 15 additional actual-FS1 negotiation scenarios pass on both the managed
host and existing noninteractive Windows runner, together with the retained 22
origin and five prior identity cases (one group, overlapping previous matrices).
Release CoreTests and BASE product source builds pass with zero warnings/errors.
No production controller, common setup UI or Windows sender is registered yet.

### Windows authenticated choice, result and actual writer witness (#633)

An authenticated eight-field export can now enter a native choice API over the
actual saved book. The exact existing local ID/UID is selected by a native callback;
current native selection lifetime, original export origin and book identity are
rechecked. This is not an installed setup UI or durable source consent. Invalid
setup/hash, cancellation and a book change during selection fail before any writer.

The saved-book projection owns the nine modeled mutable fields, preserves omitted
empty defaults and excludes phone/email/photo/group writes. Unknown birth year,
literal N/FN rows and supported postal kinds are modeled; unsupported postal types
or changed custom labels hold instead of being reduced. Exact planning, not semantic
hash equality, distinguishes no-op from mutation. Only the choice's private pending
proof can issue a pending result; copied JSON/seed objects cannot retarget it.

Actual FS1 result staging checks the exact ten fields, full original request hash,
pins/correlation/receipt, strict integer revision and next basis. Receive performs
no book/selection callback or writer wait. Identical duplicates reuse the invocation;
conflicting genuine results hold that pending and invalidate a queued invocation.
The native worker prepares only the selected contact's passive `notesOriginalBasis`
inside the exact whole-book proposal. Long revisions remain decimal strings.

The existing `ContactSourceSavedCommit` can retain a native-only context guard before
and after its real writer; existing DAV callers keep their unchanged null-guard path.
The current actual generated `BridgeDispatcher.SaveAsync` supplies encryption, atomic
storage, native save sequence and the private saved witness. A result, transport
receipt, proposed payload or copied Boolean never supplies that witness. Native
source/result lifetime remains checked around preparation, writing and witness use.
No wire ACK or durable ACK intention is issued by these helpers.

Evidence: 21 new actual-FS1/native-choice/result/writer scenarios and additional
projection guards pass on the managed host and in the existing noninteractive
Windows runner, alongside the 22 origin/15 negotiation/five identity cases. The
actual encrypted primary preserves every selected-contact field except the intended
metadata, other contacts/domains, canonical ID/UID and exact maximum Long revision.
Cases include duplicate/conflict, type/correlation/revision errors, bad export/setup,
selection cancellation/change, source/choice revocation, Stop, stale book, mixed
proposal, post-primary write failure, counterfeit witness, exact no-op and a literal
display change with identical semantic hash. The existing original-contact group
also passes on both hosts after the shared writer change. Release CoreTests and
BASE product source builds are clean. One managed regression launch lacked the
documented Node path; rerunning with the existing canonical tools passed, with no
product change attributed to that environment error.

Still missing on Windows: durable Notes consent/known-book save chain, private
request intentions/nonces, independently sealed ACK history, restart/bootstrap,
reserved transport/pump and the common actual setup UI. No production registration,
installed-app/device/provider acceptance or package publication is implied.

### Windows private stable-book consent core (#633)

Explicit native approval can now persist authenticated choices in a separate
private store. Only the actual chosen native book owner may supply its exact
ID/UID/pins/share/setup bindings. A dedicated CurrentUser DPAPI purpose protects
a fresh independent 32-byte consent key; AES-GCM encrypts/authenticates the bounded
choice record. The native book path is keyed, and its exact canonical content is
bound to an authenticated actual primary and real native saved snapshot. No DAV
account consent, portable profile flag, ACK/request journal key or raw-key fallback
is reused. Only the existing private filesystem boundary is shared.

Approval/revocation rotate the private key/generation; unknown/interrupted state
holds. Exact raw-file CAS protects a newer explicit decision from an older worker;
a final context failure quarantines only that worker's own published state. Private
source seals belong to the exact choice object. Native callbacks run outside file
sessions, and raw key/roundtrip/plain buffers are cleared. Missing-store reads and
revocation create no key/root and perform no book/selection callback. Loading never
generates a replacement key. Revoked, lost, corrupt, pending, replayed old-record or
foreign-book state grants no permission.

On a stable genuinely saved book, a new store owner can restore only from a fresh
actual authenticated export with the same private source/pins/setup and unchanged
selected ID/UID, without asking the chooser again. A primary read after reopening
still leaves the native saved snapshot absent; consent cannot call `RecordSaved`
to fabricate it. A changed actual book deliberately holds at this stage: the
known-book save chain and actual writer advancement are not joined yet. This is
not complete restart/automatic Windows synchronization or permission to activate it.

Evidence: 22 new synthetic consent-core scenarios pass on both the controlled
managed host and existing noninteractive Windows runner, together with the prior
origin/negotiation/pending/actual-writer/identity group. They cover missing store,
stable restore, revocation, key loss/corruption/pending/old-record replay, foreign
book/choice, wrong source/setup, changed-book hold, actual same-content save,
reopen without a saved observation, raw protector rejection, counterfeit/foreign
seals, callback lock order, newer-decision CAS, book change during approval and key
buffer clearing/unavailability. Windows additionally exercises a real dedicated
synthetic DPAPI key and rejects the DAV-purpose unprotect; non-Windows production
protection refuses instead of falling back. Release CoreTests and BASE product
source builds pass without warnings/errors. The initial test-only compile errors
(fixture AES decrypt argument and platform guard inside a lambda) were corrected;
no product failure was inferred from them.

Still outstanding: known-book intent/advancement/recovery and real save/bootstrap
hooks before using persistent seals for metadata saves, private request intentions,
independent ACK history, reserved Windows transport/pump and common native setup.
Whole-private-root rollback/hostile same-user or administrator control is not claimed
prevented. No production controller, package installation or publication is enabled.

### Windows actual known-book writer/repair join (#633)

The previously stable-only core now has a separate authenticated known-book save
intent and the actual existing native writer hook. A native in-memory proof binds
store/key/generation/token, actual before snapshot or authenticated primary/owned
model, exact next canonical content and raw payload SHA. Its private seven-field
HMAC intent is durable/read back before the native writer invalidates its old saved
observation. Native callbacks remain outside private file sessions. Mutating save
and recovery calls use the existing serial native book mutation gate, not receive.

`BridgeDispatcher.SaveAsync` consults only an explicitly injected native store,
default null, with no startup factory or scheduler. It prepares immediately before
actual storage and confirms after real encrypted/atomic writing and `RecordSaved`,
before the contact result's post-writer source guard. The exact saved raw hash,
native book identity/next sequence and original intent are checked. The same
consent key/generation/choices survive an ordinary known book save without another
selection; a changed/missing selected ID/UID still holds that binding. Passive
`notesOriginalDauerhaft`/`notesOriginalFehler` fields report correlation, not authority.
A private chain error does not block an ordinary user save; Notes delivery holds.

The signed intent stays throughout encrypted record replacement/readback and is
removed only afterwards. Recovery accepts only its exact old/new content and
cannot roll an already advanced new book back to the old book or overwrite newer
source consent. Fake/copied-store intents, altered MACs, unrelated targets and
revocation fail closed. A recognized primary plus the actual owned native model
can repair permission bookkeeping after reopening without a saved snapshot; it
never calls `RecordSaved` or issues a writer witness. A stale owned model is denied.
Only a subsequent actual ordinary/native bootstrap save creates the first real
saved observation; automatic controller bootstrap scheduling remains unconnected.

Evidence: 15 additional actual-writer/recovery scenarios and five interruption
boundaries pass on both managed host and the existing noninteractive Windows
runner. The persistent-seal metadata case reaches the actual generated encrypted
`SaveAsync` and obtains the real saved witness. Other cases cover ordinary writes,
first real save, prepared-only/after-primary crashes, stale model, counterfeit and
foreign-owner intents, wrong target/MAC, no rollback, revocation/newer decision,
callback lock order, ID/UID change and missing native model. Failures after intent
write/content replacement/readback/before deletion/after deletion preserve a
successful ordinary user write and recover without an extra book save or fabricated
save sequence. Existing original-contact regressions pass on both hosts; Release
CoreTests and BASE product builds are clean. Final source change after these runs
is a comment correcting the now-joined class description, with no behavior change.

Still outstanding: independent private request-intention/outcome history and fresh
send nonces, exact restart recovery, reserved Windows transport/controller pump,
automatic bootstrap scheduling and genuine common setup. No installed-app/UI/live
provider/device acceptance, production registration or package delivery is implied.

### Windows independent journal primitives (#633)

The Windows history crypto accepts only a mandatory accessor returning an owned
copy of an already existing independent 32-byte journal key. No backend is chosen
or registered and no key is created/replaced. Request and saved-ACK envelopes use
separate AES-GCM purposes bound to exact record IDs; physical book/contact slots
use a separate HMAC domain. Decoding rejects duplicate fields, noncanonical clear
JSON, tampering and over-budget input. Owned key/plain buffers are cleared.

The existing private filesystem boundary now offers an explicit journal layout,
not arbitrary filenames: only `.journal-key` and `p-`/`r-`/`a-` plus 64 lowercase
hex digits and `.json`. Only that layout permits up to 2 MiB; consent names and
256 KiB limits remain unchanged. New journal roots are published by no-replace
directory rename so a concurrently existing root cannot be reported as newly
created for identity initialization. A missing-store read creates nothing.

Focused crypto/layout checks and existing original-contact/private-file regressions
pass on the controlled managed host and existing noninteractive Windows runner;
Release CoreTests/BASE builds have zero warnings/errors. These primitives issue no
source permission, send nonce, saved witness or ACK. Actual request/outcome stores,
recovery/pump/setup and key-backend selection remain outstanding.

### Windows physical-first request intentions (#633)

The native serial worker can now seal a request only from an exactly owned pending,
current real saved snapshot and dedicated durable source seal. The encrypted record
binds the complete modeled request/target, authenticated export, selected ID/UID,
private source/key/generation/book seals, chosen before contact and whole-book
hashes. It does not copy the entire book into each intention. The existing independent
journal key is pinned for every operation; no replacement/backend is supplied.

A physical book/contact HMAC slot is reserved before writing the independent UUID
archive. Both are read back before issuing the private in-process proof. Unknown
existing roots without journal identity hold rather than initialize. A physical-only
crash record remains discoverable, and another UUID/setup cannot bypass its hold.
Loaded records are cloned read-only data and never recreate a process proof.
The typed fresh proof requires the same pending and fresh negotiated pins, current
source/book/complete frame and unchanged independent physical/archive history.
Result arrival, Stop, revocation, key/identity changes or tampering deny its use.
Native source/book/protocol callbacks run outside registry/private file sessions.

Evidence: 20 new synthetic request cases pass on managed host and the existing
noninteractive Windows runner, retaining the previous actual-writer/consent/crypto
group. Cases cover physical/archive/readback interruption, Stop during sealing,
loaded-history denial, unknown root, key/identity loss, archive/physical tampering,
different UUID/setup, counterfeit/foreign proof, missing private consent, missing
store, result arrival, cancelled protocol and intervening actual native save.
Release CoreTests and BASE builds have zero warnings/errors. No Windows sender is
registered. Terminal retirement, query recovery, independent saved-ACK history,
controller/pump/setup and production key-backend selection remain outstanding;
physical holds are deliberately not released by this slice.

### Windows genuine independent saved-ACK history (#633)

`NotesOriginalSavedAckIntents` now seals an independent encrypted record only after
the actual pending's real `ConfirmedSave` witness and exact owned process request
context verify. The original physical/archive intention must still match. The
record binds the complete request history/result and actual saved book identity,
sequence/hash to the same existing independent journal identity. It cannot be
created from a transport/result receipt, failed writer, missing or loaded-only
request store. No source-consent key or replacement journal key is used.

Only durable readback plus fresh native rechecks issue the private in-process ACK
proof. Its body revalidates the current genuine witness/source/result, unchanged
physical/archive request, exact outcome ciphertext/frame and process epoch.
Idempotent sealing reuses identical history, never overwrites conflicting history.
Read-only loads return cloned data, not an ACK proof. Stop/revocation/later real
book writes invalidate live proof but do not delete genuine independent history.
Interruptions after durable history leave read-only recovery data, not send rights.

Evidence: 17 additional actual generated-writer synthetic scenarios pass on both
managed host and existing noninteractive Windows, alongside retained prior cases.
They cover real saved ACK/idempotence, before/failed save, absent or reloaded request
context, outcome/request tampering, missing history, key change, revocation/later
native save/Stop, history-write/readback interruptions, Stop/revoke during sealing
and unknown pre-existing outcome root. Release CoreTests and BASE builds are clean.
Still outstanding: fresh native reauthorization of loaded history, query-only
restart recovery, exact terminal/mapping installation and physical retirement,
reserved sender/controller pump/bootstrap and common setup. None is inferred from
the now-durable JSON; no production sender/key backend or installation is enabled.

### Windows target-free historical queries and fresh ACK reauthorization (#633)

After reopening, a private query proof requires the actual independently encrypted
saved-ACK record, matching physical request history, current private source/key/
generation/book/setup/pins, authenticated known primary and actually owned native
model. The exact chosen ID/UID, modeled target and installed metadata must still
match. An unrelated known book edit is preserved; changed chosen content or mapping
holds that source. The native saved snapshot may remain absent: this correlation
never calls `RecordSaved` or manufactures a new writer witness.

The typed query carries seven fields and no target or desktop saved hash. Only a
subsequent fresh actual-FS1 result, or exact prepared/settled status including the
original genuine saved hash, can issue a private restored ACK proof. That proof
keeps the actual origin/protocol/private-history lifetime and rechecks all current
bindings when used. It returns the original historical ACK/hash, not a receipt for
the current book. A terminal observation does not install mappings or release the
physical slot. Without genuine local saved-ACK history, even an otherwise matching
terminal hash cannot reconstruct ACK authority.

Evidence: 15 additional query/reauthorization cases (32 saved-ACK cases including
the retained 17) pass on managed host and existing noninteractive Windows. They
cover restart with no saved observation, unrelated known save, revocation, changed
target/mapping, no offer/history, Stop, exact prepared/settled result, wrong receipt/
desktop hash, copied/expired origin and missing history after query. Reopened
native snapshots stay absent throughout; physical holds stay intact. Release
CoreTests and BASE builds are clean. One expanded Windows run hit its existing
bounded deadline without a result; the unchanged assembly passed the separately
bounded repeat. No product defect was inferred from the timed-out run.

Unconfirmed (no genuine saved-ACK) recovery, exact terminal retirement, reserved
Windows sending/controller/bootstrap/pump, key-backend selection and actual common
setup remain outstanding. Production stays OFF; no installation/device acceptance
or publication is implied.

### Windows unconfirmed query-only restart (#633)

A separate opaque unconfirmed-query proof can now correlate the selected physical
request record with current private source/key/generation/book/setup/pins, known
authenticated primary and actually owned model. The chosen ID/UID and exact modeled
target must still match; unrelated known edits are retained. A physical-only crash
record is sufficient for this read-only question, not for request-send rights.
The query has seven fields, the original UUID and no target/desktop hash. It does
not create a pending writer, saved snapshot, witness or ACK. Stop and changed
source/target/history/protocol fail closed; no missing store/key is created.

Ten additional synthetic cases pass on the full managed group and a specifically
selected new-test-only noninteractive Windows slice: restart, physical-only crash,
revocation, changed target, unrelated native save, no offer, Stop, missing record,
unnegotiated foreign pins and tampered physical record. Reopened snapshots remain
absent. The explicit Windows slice is not represented as rerunning the entire
group; unchanged earlier Windows history/reauthorization evidence is retained.
Release CoreTests and BASE builds are clean. Fresh VERIFIED local recovery,
bootstrap/writer scheduling, terminal retirement and the reserved controller/pump/
setup are still missing; query support alone enables none of them.

### Windows durable terminal retirement and exact next-slot reuse (#633)

A fresh authenticated exact `settled` status can now seal a separate independent
terminal record bound to the original genuine ACK/request/physical slot. Durable
terminal readback and the still-current native source/ID/UID/installed metadata
precede any request retirement. Prepared, forged, missing/tampered, revoked or
wrong-installation proof cannot release the hold. Terminal hashes alone remain
insufficient; the genuine original ACK history is never replaced by terminal data.

The opaque terminal proof authorizes only its own request store. Retirement writes
the settled archive first and physical slot last, then verifies both. Partial
transitions stay held and are repairable only through the same checked durable
terminal chain. A next UUID can reserve that slot only with the matching native
terminal proof and exact settled physical/archive state. An old completion cannot
retire or overwrite a new pending request. Historical data stays private/retained.

For an already retired request, independently validated terminal history plus exact
installed ID/UID/mapping allow later local content edits without permanently
stranding the next request. Before retirement, unsettled work still requires its
exact chosen modeled target. A reloaded terminal chain needs fresh native status
reauthorization, never a fabricated current writer witness or saved snapshot.

Fifteen new synthetic actual-writer cases pass in the full managed group and a
clearly identified new-test-only noninteractive Windows slice. They cover success,
prepared/fake proof, terminal/archive/physical interruption, wrong installation,
tampered/missing terminal, missing archive, exact next-UUID reuse, reloaded repair,
revocation/Stop/mapping change between terminal sealing and physical retirement.
Release CoreTests and BASE builds are clean; unrelated platform evidence is retained.
Fresh VERIFIED local recovery/bootstrap, reserved transport/controller/pump, the
existing key-backend selection and common real setup remain unconnected; production
stays OFF and no package/device acceptance or installation is implied.

### Windows fresh VERIFIED local recovery through actual saves (#633)

An unconfirmed query can now issue a separate opaque local-recovery context only
after the actual fresh FS1 origin authenticates the exact ten-field VERIFIED result
for the original request. Prepared/settled status, wrong request hash/revision/type,
copied context or imported JSON cannot do this. Current query/private source/known
primary/owned model/selected ID/UID/exact target and native protocol/origin remain
checked throughout. The old export's expired origin is not resurrected.

Resume requires a genuine current native saved snapshot; otherwise a typed
`RecoveryNeedsRealSave` reports that requirement, without creating a snapshot or
granting a write. After an actual ordinary native save, the recovered pending owns
the same UUID/request/result and a fresh exact current saved-book proposal. Unrelated
known edits are retained. This context can only perform the local metadata commit:
provider-send intention capture always denies it. Its in-memory ownership is kept
separate from fresh provider-send proofs and is cleared by Stop.

Only the subsequent actual metadata writer witness can seal an independent ACK.
For a physical-only crash, that step can repair the missing archive with the exact
already authenticated physical ciphertext; it never mints a provider-send nonce.
Queued recovery fails closed on revocation, Stop, chosen-target change or expiry,
without overwriting the current native user data. Existing native writer/consent
hooks supply both real saves; no primary read calls `RecordSaved`.

Twelve new synthetic actual-FS1/writer cases pass on the full managed group and an
explicit new-test-only noninteractive Windows slice: restart, physical-only, wrong
result, prepared status, stale revision, Boolean version, revocation, changed target,
Stop, expired queued invocation, counterfeit context and unrelated-edit rebase.
The restart path observes real native sequence 1 after the deliberate ordinary save
and sequence 2 after metadata save before ACK authority. Release CoreTests and BASE
builds are clean. These tests explicitly invoke the native ordinary writer; actual
automatic bootstrap queueing is not implemented by this slice. Common setup,
reserved transport/controller/pump and production existing-key backend selection
remain outstanding; production remains OFF and nothing is installed/published.

### Windows typed bootstrap invocation at the actual writer (#633)

The first-save requirement now has an opaque one-use native bootstrap invocation,
issued only from the current private fresh VERIFIED recovery context. It owns the
actual loaded native text, checked against the authenticated known primary, and
requires that no real saved scope exists yet. Payload/current model/permission/
origin are rechecked before writing. The private optional native argument of the
actual `BridgeDispatcher.SaveAsync` dispatches this object through the existing
encrypted atomic writer and real `RecordSaved`; it is never deserialized from a
renderer token or Boolean. Mixed historical/contact/tree/sync lanes are denied.

Completion requires the actual current saved text/hash/scope after the write, not a
receipt or primary observation. It reports bootstrap correlation only, not the
subsequent metadata-saved witness or ACK authority. Stale/changed/mixed/forged,
revoked, expired or already-used invocations fail before replacing user data.
The normal no-bootstrap save path is unchanged and retains ordinary-save behavior.

The existing recovery matrix now invokes this actual typed path, with eight added
negative/bootstrap cases (20 overlapping recovery cases total). Full managed tests
and the new-recovery-only Windows slice pass; original-contact regressions also
pass on both hosts after the shared SaveAsync signature/dispatch change. Cases
cover forged object, changed payload, intervening real save, revocation/expiry,
post-primary failure, double invocation and mixed tree save. Release CoreTests and
BASE builds are clean. This joins the real native write boundary, not an automatic
queue: controller construction, shared bounded bootstrap scheduling, reserved
transport/pump, key-backend selection and actual common setup remain outstanding.

### Windows reserved typed FS1 sending (#633)

The coordinator now has separate native-only send methods for probes, fresh-owned
requests, unconfirmed/history queries and genuine live/restored ACKs. No method
accepts copied draft JSON or generic queue items; there is no legacy/mailbox
fallback. ACKs additionally require the actual current negotiated paired pins.
Probe transport receipts alone do not negotiate a profile or grant source access.

Current paired desktop/peer IDs/keys/permissions and Stop generation are captured
under the brief tree gate. Native body/source callbacks and networking run outside
tree/book gates. Native WLAN policy, own secret availability/identity, pins, Stop
generation and exact body are rechecked around every network phase and receipt.
Existing endpoint/Post/FS1 crypto primitives are reused, with an eight-second linked
budget for the whole operation and only existing paired endpoint alternatives.
Offline/uncertain outcomes are quiet false; explicit caller cancellation propagates.
An authenticated delivery receipt never confirms metadata save or native settlement.

Seventeen new synthetic authenticated-handler cases pass in the full managed group
and a clearly identified new-test-only noninteractive Windows slice. All six typed
paths, offline/counterfeit request/ACK, policy/permission/key loss after handshake,
Stop before message/after receipt, invalid receipt, caller cancellation and the
actual bounded network timeout are covered. A separate thread acquires tree and
global book gates at every callback; custom assertion exceptions cannot be mistaken
for expected network failure. Generic outbox stays unchanged and native request
holds remain pending after ACK delivery. Release CoreTests and BASE builds are clean.
No controller, timer or sender is registered at startup; bounded discovery/owner
dispatch/shared bootstrap scheduling, existing-key backend and actual setup remain
outstanding. This is not installed-app/device/provider acceptance or publication.

### Windows regular fresh-export bootstrap and bounded private source lookup (#633)

An authenticated regular export now has its own private bootstrap context, distinct
from unconfirmed VERIFIED recovery. It binds the existing exact private choice,
key/generation/book/share/setup/pins, known authenticated primary, actual owned model
and selected ID/UID. Schema validation alone grants nothing. Missing consent/key,
unknown primary, wrong setup/ID/UID, expiry/Stop/revocation or unsupported chosen
projection holds before bootstrapping; there is no chooser/name/default-book fallback.

Without a real saved snapshot, restore reports a typed first-save requirement.
Only an actual one-use native writer invocation creates the first real scope;
afterwards the same export restores its existing private selection and plans an
exact no-op or pending request without replacing the consent key or asking again.
Bootstrap adapters accept only the private export or VERIFIED-recovery context,
never fabricated request history or arbitrary callback authority. A second queued
bootstrap cannot write again after the first actual save, while that second source
can use the resulting real saved scope. Shared automatic scheduling remains separate.

Bounded discovery exposes at most the 256 already-private selections and their
native book binding, only after current known-primary/owned-model checks. ID/UID
conflicts omit that source instead of blocking unrelated selections. Returned
hints are clones, not mutation/ACK rights; no directory search/key/store creation
or primary-read `RecordSaved` is involved.

Fifteen new synthetic cases pass in the full managed group and a Windows slice that
also reruns the 20 affected VERIFIED/bootstrap cases (overlapping prior evidence).
They cover regular save/no-op, absent consent, hash/setup/key/primary/UID failures,
revocation/Stop/expiry, unsupported postal projection, reopened read-only discovery,
two-source UID isolation and late duplicate bootstrap denial. Reopened scopes stay
absent until the actual writer. Release CoreTests and BASE builds are clean.
No production controller/pump/common setup or existing-key backend is registered;
automatic coalesced bootstrap dispatch is still missing and nothing is installed.

### Historical ACKs after later local edits (#635)

The initial Windows history gate was too strict: after a real metadata save and
independent genuine ACK sealing, a later ordinary local content edit prevented even
the target-free inquiry/reauthorization of that old ACK. A positive synthetic case
reproduced `notes_choice_historical_target_changed`, leaving the old physical hold
stranded despite unchanged private source, ID/UID and installed original metadata.
The earlier Windows descriptions requiring current mutable-target equality for
genuine historical ACKs are superseded by this correction.

Only for independently authenticated genuine saved history, current mutable content
may now advance. Current private key/generation/book/setup/pins, known authenticated
primary/owned model, exact ID/UID and installed original metadata still must match.
The original request/target remains immutable and authenticated inside its independent
journal. Fresh actual native result/status is still required to resend the original
saved hash; terminal durability and matching installation still precede retirement.
No book rewrite or new saved witness is needed. Unconfirmed recovery/fresh provider
requests keep their strict exact-current-target checks unchanged.

The final focused matrix passes on host and noninteractive Windows: 14 historical
positive/negative cases, 10 unconfirmed-query and 20 VERIFIED/bootstrap cases
(overlapping earlier evidence). Explicit ID/UID/mapping/key/revocation/history and
missing-history terminal reconstruction negatives remain denied. A subsequent local
edit survives fresh settled status and journal retirement byte-for-byte, with the
reopened saved snapshot still absent. The full earlier managed matrix and clean
Release CoreTests/BASE builds are retained; the last two additions are test-only
ID/UID negatives and need no second unchanged product build.

Linux already separates these authorities in `_verify_history_context` versus
`_RecoveredRequestContext.require_current`; that concrete source approach was
ported without changing Linux/Notes inputs or claiming new Linux/physical Android
acceptance. Production registration, setup and device/package pauses are unchanged.

### Windows bounded owner controller and deferred plans (#633)

The explicitly injected controller now stages only bounded authenticated FS1 frames
at receive time; it performs no book/key/readiness callbacks there. Duplicates replace
their queue entry rather than growing it. A separate serial deferred turn uses the
existing native book gate for private source refresh, exact owner correlation and
at most one rotating physical-source lookup. Genuine saved-ACK history has priority;
corrupt or mismatched ACK history never downgrades to unconfirmed recovery. Peer,
queue and owner budgets and isolated holds prevent one source from blocking others.

Native work offers carry only the existing typed bootstrap or metadata invocations.
Owner guards add restrictions to queued writes, not permissions. Actual completion
requires the real native writer witness before independent ACK sealing. A failed
save drops only memory ownership; its durable physical hold survives. Stale whole-
book snapshots demote to same-UUID local recovery and preserve other source saves.
Exact independent terminal proof remains mandatory for retirement and next-UUID
slot reuse; old completion cannot overwrite a new request.

Opaque transport plans use only the reserved typed FS1 lanes, rotate among owners
and bound retries to 30 seconds. A new genuine save can promptly schedule its ACK.
Expired offers renew the challenge and cancel old queued writer/bootstrap/process
proofs without releasing disk holds. Restored work queries first and never recreates
provider-send authority. Cached native readiness is only an additional restriction.

Seventeen synthetic receive/deferred/actual-writer cases pass on the host (including
the full managed group) and an explicit controller-only noninteractive Windows
slice: fresh/reopened/physical-only/history discovery, corrupt-history hold, bounded
duplicate staging, readiness, Stop/failure, stale rebase, retry bounds, counterfeit
plan, expired-offer renewal, exact next UUID and two-source fairness/conflict isolation.
Release CoreTests and BASE builds are clean. No production factory, key backend,
maintenance pump, UI/SavedBook dispatch or inline writer-completion callback is
registered by this layer. Tests explicitly dispatch the actual native writer; this
is not yet automatic installed operation or device/provider acceptance.

### Windows inline native save completion (#633)

The controller now issues an opaque one-use completion bound to its exact owned
native work, text/token/bootstrap and current readiness restriction. The private
optional `SaveAsync` argument accepts this native object, not renderer JSON or a
saved Boolean. It checks before writing and seals the genuine independent ACK
immediately after the actual writer returns, before releasing the serial book gate
or acknowledging the renderer. Bootstrap completion is similarly correlated there.
Calling completion without a real writer witness cannot create ACK history.

If only independent journal sealing fails after the actual book save, the save
remains successful with a Notes error marker; Notes memory ownership is dropped
while the durable request hold remains. Early rejection, failed write or stale
readiness likewise releases no disk authority. Ordinary saves without a native
completion retain their existing behavior; the shared original-contact path was
regression-tested on both hosts after this dispatch change.

The 17 controller scenarios now use inline completion and pass again on host and
Windows. Five additional cases cover unknown journal identity after genuine save,
forged completion, altered payload, readiness loss and completion without a writer.
Windows runs are explicit bounded slices, not a claim that the full native group
was repeated; the full managed group and original-contact group also pass. Release
CoreTests and BASE builds are clean. No production factory/backend, UI/SavedBook
CAS dispatch, maintenance/event pump or real common setup is enabled by this hook.

### Windows single-use UI/SavedBook handoff (#633)

An explicitly injected native UI session can now publish one bounded eight-second
lease for exact controller-owned save work. It retains the native before text and
real completion object; renderer token echo can select only that existing work,
never construct source permission, a pending writer or ACK proof. Under the actual
book gate, `SaveAsync` consumes the lease once, rechecks current native before/text
and derives bootstrap/completion/contact invocation internally. Cancellation,
expiry, Stop, replay, unknown tokens or changed text cannot replace user data or
release a physical hold. There is no startup factory or key-backend selection.

The actual frontend callback independently requires idle editor/sync/save/note-
snapshot/tree/contact lanes and equality of both current `DATEN` and its last saved
model with the native before model. Metadata proposals may change only Notes basis
metadata, not IDs/content or unrelated domains. A required unchanged bootstrap is
deliberately sent through the existing serial SaveACK machinery. The exact native
payload and opaque lease accompany the save; a later queued user edit is preserved
and does not reuse that lease. Rejected offers cancel quietly rather than writing
behind unsaved renderer state.

Eight native UI-lease/actual-writer cases pass on host and noninteractive Windows,
including bootstrap, metadata/replay, cancel, expiry, counterfeit token, mixed text,
intervening native save and session Stop. Thirteen actual application DOM cases
separately pass for accepted metadata/bootstrap, unsent edits, pending/timed saves,
wrong before/UID/noncontact data, malformed token, duplicate offer and later queued
user edit. These are separate synthetic native-command and frontend checks, not an
interactive installed-UI or combined live-device acceptance claim. Full managed
and original-contact regressions pass; the latter also passes on Windows after the
shared dispatcher/contract/frontend change. Release CoreTests and BASE are clean.
Automatic event/maintenance pumping, prompt readiness negotiation, shared bootstrap
coalescing and actual common setup/backend registration remain outstanding.

### Windows explicit event/maintenance worker and UI restriction (#633)

An explicitly injected worker can now attach to the existing coordinator maintenance
loop. Receive and native SaveACK completion only release a single coalesced wake;
book/source work, UI publication and typed networking remain deferred. The existing
30-second periodic loop also waits for that wake without creating another timer,
listener or server. Event wakes do not accelerate generic outbox/mailbox polling.
Turns serialize, process at most four staged items and offer at most one UI save or
one reserved network operation. A failed UI handoff drops only its exact memory
lane; durable physical history remains held. Backlogs can wake another bounded turn.

Readiness uses a five-second native before-model probe and short cached restriction.
The frontend reports idle/current/last-saved equality without saving anything. Native
probe identity, model, expiry, one-use reply and Stop are checked; this Boolean is
never consent, a writer witness or ACK authority. The final UI lease CAS and native
writer checks still apply. Stop detaches only the explicitly attached pipeline,
cancels its controller/UI/readiness state outside the tree gate, and retains disk
holds. Foreign explicit receive callbacks are not overwritten or detached.

Eight readiness and three worker scenarios pass on host and noninteractive Windows:
stale/foreign/expired/model-changed/replayed probes, cache expiry/Stop, overlapping
turn coalescing, actual existing-loop receive wake through UI lease/native writer/
inline ACK, and Stop of pending work. The loop test never calls service StartAsync
or opens listeners; a bounded event completion proves dispatch before the periodic
tick, and writer wake is observed outside the book gate. The full managed group,
16 frontend DOM cases and original-contact regression pass; the latter also passes
on Windows. Release CoreTests and BASE builds are clean. All pipeline construction
remains explicit: no startup factory, existing-key backend or common setup is
registered. Combined frontend/native wire and installed/device acceptance are not
claimed by these separate synthetic checks.

### Combined actual frontend/native worker wire (#633)

Three controlled host cases now join the actual application DOM to the native
command parser, explicit event worker, one-use UI lease, actual encrypted SaveAsync,
inline saved-ACK journal and terminal retirement. The synthetic counterpart uses
real FS1 framing/authentication through the existing HTTP-handler test boundary;
no listener, real device or provider writer is started. Frontend SaveACKs in this
wire come only from the actual native writer, not synthetic success Booleans.

The cases cover ordinary operation, reopening with no saved scope (requiring an
actual unchanged bootstrap before metadata save) and an ordinary local edit after
the genuine metadata SaveACK. The last case preserves that real later saved edit
while reusing the original historical saved hash for terminal handling. Exactly
one provider-request UUID is used; the unrelated synthetic note and actual
encrypted/native/frontend final book agree after retirement. Serialized process
messages and bounded event waits replace polling or a new test server.

The test harness binds its controller to the post-reopen native writer. Its
concurrent-worker gate check uses a bounded acquisition rather than assuming that
no independent actor could acquire an already released gate; existing single-actor
regressions keep their immediate release assertion. These were test-harness fixes,
not inferred product defects. The three joined cases, full managed group, 16 DOM
cases and existing original-contact regression pass. Product inputs did not change
in this test-only slice; prior clean BASE/native Windows checks are retained, not
represented as a new joint Windows/installed GUI acceptance. Windows joint DOM and
physical Android/provider acceptance, common setup and production key-backend
registration remain open; no installation/publication is implied.

### Read-only existing Windows journal-key backend (#633)

The new explicit native-path adapter reads only an already existing phone
`storage.key` with its exact current-user DPAPI purpose. It never constructs
`TelefonStore`, invokes its create-if-missing loader, creates a database or obtains
a consent/book-encryption key. A fixed HKDF-SHA256 domain derives a separate stable
32-byte Notes journal key from that existing independent secret. Missing, replaced,
malformed or unavailable material holds; an existing journal identity is never
adopted under a replacement key. Relative/current-directory profile guessing and
Unix production fallback are rejected.

The private filesystem boundary has a separate read-only existing-key layout:
only `storage.key`, at most 4 KiB, no root creation, write or delete. Consent names/
256-KiB limits and the exact journal names/2-MiB limit remain unchanged. The standard
private lock may be created only in an already existing key directory; no key or
history state is initialized by reading. Ownership/ACL/reparse/link checks remain
mandatory. The envelope is read again after decoding, outside the private session,
to reject a changed key. Owned raw/decoded buffers are cleared; the derived copy
belongs to its journal consumer and is cleared there.

Twelve additional synthetic cases pass on host and Windows, including actual
current-user DPAPI on owned Windows fixtures: absence, stable/domain-separated
owned derivation, loss/replacement with an existing physical hold, malformed/
noncanonical/incorrect-length data, decoding failure, change during decode, narrow
read-only layouts and symbolic/hard-link rejection. Prior journal primitives and
original-contact/private-file regressions also pass on both hosts; the full
managed group and clean Release CoreTests/BASE builds are retained. No actual user
phone key, database or Android keystore was read. This supplies a backend, not
startup registration/common setup; installed-root availability/ACL and interactive
setup/device acceptance remain open and nothing is installed or published.

### Explicit Windows native session composition (#633)

The concrete session now composes the existing-key reader, fixed private request/
outcome roots, genuine choice store, controller, UI readiness/lease and deferred
worker. Admission requires current authenticated private choices, the exact native
profile book binding and an existing independent key. Without genuine choices,
even an existing phone key or portable auto fields trigger no phone-key lookup,
journal creation, prompt or receiver attachment. Missing keys, unknown books and
foreign callbacks remain held; no identity, key, database or service is created.

The bridge has an explicit internal known-choice resume entry using only its
already existing coordinator and actual writer/model/primary callbacks. It is not
called by startup or a renderer command. Failure, cancellation and shutdown clean
up only owned hooks. Notes-only Stop detaches its own maintenance/receive binding,
preserves tree identity/private consent/durable holds, and does not remove a foreign
receiver installed before or after attachment. A stopped instance cannot restart
its old proofs; a new explicit session must revalidate current known state.

Ten composition cases and the 11 affected readiness/worker cases pass on host and
noninteractive Windows, alongside original-contact/private-file regressions and
the full managed group. Cases cover default OFF/no key lookup without consent,
missing key, wrong profile/unknown primary, foreign receivers, idempotent admission,
reopening without a saved scope then real bootstrap/metadata saves/independent ACK,
owned detach and key loss after attachment. The bridge entry is compiled, not a
claim of modal/installed GUI acceptance. Release CoreTests and BASE are clean;
the product build precedes only later test additions, not product changes.
Common conscious first-setup UI, automatic startup registration and real provider/
device acceptance remain open. The full draft remains unadvertised and production
OFF; composition alone enables none of those missing release gates.

### Monotone native source addition (#637)

Windows `NotesOriginalChoiceStore.AddSources` and Linux
`NativeNotesChoiceStore.add_sources` are separate native addition operations, not
aliases for a full replacement decision. They require an authenticated existing
private grant, recognized actual saved/primary book and current genuine native
choices. They retain the exact existing consent key/epoch, book/content binding
and unchanged source records, and merge only independent additional sources.
Existing local IDs and peer/own/share bindings may not be changed or collide.
Identical additions are idempotent without key/approval rewriting or journal
intention creation. Empty addition does not revoke or initialize a missing grant.

Native book observations and choice origins/guards are checked outside private
file sessions; private-state CAS rejects concurrent revoke/full replacement and
prevents lost updates. Pending book intents and missing/corrupt/unknown private
state hold rather than being cleared. Failed publication or changed post-save
context leaves its own record pending, without overwriting a newer decision.
Full `Approve`/`configure` and `Revoke`/`revoke` retain their stronger epoch
boundary. Historical/unconfirmed source-seal, exact-target, independent journal
and actual writer checks have not been relaxed. Loaded request history still
grants queries only, never provider replay.

The availability gap was reproduced separately with real synthetic native saves
on Windows-source host and Linux: full replacement with fresh A+B choices strands
old A history by design. Both platforms now test that this replacement boundary
remains, while addition preserves genuine saved history through reauthorization
and exact terminal retirement. Sixteen cases per platform cover that history,
idempotence, fresh/loaded intentions and closed admission/collision/unknown-book/
concurrent-decision paths. All 16 Windows cases also pass noninteractively on
Windows. The full managed group (including joined DOM/native wire), 309 selected
Linux cases and original-contact/private-file regressions pass; the latter also
passes on Windows. Release CoreTests/BASE builds are clean. A test-only wire
final-observation race was corrected by joining its owned worker turn before
reading the released private journal, without changing production behavior.

These APIs are not yet connected to common setup or startup. #636 retains that
work and the installed GUI/provider/device/package acceptance gates. The draft
remains unadvertised and production OFF; no user original, notebook, actual phone
key, device, installed application or package was accessed or activated here.

### Windows bounded setup export acquisition (#636, partial)

An explicitly created native setup collector can now share authenticated receive
with an existing controller without replacing its callback/owner. It uses a
separate exclusive setup slot, one exact native protocol challenge, a two-minute
lifetime and at most eight exports. Receive does no book/key IO, chooser, source
publication or writer work. A matching setup negotiation is not passed into an
ongoing worker negotiation; exports can still reach already authorized workers.
Results and terminal frames are not even presented to the setup observer.

Deferred opaque candidates require genuine current offer/export origins, exact
pins/frame identity and current acquisition ownership. Display returns copies.
The existing native choice constructor still needs a conscious existing-contact
selection and exact current native snapshot. Collection/contact choice alone
cannot produce durable consent. Conflicts hold their bounded source slot;
duplicates invalidate stale candidate references. Export-before-offer waits for
the genuine negotiation. Cancel, expiry, Stop, foreign slot or an intervening
book save cannot become permission; owned detach retains the existing worker.

Eighteen acquisition cases plus one shared-receiver result/terminal-isolation
case pass on host and noninteractive Windows. Eleven affected readiness/worker
cases, full managed group with joined DOM/native wire and original-contact/private
file regressions pass, the latter also on Windows. Release CoreTests/BASE are
clean. No setup collector is registered by startup or renderer command, no modal
dialog is opened and no grant is published by this component. Actual native
dialog/decision publication, setup-time decision CAS, restart registration and
Linux counterpart remain open in #636. This Windows step is not Linux or installed
GUI/device/provider acceptance; all existing pauses remain effective.

### Windows native setup dialog and before-dialog decision CAS (#636, partial)

The native candidate entry now connects a real Windows dialog implementation to
a bounded decision flow, still without startup/renderer registration. The dialog
shows the native peer ID/key, exact share/setup and existing local IDs/UIDs. No
contact is preselected; Cancel has initial focus and only an explicit selection
enables persistent updates. Display text is sanitized in native controls, not used
for identity matching. The modal implementation is compiled but not interactively
executed under the existing GUI pause.

Before the dialog, an opaque one-use native decision captures authenticated private
state plus the actual saved snapshot/primary. The dialog runs outside book/tree/
private file locks with detached display copies. On return, cancellation, genuine
candidate/current origin, exact snapshot/primary and selected native ID/UID are
rechecked. The BEFORE-dialog private-state CAS reaches the actual publication,
not a precheck followed by a fresh decision. Initial/revoked setup uses a full
decision; existing sources use only monotone addition. A same-owner empty revoke
also invalidates open in-process setup decisions without creating a key or grant;
persistent decisions from other store instances are still caught by private CAS.

Nineteen synthetic native dialog-boundary cases pass on host and noninteractive
Windows, including initial/addition, cancellation, concurrent revoke/replace,
actual save during selection, stopped acquisition, forged selection/proof,
display aliases, one-use commit and revocation during key protection/publication.
The 16 addition cases pass again on Windows; full managed (including joined wire)
and original-contact/private-file regressions pass, the latter also on Windows.
Release CoreTests/BASE are clean. Callback tests are not an interactive modal
acceptance claim. Actual peer/acquisition UI ingress, Linux setup counterpart,
startup recovery registration, installed permissions/ACL and provider/device/
package acceptance remain open. No renderer field, general contact-sync flag or
transport delivery becomes consent, and production remains OFF/unadvertised.

### Linux before-dialog native setup decision (#636, partial)

Linux now has the corresponding one-use `NativeNotesSetupDecision`. Before any
chooser, it authenticates private state/no pending intent, captures actual saved/
primary observations and distinguishes initial consent from monotone addition.
Only a digest of exact bounded private files, not the raw consent key, is retained
by the decision. Native book context is checked outside private locks; the
BEFORE-dialog digest is checked under the actual publication lock. The selected
genuine native choice, book and original private decision must still match.

Same-owner full decisions/revocation invalidate pending in-process setup, including
an empty revoke without creating a key. Persistent decisions by another store
instance are rejected by private-state CAS. Closing/cancelling a chooser requires
no commit; wrong types, reused decisions, unknown/pending private state and actual
saves during selection cannot grant a source. Changed post-publication context
holds only that own published record, without discarding a newer decision.
Existing public replacement/revoke, monotone addition and strict historical/
unconfirmed/writer/journal semantics remain intact.

Eighteen new actual synthetic encrypted-writer/native-choice cases and the 309
affected Linux regression cases pass. These tests do not open GTK, a listener,
installed profiles/keyrings or private originals. Linux setup acquisition/GTK
entry and automatic recovery registration are still missing; the Windows modal
and physical provider/device/package acceptance gates also remain open in #636.

### Linux bounded setup acquisition alongside the existing receiver (#636, partial)

Linux now has the equivalent explicit collector and a separate native `BaumDienst`
setup slot. Its presence can admit genuine authenticated setup exports before a
normal controller exists, but never grants a source. It does not replace the
secure callback. Only its exact protocol reply is exclusive; exports can reach
already authorized workers, while result/status/terminal lanes never reach setup.
Service Stop cancels the owned acquisition outside the receive/tree lock.

The collector retains at most eight exports for two minutes. Candidate/frame/pin/
origin checks, duplicate invalidation, isolated conflict slots, current actual
saved contact choice and owned cancellation mirror the Windows boundary. Waiting
is a bounded event wait in a deferred native caller, not polling or a collector-
created thread/timer/listener. An independent optional native-selection guard is
kept separate from the durable consent guard: consent attachment cannot overwrite
acquisition checks. Closing acquisition invalidates old ephemeral choices; a
genuine committed source remains recoverable only through a fresh real export.

Twenty acquisition/isolation cases, the 18 setup-decision cases, FS1 identity and
tree opt-out regressions (57 cases together), and the 309 affected Notes cases pass.
The new helper is in the existing DEB/RPM/Flatpak/AppImage source manifests; manifest
and shell-syntax checks pass without building/installing packages. Windows inputs
are unchanged and prior Windows checks are retained. No Linux GTK dialog, actual
peer/acquisition UI ingress or startup registration is enabled yet. Installed
permissions/keyring, native GUI/provider/device and package acceptance remain open.

### Linux native candidate flow and GTK dialog adapter (#636, partial)

The Linux native-only candidate entry now connects the real GTK dialog source to
the same before-dialog decision flow. It requires the main thread, one prompt,
an unlocked/nonclosing native context and the same genuine store. It is not an IPC
factory or startup/acquisition registration. The dialog has no preselected contact,
defaults to Cancel and enables updates only after explicit selection. Native peer
ID/key, exact share/setup and local ID/UID are shown as sanitized literal text,
not markup or identity/name matching.

Chooser callbacks receive detached views outside book/private/tree gates. After
return, usable context, exact candidate/current origin, saved snapshot/primary and
native ID/UID are rechecked before the one-use initial/addition decision commits.
Cancellation, source/permission changes, a real save during selection, stopped
acquisition and display aliases cannot grant or replace an original implicitly.

Nineteen actual-flow/window-entry cases pass using synthetic native choosers and
real encrypted saves/FS1. Six additional cases execute the actual GTK adapter with
controlled widgets for Cancel, unselected Apply, explicit IDs, literal/bidi-safe
display and guaranteed dialog cleanup on error. No real GTK display is opened;
this is not installed GUI acceptance. Existing 309 Notes and 57 acquisition/
decision/identity/opt-out results are retained: comparison confirms that only new
native flow/dialog definitions were added and all previously tested module ASTs,
consent/return source inputs are unchanged. Actual peer/acquisition UI ingress,
existing-key session composition/startup recovery and installed/provider/device/
package acceptance remain open; production stays OFF/unadvertised.

### Linux read-only existing independent journal key (#636, partial)

The explicit native-root adapter reads only an already existing private
`telefon/storage.key` in its exact native 32-byte format. It never constructs
`PhoneStore`/`PhoneService`, looks up a keyring/consent/book key, repairs permissions
or creates a root, lock, identity, database or replacement secret. HKDF-SHA256 uses
a fixed Linux-specific journal domain, separate from raw phone storage and the
Windows journal domain. Missing material returns unavailable; unsafe or changing
material holds.

Descriptor-relative no-follow/nonblocking read checks private owner/mode, regular
single-link leaf and exact length. Two reads and final path/descriptor correlation
check root/leaf identity and key contents. Owned mutable raw buffers are cleared
on success/failure, descriptors are closed and the separate derived copy belongs
to its journal consumer. No renderer/imported path or default profile guessing is
accepted by the adapter.

Twenty-two owned-fixture cases pass, including independent derivation vectors,
raw-buffer cleanup, missing/unsafe/short/long/link/FIFO inputs, owner mismatches,
key/root changes during reading, descriptor closure and real existing physical
journal holds after loss/replacement. Existing Linux source manifests include the
helper and their syntax checks pass, without package builds/installation. The
backend is not registered or read against actual user keys. Native session/UI
composition and startup recovery, installed profile/permission and provider/
device/package acceptance remain open; prior unchanged platform evidence is kept.

### Linux joined native work/UI/numeric writer completion (#638)

Native Notes work no longer writes behind the renderer with a private string
SaveID. An explicit controller's worker offers an eight-second one-use native
lease. The actual DOM requires an idle save/editor/snapshot lane and matching
current AND previously saved JSON models (object-key order is insignificant,
arrays/values are not). Only Notes-basis metadata deltas or an unchanged bootstrap
are admitted. The exact native text then uses the ordinary numeric save IPC/queue;
unknown string SaveACKs remain ignored. Neither the UI comparison nor a token is
source permission or a saved witness.

A freshly reopened DOM may compare an unchanged bootstrap against its separately
retained exact loaded model, never a synthesized saved ACK. This baseline is
captured before normalization, cleared on init/restore, and cannot admit a normal
metadata save without a preceding real save. Unsent edits or normalization changes
fail the model comparison. Native source/primary/origin/owner/writer checks still
govern every mutation and the real writer must establish the saved witness.

Claiming requires exact native ownership/current text/payload and consumes the
lease once. Expiry, cancellation, lock or owner replacement holds only its memory
lane, without releasing physical request reservations. The existing worker tick
expires lost UI offers; no new thread/timer/startup registration is introduced.
Real completion and independent journal sealing run inside the serial book gate
before another save, without acquiring controller._work in reverse lock order.
Journal failure holds Notes but does not falsify an already successful user save.

Twenty-five native lease/completion/manifest cases and seven actual DOM/native
wire cases pass, including reopening, unchanged bootstrap, later and unsent edits,
unknown ACKs, invalid tokens/types/owners, revoke/Stop/expiry, journal failure and
the controller-work-lock inversion check. With actual joined original-contact
wire/result regressions, the final focused run passes 75 cases. The 309 affected
Notes regressions also pass; old native-worker fixtures now explicitly claim
numeric UI offers rather than expecting a behind-DOM string save. These are
bounded synthetic encrypted/FS1 fixtures, not GTK/installed/provider/device proof.
The original red reproduction showed metadata loss, NOT lost historical-query
availability or unauthorized provider writes. Windows product inputs are unchanged;
the fresh-loaded-model bootstrap detail is not claimed tested/fixed there.
Production registration and all #636 setup/installed/device/package gates remain.

### Durable native saved-ACK intent, no production sending (#628)

`NativeNotesAckIntents.seal_after_save()` now requires the actual pending
controller's confirmed private writer witness before persisting an encrypted
private intention. It uses a required existing independent journal-key accessor,
never a source-consent key, imported key or silently created replacement key.
The existing descriptor-relative private filesystem read/write/permission
primitives are reused without reusing consent storage or its authority API.
AES-GCM binds the private per-request identity; atomic write, exact readback and
file/directory durability precede the fresh native intent. Book/origin/mapping
callbacks run outside the private file lock and are rechecked after persistence.

A fresh `NativeNotesSavedAckIntent` can read draft `kontakt_original_saveack`
data only while its ciphertext and original confirmed pending/save context still
match. It contains the exact eight result-correlation fields plus the actual
desktop saved-payload hash. A conflicting outcome cannot overwrite an existing
request intent. Exact repeats preserve the existing ciphertext. Missing keys,
changed native saves, corrupted ciphertext, revocation and fabricated proofs
cannot produce a positive ACK. A failure after the durable write leaves readable
held history, not an inferred send success or reconstructed fresh grant.

`load_held()` deliberately returns history only, with no send or provider replay
authority. Reauthorization from a fresh repeated result and genuine private
mapping/primary and read-only terminal-status reconciliation are described above.
Generic Linux queue,
send and direct FS1 paths reject both an ACK art argument and a disguised ACK
body before any network call; no renderer/outbox route can send copied ACK JSON.
No dedicated negotiated native sender or Notes ACK receiver is enabled yet.

The changed Linux matrix passes 115 cases, including seven actual encrypted
writer/intent scenarios and six reserved generic-send denials; one subsequently
added actual post-durable-write revocation case passes separately. These counts
overlap previous matrices. Synthetic independent keys and isolated private files
are used; no installed journal key, original contact or real device is accessed.
The native Notes terminal phase is now implemented below. Native setup UI,
Windows controller, negotiated sending and package/device acceptance remain open.

### Notes authenticated desktop-ACK receive phase (#628)

The isolated native `Baumwerk` controller now admits the dedicated draft
`kontakt_original_saveack` only through actual FS1 origin and its existing native
receive transaction. Legacy/unproven calls reject it and the production
controller remains absent. Current source consent, setup/private mapping context,
exact verified native after-model and the complete eight result fields are
rechecked; a valid desktop saved-payload digest is required.

The existing encrypted VERIFIED record can then durably retain
`desktop_saved_sha256`. Repeated identical ACKs preserve its ciphertext;
conflicting correlation or a different desktop hash cannot replace it. Source
revocation, fabricated origins, mismatched types/fields and production dispatch
are negative cases. Legacy receipts remain readable and are not inferred to have
been desktop-saved. No provider write is authorized by this acknowledgement.

The affected host API28/API35 run passes 94 attempt, 46 controller and 28 native
origin cases. A subsequently added two-case actual receive pair-commit
interruption/restart test passes separately, giving 48 controller cases in the
retained composite evidence. It recovers an already durable ACK phase and retries
without another provider batch or changed receipt ciphertext.

That earlier phase alone deliberately did not install a mapping or release the
physical original slot. The controller now joins the crash-safe terminal phase
below; direct receipt acknowledgement alone still does not settle an attempt.
The overall negotiated counterpart sender and native setup remain unfinished.
A separate synthetic Linux sender-intent test and Notes receiver test are not a
physical or installed cross-device end-to-end acceptance claim.

### Native terminal history and exact next-map installation (#628)

The actual authenticated ACK controller now performs this ordered durable
sequence: retain desktop acknowledgement, write separate per-request prepared
history, CAS-install the **exact presealed next mapping ciphertext**, complete
the terminal history, then mark the physical slot released. There is no file
deletion. A released slot may be overwritten only by a new request UUID while
its matching independent terminal history remains available. Missing or damaged
history turns a released marker into a hold, never an empty default slot.

Only a private native `Abschluss` proof from acknowledged history authorizes map
installation. The encrypted next map must match the actual native after-model,
revision, canonical share, original, peer and setup decision. The installed map
may be the old quoted ciphertext or already the exact next ciphertext; a third
valid ciphertext is held rather than overwritten. A new native provider edit or
setup decision cannot be overwritten by an old prepared settlement. No new random
mapping hash is generated after desktop SaveACK, so the saved next basis stays
equal to the actual installed one.

Recovery after prepared-history write, map replacement, complete-history write
or released-marker replacement is idempotent and does not replay the provider.
Old UUIDs remain non-replayable after the physical slot is reused. A historical
identical ACK can be recognized without clearing a newer attempt or rolling its
map backwards. Historical ACK checking is read-only source/setup continuity,
not fresh permission to apply the old target. All native/provider callbacks stay
outside private file locks; actual receive work stays under the native writer
gate. Pinned original protections are retained, not silently deleted/unpinned.

The changed host API28/API35 matrix passes 94 attempt, 66 mapping/export and
68 controller cases. Two subsequently added cases check preservation of a third
valid map ciphertext. Controller evidence includes five injected durable phase
interruptions, actual receive pair-commit interruption, sequential requests with
historical ACKs, changed native data/setup, absent history and copied proof
rejection. The first run's two old damaged-slot tests differed only in exception
type; unreadable slots now retain the previous held error contract and the full
changed matrix was actually rerun. No invalid slot was treated as empty.

Linux's intent store still exposes loaded records only as held history; Windows'
confirmed-save witness does not itself settle a Notes physical attempt. Neither
is assumed to implement this Android-side terminal journal. Those counterpart
orchestrators, outstanding-outcome restoration beyond fresh-export private choice,
native UI,
negotiation and reserved native sending remain open. Production capability/UI
advertisement stays OFF; no installed/device acceptance is inferred.

| Counterpart | What the source establishes | What is still needed for this automatic path |
| --- | --- | --- |
| Notes Android | Authenticated full DTO; reviewed writer; resource19; new independent native original/decision/full-content core below | Join durable native approval, genuine setup and authenticated sender/receiver to the correlated durable result receipt; the new core is not advertised or automatically invoked |
| Stock KDE Connect / Android | Existing upstream read path | A genuinely supported counterpart write capability; do not invent a KDE write packet or use Notes capabilities for another peer |
| Akonadi | The actual helper re-fetches the requested collection/item, checks `CanChangeItem`, collection ownership and exact revision/UID, disables automatic conflict handling, and reads the modified item back. Python requests bind collection generation/instance and native item ID/revision | Connect these native identities/rights to distinct durable approval and protected automatic result-save admission; helper existence/discovery labels alone do not grant it |
| EDS | Existing `BookClient` connection and explicit ordinary modify/readback functions | Independently establish backend-specific guarded update semantics, current writable rights, exact source/revision and durable consent before adding automatic authority |

In particular, the current ordinary EDS `eds_kontakt_aendern` uses `_buch_flags()`
(`NONE` when available) and has a legacy signature fallback. It is **not** a proven
compare-and-swap adapter for this stricter automatic path. Upstream documents that
the default conflict mode keeps the local value, and that operation flags may be
ignored by unsupported backends. Merely passing `CONFLICT_FAIL`, observing an
address-book revision or checking a contact before writing cannot by itself prove
atomic backend CAS. This is an unfulfilled automatic-path requirement, not a
claim that every ordinary EDS synchronization has reproduced a data-loss bug.

Relevant upstream contract:

- [BookClient.modify_contact_sync](https://gnome.pages.gitlab.gnome.org/evolution-data-server/libebook/method.BookClient.modify_contact_sync.html)
- [BookOperationFlags](https://gnome.pages.gitlab.gnome.org/evolution-data-server/libebook-contacts/flags.BookOperationFlags.html)

No new blanket minimum dependency version, old-API downgrade, permission fallback
or installation follows from these differences. An unsupported source stays held
or read-only, without blocking separately supported approved sources.

## Required transaction and acceptance

1. A genuine native setup decision binds the confirmed peer and each exact native
   account/source identity to durable revocable authority. Imported settings,
   content mappings, capabilities and provider labels cannot mint it.
2. A committed/unrepaired native Organizer SaveACK identifies the exact current
   local book and pending full-field edit. A transient connection/credential wait
   preserves human intent without granting currently unavailable access.
3. Re-read the exact existing original and current native rights/revision. Refuse
   ambiguous aggregate/raw targets, changed account/source identity, missing
   baseline and unrepresentable fields. Never fall back to a default book, name
   matching, canonical UID substitution, create or delete.
4. Protect the actual original before the guarded provider operation. Preserve
   unrelated native rows and metadata, and assert revision at the actual mutation
   boundary, not just during preparation. Isolate contact/source conflicts.
5. Verify original identity and all written names/scalars/postal values by native
   readback. A transport ACK or cached DTO is not a save receipt. Hold uncertain
   outcomes for reconciliation instead of replaying an apply automatically.
6. Advance the local source baseline only through the existing actual encrypted
   writer and its exact confirmed result SaveACK. Preserve newer edits, all other
   book domains, Notes priority and clean-result no-loop behavior.
7. Exercise native sender/receiver and frontend/writer wiring separately for Linux,
   Windows and Notes, then label any later physical acceptance separately. Existing
   device/VM/install/publication pauses and conditional delivery remain effective.

## Current targeted evidence

`magnolie-organizer/pruefungen/test_phone_contact_values.py` adds 36 negative/positive
boundary cases: nine full-return-only fields are rejected at preparation, apply
and report validation, and at the actual native value RPC before transport. A
rejected widened apply leaves a genuine phone/email ticket usable. The affected
56-case matrix passes. This protects resource19's existing scope; it does **not**
implement the full return above. At that boundary-test checkpoint Notes inputs
had not changed and no Notes rebuild was warranted by those tests alone.

## Native Notes original/decision/content core (still not runtime activation)

The subsequent source work adds three independent native components:

- `KontaktOriginalBindung` can only be constructed by actual native observation.
  It pins the original raw/contact IDs, lookup key, account/type/data set, source
  ID, provider revision and database creation timestamp. It requires genuine
  READ/WRITE_CONTACTS access and explicit native writable flags. Unknown/busy
  providers, profile contacts, missing originals and ambiguous aggregates are
  held. Even an empty linked raw contact counts as ambiguous. Native assertions
  cover database generation, raw identity/revision/rights, lookup/profile status,
  exact aggregate membership and row rights in the eventual mutation batch.
- `KontaktOriginalFreigaben` is an **unconnected native decision core**, with an
  optional owned durable store as described below. Its exact-source/generation witness is
  checked independently before and after additional lifetime callbacks. Fake
  witnesses, another pinned peer, unoffered sources and stale/revoked decisions
  cannot authorize the writer. Cancel leaves the previous decision untouched;
  empty selection revokes it. A temporary peer wait retains intent and a fresh
  provider revision does not require another source decision. Default-OFF observes
  no peer. Returned mutable choice containers cannot expand the accepted selection.
- `KontaktOriginalInhalt` requires that typed native approval. It updates only
  names/raw N/FN, company, note, birthday, anniversary and modeled postal values.
  It preserves unchanged row IDs and native columns, including custom postal
  labels, PO boxes, company titles and unrelated event/application/phone/email
  rows. Ambiguous row pairing is held before protection; deleting a postal row
  containing unmodeled values is also held. Each actual attempt is consumed,
  including failed or uncertain outcomes. Protection precedes the single guarded
  provider batch; exact full readback is required, not a transport ACK. Operation
  count and actual Parcel size are bounded before protection, without splitting
  the transaction. A provider-issued lookup-key change can be read back only via
  the same native contact/raw/account/source/database identity, never a fallback.

The database generation uses `ProviderStatus.DATABASE_CREATION_TIMESTAMP`, an
API available since **26**, matching the unchanged `minSdk=26`. Missing support
holds this new path; it does not trigger an invented identity, new installation
or SDK downgrade. Supported APIs remain unchanged. Targeted host Robolectric
checks cover API28 and API35, not physical devices or minimum-API26 acceptance.

The initial new-core matrix contained 54 passing cases across those two API levels.
The affected existing reviewed-writer, provider/name, phone/email and resource19
regressions also passed (26 cases; unchanged inputs reused after the later core
edits). Synthetic providers/decision/protection callbacks are used throughout.
No actual installed app, AndroidKeyStore, real contacts or device is accessed.
These source changes now **do** change effective Notes inputs, but only targeted
host compilation/unit tests have run; no APK package, installation or delivery
is claimed.

### Protected native intent and typed restoration

`KontaktOriginalSchutz` now reuses the existing authenticated `DatenDateiKrypto`
format with a dedicated AndroidKeyStore key/domain, not phone/tree/book keys.
Construction creates nothing. Reads require an existing key; missing/temporarily
unavailable keys never cause regeneration, plaintext fallback, migration or a
prompt. Only explicit native setup rotates the consent key. Successful revoke
and subsequent setup invalidate old ciphertext; no password-derived verifier is
stored. Actual AndroidKeyStore behavior is still a separate native acceptance.

`KontaktOriginalDauerfreigaben` requires the live scope-minted setup witness before
and after persistence phases. The normal source scope is held during publication;
no runtime permission precedes confirmation. Its private encrypted state binds
the exact pinned peer and native database/account/data-set source identities.
Its private files use no-follow reads, bounded sizes, owner-only permissions,
cross-process file locking and the existing atomic-write/flush/directory-sync
pattern. Native peer/provider callbacks run outside the private file lock.

Additional native setup dependencies run before the owned durable source store
publishes a new approval, with context checks around them. Thus failed exact-
original setup cannot leave a fresh owner able to restore a new partial approval.
A previously accepted durable record remains unchanged if such an early dependency
fails; the failed current scope itself stays blocked. This ordering does not yet
implement the pending private canonical share/original mapping or its actual UI.

A persistent negative/pending marker is installed before changing keys/state and
precedes explicit key revocation. Publication uncertainty, including failure
immediately after pending-marker removal, is held instead of being acknowledged.
An unsuccessful explicit setup can require clarification; it never silently
repairs keys or claims success. This differs from ordinary temporary peer/key/
permission loss, which must preserve the accepted encrypted human intent.

When the scope owns this actual store, setup persists through that store before
grant publication, every writer guard independently checks its current typed
stored witness, and fresh-owner restoration accepts only a current witness from
that same native store object. No JSON or self-attesting replacement can supply
it. Volatile pause preserves persistent intent; explicit revoke is separate. A
failed durable revoke stays blocked in that process, including after Cancel or
pause, until a genuine new successful native setup. Repeated restoration of the
same unchanged record does not invalidate an in-flight grant.

The latest combined native original/decision/private-store/restore/write matrix
passes **98 cases on host Robolectric API28/API35**. It includes fresh-owner return
with no second human decision, old-cipher replay, source/key/peer waits, failed
publication/revoke, fake or foreign typed records, native callback lock boundaries
and strict canonical schema checks. Six dedicated protection cases and three
existing shared-cipher cases also pass; earlier native matrices overlap these
cases and must not be summed. Provider, decision, protection and keystore callbacks
remain controlled; no physical Android device or real contacts/keyring are used.

### Explicit canonical-share/native-original mapping

`einrichtenOriginale` can collect source choices and exact original choices in
one native setup decision. Each selected canonical share ID must belong to an
offered actual native observation and to a selected source; reconstructed offers,
unoffered native observations and mutated choice containers cannot add mappings.
The source-only setup API deliberately selects **no** original mappings. Portable
`KontaktSpur`/`baumKontakt` records may be suggestions for native review, never
authority to register or retarget an original automatically.

`KontaktOriginalZuordnungen` stores the exact canonical ID unchanged with native
database/raw/account/source identity, contact/lookup observation, revision and
before-content hash in private journal-key-encrypted files. It does not create
missing keys, read providers on missing-state lookup, or infer source permission.
A canonical share cannot silently move to another native original. The mapping
and owned source approval bind the **same native setup UUID**. Thus a partially
written mapping cannot be combined after restart with an older accepted source
approval. Ordinary restoration retains that UUID and needs no second decision.
After a failed setup, affected partial mappings may remain held for clarification;
no all-or-nothing multi-file rollback is claimed.

A fresh apply token now requires this current private mapping in addition to
native source permission and pinned protection. It pins mapping-file continuity
around lifetime callbacks, including after the provider revision advances. Loss
of that mapping prevents a positive result even if the provider already wrote.
The native reservation/verified receipt records the actual canonical share and
mapping-baseline hash. Legacy records without those fields remain readable as
history/negative holds, not newly reconstructed mapping permission.

The return must also quote the baseline observed by its sender. The apply API has
no default that fills the current native mapping hash behind the peer: a wrong or
older quote is rejected before reservation/provider mutation. That hash is a
revision quote, not consent. Genuine export and authenticated request/response
transport still need to deliver it and bind it to the actual pending request.

Host API28/API35 checks cover 28 mapping cases, 50 canonical-bound outcome cases,
104 source-core cases and 20 protection cases in the final changed-input run.
Canonical IDs retain the existing protocol's Unicode code-point limits without
renaming or truncation, including through verified-receipt persistence. The
matrices overlap earlier checkpoints.
That checkpoint was a native API boundary, not an installed automatic feature.
Native export, authenticated receive and terminal settlement have since been
joined as described above; combined setup UI, production negotiation/sending and
desktop restoration remain unconnected. No source change is handled by prompting again on
every run or by secretly registering imported mappings.

### Native basis refresh without another setup decision

`KontaktOriginalZuordnungen.aktualisieren` can refresh an already explicitly
selected original using its fresh native observation and restored source grant.
The exact original identity, peer pin, canonical ID and setup UUID must still
match. Missing mappings are never registered from imported metadata. Changed
observations require an advanced provider revision; unchanged observations keep
their exact existing encrypted record and quoted basis rather than churning it
on every export. Key loss, identity changes and unversioned/regressed changes
remain holds, not silent reapproval or new setup prompts.

Refresh is serialized with reservation through the actual private physical-
original ledger lock. Any existing unknown **or VERIFIED** attempt blocks it,
irrespective of request/peer/source metadata. Source/provider callbacks are
outside that private file lock. This deliberately does not release a verified
attempt before the authenticated actual desktop-save lifecycle exists.

Changed-input host checks cover 44 mapping/refresh cases and 54 attempt cases
(API28/API35); prior matrices overlap. This is a native refresh API, not yet
an actual authenticated export packet or a baseline-save acknowledgement. The
future sender must export the exact observed content with its quote, and must
not fill a return's stale quote from this refreshed native state.

`KontaktOriginalExport` now supplies that native observed-content boundary: a
private offer carries the exact canonical ID, refreshed quote, native revision
and an owned serialized snapshot of the observed contact together. Reading an
offer rechecks the actual source grant, mapping continuity and absence of a
physical attempt. A copied value cannot mint the private offer; returned list
containers cannot mutate its retained snapshot. After a native edit, an old
offer is held and a freshly captured offer contains both the new content and
new quote without another setup decision. This object is not yet a negotiated
wire envelope, queued send, desktop baseline SaveACK or permission to write.

The export extension covers 54 mapping/export and 54 attempt host cases across
API28/API35. One new container-isolation test initially assumed a nonempty raw
name list in its synthetic provider; only its fixture was corrected to include
an explicit synthetic phone row. The two affected cases then passed in a
targeted rerun; the other 106 passing cases were retained unchanged.

Native automation can resolve a selected canonical original through the private
mapping's raw ID, then capture and compare its current native database/account/
source identity. It does not depend on imported `KontaktSpur` IDs or a stale
lookup key after a local rename, and never searches by name or a default book.
The resulting observation still requires a live source grant and matching setup
UUID before refresh/export/apply; resolution alone grants no rights. Missing
private mappings do not read providers or create state. Replaced native identities
and ambiguous aggregates are held. The affected mapping/export/resolution matrix
now passes 62 API28/API35 host cases, including fresh-owner export after a native
rename with the canonical ID unchanged and no second setup decision.

### Pinned original protection and durable native outcomes

Controller admission can now use `vorbereitenGeplant` to validate the request
identity and quoted mapping basis, reject an existing physical hold, and run
the actual native field/scope, ambiguity and Parcel-budget planner **before**
invoking original protection or reserving a durable attempt. The planner is
shared with the eventual writer, not a second approximation of its rules.
Unchanged targets are rejected without creating a mutation attempt. Apply still
replans and performs the native assertions in the actual atomic provider batch;
preflight is not reusable write permission or a replacement for CAS.

The changed-input run passes 104 source/writer and 64 attempt host cases on
API28/API35. New admission cases exercise out-of-scope/invalid/unchanged content,
native scalar ambiguity, oversized Parcel, stale basis, failed protection and
an actual protected verified write. No authenticated full-return dispatcher is
enabled by adding this native controller entry point.

The automatic native postal planner explicitly supports `privat`, `arbeit` and
`sonstige`; unknown or empty requested kinds are rejected before protection and
reservation rather than silently written as `TYPE_OTHER` and rejected only by
readback (#630). The before-fix actual synthetic FS1/controller/provider cases
reached one unexpected batch for each unsupported kind on API28/API35. The
corrected 104 source/writer plus 36 controller cases pass, including supported
`sonstige` readback and an unrelated scalar edit preserving an unchanged custom
postal label, PO box and native unmodeled column. Generic transport/manual-review
DTOs are not restricted by this automatic writer limitation. Lossless editing of
additional custom postal kinds is not claimed as implemented.

The reviewed Linux DAV path writes an exact prepared vCard and checks native UID,
ETag and returned content; Windows DAV delegates vCard writing to `ExchangeCodec`,
not this Android enum fallback. No identical cross-platform fault was established
from those source paths, and no live-provider or wider EDS/Akonadi acceptance is
inferred. Their remaining authority/representation scope stays in #628.

`KontaktOriginalSicherungen` now writes and rereads an actual pinned contact-only
before-image through the existing snapshot store and AES-GCM journal cipher.
It checks native identity, complete row membership, exact portable content and
restore/Parcel budgets before encryption. Arbitrary application BLOBs without
supported restore typing are held; the existing photo BLOB codec is retained.
The private typed witness cannot be forged from a snapshot descriptor or retargeted
to another preparation. No app/notebook snapshot is read by this producer.

`KontaktOriginalVersuche` uses the existing **journal** key, never the revocable
source-consent key. Default missing-state reads create nothing; reads do not
regenerate unavailable keys. A durable hold is indexed by native database creation
stamp and raw-contact ID. Its authenticated contents additionally bind the peer,
account/source identity, request/hash, prior revision/content, target hash and
verified pinned protection. Changing request ID, peer, account/source identity or
provider revision cannot create an empty slot for the same unknown original.
Other native originals remain independent.

Only a fresh confirmed reservation mints a private one-use apply token. Reloaded
holds never authorize replay. The token consumes itself before validation, owns
a copy of the target and rechecks actual protection/history around external
lifetime callbacks. The native writer supplies its atomic identity/revision
assertions and exact readback. A second native readback and actual advanced
revision precede the atomic encrypted `verified` receipt and its reread. A typed
verified receipt can be loaded again without another provider write. If provider
write succeeds but receipt storage fails, the outcome stays held, not saved or
replayable. Revocation or failed exact readback cannot produce a positive receipt.

The earlier outcome checkpoint passed 36 API28/API35 host cases; its subsequent
canonical-bound extension is recorded above. The changed-input protection matrix
passes 20 cases and the durable source core passes 104; earlier
overlapping matrices are not additional cases. Software keystore/peer/provider
fixtures and private test files are used, not real contacts or installed apps.
Native receipts are **not** desktop baseline SaveACKs. Verified records still
block the next write until the separately authenticated terminal lifecycle above
has completed; receipt creation alone does not release them.

Next, connect genuine native setup, authenticated full receiver/sender and the
actual desktop baseline-save acknowledgement/reconciliation lifecycle.

### Provisional next basis bound to the actual verified provider result (#628)

New native VERIFIED records also retain an encrypted **provisional** next mapping
prepared only after actual provider readback and an advanced native revision.
It retains the same canonical original, peer/source/setup identity and carries
the exact resulting revision/content. The next basis hash is the hash of those
exact presealed bytes, stable when the verified record is reloaded. The current
mapping remains byte-for-byte unchanged and the physical attempt stays held.

This ordering lets a future desktop result save include the actual next basis
before issuing its authenticated SaveACK. Generating a different basis only
after that ACK would leave the desktop's saved baseline behind again. The terminal
phase above now installs those exact bytes after authenticated desktop ACK.
Unknown outcomes
cannot mint it; legacy VERIFIED records without it stay readable but do not gain
an invented next basis. Copied provisional objects, malformed Base64/hash pairs,
unmapped records and pending-map fields on an unknown hold are rejected.

The affected 72 API28/API35 attempt cases pass, including decrypting the actual
provisional map under its own mapping domain, checking exact native result and
unchanged installed map, restart-stable quote, legacy hold and malformed-history
rejection. Existing mapping/source/protection evidence is retained where its
behavior did not change. This earlier provisional-map checkpoint alone was not
an authenticated dispatcher or terminal-history release.

### Desktop confirmed-save evidence for the result lifecycle

The native outgoing-result boundary can now read a current or reloaded VERIFIED
receipt with the same request ID/hash, canonical ID, before/next basis, target
hash, native receipt ID and after-revision. It rechecks the actual native source
grant, same private mapping/source/setup context and exact current native result
on every read. The historical mapping check is explicitly read-only: its old
provider revision is not reinterpreted as fresh apply permission. Lost-result
re-emission does not invoke the provider writer again.

Revoked permission, a new setup decision, changed native after-state, legacy
missing-next-basis records or copied result objects cannot produce this outgoing
result. The affected 82 API28/API35 attempt cases pass. This remains native
result data, not an enabled negotiated wire frame or a desktop SaveACK. Native
receive correlation and terminal settlement are now implemented above; production
counterpart negotiation/sending and restoration remain open.

The existing Linux contact-result commit and Windows `ContactSourceSavedCommit`
now issue process-local saved witnesses only after their real native writer has
confirmed the exact proposed book, original book identity, advanced save sequence
and exact persisted hash. A copied `confirmed` result, renderer ACK, ordinary save,
another offer or reconstructed witness cannot supply that evidence. Consumers
must recheck the current saved generation and native lifetime immediately before
using it to construct an authenticated baseline acknowledgement. Later saves,
unsaved edits, unavailable books or revoked lifetime invalidate its usability.

Linux checks exercise the actual isolated plain/encrypted writer. Windows checks
exercise the actual generated `SaveAsync` body and encrypted atomic store, both
as managed host tests and with the existing bounded noninteractive Windows probe.
This is not the paused interactive Windows UI acceptance (#625), installation,
or full Notes result transport. No new bridge command or wire capability is
enabled by exposing this native-only evidence.
Do not opt the runtime into these APIs piecemeal and advertise complete automation.
The full #622 transaction, Linux/Windows sender wiring and independently verified
wider provider authority remain open; resource19 is still unchanged.
