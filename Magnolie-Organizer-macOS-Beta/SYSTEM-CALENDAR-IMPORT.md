# Mac-Systemkalender: lokale Terminübernahme

Quellpatch zu [#770](https://github.com/maik3531/Magnolie-Organizer/issues/770),
Fortsetzung von #721 / #121. Stand: 25. November 2026.

Der Anschluss verwendet Apples vorhandenes EventKit und den Kalenderbestand des
Macs. Der Nutzer benötigt dafür kein zusätzliches Programm und keine eigene
iPhone-App. Ist derselbe geeignete Kalender auf iPhone und Mac eingerichtet,
bleibt Apple Kalender die iPhone-Oberfläche. Die Kontosynchronisation übernimmt
weiterhin der eingerichtete Anbieter. AirPlay ist davon unabhängig.

**Quellstand mit ausgeführten JS-Vertragstests, keine native Freigabe.** Dieser
neue Swift-/AppKit-Code wurde hier weder kompiliert noch mit realen Konten oder
einem iPhone ausgeführt. Ältere Mac-Prüfungen anderer Quellstände gelten nicht
als Abnahme dieses Anschlusses.

## Bedienung nach dem nativen Bau

1. Das Magnolie-Buch öffnen und entsperren. Im App-Menü **Termine aus einem
   Mac-Kalender übernehmen** wählen; alternativ in den Systemkonten den
   Kalenderimport öffnen. Der bestehende Editor-/Speicherablauf behandelt zuvor
   offene Änderungen.
2. Falls erforderlich, den ausdrücklich angeforderten Kalenderzugriff in macOS
   freigeben. Bloßes Auflisten von Konten fordert weiterhin keine Berechtigung an.
3. Einen tatsächlichen EventKit-Kalender und einen Zeitraum auswählen. Der letzte
   Tag ist einschließlich gemeint. Datumsspannen werden in der Anzeigezeitzone
   ausgewertet, mit der bestehenden normativen Zeitzonendatenbank.
4. Die Vorschau zeigt neue Termine, bereits übernommene Termine, Änderungen in
   der Quelle sowie ausgelassene Einträge mit Gründen. Während des Lesens ist
   Abbruch möglich. Gleiche Kalendernamen werden über ihre tatsächlichen
   Kennungen getrennt ausgewählt.
5. **Lokale Kopien übernehmen** bestätigen. Der Host liest den gewählten Bereich
   erneut; eine geänderte Quelle erfordert eine neue Vorschau. Vor der Mutation
   entsteht über den bestehenden Speicherweg ein Wiederherstellungspunkt.
6. Erfolg erscheint erst, wenn die neuen Termine dauerhaft gespeichert wurden.
   Scheitert die abschließende Speicherung, bleiben die Kopien als ungespeicherte
   Änderungen sichtbar. Diese zuerst speichern; es wird kein Erfolg behauptet.

Die Auswahl bereits bekannter Systemquellen in den Einstellungen startet keinen
Import. Die neue Aktion besitzt ihren eigenen nativen Auswahl- und Prüfablauf.

Nachtrag [#773](https://github.com/maik3531/Magnolie-Organizer/issues/773): Der
Startknopf bei den Systemkonten verlässt den eigenen Einstellungsdialog nach
dem bestehenden Editor-/Speicher-Guard über dessen kanonischen Schließpfad.
Andernfalls blockierte der noch offene Einstellungsmodal die spätere native
Vorschau. Weitere offene Dialoge bleiben geschützt; die Vorschauprüfung wird
nicht gelockert. Der Knopf bleibt während einer unvollständigen Quellenanfrage
gesperrt und startet ausschließlich den parameterlosen nativen Auswahlweg.
Ungespeicherte DAV-/Nextcloud-Eingaben werden gesondert vor dem Start und erneut
vor dem Schließen geprüft, einschließlich einer alleinigen Kennworteingabe.
Solche sichtbaren Entwürfe bleiben erhalten und blockieren den Import mit einem
Hinweis. Der Start speichert oder verwirft keine Kontokonfiguration automatisch.

## Was übernommen wird

Unterstützte einzelne Termine werden als **bearbeitbare lokale Kopien** angelegt.
Titel, Notiz, Ort, Anfang und Ende, Ganztagsdaten, unterstützte URL sowie
bestätigter/vorläufiger Status und frei/belegt werden erhalten. Zeitgebundene
Termine verwenden präzise UTC-`DTSTART`-/`DTEND`-Zeilen; die sichtbare Minutenanzeige
ersetzt diese Zeitquelle nicht. Ganztagstermine behalten DATE-Werte und das
exklusive iCalendar-Enddatum. Die gelesenen öffentlichen Ursprungsfelder und die
Herkunft bleiben zusätzlich in den Buchdaten erhalten.

Die Übernahme begrenzt jeden Lauf auf **366 Tage, 10.000 Datensätze und 16 MiB**.
Ein überschrittenes Gesamtlimit bricht den Vorschlag ab; es wird kein verkürzter
Teilbestand als vollständige Übernahme ausgegeben. Der konservative Zeitraum
liegt unter der EventKit-Grenze, oberhalb derer Apple die Abfrage verkürzt.
Der allgemeine ältere Quellenleser wird separat in #771 geprüft.

Ausgelassen werden insbesondere Serien und abgetrennte Instanzen, Termine mit
Alarmen oder Teilnehmern, Geburtstagskalender, abgesagte Termine, unklare
Kennungen/Datumsgrenzen, nicht abbildbare Zustände und Angaben, die der gemeinsame
Organizer-Normalisierer kürzen oder verändern würde. Die Vorschau nennt diese
Auslassungen. Eine vorhandene Erinnerung wird nicht still entfernt und als
vollständig übernommener Termin dargestellt.

Für Kopien werden keine neuen Standarderinnerungen aktiviert. Gezielte
Mac-Projektionsanpassungen erhalten diesen ausdrücklichen Zustand beim erneuten
Laden, beim Bearbeiten und in der laufenden Erinnerungsprüfung. Gewöhnliche Organizer-Termine
behalten ihr bisheriges Verhalten. Bei Kalenderkopien bleibt die Auswahl der
Standarderinnerung im Editor sichtbar, damit sie bewusst eingeschaltet werden
kann. Später gesetzte lokale Alarme bleiben eine eigene Benutzerentscheidung.

## Wiederimport, Änderungen und Datenhaltung

Die Kopieridentität bindet die bytegenaue native Kalenderkennung und
Ereigniskennung. Titel und Datum dienen nicht als Dublettenschlüssel. Verschiebt
sich ein Termin bei gleichbleibender nativer Kennung, bleibt die Zuordnung
erhalten. Ein anderer Kalender oder eine andere Kennung ist eine andere Quelle;
Apple weist ausdrücklich darauf hin, dass ein Kalenderwechsel die
Ereigniskennung ändern kann. Es gibt keine behauptete Wiedererkennung über
Kontoneueinrichtung oder Kalenderwechsel hinweg.

| Situation | Verhalten |
| --- | --- |
| Noch nicht vorhandene native Identität | Neue lokale Kopie nach Vorschau und Bestätigung |
| Bereits übernommene Identität, gleiche Quellrevision | Als bereits vorhanden zählen; keine zweite Kopie |
| Bereits übernommene Identität, geänderte Quellrevision | Änderung mit Titel/Datum anzeigen; bestehende Kopie erhalten |
| Lokal bearbeitete Kopie | Unverändert erhalten |
| Kopie im Papierkorb | Nicht neu anlegen; Hinweis auf Wiederherstellung aus dem Papierkorb |
| Widersprüchliche Herkunft, mehrere Zuordnungen oder anderes Elternkonto | Übernahme ohne Mutation zurückweisen |
| Termin fehlt im aktuellen Zeitfenster | Keine lokale oder native Löschung |

Die Vorschau liegt nur im Speicher. Sie ist an das tatsächliche Buchobjekt,
seinen Inhalt, die Anzeigezeitzone und eine begrenzte Gültigkeit gebunden. Ein
nachträglich geöffneter Editorentwurf blockiert die Mutation auch dann, wenn er
noch nicht in den Buchdaten steht. Entsperrung, Wiederherstellung, Beenden,
Dokumentgeneration, Quellenberechtigung und Quellinhalt werden an den relevanten
Übergängen erneut geprüft.

Die Quellrevision erfasst **nur die serialisierten öffentlichen Felder**. Sie ist
kein Server-ETag, kein atomarer EventKit-Schreibschutz und kein Beleg für
anbieterinterne Daten. Quelle und Magnolie-Buch sind keine gemeinsame atomare
Datenbanktransaktion; übernommen wird der geprüfte Lesestand. Es gibt keinen
nativen Schreibzugriff, keine Hintergrundsynchronisation und keine Löschfreigabe.

Vollständige JSON-Sicherungen erhalten die Herkunftserweiterungen. Der vorhandene
strenge ICS-Export weist derzeit nicht exportierbare Herkunftserweiterungen
zurück, statt sie still zu verlieren; ICS-Export solcher Kopien ist deshalb
noch kein freigegebener Roundtrip. Erinnerungen, Kontakte und Apple Notes
erhalten durch diesen Kalenderanschluss keine neue Synchronisationsfunktion.
Die Machbarkeitsmatrix steht in `IPHONE-INTEROPERABILITY.md`.

## Implementierung und Nachweis

- `Sources/BetaCore/SystemCalendarImport.swift`: begrenzte, reine Vorbereitung,
  kanonischer iCalendar-Codec, Herkunft und erneute Inhaltsprüfung.
- `Sources/MacBeta/SystemCalendarImportHost.swift`: native Berechtigung,
  Quell-/Datumsauswahl, abbrechbares Lesen, Vorschau und Übergabe.
- `Projection/system-calendar-import.js`: privater Vorschlag, Dublettenschutz,
  ausschließlich additive Mutation und bestehende dauerhafte Speicherung.
- `macos_kalender_importieren` erlaubt nur den parameterlosen Dialogaufruf.
  Dateipfade, Kontokennungen oder fremde Nutzlasten werden von diesem
  Renderer-Befehl nicht als Auswahl oder Berechtigung angenommen.

Portable Prüfung mit vorhandenem Node/JSDOM:

```bash
MACOS_BETA_JSDOM=/absolute/path/to/jsdom/lib/api.js \
python3 Magnolie-Organizer-macOS-Beta/tools/check_system_calendar_import.py \
  --js-runtime /absolute/path/to/node
```

Der Prüfer erzeugt die tatsächliche Projektion aus den aktuellen Quellen,
benutzt echte kanonische Editor-, Kalender-, Erinnerungs- und Speicherfunktionen
und meldet Änderungen der Eingangsquellen während des Laufs. EventKit-Nutzlasten
und native Speicherantworten sind synthetisch. Er installiert keine Werkzeuge.
Die Swift-Fälle in `SystemCalendarImportTests.swift` prüfen den Kern und die
Enumwerte gegen das tatsächliche EventKit-SDK, wurden hier aber nicht ausgeführt.

Vor einem installierbaren Kandidaten bleiben auf Intel und Apple Silicon offen:
Swift-Bau und vollständige relevante Tests, tatsächliche Kalender-/Rechteauswahl,
verweigerter und widerrufener Zugriff, Konto-/Quellwechsel, gleiche Anzeigenamen,
Datumseingabe und Barrierefreiheit, echte UTC-/Ganztag-/Zeitumstellungsfälle,
Quelländerungen während der Vorschau, Abbruch und erneutes Öffnen, verschlüsseltes
Profil sowie dauerhafte Speicherung/Wiederöffnung. Die iPhone-Gegenprobe muss
denselben tatsächlich eingerichteten Kalender verwenden.

## Primärquellen

- [Apple EventKit](https://developer.apple.com/documentation/eventkit)
- [EventKit-Ereignisse lesen](https://developer.apple.com/documentation/eventkit/ekeventstore/events(matching:))
- [EventKit-Datumsprädikat und Vierjahresgrenze](https://developer.apple.com/documentation/eventkit/ekeventstore/predicateforevents(withstart:end:calendars:))
- [EventKit-Ereigniskennung und Kalenderwechsel](https://developer.apple.com/documentation/eventkit/ekevent/eventidentifier)
- [Änderungen am EventKit-Bestand](https://developer.apple.com/documentation/eventkit/ekeventstorechangednotification)

Quellpatch und native Paketfreigabe bleiben getrennt. Die Änderungen werden für
die spätere Übernahme mit Codex in einem Arbeitszweig und im Issue gesichert;
dieser Schritt führt keinen Merge nach `main` aus und veröffentlicht kein Paket.
