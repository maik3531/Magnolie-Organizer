# #854 / #857: BE/NL-Provider mit echten Anbieterantworten korrigiert

Der bislang fehlende Windows-Providerpatch ist vollständig vorbereitet. Eine
zusätzliche Live-Gegenprobe hat eine falsche Annahme in den bereits gelieferten
Linux-, Swift- und Kotlin-Teilpatches aufgedeckt. Auch diese drei Pfade sind
korrigiert. Die Lieferung enthält vollständige Quellpatches, ausführbare
Regressionen, unveränderte Anbieterantworten und die genauen Prüfgrenzen.

Fachissues: [#854 – internationale Erweiterung](https://github.com/maik3531/Magnolie-Organizer/issues/854)
und [#857 – niederländische Gruppen mit Verwaltungsangaben](https://github.com/maik3531/Magnolie-Organizer/issues/857).
Ursprüngliche Prüfbasis: `1749c92eb42801c38eaba31b272d8c0e27be9164` plus
#855/#856. Der aktualisierte Abgleich mit der zwischenzeitlichen Codex-Übernahme
steht im folgenden Abschnitt. Die Produktübernahme von #854/#857 und die
Freigabe installierbarer Pakete bleiben der späteren Codex-Prüfung vorbehalten. Diese Lieferung aktiviert noch keine neue Gruppenauswahl in der
Oberfläche.

## Aktualisierte Anwendungsbasis nach Codex-Übernahme – 28.11.2026

Codex hat [#855](https://github.com/maik3531/Magnolie-Organizer/issues/855#issuecomment-7239370495)
und [#856](https://github.com/maik3531/Magnolie-Organizer/issues/856#issuecomment-7239395916)
in Produkt-main übernommen und beide Issues geschlossen. Der abschließend gelesene
Stand ist `8b0b253b9593d139c3ceeadcc222a498a5da34f3`.

**Auf diesem Stand den vollständigen BE/NL-Patch direkt anwenden; #855/#856
nicht nochmals anwenden.** Alle fünf vorhandenen Produktblobs entsprechen genau
seinen Voraussetzungen, alle 22 neuen Pfade fehlen dort wie erwartet.
`git apply --check`, `git apply --check --index`, tatsächliche Anwendung mit
Index und Rücknahme sind auf den isoliert rekonstruierten, remote verifizierten
Quellen bestanden. [Vollständiger Nachweis](CURRENT-MAIN-CHECK.json).

Git meldet dabei eine Moduswarnung, weil der Patchheader das Linux-Programm als
`100644` nennt, main es aber bereits als `100755` führt. Die tatsächliche
Anwendung bewahrt `100755` in Dateisystem und Index; auch die Rücknahme stellt
Blob und Modus exakt wieder her. Hinzu kommen 37 Leerzeichenwarnungen, deren
Ausgaben im Nachweis stehen; sie sind kein Anwendungsabbruch. Die unveränderten
Quellpatchbytes und alle bisherigen Prüfsummen bleiben gültig. Funktions- oder
native Tests wurden für diesen reinen Basisabgleich nicht erneut ausgeführt.

Die Übernahme von **#854/#857**, die gemeinsame GUI/MCP/Cache-Integration und
native App-/Paketabnahme bleiben offen. Bei weiter verändertem main vor
Anwendung erneut den Quellstand und aktive Issue-Markierungen abgleichen.

## Was die reale Gegenprobe verändert hat

OpenHolidays liefert für niederländische Ferien sowohl `groups` als auch
`subdivisions`. Alle zehn aufgenommenen Landeszeilen für 2026 haben beide
Listen. Der offizielle Importer ergänzt Verwaltungsgebiete aus den Gruppen;
bei mehreren Gruppen kann die Liste nur aus der zuerst verarbeiteten Gruppe
stammen. Die bloße Anwesenheit von Gemeinden belegt deshalb keine Einschränkung
einer Feriengruppe.

Die vorherigen Linux-, Swift- und Kotlin-Patchvorschläge behandelten jede solche
Kombination als kommunale Ausnahme. Der erste Windows-Paritätskandidat
übernahm diese Regel und bestand damit 72 synthetische Prüfungen. Der Replay
echter Antworten widerlegte sie: Jede der drei niederländischen Gruppen
hatte sechs passende Perioden, von denen der Parser keine übernahm. Dieser
Kandidat wurde verworfen. Die frühere Testannahme wurde ausdrücklich korrigiert,
statt ihre grünen Ergebnisse als Beleg für die echte Anbieterintegration
weiterzuführen. [Anbieteranalyse mit gebundenen Primärquellen](PROVIDER-CONTRACT.md).

Der endgültige Quellstand verwendet ausdrücklich mitgelieferte gültige Gruppen
als Schulgruppenidentität. Zusätzliche gültige Verwaltungsangaben werden nicht
in diese Identität eingemischt. Fehlerhafte oder fremde Listen bleiben
abgewiesen. Explizit lokale Datensätze werden nicht auf eine ganze Gruppe
ausgeweitet. Vorhandene unbekannte oder falsch typisierte `regionalScope`-Werte
geben keine Ersetzungsbefugnis; ein fehlendes Feld bleibt mit älteren Antworten
kompatibel. Ein `Exception`-Tag wird nicht ohne geografischen Beleg als
Gemeindeeinschränkung interpretiert.

Öffentliche Feiertage werden bei einer Schulgruppenwahl einmal pro Jahr
landesweit abgerufen, mit getrenntem leerem Regionsscope. Schulferien verwenden
`groupCode`. Leere oder nur nationale Ferienantworten erfinden keine bestätigte
Gruppenabdeckung. Die landesweite Ferienabdeckung verlangt alle drei bekannten
expliziten Gruppen. Diese strukturelle Prüfung beweist keine vollständige
amtliche Kalenderdatenbank.

## Genau eine zur Ausgangslage passende Anwendung

| Ausgangslage | Passender Weg |
| --- | --- |
| Produktbasis mit #855/#856, aber ohne einen der BE/NL-#854-Providerpatches | [Vollständiger korrigierter Vierplattformpatch](be-nl-providers-854-857-after-855-856.patch) |
| Bereits alle drei veröffentlichten BE/NL-Teilpatches für Linux, Swift und Kotlin angewandt | [Windows-Teilpatch samt gemeinsamen Fixtures](windows/be-nl-windows-854-857-after-855-856.patch), dazu die drei kleinen #857-Folgepatches unten |
| Nur einzelne frühere Plattformpatches übernommen | Die vorhandenen Quellblobs mit den Manifesten vergleichen und nur den passenden Plattformweg übernehmen; den Gesamtpatch nicht zusätzlich über bereits enthaltene Teile legen |

Die Voraussetzung #855/#856 ist entweder der gemeinsame Patch aus
[Artefaktcommit a473d769](https://github.com/maik3531/Magnolie-Organizer/blob/a473d769d590cf2a2771f2e890727025230a0f80/patches/codereview-holiday-live-austria-2026-11-28/holiday-cache-855-plus-austria-856.patch)
oder der ursprüngliche #855-Patch gefolgt von #856. Deren Ergebnisbaum lautet
`e02b1150060a66d9289cfd910356b44029cb270b`.

Die drei Ergänzungen für bereits angewandte Plattformpatches sind:

- [Linux-Folgepatch #857 nach Linux-#854](be-nl-linux-857-after-854.patch).
- [Swift-Folgepatch #857 nach Swift-#854](be-nl-swift-857-after-854.patch).
- [Kotlin-Folgepatch #857 nach Kotlin-#854](be-nl-kotlin-857-after-854.patch).

Diese Ergänzungen setzen die jeweilige frühere BE/NL-Lieferung voraus:
Linux `d2226e21`, Swift `01fa2ba5`, Kotlin `740311cd`. Ihre Tests verwenden den
gemeinsamen Fixturebestand des Windows- oder des vollständigen Vierplattformpatches.
Die Bytes der Aufzeichnungen liegen zusätzlich im lesbaren Ordner
[fixtures](fixtures). **Gesamtpatch und Einzel-/Folgepatchweg sind Alternativen.**
Die vorherigen BE/NL-Patchvorschläge ohne #857 sind keine abschließend geprüfte
niederländische Gruppenlösung.

Gesamtpatch: **326.714 Bytes**, SHA-256
`bad577950aa8f78fd9d306b72440b5aa10176e15c5ce3f033302e54b28d44b75`.
Er umfasst fünf Produktdateien, sieben Prüfdateien sowie 15 gemeinsame
Fixture-/Herkunfts-/Lizenzdateien. Alle 27 geänderten oder neuen Dateien sind
im [Quellmanifest](SOURCE-MANIFEST.json) gebunden.

Die [unabhängige Schlussprüfung](REVIEW.md) bestätigt die Quell-/Testbindungen
und die Übergabereife; ihre 98 mechanischen Vergleiche sind gesondert in
[REVIEW-BINDINGS.json](REVIEW-BINDINGS.json) dokumentiert.

## Tatsächlich ausgeführte Prüfungen

| Bereich | Vergleichsstand | Endgültiger Quellstand |
| --- | ---: | ---: |
| Windows, neue Gruppen- und Datenformprüfungen | #855/#856: 2/90 | **90/90** |
| Linux, korrigierte Gruppenprüfung | veröffentlichter #854-Patch: 68/90 | **90/90** |
| Swift, vollständiger Feiertagsdienst | veröffentlichter #854-Patch: 76/98 | **98/98** |
| Kotlin, vollständiger Feiertagsdienst | veröffentlichter #854-Patch: 90/112 | **112/112** |
| Bisherige Windows-Cache-/Österreich-Prüfungen | vorhandene unveränderte Anforderungen | **43/43** |

Die unterschiedlichen Vergleichsstände sind absichtlich angegeben: Windows
besaß bisher noch keinen veröffentlichten BE/NL-Teilpatch, die anderen drei
Plattformen schon. Die Fallzahlen zählen Prüfanforderungen, keine unabhängigen
Fehler. [Zusammenfassung](TEST-SUMMARY.json),
[Windows-Teilbericht](windows/README.md),
[gebundene Plattformprotokolle](cross-platform/TEST-SUMMARY.json).

Windows wurde mit .NET SDK 10.0.404/Runtime 10.0.15 im isolierten Linux-Host
geprüft. Das Testziel war `net10.0`, der Produkttarget blieb unverändert.
Der Host kompiliert die tatsächlichen vollständigen betreffenden Bridge-Methoden,
den vollständigen Parser und den echten Setup-Normalisierer. HTTP, Form-Callback
und Gettext sind kontrolliert. Kein vollständiger WinForms-Bau.

Linux prüft die tatsächlichen vollständigen Abruf-/Parserfunktionen mit
Python 3.12.14 und kontrolliertem HTTP-/Setup-Kontext. Swift 6.4.3 kompiliert
den vollständigen tatsächlichen Feiertagsdienst mit echter Foundation-JSON-
und Datumsverarbeitung; HTTP und BetaError werden vom Testhost bereitgestellt.
Kotlin 2.4.21 kompiliert diesmal ebenfalls den **vollständigen tatsächlichen
Dienst**, einschließlich Query-Validierung, JSON-Decodierung, Datumsverarbeitung,
Aggregation und Modellen. Verwendet wurden die vorhandenen Produkt-Testversionen
`org.json` 20240303 und ThreeTenBP 1.7.5, JVM-Ziel 17 und Java 21.0.13.1.
HTTP und Abbruchumgebung sind kontrolliert. Damit ist die frühere Kotlin-Grenze
eines nur nachgebildeten JSON-Parsers für diesen neuen Prüflauf behoben.

## Echte Antworten und wiederholbare Proben

Zwölf echte HTTPS-Anfragen sind gespeichert: je Land Gruppenverzeichnis,
landesweite Schulferien und öffentliche Feiertage, außerdem alle sechs
gruppenspezifischen Schulferienabfragen. Alle antworteten im aufgezeichneten
Lauf mit HTTP 200. Die sechs Gruppenabfragen lieferten BE-DE vier, BE-FR und
BE-NL jeweils sechs sowie NL-NO/NL-MI/NL-ZU jeweils sechs Perioden. Die Tests
prüfen die tatsächlichen Periodengrenzen und Identitäten. Jahresübergreifende
Intervalle bleiben vollständig erhalten.

Die Hosttests spielen die **unveränderten** aufgezeichneten HTTP-Antwortbytes
erneut ein. Sie sind keine zusätzlichen Live-GUI-Läufe. Anfrage-URLs, Abrufzeiten,
Hashes und HTTP-Metadaten stehen in [fixtures/requests.json](fixtures/requests.json).
Die Datenlizenz und Attribution sind [separat enthalten](fixtures/ATTRIBUTION.md).

Nach Anwendung des passenden Quellpatchwegs kann der Windows-Prüfer wie in
[seinem Bericht](windows/README.md#repeat) ausgeführt werden. Für Linux genügt:

```sh
python3 magnolie-organizer/pruefungen/holiday_groups_854_probe.py . \
  contracts/fixtures/holiday-groups-2026-11-28
```

[run-host-probes.py](run-host-probes.py) wiederholt die drei anderen
Vorher-/Nachher-Läufe. Er erwartet `--before`, `--after`, `--fixtures`,
`--toolchain` und `--output`; die Quellen, Tests, Runtimeversionen und JAR-Hashes
stehen in der zugehörigen Zusammenfassung. Die verwendete Werkzeuganordnung
unter `--toolchain` ist `swift/swift-6.4.3-RELEASE-debian13/usr/bin/swiftc`,
`kotlin/kotlinc/bin/kotlinc` sowie die beiden genannten JAR-Dateien direkt im
Werkzeugordner. Die Skripte laden oder installieren nichts. Die öffentlichen
Originalquellen und die Prüfung der verwendeten Werkzeuge sind unter
[toolchain](toolchain) dokumentiert; Werkzeugbinaries gehören nicht zum Patch.

Der Gesamtpatch wurde unabhängig in einem isolierten Git-Baum mit allen
beteiligten exakten Ausgangsdateien vorwärts angewandt, bytegenau mit den
geprüften Kandidaten verglichen und rückwärts wiederhergestellt. Auch die
Einzel-/Folgepatches bestanden diesen Rundlauf. Das sind keine behaupteten
vollständigen Produktbäume: [Gesamtbeleg](PATCH-CHECK.json),
[Folgepatchbelege](FOLLOWUP-PATCHES.json).

## Verbleibender Umfang und sichere Fortsetzung

Der gemeinsame Desktop-GUI-/MCP-Importer muss bei ausgewählter Schulgruppe den
landesweiten **öffentlichen** Feiertagsscope ausdrücklich akzeptieren, während
Schulferien an die angeforderte Gruppe gebunden bleiben. Das bloße Hinzufügen
der sechs Auswahlcodes würde diesen Vertrag nicht erfüllen. Die direkte
landesweite Auswahl soll ebenfalls erhalten bleiben. Diese Integration,
Ersteinrichtung, Handbuch und Übersetzungen bleiben der nächste Umfang in #854.

Vollständige native Linux-/Windows-/Mac-/Android-Oberflächen, installierte
Pakete, reale Geräte sowie amtliche Kalender-Vollständigkeit sind nicht
abgenommen. Ein erfolgreicher JSON-Abruf oder Hosttest beweist diese Schritte
nicht. Der separate #128-Abgleich ist weiterhin eine andere aktive Arbeit.

Vor einem Folgepatch frische Issue-Kommentare, Codex-Bearbeitungsmarkierungen,
verknüpfte Änderungen und den aktuellen Quellstand lesen. Den eigenen engen
Umfang als in Arbeit markieren und nach Abschluss mit Patch, Nachweis und
offenem Rest übergeben. Das stündliche Code-Monitoring wurde auf ausdrücklichen
Nutzerwunsch um diese Koordination ergänzt; keine bereits aktiv bearbeitete
Teilaufgabe parallel identisch implementieren.
