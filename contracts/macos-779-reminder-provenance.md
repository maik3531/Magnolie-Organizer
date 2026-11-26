# #779 — Aufgabenherkunft beim Desktop-/Mac-Austausch

Geprüfte Produktbasis: `616069f15fed21d8d8d05c8ef795f4ed21bd059c`.
Der ursprüngliche Verdacht eines Feldverlusts ist im vollständigen aktuellen
JavaScript-Pfad **nicht bestätigt**. `normalisiere()` baut Aufgaben zunächst
explizit auf, ruft vor seiner Rückgabe aber `bewahreUnbekannteFelder(d, roh)`
auf. Dieser erhält unbekannte Aufgabenfelder anhand der vorhandenen lokalen
ID, darunter `nativeReminderImport` und `nativeReminderRecord`.

Deshalb enthält dieser Patch eine überprüfbare Regression und Befundkorrektur,
keine unnötige Änderung der Produktnormalisierung. Er macht keine Aussage
über andere oder ältere Quellstände ohne diesen Erhaltungspfad.

## Tatsächlich ausgeführte Prüfung

Node 24.22.3, JSDOM 26.1.0, Linux-Prüfhost. **80 Assertions bestanden**:

- Tatsächliche getrennte Linux- und Windows-Frontendquellen laden ein
  synthetisches JSON-Buch mit dem vollständigen öffentlichen #777-Fixture.
- Tatsächlicher Aufgabeneditor ändert den lokalen Titel. Der kanonische
  Save-Payload bewahrt lokale ID/UID, Herkunft und ursprüngliche Rohfelder.
- Die öffentlichen Callbacks für Journal-Restore, klassische Sicherung und
  vollständiges Archiv erhalten dieselben Felder; erneute Normalisierung ebenso.
- Jahr-/Zeit-/Unicode-Originalwerte bleiben im Quellenbeleg unverändert.
  Auch unbekannte künftige Metadaten bleiben passiv. Inhalte darin aktivieren
  keine Synchronisation, Delegation oder Erinnerung.
- Beide gespeicherten Desktop-Ergebnisse kehren in die tatsächlich erzeugte
  Mac-Oberfläche zurück. Derselbe native Herkunftsschlüssel wird als vorhandene
  Kopie erkannt, ohne neue Aufgabe oder Überschreiben der lokalen Titeländerung.
- Eine im Papierkorb liegende Kopie wird anhand ihrer Herkunft erkannt und
  beim erneuten Vorschlag ausgeschlossen.

Die nativen Antwort-/Save-ACKs und Quelldaten sind synthetisch. Es wurden keine
installierten Linux-/Windows-/Mac-Programme, nativen Speichermedien oder echten
EventKit-Konten ausgeführt. Diese Grenzen bleiben separat offen.

## Wiederholen

Aus der Repositorywurzel, nach Installation der bestehenden
`magnolie-organizer-windows/package.json`-Testabhängigkeiten:

```sh
python3 magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py
python3 magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py --output magnolie-organizer-windows/app/web
python3 Magnolie-Organizer-macOS-Beta/tools/check_reminder_desktop_roundtrip.py --js-runtime node
```

Bei einer externen vorhandenen JSDOM-Installation `MACOS_BETA_JSDOM` auf deren
`jsdom/lib/api.js` setzen. Der Runner erzeugt eine kurzlebige Mac-Projektion,
führt beide tatsächlichen Desktop-Frontends aus und prüft, dass die Mac-
Produkteingaben während des Laufs unverändert bleiben. Der reine Desktop-Test
kann auch mit `node magnolie-organizer-windows/tests/native-reminder-provenance.js`
ausgeführt werden; er meldet dann ausdrücklich `macReplay: false` und 72 Assertions.

Für Codex: zuerst diesen Regressionstest auf dem zu übernehmenden Zielstand
ausführen. Nur bei einer dort tatsächlich abweichenden Erhaltungskette einen
Produktfix entwickeln. Kein pauschales Ersetzen aller Aufgaben durch einen
ungeprüften Objekt-Spread und keine Herkunftsfelder als Schreibfreigabe deuten.
