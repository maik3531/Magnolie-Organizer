# macOS Beta Feature Matrix — 2.0.30-beta.1

Updated 2026-11-08 (2.0.30 projection and native candidate verification).
The target remains the same UI and functionality as the current
Linux/Windows Organizer. This phase does **not** achieve native feature parity.
Native builds, ad-hoc signing, core/WKWebView tests and the real bundle lifecycle
smoke passed on macOS 15 for arm64 and x86_64 (Actions run 42506117045, port source
0c22df32; later source changes still require native checks). The smoke
verifies first save, normal quit, reopen, a second atomic save and strict whole-data
equality. Full application/feature acceptance remains pending. Linux host tests
alone do not establish macOS behavior.

## Local Features

| Feature | Source implementation/evidence | Remaining work |
| --- | --- | --- |
| Calendar/day views, tasks/subtasks, notes, contacts, anniversaries | Current shared frontend projection; host rendering and actual editor cases | Real WKWebView visual/input acceptance; full native feature parity cannot be inferred from views |
| Planner, health and Custom module/designers | Current shared UI/model code is projected, not manually forked | Broader functional acceptance, system print-panel/manual acceptance, office export and Custom sync |
| Create/edit/save | Whole JSON, private lease, atomic write, fsync, expected-file check; portable Swift tests | APFS/F_FULLFSYNC, disk-full, native quit/crash injection |
| Delete/recycle bin/merge edits | Shared UI logic; destructive structural saves require recovery copy; contact deletion waits for token ACK | Full deletion/merge matrix on Mac; snapshots are not automatic recovery of unsaved edits |
| Local recovery | Exact disk bytes in private `Recovery-macOS-Beta/*.json`; read-back verification before destructive commit; restart tested in portable Swift | No indexed desktop journal, schedules, retention/pruning, selective/additive recovery, cryptographic plaintext snapshot index |
| Full JSON import/restore | Native selected-file capability; pinned bytes/path; duplicate-key/shape checks; canonical normalizer preflight; durable pre-restore copy; complete replacement | Native picker/crypto/commit integration on Mac; not `.magnolie` complete archive import |
| JSON backup/export | Whole document including unknown fields and embedded attachments; always encrypted; separate password prompt for plain profile | Native prompt/save panel/crypto interoperability run; no external backups rekeyed |
| Encryption | Desktop v1 read/v2 read-write CryptoKit/CommonCrypto implementation and public test vectors | Apple crypto execution; password change/removal; keychain/rekey transactions |
| ICS export | Source-preserving appointments/tasks/anniversaries, recurrence and exception/raw properties, historical/future VTIMEZONE; real shared editor → Swift tests | Eight independent published-codec roundtrips pass on both architectures; native picker/manual acceptance remains open; unsupported fields fail the whole export |
| ICS/vCard/CSV import/export | Selected-file ICS import, canonical merge and source-header metadata; eight published-codec import/reexport cases pass on both architectures | Native picker/manual import acceptance; vCard/CSV and other formats remain unsupported |
| `.magnolie` multi-file complete archive | Unsupported explicitly | Full format/attachments/settings/restore transaction and shared fixtures |
| System printing / PDF | Isolated ephemeral WKWebView, JavaScript disabled, no bridge/network/local-file access; AppKit print dialog includes Save as PDF | Native PDF-engine test and manual OS print-panel acceptance pending; physical paper output is never inferred |
| Clipboard/attachments | Native text clipboard; Save for supported PDF/image data URLs | Native AppKit validation; automatic attachment opening |
| Regional settings | Current shared renderer bound to existing Beta handler (not the desktop MCP API); save-ACK before native commit; validated values; field mapping/save-failure/double-click host tests. Native time-zone management shows an explicit limitation; automatic native zone refresh is inactive and imported settings remain intact | Native locale/timezone behavior and all localized system dialogs; desktop revision-bound native MCP and automatic time-zone detection parity |
| Localization | Entire current shared gettext-generated UI catalogs; native catalog generated from those same messages; English fallback + 19 locale catalogs | Existing Beta capability prose, EventKit/notification notices and many diagnostic messages remain English; full native localization is **not** claimed |
| Native standard controls | Shared gettext labels; Undo/Redo supplement has all 19 translations plus English msgids (20 languages) | Human language review and actual AppKit/VoiceOver reading |
| Keyboard/accessibility | Shared tablists/modal focus/escape; Command+digit/formatting bindings; native Undo/Redo/clipboard menu actions; visible Beta-summary focus | Real Cmd+formatting, focus restoration, VoiceOver, contrast/zoom/RTL and keyboard-only native dialogs |
| Icons/fonts/MobileAlias | Whole canonical symbols and font trees copied byte-identically; current `mobile-downloads.json` alias included; Beta identity/resource inventory tested | Native metrics/rendering; mobile metadata does not enable phone integration |

## Critical Native Gaps

| Area | Current status | Priority/acceptance |
| --- | --- | --- |
| AppKit/WKWebView host | Both architectures passed real WKWebView tests and application save/quit/reopen at the earlier baseline | New native modules require renewed builds; permission/native-dialog/upgrade acceptance remains open |
| Notifications | Open/unlocked/consented checker only; one-off early/due task calculations tested | P0 for reminder parity: durable scheduler, restart deduplication, recurrence, wake/closed-app delivery, denial/revocation |
| macOS calendars/reminders | Async EventKit facade, explicit OS permission actions, native settings source selection; unavailable sources preserved | Full item import/edit/sync coordinator and actual account/permission acceptance; sync remains disabled |
| System contacts | Contacts.framework discovery, bounded vCard reads and explicit OS access facade | Full UI import/sync integration and real account permission acceptance |
| DAV/CalDAV/CardDAV/Nextcloud/Graph | Native DAV configuration/discovery GUI, bounded HTTPS protocol (20 tests), Keychain storage, 19 account/boundary/transaction cases, 15 typed calendar-snapshot tests and sibling-preserving resource-patch tests pass on both architectures | Real server/account GUI acceptance and complete conflict/deletion/local-commit synchronization coordinator; Graph unsupported |
| Magnolienbaum/personal sync | Unsupported | Pairing, consent, durable queues/receipts, contact/custom/attachment interop |
| Phone/SMS/Bluetooth/KDE Connect/audio | Unsupported | Native transport/hardware/control contracts and actual-device validation |
| Background/tray/autostart/cloud backup | Unsupported | LaunchAgent/status item lifecycle, encrypted/locked policy, durable jobs |
| Printing/PDF/ODS/office letters | Unsupported native bridge | Print pagination, export fidelity and platform launch integration |
| Weather/holidays/maps/mail/external links | Native public/school holiday HTTPS service and canonical callback; atomic complete results and regional scopes | Live public-holiday HTTPS passed on both architectures; broader school/region/native UI acceptance pending; other listed services unsupported |
| Handbook | Canonical offline 2.0.30 manual bundled byte-for-byte; isolated local WebKit window, search, Help menu and shared handbook command; 17 host tests pass | Native manual/search/isolation tests running on both architectures at 8e3aa630; no manual-specific native result yet |
| Update/contributor/protected-image rendering | Unsupported; no production trust roots installed | Separate Beta metadata/trust policy and native implementation |
| Compatibility | Deployment target 12.7 with actual Mach-O minimum verification implemented | Native build verification running; actual Monterey runtime and older-device acceptance pending |
| Shipping/signing/notarization/installer | User explicitly authorized publication after complete validation; no production artifact or release yet | Complete native feature/package acceptance, production signing/notarization and upgrade checks |

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
