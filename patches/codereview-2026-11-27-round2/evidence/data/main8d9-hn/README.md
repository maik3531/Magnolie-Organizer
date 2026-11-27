# #837 – exakte CSV-Prioritätskurzwerte H/N

## Quellstand und enger Umfang

Basis ist exakt `8d9aec671a4c63f999ed7fbe74f8752af6978250`.
Der Ergänzungscommit ist `14bc2fa1330037120f98b6dc31c76f5690a29eb6`
(`Refs #837`), Quellbaum `6d5cba6c875e024d55cb40cbc0278c9c5fe1a726`.
Der eigene Prüfzweig heißt `review/round2-837-hn-20261127` und ist sauber.

Die Basis ordnet in beiden tatsächlichen Aufgaben-CSV-Readern die vollständigen
Werte `H` und `N` der normalen Priorität 2 zu. Der Patch ergänzt ausschließlich
`H` in der exakten Hoch-Menge und `N` in der exakten Niedrig-Menge. Die neueren
Spaltenaliase, Abschlusswörter sowie der normale Rückfall für unbekannte Werte
bleiben unverändert. Der bestehende gemeinsame Vertrag erhält zwei zusätzliche
Zeilen; seine bestehenden Tests prüfen dadurch insgesamt 14 Aufgaben statt 12.
`ARBEITSSTAND.md` dokumentiert den begrenzten Prüfstand.

## Tatsächliche Vorher-/Nachher-Ergebnisse

Die vier synthetischen CSV-Zeilen wurden durch `lotus_csv_lesen` aus der aktuellen
Linux-Quelle und den vorhandenen `NativeImportProbe` mit dem tatsächlichen
C#-`ExchangeCodec.ParseImport` verarbeitet. Es wird keine Parserlogik nachgebaut.

| CSV-Wert | Soll | Linux vorher | C# vorher | Linux nachher | C# nachher |
|---|---:|---:|---:|---:|---:|
| `H` | 1 | 2 | 2 | 1 | 1 |
| `N` | 3 | 2 | 2 | 3 | 3 |
| `Normal` | 2 | 2 | 2 | 2 | 2 |
| `Not set` | 2 | 2 | 2 | 2 | 2 |

| Gezielte Prüfung | Vorher | Nachher |
|---|---|---|
| Beide echten Reader, vier Werte pro Port | 4/8 bestanden, Exit 1 | 8/8 bestanden, Exit 0 |
| Bestehender Python-Vertragstest, drei Spaltengruppen | 1 fehlgeschlagen, 2 bestanden, Exit 1 | 3 bestanden, Exit 0 |
| Bestehende C#-Vertragsgruppe | 0/1 bestanden, Exit 1 | 1/1 bestanden, Exit 0 |
| C#-Quellhost-Bau | 0 Warnungen, 0 Fehler | 0 Warnungen, 0 Fehler |

Die gemeinsamen Vertragstests prüfen CSV-Import und VTODO-Export/Reimport mit
Titel, Fälligkeit, Erledigtstatus und Priorität. Die vorhandenen deutschen und
englischen Alternativspalten, normale/unbekannte/leere Prioritäten und die
Abschlusswörter bleiben Teil dieser 14 Aufgaben. Die Vorher-Läufe enthalten
bereits die zwei neuen Vertragszeilen, aber noch unveränderte Produktquellen
der Basis. Die C#-Vertragsgruppe stoppt beim ersten H-Fehler; die separate
Reader-Probe weist H und N sowie beide Kontrollen für beide Ports einzeln nach.

## Reproduzieren

Voraussetzungen: vorhandene Python-Abhängigkeiten wie im Repository,
Python 3.13.5 und .NET SDK 8.0.408 im dokumentierten Prüflauf. `source_root`
bezeichnet einen eigenen Checkout, `evidence_dir` diesen Belegordner und
`dotnet_exe` das vorhandene .NET-Programm. Im Prüflauf war `TZ=UTC` gesetzt.
NuGet-Abhängigkeiten wurden mit dem bestehenden Sperrstand aus dem vorhandenen
Cache wiederhergestellt.

Für den Vorher-Lauf die genannte Basis auschecken und nur die Vertragsänderung
aus [837-main8d9-hn.patch](837-main8d9-hn.patch) anwenden:

```sh
cd "$source_root"
git apply --include=contracts/lotus-task-csv-vectors.json "$evidence_dir/837-main8d9-hn.patch"
export TZ=UTC
cd "$source_root/magnolie-organizer-windows"
"$dotnet_exe" restore tests/native-import/NativeImportProbe.csproj --locked-mode --ignore-failed-sources -p:NuGetAudit=false
"$dotnet_exe" build tests/native-import/NativeImportProbe.csproj --no-restore
"$dotnet_exe" tests/bin/Debug/net8.0/CoreTests.dll 'Lotus task CSV'
cd "$source_root"
/usr/bin/python3 -m pytest -q magnolie-organizer/pruefungen/test_lotus_task_csv.py
/usr/bin/python3 "$evidence_dir/check_csv_readers.py" --source "$source_root" --dotnet "$dotnet_exe"
```

Für den Nachher-Lauf die restlichen Patchdateien mit
`git apply --exclude=contracts/lotus-task-csv-vectors.json` anwenden, den
Quellhost erneut bauen und dieselben drei gezielten Prüfungen wiederholen.
Die ersten Fehlerausgänge sind beim Vorher-Lauf ausdrücklich erwartet.

## Belege und Grenzen

[readers-before.log](readers-before.log) und
[readers-after.log](readers-after.log) enthalten die Einzelwerte sowie
SHA-256 der beiden tatsächlichen Produktquellen, des gemeinsamen Vertrags
und der jeweils gebauten C#-Assembly. Die Angabe `source_commit` in beiden
Rohlogs ist der zum Laufzeitpunkt noch ausgecheckte Basis-HEAD; die nachher
geprüften Quellbytes wurden anschließend unverändert in den genannten
Ergänzungscommit übernommen. [manifest.json](manifest.json) verbindet Basis,
Commit, Ergebnisse und Loghashes. Sein Feld `artifacts` erfasst sämtliche
hier ausgelieferten Dateien mit relativem Namen, SHA-256 und Bytegröße; das
Manifest selbst ist davon ausgenommen.

Die C#-Prüfung läuft mit tatsächlichen Windows-Produktquellen im Linux-.NET-
Quellhost. Eine native Windows-/GUI-/Paketabnahme wurde nicht durchgeführt.
Es gab keine weitere Scope-Suche, keine Kontaktdatenänderung und keine
GitHub-Mutation oder Main-Integration. Der Ordner enthält ausschließlich
Textbelege; die gebauten Binärdateien sind nicht Bestandteil der Lieferung.
