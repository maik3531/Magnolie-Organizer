# Phone webcam: two capture providers, one native AV backend (Refs #244)

## Original native parent controller and versioned C boundary (Refs #551)

PhoneCameraAudioParent now owns the actual runtime/control/status/anchor/audio
composition behind a versioned trusted-native C API. Its callbacks MUST originate
from the exact #550 managed output authority, never renderer flags or copied
pairing state. The expected worker hash MUST come from the immutable program
payload. Production creation uses the protected fixed-sibling RuntimeImage gate;
positive tests cannot bypass that gate except through absent-in-production test
access to the fixed own diagnostic executable. Opaque handles are not pointers,
are never reused, and permit only one original active owner at a time.

Prepare creates all own first-instance user+SYSTEM/local/exact-held-child pipes
and the outer guardian before Resume. The control publisher runs independently
at 40-ms intervals while the actual worker prepares. Its internal first-publication
event only closes a startup race; Ready additionally requires the exact worker
status and same runtime's completion gate, fresh control and live original owner.
Merely creating a handle or process does not grant readiness or SEND.

The first actually admitted audio OR video PTS maps through ONE parent clock.
The same exported 33-byte anchor goes to the worker and is available for the
trusted FrameServer broker; every video frame must pass the parent observer before
native video delivery. Audio uses a private erased 1938-byte copy, exact native
sequence/monotone PTS admission and SEND checks. Its actual runtime operation is
started before PCM publication and completed only by the same child's exact token
status under the original 250-ms deadline. No new audio receipt-time origin is
created, and export cannot substitute another scope/epoch.

Stop is a terminal signal independent of the command mutex. Stop-reachable child
objects are published once through atomic pointers and retained until all callers
finish. Clock retirement occurs while its parent callback context is still alive.
Close stops/joins publishers and verifies own worker exit before removing its
handle; unconfirmed cleanup retains the terminal registered owner. Callers must
retain callback/module lifetime until successful Close. Unknown/stale handles,
replay, overlap, malformed records or original loss cannot revive or replace it.

Six NEW actual Windows native/kernel groups passed: C-ABI/invalid/protected-image
refusal; joined lease/status/anchor/PCM flow; no SEND/size/replay; original loss,
exclusive owner and no revival; pending operation Stop with concurrent Close; and
production DLL exports loaded only for version/invalid/denied-owner calls. The
positive IPC peer is deliberately the fixed own diagnostic executable, NOT real
AudioRender Open/Write or protected-package readiness. MSVC /W4 /WX test and
production DLL builds passed without private test access in the latter. An initial
test-only missing algorithm include failed before execution and was corrected;
no unchanged old suites were rerun. No endpoint, AudioClient, stream, MF startup,
installer/UAC/default/VM or physical capture operation was used.

The DLL is not yet embedded/loaded by the production Organizer. Immutable DLL
artifact/resource identity, managed loader and concrete outputs, FrameServer
context/source wiring and actual device/AV latency/phone/OBS/package acceptance
remain #503/#536/#538/#486. IPC/clock success is not synchronized system-microphone
readiness. Original device pauses, default-OFF and release gates remain in force.

## Original joined output authority, not substitute callbacks (Refs #550)

IPhoneCameraOutputs.PrepareAsync now receives the exact original session-owned
OutputAuthority, not a separately supplied mute flag/readiness callback. The owner
exposes it only after the authenticated phone's prepared control and exact original
accepted media socket/IP checks. Its native scope and original mute/front choices
remain immutable. A reconstructed object—even for the same session—is rejected
by identity and cannot retire the genuine owner; another session owns a different
context/scope. Metadata or copied flags cannot replace that original object.

Current checks the same original binding/capture context directly, WITHOUT calling
output readiness recursively. Thus prepare can require Current before devices are
ready or actual SEND is published. Sending additionally checks the original
session's actual published SEND state. Merely querying Sending during prepare
refuses that grant without inventing SEND or invalidating a still-current prepare.
Original loss is permanent; returning a source flag cannot revive the context.
Stop withdraws output admission/SEND before cancellation callbacks or outputs.Stop.
A genuine backend failure retires only this original joined owner once and keeps
its first error; an old stopped owner cannot affect a replacement session.

Five NEW actual encrypted local-TCP/controlled-output groups passed on the existing
local .NET host and on actual Windows: prepare versus SEND; exact/forged identity
and independent owners; original loss/no revival; backend failure/cleanup; original
explicit mute. Because the Prepare interface and Stop ordering changed, the ten
affected existing Windows session/control/AV/mute/stall/cleanup cases also passed.
These are five new groups checked on two runtimes plus ten regressions, not twenty
new tests. The canonical test build and changed actual optional Windows product
build passed with zero warnings/errors. Unchanged native worker/artifact/driver
and unrelated test suites were not rerun; BASE excludes the unchanged file path.

The controlled test output is not a production native implementation, and the
typed context is not endpoint readiness or phone OS consent by itself. Native
parent API/data/anchor publication, concrete managed native outputs and trusted
FrameServer service context/broker wiring remain #503. Real device/phone/OBS and
checked-package acceptance remain #536/#538/#486; no AudioClient/endpoint/stream,
installer/UAC/default/VM/physical capture or release was exercised by these tests.

## Immutable optional worker artifact and installed sibling (Refs #549)

The worker now has a source-bound builder using the existing Windows MSVC/SDK,
not a replacement compiler or setup-helper rebuild. Its native x64 executable
and strict v1 SHA256 manifest cover 23 fixed native/build inputs. The optional
MSBuild runtime target verifies those exact current-source hashes and PE identity,
then snapshots the checked bytes. ONE intermediate snapshot supplies both the
embedded worker/resource descriptor and the fixed output/publish sibling. Publish
does not reopen a mutable external artifact as its runtime image source.

The managed runtime payload reads ONLY its own immutable assembly resources,
validates bounded x64 executable/descriptor/hash/source structure, and retains
its own binary copy. Missing resources mean unavailable, not download, user-path
staging or permission to execute. Resource identity supplies the future native
verifier's expected hash; an adjacent manifest/setting/command-line hash never
does. Ordinary/base builds need no native compiler or runtime artifact, and a
supplied artifact is rejected if the optional camera composition is disabled.
No extra runtime elevation or write-to-user-directory path is introduced. The
installed sibling still requires the protected-path/held-identity checks of #546.

Three NEW managed memory groups passed for immutable copy/no external fallback,
PE/digest rejection and strict manifest structure. The actual builder produced a
native executable and exact 23-source manifest without executing it. Current BASE
and BOTH Windows-target product builds passed with zero warnings/errors; actual
PE inspection confirmed absence in BASE and matching embedded/sibling bytes in
BOTH. The existing setup-helper resource hash remained unchanged. Actual
publish-item computation points to that checked intermediate snapshot. Four new
actual imported-target refusals passed for changed image, stale source, wrong
machine and disabled camera composition. No old worker/guard/audio test suite was
rerun; the memory-test inputs/assembly were preserved before adding only the
read-only product-inspection helper.

This is build/resource/output wiring, NOT an installed protected runtime or audio
readiness acceptance. No application/worker/helper was started, installed or
published for these checks; no endpoint/stream/AudioClient/UAC/default/VM operation
was used. Native parent API/data/anchor publication, actual authenticated managed
outputs/session binding, FrameServer broker and real phone/OBS/latency/package
acceptance remain #503/#536/#538/#486. Device pauses and default-OFF remain intact.

## Actual isolated audio worker entry (Refs #548)

PhoneCameraAudioWorker now builds as the standalone native x64 worker consumed by
the runtime's fixed CLI: three distinct canonical nonzero control/audio/anchor
GUIDs and one strictly decimal inherited original parent handle. It refuses a
self/guessed/noninherited/dead/non-OS-parent handle or absent bounded kill-on-close
one-process job. The original named terminal stop event must already exist and
be unsignalled. Missing stop/control bootstrap is rejected before worker COM/MF
startup, journal/topology queries or any AudioClient call; it never creates a
replacement stop event or grants control from command-line metadata.

The actual source path receives the original Prepare lease, starts its independent
control reader, and calls AudioRender::Open with that actual lease. The separate
outbound report channel checks the kernel server against the SAME held parent.
Ready is emitted ONLY after successful Open and live original Current checks.
The worker waits for actual SEND, reads the immutable 33-byte anchor from its
original-parent-admitted anchor pipe and imports it with the control scope.
There is no first-audio receipt-time anchoring. It then admits exact audio records
through AudioRelay/Samples, maps original sample PTS through that clock, executes
the real renderer Write and emits exact monotonically matching operation tokens
ONLY after successful Write and live SEND checks. No constructor/status flag or
arbitrary readiness callback replaces these calls.

Report IO has a 50-ms bound; errors/stop withdraw the context and control reader.
Control is signalled/joined before its lease/context is destroyed. The outer
RuntimeProcess guard remains mandatory, including during COM shutdown/release:
this worker cannot make Windows COM calls cancellable. Muted sessions must not
launch this microphone worker; it does not silently change mute or fall back to
another endpoint. No capture, setup, default/volume/global-effects API is added.

Actual x64 MSVC /W4 /WX builds passed for the linked worker and test executable.
Five NEW selected negative groups passed: strict CLI; parent/handle refusal; actual
guarded child with missing stop event; missing original control pipe; terminal
original stop event. A test-only observer confirms every case returns BEFORE
worker COM/MF/AudioRender entry; it cannot bypass admission or substitute a device.
The separately built production PE contains no test access. That exact hash-bound
production PE was also executed with no arguments, an invalid command and no
parent handle, yielding the expected64/64/65 exits; no own test process remained.
No old status/guard/AV suite was rerun. These negative admission cases are NOT a
positive worker/AudioClient/system-microphone/AV/OBS/package readiness acceptance.

Positive Open/Write and combined AV operation remain unexecuted: real-PC audio
starts are suspended under #536; #538 has no verified logged-in safe VM baseline.
The immutable embedded worker artifact/manifest and protected installation,
productive managed original-session/output binding, native parent audio/anchor
publication and FrameServer broker remain #503, as do actual latency compensation,
phone/OBS/system-capture and final checked-package acceptance. No devices are
unpaused and no installer/package is published by this worker source change.

## Exact-worker status receipt bound to outer deadlines (Refs #547)

RuntimeStatus supplies the parent's separate inbound status pipe for the SAME
RuntimeProcess. First-instance/local byte-mode overlapped IO, remote rejection and
a user+SYSTEM DACL protect the fixed control-scope-derived namespace. Accept checks
the actual kernel client PID against the held original child, never a lookup or
substitute process. The runtime must outlive the status reader and its joined task.
The independent control publisher remains free to renew leases while status waits.

Each private 18-byte v1 record is phase, u64 big-endian status sequence and u64
big-endian operation token. Ready is first, phase1/sequence0/token0; a subsequent
write report is phase2 with the next exact sequence and actual outstanding token.
Ready calls the SAME runtime's CompletePreparation; write acknowledgement calls
its CompleteOperation. Malformed/partial/replayed/cross-token/phase records,
unexpected peers, original withdrawal or Stop cancel ONLY this owned pipe and
retire that own runtime. Reads use a whole-record bound and repeatedly recheck
the original runtime's existing deadline. Thus a late complete record can never
extend the outer bootstrap/operation window or resurrect a killed worker.

Six selected NEW actual Windows own-child/kernel-pipe groups passed: exact ready
and operation receipt; invalid ready version/phase/sequence/token; subsequent
sequence/token/phase replay; partial record under the original operation deadline;
Stop during an observed pending read plus original withdrawal; and another kernel
client rejected while the expected child remained suspended. Existing guard groups
were not rerun. MSVC /W4 /WX and a production status object without private test
observers built cleanly. Tests deliberately use a fixed diagnostic child emitting
controlled records, NOT an actual initialized audio renderer or protected package.

Status bytes alone do NOT establish audio readiness: the actual packaged worker
must emit Ready only after positive original-lease-backed AudioRender::Open, and
write completion only after that renderer's actual Write under the matching
operation. Its native entry/report producer, immutable artifact/manifest and
managed authenticated-session/AV/FrameServer integration remain #503. No positive
real AudioClient/endpoint/stream/MF startup/install/UAC/settings/default or VM was
used; phone/OBS/system-microphone and package acceptance remain open.

## Verified suspended runtime and external process guard (Refs #546)

RuntimeImage accepts only the fixed native worker sibling of the current program,
with SHA256 expected from the immutable original application payload. External
manifests, settings, arbitrary executable paths and user-provided hashes are NOT
trust sources. Read/delete-denying file and ancestor handles, non-reparse checks
and administrator/SYSTEM/TrustedInstaller ownership plus mutation ACL checks
protect that identity; writable portable installations fail closed. The drive
root is held without treating its general directory-creation ACL as app trust.

