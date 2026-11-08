# Magnolie Organizer macOS Beta

Parallel development port, not a production release and not feature-equivalent to
the Linux/Windows native applications. Native builds, ad-hoc signing, core/WKWebView tests and the real bundled-app
start/save/quit/reopen/data-preservation smoke passed on macOS 15 for Apple Silicon
and Intel in [Actions run 42500979784](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42500979784)
at port source `ab646c6d`. Later source changes require renewed native checks.
The two development candidates include source provenance, checksums and native
evidence. This validates the local startup/persistence workflow; full feature,
permission, upgrade, accessibility and distribution acceptance remains incomplete. Do not use the only
copy of important data with this Beta.

The canonical directory is `Magnolie-Organizer-macOS-Beta` beside the existing
Linux and Windows source directories. Shared product sources, dependency declarations and the Windows release workflow
remain unchanged. The dedicated candidate workflow builds this port separately.

## Identity

- Version: **`2.0.30-beta.1`**. See [POLICY.md](POLICY.md) for numeric bundle versions and release boundaries.
- App name and executable: `Magnolie Organizer macOS Beta`.
- App bundle: `Magnolie Organizer macOS Beta.app`.
- Identifier: `io.gitlab.maik3531.MagnolieOrganizer.macOSBeta`.
- Data: `~/Library/Application Support/io.gitlab.maik3531.MagnolieOrganizer.macOSBeta/organizer.json`.
- Development output and exported filenames include `macOS Beta`.
- No stable Windows, Linux or Notes profile is discovered, imported or reused automatically.

The `2.0.30-beta.1` identity targets the published desktop 2.0.30 baseline.
It remains a partial macOS Beta, not a claim that every desktop native feature
is available. Projection/build manifests record the actual input hashes; host
checks against a moving development checkout do not establish release-tag parity.

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
Swift concurrency is supported on this deployment target; no user-installed Swift
toolchain is required to run the bundle. A current SDK/toolchain is required to build.

## Implemented Source

| Area | Current Scope |
| --- | --- |
| Desktop interface | Entire canonical Linux web tree, styles, fonts, symbols and catalogs projected by generator, not a separate hand-maintained organizer UI |
| Handbook | Canonical 2.0.30 handbook bundled unchanged, including languages, search and assets; separate nonpersistent local WKWebView, no Organizer bridge; user-clicked HTTPS links open in the system browser |
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
| Clipboard/attachments | Text clipboard; attachment Save for PDF/JPEG/PNG/GIF/WebP data URLs, not automatic attachment opening |
| Reminders | Open-app checker with independent one-off early/due task reminders, connected to permission-gated macOS notifications; no persistent scheduler |
| macOS calendars/reminders/contacts | Native explicit OS access, async discovery and canonical source selection; full import/synchronization remains unfinished |
| DAV accounts | Canonical native configuration, Keychain credentials, revision-bound verified save/rollback and explicit collection discovery; 19 native account tests |
| DAV calendar foundations | Complete typed REPORT snapshot decoding and surgical component edits preserving resource siblings; native tests pass on both architectures; no record-sync coordinator yet |

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
- Selected UTF-8 ICS files are decoded off the UI thread and applied through the
  canonical importer; source headers are retained by file hash in the same saved
  profile transaction. Independent native import/reexport checks pass on both
  architectures. vCard/CSV/archive import remains unfinished.
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
  arithmetic has no 1582 cutover. The codec context migration still needs its
  native compilation and roundtrip run; standalone point/definition oracle
  results do not alone prove the complete codec integration.
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
  system synchronization is unfinished and its action remains disabled.
- Public/school holiday retrieval uses a bounded native HTTPS service and the
  canonical cache importer. DAV account configuration and explicit discovery use native Keychain storage and
  verified rollback. Complete Nextcloud synchronization and conflict/deletion
  transactions remain unfinished; successful setup is not a synchronization ACK.
- Printing renders an immutable selected HTML snapshot in a separate ephemeral,
  JavaScript-disabled WKWebView with no native bridge, network or local-file access.
  AppKit supplies the system print dialog and its Save as PDF action. The native
  PDF-engine test does not establish manual print-panel or physical-paper acceptance.
- No Graph sync, Magnolia tree, phone/SMS/Bluetooth, weather download,
  tray/background service, autostart, scheduled backup, office export,
  full ICS/vCard/CSV import, updater, manual downloader, contributor validation or
  native protected-image rendering is implemented.
- Unsupported desktop controls retain an explicit Beta limitation notice or
  receive a negative response. They do not signify native feature parity.
- This is a non-sandboxed development shell, not a hardened/notarized distribution.
  CSP and WKWebView navigation restrictions block remote content; the bridge
  cannot run arbitrary shell commands or accept arbitrary profile paths.

## Using The New Local Features (on a future tested Mac build)

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

The portable Foundation/POSIX/ICS code has been compiled and tested with Swift
on Linux. CryptoKit/CommonCrypto and all AppKit code still require Apple's SDK
and remain unverified on macOS.

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
approval. Existing desktop sources and repository workflows remain untouched.

## macOS Development

Requires a legitimate Mac or an explicitly available Apple-hosted runner, Xcode
15+ or its Apple Command Line Tools with the macOS SDK, Python 3.10+, and a
macOS host supported by that Xcode version (Xcode 15 requires macOS 13.5+).
The generated application targets macOS 12.7+; the build host may be newer. There are no Swift package downloads. Build only after the freeze steps:

```sh
python3 tools/build_dev.py
```

This runs `swift test`, makes a **debug** bundle for the runner's architecture,
copies the verified UI/resources/licenses, and applies local ad-hoc signing.
It refuses to overwrite an existing output app. It does not launch the app,
build a DMG/PKG/production release, notarize, upload or publish anything.

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

The authorized candidate workflow is
[`ports-2.0.30.yml`](../.github/workflows/ports-2.0.30.yml). It runs manually or on
the dedicated `codex/ports-2.0.30` branch. It retains the reviewed port sources but
selects canonical desktop inputs from the exact published `v2.0.30` commit
`067c38934b539943d8e1720abafd8a80b401d797` in its disposable runner checkout.
Catalog generation precedes the build-local freeze. Host, Apple crypto and real
WKWebView tests must pass before the development app is packaged and uploaded.
The zip includes source provenance and SHA-256 checksums; Actions retains it for
14 days. Its architecture follows the runner and is recorded in the build metadata.

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

## Import selected note files

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
