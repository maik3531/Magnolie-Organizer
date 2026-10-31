# Read-only native contact-group diagnosis (device-status version 18, #252)

This optional debug resource leaves the account-bound version-17 write contract
unchanged. It is advertised alongside group writes. It is usable only through
the current own-device Wi-Fi pairing with fresh controls, contact-read and
group-write settings, both Android contact permissions, and the phone's locally
enabled developer Wi-Fi diagnostics. Disabling that local option blocks the
probe before and after provider access. There is no remote enable command.

The request is exactly `version: 18`, UUIDv4 `request_id`,
`action: "diagnostics"`, and the exact native contact `uid`. Contact fields,
account selectors, groups and apply tokens are forbidden. It uses the existing
bounded live resource transport, eight-second desktop deadline, and 60-second
maximum response TTL. Peer/key/channel/UID/request matching remains mandatory.

The reply contains exactly `version`, `request_id`, `action`, `uid`, `state`,
`stage`, `error_type`, `reason`, `raw_count`, `version_count`, `account_count`,
and Booleans `mime_supported`, `reader_complete`. The latter records whether the
same full bounded group reader succeeds independently of the provider's MIME
hint; this debug read still never enables a write. False means not confirmed
or a reader failure. Counts are integers from 0 to 10,000. `state` is
`available` or `failed`; the preparation stages are `request`, `permission`,
`snapshot`, `snapshot_shape`, `uid`, `raw_versions`, `account_scope`, `groups`,
`catalog`, `report`, `complete`. Only a Java exception class name (ASCII letters
and digits, at most 64 characters) is returned, never an exception message,
stack trace, provider SQL, account name, group title or contact content.
`reason` is one of `none`, `contact_groups_ambiguous_account`,
`contact_groups_unknown`, `contact_groups_unavailable`, `contact_groups_incomplete`,
`provider_failure`. The actual bounded reader distinguishes a missing provider
interface from a membership whose referenced group definition is unresolved.
An available result has stage `complete`, type `None`, reason `none`.

The probe follows the actual preparation path but never calls apply or a provider
mutation. Any ticket created solely by the probe is removed immediately; another
live user's ticket remains untouched. Results are transient, cannot satisfy a
version-17 save request, and never enter device-status history or a persisted
outbox. This gives a bounded native failure location when the ordinary write
acknowledgement intentionally returns only `temporary_failure`.

The desktop exposes this through the developer-only read-only MCP tool
`notes_contact_groups_diagnostics_read`, using an existing local contact ID and
its already observed Notes source. The tool cannot select an unrelated account,
switch the paired key or apply groups. Its public result omits native UIDs and
request tokens and checks the same book/source again after the asynchronous read.
