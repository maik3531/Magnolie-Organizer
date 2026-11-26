# Mac-Importe: Speicherzustand nach Darstellungsfehler (#778)

## Ausgangspunkt und Fehlernachweis

Basis: `616069f15fed21d8d8d05c8ef795f4ed21bd059c`, der gemeinsame Arbeitszweig
aus #777 mit Kalender-, Apple-Notes- und Kontaktkopien aus #770, #772 und #775.
Dieser Patch ist zur späteren Prüfung/Übernahme vorbereitet; er ist keine
Veröffentlichung und kein nativer Mac-Freigabenachweis.

Alle drei Commit-Handler hängen bestätigte Kandidaten an das lokale Buch an
und rufen dann `planeSpeichern()` und `zeichneAlles()` auf. Erst anschließend
wird der dauerhafte Save-ACK-Callback registriert. Eine Ausnahme im öffentlichen
`MagnolieAppearance.update`-Hook erreicht deshalb den bisherigen Fehlerpfad,
obwohl die lokale Mutation bereits erfolgt ist und ein Save-Timer laufen kann.

Die drei neuen Regressionen wurden **vor dem Produktfix** gegen die reale
erzeugte Oberfläche ausgeführt. Jeder Runner scheiterte mit
`actual: Error: Synthetic renderer failure after append` an der Erwartung,
dass die Meldung zusätzlich die hinzugefügte Kopie und die noch nicht bestätigte
Speicherung erklärt. Die Ausnahme wurde über den öffentlichen Renderer-Hook
ausgelöst; die Commit-Handler und der gemeinsame Renderer wurden nicht ersetzt.

Damit ist dieser Darstellungsfehlerpfad für jeden der drei Anschlüsse
synthetisch reproduziert. Tatsächlicher Datenverlust, ein nativer Absturz
oder ein falsches Erfolgs-ACK werden daraus nicht abgeleitet.

## Änderung

- `appended` wird erst nach erfolgreichem Anhängen gesetzt.
- Ein Folgefehler vor beobachtetem Save-ACK meldet: Kopien hinzugefügt,
  Speicherung noch nicht bestätigt; ausstehende Änderungen prüfen/speichern.
- Ein tatsächliches Save-NACK behält seinen getrennten Hinweis auf noch
  ungespeicherte Kopien.
- Nach beobachtetem Save-ACK bleibt ein Dokumentwechsel beim spezifischen
  Dokumentwechsel-Fehler. Er wird nicht als unbestätigte Speicherung umgedeutet.
- Fehler vor der Mutation erhalten keinen Hinweis auf angeblich hinzugefügte
  Kopien. Token-, Checkpoint-, Entwurfs-, Herkunfts- und Dokumentguards bleiben
  erhalten.
- Die drei neuen Meldungen sind auf Deutsch angebunden. Die native
  Fehlerklassifikation verwendet wie beim Erinnerungsimport den vollständigen
  übersetzbaren Meldungsschlüssel.

Es gibt keine Rücknahme, keine automatische Wiederholung und keine neue
Speicher-Erfolgsbehauptung. Die angehängten Kopien bleiben verfügbar, damit
ein erneutes Speichern und die bestehende Herkunftserkennung funktionieren.

## Geprüfte Quellen und Regressionen

| Anschluss | Produktpfad | Regression |
| --- | --- | --- |
| Kalender | `Projection/system-calendar-import.js`, `macOSBetaCommitCalendarImport` | `tests/system_calendar_import.mjs` |
| Apple Notes | `Projection/apple-notes-import.js`, `macOSBetaCommitAppleNotesImport` | `tests/apple_notes_import.mjs` |
| Kontakte | `Projection/system-contact-import.js`, `macOSBetaCommitContactImport` | `tests/system_contact_import.mjs` |

Alle Pfade in dieser Tabelle liegen unter `Magnolie-Organizer-macOS-Beta`.
Die native Klassifikation steht in `Sources/MacBeta/main.swift`; deutsche
Texte stehen in `Resources/native-extra-i18n.json`.

Prüfumgebung: Linux, Node **24.22.3**, JSDOM **26.1.0**. Verwendet wurden die
vorhandenen Projektionsrunner, die aus den tatsächlichen kanonischen Quellen
eine temporäre Mac-Oberfläche erzeugen und unveränderte Eingaben nachprüfen.
Systemdaten, Checkpoint- und Save-Antworten sind ausdrücklich synthetisch.

| Runner | Ergebnis |
| --- | --- |
| `check_system_calendar_import.py` | **327 Prüfungen bestanden** |
| `check_apple_notes_import.py` | **195 Prüfungen bestanden** |
| `check_system_contact_import.py` | **246 Prüfungen bestanden** |
| Summe | **768 Prüfungen bestanden**, drei Runner mit Exitcode 0 |

Die Ergänzung umfasst **52 neue Assertions**. Die bestehenden positiven
Importe, Save-NACKs, Entwurfs-/Settings-/Token- und Herkunftsfälle bleiben in
denselben Runnern enthalten. Neue Fälle prüfen für jeden Anschluss Englisch
und Deutsch, Erhalt der Kopie und vorhandener lokaler Datensätze, Herkunft,
die tatsächlich gesendeten Retry-Savebytes sowie Wiederöffnen dieser Bytes
ohne doppelte Kopie. Zusätzlich werden Vor-Mutation-Fehler und ein bereits
beobachtetes Save-ACK von unbestätigter Speicherung unterschieden.

Wiederholung aus dem Repository-Stamm mit installierter vorhandener
Desktop-JSDOM-Abhängigkeit:

```sh
python Magnolie-Organizer-macOS-Beta/tools/check_system_calendar_import.py --js-runtime node
python Magnolie-Organizer-macOS-Beta/tools/check_apple_notes_import.py --js-runtime node
python Magnolie-Organizer-macOS-Beta/tools/check_system_contact_import.py --js-runtime node
git diff --check
```

Liegt JSDOM außerhalb des Repositorys, kann der bestehende Runner über
`MACOS_BETA_JSDOM` auf dessen `jsdom/lib/api.js` zeigen. Kein Test oder
Produktguard wird dafür abgeschwächt.

## Noch offen und andere Plattformen

Swift-/AppKit-/WKWebView-Kompilierung und echte Speicher-/Wiederöffnungsabnahme
auf Intel- und Apple-Silicon-Macs wurden hier nicht ausgeführt. Insbesondere
die native Alertdarstellung, Systemkonten, Rechte und tatsächliche Datenträger-
Dauerhaftigkeit benötigen weiterhin den bestehenden nativen Abnahmeweg.
Die deutschen UI-Tests sind kein vollständiger Sprachkatalognachweis.

Die drei Transaktionen liegen ausschließlich in der Mac-Projektion.
Linux/Windows verwenden andere native Importwege. Der gemeinsame Renderer
kann zwar grundsätzlich werfen, daraus folgt aber weder derselbe Ablauf noch
ein bereits nachgewiesener Plattformfehler. Dieser Patch verändert keine
gemeinsame Linux-/Windows-Produktdatei. Die getrennten Austauschfragen #776
und #779 bleiben eigene Aufgaben.

