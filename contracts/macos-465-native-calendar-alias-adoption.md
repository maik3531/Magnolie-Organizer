# Mac #465: native Altkennungsbelege bis zur bestehenden Importlogik führen

Stand: 26. November 2026. Patchbasis:
`e89d2eec099a933ddbad4bdc529eb7f7698af2ed`, auf dem vollständigen
Mac-Zweig `616069f15fed21d8d8d05c8ef795f4ed21bd059c`.
Der vorangehende #771-Fix ist unabhängig von der Aliaszuordnung.

## Bestätigter Befund und begrenzter Fix

Der Swift-Reader hatte seit `405406b9` einen getrennten
`ICalendarImport.Result.legacyAndroidAliases`-Beleg. Er bindet die historische
Android-Hashkennung an den SHA-256 der tatsächlich eingelesenen ICS-Bytes,
die Gesamtzahl und Position der Termine, Quellkennung, ursprüngliche Wire-UID
und vollständige rohe `RECURRENCE-ID`-Zeile. Die native Hostantwort verwendete
jedoch nur `.document` und übertrug diesen Beleg nicht.

Die aktuelle Mac-Projektion enthält bereits die gemeinsame Desktop-
Aliaslogik aus #462. Deshalb wird deren Fehlen nicht behauptet. Sie konnte
die alte Kennung bisher nur erneut über `crypto.subtle` berechnen.
Der neue Patch führt die schon vorhandenen nativen Belege bis zu diesem
Planer. Ein zweiter Merge oder eine UID-/Titel-/Datumsheuristik entsteht nicht.

`Result.response` ergänzt die temporären Belege in der Hostantwort. `document`
und `icsImportMetadata` bleiben unverändert und ohne Belegfelder. Die schon
vorhandene gemeinsame 96-MiB-Projektionsgrenze zählt Dokument und Sidecar.

Der Mac-Callback übernimmt eine eigene Kopie der Antwort. Er registriert den
Sidecar nur für diesen Empfang in einer `WeakMap`, gebunden an:

- exakten aktuellen Buchgegenstand und vollständigen Buchinhalt;
- Sidecar-Version/Algorithmus, Quellhash und zugehörige Metadaten;
- Terminzahl, Positionen und alle gelieferten Terminidentitäten;
- kanonische/alte UID, Quelle, Wire-UID und unveränderte rohe RID;
- eindeutige Indizes, Quell-/UID-Kombinationen und Serieninstanzidentitäten.

Vor dem Plan und vor jeder Sammlungsmutation werden diese Bindungen erneut
geprüft. Ein gleichnamiges Feld aus einem Buch oder eine direkte unregistrierte
Importnutzlast ist keine native Evidenz. Die bestehende Desktoplogik entscheidet
weiter, ob genau ein vorhandener Datensatz mit der bewiesenen Altkennung
existiert. Unbekannte Hashes, zwei vorhandene Zeilen oder mehrdeutige Eingänge
scheitern vor der Mutation. Alte lokale ID/UID, Verweise, Unknowns, lokale
Alarme, Teilnehmer, Anhänge und Providerlisten bleiben wie bisher erhalten.

Der bestehende Normalisierungspfad für mehr als 1000 Termine behält die
Objektidentität des temporären Sidecars. Sein rekursiver Aufruf wird jetzt
auch zurückgegeben, damit die native Callback-Promise bis zur abschließenden
Prüfung reicht. Während der Teilverarbeitung geänderte oder neu geöffnete
Bücher verwerfen den alten Eingang. Reine Registrierungsfehler werden als
Importkonflikt gemeldet; spätere Merge-/Darstellungsfehler werden nicht durch
den neuen Wrapper als unveränderte Vorbereitung ausgegeben.

## Reproduktion und tatsächlich ausgeführte Prüfungen

Die neue Regression wurde zunächst gegen die vorangehende, unveränderte
Projektion `e89d2eec` ausgeführt. Ohne eingespritztes WebCrypto ignoriert diese
den nativen Sidecar; der Titel der alten Zeile bleibt stehen. Die positive
Adoptionsassertion scheitert. **Das ist ein reproduzierter Host-/DOM-Befund,
keine Behauptung, dass ein bestimmtes installiertes WebKit WebCrypto vermisst.**

Mit dem Patch bestehen unter Linux, Node 24.22.3 und JSDOM 26.1.0 fünf gezielte
Testgruppen:

