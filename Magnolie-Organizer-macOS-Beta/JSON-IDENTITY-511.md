# #511: exakte JSON-Identitäten und verbleibende Darstellungsgrenze

Geprüfte Ausgangsbasis: `616069f15fed21d8d8d05c8ef795f4ed21bd059c`.
Dieser Patch ist eine begrenzte Sicherung des bestehenden Speichervertrags.
Er ist **kein vollständiger Abschluss von #511** und gibt keine neuen
JSON-Schlüsselpaare für die Swift-Dictionary-Brücke frei.

## Konkret korrigierter Quellenbefund

`Document.assertNoLoss` verglich bisher Feldnamen über `Set<String>` und ordnete
Datensätze über `[String: Any]` nach `id` zu. Swift vergleicht die beiden
Zeichenfolgen `caf\u00e9` und `cafe\u0301` kanonisch gleich. Ihre UTF-8-Bytes
sind jedoch verschieden: `636166c3a9` und `63616665cc81`.

Zwei **einzeln darstellbare** Dokumente konnten deshalb einen unterschiedlichen
Feldnamen oder eine unterschiedliche Datensatz-ID enthalten, während die
No-loss-Prüfung die neue Identität für die alte hielt. Der tatsächliche
Speicherhandler in `Sources/MacBeta/main.swift` entscheidet anhand dieser
Prüfung, ob vor dem Schreiben eine Wiederherstellungskopie erforderlich ist.
Der Quellenbefund ist nicht als bereits beobachteter Nutzerdatenverlust zu
verstehen; ein neuer nativer Lauf wurde hier nicht ausgeführt.

Der Patch verwendet die vorhandene `OpaqueUTF8Identity` für beide Zuordnungen.
Ein anderer dekodierter Feldname beziehungsweise eine andere ID verlangt damit
den bestehenden Recovery-Pfad. Zwei unterschiedliche IDs dürfen zugleich im
Array bleiben und ihre Position tauschen; ihre unbekannten Felder werden
jeweils über die genaue ID geprüft. Echte doppelte IDs werden weiterhin
abgewiesen. Anzeigenamen, Nutztexte, Kalender-UIDs und Dateninhalte werden
nicht normalisiert oder umgeschrieben. Der atomare Speicher- und
Recovery-Schreiber bleibt unverändert.

## Bewusst unveränderte Brückengrenze

Innerhalb **desselben JSON-Objekts** kann ein Swift-`[String: Any]` beide
kanonisch äquivalenten Schlüssel weiterhin nicht sicher darstellen.
`JSONKeys` prüft daher jetzt zwei getrennte Sachverhalte:

1. Genau derselbe dekodierte UTF-8-Schlüssel, einschließlich anderer
   JSON-Escapeschreibweise: weiterhin `Duplicate JSON key.`.
2. Verschiedene dekodierte UTF-8-Schlüssel, die erst der Swift-Vergleich
   zusammenlegen würde: ausdrücklicher Hinweis auf die noch bestehende
   macOS-Darstellungsgrenze; die Originaldatei bleibt unangetastet.

Der zweite Guard bleibt **vor** `JSONSerialization.jsonObject` bestehen.
Nur den ersten Guard auf UTF-8 umzustellen und den zweiten zu entfernen wäre
kein Fix: Die nachfolgende Foundation-/Swift-Brücke könnte Werte verlieren.
Die neue Diagnose wird auch auf Deutsch bereitgestellt. Eine vollständige
Übersetzungsabnahme aller nativen Meldungen wird nicht behauptet.

## Konkrete Prüfungen

`tests/opaque_json_keys.mjs` führt die tatsächlich erzeugte Mac-Oberfläche aus.
Die Fixture enthält beide Schlüssel am Root, in einem unbekannten Objekt und
in einem darin verschachtelten Array sowie zwei gleich aussehende, byteweise
unterschiedliche Datensatz-IDs. Geprüft werden echte Initialisierung und
Normalisierung, der tatsächliche `speichern`-Request sowie die tatsächliche
Restore-Vorbereitung. Die 20 Assertions bestätigen den Erhalt an dieser
JavaScript-Grenze. Der native Transport und sein Save-ACK sind synthetisch.
Das belegt weder Swift-Akzeptanz noch einen nativen Dateischreibvorgang.

`DocumentOpaqueIdentityTests.swift` enthält die getrennten nativen Regressionen:

- echte Duplikate bleiben ungültig;
- äquivalente, unterschiedliche Schlüssel werden an jeder Objekttiefe
  ausdrücklich vor der unsicheren Brücke abgewiesen;
