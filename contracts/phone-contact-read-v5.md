# Read-only Notes contacts through the paired phone channel (#62 / #23)

Device-status version 5 adds a bounded read-only contact-resource query to the
existing authenticated phone channel. The original capability/grant name sets
remain unchanged for compatibility with older peers. Ordinary status requests
and reports keep their existing versions and meanings.

Notes advertises `device_status.versions` containing `5` for a computer only when
that computer has explicitly been allowed to read contacts, both sides identify
the pairing as their own device, and Android grants READ_CONTACTS. Granting basic
device status alone does not authorize this extension. Removing this permission
removes version 5 from the next capability advertisement. Every request and the
final response recheck the current peer/key, explicit contact-read permission,
own-device state and Android permission, including during an ongoing read.

Requests use `device_status.request` with exactly:

```
{"version":5,"request_id":"UUIDv4","action":"index|cards","offset":0,"uids":[]}
```

For `index`, `uids` is empty and offset selects at most 128 entries from a sorted
index of at most 10,000 contacts. For `cards`, offset is zero and one to five
distinct UIDs are selected. UIDs are nonempty strings of at most 256 characters,
without control characters. No write, delete or provider-configuration operation
exists in this extension.

Replies use `device_status.report` with exactly `version`, `request_id`, `action`,
`offset`, `total`, `contacts`. Index entries contain exactly `uid` and `timestamp`;
card entries additionally contain `vcard`. Timestamps are nonnegative provider
update times in milliseconds, at most 253402300799999. Unknown dates use zero.
The UTF-8 report is limited to 128 KiB; one vCard is limited to 96 KiB. Photos are
bounded thumbnails. Replies are transient, expire within 60 seconds and are
accepted only for a live request on the same current authenticated connection.
They are not saved as ordinary device-status history or replayed to a new peer.

The desktop associates source UIDs with the Notes peer ID and SHA-256 of its
pinned public key. Photo-only projection exposes matching numbers/emails and
the photo, preserving explicit local photo choices. Full-contact requests enter
the existing field-level preview and durable-save flow; they do not silently
replace local fields. Messenger fields come only from readable provider rows
that explicitly contain that service identifier. A phone number alone does not
establish membership, and no private messenger profile endpoint is queried.
