# Mac-/Android-Integrationsnachprüfung – 26. November 2026

Die neuen Git-Vergleiche sind **konfliktfrei**. Es wurde kein Arbeitszweig,
`main`, Issue oder Release verändert. Dieser Beleg prüft Übernehmbarkeit und
Dateiüberschneidungen; er bestätigt keinen nativen Testlauf oder Release.

## Exakte Remote-Anker

Die erste Reflesung lief von **2026-11-26 13:37:40,844979 Uhr Europe/Berlin** bis
**13:37:47,598496 Uhr Europe/Berlin**. Sie band Mac `8c860a14f7e10904c1b3a159ae84619c2c24ba82`
und Android `92e2c645cf0a8075325874f335087412e7f79c79` an Main `d4da48a5…`.
Dieser abgeschlossene Snapshot bleibt in [integration-8c860a14.json](integration-8c860a14.json) erhalten.

Die abschließende Reflesung von **2026-11-26 13:46:13,366463 Uhr Europe/Berlin** bis
**13:46:19,602751 Uhr Europe/Berlin** erfasste die inzwischen veröffentlichten Folgecommits:

| Zweig | Tatsächlicher Remote-Commit |
| --- | --- |
| `main` | `d4da48a5eadd0bda22422b924bef4ee3b4324040` |
| `work/macos-issue-fixes-20261126` | `625233067cd49e204786deb5706e6bc08ef85c4e` |
| `work/android-tablet-20261126` | `7a7d90b04796cf338b98f0fdbb87e8da1c967043` |

[Neuer vollständiger Vergleich](integration-62523306.json) ·
[Reflesung](remote-refs-8c860a14-final.json).

## Main und Mac-Arbeitszweig

Main ist weiterhin die exakte Merge-Base und ein Vorfahr des Mac-Stands.
Für `8c860a14` waren es **0 nur auf Main / 20 nur auf Mac**; für `62523306`
sind es **0 / 21**. Die isolierte `git merge-tree --write-tree`-Berechnung
für den neueren Stand ergibt ohne Konflikte exakt seinen vorhandenen Tree:
`8e02071077d08f926aa17637a4d538f0957c74ee`. Eine Gesamtübernahme wäre an diesen Refs technisch
als Fast-forward möglich. Sie wurde nicht ausgeführt.

Der zusätzliche Commit `62523306` ändert den Apple-Metadatenprüfer, zwei
zugehörige Testdateien und `ARBEITSSTAND.md`. Die frühere Patch-/Bundle-
Wiederherstellung wurde nicht wiederholt; ihre eingefrorenen Belege bleiben
unverändert. Die tatsächliche native Bewertung von #806 und Lauf #102 ist
von dieser Git-Prüfung getrennt.

## Tatsächliche Überschneidungen mit Android

Beide Arbeitszweige haben dieselbe Main-Basis. Android liegt **16 Commits**
davor. Gegen diese Basis ändern Mac **348** und Android **247** Pfade.
Genau zwei Pfade sind auf beiden Seiten geändert:

| Gemeinsamer Pfad | Ergebnis der direkten Prüfung |
| --- | --- |
| `.github/workflows/ports-2.0.30.yml` | Automatisch konfliktfrei zusammenführbar. Der berechnete Mac-Job entspricht exakt dem Mac-Zweig, der Tablet-Job exakt dem Android-Zweig. |
| `ARBEITSSTAND.md` | Ebenfalls automatisch konfliktfrei zusammenführbar; beide Entwicklungsberichte werden kombiniert. |

Weitere gemeinsam geänderte Produktquellpfade liegen in diesen beiden
Diffs nicht vor. Die Android-Erweiterungen der globalen Workflow-Einstellungen
bleiben im berechneten Ergebnis erhalten. Insbesondere ergänzen sie
`tablet-build-only` und `tablet-system-records`; `all` und `macos` bleiben
vorhanden. Der berechnete gemeinsame Workflow wurde nicht ausgeführt.

Auch die vollständige isolierte Mergeberechnung Mac ↔ Android meldet
**keinen Textkonflikt**. Ihr ausschließlich in der Prüfablage erzeugter Tree
ist `611d737c8d4e142cc0272995f1579dadaa45a00b`. Es wurde daraus kein Commit und kein
integrierter Arbeitszweig erstellt.

## Konsequenz für die dokumentierte spätere Übernahme

Der vorhandene Plan `contracts/macos-stable-integration-2026-11-26.md` fordert
zu Recht einen frischen Refvergleich und den Erhalt der Änderungen beider
Port-Jobs. Eine vollständige alte Kopie der Workflow-Datei würde diese
getrennten Änderungen gefährden; die tatsächliche Git-Zusammenführung erhält
sie an den hier geprüften Refs.

Ein eigener Stable-/Release-Zweig, die nächste Versionsnummer und die endgültige
Übernahmemethode bleiben nicht festgelegt. Main ist die geprüfte gemeinsame
Basis. Neue Commits auf Main oder einem Arbeitszweig erfordern einen neuen
passenden Integrationsvergleich. Der hier berechnete gemeinsame Mac-/Android-
Stand wurde weder gebaut noch nativ ausgeführt und ist keine Freigabe für
Pakete, Konten, Geräte oder vollständige UI-Abläufe.

## Herkunft der dauerhaften Fassung

Die fünf übernommenen JSON-/Refbelege sind bytegleich mit den ursprünglichen
Captures übernommen. Die Lesefassung stellt die Erfassungszeiten in
Europe/Berlin dar; die JSON-Daten behalten ihre ursprünglichen UTC-Zeitstempel.
Ursprüngliche Lesefassung: SHA-256
`e1e2b18bd4b03e3e3e13c18d40a7a464029587075865eab657433000024c8f2e`.
Der spätere Testwurzelfix `f7957801` und die Ergebnisse seines nativen Folgelaufs
sind eigene Belege; diese Integrationsprüfung wird nicht nachträglich umbenannt.
