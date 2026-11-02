# Device-file manifest and native resume ledger v1 (#329)

Status: **source groundwork, not a negotiated or advertised capability**.
The Python/Windows/Kotlin ledger and manifest implementations are not a
working Android photo-folder sync, Windows resume implementation or accepted
native transfer feature. There is no
new message handler, listener, grant default or automatic filesystem action.

This contract is separate from personal note/task/book transactions. Neither
a chunk witness nor a complete file digest is a Notes/Organizer SaveACK or
permission to publish destination files. Native final publication must use the
existing fresh-authority/no-overwrite gate, not just a persisted ledger.

## Immutable manifest

The exact object fields are `format`, `transfer_id`, `source_id`, `sender_id`,
`receiver_id`, `chunk_bytes`, `total_bytes`, `files`. Version is integer `1`;
chunk size is integer `65536`. IDs for the transfer/source snapshot and each
file are 32 lowercase hex digits. Sender/receiver identifiers are distinct
16–160 character ASCII letters/digits/underscore/hyphen strings and must match
the actual authenticated peers; a wire identifier alone proves no identity.

`files` is an ordered immutable list of 1–128 exact objects `{id,path,size,sha256}`.
Each file is at most 50 MiB, the total at most 400 MiB; total is the exact sum.
Sizes are integers (not booleans, strings, decimals or exponent forms). SHA-256
is lowercase 64-character hex. A changed sender/receiver, source snapshot,
member list/order/path/size/digest or transfer ID changes the manifest witness.
No late file may extend a previously accepted manifest.

Paths are relative slash-separated NFC text, no empty/dot/dot-dot components,
at most 16 components, 1024 Unicode characters/4096 UTF-8 bytes overall and
255 UTF-16 code units per component. Windows reserved names, trailing dot/space,
alternate-stream/path characters and Unicode category-C characters are rejected.
Duplicate IDs, Unicode-casefold-equivalent paths and file/parent-directory
collisions are rejected conservatively. Native destination planning must still
check the actual target filesystem, choose collision-safe paths and prevent
symlink/reparse traversal. A manifest path is not an OS path or a destination
grant. Platform ports must pass shared vectors before any negotiation is enabled.
Receivers may conservatively reject additional filesystem-equivalent names;
the Windows preflight also rejects invariant case/diacritic aliases rather than
risk binding two manifest members to the same target.

### Manifest SHA-256 framing

Start SHA-256 with ASCII `magnolie-file-manifest-v1` followed by one NUL byte.
A text field is a big-endian unsigned 32-bit UTF-8 byte length then its UTF-8
bytes, with no terminator. Append in order:

1. framed transfer ID, source ID, sender ID, receiver ID;
2. unsigned big-endian 32-bit chunk size, 32-bit file count, 64-bit total bytes;
3. for each file in order: framed ID, framed path, unsigned big-endian 64-bit
   size, then its 32 raw SHA-256 bytes.

The resulting digest is represented as lowercase hex. This framing does not
depend on JSON escaping, object-key ordering or a book canonicalization helper.
The accompanying vectors are synthetic and include a Unicode path.

## Complete offer-envelope preflight (not registered yet)

The Android and desktop preflights prepare kind `file_transfer.offer`, with exact body
`{version:1,manifest:<complete immutable manifest>,manifest_sha256:<fingerprint>}`
and the existing exact `TelefonNachrichten` application header. TTL is at most
60 seconds. The entire canonical UTF-8 application message must fit the unchanged
262144-byte application maximum; budgeting just the manifest/local frame is not
enough. Exactly the maximum fits, one byte more fails without splitting, trimming
or mutating the manifest. The encrypted transport retains its separate outer
frame bound. Native sender/receiver IDs and the full manifest fingerprint are
checked; none is permission inferred from the offer itself.

`IndexedPhotoSource.offerMessage` runs this preflight only under the current
sealed native index head and source lease. A returned message grants no enduring
send authority; actual send/receive handlers must recheck negotiated consent.
The kind is deliberately still rejected by the application dispatcher and is not
advertised. Linux `magnolie_file_offer` and Windows `DeviceFileOfferEnvelope`
check the same complete encoding and native peer bindings. The separate shared
`file-transfer-offer-v1-vectors.json` binds the existing Unicode manifest vector
to an exact complete canonical application byte count and SHA-256 on all three
platforms. Each platform tests exact maximum/+1-byte behavior independently.
Actual handler/acceptance integration remains pending; Windows source-host
checks are not native GUI/installed-package acceptance.

## Native binding and actual readback

The native owner supplies the authenticated sender/receiver IDs and identity
fingerprints (`sender_identity_sha256`, `receiver_identity_sha256`), a permission
epoch and a destination-owner token, all independent of wire or checkpoint
claims. For magnolie-phone/1 these are the already authenticated static public
key fingerprints, not invented TLS certificates. A separately negotiated TLS
transport would have to supply its genuine pinned identity. No new identity is
created by constructing a ledger. Fingerprints/epoch/token are 64 lowercase hex
characters. The native current-binding callback must also enforce live consent,
source/owner validity and deadline; a persisted binding is never authority.
Reconnection may keep a ledger only when this exact binding and the manifest
remain valid. Revocation/changed peer, source or destination requires new consent.

