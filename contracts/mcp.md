# Organizer MCP contract

Implementation and complete product coverage are tracked in issue #170.
This document describes the implemented tools; the remaining product operations
are still being connected to the same interface.

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
| `organizer_appointment_read` | Appointment, provider/read-only metadata and revision token |
| `organizer_appointment_create` | Local/timed/all-day appointment, repeat configuration, alarms, participants and attachment metadata |
| `organizer_appointment_update` | Revision-checked editor fields and provider moves through the existing ICS mirror |
| `organizer_appointment_delete` | Appointment/series trash and provider tombstones; read-only records remain protected |
| `organizer_contact_read` | Contact and revision; optional product-field projection for large photos |
| `organizer_contact_create` | Local contact, typed phone/email/address lists, groups, photo and linked anniversaries |
| `organizer_contact_update` | Revision-checked editor fields while retaining unrelated vCard/provider metadata |
| `organizer_contact_delete` | Native pre-delete recovery snapshot, renewed revision check, tombstones/trash and linked-reference cleanup |
| `organizer_trash_restore` | Existing type-specific product restore handler |
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

## Remaining coverage in #170

The remaining work includes mutation handlers for the other product sections,
settings changes, notebooks/groups and attachments, imports/exports and planners,
recovery/backup operations, synchronization/accounts, Magnolienbaum operations,
the remaining phone/KDE actions, and complete
installed-product acceptance.
The listed tools execute their current product operations; remaining functions
are not represented by success-only placeholders.
