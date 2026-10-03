# Desktop feature availability, capability version 6

Refs #27. Version 6 of `personal_tasks_sync` adds a desktop-to-phone availability
snapshot. Ordinary task/note record formats 1–3, Custom scope version 4 and note
direction version 5 retain their existing contracts. No capability key is added.

`personal_sync.desktop_features` has a maximum lifetime of one day and exactly:

```json
{"format":6,"revision":1,"custom_tab":false,"tree":false}
```

The revision is an integer from 1 through 9007199254740991. Both feature values
are actual JSON booleans. A duplicate revision is accepted only for an identical
body; lower revisions and same-revision changes are rejected. Revisions survive
ordinary profile restoration. Unchanged snapshots retain their revision.

Only the desktop publishes these settings, after the authenticated peer has
freshly advertised support. Notes binds the received snapshot to that paired
computer and key. It does not infer availability from an IP address, name or an
unverified discovery result. The snapshot contains no document content or keys.

`custom_tab` describes the configured desktop tab. An unavailable tab pauses
Custom data and reminders without discarding saved consent, Custom data or
existing copies. Consent messages remain processable while the tab is unavailable;
ordinary task capabilities are unchanged. Older peers retain their existing UI.

`tree` describes the configured Magnolienbaum availability. Notes presents the
corresponding controls collapsed. Existing independent/legacy tree use and
pending received content remain accessible. These hints never establish a tree
pairing, grant contact permissions, or bypass existing Custom consent.