Chunks use explicit member ID and integer chunk index, with exact expected byte
length including the final partial chunk. The native staging writer must durably
finish an owned bounded write, and the reader must return bytes from that same
owned staging file. Missing files must raise, not look like an empty file.
The ledger retains a chunk proof only after actual byte readback and fresh
binding checks. Duplicate chunks must match both the prior witness and actual
bytes; they are not written again. Progress is the sum of verified chunk sizes,
not the advertised total or a checkpoint counter.

An exact checkpoint carries version, manifest witness, binding and bounded
member/index/SHA claims. Restoring it revalidates the native binding and reads
every claimed chunk again. Duplicate, missing, malformed, changed or corrupt
claims cannot create a resumable proof. Before a file can be considered verified,
all chunk witnesses and the complete file SHA-256 plus exact EOF are checked
again. Final zero-byte files also require a real owned read/EOF observation.
This result is a verified staged member, **not** a saved destination receipt.

The ledger implementations serialize their operations, do no I/O on import and do
not itself persist metadata, open peer stores, create a destination, select an
Android folder, announce capabilities or publish files. Native ownership-safe
storage and negotiation, SAF opt-in, UI and end-to-end recovery remain active
work in #329. The three implementations have matching shared UTF-8 manifest and
checkpoint-vector tests plus actual owned-staging readback tests. Bounded
Windows source-host and Kotlin unit tests are not physical-device acceptance.

## Linux protected staging groundwork

`EncryptedTransferStage` connects the Python ledger to directory-descriptor-
bound private storage. The native coordinator must supply the accepted manifest,
fresh native binding, a private parent and existing local AEAD protection
callbacks. It never creates a personal identity/key store or chooses a public
destination. Only opaque owner/member/chunk identifiers become filesystem names;
sender-supplied relative paths do not.

The root/entry ownership, permissions, directory identities, regular-file type,
link count and bounds are checked. Reads/writes use no-follow directory-relative
operations. Ciphertexts are bound to owner, manifest, native binding and entry.
A durable chunk is read back and authenticated before the ledger retains a
proof. Existing conflicting or later changed entries are not overwritten or
adopted as a new baseline. Unknown files make cleanup fail before deleting any
adopted files; no recursive deletion or wrong-key reset is used.

Checkpoints are immutable encrypted versions, never blind replacements of a
concurrently changed head. At most eight checkpoint versions are retained by
this primitive. Closing releases descriptors without discarding resumable data.
A synthetic fresh-process test opens an actual encrypted checkpoint and checks
actual chunk bytes again, without sharing an in-memory proof ledger. Missing
owned zero-byte markers are not treated as successful empty files.

`commit_checkpoint` connects immutable versions to native durable-index
callbacks. The head must actually commit and read back before noncurrent
versions can be retired under the same native head/scope gate. A failed write,
post-commit acknowledgement failure, no-op gate or concurrent head/permission
change cannot manufacture retirement. A committed head with a later retirement
failure is distinguished from an uncommitted write; changed original witnesses
are preserved with cleanup pending. The explicit recovery path can retire
noncurrent versions without creating another version when bounded slots filled
during earlier failed attempts. A real encrypted SQLite fixture verifies these
boundaries and preserves unrelated rows; it is not the application's job index.

This is not yet an integrated native job coordinator: its protected index,
retired-context quota and restart cleanup after revoked grants still need
integration. Protected Windows/Android staging adapters, protocol handlers, SAF source consent and
end-to-end/native acceptance also remain open. No capability is advertised by
these classes, and no user data or installed test package is changed by their
source tests.

The Notes protection primitive for new transfer state reads only the existing
phone-storage key. Missing/unavailable keys fail without generating a replacement,
deleting keys, constructing a personal phone store or migrating settings.
AEAD entries are bound to the native context and bounded before key lookup.
This separate primitive leaves existing general phone-storage behavior unchanged;
it still needs to be connected to the protected Android staging/source policy.

## Android photo-source consent groundwork

Dedicated gallery policy persists in encrypted, bounded rows of the private
source-job database, separate from personal/book settings and Android permissions.
It binds immutable native receiver identity, local policy epoch, enabled categories
and explicit enable state; neither stored enablement nor a desktop command proves
OS READ/WRITE access. Native ciphertext CAS prevents simultaneous source edits
from overwriting each other. An encrypted before/wanted-version repair fence is
durable before publication, with actual SQL/readback/native-permission checks;
uncertain clear acknowledgements re-establish that same fence, not a policy reset.
Explicit repair can keep only the actually observed authenticated before/wanted
state. Unknown concurrent policy/fence states remain preserved and blocked.
The native controller also remains fenced after uncertainty until recreated;
disabling never revokes app-wide Android rights. Eight policy/provider-store
cases and 18 affected source-index cases passed. This is not yet an active remote
settings handler or automatic scan. Policy-backed gallery authority now also
passes the combined native reservation/freeze/publish/restore/offer/disable/cache-
retirement path. A nested protected-policy read reuses only the same thread's
already-held OS lock for the exact private index root; it still rechecks root,
database and sidecar witnesses. Other threads/roots cannot reuse that lock. This
avoids incorrectly rejecting a valid source on an overlapping FileChannel lock.
The combined and affected index suite passes 28 cases; an earlier focused
integration failure remains recorded, not relabeled as a successful run.

