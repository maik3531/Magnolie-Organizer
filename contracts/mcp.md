# Organizer MCP contract

Implementation and complete product coverage are tracked in issue #170.
This document describes the implemented tools; the remaining product operations
are still being connected to the same interface.
The remaining user-facing operation groups are tracked in [the coverage checklist](mcp-coverage.md).

### Own Notes shared synchronization preferences

`organizer_notes_settings_read` selects the sole paired `peer_id` and displayed
phone `fingerprint`. It reads actual local/remote own-device confirmation,
automatic Wi-Fi preference and `{supported, initialized, ready, values}` for
the existing shared preference contract. Unsupported older peers remain readable;
these updates require shared-settings protocol v9. A read never initializes the
shared register, confirms ownership, starts a listener, subscribes to GUI events
or replays content. Initial native identity/adapter initialization may occur.

The separate process/store-bound `revision` includes the phone control context,
own-device confirmations, legacy note policy and complete shared register vectors,
including counters that do not change an effective value. Volatile status/report
contents and transport readiness do not enter that revision. Only typed consent
and preference fields are returned, never raw register metadata or content.

`organizer_notes_settings_update` requires this `expected_revision`, the same
peer/fingerprint, one `field`/typed `value` and a complete explicit `initial`:
`content_mode` (`phone_import`, `phone_scope`, `two_way`), `auto_mode` (`manual`,
`wifi`, `connection`), `skip_deletions`, `custom_enabled`, `time_enabled` (booleans),
and `time_mode` (`phone_import`, `two_way`). An existing register retains its
other saved choices; only a missing register uses the initial snapshot. The
existing GUI handler performs the update and rechecks the revision under its
mutation lock, after the Windows note-policy semaphore has been acquired.

As in the GUI, an explicit choice confirms the selected device locally as an
own Notes device and applies existing automatic-sync/deletion-grant policies.
It does not grant remote ownership. Existing control frames can be queued and
automatic synchronization can become enabled. `local_verified: true` and
`persisted: true` require actual store readback; `delivery_confirmed` is always
false. Failures, cancellation or timeouts can follow local changes or queued
frames: read state before retrying. Native replies do not modify book data or GUI
drafts/dialogs. Manual/initial content synchronization remains a separate workflow.

`organizer_notes_ownership_update` takes the same exact identity and current
Notes-settings `expected_revision`, plus `own_device`. It calls the existing
native ownership handler, with the same locked CAS and actual store readback.
Withdrawal sets local ownership and automatic Wi-Fi synchronization false and
performs the platform's existing identifier/staging/protocol cleanup. It preserves
the paired-phone binding and remote ownership confirmation and does not delete
ordinary book entries. Native cleanup can discard synchronization register metadata;
read state afterwards rather than assuming settings survive withdrawal on every
platform. Confirmation uses the currently available shared automatic mode or the
remaining stored local mode. It adds no remote consent or content grants.
`persisted: true` proves local settings only; `delivery_confirmed` remains false,
including when an existing control frame was queued while the phone was offline.

`organizer_notes_legacy_mode_update` exposes the existing older-peer manual/
automatic Wi-Fi operating choice: `auto_wifi`, `skip_deletions`, exact identity
and current Notes-settings revision. It requires both lack of shared-settings
support and absence of a retained shared register. A peer with shared settings
must use the shared preference handler instead. The existing legacy handler
confirms local ownership and grants notes/tasks together, applies its existing
new-own-device defaults and deletion protocol cleanup, then reads actual stored
ownership, mode and grants back. Remote ownership remains unchanged. The public
settings snapshot also includes actual local `skip_deletions`, independently of
a shared-register effective choice. Delivery is never inferred from saving grants.

`organizer_notes_legacy_direction_update` uses `mode: phone_import|two_way`, the
current Notes-settings revision and exact paired identity. It shares the existing
GUI note-policy handler, including fresh policy revision/epoch and pending
note-module protocol cleanup. Shared-capable peers and retained shared registers
are rejected; they use `content_mode` in the shared preference tool instead.
The settings snapshot contains `note_direction: {supported, local_mode}` with
`local_mode: null` when no explicit policy is stored. An explicit initial import
choice is stored, not mistaken for a durable write merely because import is the
default. Readback verifies the actual saved local mode. The existing import
direction/deletion protections remain; task direction and ordinary book content
are unaffected. Saving a local policy does not prove fresh remote agreement.

`organizer_notes_legacy_policy_update` selects `policy: custom|time` and an
`enabled` boolean with the current Notes-settings revision and exact paired
identity. The same GUI/native policy handlers create local policy epochs and
revisions, invalidate their existing pending transfer work and send existing
control frames. Windows custom handling is shared by GUI and MCP behind the
same note-policy gate; time handling uses its existing gate. Shared-setting peers
and retained shared registers use the shared preference tool instead. Existing
platform capability/ownership constraints apply; enabling time requires local
ownership. No remote consent, content direction or ordinary book record changes
are implied. The returned `policies.custom` and `policies.time` contain only
`supported` and `local_enabled` (null means no explicit local policy). Both raw
local/remote policy registers are included in the private settings revision,
not in the public response. `persisted` requires actual stored local enablement,
not a merely queued frame; remote delivery/agreement remains unconfirmed.

`organizer_notes_legacy_time_direction_read` reads the existing book preference,
whole-book revision and exact native Notes state. Modern peers use shared
`time_mode`; the local legacy preference never overrides it.

`organizer_notes_legacy_time_direction_start/status/cancel` runs the change as a
session-owned, process-local operation (48-hex `operation_id`, 30-minute retention,
32 retained operations, one active operation). Start requires `peer_id`,
`fingerprint`, `expected_book_revision`, `expected_notes_revision` and
`mode: phone_import|two_way`. Both revisions are checked before creation and again
at the queued write. The shared GUI data handler changes only the selected book
preference and invalidates its existing automatic-sync hash. `book_persisted`
becomes true only after native SaveACK. If an enabled native time policy changes
direction, the existing native handler is then disabled/re-enabled under fresh
Notes CAS revisions, creating the same new policy epochs as the GUI.

