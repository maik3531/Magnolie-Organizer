# Unabhängige Gegenprüfung und Linux-Nachkorrekturen #835

Basis des Vergleichs: `1543858e251d7e29ebeafb67d2605991c1d442d5`.
Arbeitswurzel: `$REVIEW_SOURCE`.
Bearbeitet wurden ausschließlich `magnolie-organizer/bin/magnolie-organizer`
und `magnolie-organizer/pruefungen/test_absolute_reminder_legacy.py`.
Kein eigener Commit; beide Dateien wurden nach erfolgreicher Prüfung an die
Integration zurückgegeben.

## Bestätigte Befunde und Ergebnis

1. **Upgrade wiederholt quittierten absoluten VTODO-Alarm.** Ein echter Lauf
   des Basisimporters und Basisschedulers erzeugte eine alte Serieninstanzmarke.
   Nach JSON-Persistierung und Übergabe an den ersten #835-Entwurf erschien
   dieselbe Meldung nochmals unter der neuen Komponentenmarke. Der Linux-Fix
   rekonstruiert ausschließlich tatsächliche alte Instanzen anhand der
   Originalkomponente und des gespeicherten Meldezeitpunkts. Ein ähnlicher
   Präfix genügt nicht. Andere Quellen, andere Triggersekunden und der zweite
   DST-Fold werden nicht durch eine alte Minutenmarke quittiert.
2. **Gültiger undatierter VTODO bleibt stumm.** Absolute Trigger brauchen
   keinen DTSTART/DUE-Bezug. Der ursprüngliche Entwurf erreichte den absoluten
   Pfad erst nach erfolgreicher Fälligkeitsprüfung. Der Linux-Fix verwendet bei
   wirklich fehlender Fälligkeit ausschließlich für die Anzeige den
   Triggerzeitpunkt. Gespeicherte Daten bleiben unverändert. Fehlerhafte
   vorhandene Datums-/Zeitfelder werden nicht als fehlend behandelt. Windows
   wurde vom Integrationsverantwortlichen entsprechend korrigiert.
3. **Zeitgleicher normaler/relativer und absoluter Alarm erzeugt zwei
   Meldungen.** Bestätigt für VEVENT-Standard/relativ und VTODO-Fälligkeit/relativ.
   Die echte Basis erzeugte jeweils eine Meldung. Der Linux-Fix verbindet den
   absoluten Alarm mit einem vorhandenen normalen Alarm derselben
   Originalkomponente am exakt gleichen UTC-Zeitpunkt. Beide Identitäten
   werden gemeinsam quittiert. Eine bereits persistierte normale Quittierung
   gilt dabei auch für ihren zeitgleichen Partner. Nach Entfernen des
   absoluten Alarms feuert der normale Partner nicht erneut. Unabhängige reine
   relative Serienmeldungen bleiben erhalten.

Der undatierte VTODO-Fall wurde gegen die Primärquelle geprüft:
[RFC 5545 §3.6.2](https://www.rfc-editor.org/rfc/rfc5545.html#section-3.6.2)
erlaubt Aufgaben ohne DTSTART/DUE;
[§3.8.6.3](https://www.rfc-editor.org/rfc/rfc5545.html#section-3.8.6.3)
bindet absolute Trigger an ihren UTC-Zeitpunkt. Die Datumsbezüge sind für
relative Trigger erforderlich.

## Prüfung

- `review-independent-linux.json`: erste echte Upgrade-/Undated-Gegenbeispiele,
  erfolgreiche Kontrollen für Cancelled/Completed, Datenschutz und Serien.
- `review-independent-linux-after.json`: beide ursprünglichen Gegenbeispiele
  nach ihrer Korrektur erfüllt.
- `review-legacy-goldens.json`: sechs durch den echten Basiscode erzeugte
  Zustände, einschließlich Quellenbindung, Serie, Sekunden und beider Folds.
- `review-coincident-before.log`: drei neue Deduplizierungsgruppen vor dem Fix
  rot (zwei Meldungen statt einer), relativer Kontrollfall grün.
- `review-coincident-after.log`: 13/13 fokussierte Tests grün.
- `review-combined-after.log`: 61/61 grün, zusammengesetzt aus den 13 neuen
  Tests und 48 bestehenden Integrations-/Serienregressionen.
- `review-coincident-baseline-after.json`: vier vollständige echte
  Basisvergleiche. Basis jeweils eine Meldung/eine Quittierung, Korrektur
  jeweils eine Meldung/zwei Quittierungen.
- `review-independent-windows-final.log`: externe Probe gegen den vom
  Integrationsverantwortlichen gebauten Core. Gültig undatiert 1/1
  original/background; fehlerhafte vorhandene Felder 0/0; zeitgleiche
  Aufgabenalarme eine Meldung; echte AtomicStore-Persistierung und neu
  konstruierter Scheduler eine Erstmeldung und null Wiederholungen.
- `git diff --check`: ohne Befund.

Die vorhandenen plattformspezifischen Nachholregeln wurden wie angewiesen
beibehalten: Linux-Aufgaben verwenden ihr bestehendes 14-Stunden-Fenster,
Windows das vorhandene 5-Minuten-Verhalten. Die Abweichung ist im
6-Minuten-Nachholprobe separat dokumentiert und wurde nicht als neue globale
Alarmvereinheitlichung ausgegeben.

## Übergabestand

- Python-Produktdatei SHA256:
  `ebf571085314e3989b74236c66297413e27c358182117aa3349dc89c1c5f49e3`
- Neue Testdatei SHA256:
  `457a0282110b39e4fb96ff11380d14badab93cfeb1f457fe0b15c0303cd14908`

Die Prüfung betrifft die realen Importer, Scheduler und lokalen Zustandsdateien
mit eigenen synthetischen Datensätzen. Es wurden keine nativen
Benachrichtigungsfenster oder installierten Windows-/Linux-Pakete abgenommen.
