# Lotus Organizer 6 native import

Issues: #212 (basic import), #222 (remaining legacy features).
Both Organizer editions use the existing `lotus` import route for
CSV and binary `.or6` files, including eligible entries in bounded ZIP archives.
The preview and staged-review MCP tools keep their existing schemas, source
revisions, book revision checks, cancellation and GUI-draft boundaries.

## Supported subset

- Basic appointments: description, local date/time, explicit end, confidentiality
  and tentative flag. No time-zone conversion is inferred from the legacy file.
- Tasks: description, due date, priority and completed state.
  Independently verified native status values 1/2 (open) and 4 (completed)
  take precedence over a completion timestamp that a Lotus reexport may retain
  on an open task (#567). Unverified/missing status layouts retain the previous
  timestamp fallback.
  Verified finite repeating-task sets retain their original native repeat-object
  links, occurrence indices and start/due arrays as one recurring task (VTODO),
  not appointments or unrelated tasks. Known completed occurrences within an open
  set become source-bound completed instances plus exclusions on the master.
  The existing task list selects the next due date and completes one occurrence
  without completing the future series. Reimport does not undo that local edit.
  Freed occurrences stay excluded. A rule is emitted only if its expansion
  exactly matches the native dates; otherwise the explicit finite set is kept.
  Unlinked occurrences, unknown task states, mixed task/appointment definitions
  and other differing content remain unsupported rather than being guessed away.
- Contacts: names, company, telephone numbers, email addresses and postal
  addresses; additional basic text fields are retained in the contact note.
  Mail-merge names and nonempty native `Extn` slots are retained as explicitly
  labelled source text (#579). Slot positions remain visible; no interpretation
  as a phone label or dialable extension is inferred, and numbers are unchanged.
  Native `State` values remain in the corresponding structured address `region`
  slot (#580), including sparse source slots; no region is guessed from a postal
  code. Existing labelled source-note text is retained as well.
- Notepad pages: title and plain text extracted from RTF, including escaped
  Windows-1252 characters and Unicode escapes. Embedded objects are not executed.
- Stable record identities derive from the legacy object's origin and ID.
- Finite appointment series use their live native repeat-object links and
  independently stored start/end arrays. A verified weekly rule remains editable;
  other matching finite sets retain explicit recurrence dates. Deleted native
  occurrences become exceptions. Active unlinked or conflicting occurrences are
  not guessed into a series or flattened into unrelated appointments.
  Fully converted sets do not increment the shared unresolved-rule warning
  counter: the ordinary calendar engine can already expand them.
- Contact category labels and explicit direct distribution-group memberships are
  retained as contact groups. Group cards do not become fictitious people.
  Verified native Work, Home and Work-fax slots retain their phone contexts;
  empty preceding slots do not change later slot meanings.
- Basic planner date spans become all-day appointments with the original
  inclusive last date. Present native `Row` (field 18) and `KeyID` (field 19)
  values remain separately labelled in the note (#568); absent fields are not
  fabricated as zero. `Row` is not an event-type number. Row layout, event-type
  labels, palette colors and busy-time booking are not inferred from these
  numbers; named types and color migration remain unverified.
- Native anniversaries with the verified annual checkbox become anniversary
  entries. Turning that checkbox off in the original application produces a
  single all-day appointment with the same stable identity, not a yearly rule.
- Basic call and web entries become explicitly labelled plain-text notes, since
  the target book has no legacy call-log or bookmark collection. Call text keeps
  the original date/time span, contact/company/number, status and completed flag.
  Web text keeps the URL and description. Neither conversion dials a number,
  opens a URL, creates a contact or invents a calendar appointment.

Unsupported series overrides, nested/empty distribution groups and
custom planner/anniversary/call repetitions are not converted into basic
appointments or contacts. Confidential entries in the newly supported sections
are skipped rather than dropping a confidentiality marker the destination
collection cannot represent. Distribution-list-specific options are not contact-group permissions.
Unsupported live entries are counted where
identified. Formatting, attachments, non-contact categories and alarms are not transferred.
An allocated notepad entry with a nonempty body in an unrecognized non-RTF format
is omitted as one unsupported entry rather than blocking every other supported
collection (#564). Its title is not imported as a misleading empty replacement,
and the body is not guessed to be plaintext. Known empty-body sentinels retain
their existing title-only behavior. Recognized but malformed RTF still rejects
the import, as do corrupt allocation/schema/field boundaries. The original file
remains untouched; the existing import preview/report must be reviewed for
omission counts before accepting the supported subset.
The native result always includes the translated limitation report; this is
not advertised as a lossless conversion. Password-protected or unfamiliar
storage variants are rejected rather than guessed.

## Storage boundaries

The accepted binary signature is `30 4b 04 b3`. Decode each little-endian
16-bit word by rotating left by one bit. The decoded file contains a complete
allocation chain from offset zero: `(uint32 tag, uint32 self, uint32 size)`.
Each size is at least 12, four-byte aligned and entirely inside the file. The
root allocation is 1024 bytes. Traversal must terminate exactly at EOF.

Schema allocations (`ffffffff`) identify a collection and its linked field
descriptors (`fffffffd`). Descriptor references must resolve to allocation
starts, remain bound to the owning schema and contain neither cycles nor
duplicate field IDs. Application records must reference that same schema and
type. Sparse property entries contain `(uint16 id, uint16 length, uint32 value)`;
up to four bytes are inline, larger fields use record-relative offsets beyond
the property table and remain within the owning allocation.

Free allocations (`fffffffc`) may retain deleted text. They are skipped as
whole allocations, so old records and old versions are not resurrected.
Limits are 32 MiB per file, 250,000 allocations, 512 fields per record/schema,
1 MiB per RTF body and 64 nested RTF groups. Existing archive limits also apply.

## Independent native fixtures and checks

`or6-native-fixtures.json` contains gzip/base64 representations and SHA-256
digests of three synthetic files saved by Lotus Organizer 6.1. It contains no
application executable or installer. The expected values were chosen before
parsing, not generated by either reader. The deleted-contact file was produced
with the application's own delete action; its appointment, task and note remain.

Python and C# tests verify these values, empty alphabet placeholders, retained
free storage, malformed allocations, schema cycles, foreign references,
duplicate properties, field bounds, malformed RTF, ZIP dispatch and source CAS.
`or6_cross_platform.py` compares both readers' actual output using an already
built CoreTests assembly. It does not start a build, emulator or VM.

`or6-native-extensions.json` adds seven independently authored synthetic files
saved by the unmodified supplied Lotus application in an offline Wine 10/Debian
13 reference environment. Expected weekly dates, phone types and group members
were chosen before parsing. The deleted occurrence was removed with Lotus's
own “Just this one” action. No vendor program, runtime or installer is included.
The final two files additionally verify preselected planner/anniversary/call/web
values, exact replacement of the original phone/URL edit controls and the
original annual-checkbox on/off distinction. Earlier private snapshots with an
incorrectly inserted phone number or URL are not the public expected dataset.

`or6-native-tasks.json` retains a separately authored original-program weekly
Task series, with three preselected Tuesday due dates. Both readers and actual
task export/reimport retain one series; both frontends additionally verify
next-due selection, source-bound duplicate reimport, original completion
exceptions and single-occurrence completion without losing future tasks.
