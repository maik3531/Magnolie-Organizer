# #842: Beschädigtes UTF-16 vor dem Windows-Import abweisen

## Befund und Korrektur

Der tatsächliche Windows-Dateieinstieg `ExchangeCodec.ParseImport` akzeptierte
UTF-16LE/BE mit BOM auch bei ungültigen Codeeinheiten. Die Standarddecoder
ersetzten beschädigte Zeichen still durch U+FFFD. In zwölf synthetischen
Datei-/ZIP-Fällen wurden so Kontaktname oder Termintitel als `Mü�ller`
zurückgegeben. Derselbe Linux-Dateieinstieg wies die beschädigten Bytes ab.

Die Korrektur verwendet ausschließlich in den beiden durch BOM ausgewiesenen
UTF-16-Zweigen einen Decoder, der ungültige Bytes zurückweist. Der vorhandene
lokalisierte Text `The content is unreadable.` wird als `InvalidDataException`
weitergegeben; die zugrunde liegende `DecoderFallbackException` bleibt erhalten.
Der Importfehlerweg gibt dann keinen Importdatensatz an die Oberfläche zurück.

UTF-8, der bestehende Windows-1252-Rückfall und die vorgeschaltete Erkennung von
OR6-Dateien werden nicht verändert. Ein tatsächlich korrekt kodiertes U+FFFD
wird weiterhin importiert. Es wird nicht nach Ersatzzeichen im fertigen Text
gesucht: Das würde gültige Benutzerdaten ablehnen und die eigentliche
Kodierungsursache nicht zuverlässig erkennen.

## Geprüfter Quellstand

- Basis: `0cdd6f992e094cd724203713da3bf145c36958fc`.
- Quellcommit: `565d432b78e5c3e8b9556b1616b116389e6fbef3`.
- Ergebnisbaum: `a919b7fd9a2f0617906098638785dcb12a136353`.
- Produktänderung: `magnolie-organizer-windows/ExchangeCodec.cs`.
- Regression im vorhandenen CoreTests-Lauf: `UnicodeImportTests.cs` und dessen Registrierung in `tests/Program.cs`.

`842-malformed-utf16.patch` enthält die vollständige Änderung gegen die genannte
Basis. Der SHA-256 und die Quellenbindungen stehen in `manifest.json`.
Der übergeordnete Review liefert zusätzlich eine geordnete Gesamtserie und
einen Gesamtpatch; diese sind alternative Wege zur zusammenhängenden Einpflege.

## Nachweise

| Prüfung | Ergebnis |
|---|---|
| Tatsächlicher unveränderter Byte-Einstieg, beide UTF-16-Reihenfolgen, CSV/vCard/ICS, Datei und ZIP | 12 unerwartet erfolgreiche Importe mit verändertem Inhalt; dieselben Linux-Bytes abgewiesen |
| Neue CoreTests-Gruppe gegen unveränderte Produktquelle | Erwarteter Fehler: `Malformed UTF-16 was accepted: contacts.csv` |
| Dieselbe Gruppe nach Korrektur | 148 Datei-, ZIP- und Müllkalenderfälle bestanden |
| Bestehende Gruppe ICS/VCF/LDIF/Claws/Lotus/Thunderbird | Bestanden |
| Bestehende Gruppe Importdateien, Quellenbindung und Archivgrenzen | Bestanden |
| Bestehende Aufgaben-CSV-/VTODO-Gruppe | Bestanden |
| Unabhängige Prüfung des tatsächlich kompilierten Decoders | 28 zusätzliche Randfälle bestanden |

Die 148 Fälle prüfen die tatsächlichen `ParseImport`- und
`ParseWasteImport`-Einstiege. Enthalten sind beide CSV-Auswahlen, vCard, ICS,
LDIF und Claws-XML. Hohe und niedrige ungepaarte Surrogate sowie eine ungerade
Bytezahl werden in beiden Reihenfolgen abgewiesen. Bei den defekten ZIP-Fällen
steht vor dem beschädigten Eintrag ein erfolgreich lesbarer Eintrag; trotzdem
darf kein Teilimport als erfolgreich zurückgegeben werden.

Die positiven Kontrollen enthalten UTF-8 mit/ohne BOM, beide UTF-16-Reihenfolgen,
Windows-1252, Umlaute, eine ZWJ-Sequenz mit Nicht-BMP-Zeichen und ein gültiges
U+FFFD. Der unabhängige Decoderlauf ergänzt BOM ohne Inhalt, den kleinsten und
größten Nicht-BMP-Codepunkt, eine innere BOM, vertauschte Surrogate und die
unveränderten Rückfallpfade für einzelne FF/FE-Bytes sowie ungültiges UTF-8.

## Wiederholung

Verwendet wurden das bestehende CoreTests-Projekt, dessen gesperrte
Abhängigkeiten und .NET SDK 8.0.408 entsprechend dem Repositoryworkflow.
`DOTNET` bezeichnet das vorhandene SDK; `REVIEW_CHECKOUT` den korrigierten
Quellcheckout. Im Arbeitsverzeichnis `magnolie-organizer-windows`:

```bash
"$DOTNET" restore tests/CoreTests.csproj --locked-mode
"$DOTNET" run --project tests/CoreTests.csproj --no-restore -- 'UTF-16 import'
MAGNOLIE_TEST_SOURCE_ROOT="$REVIEW_CHECKOUT" TZ=Europe/Berlin \
  "$DOTNET" tests/bin/Debug/net8.0/CoreTests.dll \
  'ICS / VCF / LDIF / Claws / Lotus / Thunderbird'
MAGNOLIE_TEST_SOURCE_ROOT="$REVIEW_CHECKOUT" \
  "$DOTNET" tests/bin/Debug/net8.0/CoreTests.dll 'Import file / native readers'
MAGNOLIE_TEST_SOURCE_ROOT="$REVIEW_CHECKOUT" \
  "$DOTNET" tests/bin/Debug/net8.0/CoreTests.dll 'Lotus task CSV'
```

Für den roten Vergleich dieselben neuen Testdateien gegen die unveränderte
Produktdatei der Basis bauen. Der Test muss dort am ersten defekten
Kontakt-CSV-Fall scheitern. Die Decoder-Diagnose unter
`independent-decoder-review` lädt das tatsächlich gebaute CoreTests-Assembly
und ruft dessen interne Funktion per Reflection auf; sie enthält keinen
nachgebildeten Decoder.

## Grenzen

Alle verwendeten Kontakte und Termine sind synthetisch. Die C#-Funktionen
wurden auf Linux unter .NET 8 ausgeführt; dies ist keine native Windows-GUI-,
DPAPI-, Installer- oder Paketabnahme. Es werden keine Produktquellen nach
`main` übernommen und keine Pakete veröffentlicht. #817 bleibt als bereits
behobener anderer Fehler geschlossen: Dort wurde gültiges UTF-16 unter Linux
zu früh als Binärdatei abgewiesen.
