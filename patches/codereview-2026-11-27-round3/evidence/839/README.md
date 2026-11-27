# #839: zusammenfallende Erinnerungen und alte Meldebelege

Quellbasis: `0cdd6f992e094cd724203713da3bf145c36958fc`.

Geprüfter Quellcommit: `016f4e457a3313320c7eaa884375952e6d41ec03`, Baum
`06573f41cecdec4b8ee9d009b763fc5218c0dd6b`.

Fortsetzung des [wieder geöffneten Issues #839](https://github.com/maik3531/Magnolie-Organizer/issues/839#issuecomment-7222733736).
Der vollständige Patch enthält fünf Produktdateien und drei vorhandene Testdateien.

## Bestätigter Fehler

Eine synthetische ICS-Datei enthält einen gewöhnlichen Termin um 10:30 UTC und
einen absoluten DISPLAY-Alarm genau zu diesem Zeitpunkt. Der tatsächliche
Python-Importer liefert `standardErinnerung=true`. Mit normalem Vorlauf 0 geben
die erzeugten Port-Oberflächen zwei Meldungen für denselben Eintrag aus:

- macOS: zwei Aufrufe der vorhandenen `erinnerung_zeigen`-Brücke bei einem Poll.
- Tablet: zwei verschieden benannte Alarmzeilen mit identischem Auslösezeitpunkt,
  auch in der gewöhnlichen Speichernachricht. Die tatsächliche Kotlin-Funktion
  `eligibleAlarms` lässt beide Zeilen durch. Ein vorhandener Meldebeleg nur für
  den absoluten Alarm lässt die gewöhnliche Meldung erneut zu.

Die zusätzliche Gegenprüfung auf der unveränderten macOS-Basis zeigt einen
zweiten Randfall derselben Meldeidentität: Nach der absoluten Aufgabenmeldung
entfernt eine Quellaktualisierung deren VALARM. Die damit wieder unterstützte
normale Fälligkeits- oder Vorlaufmeldung wird innerhalb derselben geöffneten
Sitzung nochmals ausgelöst. Beide Varianten wurden als echte Brückenaufrufe
reproduziert. Das Entfernen war eine Änderung des gelieferten Quellmodells;
ein vorhandener UI-Knopf zum Bearbeiten schreibgeschützter absoluter Alarme
wird damit nicht behauptet.

## Korrektur

Das Tablet fasst Alarme nur für dieselbe Sektion, lokale Eintrags-ID und exakte
UTC-Zeit zusammen. Die bisherigen Meldeschlüssel bleiben als begrenzte
`receiptAliases` erhalten. Die native Eignungsprüfung berücksichtigt jeden
dieser Schlüssel; die verschlüsselte Speicherung übernimmt bestehende Belege
auf alle zugehörigen Schlüssel und erhält sie beim Entfernen eines Alarmtyps.
Die Zustellschleife schreibt nach ihrem Benachrichtigungsaufruf dieselben
zugehörigen Schlüssel.

Bereits gespeicherte Pläne ohne Aliasfelder werden auch vor einem erneuten
Öffnen/Speichern der Web-Oberfläche abgeglichen. Die native Funktion bindet die
alten Schlüssel an eindeutige tatsächlich gespeicherte lokale Eintrags-IDs.
Gleiche fremde UID, andere Einträge, andere Sektionen und andere Sekunden
bleiben getrennt. Ein mehrdeutiger lokaler Name wie `one:absolute` neben `one`
oder mehrfach vorkommende lokale IDs begründet keine sichere automatische
Zusammenlegung; solche Mehrdeutigkeiten werden nicht geraten. Die Verarbeitung
kompiliert das feste Vorlaufmuster einmal.

macOS verbraucht bei einer absoluten Meldung alle zeitgleichen vorhandenen
Meldeidentitäten. Für Aufgaben werden zusätzlich ausschließlich die möglichen
Fälligkeits-/Vorlaufbelege aus den vorhandenen Kernfeldern abgeleitet. Dadurch
bleibt die Meldung nach einer Quellaktualisierung verbraucht. Die Korrektur
erweitert nicht die bisher unterstützten gewöhnlichen Aufgabenalarme mit VALARM.

## Prüfnachweise

| Pfad | Vorher | Nachher |
|---|---|---|
| macOS: Termin, absolute und normale Meldung gleichzeitig | 2 Brückenaufrufe | 1 Brückenaufruf |
| Tablet: derselbe importierte Termin einschließlich normalem Speichern | 2 Alarmzeilen | 1 Zeile mit beiden Meldeidentitäten |
| Kotlin: alter Plan mit beiden Zeilen | 2 geeignete Meldungen | 1 Meldung in der Regression |
| Kotlin: alter Plan mit bereits gemeldetem absoluten Alarm | normale Meldung erneut geeignet | keine erneute Meldung |
| macOS: Aufgabe nach Entfernen von VALARM, Fälligkeit und 1 Tag Vorlauf | jeweils zweite Meldung | jeweils weiterhin nur eine Meldung |

Die finale Prüfung umfasst **398 bestehende/ergänzte macOS-UI-Prüfungen**, **30
Tablet-UI-Fälle** und **23 JUnit-Prüfungen** in der vorhandenen `VaultTest`-Klasse.
Die JVM-Prüfung kompiliert die tatsächlichen Produktklassen für Speicherung,
Verschlüsselung, Meldebelege und Eignungsprüfung. Sie umfasst alte verschlüsselte
Zwei-Zeilen-Pläne ohne erneutes Web-Speichern, Belege beider bisherigen
Identitäten, erneutes Öffnen, Entfernen beider Alarmarten, neue Zeitpunkte,
mehrdeutige IDs, getrennte Quellen/Einträge und die atomare Abweisung ungültiger
Aliasfelder. Die normale Testklasse übernimmt außerdem die tatsächlich von der
Tablet-Oberfläche erzeugten Alarmvektoren mit passendem Projektionshash.

JSDOM führt die vorhandenen erzeugten Oberflächen/Controller und Brücken aus.
Die JVM-Prüfung verwendet die vorhandenen Produktklassen und JUnit-Abhängigkeiten
mit dem im Repository festgelegten Kotlin 2.4.21. Ein Android-SDK war hier nicht
vorhanden; deshalb ist dies kein vollständiger Android-/Gradle-Bau. Der
`ReminderReceiver` und Androids `NotificationManager` wurden nicht ausgeführt.
Seine gemeinsame Belegfunktion und die tatsächliche verschlüsselte Speicherung
sind geprüft; der Zustellaufruf selbst bleibt eine native Abnahme. Ebenso wurde
keine echte macOS-Mitteilung zugestellt. macOS behält den bestehenden
Sitzungsumfang seiner flüchtigen Meldemenge; ein neuer dauerhafter Mac-Belegspeicher
wird nicht behauptet. Paket-/Geräteabnahmen bleiben bei #680, #113 und #121.

## Wiederholen und übernehmen

`run_port_checks.py` nutzt die vorhandenen Repository-Werkzeuge: PO-Kataloge,
Importhelfer-Abhängigkeit, macOS-Freeze/Projektion, Tablet-Projektion sowie die
vorhandenen Oberflächentests. `run_native_tests.py` kompiliert den gezielten
JVM-Quellumfang und startet die vorhandene `VaultTest`-Klasse. Die benötigten
Werkzeug-/Jar-Identitäten sind in `kotlin-dependencies.json` dokumentiert.

```text
python3 run_port_checks.py REPOSITORY EXISTING_TOOL_ROOT OUTPUT_DIRECTORY
```

Der vorhandene Werkzeugordner enthält `gettext/usr/bin`,
`gettext/usr/lib/x86_64-linux-gnu`, `js/node_modules` und `kotlin/*.jar`.
Ein zusätzliches `PYTHONPATH` ist nicht erforderlich. Der Runner erstellt
keine installierbaren Pakete. Die Quelle muss für die ausdrückliche lokale
Freeze-Phase ruhen. Normale native CI-/Geräteprüfungen können nach Übernahme
weitergeführt werden.
