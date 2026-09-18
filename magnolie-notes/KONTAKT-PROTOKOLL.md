# Contact Protocol Extension for Magnolie Notes 1.0.14

This is a coordination contract for the Android, Linux and Windows implementations.
Desktop and Android source implement the same unreleased version-2 extension.
The source directory has the stable name `magnolie-notes`.

## Authenticated Capability Exchange

Use the existing encrypted Magnolienbaum message transport and its normal replay
protection. Do not trust capabilities from DNS-SD, UDP discovery, an unauthenticated
pairing request, or a peer identifier alone. The pinned partner must be confirmed.

```json
{
  "art": "kontakt_faehigkeiten",
  "fassung": 1,
  "kontakt_sync": [1, 2],
  "kontakt_import": [],
  "antwort": false
}
```

The field set is exact. `fassung` is the integer 1, `antwort` is a JSON boolean,
and the sync version array is exactly `[1]` or `[1,2]`. `kontakt_import` names
supported RECEIVING versions and accepts `[]`, `[1]` or `[1,2]`. Android advertises
`[]` because it only sends one-time import cards. An updated desktop receiver
advertises `[1,2]`; Android then sends version 2 to that desktop. A receiver persists the
versions against the authenticated partner and, for `antwort:false`, queues its
own capabilities with `antwort:true`. It must not answer a response, avoiding
loops. Capabilities do not grant contact read/write permission or content trust.

Android announces on receiving-service startup and pairing completion, and probes
before a manual contact operation when version 2 has not yet been advertised.
Both apps' receivers must run to finish this two-way exchange. Old partners
remain version 1; receipt of a transport ACK is NOT capability confirmation.
Removing a partner clears its stored capabilities. Unauthenticated pairing fields
cannot overwrite an established partner's endpoint, pinned protocol, consent or
capabilities. An explicitly selected, valid file exchange may advance `baum-1`
to `baum-fs1` with the same pinned key; it preserves all other partner fields.
It cannot downgrade another protocol or replace a pinned key.

File requests keep their nonce across retries and restarts. Receiver receipts
are bound to the exact canonical request and expire after 24 hours. A consumed
invitation rejects different nonces; an exact replay returns the stored receipt
without changing partner state or requeuing probes. Selected files are checked
again after network I/O and within the commit boundary for expiry.

Queued legacy messages retain their existing encrypted envelope and counter
after an upgrade. New legacy envelopes and counter reservations are persisted
before transmission, and deliveries are serialized per outbox. The Android
receiver acknowledges a previously authenticated exact envelope without applying
its mutation again; a different envelope cannot reuse that counter. Legacy ACKs
are still not cryptographically authenticated and never update partner trust or
protocol. Older installations did not persist legacy envelopes: their pending
items stay on the legacy transport, not silently re-encoded as new FS1 messages;
previously lost, unrecorded nonces cannot be reconstructed retroactively.

Desktop advisory probes use a separate queue lane so an old peer rejecting an
unknown probe cannot block representable legacy contact content. Retry counters
remain authenticated; a later baum-1 advisory retry gets a fresh encryption
counter if intervening content was sent. Contact completion reports refer to
the contact's own queued ID, never another message's ACK. Outbound contact
versions are checked again on delivery; a changed negotiation cannot silently
rewrite a queued import preview or its cards.

## Version 1 Remains Strict

Do not add `jubilaeum` to version-1 payloads. Keep the old exact contact field set
and optional `foto`. Old version-1 messages and their hashes remain unchanged
when no anniversary is present. Android refuses a version-1 outgoing contact
operation containing an anniversary, before queuing any contact content, rather
than silently dropping the field. It explains that both apps need updating and
opening before another attempt. No new permission or confirmation dialog is added.

## Contact Sync Version 2

After the peer has authenticated support for `kontakt_sync` version 2, send the
existing `kontakt_sync` envelope with integer `fassung:2`. The envelope remains
exactly `art, fassung, freigabeId, version, quelle, geaendert, kontakt`.

The contact object contains exactly these required fields:

```json
{
  "vorname": "",
  "nachname": "Van Dame",
  "anzeigename": "Van Dame (Club)",
  "vcardName": ["N:Van Dame;;;;", "FN:Van Dame (Club)"],
  "firma": "",
  "notiz": "",
  "geburtstag": "--02-29",
  "jubilaeum": "--06-07",
  "telefone": [],
  "emailEintraege": [],
  "anschriften": []
}
```

`anzeigename` is an independent string (at most 2048 Unicode code points).
`vcardName` is a required array, empty when no source N/FN was supplied, of at
most 32 unfolded N/FN property lines, each at most 2048 Unicode code points.
An optional alphanumeric/hyphen property group and parameters are allowed;
no C0 or DEL character is allowed anywhere in a line. Other property names are
rejected. Keep escaped delimiters, multiple values, additional/prefix/suffix N
components, parameters and additional N/FN instances intact. The editable
`vorname`/`nachname` and independent `anzeigename` are the canonical projection;
export reconciles only changed scalar components with the retained raw syntax.
Android retains raw name syntax in a contact-scoped provider data row alongside
the native StructuredName projection. No name is split or filled from FN.