RuntimeProcess creates ONLY that image, suspended, with a fresh unnamed job:
kill-on-close, one process and 256-MiB process-memory limit. No shell, elevation,
installer, existing PID or foreign-process termination API is exposed. The exact
inherited-handle list contains only a read/query original parent process handle;
the job/other parent handles are not inherited. Environment/search inputs are
reduced to the Windows system directory and the verified working directory.
The independent guard starts before the caller may Resume. The caller must first
establish original pipes/terminal stop channel, then verify actual child readiness
before CompletePreparation; that method by itself grants NO readiness/authority.

Bootstrap has a fixed 10-s deadline, including suspended time. Each subsequently
declared native operation has a fixed 250-ms deadline and an exact one-use token.
Overlap, replay, late completion, phase misuse, original Current loss on calls or
Stop permanently retire the child. Original session retirement MUST signal Stop;
the guard deliberately does not call a potentially blocked original callback
while timing a native call. It requests own-job termination before notifying an
owner on timeout; process exit is checked separately. An idle process is not a
heartbeat/readiness witness. Stop signals without waiting on a command mutex or
COM; WaitStopped explicitly reports cleanup confirmation/failure. The original
owner must keep contexts alive and join/dispose outside its callbacks.

Six new actual Windows kernel-process groups passed using the fixed own diagnostic
executable through private test access only: job secured before Resume; operation
deadline/replay/no revival; Current withdrawal/Stop; the real unchanged 10-s
bootstrap limit while still suspended; mutable/missing-image and phase refusal;
and abrupt own-parent ExitProcess. In the latter the child deliberately ignores
parent death, proving kernel job cleanup rather than voluntary shutdown. A held
wait-only child object is transferred to the test root, never reopened/killed by
PID. MSVC /W4 /WX and a production object without private test access passed.

This does NOT positively validate a protected installed worker image: the existing
test build directory is user-writable and is refused by the productive verifier.
The actual worker binary/embedded immutable manifest, readiness/operation response
protocol and managed original-session binding remain #503, together with AV-anchor
distribution/FrameServer broker, actual device latency and phone/OBS acceptance.
No AudioClient, endpoint, stream, MF startup, installer/UAC/settings/default, VM or
physical capture was used. Linux/macOS process models remain separately unverified.

## Immutable cross-process AV epoch record (Refs #545)

PresentationClock can now export its fixed original anchor AFTER its first
admitted frame and import that exact anchor once BEFORE any consumer-local Map.
The 33-byte v1 record contains version, the exact original scope GUID (canonical
Data1/Data2/Data3 big-endian followed by Data4 bytes), remote PTS and native MF-time
microseconds (both u64 big-endian, bounded to 2^53-1). The original mapper latches
its export scope; subsequent exports preserve both coordinates and cannot change
scope. An importing mapper cannot become a new exporting origin or reimport.

Import validates/copies the entire record before committing either coordinate,
requires the expected nonzero original scope and original Current/actual SEND,
and rechecks withdrawal at its final guard. Invalid/partial/cross-scope/range
records, replacement and authority loss retire the clock. Failed export never
partially modifies its destination. Consumer arrival time checks its local clock
domain only; it does NOT replace the original native or remote coordinate. Map
continues to enforce original authority, integer/range/rollback and 250-ms due
bounds. The exact SAME producer record must reach both tracks via their admitted
original process/broker channels; these bytes alone grant no authority/readiness.

Six new selected native groups passed: identical large-integer mapping despite
different arrival times; malformed/cross-scope/range rejection; first-frame and
fixed-scope export; no reimport/reanchor; original/final-guard withdrawal; and an
actual own child importing the original record through a kernel pipe restricted
to its explicitly inherited read handle. In the first bundle five groups passed;
one test itself added ten million to an already near-maximum PTS. Only that test
was corrected to use a separate valid long-lived epoch and rerun successfully.
No product code was changed after the first build. The changed clock object/API
also passed the nine existing local-anchor/authority/range/MF-domain regressions;
these are not additional new tests. Builds used existing x64 MSVC /W4 /WX.

This implements epoch transfer, not productive distribution or AV synchronization
acceptance. The authenticated session must establish the original anchor from its
first actually admitted frame, send the same record to the audio child and trusted
FrameServer resolver, and preserve lease withdrawal. That runtime/broker wiring,
verified launcher/outer guardian, actual device latency compensation and real
phone/OBS/system-microphone acceptance remain #503/#536/#538/#486. No AudioClient,
endpoint, stream, driver/install/settings/default or VM was used for these tests.
Linux's shared local epoch is not changed or newly accepted by this Windows work.

## Original-parent control publisher (Refs #544)

OutputPublisher implements the producing half of the native control lease. It
requires original native Current/SEND/retirement callbacks and a held live OWN
child process whose OS parent is the current process. The verified native launcher
must create that child suspended and establish its pipes/outer guardian before
resuming it; this class never launches, elevates, looks a process up again by PID,
terminates a process, installs a driver or opens an audio endpoint.

The fixed local control pipe is first-instance, byte-mode, overlapped, rejects
remote clients and has a DACL limited to the process user and SYSTEM. Accept
requires the kernel client PID to match the still-held original child object.
Each serialized publication derives its phase from the actual original SEND
callback, not a supplied renderer flag: no SEND-first or rollback to prepare.
The whole 18-byte record expires in at most 250 ms; pending writes use a 50-ms
limit, peer accept is bounded and all owned IO is cancelled/drained on failure.

Stop signals a unique terminal per-scope event and cancels ONLY its own outbound
IO without waiting for a publisher mutex. The child must include that original
event in its control bootstrap guard, so withdrawal does not wait for lease expiry.
An existing event/pipe collision is refused, never reset, signalled or reused.
Original retirement is idempotent even when its callback signals Stop again.

Five actual Windows kernel-pipe/owned-child groups passed: prepare/SEND/terminal
stop; absent Current/SEND-first refusal; phase/clock rollback; wrong held child,
wrong kernel client and untouched existing-event collision; and Stop during a
backpressured write. A controlled clock deliberately does not expire in the stop
test, proving the terminal event—not expiry—withdraws the child. MSVC /W4 /WX and
a separate production object without the private test observer both built cleanly.
No AudioClient, endpoint, stream, MF startup, install, settings or defaults were used.

Successful publication means metadata delivery only, NOT child/device readiness
or phone consent. The productive managed-session binding must supply the exact
authenticated Current and actual SEND state, never a saved pairing/checkbox. The
verified runtime launcher, positive child readiness, one shared interprocess AV
anchor, FrameServer bridge and real device/phone/OBS/package acceptance remain
#503/#536/#538/#486. Default-OFF, explicit mute and device pauses are unchanged.

## Nonblocking native AV-clock retirement (Refs #543)

PresentationClock::Stop is now a lock-free, idempotent retirement signal, not a
wait for the mapper's anchor mutex. The original retirement callback fires once.
Callbacks may signal Stop, but still must not reenter Map or destroy the clock
or context; the owner stops and joins its workers before destruction. Current
and SEND checks recheck the retirement signal after callbacks, including the
final mapping guard, so the controlled in-guard stop produces no usable mapping.
Actual downstream delivery still requires its separate original authority check.
Mapping remains serialized and uses the same fixed joined AV epoch/bounds.

The OLD callback contract prohibited reentrancy. This is a newly required safe
joined-owner stop integration, not proof of a historical runtime clock failure
or an explanation of the independent Audiosrv/SystemSettings incident. Before
the change, controlled own-child cases failed the new nonblocking/reentrant-stop
requirements. After the change all four cases passed under the same bounded
own-child harness. Because Clock::Check/retirement changed, the nine existing
integer/AV-offset/range/authority/native-MF-clock groups were also rerun and passed;
they are regression evidence, not nine additional new tests. No endpoint,
AudioClient, stream, installer, default role or settings operation was used.

The Linux _PresentationClock.delay has no corresponding native stop/anchor mutex;
its session uses a different lock/wakeup design. No Linux/macOS fix or device
acceptance is inferred from this Windows source change. Shared interprocess AV
anchor/bootstrap and productive native output/device/phone/OBS gates remain #503.

## Original native output-control lease (Refs #542)

OutputLease owns an already kernel-original-process-admitted control PipeReader.
Its fixed private 18-byte v1 record contains phase (1 prepare, 2 SEND, 3 stop),
big-endian sequence and local GetTickCount64 expiry. Whole records retain the
original pipe deadline and are erased after use. No constructor grants Current
or SEND. Prepare grants only Current, SEND cannot be the first record or roll back
to prepare, and stop is terminal with zero expiry. Each nonterminal lease must be
strictly future and no more than 250 ms away. Sequence replay/gaps, stale/far-future
expiry, clock rollback, process loss, malformed/partial control, concurrent reads
and Stop fail closed, signal the control reader and retire the original joined
owner once. Even a fresh-looking later record cannot renew an already expired
lease. The control reader's bootstrap guard must not recursively query this lease.

AudioRender::Open now accepts ONLY this actual control-backed lease; its productive
factory no longer accepts caller-supplied Current/SEND callbacks or replacement
control objects. Prepare uses its Current callback; Write/Start use its separate
SEND callback. The same held control process must still be the actual OS parent.
The lease and original callback context must outlive all borrowing workers/clocks.

Eight selected Windows kernel-pipe/own-child groups passed for phases, malformed
records, sequence/phase rollback, expiry/no resurrection, pending-read Stop/expiry,
original process exit, no-grant creation and concurrency/partial-record deadline.
The changed typed render factory checks were selected separately, including a
real accepted PREPARE that still cannot admit an in-process UI fallback. An initial
test-fixture disconnected-pipe reuse failure was corrected with a fresh namespace;
only that failed case was rerun, not the unchanged passing case. The existing
MSVC /W4 /WX builds and production render object without test access passed.
No positive real device initialization, AudioClient or stream was exercised.

This lease is NOT a phone consent or independent original-session authority:
the productive parent publisher must originate only from the actual authenticated
joined session, publish SEND only after actual SEND, and withdraw/terminate its
owned child on retirement. That publisher/child bootstrap, the ONE shared AV clock
mapping and real endpoint/normal-consumer/phone/OBS/package acceptance remain open
under #503/#536/#538/#486. No platform/device pause or default-OFF gate is lifted.

## Isolated native audio render worker (Refs #541)

AudioRender now implements the actual WASAPI render-side code, but is not yet
connected to a productive child-process bootstrap or advertised as ready. Open
now consumes only the control-backed OutputLease above, with original live
Current/SEND/retirement and an already admitted control PipeReader whose held
server process is the actual OS parent, not the current process. This rejects an
in-process UI fallback before any device access.
Preparation checks the original current capture context, not SEND: the original
session prepares outputs before it publishes SEND. Initialization never starts
the stream; every actual Write/Start additionally requires actual original SEND.
The control reader and callback contexts must outlive the worker. Its original
controller must externally bound/terminate this isolated child: endpoint COM
activation, Initialize, buffer, Stop and Release calls cannot be made cancellable
by this class. A late-returning call is a failure, never reported as timely output;
already committed OS data cannot be retroactively erased by a local timer.

The positive initialization path only reads the existing protected setup journal,
checks its scope/state/error and unique ROOT\\MEDIA instance, active VB hardware
ID/provider/version, and selects exactly one active topology-matching speaker-form
render endpoint with the original never-default mask 0x307. It never selects a
default or name/format fallback, starts setup, or changes properties/roles/volume.
It requires per-client RAW, shared event-driven 48-kHz float stereo and a bounded
buffer; this does not alter global effects or make ordinary capture clients work.

Each already admitted 960-sample PCM16LE block is copied privately, converted by
the exact power-of-two normalization and duplicated to stereo without resampling
or gain adjustment. Presentation uses the supplied ONE joined native epoch, not a
new audio origin. The write has a 250-ms whole-operation guard around pacing and
buffer waits, live checks at acquisition/copy/commit/start boundaries, and shared
retirement on failure or concurrent writes. Revocation before commit erases the
acquired output buffer and releases it as silent; Stop itself only signals.

