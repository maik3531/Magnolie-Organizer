# #566: abgegrenzter CSV-Kontaktbefund

## Ergebnis und Quellstand

- Gesamte Prüfbasis: `1543858e251d7e29ebeafb67d2605991c1d442d5`.
- Direkter Vorgänger: `c68c17041831650a3378cc2a8c60de0f13287b32` (#837).
- Commit: `73af57871683d750a74fcd449cd5a5270109ab70`, `Refs #566: Preserve CSV contact addresses within their source roles`.
- Patch: `566-csv-contact-fields.patch`, nach dem #837-Patch anzuwenden.
- SHA256: `81c13cee283ce1852591507d130998275265edd8d50e1c7b7fb32110374c44a1`.

Dies behebt den nun synthetisch belegten CSV-Teilfall des bestehenden offenen
Issues #566. Die Ursache des historischen privaten OR6-/UI-Konfliktberichts
ist damit ausdrücklich nicht bewiesen oder insgesamt behoben. Die Zuordnung und die bestätigte Linux-Erweiterung wurden vor Produktänderungen im bestehenden Issue dokumentiert.

## Tatsächliche Datenfehler

`contacts-home-work.csv` und `before.json` zeigen: Linux las im ursprünglichen
positiven Fall beide Anschriften mit HOME/WORK. Windows behielt nur die erste
Anschrift, verlor die zweite vollständig und entfernte die HOME/WORK-Rollen
beider Telefonnummern. Der Import meldete trotzdem keinen ausgelassenen
Eintrag und keinen Warnbericht. Die Ursache war die Erstellung genau eines
Anschriftenobjekts aus jeweils dem ersten Feldtreffer und eine auf CELL/FAX/
VOICE reduzierte Telefonabbildung im CSV-Zweig von `ExchangeCodec`.

Weitere unabhängige Layoutkontrollen belegten auch einen Linux-Fehler:

- Eine reine Geschäftsanschrift erhielt zusätzlich die erfundene Rolle HOME.
- Bei gemischter Spaltenreihenfolge entstand neben den wirklichen Anschriften
  zusätzlich eine Privatstraße mit dem Geschäftsort.

Belege: `linux-layout-before.json`, `work-only.csv`, `interleaved.csv`.
Linux rief auf den bereits aus beliebigen ersten Spalten gefüllten
Skalarfeldern `_anschrift_liste` auf. Dieser alte Kompatibilitätspfad ergänzt
HOME. Erst danach wurden die wirklichen Rollenanschriften angefügt.

## Enger Fix

Beide CSV-Reader sammeln allgemeine, HOME- und WORK-Spalten zuerst als getrennte
Anschriften. Die bisherigen Skalarfelder `strasse`, `plz`, `ort` stammen danach
zusammen aus der ersten tatsächlich vorhandenen Anschrift. Allgemeine Spalten
bekommen keine erfundene Rolle, leere Gruppen erzeugen keine leeren Anschriften,
fehlende Felder einer Rolle werden nicht aus einer anderen Rolle gefüllt.

Windows verwendet für Telefonnummern dieselben vorhandenen bekannten
CSV-Spaltenmuster wie Linux, einschließlich der festen Rollen HOME/WORK und der
Gerätetypen VOICE/CELL/FAX/PAGER. Andere Kontaktimporter, Kontaktzusammenführung,
Konfliktentscheidungen, Anbieterrechte, UID-/Quellenbindungen und die vCard-
Writer selbst sind nicht Teil der Produktänderung.

Die Änderungen in Linux betreffen nur `_lotus_kontakte`; Windows ändert nur
den Kontaktzweig von `ParseLotusCsv` und dessen neue private CSV-Feldhelfer.
Keine neue Oberfläche oder Datenmodelländerung ist erforderlich.

## Tatsächlich ausgeführte Prüfungen

Der gemeinsame Vertrag `contracts/lotus-csv-contact-fields.json` enthält acht
vollständig synthetische Sollkontakte:

1. Zwei vollständige HOME-/WORK-Anschriften und entsprechende Telefonnummern.
2. Reine Geschäftsanschrift ohne hinzuerfundene HOME-Rolle.
3. Ineinander verschachtelte Spalten verschiedener Rollen, ohne Mischanschrift.
4. Allgemeine plus private plus geschäftliche Anschrift und fünf Telefontypen.
5. Unvollständige Geschäftsanschrift, die keine privaten Felder übernehmen darf.
6. Leere Rollenfelder, die keine leeren Anschriften erzeugen dürfen.
7. Unbeschriftete allgemeine Anschrift ohne erfundene HOME-/WORK-Rolle.
8. Englische HOME-/WORK-Spalten.

Beide Tests rufen echte Import-Einstiegspunkte auf, prüfen sowohl den Lotus- als
auch den Kontaktdatei-Import einer CSV und kontrollieren anschließend dreifach
vCard-Ausgabe und erneutes Einlesen. Kontrolliert werden alle Telefonnummern,
Rollentypen und vollständigen Anschriften sowie die Konsistenz der alten
Skalarfelder. Python prüft zusätzlich unveränderte Writer-Eingaben. Windows
verwendet für den Export den tatsächlichen `RecordExportFile.Convert`-Pfad.

| Prüfung | Vorher | Nachher |
| --- | --- | --- |
| Acht Python-Kontaktvektoren | 6 fehlgeschlagen, 2 bestanden | 8 bestanden |
| C#-Kontaktgruppe, alle acht Vektoren | 0/1 Gruppen | 1/1 Gruppen |
| Mit den 27 #837-Aufgabenvektoren | — | Python 35/35; C# 2/2 Gruppen |

Logs: `python-before.log`, `windows-before.log`, `python-after.log`,
`windows-after.log`. `git diff --check` bestand; der Arbeitszweig ist nach dem
Commit sauber.

## Grenzen und Quellarchiv

Die C#-Prüfungen kompilieren und führen die tatsächlichen Windows-
Produktionsquellen mit .NET 8 auf dem Linux-Host aus. Es gab keine native
Windows-, GUI-, Profil-, Provider- oder Paketabnahme. Keine privaten Originale
wurden verwendet. Der anfänglich rote große Exchange-Gate ist inzwischen als
Fehlkonfiguration der isolierten Zeitzonenumgebung aufgeklärt: explizites
`TZ=Europe/Berlin` zusammen mit dem vorhandenen `TZDIR` lässt sowohl die
unveränderte Basis-DLL als auch den finalen CSV-Stand bestehen, jeweils 1/1
Gruppe. Die genaue Ursache, gezielten Einzelproben und korrigierten Logs stehen
in `../exchange-diagnosis/REPORT.md`. Dafür wurde kein Produktfix vorgenommen.

Das vorhandene `Get-SourceContractFiles` in
`magnolie-organizer-windows/build/Release.Common.ps1` sammelt neue geprüfte
JSON-Verträge automatisch. Der neue Test behält den vorhandenen
`TestSource.Root("contracts/...")`-Suchweg bei; ein Monorepo außerhalb des
eigenständigen Quellarchivs wird nicht vorausgesetzt. Ein neues Releasearchiv
wurde in dieser Runde nicht gebaut.

## Reproduktion

Aus dem Repository:

```sh
env PYTHONPATH=$REVIEW_TOOLS/pydeps /usr/bin/python3 -m pytest -q magnolie-organizer/pruefungen/test_lotus_csv_contact_fields.py magnolie-organizer/pruefungen/test_lotus_csv_task_values.py
```

Aus `magnolie-organizer-windows`:

```sh
env DOTNET_CLI_HOME=$REVIEW_TOOLS/dotnet-home NUGET_PACKAGES=$HOST_USER/.nuget/packages $REVIEW_TOOLS/dotnet/dotnet run --project tests/CoreTests.csproj --no-restore -- 'Lotus CSV'
```

Die roten Vorherläufe erfolgten mit den neuen Tests/Verträgen vor jeder
Kontaktproduktänderung. Zur Wiederholung diese Testdateien und die eine
Testregistrierung in einen isolierten Checkout des direkten Vorgängers
übernehmen und die Produktdateien dort unverändert belassen.
