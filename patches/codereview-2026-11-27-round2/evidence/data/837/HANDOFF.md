# #837: CSV-Aufgabenwerte

## Ergebnis und Quellstand

- Basis: `1543858e251d7e29ebeafb67d2605991c1d442d5`.
- Commit: `c68c17041831650a3378cc2a8c60de0f13287b32`, `Refs #837: Preserve CSV task priority and completion values`.
- Patch: `837-csv-task-values.patch`.
- SHA256: `8654be848a85ee1ceeb33e1704f8cb4bd396cf494b96ed0943c3fa8f82c96dcc`.

Der tatsächliche Windows-CSV-Reader setzte Hoch/High und 3/Niedrig auf normal,
COMPLETED/ABGESCHLOSSEN auf offen. Der Linux-Reader behandelte schon `Normal`
wegen des Anfangsbuchstabens N als niedrig; auch unbekannte Präfixwerte wurden
als hohe/niedrige Priorität geraten. `before.json` und
`tasks-status-priority.csv` belegen die ursprünglichen Datenfehler.

Die kleine Produktänderung betrifft ausschließlich die CSV-Aufgabenwerte.
Beide Reader erkennen hohe Werte 1/H/High/Hoch und niedrige Werte
3/N/Low/Niedrig exakt, ohne Beachtung der Großschreibung und mit äußerem
Leerraumtrimmen. Alle anderen Werte bleiben normal. Windows ergänzt nur im
CSV-Aufgabenzweig die bereits von Linux verstandenen Abschlusswörter
COMPLETED/COMPLETE/ABGESCHLOSSEN/FERTIG. Das allgemeine Ja/Nein-Prädikat anderer
Datenarten, Datumsleser, nativer OR6-Reader und Synchronisationsentscheidungen
bleiben im Patch unberührt.

## Tatsächlich ausgeführte Prüfungen

`contracts/lotus-csv-task-values.json` enthält 27 gemeinsame, rein synthetische
Sollfälle: 15 Prioritätswerte und zwölf Abschlusswerte. Die bekannten deutschen
Prioritäten kommen auch im vorhandenen öffentlichen Generator
`magnolie-organizer/pruefungen/erzeuge_lotus.py` vor.

Die neuen Tests rufen die tatsächlichen `import_rohdaten_lesen`/
`ExchangeCodec.ParseImport`-Einstiegspunkte auf. Sie prüfen Titel,
Schalttag-Fälligkeit, Priorität und Abschluss, erneutes Einlesen derselben CSV
und drei VTODO-Ausgabe-/Einlesezyklen. Der Python-Writer darf sein Eingabeobjekt
nicht ändern. Unbekannte Prioritäten und nicht abgeschlossene Statuswörter
werden ausdrücklich kontrolliert.

| Prüfung | Vorher | Nachher |
| --- | --- | --- |
| Neue Python-Vektoren | 6 fehlgeschlagen, 21 bestanden | 27 bestanden |
| Python mit bestehenden OR6-Status-/Einzelaufgabenfällen | — | 35/35 bestanden |
| Neue C#-Gruppe, alle 27 Vektoren | 0/1 Gruppen | 1/1 Gruppen |
| Bestehende C#-OR6-extension-Gruppe | — | 1/1 Gruppen |
| Bestehender Exchange-Gate mit expliziter Hostzone | 1/1 Gruppen auf Basis-DLL | 1/1 Gruppen auf finalem CSV-Stand |

Die Logs liegen jeweils hier: `python-before.log`, `python-after.log`,
`windows-before.log`, `windows-after.log`, `windows-existing-or6.log`.

## Aufgeklärte Testumgebung und Grenzen

**Korrigierter Nachweis: Der bestehende große Windows-Test
`ICS / VCF / LDIF / Claws / Lotus / Thunderbird` besteht sowohl auf der vor dem
Produktfix gebauten Basis-DLL als auch auf dem finalen CSV-Stand, jeweils 1/1
Gruppe.** Der anfänglich rote Lauf war eine Fehlkonfiguration der isolierten
Testumgebung, kein offener Produkt- oder Fixturebefund.

