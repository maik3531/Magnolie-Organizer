# Android 6 / API 23 compatibility audit — Refs #121

This is preparation for broader public tablet support. The currently declared
minimum remains API 26. The changes below do not establish API 23 runtime
acceptance and do not claim that a tablet's manufacture year proves compatibility.
Notes product sources are unchanged.

## Confirmed runtime gaps

| Area | Existing dependency | API 23 assessment |
| --- | --- | --- |
| Calendar/holiday codecs | `java.time`, `ZoneRules`, future transition rules | Native API 26. Official desugaring can supply classes, but its legacy rules implementation needs separate history/future validation; it cannot justify fabricated VTIMEZONE rules. |
| Vault and DAV files | `java.nio.file`, `File.toPath`, POSIX modes/owner/symlink checks, atomic rename | Native API 26. The examined NIO desugaring fallback does not preserve these contracts; see below. |
| Directory durability | Shared `FileChannel.open(Path, READ).force(true)` | Examined desugared Linux provider explicitly rejects directory channels. Notes source must remain unchanged; an Android-native injected implementation is needed. |
| Portable backup | `PBKDF2WithHmacSHA256` named factory | Android's named platform factory starts at API 26. The prepared fallback uses existing JCA `HmacSHA256`, identical UTF-8 password conversion, 210000 iterations and a 256-bit key. No SHA-1 fallback or provider installation. |
| Base64 | `java.util.Base64` | Native API 26; explicitly present in the pinned desugaring configuration's API <=25 rewrites. |
| Notifications | Channel creation/channel Builder API 26; `areNotificationsEnabled` API 24 | Prepared API-26 guards plus official AndroidX `NotificationCompat` / `NotificationManagerCompat`, pinned `androidx.core:core:1.13.1`. IDs, private/public text, scheduling and receipt rules remain the same. |
| Password entry | `importantForAutofill` API 26 | Prepared API-26 guard. Password text remains hidden and not persisted in profiles. |
| WebView Safe Browsing | Framework setter API 26 | Prepared official WebSettingsCompat feature test/setter; no call into a missing platform API. External WebView navigation/resources remain blocked independently. |

Android Keystore AES/GCM, `KeyGenParameterSpec`, immutable pending intents,
`setAndAllowWhileIdle`, runtime permissions and typed `getSystemService` are
available at API 23. No cryptographic, certificate-validation or HTTPS policy is
relaxed by this preparation.

## Examined official desugaring artifacts

Retrieved over HTTPS from Google's Android Maven repository and checked against
its published SHA-1 sidecars; SHA-256 recorded independently:

- `com.android.tools:desugar_jdk_libs_nio:2.1.5`:
  `d8044befae095781b9a80bf1faa92edc30382d75d437476784c1bf991598a976`
- `com.android.tools:desugar_jdk_libs_configuration_nio:2.1.5`:
  `7db51661cd07d1fd5cf12769a75ba201910624bb3801c09363dd3cb28e31c51b`

The configuration requires compilation API 30 or newer (this project uses 35).
Its API <=25 block rewrites time, Base64 and NIO classes. These are compilation
configuration thresholds; they must not be mistaken for proof of per-device
native time/file-system behavior in an APK compiled with minSdk 23.

In the upstream 2.1.5 source tree at
[`ec1741f99ecc2c6595cd91e8f2c0f8298af03eed`](https://github.com/google/desugar_jdk_libs/tree/ec1741f99ecc2c6595cd91e8f2c0f8298af03eed),
`jdk11/src/addon/java/desugar/sun/nio/fs/DesugarLinuxFileSystemProvider.java`:

- `newFileChannel` rejects directories explicitly.
- `readAttributes` / attribute views support basic attributes, not the required
  POSIX owner/mode contract.
- `move` delegates to `File.renameTo` without checking its boolean return.

A blanket NIO desugaring substitution is therefore insufficient. Lowering the
minimum requires public Android `android.system.Os` operations (available since
API 21) or an equally verified implementation for rename, directory fsync,
symlink/owner/mode checks, injected into production storage. Failure checks and
commit/readback outcomes must remain authoritative. No NIO backport has been
silently substituted in this preparation.

## Time-zone data is also a blocking contract

The inspected desugared `ZoneRulesProvider.TimeZoneRulesProvider` wraps
`java.util.TimeZone`; its rules do not expose complete historical transitions and
future transition rules. A separate artifact probe demonstrated empty history/
future lists for named regions. A named region must not consequently be exported
as a fabricated fixed-offset zone. API 23 has no public Android ICU API; the
public API 24 surface also does not supply the complete transition/rule classes
needed here. Existing complete embedded VTIMEZONE data, proven fixed offsets and
UTC are separate cases. A complete trusted time-zone backport or a verified public
platform bridge for newer devices is needed before claiming full named-zone
export parity from a minSdk-23 build.

## WebView is a separate requirement

`WEB_MESSAGE_LISTENER` must be supported by the installed WebView provider.
That feature alone does not prove the shared UI works: the canonical UI also
uses `Array.at`, `Object.hasOwn` and `inert`, requiring a substantially newer
renderer than the stock Android 6/7 images. The relevant Chromium feature
baselines are 92, 93 and 102 respectively. The shipped UI and its security/save
fences need an actual supported, updated WebView, not a device-year assumption.
Optional Intl APIs already have canonical fallbacks. No arbitrary WebView APK,
certificate bypass or modified provider signature is part of this work.

## Verification and outstanding acceptance

Prepared host tests verify published PBKDF2-HMAC-SHA256 vectors, Unicode/NUL/
supplementary/malformed UTF-16 conversion against the named JCA factory, the real
210000-iteration key and portable-envelope interoperability in both directions.
They do not establish the availability or behavior of Android 6's actual JCA,
Keystore, POSIX provider or WebView.

Before declaring API 23 support, native evidence must cover first save/reopen,
private mode/owner/symlink checks, rename/fsync/readback failures, Keystore-backed
vault and DAV credentials, portable backup roundtrips, calendar/holiday time-zone
rules, notifications with channels absent, SAF and a sufficiently recent WebView.
A mere minSdk edit or an SDK-35 emulator run cannot satisfy these checks.
