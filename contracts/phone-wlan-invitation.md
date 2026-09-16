# Desktop-initiated WLAN first pairing

This additive discovery mechanism does not authenticate a device. Trust still
comes exclusively from the existing `magnolie-phone/1` pairing transcript,
matching-code confirmation on both devices, confirmation/finish proofs, and the
pinned forward-secret session. Existing phone-initiated clients remain compatible.
Bluetooth first pairing and daemon setup IPC are outside this unit.

## User flow

1. Enable the phone connection and leave the Android phone connection screen open.
   The screen advertises a temporary `_magnolie-invite._tcp.local.` NSD service.
2. Click WLAN Connect in Linux or Windows setup and explicitly select the phone.
   Setup discovers services, not authenticated peers. It refuses to replace an
   existing telephone pairing.
3. Android displays a native Compose confirmation using the existing localized
   phone title, `Connect to %1$s`, and Cancel labels. No handshake starts before
   accepting this invitation.
4. Android connects to the invitation TCP socket's actual source IPv4 address on
   port 8741, binding the outgoing pairing connection to the invitation's local
   interface. Neither a URL nor an advertised callback host is accepted.
5. Both users compare and confirm the unchanged telephone verification code.
   Android checks that the actual desktop device ID equals the invited ID.
   Desktop checks the selected phone ID, source address and scoped pairing token.
6. The existing pinned secure session reconnects. Setup returns authenticated
   connected status only after the selected peer is online over WLAN. The own-phone
   flag is set only when explicitly checked on the PC confirmation, after that
   authenticated result. No additional grant APIs are called.

The Linux callback is `SetupPhoneServices.connect("wifi", prompt)`, using
`_connect_wifi`. Windows uses `FirstRunSetupPhoneServices.ConnectAsync("wifi", ...)`.
The pre-existing daemon ownership refusal remains in effect, so this unit does
not steal daemon-owned transports or start duplicate listeners.

## Wire contract

NSD TXT fields are exactly `v=1`, `id=<phone UUID>`, `name=<display name>`, and
`nonce=<canonical Base64, 16 random bytes>`. The NSD port is the temporary TCP
invitation receiver, not the existing telephone listener. Windows obtains the
invitation address from the mDNS packet source; Linux resolves the NSD service.
Both limit candidates to local IPv4 private/link-local addresses. IPv6-only
invitation discovery is not implemented; existing protocol transports are unchanged.

The invitation and acknowledgement use the existing length-prefixed JSON framing,
with a 2048-byte maximum and exact schemas:

```json
{
  "p": "magnolie-phone-invite/1",
  "type": "offer",
  "target": "<selected phone UUID>",
  "nonce": "<phone's current availability nonce>",
  "device_id": "<desktop UUID>",
  "name": "<desktop display name>",
  "token": "<public scoped telephone pairing token>",
  "port": 8741,
  "ttl": 60
}
```

```json
{"p":"magnolie-phone-invite/1","type":"accepted","nonce":"<same nonce>"}
```

The token is the existing public pairing-window cookie, not a credential or proof
of trust. The acknowledgement means only that Android's user accepted an invitation.
No keys, passwords, grants or own-device flags are transmitted in these frames.

## Bounds and cancellation

- Availability lasts at most 120 seconds and only while the screen is active.
  Leaving/backgrounding the screen closes the receiver. Retrying is explicit.
- At most eight accepted TCP sockets, one worker and one pending invitation per
  availability window. A complete unauthenticated frame must arrive within two
  seconds, including slow trickle senders.
- A valid invitation consumes the nonce even on rejection, disconnect or expiry.
  Its consent window is at most 60 seconds, measured on Android's monotonic clock
  and capped by the remaining availability window. Extra frames abort the request.
- Closing the PC invitation socket clears the pending phone prompt. Acceptance
  after expiry cannot start a callback. A new availability window uses a new nonce.
- Loopback, unspecified, multicast and public callback addresses, arbitrary URL/host
  fields, noncanonical nonces/IDs, unexpected ports/TTLs, control/bidi formatting
  in names, and oversized/duplicate-key frames are rejected. Compose Text renders
  names as text, not HTML.
- The desktop pairing window is scoped to the selected phone and expires after
  120 seconds. Cancel interrupts only that setup pairing's pending work. Completed
  explicitly confirmed relationships remain retained, as in existing setup.
- Windows mDNS collection is limited to four seconds, 256 datagrams, 64 partial
  records and 16 returned phones. Linux resolves at most 16 service names over a
  four-second discovery window.

## Validation and reproduction

`TelefonWlanInvitationTest` runs the actual Android `TelefonWerk` pairing client
and encrypted session, not a reimplementation of its handshake. It starts the
real Linux or Windows setup adapter in an isolated fixture process, publishes NSD
records over real multicast, accepts the actual TCP invitation, compares the two
displayed codes, explicitly confirms them, then requires the setup adapter's
authenticated online result. JVM Keystore material is supplied by a test-only
in-memory provider; production framing, crypto, persistence and transport code run
unchanged. No production profile, signing key or physical phone is accessed.

Network integration tests require explicit `MAGNOLIE_WLAN_INTEGRATION=1`, an
available IPv4 LAN interface, a free fixture telephone port 8741, Python zeroconf,
and the built sibling Windows CoreTests. Ordinary unit runs do not initiate these
LAN integrations. The test fixture's NSD publication is restricted to the default
route's local IPv4 interface, avoiding host Docker NAT source rewriting.

```sh
dotnet build tests/CoreTests.csproj --no-restore
MAGNOLIE_WLAN_INTEGRATION=1 dotnet run --project tests/CoreTests.csproj --no-build -- "Telefon WLAN"
```

From the Android project, with the installed SDK and Python dependencies available:

```sh
MAGNOLIE_WLAN_INTEGRATION=1 ./gradlew :app:testDebugUnitTest --tests '*TelefonWlanInvitationTest'
```

From the Linux project:

```sh
python3 -m pytest pruefungen/test_phone_invitation.py pruefungen/test_telefon.py pruefungen/test_setup_services.py
```

Fresh local runs completed both setup adapters' full pairing/secure-session flows,
Android invitation cancellation/expiry/resource-budget tests, and desktop real-TCP
wrong-target/source, expired/cancelled/replayed-token and existing-peer tests.
The native Windows WLAN adversarial TCP/API group also passed via SSH as `maik3`.
The full Windows-target production project compiled with zero errors/warnings.

A separate cross-machine native Windows attempt successfully discovered and
selected the owned JVM phone fixture, but TCP connect to its ephemeral invitation
endpoint on `192.168.178.43` timed out with Windows socket error 10060. No firewall
or network permissions were changed. That external cross-machine reachability
gate, Android native NSD/Compose instrumentation, and physical handset validation
are not certified by the successful same-host tests. No validation APK was signed
or installed in this unit.

## Packaging and localization

Android's new `TelefonEinladung.kt` and `TelefonEinladungsDialog.kt` are included
automatically by the existing Android source set. Windows includes the new
`TelefonInvitation.cs` through SDK compile globbing; CoreTests explicitly links it
and the actual setup adapter. Linux changes stay in the already-installed
`magnolie_telefon.py` and `magnolie_setup_state.py`; zeroconf is already a declared
Debian/RPM/Flatpak/AppImage dependency. No production packaging manifest changes
are required. The new fixture host script is test-only.

No new visible Android string keys or desktop gettext msgids were introduced.
Existing translated phone title/connect/cancel/search strings are reused. KDE's
selected-device path, catalogs, release files and general data/sync code are not
changed by this WLAN unit.
