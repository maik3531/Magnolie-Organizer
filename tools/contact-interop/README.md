# Contact Interoperability Gate

This harness uses synthetic contacts, fresh native builds and isolated profiles.
It does not read real address books, install software, build releases or contact
external services. `CONTACT_INTEROP_HOME` must be under `/tmp/opencode/`.

## Coverage

- Current Linux launcher and Windows coordinator authenticate FS1 requests,
  reject forged/replayed messages, save peer capabilities, and queue replies.
- Capabilities do not change consent, and a transport ACK does not imply support.
- A rejected capability probe cannot block an old peer's representable v1 cards;
  an unrelated probe ACK cannot be reported as contact delivery.
- Strict v1/v2 contact codecs, separate receiving-version negotiation, required
  fields, value types, limits, dates and one-time import manifest/card matching.
- Current Android compiled `KontaktSync`, generated `KontaktDaten` serializer,
  `KontaktImportAblauf`, `Krypto` and `Sitzung` are used, not reimplementations.
- Both actual web applications perform import, localStorage save/reload, contact
  merge, revision comparison, legacy preflight, preview and explicit confirmation.
- Native parse -> web save -> native vCard/LDIF -> other desktop native parse,
  including second and third imports, original UID, independent/empty FN,
  missing given/family components, structured multi-value N, name parameters,
  address PO-box/additional components, unknown properties and yearless dates.
- Android-generated import manifests/cards travel through actual Android FS1
  encryption, the desktop native authenticated inbox, web preview and saved data.
- Existing translated error keys are checked in every Windows native catalog.
- Actual checksum-pinned Thunderbird ESR 140.8.0 imports the emitted vCards,
  including the vCards embedded in LDIF, saves them to its SQLite address book,
  and reads them back after a process restart. Its re-export is parsed by both
  desktop codecs and checked against the original contacts.

Yearless birthdays and all anniversaries select vCard 4.0, with RFC 6350 basic
dates (`--0229`, `19800229`), URI photos and explicitly text-valued phone/UID
fields. Cards with only a full birthday retain vCard 3.0 compatibility. Internal
and contact-sync dates remain canonical `--MM-DD` / `YYYY-MM-DD`.

## Run

First compile the current Android debug/test classes. In this workspace the
isolated offline Gradle wrapper is `/tmp/opencode/android-fixes-20260907/gradle.sh`:

```sh
bash /tmp/opencode/android-fixes-20260907/gradle.sh :app:testDebugUnitTest \
  --tests '*KontaktVersion2Test' --tests '*KontaktProviderRegressionTest' \
  --tests '*KontaktSyncTest' --tests '*KontaktImportTest' --tests '*KontaktEingangslogikTest'
```

Run that command in `magnolie-notes-1.0.13`. Build the Windows core with .NET
8.0.408 and the harness entry point, in `Magnolie-Organizer-Windows-2.0.0`:

```sh
CONTACT_INTEROP_HOME=/tmp/opencode/contact-integration-20260907 bash ../tools/contact-interop/sandbox.sh \
  /tmp/opencode/dotnet-8.0.408/dotnet build tests/CoreTests.csproj \
  --configfile /tmp/opencode/native-exchange-fixes-20260907/NuGet.Config \
  -p:BaseIntermediateOutputPath=/tmp/opencode/contact-integration-20260907/obj/ \
  -p:OutputPath=/tmp/opencode/contact-integration-20260907/bin/ \
  -p:CustomAfterMicrosoftCommonTargets="$(realpath ../tools/contact-interop/windows.targets)" \
  -p:UseSharedCompilation=false -p:NuGetAudit=false
```

Prepare the official Thunderbird test copy once, then run from the canonical
repository root. Preparation downloads only into scratch space, verifies the
pinned SHA-256 and copies test configuration; it never installs Thunderbird:

