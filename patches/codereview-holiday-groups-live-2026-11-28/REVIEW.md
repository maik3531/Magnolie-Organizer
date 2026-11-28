# Unabhängige Gegenprüfung der Anbieterpatches #854/#857

Stand: 28. November 2026.

**Ergebnis: Der geprüfte Anbieterumfang ist zur Patchübergabe freigegeben.**
In den abschließend gelesenen Quellen und im zusammengesetzten Lieferartefakt
bleibt kein von dieser Gegenprüfung festgestellter Blocker offen. Die Freigabe
bezieht sich auf die hier gebundenen Patchbytes. Produktmerge, Freischaltung der
Gruppenauswahl und native Paketabnahme benötigen die unten genannten weiteren
Integrationsnachweise.

## Umfang und Belegbindung

Die Gegenprüfung hat die ursprünglichen #855/#856-Artefakte, die bereits
veröffentlichten Linux-/Swift-/Kotlin-Gruppenpatches und die endgültigen
Windows-/Linux-/Swift-/Kotlin-Kandidaten gelesen. Zusätzlich wurden die
offiziellen API- und Datenquellen zu Gruppen und Verwaltungseinheiten
unabhängig ausgewertet; die Primärquellen und ihre festgeschriebenen Commits
stehen im [Anbietervertrag](PROVIDER-CONTRACT.md).

Die abschließenden Ergebnisprotokolle wurden geprüft. Die fachlichen Tests
wurden in dieser Gegenprüfung nicht nochmals ausgeführt. Ein unabhängiger
mechanischer Abgleich der Lieferdateien ergab **98 Prüfvergleiche ohne
Abweichung**. Der vollständige Nachweis steht in
[REVIEW-BINDINGS.json](REVIEW-BINDINGS.json). Er umfasst:

- Bytezahl, SHA-256 und Git-Blob-ID aller 27 im Gesamtpatch geänderten oder
  neu angelegten Dateien sowie der fünf vorhandenen Voraussetzungssourcen;
- 32 Bindungen der aufgezeichneten Windows-/Cross-Läufe an die Produktquellen,
  Prüffälle und Antwortfixtures im gemeinsamen Manifest;
- die unveränderte tatsächliche Windows-Ersteinrichtungsnormalisierung und
  den Hash der für den C#-Host extrahierten Produktmethoden;
- sämtliche 27 Vorher-/Nachher-Blobpaare und die vollständige Pfadmenge im
  Gesamtpatch sowie dessen Bytezahl und Hash;
- die unveränderte Übernahme der Cross-Laufzusammenfassung und der Windows-
  Quellbindungen in das Lieferartefakt.

Die Summen zählen mechanische Vergleiche mit teilweise überlappenden Dateien,
keine zusätzlichen fachlichen Testfälle.

## Zusammengesetzter Patch

| Merkmal | Geprüfter Wert |
| --- | --- |
| Datei | `be-nl-providers-854-857-after-855-856.patch` |
| Größe | 326714 Bytes |
| SHA-256 | `bad577950aa8f78fd9d306b72440b5aa10176e15c5ce3f033302e54b28d44b75` |
| Geänderte oder neue Dateien | 27 |
| Basis von `main` | `1749c92eb42801c38eaba31b272d8c0e27be9164` |
| Voraussetzung | Diese Basis mit vollständigem #855/#856-Patch, vor einem früheren BE/NL-#854-Anbieterpatch |

Der Hauptlauf dokumentiert in [PATCH-CHECK.json](PATCH-CHECK.json) erfolgreiches
`git apply --check`, Vorwärtsanwendung und bytegenaue Rückwärtsanwendung auf
isolierten Bäumen aller beteiligten Quellen und neuen Dateien. Die hier
unabhängig verglichenen Patchbytes, Pfade und vollständigen Git-Blob-IDs stimmen
mit diesem Nachweis und mit [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json) überein.
Die isolierten Bäume sind kein vollständiger Repository-Build.

## Fachliche Befunde und endgültige Behandlung

| Prüfpunkt | Ergebnis in den endgültigen Quellen |
| --- | --- |
| Tatsächliche NL-Antworten mit Gruppen und abgeleiteten Verwaltungseinheiten | Ausdrückliche gültige Gruppen bleiben erhalten; die bloße Verwaltungseinheitenliste verwirft sie nicht mehr. |
| Verwaltungs- und Gruppenidentität | Keine Gruppenzuordnung wird aus der angefragten Region erfunden. Kotlin leert vorhandene Verwaltungsscopewerte, bevor die belegten Gruppen übernommen werden. |
| Fremde, präfixlose oder beschädigte Zusatzscopes | Werden nicht als passende Geografie ausgegeben und bestätigen keine Ersetzung. Die im ersten Windows-Kandidaten gefundene Lücke ist korrigiert. |
| `regionalScope: Local` | Bleibt bei Landesabfragen gegebenenfalls auf die belegte Gemeinde beschränkt; wird nicht als vollständiger Gruppenzeitraum übernommen und erteilt keine Gruppen-Ersetzungsbefugnis. |
| Fehlender oder unbekannter `regionalScope` | Ein fehlendes Feld bleibt kompatibel zu bisherigen gültigen Gruppenantworten. Ein ausdrücklich vorhandener unbekannter oder falsch typisierter Wert verhindert vollständige Ersetzungsbefugnis; positive explizite Zeilen können erhalten bleiben. |
| Tag `Exception` | Wird nicht ohne Quelle in eine geografische Beschränkung umgedeutet. |
| Landesweite Zeile mit allen drei Gruppen und gültigen Zusatzscopes | Wird konsistent akzeptiert. Landesweit plus nur teilweise genannte Gruppen bleibt widersprüchlich. |
| Leere oder nur nationale Schulferienantwort | Belegt keine vorhandene Gruppenabdeckung. Eine Landesabfrage benötigt alle drei bekannten ausdrücklich belegten Gruppen. |
| Öffentliche Feiertage bei Schulgruppenwahl | Ein Abruf pro Jahr, kein Gruppenparameter, eigene leere Regionskennung in Zeilen und bestätigtem Abrufbereich. |
| Österreich / bestehende Verwaltungsregionen | Die #856-ISO-/Providerzuordnung und die bestehenden DE-/CH-Pfade bleiben erhalten. |