The existing x64 MSVC /W4 /WX build passed including a separate production object
without the private test-friend macro. Nine groups passed using controlled
IAudioClient/IAudioRenderClient implementations, real MF memory samples, and owned
kernel-pipe child processes for actual-parent admission. They cover exact signed
PCM conversion, invalid input, eight owner boundaries/silent refusal, client
errors, pending-write Stop/concurrency, whole deadline/PTS/clock rollback,
no-owner/no-parent/in-process denial, SEND refusal before writing/starting, and
late-returning padding/acquire/commit/start
calls. Positive journal/device initialization and real
AudioClient activation were NOT executed; no real endpoint, stream, driver,
settings or defaults were touched. Earlier versions were rerun only after adding
actual-parent admission and fixing deadline checks around returning COM calls;
counts are not additive.

Original process launch/lease/bootstrap, shared AV scheduling, actual endpoint IO
and ordinary-consumer/phone/OBS/package acceptance remain open under #503/#536/#538.
No Linux/macOS output or Android/device pause is changed by this source work.

## Native audio pipe receiver (Refs #540)

AudioRelay now takes ownership of an already original-process-admitted PipeReader
and retains an explicit guarded Samples owner. One fixed 1,938-byte record uses
the reader's single whole-record deadline, then the AudioRecord entry copies PCM
into its own Media Foundation sample. Private record storage is erased after
each receive. Stop, malformed input, read failure, missing output or concurrent
read refusal retire the pipe and shared sample owner; no partial sample escapes.
Creation refusal preserves the caller's existing reader/result ownership.

The existing x64 MSVC /W4 /WX relay build passed. Seven new Windows groups alone
executed actual local kernel pipes and owned test child processes with synthetic
PCM: fragmented consecutive records; malformed-record/shared retirement; pending
read Stop/revocation; a partial record's whole deadline; mute/SEND refusal; invalid
creation/null output; and original process exit. No AudioClient, endpoint, stream,
device, driver, default role or settings operation was used. The old video tests
were not rerun and their SourceReader evidence is not claimed for these audio tests.

This is a native receiver primitive, NOT a productive WASAPI output process or
system microphone. The original production owner must admit distinct channels,
bind the exact sample/control owners, recheck authority at actual delivery and
join AV scheduling/retirement; none is granted by creating this receiver. Those
bridges and real phone/OBS/package acceptance remain #503/#486; #536/#538 remain
open. Linux/macOS device output is unchanged and not newly accepted.

## Native audio record reception (Refs #539)

The native Samples::AudioRecord entry now accepts the exact existing 1,938-byte
v1/track-2 record, decodes its big-endian sequence/PTS with explicit integer bounds,
and sends its unchanged PCM16LE payload through the original Samples::Audio path.
That path retains the original live-owner checks, explicit mute, sequence/PTS
continuity, shared AV epoch/skew and fail-closed retirement of both sample lanes.
Invalid sizes, headers and integers produce no sample; input bytes are unchanged.
Successful reception owns an independent actual Media Foundation memory buffer.

The existing x64 MSVC /W4 /WX native build passed. Only three new memory groups
were executed on Windows: payload/header/bounds and independent-buffer delivery;
invalid-record atomic rejection/shared retirement; and original-owner, mute,
continuity and AV-skew refusal. No AudioClient, endpoint or stream was opened;
no driver, settings, default roles or installation changed. This is a native
sample receiver entry, NOT a connected pipe/output process, system microphone,
ordinary OBS/browser capture, phone AV synchronization or package acceptance.
It does not change Linux/macOS outputs; productive Windows integration remains
#503 and normal-consumer/isolated-environment acceptance remains #536/#538.

## Native audio record boundary (Refs #537)

The optional Windows camera composition now includes PhoneCameraAudioPacket:
an exact 1,938-byte native record containing version 1, track 2, big-endian u64
sequence and PTS microseconds, then 1,920 unchanged PCM16LE mono payload bytes
(960 samples at 48 kHz). It copies payload ownership and rejects wrong tracks,
lengths, negative/ambiguous integers and nonexact destinations before modifying
the destination. Two memory checks cover signed PCM extremes, little-endian
payload preservation, header byte order, integer bounds and atomic rejection.
Actual base/both Windows-target builds and PE inspection confirm exclusion from
the base composition and inclusion with camera support. This serializer neither
opens a native pipe/device nor grants capture/SEND or proves a productive audio
adapter, ordinary OBS compatibility or joined AV scheduling. The phone wire
format is unchanged; the isolated output process still needs a trusted bridge.

## Live Notes UI admission (Refs #535)

The Advanced webcam card, including its first-setup restart hint, is hidden until
native status confirms a currently connected authenticated Notes session. A saved
pairing is insufficient. Linux status checks existing live channels only, without
optional module imports or device inventory; missing or failed status fails closed.
The open settings view refreshes status every two seconds. Disconnect hides the
card and discards local choices. Native start/install still require their exact
original live channel and one-use action; visibility itself grants no authority.
Wi-Fi and actual capabilities remain separate native preparation requirements.

The German hint is: „Bei der erstmaligen Einrichtung kann wegen einer nötigen
Treiberinstallation ein Neustart erforderlich sein.“ The hint has entries in all
19 Linux catalogs. There is no claim about what normal Wi-Fi use does not require.
Windows has no productive Advanced webcam card yet; its future admission must
observe this same live-connection requirement. Its explicit VB-CABLE installation
question and actual reboot-required result remain distinct from this generic hint.
Controlled native/DOM/catalog tests are not phone, OBS or delivery acceptance.

## Actual Windows setup and reboot boundary (Refs #533, #534)

After an interrupted first run with no accepted installation, a fresh clean
preflight preceded the separately authorized successful second run. The original
unelevated desktop parent and same-user elevated child were observed; the native
application returned 3010 and the own journal reported reboot-required. The
unchanged signed VB-CABLE Pack46 package installed one new owned MEDIA devnode;
its actual driver version is VB-Audio Software 3.5.2.0, not “4.6”. All six original
user audio-default selections matched before/after installation. The 618 checked
temporary application files and temporary tasks were removed; the successful
driver, protected package and journal were intentionally preserved.

The user subsequently restarted Windows manually. Read-only postboot acceptance
confirmed that exact signed device active, all three topology-matched endpoints
active with NeverSetAsDefaultEndpoint=0x307, all six original defaults unchanged,
and the original ProgramData ACL unchanged. The journal was not rewritten by the
acceptance probe. No automatic reboot, security weakening or reinstall occurred.

This proves installation and that postboot endpoint state, not a usable system
microphone. Separate bounded synthetic PCM probes under #534 block in capture
IAudioClient::Initialize, including before any render AudioClient is initialized.
Starting render with silence first did not resolve the block; omitting the
render-only NOPERSIST flag on capture did not resolve it either. No successful
PCM, phone/Wi-Fi AV, FrameServer broker, OBS or package acceptance follows from
the setup result. A later transient missing-default snapshot was rejected before
audio IO; a fresh original-user read-only snapshot again matched all six defaults.
The cause of that transient observation remains unconfirmed. Probe code is not
an accepted productive output adapter and is not shipped as such.

### Subsequent processing-path and actual PCM evidence (Refs #534, #536)

A one-shot own-thread Wait Chain Traversal query subsequently confirmed an ALPC
wait toward the Windows Audio service, without a detected wait cycle. Existing
SCM/WER events independently record two Audiosrv hang terminations, waiting on
audiodg AudioClientRpc. No debugger privileges, foreign thread suspension or memory
dumps were used. Windows' existing service recovery restarted Audiosrv; Magnolie
did not restart the service or Windows. Read-only inspection of the exact owned
virtual endpoints found additional signed Waves MaxxVoice/MaxxAudio mode/stream
effects. This is evidence of the actual processing configuration, not proof that
Waves alone caused the hang or permission to modify other devices or drivers.

Requesting RAW through IAudioClient2::SetClientProperties for the own capture
client allowed Initialize to return. RAW is a per-client processing option, not
a privacy, driver, exclusive-mode or always-on endpoint-effect bypass. Both own
clients in RAW with render prepared first subsequently carried real synthetic
PCM. The original unchanged-sample tests remained failed. Analysis of synthetic
buffers only identified startup settling followed by an exact adjacent-sample
0.5/0.5 interpolation. A separate predeclared test then sent 9,600 silence frames
followed by 48,000 signal frames at 48 kHz and checked only that fixed two-tap
model: all 48,000 signal frames matched in both channels with maximum error zero.
No fitted gain, arbitrary DSP model or changed result for an earlier failed run
was used. Six original-user default selections remained unchanged, and a fresh
normal-desktop read-only check confirmed both audio services running with exit 0.

This proves a bounded own virtual PCM data path with the stated transformation,
not unprocessed bit-exact audio or ordinary OBS/browser capture. Those consumers
do not necessarily request RAW. A separate own-endpoint property experiment
durably saved the original empty Disable_SysFx property, set and read back the
documented value using the ordinary endpoint IPropertyStore, tested normal-mode
capture, and restored/verified the original empty value under the same own
topology and 0x307 policy. Normal capture still timed out. The experiment therefore
does not establish effective control of the modern effects store and must not be
shipped as an automatic fix. No global enhancement setting, other endpoint, ACL,
driver, volume, default selection or security setting was changed. Undocumented
policy interfaces and restricted-capability bypasses are not acceptable fallbacks.
The normal-consumer/system-service issue remains #536; concrete productive output
adapters, common AV scheduling, phone permissions and OBS acceptance remain #503.

## Explicit Linux driver setup and confirmed installation (Refs #515, #520, #524)

Only an explicit Advanced-functions Enable/prepare with an original connected
Notes parent may prepare the host driver. Status, startup, KDE-only selection,
missing Notes and disabled optional builds do not run driver setup. Virtual
inventory uses only virtual sysfs nodes and metadata-only QUERYCAP on a held
read-only descriptor; physical cameras, frame buffers and format changes are
excluded. The actual capture output still requires its original native owner.

When the current kernel has no `v4l2loopback` module, a supported host with native
PackageKit integration gets an explicit install-and-set-up question. A one-use
native offer (60 seconds, exact original Notes parents) is required in addition
to the normal system authorization. Cancel, provider change, stale offers or
context loss cannot start installation. Package names, repositories and commands
are never supplied by the renderer. Debian/Ubuntu and Arch-family hosts resolve
only `v4l2loopback-dkms` from their existing repositories, restricted to a single
newest architecture-appropriate result. Installation AND the fixed setup operation
share ONE normal pkexec authorization of isolated system Python. No password is
read or stored by Magnolie. The already authorized root worker uses native system
PackageKit with interaction DISABLED: failure cannot silently fall through to a
second password dialog. ONLY_TRUSTED remains mandatory, without adding repositories,
importing signing keys or performing a general upgrade. The package-phase deadline
is 600 seconds with native cancellation; one original 710-second deadline spans
the authorization, installation and setup, with a five-second cancellation grace.
An unconfirmed timeout is latched:
there is no automatic retry or rollback claim. Package success alone is not a
current-kernel-module or capture proof. The root worker confirms actual module
loading and the original user worker checks inventory under the same Notes parents.
After combined success, even delayed udev publication only gets a bounded inventory
wait: it cannot start setup again or request another authorization. Missing kernel headers, module-signing/boot or
backend problems are not papered over by a successful package transaction.

During this combined operation, the original user worker checks its live Notes
context and writes only binary native monotonic heartbeats on one private stdin
pipe. The root worker requires a fresh stamp after the dialog; old queued stamps,
EOF, stale/future/nonfinite stamps and the original deadline cannot authorize new
IO. This pipe accepts no package names, paths, commands, consent flags or passwords.
Context loss cancels the original native package transaction and interrupts setup
through its existing exact-owned rollback. The pipe/worker ends with the operation;
no persistent privileged service, broad polkit policy or reusable admin token exists.
These heartbeats grant no phone capture or SEND authority.

An unknown AppImage host, unavailable PackageKit integration, ambiguous/missing
package or failed installation gets a manual system-package-manager hint naming
`v4l2loopback`; the AppImage never guesses arbitrary distro commands. Existing
usable outputs and the separate installed-driver setup continue to work without
PackageKit. The DEB declares `v4l2loopback-dkms` only as Recommends, never Depends,
and only if its actual staged composition contains the optional webcam feature.
No install hook starts phone capture or performs Magnolie's driver setup.

An installed but unavailable output is
prepared with normal polkit administrator authorization. Isolated system Python
executes a fixed standard-library-only operation, not a user-writable script or
renderer-supplied code/path. The only native argument is the original monotonic
setup deadline: a late authorization cannot create a new privileged interval.
No permissive polkit policy, persistent capture authorization or generic IPC
root-command route is introduced.

