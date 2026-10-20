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
Reading this context emits no GUI callback, starts no listener and sends no
network request. It provides no recipient-delivery or call-completion claim.
The Linux private IPC route validates exact identity fields; reads do not occupy
the transport mutation lock and can inspect the current connection while a new
transport setup is pending.

## Remaining connections

Public call tools, source-bound command execution/receipts and cancellation are
still being connected. Queue acceptance and a transport ACK cannot establish an
OS call action. Existing dial/answer/end handlers and their command references
remain the execution engine. Private command replies need owner-bound routing
and lifetime checks before public actions are enabled.

SMS uses the existing supported KDE adapter; the current Magnolie Notes phone
protocol does not offer SMS sending. History and planning use the existing book
records and scheduler. Plans require actual durable book save before external
handoff, including the existing restored-plan review rules. Routing and
notification preferences, SMS execution/history/planning, public schemas and
20-language handbook coverage remain in #192. Combined installed acceptance
remains in #113.
