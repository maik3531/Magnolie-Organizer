# Calendar time-zone data

The calendar codecs use `org.threeten:threetenbp:1.7.5`, with the complete bundled
**TZDB version `2026egtz`**. The same `org.threeten.bp` implementation is used on
all supported Android versions. It does not use desugar's approximate
`java.util.TimeZone` rule provider, a sampled transition database, hidden Android
APIs, or a reflection bridge to platform time classes.

[The pinned artifact record](threetenbp-1.7.5.json) contains the artifact, POM,
TZDB resource and license SHA-256 hashes and the verified release-signing
fingerprint. The JAR and its published checksum/signature were downloaded from
[Maven Central](https://repo.maven.apache.org/maven2/org/threeten/threetenbp/1.7.5/).
The detached OpenPGP signature was verified using the key published by the
[project maintainer](https://api.github.com/users/jodastephen/gpg_keys), whose
identity is also recorded in the artifact POM. The dependency's BSD 3-Clause
[license is retained in the application's resources](../app/src/main/resources/third-party/ThreeTenBP-1.7.5-LICENSE.txt).

The Beta's `verifyThreeTenRuntime` Gradle task checks the resolved **debug**
runtime JAR and its TZDB resource before `preBuild` and compile/test tasks. It
does not replace repository-wide dependency verification. Release builds remain
disabled; enabling another runtime variant also requires extending this check.

The main artifact is required; the `no-tzdb` classifier must not be substituted.
Its class-file version is 50 (Java 6), and its timezone provider loads
`org/threeten/bp/TZDB.dat` from the packaged classpath. Calendar tests check that
the declared data version, complete historical transitions and unbounded future
rules remain available. Gap/fold tests include Morocco's two Ramadan changes
within ninety days, which the old desugar provider could miss. Independent
published Python and JVM `java.time` references cover history and years through
8000; the native test APK separately checks the packaged provider and external
golden clocks on Android.

This dependency assessment and JVM evidence do not establish Android 6 release
readiness. The minimum Android API must remain unchanged until native legacy
storage, packaging, lifecycle and calendar checks pass. A future database update
must update the pinned module, hashes, retained license and versioned test
expectations together, and rerun the independent timezone checks.

Native notification delivery consumes epoch milliseconds projected by the shared
JavaScript UI. This dependency change does not replace WebView `Intl` data or
prove reminder projection parity on older WebViews. That needs a separate native
wall-clock comparison against the bundled database and independent golden clocks.