The operation loads only `v4l2loopback` and creates its own
`magnolie-phone-webcam.conf` under `modules-load.d` and, if no existing module
options/live parameters would be overridden, `modprobe.d`. Default new-module
options are one output, exclusive caps and a Magnolie label; no fixed video number
or default-device change is imposed. Directory/file owner, mode, type, link and
exact-content checks reject unfamiliar files and symlinks. New files are published
exclusively and durably; failure rolls back only unchanged newly owned files.
No existing module is unloaded. Autoload prepares the driver for future boots,
not phone capture. Reconnection, phone permissions and original AV/SEND authority
remain independently mandatory.

Driver/probe/administrator failure returns typed UI status without camera choices.
Setup is single-flight and original Notes context is rechecked around native IO.
Administrative time is bounded inside the privileged operation and outside it;
only the prepare and explicitly confirmed installation IPC/UI waits are extended.
Other request deadlines are unchanged. Unit tests use real private test files
and controlled command/PackageKit adapters, never host package/module/configuration changes. Actual
native package installation, system authorization, boot autoload and OBS/phone acceptance remain separate
from these source/host proofs. No package was installed or published for them.

## Scope and current status

The user prioritizes webcam before further photo target switching and requests
two possible Android providers: **KDE Connect** and **Notes**. The desktop output
backend and binary media contract are provider-independent. Controls belong only
in Organizer → KDE Connect → Advanced functions. Android shows genuine OS
permission/foreground-service controls, not a new settings page.
Webcam is a separate optional feature, OFF by default, independent of photo/video
sync. Selecting/enabling photo sync or merely connecting either app never enables
camera/microphone capture. Notes has priority for automatic provider selection.
While enabled, expose genuine system-wide camera and associated microphone
endpoints, behaving like separately attached webcam hardware for applications
using the OS's normal capture interfaces. No per-application Magnolie plugin,
private stream URL or Organizer preview can substitute for this requirement.
Explicit disable/disconnect must retire both endpoints/feed paths. Verify actual
compatibility in independent capture applications rather than promising every
possible application's behavior without testing it.
The Organizer must remain fully usable without this optional feature. No new
mandatory package, virtual-device driver, camera/audio service or phone app may
become a base startup dependency. Do not import/probe webcam backends during base
phone-service startup, even when the optional code was included in the build.
Load and inspect native prerequisites only for an explicitly enabled webcam.
Missing prerequisites must disable/report only this feature, not abort Organizer
startup or unrelated synchronization. No new mandatory package dependencies have
been added by this backend unit; V4L2/Pulse prerequisites remain optional.

This is an implemented backend boundary, **not a usable/delivered webcam yet**.
Linux output adapters, binary transport, joined output lifetime, provider selection
and native Notes capture/control dispatch exist. Organizer Advanced-functions
controls now expose the explicit native entry. Windows native outputs, a compatible
KDE capture provider and actual phone/native-camera/OBS acceptance remain open.
Normal startup advertises no webcam activation.
No installed OBS/phone capture acceptance or package delivery is claimed.

### Native Notes capture implementation (explicit activation only)

The Notes source now has a real ActivityResult permission host, a one-use original
request and foreground-capture permit, and a Camera2/ImageReader + AudioRecord
engine. Constructors do not prompt, probe devices or start capture. The permission
host requires a visible original Activity and rechecks actual OS permissions;
result Booleans, missing microphone permission, expired or changed native contexts
cannot authorize a start. An old stopped Activity keeps its OS-result slot until
that exact callback returns, preventing reassignment to a newer request.

The engine requires the original actual camera/microphone foreground-service
types before looking up a camera. Explicit mute omits microphone capture. It uses
bounded ImageReader buffers, exact padded/interleaved YUV→I420 conversion, and
Camera2 realtime / AudioRecord boottime timestamps. Native permission loss,
device errors, startup/stalled tracks and close retire the common session.
Late camera-open callbacks close their original device on the still-live app
executor; unknown native shutdown remains pending rather than authorizing reuse.
Ordinary optional adapter/observer failures are contained instead of crashing
the Activity or native cleanup thread.

The entry now has early MainActivity permission-host registration and a private
camera/microphone foreground-service declaration. Camera, autofocus and microphone
hardware remain optional; registration never prompts or starts capture. All four
gallery permission/consent slots and the webcam slot mutually block each other.
The visible-Activity rendezvous holds no persisted request and never launches UI
from the background. The native authenticated routes below now join this entry,
and the Advanced-functions UI now exposes it. This is not physical phone/webcam
acceptance or evidence of working OBS capture.
The new checks cover 15 distinct JVM/Robolectric cases, including real Android
adapter APIs under simulation and synthetic YUV buffers, not physical capture.

The bounded capture/send lane now implements separate current-capture and actual
bilateral-SEND guards. Before receiver-ready admission it retains only the newest
private video/audio sample and sends nothing; readiness requires fresh samples
for both default tracks. Active audio has a ten-packet bound and stops both paths
on backpressure, never silently dropping audio. Only whole unsent video frames
may be replaced, without allocating gaps in per-track wire sequences. The common
epoch comes from the actual held boot timestamps, not UI flags or receipt time.
Guards remain live even while the queue is empty; denied old owners cannot revive
when matching flags return. A dedicated already-connected SocketChannel writer
uses nonblocking bounded IO and creates no listener, target selection or reconnect.
Ten targeted JVM tests include independent wire digests and an actual local socket
write.

The joined foreground run now owns the actual Camera2/AudioRecord engine, lane
and originally admitted dedicated socket. The remote address must match the
authenticated parent's pinned peer; capture preparation is not permission to
send. Five joined-runtime tests cover generated-source wire output, missing SEND,
wrong peer and the real default engine's no-camera cleanup under Robolectric.
Three affected existing engine tests also passed after the lifetime join.

The nonexported, nonsticky service accepts only a one-use in-memory native handoff,
uses the actual camera/microphone foreground types, and stops only for its exact
opaque original token. The one-capture slot remains held until native drain AND
service destruction. Its localized notification distinguishes starting, actual
capture preparation, explicit mute and stopping. Missing/restored/stale intents
cannot create capture. Five service tests passed; a later Activity/manifest check
passed 34 cases covering the service, permission host, rendezvous, optional hardware
contract and phone-module isolation. Android manifest declarations are not OS
consent or physical acceptance. The authenticated control/start join is described
below; native device-success and OBS acceptance remain open.

## Authenticated control exchange under implementation

Reserved desktop discovery version **24** is distinct from file versions 21/22
and capability 23. It is never advertised on startup or from saved flags. The existing capability key set is
strict and Notes already has 16 versions when all current handlers are enabled;
adding a seventeenth would break old peers. The compatible design therefore uses
desktop-only discovery followed by a fresh phone-initiated probe on that same
authenticated parent. Never send extension controls to an unproven older peer.

The matching Notes/Python schema uses small `device_status.request/report` v24
controls: probe, offer/unavailable, prepared, send, stop/error. Offers bind the
fresh UUID/nonce, new session/key, numeric dedicated port, explicit mute and camera
choice; URLs, AV payloads, permission flags and extra fields are rejected. JSON
here carries control/key negotiation only, never frames or audio. The Notes
envelope has a 4096-byte/60-second bound. The Python PhoneService dispatcher now
validates the same envelope bound before any ordinary status, replay or storage
route. Reserved v24 controls are rejected from persistent queue/history APIs too.

The desktop exchange now binds its fresh random session/key and offered port to
one actual original TCP control socket and one listener on that original local
interface. Only a matching prepared message permits an accepted media socket
with the original peer address and that exact listener's local address/port.
No accept worker, target URL or reconnect is created by this controller.
The receiver creates both native endpoints before invoking the bounded original
control callback for SEND. A separate live data guard must then confirm the
agreement; a successful callback/ready Boolean alone is insufficient. Both the
binary socket and native-output lifetime continue checking the original guards.
Failure retires the endpoints/key/listener, not the base phone control socket.

Ten desktop-exchange tests use real local TCP control/media sockets, actual
encrypted synthetic AV and controlled native-output adapters, not physical capture
devices. Nine affected receiver cases and 29 native-output cases also passed;
the added optional module remains covered by the 20 composition cases. These
earlier adapter tests did not prove an encrypted parent. That original limitation
is addressed by the separate signed-dispatch tests below, not retroactively
claimed for those older tests. No Windows native outputs are added.

### Linux native service integration (Refs #503)

`PhoneService.begin_native_webcam` is now an explicit native confirmation entry,
not a settings loader or incoming-packet action. It requires the actual current
SecureChannel/Wi-Fi peer, original service/store generation, protected paired
identity, an actually sent capability witness and the optional camera build.
No photo-sync binding, stored grant or shared-document role authorizes it. It owns
one bounded worker and four-entry private control queue. Only that original owner
may advertise v24, accept its fresh phone probe, bind the dedicated socket and
prepare native outputs. Normal startup imports/probes no camera modules.

Probe tokens and ACK IDs are bounded in-memory channel records, not durable
replay state. Old probe/STOP/ACK messages cannot retire a different new owner.
Explicit stop, service stop, pairing/transport replacement, generation loss and
identity loss retire the original owner without provider fallback. A slot is not
reusable until its worker and native cleanup have actually drained. The exact
original STOP and v24 withdrawal use bounded parent control sends. Withdrawal
checks the actual outbound capability object's identity under the writer lock,
so it cannot restore old metadata over another real control update.

The sender bounds writer-lock waiting and uses the original socket's existing
bounded timeout without changing its receive timeout. It rechecks the nonblocking
native owner before frame publication. Denial before IO consumes no sequence and
keeps the parent. An actual attempted ciphertext-write failure retires only that
uncertain original parent, rather than reusing a partial frame/sequence. Ordinary
AV stop/failure does not reconnect or close a healthy parent.

The activity projection requires actual video and default audio writes through
the paired native outputs; a connection, offer, prepared/READY message or UI flag
cannot turn the camera icon on. Explicit mute requires only real video writes.

Eleven new service cases perform the actual signed X25519/HMAC PhoneService
handshake and AES-GCM parent dispatch over local TCP. The positive case negotiates
offer/prepared/SEND, sends real encrypted generated AV into controlled output
adapters, then stops both paths while keeping the encrypted parent usable. They
also check nonpersistent controls, optional-OFF, old peers without probes, original
context loss, late old messages and failed native construction. Ten writer cases
check bounds, revocation and normal-send compatibility. These are not physical
Android/OBS or actual V4L/Pulse-output tests; the phone counterpart is test code.

The #504 fix retains the actual native cleanup owner on unconfirmed Pulse
load/unload exceptions, including constructor failures. The service retains that
private receipt and keeps its slot busy, even if no receiver constructor returned.
The targeted Pulse model has 15 passing cases, including two fail-before/fix-after
cases and confirmed-cleanup control; it opens no real Pulse source. The signed
dispatch failure test exercises this actual Pulse adapter against the controlled
native ABI model and checks no guessed cleanup or capture-slot reuse occurs.

The Notes exchange binds one original parent object, fresh probe/nonce, monotonic
startup lifetime, phase and live native parent guard. Changed/expired original
authority cannot revive when matching flags return. Foreign parent/nonce packets
cannot adopt or retire a different exchange. A permit with matching metadata is
insufficient: it must belong to the exact original Android permission request.
The exchange can construct the real joined foreground run; only that run's source
preparation callback permits a matching receiver-ready SEND transition. Before it,
an offer is neither an OS permit nor wire SEND. A matching stop retires the run.

Checks passed: 41 Python body cases, six Notes schema/capability/envelope cases
and seven original-exchange cases. The joined positive case uses genuine Android
permission/foreground adapters under Robolectric and generated source samples;
it does not prove a physical phone.

### Notes dispatcher and native lifecycle integration (Refs #503)

`TelefonWerk` now consumes the webcam namespace before ordinary replay/storage.
Only an actually accepted fresh desktop capability control on that original TCP
parent can create the private runtime; saved v24 metadata never starts a probe.
Discovery received during authentication waits for actual session activation.
Withdrawal, parent/lifecycle/generation replacement and stop retire its original
runtime. Private bounded ACK records never enter the persistent queue. Neither
control IO nor its original guard acquires Werk's book/storage monitor.

`PhoneWebcamNotesRuntime` sends its fresh probe over the actual encrypted parent,
then handles only matching offers. The main thread requests genuine OS consent
through the existing visible-Activity host and starts the real one-use FGS only
with that request's exact permit. No foreground host means an error, not an
Activity launch. A late grant after parent revocation cannot start a service.
The actual source-prepared callback queues a bounded worker operation: connect
the dedicated socket to the parent's actual remote IP, bound to its actual local
interface, then send PREPARED. No socket connect/control write blocks a native
capture callback or the Activity. Only a matching authenticated SEND activates
that original binary lane. No silent provider switch/retry exists.

