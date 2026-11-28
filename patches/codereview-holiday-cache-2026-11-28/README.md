# #855 – Feiertags- und Feriencache gezielt erneuern

**Vollständiger Einzelpatch zur späteren Prüfung/Übernahme mit Codex:**
[holiday-cache-855.patch](holiday-cache-855.patch). Fachissue:
https://github.com/maik3531/Magnolie-Organizer/issues/855 .

Der Hauptzweig wurde durch diesen Review nicht geändert; der Patch enthält
Produktquellen, Regressionstests, Vertragsdokumentation und Arbeitsstand.
Mac-Quellen und fünf Swift-Testmethoden sind enthalten, hier jedoch ausdrücklich
nicht kompiliert. Vor Übernahme dieses Plattformteils ist die Swift-Prüfung offen.

## Verbindliche Quellbindung

- Basis: `1749c92eb42801c38eaba31b272d8c0e27be9164`
- Basisbaum: `dac30a55fccc3c71cc9085c9c9d89445aa603580`
- Ergebnisbaum nach vollständigem Patch: `f4f94a2c2cf73a064448d3208f31d471e150dbe4`
- Patch: 129,502 Bytes; SHA-256 `c1cecd73eda51d3726962039bbb5b9e3bef8d34dede05897a64908acbb2f588c`
- 18 beabsichtigte Quell-/Test-/Dokumentationsdateien; Einzelbindungen:
  [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json).
- Git-Anwendung in einem separaten Index vorwärts geprüft und ausgeführt;
  der Ergebnisbaum stimmt exakt. Rückwärtsprüfung und Rücknahme ergeben
  exakt den Basisbaum: [PATCH-CHECK.json](PATCH-CHECK.json).

Frischen `main` und die Fachissues vor Übernahme vergleichen. Ältere Gesamtpakete
nicht erneut anwenden. Dieses Paket enthält ausschließlich #855; #850/#851/#852
haben eigene frühere Patches, #853/#854 ihre eigenen Erweiterungsaufträge.

## Reproduzierter Fehler

`wendeFeiertageDatenAn` entfernte aus `DATEN.feiertage` vor dem Einfügen sämtliche
Perioden, die eines der Antwortjahre berührten. Herkunftsland, angefragte Region,
Ferien-Opt-out und tatsächlich erfolgreicher Abruf spielten dabei keine Rolle.
Ein Sachsen-Abruf konnte dadurch österreichische Feiertage, bayerische Ferien
und Schweizer Ferien über den Jahreswechsel löschen. Auch bereits gespeicherte
Ferien verschwanden, wenn anschließend nur öffentliche Feiertage geladen wurden.

Beide vollständigen Desktopskripte mit HTML, i18n, normativen Zeitzonenassets und
ihren tatsächlichen UI-Anfrage-/Antwortwegen reproduzieren diese Fehler. Es ist
kein nachgebauter Cachealgorithmus. Der Host verwendet JSDOM und eine kontrollierte
native Brücke; daraus folgt keine native WebView-/GTK-/WinForms-Abnahme.

## Was der Patch ändert

Linux, Windows, Tablet und Mac liefern das additive Antwortfeld `abrufbereiche`.
Ein Datensatz darin bestätigt ausschließlich eine vollständig und gültig
ausgewertete Endpoint-/Jahr-/Regionsabfrage. Ein gültiges leeres Array kann somit
einen leeren Kalenderbereich bestätigen. Ausgelassene Schulferien, abgefangene
HTTP-Teilfehler, beschädigte Formen/Zeilen, fehlende Pflichtfelder oder nicht zur
Anfrage passende Zeilen liefern keine entsprechende Ersetzungsbefugnis. Bisher
tolerierte gültige Zeilen bleiben lesbar. Das Feld wird nicht im Buch gespeichert;
eine Migration oder zusätzliche Berechtigung ist nicht erforderlich.

Der gemeinsame Import bindet die bestätigten Bereiche an den Anfrage-Snapshot:
Land, Region(en), Ferienwahl und Jahre. Fremde oder unklar zugeordnete Bestände
bleiben erhalten. Bei einer gemeinsamen Zeile für mehrere Bundesländer bleibt
der nicht erneuerte Anteil mit konsistenten geografischen Feldern und Beschriftung
bestehen. Gleichwertige positive Zeilen werden wieder zusammengeführt, damit
wiederholte enge Abrufe keine Dubletten anhäufen. Gewöhnliche Termine, Serien,
synchronisierte Kalendertermine, Notizen und Aufgaben bleiben unberührt.

