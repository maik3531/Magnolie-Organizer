# Zeiterfassung / time tracking (#82)

Local Notes storage, controls and Android printing are implemented, along with
both desktop editors, calendars and ODS renderers. The version-7 extension of
`personal_tasks_sync` carries time data through the existing encrypted phone
connection. Runtime interoperability is exercised with both Python and C# peers;
final native package acceptance remains a separate release gate.

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
Notes additionally stores a local encrypted pause-run snapshot: the fixed windows
selected at start, completed manual intervals, precise manual alarm start,
replaced fixed occurrences, acknowledged notices and early fixed-pause endings.
The local automation snapshot is not sent. An optional shared `pausePlan` carries
only the calculation basis (`fixed`, `manual`, `replaced`, `fixedEnds`,
`baseMinutes`) so another device can project a running record consistently.
WLAN configuration, alarm permissions, precise notification anchors and delivered
notices stay local. Only changes to the calculation basis advance the vector
clock; display ticks do not. Finishing materializes its effective total in the ordinary entry
and removes the automation snapshot. An active fixed pause can therefore be
shown as paused without creating a second manual pause-start. Explicit timing
corrections override the automatic total; text-only edits keep its original
anchors. Local trash/restore preserves the snapshot until removal expires.

## Background tracking and alarms (#89)

While tracking is open, including pauses, show a briefcase status notification.
Optional WLAN autostart uses a visible configured SSID, without association or
credentials. Repeated observations do not create another open interval, and
losing the WLAN does not stop tracking. Honor Android scan/permission limits.

After **every** stop, manual or automatic and irrespective of the start source,
block further WLAN-triggered starts for a configurable interval, default one hour.
Persist the deadline and processed stop identity. A repeated stop event must not
extend the deadline indefinitely. Require a fresh observation after the block;
manual starts remain available. Example: stop at noon, return at 14:00 for a
separate shift. The block is not itself a shift schedule.

Fixed breaks are clock windows, not unconditional deductions. Only their actual
overlap with a recording counts. A manual pause already active when a fixed
window starts replaces that entire fixed occurrence, including its later unused
remainder. Show this replacement once and use the fixed duration as an alarm
target measured from the original manual pause start. Starting another pause
while already paused is forbidden. Separate fixed 30 minutes and later manual
15 minutes produce 45 minutes; replacement must not add the fixed period again.

The optional manual pause alarm offers 5/15/30/45 minutes and warns once one minute
before the target. Persist a precise original start even though display omits
seconds. Late activation never resets it; an already passed warning is handled
immediately, without repeated warnings after restart or reevaluation.
Pause delivery uses the existing Android alarm receiver/worker and its exact-
alarm permission fallback. The claimed warning is saved atomically before
notification; stale deliveries are checked against the current precise target.
Resuming, disabling the alarm or finishing cancels the pending target. Without
Android exact-alarm permission, the UI explains that delivery can be delayed.

The optional end-of-work alarm uses either a clock time or hours since tracking
started, with the user's choice of including or excluding pauses. Automatic stop
is an additional opt-in, default off. Early manual stop cancels the alarm, and
automatic stop applies the same WLAN blocking rule. Service, scan, alarm delivery
and settings integration for these extensions must be verified independently of
the currently implemented calculation helpers.

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

### Transport and persistence

`personal_sync.time_settings` carries independent per-peer consent with a fresh
UUID epoch and increasing revision. `personal_sync.time_request` and
`personal_sync.time_batch` bind both current epochs/revisions and a `manual` or
`auto_wifi` trigger. Each authenticated connection must receive fresh capabilities,
grants and own-device settings, and exchange its current time policies. Cached
policies alone cannot reopen a connection. Note-import direction and note/task
permissions do not substitute for time consent.

Batches contain at most 32 distinct records and 192 KiB of canonical UTF-8 body.
Snapshots are divided without dropping records; an individually oversized record
fails before the snapshot is sent. Notes accepts an Organizer calendar projection
but cannot send one or send deletion markers. Desktop batches wait for the previous
batch's durable acknowledgement, keeping calendar projections ordered across
retries. A manual Bluetooth snapshot supersedes queued Wi-Fi-only time snapshots.

Desktop receivers stage encrypted packets and issue an acceptance only after the
application document has been saved and the live authorization checked again.
Commit tokens are bound to message and peer identity. Notes writes its encrypted
Bestand before accepting a packet. Repeated deliveries remain idempotent, including
the WLAN stop block. Disabling consent purges pending time work. Failed consent
persistence keeps transmission blocked until a successful local retry; incoming
controls cannot clear that failure. Backup restoration and the time-tracking
master switch revoke time consent while preserving local records.

Organizer deletion produces a content-free causal marker: `deleted=true`,
`startMinute=endMinute=0`, `pauseMinute=null`, `pauseMinutes=0`, `zone="UTC"`,
empty type/note and no pause plan. Only Organizer-originated batches may carry
these markers. Restoration advances the clock; a stale Notes version must not
silently restore an Organizer deletion. Conflict selection checks that both the
local record and the reviewed alternatives are still current.

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

A normal monthly sheet must fit one printed A4 portrait page, following the
original user-supplied timesheet: month/name above six visible columns (date,
start, end, gross hours, pause, net working time), with pale-yellow input cells,
orange hour totals, cyan pauses and totals/signature below. Additional records flow to
further A4 pages at readable text size, with repeated column headings and final
totals/signature after the last record. Never truncate extra records or scale an
arbitrarily long month to one page. Verify actual rendered PDF pagination, not
only XML print settings, for both normal and overflowing months.
The desktop print dialog offers all days or individual day checkboxes, and disables
printing/export when the selection is empty. Changing the month resets to that
month's valid days. Preview, printing and ODS use the same selection.
HTML printing measures rows with browser fonts in an isolated shadow tree and
emits explicit page sections, because WebKit does not repeat table headers by
itself. Activity, end-date, zone, notes and clock-adjustment metadata remain in
the records and editable ODS helper columns rather than widening the printed sheet.
The 15.418-cm table follows the supplied template's column geometry; compact
unbroken clock text accommodates regional AM/PM labels. A native print-metric allowance is reserved
vertically; font size is not reduced to squeeze arbitrary overflow onto one page.
Set paper size, orientation and margins in the document and initial Android
print attributes so supported print services use the intended format by default.
Existing annual and monthly planners remain A4 landscape; their settings are
independent of the time-tracking template.

Gross, pause subtraction and monthly sums are real OpenFormula formulas, with
cached results matching the app. Midnight and multiple-day intervals must be
handled explicitly. Invalid pauses must produce a visible error rather than an
unnoticed negative total. The template's automatic 30/45-minute break rule is
not treated as an instruction to invent breaks the user did not record.
