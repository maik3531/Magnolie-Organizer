# Magnolie Organizer macOS Beta

Parallel development port, not a production release and not feature-equivalent to
the Linux/Windows native applications. The native Swift implementation has **not
been compiled or tested on macOS** in the current Linux environment. Do not use
the only copy of important data with this Beta.

The canonical directory is `Magnolie-Organizer-macOS-Beta` beside the existing
Linux and Windows source directories. No stable product source, library,
dependency, active workflow or release artifact is modified by this port.

## Identity

- Version: **`2.0.18-beta.1`**. See [POLICY.md](POLICY.md) for numeric bundle versions and release boundaries.
- App name and executable: `Magnolie Organizer macOS Beta`.
- App bundle: `Magnolie Organizer macOS Beta.app`.
- Identifier: `io.gitlab.maik3531.MagnolieOrganizer.macOSBeta`.
- Data: `~/Library/Application Support/io.gitlab.maik3531.MagnolieOrganizer.macOSBeta/organizer.json`.
- Development output and exported filenames include `macOS Beta`.
- No stable Windows, Linux or Notes profile is discovered, imported or reused automatically.

## Implemented Source

| Area | Current Scope |
| --- | --- |
| Desktop interface | Entire canonical Linux web tree, styles, fonts, symbols and catalogs projected by generator, not a separate hand-maintained organizer UI |
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
| Export | Simple appointment ICS, including consistent editor-mirrored LOCATION and time properties; rich/recurring/provider-bound records refused rather than flattened |
| Clipboard/attachments | Text clipboard; attachment Save for PDF/JPEG/PNG/GIF/WebP data URLs, not automatic attachment opening |
| Reminders | Open-app checker with independent one-off early/due task reminders, connected to permission-gated macOS notifications; no persistent scheduler |
| macOS calendars/reminders | Optional EventKit listing of calendar/list names and sources from native menus, read-only; no item import or sync |

"Implemented source" is not a statement of native build or runtime validation.
Development is paused; the source checkpoint and remaining work are tracked in
[issue #9](https://github.com/maik3531/Magnolie-Organizer/issues/9).

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
- The ICS subset uses desktop `endDatum`/`endZeit`, escapes/folds content, and
  refuses recurrence, alarms, attendees, attachment links, provider data and other
  meaningful fields it cannot represent. Global reminder preferences and local
  record metadata are not ICS fields. Redundant raw properties must agree with
  structured fields; supported UTC/IANA timezone qualifiers are retained and
  mismatched/partial zoned start/end pairs are rejected. The editor's empty
  `TZID=` denotes floating time and is emitted without that empty parameter.
  Use JSON backup for a complete copy.
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
- No macOS Internet Accounts integration is offered. The generated sync page
  has no Linux EDS/Akonadi selectors or Linux package-install instructions. Native
  read-only EventKit discovery does not masquerade as desktop synchronization.
- No DAV/Graph/Nextcloud sync, Magnolia tree, phone/SMS/Bluetooth, system contacts,
  weather/holiday downloads, tray/background service, autostart, scheduled backup,
  printing/PDF/office export, full ICS/vCard/CSV codecs, updater, manual downloader,
  contributor validation or native protected-image rendering is implemented.
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
15+ or its Apple Command Line Tools with the macOS SDK, Python 3.10+, and macOS
13+. There are no Swift package downloads. Build only after the freeze steps:

```sh
python3 tools/build_dev.py
```

This runs `swift test`, makes a **debug** bundle for the runner's architecture,
copies the verified UI/resources/licenses, and applies local ad-hoc signing.
It refuses to overwrite an existing output app. It does not launch the app,
build a DMG/PKG/production release, notarize, upload or publish anything.

The resulting development path is
`Output/Magnolie Organizer macOS Beta-2.0.18-beta.1/Magnolie Organizer macOS Beta.app`.
Its build record explicitly says native UI validation and production release
are false, even when compilation and Swift tests pass.

`ci/macos-beta-manual.yml.example` is an **inactive** workflow template, outside
`.github/workflows`. It has only `workflow_dispatch`, a required freeze
confirmation gate, read-only repository permissions, a macOS runner and no
upload steps. Installing/dispatching it requires separate approval and an
available runner. It prepares isolated test dependencies, current-source host tests,
Apple crypto tests and a real-WKWebView smoke test; the template has not been run.
No active stable CI configuration was changed.

## Licensing

New program sources and documentation follow the repository's GPL-3.0-or-later
license unless a file says otherwise. See [LICENSE.md](LICENSE.md). Generated
fonts and assets retain their existing notices. The generator copies the
unmodified protected MGA containers and their separate permission; it does not
decrypt, extract for redistribution or relicense them.