```sh
CONTACT_INTEROP_HOME=/tmp/opencode/contact-integration-20260907 \
  /usr/bin/python3 tools/contact-interop/thunderbird.py
CONTACT_INTEROP_HOME=/tmp/opencode/contact-integration-20260907 bash tools/contact-interop/sandbox.sh \
  /home/maik3531/.bun/bin/bun tools/contact-interop/run.js
```

The canonical `sandbox.sh` uses Bubblewrap with a read-only host/repository, a private
temporary filesystem and no external network. HOME, XDG paths and SDK home are
isolated, including a writable mode-0700 `XDG_RUNTIME_DIR`; ASP.NET certificate
generation is disabled. `run.js` uses
`/usr/bin/python3`, the existing Windows jsdom dependency and the installed
read-only Kotlin dependency cache. The scratch `evidence.json` contains only
synthetic contacts and emitted protocol objects.

Run the complete Linux script suites, without pytest collection or selections:

```sh
bash tools/contact-interop/sandbox.sh /usr/bin/python3 magnolie-organizer-2.0.0/pruefungen/test_parser.py
bash tools/contact-interop/sandbox.sh /usr/bin/python3 magnolie-organizer-2.0.0/pruefungen/test_import_export_vertrag.py
```

Thunderbird runs with private Xvfb/DBus, software OpenGL and a minimal keyboard
map compatible with the installed X server. No host desktop services are
activated. The pinned ESR emits `uncaught exception: undefined` at shutdown even
for an empty profile. The gate runs that empty-profile control first, records the
diagnostic and requires import/reload diagnostics to match exactly. A diagnostic
during contact processing, any additional warning or a changed diagnostic fails
the gate; no warnings are filtered away or turned into xfails.

## Scope Limits

This is not a Windows UI/DPAPI or Android device/background-service/R8 release
certification. Android provider behavior is separately tested by
`KontaktProviderRegressionTest` using the actual adapter with an in-memory
ContactsProvider fixture, including N/FN metadata and both event types.
Actual third-party LDAP clients may discard `magnolieVCard`; losslessness applies
to the two updated Magnolie codecs, not to clients that remove that extension.
Live mailbox, external CardDAV/EDS accounts and real ContactsProvider account
aggregation are not exercised. The shared sync projection is exactly the v2
schema, not an arbitrary vCard attachment; opaque non-name vCard properties are
preserved by file exchange, not added to the contact-sync DTO.

No catalogs were changed and there are no new visible msgids. Windows reuses
`Not sent.`, `The data is invalid.` and `Conflict`; Linux also uses its existing
`This type cannot be shared.` and contact-validation errors. Android reuses the
translated existing generic error for unsupported names, rather than falsely
claiming an anniversary is present. Its existing anniversary update error remains
specific to actual anniversaries.

## Implementation Files

Under `Magnolie-Organizer-Windows-2.0.0`: `BaumContactSyncContract.cs`,
`MagnolienbaumCoordinator.cs`, `MagnolienbaumPairing.cs`, `ExchangeCodec.cs`,
and `app/web/anwendung.js`.

Under `magnolie-organizer-2.0.0`: `bin/magnolie-organizer`,
`web/anwendung.js`, and the contact assertions in `pruefungen/test_parser.py`
and `pruefungen/test_native_import_regressions.py`.

Under `magnolie-notes-1.0.13/app/src/main/java/io/gitlab/maik3531/magnolienotes`:
`baum/KontaktSync.kt`, `baum/KontaktImport.kt`, `baum/KontaktEingang.kt`,
`baum/KontaktPruefung.kt`, `baum/AndroidKontakte.kt`, contact-related paths in
`baum/Baumwerk.kt`, and existing-resource selection for contact conflicts in
`ui/BaumBlatt.kt`. Focused Android tests are `KontaktVersion2Test.kt` and
`KontaktProviderRegressionTest.kt` in the corresponding `src/test/.../baum` tree.

The shared contract is `contracts/kontakt-v2.schema.json`; protocol coordination
is recorded in `magnolie-notes-1.0.13/KONTAKT-PROTOKOLL.md`. The remaining files
in this directory are test adapters and the interop runner, not application code.
