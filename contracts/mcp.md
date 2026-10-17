# Organizer MCP contract

Implementation and complete product coverage are tracked in issue #170.
This document describes the implemented tools; the remaining product operations
are still being connected to the same interface.

### Native card printing

`organizer_cards_print` uses the existing GUI print-page builders for contacts,
tasks, notes, custom blocks, visible anniversaries and monthly appointment cards. Supply the full
`expected_book_revision`, `section` and optional explicit `ids`; omitted IDs mean
all cards in that section. Tasks include completed tasks and ignore GUI filters.
Hidden anniversaries cannot be selected. Appointment cards require explicit
`year`/`month`; their IDs select source appointments and include all their product
occurrences within that month, deduplicating multi-day occurrences as in the GUI.
Pending recurrence expansion yields `native_busy`. Other card sections reject
year/month. The native durable-save gate runs before
dispatch. At most 5000 cards and 750000 UTF-8 page bytes are accepted; arbitrary
HTML, commands and printer names are not inputs.

The correlated native result distinguishes Linux `dialog_returned` with
`dialog_action: print|cancel` from Windows `dialog_requested` with unknown choice
(WebView2's system ShowPrintUI returned). `paper_output_confirmed` is always false:
neither is spool-submission or physical-print proof. Linux has no viewer fallback
for this tool. Cancellation or the 25-second request timeout after dispatch may
leave an existing dialog open, and Linux may still return from that dialog later.
Inspect the existing dialog before retrying. Late results never open Organizer
menus or notifications.

`organizer_planner_print`, `organizer_health_print` and `organizer_time_print`
use the same explicit model selections as their corresponding spreadsheet exports
without destination/overwrite/launcher fields. They render the actual existing
GUI year/month planner, health forms/tables/insulin schemes/history charts and
monthly time-report HTML layouts. The same revision/save/UTF-8/native-dialog gates
and honest dialog-only receipt apply. Visibility flags, date ranges, units and
document-only report names do not change GUI selection or stored preferences.
Planner recurrence expansion must be complete before printing.

## Transport and session

Start the desktop Organizer normally, then run the same executable with
`--mcp-stdio` as the MCP client's stdio command. On Windows this is
`Magnolie Organizer.exe --mcp-stdio`; on Linux it is
`magnolie-organizer --mcp-stdio`. The command attaches to the running book for
the same profile and account. It does not open another book or create a profile.

The local connection uses a same-UID abstract Unix socket on Linux and a
`CurrentUserOnly` named pipe on Windows. No TCP listener or bearer-token file is
used. Losing the book connection ends the stdio client, including when its stdin
remains open. Protocol records are newline-delimited UTF-8 JSON, at most 1 MiB
including the newline. Normal diagnostics do not belong on protocol stdout.

The client sends `initialize` with `protocolVersion`, `capabilities`, and
`clientInfo` (`name` and `version`), then `notifications/initialized`.
Supported versions are `2025-11-25`, `2025-06-18`, `2025-03-26`, and `2024-11-05`.
An unsupported proposal receives the newest supported version for negotiation.
`ping`, `tools/list`, `tools/call`, and `notifications/cancelled` are supported.
Tool listings have up to 100 items; pass the returned `nextCursor` as `cursor`.
Each session allows eight pending calls. Sessions and invocation correlations
are ephemeral and independent of client-supplied JSON-RPC IDs.

## Results and writes

Successful tool calls return text JSON and the same object as `structuredContent`,
with `isError: false`. Product failures return `isError: true` and a structured
`code` and `message`. Invalid requests, unknown tools and invalid arguments use
JSON-RPC errors. A locked or not-yet-open book rejects data access; status remains
readable. Authorization is checked again before returning an operation's result.
Every tool declares an `outputSchema` for its success envelope in `tools/list`.
Results are validated against that contract before return; a malformed provider
result becomes `invalid_result` without returning its rejected values. Entity
documents retain their product-model and provider-specific fields inside the
typed read envelope. Both desktop products expose the same tool contracts.
Conditional native social actions are listed in status `supportedSocialServices`;
an unavailable action returns `unsupported_feature` instead of being silently
dropped from a contact. Existing platform-specific product actions are retained.

A successful product write includes `persisted: true` only after the existing
native durable-save acknowledgement. A cancelled or timed-out call may already
have reached the native operation. Read the affected state before retrying.
Note creation accepts an optional caller-generated UUID: an existing ID returns
`already_exists` rather than creating a duplicate. Note and task updates and
deletions require the opaque `revision` from the corresponding read tool as
`expected_revision`. Concurrent changes produce `conflict` instead of overwriting
the newer entry. An active unsaved editor draft produces `editor_busy`; reads
remain available. Pristine inline editors are refreshed when a mutation is applied.
An already open Organizer dialog yields `dialog_busy` for external book-data
writes, respecting the same modal transaction boundary as the graphical book.
Status reports both `editorDirty` and `dialogOpen` without returning draft text.

## Implemented tools

| Tool | Operation |
| --- | --- |
| `organizer_status` | Live version, readiness, lock and pending-save status |
| `organizer_data_read` | Product section; optional `id` lookup or array `offset`/`limit` pagination |
| `organizer_content_read` | Bounded base64 UTF-8 byte chunks for a selected product string, with content revision checking |
| `organizer_attachment_upload_begin/append/status/cancel/finalize` | Session-owned bounded image/PDF staging, full digest and native file-signature validation, revision-checked durable attachment commit |
| `organizer_attachment_remove` | Revision-checked product attachment trash and shared-note update |
| `organizer_settings_read` | Current product settings |
| `organizer_sync_sources_read` | Actual native calendar/address-book/account availability, with request- and callback-bound results |
| `organizer_note_read` | Note and revision token |
| `organizer_note_create` | Plain-text note in an existing notebook; native save acknowledgement |
| `organizer_note_update` | Revision-checked title, plain text or notebook change; attachments retained |
| `organizer_note_delete` | Revision-checked product deletion and configured trash/sync policy |
| `organizer_notebook_group_read/create/update/delete` | Group revision, create with default notebook/page, rename/reorder and delete with page migration |
| `organizer_notebook_read/create/update/delete` | Notebook revision, create, rename/reorder/move between groups, delete with page migration and trash assignment restoration |
| `organizer_task_read` | Task and revision token |
| `organizer_task_create` | Local task, person assignments, reminder fields and parent hierarchy |
| `organizer_task_update` | Revision-checked editor fields, retaining recurrence/provider metadata |
| `organizer_task_delete` | Product trash/tombstones; children are promoted to the deleted task's parent |
| `organizer_task_set_completed` | Complete or reopen a task; recurring masters produce one detached completed occurrence |
| `organizer_person_read/create/update/delete` | Task-assignment people, badge/color/note metadata and removal without deleting assigned tasks |
| `organizer_anniversary_read/create/update/delete` | Revision-checked anniversaries, unknown-year dates and linked-contact birthday maintenance |
| `organizer_vacation_read/create/update/delete` | Local vacation periods with validated inclusive date ranges, symbols and display style; revision-checked writes use the shared UI handler and wait for native persistence. Deletion is permanent, matching the UI. Calendar visibility is configured separately. |
| `organizer_shift_read/create/update/delete` | Shift definitions, including overnight times and semantic type; permanent deletion clears shift assignments and removes otherwise-empty day markers, returning `affected_dates`. Writes are revision-checked and durably acknowledged. |
| `organizer_cycle_marker_read/create/update/delete` | Cycle-marker definitions with semantic type, symbol and color; permanent deletion removes only that definition from assigned day markers and preserves other assignments, returning `affected_dates`. Visibility is configured separately. |
| `organizer_day_marker_read/set` | Raw date-addressed shift/cycle assignments, including a date-bound revision for an unassigned day. Set validates referenced definitions and preserves omitted assignment fields. Empty shift and cycle assignments remove the marker through the existing product handler. Writes await native persistence. |
| `organizer_waste_read/create/update/delete` | Local waste collections with first date, interval (0 = one-time), type and color. Imported schedules retain date metadata and reject direct date/interval edits. Reads can project fields while revisions cover the entire definition; writes use shared UI helpers and await native persistence. |
| `organizer_vital_read/create/update/delete` | Vital measurements with canonical kg/cm/Celsius units, product numeric ranges, explicit page or first free page, revision-checked edits and native persistence. Zero clears an optional numeric measurement. |
| `organizer_blood_glucose_read/create/update/delete` | Blood glucose records with unit-specific product ranges, page allocation and revision-checked persistent edits. A unit-only update uses the UI conversion/rounding; an explicitly supplied value is interpreted in the selected unit. Medication and insulin-scheme configuration are separate. |
| `organizer_medication_read/create/update/delete` | Stored medication records, names/forms, date ranges, weekday selection and typed weekly plans. Uses the same health-table mutation handler, page allocation, revision checks and durable saves; empty weekly-plan rows are removed. |
| `organizer_insulin_scheme_read/update` | Revision-checked partial configuration with the product model's field names, typed rule arrays and native save acknowledgement. Omitted fields are preserved; supplied arrays replace their previous contents. |
| `organizer_time_record_read/create/update/delete` | Manual completed time records using UTC Unix minutes, native time-zone/pause/lifecycle validation and product-owned synchronization clocks. Creation requires tracking enabled. Metadata edits preserve pause plans; timing edits reset them as in the manual editor. Deletion writes a tombstone and archives according to trash settings. |
| `organizer_time_settings_read/update` | Revision-checked local tracking enablement and report-name settings through the product handler. Persistence acknowledgement covers local settings. |
| `organizer_time_conflict_read/resolve` | Reads current and competing time-record versions under a shared revision. Resolution selects an existing version (0=current, 1..N=competing) through the product conflict engine and merges version clocks. |
| `organizer_custom_module_read/create/update/delete` | Custom designer modules with product page capacity, unique-type rules, presentation settings, revision checks and native persistence. Reads support field projection. Removal archives the module and clears linked text references through the shared product handler; trash restore uses the existing restore tool. |
| `organizer_custom_item_read/create/update/delete` | Custom text/task/appointment items with parent-bound revisions, field projection, product HTML sanitization, typed dates/basic recurrence, linked-text validation and native persistence. Removal uses product trash/reference cleanup. Item fields are validated against the parent module type. |
| `organizer_drawing_read/replace` | Drawing JSON read in bounded UTF-8/base64 chunks under a full module revision; typed replacement uses the actual drawing validator, PNG background decoding and shared import/editor handler before native persistence. External writes are blocked while a drawing gesture is active. Direct replacement is subject to the local RPC frame limit. |
| `organizer_drawing_upload_begin/append/status/cancel/finalize` | Session-owned, revision-bound drawing JSON staging up to the product import limit of 16 MiB, two drawing transfers, five-minute expiry and contiguous 64 KiB byte chunks with identical retry support. Finalize verifies SHA-256, strict UTF-8/typed JSON, actual drawing validity and background decoding before native persistence. Transfers are removed on cancel, close, expiry and finalize. |
| `organizer_recovery_list` | Actual native recovery inventory and schedule with bounded pagination and canonical metadata; archive payload and local filesystem paths are omitted. |
| `organizer_recovery_snapshot_preview` | Correlated native verification/summary plus opaque file-state revision. `verify:false` permits inspection of damaged archive metadata without claiming payload verification; `verified` reports the actual mode. |
| `organizer_recovery_snapshot_create` | Flushes book writes through the native save gate, then creates/reuses a manual checkpoint under the product policy. Returns confirmed metadata from the actual native result; a concurrent book change is reported explicitly. |
| `organizer_recovery_snapshots_delete` | Deletes up to 100 selected IDs with revisions obtained from preview/inspection. The native journal checks every selected state under its lock before the first deletion, including changed payload bytes. Active restore leases are rejected. Native result reports the actual deletion count. |
| `organizer_book_revision_read` | Opaque revision of the current complete in-memory book, required to authorize a restore. |
| `organizer_recovery_snapshot_restore` | Explicit areas (`all`, `contacts`, `calendar`, `notes`) and mode (`additive`, `replace`) with snapshot-file and current-book preconditions. Uses the actual native restore transaction/checkpoint/fences; the frontend adopts committed data before the small MCP acknowledgement. Returns commit/repair state and a fresh book revision. Synchronization is explicit after an API restore. |
| `organizer_recovery_creation_policy_read/update` | Revision-checked point-creation/grouping settings (`change`, `daily`, `weekly`, `startup`, `interval`, 1–1440 minutes) using the UI data helper and native save acknowledgement. Retention and backup configuration are separate. |
| `organizer_recovery_runtime_policy_read/update` | Actual native periodic scheduling/retention settings, revision-checked against a fresh native read. Update runs the product setters and retention engine, verifies their correlated settings response, and persists matching book preferences. |
| `organizer_backup_create` | Native backup after the book-save gate, returning the actual created file path only after a correlated success. Empty destination uses the product default; native destination/password/encryption rules remain in force. |
| `organizer_archive_preview` | Actual native complete-archive verification/decryption and canonical metadata/counts. No imported book data or GUI import dialog is produced; incorrect passwords/invalid files return a typed failure. |
| `organizer_archive_export` | Save-gated native complete-archive export to an explicit path, verified with the product reader before confirmation. Optional password; existing targets require explicit overwrite, linked targets and the active profile are rejected. |
| `organizer_archive_import` | Native complete-book replacement with a mandatory checkpoint and the product's device-settings/sync-epoch rules. Requires the archive text revision from preview, current book revision, and explicit replace mode. The exact revision-checked archive text is imported; committed data is adopted even on late/cancelled replies and repair state is reported. |
| `organizer_backup_preview` | Native classic JSON backup verification/decryption, counts and a revision of the exact source text. Complete `.magnolie` files use the archive tools. |
| `organizer_backup_restore` | Revision- and save-gated classic JSON restore using the product's encryption transaction and mandatory checkpoint. Explicit replace mode; committed and repair state are returned after data adoption, including late replies. Platform password behavior is preserved: Linux retains an existing profile password or adopts an encrypted backup password; Windows adopts the backup encryption state. |
| `organizer_backup_settings_read/update` | Backup folder and automatic cloud-folder preferences using the shared GUI handler, full preference revisions and native save acknowledgements. Protected-password availability comes from the correlated native vault status, without returning the password. Enabling requires a custom folder and available protected password; backup tests and password storage are separate. |
| `organizer_backup_password_store` | Store/replace the automatic-backup password through the native protected secret store, requiring the complete current book revision. Confirms native store success and availability; existing-password availability alone is not success. Neither password values nor raw vault errors enter results or book data. |
| `organizer_backup_test` | Actual native cloud-folder backup creation and readback verification, with current-book/save preconditions. Request/source identity follows the real worker through success and failure. Returns the actual archive path after durable status metadata save; late/cancelled outcomes update metadata only for the same book and backup folder. |
| `organizer_health_settings_read/update` | Revision-bound module/tab visibility, at-least-one-view policy, display units and untimed calendar-marker schedules through shared GUI handlers and native save acknowledgements. Measurement/medication data remains canonical and unchanged; schedule edits clear legacy time like the GUI. |
| `organizer_calendar_settings_read/update` | Revision-bound calendar/planner week numbering, click behavior, past-entry visibility, shift/cycle/vacation/waste module visibility and cycle notification options through the shared GUI handler and native save acknowledgement. Definitions/records are retained; notification opt-ins change only when explicitly supplied. |
| `organizer_display_settings_read/update` | Revision-bound selection/accessibility/date-button/attachment-preview preferences, typography, optional/custom tab settings and actual calendar-view selection through shared GUI handlers. Hiding the current tab falls back to calendar and health visibility remains mirrored. Native save acknowledgement confirms local preferences; dictionary availability and remote feature delivery are separate. |
| `organizer_spellcheck_word` | Actual native dictionary check and at most eight suggestions, using the product-supported German/English boundary. Native error responses that contain `correct=true` fallback values are still errors, never successful dictionary checks. |
| `organizer_dictionary_add_word` | Book-bound native personal-dictionary addition followed by another actual native check. Confirms provider visibility without writing book data or assuming dictionary availability; callback/request correlation suppresses unrelated or late spelling UI. |
| `organizer_regional_settings_read/update` | Read actual native startup configuration separately from book regional metadata. Combined preference revision plus native current-value CAS protects writes; actual native writer/readback precedes matching book metadata and durable save acknowledgement. Existing record timestamps remain unchanged. Restart is required for all runtime/native windows; cancellation can leave startup configuration saved, so re-read before retrying. |
| `organizer_tray_settings_read/update` | Stored native tray preferences, current indicator state and actual autostart registration are read separately from book preferences. Native state CAS, stored readback/indicator/registration checks and book-save acknowledgement protect writes. Autostart enables tray/start-minimized; explicit tray disable clears them. Indicator state does not guarantee visibility on every desktop host. |
| `organizer_background_permissions_read/update` | Linux standalone-service optional permissions via the shared GUI policy builder and actual native settings/lifecycle/autostart readback, native CAS and book-save acknowledgement. Core pairing/monitoring plus service/autostart stay enabled under existing product policy; unavailable tree-change offers stay off. Reads do not reconcile autostart entries. Windows reports unsupported capability without pretending to configure a daemon. |
| `organizer_notification_settings_read/update` | Revision-bound appointment/anniversary preferences through the shared GUI handler and durable book-save acknowledgement. Explicit enablement/lead-time/wake changes additionally await correlated native scheduler/session-worker and autostart readback; a failure can occur after preferences were saved. Wake scheduling is reported separately (`null` when not attempted), without claiming notification delivery or that the machine actually woke. Linux disable can leave the existing idle session worker running. Reads expose stored and effective style/kind; Wayland rejects Organizer-style notifications. |
| `organizer_contact_settings_read/update` | Full address-preference revision and partial display/sender/sort/letter/map settings through the shared GUI handler and durable save acknowledgement. Sorting follows the selected contact to its new index letter. Hiding own profile, photos or existing groups preserves their content and membership; communication routing remains separate. No external map, letter or mail action is launched. |
| `organizer_trash_settings_read/update` | Revision-bound recycle-bin enablement and retention through the shared GUI handler and native save acknowledgement. Zero days means manual emptying only; other values match the product choices (7/30/90/365). Changing policy does not empty current trash. Disabling bypasses trash for future deletions; finite retention takes effect through the existing cleanup on book opening. |
| `organizer_reminder_privacy_read/update` | Locked-book background-reminder permission and separate confidential-content opt-in through the shared GUI handler. Reads distinguish in-memory settings from content-free native projection state. Revision-bound writes wait for the native book save and then verify the actual filtered projection or its removal, including recoverable copies; errors can follow already saved preferences. Disabling permission clears confidential disclosure. Encryption/password changes and reminder service setup are separate. |
| `organizer_password_status` | Actual unlocked native primary-file encryption state, an opaque native-source `state_revision`, and stored/current book revisions with `matches_book` to distinguish pending edits. No password, key or content is returned. The state token covers the native primary representation (including password rewrapping), and is not a portable file checksum. |
| `organizer_password_set/remove` | Existing native password transactions with mandatory `expected_book_revision` and `expected_state_revision` from status. Flushes book saves first; native current-file/content CAS rejects intervening saves or rewrapping. Success requires authenticating/readback of the resulting primary with unchanged book content. Existing platform backup/journal policies are retained and related-file changed/failed counts are separate; no claim that every related file changed successfully. A committed late response updates the same book's encryption flag without opening settings/toasts. Cancellation can follow commit; re-read status before retrying. |
| `organizer_records_export` | Full-section ICS appointments/anniversaries/tasks, Lotus CSV appointments, vCard or LDIF contacts through the shared GUI preparation and actual native codecs. Requires current book revision, book-save gate, explicit file and overwrite choice; active-profile and linked targets are rejected. Actual file-byte/SHA-256 readback confirms writing. Native skipped/loss counters are returned; raw omission count is `null` where not reported. Product format limitations remain, and private contact galleries/provider bindings are removed by the same contact preparation as the GUI. No application or mail action is launched. |
| `organizer_import_preview` | Explicit-file inspection through the actual native ICS/vCalendar/Lotus CSV/vCard/LDIF/Claws XML reader and supported bounded ZIP handling. Returns parsed section counts, source bytes/SHA-256 and an opaque format/path/content revision; optional `expected_revision` rejects a changed source before parsing. Parsed content stays inside the native/web bridge and is not returned in the MCP envelope. No book change or import/conflict dialog occurs. Native counters are `null` where unreported. This is inspection; additive import application is separate. |
| `organizer_import_review_begin` | Stage a native-parsed additive import under the current complete book revision. Existing GUI contact planning, privacy stripping, remembered rejections and reliable-time preferences are used. Optional source revision and note destination; the selected/current notebook is captured. At most two session-owned reviews are held globally, with five-minute idle expiry renewed by use. No book mutation or dialog. |
| `organizer_import_review_read` | Bounded pages of contact decisions/candidates and normalized-list counts, without large notes/photos. Includes the selection revision and unresolved count. Virtual earlier source cards remain stable candidates within the staged review. |
| `organizer_import_review_decide` | Atomic batches of up to 100 staged decisions under `expected_selection_revision`. New/skip/keep/merge/replace/newer, scalar choices, normalized list add/keep/replacement and optional birth-name preservation use the existing product model. Only offered targets/valid list indices are accepted; newer requires bound reliable timestamps. Book data is unchanged. |
| `organizer_import_review_content_read` | Cached records, sanitized incoming contacts, offered candidates and GUI-normalized lists as at most 64 KiB UTF-8/base64 byte chunks. Strings retain literal text; other values use JSON. Content revisions protect subsequent chunks; traversal stays inside the chosen staged record. |
| `organizer_import_review_cancel` | Release this session's staged review without book mutation. Session close and idle expiry release it as well. |
| `organizer_import_review_apply` | Recheck native source identity/content, complete book and selection revisions, editor/modal/sync gates and all contact decisions. Use the existing pre-contact snapshot and shared additive entity/contact handlers against isolated collection drafts. Only imported collections are committed; unrelated runtime objects retain identity. Returns product merge statistics and the new book revision after native save acknowledgement. The review is consumed at model commit, so cancellation/save failure can follow mutation and requires live-book inspection before retrying. No import dialog or toast is opened. |
| `organizer_planner_export` | Existing GUI year/month calendar model and ODS payload, with explicit year/layout/month and matching holiday/vacation/month-entry options. Requires complete book revision and save gate; does not change the selected GUI year or preferences. Pending product recurrence expansion yields `native_busy`. Uses the native document generator and explicit file/overwrite guards; actual byte/SHA-256 readback confirms the saved ODS. Office opening/rendering is not implied. |
| `organizer_contacts_spreadsheet_export` | GUI contact ODS preparation with selected/all contacts, selected columns, automatic removal of empty columns, current name order/regional dates and resolved emergency contacts. Product limits of 5,000 contacts and 4 MiB prepared payload are retained. Native source/save gates and file-byte/SHA-256 readback protect explicit destination writes. |
| `organizer_health_spreadsheet_export` | GUI health table/history ODS preparation with explicit table and blank/stored-values mode, date range, glucose/insulin scheme and one/all history charts. Current regional labels/display units are used; canonical measurements/preferences remain unchanged. Native document generation and byte/SHA-256 readback confirm the file. |
| `organizer_time_spreadsheet_export` | Original monthly time-report ODS preparation with actual product entries, selected days, pause/clock-change rules, regional labels/digits and projected public holidays. Optional document-only report-name override does not change tracking/preferences. Full book revision/save gate and actual native file readback are required. |
| `organizer_letter_export` | Shared GUI postal-address preparation and existing native letter template for a stored contact or own profile. Optional document-only sender/layout overrides, full book revision, save gate, explicit destination and overwrite choice. Confirms actual file bytes/SHA-256; returns the native format (`fodt` on Linux, `odt` on Windows), so callers can choose the corresponding filename extension. Creation does not imply office opening/rendering or mail/fax delivery. |
| `organizer_attachment_save` | Export an existing note attachment to an explicit file using the native product validator/writer and actual-file readback. Full note revision required; explicit overwrite, active-profile and symlink guards. Returns confirmed path, byte count and SHA-256. |
| `organizer_attachment_open` | Revision-bound native request to open an attachment with the registered application. Confirms operating-system launcher acceptance only; Linux waits for a successful launcher exit with a 15-second timeout. Native callbacks are correlated, including failures and late responses. |
| `organizer_appointment_read` | Appointment, provider/read-only metadata and revision token |
| `organizer_appointment_create` | Local/timed/all-day appointment, repeat configuration, alarms, participants and attachment metadata |
| `organizer_appointment_update` | Revision-checked editor fields and provider moves through the existing ICS mirror |
| `organizer_appointment_delete` | Appointment/series trash and provider tombstones; read-only records remain protected |
| `organizer_contact_read` | Contact and revision; optional product-field projection for large photos |
| `organizer_contact_create` | Local contact, typed phone/email/address lists, groups, photo and linked anniversaries |
| `organizer_contact_update` | Revision-checked editor fields while retaining unrelated vCard/provider metadata |
| `organizer_contact_delete` | Native pre-delete recovery snapshot, renewed revision check, tombstones/trash and linked-reference cleanup |
| `organizer_trash_restore` | Existing type-specific product restore handler |
| `organizer_trash_revision_read` | Complete recycle-bin revision and count without large deleted payloads. |
| `organizer_trash_empty` | Permanent complete-bin removal through the shared GUI handler, requiring the current complete-bin revision and native durable-save acknowledgement; live data and synchronization tombstones are retained. |
| `organizer_own_profile_read/update` | Separate own-profile document, full revision with optional data-field projection, and durable revision-checked creation/update through the shared GUI profile handler and typed contact validators. Profile anniversaries remain local to the profile; regular contacts/calendar records are not generated. Provider contact identity is stripped and unrelated profile fields retained. |
| `organizer_holidays_read/clear/retrieve` | Read location/settings/options and full imported-holiday revision; clear through the shared GUI handler or retrieve explicit years through the actual correlated native holiday service, applying the shared GUI importer and durable save gate. Changed settings/data or cancelled/late fetch responses are not adopted. |
| `organizer_holidays_settings_update` | Revision-checked country/region/all-region/public-holiday visibility/school-holiday settings through the shared GUI selector. Invalid cross-country selections fail without partial changes; country selection resets region and retrieval remains explicit. |
| `notes_diagnostics_read` | Ephemeral WLAN diagnostics through the confirmed own Notes connection |
| `kde_media_devices` | Current supported media devices |
| `kde_media_status` | Media state and fresh source token for `device_id` |
| `kde_media_action` | Source-token-bound player action; finite action enum, no shell command |
| `kde_players_read` | Registered music/video applications and current selection |
| `kde_player_select` | Select a registered application for the `music` or `video` slot |
| `kde_input_status` | Existing incoming-control status |
| `kde_input_settings` | Existing paired-device incoming-control settings |
| `kde_filesystem_status` | Current available filesystem devices and source tokens |
| `kde_filesystem_open` | Existing WLAN/source-bound native filesystem opening |

`tools/list` supplies the exact input schemas. The native providers retain their
pairing, source-token, application-registration, availability and lock checks.
Notes diagnostics additionally require desktop developer mode, Notes WLAN
debugging, an own-phone Wi-Fi session and current device-status permissions.
Diagnostic reports are returned through the call and are not added to book data.

Contact deletion waits for the existing native recovery-policy checkpoint.
The policy can reuse an intact checkpoint within the selected grouping interval;
MCP does not change the configured interval or force an extra checkpoint per edit.

For recurring task completion, `as_of` selects the next occurrence on or after
that local calendar date; it defaults to the book's current date. The existing
recurrence worker is awaited. The returned `completed_id` identifies the changed
entry, while a recurring master remains open. Linux and Windows retain their
native instance-UID conventions. Repeating the old revision cannot complete a
second occurrence. A detached completed instance can be reopened by its own ID.

`organizer_data_read.section` uses the existing model keys: `termine`, `aufgaben`,
`kontakte`, `notizen`, `customOrganizer`, `zeiterfassung`, `notizgruppen`,
`notizbuecher`, `jahrestage`, `feiertage`, `urlaube`, `muelltermine`, `papierkorb`,
`personen`, `schichten`, `smsVerlauf`, `smsPlanung`, `zyklusmarker`, `tagmarken`,
`gesundheit`, and `eigenesProfil`. Returned IDs are the product's IDs.

Data reads optionally select `fields` and a `path` inside that section. An `id`
first selects the root collection's entity; path strings then select its own
object fields and path integers select array positions. Nested arrays retain
pagination. Prototype traversal and filesystem paths are not supported.
For example, `section: "notizen", id: NOTE_ID, path: ["anhaenge"]` with
`fields: ["id", "name", "art"]` lists attachment metadata without inline data.

`organizer_content_read` uses the same section/entity/path selection and returns
at most 65,536 bytes per chunk. `offset`, `total_bytes` and `next_offset` are byte
positions; base64 decoding and joining the bytes before UTF-8 decoding preserves
characters split across chunk boundaries. Supply the first result's `revision`
as `expected_revision` on subsequent calls; changed content yields `conflict`.
Stored image/document data URIs are returned as their original UTF-8 strings,
not opened or interpreted by the chunk reader.
The note/task/appointment/contact read tools also accept a `fields` projection;
their revision still covers the entire entity, so large entries can be safely
updated or deleted without first returning their complete inline content.

Attachment uploads bind the note ID and entity revision at `begin`. File bytes
are appended in contiguous base64 chunks of at most 65,536 decoded bytes, up to
8 MiB per file. At most two transfers are staged across the book; tokens belong
to the creating MCP session, expire after five minutes, and are discarded on
cancel, session close or finalization. Identical chunk retries do not append twice.
`finalize` checks the declared SHA-256, then uses the actual product FileReader
validator for JPEG/PNG/WebP/GIF/PDF magic bytes, size and total note limits. The
note's revision and current book/lock/editor state are rechecked before mutation;
`persisted: true` still requires the native save acknowledgement. Staging itself
does not add anything to book data. Restoring a removed attachment uses the same
`organizer_trash_restore` handler as the graphical product.

Calendar mutations respect the current book loader's collection limits: 256
vacation periods, 64 shift definitions, 32 cycle definitions, 64 waste definitions
and 20,000 day markers. Creates beyond those bounds return `limit_reached`.
Definition names must be nonblank so entries survive the normal product reload.

Cloud-backup test bookkeeping retains at most eight request/source/book/folder
contexts for two minutes to adopt actual late worker outcomes without reopening
dialogs. A timed-out or cancelled call does not itself confirm backup success.

Password transactions retain at most eight content-free native commit correlations
until their actual responses arrive, including after RPC cancellation or timeout.
Book binding uses weakly assigned opaque identifiers rather than retaining old
book documents. Outstanding commits do not expire on a cleanup timer; a full
correlation table rejects another password action with `native_busy` before
native submission. A failed submission releases its reservation. Responses for
other IDs or replaced books cannot change the current book's encryption flag.

Staged import reviews retain parsed records only for their owning session and
unchanged book. Read/decision/content operations renew the five-minute idle
expiry. Contact cards are sanitized through the GUI review model before staged
content reads: imported data cannot grant synchronization/sharing rights or
inject local clock proofs. Candidate and normalized-list views let clients make
the same explicit choices as the GUI without opening it. Content reads are
cached; apply re-reads the actual source with the captured native revision.
Product merge counts include reviewed contact updates, and linked birthdays
follow the contact handler rather than being imported twice. `notes_skipped`
reports notes rejected by local validation, including oversized HTML. A full
review table returns `review_limit`; incomplete choices return
`decision_required`. A changed book invalidates the review. A review is one-use
once its model change begins; `persisted: true` still requires the durable native
save acknowledgement.

Planner, contact/health/time spreadsheet and letter exports accept optional
`open_with_registered_app` (default false). File confirmation remains based on
actual native byte readback. `launcher_accepted` is `null` when opening was not
requested, `true` after operating-system launcher acceptance, and `false` when
the document was saved but opening failed. Linux waits for a successful bounded
`xdg-open` exit; Windows uses the existing shell-launch result. This does not
claim a visible office window, successful rendering, printing or delivery.
Correlated late/cancelled replies do not open Organizer dialogs or toasts.

## Remaining coverage in #170

The remaining work includes other settings changes,
imports/exports and planners,
synchronization/accounts, Magnolienbaum operations,
the remaining phone/KDE actions, and complete
installed-product acceptance.
The listed tools execute their current product operations; remaining functions
are not represented by success-only placeholders.
