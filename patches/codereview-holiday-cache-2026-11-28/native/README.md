# #855 – native Abrufbereiche für den Feiertags-/Feriencache

Geprüfte Produktbasis: `1749c92eb42801c38eaba31b272d8c0e27be9164`.
Dieses Teilpaket prüft die tatsächlichen Linux-/Windows-Providerfunktionen;
die gemeinsame Cacheanwendung und Mac-/Tablet-Parität werden separat belegt.

## Änderung

Die native Antwort enthält zusätzlich `abrufbereiche`, je vollständig und
gültig verarbeitetem Endpoint-/Jahr-/Regionsabruf einen Datensatz mit
`country`, `region`, `art`, `von`, `bis`. Es werden keine persistenten Datenfelder
ergänzt. Der Jahresbereich ist inklusive 1. Januar bis 31. Dezember.

Ein erfolgreiches leeres Array bestätigt einen leeren Bereich. Ein wegen
Opt-out oder fehlender erforderlicher Region nicht ausgeführter Schulferienabruf,
ein unterdrückter Schulferien-HTTP-Fehler oder eine unvollständig ausgewertete
Antwort bestätigt keinen solchen Bereich. Vorhandene tolerante Parserauswertung
gültiger Zeilen bleibt erhalten; diese Zeilen erteilen keine Löschbefugnis.

Ungültige Antwortform, übersprungene Zeilen, korrigierte Enddaten sowie defekte
Namens-/Regions-/Nationwide-Felder verhindern die Bereichsbestätigung.
Die offiziell erforderlichen Felder `endDate` und `nationwide` müssen für eine
Bestätigung vorhanden und gültig sein. Ihr bisheriger Lesefallback allein genügt
nicht. Alle Zeilen müssen das angefragte Jahr überlappen und geografisch zur
Anfrage passen. Eltern-/Kindregionen bleiben zulässig; unbekannte Geografie einer
nichtlandesweiten Zeile reicht bei einer ungefilterten Länderabfrage nicht aus.

Linux behält sein bisheriges Verhalten, Schulferien-RuntimeError zu überspringen.
Windows behält seinen Schulferien-HttpRequestException-Fallback und den vollständigen
Fehlercallback bei ungültigem JSON. Nur tatsächlicher Erfolg erhält eine Deckung.

## Tatsächlich ausgeführt

| Prüfprogramm | Unveränderte Basis | Kandidat |
|---|---:|---:|
| Python, 26 Testmethoden | 14 bestanden, 12 Methoden fehlgeschlagen (15 Assertions einschließlich Unterfälle) | 26 bestanden |
| C#, identischer 26-Fälle-Host | 15 bestanden, 11 fehlgeschlagen | 26 bestanden |

Die roten Prüfungen kennzeichnen die bisher fehlende Herkunft/Vollständigkeit der
Antwort. Sie sind keine 23 eigenständigen Produktfehler. Den tatsächlichen Verlust
gespeicherter Daten belegt die gesonderte Frontendregression.

Python lädt per AST die unveränderten Produktfunktionen einschließlich Datumprüfung
und Namensnormalisierung sowie den tatsächlichen Regionsnormalisierer. HTTP und
Gettext sind kontrollierte Doubles; die GTK-Anwendung wird nicht gestartet.

C# kompiliert die unveränderten aktuellen Bridge-Methoden `FetchHolidaysAsync`,
`AddHolidayEntriesAsync`, `Text`, `Boolean`, Größenkonstante und Regionsrecord sowie
den tatsächlichen Parser und Setupnormalisierer. Nur HTTP, Callback und Gettext
sind Doubles. SDK **8.0.428**, Laufzeit **8.0.34**, beide endgültigen Builds mit
**0 Warnungen / 0 Fehlern**, ausgeführt auf Linux. Der erste Hostbau scheiterte
an einem fehlenden `#nullable enable` im generierten `.g.cs`-Wrapper; die Logs
sind erhalten. Nach Wrapperkorrektur wurden Basis und Kandidat tatsächlich gebaut
und ausgeführt. Die Produktmethoden wurden dafür nicht umgeschrieben.

Die SDK-Datei wurde einmalig von der offiziellen Downloadadresse in Scratch
bereitgestellt und gegen den SHA-512 aus den offiziellen .NET-8-Releasemetadaten
verifiziert. Keine globale Installation, kein Produkt-/Dienststart und keine
Windows-GUI-, Live-Provider-, Geräte- oder Paketabnahme.

## Wiederholung

```sh
python magnolie-organizer/pruefungen/test_holiday_fetch_coverage.py
python magnolie-organizer-windows/tests/holiday-fetch-coverage.py \
  --dotnet /path/to/dotnet \
  --build-dir /tmp/magnolie-holiday-coverage
```

Python akzeptiert `MAGNOLIE_HOLIDAY_SOURCE` für eine unveränderte Basiskopie der
Anwendungsdatei. Der C#-Host akzeptiert `--source-root` für einen Basischeckout.
Für beide Vergleichsseiten wurde jeweils dieselbe aktuelle Testdatei verwendet.
Die SHA-256-Bindungen stehen in `native-receipt.json` und den Lauf-Bindungsdateien.

## Primärquellen des Providervertrags

- [Offizieller HolidayResponse-DTO: erforderliche Felder](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Dtos/Responses/HolidayResponse.cs)
- [Offizieller Controller: inklusive Überlappung sowie Eltern-/Kindregionen](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Controllers/HolidaysController.cs)

Ein jahresübergreifender Zeitraum wird vom Provider vollständig zurückgegeben,
wenn er das Abfragejahr berührt. Die geprüfte Korrektur verändert daher weder
Enddaten noch Providerzeiträume und behauptet keinen eigenständigen Fehler dieser
Provider-Intervallregel. Neue Datenquellen, Länder, Feriengruppen und Festtagsmotive
bleiben die eigenständigen Erweiterungen #853/#854.
