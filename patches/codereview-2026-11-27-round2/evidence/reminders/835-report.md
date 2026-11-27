# #835 – Absolute Kalendererinnerungen erhalten und zuverlässig quittieren

**Issue:** [#835](https://github.com/maik3531/Magnolie-Organizer/issues/835)  
**Ausgangsbasis:** `1543858e251d7e29ebeafb67d2605991c1d442d5`  
**Geprüfter Endstand:** `ed3ffa936088840e4c3437eab5c37417fd31c86b`  
**Umfang:** Linux-Organizer und Windows-C#-Scheduler; Quellkorrektur mit gezielten Hostprüfungen.

## Bestätigter Fehler

Importierte `VALARM`-Einträge mit `ACTION:DISPLAY` und absolutem UTC-Trigger wurden gespeichert, erreichten die Erinnerungsplanung jedoch nicht zuverlässig. Die erste Reproduktion verwendete die tatsächlichen ICS-Importer und einen ausdrücklich fälligen Alarm, dessen zugehöriger Termin erst zwei Tage später beginnt.

| Unveränderte Basis | Absolute Importkontrollen | Relative Gegenkontrollen |
| --- | --- | --- |
| Windows: VEVENT/VTODO, jeweils Original-, Runtime- und Hintergrunddaten | **0/6 bestanden** | **6/6 bestanden** |
| Linux: VEVENT/VTODO, jeweils Original- und Hintergrunddaten | **1/4 bestanden**; nur das ursprüngliche VTODO funktionierte | **4/4 bestanden** |
| Gesamt | **9 von 10 absoluten Alarmen fehlten** | **10/10 bestanden** |

Windows berücksichtigte bislang relative Minutenabstände. Seine Projektion entfernte außerdem schreibgeschützte absolute Alarme. Linux verlor solche Alarme bei der Projektion beziehungsweise Normalisierung oder band ihre Auswertung an expandierte Vorkommen und deren Suchfenster. Ein funktionierender unmittelbarer Linux-Aufgabenpfad verdeckte dabei die Lücken im Hintergrundbetrieb. Die Quelldaten enthielten den Alarm weiterhin; der Befund betrifft seine Auslösung.

## Verhalten nach der Korrektur

Absolute DISPLAY-Trigger werden als **UTC-Zeitpunkte mit Sekundenauflösung je Kalenderkomponente** geplant. Die Identität enthält die bestehende Eintrags-/Quellenidentität und den absoluten Trigger. Ein Serienmaster erzeugt dadurch eine Erinnerung je absolutem Trigger. Eine Verschiebung seines Startdatums oder ein Scheduler-Neustart erzeugt keine neue Alarmidentität. Verschiedene Quellen, Triggersekunden und die beiden UTC-Zeitpunkte einer wiederholten lokalen Stunde beim Sommerzeitwechsel bleiben unterscheidbar.

Beide Projektionen erhalten die benötigten Alarmfelder und lassen private `DESCRIPTION`-Inhalte weg. Die tatsächliche Windows-Oberfläche bildet Termin-Alarme als `bearbeitbar:false` mit `triggerRaw` ab; Aufgaben behalten ihre Alarme dagegen in `icsRoundtrip`. Beide Darstellungen sind geprüft. Auch `BEGIN:valarm`/`END:valarm` bleiben nun in der C#-Projektion erhalten: derselbe bestätigte Randfall liefert vor und nach jeder Projektion genau einen Alarm.

Ein VTODO ohne DTSTART und DUE kann einen absoluten Alarm auslösen. Zur Anzeige dient dann der Triggerzeitpunkt; gespeicherte Aufgabenfelder werden nicht um erfundene Datumswerte ergänzt. Vorhandene ungültige Datums-/Zeitangaben gelten weiterhin als Fehler und werden nicht als absichtlich undatierter Eintrag behandelt. Abgesagte Komponenten, deaktivierte Alarme, erledigte Aufgaben und die bestehenden Vertraulichkeitsfilter bleiben ausgeschlossen.

### Vorhandene Quittierungen und gleichzeitige Alarme

Die Linux-Prüfung verwendet alte Quittierungsschlüssel, die durch Ausführen des tatsächlichen Importers und Aufgabenplaners der Ausgangsbasis gewonnen wurden. Diese enthalten noch Vorkommens- und lokale Minutenangaben. Die Übernahme erkennt nur passende ursprüngliche Quellen, Komponenten, Trigger und tatsächliche Serienvorkommen. Eine ähnliche Kennung, eine andere Sekunde oder die zweite Stunde einer Sommerzeit-Rückstellung übernimmt keine fremde Quittierung.

Fallen eine normale Fälligkeits-/Standarderinnerung oder ein relativer Alarm und ein absoluter Alarm **für denselben Eintrag exakt auf denselben UTC-Zeitpunkt**, wird nur eine Meldung erzeugt. Windows verwendet den absoluten Schlüssel als kanonische Identität und speichert passende bisherige Schlüssel als Aliase. Linux erhält in diesem Fall die normale Meldungsidentität und quittiert den absoluten Schlüssel gemeinsam mit ihr. Bereits gespeicherte normale Quittierungen verhindern damit auch nach einem Upgrade eine Wiederholung. Ebenso erscheint keine zusätzliche Meldung, wenn der absolute Alarm nach seiner Zustellung entfernt wird. Andere Einträge, Quellen und Sekunden werden nicht zusammengelegt.

## Prüfnachweise

| Prüfbereich | Tatsächlicher Stand |
| --- | --- |
| Gemeinsame Vertragsdaten | **24 Vektoren** in `contracts/absolute-reminder-vectors.json`; **138 C#-Import-/Projektionsfälle** bestanden |
| Neue Python-Hauptgruppe gegen alte Produktbasis | **98 Fälle: 55 fehlgeschlagen, 43 bestanden**; derselbe fachliche Prüfumfang bestätigt die Korrektur |
| Python-Gesamtprüfung | **198/198 bestanden**; vorheriger Stand: 194. Die Legacy-/Koinzidenzdatei umfasst nun 13 statt neun Testmethoden; die Hauptgruppe bleibt bei 98 Fällen |
| C#-Remindergruppen | **6/6 bestanden**, einschließlich `AbsoluteReminderCoincidenceTests`; zusätzlich 18 Prüfungen gegen ungültige vorhandene Datums-/Zeitwerte |
| Unabhängige C#-Kontrolle | **176 Assertions** für echten Import, tatsächliche JS-Normalisierung, Projektionen und Zustandsdateien; danach gezielt sechs VALARM-Schreibweisenfälle und 18 Deduplizierungsassertions bestanden |

Die Neustartprüfungen schreiben und lesen tatsächliche Zustandsdateien. Getrennte Scheduler-Instanzen bestätigen unter anderem die Meldungsfolge **1, 1, 0** für zwei unterschiedliche Triggersekunden sowie **1, 0** für einen gleichzeitig normalen und absoluten Alarm. Alte Quittierungen, spätere Datumsänderungen, Quellenabgrenzung und das Entfernen eines bereits zugestellten absoluten Alarms sind berücksichtigt.

Eine bestehende Weckzeitreferenz musste fachlich berichtigt werden: Ihr bisheriger Vergleich ließ den absoluten Trigger selbst aus und erwartete deshalb erst den nächsten relativen Serientermin. Der gemischte Fall wird nun unabhängig auf **25.10.2026, 01:15 UTC** geprüft. Für die ausschließlich relative Teilmenge bleibt der bisherige Referenzvergleich erhalten; seine Erwartungen wurden nicht gelockert.

## Gezielte Wiederholung

Aus der Repository-Wurzel, mit den vorhandenen Projektabhängigkeiten; die folgenden Bash-Kommandos erzwingen UTC für die Hostprüfung:

```bash
TZ=UTC python3 -m pytest -q \
  magnolie-organizer/pruefungen/test_absolute_reminders.py \
  magnolie-organizer/pruefungen/test_absolute_reminder_legacy.py \
  magnolie-organizer/pruefungen/test_naechster_weckzeitpunkt.py \
  magnolie-organizer/pruefungen/test_reminder_projection.py \
  magnolie-organizer/pruefungen/test_regional_reminders.py \
  magnolie-organizer/pruefungen/test_recurrence_integration.py \
  magnolie-organizer/pruefungen/test_native_recurrence_regressions.py

TZ=UTC dotnet run \
  --project magnolie-organizer-windows/tests/CoreTests.csproj \
  -c Release --no-restore -- Reminder
```

Die C#-Regressionen liegen in `magnolie-organizer-windows/tests/AbsoluteReminderTests.cs` und `AbsoluteReminderCoincidenceTests.cs`; der Filter `Reminder` nimmt auch die bestehenden Serien-, Neustart-, Datenschutz- und Jahrestagsgruppen mit. Produktänderungen betreffen `magnolie-organizer/bin/magnolie-organizer` und `magnolie-organizer-windows/ReminderScheduler.cs`.

## Grenzen

Die bisherigen Nachholregeln bleiben editionsspezifisch: Windows verwendet ohne aktivierte Nachholung ein Fünf-Minuten-Fenster; Linux-Aufgaben besitzen ihre bestehende 14-Stunden-Regel. #835 vereinheitlicht diese Semantik nicht. Die Alarmidentität und Deduplizierung umgehen diese Grenzen nicht.

Die Nachweise sind Hostprüfungen mit tatsächlichen Produktfunktionen, JSDOM-Oberfläche und kontrollierten Meldungs-Callbacks. **Native Windows-/Linux-GUI-, Benachrichtigungs- und Paketabnahmen stehen offen.** Eine Übernahme oder Abnahme für macOS oder Android-Tablet wird nicht behauptet. Der Quellenstand stellt keine Paketveröffentlichung dar.