Phases are `preparing`, `saving`, `resetting`, `completed`, `failed`, `cancelled`.
`policy_reset` confirms both local policy receipts; `native_outcome_unknown`
marks an unconfirmed dispatched request. Completion is local work only:
`delivery_confirmed` is always false. Failure/cancellation may follow a saved
direction or a partial reset that leaves time synchronization disabled. Read
both states before retrying. Cancellation stops subsequent work, not an already
dispatched save or native request. Source/book changes, drafts and dialogs stop
further sends; late receipts never modify drafts. Session closure aborts and
removes its operations; another session cannot inspect or cancel them.

### Native call context and commands

`organizer_phone_call_read` accepts the selected `peer_id` and `fingerprint`.
Its `source_revision` binds native profile/key/current connection and current
controls. `call` contains a redacted authenticated event from that session or
null; it is explicitly not a fresh OS query. `call.revision` is a decimal string
so 64-bit revisions survive JavaScript. The observation scope distinguishes
shared call-state permission from an existing native outgoing-request scope.

`organizer_phone_call_command_start` requires the exact `expected_source_revision`,
a unique UUID-v4 `command_id` and `command: dial|answer|end`. Dial requires `to`
in E.164 form. Answer/end instead require the exact `call_ref` and decimal
`expected_call_revision`; fields belonging to another action are rejected.
The tool returns a session-owned 48-hex `operation_id` for
`organizer_phone_call_command_status/cancel`. Native owner tokens remain private.

The native owner is reserved without dispatch, then started after frontend
session/book/editor checks. Native source validation precedes the existing
command writer and actual sender claim. `receipt_persisted` confirms the local
command receipt, not a book save or phone action. Only the correlated authenticated
phone result sets `phone_result_received`; queue/transport ACKs do not. `reported`
may contain a failed phone result. `submitted` confirms neither an established
conversation nor delivery. Actual adapter/platform/permission limits apply.

Private requests preserve the existing adapters and do not enable unrelated GUI
call-monitoring grants. Cancellation stops waiting/future claims and always
reports `remote_recall_confirmed: false`; an already claimed dispatch can have
an unknown outcome. Late results and late-created handles cannot mutate drafts
or adopt another session's job. See `communications-mcp.md` for native bounds,
scope/receipt details and remaining communications integration.

### Native Notes timer control

`organizer_notes_timer_read` requests live native state from the selected
`peer_id`/`fingerprint`, returning `source_revision`, `report.revision` and
`report.restore_epoch`. This requires both peers to negotiate timer version 13,
fresh current controls, both own-device confirmations and enabled time policies.
Old peers report `unsupported_feature`; no cached state is substituted.

`organizer_notes_timer_start/pause/resume/finish` require
`expected_source_revision`, `expected_timer_revision`, `restore_epoch` and a
caller-generated v4 UUID `operation_id`, in addition to the exact peer identity.
Start optionally accepts `activity` and `note`; the other actions require the
exact active `entry_id`. Source/state revisions are CAS values, not authority.
Shared `phone_import` direction denies mutations. Actual execution uses the
existing Notes handlers, native time/zone and encrypted atomic book writer.

An exact operation retry returns a durable duplicate receipt without repeating
the command, even after reopening the book. A duplicate result may show newer
current timer state than the original command. `report.persisted=true` confirms
the actual native book write or its retained durable receipt. Reads always use
false. `runtime_request` reports only whether existing alarm/service hooks were
requested or failed; it does not claim a running OS service. Ordinary transport
ACKs and queued sends cannot complete this call.

Requests remain ephemeral and owner/source-bound. Cancellation stops waiting,
not an already dispatched command; read fresh state before retrying after an
uncertain outcome. Reports are not replayed to GUI caches or written into the
desktop book. Late replies cannot change open drafts or dialogs. See
`notes-timer-control.md` for bounds, native persistence and integration gates.

### Fresh phone device status and temporary identifiers

`organizer_phone_device_status_read` requires the latest phone-control
`expected_revision`, `peer_id` and displayed phone `fingerprint` (four hyphenated
groups of four hexadecimal digits). It uses the existing verified WLAN session,
fresh capabilities/grants, request UUID and exact source connection/key. It does
not start a listener, subscribe to GUI events, replay an outbox or read the stored
status cache. Status reports use the existing v1/v2/v3 contract; no new phone wire
version is required.

`include_identifiers` defaults to false independently of the GUI's own-phone
identifier preference. Explicit true additionally requires both own-device
confirmations, both grants, fresh own-device controls and v4 support. Android/OS
sharing restrictions remain represented by `available`, `not_shared`,
`permission_missing`, `os_restricted`, `no_subscription` or `unavailable`; unavailable
fields have empty values. Raw identifiers are never put in status/history/outbox
or GUI caches. A single-use native result token is reauthorized at UI dispatch
before raw values are serialized. Revocation, profile lock, owner/channel/key
changes and expiry prevent disclosure.

The result contains bounded `status` fields, `identifiers` or null, protocol
version, source fingerprint, receive/expiry times and explicit
`source_verified: true`, `request_correlated: true`, `persisted: false`. Results
expire within 60 seconds. Cancellation uses the exact native query UUID; matched
and retired query nonces are intercepted before the ordinary GUI/cache path, so
late replies cannot mutate GUI drafts/dialogs. Native waits are bounded to ten
seconds/eight concurrent reads. Live retired-nonce metadata is bounded rather
than evicted early; a full budget returns `native_busy`. Identifiers received by
the caller are a snapshot, not a promise that a client erases its own copy.

### Optional note email/fax handoff (#88)

