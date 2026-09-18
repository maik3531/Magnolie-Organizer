# macOS Beta Feature Matrix — 2.0.18-beta.1

Updated 2026-09-14. The target remains the same UI and functionality as the current
Linux/Windows Organizer. This phase does **not** achieve native feature parity.
“Source implemented” means executable logic exists; no macOS branch has been
compiled or exercised here. Linux host/Swift tests do not establish macOS behavior.

## Local Features

| Feature | Source implementation/evidence | Remaining work |
| --- | --- | --- |
| Calendar/day views, tasks/subtasks, notes, contacts, anniversaries | Current shared frontend projection; host rendering and actual editor cases | Real WKWebView visual/input acceptance; full native feature parity cannot be inferred from views |
| Planner, health and Custom module/designers | Current shared UI/model code is projected, not manually forked | Broader functional acceptance, native print/office export and Custom sync |
| Create/edit/save | Whole JSON, private lease, atomic write, fsync, expected-file check; portable Swift tests | APFS/F_FULLFSYNC, disk-full, native quit/crash injection |
| Delete/recycle bin/merge edits | Shared UI logic; destructive structural saves require recovery copy; contact deletion waits for token ACK | Full deletion/merge matrix on Mac; snapshots are not automatic recovery of unsaved edits |
| Local recovery | Exact disk bytes in private `Recovery-macOS-Beta/*.json`; read-back verification before destructive commit; restart tested in portable Swift | No indexed desktop journal, schedules, retention/pruning, selective/additive recovery, cryptographic plaintext snapshot index |
| Full JSON import/restore | Native selected-file capability; pinned bytes/path; duplicate-key/shape checks; canonical normalizer preflight; durable pre-restore copy; complete replacement | Native picker/crypto/commit integration on Mac; not `.magnolie` complete archive import |
| JSON backup/export | Whole document including unknown fields and embedded attachments; always encrypted; separate password prompt for plain profile | Native prompt/save panel/crypto interoperability run; no external backups rekeyed |
| Encryption | Desktop v1 read/v2 read-write CryptoKit/CommonCrypto implementation and public test vectors | Apple crypto execution; password change/removal; keychain/rekey transactions |
| ICS export | Simple appointments, LOCATION and time reconciliation, TZ/DST validation; live shared editor → compiled Swift tests | Recurrence, VTODO, VALARM, attendees, provider data, full round-trip codec |
| ICS/vCard/CSV import/export | Shared controls remain; unsupported native commands return negative responses | Full codecs, import previews/merging and format interoperability |
| `.magnolie` multi-file complete archive | Unsupported explicitly | Full format/attachments/settings/restore transaction and shared fixtures |
| Clipboard/attachments | Native text clipboard; Save for supported PDF/image data URLs | Native AppKit validation; automatic attachment opening |
| Regional settings | Existing shared renderer exposed; save-ACK before native preferences commit; validated values; preserved unknown settings; restart applies locale | Native locale/timezone behavior and all localized system dialogs |
| Localization | Entire current shared gettext-generated UI catalogs; native catalog generated from those same messages; English fallback + 19 locale catalogs | Existing Beta capability prose, EventKit/notification notices and many diagnostic messages remain English; full native localization is **not** claimed |
| Native standard controls | Shared gettext labels; Undo/Redo supplement has all 19 translations plus English msgids (20 languages) | Human language review and actual AppKit/VoiceOver reading |
| Keyboard/accessibility | Shared tablists/modal focus/escape; Command+digit/formatting bindings; native Undo/Redo/clipboard menu actions; visible Beta-summary focus | Real Cmd+formatting, focus restoration, VoiceOver, contrast/zoom/RTL and keyboard-only native dialogs |
| Icons/fonts/MobileAlias | Whole canonical symbols and font trees copied byte-identically; current `mobile-downloads.json` alias included; Beta identity/resource inventory tested | Native metrics/rendering; mobile metadata does not enable phone integration |

## Critical Native Gaps

| Area | Current status | Priority/acceptance |
| --- | --- | --- |
| AppKit/WKWebView host | Source exists; Linux excludes it entirely. A real-WKWebView test is prepared but **NOT RUN** | P0: legitimate macOS runner compilation, UI load, native Host save/quit/navigation and permission failures |
| Notifications | Open/unlocked/consented checker only; one-off early/due task calculations tested | P0 for reminder parity: durable scheduler, restart deduplication, recurrence, wake/closed-app delivery, denial/revocation |
| macOS calendars/reminders | EventKit read-only listing of calendar/list names via native menu | Item import/edit/sync, permissions; not Internet Accounts/EDS synchronization |
| System contacts | Unsupported | Contacts.framework/provider contracts and user-approved import/sync |
| DAV/CalDAV/CardDAV/Nextcloud/Graph | Unsupported | Authentication, retries, conflict/deletion contracts, transport tests |
| Magnolienbaum/personal sync | Unsupported | Pairing, consent, durable queues/receipts, contact/custom/attachment interop |
| Phone/SMS/Bluetooth/KDE Connect/audio | Unsupported | Native transport/hardware/control contracts and actual-device validation |
| Background/tray/autostart/cloud backup | Unsupported | LaunchAgent/status item lifecycle, encrypted/locked policy, durable jobs |
| Printing/PDF/ODS/office letters | Unsupported native bridge | Print pagination, export fidelity and platform launch integration |
| Weather/holidays/maps/mail/external links | Unsupported native network/launch handlers | Restricted native services and callback/error contracts |
| Manual/update/contributor/protected-image rendering | Unsupported; no production trust roots installed | Separate Beta metadata/trust policy and authorized native implementation |
| Shipping/signing/notarization/installer | No production artifact or release | Review + Mac acceptance + final explicit release authorization |

`BRIDGE-COVERAGE.md` lists each statically detected shared frontend/Windows-contract
command against the Swift allowlist. `erinnerung_einrichten`, for example, is only
a limitation response, not an implemented scheduler. Missing callbacks/status
datasets are not fabricated as successful empty results.

## Next Bounded Phase

1. Review the new recovery/restore transaction and its encryption retention policy.
2. With explicit repository/runner authorization, install the inactive CI template
   on a reviewed ref and run it on GitHub's real macOS runner. Record exact SDK,
   architecture, test output and failures. No Linux macOS spoof/emulator substitute.
3. Exercise the production Host (not just the WK test harness) for native dialogs,
   permissions, write failure/quit, VoiceOver and keyboard-only operation.
4. Continue common format/import/export and native service implementations against
   the shared contracts. Keep this matrix partial until actual evidence supports it.
