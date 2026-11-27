# #807: Serienausnahme der nativen Android-Provider-Fixture

## Tatsächlicher Ausgangsbefund

Actions-Lauf 45817099578, Versuch 2 (#99), veröffentlichter Head `92e2…`;
lokale bytegleiche Quellbasis `3583239a9b7013f09dfdc7fff7423f5e810f51b0`.
Der vollständige APK-Gate war erfolgreich. Der echte API34-Stage `system-records`
stoppt in `NativeSystemProviderSmoke.kt:185` bei der Anforderung, dass nach dem
Einfügen einer Ausnahme genau zwei Serieninstanzen vorhanden sein müssen.

Das Originalreceipt bestätigt acht vorangegangene fachliche Prüfgruppen und
Cleanup. Alle 16 protokollierten Produktaufrufe hatten keine effektiven
Kontakt-/Kalender-Schreibrechte; Cleanup entfernte beide erzeugten Kontakte und
beide Kalender vollständig. Die Anzahl und konkreten Zeitfelder der Serienzeilen
wurden im ursprünglichen Fehlerbeleg nicht erfasst. Insbesondere ist weder
`size=1` noch eine Duplikatanzahl als tatsächliches Gerätedatum belegt.
Die Vorab-Cancellation nach dem Serienfall wurde nicht erreicht.

Originalreceipt SHA256: `06885d6699fe48d5e99caf35bd53adc46b8bda1ab275167120cfb585b8e54e26`.

## Eng begrenzter AOSP-Quellbefund

Die tatsächlich geladenen offiziellen Quellen gehören zum Commit
`94405b4ad2ca9ddec5fcad85d42cd308229b61f0` des Zweigs `android14-release`.
Der erneute Abruf über den festen Commit war bytegleich mit dem Zweigabruf;
URLs, Größen und SHA256-Werte stehen in `aosp-source-manifest.json`.

`CalendarInstancesHelper.updateRecurrenceInstancesLocked` löscht im Zweig ohne
Sync-ID Instanzen anhand der ursprünglichen Event-ID. Die folgende Auswahl zur
Expansion erhält dagegen die Zeilen-ID der Ausnahme; der Quellcode enthält dazu
ein ausdrückliches TODO. `getRelevantRecurrenceEntries` wählt ohne Sync-ID nur
jene eine Eventzeile, mit Sync-ID dagegen Serie und zugehörige Ausnahmen.
`performInstanceExpansion` verbindet Ersatzinstanzen über `_SYNC_ID` und
`ORIGINAL_SYNC_ID`. Das ist eine konkrete Erklärung aus dem AOSP-Code für einen
unvollständigen Instanzsatz bei der bisherigen Fixture; es rekonstruiert nicht
die im Originalreceipt fehlenden Gerätedaten.

`CalendarProvider2` akzeptiert direkte Event-Inserts und ergänzt bei bekanntem
Master-Sync-ID-Wert das entsprechende Originalfeld. Der öffentliche
`CONTENT_EXCEPTION_URI`-Weg kopiert ebenfalls einen gegebenenfalls leeren
Master-Sync-ID-Wert und verwendet anschließend denselben Instanzhelfer. Ein
bloßer URI-Wechsel ist deshalb kein aus dieser Quelle belegter Fix.

## Korrektur ausschließlich in der Test-Fixture

Die Fixture schrieb bereits mit `CALLER_IS_SYNCADAPTER=true`. Der Serienmaster
bekommt nun eine eindeutige synthetische `_SYNC_ID`; die Ausnahme erhält ihre
eigene `_SYNC_ID` und eine passende `ORIGINAL_SYNC_ID`. Die wirklichen
`ORIGINAL_ID`, `ORIGINAL_INSTANCE_TIME` und `ORIGINAL_ALL_DAY` bleiben erhalten.
Es wird kein Konto eingerichtet, kein Server verbunden und keine
Produktberechtigung oder Produktimplementierung verändert.

Ein zusätzlicher, lesender Readback fragt ausschließlich die zwei tatsächlich
eigenen Event-IDs im eigenen Kalender ab. Nach dem Ablegen der Fixture-Rechte
prüft er gespeicherte Verknüpfung, Datum/Uhrzeit, RRULE/DURATION, Ganztagsstatus
und Bestätigungsstatus. Die Diagnose enthält begrenzte Providerfelder sowie die
tatsächlichen Vorher-/Nachher-Zeiten und Anzahlen im nächsten nativen Receipt.
Die Anforderung `seriesAfter.size == 2`, die ursprüngliche Instanzidentität,
12:00 Uhr für die Ausnahme und die unveränderte zweite Instanz bleiben hart.
Fehlende oder zusätzliche Instanzen werden weiterhin als Fehler behandelt.

Maschinenlesbarer Scope im nativen Receipt:

```json
{
  "recurrenceFixtureUsesSyncMetadata": true,
  "unsyncedLocalRecurrenceExceptionsTested": false
}
```

Direkt eingefügte komplett ungesyncte lokale Serienausnahmen sind damit nicht
abgenommen. Die Änderung prüft gültig über Sync-Metadaten verknüpfte Instanzen.
Ein allgemeiner Fehler des Produktmappers oder eine allgemeine Behebung des
Android-Provider-Sonderfalls wird nicht behauptet.

## Prüfung und nächster Schritt

`compile-provider-fixture.py` ist der tatsächlich ausgeführte enge API-Compileweg.
`compile-receipt.json` und das darin benannte `instrumentation-kotlin.log` binden
Ergebnis, Befehle, Toolchain, Quell- und Abhängigkeitshashes. Der Compile benutzt
die echten API37.2-Artefakte vor der JVM-JSON-Implementierung und kompiliert die
16 tatsächlichen Kotlin-Dateien des AndroidTest-/gemeinsamen Testquellpfads.
Unveränderte Produkt-/Java-/R-Eingaben des vorhandenen vollständigen Compiles
werden nach Hashvergleich wiederverwendet. Das ist kein neuer Gradle-/APK- oder
Androidlauf; die Änderung muss weiterhin im bestehenden API34-Owner geprüft
werden. Der dokumentierte Compilerweg ersetzt keine vorhandenen Gates.

Aktueller SHA256 von NativeSystemProviderSmoke.kt:
`d8b598923ef3f1d092ed3ffb83268571e748a6cb3ac035c8fb69ca0e1826fba3`.

## Offizielle Primärquellen

- [CalendarInstancesHelper.java](https://android.googlesource.com/platform/packages/providers/CalendarProvider/+/94405b4ad2ca9ddec5fcad85d42cd308229b61f0/src/com/android/providers/calendar/CalendarInstancesHelper.java) — SHA256 `04b9f6d643172c2d47b7245a806fa0bd48f3befe4d1ea8922fc04bdd3fcdb3e0`.
- [CalendarProvider2.java](https://android.googlesource.com/platform/packages/providers/CalendarProvider/+/94405b4ad2ca9ddec5fcad85d42cd308229b61f0/src/com/android/providers/calendar/CalendarProvider2.java) — SHA256 `37c13f9830df96df538f6dfd4b21d3369b7b1bdeeb8f1ce4d59d6012cfad3dd7`.
- [Android CalendarContract.Events](https://developer.android.com/reference/android/provider/CalendarContract.Events) — öffentlicher Events-/Exception-URI-Vertrag.
