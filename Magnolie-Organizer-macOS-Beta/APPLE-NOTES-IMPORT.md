# Apple-Notizen direkt als lokale Textkopien übernehmen

Quellpatch zu [#772](https://github.com/maik3531/Magnolie-Organizer/issues/772),
Fortsetzung von #721 und #770. Stand: 25. November 2026.

Der Anschluss verwendet Foundation `NSAppleScript` und die vorhandene Mac-App
**Notizen**. Es wird kein zusätzliches Empfänger-, Skript- oder Notizprogramm
installiert. Für Inhalte vom iPhone müssen die gewünschten Notizen bereits im
entsprechenden Konto der Mac-App verfügbar sein. Die bestehende Apple-Notizen-App
bleibt auf dem iPhone nutzbar; Magnolie benötigt dafür keine eigene iPhone-App.
AirPlay überträgt weiterhin nur Bild und Ton und ist kein Transport für diese
Notizdatensätze.

**Implementierter Quellpfad zur Prüfung, keine native Funktionsfreigabe.** Hier
stehen weder macOS noch eine Swift-Toolchain bereit. Der neue native Code wurde
in dieser Umgebung nicht kompiliert oder mit Apple Notizen ausgeführt. Insbesondere
die installierte Notes-Scripting-Dictionary, deren konkrete Rückgabetypen sowie
Automation-Freigabe und Inhaltsvollständigkeit sind native Abnahmekriterien.
Eine nicht unterstützte Dictionary oder ein nicht prüfbarer Zustand führt zu
einem Fehler beziehungsweise sichtbaren Ausschluss; fehlende Informationen
werden nicht durch erfundene Normalwerte ersetzt.

## Bedienung nach dem nativen Bau

1. Das Magnolie-Buch entsperren und das gewünschte bestehende Notizbuch auswählen.
   **Textkopien aus Apple Notizen …** im App-Menü oder bei den Systemquellen öffnen.
   Der kanonische Editor-/Speicherablauf behandelt zuvor offene Änderungen.
2. Falls macOS danach fragt, die Automation-Freigabe für Apple Notizen erteilen.
   Erst die ausdrückliche Importaktion greift auf Notizen zu. App-Start und die
   allgemeine Systemkontenanzeige starten diesen Zugriff nicht.
3. Konto und Ordner anhand der tatsächlich gefundenen Quellen auswählen. Gleiche
   Anzeigenamen bleiben getrennte Einträge mit eigenen Quellkennungen.
4. Bis zu 32 Notizen auswählen. Die Liste enthält Titel und Schutzstatus;
   Notiztexte werden erst für die ausgewählten Kennungen gelesen.
5. Vollständige Textvorschau und Zielnotizbuch prüfen. Die Vorschau nennt neue,
   bereits kopierte, an der Quelle geänderte und ausgeschlossene Notizen.
6. **Angezeigten Text kopieren** bestätigen. Derselbe Bestand ausgewählter
   Quellkennungen wird erneut gelesen und mit dem Vorschlag verglichen.
   Geänderte Inhalte oder Zuordnungen erfordern eine neue Vorschau.
7. Die vorhandene Speicherlogik erzeugt den Wiederherstellungspunkt und speichert
   die neuen lokalen Kopien. Erst die dauerhafte Speicherquittung erlaubt eine
   Erfolgsmeldung. Nach einem Speicherfehler bleiben die sichtbaren Kopien
   ausdrücklich ungespeichert; diese Änderungen zuerst speichern.

Ein Abbruch während des Lesens verwirft das Ergebnis. Ein bereits wartender
Apple-Event-Aufruf kann weiterhin zurückkehren; `Task.cancel()` ist keine harte
Beendigung von AppleScript. Der Host und die serialisierte Leserinstanz bleiben
bis zur Rückkehr belegt. Verspätete Ergebnisse dürfen weder importieren noch
einen neuen Vorschlag in einem anderen Dokument öffnen. Nach Beginn der lokalen
Speichertransaktion wird kein Abbruch angeboten, der einen Rollback vortäuschen
würde.

## Was übernommen wird

Übernommen wird ausschließlich der angezeigte **Literaltext** als bearbeitbare
lokale Magnolie-Notiz. Der vorhandene Notizkonstruktor erzeugt daraus escaped
HTML. Die ursprüngliche HTML-Repräsentation aus Notes wird nicht gerendert,
ausgeführt oder zum Laden von URLs verwendet.

Formatierung, Checklisten, Tabellen, Zeichnungen, Tags, Zusammenarbeit und
andere besondere Notes-Funktionen werden nicht als entsprechende Funktionen
konvertiert. Ein Text, der eine Tabelle oder Checkliste beschreibt, bleibt Text.
Die Quellenfassung ist kein vollständiges Archiv der Apple-Notiz.

Leere Titel und Texte, Tabs, LF-Zeilenumbrüche, Emoji und kombinierende
Unicode-Zeichen bleiben in der geprüften Projektion erhalten. CR und CRLF im
Notiztext verändert der vorhandene HTML-Parser; solche Texte werden deshalb
derzeit sichtbar ausgeschlossen. Auch überlange HTML-Knotenfolgen können an
der vorhandenen Editorgrenze scheitern. Der Anschluss kürzt oder normalisiert
die Quelltexte nicht stillschweigend, um diese Grenzen zu umgehen.

| Gelesener Zustand | Verhalten |
| --- | --- |
| Nicht geschützte Notiz, null gemeldete Anhänge, vollständig prüfbarer Text | Neue Textkopie nach Vorschau und Bestätigung |
| Leerer Text | Zulässig, sofern Titel und leere Notiz im kanonischen Editor unverändert erhalten bleiben |
| Geschützte Notiz | Kein Textabruf; sichtbarer Ausschluss |
| Fehlender oder unbekannter Schutzstatus | Sichtbarer Ausschluss, kein erfundenes `false` |
| Mindestens ein gemeldeter Anhang | Kein Textkopie-Import; separater Dateiimport für ausdrücklich exportierte Dateien |
| Unbekannter Anhangsstatus oder fehlende Text-/Revisionsinformation | Sichtbarer Ausschluss |
| Fehler beim Lesen einer ausgewählten Notiz | Sichtbarer Ausschluss; Quell-/Identitäts-/Berechtigungsfehler können den gesamten Lauf abbrechen |
| Normalisierung würde Titel, Text, HTML oder Herkunft verändern | Sichtbarer Ausschluss statt gekürzter Kopie |
| Quelle, Konto, Ordner oder ausgewählte Identität verändert | Neuer Auswahl-/Vorschauablauf erforderlich |

„Keine gemeldeten Anhänge“ ist allein kein Nachweis, dass die Scripting-Schnittstelle
alle Inhalte einer Apple-Notiz beschreibt. Die tatsächlichen Notes-Fälle mit
Tabellen, Zeichnungen, geteilten Inhalten und Anhängen bleiben deshalb Teil der
nativen Inhaltsabnahme. Der Nutzer bestätigt ausdrücklich nur den sichtbaren
Text, keine behauptete vollständige Notizmigration.

## Identität, Wiederimport und Speichern

Die Kopieridentität entsteht aus längengefassten, bytegenauen UTF-8-Werten der
nativen Konto- und Notizkennung. Namen, Titel und Text sind keine
Dublettenschlüssel. Der Ordner ist Teil der Herkunft und Revision; ein
Ordnerwechsel bei unveränderter Konto-/Notizkennung erzeugt keine zweite
Identität. Eine neue native Kennung oder ein anderes Konto wird als andere
Quelle behandelt. Eine Wiedererkennung nach Kontoneueinrichtung wird nicht
behauptet.

| Situation | Verhalten |
| --- | --- |
| Neue Quellidentität | Neue lokale Notiz mit frischer Magnolie-ID |
| Bereits kopiert, unveränderte Quellrevision | Überspringen, keine Dublette |
| Bereits kopiert, Quelle inzwischen geändert oder verschoben | Geänderte Quelle in der Vorschau nennen, vorhandene Kopie erhalten |
| Lokal bearbeitete Kopie | Titel, Text, Anhänge und andere lokale Änderungen erhalten |
| Kopie im Papierkorb | Nicht automatisch wieder anlegen |
| Widersprüchliche oder mehrfache lokale Quellzuordnung | Gesamten Vorschlag ohne Mutation zurückweisen |
| Notiz fehlt in der aktuellen Auswahl | Keine lokale oder native Löschung |

Der private JS-Vorschlag ist an das tatsächliche Buchobjekt, dessen vollständigen
Inhalt, das Zielnotizbuch und eine begrenzte Lebensdauer gebunden. Offene Editor-
und Modalzustände einschließlich noch nicht übernommener Notizeditor-Eingaben
blockieren die Mutation. Diese Prüfung findet vor und nach dem bestehenden
Recovery-Checkpoint statt. Dokumentwechsel, Sperre, Wiederherstellung und
Beenden werden zusätzlich auf der nativen Seite geprüft.

`nativeAppleNotesImport` hält die Kopierart, Quellkennungen, Namen, Identität und
Revision. `nativeAppleNotesRecord` hält die tatsächlich gelesenen Felder der
importierten Textkopie. Vollständige JSON-Buchsicherungen erhalten diese
Erweiterungen. Ein reiner Text-/Notizexport ist kein Backup aller
Herkunftsmetadaten oder der ursprünglichen Notes-Funktionen.

Die Revision gilt für **serialisierte gelesene Felder**: Titel, Plaintext,
HTML-Repräsentation, Änderungsinformation, Schutz-/Anhangsstatus und
Quellzuordnung. Die Vorschau bindet auch ausgeschlossene ausgewählte Einträge.
Das Änderungsdatum allein genügt nicht. Quelle und Magnolie-Buch bilden keine
gemeinsame atomare Datenbanktransaktion; es gibt keinen serverseitigen CAS-Token.
Nach der erneuten Leseprüfung wird der geprüfte Lesestand kopiert.

## Technischer Umfang

- `Sources/MacBeta/AppleNotesReader.swift`: feste AppleScript-Handler, typisierte
  Argumente und Antworten als Apple-Event-Deskriptoren, serieller Hintergrundzugriff,
  tatsächliche Quellkennungen und lesende Erfassung.
- `Sources/BetaCore/AppleNotesImport.swift`: begrenzte reine Datenvorbereitung,
  bytegenaue Identität, Revision, Ausschlüsse und erneuter Snapshotvergleich.
- `Sources/MacBeta/AppleNotesImportHost.swift`: native Konto-/Ordner-/Notizauswahl,
  vollständige Literaltextvorschau, Abbruch und erneutes Lesen vor der Übernahme.
- `Projection/apple-notes-import.js`: kanonische lokale Notizen, private
  Vorschläge, Herkunfts-/Papierkorbschutz, Recovery-Checkpoint und Speicherquittung.
- `macos_apple_notizen_importieren`: ausschließlich parameterloser Dialogaufruf.
  Der Renderer erhält dadurch keine Möglichkeit, Skripte, Quellkennungen oder
  beliebige Importnutzlasten als native Auswahl zu übergeben.
- `NSAppleEventsUsageDescription`: Zweckbeschreibung für die reguläre
  macOS-Automation-Freigabe. Die vorhandene Beta bleibt ein nicht gehärteter,
  nicht sandboxed Entwicklungsbau; eine spätere Hardened-Runtime-Konfiguration
  benötigt zusätzlich die passende Apple-Events-Entitlement und eigene Abnahme.

Grenzen: 32 ausgewählte Notizen, 1 MiB pro Text beziehungsweise HTML-Feld,
8 MiB für den gesamten Nachweis und unabhängig davon die finale JSON-Nutzlast,
4096 UTF-8-Bytes pro Titel und 16384 pro Kennung. Quell- und Metadatenlisten
besitzen zusätzliche Grenzen. Übergrenzen werden nicht als abgeschnittener
vollständiger Bestand dargestellt.

Die Produktimplementierung verwendet weder `osascript` noch Shellbefehle,
UI-Automation, private Notes-Datenbanken oder CloudKit-Innendaten. Namen und IDs
werden als Daten an feste Handler übergeben, niemals in Skripttext eingefügt.
Es gibt keine Apple-Notes-Schreib-, Lösch-, Verschiebe- oder Entsperrbefehle.
`with timeout` begrenzt das Warten auf einzelne Anwendungskommandos; es ist keine
allgemeine harte Prozess- oder Speichergrenze. Begrenzte Schleifen und spätere
Ergebnisverwerfung ergänzen diese Grenze.

## Wiederholbare Prüfung

Die portable Prüfung verwendet die tatsächliche aktuelle UI-Projektion und den
kanonischen Notizeditor mit synthetischen Notes-Nutzlasten und einem
synthetischen nativen Speichertransport:

```bash
MACOS_BETA_JSDOM=/absolute/path/to/jsdom/lib/api.js \
python3 Magnolie-Organizer-macOS-Beta/tools/check_apple_notes_import.py \
  --js-runtime /absolute/path/to/node
```

Der Prüfer überwacht die Eingangsdateien und verwirft einen Lauf, in dem sich
der Quellstand ändert. Er installiert keine zusätzlichen Werkzeuge.

Auf einem Mac im vorhandenen Swift-Paket:

```bash
swift test --filter AppleNotesImportTests
```

Die Swift-Fixtures prüfen reine Quellidentitäten, Revisionen, Inhaltsschranken
und den Bridgevertrag. Sie sind kein Ersatz für einen Lauf der tatsächlichen
Notes-Skripte, der Automation-Freigabe oder des AppKit-/WKWebView-Ablaufs.
Die vorgegebenen Projektions-/Bauschritte in `README.md` bleiben maßgeblich;
fehlende Sprachkataloge dürfen nicht durch Ersatzdaten verdeckt werden.

## Offene native Abnahme

Vor einer Aussage zur tatsächlichen Nutzbarkeit auf macOS 12.7 und einem
aktuellen unterstützten macOS müssen Intel und Apple Silicon geprüft werden:

1. Swift/AppKit/Foundation kompilieren und die relevanten Pakettests ausführen.
2. In Apples Script Editor die installierte Notes-Scripting-Dictionary prüfen.
   Benötigte Begriffe: Konto, Ordner, Notiz, native ID, Name, Container,
   `plaintext`, `body`, `password protected`, `modification date` und Anhänge.
   Rückgabetypen mit den tatsächlich gesendeten Deskriptoren vergleichen.
3. Die gebaute Magnolie-App ausführen: Freigabe erteilen, verweigern und später
   entziehen; Notizen geschlossen, geöffnet, blockiert und nicht verfügbar testen.
   Eine Script-Editor-Freigabe beweist keine Freigabe der Magnolie-App.
4. Gleichnamige Konten, verschachtelte/gleichnamige Ordner, gleichnamige Notizen,
   verschobene und gelöschte Notizen sowie echte iCloud-Änderungen prüfen.
   Kontrollieren, dass zurückgelieferte Notes-Objektreferenzen an stabile IDs
   gebunden bleiben: Aufzählung und Reihenfolge während eines Lesevorgangs ändern
   und die tatsächlichen Deskriptoren prüfen. Die vorhandenen Vorher-/Nachher-
   Identitätsprüfungen allein beweisen keine atomare Referenzstabilität.
5. Schutzstatus, Anhänge, Zeichnungen, Tabellen, Checklisten, geteilte Notizen,
   Unicode, Zeilenumbrüche, leere Notizen und Größenüberschreitungen prüfen.
6. Quelle während der Vorschau ändern, Dokument/Notizbuch wechseln, neue
   Editoreingaben beginnen, abbrechen und verspätete Antworten provozieren.
7. Speicherfehler, verschlüsseltes Profil, Wiederöffnung, erneuten Import und
   Papierkorb/Wiederherstellung anhand tatsächlicher gespeicherter Daten prüfen.
8. Eine auf dem iPhone erstellte Notiz über das tatsächlich gemeinsame
   Mac-Notizkonto lesen und den Textvergleich durchführen. Die Kontosynchronisation
   bleibt Aufgabe des eingerichteten Anbieters.

## Primärquellen

- [Apple DTS: Apple Notes API](https://developer.apple.com/forums/thread/813810)
- [Foundation: NSAppleScript](https://developer.apple.com/documentation/foundation/nsapplescript)
- [Apple DTS: NSAppleScript außerhalb des Hauptthreads und Serialisierung](https://developer.apple.com/forums/thread/759287)
- [Apple: NSAppleEventsUsageDescription](https://developer.apple.com/documentation/bundleresources/information-property-list/nsappleeventsusagedescription)
- [Apple: Apple Events Entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.automation.apple-events)
- [AppleScript Language Guide: Timeout](https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_control_statements.html)
- [Apple Script Editor: Scripting-Dictionary einer App ansehen](https://support.apple.com/en-mo/guide/script-editor/scpedt1126/mac)
