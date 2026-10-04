# Zeiterfassung / time tracking (#82)

Implementation contract in progress. Local Notes storage and controls are being
implemented first; version-7 synchronization and the monthly export described
below are not yet available. Capability negotiation must not advertise them
until their complete transport and export implementations have passed their gates.

Time tracking is an optional own-device feature, separate from ordinary calendar
appointments and from note-import direction. Turning it off preserves entries.
The UI has one primary confirmation slider: start becomes finish in the same
place while a record is running. Only then is a second slider shown, switching
between pause and end-pause/resume. Finishing hides the pause slider and restores
start. A tap or an incomplete drag does not perform an action. Manual entry and corrections are
also available. Display and input omit seconds.

A hamburger menu switches between tracking, time-tracking settings and recorded
entries. History entries open for editing or local removal. Settings provide
direct Android printing using the same original layout as the ODS, with month
selection and all-day/selected-day filtering.

Removing entries or whole months in Notes is local only. It must not generate a
deletion on Organizer. Organizer deletions originate only there. Notes retains
separate removal identities so a subsequent sync does not silently reimport the
removed entries. Removed months remain in encrypted local trash for **30 days**,
with restoration available. Expiration or explicit permanent local removal drops
the contents but keeps the suppression identities. None of these operations may
delete Organizer data or produce an outgoing synchronized tombstone.

Sunday and holiday rows use distinct restrained background colors with dark,
legible text in both ODS and Android print output. Holiday eligibility follows
the **existing Organizer region setting** (country and applicable subdivision),
reused by Notes without an additional region preference. Do not infer it from
language, phone location or time zone. A regional holiday must match that
subdivision when one is selected. If Organizer has no subdivision selected, **all
available holidays of the configured country**, including regional ones, qualify.
If holidays are disabled in Organizer, omit holiday annotations and highlighting
entirely; Sunday highlighting remains. Reuse this existing toggle without adding
another holiday switch in Notes.
Holiday marking is evidence of calendar classification, not an automatic
decision about wage supplements.

## Entry model

Entries use a stable UUIDv4. Start, optional end and optional pause-start are UTC
epoch **minutes**, with an IANA zone retained for their local calendar display.
Completed pause minutes are stored independently. An absent end means open; an
open pause-start means paused. Finishing closes any current pause. Gross and net
minutes are calculated from these fields, not from a periodically saved counter.
A restart therefore does not lose the running interval or create another entry.

The editable type is ordinary text, suitable for work or other activities. A new
entry may propose an early/late/night label from its local start time, but never
locks the choice. Notes are plain text. Correcting duration updates the end
consistently; a pause must be nonnegative and cannot exceed gross duration.

Local starts do not silently create a second open interval. Existing or remotely
received entries keep their IDs and remain individually editable. Synchronization
requires its own setting on both paired own devices and fresh negotiated support
for the version-7 extension of `personal_tasks_sync`. It is not enabled by merely
viewing an entry or by enabling one-way note import. Concurrent differing edits
must remain reviewable rather than silently destroying one version.

## Calendar and ODS

The calendar uses a small briefcase mark and a tooltip with type and start/end.
Recorded intervals remain distinct from repeating planned services. Opening the
mark offers the recorded entries without creating duplicate ordinary appointments.

The monthly editable ODS uses an original Magnolie layout: a restrained title and
month/name area, clear daily rows, a highlighted monthly total and a signature
area. The supplied spreadsheet is only an example of needed information, not a
layout to reproduce. All UI, slider and ODS
labels use the effective system/application language, including localized dates
and weekdays. The German translations are **Zeiterfassung**, **Uhrzeit**
(Beginn/Ende), **Stunden**, **Pause in min**, **Gesamtzeit**; these are not hardcoded
labels for other languages. It includes free dates, multiple entries on a date, month/name and
date/signature areas. Existing example names are never embedded in the program.
Start/end respect the effective regional 12-/24-hour clock setting, including
localized AM/PM when applicable, and omit seconds. This applies to the application
and the ODS. Elapsed durations and sums are independent of the clock convention:
they do not wrap at 12 or 24 hours and contain no seconds. Pause input is an
explicit number of minutes.

A normal monthly sheet must fit one printed A4 page. Additional records flow to
further A4 pages at readable text size, with repeated column headings and final
totals/signature after the last record. Never truncate extra records or scale an
arbitrarily long month to one page. Verify actual rendered PDF pagination, not
only XML print settings, for both normal and overflowing months.
Set paper size, orientation and margins in the document and initial Android
print attributes so supported print services use the intended format by default.
Existing annual and monthly planners remain A4 landscape; their settings are
independent of the time-tracking template.

Gross, pause subtraction and monthly sums are real OpenFormula formulas, with
cached results matching the app. Midnight and multiple-day intervals must be
handled explicitly. Invalid pauses must produce a visible error rather than an
unnoticed negative total. The template's automatic 30/45-minute break rule is
not treated as an instruction to invent breaks the user did not record.
