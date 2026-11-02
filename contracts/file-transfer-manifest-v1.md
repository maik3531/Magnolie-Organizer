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
Concrete gallery-item source leases/readers, desktop policy control, native OS
permission launchers and full inventory/receipt integration remain outstanding.

## Protected Android source snapshots

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

## User-required photo sync policy (open integration criteria)

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
