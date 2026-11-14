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
This is still a native API boundary, not an installed automatic feature. Actual
combined setup UI, genuine native export/baseline advancement, authenticated full
request/result/desktop-SaveACK handling and safe terminal-history release remain
unconnected. In particular, no source change is handled by prompting again on
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
block the next write until that separately authenticated lifecycle is joined;
automatic release/reconciliation is deliberately not invented here.

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
after that ACK would leave the desktop's saved baseline behind again. No code
currently installs the provisional map or releases history. Unknown outcomes
cannot mint it; legacy VERIFIED records without it stay readable but do not gain
an invented next basis. Copied provisional objects, malformed Base64/hash pairs,
unmapped records and pending-map fields on an unknown hold are rejected.

The affected 72 API28/API35 attempt cases pass, including decrypting the actual
provisional map under its own mapping domain, checking exact native result and
unchanged installed map, restart-stable quote, legacy hold and malformed-history
rejection. Existing mapping/source/protection evidence is retained where its
behavior did not change. This is still not an authenticated result dispatcher,
actual desktop baseline SaveACK or terminal-history release.

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
result data, not an enabled negotiated wire frame or a desktop SaveACK. Real
transport correlation and crash-safe terminal-history settlement remain open.

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
