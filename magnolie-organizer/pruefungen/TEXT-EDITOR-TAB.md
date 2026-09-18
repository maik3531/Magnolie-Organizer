# Tabulatoren und Designer-Aktionszeile – Prüfung vom 14.09.2026

## Bedienung und Quellumfang

In beiden Desktop-Quellen heißt die Datei `web/anwendung.js`:

- Linux: `magnolie-organizer/web/`
- Windows: `magnolie-organizer-windows/app/web/`

`bindeSchreibTab` ist ausschließlich an das Notiz-Schreibblatt `#notiz-text`,
die Kalender-/Terminnotiz `#tb-notiz` und bearbeitbare Custom-Textblöcke gebunden.
Tab fügt ein echtes U+0009-Zeichen an der Schreibmarke ein und ersetzt eine
vorhandene Auswahl. Umschalt+Tab führt zum vorherigen Feld, Strg+Tab zum
nächsten erreichbaren Bedienelement. Der sichtbare, mit `aria-describedby`
zugeordnete Hinweis enthält manuell ausgeschriebene Texte für alle 20 Sprachen.

Die native Bearbeitungshistorie verarbeitet Strg+Z, Strg+Umschalt+Z und Strg+Y.
Einfügen erzeugt genau ein natives `beforeinput` und ein natives `input`;
es gibt kein zusätzliches künstliches Draft-/Speicherereignis. Der Handler
prüft Fokus, Schreibschutz, Komposition und die Grenzen einer Richtext-Auswahl.

Die vorhandene separate `.custom-editor-aktionen`-Zeile samt 12 px Abstand
wurde erhalten. Das Checkbox-Label ist nun ein eigener flexibler Block mit
oben ausgerichteter Checkbox. Custom-Richtext verwendet `white-space: pre-wrap`,
damit auch nach dem Entfernen von WebKit-spezifischen Span-Attributen durch die
HTML-Bereinigung Tabulatoren sichtbar bleiben.

Die Tab-Erkennung im modalen Fokusumlauf berücksichtigt außerdem `code=Tab`:
WebKitGTK meldet bei einem echten Umschalt+Tab hier `key=Unidentified`,
`code=Tab`, `keyCode=9`. Escape und die übrige Dialoglogik werden weiter über
die vorhandenen Handler verarbeitet.

## Reproduzierbare native Prüfung

Vom Veröffentlichungs-Quellverzeichnis aus, nacheinander ausführen:

```sh
mkdir -p /tmp/opencode/text-editor-native
sh magnolie-organizer/pruefungen/text_editor_isolated.sh --web linux
sh magnolie-organizer/pruefungen/text_editor_isolated.sh --web windows
```

Der Wrapper begrenzt jeden Lauf auf 240 Sekunden und CPU 0/1. Er verwendet
einen privaten Xvfb, WebKitGTK 2.52.6, Software-Rendering, einen flüchtigen
Browserkontext, ausgeblendete Host-/GPU-Geräte, ein leeres Home und einen
isolierten D-Bus. Eingebunden werden nur die beiden Web-Quellverzeichnisse,
das Prüfskript und das Nachweisverzeichnis. Die Speicherbrücke nimmt synthetische
JSON-Daten entgegen; der produktive Anwendungskern wird nicht gestartet.

| Lauf | Ergebnis | Dauer | Prüfblöcke | Screenshots |
|---|---|---:|---:|---:|
| Linux-Webquellen | erfolgreich | 88,77 s | 72 | 15 |
| Windows-Webquellen in WebKitGTK | erfolgreich | 88,53 s | 72 | 15 |

Geprüft wurden:

- echte XTest-Tastendrücke: Tab, Umschalt+Tab, Strg+Tab, Rückgängig/Wiederholen,
  normale Texteingabe und Return;
- leere Felder, Einfügen in der Mitte, Auswahlersetzung, formatierte Auswahl,
  wiederholte sowie führende und abschließende Tabulatoren;
- genau ein natives Input-Ereignispaar pro Einfügung und abbrechbares `beforeinput`;
- Schreibschutz, fehlende/feldfremde Auswahl und laufende Komposition;
- japanisch-arabischer Text über das native WebKit-Eingabemethoden-Commit;
- mehrzeiliger Text durch Speichern, JSON und Neuladen in allen drei Schreibflächen;
- echte Checkbox-/Fokusbedienung im Designer, Tab-Umlauf an beiden Dialogrändern,
  Escape sowie normale Tab-Navigation in Suche und Titel;
- je 43 Designer-Layouts: alle 20 Sprachen bei 1280 px und 390 px, zusätzlich
  Deutsch, Arabisch und Französisch bei 200 % Zoom;
- mindestens 12 CSS-px Abstand zwischen letzter Einstellung und Entfernen-Knopf,
  kein horizontaler Dialog-/Control-Überlauf; bei normaler Breite zwei Spalten;
- tatsächliche WebKit-PDF-Ausgabe des vorhandenen Notiz-/Custom-Druck-HTML:
  erhaltene Zeilenumbrüche und Positionierung an Vielfachen eines Tabstopps.

Die JSON-Berichte enthalten native Ereignisse, Geometrie und SHA-256-Werte der
vier geprüften Quelldateien. Die abschließende Hash-/Paritätsprüfung bestätigte
identische Editor-Handler in beiden Quellen und die Übereinstimmung der
Berichte mit dem aktuellen Quellstand. `git diff --check` für die vier
geänderten Webdateien war erfolgreich.

## Nachweise

Unter `/tmp/opencode/text-editor-native/{linux,windows}/` liegen jeweils:

- `report.json`
- `note-reloaded-tabs.png`, `custom-reloaded-tabs.png`, `diary-reloaded-tabs.png`
- `designer-de-1280-zoom1.png`, `designer-ar-390-zoom1.png`
- `designer-de-1280-zoom2-remove-row.png` sowie entsprechende AR-/FR-Bilder
- synthetische `*-saved.json`, Druck-HTML, native PDF-Dateien und PDF-Textkoordinaten
- ODT-Proben und deren `content.xml`

## Explizite Prüfgrenzen

**ODT:** Die derzeitige Oberfläche besitzt keinen direkten Notiz-/Custom-ODT-
Export. Die ergänzende LibreOffice-Probe unterscheidet zwei Wege:

- Erhaltener Klartext → ODT: alle drei Tabulatoren werden als `text:tab`
  gespeichert. Die semantische Rückübersetzung des ODT-Inhalts ergibt exakt
  `First\tB\n\tC\t`.
- Bestehendes Druck-HTML → LibreOffice → ODT: **keine** `text:tab`-Elemente;
  LibreOffice faltet die HTML-Tabulatoren. Dieser Weg ist nicht verlustfrei.
  Der erfolgreiche Gesamtlauf umfasst hier eine dokumentierte Diagnose,
  keine bestandene Behauptung verlustfreier HTML-zu-ODT-Konvertierung.

**Plattform/Eingabe:** Die Windows-Webquellen wurden mit derselben nativen
WebKitGTK-Engine geprüft, nicht unter Windows/WebView2. Der Kompositions-Guard
wurde mit einem DOM-Kompositionsstart und echtem Tab getestet; der Unicode-
Commit durchlief den nativen WebKit-IME-Kontext. Eine physische Touch-Tastatur
und eine vollständige betriebssystemspezifische IME-Preedit-Sitzung wurden
nicht geprüft. Es wurden keine VMs/Emulatoren und kein Produktionsbuild oder
Veröffentlichungslauf gestartet.
