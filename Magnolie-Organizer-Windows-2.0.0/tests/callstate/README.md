# Delayed Callback Probe

Run `taskset -c 0,1 python3 -B tests/callstate/DelayedCallbacks.py` from the Windows
source directory. The current test environment SDK is
`/tmp/opencode/fivefixnative/dotnet/dotnet`. Generated compilation files go to
`/tmp/opencode/v1-v4-probe`; synthetic stores are removed after the run.

The driver links current portable product sources and extracts the current
`MainForm.TrackIncomingCall`, `ShowIncomingCall`, and `SendAsync` methods unchanged.
`Framework.cs` supplies capture-only UI, notification, timer, and WebView objects.
The actual KDE backend sends only into an overridden capture `SslStream`, without
constructing a listener or starting discovery. Actual phone commands use an
in-memory stream, not a device. Peer IDs, keys, caller data and messages are dummy.

Covered boundaries: actual bridge parsing requires the SMS device/key and status
request ID and rejects missing/unknown fields; expected SMS device/key and digest journal; delayed identifier
dispatch after ownership/capability/key/expiry/reopen/new-request/disconnect changes;
queued ringing/idle coalescing, current-state withdrawal, real command serialization
to a capture stream and one-shot sibling rejection. A real-thread overlap holds
the generation lock, lets an older callback wait, then presents a newer call;
the older callback must recheck authority under that lock and leave it intact.
The separate
`device-identifiers.js` tests request matching in the actual frontend renderer.

This is not native WinForms, WebView2, Toast, Windows activation, Windows HFP, or
physical call/SMS verification. `CallstateProbe.csproj` is the smaller pure ticket
test and intentionally does not compile these framework fakes.
