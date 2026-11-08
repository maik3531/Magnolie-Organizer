# JS port integration plan — review checkpoint (Refs #121, #447)

This is a plan. No UI hook has been changed. Phase1 is a2dbc859; the separate
native-resource/production-codec smoke wiring is c0387b8a. Linux and Windows
product sources remain unchanged.

## One synchronous bootstrap, two projections

Both projectors (`Android.../tools/project-web.cjs` and
`macOS.../tools/project_ui.py`) will read the same shared resolver, normative JSON,
manifest and public-domain license from `port-adapters/timezones`. They will
verify manifest schema/version, JSON SHA2e6b.../428473bytes and license SHA before
producing any output. The existing frozen input/output inventories cover every
new asset; generated assets are not authoritative source.

One generated external `normative-timezones.js` will concatenate the exact shared
resolver, a new shared pure port-runtime factory, and a fixed initializer carrying
the exact JSON model and approved identity. It loads synchronously before
`tablet.js` / `macos-beta.js` / `anwendung.js`; no fetch, bridge roundtrip or
network request is required to calculate a point. Both outputs also retain the
raw verified JSON, manifest and license as inventoried assets. Codec resource
copying remains with the native provider owners; web and codec bytes must match.

The shared runtime takes an explicit zone for every calculation. Its system-zone
accessor reads only the fresh public OS/Intl **identifier** and validates it
against the normative registry; it never asks the OS for an offset. An invalid
explicit zone cannot fall through to system rules or UTC. Main/worker provider
identity is immutable for the lifetime of the document.

## Concrete reviewed anchors

Use one shared patch manifest with exact start/end anchors, original block SHA
and fixed replacement snippets. Both projectors implement only the same generic
single-match/hash-checked application. Run these patches before platform-specific
rewrites. Marker blocks permit host tests to reconstruct and compare the original
canonical text; no hand-maintained second copy of the whole UI is introduced.

| Anchor/group in canonical `anwendung.js` | Replacement behavior |
|---|---|
| `gueltigeIanaZeitzone` | Normative registry membership and explicit system sentinel; preserve accepted original aliases. No ICU validation/canonicalization. |
| `eigeneIanaZeitzone`, `organizerZeitzone` | Explicit known ID, or freshly resolved system ID. Invalid explicit IDs do not trigger an OS-rule fallback. |
| `organizerDatumzeitTeile` | `wallParts`, mapped to the existing German field names. |
| `organizerZeitpunkt` | Exact `resolveWall`: first fold / forward gap for the existing Date-construction use case. No three-step Intl inversion; validation/save paths retain their own strict policy. |
| `datumText` | Explicit option zone takes precedence; otherwise absolute=true uses organizer zone, while civil/date-only values retain civil meaning. Format only the correctly projected civil value through Intl with timezoneUTC. Replace timezone-name parts with the correct normative numeric offset label, including historical seconds; never preserve stale ICU zone names. |
| `kontaktOrtszeit` | Existing `datumText` target-zone display uses the same formatter; own/system identity comparison no longer asks ICU to validate a zone. |
| `zeitDatumTeile` | Preserve the explicit fixed-offset domain branch; named-zone projection uses the provider. |
| `zeitLokaleMinute` | Exact fold candidates / reference-offset selection, strict versus explicit forward gaps. Preserve the domain's integer-minute storage and rounding; strict saves reject nonrepresentable historical precision with a typed unsupported result. |
| `zeitOrtszeitpunkt` | Resolve calendar planning directly at second precision instead of reconstructing seconds from a rounded UTC minute. |
| `icsExpansion`: own/planned target validation | Normative IDs; a valid embedded source definition remains the first authority even for a colliding built-in name. |
| `icsExpansion`: named `wall` / `instant` | `epoch+offset` and exact wall candidates. Generated gap occurrences are omitted; explicit gap/fold policies preserve the existing RFC behavior. The embedded-definition branch remains separate. |
| `icsExpansion`: source-high/fold bounds | Exact earlier/later wall candidates determine fold width; remove the five-day sampled-offset approximation. |
| `icsRuntimeVorbereitung` key | Include normative version/hash and resolved zone in job/cache identity. |
| `icsRuntime` fixed worker source and message | Same trusted factory/model/runtime is initialized inside the actual worker before jobs. Include/verify identity in each request/response and reject mismatches. Do not interpolate calendar content into executable source. |
| `zeitzonenName`, `zeitzonenAuswahl` | Normative registry/list, preserved selected aliases, stable city/original ID for selectors or contexts without an instant. Only dated contexts may show the exact instant offset; never attach today’s winter offset to a future summer record. |
| Personal-sync timezone identity validation | Replace the named Intl validation/resolvedOptions step with the same normative identity. System still supplies identity only. |

