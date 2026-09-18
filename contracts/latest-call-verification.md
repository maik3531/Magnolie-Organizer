# Latest call fixes — 2026-09-14

Canonical source: `magnolie-organizer-veroeffentlicht`.

## Follow-up: clean finite-exit gate PASS

The Android wrapper's previous exit 124 is superseded by a fresh, genuinely
executed API-35 fixture run with **exit 0 in 118.837 seconds**. All 12 tests passed,
with zero failures/errors/skips. There was no timeout, forced cleanup or remaining
owned process. Application source hashes matched before and after the run.

- Enforced cgroup: `memory.max=6442450944` (6 GiB), `cpu.max=200000 100000`
  (two CPUs), `memory.swap.max=0`; affinity CPUs 0 and 1, one Gradle worker and
  one test fork. Raw cgroup peak: **3336798208 bytes / 3.11 GiB**; no OOM events.
- Progress/process snapshots were written at approximately 0/30/60/90 seconds;
  individual test results and the actual exit were logged immediately.
- `BUILD SUCCESSFUL` occurred at 118.699 seconds; actual exit followed **138 ms**
  later. The gate requires process exit, fresh JUnit files and unchanged sources;
  it does not infer success merely from Gradle's success text.
- Wall budget: 20-second shared-lock wait, at most 260 seconds for the child,
  bounded TERM/KILL and reaping; transient-unit and outer guards keep the wrapper
  below five minutes. No emulator, VM, real profile or phone is involved.

Reproduce from the canonical root:

```sh
python3 -B magnolie-notes/werkzeuge/call_fixture_gate.py
python3 -B magnolie-notes/werkzeuge/test_call_fixture_gate.py
```

The first command uses existing offline dependencies only. The second has four
passing supervisor regressions: EOF/normal exit, nonzero exit preservation,
success-text followed by a hang, and a detached orphan that must be killed/reaped
and must fail the gate. Normal fixture completion required none of that forced
cleanup. The original `/tmp/opencode/latest-call-android.sh` now delegates to this
bounded repository runner.

### Wrapper diagnosis

The old daemon logs showed completion/result dispatch followed by a 60-second
wait for the Gradle client's final message. A controlled reproduction with an
inherited terminal input stalled even with every task **UP-TO-DATE**, when no
Robolectric test worker had been launched. The same launch with `stdin=DEVNULL`
exited naturally in 9.78 seconds. This isolates the failure to the terminal-linked
launcher/client shutdown path rather than application call-listener threads.
An intermediary launcher also changed the symptom, so this report does not claim
an unobserved JVM-internal stack frame as the cause. A cross-namespace `jcmd`
attach was denied; no speculative application-thread rewrite was made.

The fix explicitly closes child stdin, closes inherited descriptors, waits for
the actual child, tracks/reaps owned descendants, and preserves failure on any
timeout or forced cleanup. It also prevents the shared Android lock descriptor
from leaking into launched child processes.

### Current-source native and frontend gate

The latest combined native gate is **PASS**. It includes all four complete Linux
Python modules compiled at their actual source paths, 153 Python call/audio/
protocol tests, five phone-daemon compatibility tests, 95 C# capture assertions,
both frontend traces, all 20 existing call/audio translations, and isolated
GTK/WebKit checks for both web trees.

The actual `magnolie-organizer-windows/MagnolieOrganizer.Windows.csproj`
also passed its complete **Debug `Compile` target** in **8.819 seconds**, retaining
the project's warnings-as-errors policy. This compiles the actual Windows source
set, including native form/notification code, rather than only extracted test
methods. Restore was offline and locked; outputs stayed in the private temporary
tree. No production build or publish target was invoked.

The first redirected-output attempt incorrectly included old canonical `obj`
assembly attributes and failed. The test sandbox was corrected to hide only the
canonical generated `obj/bin` directories, leaving their real contents and the
project untouched. Compilation then exited 0. Concurrent edits by the other
agent changed the two frontend files during that check; the hash gate detected
this. Only the frontend/audio/GTK checks were repeated against the newest files;
that recheck exited 0 in **6.720 seconds**, with unchanged hashes during the run.
All other recorded native source hashes still matched.

