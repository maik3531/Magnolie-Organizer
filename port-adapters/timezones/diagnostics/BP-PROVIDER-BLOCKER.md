# Blocking provider finding (Refs #121, #447)

The pinned ThreeTenBP 1.7.5 database is **not approved as the common normative
point provider**. These are public synthetic host/JVM reproductions, not an
Android-device or Mac-runtime claim. No upstream issue was opened.

Exact trusted inputs are in [bp-provenance.json](bp-provenance.json): JAR SHA256
`58c5593452f871ebf736dfda3bf8f3bc0de4e92cec61bc19c8ad81f9dfb70d72`,
embedded TZDB SHA256
`e28750a597bca9fe12fc927d6e8dd71cc71e9195a90e2bc7490265ffa10f1b12`,
Global-TZ **2026egtz-rearguard** archive SHA256
`0f391ed721b54225189a1c5cac469fa24a07c1283e9e460650fd28155e19240d`.
The official BP update workflow uses this Global-TZ/rearguard family. Global-TZ
history must not be compared indiscriminately with normal IANA history.

## Direct provider reproduction

Using the unmodified pinned JAR:

```kotlin
val zone = org.threeten.bp.ZoneId.of("Asia/Gaza").rules
zone.getOffset(org.threeten.bp.Instant.parse("2074-03-24T00:00:00Z")) // +02:00
zone.getOffset(org.threeten.bp.Instant.parse("2074-07-15T12:00:00Z")) // +02:00
zone.transitionRules // March rule reports +03:00 -> +03:00
```

Independent `zic -b fat` compiled directly from the exact verified Global-TZ
archive, read with CPython `zoneinfo.ZoneInfo.from_file`, returns **+03:00** at
both timestamps. The installed independent JDK agrees. The BP history omits the
required March 2074 transition; this is not a JS alias, parsing or formatting bug.

The complete offline comparator checked **592 zones / 269,477 cases**, including
40,521 independent TZif transition timestamps and 24,000 future transitions across
400 Gregorian years / 93 distinct POSIX models. It completed and then **failed**:
930 JS-prototype disagreements, Asia/Gaza:865 and Asia/Hebron:65. Models were deduplicated by the
complete independent POSIX footer; other zone identities still receive historical
and year1/99/400/2400/9999 point/wall tests. Full counted synthetic samples are in
[bp-independent-report.json](bp-independent-report.json).

A separate complete run uses [BPReferenceWorker.kt](BPReferenceWorker.kt) and
calls the actual pinned provider directly, with no JS payload interpretation.
For the same269,477 independent cases it **fails with1,340 disagreements**:
Asia/Gaza:1,270 and Asia/Hebron:70. Its counted results are separately retained in
[bp-direct-independent-report.json](bp-direct-independent-report.json).
The930 and1,340 counts describe different engines and must not be conflated.

The first shared-JS prototype separately had a historical-gap selection bug:
it considered last rules before the last historical transition. Restricting those
candidates to their future applicability fixed that implementation defect. The
930 JS failures above are after that correction; the separate1,340 direct-provider failures independently confirm the provider defect.

## Actual production codec consequences

[ProbeThreeTenGaza.kt](ProbeThreeTenGaza.kt) calls the actual Kotlin production
importer/exporter. Its new-record input is the actual saved shared-UI fixture,
with only public synthetic date/time/zone values changed.

- Import `DTSTART;TZID=Asia/Gaza:20740715T123000` into UTC: **accepted as 10:30**,
  independently required 09:30.
- Export a new 12:30–13:30 Gaza appointment: **accepted**, 5711 UTF8bytes.
- Import the actual exported bytes into UTC: **accepted as 10:30** again.
- Therefore this is a wrong one-hour result, **not** a safe unsupported/rejection.

The recorded result and exact production-source hashes are in
[bp-production-codec-report.json](bp-production-codec-report.json).
Compile the probe in package `io.gitlab.maik3531.magnolietabletbeta` together with
`ICalendarImport.kt`, `ICalendarExport.kt` and `TimeZoneExport.kt`, using pinned
Kotlin 2.0.21 target17, the pinned ThreeTen JAR, and the existing JSON20240303 JAR.
Pass `app/src/test/resources/calendar-export-system-zone-ui.json` and an output
directory to its main method. No fixture is written into the app or a user vault.

The blocked BP extraction generator requires an explicit diagnostic output path
outside this source directory. No erroneous BP payload is retained as a product
asset. The full test can be reproduced with its explicit diagnostic payload:

```sh
python3 port-adapters/timezones/diagnostics/extract-bp.py --compiler-cache CACHE --threeten-jar BP_JAR --output /tmp/BP-DIAGNOSTIC.json
python3 port-adapters/timezones/check-independent.py GLOBAL_TZ_ARCHIVE --payload /tmp/BP-DIAGNOSTIC.json
```

The second command must fail until its input is an independently correct model.
Do not mask this with a Gaza-specific correction, edited JAR checksum, finite
future table, or an assertion exemption. A directly generated normative
TZif/POSIX model is the proposed next source, shared by UI and native codecs.