Original parent writes now have bounded lock admission and reuse the existing
original-pipe deadline watchdog for actual IO; the read timeout is not misused
as a write timeout. Pre-publication denial consumes no counter and leaves a
healthy parent open. Attempted uncertain ciphertext IO retires that exact pipe.
Startup is bounded to the original 60-second window, including pending consent;
close removes the runtime's own callbacks and signals worker/capture shutdown.
The Notes queue, prepared-outbox and inbox/history paths reject v24 and malformed
numeric/string aliases even outside the main dispatcher.

Five runtime cases use actual encrypted local TCP parent/media sockets and the
genuine ActivityResult/FGS adapters under Robolectric. Generated source buffers
prove the complete permit/service/connect/PREPARED/SEND/AV/STOP join; the real
default Camera2 factory is separately checked for no-camera failure, not positive
physical capture. Four actual Werk-routing cases use a controlled admitted parent
and check saved-metadata inactivity, real control dispatch, foreground denial,
withdrawal and progress while Werk's monitor is held. These admitted-parent tests
do not claim a newly exercised signed Notes handshake. Seven bounded-writer cases,
the queue rejection case and affected ordinary protocol/queue/manual-sync checks
also pass. The PC retains a phone's explicit permission-denied reason instead of
misreporting it as a successful ordinary stop.

Both base dispatchers and the Organizer frontend are now joined in source.
Physical Android/OBS, Windows-native endpoints and the compatible KDE streaming
provider remain open; no physical usability acceptance is claimed.

### Advanced-functions native activation (Refs #503)

Controls appear only below KDE Connect → Advanced functions, including for a
Notes-only installation with no paired KDE provider. Off remains the default;
opening the page only reads status and does not enumerate devices or import the
optional native module. Explicit Enable prepares at most 32 opaque choices from
live original Wi-Fi Notes parents and existing virtual video devices. Stock KDE
selection reports that a compatible extension is required, without fallback.

Preparation issues a private one-use action token and per-choice tokens, expiring
after 60 seconds. It never returns a path or URL to the UI. Start consumes the
action, validates explicit mute/front booleans, opens/validates the selected
loopback output, checks fstat identity and holds that exact descriptor. Original
store/generation/key/channel/actually-sent-capabilities identity is checked again
under service admission before the authenticated discovery probe. The receiver
uses that held original output, never reopens a path selected by JSON. Pending
permission, cancellation, constructor failure and stop close the held output;
uncertain native cleanup continues to retain the original capture slot.

Strict status/action IPC and PhoneServiceProxy accept only prepare/provider,
start/action-token/choice-token/mute/front, cancel/action-token and stop/lease.
No persisted enabled flag, driver install, arbitrary native factory, path or URL
is accepted. The actual GUI bridge also checks book trust and lock state. Stop
requires the original opaque owner lease. Active status follows actual native AV
delivery, not successful preparation or a phone's permission reply. New labels
and diagnostic reasons are translated in all 19 desktop catalogs.

Automated acceptance covers a real Unix daemon socket and signed encrypted phone
parent, plus generated encrypted AV through the original held controlled video
and controlled audio adapters. The actual frontend function executes with a
controlled DOM/bridge, and the actual GUI handler is tested without GTK. These
are source/runtime proofs, not native GUI/physical phone/OBS acceptance; no new
driver, APK, installer or release was installed or published.

### Windows implementation boundary (still open)