The popup fixture now decodes a generated local PNG through the real GTK image
loader, checks the 42×42 avatar, Magnolie style class and accessible controls, and
checks foreground and hidden/tray frontend behavior. It runs under private
Xvfb/D-Bus with Mesa software rendering, without a host window or host GPU.

### Measured fixture latency and logs

These measurements are synthetic local pipeline timings, not phone/network/HFP
latency or a hardware performance guarantee:

| Measurement | Observed |
|---|---|
| Android-emitted state → Linux native backend/Unix IPC/frontend callback | 4.103–11.090 ms |
| Incoming answer action → captured phone transport command | 10.465–10.905 ms |
| Actual GTK compact surface mapping, latest two web-tree runs | 1.890–53.929 ms |
| Gradle success text → clean process exit | 138 ms |

Evidence:

- `/tmp/opencode/latest-call-clean/gate-result.json`, `run.log`, `progress.jsonl`,
  `sources-before.json`, `sources-after.json`, fresh JUnit XML and `trace/*.json`.
- `/tmp/opencode/latest-call-native-clean/verified-gate.json` combines the retained
  `native-result.json`, successful compilation in `compile-recheck.json`, and
  the final `frontend-recheck.json`; `verified-sources.json` records the final
  source hashes. Earlier unsuccessful aggregate checks are preserved, not
  relabeled as successful runs.
- Native stage `*/run.log` and `*/process-result.json` contain exits and timings;
  `linux-trace/run.log` and `gtk-*-recheck/run.log` contain pipeline/map timings.

Windows automatic hands-free remains **unsupported in the current deployment**.
The explicit feature request and researched driver-free OS candidate, including
package/capability and Store-versus-sideload distinctions, are recorded in
[windows-handsfree-feature-request.md](windows-handsfree-feature-request.md).
No manifest permissions, driver, keyboard automation or Qt rewrite were added.

## Inspected baseline and corrections

The existing working tree already contained directed Android call tracking,
ephemeral action tickets, Linux daemon/GUI delivery acknowledgements, native
compact call surfaces, and the native HFP capability implementation. These were
inspected and extended rather than replaced.

Corrections in this pass:

- GUI calls always try the compact Magnolie surface, including a hidden/tray GUI
  and profiles whose **reminder** style is system notifications. Failure falls
  back to the native notification API. Unsupported answer/reject controls remain
  visible, translated, individually disabled and accessibly labeled.
- The frontend no longer disables rejection just because answering is unavailable;
  the backend issues each action only if its actual capability/grants permit it.
- Linux system-action activation consumes the exact live ticket through same-user
  IPC and then launches the GUI without forwarding/replaying a call request.
  Successful Windows system activation restores the existing GUI host.
- Call-state capability/version revocation also prevents action issuance/execution.
  Both desktops reject expired/future call observations as well as expired tickets.
- Linux observations retain their authenticated source channel. Reconnect cannot
  mint new tickets from a previous session's ringing state. Initial handshake
  observations are re-presented only when their own channel activates. Delayed
  callbacks recheck authority before changing daemon/GUI state.
- Both frontends reject stale revisions, direction changes within one ID and
  terminal-call resurrection; retained metadata contains no caller name/photo.
- Android installs the pending desktop answer origin before entering Telecom.
  Immediate OFFHOOK callbacks therefore correlate correctly. A previous effect
  attempt without a durable result no longer claims `already_answered` or
  successfully submitted termination.

All user-visible labels/explanations reuse the existing manually authored
20-language translations. The call/localization fixtures validate the PO entries,
native catalog and `msgfmt` format checks. No new message IDs or PO rewrites were
needed for this pass.

## Executed verification

