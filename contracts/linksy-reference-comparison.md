# Linksy reference comparison — #233

Source review dated **2026-10-27**. This completes the requested source/license,
feature-gap and compatible-extension assessment. Its implementation follow-ups
are #244 (camera/microphone), #245 (screen/second display) and #246 (general
file/photo transfers).

## Source and license baseline

| Component | Immutable source inspected | License/status evidence |
| --- | --- | --- |
| Linksy Linux desktop | [`e2c8970413f8547ff3d85e84b4757e33837b5a22`](https://github.com/LinkSy-mg/linksy-desktop/tree/e2c8970413f8547ff3d85e84b4757e33837b5a22), workspace 0.9.13 | Root [`Cargo.toml`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/Cargo.toml) declares **AGPL-3.0-or-later**; root `LICENSE` contains AGPLv3. `linksy-core` inherits the workspace license. The website's [license page](https://linksy.diary.mg/license) explicitly applies this statement to Linux. |
| Linksy Android | [`3095bbb52badb880d8e8cb037c353a71027f393c`](https://github.com/LinkSy-mg/linksy-mobile/tree/3095bbb52badb880d8e8cb037c353a71027f393c), `pubspec.yaml` 0.2.11+5052 | Public Flutter/Android/Rust source. The complete repository license-file listing contains font licenses, but no root project license; README, pubspec and bridge Cargo metadata do not declare a project-wide license. The embedded desktop core has the license above. Source visibility and an explicit Android-wide license statement are distinct findings. |
| Android's embedded core | [`rust/Cargo.toml`](https://github.com/LinkSy-mg/linksy-mobile/blob/3095bbb52badb880d8e8cb037c353a71027f393c/rust/Cargo.toml) pins `dcd7668e99dbf35fc419bc32744cc84cd1b0ce76` | The phone uses `linksy-core` through `flutter_rust_bridge`, rather than a separately implemented Dart wire protocol. This pin differs from the desktop main revision reviewed above. |
| Relay deployment | [`59e21bed24b2b8c8286b16198e38ffb2b5a7a555`](https://github.com/LinkSy-mg/linksy-server/tree/59e21bed24b2b8c8286b16198e38ffb2b5a7a555) | Public Docker/Compose/TOML deployment of a pinned upstream iroh relay, according to its README. No root license is declared for this deployment repository. Its README still discusses 0.6 as future work, so it is not the current client feature inventory. |
| Magnolie comparison point | [`363813cd`](https://github.com/maik3531/Magnolie-Organizer/tree/363813cd) | Organizer Linux/Windows, Android Notes and their existing native KDE/Notes adapters. Native adapter/test evidence and installed-package acceptance remain separate; the current combined live/package gates are #242/#237/#113. |

The extension designs below use Magnolie's own capability, session and native
adapter contracts. Linksy is an independent protocol: QUIC/TLS 1.3, its own device
certificates, discovery and pairing. It is not a KDE Connect packet provider or
a `magnolie-phone/1` peer.

## Which upstream descriptions are current?

The source pins matter because several upstream descriptions disagree:

- Desktop Cargo is **0.9.13**, while README installation examples still use 0.5.5.
- The website places the Qt frontend in the future. The pinned roadmap records it
  as delivered in 0.8.4, and `crates/linksy-qt` exists.
- The desktop protocol status table describes Android 0.1.16. Its terminal and
  Wi-Fi Direct rows are therefore older than the inspected Android 0.2.11 code.
  The phone now contains `lib/features/terminal/terminal_screen.dart` and
  `lib/app/terminals.dart`.
- The website says self-hosted relay selection is planned. Current desktop
  [`settings.rs`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/crates/linksy-core/src/settings.rs)
  has a validated user `relay` URL, and the Android handoff documents that setting.
  A build with relay code removed remains a roadmap item.
- Wi-Fi Direct has code on both sides and upstream reports support from desktop
  0.9.9 / Android 0.2.9. Its same-channel/router compatibility is still active
  roadmap work; desktop hardware tests in `direct.rs` are explicitly ignored
  without suitable NetworkManager/Wi-Fi hardware. The website's 80 MB/s figure
  is an upstream claim, not a Magnolie measurement.
- The current roadmap explicitly has **no Windows/macOS plans**. The older
  protocol introduction's “come later” sentence is not a platform commitment.

Useful upstream primary sources:

- [Desktop roadmap](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/ROADMAP.md)
- [Wire protocol and feature status](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/docs/protocol.md)
- [Android handoff](https://github.com/LinkSy-mg/linksy-mobile/blob/3095bbb52badb880d8e8cb037c353a71027f393c/docs/android-app.md)
- [Desktop/compositor support](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/docs/desktop-support.md)

## Functional comparison

“Present” below means an identified Magnolie implementation with its adapter or
contract checks, rather than an inference from what KDE Connect in general can
do. Pending installed/personal acceptance is still tracked in #242.

| Area | Linksy reference | Actual Magnolie scope and conclusion |
| --- | --- | --- |
| Discovery, pairing and local encrypted connection | mDNS, six-digit session code/QR, own certificate trust and QUIC streams | Native KDE certificate-pinned pairing and the separate Notes pairing/transport already exist. This is architectural reference, not a missing basic feature. The protocols and pairing identities are different. |
| Notes, tasks, calendars, contacts and own profile | General device-sharing application; the inspected feature inventory is not an encrypted organizer-book synchronization model | Magnolie already has these domain models, source-bound imports, clocks, conflict/deletion handling, protected saves and contacts/profile workflows. File/clipboard sharing does not replace them. Existing implementation/acceptance work remains under #190/#194/#146/#242. |
| Phone status and battery | Battery updates and Ring | Fresh nonce/source-bound Notes `device_status` already supplies battery and richer status. Ring is not in the inspected native Notes capabilities or direct KDE capability advertisement; the official KDE app's general ability is not proof of a Magnolie Ring action. Treat it as an additional basic-device action candidate. |
| Notifications, calls and SMS | Linux protocol/UI has these categories, but current Android source/handoff deliberately omits SMS, notification-listener and phone-control support; call-state pause is distinct | Notes implements optional **read-only selected notifications**, incoming-call state and permission/capability-bound dial/answer/end requests. Native KDE SMS send/history paths exist. Complete communication-tool routing remains #192. Upstream statements about sideloading are not a replacement for Magnolie's actual Android OS/permission checks. |
| Clipboard and links | On-demand text, file clipboard, watched computer clipboard and `open_url` | Native KDE clipboard **reception** has explicit device, confirm/automatic and byte bounds. The direct backend does not advertise a complete bidirectional clipboard/URL service. File clipboard and a dedicated open-on-other-device workflow are additional candidates, not already completed features. Existing receive/routing integration remains #193. |
| General files/folders | Offer/accept offsets, cancellation, BLAKE3 whole-file verification and temporary-file rename | Magnolie has bounded KDE file reception and separate native filesystem browsing. The direct receive limit is currently 50 MiB; notes' verified/missing-range attachment protocol has its own 8 MiB attachment limit. Neither establishes Linksy-style general resumable folder batches. Planned as #246. |
| New-photo import | Per-computer opt-in, selected Android folder, new photos, bounded offers into date folders | Contact/profile photo import and note attachments are different existing features. A selected gallery/photo-folder producer is additional work in #246. |
| Phone files in a desktop file manager | A chosen phone folder, core filesystem protocol and a local WebDAV bridge | Native KDE SFTP/filesystem adapters and Windows explorer integration already exist. Current final WinFsp/SSHFS/Explorer/WLAN acceptance stays in #242; the comparison does not create a second “missing file browser” issue. |
| Media playback and volume | Computer MPRIS players, camera-independent media controls, newer system-volume controls | Native MPRIS/KDE player state, registered/local players and media payload handling already exist. Fresh paired playback/control checks remain #242 and remaining typed actions #193. A computer-wide volume policy or automatic call-to-pause workflow is a narrower integration candidate, not a new playback engine. |
| Mouse, keyboard and slides | Input sessions, screen control, presentation keys | Native scoped KDE input and presenter handling already exist; #149/#153 retain their actual setup/action scope. Full screen streaming is separate. |
| Drawing tablet | Touch/input can accompany a viewed or virtual display | Magnolie already has digitizer/input/Zeichenblatt paths; first/re-pair initialization remains #168. A drawing sheet is not an OS-created second monitor. |
| Screen viewing/control and extra monitor | ScreenCast/RemoteDesktop portals, H.264, virtual/headless outputs with session cleanup | Additional feature family #245. Existing pointer input or the drawing sheet is not evidence of continuous screen capture or a true extra desktop output. Platform/compositor support must be negotiated. |
| Phone camera/microphone as PC devices | Camera2/MediaCodec/AudioRecord; desktop PipeWire and optional V4L2 loopback publication | Additional feature family #244. QR scanning, saved photos, note audio attachments and controlling media playback are not live camera/microphone input devices. |
| Wi-Fi Direct and USB | Android group owner + NetworkManager peer; AOA/UDP bridge | Native Notes WLAN and Bluetooth RFCOMM already exist. Wi-Fi Direct and a general USB/AOA transport are distinct future transport candidates. USB is explicitly still described as hardware-unverified in the handoff and receives further roadmap work. #128 covers current active-transport sync policy, not a completed implementation of these new transports. |
| Internet reachability | Iroh with a seven-day same-network/cable lease, user relay selection and restricted relayed bandwidth | Magnolienbaum already provides its own internet/content-sharing model (#42 retains its pairing scope). This is not a general remote camera/screen/phone link. Linksy's direct/relay path selection is reference for a separately designed transport capability, not a protocol substitution. |
| Locate and proximity lock | Explicit foreground phone location; chosen-device heartbeats can lock the OS session, never unlock it | Native timezone source detection and application/profile lock already exist, but do not establish a phone-location map or proximity-triggered OS lock. These remain optional, separate candidate policies with actual device/session binding. |
| Terminal | Source-backed remote terminal with per-device permission, computer-set code, resize and resume | #153's configured commands and the existing typed MCP tools cover controlled application actions. A persistent general shell is a separate optional feature family, not an automatic consequence of the reference comparison. |
| Languages, service and packaging | GTK/Qt frontends, service, CLI, ten advertised languages and release tooling | Magnolie already has native service/lifecycle, packaging/update, MCP and twenty-language handbook/UI infrastructure. Those are existing strengths rather than new Linksy-derived gaps. |

## Code-level reference mechanisms

1. **Resumable transfers:**
   [`transfer.rs`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/crates/linksy-core/src/transfer.rs)
   explicitly implements per-file accept offsets, a whole-file hash and
   `.linksy-part` staging. This is a concrete mechanism, not just the website's
   “any size” wording.
2. **Media as devices:**
   [`sessions.rs`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/crates/linksyd/src/sessions.rs)
   manages camera/microphone/display sessions;
   [`linksy-screen`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/crates/linksy-screen/src/main.rs)
   publishes incoming video/audio as PipeWire/V4L2 sources. The native device and
   codec dependencies qualify the website's setup/compatibility claims.
3. **Direct-link lifecycle:**
   [`direct.rs`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/crates/linksyd/src/direct.rs)
   uses NetworkManager's WifiP2P device and releases each link. Hardware-specific
   tests and router/channel work remain visible instead of becoming an assumed
   universal speed guarantee.
4. **Bounded away access:**
   [`away.rs`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/crates/linksy-core/src/away.rs)
   declares the seven-day lease. The [relay description](https://linksy.diary.mg/relay)
   distinguishes introductions/small relayed messages from directly transported
   large media. This is connectivity policy rather than organizer-book consent.
5. **Presence lock:**
   [`lock.rs`](https://github.com/LinkSy-mg/linksy-desktop/blob/e2c8970413f8547ff3d85e84b4757e33837b5a22/crates/linksyd/src/lock.rs)
   watches selected devices, locks once per departure and waits for another
   heartbeat before rearming. That policy can be evaluated independently of a
   shell, screen stream or application-profile unlock.

## Magnolie evidence and integration boundaries

- [Actual native KDE packet advertisement](../magnolie-organizer/bin/magnolie_kdeconnect.py):
  `identity_packet`, explicit clipboard/file receive policy, bounded file parser,
  verified contact import and native media/input/filesystem adapters.
- [Windows KDE backend](../magnolie-organizer-windows/KdeConnectDirectBackend.cs),
  [filesystem](../magnolie-organizer-windows/KdeFilesystem.cs),
  [media](../magnolie-organizer-windows/KdeMediaState.cs) and
  [input](../magnolie-organizer-windows/KdeInputState.cs).
- [Actual Notes capability list](../magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonModelle.kt):
  `TelefonCapabilities.phase1`, including status, explicitly optional call/
  notification capabilities, notes/tasks/deletions and Bluetooth RFCOMM.
- [Personal Sync wire limits and attachment validation](../magnolie-organizer/bin/magnolie_personal_sync.py)
  and [existing Notes protocol scope](../magnolie-notes/KONTAKT-PROTOKOLL.md).
- Existing adapter/contract tests include
  [`test_kde_input.py`](../magnolie-organizer/pruefungen/test_kde_input.py),
  [`test_kde_presentation.py`](../magnolie-organizer/pruefungen/test_kde_presentation.py),
  [`test_kde_media.py`](../magnolie-organizer/pruefungen/test_kde_media.py),
  [`test_kde_filesystem.py`](../magnolie-organizer/pruefungen/test_kde_filesystem.py),
  [`KdeContactImportTests.cs`](../magnolie-organizer-windows/tests/KdeContactImportTests.cs)
  and [`ScopedDataRuntimeTest.kt`](../magnolie-notes/app/src/test/java/io/gitlab/maik3531/magnolienotes/telefon/ScopedDataRuntimeTest.kt).
  Their native fixture/readback scope is distinct from personal handset and final
  package acceptance in #242/#237.

## Compatible follow-up plan

The three selected extensions have independent scopes and acceptance criteria:

- **#246 — General resumable batches and selected photo folders.** Reuse native
  destination/device policy and verified-chunk experience while defining a
  general transfer identity, resume/finish protocol and actual file readback.
- **#244 — Camera and microphone input devices.** Negotiate independent media
  capabilities and native Android consent/lifecycle; publish actual Linux/
  Windows device sources with tested native platform support.
- **#245 — Screen and virtual monitor.** Reuse native input handling, define
  explicit view/control/display sessions and verify real portal/output cleanup.

Each design fits the existing key/device/grant/session/source/cancel model and
has its own native readback acceptance. Existing #149/#153/#168/#193/#192 tasks
keep their concrete input, presentation, drawing, routing and communication
scope. The selected enhancements are implementation follow-ups to this comparison,
not assertions of installed support or additional completed release features.
