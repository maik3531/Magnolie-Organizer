# Contact synchronization with native group memberships (fassung 4)

Refs #195. Version 4 extends the existing `kontakt_sync` message and provider
transaction paths. It is not an independent contact or group storage engine.

The version-3 envelope/content-time fields remain mandatory. Its `kontakt` object
additionally requires `gruppen`, an explicit array of at most 100 nonblank group
titles. Each title has at most 256 Unicode scalar values and no C0/DEL characters.
Titles are normalized to NFC, trimmed, deduplicated case-insensitively and sorted
in the product's ordinal string order. Preset labels use the existing contact
group display/alias machinery; custom titles remain literal.

An accepted version-4 set replaces the editable memberships, including removals.
`gruppen: []` explicitly clears editable memberships. Versions 1–3 have **unknown**
memberships, not an empty group set; they preserve current native groups. Existing
version-1/2/3 wire fields and their legacy fingerprints are unchanged. A version-4
message cannot be silently down-converted because that would lose additions or
an explicit removal.

Capability advertisement uses the existing authenticated `kontakt_faehigkeiten`
exchange with `kontakt_sync: [1,2,3,4]`. Version-4 probes use the existing advisory
FS1 transport mechanism independently of old version-3 probes. An older receiver
rejecting this optional probe does not consume/fail queued user contact data.
Delayed lower-version replies cannot erase a previously confirmed higher
capability; a fresh explicit advertisement can still declare a downgraded peer.

On Android, group support is positively detected through the actual Contacts
Provider group interface. Unsupported/unknown groups stay `null` internally and
cannot become an accidental clear. The native snapshot reads real GroupMembership
rows and group titles. Automatic/favourite system memberships are preserved.
New groups/memberships belong to the selected RawContact's account/data set;
same-named groups in another account are not reused. Removing membership never
deletes a global group or another contact. For aggregated contacts, removed
memberships are scoped to the bound RawContact set.

Group planning joins the existing RawContact-version-asserted atomic provider
batch, verifies expected definitions and reads the resulting memberships back.
Provider races, failed transactions and unrepresentable writes cannot produce a
successful group-sync acknowledgement. Existing conflict review, recovery
snapshots, identity binding, transport replay protection and content-time rules
remain authoritative.

Conflict review can explicitly retain local memberships while merging the other
contact fields. Desktop MCP exposes the same choice as `group_choice` on
`organizer_tree_inbox_apply`; it is valid only for `merge` with known groups.
The default is the full incoming set. Complete replacement uses incoming groups.
Remembered review fingerprints include known groups, so unchanged retransmissions
preserve the user's decision while changed group sets require a fresh comparison.
Group-only changes participate in recovery-snapshot change detection.

Android's incoming-fragment planner preserves a single known group set, even
alongside legacy fragments with unknown groups. Different known sets, including
an explicit empty set versus nonempty memberships, are conflicts requiring
individual review; automatic fragment union must not resurrect removed groups.
