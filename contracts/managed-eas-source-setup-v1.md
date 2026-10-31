# Managed EAS source setup, version 1

Implementation scope: #29. This is **folder discovery/setup**, not an EAS data
adapter, remote CRUD acknowledgment or sync-commit protocol. It must not be used
to claim that Microsoft contacts/calendars have already been synchronized.

## Ownership and transport

The existing current-user-only managed Thunderbird native channel is used.
Only Magnolie's managed profile and its pinned caller-scoped TbSync adapter can
perform these operations. The provider retains its own OAuth implementation and
credentials. No client IDs, tokens, passwords or raw account configuration cross
the source-control boundary.

The native envelope retains `version:1`, correlated 32-hex `id`, and `ok`.
New managed operations are `eas-source-list`, `eas-source-inspect`,
`eas-source-prepare`, and `eas-source-enable`. Account/folder requests contain
`account_id` and `folder_id`; enable additionally contains `token` and
`revision`. Unknown fields are rejected. Ordinary, non-managed Thunderbird
profiles do not expose the managed source scope.

The background obtains the persistent owned `profile_id` before and after the
provider call. A changed profile rejects the result. It forwards only the
explicit source-control request to `tbsync@jobisoft.de`; the adapter accepts only
`magnolie-bridge@magnolie-organizer.org`.

## Source identity and catalog

`source_identity` is SHA-256 over a structured, ordered JSON array of provider,
account ID, provider-owned server type/server/user, native folder ID, kind and
optional native server-folder ID. Display names, volatile sync times,
credentials and replaceable local target IDs are excluded.

`revision` separately binds source identity, selection and the exact nullable
local target ID. The Organizer namespace is
`managed-eas:<profile UUID>:<source_identity>`; it is not a DAV URI.

Each descriptor contains `protocol:1`, `version:1`, `account_id`, `folder_id`,
`kind` (`contacts` or `calendars`), `source_identity`, `revision`, boolean
`selected`, nullable `target_id`, and **`provider_sync_confirmed:false`**.
Catalog entries additionally contain a bounded name. Catalog replies have
`complete:true`, the owned profile ID and at most 256 entries; a failed or
incomplete catalog is not an empty remote address book. Unsupported task folders
are not advertised as implemented sources.

The provider and exact owned enabled account must still be available. Missing,
ambiguous, retyped, inconsistent or unidentifiable folders are rejected.
An unselected folder with an existing target is inconsistent, not permission to
create another target.

## Prepare, enable, inspect

Prepare creates one of at most 16 in-memory, one-use tickets, lasting 25 seconds.
It changes no selection. Tickets bind the complete source revision. Enable
consumes its ticket even on rejected/uncertain attempts, re-reads the exact
native account/folder, checks expiry again after preflight, and rejects a changed
identity or revision.

Enable uses the provider's normal guarded `setFolderSelected` operation with
`selected:true`. Already selected matching targets are not recreated.
Deselection, reset, migration/rescue and target deletion are not exposed by this
protocol. Source mutation is serialized with managed account changes.

The selected reply requires a fresh matching identity, selected state and a
materialized target. Replacing a previously selected target is rejected. A lost
reply must be resolved with inspect; never blindly replay an enable ticket or
roll back a possibly completed setup.

The client must preserve its durable user choice before applying setup. That
frontend integration and the actual EAS data/confirmation path remain separate
work. Neither a local target, empty provider queue, folder timestamp nor this
selected reply proves a completed remote read/write. In particular, upstream
server-wins conflicts can discard the provider's queue item; Magnolie must retain
its own user intent and verify actual provider completion/readback before
declaring data synchronization successful.
