# MCP completion checklist (#170)

The implemented tool contracts and their platform limits are in [mcp.md](mcp.md).
This checklist follows existing user-facing operations. Native transport replies,
worker-internal messages and duplicate legacy command aliases are implementation
details, not separate product features requiring another public tool.

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

## Remaining operation groups

| Group | Existing product operations to finish connecting | Completion evidence |
| --- | --- | --- |
| Magnolienbaum | Enable/name/status, discovery and pairing, partner/trust/sharing settings, introductions, shared/delegated items, incoming-item handling and pairing-file operations | Existing identity/fingerprint guards, transport outcomes and acknowledged native state |
| Phone and KDE lifecycle | Status, available pairing/confirmation/removal/reconnect operations, offered permissions and Bluetooth lifecycle | Existing device/attempt/source identity guards and native receipts |
| Own Notes synchronization | Own-device selection, note/shared-book direction and operating preferences, existing initial/manual sync, contact/photo/profile transfer | Existing confirmed-peer and transaction gates; actual result/readback |
| Communications | Routing/notification preferences, dial/accept/hang-up, SMS send/history/planning through existing supported adapters | Existing call/command references, source/fingerprint checks, receipt versus delivery distinction |
| Other offered KDE actions | Existing drawing/input/device actions not already covered by media/filesystem tools | Current capability/source validation, existing permission handlers, truthful unsupported results |
| Running time tracking | Existing start/pause/resume/stop workflow, separate from completed-record CRUD | Shared time engine, clocks, running-record constraints and save acknowledgement |
| Remaining utilities/preferences | Existing contact-duplicate assistant, weather/medication lookup, developer/preferences, Thunderbird extension setup and application-support actions not represented by current settings/export tools | Shared product handlers, bounded typed results and actual launch/write outcomes |

## Acceptance gate

- Every offered user-facing action maps to an implemented tool or an explicit
  platform/capability limit; read-only metadata does not stand in for an action.
- Both desktop catalogs and input/output schemas agree. Real native handlers are
  exercised where available; fixtures and physical-device evidence are identified.
- Cancellation, late replies, active drafts, book/profile changes, save failures
  and native cleanup are covered by the relevant existing test harnesses.
- The connected Notes/developer/KDE paths participate in the overall installed
  acceptance. Source-only checks do not constitute that acceptance.
- New requested group/filter/send/category functions (#160/#177/#88/#183) extend
  this interface when implemented, before the combined local handover.

The checklist is complete only when these groups and the overall acceptance are
finished; an increased tool count is not itself a completion criterion.
