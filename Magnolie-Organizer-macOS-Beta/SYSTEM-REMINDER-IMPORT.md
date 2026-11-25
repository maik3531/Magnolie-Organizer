# Ausgewählte Apple-Erinnerungen als lokale Aufgaben

Refs #777, Fortsetzung von #721. Quellpatch auf
`work/777-macos-reminder-copy`, aufbauend auf #775. Stand: 25. November 2026.
Der Patch wird gemäß Nutzerauftrag für die spätere Codex-Übernahme im Issue
bereitgestellt. Native Swift-/EventKit-/AppKit-Abnahme und Paketfreigabe stehen
noch aus.

## Zweck und Bedienung

**macOS-Erinnerungen übernehmen…** im nativen Menü oder unter den
System-Internetkonten startet die ausdrücklich angeforderte Übernahme. Nach
der normalen macOS-Freigabe werden eine Erinnerungsliste und bis zu 100 ihrer
offenen oder erledigten Einträge ausgewählt. Die Vorschau zeigt Quelle und
Konto, Ziel, Anzeigezeitzone, vollständige übernommene Texte und Werte sowie
neue, vorhandene, an der Quelle geänderte und ausgeschlossene Einträge.

Erst **Angezeigte Aufgaben übernehmen** erzeugt eigenständige Aufgaben im
aktuellen Magnolie-Dokument. iPhone-Erinnerungen müssen vorher im gewählten
Mac-Konto verfügbar sein. Magnolie verwendet direkt EventKit im eigenen
Prozess; ein zusätzliches Hilfsprogramm oder eine eigene iPhone-App wird
nicht benötigt. Die Übertragung zwischen iPhone und Mac bleibt Sache des
eingerichteten Kontodienstes. AirPlay ist daran nicht beteiligt.

Die Kopie verändert keine Quelle, aktiviert keinen Rückabgleich und erzeugt
keine Aufgabenbenachrichtigung. Der vorhandene vollständige
Systemquellen-Abgleich bleibt als nicht implementiert gekennzeichnet.

## Bewusster Umfang einer eigenständigen Kopie

