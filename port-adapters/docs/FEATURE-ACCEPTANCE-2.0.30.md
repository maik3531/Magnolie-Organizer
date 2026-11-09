<!-- Scope: Issue #121; source inventory and acceptance boundaries, not a completed parity claim. -->
# Published 2.0.30 complete source inventory and Mac/Tablet acceptance map

Reference release `067c38934b539943d8e1720abafd8a80b401d797`; current port snapshot `0288d99f7dcd4b366748b8c36338edd1dbcafb49`. This inventory separates source presence, a working native adapter, test execution and actual platform acceptance. It does not certify feature parity.

## Inventory coverage

- All 8 declared primary sections and 13 settings pages; all 35 persisted root model keys.
- Union 206 outer native wire commands from every tagged web JS literal, published Python dispatcher, published Windows typed contract plus current port allowlists. Each command has its own row in [command appendix](BRIDGE-ACCEPTANCE-2.0.30.md); source sites/status also in JSON.
- All 1,364 mechanically detected named JS functions, 210 literal MCP tools, 122 App callbacks and 64 tagged contract files indexed in the scratch source-evidence JSON (not a committed dependency). Named helpers are not separate user features and literal MCP names do not cover computed action enums by themselves.
- Computed send routing is recorded explicitly: KDE request helper and mcpNativeAufruf use shorthand cmd; the ready/quit ternary resolves to known commands. Their action payloads must be reviewed against the matching tagged contracts; native-only interface methods are not inferred as parity from an allowlist.

## Evidence boundary

Known historical baseline: macOS 15 arm64/x86_64 latest completed Mac core/WK and real bundle save/quit/reopen passed on [run 42506117045](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42506117045) at source `0c22df32c1023da6f6c24a6ec33470784dc14b8f`. New modules and deployment/CSS changes need current-source native CI. Android earlier basic editors/Keystore/restart/geometry passed, but the complete 40 trusted-touch gate has not passed; the latest Android attempt reaches a basics-stage deadline; it no longer reproduces the older observed GMS death. A deadline does not prove its former cause was fixed or that full native interaction acceptance passed. These are historical, not current-source acceptance badges.
Current host checks used in this work: Mac host 18 tests including 82UI/81recovery/3×50editor assertions and 11 shared alarm checks; Tablet standard web 103 including the small CSS source/AST checks; these use fake native handlers. Native protocol/codec unit tests reported in port docs are source-specific and do not prove physical accounts, file panels, notification delivery or handset/HFP behavior. Every row below requires current native manual/integration validation unless the evidence explicitly says otherwise.

## Functional families (all main product surfaces, not only requested examples)

### Current bounded checkpoint (2026-11-09; Refs #121)

These results supersede the corresponding pending historical entries below;
the inventory table remains tied to its original source snapshot.

- Mac [42562106430](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42562106430)
  at `cbdc0876` passes both complete existing macOS 15 architecture jobs,
  including actual bundle start/save/quit/reopen and candidate packaging.
  Actual handbook load/search/isolation, note-file import, printing/PDF,
  strict drawing replay and calendar reference checks have native evidence.
  The new native restore core (nine tests), ordinary epoch policy (two tests)
  and actual WK restore/model/admission handoff pass in all four suite calls
  per architecture. Three native legacy-alias evidence tests also pass, and
  the drawing pointer-release projection includes the shared correction in #468.
  Each invocation runs 318 tests with zero failures; the four invocations
  explicitly record 3/4/4/5 environment-dependent skips on each architecture. This does not exercise a real restore-file
  panel click, every feature or older macOS runtime compatibility.
- Android API34 [42537601160](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42537601160)
  at `7278298b` passes the isolated services and file-picker jobs. The latter
  includes durable three-collection ICS import, unchanged cancellation, atomic
  invalid-component rejection and an actual 526-byte SAF export with verified
  recurrence and alarm data. Native case-insensitive source VTIMEZONE checks
  also pass. Full provider synchronization is not exercised by these fixtures.