- nicht kollidierende Unicode-Schlüssel behalten ihre UTF-8-Bytes;
- Feld-/ID-Ersetzungen verlangen Recovery, unveränderte Identitäten nicht;
- zwei unterschiedliche IDs dürfen umsortiert werden; unbekannte Felder
  dürfen nicht zum anderen Datensatz wechseln;
- die echte `OrdinarySaveEpochPolicy` und der echte `AtomicStore` erhalten
  vor der Ersetzung die exakten ursprünglichen Datei-Bytes und öffnen den
  neuen Stand anschließend wieder;
- ein nicht darstellbares Schlüsselobjekt verändert den vorhandenen
  Profilstand nicht;
- der vom tatsächlichen JavaScript-Runner erzeugte Save-/Restore-Text wird
  an der nativen Grenze weiterhin sicher abgewiesen.

Die zehn Swift-Testmethoden sind vorbereitet. In der Entwicklungsumgebung
dieses Patches ist kein Swift-Compiler vorhanden; sie sind hier **nicht
kompiliert und nicht ausgeführt**. Historische native Kalender-/Restore-Tests
anderer Commits ersetzen diesen neuen Nachweis nicht.

### Wiederholbare Befehle

Aus dem Repositoryroot, mit dem vorhandenen Node/JSDOM des Projekts:

```sh
python3 Magnolie-Organizer-macOS-Beta/tools/check_opaque_json.py --js-runtime node
```

Auf dem bestehenden Mac-Prüfweg jeweils für Intel und Apple Silicon:

```sh
python3 Magnolie-Organizer-macOS-Beta/tools/check_opaque_json.py --js-runtime node --swift /usr/bin/swift
```

Der zweite Befehl verwendet die originalen erzeugten UI-Eingaben und führt
gezielt `DocumentOpaqueIdentityTests` aus. Der vorhandene begrenzte
Swift-Prozesswächter wird wiederverwendet. Ohne `--swift` wird ausschließlich
die JavaScript-Grenze geprüft. Temporäre Projektionen und Builddateien werden
entfernt; die Eingangsdatei-Inventur muss vor/nach dem Lauf identisch bleiben.

## Noch erforderlicher vollständiger #511-Fix

Die dauerhafte Lösung braucht eine durchgehende verlustfreie JSON-Struktur:
Objektmitglieder mit bytegenauen dekodierten Schlüsseln, Werte und Zahltypen
ohne nachträgliches `String`-Dictionary als einzige Datenquelle. Ein
temporäres Ersetzen unbekannter Schlüssel durch erfundene ASCII-Namen würde
dynamische Metadaten-/ID-Maps verändern und ist kein sicherer Übergang.

Vor Freigabe solcher Schlüsselpaare müssen mindestens diese tatsächlichen
Wege dieselbe Repräsentation behalten:

| Grenze | Erforderlicher Nachweis |
| --- | --- |
| `Document.object/plain/encode` | Beide ursprünglichen Schlüssel und Werte einschließlich verschachtelter Erweiterungen; echte Duplikate, Tiefen- und Bytegrenzen bleiben streng |
| `Document.assertNoLoss` | Opaque Feld- und ID-Zuordnung auch nach dem Wechsel der Objektstruktur; keine vermischten unbekannten Felder |
| `OrdinarySaveEpochPolicy.prepare` | Nur die festgelegten nativen Epochenslots ändern; das übrige Buch mit allen Zahlen und unbekannten Mitgliedern erhalten |
| `DAVBookRestore.transform` und `NativeBookRestore` | Quarantäne/Recovery/Authentifizierung/atomare Publikation bleiben gebunden; kein archivierter Sync-Grant wird neu aktiviert |
| Native Buch-Admission und tatsächliche Disk-Snapshots | Autorität aus genau den gespeicherten Bytes prüfen; kein verlustbehaftetes normalisiertes Shadow-Dictionary |
| `RegionalSettings.merging`, Backup, Verschlüsselung und weitere Ganzbuch-Schreiber | Fremde Schlüsselpaare bleiben bei einer Änderung bekannter Felder unangetastet |
| Swift ↔ WKWebView und echter Export | Transport als unveränderter JSON-Text beziehungsweise geeignete typisierte Struktur; Objektbrücken dürfen die Paare nicht vorab zusammenlegen |

Abschlussfolge: parse → native validate → normaler Save → tatsächlicher
Disk-Readback → getrenntes Neuöffnen → JSON-Export; zusätzlich verschlüsselter
Restore und Fehlerfälle. Erst ein erfolgreicher End-to-End-Nachweis auf beiden
Mac-Architekturen rechtfertigt das Entfernen des derzeitigen Brückenguards.
Linux/Windows sind durch diesen Swift-Befund nicht als fehlerhaft oder
korrigiert ausgewiesen.
