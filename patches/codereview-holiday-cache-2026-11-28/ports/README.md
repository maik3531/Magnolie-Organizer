# #855 – Mac/Tablet provider coverage parity

Base: `1749c92eb42801c38eaba31b272d8c0e27be9164`.

Both native services now include `abrufbereiche` with the country, requested
region, kind and complete requested year for each successfully parsed endpoint.
An empty valid page is confirmed coverage. School opt-out and a missing required
school region cannot certify a school scope. Existing atomic transport/parse
failure behavior remains in place. Tolerated malformed optional metadata and
rows inconsistent with the request are still available to the existing display
path, but cannot authorize deletion from the prior cache.

The official [OpenHolidays response DTO](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Dtos/Responses/HolidayResponse.cs)
requires `endDate` and `nationwide`. Missing, null or malformed values therefore
cannot certify replacement, even when the old parser can still display a row.
A non-national row with no geographical scope likewise cannot certify a
countrywide query. Scope validation matches the desktop candidate, including
canonical short codes and parent/child region relationships.

The Mac `fetch` API remains compatible; the application uses `fetchResult` to
forward the coverage alongside the ordinary rows. Tablet's existing callback
serializer forwards the new additive field. No persisted schema, provider,
permissions, installed packages or published releases changed.

## Actually executed

- The project-declared Kotlin compiler **2.4.21**, bytecode/JVM target **17**,
  executed on **OpenJDK 21.0.13.1** (Debian build `21.0.13.1+2-1-deb13u1-Debian`).
  The recorded `java` command resolves through `/usr/bin/java` to
  `/usr/lib/jvm/java-21-openjdk-amd64/bin/java`. Target 17 is a compiler setting,
  not evidence of execution on a Java 17 runtime.
- Complete actual `HolidayService.kt`, `DAV.kt`, `StandardBase64.kt` and the
  regular `HolidayServiceTest.kt` compiled together. No substituted model or
  Android transport stubs.
- **20 JUnit tests passed**, including four added coverage methods (multiple
  regions/years/kinds, confirmed empty pages, school opt-out, missing subdivision,
  malformed optional metadata, unrelated year/region and parent/child scope).
- Compiler emitted one pre-existing warning in `DAV.kt:41` about an unused
  expression; compile and JUnit exit codes are both zero.
- Input hashes before and after the run match, and `git diff --check` passed.

The final source-bound logs are `kotlin-final/compile.log`,
`kotlin-final/junit.log` and `kotlin-final/receipt.json`. Earlier candidate runs
are historical and are not the final source binding.

Compiler and dependencies were fetched to disposable scratch storage from
Maven Central. Exact URLs, sizes and SHA-256 are in `toolchain-manifest.json`;
ThreeTenBP additionally matched the repository's required JAR hash. Test network
responses come exclusively from the existing recording test transport.

## Remaining limits

**Swift is not compiled or executed in this environment.** Five Swift regression
methods accompany the candidate; native macOS verification remains open.
The JVM run is neither a full Android Gradle build nor a tablet, UI, installed
package or live-provider acceptance test.

## Replay

Prepare the exact declared artifacts with `download-kotlin-tools.py`, then run:

```sh
python run-kotlin-host.py --repo /path/to/Magnolie-Organizer \
  --compiler-cache /path/to/compiler-cache --output /path/to/new-test-output
```

The runner compiles product sources directly and invokes the regular JUnit test
class. It logs commands, exit codes and unchanged input hashes. Published evidence
should include scripts, manifests and text logs, but not downloaded compiler
JARs or generated test binaries.
