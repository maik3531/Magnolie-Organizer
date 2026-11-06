# Managed media backup locations and exclusions

Refs #392 and #338. Backup bytes are not synchronization input or output, a
comparison baseline, a complete phone/PC inventory, or deletion evidence.

Managed catalogs use the fixed dedicated **`Backup` child** of their native
storage parent. The default parent is the respective photo/video destination.
An optional alternative parent must keep this same child convention. Selecting
another parent must not rename, move, merge, adopt or remove an old catalog.
Old parents/catalogs must remain separately recoverable with their original
native identity and protected witnesses. An existing foreign `Backup` directory
is never adopted simply because its name matches.

Synchronization rejects any directory whose canonical native path has a whole
component named `Backup`, case-insensitively, including all descendants. This is
a conservative deny-only rule independent of current pairings, selected paths,
retention, online disks, catalog readability or missing metadata. `Backup-other`
and `myBackup` are not matching components. Native no-link/no-reparse ownership
checks remain required; this rule grants no path, permission or file authority.

The rule applies before accepting a synchronization destination, to persisted
destination admission, and to actual media IO. A historical protected mapping
into an excluded subtree remains stored, but cannot authorize new comparison
reads or mutation there. An excluded observation is **unknown**, not missing or
deleted. It must not produce absence proofs, deletion proposals, accepted
baselines or re-upload candidates. Inventories must prune excluded directory
subtrees before entering them, and keep excluded/incomplete coverage distinct
from authoritative absence.

Explicit local recovery may read the original authenticated backup object;
that is not synchronization admission. Recovery publication must create a new
file outside backup subtrees, verify original bytes and never overwrite an
existing file or replay historical deletion. It is not a phone write grant.

The exclusion invariant does not itself implement alternative-parent selection,
historical catalog discovery, PC upload or bilateral deletion. Those require
their separate real native owners and functional acceptance before rollout.

## Windows local parent choice and historical sources

Backup parent selection is separate from synchronization destinations and shared
phone intent. The native folder picker supplies the existing parent owner; the
browser supplies only the media kind and opaque current selection version.
The saved/unlocked book, native parent identity and version are rechecked. A
choice alone creates no `Backup` directory and moves/copies/deletes no history.
The next actual Saved/END backup uses the selected parent's `Backup` child.

The protected local record retains the original default and every former parent.
Choosing **Use default** changes only future storage selection, not those retained
references. Unchanged choices do not rewrite the ciphertext or renew versions.
An existing foreign or damaged catalog is held, never adopted or reset.

The recovery-source selector is independent of the active future storage parent.
It lists one original catalog at a time using an opaque retained location ID;
an unavailable or changed parent is held, never treated as empty deletion
evidence or silently replaced by another source. Native confirmation captures
the exact selected source parent and version. Recovery publishes a new file into
the data destination, not into either current or historical backup storage.
Source-channel access and phone write authority are not prerequisites for this
local recovery and are not created by choosing a storage/recovery location.

## Linux local storage ownership

Linux Saved/END backup copying resolves a separate protected local storage-parent
selection. Its stable local peer/domain scope is independent of pairing epochs
and source-grant revisions. Unconfigured reads create no metadata or directories;
the data destination remains the default parent. A native local action with a
short-lived owner ticket and exact selection-version CAS changes future storage
only. Default and former parents are retained without opening offline drives.

The settings record uses the existing private telephone key without constructing
PhoneStore or creating keys. A separate native-root anchor prevents a missing
original settings database from being silently reset. Foreign Backup catalogs,
replaced native parents, corrupt settings and stale native actions are held.
Selection does not create Backup storage, copy bytes, rotate media grants or
enable synchronization. Actual Saved/END copying captures the chosen settings
version and checks it throughout original-byte backup creation.

Linux local-history APIs resolve an opaque source ID to one exact retained native
parent, independently of the active future-storage choice. Reads and preparation
of a new recovery file continue after the transport owner and original data
directory disappear. An unknown or unavailable historical source is held; there
is no automatic fallback. The new-file preparation does not publish a mapping,
overwrite a target, replay deletions or create phone write authority.

The Linux native picker uses a read-only preflight on the native IO lane before
opening the GTK folder dialog on the UI thread. Preflight captures the exact
selection CAS and saved-book witness; both are rechecked after the dialog. The
private IPC route accepts the native picker path, while browser requests contain
only the peer/fingerprint, media kind, action and correlated request ID. No path
is accepted through the public photo-action or source-wire schemas.

