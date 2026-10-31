# Existing contact-group title change (resource 20)

Issue: #279. Desktop support is advertised separately; Notes advertises the
operation only with effective contact read/write choices and OS permissions.
Resource 5 remains read-only, 17 changes memberships, and 19 changes selected
phone/email lists. Source enablement is not a public-package release receipt.

## Explicit operation

The user selects an existing, strongly bound Notes contact and explicitly
requests `old_title` → `new_title`. The provider resolves exactly one owning raw
contact/account and exactly one existing membership group. It changes that
group's title, retaining its native ID, source ID and all memberships. This is
an account-group operation, affecting all its members, rather than a change to
only the selected contact's memberships.

Reject ambiguous raw owners, incomplete reads, system/read-only groups and an
existing target title in that account. Do not infer an account from its display
name, create a second group, merge groups or change an unrelated group's title.

## Bounded two-phase messages

JSON uses exact keys, integer `version: 20`, UUIDv4 `request_id`, action
`prepare`/`apply`/`inspect`, valid native contact `uid`, and distinct `old_title`/`new_title`.
Titles are nonblank trimmed NFC strings, at most 256 Unicode code points, with
no controls or unpaired surrogates. The complete message is at most 16 KiB.

* Prepare request: `version`, `request_id`, `action`, `uid`, `old_title`,
  `new_title`.
* Apply request: the same fields plus the prepared UUIDv4 `token`.
* Inspect request: the common request identity/title fields plus `group_id` and
  `account` from the persisted preparation. It reads the existing group by native
  ID under the contact's current membership/account, rather than its old title.
* Prepare/apply report: the request identity/title fields plus `token`, `state`,
  `group_id`, `account`, `group_identity`. State is `prepared`/`saved`, respectively. `group_id` is
  the canonical positive signed-64-bit decimal ID encoded as a string.
  `account` has exactly string keys `name`, `type`, `data_set` (each at most 256
  code points, empty allowed).
* Inspect report: the common request identity/title fields plus `state: current`,
  `group_id`, `account`, `group_identity`, `current_title`. It has no token and
  creates no preparation or provider mutation. The current provider title is
  valid nonblank Unicode text of at most 256 code points, without controls or
  unpaired surrogates; unlike a requested new title it is not silently normalized.

`group_identity` is a lowercase SHA-256 fingerprint computed by the provider
adapter over native ID, exact nullable account components and native source ID,
excluding the mutable title. Encoding is ordered ID-as-decimal-string, account
name/type/data-set, source ID; each UTF-8 byte string has a four-byte big-endian
signed length, with -1 for null. This distinguishes null from an empty provider
field and detects replacement/source rebinding without exporting source IDs.

The desktop checks the exact request identity and both titles. Apply additionally
requires the original token, group ID, account and identity fingerprint from prepare. A transport ACK
is not proof of a saved title.

After an uncertain apply or lost saved report, retain the prepared native
identity durably and inspect it. Convergence requires the same UID, intent,
group ID, account and identity fingerprint, with the observed current title
equal to the desired new title. A different identity/title is a conflict or
unresolved observation. Never recreate the old label or retry a mutation based
only on a matching visible title. Inspection is an observation, not a claim
that a previous transport result was delivered.

## Native scope and lifecycle

Require current paired-key/channel identity, fresh authenticated controls, the
existing contact-write choice and current READ/WRITE_CONTACTS permission. Keep
at most eight preparation tickets for 30 seconds, bound to the transport owner,
UID, raw/account/catalog snapshot and both titles. Desktop preparations must
expire sooner. Consume apply once before provider I/O; reject stale raw versions
or a changed catalog in one provider CAS batch. Re-read the native membership
and group title before reporting `saved`. Revocation/close clears owned tickets.

After a successful rename, desktop group projections must follow authoritative
fresh native reads on their existing UID/key bindings. Preserve independent
offline membership edits. A matching visible title alone does not identify
another contact's account or authorize a global desktop replacement.
