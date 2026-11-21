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
The pre-download review also takes the shared lane before comparing an old
target, and a media resume takes it before reopening the original stage.
Neither can turn a busy lane into missing-file evidence or an acceptance.
Preparing or moving a trash entry, canceling, restoring and explicitly
purging also use the shared lane. It needs the existing local phone DB inode,
not an active connection, a SQLite session or current pairing. A read-only
trash listing still does not acquire the lane. Expiry already has its own
exclusive retention permit and is not admitted through the shared lane again.

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
the location check itself does not classify an edit or grant access. A private
bridge now compares actual bytes through the existing target reader, using
the authenticated original receipt and a shared media activity lease. It
rechecks the moved checkpoint and both names after reading, and never falls
back to the old path or rewrites the receipt. It preserves an edit on the
same inode and classifies unchanged bytes independently of the new path. The
native caller still has to supply the live book and exact checkpoint.

An owner-bound comparison additionally requires the separate sealed terminal
checkpoint and a complete selection of verified moved outcomes. If the
independent checkpoint is absent, the selection is partial, or the journal
has advanced without the original owner, the comparison holds rather than
trying the old path. This private comparison does not change any mapping or
provide a new Saved receipt.

Linux receive now checks this fence under its shared media activity lease in
review, fresh admission, resume admission and pre-publication. The comparison
uses the moved inode and its immutable original receipt. Fresh admission
repeats the version review in the same connection operation and lease as
acceptance. Resume rechecks the version parent before reopening its original
stage. Both recheck the owner and journal before emitting ACCEPT.
An incomplete owner operation holds the receive; with an intent present,
an unmapped member is not treated as new. Alias evidence is not an alternate
path. A synthetic GIF verified no download for an unchanged moved original
and no version publication or Saved reply when that inode was edited during
download. Ordinary receive still has no entry point to create an intent or
move a file. SEND, recovery copies, trash, and Saved retry are not enabled by
this comparison.

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
  The private Linux path now also inventories real names at each pinned target
  directory descriptor, before use and during the endpoint recheck. An alias
  or an incomplete bounded inventory holds. A case alias discovered after
  rename does not credit an outcome or trigger an undo; the spent attempt and
  both files are preserved for inspection. This is not an atomic reservation
  of differently spelled names from external writers.

## Native journal requirements

Before offering **Yes**, provide a protected local journal with one original
operation identity, one confirmed selection and no automatic renewal. Bind it
to the unlocked book, current preferences and destination identity. The
original saved receipt and transfer baseline must remain immutable.

A private read-only restart inspection now takes the exact externally held
checkpoint for the complete selection, rechecks the original saved book, and
uses the shared media lane. It distinguishes an unspent member at its source,
spent attempts found at either endpoint, recorded outcomes and uncertain
entries. Even a spent attempt found at the target stays held until the original
owner separately proves and commits the outcome. Missing or stale checkpoints
fail the whole inspection. The sealed owner described below persists outside
the journal; opening the journal alone does not establish that owner.

The owner's checkpoint has a strict, path-free encoding: the confirmed
selection digest (including the operation, preferences, and exact members),
saved-book digest, full destination digest, and both journal revisions. It is
only metadata: decoding it cannot establish consent. The owner persists it
separately and comparison holds when a surviving witness proves a store is
missing or out of step. Coordinated loss or rollback of all witnesses is not
covered. The product must not enable relocation without native confirmation,
scoped recovery and coordination with other consumers.

The first independent step is implemented privately: a one-shot native action
can persist a sealed confirmation intent in the existing `phone.db` under the
exclusive media lane. It binds the original operation, selection, saved book,
destination and exact historical mapping digests to the original local and
paired identities. It cannot replace an existing intent or create a journal.
An intent surviving a failure after commit is a hold, not proof of a completed
preparation. The live confirmation now binds the exact first prepared journal
checkpoint in a second sealed row after the anchored preparation readback.
No phone DB transaction spans journal I/O. In the private end-to-end GIF
primitive the same live confirmation and exclusive lane also bind each spent
attempt in both stores before the rename, and each verified outcome after file
and parent checks. A cut between commits remains held; restart cannot adopt a
newer journal head or repeat the confirmation. The outer checkpoint is not
an execution or restart grant. The current single peer-bound owner and the
conservative hold for unmapped members are not the final conflict scope.
Exposing explicit native confirmation remains open.

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
