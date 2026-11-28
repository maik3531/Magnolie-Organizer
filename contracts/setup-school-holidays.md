# Desktop setup: route defaults and school-holiday consent

Canonical implementations: `magnolie-organizer` (GTK/Python) and
`magnolie-organizer-windows` (WinForms/C#), with their existing desktop JavaScript.

## Before → after

| Flow | Before | After |
| --- | --- | --- |
| Own address | Setup copied address/country; map action stayed at its global location default. | Setup defaults to Route only with usable address content, using `eigeneAnschriftTaugt` and excluding digits in names alone. Explicit existing map actions/providers are retained. |
| Unedited address | A system country alone could replace an existing sender/country. | Country-only defaults do not replace an existing sender or imported country. |
| Region choice | Setup stored the region; no school-holiday consent was passed. | Native checkbox names the selected localized region and starts unchecked. |
| Consent | No setup-to-provider connection. | `schoolHolidays` plus `schoolHolidayRegion` bind explicit consent to a supported subdivision. Country/region changes revoke the staged choice; language-only redraws retain it. |
| Finish | Address/settings handoff only. | Shared apply persists `einstellungen.ort.ferien` and `setupFerienAbruf`; after successful durable save, the existing `feiertage` bridge retrieves the current and following year. |
| Cancel / Skip | Skip returned default selections without an explicit skip discriminator. | Cancel returns no selection; Skip sets `setupSkipped` and shared apply exits before changing address/map/holiday settings. Neither starts holiday retrieval. |
| Response/restart | Existing dedicated holiday cache. | The same `DATEN.feiertage` cache is saved and normalized on restart. Success clears pending retrieval; offline failure retains it for the next startup. Stale country/region responses are discarded. |
| Calendar display | `ort.ferien` selected retrieval content only. | The existing setting also filters school-holiday records in calendar views, retaining cached data and ordinary appointments/Planner recurrence definitions. |

Retrieval does not enqueue an ICS import or create appointments. Existing synchronized
holiday deduplication is reused. Repeated setup handoff is ignored in a session;
repeated results merge without appending duplicate periods.

## Cache replacement authority (Refs #855)

The additive native result field `abrufbereiche` lists only completely parsed,
successful endpoint/year/region requests. Each object contains `country`,
`region` (empty for a whole-country query), `art` (`public-holiday` or
`school-holiday`), `von` (`YYYY-01-01`) and `bis` (`YYYY-12-31`). A valid empty
response certifies an empty area; an omitted school request, caught transport
failure, malformed/partial response or row outside the requested area does not.
Tolerated valid rows can still be displayed without certifying cache removal.
The official provider requires explicit end dates and nationwide flags; their
legacy display fallbacks do not establish complete replacement data.

The shared importer binds these areas to the captured country, requested
regions, school opt-in and years. GUI callbacks without a pending request are
ignored; MCP retains its existing request/revision/save gates. Visibility of
public holidays is independent of successful retrieval and cache replacement.

An old row is removable only when all its years and geographic scope are
covered. Other countries, opt-out/failed school areas and unqualified or
contradictory legacy geography survive. An explicit multi-region row can retain
its unaffected regions; both geographic fields and generated labels are updated
together. Equivalent positive regional rows are reunited so repeated narrow
refreshes cannot accumulate duplicate remainders. Ordinary appointments,
recurrence, synchronized calendar records, notes and tasks are not changed.

OpenHolidays uses inclusive overlapping intervals and returns complete start/end
dates. Nevertheless an omitted old period can have been moved outside the
requested year, so one year alone cannot delete a period spanning an unrequested
year. Likewise a regional query alone cannot remove a nationwide record.
These ambiguous records are retained conservatively; this can leave an older
partial view until a sufficiently complete request is available. Stable provider
identities and richer coverage/status remain a separate international extension.
Older native hosts without `abrufbereiche` merge returned rows without deleting
unmatched old cache entries. The field itself is transient and introduces no
persistent book-format migration or additional permission.

In the regular Desktop settings and MCP (#854), France uses OpenHolidays
school subdivisions; Belgium and the Netherlands use the explicit school
groups verified in #857. A group request may replace only that group's
school rows and the independent nationwide public calendar. Local public
rows and other groups remain unchanged. Missing or unconfirmed school years
are merged without removing cached school rows; a selected school area
must have provider evidence at both calendar-year edges before replacement.
Choosing “All” still sends the unfiltered country request. A mailing address
in setup does not select one of these separate school areas.

Regression entry points: `tests/holiday-cache.js` and
`tests/holiday-cache-mcp.js` in the Windows source tree execute both complete
desktop frontends. Native provider/source-host tests and Mac/Tablet service
tests cover the response contract. Native GUI, real HTTP availability and
installed packages remain separate acceptance work.

## Availability and consent

Setup offers region-bound retrieval only for the existing local OpenHolidays
subdivisions: Germany (16 states, including `DE-SN`), Austria (9 states), and
Switzerland (26 cantons). Unknown/free-text regions have no invented code or data.
Recognized codes, display names, and supported aliases resolve to their local
country; a foreign subdivision is rejected. The existing provider can return no
records for a requested region/year, which keeps the existing availability message.
The native setup explains the OpenHolidays internet request alongside the checkbox.

The original setup-host verification is offline: actual Python and C# provider functions receive
recording HTTP adapters. It verifies DE-SN, AT-9, CH-ZH request paths, opt-out,
empty responses, and mismatched-country rejection. It does not claim a live service
availability check or a Windows GUI run on Linux.

## Austrian provider identifiers (Refs #856)

Settings, bridge requests, cached `region`/`regions` and `abrufbereiche` use the
existing ISO 3166-2 identifiers. OpenHolidays uses different identifiers at its
HTTP boundary. The official `/Subdivisions?countryIsoCode=AT` response, verified
on 2026-11-28, defines these nine pairs:

| Internal ISO identifier | OpenHolidays `code` |
| --- | --- |
| AT-1 | AT-BL |
| AT-2 | AT-KÄ |
| AT-3 | AT-NÖ |
| AT-4 | AT-OÖ |
| AT-5 | AT-SB |
| AT-6 | AT-SM |
| AT-7 | AT-TI |
| AT-8 | AT-VA |
| AT-9 | AT-WI |

All four providers translate the selected ISO identifier before URL encoding and
translate known response aliases back to ISO before existing character/scope
validation. The Unicode provider aliases are encoded as UTF-8 in the URL; the
general region grammar is not loosened. Known ISO response codes remain compatible.
Unknown Austrian selections cannot start a falsely qualified request. Unknown,
foreign, prefixless or mixed response scopes never certify complete Austrian
coverage, including nationwide rows and whole-country requests. Existing strict
handling of other malformed Unicode codes remains intact.

HTTP 200 alone does not establish that a supplied region is recognized. In the
recorded live Vienna/2026 comparison, `AT-9` returned only six nationwide school
periods while the correct `AT-WI` returned eight, including semester and summer
holidays. The confirmed response fixture, provider attribution, exact source
hashes and compiler/live follow-up proofs are delivered with #856. This fixes an
existing supported region; country/provider expansion remains a separate task.

No persisted selection or book format changes, new permission, additional setup
step or generated holiday date is introduced. The #855 conservative handling of
partially covered national/cross-year cache periods still applies.

## Localization

The new question and availability message are manually translated in both sets of
PO files. English is the source language; the 19 translated catalogs complete all
20 supported languages: en, de, fr, es, it, nl, pt, ru, cs, pl, hsb, da, nb, hi,
zh_CN, ja, ar, uk, be, tr.

Artifacts use existing `werkzeuge/pot_erzeugen.py`, `po_zu_js.py`, `msgfmt --check
--check-format`, and Windows `po_zu_native.py`. Linux consumes MO, both desktops
consume web JavaScript, and native Windows consumes `app/native-i18n.json`.
Both source extractors include the dynamic `%(state)s` question. Tests check the
placeholder and reused network/availability messages in every language.

## Scoped verification

All runs are serial, pinned to two CPUs, with a 6 GiB address-space ceiling.
Fixtures and compiled outputs live under `/tmp/opencode`; desktop services,
phones, VMs, emulators, and real user profiles are not test inputs.

- `magnolie-organizer-windows/tests/setup-holidays.js`: 88 cases against
  both actual desktop scripts, including all 20 languages, explicit map preferences,
  invalid/partial addresses, bound consent, durable save failure, retry after
  restart, cache/view settings persistence, deduplication, and stale responses.
- `magnolie-organizer/pruefungen/test_setup_holidays.py`: actual GTK dialog
  and event loop; Finish/Cancel/Skip in all 20 languages (60 runs), region changes,
  unsupported input, language switching, PO/MO/web/native catalog parity, and
  actual Python provider URL tests.
- Existing `test_setup_address.py` and `test_ersteinrichtung.py` cover optional
  address/import preferences and setup state lifecycle.
- `tests/setup-holidays-native.ps1`: uses PowerShell's bundled Roslyn to compile
  canonical setup state, normalizer, atomic store, and native gettext; isolates
  host regional discovery with a stub. Executes state/serialization/persistence
  and all-20-language gettext checks, then compiles actual WinForms setup and
  its GUI self-test against Windows reference assemblies. Actual C# provider
  methods are extracted verbatim as syntax nodes and executed with offline HTTP.
- `FirstRunSetupUiSelfTest.VerifyHolidayLanguages` adds all-20-language native
  WinForms assertions for execution later on Windows.

Example limits for the .NET probe (the small GC reservation permits the same
6 GiB virtual-memory cap):

```sh
taskset -c 0,1 prlimit --as=6442450944 -- env \
  DOTNET_GCHeapHardLimit=10000000 DOTNET_GCHeapCount=1 \
  DOTNET_gcServer=0 DOTNET_GCRegionRange=40000000 \
  /tmp/opencode/powershell-7.4.13/pwsh -NoLogo -NoProfile \
  -File tests/setup-holidays-native.ps1 \
  -TemporaryRoot /tmp/opencode/setup-holidays-windows-final \
  -WindowsDesktopReferences /home/maik3531/.nuget/packages/microsoft.windowsdesktop.app.ref/8.0.30/ref/net8.0
```