Die öffentlichen APIs von [`EKReminder`](https://developer.apple.com/documentation/eventkit/ekreminder.md)
und [`EKCalendarItem`](https://developer.apple.com/documentation/eventkit/ekcalendaritem.md)
stellen nicht sämtliche Funktionen der Erinnerungen-App bereit. Für diesen
Anschluss gelten Unteraufgabenbeziehungen, Anhänge, Tags, Markierungen,
Zuweisungen, Rich Text und unbekannte Providerfelder ausdrücklich als
**nicht verfügbar**. Daraus folgt keine Aussage, dass sie im Original fehlen.
Jede Kopie erhält die sichtbare Kennzeichnung als eigenständige Aufgabe;
eine vermeintlich verlustfreie Spiegelung wird nicht angeboten.

| Ursprüngliche Information | Abbildung und Grenze |
| --- | --- |
| Titel | Unveränderter Titel. Fehlende/leere Titel, Rand-Leerraum und nicht darstellbare Steuerzeichen führen zum sichtbaren Ausschluss. |
| Notiztext | Öffentlicher Klartext im vorhandenen Aufgaben-Notizfeld. Formatierungen und andere App-Funktionen werden nicht behauptet. CR/CRLF und nicht unverändert bearbeitbare Texte werden ausgeschlossen. |
| Offen/erledigt | Bestehendes lokales Erledigt-Feld. Ein erledigter Eintrag ohne ursprünglichen Erledigungszeitpunkt ist zulässig; kein Zeitpunkt wird erfunden. |
| Priorität | Original 1–3 → Hoch, 4–6 → Normal, 7–9 → Niedrig; 0 ohne Priorität → Normal. Die Vorschau erklärt die Gruppierung und zeigt den Originalwert. |
| Beginn/Fälligkeit ohne Uhrzeit | Kalenderdatum bleibt DATE, ohne künstliche Mitternacht oder Datumsverschiebung. |
| Beginn/Fälligkeit ohne eigene Zeitzone | Datum und Uhrzeit bleiben floating, auch wenn der eingebettete Kalender oder das Erinnerungsobjekt eine Zeitzone trägt. |
| Explizite Zeitzone | Auflösung mit der vorhandenen normativen Zeitzonendatenbank; Darstellung in der Dokumentzeitzone. Lücken und doppeldeutige Uhrzeiten werden ausgeschlossen. |
| Sekunden/Bruchteile | Ausgeschlossen, wenn sie im tatsächlichen Aufgaben-Editor nicht erhalten bleiben. Auch historische Sekundenverschiebungen der Anzeigezeitzone werden berücksichtigt. |
| Datumsfenster | Ungültige oder nicht bearbeitbare Kombinationen werden ausgeschlossen, etwa ein Beginn mit Uhrzeit und eine Fälligkeit nur als Datum. Floating und gebundene Zeiten werden nicht zu einem gemeinsamen Zeitfenster vermischt. |
| Serie/Alarm | Einträge mit öffentlichen Wiederholungsregeln oder Alarmen werden sichtbar ausgeschlossen. Keine Abflachung einer Serie und keine stille Alarmabschaltung. |
| Ursprüngliche Erstellungs-/Änderungs-/Erledigungszeit | Lesbar in der Vorschau; Originalwerte bleiben als Quellenbeleg erhalten. Neue lokale Aufgaben bekommen eigene Erstellungs-/Änderungszeiten. |
| Ort und URL | Sichtbar als Ursprungsdaten; keine Aktivierung als Aufgabenfelder, kein Aufruf der URL. |
| Native Kennungen und übrige gelesene Metadaten | Getrennte Herkunftsdaten, ohne Berechtigung zum Synchronisieren, Delegieren oder Quellschreiben. |

Apples Dokumentation zu
[`dueDateComponents`](https://developer.apple.com/documentation/eventkit/ekreminder/duedatecomponents.md)
unterscheidet Datum, floating und die unabhängig vom Beginn geltende Zeitzone.
[`isCompleted`](https://developer.apple.com/documentation/eventkit/ekreminder/iscompleted.md)
erlaubt ausdrücklich erledigte Einträge ohne `completionDate` nach Änderungen
durch andere Clients. Diese Fälle bleiben im neuen Vertrag unterscheidbar.

Nur gesteuerte DTSTART-/DUE-Zeilen bilden aktive Kalenderinformationen der
lokalen Aufgabe. Die ursprüngliche native Priorität bleibt ausschließlich in
`nativeReminderRecord`; eine veraltete aktive PRIORITY-Zeile darf spätere
lokale Änderungen oder Exporte nicht widersprüchlich machen. Dasselbe gilt
für ursprüngliche Zeitstempel und nicht abgebildete öffentliche Felder.

## Native Lesegrenzen und Quellenprüfung

`SystemReminderReader` und die additiven `SystemAccounts`-Methoden verwenden
die vorhandene private serielle Store-Queue. Die normale Freigabe wird erst
beim ausdrücklichen Start angefordert. Aktuelle Systeme verwenden die
verfügbare Vollzugriffs-API; ältere unterstützte Systeme den vorhandenen
versionsabhängigen EventKit-Pfad. Zugangsdaten bleiben bei macOS.

Die Listenauswahl bindet native Listenkennung, Kontokennung, Typ, Titel,
Schreibschutz und Berechtigungszustand. Für die Eintragsauswahl werden nur
Kennung, Listen-/Kontozugehörigkeit, Titel und Erledigtstatus ausgewertet.
Anders als Contacts bietet EventKit kein `keysToFetch`: Der Framework-Aufruf
liefert bereits EKReminder-Objekte. Die Grenze von 10.000 Listeneinträgen wird
nach dessen Rückkehr geprüft und begrenzt nicht dessen interne Allokation.

Nur ausgewählte Kennungen werden anschließend gezielt neu aufgelöst und mit
`refresh()` gelesen. Zugehörigkeit, Quelle und Berechtigung werden vor und
nach dem Abruf geprüft; der vollständige ausgewählte Abruf wird nach der
Vorschau wiederholt. Native Identitäten werden als exakte UTF-8-Werte
verglichen, nicht über Anzeigenamen oder normalisierte Unicode-Gleichheit.

Die Anwendungsgrenzen betragen 256 Listen, 100 ausgewählte Erinnerungen,
4.096 UTF-8-Bytes je Titel, 1 MiB je Notiztext und 16 MiB für den Quellenbeleg.
Der erzeugte Gesamtvorschlag einschließlich mehrfach dargestellter Texte hat
eine eigene 16-MiB-Prüfung. Weitere Grenzen gelten für Kennungen,
verschachtelte Werte, Alarm- und Serienfelder.

Asynchrone Listenabrufe besitzen eine einmalige Completion, eine monotone
20-Sekunden-Frist und 100-ms-Prüfungen auf Abbruch. Bei Abbruch wird
`cancelFetchRequest` aufgerufen und die eigene Fortsetzung abgeschlossen:
Apple dokumentiert, dass ein
[abgebrochener Abruf seine ursprüngliche Completion nicht aufruft](https://developer.apple.com/documentation/eventkit/ekeventstore/cancelfetchrequest(_:).md).
Ein laufender synchroner Systemzugriff kann trotzdem später zurückkehren;
sein Ergebnis berechtigt dann nicht mehr zur Übernahme. Es gibt kein
Semaphore-Warten auf dem UI-Thread.

## Lokaler Vertrag und Wiederholung

Der neue parameterlose Bridge-Befehl `macos_erinnerungen_importieren` öffnet
`SystemReminderImportHost`. Der Core erstellt aus geprüften Wertobjekten
einen Vorschlag; die tatsächliche kanonische Oberfläche konstruiert daraus
neue Aufgaben mit unabhängigen lokalen IDs. Native Herkunft steht getrennt
in `nativeReminderImport` und `nativeReminderRecord` mit
`copyKind: "standalone-public-fields"`.

Der SHA-256-Quellenbeleg bindet Listen-/Kontometadaten und sämtliche
ausgewählten Rohdatensätze einschließlich Ausschlüssen. Er ist eine Revision
der tatsächlich gelesenen Felder, kein atomarer Serverstand und kein Beleg
für nicht verfügbare App-Felder. Lokale native IDs können sich bei einer
Neusynchronisation ändern; über Namen oder externe Provider-IDs wird deshalb
keine vermeintlich sichere Wiedererkennung erfunden.

Vorhandene Kopien bleiben unverändert. Änderungen an der Quelle werden
angezeigt, ohne lokale Änderungen zu überschreiben. Im Papierkorb liegende
Kopien werden nicht erneut angelegt. Widersprüchliche Mehrfachzuordnungen
brechen den Vorschlag ab. Gleiche Titel erzeugen keine Zusammenführung.

Die Projektion normalisiert ausschließlich neue Kandidaten und prüft den
gesamten Aufgabenbaum auf Klonen: Anhängen und späteres Zeichnen dürfen weder
Rangfolgen noch Beziehungen oder Felder vorhandener Aufgaben verändern. Neue
Aufgaben werden als weitere Wurzeleinträge angehängt. Bestandsaufgaben,
Notizen, Kontakte, Jahrestage und Alarmzustände bleiben unverändert.

Eine private, fünf Minuten gültige Vorschau bindet das konkrete Buchobjekt,
den vollständigen serialisierten Inhalt und die Anzeigezeitzone. Monotone
und Wanduhr-Frist, Editor-/Konto-/Kennwortentwürfe, ausstehende Notizänderungen,
Sperre und Wiederherstellung werden kontrolliert. Dieselben Prüfungen laufen
nach dem Wiederherstellungspunkt erneut. Ein fremdes Token verbraucht keine
gültige Vorschau. Das normale dauerhafte Save-ACK beendet die Übernahme;
ein tatsächlicher Save-NACK kennzeichnet die Kopien ausdrücklich als
ungespeichert. Scheitert dagegen die Darstellung nach dem Anhängen, kann ein
bereits geplanter Save noch laufen. Die eigene Meldung erklärt deshalb, dass
die Kopien hinzugefügt wurden, ihre Speicherung aber nicht bestätigt wurde;
sie fordert zum Prüfen/Speichern auf und behauptet keine Rücknahme. Dieser
Fall ist mit einer Ausnahme im tatsächlichen öffentlichen Renderer-Hook
reproduziert und mit Save-Retry geprüft. Der gleiche Quellpfad in älteren
Kalender-/Notes-/Kontaktkopien wird getrennt in #778 verfolgt.

## Prüfung und noch erforderliche Abnahme

`Tests/BetaCoreTests/SystemReminderImportTests.swift` prüft den reinen
Core-Vertrag. Das vollständige JSON-Fixture unter
`Tests/BetaCoreTests/Fixtures/system-reminder-copy.json` wird sowohl von Swift
als auch vom echten erzeugten UI-Test verwendet.
`tests/system_reminder_import.mjs` und
`tools/check_system_reminder_import.py` prüfen die wirkliche Projektion,
Editorerhalt, Aufgabenbaum, Quellenklassifizierung, Guards,
Wiederherstellungspunkt und Speicherquittung mit synthetischen nativen
Eingaben. Die abschließenden tatsächlichen Ergebnisse stehen im aktuellen
Abschnitt von `../ARBEITSSTAND.md` und in #777.

In dieser Linux-Arbeitsumgebung wurden keine Swift-/EventKit-/AppKit-Tests
ausgeführt. Vor Freigabe sind auf unterstützten Macs erforderlich:

1. Native Kompilierung und Swift-Core-/Bridge-Tests, einschließlich der
   gemeinsamen Fixture- und Zeitzonenfälle.
2. Auswahl und vollständige Vorschau mit echten lokalen/iCloud- und
   gegebenenfalls weiteren verfügbaren Erinnerungslisten; offene und
   erledigte Einträge, DATE, floating, Zeitzonen und Ausschlussfälle.
3. Ablehnung/Widerruf der Berechtigung, gelöschte oder verschobene Quellen,
   Änderungen während der Vorschau, Abbruch und Zeitüberschreitung.
4. Tatsächliche Bearbeitung, dauerhaftes Speichern, Neustart,
   Wiederherstellung und Erhalt bestehender Aufgaben samt Unteraufgaben.
5. Installations-/Start- und Geräteabnahme des daraus gebauten Pakets.

Linux und Windows verwenden keine EventKit-API. Der Patch verändert ihre
Produktquellen nicht. Der JSON-Austausch der neuen Zusatzmetadaten mit diesen
Editionen ist hier nicht nativ geprüft. Deren gemeinsamer Aufgaben-Normalizer
übernimmt unbekannte Herkunftsfelder nicht wie `MacBeta.preserve`; ihr Erhalt
beim Austausch darf daher nicht vorausgesetzt werden. Diese konkrete
Quellenabweichung wird in #779 separat geprüft; eine native
Verlust-Reproduktion wird nicht behauptet. Vorhandene gemeinsame Datentypen und
die bewusst begrenzte Abbildung vermeiden zusätzliche aktive ICS-Sonderfelder;
daraus wird keine vollständige Plattformfreigabe abgeleitet.
