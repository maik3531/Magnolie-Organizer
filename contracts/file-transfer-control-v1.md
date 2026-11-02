# Dedicated own-peer file controls (integration in #330)

These controls are separate from contacts, Notes/Organizer personal-sync grants,
book SaveACKs and Android media permissions. The native implementations are
present in Linux `magnolie_file_control`, Android `DeviceFileControl` and Windows
`DeviceFileControl`. They do not yet register a transport handler, advertise
support, create settings/keys, prompt for permission or start any worker.

## Compatibility and discovery

Existing applications validate the global capability/grant **key sets exactly**.
Adding a new global key would break older paired peers. Discovery version **21**
is therefore reserved in the existing `device_status.versions` metadata family,
following its established feature-discovery versions. It must remain absent
until the actual native file/control handlers and authority paths are ready.
The `device_status` grant itself is **never file consent**. A peer without this
negotiated discovery version must not be sent new file-control messages. No
existing capability/grant set, pairing or permission is migrated by this work.

## Dedicated body and bounds

Kind: `file_transfer.control`. Maximum complete application envelope: 8192 UTF-8
bytes; maximum lifetime: 60000 ms. The normal authenticated message header and
its exact native sender/receiver/channel checks remain mandatory. The body is:

```json
{
  "format": 1,
  "grant_revision": 3,
  "grant_epoch": "<64 lower-case hex>",
  "send_files": false,
  "receive_files": false,
  "manifest_versions": [1],
  "session_epoch": "<64 lower-case hex>",
  "sequence": 1,
  "echo": null
}
```

No unknown fields, Boolean/string integer aliases or coerced flags are accepted.
Grant revision and session sequence are positive safe JSON integers through
9007199254740991. Supported manifest versions are sorted, unique, 1..65535 and
limited to eight entries. Send/receive directions are independent and initially
off. Remote packet parsing returns wire metadata, **not** a native local grant.
Native local grants must come from protected own-computer policy and its current
native owner; a handler-ready flag is not accepted from the peer.

## Freshness without breaking genuine interrupted-transfer resume

`grant_epoch`/`grant_revision` belong to persistent native consent. Native source,
destination and actual OS access must still be checked independently. A fresh
random `session_epoch` and monotonic `sequence` belong only to the current
authenticated native channel/handler ownership. Native peer ID/public key,
paired/own-computer state on both sides, current owner reference and actual
negotiated handler support are checked outside the packet.

Challenge SHA-256 is over `magnolie-file-control-challenge-v1\0` followed by the
canonical JSON grant fields, `format` and `session_epoch`; sequence and echo are
excluded. `echo` returns the other side's challenge. Directional readiness
requires both a fresh remote echo of the current local challenge and an **exact
native send-completion ticket after actual guarded channel send** of the current
echo. Merely constructing, parsing or copying a packet is insufficient. Echoes
settle without an unbounded feedback loop. A stale echo from a previous channel
does not authorize the new channel.

Persistent permission epoch is SHA-256 over `magnolie-file-permission-v1\0`
followed by canonical, device-ID-sorted entries `[id, native-public-key-sha,
grant-permission-fields]`. Permission fields exclude capability-version lists;
the current negotiated operation remains manifest format 1. Ephemeral session
nonces/sequence/echo are excluded, so fresh genuine reconnection can resume an
unchanged accepted binding after new authenticated agreement. Consent changes
change its epoch. Compatible future manifest capability additions require fresh
echo but do not reset existing v1 consent; losing v1 support pauses it.

Native identity/channel/local-store owner replacement is not silently adopted.
Revision rollback, same-revision changed permission or same-sequence changed
packet fails closed. Same-packet duplication is idempotent. Offline/locked/
unpaired/not-own/unsupported state yields no active native file binding, never
deletion evidence or newly granted consent. Android's native photo-receiver
adapter additionally feeds the existing gallery/SAF source authorities: it does
not substitute for actual OS READ grants or enable a source policy by itself.

## Verified boundary and open work

The shared vector is 284 canonical body bytes, SHA-256
`4a607be40c5d2fc917158a1007334416882ecc14a0ea18ce1681cd4a9a5c633d`,
challenge `3f919e84648c52122aa9946d27a6cd265077739a41d19f6d9395934325e2c8a4`.
Both directions derive persistent permission epoch
`8cdc2f824872a22de57b19374617d1e94770eca5ca921ad79c8469556dfa5150`.

Twenty-four Python tests, eight Android unit cases and the targeted Windows
source-host group pass; Windows build has zero warnings/errors. These are native
control/codec/scope tests, **not** an authenticated physical phone, actual OS
permission prompt or end-to-end transfer acceptance. Protected local file-policy
controller/persistence, actual channel send/receive registration, source request/
selection, MainActivity/notification-tap wiring and Organizer-only controls remain
to connect. Discovery 21 is still not advertised. No extra phone settings or
automatic background action has been added.
