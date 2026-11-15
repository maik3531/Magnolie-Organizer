# DAV colour fingerprints and legacy migration

Source work: #450. Installed-package and real-provider acceptance: #652.

## Separate formats

| Projection | Current format | Preserved legacy implementation |
| --- | --- | --- |
| Linux appointments | `linux-calendar-3` | `_sync_inhalt_hash`, `linux-calendar-2` and older mappings |
| Linux tasks | `linux-task-2` | `_sync_inhalt_hash`, `linux-1` |
| Windows appointments | `windows-calendar-2` | `SyncBaseline.Hash`, `windows-1` |
| Windows tasks | `windows-task-2` | `SyncBaseline.Hash`, `windows-1` |

These are platform-specific projections, not interchangeable hash algorithms.
The old functions, field lists and known vectors are unchanged. Contacts retain
their existing formats and hashing. Linux non-DAV callers retain the old path.

The new projections include normalized six-digit `akzentFarbe`. Missing and empty
colour are equivalent. A parameterless top-level generated colour property in
`icsRoundtrip` does not independently pin an old colour after a confirmed write.
Nested properties and properties with unknown parameters remain opaque content.

The event/task writer audit also covers task `kategorien`, the effective exported
task parent (`icsElternUid` with the existing `elternUid` fallback), and event
exception/end flags. Linux adds `icsAusnahmen`, `icsEndeFehlt` and `icsNullDauer`;
Windows already included those event fields. Transport stamps and generated
export aliases do not become new user-edit or permission authority. Existing
identity/source validation remains separate. This audit is not a claim that
every UI field is supported by every provider or serializer.

## Conservative migration

An old content hash cannot establish that previously omitted colour fields are
clean. Differing local content must be preserved through the existing conflict
copy path rather than overwritten solely because an old hash or ETag is equal.
Linux uses this conservative path for differing unknown/legacy projections.

Windows retains its previously tested legacy LOCATION normalization only when
the observed remote independently agrees on **all newly added fields**. In that
case the unchanged old algorithm may classify only the fields it actually
covered. A colour/category/parent disagreement cannot use that exception.
Without the remote comparison, a legacy hash cannot authorize local deletion.

Current baselines use actual provider ETags. A failed conditional PUT does not
advance the caller's baseline. A returned candidate is not a durable saved-book
receipt: existing journal, save and commit barriers remain required.

## Opaque colour parameters

An unchanged parameterized colour property is exported with its parameters.
A conflicting colour edit/removal is rejected before publishing that resource.
The error must propagate instead of being caught by the ordinary invalid-record
skip mechanism and turned into a successful partial export.

## Checked source scope

`test_dav_accent_baseline.py` covers the actual Linux DAV orchestrator with an
in-memory provider, including conditional writes, legacy differences and stable
readback. `CalendarAccentSyncTests.cs` exercises the actual C# engines/codecs;
the existing Nextcloud test group invokes it without a separate runner entry.
`calendar-accent-edits.js` operates both canonical event/task forms and checks
set/change/remove without changing identity or opaque ICS data.

Synthetic host/native-Windows tests do not replace installed GUI, real server,
durable-book or Mac/Tablet acceptance. Those checks remain explicitly open in
#652 and #121. No installation, account or publication permission is granted.
