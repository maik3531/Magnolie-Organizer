# Phone contact value writes — resource 19

This resource changes phone-number and email-address lists of an already bound
existing native contact. The current provider writer requires one unambiguous raw
contact. The common contact-write choice controls this resource and group writes;
old explicit opt-outs remain bound to the confirmed computer key. Capability 19
requires readable contacts, write permission and this choice on the phone. Desktop
consumers independently require a fresh authenticated own-phone WLAN session.
Resource 5 remains read-only and resource 17 retains its group-only meaning.
Names, scalar fields, postal addresses and photos are outside resource 19.

All requests and reports are exact JSON objects, at most 128 KiB of canonical
UTF-8. IDs and tokens are lowercase UUIDv4; `uid` is the existing bound native
contact UID, at most 256 code points. Text rejects controls and unpaired surrogates.

Prepare request: `version:19`, `request_id`, `action:"prepare"`, `uid`,
`field_names`: a unique nonempty selection of `telefone`, `emailEintraege`.

Apply request: `version:19`, `request_id`, `action:"apply"`, `uid`, `token`,
`fields`: an object whose keys exactly match the prepared field selection. An
absent field is untouched; an empty array explicitly clears that selected list.
Each list has at most 100 exact `{art,wert}` objects. `art` is `privat`, `arbeit`,
`mobil` or `sonstige`; `wert` is nonblank and at most 4096 code points. Values must
be unique under the existing contact projection's phone/email normalization.

Reports: `version`, `request_id`, `action`, `uid`, `token`, `account`, `state`,
`fields`. State is `prepared` only for prepare and `saved` only for apply. Account
is the exact `{name,type,data_set}` source identity; every string is bounded to
256 code points. Reports contain only the requested fields and actual provider
values. Request correlation, field selection, account, UID, fingerprint and live
connection must be checked again by each desktop consumer.

The native preparation is ephemeral, session-owner-bound, single-use, at most
eight tickets, with a 30-second monotonic expiry. Current implementation requires
one unambiguous raw contact and complete native versions. No name/domain-based
account guessing. Reconnect, unpair, revocation, lock or owner change must clear
the tickets. Session retirement removes only that owner's tickets, so a late old
session cleanup cannot revoke a new session's preparation.

Desktop transport codecs validate exact shapes, types, bounds and correlation;
the native writer additionally enforces the provider projection's normalized
uniqueness and ambiguous-row rules. The shared editor/MCP mutation handler records
field-specific durable intent. Sending follows local SaveACK, a fresh preparation,
the original common baseline and actual matching saved readback. An independently
changed field is left at the observed native value while nonconflicting selected
fields converge. Only acknowledged wishes are cleared with another SaveACK. A
later local edit is based on a causally confirmed own write rather than becoming a
false concurrent edit. The read path keeps observed values separate from common
baselines and never overwrites an offline wish or guesses an initial value winner.

Phone and email deltas share one provider batch containing raw-version assertions.
Unchanged native rows, custom labels, primary flags, unrelated MIME rows and
unprojected duplicate rows remain intact. An ambiguous edited projection fails
before any batch. Updates use the original data-row ID; only changed value
columns are written, and stale normalized-number data is cleared only for a phone
number update. A failed batch rolls back both lists. A fresh actual readback is
required before `saved`; transport ACK is never a save receipt. An uncertain
operation consumes its ticket and requires a new prepare/read instead of replay.
