# Phone webcam: two capture providers, one native AV backend (Refs #244)

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
runtime readiness. Neither a Windows native adapter nor its acceptance is claimed.

#### Windows dedicated binary receiver (Refs #503)

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
These are .NET tests on the Linux host, not native Windows endpoint acceptance.
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

Requires an already provisioned writable v4l2loopback output node; never install
or load drivers automatically. Refuse physical camera drivers, substituted
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

## Remaining acceptance

Implement both provider adapters without fabricated capabilities or shared app
permissions, genuine Android permission/foreground capture lifecycle, native
original-channel control/start/stop, original-context UI, native Windows camera
and audio endpoints, and observed consumer state. Then prove actual video plus
matching audible audio in OBS/other capture software, and stop/denial/revocation/
disconnect/process-death behavior on supported OS/driver/device versions. Physical
Android acceptance remains subject to the existing #423 pause. Build opt-in stays
separate from photo sync and defaults OFF for an unconfigured desktop self-build.