| Prüfung | Ergebnis |
| --- | --- |
| Native Aliasadoption im tatsächlich projizierten UI | 101 Prüfungen |
| Allgemeiner UI-/Hostvertrag | 109 Assertions |
| Bestehende Systemkalenderkopien | 307 Prüfungen |
| Reproduzierbare vollständige Projektion | Bestanden |
| Freeze- und Manipulationserkennung | Bestanden |

Die Aliasprüfung verwendet den echten aktuellen Pythoncodec als unabhängige
Dokumentquelle und synthetische Sidecars nach dem Swift-Vertrag. Belegt sind
zwei Wiederimporte, tatsächliche Save-Nutzlasten und erneutes Frontend-`init`,
sechs Grenzen für Quelle/Wire-UID/RID/TZID/RANGE/VALUE, fünf Mehrdeutigkeiten,
14 manipulierte Bindungen, 1001 Termine mit Teilverarbeitung, konkurrierende
Buchänderung, Dokumentwechsel und Erhalt der eigenen Eingangskopie.
Save-ACKs sind synthetisch; es wurden keine echten Dateien neu geöffnet.

Die vorhandenen 19 UI-Kataloge wurden mit `po_zu_js.py` und GNU `msgfmt` aus
den unveränderten PO-Quellen vorbereitet. `git diff --check` und Python-
Syntaxprüfung bestehen. Es wurden keine gemeinsamen Linux-/Windows-
Produktdateien geändert.

## Nachprüfung mit Codex

```sh
cd Magnolie-Organizer-macOS-Beta
MACOS_BETA_JSDOM=/path/to/jsdom/lib/api.js \
  python3 tools/check_legacy_calendar_aliases.py --js-runtime /path/to/node
```

Die alte Fehlerphase lässt sich mit demselben Runner und
`--baseline-ref e89d2eec099a933ddbad4bdc529eb7f7698af2ed` wiederholen;
dieser gezielte Baseline-Lauf soll an der Adoptionsassertion scheitern.

Ein zusätzlicher Swift-Test prüft die native Antwort, die Quellbindung und
den getrennten unveränderten Dokumentwert. **Er ist hier nicht kompiliert
oder ausgeführt**, da kein Swift-/macOS-System verfügbar ist. Auf macOS kann
der Test einen tatsächlichen Swift-DTO für denselben UI-Runner schreiben:

```sh
MACOS_BETA_LEGACY_ALIAS_ENVELOPE=/absolute/path/to/native-alias-envelope.json \
  swift test --jobs 2 --filter LegacyAndroidAliasEvidenceTests
MACOS_BETA_JSDOM=/path/to/jsdom/lib/api.js \
  python3 tools/check_legacy_calendar_aliases.py --js-runtime /path/to/node \
  --native-envelope /absolute/path/to/native-alias-envelope.json
```

Auch dieser DTO-Lauf ersetzt nicht den echten AppKit-Dateidialog,
WKWebView-Callback und dauerhaften Save/Reopen auf Intel und Apple Silicon.

## Verbleibender Umfang von #465

Bereits doppelt gespeicherte Ausnahmezeilen werden ausdrücklich **nicht**
automatisch repariert. Solche Mehrdeutigkeiten werden in der neuen Suite
ohne Mutation abgewiesen. Eine ausdrücklich bestätigte exakte Paarreparatur
muss Unknowns, widersprüchliche lokale Listen, alle Verweise und
Komponentenassoziationen gesondert auflösen und native Wiederöffnung belegen.
Der strenge Reopenvalidator bleibt unverändert. Der Tablet-Port und die
Android-Pause aus #423 bleiben eigenständiger Restumfang.

Dies ist eine Quellstandsicherung für die spätere Prüfung/Anwendung,
keine native Gesamtabnahme, Installation oder Veröffentlichung.

## Reproduzierbarkeit nach dem gemeinsamen Kontaktpatch

Der Baseline-Modus erzeugt jetzt eine vollständige isolierte Git-Archivkopie
des angegebenen historischen Commits. Dessen eigener Projektor liest dessen
eigene Eingaben; die 19 ignorierten Sprachkataloge werden mit seinem Generator
aus seinen PO-Dateien und echtem gettext neu erstellt. Die heutige Testfixture
und der heutige Probe-Runner bleiben absichtlich konstant. Dadurch vermischt
die Baseline keinen alten Mac-Projektor mit den neuen Kontaktankern aus #776.
Der erneute Probe-Lauf gegen `e89d2eec` scheiterte an der erwarteten fachlichen
Adoptionsassertion (alter Zeilentitel blieb unverändert), nicht an einem
Projektionsanker. Der aktuelle Lauf bestand weiterhin 101 Prüfungen.