`PhotoFolderScope` captures a native picker ticket before an explicit system
tree selection. The result cannot migrate to another peer, key, native lifecycle
owner or transfer-permission epoch. Selecting a source creates an off preference;
enabling is a separate explicit action requiring a ready, paired own receiver,
both relevant grants, the negotiated manifest version and persisted read access.
Leases bind the exact dedicated source preference/version, receiver and observed
read-grant stamp. Ordinary book saves do not change that dedicated source state.
Pending pickers, repair fences, revoked rights and stale owners prevent use.

`AndroidReadOnlyPhotoTrees` accepts canonical content-tree URIs only and requests
persistable READ, never WRITE. It does not release app-wide Android permissions
when a source changes or is disabled; those rights may belong to backup/import
features too. A missing READ grant is not a gallery/default-folder fallback.
The adapter's resolver tests use a synthetic Robolectric application and grants,
not a physical user's system picker or personal provider.

`ProtectedPhotoFolderPreferences` implements the dedicated source store using
existing-key AEAD protection, a native process/file publication gate, exact
ciphertext versions and actual readback. It requires an existing private native
directory, not a SAF or peer-supplied path. Before replacing source state it
durably creates an encrypted repair fence preserving both the before and wanted
ciphertexts. Missing state alone means off; malformed state/fences and missing
keys never become defaults. Failed/uncertain changes remain fenced, including
after recreating the store. Concurrent bytes are not rolled back or accepted as
a new baseline.

Explicit native repair inspection accepts only the exact authenticated before
or wanted ciphertext. Acknowledgement rechecks the inspected state and fence
under the publication gate; unknown concurrent states and invalid fences stay
blocked and preserved. Repair does not choose a new source or enable permission
by itself. This storage boundary is not yet wired to the native picker/controller
or repair UI. Frozen source snapshots and transfer handlers also remain outstanding.
These source classes alone do not expose a photo-sync UI, scan photos, schedule
work, change existing permissions or advertise a feature.

`AndroidPhotoFolderInventory` supplies a separate, explicitly invoked read-only
metadata enumeration. It revalidates the native source lease and cancellation
around provider/cursor operations and verifies each document is a child of the
selected tree. Traversal is limited to 512 visited entries, 32 directories and
16 path components, with the manifest's image count/size/total bounds. Duplicate
IDs, cycles, portable path aliases, virtual documents, unknown sizes and invalid
metadata fail without returning a partial list. Ignored non-image entries still
consume the traversal budget; every opened cursor is closed on success/failure.

The immutable result is explicitly **advertised provider metadata**, not a
frozen source, file hash, offer, permission receipt or resumable identity. The
future native sender must still freeze actual bounded bytes into owned protected
storage, read them back and form the manifest from those actual bytes. Inventory
does not open file contents, mutate the provider, release grants or start itself.
Resolver/provider tests use synthetic documents, not personal photo folders or
physical SAF acceptance.

The inventory uses the API26+ bundle query form. API26–28 descendant checks
use the same read-only provider call as the
[Android 8 framework](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-8.0.0_r1/core/java/android/provider/DocumentsContract.java),
through public `ContentResolver.call`; the public resolver-based
`DocumentsContract.isChildDocument` convenience method is guarded to API29+.
There is no hidden-API reflection, path-prefix trust fallback or minimum-Android
version increase. Missing/invalid provider descendant results fail closed.

`AndroidGalleryAlbumDiscovery` is a second read-only metadata adapter for the
requested desktop-driven automatic sources. It does nothing before explicit
native activation or without actual Android photo-read permission. Queries are
targeted to enabled camera/messenger/screenshot/download categories, use bounded
keyset pages over the platform image index, and never crawl filesystem paths
or open image contents. Known modern WhatsApp received-image paths are matched
exactly (not sent-image or backup subfolders); ambiguous same-name legacy albums
require a choice on the desktop, not knowledge of technical Android paths.

