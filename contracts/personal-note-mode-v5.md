# Personal note direction, capability version 5

Refs #76. This extends `personal_notes_sync.versions`; it adds no capability key
and does not change the ordinary version 1–3 batch formats or version 4 custom
scope. Older peers retain their negotiated bidirectional protocol. Import mode
requires authenticated version 5 support from both endpoints.

`personal_sync.note_settings` has a maximum TTL of one day and exactly:

```json
{"format":5,"mode":"phone_import","revision":1,"epoch":"12345678-1234-4234-9234-123456789abc","peer_epoch":""}
```

- `mode` is `two_way` or `phone_import`.
- `revision` is an integer from 1 through 9007199254740991.
- `epoch` is a canonical lowercase UUID v4. Every local preference change
  advances the revision and generates a new epoch.
- `peer_epoch` is empty until the remote policy is known, then acknowledges
  exactly that remote epoch. A same-revision update may change only this echo.
- Old revisions, a changed mode at the same revision, and a revision advance
  reusing the old epoch are rejected.

Policy is saved per paired device/key. Fresh policy messages must be exchanged
on every secure connection before note content is sent. An acknowledgement of
the previous connection or an earlier preference is insufficient. Pending note
traffic waits for this exchange. Existing own-device and module permissions
remain prerequisites.
The connection must also receive current capabilities, grants and own-device
settings. Accepted retransmissions may satisfy this requirement only when they
still match the saved current control state; rejected or superseded controls do
not count. Restoring document content does not reset the paired device's direction
policy or its revision high-water mark.

Import mode is effective if either participant selects `phone_import`. Note and
notebook records and attachment bytes then travel only from phone to desktop.
Requests, receipts, reports and empty completion batches remain bidirectional.
Attachment requests travel in the opposite direction to attachment bytes.
Mixed task/note batches must be filtered before enqueueing; the receiver rejects
a batch containing forbidden note content without partially applying it.

Note, notebook and attachment deletion proposals/decisions are disabled in both
directions in import mode. Imported desktop copies therefore survive later phone
deletion. Task permissions and their deletion policy remain independent.

Every queued send and every incoming application step, including resumed batches
and attachment staging, must recheck current direction and permissions. A mode
change does not delete, reorder or recreate existing documents. Local edits on
desktop copies retain the existing vector-clock conflict review. Message IDs,
batch hashes, original record identities and authenticated replay receipts are
unchanged.

Native deletion-kind proofs are bound to the peer, proposal direction, immutable
proposal ID and exact vector clock. They are encrypted, retained for at most 30
days without extending their lifetime on retransmission, and limited to 10,000
entries. Unknown or expired proofs never authorize note deletions in import mode.
