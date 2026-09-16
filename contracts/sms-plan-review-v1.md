# SMS plan review / restore contract v1

Applies to the Linux and Windows desktop sources. Scheduling runs only in the
open, initialized, unlocked frontend with a uniquely available KDE Connect phone.

## Live permission and restored content

`einstellungen.adressen.smsSchedulingEnabled` defaults to **false**. Only boolean
`true` is permission. Full backup, complete-archive and full snapshot restore keep
the **live installation's** value, never the archive's value; a new profile without
live permission stays off. This does not change other phone/own-device preferences.

Full restore retains the archived plans as contents, with these state transitions:

| Archived state | Restored state | Automatic submission |
|---|---|---|
| `planned` | `paused` | No; individual review and enable required |
| `paused` | `paused` | No; individual review and enable required |
| `submitting` | `uncertain` | No retry; the earlier effect may have occurred |
| `queued`, `submitted`, `uncertain`, `sent`, `failed` | unchanged | No retry |

Plan IDs, recipient, country, text, original draft, time, client reference and
failure metadata are retained. Archives continue to contain the full scheduling
preference, plans and SMS history; archive creation does not erase SMS content or
rewrite the live permission. The restore operation prepares a separate live copy.

Snapshot selections `contacts`, `calendar`, `notes` (alone or combined, replace or
additive) do **not** select SMS plans or scheduling preferences. They preserve the
live SMS collection. Only `all` selects archived SMS plans. The Windows restore
wrapper must forward `restoreSmsPlans: areas.Contains("all")`; full restore calls
use the default `true`. Linux uses the same `bereiche == {"all"}` boundary.

The settings toggle pauses/resumes existing live `planned` work, including overdue
plans. It cannot activate a restored `paused` plan. Per-plan **Review and enable**
shows its exact recipient, country, scheduled time and outgoing text. **Enable
this SMS plan** is a separate explicit action, available only with local scheduling
on. It does not change that preference. The dialog explains that overdue work may
be handed off after enable. Closing/cancelling review changes no plan metadata.

## New plans and text approval

**Schedule SMS** opens a preview; it does not insert or save a plan. Every row,
including unchanged GSM text, is previewed with its actual normalized recipient,
country, due time and the exact trimmed GSM-converted text that will be stored and
sent. Unsupported-script replacements (`?`), emoji substitutions, combining-mark
loss and whitespace changes therefore cannot enter a new plan without review.

**Confirm SMS plans** accepts that entire displayed batch. A SHA-256 digest and an
exact serialized batch bind the preview to the original draft, outgoing text and
metadata. Approval is in-memory only, bound to its own preview generation and the
current data object. Input/change, row addition/removal, cancel, close, lock or
restore invalidate it. A stale button cannot approve even a later identical
preview. Confirmation rechecks the current batch, including programmatic changes
without an input event. No approval is inferred from archive hashes.

Accepted plans retain `originalText` verbatim (up to the input's 5000-character
bound). Fields are disabled while the creation save is pending; success is shown
only after durable Save ACK. On save failure, the unsent inserted rows are removed
from the in-memory batch and the original editor values remain for correction or
retry. No existing plans are silently evicted to make room for a new batch.

## Durable submission and replay

New/re-enabled rows are ineligible while their approval save is pending. The
scheduler then persists its `submitting` reservation/history and waits for that
save's ACK before handoff. Late/stale ACKs, restore, lock, revoked permission or
changed phone cannot authorize a handoff. A changed recipient/country/text/time/ID
while this save is pending pauses the plan for review.

Submission uses the exact stored text and country with stable `plan:<id>`; review
never allocates a replacement ID for restored work. The Linux SQLite and Windows
digest-only native submission journals reserve before the external effect. They
are not restored/cleared with content archives, reject changed payloads for the
same ID and suppress already-reserved work across restarts. A fresh installation's
empty journal is not permission: restored unknown IDs remain paused at the UI
boundary. `queued`/`submitted` mean handoff, never proof of delivery.

## Reproducible source tests

- `python3 -B magnolie-organizer-2.0.0/pruefungen/asr_sms_restore.py`: real Python
  restore function and small offline .NET host containing current Windows restore,
  selection, submission and journal sources; feeds native results through all
  three restore callbacks of both complete jsdom frontends. Approved Unicode
  captures then traverse both native submission/journal paths with captured effects.
- `bun Magnolie-Organizer-Windows-2.0.0/tests/asr-sms-regressions.js`: complete
  frontend DOM interactions, delayed ACKs, original drafts, batch/stale approval,
  partial/full restore fixtures and per-plan enable.
- `bun Magnolie-Organizer-Windows-2.0.0/tests/planned-sms-save-regressions.js`:
  pre/post-save failures, stale ACKs, lock/restore and default-off lifecycle.
- `python3 -B tools/asr_sms_locales.py --check`: seven manually authored messages
  in all 20 UI languages; both PO/POT/JS sets, Linux MO and Windows native catalog.

Run sequentially under `systemd-run --user --scope -p MemoryMax=6G
-p CPUQuota=200% taskset -c 0,1 ...`. Tests use temporary synthetic profiles and
captured transport. These checks do not claim a native WebView/OS/phone test or a
release build.