The result retains its native policy activation/epoch and distinguishes full
image access from selected-only visibility. Neither an empty catalog nor full
permission plus album metadata proves any file deletion. Permission/source/
owner changes or malformed/unbounded pages discard the whole result. The media
read permissions are declared, but no startup permission request, new phone
settings screen, background discovery or automatic synchronization is started.
Gallery source leases bind exact native catalog membership, the active policy,
receiver ownership and permission epoch, actual read coverage, mounted volume and
its opaque MediaStore version (per-volume API29+). Legacy platforms without a
reliable volume namespace and selected-only visibility additionally bind a
runtime nonce: old runtime proofs cannot authorize restored source jobs. A source
lease never proves file deletion. `GalleryPhotoAccessController` owns a random
native access epoch and rotates it for permission operations, access-change
notifications and native background/resume transitions even if coarse OS flags
remain unchanged. Exact one-shot foreground prompt tickets bind policy, enabled
categories, receiver owner/key/permission epoch and a 120-second monotonic limit.
Results read actual OS permissions rather than trusting callback Booleans;
stale results never migrate to another source or revoke app-wide rights. No
remote packet supplies that authority. Its real activity lifecycle/permission
launcher and authenticated desktop-policy adapters are still to be connected;
this controller does not start UI or request permissions on construction.
`GalleryPhotoPermissionLauncher` provides the concrete AndroidX
`ComponentActivity`/`RequestMultiplePermissions` adapter and native lifecycle
hooks. Construction registers only; an explicit native foreground/UI-thread
request is required. Background requests fail as foreground-required rather than
launching an activity; old results after recreation/destruction cannot reconstruct
native tickets. Five actual AndroidX/Robolectric lifecycle/result-dispatch cases
pass without touching personal state. The adapter is not yet instantiated by
MainActivity or an authenticated desktop command; background notification-tap
handoff and physical OS-dialog acceptance remain outstanding. No phone settings
surface has been added.
`AndroidGalleryPhotoSource` now inventories only the selected native image album
using bounded keyset pages (32 rows, at most 128 images/400 MiB, 30-second scan
deadline). Every returned member must match its bucket, label and modern relative
path; pending/trashed rows, unsafe/colliding names, malformed metadata, excess
pages and order violations fail without a partial result. The opaque native
member witness includes row ID and insertion timestamp, not a content digest.
Actual cancellable READ-only PFD access rechecks membership/metadata around open
and scope around every read. It feeds the same encrypted, double-read/readback
snapshot and durable source-job index; cached restore does not reopen originals.
Synthetic provider tests cover API28/29/35, including actual framework permissions
and PFDs, not physical phone/gallery acceptance. No adapter writes/deletes images,
requests permissions or starts a worker. Desktop policy control, native OS
permission launchers and full inventory/receipt integration remain outstanding.

## Protected Android source snapshots

Private gallery-origin/source records passed 71 focused origin/compatibility/index/
workflow cases. The format-2 native snapshot record adds member-to-provider correlation
inside the existing authenticated index row, without changing chunk/manifest
AAD, wire manifests or cache-file layout. Format-1 snapshots must retain their
original byte/identity checks and expose no inferred origin mapping. Correlation
of row ID/insertion time is explicitly not a unique mutation identity, Android
permission, completed destination receipt or a bidirectional baseline; coarse
provider timestamps alone cannot prove that a deleted/reinserted row is the
same photo object.

The opaque correlation ID binds the native sender, album source key, actual
volume namespace and native member witness. Edits/renames/access refresh do not
rekey known-namespace members; unknown legacy namespaces retain runtime binding.
Restored origin entries must exactly match ordered manifest IDs and recompute
against the current native lease. Legacy format-1 records expose `null` origins,
never guessed IDs. The original chunk/manifest AAD and cache-file quota/layout
remain unchanged; private cleanup accepts both authenticated record formats.

On API30+, the actual MediaStore reader additionally requires typed nonnegative
`generation_added` and `generation_modified`, with modified generation at least
insertion generation. Insertion generation becomes part of the native member;
modification generation is a separate `nativeRevision` so cropping does not
rekey the photo correlation. Same-size/same-coarse-mtime modification is detected
through actual revision readback. Inner origin format 2 retains that revision;
old inner format 1 remains correlational with no manufactured generation proof.
Positive native insertion generation plus the actual known volume namespace
can expose an insertion witness, but `provesMutationIdentity` remains false:
ownership/WRITE consent/fresh content CAS and no-loss provider mutation are not
granted by metadata. Generation zero, legacy/unknown namespaces and malformed
provider values do not create insertion proof. The SAF reader explicitly rejects
a gallery revision instead of silently treating it as SAF-provider authority.

`NativeGalleryPhotoWorkflow` now joins the explicit native protected-policy,
ActivityResult permission lifecycle, targeted album discovery, bounded actual
image/PFD reads, durable reservation, encrypted freeze/publish, cached restore,
complete offer preflight and explicit retirement paths. Construction opens only
the supplied private source index; it does not start scans, prompts, workers or
network activity. Enabling categories never implies Android permission. Native
receiver identity/grants and existing local sender ID/key still come from the
future authenticated service coordinator, not from a wire request.

Workflow catalogs bind the actual native access epoch through every discovery
boundary. A catalog captured before resume/selected-access changes cannot later
authorize an album merely because coarse permission flags still match. Failed
builds hold their reservations and exact native cleanup handles; a copied/forged
failure ID cannot discard cache, and restart without partial original witnesses
remains repair-held. Source disable prevents offers but does not delete live
images. Thirteen image/workflow, eight discovery and seven scope cases pass,
including actual synthetic provider/PFD/Activity/SQLite integration. These are not
physical phone/end-to-end acceptance. MainActivity/service/PC-command instantiation,
dedicated file-grant negotiation, receiver handlers and Organizer-only controls
remain outstanding. Frozen manifests also do not yet carry durable per-photo
origin/receipt baselines for bidirectional edit/delete synchronization.

