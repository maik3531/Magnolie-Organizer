# Lotus Organizer 6 native import

Issues: #212 (basic import), #222 (remaining legacy features).
Both Organizer editions use the existing `lotus` import route for
CSV and binary `.or6` files, including eligible entries in bounded ZIP archives.
The preview and staged-review MCP tools keep their existing schemas, source
revisions, book revision checks, cancellation and GUI-draft boundaries.

## Supported subset

- Basic appointments: description, local date/time, explicit end, confidentiality
  and tentative flag. Native categories of ordinary appointments and verified
  uniform finite appointment series map to the existing `kategorien` field
  (#613). The existing user's category palette may color them, but the import
  does not guess a native color from a category name. Verified independently
  indexed calendar occurrences (#614) retain moved start/end clocks and changed
  title/category as source-bound exceptions, not unrelated appointments. Their
  `RECURRENCE-ID` is the original array slot, never the moved start. Native child
  identity remains the imported UID and `X-MAGNOLIE-OR6-OBJECT-UID` provenance
  through calendar export/reimport. The original master excludes each overridden
  slot; missing-slot and active-orphan guards remain in force.
  This calendar-only path requires unique in-range indices; absent index0 is
  accepted only with the native computed uint32 declaration (kind `0x2003`),
  and present indices must be exactly four bytes. Task index recovery is not
  applied. Unknown differing fields, including meeting metadata and `$Busy`,
  remain guarded, as does unverified empty-category clearing. Pencil-in/Busy
  availability semantics remain separate under #615. No timezone is inferred.
- Tasks: description, native local start/due dates and clocks, priority and
  completed state. Ordinary single tasks use the same existing structured
  `startDatum`/`startZeit`/`faellig`/`faelligZeit` fields as task series (#612),
  including the existing task editor and VTODO roundtrip. Missing native stamps
  remain empty, not filled from a due date, current date or guessed work hours;
  no source timezone is inferred. Original identity/status/priority are unchanged.
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
   Individually assigned categories also become source-bound `RECURRENCE-ID`
   exceptions, including open occurrences; completion never spreads the category
   or status to other dates. A later scoped rule edit may restart indices while
   retaining earlier linked records. Those historical dates preceding the current
   array segment are preserved, not deduplicated by relative index. Earlier
   dates must lie within the native anchor and pass the same content/duration/
   state guards. Current index/start/due matches are required except for the
   independently verified complete-set edit forms (#610): the original “All”
   action can copy index0 to every linked task; moving occurrences can leave old
   template dates unchanged. Recovery requires a complete, uniquely dated live
   linked set, with all indices zero or a full unique in-range slot set. Unknown
   indices, incomplete sets, conflicting dates/content/duration/state and known
   active unlinked tasks remain guarded. It never binds unrelated tasks by title.
   Only observed live start/due values are projected in memory. A rule must match
   the entire actual expansion, otherwise the exact finite `RDATE` set is used:
   old template dates do not become phantom tasks. Changed template arrays remain
   as non-scheduling `X-MAGNOLIE-OR6-TASK-TEMPLATE-STARTS` / `...-DUES` provenance
   (`yyyyMMddTHHmmss`, comma-separated) across VTODO export/import and restore.
   No historical dates or lost original recurrence identities are guessed.
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
  fabricated as observed zero fields. `Row` is not an event-type number.
  A uniquely bound planner configuration now supplies the original key name as
  `kategorien` and the independently verified key color as `akzentFarbe`. The
  existing calendar, annual planner, print and spreadsheet views use these
  fields directly; there is no separate planner UI or guessed global category
  palette. The native configuration's explicit Section ID owns the labels.
  A unique allocated planner root and matching native schema name/namespace
  identify the event scope, including multiple planners sharing one options
  schema. Native OID arithmetic and globally unique options are not assumed.
  All15 original-program key slots and their actual event fills were verified
  after save/reopen; native bright green is `#00c200`, not guessed `#00ff00`.
  The explicitly selected first slot omits KeyID19 in the original file; its
  semantic zero default applies only to the declared native uint16 KeyID and
  does not invent a present field in source notes. Missing/ambiguous configuration
  or an unknown key does not acquire a guessed name/color. A prior export that
  already discarded renamed keys cannot recreate them. Row layout and busy-time
   booking remain separate unsupported semantics, not inferred from a key.
   Legacy planner clocks (#609) also retain the independently verified inclusive
   date presentation: midnight Dec3 to midnight Dec4 occupies both dates;
   same-date 08:00–18:00 and zero-duration midnight each occupy one date. These
   additional forms are limited to nonreversed timestamps with reserved byte
   zero, either both midnight or same-date whole hours. Original local clocks
   remain in `icsRoundtrip` as `X-MAGNOLIE-OR6-PLANNER-LOCAL-START` and
   `X-MAGNOLIE-OR6-PLANNER-LOCAL-END` (`yyyyMMddTHHmmss`). They are provenance,
   not event times, timezone guesses or recurrence rules. Calendar export/import
   and profile restoration preserve them. Other clock forms remain unsupported;
   anniversary, repetition and confidentiality guards are unchanged. Original
   UI date presentation and retained raw clocks were independently inspected;
   successful normalization by the original boundary editor is **not** claimed.
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
identified. Formatting, attachments and alarms are not transferred; unverified
category/override combinations remain unsupported rather than guessed.
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

`or6-native-planner.json` retains a synthetic two-planner original-program file:
each section has15 independently renamed keys, and all15 slots were explicitly
selected for dated events before saving and reopening. The fixture includes
two different key names for the same numeric slot in different sections, a
shared options schema, and the original first-slot omission. Independent
expected names/dates/colors are retained beside the source hash. Both native
readers test scope ambiguity/missing metadata and calendar export roundtrips;
both full frontends additionally verify real calendar rendering, annual-planner
models, print/ODS output, duplicate reimport and preservation of a local color
edit. These are source/controlled UI checks, not installed-package approval.

`or6-native-planner-boundaries.json` adds three synthetic timestamp variants
whose inclusive date ranges were inspected in the unmodified original UI.
Both readers test exact clock provenance, calendar export/reimport, seven
negative clock/flag guards and anniversary exclusion. Both full frontends check
each affected date and its neighboring dates, including overlapping entries
matched by title, annual/ODS models, print, reimport and profile restoration.

`or6-native-task-scopes.json` retains genuine synthetic original-program
single-category and later-segment-extension snapshots. The latter has four
linked occurrences with indices `0/1/0/1` but only two current-array dates.
Expected completion/category/date values were selected before the original UI
actions. Both readers verify exact VTODO roundtrips and conflicting-history
guards; both full frontends verify effective dates/categories/states, profile
restoration, the original category in the editor, actual single-occurrence
completion and reimport preserving the local edit. Additional native binding
 forms are covered separately by the following complete-set edit fixtures.

`or6-native-task-bindings.json` retains three genuine synthetic original-program
snapshots: a single moved/category occurrence, all indices copied to zero with
exact original dates, and a whole-set date shift after reopening while template
arrays remain unchanged. Original UI and source values were independently
checked. The original bulk “All” operation also copies the selected status and
category; its resulting open/blank values are not attributed to the importer.
Both readers test exact effective dates/states/categories, template provenance,
VTODO roundtrip and seven ambiguity/incompleteness guards. Both full frontends
check expansion, profile restoration, actual single-occurrence completion and
reimport without undoing the local edit. These verified finite forms do not
establish compatibility with every possible native task edit or infinite rule.

`or6-native-section-removal.json` retains the genuine synthetic ordinary
notebook-section removal before, after confirmed Remove/Yes/Apply/save, and after
reopening (#570). Both readers verify two active/imported pages before and zero
after, identical other collections/counters, and unchanged caller buffers. Early
automation samples that missed the confirmation are intentionally not included.
This establishes no resurrection for that verified ordinary removal path, not
general visibility or reachability semantics for arbitrary active/detached/hidden
native roots. Those broader container/selection checks remain a separate open
safety topic (#611); private excluded sections are never used to reconstruct it.

`or6-native-appointment-categories.json` adds independently inspected original
single and weekly-Saturday appointment files. The category was assigned while
single, before creating the native three-occurrence weekly set; save/reopen,
category, clocks and all three original Find results were verified. Both readers
test existing calendar export/reimport and absent category. A differing member
category now remains a bound exception under #614, never a whole-set category.
Both full frontends additionally verify selected-day rendering and the
existing local category palette, annual/ODS/print output, profile restoration,
duplicate reimport and preservation of a local category edit. This does not
claim support for other still-held native override/repetition forms (#243).

`or6-native-appointment-overrides.json` retains genuine synthetic original-program
single-move and title/category-edit snapshots after save/reopen, plus a guarded
Pencil-in/Busy intermediate. Original native links, indices and slot arrays were
independently checked against the original UI. Both readers test original versus
actual clocks, native identity, calendar roundtrip and ambiguous/unknown-field
guards. Both full frontends verify old/moved days, changed content, profile
restoration, the actual moved-exception editor and reimport preserving its local
edit. Earlier-fragment, duplicate-index and meeting-metadata forms not explained
by these fixtures remain outside this proven scope (#243).