`organizer_note_send_settings_read/update` uses a preference revision and native
durable SaveACK. Sending defaults to disabled. The stored/read preference object
is `{enabled, faxServer}`; update inputs are `enabled` and/or `fax_server`
(`hostname[:port]`, empty to clear), with `expected_revision`. Disabling retains
the configured server. These tools never send a document.

`organizer_note_send_state_read` reads the actual saved preferences and installed
adapter metadata. Its process/store-bound native `revision` pins the settings and
selected adapter context. Discovery does not start a client or connection.
Linux supports registered compatible mail through `xdg-email --attach` and
explicitly configured HylaFAX through installed `sendfax`. The path-based email
attachment adapter is unavailable in Flatpak. Windows uses a registered compatible
Unicode Simple-MAPI client and has no implicit fax adapter. Fax phone metadata
alone does not enable fax handoff.

`organizer_note_send_start` requires `expected_book_revision`,
`expected_state_revision`, explicit distinct note `ids`, `kind: email|fax` and
`recipient`. Optional `contact_id` pins that recipient to the contact's current
email/FAX values; `subject` is optional. The shared GUI print-page builder creates
exactly the selected note text printout; embedded images/PDF attachments are not
added. No HTML, executable, arbitrary file path or printer is accepted as a tool
input. The UTF-8 page is bounded to 750000 bytes and the actual private PDF to
32 MiB, with readback/digest validation. Native preferences and adapter context
are checked again immediately before external handoff.

Start returns a session-owned opaque `operation_id`, initially possibly `saving`.
It is not a native-dispatch or PDF-success acknowledgement. Poll
`organizer_note_send_status` for the correlated phase (`saving`, `preparing`,
`ready`, `external_pending`, `handed_off`, `failed`, `cancelled`) and error code.
Handoff receipts carry the actual PDF byte count/hash and adapter identity.
`delivery_confirmed` is always false. Mail compose/client acceptance and a fax
server queue acceptance are not recipient delivery proof.

`organizer_note_send_cancel` prevents external dispatch while preparation is
pending. `cancel_accepted: false` can also mean the operation already finished;
inspect its phase. Already dispatched client/server work cannot be recalled.
Cancellation may leave PDF generation running solely to complete cleanup.
Timeouts or post-dispatch errors expose an unknown native outcome; inspect the
existing operation/application instead of creating another send. Native operation
IDs make an exact start replay idempotent, and another MCP session cannot inspect
or cancel the job. Session closure requests best-effort cancellation of pending
work and suppresses late GUI changes. Completed private handoff PDFs are cleaned
on the next use after one day. No send changes the original notes or memberships.

### Contact-group search (#177)

`organizer_contact_groups_list` returns canonical/display group names and counts,
including empty standard groups and names retained in exclusion rules.
`organizer_contacts_search` accepts optional `query`, `group_mode: all|none|group`
and `group` (required only for `group` mode). It shares the GUI's existing
full-text/phone matcher and membership selection. Results span all alphabet tabs
and contain IDs, display names and canonical/display memberships. The hidden
provider system group `MY CONTACTS` does not prevent `none` from matching.

Both tools are read-only, use `offset` and `limit` (1–100), and return `revision`,
`total`, `next_offset` and `entries`. Optional `expected_revision` pins subsequent
pages to the same result set; a changed result yields `conflict`. Canonical or
translated standard names and escaped custom names use the existing group data.
Reading/searching changes neither the GUI filter/card/editor nor the stored book.

### Contact-group exclusions (#160)

`organizer_contact_group_exclusions_read` returns `settings` and its `revision`.
`organizer_contact_group_exclusions_update` takes `expected_revision`, optional
`enabled`, and optional `notifications`, `anniversaries` and `overview` rules.
Each rule has `scope: birthdays|anniversaries` and `groups: [name, ...]`;
`overview` additionally has `calendar: boolean`. Omitted areas are retained.
Disabling retains every group's choice and scope. Success requires the native
durable SaveACK and returns `persisted: true`; stale settings return `conflict`.

The same policy drives GUI anniversary lists, appointment overview and optional
calendar marks, plus native reminders. Any excluded membership wins. Canonical
and translated standard group names resolve to existing memberships; custom names
are preserved. Contact identities/aliases and strong merged-source identity are
used; an equal title/name alone is insufficient. Contacts, provider records and
group memberships are not rewritten. Reminder privacy projections apply the
decision before removing contact identity, so they contain no address book or
group membership data.

### Appointment and task category colors (#183)

`organizer_category_colors_read` returns the local palette as `colors: [{name,
color}]` and its `revision`. `organizer_category_colors_update` replaces that
palette with `expected_revision` and `colors`; a successful result includes the
saved count and `persisted: true` only after the native durable-save acknowledgement.
Names are NFC-normalized, compared without case, and cannot contain commas,
semicolons or control characters. Colors are six-digit hexadecimal RGB values.
Duplicate normalized names are rejected. A stale revision yields `conflict`.

Existing appointment/task create and update tools accept `categories` and
`accent_color` (`#rrggbb`, or an empty string to clear the override). The entry's
custom color takes precedence over the first matching comma-/semicolon-separated
category. Removing a palette definition does not alter categories on entries or
provider metadata. The same shared color rules apply to the GUI and planner
HTML/ODS output. Colored open tasks appear on their due date, falling back to
their start date, using the existing recurrence expansion. Standard ICS interchange
preserves `CATEGORIES` and the custom `X-MAGNOLIE-ACCENT-COLOR` property; support
for displaying that private property in other programs is not assumed.

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

### Waste calendar import

Before choosing CSV columns, `organizer_waste_import_source_read` exposes exact
native-parsed CSV rows/headings or the five date/time/title/location/note fields
shown in the GUI's ICS preview. It returns at most 64 KiB of a JSON array as a
base64 UTF-8 byte chunk, with total records/bytes, offset/next offset, source-byte
revision/digest and a separate exact parsed-content SHA-256. Concatenate bytes
before UTF-8/JSON decoding; carry both `expected_revision` and
`expected_content_sha256` on subsequent chunks. No mapping or book write occurs.

