# Custom Appointment and Task Time

Follow-up inspection, focused-wheel behavior and current SMS/time integration
results: [SMS-TIME-USABILITY.md](SMS-TIME-USABILITY.md). The results below document
the earlier time-control work and its baseline reproduction.

Scope: the canonical Linux and Windows web frontends only. No installed files,
projected trees, release artifacts, phone services, SMS or Calls UI are changed.

## Root Cause

The installed custom dialog created `eingabe("time", "")` for new entries and
did not call the calendar's `bindeZeitRad`. In WebKitGTK 2.52.6, the native time
editor displays numeric segment placeholders. Entering only the hour can visibly
produce `10:30` while the DOM value remains empty and `validity.badInput` is true.
The displayed `30` is not a minute value. Blurring cannot recover a value that
was never entered. `reportValidity()` then displays WebKit's English
`Invalid value`, irrespective of the app's German translation.

The native reproduction uses the installed `/usr/share/magnolie-organizer/web`
assets with synthetic data, not a simplified time-input example. Trusted X11
wheel events leave the old custom field unchanged because it has no binding.

## Shared Behavior

- `eingabe("time", ...)` retains the same native hour/minute keyboard editor as
  the normal calendar. No replacement widget or fabricated blur-commit handler.
- New custom appointments and tasks receive the actual value from
  `vorgabeZeiten().zeit`, the calendar's next-quarter-hour suggestion and bounds.
  The test clock is fixed at 09:22 UTC, giving a real 09:30 value. Production
  uses the current organizer time zone and clock.
- Existing empty times remain empty. The optional fifth `leerErlaubt` argument
  to `bindeZeitRad` prevents a wheel gesture from supplying missing segments.
  Its default is false, preserving the existing four-argument contracts.
- Calendar wheel behavior is reused: five minutes, Shift for one hour, configured
  direction, and clamping at 00:00/23:55 without changing the date. WebKitGTK
  converts Shift+wheel into `deltaX`; the shared handler now reads that axis.
- Native keyboard segment stepping still wraps, e.g. 23:00 hour-up becomes
  00:00, or 00:59 minute-up becomes 00:00, without changing the date.
- The existing `bindeDatumseingabe` remains in use through `eingabe("date", ...)`.
  The separate `bindeGesundheitsZeit` text widget is deliberately not reused:
  it has different stepping rules and fills incomplete values from the current
  health time. It does not implement the calendar's contract.
- Apply reads the current native value and validity without forcing blur.
  A complete 09:30 edited to hour 10 saves 10:30. Empty values save empty;
  incomplete values do not mutate the draft's stored item.
- Invalid-time feedback is an inline, translated `role="alert"` associated with
  the field using `aria-describedby` and `aria-invalid`. The global toast is
  behind this modal, so changing its stacking or other consumers is unnecessary.
  Correcting the field clears the visible error. No custom-dialog call to
  `reportValidity()` remains.

## Translation Keys

New manually translated key:

`Enter both hours and minutes, or leave the time completely empty.`

German:

`Bitte Stunden und Minuten eingeben oder die Uhrzeit ganz leer lassen.`

Existing reused wheel hint:

`Use the mouse wheel to change the time in 5-minute steps (hold Shift for whole hours)`

Both PO/POT sets and their generated web catalogs include the new key. Coverage
is English source plus ar, be, cs, da, de, es, fr, hi, hsb, it, ja, nb, nl, pl,
pt, ru, tr, uk, zh_CN: all 20 app languages. Catalogs are compiled with the
existing `po_zu_js.py`; no release build is involved.

## Tests

`magnolie-organizer-windows/tests/custom-time-regressions.js` exercises both
frontends: defaults, stored empty values, both wheel directions, Shift stepping,
native horizontal Shift axis, bounds, disabled fields, focused Apply, save
serialization, all translated errors/hints, and legacy linked start/end controls,
including the multi-day exception. It is registered in `tests/run.js`.

