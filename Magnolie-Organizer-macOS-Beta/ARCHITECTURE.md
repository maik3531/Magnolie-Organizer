# Architecture And Contracts

## Read Before Porting

The source review covered these existing contracts, without editing them:

- `../magnolie-organizer/web/anwendung.js`: `Bruecke.sende`, `App.init`,
  `normalisiere`, acknowledged `speichern`, `App.gespeichert`, `vorBeenden`,
  `mutations_snapshot`, `edsStatus`, `pruefeErinnerungen` and export dispatch.
- `../magnolie-organizer/web/index.html`, `stil.css`, `i18n.js`, catalogs
  and fonts: canonical visual implementation and restrictive CSP.
- `../magnolie-organizer/bin/magnolie-organizer`: full-document storage,
  `verschluesseln`, `daten_verschluesseln`, `daten_entschluesseln`, ICS codecs.
- `../magnolie-organizer-windows/BridgeDispatcherContract.cs`: typed
  command envelope, duplicate rejection and 384 MiB upper bound.
- `../magnolie-organizer-windows/BridgeDispatcher.cs`: initialization,
  encrypted save gating, correlated save acknowledgements, unlock and native
  callback shapes. Windows is a separate projection, not the UI source copied here.
- `../magnolie-organizer-windows/EncryptionService.cs`: v1/v2 envelope
  markers, algorithms, salt/nonce/key lengths, AAD and PBKDF2 bounds.
- `../contracts/`: hashed shared contract context; no phone/contact/custom sync
  implementation is claimed merely because these contracts exist.

## Projection Boundary

`tools/project_ui.py` copies the complete live Linux `web/` and `symbole/`
trees into a generated build projection, including all catalogs and licenses.
It never copies an old Windows ZIP or previously built Linux release payload.

The transformations are explicit, occurrence-checked source bindings: transport
adapter, unknown-field preservation around normalization, save-before-encryption
and current-file-only password scope, unavailable native-service pages, no automatic
trash/tombstone deletion and the existing open-app reminder checker with a one-off
task alarm adapter. Organizer view/model code
and base styling are not manually forked. `Projection/` is platform glue only.

UI host tests use disposable projections from a captured current source state.
They neither assert that concurrent desktop edits are frozen nor leave a static
payload that a later build can accidentally pick up. Developer builds require a
fresh explicit freeze and reproducibility verification.

## Native Boundary

`Sources/MacBeta/main.swift` hosts WKWebView in a distinct AppKit application.
Only the bundled entry document's main frame can send native messages. The
handler is registered before load. Browser storage is ephemeral; the native
store, not localStorage, owns the profile. Navigation away from the local entry,
subframe commands, unknown commands, additional fields and wrong field types
are rejected. There is no general native eval, shell execution, download or
filesystem-path API. Native results use `callAsyncJavaScript` arguments, not
string interpolation of user content.

`Sources/BetaCore/Contract.swift` defines the executable command allowlist.
The generated JavaScript adapter's allowlist is derived from that enum, not a
second independently maintained command list. Swift still validates every
incoming request. Unsupported commands receive negative results; mutation
snapshot and save failures use the canonical callback/token/ID contracts.

No empty service snapshots are fabricated: some desktop status callbacks would
disable settings, advance sync state or replace metadata if given an empty
dataset. In particular, no EDS-shaped "success" is used for EventKit.

## One-Off Task Alarms

The A3 follow-up replaces only the task portion of the generated open-app checker.
`MacBeta.taskAlarms` derives early and due instants independently from actual
desktop task fields. IDs contain the record identity, UTC due instant, lead days
and UTC trigger instant. They do not depend on the title or display-zone spelling.
The canonical session deduplication set and `meldeErinnerung` callback are reused.

Source `DUE` values are reconciled with display fields, including an explicit UTC
instant within a DST fold. Calendar-day subtraction happens in the source zone;
the resulting wall time is resolved back to UTC. Unknown zones, contradictory
data and unsupported rich/recurring tasks cannot invent alarms. A nonexistent
wall time is skipped, not shifted. This is not durable scheduling: the native
menu consent gate and all open/unlocked/global/Custom gates remain unchanged.

## Simple ICS Reconciliation

The A4 follow-up keeps the narrow Swift serializer rather than introducing a
second full desktop ICS codec. The canonical editor can store both `ort` and a
raw `LOCATION`, plus raw DTSTART/DTEND after time edits. The exporter compares
supported raw properties with the structured serialization and emits one copy.
Known UTC/IANA time qualifiers are retained only with consistent paired time
representations. Contradictions, duplicate raw properties, unknown parameters,
recurrence, alarms, attendees, attachment links and provider data fail closed.

`tests/editor_regressions.mjs` drives the current generated task and appointment
editors. `tools/check_editor.py` hands the unchanged resulting records directly
to `CoreTests.testCurrentEditorAppointments`; neither a reduced handcrafted model
nor removal of `icsRoundtrip` stands in for real editor output.

