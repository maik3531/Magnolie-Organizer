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
An incomplete owner operation still holds the receive. With a complete
terminal witness, the receiver authenticates all selected historical mapping
roots by exact protected digests, even after a version advances a head. Only an
independent association with a disjoint output route may be admitted as new.
Existing and proposed version outputs must not reuse either reserved name.
Admission, resume and publication enforce this; alias evidence does not supply
an alternate path. Missing or non-root evidence holds. A synthetic GIF verified
no download for an unchanged moved original
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
  The private single-file preview now derives the source and target from the
  original accepted manifest, history and exact mapping/Saved evidence. It
  reads the current original inode, so a local edit can qualify only if its
  current bytes still prove GIF animation. The preview requires existing
  safe target parents and creates no directory, journal, or consent. The native
  parent inspection distinguishes an exact missing suffix from a linked,
  aliased, unsafe or concurrently changed parent. A missing suffix currently
  holds the ordinary preview. An internal read-only draft can retain that
  suffix with the freshly proven original GIF and its exact mapping. It is
  not a prepared rename record or an instruction to create directories. The
  preview does not yet enumerate a complete user-visible selection. The private native
  selection entry point can freeze an exact explicit list of up to 128 current
  image mappings under a single shared lease. All selected members must pass;
  it never silently drops one, creates missing parents, or grants a move.
  Its separate folder-plan mode binds all verified members into one read-only
  digest, including the existing inode prefixes and exact missing suffixes.
  Common parents must agree in spelling, identity and existence. Creating a
  folder changes the plan; neither the plan nor its members are rename records.
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
The private owner entry point now reads its own sealed intent and checkpoint,
requires the original destination, and supplies the live guard to inspection.
It does not accept a caller's checkpoint or restart an operation.
The private connection readback resolves that destination from the complete
protected historical mapping set. It matches each original path, parent chain
and inode to the anchored records instead of taking a current preference path
or a caller-supplied target. A fresh synthetic connection observed a prepared
original; after a local edit it reported a hold with the file, mappings and
journal unchanged. This is not yet exposed as a recovery action.

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
The private GTK confirmation component defaults to No. An explicit Yes while
the original window and action are current returns the exact selection as a
one-shot native handoff to the original caller. The same action and guard still
apply when claiming it; its deadline is not renewed. Close acts as No and a
digest alone is not a handoff. This component has no product entry point and
no direct disk or permission effect. The private connection now consumes that
handoff for preparation only. It compares a fresh read-only preview to the
entire confirmed selection, then carries the same catalog, mapping, policy and
binding witnesses into exclusive preparation. A changed catalog at that boundary
holds without intent. Neither preparation nor its result authorizes a rename.
When the separate read-only folder plan includes missing parents, a private
GTK variant discloses folder creation explicitly. No is still the default.
Yes hands the exact plan back under the original action; the existing rename
preparation rejects this separate handoff type. The dialog creates no folders.
The native connection can now revalidate that exact plan and seal its digest
in a separate owner row before any folder creation. A changed target parent,
revoked action, or mismatched handoff cannot be used for preparation. A durable
folder-plan row holds the ordinary rename path and supplies no restart or
directory-creation authority. No folder or rename journal is created here.
The private first-attempt transition additionally seals the exact first
missing name and its existing parent chain under the same original action and
exclusive lease. An interruption on either side of that commit does not allow
another attempt. Even an isolated surviving attempt holds the ordinary path.
This transition does not call mkdir or return permission to do so later.
The private live continuation can now install that first directory only: it
holds the parent descriptor, stages an empty private directory, and publishes
it without replacing an occupied name. It records the verified new inode only
after filesystem sync. The private staging name is excluded from media scans.
A late collision preserves both directories; a cut after installation without
a result is held, not repeated or cleaned up automatically. The same live
operation can now continue through a bounded, deduplicated parent list. Each
child attempt uses the exact confirmed or newly recorded parent identities. A
replaced parent holds before inserting a child. While that same live operation
continues, the completely recorded folder set can form exact rename candidates.
The native source inode, original confirmed bytes and animation evidence are
checked again; a local edit after folder creation holds. The candidates neither
authorize a media rename nor permit continuation after restart.
The private preparation path can bind the original folder plan, the exact
materialized selection and the prepared rename journal in an independent sealed
row. If approval ends after the journal commit but before that row is committed,
the journal is not adopted or prepared again. No original is renamed here.
The private connection can consume the original GTK handoff for this complete
path. Isolated tests cover sealing, preparation through parent creation, and
the live folder-based move. The synthetic original retained its bytes, inode,
mode, and mtime, with mapping, receive jobs, and preferences unchanged.
Reconnect verified the result without replay or wire output. The connection
still exposes no user-facing move action.
Existing target folders also have an isolated, live GTK handoff. It checks the
same original selection and catalog, neither creates nor replaces folders, and
preserves the original file identity and bytes. Decline, withdrawal, and stale
evidence do not move a file; reconnect only inspects the persisted outcome.
The private execution primitive can use that same live folder approval to move
the original GIFs. Each file attempt and result advances the separate sealed
folder checkpoint by exact compare-and-swap. A split before the attempt owner
commit prevents a rename; a split after a rename does not replay it. The
folder-based terminal checkpoint now also binds the complete, exact set of
folder attempt and result rows. A private read-only recovery entry checks this
evidence and the original owner/journal agreement after reopen. A missing row
or split holds; no entry is repaired, adopted, or replayed. The same check
now guards the connection's read-only recovery and receive comparison. A
synthetic reconnect recognized the moved original without another download or
Saved response. An incomplete or competing owner still holds.

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
