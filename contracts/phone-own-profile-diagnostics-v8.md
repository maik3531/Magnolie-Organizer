# Own-profile provider diagnostics (device-status version 8)

Refs #146. This optional read-only extension uses the existing authenticated,
paired own-device contact-read authorization. It grants no additional access.
Version 7 profile reads and version 5 contact reads remain unchanged.

Both peers must advertise device-status version 8. The request has the same
fields as a version 7 profile request, with `version: 8`, `action: "profile"`,
`offset: 0`, and an empty `uids` array.

The response retains the version 7 `profile: {state, vcard}`, `total`, and empty
`contacts` fields. Version 8 additionally requires `diagnostics`, an array of at
most 32 records with exactly these fields:

- `stage`: `canonical_header`, `marked_header`, `data`, `photo`, or `finish`.
- `rows`: integer -1 through 1000; -1 means a count is unavailable, larger provider
  counts are capped at 1000.
- `outcome`: `ok`, `no_cursor`, `empty`, `ambiguous`, `invalid_identity`,
  `permission_denied`, `unsupported_or_invalid`, `provider_changed`, `too_large`,
  `no_profile`, or `provider_failure`.

These records contain no contact names, IDs, addresses, birthdays, photo bytes,
medical values, arbitrary provider exception messages, or filesystem paths.
Unknown fields, stages, outcomes, non-integer counts and oversized arrays are
rejected. The existing 128 KiB report limit still applies.

Diagnostics describe the actual query result, not a successful data import.
An unavailable profile remains unavailable; no substitute person is fabricated.
