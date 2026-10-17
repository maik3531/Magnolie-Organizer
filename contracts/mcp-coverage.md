# MCP completion checklist (#170)

The implemented tool contracts and their platform limits are in [mcp.md](mcp.md).
This checklist follows existing user-facing operations. Native transport replies,
worker-internal messages and duplicate legacy command aliases are implementation
details, not separate product features requiring another public tool.

## Remaining operation groups

| Group | Existing product operations to finish connecting | Completion evidence |
| --- | --- | --- |
| Accounts | Direct Microsoft sign-in lifecycle; direct Graph configuration/sign-out; existing Internet-account status/sign-in/rename/removal and Thunderbird setup | Actual account/OAuth handlers, cancellation and credential-commit gates; typed platform limits |
| Provider synchronization | Start/read/cancel/commit the existing synchronization transaction; existing contact/provider decisions and source routing | Existing recovery checkpoints, real provider result adoption, conflict decisions and durable save |
| Magnolienbaum | Enable/name/status, discovery and pairing, partner/trust/sharing settings, introductions, shared/delegated items, incoming-item handling and pairing-file operations | Existing identity/fingerprint guards, transport outcomes and acknowledged native state |
| Phone and KDE lifecycle | Status, available pairing/confirmation/removal/reconnect operations, offered permissions and Bluetooth lifecycle | Existing device/attempt/source identity guards and native receipts |
| Own Notes synchronization | Own-device selection, note/shared-book direction and operating preferences, existing initial/manual sync, contact/photo/profile transfer | Existing confirmed-peer and transaction gates; actual result/readback |
| Communications | Routing/notification preferences, dial/accept/hang-up, SMS send/history/planning through existing supported adapters | Existing call/command references, source/fingerprint checks, receipt versus delivery distinction |
| Other offered KDE actions | Existing drawing/input/device actions not already covered by media/filesystem tools | Current capability/source validation, existing permission handlers, truthful unsupported results |
| Running time tracking | Existing start/pause/resume/stop workflow, separate from completed-record CRUD | Shared time engine, clocks, running-record constraints and save acknowledgement |
| Remaining utilities/preferences | Existing weather/medication lookup, developer/preferences and application-support actions not represented by current settings/export tools | Shared product handlers, bounded typed results and actual launch/write outcomes |

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
