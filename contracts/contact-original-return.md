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
