# Issue #827 — Handbuchquellen und gettext-Kataloge synchronisieren

## Reproduktion

Die unveränderte Ausgangsversion `63ca6c8f351dd52627dfc550ff0075e703957ab5`
enthält neun aktuelle Handbuchtexte nicht im gespeicherten POT. Drei ältere
Fassungen ersetzter Texte bleiben im POT und allen PO-Dateien stehen. Die
kanonische Extraktion und die archivierten Übersetzungsquellen widersprechen
sich dadurch. Der vorhandene Python-Katalogtest meldet auf dieser Version
**2 fehlgeschlagene, 7 erfolgreiche Prüfungen**:

- `test_effective_sources_are_in_template`
- `test_temporary_pot_does_not_rewrite_source_markers`

Die neun Texte sind bereits vollständig in den direkten Sprachabbildungen
von `inhalt.js` enthalten. Deshalb ist dieser Befund eine fehlerhafte
Katalog-/Quellenpflege; er beweist keinen englischen Text in diesen angezeigten
Kapiteln. Die vorhandenen Laufzeitübersetzungen werden hier übernommen.

## Gezielte Korrektur

Die kanonischen Marker und das POT werden aus den aktuellen Quellen erzeugt.
In jeder der 19 PO-Dateien werden genau neun Schlüssel ergänzt und genau die
drei nicht mehr verwendeten Vorgänger entfernt. Die 171 ergänzten Übersetzungen
stammen unverändert aus den vorhandenen Sprachabbildungen. Alle weiterhin
vorhandenen `msgstr`-Werte wurden vor/nach der Änderung verglichen und sind
identisch. Andere PO-Blöcke werden nicht neu formatiert.

| Aktueller Inhalt | Handbuchseite |
| --- | --- |
| Downloadkarten einschließlich QR-Bildern | `android-apk-transfer` |
| Auswahl der Zieladresse | `maps-routes-and-messages` |
| Aktuelle Kopplung und Bestätigung am Gegenüber | `phone-pairing` |
| Vollständige Kontaktgruppen-Anleitung | `contact-details-and-anniversaries` |
| Mehrere Bildschirmabschnitte pro Seitennummer | `welcome` |
| Kalendernavigation mit Pfeiltasten | `turning-pages-and-moving-around`, wiederverwendet in `keyboard-shortcuts-at-a-glance` |
| AppImage-Katalogverweis | `the-appimage` |
| F-Droid-Verweis für Notes | `first-run-assistant` |
| Aktueller OR6-/CSV-Importumfang | `moving-from-lotus-organizer` |

Die entfernten Schlüssel sind die alten Fassungen für Kopplung, Kontaktgruppen
und OR6-Import. Der sichtbare Umfang des Diffs entsteht vor allem durch die
vollständigen HTML-Schlüssel und eingebetteten Download-QR-Bilder.

Diese Nachprüfung enthält bereits den separaten Warnhinweis aus #824 und die
separate Notes-Importanleitung aus #821/#92. Der Commit ändert ihre Inhalte nicht.

## Ergebnis

Nach `python3 magnolie-handbuch/werkzeuge/kataloge_bauen.py`:

- `python3 -m pytest -q magnolie-handbuch/pruefungen/katalog_test.py`:
  **9 erfolgreich**. Dazu gehören temporäre deterministische Extraktion,
  unveränderte Marker beim Lesen und installierter abweichender Präfix.
- `python3 magnolie-handbuch/pruefungen/katalog_audit.py`:
  **463 POT-Schlüssel, keine fehlenden Quellen**; alle 19 Kataloge ohne fehlende,
  zusätzliche, leere oder fuzzy Einträge; native MO- und Web-JS-Inhalte stimmen
  überein; `msgfmt --check --check-format` erfolgreich.
- `node magnolie-handbuch/pruefungen/editorial_test.js`:
  **20 Sprachen unter beiden Plattformvarianten erfolgreich**, einschließlich
  der tatsächlichen Zusammensetzung des Wiederherstellungskapitels.
- `git diff --check`: erfolgreich.

Umgebung: Python 3.12, Node.js, jsdom 26.1.0 und GNU gettext 0.23.1.
Die generierten MO-/JS-Kataloge bleiben Build-Ausgaben. Die Prüfung belegt keine
native Druckausgabe oder Bildschirmgeometrie auf GTK/WebView2/WKWebView.