Eine normale GUI-Antwort ohne ausstehende Anfrage wird ignoriert. Der bestehende
MCP-Weg mit `requestId`, Revisionsprüfung und nativer Speicherbestätigung bleibt
erhalten. Eine fehlgeschlagene Speicherbestätigung meldet weiterhin `save_failed`;
wie im bestehenden MCP-Vertrag bleibt die beabsichtigte Änderung dabei zunächst
im Arbeitsspeicher. Es wird keine erfolgreiche dauerhafte Speicherung behauptet.

## Tatsächlich ausgeführte Prüfungen

| Bereich | Unveränderte Basis | Endgültiger Kandidat |
| --- | ---: | ---: |
| Beide vollständigen Desktopskripte, gleiche 80 Fälle | 16/80 | **80/80** |
| Tatsächlicher MCP-Aufruf, HTTP-Fehler, SaveACK-Erfolg/-Ablehnung | – | **6/6** |
| Vorhandener Einrichtungsablauf, englischer Quellkatalog | – | **50/50** |
| Linux-Originalfunktionen, Python-Host | 14/26 | **26/26** |
| Windows-Originalmethoden/Parser, C#-Host | 15/26 | **26/26** |
| Vollständiger Tablet-Dienst und reguläre JUnit-Klasse | – | **20/20** |
| Fünf neue Swift-Testmethoden | nicht ausgeführt | **nicht ausgeführt** |

Die 64 roten Frontendfälle beziehungsweise roten Native-Vertragsprüfungen sind
keine ebenso große Zahl unabhängiger Programmfehler. Sie prüfen verschiedene
Erhaltungs- und Vollständigkeitsanforderungen desselben Befunds.

- [Frontend-Vorher](frontend/before.json), [Frontend-Nachher](frontend/after.json),
  [MCP](frontend/mcp-after.json), [Einrichtungsprotokoll](frontend/setup-english.log).
- [Native Belege und Wiederholung](native/README.md): echte Produktfunktionen,
  kontrollierte HTTP-/Callback-/Gettext-Doubles. C# SDK 8.0.428, Runtime 8.0.34,
  Ausführung unter Linux; beide endgültigen Builds ohne Warnung/Fehler.
- [Tablet-/Mac-Belege](ports/README.md): Kotlin 2.4.21, JVM-Bytecodeziel 17,
  tatsächliche Laufzeit OpenJDK 21.0.13.1. 20 JUnit-Fälle; eine vorbestehende
  Warnung in `DAV.kt`. Keine Android-Stubs, kein Android-SDK-/Gradle-/Gerätelauf.
- [Maschinenlesbare Zusammenfassung](TEST-SUMMARY.json).

### Korrigierte Prüfannahmen und verworfene Kandidaten

Die unabhängige Gegenprüfung fand im ersten Frontendkandidaten einen falschen
optionalen `.has`-Aufruf und danach wachsende Regionsdubletten. Der Kandidat wurde
verworfen; beide Fälle stehen in der endgültigen Regression. Der erste begrenzte
Lauf mit 14/68 liegt als historisches Fehlerprotokoll bei und ist kein Nachweis
für den endgültigen Patch.

Der erste MCP-Zusatztest erwartete irrtümlich einen allgemeinen In-Memory-Rollback
nach SaveACK-Ablehnung. Der bestehende Produktvertrag verspricht stattdessen
`save_failed` und fordert erneutes Lesen der aktuellen Daten. Der Test wurde an
diesen überprüften Vertrag gebunden; kein Produktcode und keine Speichersperre
wurden dafür gelockert. Das ursprüngliche Erwartungsfehlerprotokoll bleibt erhalten.
Ein erster C#-Hostbau benötigte `#nullable enable` im Testwrapper; anschließend
liefen Basis und Kandidat mit identischem Host. Auch dessen erste Logs liegen bei.

