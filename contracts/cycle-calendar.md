# Optional cycle-calendar reminders

Only explicit `bleeding-light`, `bleeding-medium` and `bleeding-heavy` markers
are used. Edited display names and other marker types do not imply bleeding.
Dates are deduplicated. Consecutive recorded bleeding days whose gap is at most
three days form one episode; its first recorded date is the start.

A forecast requires at least two valid start-to-start intervals (at least three
recorded starts). Intervals outside 14–60 days are excluded from the forecast.
The median of the last twelve valid intervals is rounded to the nearest whole
day, with positive halves rounded upwards. The estimated next start is the most
recent recorded start plus that median. Dates outside the supported calendar
range are not generated.

The unusual-interval option compares the latest recorded start-to-start gap with
the median of up to twelve earlier valid intervals, requiring at least two such
earlier intervals. A hint is generated when the absolute difference reaches the
configured threshold, initially seven days. The latest gap itself is not included
in its comparison baseline and can exceed the forecast's 14–60-day range.

Forecast and unusual-gap hints are independently disabled by default. Forecast
lead time is 0–30 days, initially one; deviation threshold is 1–30 days, initially
seven. Disabling the cycle calendar suppresses both. The existing reminder
service schedules the generated entries at 08:00 in the Organizer's regional
time zone. They are ephemeral reminder projections, not ordinary appointments
and not new events uploaded to a calendar provider.

Stable reminder identities include the last start and forecast date or actual
gap. Re-reading unchanged data does not create another reminder; corrections
replace the projected result. Existing reminder journaling and missed-reminder
settings continue to apply. The forecast is an estimate from recorded data;
the algorithm does not infer unrecorded episodes.
