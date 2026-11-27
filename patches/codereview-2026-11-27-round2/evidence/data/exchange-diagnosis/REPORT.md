# Exchange-Gate: bestätigte Ursache in der isolierten Testumgebung

## Ergebnis

Der vorhandene Gate `ICS / VCF / LDIF / Claws / Lotus / Thunderbird` besteht
**auf der unveränderten Basis-DLL und dem finalen CSV-Stand jeweils 1/1 Gruppe**,
wenn neben dem vorhandenen `TZDIR` die tatsächliche unüberschriebene Hostzone
explizit als `TZ=Europe/Berlin` gesetzt wird.

Es handelt sich um eine durch den Agenten verursachte Testumgebungs-
Fehlkonfiguration. Kein Produkt- oder Fixturefix und kein neues Issue sind
dafür erforderlich. Die früheren roten Gate-Logs sind durch diese Diagnose
eingeordnet; sie belegen keinen verbleibenden Produktfehler.

## Drei gezielte Prozesse mit identischen Eingaben

Der kleine Diagnosehost referenziert ausschließlich die schon vor den
CSV-Produktänderungen gebaute `CoreTests.dll` aus `../native-probe/`. Er ruft
die tatsächlichen Methoden `ParseWasteImport` und `ParseImport` auf und wertet
jeden Teilausdruck der betroffenen Assertion getrennt aus. Es wird keine
kopierte Parserimplementierung verwendet und kein gemeinsames `obj`-Verzeichnis
des Integrationszweigs gebaut.

| Umgebung | .NET Local.Id | Normative Systemzone | Schadstoff-Notizen | Assertion |
| --- | --- | --- | --- | --- |
| Weder TZ noch TZDIR überschrieben | Europe/Berlin | Europe/Berlin | beide vorhanden | alle Teilausdrücke wahr |
| Nur TZDIR auf Python-tzdata gesetzt | Local | TimeZoneNotFoundException | `notiz` nicht materialisiert; read-only/unresolved | NullReference beim Zugriff auf erste Notiz |
| Derselbe TZDIR plus TZ=Europe/Berlin | Europe/Berlin | Europe/Berlin | beide vorhanden | alle Teilausdrücke wahr |

Die vollständigen Beobachtungen stehen in `default-environment.json`,
`tzdir-environment.json` und `explicit-zone-environment.json`. Alle drei
enthalten den Fixturepfad, Fixture-Hash, Basis-DLL-Pfad und DLL-Hash sowie
lokale Zone, Kultur, getrennte Teilausdrücke und beide tatsächlichen
Importergebnisse.

Der erste Payload bleibt jeweils nach dem zweiten `ParseWasteImport`-Aufruf
unverändert. Beide Dateinamen liefern dieselbe Quellidentität. Die zwei
Schadstoffeinträge werden in jedem Prozess erkannt und ihre leeren
Ganztags-Uhrzeiten sind korrekt. Der exakt scheiternde Teilausdruck ist
`hazardous[0]["notiz"]!.ToString().Contains("14:30", ...)`.

## Ursachenkette

Der anfängliche Testaufruf setzte `TZDIR` auf
`$PRIMARY_RUNTIME/dependencies/python/lib/python3.12/site-packages/tzdata/zoneinfo`,
um dort vorhandene Aliasdateien verfügbar zu machen. Ohne explizites `TZ`
änderte dies im beobachteten .NET-Prozess die Kennung der lokalen Zone von
`Europe/Berlin` zu `Local`.

`CalendarRecurrence.Zone("system")` löst `TimeZoneInfo.Local.Id` ausschließlich
gegen den gebundenen normativen Zeitzonenbestand auf. `Local` ist darin keine
gültige Kennung. Der dadurch ausgelöste `TimeZoneNotFoundException` führt in
`ExchangeCodec.ParseIcs` in den vorhandenen unresolved/read-only-Zweig. Das
erklärt sowohl das fehlende materialisierte Notizfeld als auch die ansonsten
intakte Anzahl/Datums-/Titelkontrolle. Beide Import-Einstiegspunkte verhalten
sich bei identischer Umgebung gleich; der zuvor korrekte direkte Import war
ohne den TZDIR-Override gelaufen.

## Abschließender vorhandener Gate

Mit exakt demselben Fixture und der korrigierten Umgebung wurden die
ursprüngliche Basis-DLL und der finale CSV-Stand separat geprüft:

- `baseline-gate-correct-environment.log`: **1/1 Gruppen bestanden**.
- `current-gate-correct-environment.log`: **1/1 Gruppen bestanden**.

Verwendete Umgebung: `TZ=Europe/Berlin`, obiger `TZDIR` und
`MAGNOLIE_TEST_SOURCE_ROOT=$REVIEW_WORKSPACE/round2-data`.
Es wurden nur der kleine Diagnosehost und der einzelne betroffene bestehende
Gate ausgeführt, keine breite Testsuite.

## Reproduktion

Der Diagnosehost besteht aus `Probe.csproj` und `Program.cs` in diesem Ordner.
Er baut mit dem vorhandenen .NET 8 SDK; `build.log` enthält null Warnungen und
null Fehler. Ohne zusätzliche Packages referenziert er die Basis-DLL direkt.

Beispiel der korrigierten Einzelprobe, aus diesem Ordner:

```sh
env TZ=Europe/Berlin TZDIR=$PRIMARY_RUNTIME/dependencies/python/lib/python3.12/site-packages/tzdata/zoneinfo $REVIEW_TOOLS/dotnet/dotnet bin/Debug/net8.0/NativeImportProbe.dll $REVIEW_WORKSPACE/round2-data/contracts/waste-calendar-v1.json
```

Für die fehlkonfigurierte Gegenprobe `TZ` entfernen, `TZDIR` gleich lassen.
Für den unveränderten Hostprozess beide Variablen entfernen. Der gespeicherte
Basis-Gate wird aus `magnolie-organizer-windows` aufgerufen:

```sh
env TZ=Europe/Berlin TZDIR=$PRIMARY_RUNTIME/dependencies/python/lib/python3.12/site-packages/tzdata/zoneinfo MAGNOLIE_TEST_SOURCE_ROOT=$REVIEW_WORKSPACE/round2-data $REVIEW_TOOLS/dotnet/dotnet $REVIEW_WORKSPACE/round2-evidence/data/native-probe/bin/Debug/net8.0/CoreTests.dll 'ICS / VCF / LDIF / Claws / Lotus / Thunderbird'
```

Für den finalen Quellstand stattdessen die bereits gebaute
`tests/bin/Debug/net8.0/CoreTests.dll` aus demselben Windows-Arbeitsordner
verwenden. Der Quellworktree bleibt durch diese Diagnose unverändert.