The initially closed Backups fold reads actual storage choices and exposes native
folder/default choices separately for photos and available video destinations.
Correlated failures/cancel preserve existing choices; opening settings does not
start synchronization, and failed reads do not automatically retry. Existing
translations are reused. Native recovery publication/source selection is joined
below; physical GTK dialog and installed-package acceptance remain required.

## Linux durable local recovery publication

The native recovery owner now publishes a new file through an independent
anchored, encrypted prepared/restored journal. The prepared event records the
exact historical source/version hash, original Saved mapping, new data destination,
private stage inode, generated new name and original byte hash before the first
payload write. The empty stage inode and directory entry are synced first.
Recovery checks that same owned inode after interruption and uses no-replace
publication; a foreign target or replaced stage is held and preserved. Verified
complete stages and already published candidates are not copied again.

The restored record preserves original lineage but is neither a phone Saved ACK,
a deletion receipt nor a new phone write grant. Original Saved mappings and user
edits are not replaced. Local publication works without the original transport
owner or original data directory; the native caller supplies an explicitly owned
new destination and the current saved/unlocked-book guard.

Unpublished `.magnolie-restore-<32hex>.part` files and private publication
directories are deny-only synchronization exclusions. Target comparison returns
unknown without reading their payload; trash/deletion admission rejects them.
New generated restored filenames remain eligible for the future PC source lane.
That lane must apply the same exclusion before directory descent or leaf access.

Native local discovery reads authenticated location anchors without opening old
drives. The actual Saved/END worker registers its default parent before backup
bytes so later recovery does not depend on the pairing. Older default catalogs
remain discoverable through read-only, physically bound decryption of existing
photo/video preference metadata, without creating a preference/transport authority,
claiming association, changing grants or migrating settings during a read. An
empty location bootstrap after a failed CAS does not hide that older default.
Corrupt or missing originals are held, never reset or silently treated as empty.

The native local recovery controller supports bounded source discovery, exact
historical-source version pages and explicit publication. These local operations
alone do not complete PC-to-phone restoration or bilateral deletion synchronization.

## Linux independent original-catalog witness

The native private telephone directory retains a sealed original-catalog witness
separate from the `Backup` folder. It binds the exact parent/catalog/DB/lock
identity and original sealed header; a reciprocal catalog marker also binds the
external witness identity. A known catalog whose entire folder vanished cannot
be silently bootstrapped again. Missing, changed or corrupt external witnesses
are held before writable catalog opening, without deleting or replacing bytes.

Both ownership files are atomically published from private new metadata files.
New catalogs bind ownership before any backup payload. Existing format-1 catalog
headers, versions and object bytes are unchanged. Older authenticated catalogs
without these witnesses stay passively readable; only a real verified Saved
backup action adds the binding. Interrupted marker completion does not poison a
valid external witness or force payload recopy. Neither passive history nor a
folder-choice preview creates or repairs these records.

## Linux recovery surface and foreground ownership

The closed Photos/videos recovery fold is available both in general Backups
settings and in the paired local backup controls, without requiring an online
phone. Source and version pages are bounded to 128 rows. The browser sends only
correlated request IDs and opaque scope/source/reference hashes, never a target
path or a claimed confirmation. Unavailable historical sources remain held; a
refresh or pagination cannot silently replace the selected source. Failure or
cancel preserves the version, and lost replies cause no automatic retry.

The native handler captures the existing immutable book lifecycle owner, current
data-object identity and actual saved-book witness before the GTK folder dialog
and native Yes/No confirmation. After the dialog it rechecks those same witnesses
on the IO lane before publication. Lock/unlock, profile or book turnover retires
the old owner even when the final visible settings look unchanged. Local recovery
uses no PhoneService bootstrap, peer impersonation or phone permission.

A distinct active-copy permit continuously checks the actual saved book and
native operation owner without holding a SQLite writer transaction for the
duration of a large video copy. Actual Saved/END backup copying uses the same
non-destructive permit; concurrent phone metadata writes remain possible and
concurrent saves can pause and retire a copy promptly. It is not a
cleanup/compression permit and has no retention-day authority. The
short-lived native start ticket remains distinct from the bounded two-hour owned
foreground run; ordinary source/version reads retain their short deadline.
Available destination space is checked before new payload creation. Read-only
legacy discovery, original-version retention and no-overwrite publication remain
unchanged. Physical native dialog/package acceptance is still pending.

