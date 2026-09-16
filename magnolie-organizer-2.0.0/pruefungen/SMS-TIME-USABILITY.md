# SMS scheduling and native custom-time usability — 2026-09-14

## Inspection and integration

The canonical source already contained the following interrupted-task fixes in
both desktop `anwendung.js` files:

- `einstellungen.adressen.smsSchedulingEnabled` defaults to `false`. Only an
  actual stored boolean `true` enables it, including during upgrade/import.
- SMS settings immediately update Schedule visibility. The scheduling dialog,
  save action, scheduler and post-durable-save callback independently check the
  preference. The existing platform-specific phone/routing checks remain in use.
- Turning scheduling off retains plans and their statuses. Pending plans can be
  reviewed from SMS settings while scheduling is off. Explicitly enabling it
  resumes pending plans, including overdue ones; already handed-off messages
  cannot be recalled. This policy is displayed in the settings. Changing the
  preference does not itself invoke the scheduler or grant transport permissions.
- Custom appointments/tasks use the normal calendar's native `input[type=time]`,
  `vorgabeZeiten()` and `bindeZeitRad`. A new time has real hours **and minutes**;
  an existing empty time remains optional. Apply reads the native value and
  validity directly. Incomplete values receive an associated localized inline
  alert, without `reportValidity()` or a fabricated browser segment editor.
- The SMS draft/revision ACK logic and durable planned-SMS save/journal contract
  were already present.

The new production change is a narrow, identical guard in both shared
`bindeZeitRad` handlers: only the focused, enabled, writable time field consumes
the wheel event. Hover-only page scrolling cannot edit a time. This also applies
to normal-calendar and scheduled-SMS time fields because they share the handler.
Five-minute stepping, Shift-hour stepping, configured direction, native horizontal
Shift-wheel events, bounds and calendar start/end coupling are retained.

## Translation review

No new visible strings are introduced by the focus guard. Existing manually
translated SMS enable/pause/resume policy, time validation and calendar wheel
instructions were retained with their exact semantics. `sms_time_catalogs.py`
checks both PO/POT sets for syntax, formats, missing/fuzzy entries and verifies
the relevant labels across English source plus all 19 translated languages.
It checks both frontends against the manual SMS contract and the generated
native resources. `--generate` regenerates the 38 web catalogs, Linux MO catalogs
and Windows `app/native-i18n.json` using the existing compilation tools.

## Native test protocol

`custom_time_isolated.sh` now enforces a 240-second timeout per invocation
(five-second kill grace), CPUs 0 and 1, an empty device tree, software rendering,
isolated network/home/runtime and its own Xvfb/session bus. The tested assets are
read-only canonical source. No native application backend is started.

`custom_time_webkit.py` exercises both source frontends in German and English:

- New/existing appointments and tasks; real default minutes `30`; editing only
  the hour; editing only the minutes; native midnight wrap; blank/partial input;
  focused/unfocused wheel, Shift and reverse direction; bounds; Apply by mouse,
  keyboard, and without depending on blur.
- A real Tab/Arrow/Enter traversal through native hour/minute segments and the
  dialog controls. Partial segment validity comes from WebKit, not a JS mock.
- Normal-calendar comparison cases, including no mutation on hover-only wheel.
- SMS upgrade with overdue plans and no preference, checkbox on/off, bridge save
  payload, complete frontend reload from that saved document, pending-plan review
  while off, and an available synthetic phone while overdue plans stay paused.
  Reload covers frontend persistence/normalization; it is not a Windows-native
  setup or native filesystem durability test. Existing separate ACK tests cover
  the durable-save boundary with a capture-only bridge.
- `--all-locales`: native partial-input validation and SMS settings/policy labels
  in all 20 languages, with actual GTK screenshots and associated alert checks.

Every screenshot records viewport/dialog geometry, horizontal overflow, text
overflow and viewport escape. JSON also records source SHA-256, engine version,
CPU affinity, elapsed time, native event trust, current values and saved items.
All SMS bridges are capture-only; native UI scenarios assert no send command.

Example from the canonical root (create the evidence directory first):

```sh
MAGNOLIE_TIME_EVIDENCE=/tmp/opencode/sms-time-usability-20260914 \
  sh magnolie-organizer-2.0.0/pruefungen/custom_time_isolated.sh \
  --web magnolie-organizer-2.0.0/web --output /tmp/evidence/linux-de \
  --locale de --all-locales
```

Use `Magnolie-Organizer-Windows-2.0.0/app/web` for the Windows frontend, and
`--locale en` for English. Windows frontend WebKit coverage does not represent
a native Windows WebView2 execution.

Run native invocations sequentially on the shared two-CPU budget. Two initial
parallel invocations stopped with missing input events in their native event
logs (one missing second digit; one unprocessed Apply click). Their reports are
retained in `linux-en/` and `windows-de/`. The harness now spaces physical key
events by 60 ms and allows 200 ms for native event processing. Paced repeat
reports use distinct `*-paced/` directories; no product-code change was made
to accommodate those test-input failures.

## Results

Evidence directory: `/tmp/opencode/sms-time-usability-20260914/`.

- Targeted custom-time suite: **164 cases passed**, both frontends, all 20 locales.
- Planned SMS/durable-save lifecycle: **30/30 passed**, including disable during
  pending save, stale ACK, failure/retry, restart normalization and status updates
  after handoff while disabled.
- Existing UI/locale suite: **240 scenarios passed**, both frontends, no send.
- Existing Planner/SMS draft-ACK regression: passed for both frontends.
- Structured appointment parity: passed.
- Complete Linux `pruefungen/test.js`: passed.
- Windows `tests/web-smoke.js`: passed.
- Catalog generation/audit: **38/38 PO catalogs passed**, with JS/MO/native parity.

Successful native runs, WebKitGTK **2.52.6**, CPUs **0,1**:

| Frontend / UI language | Cases | Screens | Wall time | Evidence subdirectory |
| --- | ---: | ---: | ---: | --- |
| Linux / DE + 20-language validation/settings | 117 | 58 | 135.337 s | `linux-de` |
| Windows / DE + 20-language validation/settings | 117 | 58 | 168.169 s | `windows-de-paced` |
| Linux / EN | 97 | 18 | 125.796 s | `linux-en-paced` |
| Windows / EN | 97 | 18 | 98.855 s | `windows-en` |
| **Total** | **428** | **152** | | |

All successful runs recorded **zero browser `reportValidity()` calls** and no
SMS send commands. The 152 captured screens were measured at **1100 × 850**:
zero horizontal dialog/control overflows and zero dialog viewport escapes.
Representative DE/EN, Arabic, Hindi, Upper Sorbian and Dutch screenshots were
also inspected visually. The longest successful invocation took 168.169 seconds,
below the enforced 240-second limit.

The two failed initial parallel runs are not counted as passes. The paced
sequential repeats passed all their scenarios; their original reports remain
available for inspection. No package, installer, production build or publication
was performed.
