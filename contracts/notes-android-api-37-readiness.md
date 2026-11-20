# Notes: Android 17 / API 37 migration boundaries (#558, #648, #691)

Current migration candidate and native matrix:
[notes-691-target37-migration.md](notes-691-target37-migration.md).
This is a source review, not native Android acceptance.
The current user authorization governs build and device checks. Source review
does not authorize signing, installation or Store publication by itself.

The user reports that Notes already runs on their Samsung with Android 17.
Preserve this positive real-use report; no current Android-17 startup failure
is claimed. Running on Android 17 and targeting API 37 are different facts.
The installed artifact's version/target and feature-by-feature results have
not been independently recorded in this review. This does not invalidate the
reported working installation or authorize replacing it.

## Reviewed baseline

After #672 the Notes source uses compile SDK 37.2, product `targetSdk = 35` and
`minSdk = 26` in `magnolie-notes/app/build.gradle.kts`. Its version catalogue
selects AGP 9.5.1 and Kotlin 2.4.21; the wrapper selects Gradle 9.6.0. The build
requires a JDK 21 toolchain with Java/Kotlin bytecode targeting 17.

The official Android 17 setup page specifies SDK 37. The current Google Maven
metadata reports stable AGP 9.5.1; the AGP 9.5 compatibility page supports API
37 and requires Gradle 9.6.0. These are review inputs, not an instruction to
install tools or blindly change version numbers. The setup page's generic
8.9.0-rc01 lower bound alone does not establish that a particular older plugin
supports the complete API-37 build. AGP/Kotlin plugin and DSL migration must be
checked together. Keep `minSdk` independent; a new target API does not justify
dropping supported older devices or replacing every device's current API path.

## Local network: confirmed migration gap, not an API-35 regression

For apps targeting 37 or later on Android 17, the platform requires
`android.permission.ACCESS_LOCAL_NETWORK` for outgoing **and incoming** local
TCP, UDP unicast/multicast/broadcast, and NSD discovery/resolution. This also
applies to local connections originating in WebViews.

The normal manifest does not declare that permission. #648 added runtime guards;
#691 couples an explicit unsigned target-37 candidate with its own LAN overlay
and extends the lifecycle, routing and receive checks. Native acceptance is still
open. This is not proof that the currently targeted API-35 application is broken.
The official guidance explicitly says **not** to declare
or request this permission while targeting 36 or lower. Do not add it to the
current manifest as a disconnected speculative fix.

| Actual Notes source | Required migration review |
| --- | --- |
| `MagnolieApp.kt`, saved `dienstAn` restart | Resume only permitted transports; no permission dialog from startup. |
| `baum/BaumDienst.kt`, `Baumwerk.kt` | Separate visible enablement, background resume, periodic work and revocation. |
| `baum/Server.kt` | Check incoming TCP and both directions of UDP traffic, not only outbound discovery. |
| `baum/Entdeckung.kt` | Include NSD registration/discovery and later permission loss. |
| `telefon/TelefonEntdeckung.kt` | A permission denial must not be misreported merely as “no peer found”. |
| `MainActivity.kt` | Re-read the actual grant, invalidate stale request lifetimes and never replay a captured peer/source action. |

An existing Bluetooth grant may allow platform pre-grant within the common
nearby-devices group. It is not a substitute for reading the actual local
network permission. Empty permission-result maps, saved enabled flags, peer
authentication and loaded histories are not permission evidence either.

A system-mediated NSD picker can authorize a selected destination where the
platform provides that capability. It does not by itself authorize arbitrary
incoming server connections, multicast discovery or other peers. Select a
picker only where its actual granted capability fits the operation.

Required behavior remains: consciously enable once, then quietly wait for
connectivity; resume after return without recurring consent dialogs. Denial or
revocation holds only the affected transport and preserves accounts, pairing,
canonical book IDs and independent synchronization consent. Do not grant LAN
access from Wi-Fi status or treat LAN permission as contact-write authority.
Bluetooth and offline editing must not be disabled just because LAN is held.

The older-device path remains platform-appropriate `INTERNET` access without a
new unsupported prompt. APK, F-Droid and Play builds share this Android source.
Desktop counterparts may observe unavailable Notes transport; they do not gain
Android permission by changing their own grants. iPhone integration through
existing apps remains a different counterpart, not a new iOS Notes app.

## Other checked behavior-change intersections

Android 17 restricts account columns in `ContactsContract.Data`. The inspected
contact snapshot in `baum/AndroidKontakte.kt` already reads account identity
from `RawContacts.CONTENT_URI` and joins data using `Data.RAW_CONTACT_ID`.
That is consistent with the documented migration direction. This bounded
source finding is not acceptance of every contact query or a real provider.
Preserve the exact account/raw-contact/source/version binding; do not replace
missing provider identity with a default book or display-name match.

The inspected main source does not declare `READ_SMS`/`RECEIVE_SMS` or directly
query the SMS provider. `TelefonModule.kt` does inspect the default SMS package
when classifying notifications. Therefore the new OTP-provider restrictions do
not justify adding SMS-reading privileges or claiming an exemption for Notes.
Notification delivery and companion behavior still require their own native
tests. No app-widget/`RemoteViews` implementation was found in this bounded
main-source search; no speculative widget bitmap patch is warranted.

## Remaining acceptance

The SDK/toolchain preparation is recorded in #672. The #691 candidate's actual
offline build, merged-manifest and unsigned-APK audits passed on 20 November
2026; the linked migration contract records their scope and host test results.
Native acceptance remains open. Check API/target
combinations, granted/denied/revoked permission, fresh setup,
restart, connection return, cancellation and late callbacks. Retain a concrete
older-device test. Remaining target/manifest and native matrix work is tracked
in #691 together with #558; #648 is the historical LAN-guard preparation.
None of these source observations activates the paused original-contact return
path or supplies its independent native system/provider evidence.

## Official references

- [Android 17 SDK setup](https://developer.android.com/about/versions/17/setup-sdk)
- [Android 17 target-specific changes](https://developer.android.com/about/versions/17/behavior-changes-17)
- [Android 17 changes affecting all apps](https://developer.android.com/about/versions/17/behavior-changes-all)
- [Local network permission and target-specific enforcement](https://developer.android.com/privacy-and-security/local-network-permission)
- [AGP 9.5 compatibility](https://developer.android.com/build/releases/agp-9-5-0-release-notes)
- [Google Maven AGP metadata](https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/maven-metadata.xml)