| Check | Result and boundary |
|---|---|
| Python `test_callstate_alerts.py`, `test_call_audio.py`, `test_telefon.py` | **153 passed**; synthetic peers/stores, fake BlueZ/Pulse, real temporary Unix IPC |
| `test_hintergrunddienst.py -k phone` | **5 passed**; phone proxy/daemon compatibility |
| Android `CallLifecycleTransportTest`, `CallControlOriginTrackerTest` | **12 tests, zero failures/errors/skips**; Robolectric API 35, controlled `placeCall`/answer/end Telecom shadow, actual dial submission/tracker/protocol receiver/encrypted queue |
| C# `tests/callstate/DelayedCallbacks.py` with Android traces | **95 assertions passed**; source-linked coordinator and extracted current native form methods; capture-only platform objects and phone stream |
| `tests/callstate/frontend.js` with Android traces | Both actual desktop frontend call handlers passed; bridge and dialog effects captured |
| `tests/call-audio-regressions.js` | Both desktop settings migrations, persisted opt-out, routing snapshots and guarded Windows capability passed |
| `pruefungen/callstate_webkit.py` for Linux and Windows web trees | Real GTK popup mapping, accessible/disabled controls, answer/reject/local silence, stale-before-map and withdrawal; both frontends visible and hidden/tray passed in isolated Xvfb/WebKit |

Android exported fresh `incoming.json` and `outgoing.json` under
`/tmp/opencode/latest-call-clean/trace`. The replay driver
`pruefungen/call_transport_trace.py` feeds those actual generated lifecycle bodies
through Linux `_payload` → daemon events → Unix IPC → native GUI presentation →
captured answer command, for both own-popup and fallback paths. Each incoming
trace produces exactly one answer command with the original call ID; outgoing
traces produce no incoming alert or answer command. The Python replay uses the
recorded clock. All three states reach the frontend callback. C# replays the same
bodies (rebasing timestamps only), then
decrypts the actual authenticated outgoing capture frame to check command type
and exact call ID. The JS driver also replays both traces through both frontends.

The Android runner is offline, uses a private home/build tree and synthetic
keystore, has no real device or bus, and does not execute queued discovery work.
Historically, the earlier Android run reported `BUILD SUCCESSFUL in 29s` and wrote passing JUnit
results, but a remaining sandbox process kept its wrapper open. The bounded
120-second wrapper then terminated it (exit 124) and released the shared Android
lock. This is **not** recorded as a clean wrapper exit or a passing release gate.
Earlier wrapper leftovers were explicitly interrupted; no test process was left
running. This historical wrapper failure is resolved by the clean follow-up gate
above. An intermediate dial-fixture assertion incorrectly compared an encoded
`tel:` URI as raw text; it was corrected to inspect the URI scheme and decoded
scheme-specific part, and the complete dial fixture then passed.
The isolated graphics runner needed explicit Mesa software-vendor selection to
avoid an Xvfb/NVIDIA loader crash; the successful runs used that selection only
inside the test sandbox.

## Hardware/platform gaps

- No real phone call, microphone/speaker/SCO transport, user profile, or host audio
  route was exercised. Trace replay plus Telecom shadows is not a physical call
  test or one uninterrupted cross-process hardware session.
- Android public `acceptRingingCall(audio-only)`/`endCall` remain permission/API-
  gated and deprecated. OEM/emergency/self-managed call restrictions and aggregate
  Telephony callback races require physical validation. No dialer role is silently
  acquired, no fake connected state is generated, and API-31+ caller numbers can
  remain unavailable.
- Linux HFP uses only the existing authorized, paired/trusted, bound phone and
  installed native HF/AG duplex endpoints. The fixture-verified loopbacks connect
  those actual OS endpoints; they are not a substitute HFP implementation. Audible
  duplex interoperability remains unverified.
- Windows automatic PC call audio remains honestly **unsupported** for this Win32
  deployment without an approved packaged `phoneLineTransportManagement` adapter.
  Windows-native WinForms/WebView2/Toast/named-pipe activation was not executed on
  Windows during this pass. Its portable capture tests do not prove native display.
- Wayland compositor placement and system notification policy/actions need native
  desktop validation. The GTK runtime map acknowledgement and fallback paths are
  tested, but Xvfb is not a Wayland compositor.

No production build, publication, VM/emulator, real phone, host audio rerouting,
or external review was used. SMS/time and Tablet application code were not edited.