`foto` remains optional under the existing photo contract. `jubilaeum` is required
even when empty. Its type is string, and its accepted values are `""`, valid
`YYYY-MM-DD` (year 0000 is invalid), or valid `--MM-DD`, including `--02-29`.
Never infer a year, calculate age from a yearless date, split a supplied partial
name, or fill a missing name component from the display name. A real date in
year 1604 remains real unless the desktop source parser has explicit omit-year
metadata; Android cannot reconstruct omitted source parameters from this DTO.

The existing nonempty-scalar/additive-list merge policy applies. Empty remote
anniversaries do not delete local values. Different nonempty anniversary dates
are contact-group conflicts, not safe automatic unions. Revisions must increase
when the projected anniversary changes. Android's local contact hash uses its
version-2 projection when a contact is not losslessly representable by version 1;
otherwise the exact existing version-1 hash bytes are retained. Name-only and
anniversary-only changes therefore advance revisions. Desktops persist a SHA-256
hash of the canonical version-2 projection, independently of the selected peer
version, rather than duplicating full photos in revision metadata.

Version 1 is representable only with an empty anniversary, an empty or ordinary
given/family display name, and no raw name lines other than the equivalent plain
N/FN projection. Complex names are rejected before any contact in that operation
is queued, not partially stripped. A capability probe is not contact content.

## One-Time Import Version 2

Negotiate `kontakt_import` separately. The existing manifest and card envelope
schemas stay the same, but BOTH use integer `fassung:2`; the card's `kontakt`
uses the same required version-2 contact object. Version-1 imports remain strict.
Preview and confirmed send must use the same negotiated version. Existing stable
`bindung`, source identity, count, byte limits and explicit preview consent remain.

## Required Desktop Work

1. Receive, validate, persist and answer `kontakt_faehigkeiten` only after normal
   pinned-partner authentication. Advertise `[1,2]` only after the paths below work.
2. Add strict, separate version-2 contact-sync and one-time-import validators.
   Do not make version 1 permissive or infer support from ACKs.
3. Carry the canonical `jubilaeum` through native DTOs, web projection, merge,
   save/reload, revision/hash calculation, import cards and re-export.
4. Keep birthdays and anniversaries separate; retain partial names and unknown
   years. Parse Apple omit-year information before creating the canonical DTO.
5. If anniversary data cannot be represented by the negotiated peer version,
   retain it locally and reject that contact operation without partial content
   transfer. Do not silently strip the field.
6. Test old/new and new/new peers, malformed/forged capabilities, missing/extra
   fields, replay, version changes, birthday-only and anniversary-only updates,
   and restart with persisted capabilities. Native desktop/Android interoperability
    remains a release gate.

## Desktop File Exchange

Both desktops write `magnolieVCard` as an RFC 2849 base64/folded LDIF attribute
containing one complete canonical vCard. Its original UID is authoritative even
when the standard LDAP `uid`/DN has to use a safe derived identifier. The full
card preserves N/FN, typed lists, additional address fields, opaque fields and
yearless BDAY/ANNIVERSARY. Readers still accept the previously written partial
`magnolieVCardN` attribute when no full card is present; new writers do not emit it.
Invalid full extensions are not silently replaced by a partial LDAP projection.
Contact parsers do not also return detached birthday arrays: the web import
creates linked contact occasions. Independent calendar birthdays remain intact.

`../contracts/kontakt-v2.schema.json` describes the exact new field sets. The
existing version-1 contract fixtures remain unchanged. Runtime validators also
enforce real dates and the unchanged photo/list restrictions noted in the schema.

## Personal Sync Chunk Agreement

This is independent of the contact extension: keep `CHUNK_RAW=180000`, indexes
0 through 46, and the 8 MiB attachment limit. Change the **attachment-chunk JSON
body** limit from 192 KiB to `256*1024` on all three platforms. Other batch limits
remain unchanged. A full chunk body is about 240252 bytes and its message envelope
still fits the existing 262144-byte application-message limit. Do not change
chunk partitioning, existing transfer identity, or encryption framing.

## Tests and Native Gates

`KontaktVersion2Test` covers exact versions, partial names, yearless dates,
anniversary conflicts and one-time imports. `KontaktProviderRegressionTest` runs
the actual Android adapter against an isolated in-memory ContactsProvider fixture.
It checks TYPE_BIRTHDAY and TYPE_ANNIVERSARY separately, including event-specific
update selection; it never accesses a real user's contacts.

Robolectric/JVM tests do not certify real ContactsProvider account behavior,
AndroidKeyStore, SAF providers, background-service delivery or an R8 release.
