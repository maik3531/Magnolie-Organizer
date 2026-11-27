# Android-Tablet: native Herkunftsprüfung, Issues #799 und #800

Stand: 26. November 2026. Reviewbasis ist der veröffentlichte PR-Head
`29acde7e3df2b8bcaaab0cc19b3377b8dbf4bd14` von PR #795. Die native Änderung betrifft
nur `AndroidSystemRecords.kt`, `SystemImportPolicy.kt` und
`SystemImportPolicyTest.kt`. Die ergänzende Webvalidierung wird getrennt geprüft.

## Bestätigte Fehler vor der Korrektur

Der unveränderte Produktionsmapper wurde mit zwei synthetischen Beispielen aus
dem öffentlichen Android-Datenvertrag ausgeführt. Beide erwarteten
Identitätsgleichheiten scheiterten: `before-junit.log` enthält **2 Tests,
2 Fehler, Exit 1**; die vorgelagerte Kotlin-Kompilierung hatte Exit 0.

1. **#799 – Kontakt nach erneutem Synchronisieren:** Die Quelle blieb dieselbe,
   die lokale `RawContacts._ID` wechselte von 7 auf 42. Android dokumentiert, dass
   `SOURCE_ID` nach dem Leeren und erneuten Synchronisieren des Kontaktspeichers
   erhalten bleiben soll. Der bisherige native Pfad las diese Kennung nicht und
   erzeugte aus der neuen lokalen Zeilennummer eine neue Importkennung.
2. **#800 – verschobener Einzeltermin:** `Events._ID=17` blieb gleich, der Beginn
   wurde von 10 auf 12 Uhr verschoben. Der alte Mapper bezog `BEGIN` bei jedem
   Termin in die Kennung ein und erzeugte eine zweite Importidentität.

`ProviderIdentityBeforeTest.kt` enthält die tatsächlich ausgeführten Beispiele;
`before-source-hashes.json` bindet die verwendeten unveränderten Produktionsdateien.
Dies ist eine Host-Reproduktion des Produktionsmappers mit Android-Vertragsdaten,
keine ausgeführte ContentResolver-Abfrage und keine Android-Geräteabnahme.

## Umgesetzte Korrektur

### Kontakte

Die nativen Vor- und Nach-Snapshots enthalten jetzt `SOURCE_ID`, `BACKUP_ID`,
lokale Zeilennummer, Version und Anzeigename. Änderungen zwischen beiden
Snapshots verwerfen den ganzen Kandidaten. Die tatsächlich vom Android-Adapter
benutzte Reihenfolge Snapshot → Detailabfragen → Snapshot → Ausgabe liegt in
einer gemeinsamen, mit synthetischen Abfragen prüfbaren Produktionsfunktion.

Die Identität verwendet zuerst `SOURCE_ID`, sonst `BACKUP_ID`, sonst eine
gerätelokale Zeilenkennung. Die dokumentierte `BACKUP_ID` ist seit API 24
verfügbar; `minSdk=26` deckt diese Voraussetzung ab. Gerätelokale Kennungen und
`rowBinding` beziehen die tatsächliche `Settings.Secure.ANDROID_ID` ein. Diese ist
seit API 26 an Signierschlüssel, Android-Nutzer und Gerät gebunden. Der rohe Wert
wird nur in den nativen Hash einbezogen; er erscheint nicht im Webpayload.
Fehlende oder ungültige Werte ergeben `provider_unavailable`, keine Ersatzkennung.

Der Erfolgspayload enthält `identitySchema:2`. Jeder Kontaktrecord enthält
`identityKind` (`source-id`, `backup-id` oder `device-raw-id`) sowie
`rowBinding` im Format `android-contact-row:<64 hex>`. `recordId` und `data.uid`
bleiben gleich. Diese Metadaten dienen ausschließlich der konservativen
Erkennung der Herkunft. Sie erteilen keine Provider- oder Sync-Berechtigung.

