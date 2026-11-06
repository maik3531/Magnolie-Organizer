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
