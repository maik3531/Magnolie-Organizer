# Magnolie Notes für F-Droid

## Öffentlicher Bau ohne Produktionsschlüssel

Magnolie Notes verwendet GPL-3.0-or-later; siehe die übergeordnete
[`LICENSE.md`](../LICENSE.md) und den dort verlinkten vollständigen Lizenztext.
Die Android-App verwendet AndroidX/Compose, Kotlin Serialization,
Bouncy Castle und libphonenumber. Sie benötigt weder Google Play Services
noch Firebase und kann ohne Konto als lokales Notizbuch verwendet werden.

Voraussetzungen: OpenJDK 17, Android SDK Platform 35 und die vom Android-
Gradle-Plugin verwendeten Build Tools. Gradle 8.13 ist über den geprüften
Wrapper festgelegt; Abhängigkeitsversionen und Prüfsummen sind eingecheckt.

Aus dem Verzeichnis `magnolie-notes`:

```sh
./gradlew --no-daemon --dependency-verification strict \
  -PmagnolieFdroid=true :app:assembleRelease
```

Ergebnis: `app/build/outputs/apk/release/app-release-unsigned.apk`.
Der Bau verwendet weiterhin R8 und Ressourcenoptimierung. Er liest keine
Signier-Properties ein und bindet auch dann keinen lokalen Schlüssel ein,
wenn auf dem Baurechner eine offizielle Signierkonfiguration vorhanden ist.
F-Droid kann die APK anschließend über seinen eigenen Veröffentlichungsweg
signieren. Der private Magnolie-Schlüssel wird dafür nicht benötigt.

Ohne `-PmagnolieFdroid=true` bleibt der bestehende offizielle Signierweg
erhalten. Der offizielle Releaseprüfer kontrolliert zusätzlich das
Produktionszertifikat und die Update-Kompatibilität.

## Signaturen und bestehende Installationen

Android akzeptiert ein Update unter derselben Anwendungskennung nur mit einer
passenden Signatur. Eine durch F-Droid selbst signierte APK ist daher nicht
automatisch ein direktes Update einer bereits über GitHub/GitLab installierten
Magnolie-APK. Vor einem Wechsel zwischen unterschiedlich signierten Ausgaben
ist eine exportierte Sicherung erforderlich. Die bisherigen offiziellen
Updates behalten ihre bisherige Signatur.

Eine Übernahme der vorhandenen Entwicklersignatur durch F-Droid kommt nur in
Frage, wenn F-Droid den veröffentlichten APK-Inhalt reproduzierbar nachbauen
und die Signatur entsprechend überprüfen kann. Ein erfolgreicher unsignierter
Bau allein ist noch kein Nachweis dafür.

Die lokale Gegenprobe für 1.0.17 mit `apksigcopier compare --unsigned` gegen
die bereits veröffentlichte APK war erfolgreich: Die kopierte öffentliche
APK-Signatur verifiziert den neu gebauten Inhalt. Die Einreichung kann deshalb
F-Droids Verfahren mit übernommener Entwicklersignatur verwenden. Die
Wiederholbarkeit auf F-Droids eigener Infrastruktur wird dort nochmals geprüft.

## Aufnahme

Die Aufnahme wird im F-Droid-Projekt geprüft. Buildrezept, Quellenstand,
Prüfergebnisse und Antragslink werden in
[Issue #72](https://github.com/maik3531/Magnolie-Organizer/issues/72) geführt.
Diese Dokumentation behauptet keine bereits erfolgte Aufnahme.
