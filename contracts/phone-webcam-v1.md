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
and an Android sender codec exist. Neither Android capture provider, authenticated
start/control integration, Organizer controls nor Windows native outputs have been
completed. No streaming capability is advertised by this unjoined backend.
No installed OBS/phone capture acceptance or package delivery is claimed.

### Native Notes capture implementation, not yet activated

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
from the background. There is still no authenticated production start route or
advertised provider, so this is not yet a usable phone webcam.
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
consent or physical acceptance. No authenticated control start/key exchange,
Organizer activation, native device-success or OBS acceptance is claimed here.

## Authenticated control exchange under implementation

Reserved desktop discovery version **24** is distinct from file versions 21/22
and capability 23. It is NOT advertised yet. The existing capability key set is
strict and Notes already has 16 versions when all current handlers are enabled;
adding a seventeenth would break old peers. The compatible design therefore uses
desktop-only discovery followed by a fresh phone-initiated probe on that same
authenticated parent. Never send extension controls to an unproven older peer.

The matching Notes/Python schema uses small `device_status.request/report` v24
controls: probe, offer/unavailable, prepared, send, stop/error. Offers bind the
fresh UUID/nonce, new session/key, numeric dedicated port, explicit mute and camera
choice; URLs, AV payloads, permission flags and extra fields are rejected. JSON
here carries control/key negotiation only, never frames or audio. The Notes
envelope has a 4096-byte/60-second bound. Python currently validates the body;
its production envelope/parent dispatcher is not installed yet.

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
the added optional module remains covered by the 20 composition cases. This is
not yet the Linux Organizer's actual authenticated message/UI dispatch path and
does not add Windows native outputs. The encrypted AV test is not a new proof of
encrypted parent control negotiation: that callback's production binding remains
to be wired and checked.

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
it does not prove a physical phone. The exchange is not yet attached to
TelefonWerk's actual authenticated dispatcher or Organizer activation. The desktop
controller above supplies output-ready integration, but its base dispatcher is
still unjoined. No new capture/control availability is advertised.

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
