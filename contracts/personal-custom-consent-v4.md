# Personal Custom Synchronization V4

Status: implemented in canonical desktop Python/C#/JavaScript and Android
sources. This is a read-only phone mirror, not a calendar/task import or a
Magnolienbaum feature. Production packaging/signing/publication is a separate
gate and has not been performed for this change.

## Compatibility Boundary

Do not add keys to the existing exact capability/grant objects or to the V1
`personal_sync.settings` body (`format`, `own_device`). Do not add custom items
to ordinary `task`, `note`, `notebook`, calendar or deletion records.

The support signal is version 4 in the existing `personal_tasks_sync`
capability version lists on both peers, with availability true. No capability
or grant key was added. Old peers continue ordinary synchronization using
their highest shared ordinary version in 1..3; V4 does not widen those codecs.

Only after bilateral support, `personal_sync.custom_settings` carries the exact
body defined in `personal-custom-consent-v4.schema.json`. Its fields are:

| Field | Meaning |
| --- | --- |
| `format` | Integer 4 |
| `scope` | Literal `custom`, never `tasks` or `all` |
| `enabled` | Explicit Boolean; missing local or remote state denies access |
| `revision` | Positive monotonically increasing safe integer per pairing/direction |
| `epoch` | Fresh lowercase UUIDv4 for every permission change |

Ordinary task grants, existing own-device settings and any existing All action
must never initialize custom consent to true. Both own-device flags are
necessary but not sufficient. Incoming run fences contain the sender epoch
and receiver epoch AND both respective revisions; all four must equal current
consent state. Revision checks prevent revival even if an older epoch is reused.
After off/on, an old run must remain unauthorized even though both switches
are enabled again.

`accept_custom_settings` / `AcceptCustomSettings` / `acceptCustomSettings`
reject lower revisions, same-revision changes and reuse of the immediately
previous epoch on a changed revision. Exact retransmissions are idempotent.
Senders MUST generate a fresh UUID for every new revision, never reuse an
older epoch, and refuse counter overflow rather than resetting the revision.

Desktop Python stores consent in the encrypted paired-peer file. Native C#
stores encrypted consent in SQLite, atomically with queued-data cancellation;
recovering an older JSON settings backup cannot restore that authorization.
Android stores consent and mirrors in the same encrypted, fsynced `Bestand`
commit. Apply, local consent changes and alarm delivery use the storage lock.
The runtime rechecks both captured epochs/revisions at final send/apply, not
just during staging. Data waits for the corresponding settings ACK. Settings
have queue priority so a full data queue cannot starve consent exchange.

An identical settings retransmission is idempotent and does not cancel pending
data. A changed revision cancels queued custom updates/requests. Unpairing
purges authorization and queues; retained Android copies are generation-bound
and cannot authorize a subsequent pairing. Failed persistence never produces
an accepted apply ACK. Ordinary grants and the existing All action remain
independent of this separate default-off opt-in.

## Stable Identity

`custom:` followed by the full lowercase SHA-256 of canonical UTF-8 JSON:

```json
["personal-custom-v1", "<persistent source UUIDv4>", "<original item ID>"]
```

The output is 71 ASCII bytes, below the ordinary 160-byte identity bound.
The original item ID is nonempty, well-formed Unicode, at most 640 UTF-8 bytes,
with no ASCII control characters or DEL. It is neither trimmed, normalized nor
truncated. The desktop normalizer permits 160 Unicode code points, hence the
larger input byte limit. Full hashes avoid ambiguous separator concatenation
and truncation collisions. Hash collisions still require fail-closed ownership
verification when applying records, not silent overwriting.

The desktop uses persisted `personalSync.actor_id` as the source UUID and
`personalSync.custom_revision` as its monotonically increasing source snapshot
revision. Both are durably saved before batches are handed to the transport.
The original custom item ID remains stable across edits, repeats, module moves
and restarts. Module IDs, module titles, item titles and occurrence dates are
NOT identity inputs. A copy/new item needs a new item ID. Another source UUID
has another mirror identity; a different paired source owner cannot overwrite
an existing mirror merely by claiming its source/item IDs.

## Data Messages

`personal-custom-v4.schema.json` describes two exact bodies:

- `personal_sync.custom_request`: format, sender/receiver epochs and revisions,
  and `trigger` (`manual` or `auto_wifi`). Only the phone sends this request.