`organizer_waste_import_preview` uses the native waste ICS/CSV reader and the
existing GUI date/group model. CSV input requires explicit zero-based column
mapping, heading-row choice and ISO/dotted/day-first/month-first date format;
`type_column: -1` uses `custom_name`. Optional location/note/UID columns default
to `-1`. ICS rejects CSV mapping. The bounded result contains at most 64 group
types with suggested display name/kind/color, raw event counts and first/last
source dates, the actual file-byte digest/revision, `book_revision` and a
`mapping_revision` binding the source revision and exact mapping object.
Preview leaves the book unchanged and opens no GUI import dialog.

`organizer_waste_import_apply` requires the preview's source, book and mapping
revisions, the same mapping, and explicit selected group types (optional
display-name/kind/color overrides). It re-reads and verifies the actual file,
uses the same GUI normalization, stable source/UID/value identities and draft
engine, verifies the book again around the mandatory native pre-change snapshot,
then waits for durable save before returning `persisted: true`. Replays and UID
date corrections retain IDs; absent old dates are retained as in the GUI rather
than replacing a whole feed. Manual waste rules and ordinary appointments are
retained. The waste calendar is enabled as by the GUI import. A failed save or
cancellation after assignment may follow applied data; re-read before retrying.

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
| `organizer_sync_settings_read` | Calendar/address-book selections and GUI sync preferences under a revision covering the complete sync preference object |
| `organizer_sync_settings_update` | Shared GUI selection/preferences, native validation of newly linked IDs and durable save; preserves offline selections and existing record/provider routing |
| `organizer_sync_start/status` | Actual shared GUI/provider synchronization workflow with native-start acknowledgement, three-way adoption, durable saves and actual journal-commit proof where required; bounded status without provider records/errors |
| `organizer_contact_provider_conflict_read/resolve` | Stored contact/provider review through existing platform decision builders and source-approval handlers, contact revision/checkpoint/save guards, no immediate remote write |
| `organizer_dav_account_read` | Actual local shared GUI Nextcloud/generic-DAV configuration and credential-presence metadata, with a process-bound keyed native revision and explicit unreadable states; no secret values or connectivity claim |
| `organizer_dav_connection_test` | Fresh read-only CalDAV/CardDAV discovery through GUI readers, checked against the expected native account revision before and after the request; collection counts, partial discovery and sanitized failure codes, no mailbox/write-permission test |
| `organizer_mailbox_write_test` | Actual GUI Nextcloud mailbox MKCOL/conditional random probe PUT/DELETE under a pinned account context and expected native revision; explicit probe acknowledgements and possible remote changes, no delivery claim |
| `organizer_microsoft_account_read` | Windows direct Graph effective public client ID, protected-token file presence and native sign-in activity, without token decryption or authentication claims; explicit unsupported-feature result on Linux |
| `organizer_microsoft_account_action` | Native-revision-bound Graph client configuration or sign-out, actual local store readback and pending OAuth/sync fencing, shared with the GUI |
| `organizer_microsoft_sign_in_begin/read/cancel` | Session-owned asynchronous Windows device-code flow shared with the GUI; public user code/verification URL, actual native state/cancellation and protected-token readback, without exposing provider tokens |
| `organizer_internet_accounts_read` | Paged managed Windows Google/Microsoft inventory and login/task availability metadata under a public-state revision; may start the existing configured helper, without token/authentication claims |
| `organizer_internet_account_action` | Shared GUI managed-account sign-in/edit launch or revision-checked rename/removal with actual status readback; provider-owned dialogs, not completed-authentication claims |
| `organizer_dav_account_update` | Full explicit native DAV configuration with expected native revision, optional credential replacement/clearing, shared GUI transaction and verified config/credential readback before persisted success |
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
| `organizer_import_review_begin` | Stage a native-parsed file or explicit local-source import under the current complete book revision. Existing GUI contact planning, privacy stripping, remembered rejections and reliable-time preferences are used. Optional source revision and note destination; the selected/current notebook is captured. At most two session-owned reviews are held globally, with five-minute idle expiry renewed by use. No book mutation or dialog. |
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
| `notes_diagnostics_read` | WLAN diagnostics and, on supporting Notes versions, the saved Android crash report through the confirmed own Notes connection |
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
Device-status version 13 adds optional `diagnostics.crash_report` with
`available`, `text` and `truncated`. The original version-11 WLAN-only response
is retained for older phones. The crash read uses the same pinned session,
developer opt-in and source/grant checks; see
[the version-13 contract](phone-developer-crash-diagnostics-v13.md).

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

`organizer_sync_start` requires the complete current book revision and starts
the same selected-provider workflow as the GUI, including the existing Windows
contact-cleanup preparation. It returns preparation status, not a completed
operation receipt. Read `organizer_sync_status` until its latest book-bound run
is terminal. The phases distinguish preparing, dispatching, receiver-confirmed
running, result saving, journal committing, completed and failed. Transport
submission (`native_dispatched`) is separate from receiver confirmation
(`native_started`). Queued native work discarded by a restore fence produces a
correlated failure instead of silently leaving the run pending.

Results use the GUI's existing three-way collection reconciliation and source/
baseline adoption. A completed run requires actual native book SaveACK. If its
native result carries a journal transaction, it additionally requires a
correlated successful commit after the native saved-result proof; a plain Linux
EDS run has `commit_required:false` and makes no journal-commit claim. Partial
provider failures retain adopted/persisted state without claiming success.
`saved_book_revision` describes the acknowledged saved snapshot; record counts
describe the normalized adopted result, not remote changes or later concurrent
edits. `running` includes the product's frontend/preparation state and outstanding
MCP work; the per-run fields distinguish native acknowledgements from pending
submission. Raw provider reports and records are excluded from status results.