Der volle bestehende Einrichtungs-Sprachlauf war wegen fehlender erzeugter
PO-JavaScript-Kataloge und fehlendem `msgfmt` nicht ausführbar. Anschließend wurde
nur die Sprachmatrix auf den englischen Quellkatalog begrenzt; alle übrigen
ursprünglichen Assertions und beide Frontends blieben identisch. Diese **50 Fälle
ersetzen keine Abnahme der übrigen 19 Übersetzungen**. Der externe begrenzte
Runner und der ursprüngliche Ladefehler sind enthalten; der Produkttest selbst
wurde nicht geändert.

## Bewusste Grenzen

Eine nur teilweise abgefragte jahresübergreifende Altperiode oder ein nationaler
Eintrag bei ausschließlich regionalem Erfolg bleibt vorsichtshalber erhalten.
Es kann deshalb ein älterer Teilstand bestehen bleiben, bis eine vollständig
passende Abfrage vorliegt. Ohne persistente Provideridentität ist eine unsichere
Löschung nicht durch eine Namensvermutung ersetzt worden. Reichere Identitäten,
Gruppen, Quellenabdeckung und örtliche Abrufhistorie bleiben #853/#854 vorbehalten.

Ältere Hosts ohne das neue Feld führen positive Ergebnisse konservativ zusammen,
löschen aber keine unbestätigten Cachebereiche. Der Legacy-GUI-Weg hat weiterhin
keine individuelle Antwortkennung; der neue Guard ist keine Zusage, jede denkbare
verspätete Antwort während eines anderen aktiven Abrufs erkennen zu können.

Swift-Compiler-/Laufzeitprüfung, native Windows-/Linux-/Tablet-/Mac-Oberflächen,
Live-Provider, installierte Pakete und übrige Sprachläufe sind offen. Keine
Veröffentlichungsfreigabe oder Aussage „alle internationalen Kalender fehlerfrei“.

## Providerquellen

Die offiziellen [Controller](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Controllers/HolidaysController.cs)
verwenden inklusive Überlappung und liefern auch jahresübergreifende Perioden
vollständig zurück. Trotzdem kann ein korrigierter früherer Zeitraum ganz aus
einem einzelnen abgefragten Jahr herausrutschen; deshalb genügt für seine
vollständige Entfernung kein bloßes Berühren dieses Jahres.
Der [DTO](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Dtos/Responses/HolidayResponse.cs)
fordert insbesondere Enddatum und Nationwide-Flag. Ein vorhandener toleranter
Lesefallback ist kein Vollständigkeitsnachweis.

## Wiederholung und Fortsetzung

Patch zunächst auf einer isolierten Kopie der angegebenen Basis mit
`git apply --check` prüfen, dann anwenden. Die JS-Prüfprogramme sind im üblichen
Windows-Webprüflauf registriert und prüfen beide Desktopquellen. Für einzelne
Läufe genügt die vorhandene Projekt-Testabhängigkeit JSDOM 26.1.0:

```sh
node magnolie-organizer-windows/tests/holiday-cache.js
node magnolie-organizer-windows/tests/holiday-cache-mcp.js
python magnolie-organizer/pruefungen/test_holiday_fetch_coverage.py
python magnolie-organizer-windows/tests/holiday-fetch-coverage.py \
  --dotnet /path/to/dotnet --build-dir /tmp/magnolie-holiday-test
```

Der gemeinsame vorhandene MCP-Harness benötigt die normal generierten
`normative-timezones.js`-Assets; sie wurden hier unverändert mit
`port-adapters/timezones/projection-assets.cjs` aus den gebundenen Quellen erzeugt.
Der 80-Fälle-Test erzeugt diese Assets ausschließlich im Speicher. Native- und
Kotlin-Wiederholung stehen in den jeweiligen Teilberichten. Heruntergeladene
Compiler, Abhängigkeiten und erzeugte Binaries sind nicht Teil dieses Pakets.

Nächster Schritt: #855 in Codex prüfen/übernehmen und die offenen Swift-/nativen
Abnahmen beachten. Der fortlaufende Review liest danach frischen main sowie
#853/#854 und deren In-Arbeit-Markierungen; Quellen-/Regionsabdeckung und
Festtagsidentitäten/SVGs benötigen weiterhin ihre eigenen vollständigen Patches.
Die separat aktive #128-Automatik nicht parallel neu implementieren.
