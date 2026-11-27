# Optional period forecast and cycle-calendar reminders

Refs #803; extends the reminders introduced for #79. This is a local planning
estimate from recorded day markers. It is not a diagnosis, a fertility model,
a contraception method, or a clinically validated probability forecast.

## Inputs and reference day

Only markers whose explicit `art` is `bleeding-light`, `bleeding-medium` or
`bleeding-heavy` count. Their IDs link to `tagmarken[].zyklusIds`. Display names,
symbols, intensity changes, other marker types and unknown IDs do not imply a
new period. Multiple markers on the same date count once. Invalid containers,
markers and dates are ignored without changing the original data.

`asOf` is a strict `YYYY-MM-DD` calendar date in years 0001–9999. An invalid
explicit reference day is rejected. Without an explicit day, the Organizer's
current regional day is used with the same bound normative time-zone rules as
the GUI. The system setting resolves the system zone name; it does not replace
the bound rules with the host's time-zone database. Missing, damaged or unknown
bound rules fail explicitly. Date differences use calendar days, not local
elapsed hours, so a daylight-saving change does not add or remove a cycle day.
Future bleeding dates are excluded and counted once per distinct date in
`futureIgnored`. They do not change starts, intervals, hints or reminders.

Sort and deduplicate the recorded bleeding dates up to `asOf`. Adjacent
recorded dates at most three days apart form one episode; the first recorded
date is its start. This grouping tolerates up to two unrecorded days and is a
planning rule, not evidence that bleeding occurred on those missing days.
`recordedRun` is the longest run of genuinely consecutive recorded days within
the latest episode; it resets at a new episode and does not bridge missing days.

## One estimate from recent contiguous history

1. Calculate the calendar-day gaps between consecutive episode starts.
2. Starting with the newest gap, keep at most twelve consecutive gaps in the
   inclusive range 14–60 days. Stop at the first gap outside that range. Do not
   skip across it to reuse older history. `excludedIntervals` reports the number
   of out-of-range gaps in the history eligible for calculation (after a pause
   boundary when present), not a number of diagnoses.
3. At least two retained gaps, therefore at least three episode starts, are
   required. After a break, two new usable gaps are needed. No default 28-day
   cycle or invented unrecorded episode supplies missing history.
4. Round the median of those gaps to a whole day, with positive halves rounded
   upwards. The single estimated next start is the most recent start plus this
   value. The inclusive start window runs from that start plus
   `max(1, shortest retained gap - 2)` to that start plus
   `longest retained gap + 2`. This is an observed planning range with a margin,
   not a statistical confidence interval or a guarantee.
5. If the last recorded bleeding day reaches or passes the window's first day,
   return `reason: ongoing` and no projected dates. This reports conflicting or
   overlapping records; it does not prove that bleeding continues today.
   An overflow beyond the supported calendar range returns `reason: range`
   without partial dates. Otherwise the reason is `ready`; insufficient history
   is `insufficient`, or `gap` if an out-of-range interval exists.
6. A reference day after the window yields `overdueDays = asOf - windowEnd`.
   The estimate stays attached to the last actual recorded start. It is never
   rolled forward to an invented next cycle.
7. History is stale only when days since the last start are greater than
   `max(120, 2 * (longest retained gap + 2))`; without retained gaps the second
   term is 120. Depending on retained history this boundary is 120–124 days.
   Stale estimates do not paint calendar cells or generate forecast reminders.
   The explanation may still show the earlier estimate explicitly as such.

The 14–60-day range, episode grouping, two-interval minimum, twelve-interval
history, margin and stale boundary are transparent software planning choices.
They are not clinical definitions of a normal cycle. A real interval outside
the range is retained in the diary and must not be called a recording mistake.

## Optional display, hints and existing reminders

Under `einstellungen.kalender.zyklusErinnerungen`, `anzeige`, `prognose` and
`abweichung` are independent strict booleans, all false when missing. Existing
saved opt-ins remain effective; adding the display option does not enable a
notification. Disabling `zykluskalenderAn` suppresses the display and both
reminder types without deleting recorded dates or the saved choices.

- `anzeige` shows the estimate, start window, explanation and calendar overlays.
  A pale drop with `≈` marks each possible start day in the window, not a
  predicted bleeding duration. All active prediction drops disappear once
  `asOf > windowEnd`, including on earlier calendar pages. These projections
  create no real appointments, day marks or provider calendar events. Missing
  data, stale history, overlapping records and calendar limits have explicit
  explanations.
