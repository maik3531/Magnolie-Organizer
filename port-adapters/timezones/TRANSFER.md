# Integration map (plan; no UI hooks changed in Phase1)

Every consumer must bind the same `provenance.json` payload SHA and `2026egtz`
version, and reject missing/malformed data. OS APIs may supply the **system zone
identifier**, not substitute their offset/history rules. No process-wide Intl,
Foundation-default-zone, or Java provider override is proposed.

| Area | Existing paths | Required transfer |
|---|---|---|
| Shared named-zone identity | `gueltigeIanaZeitzone`, `eigeneIanaZeitzone`, `zeitzonenAuswahl` | Validate/list with normative registry, preserve TZID aliases; do not require OS Intl to recognize new zones. Resolve `system` freshly to an identifier. |
| Shared instant↔civil | `organizerZeitpunkt`, `organizerDatumzeitTeile` | Synchronous provider points and explicit gap/fold policy; no iterative Intl inversion. |
| Locale absolute display | `datumText(..., absolut)`, date/clock labels | Resolve the same instant to normative civil parts; Intl may format those parts in UTC. Any zone name/abbreviation/offset must match the normative type/tail, not stale ICU DST. Date-only labels remain civil, not shifted instants. |
| Planning/time tracking | `zeitDatumTeile`, `zeitLokaleMinute`, `zeitOrtszeitpunkt` | Replace named-zone Intl/sample-offset paths while retaining reference-fold selection, fixed offsets and strict/forward gap choices. |
| ICS calculations | `icsExpansion` named-zone `wall`/`instant`, planned-target validation, source/fold bounds | Use normative named points and candidate offsets. Embedded `defined` VTIMEZONE objects retain priority, even when their TZID matches a built-in or unsupported name; original floating and DATE semantics remain separate. |
| ICS worker | Fixed-code Blob/data worker bootstrap and function-string closure | Load the same immutable factory/model once inside the worker before jobs. Version/hash must bind worker state and recurrence-cache identity. Existing deadlines and continuation limits remain unchanged. Do not capture user book objects in generated code. |
| Tablet codecs | `ICalendarImport`, `ICalendarExport`, `TimeZoneExport` | New Kotlin immutable provider from exactly this JSON; BP may supply Gregorian arithmetic only. Strict import/new-export wall validation and raw embedded precedence remain explicit. Native smoke metadata must identify normative provider separately from OS diagnostic comparison. |
| Mac native codecs | Foundation named `Calendar`/`TimeZone` construction and export fallback | New Swift provider from exactly this JSON; Foundation UTC/date-format or pure Gregorian primitives may remain. `TimeZone.current.identifier` supplies only identity. Foundation named-zone offsets cannot determine codec behavior. |
| Mac/Tablet VTIMEZONE writers | Historical type names/DST flags plus infinite footer | Separate serializer proof for every supported model. Point correctness does not establish RRULE serialization correctness. Signed/out-of-day rules need exact unlimited representation or an explicit unsupported error, never finite expansion. Existing raw source definitions remain authoritative. |

Current source contains additional direct Intl call sites for SMS, note metadata,
zone labels and date/time controls. Inventory each as absolute instant, pure civil
value or locale-pattern metadata before replacing it. In particular, updating
only date components while leaving an old Intl `timeZoneName` or offset would
continue to lie about the displayed instant. The payload preserves historical
abbreviations, DST flags and POSIX names to support consistent native export;
localized CLDR zone names need an explicit correct-offset fallback when ICU data
cannot represent that normative zone.

The main and worker payload must not generate400years of occurrences on startup.
The standalone provider calculates a point from binary history plus nearby-year
rules. Whole-model sharing is approximately428KB serialized; clone cost, worker
memory and startup latency still need real WebView/WebKit measurement under the
original limits. Node timings in README are not a device acceptance claim.

Retain the existing37-clock native `timezone-interop` comparison and saved-book
immutability proof. After each targeted integration it must demonstrate corrected
current Casablanca2026 and wide-future behavior on actual devices. Add source
VTIMEZONE, gap/fold, locales, planning, reminders and worker coverage; passing
standalone597-zone host references alone does not authorize broad feature-parity
or release claims. Android minSdk remains26 until independent legacy/storage/
actual-runtime acceptance is complete.
