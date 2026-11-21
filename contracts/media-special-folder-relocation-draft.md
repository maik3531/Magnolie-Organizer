# Local special-folder relocation (draft, #429)

This is a prerequisite for moving existing files when changing **Animationen**
or **Eigene Aufnahmen**. The relative target planner does not read or move any
file. The current `keep_existing` choice changes routing only for future files;
the native entry point still rejects `move_existing`.

The Linux preparation store can persist one complete exact selection. It
binds the root and both parent chains, current local bytes and original
mapping fingerprints in the authenticated journal. The journal only records
`prepared`: it does not perform or complete a rename. Readback distinguishes
the two exclusive locations without traversing symlinks. Reopening the draft
does not retry or finalize a move. Before calling it from the product, the
native owner must bind the prepared journal identity to the saved operation
so replacing or losing the entire store cannot admit a new preparation.

## Selection

- Begin with an authenticated saved receive job, its immutable manifest,
  accepted target and exact current mapping. Do not infer old grouping by
  stripping a prefix: a real album may be named `Animationen` or
  `Eigene Aufnahmen`.
- Bind independently verified media eligibility and old layout to the exact
  original. Missing evidence holds the affected file. A filename, suffix,
  camera album or camera model alone does not establish capture provenance.
  Do not adopt version copies, outgoing caches, trash or recovery payloads.
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
