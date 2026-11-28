# #856 – Windows: österreichische Provider- und ISO-Codes verbinden

## Ergebnis

Der Windows-Teilpatch übersetzt die neun bereits angebotenen österreichischen
ISO-Bundeslandcodes vor dem HTTP-Aufruf in die von OpenHolidays verwendeten
Providerkennungen. Zurückgegebene bekannte Providerkennungen werden vor der
bestehenden ASCII- und Vollständigkeitsprüfung wieder in ISO-Codes normalisiert.
Einstellungen, Cache, Abfrage-Snapshot und `abrufbereiche` behalten damit das
vorhandene ISO-Format.

Die Zuordnung stammt aus dem tatsächlichen `/Subdivisions?countryIsoCode=AT`-
Nachweis der gemeinsamen #856-Prüfung vom 28.11.2026:

| ISO-Auswahl | Providerkennung |
| --- | --- |
| AT-1 | AT-BL |
| AT-2 | AT-KÄ |
| AT-3 | AT-NÖ |
| AT-4 | AT-OÖ |
| AT-5 | AT-SB |
| AT-6 | AT-SM |
| AT-7 | AT-TI |
| AT-8 | AT-VA |
| AT-9 | AT-WI |

Die URL-Kodierung erfolgt weiterhin mit `Uri.EscapeDataString`, nun auf der
richtigen Providerkennung. Die drei Umlaute werden in den Tests auch anhand
ihrer tatsächlichen UTF-8-Prozentkodierung geprüft.

Unbekannte österreichische Antwortcodes, auch syntaktisch zulässige
ASCII-Kindcodes wie `AT-2-UNKNOWN`, erteilen keine Vollständigkeits- oder
Löschbefugnis. Ein Gemisch aus bekannten und unbekannten Codes erhält ebenfalls
keine solche Befugnis. Bekannte ISO-Antwortcodes bleiben kompatibel. Die
vorhandene Anfragenprüfung weist unbekannte AT-Auswahlen schon vor HTTP ab.
Die Regeln für andere Länder bleiben erhalten.

## Tatsächlich ausgeführte Prüfung

Die echten Produktmethoden `FetchHolidaysAsync` und `AddHolidayEntriesAsync`
sowie die vollständige Datei `OpenHolidayData.cs` wurden mit dem vorhandenen
`holiday-fetch-coverage.py`-Host kompiliert und ausgeführt. HTTP, Callback und
Gettext sind kontrollierte Testgegenstellen; der Produktalgorithmus wurde
nicht nachgebaut.

| Stand | Ergebnis |
| --- | ---: |
| Unveränderter #855-Kandidat, gleiche erweiterte Prüffälle | **30/43 bestanden** |
| Derselbe Kandidat mit Windows-#856-Teilpatch | **43/43 bestanden** |

Die ursprünglichen 26 #855-Prüffälle bestanden in beiden Läufen unverändert.
Hinzu kamen neun einzelne Länder-Code-/URL-/Cache-/Coverage-Abläufe sowie
acht Fälle für alle Providercodes, ISO-Kompatibilität, unbekannte und gemischte
Antworten, ungültige Auswahl, DE/CH, Ländergrenzen und Sammelabruf aller
Bundesländer. Die 13 roten Anforderungen vor der Korrektur sind keine 13
unabhängigen Fehler.

Umgebung: .NET SDK **8.0.428**, Laufzeit **8.0.34**, Linux. Beide Builds
bestanden mit **0 Warnungen und 0 Fehlern**. Der C#-Testquelltext war vor und
nach der Produktänderung identisch.

## Quellen und Einzelpatch

`windows-provider-856.patch` ist ein Windows-Teilpatch **auf den bereits
veröffentlichten #855-Kandidaten**. Ausgangsbaum:
`f4f94a2c2cf73a064448d3208f31d471e150dbe4`.
Er ersetzt keinen Gesamtpatch und darf nicht ohne Basisabgleich direkt auf
einen unbekannten Produktstand angewandt werden.

Geänderte Dateien:

- `magnolie-organizer-windows/BridgeDispatcher.cs`
- `magnolie-organizer-windows/OpenHolidayData.cs`
- `magnolie-organizer-windows/tests/holiday-fetch-coverage.cs.txt`

Patchgröße: 16.422 Bytes; SHA-256:
`63b923f22215547b1eb292a8bc2852e466f00c1b82744496bb5492c3ad1a3e1a`.
Die Vorwärtsanwendung und Rücknahme wurden in einem separaten Git-Index
ausgeführt; die Rücknahme stellt exakt den angegebenen Ausgangsbaum her.

`receipt.json`, die Vorher-/Nachher-Quellbindungen, Buildprotokolle und
Laufprotokolle enthalten die genauen Bytes und Ergebnisse. Der außerhalb
dieses Teilpakets gesicherte Live-Unterregionsnachweis hat SHA-256
`7b209ec482d8426dcc8d3dd328d480ef0fd43b141a63f094928d3ee058aeff27`.

Wiederholung nach Anwendung des vollständigen #855-Patches und dieses
Windows-Teilpatches:

```sh
python magnolie-organizer-windows/tests/holiday-fetch-coverage.py \
  --dotnet /path/to/dotnet \
  --build-dir /path/to/isolated-holiday-coverage-build
```

Für die Vorher-Prüfung denselben erweiterten Testtreiber aufrufen und über
`--source-root` eine isolierte Kopie des unveränderten #855-Ergebnisbaums
angeben. So bleiben die Prüffälle identisch.

## Grenzen

Diese Teilprüfung ist ein tatsächlicher C#-Quelllauf unter Linux mit
kontrollierter HTTP-Gegenstelle. Sie ist keine native Windows-/WinForms-/
WebView2- oder Paketabnahme. Die Live-Providerabfragen und anderen Plattformen
werden im gemeinsamen #856-Bericht gesondert ausgewiesen. Hier wurden keine
Produktpakete gebaut, installiert oder veröffentlicht und kein Produktzweig
zusammengeführt.