- `prognose` preserves the existing forecast reminder. Lead time is 0–30 days,
  initially one. The native reminder service schedules at 08:00 in the
  Organizer's regional time zone. A display-only opt-in generates no reminder.
- `abweichung` preserves the existing unusual-gap reminder and, when the display
  is enabled, also shows advisory text about a passed window, a changed latest
  interval, a wide observed range, or more than seven consecutive recorded
  bleeding days in the latest episode. The last hint explicitly asks the person
  to seek medical advice if the bleeding actually lasts that long.

After the active forecast expires, the separately enabled advisory display can
show a pale dashed drop at the original estimated start. Its tooltip explains
that the estimated window passed without a new recorded start. This advisory
symbol is distinct from an active prediction or actual recorded bleeding; it
does not establish that a period was medically missed. Changed-interval or
out-of-range-history hints belong to the latest actual start. Longer recorded
bleeding and overlap hints belong to the last recorded bleeding day. Within an
active window, the drop at the estimated midpoint can also be dashed when the
observed interval range reaches the configured variation threshold. Tooltips
state the specific recorded reason. No advisory drop ever enters the
calculation or silently confirms a date.

An active prediction drop for today or an earlier day can open an explicit
confirmation dialog. The person selects an actually available typed bleeding
definition (`bleeding-light`, `bleeding-medium` or `bleeding-heavy`) and confirms
only that observed day. Future days cannot be confirmed. Confirming writes that
single real day marker through the ordinary save path and recalculates the
estimate; it does not record the full window, imply a duration, or create an
appointment. Cancelling leaves data unchanged. Re-rendering or expiration alone
never converts a projection to a recorded event.

For the changed-interval comparison, compute the same contiguous suffix and
rounded median from the intervals *before* the latest one, requiring at least
two earlier gaps. Compare the latest actual gap, even if outside 14–60 days,
with that baseline. A difference greater than or equal to `abweichungTage`
triggers the hint/reminder. The inclusive threshold is 1–30 days, initially
seven. The displayed range-variation hint uses that same threshold. These
comparisons describe the entries, not the cause of a change.

Stable reminder IDs include the last start and forecast date or actual gap.
Re-reading unchanged data does not create another reminder; corrections replace
the projection. Existing reminder journaling, missed-reminder behavior and
permission boundaries remain in charge. The overdue, variable-range and
long-bleeding display hints are not additional operating-system notifications.
Every redraw re-evaluates the current data/reference day, with a cache confined
to that redraw; no forecast is persisted as a medical fact.

## Explicit pause for known circumstances

A click on a dashed advisory drop opens the pause controls. The person can
select pregnancy, breastfeeding, medication/hormonal treatment,
perimenopause/menopause or
another reason. These are voluntary diary choices, never diagnoses inferred
from missing periods. The stored object is
`einstellungen.kalender.zyklusErinnerungen.pause`:

| Field | Meaning |
| --- | --- |
| `reason` | One of `pregnancy`, `breastfeeding`, `medication`, `menopause`, `other`. |
| `startedOn` | Explicit recording date, a valid ISO calendar day. |
| `until` | Optional inclusive final day, not before `startedOn`; null or absent means no fixed end. |
| `resumedOn` | Optional explicit resumption day, at or after `startedOn` and no later than the reference day. |

Pregnancy initially proposes nine **calendar months from recording the pause**,
clamping a nonexistent day to the final valid day of the destination month.
For example, 2026-05-31 plus nine months is 2027-02-28. This is an adjustable
planning pause, not a calculated birth/due date or an estimate of gestational
age. Other reasons initially have no fixed end. Every reason permits a custom
end date or an indefinite pause. No fixed end means no time-based resumption.

While the pause is active, no period forecasts, missing-start hints, dashed
advisory drops or cycle reminder projections are produced. A neutral pause
status with the selected reason and final day, or no fixed end, remains visible
in the enabled cycle display. Actual diary entries remain intact and can still
be recorded. The three saved display/reminder choices remain unchanged.

