# Calendar time-zone data

Calendar named-zone conversion and VTIMEZONE generation use the shared normative
[TZif/POSIX payload](../../port-adapters/timezones/tzdb-2026egtz.json), version
`2026egtz`, schema2: 597 identifiers and 439 models. The approved payload SHA-256
is `2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c`.
Its [provenance](../../port-adapters/timezones/provenance.json) records the pinned
Global-TZ source and independent zic/CPython verification. Original aliases,
second offsets, historical transitions and unlimited POSIX tails are retained.
No named-zone rules come from BP, the operating system, desugaring or sampling.

The `prepareNormativeTimezones` Gradle task verifies the shared source hash and
copies that one JSON plus its license into generated Java resources before
compilation/packaging. The portable provider verifies the resource hash again,
validates the model and caches immutable rules. Missing or changed resources fail
closed. Source VTIMEZONE definitions remain calendar-scoped and take precedence
over named-provider lookup. Gregorian arithmetic uses explicit UTC coordinates.
Annual VTIMEZONE patterns are proven over the entire 400-year Gregorian cycle;
month-crossing wall clocks can use disjoint annual predicates, with no finite
future RDATE horizon.

The signed dependency `org.threeten:threetenbp:1.7.5` remains solely for Gregorian
value/arithmetic classes. Its named-zone provider has a
[confirmed Gaza2074 and later defect](../../port-adapters/timezones/diagnostics/BP-PROVIDER-BLOCKER.md)
and is not a semantic reference or fallback. The JAR is not patched, replaced by
a no-tzdb artifact, or registered as a global replacement provider.

[The pinned artifact record](threetenbp-1.7.5.json) retains the JAR, POM, bundled
TZDB and license SHA-256 hashes and verified release-signing fingerprint. The
published checksum and OpenPGP signature were verified against the maintainer's
public key. Its BSD3 [license](../app/src/main/resources/third-party/ThreeTenBP-1.7.5-LICENSE.txt)
remains packaged. `verifyThreeTenRuntime` still checks the exact dependency and
resource bytes before build/test; that identity check does not establish the
correctness of BP's timezone conversion.

Portable provider points are checked against the independent pinned zic/ZoneInfo
oracle. Production-codec regressions include the actual shared UI saved-record
shape and Gaza2074's correct 09:30Z. Emitted VTIMEZONE interoperability is checked
through the byte-verified published Python parser. These checks do not establish
native Android SDK, resource packaging, old-device or lifecycle acceptance.
Minimum API remains unchanged until the corresponding native gates pass.

Reminder epochs still originate in shared JavaScript. Kotlin codec migration does
not replace WebView Intl or prove UI/reminder parity; that is a separate shared
provider integration and native wall-clock acceptance task. Any data update must
change the shared payload/provenance, approved hash, tests and generated resource
expectations together and rerun independent conversion and export checks.
