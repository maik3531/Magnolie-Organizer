# Magnolie-Gesamtarchiv Fassung 1

Dateiendung: `.magnolie`. Maximale Dateigröße: 384 MiB.

Der unverschlüsselte Inhalt ist ein UTF-8-JSON-Objekt mit diesen Pflichtfeldern:

- `magnolie`: exakt `magnolie-gesamtarchiv`
- `fassung`: Ganzzahl `1`
- `datenschema`: Ganzzahl `1`
- `erstellt`: ISO-8601-Zeitpunkt
- `plattform`: `linux` oder `windows`
- `appversion`: erzeugende Anwendungsversion
- `sha256`: kleingeschriebener SHA-256-Hexwert des kanonischen `daten`-JSON
- `daten`: vollständiges normalisiertes Organizer-Datenobjekt einschließlich Data-URLs

Kanonisches JSON sortiert Objektschlüssel ordinal, verwendet keine Leerzeichen und maskiert
Nicht-ASCII-Zeichen mit JSON-`\u`-Sequenzen. Arrays behalten ihre Reihenfolge. Unbekannte
Zusatzfelder im Container und Datenbaum sind zulässig und bleiben erhalten. Unbekannte
`fassung`- oder `datenschema`-Werte werden abgewiesen.

Optional wird der gesamte kanonische Container mit der bestehenden
`magnolie-verschluesselt`-Hülle (AES-256-GCM, PBKDF2-HMAC-SHA256) geschützt. Ein leeres
Archivkennwort bedeutet ausdrücklich unverschlüsselt. ZIP-Passwörter werden nicht verwendet.

Importe prüfen Dateityp, Größe, JSON-Wurzel, Pflichtformat und SHA-256 vor jeder Mutation.
Symlinks beziehungsweise Reparse Points werden nicht gelesen. Beim Plattformwechsel bleiben
lokale Tray-/Autostartwerte, Sicherungsordner und Sync-Quellen erhalten. Graph- und andere
externe Integrationstokens sind im Datencontainer verboten.
