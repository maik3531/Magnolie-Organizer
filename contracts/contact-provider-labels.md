# Native contact provider labels (#576)

Telephone, email and postal-address values are compared separately from their
provider labels, types and roles. A metadata-only difference does not require a
value-conflict decision. Existing exact source hashes and baseline formats are
unchanged; this classification is not a weaker write authorization.

When both content times are usable and the original remote source revision has
actually changed, a newer incoming content version supplies the canonical labels.
Otherwise the existing canonical representation remains. A timestamp resulting
from our own acknowledged provider write is not a newer user edit. Unknown or
implausibly future times do not establish newer content. Equivalent Home/Privat
representations do not require repeated writes.

Older writable sources receive the canonical representation through their existing
source-specific write path. Read-only sources are not written. A planned Linux
write is not a successful provider acknowledgment: actual handlers retain their
ETag/readback bookkeeping. Windows write failures retain the original baseline.
Real value differences, group changes, photos and opaque metadata are not labels.

Checked scope: native Linux planner with controlled DAV books and actual vCard
writer/parser roundtrips, EDS planning, and native Windows engine tests with
controlled remotes plus the existing Windows contact/Graph regression group.
These are not physical provider/phone delivery tests or installable-package
acceptance. General all-source fanout and the full Notes postal/scalar write path
are separate from this correction (#575).

## Source-local failures (#581)

Linux DAV and EDS/Akonadi contact handlers do not change the contact's global
`sync` marker because one source write or EDS readback failed. The failed source
does not advance its acknowledged content baseline or successful source cursor.
Other original source mappings remain intact. In particular, an EDS baseline
recorded while planning is restored to its prior state on failed/uncertain
delivery. Retrying reads the provider again before making a new decision; a
successful second provider does not acknowledge the failed first provider.

This is checked with complete native handlers and controlled source adapters,
including creation, updates, label-only updates and failed readback. It does not
itself add an automatic scheduler for every provider or prove physical delivery.

## Original source identities (#583)

The regular Linux contact planner resolves an existing EDS/Akonadi source binding
by its original record UID and a DAV binding by its exact stored resource href.
It does not substitute a new identity based on a name or matching phone number.
Updates serialize the original source UID; the canonical local contact UID remains
unchanged. Readback and source baseline acknowledgment use the original source
record, including when a second provider has a different UID for the same person.
Ambiguous bindings or a colliding canonical UID in that source refuse planning.
Deletion uses the bound source UID and retains canonical tombstone identity on
failure; existing revision checks still apply.

Windows CardDAV already preserves `remote.Data.uid` in its outgoing copy. That
existing protection was not a new Windows bug. The new Linux correction is checked
with controlled whole EDS/DAV handlers and planner guards, not live accounts or
automatic permission to synchronize additional providers.
