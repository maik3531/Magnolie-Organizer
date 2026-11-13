# Magnolie Notes für F-Droid

## Öffentlicher Bau ohne Produktionsschlüssel

Magnolie Notes verwendet GPL-3.0-or-later; siehe die übergeordnete
[`LICENSE.md`](../LICENSE.md) und den dort verlinkten vollständigen Lizenztext.
Die Android-App verwendet AndroidX/Compose, Kotlin Serialization,
Bouncy Castle und libphonenumber. Sie benötigt weder Google Play Services
noch Firebase und kann ohne Konto als lokales Notizbuch verwendet werden.

Voraussetzungen: vollständiges OpenJDK 21 mit Compiler, Android SDK Platform 35 und die vom Android-
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

Der zusätzliche verschlüsselte Abhängigkeits-Metadatenblock des Android-
Gradle-Plugins ist für APKs und App Bundles ausgeschaltet (`dependenciesInfo`).
Die eigentlichen App-Abhängigkeiten werden weiterhin durch die eingecheckten
Versionssperren und Prüfsummen überprüft.

Ohne `-PmagnolieFdroid=true` bleibt der bestehende offizielle Signierweg
erhalten. Der offizielle Releaseprüfer kontrolliert zusätzlich das
Produktionszertifikat und die Update-Kompatibilität.

## Paketbeschreibung und optionale Telefonfunktionen

Die Fastlane-Paketbeschreibungen liegen unter
[`../fastlane/metadata/android/de-DE/`](../fastlane/metadata/android/de-DE/)
und [`../fastlane/metadata/android/en-US/`](../fastlane/metadata/android/en-US/).
Sie beschreiben neben lokalen Notizen und Aufgaben ausdrücklich die optionale
**Magnolie Notes-Telefonverbindung** zum eigenen Organizer. Diese Verbindung
benötigt weder KDE Connect noch einen eingeschalteten Notizabgleich.
KDE-Connect-Funktionen verwenden eine andere Android-App und bleiben getrennt.

Die Langtexte erläutern die optionalen Netzwerk-, Bluetooth-, Telefon-, Kontakt-,
Benachrichtigungs- und Standortzugriffe mit ihrem jeweiligen Zweck. Die vorbereiteten
Bild-Leseberechtigungen `READ_EXTERNAL_STORAGE` (bis API 32),
`READ_MEDIA_IMAGES` und `READ_MEDIA_VISUAL_USER_SELECTED` gehören zum getrennten
Fotoquellenpfad. Sie werden nicht beim Start des Notizbuchs angefordert; die
vollständige Fotosynchronisation ist noch nicht freigeschaltet. Ein Fotozugriff
setzt die gesonderte eigene Organizer-Freigabe und eine aktuelle Android-Lesefreigabe
voraus, nicht bloß Kopplung oder Kontaktzugriff. Kamera-/Mikrofonaufnahme und
Bildschirmspiegelung werden nicht als bereits verfügbare APK-Funktionen beworben.

Neu vorgesehen, aber nicht freigegeben, sind ein eigener standardmäßig
ausgeschalteter Videoabgleich und ein optionaler Foto-Unterordner für Animationen.
Animationen wie GIF bleiben dem Bild-/Fotobereich zugeordnet, nicht dem Videoziel.
Video-Lesezugriff darf nicht aus Bild-Leserechten abgeleitet werden. Die momentan
deklarierten Bildrechte und die unten beschriebenen Paketprüfungen werden dadurch
nicht zu einer Videofreigabe. Bevor ein Video-Berechtigungspfad oder eine neue
Berechtigung freigeschaltet wird, müssen sein eigener Zweck und die tatsächliche
Abfrage gleichzeitig in Manifest, Pakettext und nativer Abnahme nachgewiesen sein.

Vor jeder Einreichung müssen Beschreibung, Quellmanifest, tatsächlich gebaute APK,
aktivierte Funktionspfade und Berechtigungsabfragen zusammenpassen. Hinzugefügte
oder aktivierte Funktionen benötigen gleichzeitig eine passende Beschreibung und
native Abnahme; ein Beschreibungstext allein ersetzt weder F-Droids Prüfung noch
einen Scanner- oder Reproduzierbarkeitsnachweis. Hierdurch wird keine neue APK
gebaut, eingereicht oder veröffentlicht.

## Signaturen und bestehende Installationen

Die Über-Seite verweist bei `magnolieFdroid=true` sowie bei einer von Android
gemeldeten Installation durch `org.fdroid.fdroid` auf Updates über den
F-Droid-Client und fragt dort keine GitHub-Releases ab. Ab Android 11 wird
`getInstallSourceInfo` verwendet, auf älteren unterstützten Versionen
`getInstallerPackageName`, jeweils nur für das eigene Paket und ohne neue
Berechtigung. Das ist ein Hinweis auf den Bezugsweg, kein Signaturnachweis.
Fehlende Angaben oder andere Installer beweisen keinen direkten Projektbezug;
ein bedingter F-Droid-Hinweis bleibt auch dann sichtbar. Weitere Clients werden
nicht anhand von Namensteilen geraten. Für manuell heruntergeladene APKs kann
die ursprüngliche Webseite unbekannt bleiben. F-Droid empfiehlt den Client:
Ein reiner Webseiten-APK-Download bietet keine Updatebenachrichtigungen.

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

### Referenz für Version 1.0.17

Die damalige offizielle APK enthält noch den automatisch vom Android-
Gradle-Plugin erzeugten Abhängigkeits-Metadatenblock. Für F-Droid gibt es eine
[gesonderte signierte Referenz-APK](https://gitlab.com/api/v4/projects/78301901/packages/generic/magnolie-notes-fdroid-reference/1.0.17/Magnolie-Notes-1.0.17.apk).
In dieser Kopie wurde ausschließlich dieser zusätzliche Signierblockeintrag
durch gleich großes Null-Padding ersetzt. Alle ZIP-Einträge sind bytegleich;
die vorhandene APK-Signatur bleibt gültig. Der F-Droid-APK-Scanner und die
erneute Signaturübernahme-Gegenprobe sind erfolgreich.

SHA-256 der F-Droid-Referenz:
`6b94a5e63e27f089f8f2ba0da68c8b1e9a5cad829425ddaac3e0a012b68f3a19`.

Die zu künftigen Notes-Versionen passenden signierten Referenzen werden im
Paket `magnolie-notes-fdroid-reference` bereitgestellt. Bei neuen Builds ist
der unerwünschte Metadatenblock bereits durch die Gradle-Konfiguration abgeschaltet.

## Aufnahme

Die Aufnahme wird im F-Droid-Projekt geprüft. Buildrezept, Quellenstand,
Prüfergebnisse und Antragslink werden in
[Issue #72](https://github.com/maik3531/Magnolie-Organizer/issues/72) geführt.
Diese Dokumentation behauptet keine bereits erfolgte Aufnahme.
