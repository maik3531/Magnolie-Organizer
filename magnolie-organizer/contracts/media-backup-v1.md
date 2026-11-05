# Local PC media backup storage (implementation scope #392)

This is a local storage contract, **not** a peer capability, deletion receipt,
source inventory, Saved/END message or permission to modify a phone.

## Content and versions

- Each explicitly selected native destination has its own private `Backup`
  subdirectory. An existing unregistered directory is never adopted. Destination,
  ancestor, directory, database and lock identities are checked without following
  symlinks. Existing storage is authenticated before writable database access.
- Backup objects are keyed by the original SHA-256 **and byte count**, not a
  filename, timestamp or media label. An existing object is completely verified
  before another immutable version may refer to it. Corruption is not silently
  repaired by overwriting a shared object.
- References contain the exact protected native Saved-mapping version, original
  name and backup creation time. Different names can share bytes; changed bytes
  retain separate objects. An identical retry neither copies data again nor
  renews the creation/retention timestamp. Historical versions may be read through
  their authenticated chain without rewinding its current head.
- Objects are independent copies, **never hardlinks to writable user files**.
  The active files, source jobs, Saved/END history and live mappings are unchanged.
- The metadata header and aggregate membership are encrypted/authenticated with
  the existing local storage key. Missing keys, headers, replaced roots and
  unexpected schemas fail closed; none cause a new empty replacement catalog.
  The catalog is bounded to 4,096 references/objects and 64 MiB database storage;
  reaching a bound retains existing data rather than evicting versions.

## Lossless cold representation

- A candidate is eligible only when the newest reference to that object is
  **strictly older than 30 days**, its configured retention is longer than 30
  days or Never (`0`), and the reference is not already due to expire.
- The original media encoding is unchanged. JPEG/MP4 are not transcoded.
  Linux prepares a single XZ stream at preset 1 with a SHA-256 check; decoding
  has a 64 MiB memory limit and a strict original-byte-count bound. Trailing data,
  additional streams and a mismatched content digest are rejected.
- A representation is adopted only if it saves at least **10 percent**, including
  reserved catalog overhead and actual filesystem block allocation. A sparse
  file is not "optimized" into a larger physical file. An unprofitable trial is
  recorded so the same object is not recompressed endlessly.
- The new private inode is registered before writing. Its bytes are flushed and
  decoded/hashed before the catalog can select it. All references remain stable.
  Only after that durable switch may the exact old owned raw inode be retired;
  a zero-byte completion marker remains. A failed/uncertain switch keeps the
  previous representation. An interrupted registered candidate is never replaced
  by adopting an unrelated occupied filename.
- Compression does **not** expire any logical version, change a retention setting
  or make `0` mean automatic deletion. Shared-object deletion/expiry must account
  for every retained reference; it is not authorized by this codec.

## Maintenance and restore

- No worker/timer/service starts merely by importing or opening this component.
  The application scheduler must supply the current saved/unlocked-book,
  retention, stop and single-native-media-worker guards.
- Cold work requires at least ten minutes of native session inactivity, at most
  15 percent external CPU load and at least 2 GiB available RAM. Native Linux
  desktop/logind idle evidence and two CPU samples are required; an unavailable
  observation is not idle. The dedicated worker's own CPU is excluded. User
  activity, changed settings, shutdown and resource pressure revoke that attempt.
  Only the dedicated background thread is lowered to nice 19, not the UI process.
- Restore validates the selected protected reference and stored representation,
  then automatically decodes into a **new, private, unpublished** file. It never
  overwrites an existing target. Native no-replace publication, restored mapping
  registration and any subsequent PC-to-phone synchronization remain the
  responsibility of their current native owners, not historical peer grants.

## Delivery boundary

The Linux storage/codec/resource-probe components have focused native-file and
protected-Saved-mapping tests. This contract does **not** claim the automatic
application scheduler, graphical backup management, Windows storage backend,
shared-reference expiry or restored-file synchronization are already integrated.
Existing production gates and the required native package acceptance remain in
force until those owners are connected and verified.
