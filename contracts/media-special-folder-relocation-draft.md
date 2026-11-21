# Local special-folder relocation (draft, #429)

This is a prerequisite for moving existing files when changing **Animationen**
or **Eigene Aufnahmen**. The relative target planner does not read or move any
file. The current `keep_existing` choice changes routing only for future files;
the native entry point still rejects `move_existing`.

The Linux preparation store can persist one complete exact selection. It
binds the root and both parent chains, current local bytes and original
mapping fingerprints in the authenticated journal. Readback distinguishes
the two exclusive locations without traversing symlinks. The draft can append
a `moved` or `canceled` observation beside the immutable preparation after
flushing both held parents and checking their identities again. The private
Linux GIF primitive records a spent attempt before calling the native
no-replace rename, synchronizes the original file, and checks both endpoints
again before recording an outcome. It is not exposed through the product UI
and changes no stored mapping. Reopening never retries or finalizes a move by
itself. An independent sealed file in the native store pins the database
identity and each preparation or outcome revision, and is flushed before
committing the corresponding database change. A cut between those writes,
loss of only one store, or disagreement between the two is held for review.
No stale checkpoint can refresh itself from either side. This does not attest
against coordinated loss or rollback of both stores: the future product owner
must still bind the operation to the live saved book and hold any missing
selection there rather than creating a new one.

The private rename also takes the existing exclusive media activity lease
and checks the exact native saved-book revision before spending an attempt
and at later I/O boundaries. Changing the book, even to the same values,
does not renew the original operation.

First-time desktop media publication takes the shared side of that lease
before inspecting version-parent targets and holds it through the first
Saved output, including publication, receipts and the mapping write.
The live Saved retry, target observation, cache retirement, historical Saved
retry and original mapping-receipt repair now use the same shared lane. They
do not project a moved path or alter the historical receipt. A busy lane
stops the action before a new read, mapping write or Saved output.

The native no-replace syscall protects the target name. It does not atomically
compare the source inode. A conflicting non-cooperating writer can still
make the outcome uncertain; the draft neither deletes nor attempts a rollback
in such a case. Do not expose this as unconditional safe relocation in the
product. The native owner must coordinate other Organizer writers and all
path consumers; conflict handling and operation-wide acceptance remain open.

The read-only path projection needs the exact anchored `moved` outcome and
the unchanged protected mapping. It checks both names and their directories
again and returns the new location separately from the saved receipt. Later
edits to the moved inode can still be compared against the original digest;
the location check itself does not classify an edit or grant access. No
production reader uses this projection yet.

## Selection

- Begin with an authenticated saved receive job, its immutable manifest,
  accepted target and exact current mapping. Do not infer old grouping by
  stripping a prefix: a real album may be named `Animationen` or
  `Eigene Aufnahmen`.
- Bind independently verified media eligibility and old layout to the exact
  original. Missing evidence holds the affected file. A filename, suffix,
  camera album or camera model alone does not establish capture provenance.
  Do not adopt version copies, outgoing caches, trash or recovery payloads.
  For the initial Linux GIF subset, readback can require independently checked,
  complete multi-frame bytes and acceptance by the local GIF decoder. This is
  bound to the same bytes as the descriptor hash; a historical animation label
  is not a substitute. Other animation formats remain unverified.
- Bound the complete selection, and detect destination collisions, including
  case-folded equivalents and targets of members that are staying put. Never
  use a chain of moves to clear an occupied target. Only the user-confirmed
  selection may move. Declining keeps existing files and mappings in place.

## Native journal requirements

Before offering **Yes**, provide a protected local journal with one original
operation identity, one confirmed selection and no automatic renewal. Bind it
to the unlocked book, current preferences and destination identity. The
original saved receipt and transfer baseline must remain immutable.

For each member, open both original parent directories on the same volume
without following links. Bind the current file identity, size and content in
the existing source directory; preserve local edits rather than replacing them
with the historical saved hash. Journal the exact operation before the
no-replace rename. Verify the moved inode and current parent identities, sync
both parents, then append the new path proof without rewriting the original
receive record. No transfer, remote deletion or new Saved receipt follows
from a local rename.

On locking, withdrawal, conflict or uncertainty, stop. Recovery distinguishes
the original inode still at the source, the same inode exclusively at the
recorded destination, and an inconsistent state. Never treat absence alone
as proof, copy bytes into a replacement, or remove an unverified name. Keep
uncertain entries visible. Only remove a known, now-empty app-owned directory
after verifying its identity; a matching directory name is not ownership.

## Acceptance still required

Test both directions for each switch, both switches together, genuine albums
named after the special folders, unchanged and edited files, destination
occupation, withdrawal and process restart on each side of the rename. Verify
hashes, inode/metadata preservation and no re-upload for an otherwise unchanged
member. Native Windows/Notes behavior is not established by the Linux planner.