Ursache: Für zusätzliche Zeitzonenaliase hatte der Agent `TZDIR` auf den
vorhandenen Python-tzdata-Bestand gesetzt, aber `TZ` nicht mitgesetzt. Dadurch
lieferte .NET `TimeZoneInfo.Local.Id == "Local"` statt der ohne diese
Überschreibung tatsächlich erkannten Hostzone `Europe/Berlin`.
`CalendarRecurrence.Zone("system")` konnte diesen Namen nicht in seinen
gebundenen normativen Regeln auflösen; beide ICS-Importer verwendeten den
vorhandenen unresolved/read-only-Zweig. Die danach nicht materialisierte
`notiz` verursachte die NullReferenceException im Teilausdruck für `14:30`,
Zeile 615. Derselbe Prozess mit `TZ=Europe/Berlin` plus `TZDIR` erkennt die
Zone und besteht sämtliche Teilausdrücke. Ohne beide Overrides ist die
gezielte Schadstoffkontrolle ebenfalls korrekt.

Fixturemutation, veränderter Loaderinhalt und unterschiedliche Kulturen wurden
durch eine eigenständige Probe mit unveränderter Basis-DLL ausgeschlossen:
dieselben Fixture-/DLL-Hashes, identischer Payload vor/nach dem zweiten
Importaufruf und identische Kultur. Die ursprünglichen roten Logs
`windows-existing-exchange-baseline.log` und `windows-existing-exchange.log`
bleiben als Verlauf erhalten. Die vollständige Ursachenprobe sowie die beiden
grünen Gate-Logs stehen unter `../exchange-diagnosis/`; siehe dort `REPORT.md`.
Für diese Diagnose wurden keine Produkt- oder Testquelldateien geändert und
kein Produktissue angelegt.

Die C#-Produktionsquellen wurden mit .NET 8 auf dem Linux-Host kompiliert und
ausgeführt; dies ist keine native Windows-, GUI-, Benutzerprofil- oder
Paketabnahme. Es wurden keine echten Konten oder fremden Dateien verändert.
Der bestehende Quellarchivsammler in `build/Release.Common.ps1` nimmt neue
JSON-Verträge automatisch auf. `TestSource.Root` findet den Vertrag sowohl im
Monorepo als auch unter `contracts` eines eigenständigen Windows-Quellarchivs.

## Reproduktion des Endstands

Aus dem Repository:

```sh
env PYTHONPATH=$REVIEW_TOOLS/pydeps /usr/bin/python3 -m pytest -q magnolie-organizer/pruefungen/test_lotus_csv_task_values.py magnolie-organizer/pruefungen/test_or6_task_status.py magnolie-organizer/pruefungen/test_or6_single_task_dates.py
```

Aus `magnolie-organizer-windows` mit dem vorhandenen .NET SDK und NuGet-Cache:

```sh
env DOTNET_CLI_HOME=$REVIEW_TOOLS/dotnet-home NUGET_PACKAGES=$HOST_USER/.nuget/packages $REVIEW_TOOLS/dotnet/dotnet run --project tests/CoreTests.csproj --no-restore -- 'Lotus CSV tasks'
env DOTNET_CLI_HOME=$REVIEW_TOOLS/dotnet-home NUGET_PACKAGES=$HOST_USER/.nuget/packages $REVIEW_TOOLS/dotnet/dotnet run --project tests/CoreTests.csproj --no-build --no-restore -- 'OR6 extension'
```

Für einen erneuten Vorhernachweis nur die neuen Tests, den neuen Vertrag und
die eine Testregistrierung in einen isolierten Checkout der genannten Basis
übernehmen; Produktdateien dort auf der Basis belassen. Genau diese Reihenfolge
wurde für die gespeicherten roten Vorherlogs eingehalten.
