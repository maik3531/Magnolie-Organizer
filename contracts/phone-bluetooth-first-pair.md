# First-time Bluetooth phone setup

No prior Magnolie WLAN relationship is needed. Daemon setup IPC is deliberately
not changed; the existing Linux daemon-ownership refusal remains in force.

## Flow and ownership

1. Enable the phone connection and open its Android screen. Choose **Pair a new
   Organizer over Bluetooth**. Android requests only Bluetooth connect/advertise
   permissions and invokes the native discoverability confirmation for 120 seconds.
2. PC setup discovers Bluetooth devices and requires selection. Windows reloads
   the exact selected association endpoint, verifies its MAC and uses native
   `DeviceInformation.Pairing.PairAsync(EncryptionAndAuthentication)` if needed.
   Linux calls BlueZ `Device1.Pair` for the selected object path, with an owned
   DisplayYesNo agent and native setup confirmation. Android's OS confirmation is
   not bypassed. Existing OS bonds are retained; no Trusted property is set.
3. The PC connects outward to the existing telephone SDP UUID:
   `7b1d9e2a-5c43-4f68-a172-9d30e6b4c851`.
   Windows resolves that service on the selected BluetoothDevice. Linux registers
   a scoped **client** Profile1 and asks BlueZ ConnectProfile to resolve SDP and
   hand over the connected RFCOMM fd. No fixed RFCOMM channel or optional PyBluez
   module is needed. Agent/Profile callbacks verify BlueZ's unique bus owner and
   the selected device path. Each registration has its own GLib context, so an
   established phone service does not depend on a visible GTK window.
4. Android's secure RFCOMM listener accepts only OS-bonded links. A public nonce
   and phone UUID precede the application invitation. Android asks its user to
   connect; accepting transfers that same duplex stream to TelefonWerk's existing
   phone-side pairing state machine.
5. Both sides display and explicitly confirm the existing matching code. X25519,
   transcript construction, confirmation/finish HMACs, framing and encrypted
   session negotiation are unchanged. Names, SDP, MACs, OS bonding and invitation
   acknowledgements are never accepted as application identity proofs.
6. After pairing finishes, the first stream closes. The PC reconnects; Android
   initiates the existing pinned forward-secret session over the newly accepted
   stream. Only this authenticated online Bluetooth status completes setup.
   The optional own-phone checkbox is applied only after that result. No contacts,
   microphone, notifications, dial or personal-data permission is added by setup.

## Normal reconnect and fallback

- Linux retains its existing outgoing Bluetooth fallback loop, timing policy and
  WLAN preference. It now uses BlueZ's native connected-fd profile adapter.
- Windows persists the selected MAC with the encrypted, code-confirmed peer or
  pending-commit record and reconnects outward for those explicitly configured
  peers. A pending route only retries the existing finish proof; it cannot bypass
  commit validation or authenticate a session early. It checks both the connected MAC
  and expected protocol peer ID. The existing Windows RFCOMM server remains for
  legacy Android-initiated connections; peers without the new address setting do
  not silently acquire an outgoing transport. Explicit unpair or pending-record
  expiry removes the route with its record.
- Android persists `bluetooth_inbound` with the encrypted peer. Its default is
  false for shipped outgoing-role peers. The server is restored for enabled known
  peers, while WLAN remains preferred. A pending finish can be retried on an
  accepted Bluetooth stream; only a subsequent authenticated session verifies it.
- The deliberately selected initial Bluetooth session is protected from incidental
  WLAN callbacks within its bounded setup window. After that session ends, normal
  WLAN discovery/preference resumes, including for a Bluetooth-first peer whose
  WLAN host address has not yet been learned.
- For a legacy WLAN-paired relationship without a Bluetooth address, the phone's
  existing paired-device selector opens a bounded, exact-MAC binding intent. An
  incoming BlueZ connection may bind that selected address only after proving the
  existing pinned key. This does not replace the relationship or trust OS bonding.
- A Linux first-session issue was corrected: newly paired remote grants start at
  revision 0 with no permissions, not at an invented revision 1. The first actual
  authenticated grant update is therefore accepted rather than forcing a retry.

## Public invitation frames

All frames use the existing length-prefixed JSON codec, with a 2048-byte limit for
this pre-authentication exchange. The availability frame is exactly:

```json
{"p":"magnolie-phone-invite/1","type":"bluetooth_available","device_id":"<phone UUID>","nonce":"<16 random bytes, canonical Base64>"}
```

The offer is exactly:

```json
{"p":"magnolie-phone-invite/1","type":"bluetooth_offer","target":"<phone UUID>","nonce":"<same nonce>","device_id":"<desktop UUID>","name":"<display name>","token":"<public scoped pairing token>","ttl":60}
```

While waiting for consent, the PC sends `wait` and Android answers `pending`,
`accepted` or `rejected`. Each control frame has exactly `p`, `type` and `nonce`.
This bounded request/reply exchange detects disconnection without a competing
reader consuming subsequent RFCOMM handshake bytes. There are at most 240 polls,
at 250 ms intervals. No URL, IP, callback port, credential or grant is accepted.