`PhotoSourceJobIndex.retireCachedSnapshot` can explicitly retire a previously
sealed private cache after a source is disabled, revoked or no longer resumable.
It first durably retires/CAS-checks the actual existing-key-authenticated index
head, then preflights all remaining original root/file identities, ciphertext
digests, private permissions, link counts, exact known names and budgets. It does
not restore source authority, expose manifest/chunk access or open live photos.
Unknown/changed entries are preserved before any unlink. An interrupted cleanup
can resume from the retired authenticated record after restart, accepting only
missing originals rather than adopting replacements. Quota remains reserved
until actual root absence, parent sync and index-row removal/readback. Partial
reservations lacking authenticated sealed witnesses still require separate
native repair and are not guessed or automatically deleted.

The protected snapshot/index pipeline consumes typed native source leases and
authorities. SAF leases remain actual canonical tree/grant observations; gallery
albums must use their own native source/access observations, never synthetic
tree URIs. The generic boundary retains the exact legacy SAF cryptographic
context, checked against its original fields, and does not grant a gallery
source access through the SAF reader.

`AndroidPhotoSourceReader` rechecks exact document identity/name/image metadata,
size/mtime and descendant status, then opens only a cancellable READ-only PFD.
Every source read is bracketed by native lease/cancellation checks. It does not
request WRITE permission, choose another folder or open personal stores.

`ProtectedPhotoSourceSnapshot` requires a newly reserved, empty private native
directory from the coordinator. It streams at most 64 KiB at a time into new
existing-key AEAD chunk files, fsyncs them and reads/authenticates actual bytes
back. A second bounded live-source read must have the same whole SHA and exact
EOF, with metadata revalidation between observations. Empty files still require
actual source opens/EOF plus an owned encrypted marker. The final immutable
manifest is exposed only after protected manifest readback and a final complete
private-byte hash check. Subsequent chunk reads use the frozen private copy,
not potentially changed live provider bytes.

CREATE_NEW operations never replace existing entries. Original inode/ciphertext
witnesses are retained, not rebased after a change. Failure returns a native
pending-cache handle rather than a completed manifest; explicit cleanup can
remove only exact adopted bytes, including after grant revocation/cancellation.
Unknown files/changed witnesses block cleanup before deletion. No recursive
provider or private-directory deletion is used by this primitive.

This is not yet the native reservation/job-index/quota/restart coordinator or
sender handler. A local metadata frame bound does not replace checking the
**complete actual encoded offer envelope** against the existing 262144-byte
application limit. No photo-sync capability, UI, background schedule or saved
destination receipt is activated by these source classes.

`PhotoSourceJobIndex` provides a dedicated native SQLite source index, not the
personal phone database. Existing-key AEAD protects each job/header, native
process/file gates and SQLite transactions serialize changes, and ciphertext
versions/CAS plus actual database reads distinguish committed heads from stale
caller state. It durably reserves and reads back quota **before** creating a
source directory. Reserved, sealed, uncertain and retired jobs all count toward
the eight-job / 400 MiB source-byte limits and bounded logical ciphertext budget.
Unindexed files/roots and invalid existing state are preserved and block new
reservations, rather than silently becoming empty storage.

Only actual verified snapshot objects can publish a sealed record. Retirement
commits before cleanup; quota is released only after actual root absence,
directory sync, row deletion and database readback. Failed/no-op cleanup or lost
post-commit acknowledgements retain the real job/head and quota for native retry.
Unrelated SQLite metadata is not discarded. Reopening index metadata alone is
not a successful frozen-byte restore. Partial-crash repair, active sender
coordination and application UI/handlers still need their concrete integration.

The native index can reconstruct a sealed private snapshot using authenticated
original directory/file identities, ciphertext witnesses and exact member names.
It revalidates the current semantic source permission context, owner plan,
protected manifest and **all actual private file hashes**. A newly ready native
lifecycle owner may obtain a fresh matching lease; stored object pointers never
grant authority. The indexed reader fences every manifest/chunk operation with
the actual current sealed database head/version and source lease before and
after IO. Retired heads block old reader objects even if cleanup failed. Unknown,
corrupt or newly out-of-scope state is preserved, not adopted as a new baseline.
This is reconstructed native storage, not yet an integrated restart/phone-service
acceptance or proof of an end-to-end transfer.

## Linux physical no-replace publication (not a durable saved receipt)

### Native protected checkpoint-head index

New native operations can now persist a `NativeAcceptedTransfer` in owner-record
context format 2: the complete ordered manifest, exact complete target mapping,
peer/permission/destination binding and original native destination/ancestor
inode witnesses. Capture checks the native binding and actual existing safe
destination; no folder or consent is created implicitly. Protected parsing is
metadata-only and does not touch or recreate an unavailable destination.
Legacy context-format-1 indices retain their original AAD/schema and expose
`accepted_transfer=None`, never an invented default destination or mapping.

