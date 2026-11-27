# Magnolie Organizer macOS Beta

Parallel development port, not a production release and not feature-equivalent to
the Linux/Windows native applications. The current follow-up is documented in
the [stability verification report](STABILITY-VERIFICATION-2026-11-26.md), with
the tested source anchor, retained failures and the plan for later integration.
The extended [run #104](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062)
completed with **`success` on both ARM64 and Intel** at
`3f3ec069895dec254c53660d14e6851cb23077cd`. It ran on 26 November 2026,
**14:15:18–14:49:42 Europe/Berlin** (13:15:18–13:49:42 UTC). The
[durable #104 evidence](verification/native-run-104.json) binds this result to
that source commit, independently of later documentation commits.

| #104 evidence, per architecture | Result |
| --- | --- |
| Runtime / AirPlay / ImportHelper tests | 26 / 27 / 17 passed, no skips or failures |
| Host suite | 34 passed, one Linux-only skip, no failures |
| Swift Debug contexts | Four contexts of 501 cases, with 4/5/5/6 skips and no failures |
| Optimized Swift Release context | 501 cases: 495 passed, six skipped, no failures |
| Original Swift → packaged private Python process | All nine checks passed; 22 original OR6 fields in four collections |
| Real app initialize/save/normal-quit/reopen smoke | All seven criteria passed |
| Independent candidate byte audit | All 65 checks passed; 3921 bound source files, 555 projection inputs and 1312 outputs |

The same 501 XCTest names recur across the five contexts; these are not five
independent sets of cases. Both packaged apps remain **ad-hoc Debug development
candidates**. The process probe exercises the actual production process and
packaged interpreter/helper without a picker, editor or saved book. The separate
fresh-profile smoke does not establish imported-data persistence, full UI/TCC
acceptance, Monterey execution or production-release approval.

The preceding complete current-source native CI pipeline passed for Apple
Silicon and Intel in
[Actions run #97](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
at `215d89029df02df2dce78f35412785ec9f9b36d8`: private CPython build and
relocation, Swift/core/WKWebView tests, strict ad-hoc bundle signing, the real
app's start/save/normal-quit/reopen/data-preservation smoke and development
packaging. Both jobs used that exact commit for the shared and Mac sources.

The [historical native verification report](NATIVE-VERIFICATION-2026-11-26.md) and
[durable machine-readable evidence](verification/native-run-97.json) record
the exact environments, results, skips, package hashes and evidence boundaries.
The CI artifacts expire on 10 December 2026; their durable records remain in
Git. Later source changes require their own applicable checks. Full feature,
Monterey, permission, account/device, upgrade, accessibility and distribution
acceptance remains incomplete. Do not use the only copy of important data
with this Beta.

The canonical directory is `Magnolie-Organizer-macOS-Beta` beside the existing
Linux and Windows source directories. Shared product sources, dependency declarations and the Windows release workflow
remain the canonical references; #776 intentionally fixes their shared contact
contract. The dedicated candidate workflow builds this port separately.

## Identity

- Version: **`2.0.30-beta.1`**. See [POLICY.md](POLICY.md) for numeric bundle versions and release boundaries.
- App name and executable: `Magnolie Organizer macOS Beta`.
- App bundle: `Magnolie Organizer macOS Beta.app`.
- Identifier: `io.gitlab.maik3531.MagnolieOrganizer.macOSBeta`.
- Data: `~/Library/Application Support/io.gitlab.maik3531.MagnolieOrganizer.macOSBeta/organizer.json`.
- Development output and exported filenames include `macOS Beta`.
- No stable Windows, Linux or Notes profile is discovered, imported or reused automatically.

The existing `2.0.30-beta.1` display identity is retained for this review branch.
#783 changes Mac candidate builds to the exact current checked-out source,
instead of restoring the released 2.0.30 desktop tree. The version label is
therefore not a source proof. This remains a partial macOS Beta; the projection
and candidate manifests record the actual commit and input hashes. See
[the complete issue handoff](../contracts/macos-issue-handoff-2026-11-26.md).

## Target systems and validation

The deployment target is **macOS 12.7 (Monterey) or newer**, for Intel x86_64
and Apple Silicon arm64. This includes a target for many 2016 Intel Macs whose
last officially supported system is Monterey; individual models and future macOS
versions still require verification. Use the artifact matching the processor.
This is a build target, not a Monterey compatibility certification. Native evidence
currently comes from macOS 15 on both architectures; startup, bundled WebKit,
permissions and full feature behavior on macOS 12.7 have not been tested.

The SDK compiler retains availability checks. EventKit uses the legacy permission
API below macOS 14 and full-access APIs only behind its macOS 14 guard. CryptoKit,
CommonCrypto and the existing TLS policy stay unchanged. The builder pins 12.7
and verifies the executable's Mach-O minimum OS as well as the bundle metadata.
#806 additionally requires exactly one unambiguous macOS deployment command;
matching CPU/minimum values alone do not establish the Apple target platform.
Swift concurrency is supported on this deployment target; no user-installed Swift
toolchain is required to run the bundle. A current SDK/toolchain is required to build.

## Implemented Source

| Area | Current Scope |
| --- | --- |
| Desktop interface | Entire canonical Linux web tree, styles, fonts, symbols and catalogs projected by generator, not a separate hand-maintained organizer UI |
| Handbook | Current canonical handbook bundled byte-for-byte, including languages, search and assets; separate nonpersistent local WKWebView, no Organizer bridge; user-clicked HTTPS links open in the system browser |
| Shell | AppKit window, WKWebView, application/edit menus, save-before-quit handshake |
| Bridge | Main-frame/local-document check, randomized handler name, typed native allowlist, explicit negative results |
| Local data | Whole JSON text, private profile lease, 0700 directory/0600 files, atomic same-directory replacement, file and directory synchronization, external-change detection |
| Unknown fields | Preserved during generated UI normalization; field/record-removing saves require a durable pre-change copy |
| Encryption | Desktop v1 read/v2 read-write, AES-256-GCM, PBKDF2-SHA256, retained v2 data-key wrapper and envelope extensions |
| Password controls | Enable encryption for current profile only; native confirmation; no removal/change/rekey transaction |
| Backup | Full encrypted JSON document via native Save dialog, including embedded attachments and unknown fields; not the multi-file Gesamtarchiv format |
| JSON import/restore | Native selection pins path and bytes; current UI normalizer preflight; full replacement after pre-restore copy; current encryption retained |
| Recovery/deletion | Shared recycle-bin/contact-delete logic; token-correlated checkpoints; private exact-byte JSON files readable after restart |
| Language/keyboard | Shared regional page enabled and durably saved; generated native gettext catalogs; Command+digit sections, Command formatting, Undo/Redo menus |
| Export | Source-preserving appointment/task/anniversary ICS, recurrence/exceptions and historical/future timezone definitions; unsupported or contradictory records fail the whole export |
| File imports | #785 projects the actual current OR6 and classic-format parsers, packages a private Python runtime and binds the native selection to the shared merge and durable Save-ACK. Runtime build, relocation and 17 ImportHelper/path tests passed on both native architectures in #104. Its nine-check probe also exercises the unchanged production Swift process with the actual packaged private interpreter/helper and original OR6 data. The separate 90 OR6-to-UI checks use synthetic native transport; actual picker/import/save/reopen acceptance remains open. See [IMPORT-CODECS.md](IMPORT-CODECS.md) and [IMPORT-RUNTIME.md](IMPORT-RUNTIME.md) |
| Clipboard/attachments | Text clipboard; attachment Save for PDF/JPEG/PNG/GIF/WebP data URLs, not automatic attachment opening |
| Reminders | Open-app checker with independent one-off early/due task reminders, connected to permission-gated macOS notifications; no persistent scheduler |
| macOS calendars/reminders/contacts | Native explicit OS access, async discovery and canonical source selection; #770 adds reviewed single calendar copies, #775 local contact copies and #777 selected reminders as independent local tasks. Each preserves existing records and requires a fresh source read plus durable save. Native validation, complete reminder fidelity and full synchronization remain unfinished; see [SYSTEM-CALENDAR-IMPORT.md](SYSTEM-CALENDAR-IMPORT.md), [SYSTEM-CONTACT-IMPORT.md](SYSTEM-CONTACT-IMPORT.md) and [SYSTEM-REMINDER-IMPORT.md](SYSTEM-REMINDER-IMPORT.md) |
| System-account field sync | #786 separately prepares explicit source/book binding and manual updates in both directions for supported Calendar/Reminders/Contacts fields, with conflict handling and an encrypted recovery ledger. No automatic adoption of copies, new native entries, deletes, series or background sync. Current Swift compilation and applicable CI tests passed in #104; actual provider/account/TCC/UI acceptance remains open. See [the complete field contract](../contracts/macos-786-native-system-sync.md) |
| Apple Notes | #772 adds direct NSAppleScript source for selected local plaintext copies with full text review, exact native identities, source reread and durable save; no extra app or source writes. Current Swift compilation and applicable CI tests passed in #104; actual Notes Dictionary/TCC/account/device acceptance remains open. See [APPLE-NOTES-IMPORT.md](APPLE-NOTES-IMPORT.md) |
| DAV accounts | Canonical native configuration, Keychain credentials, revision-bound verified save/rollback and explicit collection discovery; 19 native account tests |
| DAV calendar foundations | Complete typed REPORT snapshot decoding and surgical component edits preserving resource siblings; native tests pass on both architectures; no record-sync coordinator yet |
| iPhone AirPlay receiver | Source-integrated UxPlay receiver, native Start/Stop/PIN panel and self-contained bundle build; no separately installed receiver required. The 27 boundary tests passed on both native architectures in #104; building the optional receiver and testing an actual iPhone counterpart remain separate open checks (see [AIRPLAY.md](AIRPLAY.md)) |

"Implemented source" is not a statement of native build or runtime validation.
Current-source integration and the remaining macOS/Android Organizer parity work
are tracked in [issue #121](https://github.com/maik3531/Magnolie-Organizer/issues/121).
[Issue #9](https://github.com/maik3531/Magnolie-Organizer/issues/9) is the historical
source checkpoint, not a completed native parity acceptance.

## Important Limits

- Creation/editing/deletion uses the desktop UI. Before a save removes existing
  fields/records, the exact previous file is copied into `Recovery-macOS-Beta/`
  under the private profile, synchronized and read back. Failure blocks the save.
  The shared contact mutation handshake also creates a checkpoint before acting.
  Lossy **load normalization** is still refused. There is no automatic selection
  of a recovery file or silent empty-profile fallback.
- A failed save leaves the current edits visible but not necessarily durable.
  Closing is cancelled when the UI reports save failure. There is no recovery
  journal for every edit or crash recovery for unsaved UI edits. Recovery copies
  cover pre-destructive changes and restores, not every non-destructive save.
- New profiles start without password protection, with private filesystem
  permissions. Enable encryption in Security before handling sensitive data.
  Encrypted profiles never fall back to plaintext on unlock failure. Enabling
  encryption does not securely erase old filesystem blocks or external copies.
- Backup export uses current encryption or asks for a separate backup password.
  Existing external backups and local recovery files are not rekeyed. A recovery
  file from a plaintext profile remains plaintext (0600 in a 0700 directory),
  even after encryption is enabled. Keep original passwords for older copies.
- JSON restore is **complete replacement**, including settings and embedded data.
  It is not additive import, selective restore, or `.magnolie` Gesamtarchiv import.
  The selected file is rechecked before commit and the current desktop normalizer
  must accept it first. An encrypted current profile retains its current password;
  an encrypted import into a plaintext profile adopts the imported encryption.
- Recovery files have no automatic expiry, pruning, index, or scheduled snapshots.
  Restore them with the same JSON picker. They consume disk space until explicitly
  managed by the user; disk-full/native APFS crash behavior still needs Mac testing.
- #785 replaces the ICS-only selected-file route with the current parsers for
  ICS/VCS/LCS, OR6/CSV, vCard/CSV, Claws/LDIF, ZIP and waste dates. Parsing runs
  off the UI thread, with an app-owned interpreter, byte-bound protocol and
  manifest identity. The canonical importer still owns conflict previews and
  merging. Full `.magnolie` archive import and discovery of local programs remain
  separate documented work. The earlier native ICS evidence does not establish
  actual picker/import/save/reopen validation of this new pipeline. The private
  runtime's native build, isolation and helper tests passed in #104, together
  with the nine-check production Swift-to-packaged-Python process probe. That
  probe checks public fixture data and rejection cases without a picker, editor
  or durable import save.
- The new EventKit calendar-copy path (#770) is a bounded local import with a
  source/date picker, preview, re-read and durable save acknowledgement. It does
  not enable automatic updates or writing back to Apple Calendar. Rich or
  ambiguous records are listed as exclusions. Actual provider/TCC/UI execution
  remains unverified; current Swift compilation and applicable CI tests passed.
  JSON backups preserve the new provenance fields, while strict ICS export of
  these provenance-bearing copies remains blocked pending a complete codec.
- ICS exports retain source recurrence/exception/timezone properties and validate
  structured times against them. Tasks and anniversaries have dedicated export
  kinds. Unsupported or conflicting data aborts the complete export. Independent
  roundtrips use the published 2.0.30 Python codec and pass on both architectures.
  Import preserves source-qualified task aliases. Combined export of colliding
  external task UIDs from different sources still rejects explicitly; export
  those sources separately or use JSON backup for the complete profile.
- Native ICS entry points receive an explicit immutable timezone context from
  the SHA-verified bundled 2026egtz database. Each operation captures the current
  system identifier anew; OS numeric rules are not a fallback. Source VTIMEZONE
  definitions take priority, opaque UID/TZID bytes stay distinct, and Gregorian
  arithmetic has no 1582 cutover. Native compilation, the calendar codec and
  UTC/Berlin live-editor Swift contexts passed in #104 on both architectures.
  Their actual contexts and skips are recorded in the stability report; they do
  not replace picker/UI or Monterey acceptance.
- A one-off task's "Custom notification" (1 through 7 days before) is independent
  of "remind me on the due date". Both may be enabled. Early times use calendar
  days in the source timezone, not a fixed 24-hour duration across DST. Global
  reminders, Custom module/item consent, the unlocked profile and native menu
  consent remain separate gates. The existing five-minute open-app polling window
  is retained; this is not a missed-alarm/background delivery service.
- Supported one-off task `DUE` properties must agree with the stored display
  date/time. UTC and IANA zones are supported; contradictory/invalid zones fail
  closed. DST gaps are skipped, the first fold occurrence is used for ambiguous
  floating wall times, and explicit UTC can identify the second occurrence.
  A skipped early gap does not suppress a valid due alarm. Recurrence, custom
  VTIMEZONE definitions and rich task VALARM scheduling remain unavailable.
- Notifications require an explicit application-menu opt-in each session. Text
  may appear on the macOS lock screen. The Beta uses the macOS system presentation,
  not the desktop custom notification window. No wake, closed-app delivery,
  restart deduplication, recurring-occurrence scheduling parity or delivery
  guarantee is claimed. EventKit "reminder lists" and Magnolie notifications are
  separate features.
- The native system-source page discovers EventKit calendars/reminders and Contacts
  containers through macOS permissions. Discovery does not prompt; explicit buttons
  request access. Missing/revoked sources retain their saved selections. Complete
  system synchronization is unfinished. The legacy desktop sync action remains
  unavailable; #786 exposes the separately bounded manual field-sync route.
- Public/school holiday retrieval uses a bounded native HTTPS service and the
  canonical cache importer. DAV account configuration and explicit discovery use native Keychain storage and
  verified rollback. Complete Nextcloud synchronization and conflict/deletion
  transactions remain unfinished; successful setup is not a synchronization ACK.
- Printing renders an immutable selected HTML snapshot in a separate ephemeral,
  JavaScript-disabled WKWebView with no native bridge, network or local-file access.
  AppKit supplies the system print dialog and its Save as PDF action. The native
  PDF-engine test does not establish manual print-panel or physical-paper acceptance.
- No Graph sync, Magnolia tree, phone data sync/SMS/Bluetooth, weather download,
  tray/background service, autostart, scheduled backup, office export,
  complete archive/local-program import, updater, manual downloader, contributor validation or
  native protected-image rendering is implemented.
- The separately developed iPhone AirPlay receiver requires the explicit
  [AirPlay bundle build](AIRPLAY-BUILD.md). Its source integration does not imply
  a native build or iPhone acceptance. AirPlay supplies screen/audio; calendar,
  reminder, contact and Apple Notes connections are documented independently in
  [IPHONE-INTEROPERABILITY.md](IPHONE-INTEROPERABILITY.md).
- Unsupported desktop controls retain an explicit Beta limitation notice or
  receive a negative response. They do not signify native feature parity.
- This is a non-sandboxed development shell, not a hardened/notarized distribution.
  CSP and WKWebView navigation restrictions block remote content; the bridge
  cannot run arbitrary shell commands or accept arbitrary profile paths.

## Using The Local Features (development candidate)

1. Security → **Create backup** waits for the save acknowledgement, then uses a
   native Save dialog. Plain profiles prompt for a separate backup password.
2. Security → **Restore backup …** accepts a full plain/encrypted Organizer JSON
   file. The existing desktop dialog explains replacement and requests its password.
   Cancel, wrong password, changed selection or failed preflight cannot commit it.
3. The picker opens `Recovery-macOS-Beta/` when recovery files exist. These files
   use the same restore flow; a new pre-restore copy protects the current file.
4. **Language and regional display** exposes the existing shared regional editor.
   Save persists the choice; restart applies language/timezone/native menus fully.
5. Standard Command shortcuts and shared modal focus/escape behavior are connected.
   Native VoiceOver and WKWebView keyboard acceptance remain pending.

See [FEATURE-MATRIX.md](FEATURE-MATRIX.md) and [BRIDGE-COVERAGE.md](BRIDGE-COVERAGE.md)
for explicit native gaps. An allowlist entry is not a parity claim.

## Linux Checks

Prerequisites: Python 3.10+, `cryptography` for the canonical codec fixture tests,
and Node or Deno plus the existing desktop `jsdom` installation for UI host tests.
The tests do not install or change stable dependencies. They report a skipped UI
test explicitly when no usable host runtime/dependency is present.

```sh
python3 tools/project_ui.py audit
python3 tools/crypto_vectors.py --check
python3 tests/test_host.py
```

`MACOS_BETA_JS_RUNTIME` can select a local Node/Deno executable. When using this
shared Linux workspace, set `TMPDIR=/tmp/opencode` and a private `DENO_DIR` beneath
that directory. Python/JavaScript host tests are **not** macOS emulation.

The portable Foundation/POSIX/ICS code has also been tested with Swift on
Linux. CryptoKit/CommonCrypto and AppKit require Apple's SDK; their applicable
native CI tests passed in #104 on both architectures. A Linux host check alone
does not execute or certify those Apple implementations.

For live editor-to-Swift regression tests, set `MACOS_BETA_SWIFT` to a local Swift
executable when running `tests/test_host.py`, or run the focused helper:

```sh
python3 tools/check_editor.py --js-runtime /path/to/node-or-deno --swift /path/to/swift
```

The helper creates current canonical editor records in a disposable projection
and supplies those exact JSON objects to Swift tests. It does not strip raw
fields, commit static editor fixtures, create a freeze or reuse an old payload.
Without `--swift`, it runs only JavaScript checks. Direct `swift test` explicitly
skips the live-editor case unless `MACOS_BETA_EDITOR_FIXTURES` is supplied by the
helper; the other portable cases still execute.

## Frozen Projection

Do not freeze while the main Linux/Windows sources are still being edited.
No frozen snapshot or static organizer payload is committed with this Beta.
Only the thin adapter and deterministic projection rules are maintained here.

After the desktop source owner confirms the intended state is frozen:

```sh
python3 tools/project_import_helper.py --prepare-dependencies
python3 tools/project_ui.py freeze --confirm-desktop-frozen
python3 tools/project_ui.py generate
python3 tools/project_ui.py check
```

`SourceFreeze.json` hashes canonical UI/assets/contracts and projection inputs.
`Generated/ProjectionManifest.json` records both input and output hashes.
Verification also regenerates and compares the output, so manually changing
both a generated file and its output hash is not accepted. Source changes during
generation or after the freeze block further use. Anchor changes require review,
not fallback to an old shipped payload. Generated output is disposable and ignored.

The freeze is a reproducibility record, not an authenticity signature or release
approval. Candidate-source checks additionally bind the actual checkout.

## macOS Development

Requires a suitable real macOS VM, Mac, or macOS CI runner, Xcode
15+ or its Apple Command Line Tools with the macOS SDK, Python 3.10+, and a
macOS host supported by that Xcode version (Xcode 15 requires macOS 13.5+).
The generated application targets macOS 12.7+; the build host may be newer. There are no Swift package downloads. Build only after the freeze steps:

```sh
python3 tools/import_python_bundle.py --download \
  --source-archive /absolute/private/build/Python-3.15.2.tar.xz \
  --output /absolute/private/build/import-python
python3 tools/build_dev.py --import-runtime /absolute/private/build/import-python
```

[CLOUD-MAC-TESTING.md](CLOUD-MAC-TESTING.md) records the actual Linux cloud
environment, investigated VM/xnulinux options and concrete native test steps.
The user's own physical Mac is not required. A modern iCloud-capable test VM
and a separate real 12.7 runtime test answer different compatibility questions.

This runs `swift test`, makes a **debug** bundle for the runner's architecture,
copies the verified UI/resources/licenses, and applies local ad-hoc signing.
It refuses to overwrite an existing output app. It does not launch the app,
build a DMG/PKG/production release, notarize, upload or publish anything.

The candidate workflow additionally checks the actual production Swift import
process with the signed bundled Python helper and an original OR6 fixture,
then runs a separate optimized `swift test -c release --jobs 2` context.
Those gates do not turn the packaged Debug application into a production
release and do not cover the file picker or imported data after save/reopen.
Both gates passed on ARM64 and Intel in #104; their exact source, native
receipts and skips are recorded in the current stability report.

The resulting development path is
`Output/Magnolie Organizer macOS Beta-2.0.30-beta.1/Magnolie Organizer macOS Beta.app`.
Its build record explicitly says native UI validation and production release
are false, even when compilation and Swift tests pass.

On a fresh disposable macOS GUI runner, exercise that exact built bundle with:

```sh
swift tools/smoke_app.swift \
  "Output/Magnolie Organizer macOS Beta-2.0.30-beta.1/Magnolie Organizer macOS Beta.app" \
  /path/to/evidence-directory
```

The 90-second smoke check refuses an existing Beta profile or process. It launches
through LaunchServices, requires a visible window owned by the launched PID,
requests normal Cocoa quit, validates the real fresh profile and welcome note,
then reopens the same bundle and checks data preservation after normal quit.
It does not inject JavaScript or replace the production bridge. A real window
screenshot is included when macOS permits capture; capture unavailability is
recorded rather than replaced with an image. `bundle-smoke.json` distinguishes
this startup/save/reopen evidence from full native feature acceptance.

The builder replaces Swift's automatic ad-hoc executable signature with a new
ad-hoc bundle signature using `codesign --force --sign -`, only in the newly
created output. Strict signature verification remains required. No production
certificate or notarization is used.

The development candidate workflow is
[`ports-2.0.30.yml`](../.github/workflows/ports-2.0.30.yml). It runs manually or on
the dedicated `codex/ports-2.0.30` branch. The Mac job now uses the complete
selected checkout, including its current shared Organizer sources (#783).
`candidate_sources.py` binds the exact workflow commit and tracked-source hashes
before preparation and verifies them again before packaging. It rejects mixed
old/new source trees. Catalog generation precedes the build-local freeze;
generated inputs/output retain their separate reproducibility checks. The
Tablet job and tagged reference fixtures retain their previous source policy.
Host, Apple crypto and real
WKWebView tests must pass before the development app is packaged and uploaded.
The zip includes source provenance and SHA-256 checksums; Actions retains it for
14 days. Its architecture follows the runner and is recorded in the build metadata.
Historical Mac runs, including `42562106430` at port source `cbdc0876`, still used
published desktop source `067c3893`; they are not current-shared-source native
acceptance. See [CURRENT-SOURCE-CANDIDATE.md](CURRENT-SOURCE-CANDIDATE.md) for the
catch-up scope and exact evidence boundary. A shared-source update does not add
a Magnolie Notes companion app or enable unimplemented sync commands. Apple
services and supported existing KDE Connect clients remain separate Mac
integration paths requiring their own implemented adapters and acceptance.

This workflow has read-only repository permissions and creates development
artifacts, not a GitHub Release. A successful WKWebView test is not full production
Host/permission/Gatekeeper acceptance. No notarization or production signing is
provided. The old `ci/macos-beta-manual.yml.example` remains an inactive historical
template; the Windows release workflow is unchanged.

## Licensing

New program sources and documentation follow the repository's GPL-3.0-or-later
license unless a file says otherwise. See [LICENSE.md](LICENSE.md). Generated
fonts and assets retain their existing notices. The generator copies the
unmodified protected MGA containers and their separate permission; it does not
decrypt, extract for redistribution or relicense them.

## Bundled handbook

Help → Handbook and the existing `handbuch_oeffnen` UI command open the same
canonical 2.0.30 handbook bundled under `Contents/Resources/UI/manual`.
The handbook tree is included in source freezes and generated bundle hashes;
there is no separate content fork or automatic handbook download/install.
Its window uses a separate nonpersistent WebKit store without any native message
handler. File read access is limited to its handbook directory. Navigation accepts
only the bundled entry and safe fragments; arbitrary paths, queries and schemes
are rejected. Language selection reuses the original catalogs and controls.
Network scripts/subresources are blocked. Only explicit HTTPS link clicks may
open the system browser. Handbook printing/native commands are not bridged.
Native WebKit tests load these actual generated resources and exercise search,
result navigation, language selection, isolation and blocked external scripts.
New source still requires native execution; host projection tests alone do not
prove the handbook runs on Monterey or other macOS versions.

## Copy selected macOS reminders

**Copy macOS reminders…** in the application menu or System internet accounts
opens explicit EventKit permission, reminder-list and item selection in #777.
Open and completed entries are offered. The iPhone reminders must already be
available in the selected Mac account; the connection needs no helper program
or Magnolie iPhone app.

Up to 100 selected records and 16 MiB become reviewed, independent local tasks.
Title, plain note, completion state, supported dates and an explicitly displayed
three-level priority mapping enter the existing task editor. DATE and floating
clock values retain their meaning; explicit timezones use the document's time
database. Recurrences, alarms and values the editor cannot preserve are visibly
excluded. Public EventKit does not expose complete Reminders-app semantics:
hierarchy, tags, flags, attachments, assignments and rich text are explicitly
unavailable, never assumed absent. Copies have no source parent relationship
and do not enable task notifications.

The reader checks list/account membership and re-reads selected public fields
after review. Existing, changed and trashed local copies remain intact. The
transaction probes the canonical task graph before mutation, creates a recovery
checkpoint and requires a durable-save acknowledgement. Source data is read
only; this is not synchronization. See [SYSTEM-REMINDER-IMPORT.md](SYSTEM-REMINDER-IMPORT.md)
for field coverage, limits and the required native acceptance.

## Copy selected macOS contacts

**Copy macOS contacts…** in the application menu or System internet accounts
starts the native Contacts permission, address-book and contact selection in
#775. The iPhone data must already be available in the chosen Mac account.
No separate helper program or Magnolie iPhone app is required. The source is
read only; the reviewed records become editable local contacts in the current
Organizer document. A sync-source selection is not a local destination book.

The selection is bounded to 100 contacts and 16 MiB, with source identities and
public fields read again after review. Existing copies, local edits and trash
entries are retained. Contact notes and provider-specific fields are explicitly
outside this copy. Birthdays stay on these contacts without automatically
creating or matching anniversary entries. The existing normalizer, recovery
checkpoint and durable-save acknowledgement remain the local write authority.
See [SYSTEM-CONTACT-IMPORT.md](SYSTEM-CONTACT-IMPORT.md) for exact field coverage,
review behavior, test evidence and the required native macOS acceptance.

## Import selected note files

The separate **Text copies from Apple Notes…** action now has a direct native
source implementation in #772. It reads selected notes through Foundation
NSAppleScript, uses the existing Notes app, and requires the normal macOS
Automation permission. It does not install a helper program or require an iPhone
app. Notes from an iPhone must already be available in the selected Mac account.
Only the reviewed plaintext is copied; protected notes and notes reporting
attachments are excluded. Full text, source identities, repeat-import handling,
source revalidation and durable-save behavior are documented in
[APPLE-NOTES-IMPORT.md](APPLE-NOTES-IMPORT.md). This new path has not been run or
compiled on a Mac here; the installed Notes scripting Dictionary and TCC flow
remain explicit native acceptance gates.

The native “Import note files…” action prepares an additive import from explicitly
selected TXT, Markdown, PDF, JPEG, PNG, GIF or WebP files. It does not restore a
profile or connect to Apple Notes. Existing KDE Connect or another user-selected
file-transfer method can supply these files first; the Mac port does not implement
a KDE receiver. The user reviews filenames, text samples and format notices before
approving. Markdown stays literal editable source text. PDF/images keep original
attachment bytes; Apple Notes drawing strokes and metadata are not converted into
editable Magnolie objects. Unsupported selections fail together.

Preparation limits are 32 files, 8 MiB total and 1 MiB per text file. Native reads
reject symbolic links and changed sources, then revalidate source hashes after
preview. The projected UI uses the canonical note constructor, attachment cleaner
and normalizer, generates fresh IDs, creates a recovery checkpoint and waits for
the normal durable save ACK. Equal filenames do not overwrite or deduplicate
attachments. A failed final write leaves pending imported notes visibly unsaved
for recovery/save retry; it never reports successful import. The picker and real
transport still require native user-flow acceptance; synthetic GUI tests are not
that evidence.
