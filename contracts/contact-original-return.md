# Full original-contact return: open implementation scope (#622)

This is a source-boundary assessment, not an implemented capability or a source
grant. The completed DAV lifecycle work in #621/#623/#624 does not complete this
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

### Pinned original protection and durable native outcomes

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

The newest outcome matrix passes 36 API28/API35 host cases. The changed-input
protection matrix passes 20 cases and the durable source core passes 98; earlier
overlapping matrices are not additional cases. Software keystore/peer/provider
fixtures and private test files are used, not real contacts or installed apps.
Native receipts are **not** desktop baseline SaveACKs. Verified records still
block the next write until that separately authenticated lifecycle is joined;
automatic release/reconciliation is deliberately not invented here.

Next, connect genuine native setup, authenticated full receiver/sender and the
actual desktop baseline-save acknowledgement/reconciliation lifecycle.

### Desktop confirmed-save evidence for the result lifecycle

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