## Interrupted Linux backup copies

An actual authenticated Saved-mapping lease now persists the original version
intent before creating or writing a backup payload. The sealed intent is bound
to catalog membership and includes the original mapping, content key, timestamp
and version identity. The empty owned inode and its directory entry are synced
before object registration. Final version/object commit atomically consumes the
intent; retries preserve its original timestamp and do not recopy verified bytes.

`versions()` remains completed-only. Explicit `pending_recovery_versions()` and
the local recovery view additionally expose interrupted copies only after fresh
size/hash verification of their exact registered inode. A complete prepared
object can thus be restored through the existing native new-file confirmation
and lineage journal without the original PC file, active peer or a fabricated
phone receipt. Merely listing or restoring it does not mark its backup complete
or migrate catalog metadata. Missing, partial or corrupt payload is never offered
as a recoverable version; a substituted inode or missing intent membership holds
the operation. Intent-only interruptions remain inert and retryable.

Pending references pin shared objects against compression/retirement. Future
garbage collection must preserve them as well. Existing format-1 schemas,
headers and completed version records stay unchanged; absent pending records
need no read-time migration. Copies interrupted before this intent mechanism
existed cannot acquire reconstructed historical authority from bytes alone.

## Cross-process Linux maintenance exclusion

Active backup copies, local recovery and the full actual album worker share a
nonblocking native activity lease. Destructive maintenance takes the exclusive
lease before its existing bounded saved-book writer transaction. Both use flock
on the exact already-existing private `phone.db` inode, independently of SQLite
byte-range locks. No extra lock path, key, metadata migration or missing-lock
bootstrap is introduced. Saved-book writers still do not wait for a long copy;
their policy pause retires the copy normally.

An exclusive owner holds new album/source work before its first source command;
it neither sends cleanup commands for an unadmitted run nor automatically retries.
The activity lease remains held through actual worker IO end and error cleanup.
Independent processes cannot admit exclusive maintenance alongside shared copies,
and ordinary copies can coexist. Exceptional exits release admission. These
guards are prerequisites, not by themselves the compression/GC scheduler join.

## Native Linux idle-compression join

The existing native load/unlock retention helper now installs one optional
window-owned 60-second polling callback. It neither constructs a phone service
nor creates native storage. Only an existing native phone database and current
immutable saved/unlocked-book owner can start a dedicated pass. Book-object,
lifecycle, lock or profile-root turnover retires the old pass; the worker remains
bound to its original native root. Window destruction removes polling and signals
the worker. No frontend flag or shared media preference supplies idle authority.

Each dedicated thread lowers only its own priority to nice 19, samples native
desktop idle/CPU/available-memory evidence twice, and fails closed on unknown
evidence. A pass has a 60-second guard, visits at most 16 retained sources with
in-memory rotation and attempts at most one object of at most 400 MiB. The actual
exclusive saved-book maintenance permit excludes active sync/copy/recovery.
Only versions strictly older than 30 days with saved retention 90/365 or Never
are candidates; already expired versions are not compressed. Pending intents
pin shared objects. No-savings trials retain the raw bytes and are not repeated.

The existing bounded XZ/hash/readback and verified at-least-10-percent total
saving checks still decide publication and raw-representation retirement. Offline
or corrupt catalogs stay held without replacement or metadata repair. Original
user files and all completed version references are unchanged. This joins idle
compression, not backup-version expiry/garbage collection, reverse upload or
physical installed-package acceptance; those remain outstanding.

## Interrupted Windows backup copies

Windows likewise commits the original Saved-version intent into its existing
authenticated immutable catalog snapshot before payload creation. Pending rows
carry the same original provenance, timestamp and reference hash as the eventual
completed version. Final object/version commit consumes the pending entry
atomically; retry keeps the original time and exact candidate FID. Format-1
completed versions and legacy snapshots without pending rows remain readable
without read-time migration.

`NativeMediaBackupVersions` stays completed-only. The separate recoverable view
used by the local native source chooser/preflight also verifies complete pending
objects by exact registered identity, length and hash. Partial/corrupt bytes are
not offered; a substituted FID is held. The actual saved-book coordinator can
publish a new local file after disconnect and source-file loss without changing
the backup catalog or original phone Saved/END history. Neither listing nor
restoring marks the interrupted backup complete. Any future Windows maintenance
must pin pending references alongside completed versions before retiring bytes.