- `personal_sync.custom_batch`: the same fence/trigger, plus `source_id`,
  `revision`, `upserts`, and explicit `deletions`. Only the desktop sends data.

A batch contains 1..32 combined distinct identities and at most 192 KiB of
canonical JSON. Requests/batches carry no ordinary run or ordinary task data.
`auto_wifi` is persisted as a Wi-Fi-only queue policy and checked on receipt.
Automatic reconnect/request processing can resend unchanged content to recover
interrupted delivery. The receiver idempotently applies each source revision.

An upsert contains `id`, `item_id`, `kind` (`task` or `appointment`), `hash`,
and `value`. These kinds exist only within the separate Custom protocol and
`Bestand.personalCustom.items`; ordinary collections are never populated.
The hash is canonical SHA-256 of the value. Values carry module identity/title,
item title/note, date/time/source timezone, completion, module/item reminder
choices, effective lead minutes, default reminder minute, and recurrence.
Only the item-owned note is exported. Custom text modules, `textItemId`, HTML,
attachments and dereferenced linked text are not in the allowlist.

The desktop traverses a captured, complete custom source, including completed
items and items/modules with reminders disabled. Missing records in a received
batch have NO deletion meaning. Scope withdrawal does not traverse/filter the
source into a deletion snapshot and never changes desktop source data.

The schemas document structural constraints; codecs also check canonical
integer syntax, valid dates/timezones, UTF-8 byte bounds, source-qualified IDs,
hashes, sorted unique explicit recurrence dates, and cross-field consistency.

## Recurrence And Alarms

Recurrence has exact keys `frequency`, `interval`, `until`, `dates`, `ordinal`,
and `weekday`. Frequencies are none/daily/weekly/monthly/yearly/custom;
interval is 1..3660. `until` is inclusive or empty. Explicit dates are sorted,
unique and limited to 1000; they are used only with custom frequency, whose
`until` is empty. Monthly weekday rules pair ordinal -1 (last) or 1..4 with
ISO weekday 1..7; other rules use ordinal/weekday zero. Tasks use frequency
none and appointments cannot be marked completed.

The original start occurrence is always included. Rules follow desktop Custom
semantics: monthly day 31 clamps to the last day of shorter months, and yearly
February 29 clamps to February 28 in non-leap years. Explicit Custom dates
supplement the original date. Repetition does not manufacture new item IDs.

Android calculates future alarms in the source timezone, not the phone's
current timezone. A nonexistent local time shifts forward by the DST gap;
overlaps use the earlier offset. Missing item time uses `default_minute`.
The desktop currently sends 08:00 as that default, zero lead for tasks and
the configured appointment lead for appointments. Module and item reminder
choices are preserved independently; either off, no date, or a completed task
suppresses its alarm. Desktop-wide notification enablement is local to the
desktop; the phone requires its own bilateral Custom opt-in.

The existing reboot, timezone, clock-change and exact-alarm-permission receiver
reschedules Custom alarms too. PendingIntents use a distinct Custom URI and
full source-qualified identity. Notifications are tagged by that identity,
labeled Custom/read-only, and offer no ordinary task completion action.
Persisted fired timestamps prevent replay notifications, including after
renames or restarts. A delivered one-off notification remains visible even
though it has no next alarm. Scope-off cancels alarms/notifications but retains
copies. Android may deliver inexactly if exact-alarm permission is unavailable.

## Source Deletion

An explicit deletion proposal carries `id`, `item_id`, `prior_hash` and the
enclosing source revision/fences. The desktop emits this only for an item
removed from its complete custom source traversal and known in its persisted
custom baseline. Android checks paired-source ownership and revision, pauses
the obsolete reminder, and retains the copy pending manual confirmation.
A hash difference is shown as a changed version, never silently deleted.

The Personal synchronization view provides read-only Custom items and an
explicit review dialog. Delete/Keep validates the exact pending revision and
current consent again. Delete removes the content while retaining an identity
tombstone; Keep retains a paused copy. Repeated proposals do not reopen an
already decided identical deletion. A newer source upsert can restore its own
mirror. Neither choice sends a deletion or edit back to the desktop.

## Localization

`personal-custom-ui.json` contains the six manually authored strings in all
20 supported languages. `tools/generate_personal_custom_ui.py` inserts only
the three desktop-visible strings into both PO sets and uses the existing
PO-to-JavaScript/native compilers. Android receives all six resource entries.
English is the source locale; every other locale has explicit translations,
not English fallback/fuzzy entries. Existing localized deletion/changed-version
and generic error strings are reused.

