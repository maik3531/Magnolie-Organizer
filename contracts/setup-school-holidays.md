# Desktop setup: route defaults and school-holiday consent

Canonical implementations: `magnolie-organizer-2.0.0` (GTK/Python) and
`Magnolie-Organizer-Windows-2.0.0` (WinForms/C#), with their existing desktop JavaScript.

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
repeated results replace the retrieved years instead of appending duplicates.

## Availability and consent

Setup offers region-bound retrieval only for the existing local OpenHolidays
subdivisions: Germany (16 states, including `DE-SN`), Austria (9 states), and
Switzerland (26 cantons). Unknown/free-text regions have no invented code or data.
Recognized codes, display names, and supported aliases resolve to their local
country; a foreign subdivision is rejected. The existing provider can return no
records for a requested region/year, which keeps the existing availability message.
The native setup explains the OpenHolidays internet request alongside the checkbox.

Provider verification is offline: actual Python and C# provider functions receive
recording HTTP adapters. It verifies DE-SN, AT-9, CH-ZH request paths, opt-out,
empty responses, and mismatched-country rejection. It does not claim a live service
availability check or a Windows GUI run on Linux.

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

- `Magnolie-Organizer-Windows-2.0.0/tests/setup-holidays.js`: 88 cases against
  both actual desktop scripts, including all 20 languages, explicit map preferences,
  invalid/partial addresses, bound consent, durable save failure, retry after
  restart, cache/view settings persistence, deduplication, and stale responses.
- `magnolie-organizer-2.0.0/pruefungen/test_setup_holidays.py`: actual GTK dialog
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
