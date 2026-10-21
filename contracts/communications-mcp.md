# Communications MCP integration (#192)

## Native call context foundation

The private `call_context_read` adapter on Python and Windows exposes current
native authority and, when available, an authenticated event from the actual
current phone session. It does not query the phone OS. Both the envelope and
event explicitly carry `phone_status_queried: false`; `persisted` is false.

The source revision is native HMAC state bound to the profile, actual paired
key, current connection nonce, transport, freshly received capability/grant
controls, current local grants and selected event. A stored event alone cannot
establish provenance. Reconnecting creates a different source; events retained
from the previous connection do not become observations of the new connection.
The Windows adapter does not adopt `CurrentCall`'s durable fallback. Python binds
the peer/key when native session controls are accepted. No client-supplied peer
revision or book digest establishes this authority.

Observations are receipts for accepted events in the existing call engines.
They retain the actual connection, paired key, native receipt time and event
digest. Readback requires the engine's current event to match that receipt.
The public projection contains call reference, state, direction, phone timestamp
and native receipt timestamp; it omits telephone numbers, number-sharing status,
spam information and battery data. Call revisions use decimal strings so a
64-bit native revision is preserved exactly through JavaScript.

`permissions` reports the current capability/grant intersection for dial,
incoming state, answer and end. The existing command handlers must also enforce
their exact call identity, revision, lifecycle, protocol and adapter conditions.
An observation has scope `shared_call_state` or, for the existing Windows v2
outgoing-request authority, `outgoing_request`. The latter requires an accepted
event receipt for that exact current scoped call and can permit ending it
without enabling general incoming-state/end grants. It cannot expose another
call. Native local-grant revisions are included in the Windows source token so
revoking and re-enabling a grant does not restore a previously issued token.
Reading this context emits no GUI callback, starts no listener and sends no
network request. It provides no recipient-delivery or call-completion claim.
The Linux private IPC route validates exact identity fields; reads do not occupy
the transport mutation lock and can inspect the current connection while a new
transport setup is pending.

## Native command origins and reply routing

The existing `command_effect` store carries a local `gui` or `mcp` origin.
Legacy rows migrate to `gui`; the origin survives reopening and is retained or
deleted with the existing command. It is not part of any phone message. Ordinary
daemon dial/answer/end requests cannot select a private origin.

The same native dial/answer/end handlers can record the trusted private origin.
Result handling classifies the origin and updates the existing receipt in one
database transaction. Private results are routed to a native observer with the
actual peer/key and connection, rather than GUI command-status callbacks.
Private queued/revoked dial requests also stay out of those GUI callbacks.
When the originating owner is absent, a late result is not adopted by the GUI.
Normal authenticated call lifecycle events remain in the existing call engine.

This origin flag is routing metadata. Private command execution additionally
uses bounded native owners with opaque tokens and exact source CAS.

## Private native command owners

`call_actor_create` reserves a native owner without sending or creating a command
effect. The private handle contains a server-generated actor UUID and 256-bit
owner token. A separate `call_actor_start` allows the frontend to validate its
session/book context after receiving the handle before any dispatch can begin.
Reservations and active requests have a 15-second deadline, with at most four
active owners/workers and 128 retained records. Terminal records are retained
for 30 minutes. Status and cancellation require the exact owner and peer identity.

Start calls the existing dial/answer/end handlers with a native preparation
scope. That scope revalidates actual source authority before command persistence;
only return from the existing command writer establishes `receipt_persisted`.
The private sender validates the registered owner, exact channel/key, action,
operation reference and body before claiming one dispatch. Socket I/O happens
outside the source guard. An absent or retired owner cannot fall through to
ordinary GUI outbox replay. Cancellation stops waiting and future claims, with
`remote_recall_confirmed: false`; a claimed dispatch may have an unknown outcome.

The actual signed phone result must match the owner, channel, key, action and
operation/call reference before its deadline. Ordinary transport ACKs cannot
complete the operation. Legitimate call-state progress is allowed after dispatch;
the remaining control authority is still checked before accepting a result.
`reported` means the phone supplied a result, including a possible failure. A
phone-reported `submitted` does not confirm an established conversation.

Private Python dial requests use the same existing v1 dialer adapter without
enabling GUI call-monitoring/notification grants. Ordinary GUI requests retain
their existing grant behavior. This avoids treating an actor's result routing
as permission to enable unrelated GUI observations.

## Remaining connections

Public call context/start/status/cancel tools use frontend session-owned jobs
and matching strict schemas on both desktops. Native GUI/transport acceptance
is being completed. Queue acceptance and a transport ACK cannot establish an OS
call action. Existing dial/answer/end handlers and their command references
remain the execution engine. Native transport/GUI acceptance remains distinct
from physical handset/provider acceptance.

SMS uses the existing supported KDE adapter; the current Magnolie Notes phone
protocol does not offer SMS sending. History and planning use the existing book
records and scheduler. Plans require actual durable book save before external
handoff, including the existing restored-plan review rules. Routing and
notification preferences, SMS execution/history/planning, public schemas and
20-language handbook coverage remain in #192. Combined installed acceptance
remains in #113.