### Kalender

Der Instanzpfad liest zusätzlich `RRULE`, `RDATE`, `ORIGINAL_ID`,
`ORIGINAL_INSTANCE_TIME`, `ORIGINAL_SYNC_ID` und `ORIGINAL_ALL_DAY`. Beide
Instanzabfragen vergleichen auch diese Felder.

| Android-Fall | Identitätsbestandteile neben gewählter Quelle und Android-Geräte-/Nutzerscope |
| --- | --- |
| Einzeltermin | `single-event` + `Events._ID` |
| Normale Serieninstanz | `recurring-instance` + `Events._ID` + ursprünglicher `BEGIN` |
| Serienausnahme | `recurring-instance` + `ORIGINAL_ID` + `ORIGINAL_INSTANCE_TIME` |

Eine verschobene Ausnahme und ihre ursprüngliche Serieninstanz erhalten damit
dieselbe Kennung. Die tatsächlichen `BEGIN`/`END`-Werte, UTC-Sekunden und
Ganztagsgrenzen werden unverändert in die lokale Kopie projiziert. Unvollständige,
unaufgelöste oder widersprüchliche Ausnahmemetadaten verwerfen die Abfrage.
Kalenderrecords enthalten ebenfalls `identitySchema:2` und ihren
`identityKind`; ein Kontakt-`rowBinding` wird für Termine nicht erzeugt.

## Ausgeführte Prüfungen

- **40 JVM-Tests nach dem separaten Kontaktfix:** bisherige 31 plus neun neue
  Kontaktfälle; `contact-junit.log`, Exit 0. Der eigenständige Zwischenstand ist
  in `contact-native-files-hashes.json` und `contact-source-hashes.json` gebunden.
- **46 JVM-Tests nach beiden Fixes:** zusätzlich sechs Kalenderfälle;
  `full-compile/run-xgr0rcb2/junit.log`, Exit 0. Diese prüfen unter anderem
  Wiedererkennung nach Kontakt-Zeilentausch, Nutzer-/Gerätetrennung, Konfliktbindung
  beim späteren Zuweisen einer Quellkennung, Identitätsänderung trotz unveränderter
  Version, Abbruch, durchgereichte `SecurityException`, doppelte Quellkennungen,
  verschobene Einzeltermine, Serienausnahmen, RDATE und verschobene Ganztage.
- **Alle 38 Kotlin-Produktdateien** gegen echte Android-37.2-/AndroidX-API-Artefakte
  kompiliert, Exit 0. Die tatsächlichen Ressourcen wurden mit aapt2 36 übersetzt
  und gelinkt; echtes erzeugtes `R.java` wurde kompiliert. Keine selbst erfundenen
  Android-API-Stubs.
- `git diff --check` ohne Fehler.

Verwendet: Kotlin 2.4.21, OpenJDK 21.0.13.1, JUnit 4.13.2, JVM-Ziel 17,
Android API 37.2 und aapt2 36. `minSdk=26`, `targetSdk=35` bleiben unverändert.
Abhängigkeiten werden vor Verwendung gegen die vorhandenen Downloadmanifeste
mit ihren SHA-256-Werten geprüft.

Der tatsächlich ausgeführte Reproduktionslauf lautet:

```sh
python3 /workspace/scratch/acde70e8594b/tablet-native-followup/verify-native-followup.py \
  --repository /workspace/scratch/acde70e8594b/Magnolie-Organizer \
  --dependencies /workspace/scratch/acde70e8594b/tablet-build-dependencies \
  --output /workspace/scratch/acde70e8594b/tablet-native-followup/full-compile
```

Skript-SHA-256:
`2604413559786294342e9ce845d884f7195e40e2163afd7f46aefd517a06d744`.
Die vollständige Receipt mit 38 Quell-, sieben JVM-Eingabe-, Ressourcen- und
Abhängigkeitshashes liegt unter `full-compile/receipt.json`. Das Skript ist eine
gezielte Quellen-/Ressourcenprüfung mit bereits vorhandenen Artefakten. Es
ersetzt die vorhandenen Gradle-, Ressourcen-, APK- oder Freigabegates nicht.