The latest run is global to the open product/book, rather than owned by the
transport session: closing a client or cancelling JSON-RPC waiting does not stop
the existing provider workflow or roll back changes. A later client can inspect
it. Native results still pass book/epoch/request checks, preserve newer local
edits and unsaved GUI drafts, and do not open MCP-triggered dialogs/toasts.
Failures/timeouts can follow remote or local changes; inspect before retrying.

`organizer_contact_provider_conflict_read/resolve` inspects the stored native
contact snapshot and applies the same platform-specific GUI review logic. The
contact revision includes its mapping/conflict metadata; a native pre-contact-
merge checkpoint and durable SaveACK precede confirmed success. The conflict
source must actually be stored on that contact. Scalar and zero-based normalized
list choices are validated against the offered contact/list data. Reliably-newer
requires both actual trustworthy times; callers cannot supply replacement times.
Linux reuses its file-review draft planner and EDS/DAV approval/baseline rules,
including keep-only handling of a deleted remote card. Windows reuses its system
conflict draft builder, explicit empty-list and extra-array choices. Read `options`
for these existing platform differences. Resolving makes only the local reviewed
decision; the next actual synchronization performs any permitted remote write.

Synchronization preference writes accept calendar IDs, an address-book ID,
startup synchronization, success notifications and the reliable-newer-contact
policy. Newly linked IDs are checked against a fresh correlated native source
lookup; existing saved offline IDs can be retained, and clearing selections works
without source discovery. A still-selected primary calendar is preserved even if
the array is reordered; removing it selects the first remaining calendar, exactly
as the GUI does. Empty selections disable those links. Other phone/time preferences,
entity bindings, provider metadata and pending synchronization transactions remain
intact. These tools update preferences, not account credentials or a running sync
transaction. Revision checking includes the unexposed sync preferences as well.

