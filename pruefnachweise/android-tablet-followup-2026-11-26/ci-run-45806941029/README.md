# Vollständiger CI-Versuch und zusätzliche Korrektur zu #790

[Actions-Lauf 45806941029](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45806941029)
prüfte den veröffentlichten Head `e7d396ed39641338ce9a7b57929623bc1dbd2fe1`.
Job `139864580229`, `tablet-build-only-no-native-acceptance`, scheiterte am
26. November 2026 um 11:04:16 UTC vor dem Start von Gradle.

Checkout, 22 Provenienztests, Source-Capture, Vorbereitung und Readiness waren
erfolgreich. Der vollständige Gate führte 194 Web- und 46 Import-/Anhangschecks
erfolgreich aus. Der folgende gemeinsame Setuptest erwartete die generierte
Datei `magnolie-organizer/web/normative-timezones.js`, die im frischen Checkout
fehlte. Die beiden echten Desktop-Appskripte bleiben gültige Testziele.

Die unveränderte Joblogpassage und der Run-Receipt sind gesichert. Das
Diagnostikartefakt `15109927624` wurde heruntergeladen und sein ZIP-SHA256
`082a179a46828cf43eb4c969be85edc65d9c6200b69066381eef3170f568b05e`
bestätigt. Es enthält drei JSON-Dateien, kein APK. `artifact-build-outcome.json`
enthält die ausgewählten Ereignisse und Grenzen aus dem tatsächlichen Receipt;
die ursprünglichen Joblogzeilen bleiben separat unverändert.

## Gezielter Quellfix

Nur `magnolie-organizer-windows/tests/setup-holidays.js` ändert ausführbaren
Prüfcode: Der vorhandene gemeinsame `projection-assets.cjs`-Generator erzeugt
den normativen Bootstrap aus den aktuellen eingecheckten Daten im Speicher.
Der vollständige Setupablauf beider echten Desktop-Appskripte bleibt erhalten.
Es werden keine Desktopcaches gelesen oder geschrieben und keine Tests,
Ressourcengrenzen, Sperren oder Abbruchbedingungen entfernt.

- Vorher: gleicher ENOENT mit Exit 1 lokal reproduziert.
- Nachher: 88 Cross-Desktop-Fälle in 20 Sprachen bestanden, Exit 0.
- Virtuell vorhandene veraltete Caches: kein Lesezugriff; 88/20 bestanden.
- Beschädigte normative TZDB per isolierter Leseinjektion: harter Generatorfehler,
  Exit 1; kein Fallback auf einen Cache.
- Beide generierten Desktopcache-Dateien bleiben tatsächlich nicht vorhanden.

Die originalen Probe-/Testprotokolle und der Quellhash stehen im Receipt in
diesem Ordner. Für den normalen Test aus dem Repositorywurzelverzeichnis:

```sh
NODE_PATH=/path/to/node_modules node magnolie-organizer-windows/tests/setup-holidays.js
```

Der bestehende Test verlangt seinen temporären Prüf-Elternordner `/tmp/opencode`;
der CI-Workflow bereitet diesen bereits vor. Der Bootstrapfix benötigt keine
zusätzliche Paketinstallation oder Quellgenerierung.

`projection-comparison.json` belegt, dass ausschließlich der geänderte Setuptest
als Projektionsquelle betroffen ist. Alle 83 erzeugten Laufzeitdateien bleiben
bytegleich. Der neue Projektionshash lautet
`3dcf2073c46012e193900fce971a5bab91cefd5194f433bac7169e7f98917907`.
Die bisherige UI-Abnahme bleibt auf genau diese identischen Laufzeitbytes
begrenzt; sie wird nicht als APK- oder Android-Lauf umgedeutet.

Ein weiterer vollständiger Actions-Lauf muss den korrigierten Quellstand
einschließlich Gradle und APK-Verifikation prüfen. Dieser Beleg dokumentiert
den fehlgeschlagenen ersten Versuch und den lokal geprüften Fix.