The pause is active through and including `until`, unless explicitly resumed
earlier. A manually **newly added observed bleeding marker** dated from
`startedOn` through today is saved, but does not itself end the pause. A separate
explicit **Confirm as a new period** action records the resumption and ends the
planning pause early. **Keep pause** or cancelling that resumption question
retains both the recorded bleeding and the pause. The software never identifies
every bleeding episode as a period. A future entry, renaming a marker, changing
an existing marker's intensity, re-reading data or an existing pre-pause entry
must not silently end the pause. The separate manual end action records today's
`resumedOn` without inventing a bleeding day. Cancelling the pause-settings
dialog itself changes neither data nor forecasts.

The pause object is retained after resumption so its history boundary remains
effective. Calculation uses only recorded days at or after `resumedOn`, or
strictly after `until` following a scheduled end. It does not reuse intervals
from before or across the pause. At least three new episode starts, with two
usable intervals, are required for a fresh estimate. With no new entries after
the pause there is no recycled overdue warning from the old history. Valid
pause context with too few new starts reports `reason: restart`; an active
pause reports `reason: paused`.

Only confirm bleeding as a new period when the person actually classifies it
that way. Ending a pregnancy/menopause-related planning pause does **not**
declare a pregnancy or menopause ended. Bleeding during pregnancy can have
other causes and should receive prompt medical advice. Bleeding after menopause
should also be assessed medically, even if slight or occurring only once.
These cautions concern reported bleeding, not an alarm inferred from absent
entries. The application does not advise changing medication or treatment.

## Reference comparison and health wording

MorphHealth's public repository contains separate model-generated benchmark
implementations, not one established clinical algorithm. Reviewed at commit
`a91ffffbe160a4542f8e2f79401406052ec5845f`:

- [Repository description](https://github.com/TheMorpheus407/morphhealth-benchmark/blob/a91ffffbe160a4542f8e2f79401406052ec5845f/README.md)
  and [P04 specification](https://github.com/TheMorpheus407/morphhealth-benchmark/blob/a91ffffbe160a4542f8e2f79401406052ec5845f/SPEC.md)
  describe personal planning and a diary mode, excluding diagnosis and contraception.
- [Astra cycle implementation](https://github.com/TheMorpheus407/morphhealth-benchmark/blob/a91ffffbe160a4542f8e2f79401406052ec5845f/GPT-6-Astra/app/lib/core/cycle.dart)
  provides useful concepts: three starts, a median, a visible date window,
  exclusion of future entries and no fictional rollover. Magnolie implements
  these concepts in its own marker model. Unlike that reference, display is
  opt-in, an out-of-range interval breaks the recent history, no MAD outlier
  filter narrows the observed range, and stale dates are excluded from overlays
  and forecast reminders. No third-party runtime code or service is required.
- [MorphHealth license](https://github.com/TheMorpheus407/morphhealth-benchmark/blob/a91ffffbe160a4542f8e2f79401406052ec5845f/LICENSE)
  is MIT, copyright 2026 Cedric Mössner. The reference comparison does not claim
  a clinical validation or endorsement of Magnolie.

Health wording was checked against NHS patient information on 2026-11-26:

- [Irregular periods](https://www.nhs.uk/symptoms/irregular-periods/): changes in
  the usual pattern and periods lasting more than seven days warrant medical
  advice. This supports the conditional longer-bleeding wording; the software
  can establish only what was recorded.
- [Missed or late periods](https://www.nhs.uk/symptoms/missed-or-late-periods/):
  late or absent periods have multiple possible causes. A missing entry cannot
  distinguish those causes from incomplete documentation.
- [Vaginal bleeding in pregnancy](https://www.nhs.uk/pregnancy/common-symptoms/vaginal-bleeding/):
  bleeding has several possible causes and needs professional advice; some
  situations require urgent treatment. A diary entry cannot determine the
  cause or whether a pregnancy has ended.
- [Postmenopausal bleeding](https://www.nhs.uk/symptoms/post-menopausal-bleeding/):
  bleeding after menopause needs medical assessment, including a single slight
  episode. The pause reason is not a diagnosis of menopause.

The optional pause reason records only the person's planning choice. Pregnancy,
breastfeeding, medication effects, menopause and other clinical states are not
diagnosed or inferred by this estimator. Absence of a hint is not reassurance
about health. The UI advises medical consultation for
new, persistent or distressing changes and makes no ovulation, fertility,
pregnancy or contraceptive claim. Source tests and synthetic scenarios verify
software behavior only; they are not medical validation or native package
acceptance on Windows, Linux, macOS or Android.
