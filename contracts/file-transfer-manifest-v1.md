# Device-file manifest and native resume ledger v1 (#329)

Status: **source groundwork, not a negotiated or advertised capability**.
The Python ledger and Python/Windows/Kotlin manifest implementations are not a
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

The native owner supplies the authenticated sender/receiver IDs and certificate
fingerprints, a permission epoch and a destination-owner token, all independent
of wire or checkpoint claims. Fingerprints/epoch/token are 64 lowercase hex
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

The initial ledger serializes its operations, does no I/O on import and does
not itself persist metadata, open peer stores, create a destination, select an
Android folder, announce capabilities or publish files. Native ownership-safe
storage, Windows/Kotlin ledger ports and negotiation, SAF opt-in, UI and
end-to-end recovery remain active work in #329. The three manifest validators
have matching shared UTF-8 hash-vector tests; bounded Windows source-host and
Kotlin unit tests are not physical-device acceptance.
