# MCP completion checklist (follow-ups to #170)

The implemented tool contracts and their platform limits are in [mcp.md](mcp.md).
This checklist follows existing user-facing operations. Native transport replies,
worker-internal messages and duplicate legacy command aliases are implementation
details, not separate product features requiring another public tool.

Issue #170 was closed after documenting its implemented scope and transferring
the unfinished work, not after overall acceptance. The open implementation is
tracked in #190 (Notes actor deletion/finalization), #192
(communications), #193 (remaining KDE actions), and #194 (remaining utilities,
preferences and contact/profile transfers). Cross-platform contract/catalog/
localization checks remain in #165, and combined installed acceptance in #113.
Closing the collection issue does not enable marker 12 or public actor tools.
The running-timer group from #191 is connected below.

## Connected groups awaiting overall installed acceptance

- Accounts: direct Graph public configuration/sign-out and asynchronous device-code
  lifecycle; managed Google/Outlook/Microsoft365 status/sign-in/edit/rename/removal.
  Shared native GUI handlers, actual local/status verification and platform gates
  are connected. Credential/OAuth fixtures are distinguished from physical login
  evidence. Thunderbird extension setup belongs to the utility/setup group below.
- Provider synchronization: shared GUI start/status workflow, receiver-confirmed
  native progress, three-way adoption, durable save/journal proof and stored
  provider-conflict read/decisions. Actual private Linux EDS write/readback and
  local conflict checkpoint/save acceptance complement the typed/transport tests.
- Magnolienbaum: shared native controls/discovery/public-address/pairing,
  partner/trust/sharing/introduction settings, pairing-document/file/QR operations,
  saved-content sharing/delegation/status, asynchronous notes/tasks/contact
  synchronization, contact preview/deletion proposals and digest-checked incoming
  adoption/manual or automatic contact decisions/remembered rejection. The GUI's
  batch matcher and staged contact adoption are shared; clients can process inbox
  IDs sequentially with fresh revisions and explicit unresolved decisions.
  Actual private Linux GTK/stdio/store/file/QR/checkpoint/save/readback acceptance
  and a real private encrypted peer-send/receipt/inbox test complement portable
  C# and both-frontend tests. Windows native QR rendering is explicitly unsupported.
- Requested feature groups: appointment/task categories and accent colors (#183),
  identity-bound anniversary/reminder group exclusions (#160), explicit contact
  group search with revision-pinned pagination (#177), and optional selected-note
  email/fax handoff (#88) are connected through their shared GUI/native handlers.
  Both frontend catalogs and strict results are checked. Private GTK acceptance
  includes actual palette/group persistence, selected PDF creation/readback and
  synthetic mail/fax adapter handoff; C# transport/job fixtures do not stand in
  for physical Windows MAPI or recipient delivery. Installed overall acceptance
  remains below.
- Phone device status: fresh nonce/source-bound general status and explicitly
  requested temporary identifiers use the existing request/report contracts and
  verified WLAN session. Native dispatch rechecks consent/source, consumes one
  ephemeral result and bypasses GUI/status/history/outbox caches. Cancellation,
  retired nonces and late replies are scoped. Private GTK/stdio acceptance uses
  a synthetic pinned phone context; C#/Python checks distinguish that from a
  physical handset authentication/read.
- Native Notes timers (#191): fresh state reads and source/state/restore-bound
  start/pause/resume/finish commands use the existing Notes timer handlers and
  encrypted book writer. Strict correlated reports distinguish actual durable
  saves from reads, transport ACKs and OS-runtime requests. Both desktop catalogs,
  owner-bound cancellation/late replies, private Linux IPC and 20-language
  handbook guidance are connected. Encrypted Python/C# TCP tests reopen the native
  Notes book and verify exactly four command receipts with idempotent replay.
  Physical handset runtime and combined installed acceptance remain below.

## Remaining operation groups

Own Notes progress: native consent/shared-preference read and single-field
updates are connected through the existing GUI handlers, with an independent
settings revision, explicit complete initialization choices, actual store readback
and no remote-delivery claim. Local ownership activation and deletion grants
follow the same existing handler. Explicit ownership confirmation/withdrawal is
also connected, preserving pairing and remote consent while using existing native
protocol cleanup. The existing legacy manual/automatic Wi-Fi and deletion choice
is also connected, explicitly rejecting shared-register peers. The existing
legacy note direction and custom/time enablement are connected with explicit
policy readback as well. Legacy time direction is connected through session-owned
save/reset jobs, whole-book/native CAS and verified policy epochs. Initial/manual
content synchronization and transfers remain in the group below.

| Group | Existing product operations to finish connecting | Completion evidence |
| --- | --- | --- |
| Phone and KDE lifecycle | Remaining KDE receive preferences/routing and offered lifecycle utilities beyond the connected pinned basic controls | Existing device/attempt/source identity guards and native receipts |
| Own Notes synchronization | Own-device selection, note/shared-book direction and operating preferences, existing initial/manual sync, contact/photo/profile transfer | Existing confirmed-peer and transaction gates; actual result/readback |
| Communications | Routing/notification preferences, dial/accept/hang-up, SMS send/history/planning through existing supported adapters | Existing call/command references, source/fingerprint checks, receipt versus delivery distinction |
| Other offered KDE actions | Existing drawing/input/device actions not already covered by media/filesystem tools | Current capability/source validation, existing permission handlers, truthful unsupported results |
| Remaining utilities/preferences | Existing contact-duplicate assistant, weather/medication lookup, developer/preferences, Thunderbird extension setup and application-support actions not represented by current settings/export tools | Shared product handlers, bounded typed results and actual launch/write outcomes |

Running timer control (#191) targets the existing native Notes timer owner. The
desktop completed-record engine deliberately rejects new running entries and
reopening completed ones; that boundary must not be bypassed by MCP CRUD. A
separately negotiated v13 native timer-command contract now carries remote
start/pause/resume/finish; TimeSync batches remain data rather than commands.

Phone-control progress within the lifecycle group: actual native connection
snapshots and enable/disable, pairing-window/attempt decisions, removal, editable
grants and Bluetooth preferences are connected. Linux local/daemon ownership,
store readback, scoped callbacks and private GTK/stdio acceptance are exercised;
portable C# checks also exercise a real private incoming pairing attempt.
General device-status/privacy reads are connected above; remaining KDE operations
and overall installed acceptance are still separate.

## Acceptance gate

- Every offered user-facing action maps to an implemented tool or an explicit
  platform/capability limit; read-only metadata does not stand in for an action.
- Both desktop catalogs and input/output schemas agree. Real native handlers are
  exercised where available; fixtures and physical-device evidence are identified.
- Cancellation, late replies, active drafts, book/profile changes, save failures
  and native cleanup are covered by the relevant existing test harnesses.
- The connected Notes/developer/KDE paths participate in the overall installed
  acceptance. Source-only checks do not constitute that acceptance.
- Requested group/filter/send/category functions (#160/#177/#88/#183) participate
  in the combined local handover and installed acceptance.

The checklist is complete only when these groups and the overall acceptance are
finished; an increased tool count is not itself a completion criterion.
