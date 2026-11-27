# Independent C# review of #835

Read-only source review and actual native-source CoreTests DLL probe. The DLL was copied from the parent-confirmed completed build before the parent continued test-only changes. SHA-256 bindings are in `source-hashes.json`.

## Passed

Actual `ExchangeCodec.ParseIcs` imports four synthetic inputs (VEVENT, dated VTODO, undated VTODO, recurring master), followed by actual Windows application JS normalization in JSDOM. Both `SelectRuntimeData` and `SelectBackgroundData` then feed the actual C# scheduler. `results.log` records 176 successful assertions.

The two absolute DISPLAY alarms differ only by trigger second (10:30:15Z and 10:30:30Z); an AUDIO sibling is deliberately excluded. Assertions cover no early delivery, distinct second-level keys, the five-minute window with catch-up disabled, 72-hour expiry, cancellation in structured status and raw ICS, disabled event alarms, completed tasks, three separately constructed scheduler instances per mode over one actual state file (notice counts 1, 1, 0), two persisted report keys, and exclusion of synthetic private DESCRIPTION text from projections and notices. Recurrence master yields one notice per absolute trigger, without multiplying by recurrence count.

The actual UI contract differs by kind: appointments materialize `bearbeitbar:false` alarm objects with `triggerRaw`, whereas tasks retain their alarms in `icsRoundtrip` without an `alarme` array. Both paths passed the uppercase standard input.

## Confirmed projection gap, corrected and independently verified

`ReminderRaw` keeps BEGIN/END only when `property.Value == "VALARM"`, unlike the new case-insensitive absolute alarm parser. Actual import of `BEGIN:valarm` / `END:valarm` gives one due DISPLAY alarm before projection and zero after either projection, for both VEVENT and VTODO. Appointment UI normalization may mask the omission by constructing alarm objects; the actual task UI representation stays on the affected raw path.

`mixed-case.log` records the exact imported data and resulting projections. Mode `mixed-case` in `Probe.cs.txt` reproduces it with actual ExchangeCodec and scheduler methods. Proposed minimal correction: use OrdinalIgnoreCase for VALARM values in ReminderRaw. No product file was edited by this reviewer. Parent was notified before further work. Parent correction independently verified against a fresh copied CoreTests.dll: all six unchanged checks now return exactly one due alarm (VEVENT/VTODO × original/runtime/background). `mixed-case-fixed.log` preserves the full outputs; `mixed-fixed-hashes.json` binds the tested DLL. No product edit and no parent build were performed by this reviewer. The initial 176 assertions were not repeated because only this confirmed projection boundary required rechecking.

## Limits

This is a .NET host run on Linux, not native Windows notification/UI acceptance. The actual C# scheduler, projections, importer, atomic state writer and reloads execute; the notice callback records output instead of launching a Windows notification. JSDOM executes the actual current Windows UI source, with synthetic bridge and pre-existing generated normative timezone bootstrap reused from review-integrated. The normalizer and probe have no external service or GitHub side effects. No new dependencies, source worktree changes, or tests in the parent's project were made.

The independent project's source has `.cs.txt` suffix so the parent scratch probe's default C# glob cannot include it. Compiler output is placed outside the reminders subtree. A harmless MSBuild BaseIntermediateOutputPath timing warning remains in this scratch-only harness; compilation succeeds. The parent core build was not invoked by this probe.

## Independent check of coincident absolute and normal task reminders

A second parent-confirmed fresh CoreTests.dll snapshot (SHA-256 `67c40b025b487f123cf9bd3a84090d939750287edf8daa91136dc52a7cbb7cb4`) was used only for the narrow deduplication check. `dedup-fixed.log`, `dedup-fixed-hashes.json` and the `dedup` mode in `Probe.cs.txt` preserve the evidence.

Actual imported VTODO has a normal enabled due reminder and an absolute DISPLAY alarm at exactly the same UTC instant. All three modes (original, runtime projection, background projection) pass the same six checks:

- Exactly one canonical absolute candidate; one initial notice and zero notices after reopening the actual state file.
- Moving the absolute trigger one second later retains two distinct candidates.
- A second independent task at the same instant retains its own candidate (two total).
- Removing the absolute alarm after successful delivery does not replay the normal due reminder.
- A state file actually written by the normal-due-only scheduler suppresses the corresponding absolute candidate after restart.

The six direct assertions per mode (18 total) and all actual scheduler error guards passed; five separate scheduler instances per mode exercised real writes and reloads. The canonical key is absolute while compatible previous normal keys are retained as persisted aliases, as designed by the parent correction. No remaining blocker was observed in this narrow recheck. No product edit, parent build or native Windows UI/notification test was performed. The earlier 176 checks were not unnecessarily repeated.
