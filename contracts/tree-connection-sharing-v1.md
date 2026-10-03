# Magnolienbaum connection forwarding (#42)

This desktop extension preserves the existing home/laptop pairing and gives a
selected third computer its own home pairing. It does not distribute a device's
private key or cloud credentials. A working direct route is required; this
extension neither traverses NAT nor configures a mailbox or VPN.

## Authorization and transport

The home computer explicitly authorizes its confirmed laptop peer with
`weitergabeErlaubt`. The setting is bound to the displayed peer key. Revocation
removes unused delegated invitations; granting permission again does not restore
them. Existing accepted pairings are managed separately.

`POST /magnolie/v2/weitergabe` consumes one authenticated FS1 session obtained
through `/magnolie/v2/sitzung`. The session records the peer's static public key,
the receiver's public key, normalized source address and expiry. All are checked
again before opening the request. Bodies use the existing 128-KiB control limit.
Unknown older endpoints fail without downgrading the exchange to plaintext.

The request is an ordinary FS1 encrypted envelope. Its decrypted content is one
of the exact objects below. `id` is a canonical base64url-encoded random 16-byte
operation identifier, durably reserved on the laptop before transmission.

* `{"aktion":"einladung","id":…, "ziel":…, "adresse":…, "port":…}`
  asks the home peer to issue an invitation. `ziel` has exactly the identity
  fields `kennung`, `name`, `oeffentlich`, `port`. Its ID and public key must be
  different from those of home and laptop. The numeric address and port describe
  the reachable home endpoint. Home checks the confirmed sponsor's current key
  and permission, then creates an existing-format V2 single-use invitation bound
  server-side to the selected recipient ID/key. A repeated live request with the
  same ID and identical canonical content returns the same invitation.
* `{"aktion":"angebot","id":…, "ziel":…, "datei":…}` carries that invitation
  over the confirmed laptop/office channel. The recipient checks its own ID/key
  and the invitation's format, commitment, MAC and expiry. At most eight pending
  offers are retained. Receiving an offer does not establish a pairing.

The response is an FS1 encrypted envelope in the opposite direction, with a new
random nonce and the request's transport ID. Its content is
`{"anfrageHash":…, "ergebnis":…}`. `anfrageHash` is the uppercase hexadecimal
SHA-256 of the canonical decrypted request. Both direction and request binding
are verified. Each endpoint opens at most one envelope in this session and
erases session secrets afterward. A reply is sent only after durable state save.

## Acceptance, retries and scope

The office user checks the home name/fingerprint and accepts or rejects. The
recipient persists its V2 pairing request before sending, including its nonce,
so an interrupted response can be retried unchanged after restart. Final
acceptance revalidates local identity, the still-existing offer, sponsor key and
invitation expiry. A removed or rekeyed sponsor cannot authorize an old offer.

Home checks the recipient ID/key and the current sponsor permission before
redeeming the invitation. A wrong recipient does not consume it. Pairing state
is durable before the response is released. An exact consumed-request retry is
idempotent, but cannot revive a recipient explicitly removed at home.

The office keeps bounded acceptance/rejection receipts for 30 minutes, so a
lost offer response cannot recreate a rejected offer or prompt again for an
accepted operation. Accepted receipts also require the home peer still to have
the same confirmed key. Pending offers expire with the 15-minute invitation.

No contact, contact-deletion or onward-forwarding permission is inherited.
Existing confirmed peer settings survive a file-protocol upgrade. A newly
accepted office/home peer is not automatically trusted to import all content.
The office requests the home collection without uploading its own collection.
Home limits that request to notes already shared with the sponsoring laptop and
tasks explicitly delegated to that laptop. The sponsor's stored identity/key is
checked when deriving this scope; a missing source does not mean unrestricted
access. Received offers use the existing per-content review and identity rules.

Home and office subsequently communicate directly. The laptop is not a relay.
Both directions must be reachable for normal queued content delivery, for
example through an explicitly configured VPN. Pairing success, an offered
connection, queued content and completed content delivery are distinct states.