The current Windows target remains `net8.0-windows10.0.19041.0`. Microsoft's
[`MFCreateVirtualCamera`](https://learn.microsoft.com/en-us/windows/win32/api/mfvirtualcamera/nf-mfvirtualcamera-mfcreatevirtualcamera)
API starts at Windows build 22000, not at that base target. An eventual Windows 11
adapter therefore needs runtime availability gating and must not make Organizer
startup or the Windows 10 base require this DLL/export. Session lifetime and
current-user access can bound the camera's enumeration lifetime; they do not
implement a media source or establish a microphone endpoint.

The API requires the CLSID of a custom media source, not a stream URL. Microsoft's
[`VirtualCamera` sample](https://github.com/microsoft/Windows-Camera/tree/master/Samples/VirtualCamera)
separates the native media-source DLL from registration/installation and the
manager. Its MSI example registers the DLL under HKLM. Do not silently run that
installer, add its startup-task/systray behavior, wrap a physical PC camera or
replace the optional default-OFF model with sample defaults. A usable phone
adapter must supply decoded received phone frames to its own source and prove
bounded activation, authenticated frame delivery and complete native teardown.

A camera API is not evidence of a system microphone. Windows audio endpoint
creation/routing must be implemented and accepted separately; ordinary playback,
WASAPI loopback capture, an MF audio stream or a camera's name alone cannot be
reported as the requested independent microphone input. No new mandatory driver
or dependency is authorized by this design note. The existing Windows
`DesktopPhoneBuild.PhoneCamera` constant remains only build composition, not
runtime readiness. Neither a Windows system camera/microphone endpoint nor its
acceptance is claimed.

#### Windows microphone prerequisite and signing boundary (Refs #503)

The requested independent microphone cannot be replaced with a Media Foundation
audio stream. A new own kernel audio driver for normal current Windows with
Secure Boot would require [Microsoft's driver-signing process](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/kernel-mode-code-signing-policy--windows-vista-and-later-); an own self-signed
certificate is not a production alternative. The user cannot obtain Microsoft
or third-party signing for an own driver. Do not enable test signing, disable
Secure Boot/signature enforcement, import a local root to bypass that requirement
or promise an unsigned-driver release.

The user's required alternative is an optional already appropriately signed
third-party driver, with the same guided installation model as Linux: explain
the missing prerequisite once and ask whether to install it. After affirmative
consent Magnolie must manage the verified download, installation and explicit
endpoint routing, using normal system authorization, not send the user through
manual setup instructions or silently fall back to video without audio. No
automatic reboot or default-audio-device change is authorized. An unavoidable
reboot must be reported and remain under the user's control. Consent here is the
product-flow requirement, not permission for an immediate host driver install.
If automatic installation fails or is unsupported, Magnolie must explicitly name
the required Windows driver and offer manual installation using its official
provider instructions/download. A pending or unconfirmed installation must be
reported as such, not retried automatically or claimed successful. After manual
installation, recheck actual endpoint readiness; a help link or installed-package
flag alone cannot authorize capture/SEND or silently enable video without audio.

The provider is not selected or integrated yet. VB-CABLE is a candidate, not a
validated dependency: its [current public licensing page](https://vb-audio.com/Services/licensing.htm) describes conditional
as-is redistribution and silent installation with visible donationware/origin
attribution, but the currently downloaded package's readme retains a stricter
integration-with-author-agreement clause. Resolve the applicable permissions
and documented unattended-install behavior before relying on it. No driver
installer has been executed, bundled or accepted by these investigations.
Read-only checks on the physical Windows host verified the official Pack46
catalog with Windows' kernel signing policy, including membership of both x64
and ARM64 driver binaries and the Windows 10 INF. The catalog is signed by
Microsoft Windows Hardware Compatibility Publisher; the vendor setup also
passed Authenticode verification. This is trust evidence for those exact bytes,
not installation, functional compatibility or permission to execute the setup.

The narrowed Windows audio setup work (#530) now targets the original VB-CABLE
Pack46 package, not an own unsigned kernel driver or A+B/C+D. The current
publisher licensing page explicitly permits as-is distribution/silent embedding
with visible VB-Audio origin and donationware information, and imposes additional
licensing conditions for professional deployments where end users cannot identify
or support VB-CABLE. These conditions must be shown in the eventual guided flow;
the older package readme itself links that current licensing page. No unsupported
vendor setup command-line switch is assumed or executed.

`PhoneCameraCablePackage` pins the exact SHA256 of the INF, catalog, x64 and ARM64
SYS files and verifies all three payloads against the catalog with native
`DRIVER_ACTION_VERIFY`. Held read handles deny write/delete sharing. This is a
read-only trust lease, never an installation or endpoint-readiness permit. Five
native package groups pass on physical Windows, including real kernel-policy
catalog membership and tamper/missing/path rejection with own-copy cleanup.

`PhoneCameraCableSetup` provides a pure read-only host/device/journal/protected-path
plan and an explicitly separate elevated installation function. The latter is
only a **compiled, not executed or accepted** installer path so far. It refuses
unsupported hosts, writable source staging, any existing matching device and any
existing setup transaction. It requires an admin/system-owned fixed ProgramData
subtree and records a collision-refusing protected journal before mutation. Its
intended SetupAPI/newdev path selects the exact original INF and only one newly
owned root devnode; it never uses the API that updates all matching foreign
devices. Failure cleanup targets only that newly owned devnode, never global
driver-store packages or another device. Pending/unknown outcomes keep their
journal instead of enabling automatic retry. Publisher-required restart is
reported, never performed automatically. Two read-only native plan groups pass
on physical Windows: host/old-device query and refusal to promote user-writable
research staging, with no setup journal created.

No driver staging, device registration, installation, uninstall, vendor process,
audio default change or reboot was performed in these tests. The source now
includes verified download/protected publication, the native one-question/one-UAC
flow and named official manual fallback. Actual UAC/GUI admission, elevated driver
installation/cleanup, post-restart endpoint reprobe and real WASAPI
microphone-provider acceptance remain open. Actual installation needs
separate explicit host approval; the generated-camera approval does not cover it.

The managed `PhoneCameraAudioPackage` downloader now verifies the complete original
archive before inspecting or extracting it. It owns an immutable checked snapshot,
uses only the fixed official HTTPS origin with bounded redirects, size and time,
and extracts all original members with `CreateNew` into an empty owned directory.
It does not itself establish a protected installation directory. Eight Windows
groups passed, including an explicitly opted-in real official HTTPS download,
unchanged extraction against the native pins, rejection of changed archives,
redirect limits/cancellation and preservation of existing destination files.
Ordinary tests do not download or bundle publisher bytes.

The setup CLI has been compiled and run only with `--plan`. Its JSON now reports
whether all six default-audio endpoint identities can be inspected, the intended
endpoint policy, and `installationAttempted:false`. Current native code prepares
the newly owned devnode disabled, applies the documented never-default policy to
its own topology interfaces, verifies the stored values again after installation
before explicit enable, and compares default endpoint identities afterwards.
In addition to the configuration flag, the documented `DI_INSTALLDISABLED` flag
is set before `DIF_INSTALLDEVICE` and cleared only after policy readback, before
the explicit enable operation; there is no assumption that a registry flag alone
establishes the installation handler's disabled-state contract.
Those mutation paths are compiled only, **not validated by the read-only plan**.
The comparison describes the immediate snapshot, not post-reboot preservation.
The never-default policy blocks both automatic and manual Windows system-default
selection; the eventual installation question must explicitly disclose that
VB-CABLE is selected within individual applications instead. It does not alter
the signed INF or configure foreign interfaces. This design still needs actual
installation/rollback and post-restart acceptance after separate permission.

`PhoneCameraAudioStaging` now prepares the protected-publication source path:
elevation is checked without requesting credentials, the fixed ProgramData root
is created with an admin/system-owned protected ACL, existing paths are checked
through held handles without ownership takeover or ACL repair, and original
members are written into a fresh unpublished directory before a no-replacement
rename to the native helper's GUID path. Partial/unknown outcomes are retained
for review, not recursively deleted or automatically retried. This initial path
refuses nested/UNC ProgramData relocation rather than claiming unimplemented
held-ancestor protection. The actual protected-publication path has now passed
a separately approved Windows preparation probe: all original members and the
source-bound own helper were published unchanged, held byte leases refused helper
writes, the real native `--plan` accepted `protectedPackage:true`, and exact own
files/GUID/root were removed without a journal or driver installation. Production
cleanup consumes only a known uninstalled preparation; once installation may have
started, it refuses cleanup/reuse rather than deleting an unknown outcome.

That real probe exposed Windows-specific gaps missed by the earlier memory-only
test. Normal ProgramData allows concrete child-create/EA/attribute rights. Its
ACL is not repaired or weakened: the held parent uses `FILE_LIST_DIRECTORY` and
no data-write/delete sharing. A metadata-only directory open does not participate
in those Windows sharing checks. Own admin/system-write-only roots permit write
sharing so their children can be atomically renamed, while retaining no-delete
sharing on the held directory itself. The probe checks that actual parent
data-write access is refused. Metadata-only attribute APIs are not claimed to be
disabled by this sharing policy. Failed-probe own remnants were verified by exact
hash/membership/scope and removed before subsequent runs; no foreign ACL changed.
The separate memory-only ACL group also passes the observed standard Windows ACL.

`werkzeuge/phone_audio_helper.py` builds the own native x64 executable with the
installed MSVC/SDK and records exact source/binary hashes. The optional MSBuild
resource target rejects stale sources, changed binary bytes and base-edition
embedding, and embeds a checked snapshot rather than a mutable external path.
Runtime helper bytes and metadata come only from bounded immutable assembly
resources, never a download or an external runtime manifest. Four actual project
compositions and PE metadata checks confirm optional types/resource exclusion;
camera compositions contain exactly the compiled helper bytes. Three helper
validation groups and three negative resource-build checks pass. This hash/source
binding is not a claim of Microsoft signing for Magnolie's own user-mode helper;
the original driver catalog/kernel-policy verification remains mandatory.

`PhoneCameraAudioSetup` now supplies the explicit native setup flow. One question
names VB-CABLE, VB-Audio origin/donationware/professional conditions, administrator
approval, manual restart and per-application-only selection. After consent the
original verified archive is sent in memory through one first-instance local
pipe to the normal Windows `runas` child. Its protected ACL grants only the
original `WindowsIdentity.User` SID, its owner is that exact user, and the native
pipe rejects remote clients. Both peer process IDs, the original user SID, random
one-use token and embedded helper hash are checked. The elevated side additionally
holds the original parent process handle and matches its kernel start time before
connecting, so PID reuse cannot substitute a replacement parent.
The elevated client explicitly uses identification-only SQOS: the lower-level
server may inspect identity but cannot impersonate/delegate an administrator
token. This restriction is checked using the real Windows pipe token level.
`PipeOptions.CurrentUserOnly` must **not** be used across this UAC boundary (#532):
on Windows it also compares elevation-dependent owner identity. Same-elevation
tests missed this defect; the first real normal-to-elevated attempt aborted before
preparation. This correction does not broaden unrelated same-elevation pipes.
Elevation as a different account is refused rather than comparing the wrong
user's audio defaults. No credentials are read or stored. Native preparation and
installation require separate live handshakes on that original pipe; no phone
packet, saved flag, metadata ACK, startup or reconnect creates setup authority.
Before `runas`, the managed bootstrap must itself be protected: the apphost and
managed entry must share a local protected application directory, every ancestor
is held without namespace replacement/data-write sharing, and a bounded,
non-reparse application-tree walk checks trusted ownership/no ordinary-user
mutation rights and retains read leases on all load inputs, including runtime and
culture/native subdirectories. User-writable portable/framework-dependent hosts
are unsupported for this automatic route and receive the official manual
fallback. This avoids elevating a mutable .NET bootstrap merely because the later
native helper is pinned. One Windows group checks the ownership/ACL policy and
framework-dependent host refusal without elevation. After separate approval,
the positive protected-apphost preparation test passed on the actual desktop:
the original unelevated Session-1 parent and elevated same-user Session-1 child
were observed, actual local user/peer/birth-time binding succeeded and the child
returned only `PreparedOnly`. The user reports confirming one typical Windows
consent dialog but did not independently identify its exact dialog class; that
observation is kept separate from the technical elevation evidence. All own app
copy files, temporary task/processes and uninstalled package staging were removed.
This does not accept the advanced-functions installation-question GUI or a driver
installation, and no credentials or global UAC/security policy were accessed or
changed.
The elevated child verifies the archive again, retains protected executable/file
leases, checks the real native read-only plan, and only then may invoke install.
An unknown outcome after installation admission stays pending, never retries or
reboots. The UI awaits child ownership asynchronously; the three-minute IPC
deadline is not permission to kill an in-flight PnP transaction or claim a hard
native installation completion limit. Reboot-required is never endpoint readiness.

A separate explicit preparation-probe mode is bound at both pipe ends and refuses
all native mutation modes, including retry/uninstall; it can run only `--plan`
and then remove its known uninstalled preparation. Base builds reserve the setup
arguments and return unsupported rather than starting the ordinary GUI. Bounded
Windows setup groups cover strict result/argument/wire validation, the exact
single-user pipe ACL, actual local first-instance/owner/peer-PID checks and wrong
original-parent birth-time rejection before preparation. They do not themselves
execute UAC or installation; the separately approved protected-apphost desktop
probe supplies only the technical plan-mode UAC transition evidence described
above. Bounded diagnostic reason/Win32/child-exit codes contain no raw tokens or
credentials. The actual advanced-functions admission/provider connection,
translated question catalogs, installation-question GUI and real installation
still need acceptance. No Windows v24 readiness or
working system microphone is advertised by this preparation work.

Seven distinct affected setup checks pass using the appropriate retained proofs.
The successful protected-apphost UAC snapshot precedes the final identification-only
SQOS tightening; the latter is separately checked on a real Windows pipe and in the
current compiled project. Those different evidence boundaries remain explicit.

The eleven installation-question/outcome texts now have translations in all 19
supported native locale catalogs,
including manual-default-selection exclusion, VB-Audio origin/licensing, pending
outcome and post-restart non-readiness. A targeted extraction/compilation test uses
the actual native UI literals and production native-catalog generator, then checks
the resulting JSON against compiled gettext output for every supported locale,
without relying on English fallback. Driver/vendor/site names are also checked.
This is technical catalog evidence only: independent linguistic review and the
actual native question GUI/admission remain separate from those compilation checks.

The optional Windows camera composition now exposes the explicit local utility
`--prepare-phone-webcam-audio`. It enters a native form before normal application
startup; it never starts pairing, capture or a phone/SEND session. Only the native
default-No question may proceed to verified download and the guarded normal UAC
flow. Extra arguments are refused, and camera-excluded builds return unsupported
instead of launching the ordinary application. The form binds continuation to its
original handle/cancellation lifetime; closing cancels further admission while
retaining ownership until an already-started child exits. Reboot-required maps to
3010, unknown-pending to 1618, never to microphone readiness or automatic restart.
Actual operation of this new question window and driver installation are still
unaccepted and require separate explicit test authorization; previous plan-only
consent does not grant installation permission.

All four current Windows-target compositions compile and PE checks confirm that
the form is present only with the optional camera module. The actual copied native
runtime catalog contains the 209 owned translated entries. Unrelated existing
runtime entries were retained when merging the productive generator's output;
other pending catalog changes are not silently included in this task.

The primary phone transport is Wi-Fi for both camera video and microphone audio,
as requested for DroidCam-like use. A physical USB cable must not be required;
USB is at most an optional future alternative, not the primary implementation.
The native question explicitly distinguishes the VB-CABLE **virtual Windows
audio device** from a physical cable to the phone, in every supported locale.
This clarification is not a claim of completed phone-to-OBS wireless acceptance
or of an already implemented USB alternative.

The managed-to-native video record now has a dedicated pure serializer:
`PhoneCameraVideoPacket` restores the exact version/track + big-endian sequence/
PTS + fixed I420 payload consumed by `VideoRelay`, after the encrypted channel
has separated header and payload. It validates the complete input and exact
destination size before changing output bytes and does not retain frame storage.
Two new local memory groups check byte layout, integer limits, owned payload copy
and rejection without partial output. This is not a connected pipe, FrameServer
broker, system output adapter or SEND permission; those trust/IO boundaries remain
open. The pending Windows installation test's frozen app is unchanged by this
independent serializer work.

#### Windows dedicated binary receiver (Refs #503)

The separate native `native/phone-camera/PhoneCameraSamples` adapter now creates
real Media Foundation samples and media types from already admitted payloads.
Video converts the exact 640x480 I420 planes to tightly packed NV12, without
changing the input. Audio preserves the exact PCM16LE 48kHz mono bytes. Both
retain the same original phone PTS epoch using integer microseconds-to-100ns
conversion, with no receipt-time or separate-track rebasing. Exact payload sizes,
per-track sequences, increasing PTS and the existing 250ms cross-track bound are
enforced. Explicit mute rejects audio; invalid data, original-owner denial and
stop permanently retire both paths. The mandatory nonblocking native owner guard
is checked before allocation, around buffer filling and before sample publication.
The downstream owner must independently remain current at actual delivery.

Ten native groups passed on the physical Windows host using the real Media
Foundation APIs and generated AV only, including byte-for-byte NV12/PCM readback,
large common timestamps, all four guard boundaries, revocation/retirement, payload,
sequence/PTS, skew and mute checks. MSVC and Windows SDK were explicitly approved
and installed; their separate native smoke test compiled against the real SDK
and found the system virtual-camera API, without creating any device.
This adapter is not yet a registered COM media source, frame-server IPC, pacing
engine, system camera or microphone endpoint. It is not called by base startup
or included as a mandatory native dependency. Those native joins, the Windows
dispatcher and actual phone/OBS acceptance remain open. A Media Foundation audio
sample is explicitly **not** an independent Windows microphone input.

`PhoneCameraSource` now implements the in-process native camera media source and
stream (`IMFMediaSourceEx`, `IMFMediaStream2`, their base event interfaces,
`IMFSampleAllocatorControl`, CPU-only service/KS boundaries). It exposes one exact
NV12 video stream and consumes already admitted I420 through a private feed.
Metadata alone never grants SEND. Separate mandatory original-owner and actual
SEND callbacks are checked at publication and again when a sample event is read;
a retirement callback must revoke the original joined AV owner. Foreign source
descriptors, unsupported positions/types and external event injection are refused.
Stop/pause clear unsent requests and frames without resetting original wire
sequence authority; shutdown is permanent and breaks the source/stream parent
reference. Blocking event waits hold no state lock and are interrupted by shutdown.

There are at most sixteen outstanding requests, including samples already queued
but not read, plus one replaceable whole unsent video frame. Queued samples retain
their own monotonic arrival marker: fresh subsequent frames cannot refresh an old
sample. A 50ms native MF work-item check detects original-owner loss even while
idle, five-second startup without a frame and 250ms streaming stalls. Stale
delivery, request overflow, guard failure and invalid frames retire the source
and notify the original owner; no reconnect or invented image/audio is produced.
The callback context must remain valid until `Shutdown` returns, and callbacks
must be nonblocking/nonreentrant. The explicit native owner must call `Shutdown`
even if no capture client ever starts the source.
An optional opaque COM lifetime anchor is retained by the shared native state
until the last source/stream reference and pending callback drain. It is not
capture/SEND authority. This permits a future COM server to keep its native
context alive even when a client holds an already-shutdown stream. The actual
DLL module-accounting/bootstrap implementation remains separate.

Sixteen native source groups pass on the physical Windows host. In addition to
direct events, tokens, bounded memory, stale backlog, original-owner/SEND denial,
descriptor and lifetime checks, an actual `IMFSourceReader` consumes three complete
generated NV12 frames from this source, with exact payload/PTS readback. Real
blocking event shutdown and the actual five-second no-frame deadline are tested.
These are source-object proofs, **not system-camera enumeration or OBS/phone
acceptance**. COM activation/registration, authenticated cross-process frame-server
delivery, joined AV presentation scheduling, the independent microphone endpoint
and the Windows authenticated dispatcher remain open. No driver or registered
camera was installed for these tests, and base-project dependencies are unchanged.

`PhoneCameraPipe` adds a separately checked local input primitive for the pending
FrameServer boundary. It constructs only a fixed local pipe namespace from an
original native session GUID, opens its own overlapped read handle with security
identification (not impersonation), and checks the kernel-reported server PID
against an actual held original process handle. A process name or caller-supplied
PID is not accepted as that witness. It rejects message-mode pipes and a different
server, never reconnects, and never replaces an existing reader. Each bounded read
has one original two-second deadline across partial IO, checks the live original
owner during waits and after filling the buffer, and clears partial output on
failure. Stop wakes pending IO without acquiring the reader lock; cancellation
drains only the owned overlapped operation. Concurrent readers are refused and
retire that original reader instead of starting a queue.

Eight native pipe groups pass on physical Windows using actual distinct ordinary
test processes and local kernel pipes: partial reads, wrong kernel server identity,
stop/revocation during already pending IO, sticky revocation, the shared partial-read
deadline, original-process exit, concurrent-reader rejection and invalid context.
Six unchanged groups retain their first-run proofs; two corrected fixtures use
real duplicated process handles, not Windows' special `GetCurrentProcess()` pseudo
handle, and were the only groups repeated. This component supplies no phone/SEND
authority or frame grammar. Native bootstrap identity, server-side ACL/lifetime,
bounded video-record decoding and binding to the actual authenticated dispatcher
and source remain required; the registered FrameServer path is not yet complete.

`PhoneCameraRelay` now joins that original pipe reader to the exact original
source/feed COM identity. It accepts only fixed-size video records using the
existing 18-byte canonical plaintext packet body followed by exact I420 data.
Version, video track and integer ranges are checked; source-side continuity,
PTS and actual SEND checks remain mandatory. One fixed-size read gives the whole
record one deadline, with no untrusted size allocation or header/body time reset.
The private temporary packet is cleared after copying into the native sample and
on failure. Any parse/read/publication failure retires that original reader and
source; its owner retirement callback must still stop the joined AV session.
No source replacement, reconnect, frame fabrication or audio fallback is added.

Five new native relay groups passed on physical Windows. A separate actual test
process writes generated canonical I420 records through the held-original-process
pipe; the native relay and source deliver three full exact NV12 frames to a real
`IMFSourceReader`. Other cases reject wrong track/overflowed integers, reject a
replacement source's feed before consuming the original reader, stop already
pending pipe input through original source shutdown, and deny restored old SEND
authority. Previous unchanged sample/source/pipe tests were not repeated. This
proves the receiver half and local process boundary with controlled admission,
not the production authenticated dispatcher, server ACL/bootstrap, registered
FrameServer activation, system microphone or physical phone/OBS acceptance.
The network transport remains the existing AES-GCM binary protocol; this is
local post-admission video delivery, not a new unencrypted network option.

`PhoneCameraActivate` now implements the native `IMFActivate`/`IMFAttributes`
boundary. A mandatory trusted original-context resolver, not attribute values,
creates one source. Configuration is copied under the native attribute-store
lock before construction; subsequent attribute edits cannot replace or reconfigure
the existing source. Original context is checked around construction and before
returning an interface. Failure, revocation and shutdown permanently retire that
activation; restored flags cannot retry it. Detach transfers source lifetime to
its actual owner without shutting it down, but the old activation cannot then
create a replacement. Both activation and source independently hold their supplied
opaque native lifetime anchors.

The activation object's final COM release is not an implicit source shutdown
(#526). A separately held source remains usable without requiring a prior
`DetachObject`; the original native controller still must explicitly shut it
down. Explicit `ShutdownObject`, construction failure and original-authority
revocation retain their permanent retirement semantics. Nine native activation
groups now pass, including the regression that failed with `MF_E_SHUTDOWN` before
this correction; the four affected real DLL lifetime groups also pass. This
corrects a Windows-specific object-lifetime defect, not a phone/OBS acceptance.

Eight new activation groups pass on real Windows, covering metadata versus
authority, immutable construction snapshot/original source identity, construction
failure, context loss during/after construction, shutdown, invalid interfaces
and a detached source retaining its real COM-owned context after activation
release. The changed source-lifetime unit has sixteen passing source groups and
its affected five relay groups also pass at that exact source version; these
replace earlier runs, not additional test counts. There is still no registered
class factory, trusted production context resolver or FrameServer bootstrap.
These object tests neither register a system camera nor
grant actual phone consent/SEND or complete the Windows webcam.

`PhoneCameraFactory` now provides the native `IClassFactory` boundary: only fresh
activation/base-attribute objects, no COM aggregation or arbitrary interface/CLSID
route. The trusted native owner supplies activation construction and DLL module
lock accounting; neither callback may initiate capture or setup. A supplied
opaque lifetime anchor remains held while the factory is referenced.

Four native DLL groups pass on physical Windows. A separate private PE DLL was
compiled, dynamically loaded, queried through actual `DllGetClassObject`, and
really unloaded after native MF callbacks drained. It tests rejected class/role/
aggregation requests, distinct activation contexts, a detached source and old
shutdown stream still pinning their native context/DLL, and balanced module locks
across factory lifetimes. The probe is metadata-only and **always denies SEND**:
it contains no frame generator, phone permit, broker or microphone. No COM key,
driver or camera device was registered for these module tests. This is ordinary
test-process loader evidence, not FrameServer service loading or code-signing
policy acceptance of a registered Windows camera.

The separately approved private generated-image harness has now passed a real
Windows FrameServer/system-camera probe after the #526 activation correction.
An elevated interactive setup host created only its own temporary current-user,
session-lifetime camera. A separate **unelevated** interactive consumer opened
exactly the returned symbolic link through standard `MFCreateDeviceSource`,
not direct source activation, and read twelve complete byte-exact NV12 frames:
six of each generated pattern, with strictly increasing timestamps. One initial
status-only `STREAMTICK` response was not counted as an image. The private
generator used `MFGetSystemTime` rather than an unrelated zero-based epoch.
The camera, exact own COM tree, tasks, processes and known-hash probe files were
removed; the final DLL was removed after FrameServer stopped naturally, without
manually stopping the service. The original physical camera was unchanged and
never opened. No physical microphone, phone, foreign driver or reboot was used.
This establishes actual service activation and standard normal-user capture for
that temporary generated source, **not the production authenticated phone path,
microphone endpoint, joined AV synchronization, OBS or package acceptance**.
The test-only generator and registration scripts remain private, not a product
fallback or a persistent installed camera.

`PhoneCameraClock` (#527) supplies an independently checked common integer epoch
mapper for the pending original joined Windows AV owner. One shared instance
anchors the first admitted remote PTS to native MF system-time microseconds;
both tracks retain their exact relative offsets, including an earlier timestamp
from the other track. It never creates separate track/client epochs. Original
owner and actual SEND are checked before and after mapping. Invalid ranges,
backwards native time, native-domain overflow or more than 250ms ahead/late retire
that original clock permanently; restoring flags cannot re-anchor it. Nine native
clock groups pass on physical Windows, including microsecond differences near
the largest accepted remote PTS and a real `MFGetSystemTime` domain check.
This mapper is **not a scheduler or endpoint integration**: authenticated packet
sequence/PTS validation remains upstream; a future joined controller must share
this exact original instance between real video/audio endpoints, wait for the
mapped presentation time, and recheck original authority before native IO. No
phone wire timestamps, existing Linux pacing, or product fallback were changed.

The Windows authenticated parent now reserves v24 controls before ordinary
status processing, durable rejection/dedupe, inbox or outbox handling (#528).
Malformed string/floating aliases of version 24 are reserved too and cannot
escape into the persistent fallback. Without an explicitly bound native owner,
valid phone REQUEST controls receive only a bounded ephemeral `not_granted` ACK;
phone REPORT controls are rejected as the wrong role. Bluetooth receives a
rejection without activating webcam support or disrupting ordinary transport.

`PhoneCameraControlBinding` binds one native owner's live guard and retirement
signal to the exact original `TelefonConnection`. Packets cannot create it.
Its handoff contains at most four immutable controls; overload retires only that
owner. One original probe/request/nonce is claimed per binding and the fixed
native session is supplied by the worker, never by incoming packets. Duplicate
control IDs, old probes and controls from another exchange cannot be requeued or
stop a replacement owner. Sixteen probe identities remain remembered on that
parent; exhausting the bound rejects further probes rather than forgetting old
authority. Explicit stop, parent close/disposal and original guard failure
permanently retire the binding and wake a blocked reader. A broken native cleanup
callback is retained as an error and cannot prevent parent transport cleanup.

Bound outgoing report ACKs have a sixteen-entry in-memory identity history on
the same parent. They never enter durable ACK/retry policy, and only their first
observed status takes effect. A rejection retires only the original bound owner;
a contradictory duplicate or late old-owner ACK cannot affect a replacement.
An ACK means only queued control, never native readiness, capture permission or
actual SEND. Eleven Windows parent groups pass, including an actual encrypted
TCP parent → authenticated RunAsync dispatcher → native inbox → encrypted ACK
exchange, database non-persistence, bounded ACK writer/queue admission, replay,
old-owner isolation, original revocation and cleanup-callback failure.
This attaches the reserved transport path, not the native UI activation, v24
advertisement, provider resolver or actual native AV output. Those remain required
before Windows may expose a usable phone webcam.
The always-present validator/rejection/limited-writer boundary resides in
`TelefonWebcamBoundary.cs` (#531). Coordinator references use optional partial
hooks, so excluding webcam modules does not require their owner/session/provider
types. Without hooks the same strict reserved controls receive the bounded
ephemeral rejection and cannot enter storage. Actual Windows project builds and
PE type metadata were checked for base, camera-only, photo-only and both optional
features: provider/session types are genuinely omitted when disabled. Eleven
parent and ten affected session groups pass on physical Windows after this
split. This fixes the confirmed base-build regression without forcing optional
modules into the base edition or claiming package startup acceptance.

`PhoneCameraSession` (#529) now connects the original control binding to its own
dedicated encrypted AV receiver and a mandatory trusted native output adapter.
Construction starts nothing; explicit Run is single-use. After the original
phone probe it binds one listener only on the actual authenticated parent's local
IP, creates a fresh random session/secret, and publishes OFFER. Phone PREPARED
must arrive through that exact original binding before accepting the media socket
from the original remote IP and preparing the output provider. Both real camera
and microphone readiness must be checked before publishing SEND, except that an
explicit native mute choice omits the microphone requirement. Missing microphone
readiness aborts the joined run; there is no silent video-only fallback. No media
read or output write is reachable until SEND ciphertext publication succeeds.

The original serialized receiver enforces first-zero/consecutive per-track
sequences, increasing track PTS, the common 250ms track-divergence bound, and
refuses audio in an explicitly muted session. One integer-subtracted original
PTS anchor paces both tracks on the local monotonic clock with at most 10ms waits;
more than 250ms ahead/late aborts rather than building a playback queue. The
native adapter still must map that shared original epoch to MF system time
(#527), recheck original authority and perform actual native IO. Both original
guards and actual endpoint readiness are checked throughout. A separate bounded
monitor detects control/permission loss, a missing initial track after two
seconds and 500ms track inactivity. Startup is bounded to sixty seconds, media
accept to two seconds and native preparation receives a ten-second cancellation
deadline. The trusted provider must honor cancellation and make writes bounded
and interruptible by its nonblocking Stop; it may not detach unresolved IO.

Stop permanently cancels the original run, closes only its own sockets, wakes
pending media input and signals both outputs. Explicit stop-induced socket errors
are not misreported as capture failure. Cleanup waits for its original control/
monitor tasks and makes a best-effort STOP on the still-current parent before
disposing the binding. Cancelling an inbox dequeue transfers no control and
leaves final retirement to that owning controller. Unconfirmed provider cleanup
is retained separately and never reported as a stopped, reusable owner; no retry
or replacement is performed. Copied frame buffers and the owned secret are cleared.

Ten session groups pass on physical Windows using an actual controlled encrypted
parent, actual AES-GCM binary media socket and an explicitly controlled test-only
output adapter: joined AV and measured 20ms/66.667ms presentation spacing, required
microphone refusal before SEND, explicit mute, failed SEND publication, original
revocation during pending input and output writes, track gaps, missing initial
video while audio stays active, undeclared muted audio and pending cleanup. Eleven
affected parent groups also pass at the changed binding semantics; the six
unchanged binary-channel groups retain their appropriate earlier passing proof.
This is the productive session/controller implementation with controlled output
tests, **not a real Windows microphone/phone/OBS acceptance**. There is no default
output adapter or product test generator. Native UI admission/discovery, the
concrete FrameServer broker/ACL/activation context and real camera/microphone
provider adapters remain unconnected; the feature must not yet advertise readiness.

`PhoneCameraMediaChannel.cs` now implements the bounded original-socket receiver
for the same HKDF-SHA256/AES-GCM phone-to-desktop lane as Python and Notes. It
checks the authenticated global sequence and declared length before allocating
the payload, validates exact I420/PCM packet sizes and integer ranges, and checks
its required live original-owner guard before/during/after IO and before delivery.
Header and payload share a single two-second deadline. Stop interrupts only its
original dedicated socket before waiting for reader serialization; failure/EOF,
authentication rejection, timeout and revocation permanently retire that channel.
Mutable caller-secret bytes are not retained. It creates no listener or device.

The actual Python sender and this actual .NET receiver exchange generated audio,
video and audio packets over a local TCP connection; their PTS, per-track sequence
and payload hashes agree. Shared compact packet SHA-256 vectors are retained in
`phone-webcam-media-v1-vectors.json`. .NET CoreTests exercise framing/tamper/replay,
grammar, original key/session isolation, guard revocation, stop and deadlines.
Initially these .NET tests ran on the Linux host. The six transport groups also
pass on the existing physical Windows test machine. Neither run is native
camera/microphone endpoint acceptance.
The existing Windows main project also compiles with the optional camera flag
enabled. No Windows authenticated dispatcher, capture-control negotiation, media
source COM DLL, microphone endpoint or OBS success is claimed by this receiver.

`PhoneCameraParent.cs` additionally joins a bounded ephemeral sender to the actual
`TelefonConnection` crypto writer and original network stream. Typed v24 REPORT
envelopes are copied, checked against exact roles/fields/4096 bytes/60-second TTL,
and never sent through persistent outbox helpers. Admission is limited to two
seconds. The mandatory native guard is checked before admission, after the wait,
after encryption and after actual IO. Pre-publication rejection consumes no
sequence and leaves the healthy original parent usable; uncertain attempted IO
retires only that original stream. Ordinary and ephemeral frames share the real
existing cipher sequence. A late caller mutation cannot replace the copied
control. REQUEST-role packets cannot be sent by this desktop entry.

Five additional .NET groups execute schema/role checks and the actual encrypted
writer on local TCP, including its original semaphore, post-encryption denial,
two-second busy admission and revocation after actual ciphertext publication.
These tests construct a controlled admitted parent; they do not exercise a new
signed Windows handshake or an actual native webcam owner. No fresh-discovery
advertisement, incoming webcam dispatcher, positive SEND authority or native
endpoint is enabled merely by adding this sender. Those joins remain open.

The five parent groups have additionally passed on the physical Windows test
machine, using the existing bounded SSH test route and hash-bound test binaries.
The first Windows run exposed only a test-cleanup defect: pooled SQLite handles
prevented deleting the fixture's own `phone.db`, unlike Linux unlink semantics.
Issue #505 closes exactly that own pool before deleting the own temporary root.
Only the four affected groups were repeated; the six transport groups and one
schema group retained their unchanged prior Windows proofs. This gives eleven
distinct passing Windows transport/parent groups, not eleven native devices or
physical phone/OBS acceptance. No global SQLite pool or product behavior changed.

## KDE Connect versus Notes

Inspected upstream KDE Connect Android commit
[`207dcdb17681557f738c5b16642baa6b9fa076c0`](https://github.com/KDE/kdeconnect-android/commit/207dcdb17681557f738c5b16642baa6b9fa076c0)
(2026-11-08). Its
[manifest](https://github.com/KDE/kdeconnect-android/blob/207dcdb17681557f738c5b16642baa6b9fa076c0/src/main/AndroidManifest.xml)
declares CAMERA and RECORD_AUDIO, but its service declares connectedDevice, not
camera/microphone capture service types. Its
[plugin source tree](https://github.com/KDE/kdeconnect-android/tree/207dcdb17681557f738c5b16642baa6b9fa076c0/src/main/java/org/kde/kdeconnect/plugins)
does not contain a ready webcam/AV streaming plugin. Manifest permissions are not
a streaming protocol, current consent or a usable webcam. The installed phone's
exact KDE Connect version/capabilities have not been physically inspected.

A KDE provider therefore needs a real compatible Android extension before use;
stock KDE Connect must remain unsupported for this feature. Notes can contain a
native capture service without requiring a custom KDE Connect distribution.
Android permissions belong to each app and cannot be transferred between them.
The Notes codec is not a decision to capture twice or exclude the KDE provider.

Neither provider may require the other app to be installed. Notes-only must have
its own authenticated capture/control path without KDE Connect; KDE-only must
have its own compatible streaming implementation without Notes. If both are
installed, use one explicitly selected source, not both. If neither supported
provider is installed, report that one supported phone component is needed;
never install/download another app silently. Merely having stock KDE Connect
installed is currently insufficient and must not be presented as KDE-only webcam
support. A compatible KDE extension is still implementation/distribution work,
not an already available optional plugin install.

## Provider selection and authority

Native adapters must authenticate actual streaming offers from the original paired
channel. Offer metadata includes an opaque explicitly associated phone binding,
paired-peer binding, original channel nonce, capability revision and actual AV
profiles. Names, manifest permissions or two nearby phones cannot establish a
common phone binding. Only an opaque choice digest goes to the renderer.

Explicit Notes/KDE choices never silently fall through to the other app. Auto
prefers Notes when its real provider supports the requested video AND audio;
only when Notes is absent/unsupported may it select a genuinely supported KDE
provider **before starting**. KDE alone must actually provide streaming, not just
declare camera/microphone permissions.
Once START is claimed, pending/denied consent, disconnect or failure does not
authorize starting the other app. Only one provider may capture for a session.
The selected original offer is pinned and failure is sticky; later matching
metadata or an old channel returning cannot revive that context. Metadata and
one-use START selection are not actual Android camera/microphone authority.

## Initial AV profile

* Video: I420 / YU12, 640×480, 15 fps, 460800 bytes per complete frame.
* Audio by default: signed PCM16 little-endian, 48000 Hz, mono, 960 samples /
  1920 bytes per 20-ms packet. No implicit video-only fallback.
* Muting must be explicit. A muted session must not open microphone capture or
  accept incoming audio. Unmuting needs fresh actual microphone consent.
* Both tracks use one session identity and monotonic microsecond PTS timebase.
  Per-track sequences start at zero. Replay, gaps/backwards timestamps or more
  than 250 ms track divergence retire both outputs. Native scheduling/real
  capture AV synchrony still needs actual device acceptance.

## Dedicated binary channel

Never carry live frames through document/task JSON or file-offer histories.
The dedicated connected socket must be admitted by the original authenticated
control channel after genuine current Android capture consent. No listener or
approval bypass is created by the transport module. Each start/reconnect needs
a new random 32-byte secret and new 16-byte session identity. Never recreate
a codec with the same secret/session to reset its counters.

HKDF-SHA256 derives 36 bytes from the secret, salt = raw 16-byte session identity,
info = ASCII `magnolie-phone-webcam/1\0phone_to_desktop\0`. Bytes 0..31 are the
AES-256-GCM key; 32..35 are the nonce prefix. The nonce is prefix + unsigned
big-endian 64-bit global packet sequence. Global sequence starts at zero, with
mandatory retirement before `2^63-1`. AAD is info + session identity + header.

Header: big-endian ciphertext length (uint32), global sequence (uint64).
Encrypted body: version 1 (uint8), video=1/audio=2 (uint8), per-track sequence
(uint64, at most `2^63-1`), PTS microseconds (uint64, at most `2^53-1`), followed
by the exact profile's bytes. The ciphertext includes the 16-byte GCM tag.
Maximum ciphertext is 460834 bytes. Refuse invalid lengths/counters before
allocating or reading their payload. Recheck original authority during bounded
socket IO, with a two-second absolute per-frame deadline; no retries/reconnects
after rejection, timeout or EOF. Never queue unbounded frames.

Interoperability fixtures (synthetic keys/data, never production authority):
session hex = 32 `a` characters; secret bytes = 0..31. First encode audio packet
0, PTS 0, payload `12 34` repeated 960 times: wire length 1966, SHA256
`ac07c1baeaea58c00f70d794813f653e1409f865dc7363ecba9703612d0707e0`.
Then video packet 0, PTS 66667, all-zero 460800-byte payload: wire length 460846,
SHA256 `8b253d9e1bf3129a3b7e3a1caa5aac9316cf9dc8a7348a71aca8e9c3f8ccaee3`.
Desktop AEAD/socket tests and the actual Android-source JVM codec tests verify
these independently. They do not request permissions or capture personal media.

## Linux native-output boundary

Native `sizeimage` is a buffer allocation, not always the I420 payload length
(Refs #523). Accept only the exact 460800-byte payload or its exact rounding to
the current native page size; geometry, YU12, field and 640-byte stride stay exact.
Writes and wire frames remain 460800 bytes, with no appended stale/padding bytes.
The actual v4l2loopback0.13.2/kernel6.14 host returned allocation462848 with
otherwise exact 640×480 I420. A user-approved temporary test subsequently captured
30 complete generated I420 frames through an independent ffmpeg V4L2 client and
151680 PCM samples from the exact owned microphone through parec. Every captured
video payload matched generated frames/blank, without treating allocation padding
as image content. Both native outputs were removed, the exact own unused test
module unloaded and the original default microphone preserved. No physical AV,
package install or permanent autoload configuration was involved. This proves
these native PC backend paths, not phone/OBS synchronization or Windows endpoints.

Capture requires a provisioned writable v4l2loopback output node. Only explicit
Enable/prepare may perform the bounded driver setup described above; startup,
status and capture do not install packages or load drivers. Refuse physical camera drivers, substituted
formats/rates and missing timeout controls. Request the exact native I420 output
format and frame rate, a one-second kernel frame timeout and no indefinite frame
sustain. Stop writes a black frame when possible and closes the output; kernel
timeout also covers abrupt producer death. Native V4L2 behavior has so far been
tested through the ioctl adapter boundary, not an installed loopback/OBS run.

An owned private FIFO feeds a real PulseAudio/PipeWire `module-pipe-source`
microphone source under the same session identity. Never change default inputs.
Check actual advertised PCM format. Refuse audio backpressure/partial writes
instead of silently dropping audio. Drop only complete video frames on EAGAIN.
Native adapters must still be validated on actual audio-server/driver versions.
The initial CLI ownership check was replaced with one persistent original native
libpulse connection for load, exact source-format inspection and unload. No
automatic reconnect or historical module-index reuse on another server is allowed.
The library is loaded only on explicit use; a missing library/server fails only
this feature, without autospawning an audio daemon. A server loss/unconfirmed
module load/unload is reported as failed/shutdown-pending, never as a clean stop
or permission to guess a module ID. Native event loops/contexts are retired even
on these errors. Successful actual module removal and fault behavior still need
native source/device acceptance. A read-only native ABI/connection probe is not
proof of source creation, audio delivery or cleanup.

A subsequent bounded native Linux test did create the owned microphone source,
read 38400 bytes through a normal external PulseAudio capture client, verify
generated nonzero PCM samples, and confirm the original module unload. A separate
read-only check found zero remaining Magnolie virtual sources. Only the newly
created virtual source was read; no physical microphone/camera was opened.
This is a native microphone-backend proof, not phone AV/OBS acceptance.

That probe also exposed module acknowledgement before source export on startup.
Source readiness now waits at most three seconds for the exact newly owned source
on the same original native connection, and retries only PA_ERR_NOENTITY. Wrong
identity/format/permission and connection loss still fail; there is no reload,
reconnect or fallback. Initial data-arrival timing begins after both native
endpoints are ready, while the caller's original permission/deadline guard remains
unchanged. The affected desktop tests cover these readiness/timeout boundaries.

A common lifetime monitor retires both outputs on original-authority loss,
missing initial tracks (two seconds), or track inactivity (500 ms). The joined
receiver closes the actual media socket when outputs retire, and retires outputs
on socket failure/disconnect. Explicit stop waits for the original worker's end;
there is no restart/recovery from history. Stream activity is not proof that OBS
is consuming the camera; the requested tray indicator must use genuine native
consumer activity rather than a mere connection or output stream.

Linux output pacing now uses one original local monotonic anchor for both tracks
(Refs #521). The first accepted PTS establishes the anchor once; later packets
retain their relative presentation times instead of all being passed immediately
to the native adapters after a network burst. Subtract integer PTS before float
conversion so large valid timestamp values retain sub-second spacing. No detached
playback queue, copied frame backlog, per-track re-anchoring or audio drops are
introduced. One serialized packet waits in at most 10-ms steps, with original
guards/lifetime checks and no held native-state lock during waits. Close can wake
that original wait immediately. More than 250 ms ahead/late, a backwards/nonfinite
clock or a bounded wait that cannot progress retires both outputs. Existing
per-track sequence/PTS and cross-track divergence checks remain in force.

Controlled clock/adapter tests and the actual encrypted receiver exercise this
software pacing. A real-monotonic-clock probe with controlled adapters observes
the expected 20-ms packet spacing; it is NOT a native audio playback, video
presentation or OBS lip-sync proof. PulseAudio/PipeWire/driver latency, underruns
and actual phone AV synchronization remain #503 native acceptance. Windows does
not yet have native AV endpoints; these pacing semantics are an implementation
reference, not a claimed Windows/Notes/KDE fix.

## Remaining acceptance

Implement both provider adapters without fabricated capabilities or shared app
permissions, genuine Android permission/foreground capture lifecycle, native
original-channel control/start/stop, original-context UI, native Windows camera
and audio endpoints, and observed consumer state. Then prove actual video plus
matching audible audio in OBS/other capture software, and stop/denial/revocation/
disconnect/process-death behavior on supported OS/driver/device versions. Physical
Android acceptance remains subject to the existing #423 pause. Build opt-in stays
separate from photo sync and defaults OFF for an unconfigured desktop self-build.