On reopen, an authenticated format-2 owner record restores the full immutable
description without requiring live access. Head updates and guarded actions
must still revalidate the native binding and original destination identity.
The publisher can bind to this exact restored description; changed roots,
destination paths, mappings or bindings are rejected before a publication cache
is created. Stored consent metadata grants **no write authority** and is **not
a saved receipt**. The existing-key adapter supports its bounded 2 MiB owner
record; ordinary checkpoint-head records retain their separate small bound.

The 31 acceptance cases plus affected checkpoint/key-integration/publisher/
journal/recovery tests pass together (132 cases). They cover a complete
128-member Unicode mapping, immutable roundtrips, native root/ancestor changes,
partial/reordered/aliased mappings, unavailable destinations and legacy no-default
reopen, followed by actual restored-index → publisher → journal readback. This
does not add a global discovery/quota catalog, durable receipt heads, handlers,
Organizer controls or native end-to-end acceptance.

`ProtectedTransferJobIndex` is now an actual per-operation private SQLite head
index, rather than the synthetic test index previously used by staging tests.
Creation is explicit and exclusive under a separately reserved native owner.
Reopen never creates a replacement database/schema or key. The protected owner
record binds the manifest fingerprint, native peer/permission/destination-token
binding and original root/database/lock inode identities. Head records are
immutable encrypted rows with bounded revisions and a predecessor-ciphertext
hash chain. Original schema, DELETE journaling and FULL synchronous mode are
checked, not silently weakened or migrated.

Native CAS serializes head updates across index instances using a shared
in-process root gate and OS file lock. Same-thread nested inspection reuses the
root lock without releasing an outer guard; mutation during a guarded retirement
action is rejected. Real `EncryptedTransferStage.commit_checkpoint` can use
`publish_head`, `read_head` and `guard_head` directly through a native captured
expected-head callback. A failed post-commit readback fences later updates in
that instance. Reopening only restores an authenticated checkpoint pointer:
the stage must independently re-read every claimed chunk. Local head inspection
can work after permission revocation; mutation/retirement still requires the
current native binding. No head is a saved destination receipt or SaveACK.

Unknown entries, copied/changed original files, missing databases, invalid
ciphertext/schema, live observed head rollback and leftover SQLite sidecars are
preserved as failures. A leftover journal is held for explicit repair before
opening SQLite, not guessed to be an owned crash journal and automatically
deleted/recovered. Cross-restart external snapshot rollback protection and an
explicit journal-repair procedure remain open. The index bounds history to 128
head revisions and its database to 4 MiB; it is not yet a global job/quota index.

Twenty focused tests pass: 19 SQLite/index cases plus the actual existing-key
adapter → stage → durable head → reopen integration. They cover one CAS winner
across two native instances, nested cross-instance inspection, actual old-stage
checkpoint retirement, separate-process inspection, revoke/corrupt/identity
failures, uncertain readback, sidecar preservation and rejected durability
weakening. Global accepted-job discovery, publication/receipt heads,
recovery ownership, quota/retirement, common baselines and actual
application handlers/controls still require integration. This is not native
end-to-end photo synchronization acceptance.

### Existing native key access without personal-store construction

`ExistingFileTransferProtection` reads only an already present native telephone
directory's `storage.key`. It never constructs `PhoneStore`, whose ordinary
initialization may create keys/defaults, change identities or perform cleanup.
The adapter does not create, chmod, replace or migrate any existing directory,
key, identity, pairing, settings or database. Missing/corrupt/linked/non-private
keys fail closed. Every seal/unseal rechecks the original directory/key inode
and key bytes before and after AES-GCM. A detected root/key change fences that
instance, even if old bytes later return; a native reopen is required.

Transfer protection uses the separately length-framed
`magnolie-file-transfer-protection-v1` AAD domain, not personal-store object AAD.
The only generated randomness is a per-record nonce, never a storage key.
There is no permission or destination authority in this adapter. Its 22 focused
tests include actual stage checkpoint restore and publication-journal reopen,
empty/chunk-size payloads, exact AAD framing, missing/corrupt/linked keys, root
swaps/modes, mid-crypto rotation and unchanged opaque personal-file sentinels.
Actual application-controller wiring and the protected PC job index remain
required; merely constructing this adapter does not activate any transfer.

### Descriptor-bound physical publication

`magnolie_file_publish.NativeFilePublisher` now has 35 focused real-filesystem
tests with the existing AES-GCM stage and resume ledger. A native accepted
operation supplies an immutable complete target mapping, current transfer
binding, serialized publication gate and a separately reserved private owner.
Construction never adopts an existing publication directory. Destination and
parent directory descriptors, original inode witnesses, bounded alias checks,
full staged/temp/destination byte readback and exclusive destination linking
protect this primitive's no-replace boundary. Linux publication links the held
source descriptor through `/proc/self/fd`, without a source-path fallback.
Full-file hashing stays outside the native permission gate. Equal existing
files, aliases, linked parents, unknown cache entries and changed witnesses are
not adopted, overwritten or blindly deleted.

