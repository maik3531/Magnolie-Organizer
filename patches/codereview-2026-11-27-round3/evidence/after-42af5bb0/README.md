# Finale Nachtragsserie auf 42af5bb0

Die feste Basis ist `42af5bb030d5e0fb8a2bfc8b8f28459cfe31c2fe`.
Die vorherigen Lieferungen bleiben historische Nachweise; diese Serie erhält
die bereits in main übernommenen Lösungen aus #840/#841/#842 und die
Kontaktkorrektur aus #823. Spätere main-Stände wurden nicht verfolgt.

## Zusätzlich bestätigter Feldrest in #823

Die übernommene Kontaktkorrektur enthält die richtige lokale Identitätswahl.
In beiden Inhalts-Whitelists fehlt jedoch das unterstützte Feld
`kontaktpersonen`. Es wird im Mehrfach-Notfallkontakt-Editor, im Datenvertrag
und in beiden vCard-Lesern und -Schreibern verwendet.

Die Diagnose erzeugt mit dem tatsächlichen Python-vCard-Schreiber eine
synthetische Karte mit zwei Notfallkontakten. Beide echten Leser übernehmen
die beiden Einträge. Der aktuelle Kontakt hat dieselbe lokale ID, eine neue
UID und eine leere Notfallkontaktliste. Beim ergänzenden Restore auf 42af
bleibt die Liste leer; nur die alten Einzelfelder der ersten Person kommen
zurück. Die tatsächliche Python-Normalisierung liefert deshalb eine statt
zwei Personen. Karte und aktuelle UID werden bereits korrekt erhalten.

Der neue Produktnachtrag fügt ausschließlich `kontaktpersonen` in die beiden
vorhandenen Whitelists ein. Beide tatsächlichen Restore-Pfade erhalten danach
beide Personen. Die Vorher-/Nachher-JSONs binden die verwendeten Produktquellen,
die C#-Assembly und dieselbe vCard-Datei an SHA-256-Prüfsummen. Die Diagnose
verändert ihre Eingabekarten nicht.

## Tests und erhaltene Änderungen

Alle **40 übernommenen Vektoren**, einschließlich der drei neuen Hauptzweigfälle,
bleiben erhalten. Dazu kommen die **zwölf bisherigen Reviewvektoren** und
**ein neuer gemeinsamer Feldfall**: insgesamt **53 Fälle**, ohne gleiche IDs
oder identische Fälle unter anderem Namen.

| Prüfung | Unveränderte 42af-Produktquellen mit zusätzlichen Tests | Nach minimalem Feldnachtrag |
|---|---:|---:|
| Vier vorhandene Python-Restore-/Save-Dateien | 143 bestanden, 1 fehlgeschlagen | 144 bestanden |
| C#-Identitätsgruppe mit 53 Vektoren | Neuer Feldfall fehlgeschlagen | Bestanden |
| Tatsächliche Python-vCard-/Restore-Diagnose | 2 Personen → Liste leer; normalisiert 1 | 2 Personen erhalten |
| Tatsächliche C#-vCard-/Restore-Diagnose | 2 Personen → Liste leer | 2 Personen erhalten |

Der finale CoreTests-Bau mit SDK 8.0.408 und `RestoreLockedMode=true` hat
**0 Warnungen und 0 Fehler**. Alle **sechs** angeforderten C#-Gruppen bestehen:
Kontaktidentität, Wiederherstellungsjournal, UTF-16-Import (**148 Fälle**),
Austauschformate, native Importdateileser und Aufgaben-CSV.

Die #841-/#842-Testnachträge und der vollständige #839-Patch werden unverändert
übernommen. Die übernommenen i18n-Dateien, der UTF-16-Decoder, dessen zusätzliche
Vertragstests und beide #840-Workflows bleiben bytegleich zur festen Basis.
Die Eingaben der zuvor bestandenen 16 DOM-, 398 Mac-, 30 Tablet- und 23
JVM-Speicherprüfungen sind bytegleich gebunden; diese Suiten wurden nicht
erneut ausgeführt. Die Arbeitsstand-Dokumentation ergänzt den aktuellen Stand
und erhält den vollständigen vorherigen Inhalt.

## Portable Wiederholung

Die drei Argumente sind die Pfade des anzuwendenden Checkouts, der vorhandenen
Werkzeuge und eines frei gewählten Ausgabeordners:

```sh
python3 run-focused-tests.py --checkout REPOSITORY --tools PREPARED_TOOLS --output OUTPUT
```

Der Werkzeugordner enthält `dotnet/dotnet`, `dotnet-state`, `nuget` sowie
`python/bin/python` mit pytest. Der Runner führt den Build selbst aus,
verwendet `TZ=Europe/Berlin`, setzt den tatsächlichen Testquellpfad und
protokolliert die wirklichen Rückgabecodes. `--contact-only` beschränkt den
roten Vorherlauf auf die vier Python-Dateien und die C#-Identitätsgruppe.
Für einen Vorherlauf müssen die zusätzlichen Tests bei unveränderten
42af-Produktquellen liegen; das genaue Index-Tree und alle Eingabehashes
stehen im Vorhermanifest.

Die unterstützte Python-vCard-Diagnose ist separat ausführbar:

```sh
python3 contact-persons-probe.py --checkout REPOSITORY --output OUTPUT
```

Für die C#-Diagnose `native-contact-probe/ContactProbe.csproj` mit demselben
SDK bauen; anschließend `ContactProbe.dll` mit drei Argumenten starten:
dem tatsächlich gebauten `CoreTests.dll`, der erzeugten
`OUTPUT/emergency-contacts.vcf` und der geprüften `RestoreSelection.cs`.
Sie ruft die tatsächlichen Produktklassen per Reflection auf.

Dies sind Quell-/Hostprüfungen unter Linux. Die hier dokumentierte lokale
Prüfstufe führte keine GitHub-Schreibaktion und keinen Merge nach main aus.
Sie erstellte kein Produktpaket und enthält keine native Windows-GUI-,
macOS-Mitteilungs- oder Android-Geräteabnahme.
