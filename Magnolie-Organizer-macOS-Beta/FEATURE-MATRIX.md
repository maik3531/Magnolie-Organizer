# macOS Beta Feature Matrix — 2.0.30-beta.1

Updated 2026-11-26 (#783 current-source candidates; #784 device page; #785 current
file parsers; #786 bounded native field sync; #121 evidence/VM planning). The shared Organizer UI and data
behavior follow current Linux/Windows sources, with Mac-specific native
integrations. Mac does not require its own Magnolie Notes companion app.
Apple services and supported existing KDE Connect clients remain intended
integration paths; an available client does not establish a particular
Organizer adapter. Full native feature parity is not claimed.

The current-source native checkpoint is
[run #97](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
at `215d89029df02df2dce78f35412785ec9f9b36d8`, successful on macOS 15
ARM64 and Intel. Both jobs passed 21 runtimebuilder tests, 17 ImportHelper/path
tests, 35 host tests with one skip, and four Swift contexts of 501 cases each
with 4/5/5/6 skips. The repeated contexts overlap and are not unique test totals.
Strict signatures, actual app start/save/normal-quit/reopen and development
packaging passed. Exact scope and independent artifact checks are in the
[native report](NATIVE-VERIFICATION-2026-11-26.md) and
[durable evidence](verification/native-run-97.json).

Historical runs such as **42562106430** used Mac/adapter source `cbdc0876`
with published desktop inputs `067c3893`. They remain historical evidence.
#97 instead binds both Mac and shared inputs to its selected current checkout;
see [CURRENT-SOURCE-CANDIDATE.md](CURRENT-SOURCE-CANDIDATE.md). Full native
feature/UI, Monterey, TCC, account/device and production distribution
acceptance remain open. A CI pass does not implement the missing features below.

## Local Features

| Feature | Source implementation/evidence | Remaining work |
| --- | --- | --- |
| Calendar/day views, tasks/subtasks, notes, contacts, anniversaries | Current shared frontend projection; #783 also selects current checkout for candidate builds and tests shared note-date search/calendar navigation in generated Mac UI | Renewed current-source WKWebView visual/input acceptance; full native feature parity cannot be inferred from views |
| Planner, health and Custom module/designers | Current shared UI/model code is projected, not manually forked | Broader functional acceptance, system print-panel/manual acceptance, office export and Custom sync |
| Create/edit/save | Whole JSON, private lease, atomic write, fsync, expected-file check; current Swift tests and actual fresh-profile save/normal-quit/reopen on both architectures in #97 | Full editing/UI acceptance, APFS/F_FULLFSYNC fault scenarios, disk-full and native crash injection |
| Delete/recycle bin/merge edits | Shared UI logic; destructive structural saves require recovery copy; contact deletion waits for token ACK | Full deletion/merge matrix on Mac; snapshots are not automatic recovery of unsaved edits |
| Local recovery | Exact disk bytes in private `Recovery-macOS-Beta/*.json`; read-back verification before destructive commit; restart tested in portable Swift | No indexed desktop journal, schedules, retention/pruning, selective/additive recovery, cryptographic plaintext snapshot index |
| Full JSON import/restore | Native selected-file capability; pinned bytes/path; duplicate-key/shape checks; canonical normalizer preflight; durable pre-restore copy; complete replacement. Applicable current core/epoch/WK tests passed in #97 (#454) | Actual picker/import/save/reopen acceptance; #511's complete opaque-Unicode path; not `.magnolie` complete archive import |
| JSON backup/export | Whole document including unknown fields and embedded attachments; always encrypted; separate password prompt for plain profile | Native prompt/save panel/crypto interoperability run; no external backups rekeyed |
| Encryption | Desktop v1 read/v2 read-write CryptoKit/CommonCrypto implementation and public test vectors; applicable Apple crypto tests passed in #97 | Actual password/picker/UI acceptance; password change/removal and keychain/rekey transactions |
| ICS export | Source-preserving appointments/tasks/anniversaries, recurrence and exception/raw properties, historical/future VTIMEZONE; real shared editor → Swift tests | Eight independent published-codec roundtrips pass on both architectures; native picker/manual acceptance remains open; unsupported fields fail the whole export |
| File import / #785 | Native picker and bounded private-parser path for current ICS/VCS/LCS, OR6/CSV, vCard/CSV, Claws/LDIF, ZIP and waste formats; native runtime/relocation and 17 helper/path tests passed on both architectures in #97; 90 original OR6-to-projected-UI checks use synthetic native transport | Actual production picker/import/save/reopen; full Magnolie archive and local-program discovery remain follow-up work. The fresh-profile app smoke does not prove imported-data persistence. See IMPORT-CODECS.md and IMPORT-RUNTIME.md |
| ICS/vCard/CSV export | Existing selected-file export routes and published-codec comparisons retain their exact earlier scope | Import parity does not by itself establish new export formats or native acceptance |
| `.magnolie` multi-file complete archive | Unsupported explicitly | Full format/attachments/settings/restore transaction and shared fixtures |
| System printing / PDF | Isolated ephemeral WKWebView, JavaScript disabled, no bridge/network/local-file access; AppKit print dialog includes Save as PDF; applicable native PDF-generation tests passed in #97 | Manual OS print-panel acceptance; physical paper output is never inferred |
| Clipboard/attachments | Native text clipboard; Save for supported PDF/image data URLs | Native AppKit validation; automatic attachment opening |
| Regional settings | Current shared renderer bound to existing Beta handler (not the desktop MCP API); save-ACK before native commit; validated values; field mapping/save-failure/double-click host tests. Native time-zone management shows an explicit limitation; automatic native zone refresh is inactive and imported settings remain intact | Native locale/timezone behavior and all localized system dialogs; desktop revision-bound native MCP and automatic time-zone detection parity |
| Localization | Entire current shared gettext-generated UI catalogs; native catalog generated from those same messages; English fallback + 19 locale catalogs | Existing Beta capability prose, EventKit/notification notices and many diagnostic messages remain English; full native localization is **not** claimed |
| Native standard controls | Shared gettext labels; Undo/Redo supplement has all 19 translations plus English msgids (20 languages) | Human language review and actual AppKit/VoiceOver reading |
| Keyboard/accessibility | Shared tablists/modal focus/escape; Command+digit/formatting bindings; native Undo/Redo/clipboard menu actions; visible Beta-summary focus | Real Cmd+formatting, focus restoration, VoiceOver, contrast/zoom/RTL and keyboard-only native dialogs |
| Icons/fonts/MobileAlias | Whole canonical symbols and font trees copied byte-identically; current `mobile-downloads.json` alias included; Beta identity/resource inventory tested | Native metrics/rendering; mobile metadata does not enable phone integration |

## Critical Native Gaps

| Area | Current status | Priority/acceptance |
| --- | --- | --- |
| AppKit/WKWebView host | Both architectures passed current-source WKWebView tests and actual application save/normal-quit/reopen in #97; both captured start windows were visually inspected | Full interaction, permission/native-dialog and upgrade acceptance remains open; later source edits need their own checks |
| Notifications | Open/unlocked/consented checker only; one-off early/due task calculations tested | P0 for reminder parity: durable scheduler, restart deduplication, recurrence, wake/closed-app delivery, denial/revocation |
| macOS calendar copies | #770: explicit native source/date picker, bounded one-way copies of supported single appointments, preview, stable source identity, re-read before commit, recovery and durable-save acknowledgement; projected JS checks use synthetic native transport; current Swift compilation/applicable CI tests passed | Actual EventKit account/TCC/picker execution; series/alarms/participants and unrepresentable records are excluded; no automatic update/delete/write-back; see `SYSTEM-CALENDAR-IMPORT.md` |
| Apple Notes text copies | #772: direct NSAppleScript reader, explicit account/folder/note selection, full plaintext preview, exact source identity, source reread, canonical local note transaction and durable-save acknowledgement; current Swift compilation/applicable CI tests passed; no additional application | Actual Notes Dictionary/account/TCC/UI execution; protected notes and notes reporting attachments excluded; only reviewed text is copied, no source writes or synchronization; see `APPLE-NOTES-IMPORT.md` |
| macOS reminders | #777: explicit EventKit list/item selection, public-field preview, source reread, independently editable local task copies, provenance and durable-save acknowledgement; existing source selections preserved; current Swift and #797 text-copy regressions passed in #97 | Actual EventKit/account/permission/UI acceptance; complete component/hierarchy fidelity and synchronization remain separate |
| System contacts | #775: Contacts.framework container/contact selection, reviewed local public-field copies, source reread, exact provenance, contact-only birthdays and durable-save acknowledgement; current Swift compilation/applicable CI tests passed | Actual provider/permission/UI acceptance and further mapping fidelity; source writes and complete synchronization remain separate |
| Native system-account field sync / #786 | Separate explicit source/book binding, current EventKit/Contacts adapters, baseline comparison in both directions, supported-field updates, readback and encrypted transaction ledger; current Swift compilation/applicable CI tests passed. Existing copy provenance grants no authority | Actual provider/TCC/account/Keychain/UI acceptance in a real macOS VM. No new native records, deletes, series, automatic/background sync, or Apple Notes writeback. See `../contracts/macos-786-native-system-sync.md` and `CLOUD-MAC-TESTING.md` |
| DAV/CalDAV/CardDAV/Nextcloud/Graph | Native DAV configuration/discovery GUI, bounded HTTPS protocol (20 tests), Keychain storage, 19 account/boundary/transaction cases, 15 typed calendar-snapshot tests and sibling-preserving resource-patch tests pass on both architectures | Real server/account GUI acceptance and complete conflict/deletion/local-commit synchronization coordinator; Graph unsupported |
| Magnolienbaum/personal sync | Unsupported | Pairing, consent, durable queues/receipts, contact/custom/attachment interop |
| Phone/SMS/Bluetooth/KDE Connect/audio | Existing KDE Connect clients remain an applicable external Mac/iPhone path. The current Organizer bridge does not implement the desktop phone/pairing/media commands; importing their shared UI does not activate them | Implement and validate concrete supported Mac-to-client capabilities; no separate Magnolie Notes app is required and no blanket KDE exclusion is intended |
| Background/tray/autostart/cloud backup | Unsupported | LaunchAgent/status item lifecycle, encrypted/locked policy, durable jobs |
| ODS / office letters | Native export/launch bridge unsupported; system printing/PDF is covered separately above | Office export fidelity and platform launch integration |
| Weather/holidays/maps/mail/external links | Native public/school holiday HTTPS service and canonical callback; atomic complete results and regional scopes | Live public-holiday HTTPS passed on both architectures; broader school/region/native UI acceptance pending; other listed services unsupported |
| Handbook | Current canonical offline manual bundled byte-for-byte; isolated local WebKit window/search/Help; applicable current native load/search/isolation tests passed in #97 | Actual user interaction and Monterey acceptance; later manual/UI changes require their own checks |
| Update/contributor/protected-image rendering | Unsupported; no production trust roots installed | Separate Beta metadata/trust policy and native implementation |
| Compatibility | Deployment target 12.7 and actual Mach-O architecture/minimum checks passed for both #97 candidates | Actual Monterey runtime and older-device acceptance pending; a Mach-O target is not execution on that OS |
| Shipping/signing/notarization/installer | Both ad-hoc Debug development ZIPs and strict nested/outer signatures passed in #97; source, runtime, resource and package inventories were independently checked | Full feature acceptance, production signing/notarization/Gatekeeper, install/upgrade and release authorization remain separate; development packages are not stable releases |

`BRIDGE-COVERAGE.md` lists each statically detected shared frontend/Windows-contract
command against the Swift allowlist. `erinnerung_einrichten`, for example, is only
a limitation response, not an implemented scheduler. Missing callbacks/status
datasets are not fabricated as successful empty results.

## Next Bounded Phase

1. Review the new recovery/restore transaction and its encryption retention policy.
2. Continue the authorized GitHub macOS runner checks on both architectures.
   Record exact source, SDK, test output and failures for each candidate.
3. Exercise the production Host (not just the WK test harness) for native dialogs,
   permissions, write failure/quit, VoiceOver and keyboard-only operation.
4. Continue common format/import/export and native service implementations against
   the shared contracts. Keep this matrix partial until actual evidence supports it.
