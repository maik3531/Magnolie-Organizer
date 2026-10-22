# Saved Android crash diagnostics (device-status version 13)

Refs #113, #192. This extends the existing developer-read path used by
`notes_diagnostics_read`; it creates no independent file-access or storage engine.

The desktop requests `device_status.request` with exactly `version: 13` and a
fresh UUID-v4 `request_id` when the connected Notes peer advertises that version.
Older peers continue to receive version 11 and its unchanged WLAN-only schema.

The version-13 `device_status.report` contains exactly `version`, `request_id`,
`format: 1`, `app_version`, `events` and `crash_report`. Existing event constraints
remain unchanged: at most 128 entries with `time_ms`, `stage`, `transport`,
`failure`. The report body is bounded to 131072 serialized UTF-8 bytes.

`crash_report` contains exactly:

- `available`: boolean; a saved report was readable.
- `text`: UTF-8 text from the existing `Absturzberichte.bericht` file, bounded to
  the first 16384 source bytes, with sensitive values replaced by `***` before
  export and the same bound applied again after masking. A cut UTF-8 sequence is decoded with replacement;
  consumers allow up to 16387 UTF-8 bytes for that decoded prefix.
- `truncated`: boolean; additional source bytes were present.

If unavailable, `text` is empty and `truncated` is false. The producer reads only
the existing fixed application crash-report path (or its existing rotated
fallback), never a peer-supplied filename. It does not delete or rewrite the file.
The report includes its original timestamp, exception and cause/stack information;
it is not a claim that a new crash occurred during the request.

Crash capture and exported legacy reports use the shared sensitive-value policy:
credential fields, authorization/session tokens, password-bearing URLs, phone
numbers and email addresses become stars. Request UUIDs, timestamps, exception
types and source frames remain available. Both desktop consumers also mask the
returned text. Cross-platform examples are in
[`diagnostics-redaction-v1.json`](diagnostics-redaction-v1.json).

Authorization is unchanged: one paired own phone, fresh capabilities/grants/own
settings, device-status permission on both ends, an active pinned Wi-Fi session,
and locally enabled Notes developer/WLAN debugging. The request expires within
60 seconds; desktop reads retain the existing ten-second deadline. A report must
match the requested version, request ID, peer key and channel. Revocation, replay,
late/unsolicited replies or capability downgrade cannot release diagnostic data.
No report is added to the Organizer book, status history, inbox or outbox.

`13` here belongs to `device_status`; it does not change
`personal_tasks_sync` version 13 or enable any Notes actor marker.
