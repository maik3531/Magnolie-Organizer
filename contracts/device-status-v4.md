# Device Status v4: Ephemeral Own-Phone Identifiers

The existing 11 capability names and 10 grant names are unchanged. Desktop
`device_status` supports versions 1, 2, 3, 4. Android advertises version 4 only
while the separate, initially disabled identifier-sharing switch is enabled for
the locally owned peer and phone-number permission remains granted. Removing
version 4 revokes identifier sharing, not ordinary device status. The v1-v3
request/report field sets and their canonical serialization remain unchanged.

## Wire Contract

A v4 request has exactly `request_id` (canonical nonzero UUID), `version` (integer
4), and `include_identifiers` (JSON boolean). Its maximum lifetime is 60 seconds.
Only an explicit request over the authenticated encrypted phone channel can
produce a v4 report. No identifier requests or responses enter durable outboxes.

A v4 report has every v3 field plus exactly `version: 4` and `identifiers`.
`identifiers` has exactly `phone_number`, `serial`, and `imei`. Each has exactly
`status` and `value`. Status is one of:

- `available`: a nonempty string returned by a permitted public Android API.
- `not_shared`: request explicitly sets `include_identifiers` to false.
- `permission_missing`: the eligible API permission is absent or access throws a security exception.
- `os_restricted`: ordinary applications cannot access the identifier on this OS.
- `no_subscription`: no valid default voice subscription was selected.
- `unavailable`: the API returns no usable value, an unknown placeholder, or fails.

All non-available values are empty strings. Maximum lengths are 64 characters
for the phone number, 128 for the serial, and 32 for IMEI. Control characters
are forbidden. IMEI is a digit string, never a JSON number; leading zeros survive.
Fields have independent statuses. No value is inferred or invented.

## Android Collection

The separate provider is not called by ordinary status or incoming-call battery
collection. Both peers must mark the pairing as their own device and grant
`device_status`; Android additionally requires the separate opt-in. An ordinary
ownership checkbox does not enable this opt-in, including existing installations.

The number comes only from `getDefaultVoiceSubscriptionId()`. On API 33+ use
`SubscriptionManager.getPhoneNumber(id)`; on API 26-32 use
`TelephonyManager.createForSubscriptionId(id).getLine1Number()`. There is no
first-SIM fallback. `READ_PHONE_NUMBERS` is requested only from the new switch's
user action, through a separate permission launcher with a peer/epoch ticket.

Serial and IMEI use public APIs only on API 26-28 with an already granted
`READ_PHONE_STATE`. This feature does not request that permission or any role
to obtain hardware IDs. API 29+ reports `os_restricted` for these fields in this
ordinary application. No privileged permission, role escalation, shell property,
ADB query, contact lookup, or manual value substitution is used.

## Lifetime and Storage

Desktop acceptance requires an in-memory matching request for the same paired
key and current authenticated connection, current bilateral ownership/grants,
negotiated v4, and an unexpired 60-second request. Unsolicited, replayed, late,
or changed-peer reports do not populate the display. Responses expire in at most
60 seconds. Android captures consent epoch and permission state and checks them
again immediately before encrypted transmission. There is no identifier retry
queue. Revoked permission masks cannot silently revive after process restart.

Identifier values live in separate transient maps, never the ordinary status
cache, application data, backups, durable inboxes, durable queues, or logs.
Windows `status-cache.json` and its recoverable copies receive only stripped
ordinary status. Storage boundary sanitization also covers direct callers and
rejected unsolicited Android status messages. Linux background IPC retains only
the expiry/reference metadata and rechecks the current transient map and consent
before delivering an event. Closing the device dialog drops its frontend map.

The native GTK and Windows UI queues also retain only status references, not
identifier values. Immediately before JavaScript dispatch, the host resolves the
reference against current consent, request, identity, connection and expiry.
Linux uses the same-UID `phone_current_identifier_event` lookup for daemon-owned
phones; failed lookup or a locked book returns ordinary status only. Both web
frontends issue their own UUID on open/refresh and require that exact request ID
in the response. The phone wire schema and the v1-v3 field sets remain unchanged.
Rejecting an old/duplicate reply or resolving an old UI reference does not consume
a newer pending request or erase its accepted result. Revocation, identity and
connection changes still invalidate authorization independently of these lookups.

Ownership removal, unpairing, sharing removal, permission revocation, connection
replacement/closure, and capability/grant updates invalidate pending state.
Frontend fields are hidden unless local ownership is checked, render with
`textContent`, and expire independently of ordinary status. The peer cannot
erase information already seen or copied by another party; a disconnected peer
cannot receive revocation faster than transport detection/the 60-second limit.

## Verification Scope

Synthetic tests exercise API 28/29/33 provider decisions, false requests, denied
access, missing default subscription, leading zeros, exact fields, unmatched and
late reports, changed peers/connections, ownership/grant revocation, encrypted
framing, and durable-cache/queue exclusion. No real telephone or user profile
is queried. Carrier provisioning, dual-SIM/eSIM default-voice behavior, OEM
permission handling and actual physical-device transport remain hardware checks.

## Verification Record (2026-09-13)

- Linux protocol, identifier, background-daemon and 20-language resource checks:
  93 passed with `python3 -m pytest -q tools/test_device_identifier_locales.py
  magnolie-organizer-2.0.0/pruefungen/test_device_identifiers.py
  magnolie-organizer-2.0.0/pruefungen/test_telefon.py
  magnolie-organizer-2.0.0/pruefungen/test_hintergrunddienst.py`.
- Android: 39 tests, zero failures/skips. `:app:testDebugUnitTest` selected
  `*DeviceIdentifier*Test`, `*TelefonProtokollTest`, `*TelefonSitzungTest`,
  `*TelefonQueueDatabaseTest`, and `*TelefonTrennungTest`. Nine consent-flow
  cases ran under Robolectric API 28, 29 and 33. MainActivity and all Android
  resources compiled. Gradle ran offline, sequentially under
  `/tmp/opencode/android-build.lock`, with two CPUs and a 6 GiB memory limit.
- Windows portable native tests: the `Telefonverbindung` CoreTests group passed,
  including `DeviceIdentifierTests`, existing crypto/pairing/contracts and the
  group's personal-sync regressions. This is not an installed Windows GUI test.
- Both actual frontend rendering functions passed
  `Magnolie-Organizer-Windows-2.0.0/tests/device-identifiers.js` using Bun's Node
  compatibility, including changed peer keys, false ownership, expired results,
  capability changes and leading-zero strings. This is a synthetic DOM test,
  not an installed WebView/WebKit screenshot test.
- Ten new strings have manually authored translations in all 20 languages,
  checked against both PO trees, Windows native strings and Android resources.

No real device identifiers were queried, no production profile was opened, and
no VM, emulator, release signing, publishing or deployment was performed.