## Contract Checks

Run from the canonical release root. Python test-only dependencies are listed
in `magnolie-organizer/pruefungen/requirements-personal-custom-contract.txt`.

```sh
python3 -m pytest -q magnolie-organizer/pruefungen/test_personal_custom_consent.py magnolie-organizer/pruefungen/test_personal_custom_runtime.py magnolie-organizer/pruefungen/test_personal_sync.py magnolie-organizer/pruefungen/test_telefon.py
bun magnolie-organizer-windows/tests/personal-custom-consent.js
bun magnolie-organizer-windows/tests/personal-custom-snapshot.js
dotnet run --project magnolie-organizer-windows/tests/CoreTests.csproj --no-restore -- Telefonverbindung
```

The JavaScript test also runs with Node.js. The Android repository-local unit
selection (from `magnolie-notes`) is:

```sh
./gradlew :app:testDebugUnitTest --offline --tests '*.PersonalCustom*' --tests '*.PersonalSyncFormat2Test' --tests '*.PersonalSyncRevocationTest' --tests '*.TelefonQueueDatabaseTest'
./gradlew :app:testDebugUnitTest --offline -PmagnolieCrossTests=true --tests '*.PersonalCustomTransportTest'
```

Use the documented test SDK/JDK environment, and set
`MAGNOLIE_SCHLUESSEL_PROPERTIES` to a nonexistent test-only path so configuration
does not read production signing properties. Do not run release/signing tasks.

The cross test requires `MAGNOLIE_PYTHON`, `MAGNOLIE_DOTNET` and a freshly built
`PHONE_TEST_WINDOWS_DLL` pointing to CoreTests. It starts owned loopback TCP
hosts using the production desktop queues and encrypted channels, applies
their messages to encrypted Android storage, reopens storage before ACK, and
checks actual AlarmManager entries through Robolectric. Session key material
is synthetic; no real phone, user profile or credentials are involved.

These checks do not substitute for installed native Windows UI/device testing,
OEM background-policy testing or release acceptance. No production APK,
installer, signing, candidate manifest change or publication was performed.

## Verification Results

Verified against the canonical sources on 2026-09-11:

- Python Custom runtime/consent plus ordinary personal-sync/phone suites: 85 passed.
- Native C# phone/personal-sync group, including Custom persistence/revocation: passed.
- Both actual desktop JavaScript sources: identity/consent and snapshot tests passed.
- Android unit selection above: 27 passed, no skipped selected tests.
- Encrypted loopback cross-platform test: passed for both Python and C# senders.
- All new manual strings: matching Android resources in 20 languages, matching
  desktop PO/native translations, and deterministic JavaScript/MO generation.
- Edited source whitespace checks: passed.

The integrated pre-review on 2026-09-11 corrected the six KDE explanation
translations in nl/ar/zh_CN to retain the protected `SMS` token. Canonical source
extraction confirms that `A system KDE Connect service is active. Configure file
and clipboard sharing there.` is obsolete; its 19 translations remain as PO
history, while all 2358 current Linux keys remain active. No catalog-wide
reformatting or English fallback was introduced. Canonical JS/MO compilers were
rerun, and all 20 manually authored Custom locales still match Android, both
desktop PO sets and native JSON. Linux localization/source plus Windows source
extraction checks now pass all 20 tests.

Integration-test corrections also cover the new KDE diagnostic import, the
generated Custom callback/payload parity fixture, coordinator-to-WebView callback
forwarding, async ordinary synchronization with Custom default-off, the exact
Android task capability versions 1..4, and copy-preserving consent reset on
unpair. Exact capability/grant key assertions and ordinary payload shapes remain
unchanged. The complete Linux frontend suite and both parity tests pass.

The KDE presentation gate now includes the Ubuntu/Kubuntu 26.04 target in both
README download tables, and its test derives the expected link count from
`kde_profiles.PROFILES`. This source correction does not authorize publication.
Read-only packaging preflight also remains blocked by host accessibility-bus
diagnostics, missing Ubuntu 26.04 build rootfs, an unconfigured QEMU test image,
and deliberately unavailable production signing/branding/candidate inputs.
All 13 runtime helpers match DEB/RPM/Flatpak/AppImage inventories. These source
checks do not authorize a production build, signing or publication.
