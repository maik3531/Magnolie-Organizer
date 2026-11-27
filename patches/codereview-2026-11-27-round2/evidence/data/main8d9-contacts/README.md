# #566 – geprüften CSV-Kontaktfix an den fortgeschriebenen Main anpassen

## Anwendungsreihenfolge und Quellstand

1. Ausgangsbasis: `8d9aec671a4c63f999ed7fbe74f8752af6978250`.
2. Zuerst [den H/N-Nachtrag zu #837](../main8d9-hn/837-main8d9-hn.patch)
   anwenden: Commit `14bc2fa1330037120f98b6dc31c76f5690a29eb6`.
3. Danach [566-after-837-main8d9.patch](566-after-837-main8d9.patch)
   anwenden: Commit `e9742c759be41939e2905d6a59a1004d4a7a7bd2`,
   Quellbaum `83d110de391fb62de52649118483775658ed2d8e`.

Der direkte Elternstand dieses vollständigen #566-Ergänzungspatches ist
`14bc2fa1330037120f98b6dc31c76f5690a29eb6`. Er ersetzt bei dieser Reihenfolge
den historischen #566-Einzelpatch; beide Kontaktpatches werden nicht addiert.
Die bereits übergebene H/N-Lieferung ist unverändert.

## Ausschließlich bestehende Konflikte angepasst

Der bereits geprüfte Kontaktcommit
`73af57871683d750a74fcd449cd5a5270109ab70` wurde per `git cherry-pick --no-commit`
mit Dreiwegeabgleich übernommen. [three-way.log](three-way.log) dokumentiert
die Konflikte in `ExchangeCodec.cs`, `Program.cs` und `ARBEITSSTAND.md`.

Die Auflösung übernimmt die Kontaktfunktionen und ergänzt genau deren
Testregistrierung. Die aktuelle Aufgabenlogik mit ihren Spaltenaliasen,
Abschlusswörtern, H/N-Werten und der bestehenden `LotusTaskCsvTests`-Registrierung
bleibt erhalten. Der Arbeitsstand verwendet die aktuellen 14 Aufgabenzeilen;
die historischen 27 Aufgabenfälle und der später geklärte Exchange-Hinweis
werden nicht erneut eingebaut.

[source-comparison.json](source-comparison.json) belegt zwölf gezielte
Bytevergleiche: Kontaktfunktionen, Kontaktvertrag und beide Kontakttests stimmen
mit dem historischen Fix überein; Aufgabenfunktionen, Spaltenaliaslisten,
Aufgabenvertrag und bisherige Testregistrierungen stimmen mit dem direkten
Elternstand überein. Es gibt keinen neuen Funktionsumfang.

## Gemeinsame gezielte Prüfung

| Prüfung | Ergebnis |
|---|---|
| Python: aktuelle Aufgaben- und Kontaktregression zusammen | **11 bestanden**: drei Aufgabengruppen mit 14 Zeilen plus acht Kontaktfälle |
| C#: Filter `CSV`, beide tatsächlichen Quellgruppen | **2/2 bestanden**: dieselben 14 Aufgaben und acht Kontakte |
| Bau des C#-Quellhosts | **0 Warnungen, 0 Fehler** |
| `git diff --cached --check` | bestanden |

Die Aufgabenprüfung enthält den CSV-/VTODO-Rundlauf. Die Kontaktprüfung enthält
beide CSV-Importwege sowie drei vCard-Ausgabe-/Reimportzyklen mit expliziten
HOME-/WORK-Rollen und vollständigen, unvollständigen und verschachtelten
Anschriftsspalten. Dieser Integrationsnachweis wiederholt ausschließlich die
bestehenden relevanten Regressionen auf dem neuen kombinierten Quellstand;
er ist kein neuer Vorher-/Nachher-Produktbefund.

Aus dem Checkout wurden mit `TZ=UTC`, Python 3.13.5, .NET SDK 8.0.408 und den
vorhandenen Abhängigkeiten diese Befehle ausgeführt:

```sh
/usr/bin/python3 -m pytest -q magnolie-organizer/pruefungen/test_lotus_task_csv.py magnolie-organizer/pruefungen/test_lotus_csv_contact_fields.py
cd magnolie-organizer-windows
dotnet build tests/CoreTests.csproj --no-restore
dotnet tests/bin/Debug/net8.0/CoreTests.dll CSV
```

Die echten Ausgaben stehen in [python-combined.log](python-combined.log),
[csharp-combined.log](csharp-combined.log) und [build.log](build.log).
Der Patch wurde außerdem mit einem isolierten temporären Git-Index direkt
gegen seinen Elternstand auf Anwendbarkeit geprüft: [apply-check.log](apply-check.log).
[manifest.json](manifest.json) enthält die relativen Dateinamen, SHA-256 und
Bytegrößen unter `artifacts`.

## Grenze

Der Kontaktfix bleibt der bereits belegte CSV-Teilbefund in #566. Die Ursache
des historischen privaten OR6-/UI-Konflikts ist dadurch weiterhin nicht belegt
oder insgesamt behoben. Die Windows-Produktquellen wurden im Linux-.NET-
Quellhost geprüft; es gab keine native Windows-, GUI-, Provider- oder
Paketabnahme. Es gab keine Root-Quelländerung, GitHub-Mutation, neue Scope-Suche
oder Main-Integration. Der eigene Arbeitszweig ist nach dem Commit sauber.
