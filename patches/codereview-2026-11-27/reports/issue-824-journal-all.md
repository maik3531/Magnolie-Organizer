# Issue #824 — Vollständige Journal-Wiederherstellung verständlich anzeigen

## Ausgangspunkt und Fehlernachweis

Review auf `63ca6c8f351dd52627dfc550ff0075e703957ab5` vom 27. November 2026.
Die beiden tatsächlichen Desktop-Oberflächen wurden in jsdom geladen; die native
Brücke wurde ausschließlich als Aufzeichnungsfixture ersetzt.

Vor dem Patch zeigt die Auswahl **Alles** weiterhin das ergänzende Verfahren
„neuere vorhandene Daten bleiben erhalten“ an. Das Verfahren bleibt veränderbar.
Nach Bestätigung sendet die Oberfläche `bereiche: ["all"]` mit `modus: "additive"`.
Linux und Windows behandeln die vollständige Auswahl jedoch bereits als exakte
Wiederherstellung; spätere Änderungen und Einträge werden zurückgesetzt. Die
bisherige Rückfrage erklärt diesen Unterschied nicht ausdrücklich.

Der ergänzte Regressionstest schlägt auf der Ausgangsversion mit
`All must display its actual destructive restore method` fehl (`additive` statt
`replace`). Die vorhandenen Issues #21 (Mehrfachauswahl/Löschen), #142
(Zusammenfassung von Änderungsständen), #173 (Ergebnisanzeige nach Restore) und
#680 (native Zeitzonenabnahme) behandeln andere Fehler und ersetzen diese Prüfung
nicht. Die alten Mehrfachauswahl-/Löschprüfungen bleiben erhalten.

## Änderung

- **Alles** zeigt das tatsächlich verwendete ersetzende Verfahren und sperrt die
  Verfahrensauswahl sowie die in diesem Modus bedeutungslosen Einzelbereiche.
- Nach Abwahl von **Alles** sind das zuvor gewählte Teilverfahren und die
  vorherigen Einzelbereiche wieder verfügbar.
- Die vollständige Rückfrage enthält zusätzlich den vorhandenen, in allen
  Anwendungskatalogen übersetzten Hinweis, dass später hinzugefügte Daten
  entfernt werden. Der gesendete Modus entspricht der bestätigten Auswahl.
- Das Handbuch erklärt diesen Unterschied in Englisch und allen 19 übersetzten
  Sprachen als hervorgehobenen Hinweis im bestehenden Wiederherstellungskapitel.

Die nativen Wiederherstellungsalgorithmen und das Dateiformat werden nicht
geändert. Es entstehen keine neuen gettext-Schlüssel in den Anwendungen.

## Nachprüfung

Mit Node.js, jsdom 26.1.0, GNU gettext 0.23.1 und generierten Laufzeitkatalogen:

| Prüfung | Ergebnis |
| --- | --- |
| `node magnolie-organizer-windows/tests/journal-selection.js` | 12 Durchläufe erfolgreich: Linux und Windows, jeweils en/de/fr/pl/hsb/ar; beide Teilverfahren, Rückkehr zur Einzelauswahl, Abbruch/Bestätigung, tatsächlicher Brückenauftrag und vorhandene Löschregressionen |
| `node magnolie-handbuch/pruefungen/editorial_test.js` | Alle 20 Sprachen unter beiden Plattformvarianten; Warnung im tatsächlich zusammengesetzten Kapitel, lokalisiert und als Hinweis markiert |
| Handbuchkataloge nach kanonischem MO-/JS-Aufbau | Alle 19 PO-Dateien vollständig gegenüber dem gespeicherten POT, keine leeren/fuzzy Einträge, MO-/JS-Inhalte gleich und `msgfmt --check --check-format` erfolgreich |
| Aktuelle Android-Tablet-Webprojektion + `tests/web.test.cjs` | 194 Prüfungen erfolgreich; weitere gemeinsame Kalender-/Zeichen-/Identitäts-/Formularprüfungen erfolgreich |
| macOS `tools/check_current_sources.py --js-runtime node` | 27 Vertragsprüfungen plus 30 gemeinsame Datumssuchprüfungen erfolgreich, frische Projektion der geänderten kanonischen Oberfläche |
| `git diff --check` | Erfolgreich |

Die Projektionen wurden mit den vorgesehenen Generatoren frisch erzeugt. Für
den Tablet-Vertrag wurde der im Test fest vorgegebene historische Git-Commit
`067c38934b539943d8e1720abafd8a80b401d797` nachgeladen. Der macOS-Test verwendet
das unveränderte gepinnte phonenumbers-Wheel. Generierte Dateien bleiben
unversionierte Build-Ausgaben.

## Grenzen und separater bestehender Befund

jsdom prüft DOM-Verhalten und Texte, keine nativen GTK-, WebView2-, WKWebView-
oder Android-Pixel. Native Geräte-/Bildschirmleserabnahme ist hier nicht belegt.
Die macOS- und Tablet-Nachweise prüfen Projektion und vorhandene
Funktionsgrenzen; sie behaupten keine native Wiederherstellungsfunktion.

Bereits die unveränderte Ausgangsversion hat einen unabhängigen Drift zwischen
Handbuchquellen und gespeichertem POT: neun aktuelle Schlüssel fehlen, drei
veraltete bleiben enthalten. Der Python-Katalogtest scheitert deshalb auf der
Ausgangsversion in zwei bestehenden Prüfungen. Dieser Patch ergänzt gezielt
seinen eigenen Hinweis in Quellen/POT/Markern und allen PO-Dateien. Er erklärt
die bestehende Gesamtkatalogprüfung nicht als bestanden und behebt keine
fremden Kapitel im selben Issue.
