# Magnolie-Gesamtarchiv Fassung 1

Dateiendung: `.magnolie`. Maximale Dateigröße: 384 MiB.

Der unverschlüsselte Inhalt ist ein UTF-8-JSON-Objekt mit diesen Pflichtfeldern:

- `magnolie`: exakt `magnolie-gesamtarchiv`
- `fassung`: Ganzzahl `1`
- `datenschema`: Ganzzahl `3` bei neu geschriebenen Archiven; Leser akzeptieren `1`, `2` und `3`
- `erstellt`: ISO-8601-Zeitpunkt
- `plattform`: `linux` oder `windows`
- `appversion`: erzeugende Anwendungsversion
- `sha256`: kleingeschriebener SHA-256-Hexwert des kanonischen `daten`-JSON
- `daten`: vollständiges normalisiertes Organizer-Datenobjekt einschließlich Data-URLs

Kanonisches JSON sortiert Objektschlüssel ordinal, verwendet keine Leerzeichen und maskiert
Nicht-ASCII-Zeichen mit JSON-`\u`-Sequenzen. Arrays behalten ihre Reihenfolge. Unbekannte
Zusatzfelder im Container und Datenbaum sind zulässig und bleiben erhalten. Unbekannte
`fassung`-Werte sowie andere `datenschema`-Werte als `1`, `2` und `3` werden abgewiesen.

Datenschema 2 legt für Geburtstage und Jahrestage die Maschinenform fest: Ein bekanntes
Datum ist `YYYY-MM-DD`, ein unbekanntes Jahr wird ohne Ersatzjahr als `--MM-DD` gespeichert.
Beide Formen müssen kalendarisch gültig sein; insbesondere ist `--02-29` zulässig.
Datenschema 1 bleibt lesbar.

Datenschema 3 normalisiert den Datenbaum auf internes Datenmodell mindestens `7`.
Aufgaben erhalten eine stabile `uid`, einen Elternbezug `elternUid` und eine
nullbasierte `reihenfolge` innerhalb derselben Elterngruppe. Fehlende oder doppelte
Kennungen werden deterministisch ersetzt, ungültige Elternbezüge entfernt, Zyklen
deterministisch aufgelöst und Geschwisterreihenfolgen lückenlos normalisiert. Die
Termin-Wiederholungsart `monthly_weekday` wird als `monthly` kanonisiert. Schemata 1
und 2 bleiben lesbar und werden beim Einlesen in dieselbe normalisierte Maschinenform
überführt.

Das Gesamtarchiv-Datenschema ist nicht die Personal-Sync-Protokollfassung. Personal
Sync handelt die Fassungen `1`, `2` oder `3` aus; Fassung 3 ergänzt für Aufgaben
`uid`, `parent_uid` und `order`. Diese Protokollfelder werden bei der Übernahme auf
die entsprechenden Aufgabenfelder des Datenmodells abgebildet.

Optional wird der gesamte kanonische Container mit der bestehenden
`magnolie-verschluesselt`-Hülle (AES-256-GCM, PBKDF2-HMAC-SHA256) geschützt. Ein leeres
Archivkennwort bedeutet ausdrücklich unverschlüsselt. ZIP-Passwörter werden nicht verwendet.

Importe prüfen Dateityp, Größe, JSON-Wurzel, Pflichtformat und danach SHA-256 vor jeder Mutation.
Symlinks beziehungsweise Reparse Points werden nicht gelesen. Beim Plattformwechsel bleiben
lokale Tray-/Autostartwerte, Sicherungsordner und Sync-Quellen erhalten. Graph- und andere
externe Integrationstokens sind im Datencontainer verboten.