The phase1 API supplies exact `offsetAt`, `wallParts`, `resolveWall`; the port
runtime can derive exact earlier/later candidates for fold bounds without
exposing mutable model data. No finite future sample is introduced.

## Locale formatting and remaining actual instant displays

A new shared formatter will calculate the normative offset first, shift the same
instant to a UTC civil carrier, and use Intl solely for locale/calendar/digits/
hour-cycle layout. `formatToParts` must replace every `timeZoneName` token,
including tokens implicitly added by long/full timeStyle. An older engine's
unsupported name style may fall back to a supported UTC formatter and an accurate
numeric offset label; it may not revert to formatting the instant in the OS zone.
Numeric offset labels are deliberately used instead of an unverified localized
CLDR zone name. Raw TZif/POSIX names/DST flags remain available to native writers.

Also replace actual default-system instant formatting in `geraeteZeit`,
`journalDatum`, `smsZeitText`, note timestamp properties and the enumerated Date
`toLocaleString`/`toLocaleDateString`/`toLocaleTimeString` call sites (sync deletion,
SMS/call timestamps, journal/update/property timestamps). Each small expression
gets an exact reviewed anchor/count. Preserve each site's existing locale and
zone policy: former default-system displays use the system **ID** with normative
rules; organizer/explicit-zone displays use those IDs. Number formatting is not
touched. Locale pattern-only controls may use explicit UTC to avoid accidental
system rules. Date-only calendar values are not converted into instants.

Time tracking stores integer UTC minutes since1970; calendar planning has second
precision. Historical second-based offsets are retained by the provider. The
integration must not silently change that persisted minute-domain schema; a
nonrepresentable historical minute case needs an explicit reviewed policy rather
than claiming new precision. Existing strict/forward/reference-fold choices must
be tested through actual domain APIs/UI, not just the standalone resolver.

## Actual worker, restore and regional changes

The worker keeps the same isolated fixed-code execution (Blob/data fallback),
continuation limits and deadlines. Bootstrap includes only trusted code/model;
user calendar content remains structured-cloned data. A freshly resolved main
zone is sent per job. Restart/reload creates a new immutable provider; book
restore and regional-zone changes create new job keys and cannot reuse old-zone
results. Existing source VTIMEZONE cache signatures still distinguish source
blocks. No400year occurrence expansion happens during bootstrap or rendering.

## Checks before any readiness claim

1. Both projections reproduce, contain identical normative bytes/identity/license,
   and fail on missing/changed anchors or resource hashes. Canonical Linux/Windows
   bytes remain unchanged; new projection transformations are explicitly listed.
2. Host tests run the actual projected source for both ports: all37 external
   clocks, Gaza2074, gaps/folds, generated omissions, source-custom±23h precedence,
   alias validation/list selection, DATE/floating preservation, regional changes,
   restart and restore. Add representative non-Latin locales/hour cycles and
   actual datumText offset/name output. Re-run relevant calendar/reminder/editor
   and existing host suites after coordinating projection/vector regeneration.
3. Keep the native37-clock interop fixture unchanged. Root approved148 app-path
   comparisons (appointment, task count/point, actual datumText including correct
   offset) plus37 separately counted **raw OS-Intl diagnostics**. Emit
   appParity/osIntlParity/usedForPointRules explicitly. Raw ICU remains unpatched;
   old OS mismatches stay visible and are never reported as an OS fix.
4. The actual native WebView worker must return synthetic finite-result cases
   through `OrganizerTest.icsRuntime`; observe its real pending→ready/result path.
   A host fake Worker is not native evidence. No book/profile writes during the
   comparison; verify native saved book unchanged.
5. Compare original native cold-start, main/worker memory and point latency under
   the existing caps. No new timeout, prewarm, ForceACK or acceptance bypass.
   Successful host tests alone do not establish WebView/WebKit or release parity.