Availability and total pairing resources are bounded to 120 seconds. An offer
must arrive within two seconds; consent is capped at 60 seconds. Nonces are fresh
per stream and cannot be replayed across requests. The setup listener admits at
most eight attempts per window. Unknown fields, malformed identities, wrong MACs,
wrong targets, replayed controls, expiry and cancellation fail closed. Stream
ownership transfers explicitly at acceptance; closing the invitation UI does not
prematurely close the pairing stream now owned by TelefonWerk. Stopping setup
removes only its own listeners, agent/profile registrations and pending streams.
Completed explicitly confirmed relationships remain retained.
Nested pairing streams inherit the earliest deadline. Code expiry clears pending
key material and the code UI. Code-confirmed pending commits retain the existing
bounded finish-retry lifetime; this is not a fresh invitation or session grant.

## Tests

The integration fixtures replace only OS discovery/bonding and the physical
RFCOMM socket with real TCP duplex streams and explicit synthetic MAC metadata.
They run the actual Linux and Windows setup adapters, Android listener/factory,
TelefonWerk pairing state machine, persistence and secure session code. They
compare both displayed codes before confirming, require authenticated Bluetooth
status, break the transport, then require a second authenticated session without
another application pairing or WLAN handshake.

Coverage includes OS denial, wrong connected MAC, phone invitation refusal, PC
code refusal, Android permission denial, expired/replayed invitations, disconnect,
oversized frames, selected-MAC legacy binding, forged confirmation MACs even after
PC approval, wrong pairing target/source,
cancelled/replayed pairing tokens, and no automatic own-device/startup grants.
BlueZ tests execute the real agent/profile adapter against a fake system bus,
including a real duplicated fd exchanging frames in both directions, wrong caller
and device rejection, and exact owned-registration cleanup.

Network integration is explicit, not a default unit-test side effect:

The final current-source runs passed 100 Android telephone tests with both WLAN
and Bluetooth integration enabled, 69 focused Linux tests, and all four portable
C# telephone groups. Windows-target application and portable CoreTests builds
completed with zero warnings/errors. Android reported a deprecated API use in a
Robolectric-only legacy-bond fixture; no test failed or was skipped in that run.

```sh
# Windows source directory, portable protocol runner:
dotnet build tests/CoreTests.csproj
MAGNOLIE_BLUETOOTH_INTEGRATION=1 dotnet run --project tests/CoreTests.csproj --no-build -- "Telefon Bluetooth"

# Android source directory; requires the built sibling CoreTests and Python:
MAGNOLIE_BLUETOOTH_INTEGRATION=1 ./gradlew :app:testDebugUnitTest --tests '*TelefonBluetoothSetupTest'

# Linux source directory:
python3 -m pytest pruefungen/test_phone_bluetooth_setup.py pruefungen/test_telefon.py
```

The Windows-target `--phone-bt-native-probe` performs only read-only inventory.
The actual Windows probe returned:

```json
{"adapter":true,"classic":true,"radios":1,"powered":1,"bondedDeviceCount":1,"pairingApi":true,"rfcommApi":"Windows.Devices.Bluetooth.Rfcomm.RfcommDeviceService"}
```

It does not call PairAsync, RequestAccessAsync, discovery, advertising, radio
switching or a real-device connection. Physical SSP dialogs, OEM discoverability
behavior and radio/SDP interoperability remain hardware validation gates. An AVD
cannot establish those claims. No production phone, production signing key or
APK installation was used for this unit.

## Packaging and strings

New Android Kotlin helpers are included by the existing source set. Windows SDK
compile globbing includes `TelefonBluetoothClient.cs` and
`WindowsTelefonBluetoothClient.cs`; CoreTests links the portable helper and links
WinRT sources only for a Windows target. Linux helpers remain in the already
installed `magnolie_telefon.py` and `magnolie_setup_state.py`. Existing Gio/BlueZ
dependencies are used. No release or packaging catalog changes are required.

Two new Android keys were manually translated in all 20 resource locales:

- `telefon_bluetooth_setup`
- `telefon_bluetooth_setup_hinweis`

The SDP service label and confirmation/permission/cancel labels reuse existing
localized strings. The only additional Android manifest permission is
`BLUETOOTH_ADVERTISE`, explicitly requested together with the existing connect
permission for the discoverability action. No scanning/location/read-data
permission is requested.

New desktop gettext keys for the main owner's translation pass:

- `Wrong Bluetooth device.`
- `Bluetooth system pairing was not confirmed.`
- `Bluetooth device unavailable.`
- `Open the phone connection screen and try again.`

Other setup errors reuse existing gettext keys. Desktop catalogs, KDE selected
pairing, general data/sync code, recurrence and release artifacts were not edited
by this Bluetooth unit.
