# Custom V4 Codec And Receipt Rules

V4 continues to use the existing `magnolie-phone/1` ACK. No new wire fields,
message kinds, or golden hashes are introduced by tombstone retirement.

## Deletion Receipts

- Queueing or sending a batch is not confirmation. Only `accepted`/`duplicate`
  from the authenticated receiver can retire sender metadata.
- Android persists the mirror/deletion state before ACK. A pending deletion is
  durable confirmation of receipt, not permission to delete a phone copy. Keep
  and Delete remain local decisions; repeats preserve the decision.
- Android content restore preserves live pending/Keep/Delete state even when
  the archive contains an older live copy or omits that identity. Already
  acknowledged deletions do not depend on another desktop retransmission.
- Unknown deletions retain a revision floor so a delayed older upsert cannot
  resurrect the item, including after content restore. A stale deletion cannot
  receive a successful ACK while a newer live mirror remains.
- Native desktop ACK handling forwards only source/revision/deletion metadata
  from the matching peer's queued message, never arbitrary ACK-supplied content.
- JS serializes receipt processing with snapshots. It checks source, recipient,
  item, prior hash and deletion revision, and saves retirement durably. A lost
  event, lost ACK, or crash before saving leaves a tombstone for retry. No expiry
  or age rule removes unacknowledged deletions.
- Every recorded recipient must confirm. An offline recipient retains its
  tombstone; ACKs from another recipient cannot remove it. Legacy persisted
  entities without recipient metadata conservatively include all paired peers.
- Repeated manual snapshots contain live items plus unacknowledged deletions,
  not the full history of acknowledged deletions. Content restore keeps the
  current source identity, revision high-water and entity metadata.

## Time Zones

The wire carries a case-sensitive IANA tzdb name or backward alias, not a Windows
time-zone ID, raw offset, Java synthetic `GMT+...`/`UTC+...` ID, `Z`, `system`,
`localtime`, `posixrules`, `posix/`, `right/`, or `SystemV/` name. Names use ASCII
letters/digits, underscore, dot, plus, hyphen and path separators; syntax alone
does not establish validity.

Validate against the installed runtime's tzdb/ICU mapping rather than a frozen
global name list. Ordinary IANA aliases, including `US/Eastern`,
`Asia/Calcutta`, `Etc/GMT+5` and UTC/GMT names, stay valid. tzdb updates can add
names an older runtime cannot resolve; those are rejected, never substituted.
Two small runtime adaptations preserve real legacy IANA names:

- Java omits the fixed-rule IANA names EST, MST and HST. Resolve them to their
  defined offsets (-05:00, -07:00 and -10:00), not locale abbreviations.
- .NET/CLDR Windows-ID conversion omits some legacy IANA rule names. Desktop
  validation recognizes CET, EET, MET, WET, EST5EDT, CST6CDT, MST7MDT and PST8PDT
  explicitly. It keeps the original wire name; Android uses its tzdb rules.

Desktop snapshots resolve the configured Organizer zone once before async work.
Only `system`/the absent default chooses the host zone. An invalid explicit zone
blocks transmission and shows the existing translated sync error plus the
translated Time zone label and configured value, including automatic sync.
The local display helpers' existing system fallback is not permission to export
a guessed source zone.

## Canonical JSON

Canonical numbers are signed decimal integers; zero has the bytes `0`, including
parsed `-0`. The phone codec accepts signed 64-bit integers; V4 numeric field
validators apply their narrower safe-integer/range limits. JS uses safe integers
and must accept the valid recurrence ordinal -1. Fractional/exponent spellings
are not canonical wire integers. JSON.parse loses numeric spelling in JS;
senders still emit the normalized integer spelling.

Strings and keys are Unicode scalar sequences encoded with strict UTF-8. Valid
surrogate pairs are accepted; isolated UTF-16 surrogates and malformed UTF-8 are
rejected, not replaced. Existing Unicode key ordering, escapes, protocol labels,
identity derivation and golden canonical hashes remain unchanged.