Die ursprüngliche Annahme, jede Kombination aus Gruppen und Verwaltungseinheiten
sei eine örtliche Einschränkung, war durch künstliche Beispiele verdeckt. Der
Anbieterimport erzeugt diese Kombination selbst. Die endgültigen Prüfungen
enthalten deshalb die tatsächlichen aufgezeichneten Länder- und Gruppenantworten
neben gezielten negativen Beispielen. Die Herkunftsmerkmale für direkte und
abgeleitete Verwaltungseinheiten werden von der API nicht ausgegeben; eine
lückenlose Rekonstruktion dieser verborgenen Information ist mit den Antworten
nicht möglich. Die Behandlung von `Local` ist eine ausdrücklich konservative
Ersetzungspolitik. Sie wird im Anbietervertrag von gesicherten API-Eigenschaften
getrennt.

## Gelesene abschließende Laufbelege

| Bereich | Vergleichsstand | Kandidat |
| --- | ---: | ---: |
| Windows, tatsächliche C#-Methoden und kompletter Parser | 2/90 | 90/90 |
| Windows, vorherige #855/#856-Prüfung | – | 43/43 |
| Linux, tatsächliche Python-Anbieterfunktionen | 68/90 | 90/90 |
| Swift, vollständiger Dienst im Host | 76/98 | 98/98 |
| Kotlin, vollständiger Dienst mit realem JSON-/Datumsparser im JVM-Host | 90/112 | 112/112 |

Die Windows-Vergleichsbasis enthält #855/#856 und noch keine BE/NL-Erweiterung.
Die drei anderen Vergleichsstände enthalten zusätzlich ihren früheren
plattformspezifischen #854-Gruppenpatch. Die roten Anforderungen werden deshalb
nicht als Anzahl unabhängiger Programmfehler zusammengezählt. Die einzelnen
Ergebnisse und Laufumgebungen sind in [TEST-SUMMARY.json](TEST-SUMMARY.json),
[Cross-Laufbelegen](cross-platform/TEST-SUMMARY.json) und
[Windows-Laufbelegen](windows/TEST-SUMMARY.json) gebunden.

## Endgültig geprüfte Produktquellen

| Quelle | SHA-256 |
| --- | --- |
| Windows `BridgeDispatcher.cs` | `573facaeb82dcffb36c7b61ff6c8ae65f5750f14ce0d8e7f18795c19617d6033` |
| Windows `OpenHolidayData.cs` | `41a0320a219ffbcab7cbaa8a2ad98149789bd7e58e15962b9a401a1f9374e254` |
| Linux `magnolie-organizer/bin/magnolie-organizer` | `9f230d1e38db027793756da21bb22eaf839671926758f66ddd6bdbba1185b32f` |
| Mac `HolidayService.swift` | `d777b964ff7b5e67e579c62c4883ec1de8d7c01137fc731c8efb935f11ee927a` |
| Tablet `HolidayService.kt` | `f2d3d7204ca0311ad1b7826a5ce57271fb8d3f4f858c8c8a1722bb8db9402dc9` |

## Grenzen und noch notwendige Integration

Die Anbieterantworten werden in den Funktionstests wiedergegeben; dadurch
entsteht kein weiterer Liveabruf. Die C#-, Swift- und JVM-Nachweise sind
Hostprüfungen. Native Windows-, macOS- und Android-Abnahme sowie installierbare
Pakete sind damit nicht nachgewiesen. Vollständige GUI-/MCP-/Cache-Integration
und die erweiterte Ersteinrichtung bleiben gesonderte Arbeiten. Insbesondere
muss die gemeinsame Oberfläche den landesweiten Feiertagsbereich unabhängig
von der ausgewählten Schulgruppe akzeptieren, bevor die Gruppenauswahl
freigeschaltet wird.

Die bereits übergebenen #855/#856-Artefakte werden hier als Voraussetzung
verwendet. Diese Gegenprüfung erfordert dafür keine erneute Veröffentlichung
und keinen doppelten Issue-Kommentar. Der Hauptlauf übernimmt die Publikation
und die anschließende Prüfung der entfernten Artefaktbytes.