After an actual link, failures retain an uncertain state in this native instance;
retries cannot silently choose another filename or report a new save. Explicit
cache cleanup can operate after permission revocation using original local
witnesses, including successfully written partial/empty temporary files, but
never removes a destination photo. Closing only releases descriptors.

The returned `NativePublishedFile` is **physical readback evidence only**:
`is_saved_receipt=false` and `grants_write_authority=false`. The current
implementation still has no protected PC job/receipt index, restart
adoption/repair, shared photo baseline or transfer ACK integration. Those are
required before actual transport/UI use. Its optional protected publication
journal is described below. Tests cover
Unicode/nested/empty/multichunk saves, duplicate calls, immutable mapping,
existing/concurrently created targets, aliases/symlinks, permission gates,
revocation, path swaps, post-link fsync/readback failures and conservative
partial-cache cleanup. They do not constitute physical phone or end-to-end sync
acceptance; no handler, capability or automatic background work is enabled.

### Protected publication journal and restart inspection

`ProtectedPublicationJournal` records immutable, individually fsynced and
AEAD-read-back `prepared` → `linked` → `verified` phases. It uses native existing
protection callbacks only and creates no replacement key or personal settings.
An authenticated owner header binds the entire target mapping, manifest,
peer/permission/destination binding and reserved native owner. Protected records
bind their original directory/file identities; each phase binds the previous
ciphertext SHA and the same original source inode and target-parent chain.
There is no replace/update/delete API. Unknown entries, changed identities,
corrupt ciphertext, phase gaps and incomplete writes are held, not reset.
An uncertain append fences further writes in that instance.

The publisher can attach an exact, fresh native journal before starting. It
durably records `prepared` before the no-replace link, `linked` after the actual
link/destination-directory fsync and `verified` after destination byte readback.
All journal encryption, filesystem I/O and readback remain outside the native
publication permission gate. Journal failures before linking prevent publication;
failures after linking retain the existing uncertain-publication barrier.

Restart inspection is **read-only**, needs no live source or destination access
and grants no resumed operation. In particular, a missing `linked`/`verified`
record never proves that no link happened; restart cannot simply adopt a cache,
rewrite a record or repeat publication. The journal by itself provides no
external monotonic-head/rollback protection or current destination observation.
Even `verified` evidence remains **not a saved receipt**, common baseline or
transport ACK. The protected PC job/receipt index, native destination recovery
and exact operation ownership must still be integrated before actual handlers.

The combined 66 real-filesystem tests cover 31 journal/integration cases and
the 35 publication cases. The authenticated original owner header is re-read
before each inspection/append, not trusted from construction alone. They include separate-process inspection with an
ephemeral fixture key, scope/key/mapping mismatches, copied/linked/tampered
records, original-root changes, failed seal/write/fsync/readback, actual
publisher ordering and journal faults on both sides of the real link. This is
not power-loss, physical-phone or native end-to-end acceptance.

### Read-only native destination recovery observations

`inspect_publication_destination` authenticates the exact journal context and
re-reads the actual original target inode/parent chain and complete bytes after
restart. It does not reopen the source/cache, create directories, modify the
journal, adopt files, retry a link, or delete anything. Both an original linked
file still sharing the private cache inode and an original file after explicit
cache cleanup can be observed. Native live binding is checked before and after
observation; revocation cannot return a stale success.

The result distinguishes `original_present`, `unconfirmed_absence`,
`conflict_preserved` and `no_record`. Missing roots/parents/targets and incomplete
journal phases never prove deletion or permit republishing. Equal bytes in a
different inode, changed content, swapped parents, symlinks and unexpected hard
links are preserved as conflicts. Even an original target observed against a
`verified` journal remains **not a saved receipt or write authority**. Durable
PC receipt/head integration, recovery ownership and common-baseline acceptance
still need implementation.

Fifteen recovery tests, the 31 journal/integration cases and 35 publisher cases
pass (81 cases across the focused runs). They include original target reads
after source cleanup, both sides of interrupted journal transitions, independent
cache cleanup, missing/changed targets and native revocation during readback.

## Three-way photo comparison proposals (not execution authority)

Linux `magnolie_photo_plan` and Windows `PhotoSyncPlan` compare immutable native
content observations against an authenticated-receipt baseline association.
The association binds native peer identities, transfer binding, source epoch,
photo correlation and target-mapping token; a changed scope pauses rather than
reinterpreting the old baseline. Same-content convergence is distinct from a
simultaneous binary edit. Edit/edit and edit/delete remain conflicts. One-way
mode retains local PC edits and local tombstones instead of copying unchanged
phone bytes back over them. Unknown/unconfirmed absence is never deletion, and
an equal unmanaged target is not silently adopted as a managed photo.