## Storage Boundary

The store's missing-file result is distinct from all errors. Only a true `ENOENT`
under the exclusively leased private profile creates a new document. Existing
empty, corrupt, foreign, oversized, non-UTF-8, linked or non-private files fail
without initialization. A successfully loaded/unlocked document is required
before the shell permits saves. The adapter also fences saves before successful
UI initialization or while locked.

The native store retains the original whole JSON text, not a lossy Swift model.
Before saving, existing keys and record identities are compared. Missing objects,
shortened arrays or deleted records now require a durable pre-change checkpoint.
The normalizer still refuses record-dropping during load. It is not a merge engine
or a claim that every old profile can be loaded successfully.

Writes use an exclusive 0600 temporary file in the same directory, `fsync`,
macOS `F_FULLFSYNC`, rename and directory `fsync`. Save success is sent only after
all steps complete. The in-memory expected file is compared before each commit;
external modifications are not silently overwritten. An uncertain I/O outcome
poisons the session instead of retrying over possibly committed data. The lease
prevents two cooperative Beta processes sharing the profile. This is not a
security boundary against malicious code already running as the same OS user.

## Recovery And Restore Follow-up (2.0.18-beta.1)

`AtomicStore.checkpoint()` copies its expected on-disk bytes, never a decrypted
shadow. It checks the exclusive profile state, creates a private recovery directory,
synchronizes both directory creation and the new file, reads the copy back, and
rechecks the source. The structural no-loss comparison now selects this path before
a destructive save. `mutations_snapshot` returns the original token only after the
copy succeeds. Ordinary non-destructive saves retain the existing atomic path.

`BackupSelection` is a native-picker capability. It validates size, UTF-8, unique
JSON keys and document shape, allows explicitly selected nonprivate desktop files,
refuses symlinks/nonregular files, and pins both path and bytes. The web page cannot
substitute an arbitrary filesystem path at confirmation. No archive extraction occurs.

Restore waits for the canonical save ACK. Native code decrypts if needed, chooses
the existing encryption session (or the imported session for an unencrypted profile),
and asks the **current canonical normalizer** to preflight a temporary object.
No replacement happens before that succeeds. Native restore state and the adapter's
save fence block competing writes; quit is cancelled while this step is pending.
The selected bytes are checked again, the previous live file is checkpointed, and
only then is the replacement committed. The canonical restore callback discards its
old save queue and displays the new document without automatic tombstone/trash purge.
If UI acknowledgement fails after commit, the native save gate closes; the disk
file and pre-restore copy remain the authority on restart.

The regional handler also waits for a save ACK. `RegionalSettings` validates all
eight fields, preserves unknown preference fields and commits the updated full
document under the existing encryption policy before returning the shared callback.
Native standard menu strings are generated from the shared gettext-generated web
catalogs. Two native-only msgids (Undo/Redo) have an isolated 19-locale supplement;
English is the twentieth language through msgid fallback. Legacy Beta-specific
diagnostics/prose are still English and remain a localization gap.

## Encryption Implementation

`Sources/BetaCore/Encryption.swift` uses Apple CryptoKit AES-GCM, CommonCrypto
PBKDF2-HMAC-SHA256 and Security random bytes. No third-party crypto is embedded.

| Field | Contract |
| --- | --- |
| Marker | `magnolie-verschluesselt` |
| v1 algorithm | `AES-256-GCM/PBKDF2-SHA256` |
| v2 algorithm | `AES-256-GCM+DEK/PBKDF2-SHA256` |
| PBKDF2 | 240000 default rounds, accepted bounds 50000 through 1000000, UTF-8 password, 32-byte key |
| Sizes | 16-byte salt, 12-byte nonce, 16-byte GCM tag, 32-byte DEK, 16-byte DEK identifier |
| v1 AAD | UTF-8 marker |
| v2 wrapped-key AAD | `magnolie-daten-v2` + NUL + `dek` + NUL + raw DEK identifier |
| v2 content AAD | `magnolie-daten-v2` + NUL + `inhalt` + NUL + raw DEK identifier |
| Cipher encoding | Standard base64 of ciphertext followed by tag, nonce stored separately |

v1 reads prepare a v2 session, but unlock does not rewrite the original file.
The next successful save performs the upgrade. v2 saves retain the wrapped DEK
and unknown envelope properties while generating a fresh data nonce. The
decrypted JSON string is preserved byte-for-byte by the codec. Known temporary
DEK/derived buffers are cleared where practical; Swift/CryptoKit cannot promise
complete memory erasure of every managed copy. Passwords are not persisted or
logged. No plaintext reminder cache or keychain secret is created.

`tools/crypto_vectors.py` AST-selects the actual canonical Linux encryption
functions and uses public synthetic test entropy only in that fixture generator.
Committed fixtures are input for the Swift macOS crypto tests. Passing the Python
fixture tests alone does not establish that the Swift crypto port interoperates.
