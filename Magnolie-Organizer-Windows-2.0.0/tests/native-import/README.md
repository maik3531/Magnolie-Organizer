# Native Import Preservation

Run `magnolie-organizer-2.0.0/pruefungen/test_native_pathways.py` with pytest.
Set `MAGNOLIE_DOTNET` to the .NET 8 executable to include Windows native tests.
The harness compiles the current source into pytest's temporary directory and
uses the third-party dependencies from the Debug CoreTests build. It does not
execute old product binaries or the online synchronization decision engine.
Keep HOME, TMPDIR and XDG directories isolated when running native tests.

Set `MAGNOLIE_IMPORT_WEB_GATE=1` and optionally `MAGNOLIE_BUN` after the parallel
frontend changes. The gate calls the actual `App.importErgebnis`, persists via
the platform store, reloads the actual frontend, and runs both native exporters
and both readers. Assertions require preservation, never the previously lost
state. Setup's staged import payloads use these same native models; setup
callbacks and consent are not modified by this change.

## Frontend Contract

- Anniversaries retain `notiz`, `icsRoundtrip`, `icsTimezones`, source IDs and
  `jahrUnbekannt` through first insertion, update, normalization and persistence.
- `notiz` owns the top-level DESCRIPTION. `name`, `datum` and `typ` own SUMMARY,
  the annual anchor, yearless extension and annual RRULE. Raw dates/rules/type
  markers cannot override subsequent edits of those fields.
- `icsRoundtrip` owns LOCATION, VALARM (including its own DESCRIPTION), and
  provider extension fields. Nested alarm fields are not flattened or replaced.
- VTODO `uid` is the local graph identity, qualified by source when imported.
  `icsImportUid` preserves the native import identifier (including the native
  instance suffix for overrides). `icsSerienUid` is the ORIGINAL external
  family UID, never a qualified graph UID. Ordinary tasks export `icsImportUid`
  or their own UID when not imported; master/override pairs export the same
  external family UID. Both native instance spellings are understood.
- Merge identity is source + external family + RECURRENCE-ID value/type/TZID,
  not a parser-specific suffix. Proven pre-release qualified series values are
  repaired using `icsImportUid` and the exact graph derivation. Legitimate UIDs
  are never renamed just because they start with `mag-task`.
- `icsElternUid` and `icsElternQuelleId` retain the external parent reference even
  when only the child is present. `elternUid` remains a local graph edge. Explicit
  detach clears the external parent; adding a missing parent relinks only the
  matching source. Export resolves present graph parents before fallback metadata.
- Windows `.contact` names project to `vcardRoundtrip` N components, never
  guessed from FN. Native MiddleName/Title/Suffix and address Region survive
  serialization. The namespaced VCardName extension preserves multipart N/FN
  syntax while its native name projection remains unchanged.

## Task File Identity

Every exported VTODO carries a folded/escaped `X-MAGNOLIE-TASK-IDENTITY` JSON
value: `{"v":1,"source":"...","uid":"...","parent":"...","parentSource":"..."}`.
These are opaque source IDs and original external IDs, not local database IDs
or account credentials. Both native readers validate the UID and parent wire
bindings and restore these identities before reconciling families. Changing the
export filename or switching native parsers therefore does not create a new
source on reimport. This metadata does not select or authorize online accounts.

A single-source roundtrip leaves original external UIDs unchanged. If different
sources in the SAME export use the same external UID (also considering referenced
parents), all owners of that UID receive `urn:magnolie:task:` plus SHA-256 of
UTF-8 `source + NUL + originalUid`. Already occupied external IDs are reserved;
the smallest available positive `-N` suffix avoids a collision with a legitimate
UID. Parent edges use the same mapping. Master and exceptions within one source
share the alias; they are not independent collisions. Reimport restores the
original source/UID/parent, so a second or third roundtrip is stable. Other ICS
readers see distinct valid families and parent references without needing the
extension. No migration guesses original IDs already lost without metadata.

## Consent Boundary

Windows setup and settings currently pass only local.sqlite to the Thunderbird
calendar reader. The setup import service has a source/path selection, but no
selected cache calendar/account IDs. Automatically adding cache.sqlite there
would also import remote accounts not explicitly selected in the account UI.
No such broadening is made. A cache pass requires an explicit selection contract
shared by setup and settings, plus active-calendar and tombstone filtering.

No new visible message IDs are introduced: size/validation failures reuse
`The import file is larger than 32 megabytes.`, Linux's `The content is unreadable.`
and Windows' `The data is invalid.`