Both deletion directions default off. Reverse writes/deletions and native
desktop create/replace/trash support are not inferred from user toggles; native
support defaults unavailable. Weak source insertion identity cannot authorize
an automatic replacement proposal. Every result explicitly grants **no write
authority** and is **not a saved receipt or accepted new baseline**. Native
execution still needs fresh consent/identity/ownership/content CAS, no-loss
publication and actual readback. There is no apply function or I/O here.

The shared `photo-sync-plan-v1-vectors.json` contains 26 synthetic cases; Linux's
29-case suite and the Windows source-host group pass. These are proposal-only
tests, not file operations or physical synchronization. In particular, the
current gallery adapter does not produce authoritative deletion observations;
a native deletion state cannot be manufactured from an invisible album,
partial scan, Android READ flag or merely a missing row. Durable common-receipt
storage, mutation/publication adapters, handlers and UI remain open.

## User-required photo sync policy (open integration criteria)

The verified groundwork is archived in #329. The still-open native integration,
durable destination/receipt ownership, Organizer controls and end-to-end
acceptance continue in #330. Archiving the groundwork is not completion of
photo synchronization or permission to deliver/publish a new package.

All additional configuration belongs **only in Organizer → KDE Connect →
Advanced functions**, grouped in expandable sections. Detailed photo options
should appear only when photo synchronization is enabled. There are no additional
photo setting panels or switches in Notes or KDE Connect on the phone. Native
phone policy/controllers remain internal and are driven through authenticated
own-computer control. Android's genuinely required media-access or mutation
confirmation dialogs remain necessary; they cannot be accepted remotely or
pretended to be granted. The desktop must display pending/unsupported permissions
and actual support status. Placement under KDE Connect does not turn a KDE
device ID/name into a Magnolie identity or grant.

Photo synchronization must offer **Automatic** or **Manual**, plus **Sync now**,
in this same Organizer-only section. The conservative initial mode is Manual;
pairing, OS gallery permission or source selection alone must not start a new
background job. Automatic operation requires explicit activation and fresh
authenticated source/destination consent. Manual starts obey exactly the same
permission, identity, conflict and deletion safeguards. A running job is not
duplicated by Sync now: show its progress or coalesce a later request. Changing
Automatic to Manual stops scheduled repeats without resetting accepted members,
receipts, baselines or Android rights. Offline/revocation/lock/source changes
pause rather than prove deletions. Scheduler/UI/native automatic acceptance
remain open integration work, not an already active background service.

The Linux/Windows `PhotoSyncSchedule` groundwork now implements this run-state
boundary without creating timers, threads, stores or scans. It starts Manual,
requires an explicit mode change for automatic due checks, coalesces change
hints, and returns the same active native run for Sync now. Active ownership is
released only by the exact actual worker-end handle, not by a cancellation
request, copied handle or transport ACK. Peer/key/permission/source/destination/
native-owner changes request cancellation while retaining ownership until the
worker ends. Switching back to Manual removes repeats without modifying any
transfer binding or receipt. Close requests cancellation but does not pretend a
worker already stopped. Monotonic deadlines are not silently rebased on clock
rollback. Seven Linux tests and the Windows source-host group pass. Protected
PC preference persistence, real event-loop/worker adapters, controls and native
automatic-sync acceptance still need integration; no background sync was enabled.

The requested default desktop destination is the native **Pictures** folder
with a safely generated `<phone-name>-Fotos` child, with an optional different
user-selected destination. A device display name is not a trusted filesystem
path or publication grant. Native path planning/consent/no-overwrite and fixed
destination retry rules still apply.

Source selection must distinguish camera images from optional additional image
sources (for example received WhatsApp images, screenshots or downloads) through
simple enabled source categories and accessible gallery-album discovery. After
explicit activation, known messenger albums should be detected automatically
where Android permits, without requiring users to know technical folder paths.
Manual folder selection is a fallback for OS access limits or ambiguous albums.
This does not mean JPEG/EXIF guesses, unrequested activation or an unrestricted
filesystem crawl. Limited Android photo selection or lost album visibility is
not a complete inventory and must never prove deletion. Recursion scope must be visible, including
whether sent-image subfolders are included. Multiple sources need independent
source identities/epochs and collision-safe persistent destination mappings.
Changing source selection is not a file deletion; excluded sources must not
trigger deletion cascades or reinterpret a prior baseline as an empty inventory.

Content changes such as cropping should be synchronized, preferably both ways.
A clearly identified phone-to-desktop-only mode is acceptable when the provider
cannot support safe reverse writes. Deletion propagation must be independently
switchable per direction and initially off. Phone writes/deletions require
separate explicit Android WRITE and module consent/provider support; the
existing READ-only adapter does not silently gain mutation methods.

Mutation planning needs proven last-common content/destination associations and
fresh readbacks. A simultaneous binary edit or edit-versus-delete is a conflict,
not permission to overwrite/remove the other side. Only previously confirmed
managed members can become deletion candidates, after complete successful
inventory observations. Permission loss, partial/failed scans, changed scope,
unknown files and new destination contents never prove a deletion. These are
requirements, **not a claim that policy UI, bidirectional writes, deletion
propagation or per-photo inventory receipts are already implemented**.