`organizer_dav_account_read` reads the native persisted account/credential
snapshot used by the GUI. The opaque keyed revision binds configuration, native
storage identity and credential state (Linux's actual Secret Service value or
Windows' protected credential blob); it is neither a portable file checksum nor
an exposed password digest. Native saves and snapshot reads share their store
gate. A failed credential/config read has a null revision and unknown credential
presence, with explicit native state/error code. Windows presence describes the
native credential file, not a new DPAPI-decryption or authentication test.
`connectivity_checked` is always false. Passwords, protected blobs, authorization
headers and native error text are excluded; correlated/late replies leave GUI
account drafts and book data untouched.

`organizer_dav_account_update` supplies a complete account type/server/user and
DAV/mailbox enablement under `expected_revision`. Empty/omitted application
password retains the current value under the native endpoint-binding rules;
explicit clearing requires disabled services, and generic DAV cannot enable the
Nextcloud mailbox. The same GUI transaction writes native configuration and its
credential backend. Expected revision is rechecked inside the store gate and
actual normalized config plus new/retained/deleted credential state is verified
before `persisted: true, verified: true`. Successful writes also advance an opaque
per-store process epoch, so rewriting the same credential does not expose a
stable password-equality fingerprint. Credential values and protected blobs never
appear in results or book data. Verification failure/cancellation/timeout after
dispatch may follow native changes; re-read before retrying. Normal existing
runtime applies to enabled services, but the call does not verify connectivity
or authentication.

`organizer_dav_connection_test` requires that native account revision and an
active DAV account with a stored credential. It uses the existing GUI discovery
readers and verifies the revision again after discovery. This detects concurrent
account changes; it is not an atomic server snapshot. The result reports fresh
`connectivity_checked: true`, reachability, partial discovery, collection counts
and a sanitized error code. An authentication/network rejection is a completed
test with `reachable: false`, not a successful connection. Existing platform
discovery behavior applies, including available partial results. The call does
not read contact/calendar records, synchronize, test record-write permissions,
or create a mailbox write probe (`mailbox_tested` and `write_permissions_tested`
are false). Native request deadlines apply; cancellation or an RPC timeout can
leave bounded read-only discovery finishing in the worker. Correlated late
responses do not modify GUI drafts, dialogs or book data.

`organizer_mailbox_write_test` is a separate **writing** operation against the
enabled Nextcloud mailbox account. It reuses the GUI probe, with the native
account/credential context pinned before any remote writes and revision checks
before/after the operation. It ensures the normal six-folder mailbox hierarchy,
conditionally PUTs a random write-test object, and attempts to DELETE it. Normal
folders can remain even after a passing test. `write_test_passed` and
`probe_delete_acknowledged` are true only when both native PUT and DELETE calls
completed successfully; this acknowledges the response, not an independent
readback of absence. A failure conservatively leaves the delete acknowledgement
false/unknown. `remote_state_may_have_changed` is always true for completed tests;
revision errors, cancellation and timeouts can also follow writes or leave a
probe behind. Inspect remote state before retrying. `delivery_confirmed` is
always false. Neither book records nor GUI account drafts are changed. Login
actions and full synchronization remain coverage work.

`organizer_microsoft_account_read` reads the Windows direct Graph integration's
effective public OAuth client ID through `GraphConfiguration`, with user override
and existing build fallback. The ID is returned in canonical GUID form. It reads
only protected-token file **presence**, never token contents or DPAPI plaintext,
and reports whether the existing native device-code operation is active.
`connectivity_checked` and `authentication_verified` are always false; neither
file presence nor an active sign-in proves a valid session. The returned native
revision is process-keyed over the actual configuration sources, protected-token
bytes, store identity and operation epoch. It is neither a portable file checksum
nor a public password/token fingerprint. Metadata sampling shares the native GUI
commit gate; it is not an atomic remote-account snapshot. Correlated late replies do not update GUI drafts.
Linux returns `unsupported_feature` for direct Graph; its system-managed EDS
accounts remain visible via `organizer_sync_sources_read`.

`organizer_microsoft_account_action` requires that native revision. `configure`
uses the actual GUI configuration transaction and verifies its user override;
empty `client_id` removes that override and restores the build fallback. A changed
effective client cancels pending sign-in/Graph-sync work and deletes the old token.
`sign_out` cancels those operations, advances the native epoch, deletes the token
file and verifies absence. Sign-in and refresh-token commits check cancellation,
client identity and epoch inside the same native gate, preventing a late result
from recreating signed-out credentials. The returned `persisted:true, verified:true`
confirms local configuration/token storage, not remote token revocation or
authentication. A cancelled/failed RPC can follow native changes; re-read before
retrying. Correlated responses remain GUI-draft-neutral.

`organizer_microsoft_sign_in_begin` binds the expected effective public client
ID and starts the existing GUI OAuth device-code implementation asynchronously.
Its `flow_id` is random, local to the initiating MCP session and valid for at most
21 minutes. The native worker is bounded by 16 minutes and the existing process/
restore lifetime. Read the flow for `starting`, `pending`, `succeeded`, `failed`
or `cancelled`; only `pending` exposes the public `user_code`, HTTPS
`verification_uri` and expiry Unix seconds. Internal provider device/access/
refresh tokens and raw native errors never appear in tool results. Browser
opening defaults off; `open_browser:true` uses the same registered launcher as
the GUI, with acceptance reported separately from authentication.

GUI and MCP use the same provider request/poll runner. The expected client,
active operation, cancellation, profile and restore gates are checked before
storing a token. Native configuration changes share the commit gate. A succeeded
flow requires the actual protected-token store to be read back and compared.
`persistence_verified` describes that completed transaction, not current account
validity or a remote-record permission test. `token_storage_may_have_changed`
preserves ambiguity after attempted storage, including verification failures.
Cancel requests stop a pending flow without undoing a completed commit and
cannot cancel a later unrelated GUI flow. Read until terminal. Session close,
failed/cancelled begin and handle expiry request cancellation; a cancelled read
only cancels that status request. Closing/replacing the book invalidates the web
handle at its next use. Native late replies do not replace GUI drafts or open
dialogs/toasts. Starting does not perform synchronization. Direct Graph remains
explicitly unsupported on Linux.

The managed Windows Internet-account tools use the same serialized
`ManagedAccountOperations` handler as the GUI and the existing owned runtime/
Thunderbird account bridge. Status can start/reconcile an already configured
helper; an unconfigured status read leaves it off. Consequently the read tool is
annotated with possible local/helper side effects. The public revision covers
the complete sorted sanitized inventory, login-pending/task-availability state
and error-presence flags, not passwords or provider token validity. Entries are
paged at 100; native inventory is capped at 1000 accounts. No raw provider errors,
token values or arbitrary provider fields are returned.

`organizer_internet_account_action` accepts `sign_in`, `rename`, `remove` or
`edit`, requiring that native revision. Sign-in providers are `google`,
`personal-ms` and `office365`; existing-account providers are `google` and
`microsoft`. Changes target an account actually offered by the latest read.
Pending sign-in blocks another mutation; profile/restore/sync gates apply.
Rename/removal requires a subsequent actual status read to confirm the desired
name/absence and sets `change_verified:true`. Sign-in/edit only acknowledge
starting the existing provider interface. `authentication_verified` is always
false. The native request deadline is 20 seconds; queuing, helper startup,
provider dialogs and committed changes can outlive RPC cancellation or timeout.
Inspect current state before retrying. Correlated results do not update GUI
account drafts or book data. Linux reports explicit unsupported capability for
this Windows-only helper; existing system EDS accounts remain separate.

For local imports, supply `local_source` (`evolution`/`thunderbird` on Linux,
`windows_contacts`/`thunderbird` on Windows) and optional `local_scope`
(`contacts`/`all`, default all) instead of file `format`/`path`. The existing GUI
readers inspect local databases/files/caches without network discovery. Unsupported
platform sources fail explicitly. The opaque native revision binds source/scope
and actual parsed semantic records (excluding generated top-level import IDs),
not physical database bytes or a filesystem-wide atomic snapshot. Apply re-scans
the selected source and verifies this revision before the existing shared review
commit/checkpoint. Changes to generated IDs alone do not invalidate a review; actual
content, UID, metadata or selection changes do. Parsed record snapshots are bounded
to 32 MiB, apart from small envelope metadata, and only one correlated local scan runs per
native process. No arbitrary profile root path is accepted over MCP.

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

## Magnolienbaum controls and content

`organizer_tree_status` reads the actual native identity, service state, public
peer fingerprints/permissions, queue counts, incoming IDs and introductions.
Peers, incoming IDs and introduction offers are paged at 100 using the same
offset/limit, with independent totals and a continuation while any list has more
items; inbox bodies and private identity keys are excluded.
The process-keyed revision binds the stable control plane, including invitations
and introduction offers, rather than heartbeat or retry counters.

`organizer_tree_action` invokes the existing native enable/name, discovery,
public-address lookup,
fingerprint-bound pairing/confirmation/removal, partner preferences, introduction
permission/transfer/acceptance and selected inbox-removal handlers. Mutations
require the control revision. Targeted operations require explicit fingerprints.
Results distinguish local verification from delivery; enabling retains the
existing system firewall-permission flow. Native worker callbacks are captured
only for the correlated operation; listener/maintenance events retain normal
GUI handling. Late responses do not rebuild settings or show a toast. Public
address lookup uses the GUI's fixed external IP service and returns its parsed
address; this does not prove port reachability, firewall/NAT forwarding or a
working peer connection.

`organizer_tree_pairing_document` creates/imports the actual transferable pairing
JSON through the existing invitation codec and store. Creation persists a
time-limited invitation. Import retains signature, fingerprint and destination
validation and can contact the document's destination. Returned documents are
bounded to 8 KiB and contain no private identity key. Creation accepts an optional
explicit output `path` and opt-in `overwrite`; a file receipt contains the actual
path, byte length and SHA-256 after native atomic write and exact byte readback.
JSON output uses the actual invitation document. Linux additionally supports
`format:qr_svg`, reusing the existing pairing-link/QR renderer and its
render-before-invitation-commit order. The SVG is returned as a bounded data URI
and can be written/read back at the explicit path. Windows reports
`unsupported_feature` for QR output because its native tree has no QR renderer;
it does not create an invitation for that unsupported request. Output options
apply only to creation. An invitation can already be persisted if a later
file-write/readback fails; inspect tree state before retrying. `read_file` reads
and validates an explicit native pairing file with the existing 8 KiB codec
limits and returns the document plus raw-byte digest without importing it.
`import_file` requires that exact `expected_file_sha256` before the existing
native pairing transport can run. These are format-specific reads, not arbitrary
filesystem content access.

`organizer_tree_inbox_read` returns one actual stored item's UTF-8 JSON in base64
chunks of at most 64 KiB, with raw-byte SHA-256 and offsets. Continuations require
that digest; changed/removed content fails explicitly. Decode after concatenating
bytes, because a chunk can split a Unicode character.

`organizer_tree_content_send` shares saved notes, appointments and address cards,
delegates saved tasks, or returns a received task's completion status to its
recorded origin. It requires current record/control revisions and the recipient
fingerprint. GUI payload builders are shared; contacts omit identity/provider
bindings and photographs, appointments retain the existing bounded sanitizer,
and notes retain recipient-specific source IDs. New note-sharing/delegation
metadata is durably saved before sending. The actual native outbox commit is
read back before reporting `queue_persisted:true`; `delivery_confirmed` is always
false. Native batch delivery counters do not prove this item's delivery. Payloads
over the bounded MCP frame are rejected before sending.

`organizer_tree_inbox_apply` explicitly accepts a task, appointment, address card,
contact-sync/deletion, note or note-update offer via the existing domain handler. It requires the exact
inbox digest, complete book/control revisions and confirmed sender fingerprint.
Content chunks are independently SHA-256 checked. A native recovery checkpoint
precedes isolated-draft adoption; book SaveACK precedes content-checked native
inbox removal and removal readback. Explicit manual note acceptance follows the
GUI replacement semantics. Contact synchronization requires an explicit
`contact_decision`: `auto`, `new`, `keep`, `merge`, `replace`, `newer` or `skip`. Existing targets
require `contact_id`; merge supports field choices, incoming list positions,
existing replacement positions and whole-list replacement. The shared contact
merge also accepts `group_choice: keep|incoming` for known version-4 incoming
groups, defaulting to `incoming`. This selects the complete editable membership
set, including explicit empty removal; it never unions removed memberships back.
Legacy offers without group information preserve memberships and reject an
explicit group choice. Group choices are rejected for other decision modes.
The shared contact
decision handler preserves bindings, local identity, photo alternatives and
reliable-modification-time policy. `newer` fails when reliable timestamps are
unavailable. Deletion requires `delete` and the peer's existing deletion
permission and uses the existing trash/deletion-memory handler. Inspect incoming
content with `tree_inbox_read` and current contacts with the existing read tools
before deciding. `skip` saves the GUI's content-bound rejection memory and then
consumes that exact inbox item; changed future offers are distinct decisions.
`auto` invokes the GUI batch matcher's existing known-version, binding,
augmentation, remembered-rejection and reliable-newer rules. Unresolved conflicts
remain in the inbox for an explicit target/field/list decision; the client can
process inbox IDs in sequence with fresh book revisions. The same staged
contact-plan adoption and timestamp handler is shared with the GUI batch path.
A save can succeed before later inbox consumption
fails: inspect both book and inbox before retrying, particularly for appointment
and address-card offers which create new records.

`organizer_tree_sync_start/status/cancel` runs the shared notes/tasks selection or
complete contact snapshot asynchronously. A confirmed peer fingerprint and full
book/control revisions authorize the run. Notes/tasks retain introduced-peer
source restrictions, note alias/source IDs and the optional remote-sync request.
Contacts use the shared complete-snapshot preflight and metadata/payload builder,
negotiated legacy/modern versions, content hashes and reliable modification
timestamps. Empty snapshots and the existing deletion safety limits block a
contact start; this path does not automatically send deletion proposals.

All prepared messages must fit the bounded native frame before the isolated
metadata draft is adopted. Native book SaveACK precedes serial queueing. Each
send checks the frozen source and native control revision and requires verified
native outbox acceptance. Status reports preparation, saving, queueing and
terminal phases, metadata persistence, message totals and acknowledged queue
counts. Completion does not mark contacts remotely synchronized or enable
deletion proposals merely from queue acceptance. Cancellation stops further
sends/RPC waiting but an already dispatched native operation can still change
state. A terminal run can therefore have saved metadata and a partial queue.

`organizer_tree_contact_preview` returns the existing new/bound counts, paged
duplicate-contact ID pairs and permitted stored deletion tombstones, together
with the full book revision. Shared preflight checks protocol compatibility and
bounded MCP payloads without modifying contact bindings or exposing photos.
`organizer_tree_contact_delete_proposal` sends one explicitly selected tombstone
using the existing successful-sync, peer-permission, bound-snapshot and deletion
count safeguards and shared deletion payload builder. It requires the current
book/control revisions and peer fingerprint. Arbitrary deletion payloads and
queue-only success flags cannot authorize this operation.

Cancellation, timeouts and errors can follow local/native changes. No result
implies that cancellation rolls back saved metadata, queued content or adopted
records. Portable native fixtures and the private Linux GTK/stdio/store/adoption
probe are separate from physical paired-peer/installed-product acceptance.

## Notes phone connection controls

`organizer_phone_connection_read` reads the actual native phone-control store and
runtime snapshot. It returns public identity/fingerprints, listener/pairing state,
pending verification codes and attempt IDs, declared capabilities, editable
permission names and per-peer local/remote grants. Pairing tokens, private keys,
cached device-status contents, notifications and personal-sync payloads are
excluded. Peer, pending and platform Bluetooth-inventory lists share bounded
offset/limit pages. Linux uses its existing local service or daemon proxy without
starting a listener, subscribing to GUI events or replaying personal content.
Initial identity/adapter initialization can occur. Windows explicitly reports
that OS-paired Bluetooth enumeration is unsupported by this native adapter.

The control revision is keyed to the native process/store and covers identity,
stored preferences, peer keys/grants/capabilities and pending pairing attempts.
Volatile contact timestamps, transport observations and OS device observations
do not change this control revision. Actions still check current platform
availability and identity at their native commit point.

`organizer_phone_connection_action` runs the shared native enable/disable,
pairing-window begin, attempt-bound confirmation/cancellation, removal, editable
grant and Bluetooth preference handlers. Targeted changes require the peer ID
and fingerprint; pairing decisions also require the current native attempt ID.
There is no implicit pending-attempt fallback. Begin requires an enabled,
listening connection; enabling can invoke the existing OS firewall permission
flow. Native preferences are revision checked and actual store contents are
read back. Removal retains existing queue/permission/runtime cleanup.

`persisted:true` refers to verified local configuration, not delivery of a grant,
completed phone authentication, an OS Bluetooth pairing or an established data
link. Pairing-window/decision results report local runtime acceptance with
`persisted:false`; inspect subsequent native state for completed pairing.
`delivery_confirmed` is always false. Bluetooth preferences retain each
platform's existing capability/address/system-pairing checks. Unsupported or
fixed grants cannot become freely writable through MCP.

Immediate worker callbacks are scoped away from GUI reconstruction/replay.
Long-lived native service workers retain their normal event context. Linux
daemon operations reuse the existing owner and setup-session mutation guards;
they do not create another listener. A stored disabled flag without verified
worker shutdown is not accepted as a successful shutdown receipt. Cancellation,
timeouts and errors can follow native changes; inspect current state before
retrying. Portable/native fixtures and private GTK/stdio/store checks do not
stand in for a physical Windows/Notes/Bluetooth pairing acceptance.

These controls do not complete the remaining KDE lifecycle, general device-status
privacy paths, own Notes synchronization or communications groups.

## Existing KDE integration lifecycle

`organizer_kde_connection_read` projects the selected integration's actual stored
peer pins, discovered candidate source tokens and pending native verification
attempts. All three lists share bounded offset/limit pages and independent
totals. Clipboard text, file payloads, SMS/history and private certificates are
excluded. The process/store-bound revision covers control state, not volatile
discovery ages. A candidate token binds its observed ID, endpoint, available TLS
pin and connection generation; it does not establish trust.

Reads do not start a transport, subscribe to GUI events or activate the system
KDE service. Linux reuses its selected direct integration or daemon proxy;
the system adapter queries the existing D-Bus owner without auto-start and binds
observations to that owner and available trusted-certificate pins. Its
pairing/removal/receive-permission limits remain explicit. Unknown system local
identity/listener facts are null, not synthesized. On Windows a metadata read
does not instantiate another lazy native backend; an uninitialized integration
is reported unavailable until explicit refresh or normal application startup.

`organizer_kde_connection_refresh` invokes actual selected-integration
start/discovery/refresh methods. It can explicitly activate the installed system
service, or initialize the existing native transport once. It never creates a
second fallback integration or enables arbitrary plugins. An optional current
revision rejects a stale readable control snapshot; omission permits explicit
refresh while the selected system service is unavailable. Local request
acceptance is separate from pairing, reachability and delivery; `persisted` and
`delivery_confirmed` are false.

`organizer_kde_pairing_begin/status` runs begin/complete/renew asynchronously with
a session-owned operation ID. The current revision and candidate ID/source token
are mandatory; renewal also binds the one old peer ID and certificate pin.
Native candidate selection/TLS/staged-link handlers are shared with the GUI.
The pending native context receives its own attempt ID and MCP ownership marker.
Stored peer-state guards are checked again at the actual native pairing commit,
including native same-name/replacement cleanup. Native deadlines remain in force.

Pending status refreshes live native state. A paired terminal status records
observed local trust in that exact certificate; use `connection_read` for current
state. It does not promise delivery or continued reachability. At most eight
operation handles are retained for three minutes. Session closure removes its
handles and aborts RPC waiting; an already dispatched native handshake can still
finish establishing a pending context. Timeouts/errors therefore require reading
native connection state before retrying, rather than assuming rollback.

`organizer_kde_pairing_decide` accepts/rejects one exact live peer/attempt/pin
under the current revision. A local accept can remain pending until the phone
confirms. `paired_verified/persisted:true` require the actual native trust-store
commit marker and stored-pin readback, not just a previously known peer or a sent
confirmation packet. MCP-owned late pairing/rejection/timeout events do not open
legacy GUI verification dialogs; normal independent native events retain their
usual routing.

`organizer_kde_connection_remove` uses the existing complete native lifecycle
cleanup where available, with pinned target/revision and store-absence readback.
The Windows native handler cancels operations and removes staged/active/trust
state. The system adapter and Linux direct adapter without a complete offered
removal handler explicitly report unsupported; MCP does not merely delete a
trust-file entry and pretend connections/queues were cleaned up.

Platform limits are tested separately from private native transport/store tests.
A private network namespace is required for active KDE transport acceptance so
its protocol ports do not create another host listener. These proofs are not a
physical Windows/Android/KDE installed-package acceptance. KDE incoming
clipboard/file permissions, proposals and other device actions remain separate
coverage work.

## Remaining coverage in #170

The finite remaining operation groups are tracked in
[mcp-coverage.md](mcp-coverage.md): phone/KDE lifecycle, own Notes synchronization,
communications, other offered KDE actions, running time tracking and remaining
utilities/preferences, followed by complete installed-product acceptance.
The listed tools execute their current product operations; remaining functions
are not represented by success-only placeholders.
