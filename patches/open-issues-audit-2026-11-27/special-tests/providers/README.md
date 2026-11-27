# Gezielte Provider-/Identitätsregressionen

Geprüfte unveränderte Basis: `3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f`.
Eigener Prüfcheckout: `/workspace/scratch/7203da5bd564/open-audit-provider-tests`.
`git status --short` war nach den Läufen leer. Keine Produktdatei und kein
bestehender Test wurde geändert; keine alten Alarm-Patches wurden eingespielt.

| Zuordnung | Tatsächlich ausgeführte bestehende Gruppe | Ergebnis | Grenze |
| --- | --- | --- | --- |
| #452/#453 | `ProviderCodecMigrationTest` mit aktuellen `ProviderZone`, `TimeZoneExport`, `CalendarIdentity`, `ICalendarImport`, `ICalendarExport` | 7/7 JUnit-Tests, 0 Fehler | JVM mit gepinnten Bibliotheken und normativem TZDB-Payload; kein Android-OS-Lauf |
| #464 | `port-adapters/tests/occurrence-identity.cjs` auf frisch projizierter Mac-UI | 29/29 Prüfungen | Tatsächliche App-/Normalizer-/Reopen-JavaScriptwege; Speicherbridge und ACK synthetisch, kein WKWebView/native Dateispeicher |
| #464 | Dieselbe bestehende Gruppe auf frisch projizierter Tablet-UI | 29/29 Prüfungen | Tatsächliche App-/Normalizer-/Reopen-JavaScriptwege; Speicherbridge und ACK synthetisch, kein Android-WebView/Vault-Gerätelauf |
| #465/#785 | `ImportHelperTests.test_legacy_android_sidecar_is_exact_and_transient` | 1/1 Test | Tatsächlicher aktueller isolierter CPythonhelper mit ICS-Fixture, keine Swift-/Dateidialogabnahme |

Die Kotlin-Gruppe prüft Gaza 2074 gegen 09:30 UTC, verwirft die alte widersprüchliche
Projektion, trennt Kalendertage von verstrichenen Stunden, schützt DATE beim
übersprungenen Apia-Mitternachtspunkt, erhält eingebettete VTIMEZONE-Definitionen,
frühere interne UTC-Namen, Alias-Schreibweisen und floating-Zeiten. Sie prüft auch
die unbegrenzten Exportregeln sämtlicher zugelassenen Zeitzonenkennungen.

Die Identitätsgruppen erhalten unterschiedliche ursprüngliche RID-/Quellen- und
Wire-UID-Identitäten bei gleichem sichtbaren Zeitpunkt, einschließlich
NFC/NFD-Unterschieden, unbekannten Feldern und Aufgabenverweisen. Tatsächliche
eindeutige Dubletten bleiben dedupliziert; mehrdeutige Identitäten werden nicht
geraten. Die bestehenden Invers-/Projektionsanker werden unverändert mitgeprüft.

## Reproduktion und Belege

`run_checks.py` enthält die genauen Befehle und Umgebungsvariablen. Er verwendet
ausschließlich die bereits vorhandenen Abhängigkeiten unter `round3-tools` und
den bestehenden hashgeprüften phonenumbers-Cache. Die regulären Projektoren
erzeugen die aktuelle UI neu; es wird keine alte generierte UI kopiert.

```sh
python run_checks.py /workspace/scratch/7203da5bd564/open-audit-provider-tests /workspace/scratch/7203da5bd564/round3-tools /workspace/scratch/7203da5bd564/open-audit/special-tests/providers jvm
python run_checks.py /workspace/scratch/7203da5bd564/open-audit-provider-tests /workspace/scratch/7203da5bd564/round3-tools /workspace/scratch/7203da5bd564/open-audit/special-tests/providers ui
python run_checks.py /workspace/scratch/7203da5bd564/open-audit-provider-tests /workspace/scratch/7203da5bd564/round3-tools /workspace/scratch/7203da5bd564/open-audit/special-tests/providers helper
```

`jvm-manifest.json`, `ui-manifest.json` und `helper-manifest.json` binden
Eingangsdateien, Abhängigkeiten, Befehle, Laufzeiten und Logs per SHA-256. Das
UI-Manifest erhält zusätzlich die vollständigen aktuellen Projektionsmanifeste.

Der erste private Runner-Versuch hatte zwei Einrichtungsfehler: fehlende
`CalendarIdentity.kt` in der von mir gewählten Kompilierliste und ein um eine
Verzeichnisebene falscher Mac-Webpfad. Die `attempt-1-*`-Logs und
`*-attempt-1-manifest.json` erhalten diese unverändert. Nach Ergänzung der
tatsächlichen Produktabhängigkeit und Verwendung des dokumentierten
`Generated/web`-Pfads bestanden die Wiederholungen. Es wurde kein Produktfehler
aus diesen beiden Runnerfehlern abgeleitet und keine Assertion abgeschwächt.

Die Ergebnisse schließen die weiterhin konkret benannten nativen
Picker-/Provider-/Speicher-/Neustartabnahmen nicht. Sie sind neue gezielte
Hostbelege auf der oben genannten aktuellen Basis.
