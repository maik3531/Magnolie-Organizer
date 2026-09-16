# Requested Windows hands-free audio — feasibility record

Research date: 2026-09-14. Status: **requested, not implemented; current Windows
Win32 deployment remains unsupported for automatic PC call audio**.

## Requested behavior

Use the already authorized, OS-paired own phone as the remote HFP Audio Gateway,
with the PC in the Hands-Free role and the PC microphone/speakers carrying the
current call. Preserve the explicit persisted opt-out. Bind observations and
actions to the authenticated phone, current call ID and session. A radio, RFCOMM
connection or successful API invocation alone is not an active audio route.

No new driver, keyboard/UI automation, guessed audio routing or substituted
microphone loopback is a proposed implementation.

## Documented OS candidate

Microsoft documents `Windows.ApplicationModel.Calls.PhoneLineTransportDevice` for
Bluetooth devices associated with a `PhoneLine`. It exposes registration,
`RequestAccessAsync`, `ConnectAsync`, and audio-routing state/events. This is a
credible OS-managed candidate for a future adapter using the installed Windows
stack, not proof that the current application can use it.

- `PhoneLineTransportDevice` begins in CallsPhoneContract v5 (Windows 10 1903).
- `RequestAccessAsync` and `ConnectAsync` explicitly list the
  `phoneLineTransportManagement` capability. The former returns an actual
  `DeviceAccessStatus`; access may be denied.
- `AudioRoutingStatus` is read-only, begins in CallsPhoneContract v6, and lists
  `phoneCall` as its capability. A future adapter must inspect the requirements of
  each operation, not infer all requirements from class presence.
- The app must separately establish and observe actual call audio. A successful
  transport connection is insufficient to advertise audible bidirectional audio.

**Packaging/approval distinction:** Microsoft's capability reference, updated
2026-09-08, says restricted capabilities require approval for Microsoft Store
submission, but Store approval is not required merely to sideload a package that
declares them. It also distinguishes full-trust packaged desktop apps from
AppContainer apps: not every AppContainer capability requirement automatically
applies to every full-trust operation. The method-specific requirements and
actual access result still need validation. The existing implementation's
`approved_capability=false` is not evidence that all driver-free future Windows
implementations are impossible or that Store approval is universal.

There is presently **no verified, documented permission-/declaration-free path**
for this application's requested phone-HF scenario. No manifest capability,
package identity, device registration or access prompt was added in this pass.
Package identity alone would not implement the missing routing adapter.

## Why the other inspected APIs do not close this feature

- `AudioPlaybackConnection` uses the OS **A2DP sink** to play remote media on the
  PC. It does not provide the microphone uplink or cellular-call controls required
  for hands-free calling. It must not be presented as HFP support.
- The Windows Classic Audio endpoint documentation describes HFP headset audio:
  opening a headset input or a communications output can select HFP. That is not
  evidence that a remote phone Audio Gateway can be used as a desktop headset;
  the local/remote roles and endpoints must match the requested direction.
- `BluetoothSetServiceState` enables/disables service-driver mappings; Microsoft
  documents that it installs/removes the corresponding device driver. It is not
  a scoped current-call audio routing API and does not satisfy the requested
  no-new-driver approach.

## Work remaining before an implementation decision

1. On a future authorized Windows-only fixture/prototype, inspect the actual
   packaged/full-trust access boundary and required declarations. Keep capability
   reporting separate from implementation availability.
2. With a real phone available, prove exact device binding, local HF/remote AG,
   actual duplex route/status, denied-access handling, disconnect/reconnect, shared
   OS ownership and cleanup. Neither this Linux-host research nor source
   compilation can establish these physical facts.
3. Only after those results, implement a small native adapter with bounded calls
   and explicit lifecycle ownership. Keep Android/native logical call actions
   independent from audio selection. This does not require a Qt rewrite.

## Primary sources checked

- [PhoneLineTransportDevice](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice?view=winrt-26100)
- [RequestAccessAsync](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice.requestaccessasync?view=winrt-26100)
- [ConnectAsync](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice.connectasync?view=winrt-26100)
- [AudioRoutingStatus](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice.audioroutingstatus?view=winrt-26100)
- [App capability declarations](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/app-capability-declarations)
- [Remote Bluetooth audio playback / A2DP sink](https://learn.microsoft.com/en-us/windows/apps/develop/media-playback/enable-remote-audio-playback)
- [Windows Bluetooth Classic Audio](https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/bluetooth-classic-audio)
- [BluetoothSetServiceState](https://learn.microsoft.com/en-us/windows/win32/api/bluetoothapis/nf-bluetoothapis-bluetoothsetservicestate)