`custom_time_webkit.py` runs 19 cases for each combination of appointments/tasks
and new/existing items, plus five normal-calendar controls: 81 native scenarios
per asset set. The installed baseline is recorded with `--before`; corrected
source runs assert the results, translated visible feedback, no browser
validation calls, trusted wheel delivery, unchanged dates, and captured save
payloads. Native cases cover:

| Group | Cases |
| --- | --- |
| Initialization | Default; edit only the hour directly from the default |
| Segments | Hour digits; minute digits; native hour/minute midnight wrap |
| Wheel | Five minutes; Shift hour; reversed direction; lower/upper bounds |
| Empty/partial | Hour only; empty; wheel on each; delete minute; delete both |
| Apply | Mouse; Enter on Apply; native editing then Apply without blur |
| Calendar | Wheel; Shift wheel; reverse wheel; hour digits; midnight |

The GTK probe injects only test exports, an inert save-capturing bridge, event
logging, and a deterministic clock. Field handlers and CSS come from the tested
assets. Screenshots are captured from the actual GTK window, using software
rendering. X11 keyboard and mouse-wheel input comes from `xdotool`, not synthetic
JavaScript keyboard or wheel events. The focused-Apply case deliberately invokes
the button while the natively edited field still has focus.

Run from the canonical root, after creating an isolated evidence directory:

```sh
taskset -c 0,1 bun magnolie-organizer-windows/tests/custom-time-regressions.js
sh magnolie-organizer/pruefungen/custom_time_isolated.sh --web /usr/share/magnolie-organizer/web --output /tmp/evidence/installed-before --before
sh magnolie-organizer/pruefungen/custom_time_isolated.sh --web magnolie-organizer/web --output /tmp/evidence/linux-after
sh magnolie-organizer/pruefungen/custom_time_isolated.sh --web magnolie-organizer-windows/app/web --output /tmp/evidence/windows-after
```

`custom_time_isolated.sh` requires `bwrap`, Xvfb, `xdotool`, system Python GI,
GTK3 and WebKit2 4.1. It caps the entire process tree to CPUs 0 and 1, mounts an
empty device tree, hides the host home and runtime directory, unshares the
network, and starts its own X11 display and session bus. Only the canonical
project is exposed from the host home, read-only. WebKit uses an ephemeral
context. No VM or application backend is started. Evidence is mapped from
`/tmp/opencode/custom-time-native` (override with `MAGNOLIE_TIME_EVIDENCE`).

The existing Chromium `time-edit-browser.js` no longer simulates a deferred
blur commit. Native WebView2 on Windows is not covered by the Linux GTK probe.

## Recorded Results

- WebKitGTK 2.52.6: 81 installed baseline scenarios recorded; 81 Linux source
  and 81 Windows frontend source scenarios passed. All corrected custom Apply
  paths recorded zero browser validation calls.
- Targeted unit matrix: 158 cases passed across both frontends, including error
  correction and feedback in all 20 languages.
- `structured-appointment-parity.js`: passed.
- All 38 PO catalogs passed the existing syntax, format, completeness and
  fuzzy-entry checks against their respective POT files.
- The broad Linux `pruefungen/test.js` stops at its SMS context-menu assertion
  (expected `.sms-planung-dialog`). The Windows `tests/web-smoke.js`, with
  `MAGNOLIE_PYTHON=/usr/bin/python3`, stops at unrelated POT/source key-set
  differences, including old Custom-sync and device capacity labels. These
  failures were not changed as part of the time-control fix.
- The optional Chromium test was updated but not executed in this run.

Native PNGs and JSON event/value/save-state records are in
`/tmp/opencode/custom-time-native/{installed-before,linux-after,windows-after}`.
The `appointments-new-default-hour-*` screenshots reproduce the exact new-entry
steps without assigning a time value in the test. The installed version shows
`10:30` but reports an empty value and `badInput`; the corrected sources show
and save a genuine `10:30`. `appointments-new-partial-after-apply.png` shows
the translated inline error after deliberately clearing the original time.