- API26 [42539725882](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42539725882)
  verifies the explicit unsupported-WebView startup diagnostic and visible
  recovery screen for stock Chrome 69. It is an expected negative result,
  not application compatibility acceptance. The update/settings/retry buttons
  and a suitable updated provider on Android 8 remain unverified (#461).
- The latest API34 drawing-only
  [42546084292](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42546084292)
  at `ffd27d00` reaches actual drawing input and fails pixel equality after
  Redo. Its cause is under investigation; the earlier foreign Launcher dialog
  and readiness failures must not be assumed to explain it. The original
  complete 40-touch tablet gate remains open.
- Tablet native restore acceptance (#454), old Android recurrence aliases and
  duplicate repair (#465, following #462),
  full Nextcloud/system-account synchronization and other incomplete native
  adapters remain separate open work. None of the above certifies release
  readiness. The user has authorized publication once required checks pass.

Tablet `Vault.replace` and ordinary saves now use the restore/epoch policy
in `38ce0e85` (#454). The integrated storage/restore tests pass 27 cases with
each of actual AOSP Android JSON and the Gradle JSON dependency, plus the 17
existing Vault tests with their intended Gradle JSON dependency. Shared restore
fixtures remain byte-identical to Mac fixtures. Native Android Keystore/OS
services [run42564834374](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42564834374)
passes epoch rotation, agreement of persisted epoch copies, fresh Vault reopen,
old-page revocation and stale-epoch save rejection. Five additional native
restore durability boundary cases are prepared in `b9e9e4fb`; execution and
full restore-file/UI acceptance remain pending. An independent existing Vault serialization
defect was corrected in `c00b0ff8` (#466). Its native Android services job
[128977490166](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42561105295/job/128977490166)
passes numeric wire save/replacement/reopen, exact generated recovery bytes and
wrong-filename AAD rejection with actual OS storage/Keystore. Exact manufactured
legacy plaintext recovery also passes on the JVM. Native full UI acceptance,
arbitrary-precision parsing and complete synchronization remain separate work.

The later API34 component run42561105295 does not pass files or domains.
The files process is explicitly killed by Android after the Google fonts
provider's process suffers an ANR (#471); this is distinct from an Organizer
crash. Domains fails the unchanged 25-second initialization limit; browser
navigation records DOMContentLoaded at about 29 seconds. Fixed technical
script timings are extended in test-only diagnostics to locate the slow phase.
There is no demonstrated startup correction or completed full tablet gate.

Subsequent run42565577222 at `b9e9e4fb` reaches none of those later UI
assertions: services loses the ADB ownership check before APK installation;
files/domains fail downloading the unchanged Gradle8.13 distribution
(timeout/HTTP504). An independently reproduced FD-enumeration race is fixed
in `5da957de` (#473):58 lifecycle tests pass and a continuously owned listener
under unrelated FD churn changes from188/250 false negatives to0/250. This
establishes the tool correction, not the cause of every previous CI failure.
The native follow-up is
[run42566781256](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42566781256).

The test-only saved-book expectation in `20354edf` (#472) permits just two
empty-string UI epoch placeholders to correspond to absent native slots.
UUIDs, other values, settings, containers and unknown fields remain strict;
actual saved cancellation snapshots still compare without this adjustment.
All31 combined JVM cases pass with both AOSP14 and Gradle JSON, and the actual
projected App/production Vault pair passes the bounded comparison with both.
This changes neither the production epoch policy nor UI/device acceptance.

### Later component checkpoints (2026-11-08; Refs #121)

The table below remains the source inventory at its stated snapshot. Later
implementation and test evidence does not silently upgrade that snapshot:

- Mac: the bundled handbook's actual WebKit load/search/isolation, actual AppKit
  PDF generation, and selected note-file import with durable save/reopen passed
  on both architectures in subsequent component runs. Run
  [42520170252](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42520170252)
  at `200d1c0a` still fails drawing acceptance: trusted events hit the closed
  cover. The real-cover-click test correction is `1f5c9fd0`; its native result is
  pending. Mail/maps/HTTPS launchers now exist (`5de7da08`); real external-app
  handoff remains unverified.
- Tablet: run
  [42520174583](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42520174583)
  at `200d1c0a` passes the APK/JVM/artifact gates and boots each isolated API34
  component emulator. Actual settings, health tables, custom editors, and native
  canvas pixels/vectors with Undo/Redo pass. The domains stage then reaches its
  deadline before complete save/reopen acceptance. SAF cancellation preserves
  the entire book; the next file fixture fails in its separate test process
  because Kotlin runtime classes are unavailable. Services cleanup masks the
  primary exception. Neither component suite nor full UI acceptance is green.
- Read-only Android system-source discovery now exists (`1e580b1b`); native
  provider/permission acceptance and full synchronization remain open.
- Normative timezone data/resolvers (`a2dbc859`, `0ad30bd4`) and Kotlin codec
  migration (`b14d6a9d`) pass independent host checks for 597 IDs and 269,817
  cases. Kotlin-emitted VTIMEZONEs also pass those cases through the published
  Python parser. Installed-APK validation, Swift integration and actual
  frontend/worker migration remain separate pending gates; raw OS Intl rules
  are not repaired by these host results. See issues #447, #452 and #453.
- Existing KDE Connect iOS supports explicit file transfer. See
  [iPhone investigation](../../Magnolie-Organizer-macOS-Beta/IPHONE-INTEROPERABILITY.md).
  This establishes an alternative to publishing a new iOS app, not actual
  iPhone-to-Magnolie acceptance or whole Apple Notes access.

All these are partial, source-bound results. They do not establish complete
feature parity, old-device compatibility, production signing or release approval.

### Native checkpoint at `be3480e6` / `c922053e` (2026-11-08; Refs #121)

This later checkpoint supersedes the pending status of the individual checks
listed here, while preserving the inventory table as its historical snapshot:

- Android API34: the isolated [services job](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42533115056/job/128891477481)
  passes actual native DAV XML parsing, encrypted account/Keystore transactions,
  and Android filesystem durability checks. Hardlink creation was denied by the
  OS; this is not a native exercise of the adapter's multiple-link rejection.
  These fixtures use no live DAV server and do not accept full synchronization.
- The same installed APK passes all eight published calendar cases (11 imported
  and 11 exported records), two Gaza product-codec cases and 30 independent
  normative clock checks through year 8000. It contains the verified 597-zone
  `2026egtz` payload. The legacy Android clock disagrees on ten of the 30
  diagnostic comparisons; its numeric rules are not the product authority.
- The separate Android file-picker job passes cancellation without book changes,
  three-collection import with retained source hash and durable native save, and
  atomic rejection of an invalid later ICS component. It then fails to locate
  the actual DocumentsUI `SAVE` button because the test asks for `Save`.
  Export byte verification has not been reached; this is not export acceptance.
- The ARM Mac at `c922053e` compiles the production calendar-context migration.
  Its seven context tests and three case-insensitive VTIMEZONE structure tests
  pass. The overall job remains red: an editor fixture still expects floating
  values after resolved-system named-zone editing, and strict drawing replay
  detects antialiased edge differences despite identical stroke models.
  Independent calendar-oracle validation and both-architecture acceptance remain
  separate gates. No current all-feature or release acceptance is asserted.

The iPhone route remains explicit exported-file transfer through the existing
KDE Connect app, followed by selected-file import. Public Apple instructions
confirm PDF export on iOS18 and PDF/Markdown export on iOS26; a whole-note PDF
can omit later pages of an embedded scan, so complete original attachments must
be transferred separately. There is no physical iPhone end-to-end acceptance yet.

Subsequent native evidence on 2026-11-08:

- [Android WebView/worker interop](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42534910289/job/128896953006)
  at `1e94748a` passes 148 actual App checks against 37 independent clocks and
  two actual isolated WebView-worker Gaza occurrences, including seconds.
  Native, App and worker identities use the same verified normative payload;
  the book is unchanged. Raw OS Intl comparisons remain separate diagnostics.
- The Intel Mac at `c922053e` completes all 19 independent published-Python
  export checks, all 19 native import/reexport checks and the resource-patch
  oracle. Its overall job still fails the stale editor expectation described
  above. The ARM result is not upgraded by the Intel evidence.
- Drawing correction `61ad9ac6` makes completed strokes use the existing
  canonical replay renderer in both port projections. Canonical Linux/Windows
  sources and strict native image assertions remain unchanged. Host/browser
  checks pass; native run `42535545844` at `2163f88e` is pending acceptance.
  Dense browser drawings show measurable finish latency (about 220 ms for
  100,000 points); no universal native smoothness claim follows.
- Android API26 components at `9e47e97e` and the separate Mac leased-DAV-read
  tests are queued for native execution. Source review and grammar parsing of
  the latter do not establish Swift type correctness or test execution.

Full Nextcloud/system-account synchronization, restore-host integration and the
remaining inventory gaps continue to block an all-feature completion claim.

| Family | Published operations | Mac current scope | Tablet current scope | Actual evidence type | Missing adapter / acceptance |
| --- | --- | --- | --- | --- | --- |
| Binder/navigation | 8 sections, day/week/month pages, page flips, tab order/visibility, modal focus/dirty-editor guard | shared local UI | shared local UI | host editor/navigation; native geometry/basic earlier | native 40 trusted touches, IME/RTL/accessibility, low-end devices |
| Calendar records | Create/edit/delete, all-day/end dates, linked tasks/contact, location, organizer/attendees/calendar attachments | shared UI + native JSON/ICS | shared UI + native JSON/ICS | real editor→writer fixtures, basic Android calendar creation | manual picker/upgrade/real providers; all calendar modes |
| Recurrence | RRULE COUNT/UNTIL/BY*, RDATE/EXDATE/EXRULE, moved/cancelled overrides/RANGE, DST/VTIMEZONE | shared worker + native ICS codecs | shared worker + native ICS codecs | 448 frozen JS oracle +29 contract fixtures; native codec fixtures;17-series host fixture | native recurrence interactions and all exports/sync; no flattened rules |
| Editable/raw reminders | Relative DISPLAY, absolute/read-only alarms, raw metadata and unknown properties/parameters | shared port lossless helper + Swift guard | same helper + Kotlin guard | 11 actual form checks per port incl15→30→45/add/remove/ambiguous atomic rejection | native notification scheduling is a different feature; no repair of already lost raw data |
| Calendar categories/colors | Categories, accent colors, source/calendar scopes and exclusion policies | shared UI projected | shared UI projected | canonical color/group contract tests; port data preservation | actual palette/group CRUD and native export/provider behavior |
| Task graph | Tasks/subtasks, parent IDs/source identity, done/priority/date/time, early/due flags, delegation metadata | local CRUD + ICS; no delegation transport | local CRUD + ICS; no delegation transport | real task editor; source-qualified parent graph import/reopen tests | large hierarchy, edit/undo/deletion/provider sync native acceptance |
| Contacts core | Names/addresses/multiple phones/email, group labels and exclusions, website/social/messenger fields, formatting | local editor; native system discovery only | local editor; no Android contacts provider | actual contact editor + fidelity/group vectors | all field types, actual Contacts permission/read/write; Android provider adapter missing |
| Contact identity/merge | Duplicate detection, groups, aliases, provenance/conflicts, linked anniversaries, personal owner profile | shared local models; external sync missing | shared local models; external sync missing | normalization/identity/consent vectors; data retention tests | native merge/delete/conflict matrix; physical profile/contact synchronization |
| Contact photos | Photo editing/variants/source provenance/import-preview/history/media handoff | local views/raw data; native source/launch gaps | local views/raw data; new picker/provider gaps | shared canonical photo/identity contracts only | actual native photo/file picker, historical paths, provider image acceptance |
| Communication launchers | Mail, maps/routes, social URLs, letters/fax/system applications | unsupported except text clipboard/attachment Save | disabled/rejected external launchers | negative bridge/capability host assertions | platform NSWorkspace/Intent/handler adapters + real app handoff |
| Notes and notebooks | Plain/rich text, notebooks/groups, move/search/selection, timestamps/identity/merge and selected file import | local CRUD/store plus additive selected TXT/literal Markdown/PDF/image note import; native picker acceptance open | shared local CRUD + atomic store | actual note editor/normalization and reopen tests | native long-note/IME/keyboard/Undo/accessibility and merge acceptance |
| Notes attachments | Embedded PDF/image/document data, file/path references, adding/opening/saving attachments | selected data-URL Save and selected PDF/image note import; no generic Open | embedded data retained; new WebView picker unsupported | whole-JSON preservation + selected export cases | actual picker/open handlers, unsupported MIME/URI/file capabilities |
| Drawing | Canvas strokes/tools/eraser/history/zoom/stylus/image drawing + SVG/PDF exports | shared drawing UI; native external exports incomplete | shared drawing UI; native external exports incomplete | source projection + shared drawing code only; no broad native drawing pass | physical stylus/touch, image import, save/reopen, per-format native exports |
| Selected note send | Selected notes to PDF/email/fax recipient handoff; identity-bound send jobs | native adapters missing | native adapters missing | published contracts only; port commands reject | PDF generation/recipient app/handoff/cancellation native acceptance |
| Anniversaries | Birthdays/custom types, unknown year/leap dates, contact-derived entries, exclusions | local CRUD + ICS | local CRUD + ICS | shared date/ICS native fixtures | native edit/list/notification/group acceptance; no background anniversary scheduler |
| Planner | Year/month layout, search/holiday/birthday marks, monthly appointment preview, print/ODS | shared local UI; isolated print source implemented, native acceptance open; ODS missing | shared local UI; print bridge only, ODS missing | host rendering/recurrence contracts; no full physical acceptance | export fidelity/pagination, native interactions/low-end render responsiveness |
| Shift/cycle/day marks | Shift definitions/assignment, menstrual/cycle markers/prediction, per-day quick actions | shared local UI/data | shared local UI/data | canonical models; legacy color fallback AST tests | real CRUD/projection/filter/restore/native exported report matrix |
| Vacations | Inclusive ranges, symbol/text display, overlap/search/calendar marks | shared local UI/data | shared local UI/data | canonical model/data retained | actual native CRUD/overlap/export/restore acceptance |
| Waste calendars | ICS/CSV import-preview, source identities, bins/colors/dates, holiday authority/batch dedupe | shared model; unsupported waste-import native bridge | shared model; unsupported waste-import native bridge | published waste/authority contracts; port unsupported paths | native waste file picker/parser/preview/commit and yearly refresh |
| Time tracking | Enable/timer/activity, start/end/break, timezone/DST, reports, history, conflicts, native Notes timer links | local projected; ODS/background/device adapters absent | local projected; ODS/background/device adapters absent | canonical v7/time-control contracts; not all ports exercised | native timer/restore/DST/report/remote Notes receipt acceptance |
| Health vitals | Vital records, reference status, units/BMI/history/statistics/graphs/print | shared local forms/models; native reports incomplete | shared local forms/models; Print bridge only | host section renders; no comprehensive native health matrix | actual CRUD/charts/units/restore and all print/ODS/export paths |
| Health glucose | Glucose readings/unit conversion, insulin schema/dose calculation and flags | shared local projection | shared local projection | canonical model/contracts only | native field validation/calculation/history/save/reopen/report matrix |
| Health medication | Medication schedules/administration/history and optional external search | local projection; medication lookup missing | local projection; lookup disabled | no complete native medication acceptance | external service adapter + local schedule/record/report validation |
| Custom designer | Four types: appointments, notes, tasks, drawing;2 pages, ordering, legacy conversion, per-module identity | shared designer/local models | shared designer/local models | Android basic actual custom editor; common identity/revocation vectors | all four designer types, page/limits/reorder/delete/persist/device sizes |
| Custom reminders/sync | Explicit custom consent, per-module reminder switch, custom entity provenance/device sync | open-session limited check; no device sync | one-off custom AlarmManager; no device sync | custom consent revoke/resume and source-qualified IDs host gates | native recurrence reminders and remote content/receipt/consent acceptance |
| Search/selection | Section-aware search, filters, exclusion lists, selection/batch actions | shared local UI | shared local UI | shared host render/search logic only | native keyboard, pagination, batch error/dirty guards |
| Trash/undo/merge | Soft delete, restore, purge, structural merges, retained tombstones | private destructive checkpoints; no desktop indexed journal | pre-change backup on replacement; no complete recovery UI | durable save/recovery protocol tests; some local deletion cases | native full deletion/undo/conflict/recovery matrix; unsaved editor recovery separate |
| Private persistence | Whole document/unknown fields, atomic write/fsync, session/revision authority, crash/readback | native encrypted/plain profiles/private lease | native Keystore AES-GCM only | Mac earlier actual save/quit/reopen equality; Android basic encrypted readback/restart | current source native gates, disk-full/kill/upgrade/private permission acceptance |
| Encryption/lock lifecycle | Desktop envelopes, password enable/change/remove, backup rekeying/lock policy | v1/v2 read-write+enable only; change/remove/rekey absent | Keystore vault + portable password backup; no desktop password-lock lifecycle | public crypto vectors, tamper/fence tests; legacy API work separate | native key lifecycle, wrong/cancelled passwords, lost key, retained old recovery encryption |
| JSON backup/restore | Complete JSON with unknown fields/attachments; encrypted export; explicit full replacement | native Save/OpenPanel + snapshot; no partial/additive restore | SAF encrypted JSON + pre-change snapshot | host request/save/error/restore generation fences + codecs | actual file panels/SAF/restore failures/backup portability |
| Complete archives | Published .magnolie multi-file archive/settings/attachments and ZIP/Takeout bundles | no native complete archive adapter | no native complete archive adapter | explicitly unsupported, not equivalent to JSON backup | full bounded format/picker/selective merge/preservation implementation |
| ICS interchange | Appointments/tasks/anniversaries, source headers, calendars, recurrence/raw/tz/context | native Swift import/export + shared merge | native Kotlin import/export + shared merge | 8 independent published codec fixtures/native tests, real shared UI imported-save golden | manual file panels/SAF, all repeated/edited alarm cases on current native candidates |
| Other interchange | vCard, Lotus CSV/OR6, calendar CSV, Claws XML/LDIF, typed contact export fidelity | native adapters absent | native adapters absent | published source/contracts only | all bounded codecs/pickers/preview/revision/roundtrip integration |
| Print/PDF | Calendar/contacts/notes/health/planner/custom/year/month previews and pagination | isolated JS-free WK print renderer implemented; native acceptance pending | separate script-free Print WebView; Save as PDF via OS | shared preview + native source present, spooler acceptance pending | real pagination, font metrics, crop/RTL, save/cancel/result semantics |
| Office output | Addresses/planner/health/time ODS and letter/LibreOffice layout/profile integration | native bridge absent | native bridge absent | negative command coverage only | format fidelity, native save/open apps and actual office handoff |
| Regional preferences | 20 UI languages, format locale/timezone/units/week/hour/country | native persisted local preferences | native persisted local preferences | save-ACK/double-click/failure/localization host tests | actual old OS locale/RTL/VoiceOver/TalkBack/native translated dialogs |
| Native timezone management | Automatic system zone discovery/revision-bound refresh and source/contact display policy | management explicit limitation; auto refresh suppressed | native desktop management disabled; auto refresh suppressed | local timezone display/codecs pass; unsupported native controls tested | OS observers/permission/context snapshots and atomic setting updates |
| Public/school holidays | Native HTTPS country/region/language/inclusive dates/grouping/cache filtering | native bounded HTTP + canonical callback | native bounded HTTP + canonical callback | mock service limits/cancel/error; earlier Mac live public HTTP both architectures | real school regions/native full UI/offline/retry/current candidate acceptance |
| Weather | Location/geocode/current/forecast preferences and native data callback | native weather adapter absent | disabled; native weather adapter absent | canonical UI only | provider/native fetch/cache/permission/localization/error implementation |
| Accounts/system providers | Linux EDS/Akonadi/Thunderbird; Windows providers; calendars/tasks/contacts selection | EventKit/Contacts permission/read facade + source GUI; no full sync | no Android Calendar/Contacts/AccountManager adapter | Mac passive/source facade protocol tests; native permissions unaccepted | OS-specific grants/import/edit/delete, unavailable source retention, real account acceptance |
| DAV/Nextcloud | Config, credential vault, CalDAV/CardDAV/task collections, ETags/conflicts/deletions/commit | native setup/discovery/Keychain/protocol/typed snapshot; no coordinator | native setup/discovery/Keystore/protocol; no coordinator | protocol/TLS/credential/CAS tests, actual account GUI mock host gates | real server/provider matrix + complete record sync/atomic local commit/conflict policy |
| Graph/managed accounts | OAuth/device-code/Google/Microsoft365/Outlook/EAS provider workflows | native adapters absent | native adapters absent | explicit unsupported calls; tagged managed-account contracts | native auth/token vault/cancel/revoke/provider sync and physical account acceptance |
| Magnolienbaum | Discovery/pairing/documents/QR/trust/invites/sharing/delegation/introduction/inbox/deletions | native peer transport/coordinator absent | native peer transport/coordinator absent | tagged protocol/consent contracts; ports reject | native encrypted sessions, device identities, receipts, consent and real two-device validation |
| Own Notes/personal sync | Owner binding, initial/directional/manual sync, notes/tasks/contacts/custom/time, restores/proposals/receipts | native phone/peer adapter absent | native phone/peer adapter absent | shared identity/consent/source codecs only; no port transport acceptance | Notes-native save receipts, version-negotiation and all ownership/restore/cancel paths |
| Phone lifecycle | Wi-Fi invitation/ports, Bluetooth RFCOMM discovery/pairing, own-device grants, auto reconnect/service lifecycle | native phone adapter absent | native phone adapter absent | published phone setup/content/region/diagnostic contracts only | platform transports/identity/grants/background lifecycle and real handset acceptance |
| Phone content/device status | Fresh device state/temporary identifiers/contacts/photos/profile/group values/media/file batches | native adapter absent | native adapter absent | published contracts/vectors; no port physical transport | nonce/source/revision-bound replies, no stale status caches or fabricated empty providers |
| SMS/chat/plans | Recipient/country/GSM exact preview, history, scheduled plan approval/restore/pause/review/durable handoff | native SMS adapter absent | controls disabled/rejected; no direct Android SMS permission | published SMS review contract; capability-negative host tests | shared plan invariants + native phone-session sends/receipts; actual SIM/device delivery |
| Calls/audio | Call status/actions/outgoing origin refs, confirmed incoming answer/reject, HFP PC audio routing | native call/HFP adapter absent | native call/audio adapter absent | published call origin/audio contracts only | OS-specific audio route evidence/grants/source lifecycle; no RFCOMM-as-HFP claim |
| KDE Connect | Device lifecycle/pairing, receive preferences, files/batches/media, clipboard, notification, command/UI tools | native KDE adapter absent | native KDE adapter absent | tagged KDE contracts + desktop implementation references | platform KDE DBus/plugin availability, honest unsupported paths, bound receipts/physical device |
| KDE system controls | Volume/media/player/touchpad input/system status actions via explicit capability grants | native adapter absent | native adapter absent | published system volume/native control contracts | actual OS endpoint/control receipts and takeover/cleanup rules |
| Background/tray/autostart | Status item/tray counters, foreground/daemon ownership, locked startup, services/wake | native lifecycle/scheduler absent | no desktop daemon/tray; receivers only for supported one-offs | limited app lifecycle/receivers; not desktop equivalence | closed-app delivery, crash/upgrade/restart/dedup/wake/platform scheduling |
| Cloud backups/journal | Remote encrypted backup/retention/index/automatic jobs and section restore | native adapters absent | native adapters absent | local JSON checkpoints are not cloud/journal parity | native cloud transport, retained encryption, full recovery/rekey/cleanup acceptance |
| Spelling/editing | Native dictionary/spelling suggestions/learn word, context menu/Undo/Redo/formatting | shared editing; platform spelling bridge absent | shared editing; desktop spelling disabled | 20-language key/help and real host editor tests | native dictionaries, IME/composition, shortcuts and actual clipboard handlers |
| Manual/help/update/about | Bundled multilingual handbook/search/external links, version/download updates, contributor/protected assets | new isolated bundled handbook implementation; updates/trust roots absent | manual/update/contributor controls disabled | Mac manual content source/tests newly prepared, current native acceptance pending | manual actual WK navigation/search/fonts + signed update trust/rollback/release policy |
| MCP/automation | 210 literal Organizer tools plus computed routers/action schemas, native save/receipt/approval boundaries | no native MCP server/stdio/socket adapter | no native MCP server/stdio/socket adapter | published tool contracts; local helpers not exposed as public native tools | authorized server/session/tool registry/cancel/atomic native results for each operation |
| Developer diagnostics | Opt-in version/crash/native phone diagnostics; technical source-bound snapshots | limited native app diagnostics; phone diagnostic adapter absent | bounded startup telemetry; phone diagnostics absent | native test technical markers; no document-data logging | physical/native source/version binding, user opt-in and no private data leakage |
| Localization/fonts/accessibility | 20 locales, RTL, bundled fonts/icons, reduced motion, hit targets, focus/tab/help | projected UI + native catalog; incomplete English beta prose | projected UI + native labels; incomplete beta translations | host catalogs/font-byte equality; small legacy CSS AST gates | human locale review, real VoiceOver/TalkBack/contrast/scaling/pointer/keyboard |
| Release/platform support | Signed installers/notarization/update trust, ARM/Intel/Android ABI+OS+engine/device matrix | debug/ad-hoc test candidates; current native changes need CI | debug APK candidates; current native gate incomplete | older native candidates only, source hashes and deployment guards tracked | build/install/upgrade/run/manual all-feature device matrix before public stable claim |

## Persisted state and settings completeness

All tagged book root keys: `version`, `termine`, `aufgaben`, `kontakte`, `notizen`, `customOrganizer`, `zeiterfassung`, `notizgruppen`, `notizbuecher`, `jahrestage`, `feiertage`, `urlaube`, `muelltermine`, `papierkorb`, `personen`, `schichten`, `smsVerlauf`, `smsPlanung`, `zyklusmarker`, `tagmarken`, `gesundheit`, `einstellungen`, `letzterSync`, `letzteSyncs`, `syncStatus`, `baumKontaktGeloescht`, `baumKontaktBestand`, `baumKontaktLoeschStaende`, `baumKontaktErfolgreich`, `baumKontaktAblehnungen`, `kontaktImportAblehnungen`, `personalSync`, `geloescht`, `syncEpoch`, `syncMetadaten`.

All settings groups: `sync`, `ort`, `allgemein`, `update`, `regional`, `schrift`, `ansicht`, `erinnerung`, `adressen`, `versand`, `sicherheit`, `papierkorb`, `kalender`. The tag stores regional controls within settings even though its native settings-tab list differs from port-exposed regional UI. SMS history/plans, personal provenance/proposal/tombstone/register state and provider sync state are preserved data, not evidence that the matching transport runs in a port. Health stores vital/glucose/medication/insulin sections; Custom types are appointments/notes/tasks/drawing (legacy note/checklist/recurrence blocks convert into these).

## Full wire-command and helper appendices

[Complete command appendix](BRIDGE-ACCEPTANCE-2.0.30.md) contains every 206 inventoried outer command with release JS/C#/Python provenance and a separate per-port implementation status. The disposable source-index JSON (kept outside the repository) additionally contains every named-function source/line, all literal MCP tool names, App callbacks, all 64 contract paths, model/settings keys, unresolved computed routing and source hashes. This is the auditable exhaustive source index behind the grouped table; it is not a claim that internal helper count equals supported feature count.

Acceptance rule: for each supported operation, bind candidate bytes/source, install/upgrade, exercise the actual platform UI and permissions/handlers, verify durable saved/reopened output and failure/cancellation/conflict behavior. Unsupported operations must stay explicit. A unit-test pass or populated shared view does not close any missing-native-adapter row. Root owns public issue/release decisions; no production release was made by this inventory.

## Snapshot bindings

The published source is v2.0.30 (`067c38934b539943d8e1720abafd8a80b401d797`); current capability mappings read the committed port source at `0288d99f7dcd4b366748b8c36338edd1dbcafb49`, including the CSS fallback commit113863cf. Uncommitted native compatibility work is not certified by these rows.

| Committed port source | SHA256 |
| --- | --- |
| `Magnolie-Organizer-macOS-Beta/Sources/BetaCore/Contract.swift` | `dcc15b0b4e2120e37ecd501340c0a0f4a85e7d7854e00278bcf4b3fea7678357` |
| `Magnolie-Organizer-macOS-Beta/Sources/MacBeta/main.swift` | `abc8b2bce32ba1aa0c167539982a1e5d5de1accb12f2dbe6889d64aa3d9fb237` |
| `Magnolie-Organizer-macOS-Beta/Projection/macos-beta.js` | `8053c783199b69e7620b1362b719de88db07f4f460956876442a4904963a4dea` |
| `Magnolie-Organizer-Android-Tablet-Beta/web/tablet.js` | `232a93f0643056cc9199db0030febcadc9ff7350a9aed698bdc096d435c3ad43` |
| `Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/MainActivity.kt` | `ee3d87b60ea336d8c79911f0987ee9c354ada4de0612de42ec07a34fdf1f14d1` |

Full 1,364-function/210-tool/source-location JSON stays in the execution scratch evidence; it is intentionally not a large generated product/document payload. The human matrix and 206-command appendix are the reviewable repository record. No blanket pass claim is made for all operations or platforms.

## Narrow shared-style follow-up

[Issue #446](https://github.com/maik3531/Magnolie-Organizer/issues/446) records the source/engine-specific color-mix and WebKit selection fallback gap. Port patch113863cf is implemented and host-checked; old-engine native rendering remains untested. The Tablet-only vh/dvh fallback is explicitly separate from canonical Linux/Windows source findings. This is not a general current-Linux/Windows functional defect claim.

The committed snapshot also includes Mac note-file import0288d99f:29 Mac allowlisted command scopes versus23 Tablet scopes. This is additive TXT/literal Markdown/PDF/image preview/recovery/save source, not current native picker acceptance or complete general format parity.

The outer-command union now has206 rows because the native-only Mac note-file picker adds one port-specific command; the published-source JS/C#/Python counts remain137/182/176 respectively. The appendix flags source provenance rather than calling every extension a released2.0.30 command.
