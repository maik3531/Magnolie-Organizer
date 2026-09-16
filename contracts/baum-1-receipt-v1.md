# Baum-1 Authenticated Receipt Version 1

This extension changes only direct legacy `POST /magnolie/v1/nachricht` responses.
FS1 and authenticated Nextcloud mailbox receipts are unchanged. Implementations
must not interpret HTTP success or a legacy `{ "ok": true }` as proof of receipt.

## Cryptography

Use the existing pinned-peer `PartnerKey` (32 bytes). Derive a receipt key using
HKDF-SHA256 with empty salt (32 zero bytes in HKDF extract), info equal to UTF-8
`magnolienbaum\0baum-1\0receipt-v1`, output length 32. Here `\0` means one NUL byte.

The receipt core has exactly these fields:

```json
{"format":"baum-1-receipt","version":1,"sender":"original-sender-id","recipient":"original-recipient-id","counter":1,"envelopeSha256":"64-lowercase-hex-digits","status":"accepted"}
```

`counter` is the exact reserved envelope's integer `zaehler`. `envelopeSha256` is
SHA256 of the canonical COMPLETE reserved encrypted envelope, not plaintext and
not a newly generated retry. Canonicalization is the existing Baum canonical JSON:
lexicographically sorted keys, no whitespace, ASCII JSON escaping (including
lowercase `\u` escapes), integers in decimal. Envelope string values are included
exactly as reserved. Relevant receipt/envelope keys and IDs are ASCII.

Compute HMAC-SHA256(receipt-key, UTF-8 `magnolienbaum\0baum-1\0receipt-v1\0` concatenated
with the canonical receipt core). Add `mac` as standard padded Base64. The receiver
returns this eight-field object after durable acceptance, without an outer wrapper.
Verify all seven core fields exactly, reject extra fields, and compare the 32-byte
MAC in constant time. A receipt for another key, envelope, counter or direction
must not remove the outbox entry.

## Persistence And Compatibility

The receiver authenticates/decrypts the legacy message using the pinned peer key,
stores its effect, and durably stores its receipt/counter before returning success.
Retain at most 64 exact receipts per peer and 256 per profile, evicting the oldest
entries from the largest peer cache when necessary. An identical cached envelope receives
the same receipt without reapplying content; unknown stale counters remain rejected.
Inbox entries carry the envelope hash to recover the inbox-before-state crash window.

Before transmitting a direct message, the sender persists `receiptAttempted:true`
and `unsicher:true` on the reserved outbox item. Only a valid receipt permits deletion.
Missing/invalid/unsupported receipts and interrupted attempts retain an explicitly
uncertain message and MUST NOT automatically retransmit content or fall back to a
second delivery transport. Old reserved envelopes lacking `receiptProtocol:1` are
also uncertain: their prior effect cannot be established. New reservations carry
`receiptProtocol:1`. This conservative policy prevents duplicate effects on old
peers; it does not claim exactly-once delivery or automatic recovery of every lost
receipt. Future receipt retrieval must be a separately versioned read-only protocol.

Only failures proving that no connection existed (DNS resolution failure or TCP
connection refusal) may clear the attempted/uncertain flags and use the existing
backoff. Resets, timeouts, cancellation, HTTP error responses and missing receipts
do not prove absence of an application effect. They must remain uncertain.

Linux/Android implementations are intentionally not changed in this Windows unit.
Portable vectors in `baum-1-receipt-v1-vectors.json` fix the byte-level encoding.