| Geänderte native Datei | SHA-256 des geprüften Endstands |
| --- | --- |
| AndroidSystemRecords.kt | `b7197e69f8c9e2f9aa4e29a2122db659965517ee3fe711085690c3593e8ca8ab` |
| SystemImportPolicy.kt | `12767aebd8c90df2ba19f4d30b628d6e35813099891ac4fa7a035cbf1bbe7b45` |
| SystemImportPolicyTest.kt | `78fa04131df1a5eccce314ba4052e6841c8d14828b4cadcb5342a5658073f566` |

## Grenzen und konkrete Restabnahme

Die bestehenden MainActivity-Prüfungen von Sitzung, Buchrevision, Abbruch und
Leseberechtigung vor dem Lesen sowie vor der Auslieferung bleiben erhalten.
Die neuen Tests führen den gemeinsamen Kontaktablauf mit synthetischen
Abfragefunktionen aus. Echte Binder-/Cursor-/Provider- und Berechtigungsabläufe,
Rotation, Hintergrund/Neustart und Speicherung bleiben auf Android zu prüfen.
Es wurden kein vollständiger Gradle-/D8-/APK-Lauf, keine Installation, Signierung
oder Geräteinteraktion durchgeführt.

Schema-1-Kopien dürfen weder über Namen, Telefonwerte noch bloße Zeilennummern
automatisch umgedeutet werden. Die passende Webvalidierung muss für nichtleere
neue Ergebnisse bei Legacybestand derselben Quelle einen eindeutigen Konflikt
melden. Ein Wechsel von einer lokalen Kontaktkennung zur späteren Serverkennung
ist über gleiche `rowBinding` und unterschiedliche `recordId` als Konflikt
erkennbar; daraus entsteht kein automatischer Merge.

Ohne stabile `SOURCE_ID`/`BACKUP_ID` gibt der öffentliche Providervertrag keine
zuverlässige Herkunft über einen vollständigen Kontaktdatenbankreset. Die
Fallbackkennung ist daher nur gerätelokal. Kalenderkennungen sind ebenfalls
gerätelokal: Wiederherstellung oder Neuerstellung ganzer Kalender-/Provider-IDs
sowie Änderungen der gesamten Serienstruktur sind durch diesen begrenzten Fix
nicht als Synchronisierung abgedeckt. Vorhandene lokale Kopien bleiben erhalten.
Es werden keine Provider-Schreibrechte und keine Lösch- oder Serienautorität
abgeleitet; lokale Erinnerungen folgen weiterhin den Organizer-Einstellungen.

## Android-Primärquellen

- [Contacts Provider: SOURCE_ID, Stabilität nach erneutem Synchronisieren und VERSION](https://developer.android.com/identity/providers/contacts-provider)
- [RawContactsColumns.BACKUP_ID: persistent innerhalb Konto/DataSet, seit API 24](https://developer.android.com/reference/android/provider/ContactsContract.RawContactsColumns#BACKUP_ID)
- [Settings.Secure.ANDROID_ID: Scope seit API 26 und dokumentierte Änderungen](https://developer.android.com/reference/android/provider/Settings.Secure#ANDROID_ID)
- [Calendar Provider: Einzeltermine, Serien und Instances](https://developer.android.com/identity/providers/calendar-provider)
- [EventsColumns: ORIGINAL_ID und ORIGINAL_INSTANCE_TIME](https://developer.android.com/reference/android/provider/CalendarContract.EventsColumns#ORIGINAL_ID)
- [CalendarContract.Events: Einschränkungen für Serienausnahmen und UTC-Ganztage](https://developer.android.com/reference/android/provider/CalendarContract.Events)
