# OpenHolidays: Schulgruppen und mitgelieferte Verwaltungseinheiten

Unabhängige Quellenprüfung vom 28. November 2026 für die BE/NL-Arbeit aus
#854. Dieser Bericht enthält eigene Analyse und Quellenlinks; fremder
AGPL-Programmcode wird nicht übernommen. Die Rohdaten unterliegen der separat
zu dokumentierenden OpenHolidays-Datenlizenz ODbL-1.0.

## Bestätigter Fehler in der bisherigen Annahme

**Eine nichtleere `subdivisions`-Liste ist kein Nachweis, dass eine ausdrücklich
genannte Schulgruppe auf einzelne Gemeinden eingeschränkt wurde.** Die API
erzeugt solche Listen auch selbst aus der Gruppenzuordnung. Die bisherigen
Linux-, Swift- und Kotlin-Teilpatches verwerfen deshalb gültige niederländische
Antwortzeilen beim Abruf einer Schulgruppe. Die ausschließlich mit
gruppenreinen Beispielen geprüfte Annahme muss korrigiert werden.

Der erste Windows-Kandidat hatte dieselbe Regel übernommen. Seine Quellprüfung
allein hätte dieses Problem ebenfalls nicht ausgeschlossen; die aufgezeichneten
echten Anbieterantworten liefern die zusätzliche Gegenprobe.

## Primärquellen und Bedeutung

Maßgeblicher gelesener API-Quellstand:
`bd07111f622e80e95ef6cfd9bde3fe6e058d5336`.

| Quelle | Beobachtetes Verhalten | Folgerung |
| --- | --- | --- |
| [CsvHoliday.cs](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/cli/Imports/Models/CsvHoliday.cs) | Der Import liest direkte Verwaltungseinheiten und Gruppen getrennt. Fehlen Verwaltungseinheiten, ergänzt er sie aus den zugeordneten Gruppen. | Mitgelieferte Verwaltungseinheiten können abgeleitete Zusatzinformation sein. |
| [Holiday.cs](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/datalayer/Models/Holiday.cs) | Das interne Modell unterscheidet direkte Zuordnungen durch `HasSubdivisions` und `HasGroups`. | Die interne Datenquelle kennt eine genauere Unterscheidung als die öffentliche Antwort. |
| [HolidayResponse.cs](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Dtos/Responses/HolidayResponse.cs) | Die Antwort enthält Gruppen und Verwaltungseinheiten, aber nicht die beiden genannten Herkunftsmerkmale. | Aus bloßer Anwesenheit beider Listen lässt sich ihre Herkunft nicht allgemein bestimmen. |
| [HolidaysController.cs](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Controllers/HolidaysController.cs) | Der Schulferienabruf prüft `groupCode` gegen die Gruppenzuordnung. Ohne `subdivisionCode` wird die Antwort nicht zusätzlich auf eine Gemeinde gefiltert. Der Feiertagsabruf hat keinen Gruppenparameter. | Explizite gültige Gruppen sind für den Gruppenabruf die maßgebliche Anbieterzuordnung. Öffentliche Feiertage benötigen einen eigenen Anfrage- und Cachebereich. |
| [RegionalScope.cs](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/datalayer/Models/RegionalScope.cs) | Die Klassifikation unterscheidet national, regional und lokal. | Ein ausdrücklich lokaler Datensatz kann konservativ als lokal behandelt werden. `Regional` ersetzt jedoch nicht das fehlende Herkunftsmerkmal. |
| [HolidayTags.cs](https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/datalayer/Models/HolidayTags.cs) | `Exception` bezeichnet einen von einer Regel abweichenden Ferientermin; andere Tags bezeichnen Empfehlung, Vorläufigkeit oder Einmaligkeit. | Das Tag allein beweist keine Beschränkung auf einzelne Gemeinden. Es darf nicht ohne weiteren Beleg mit einer geografischen Einschränkung gleichgesetzt werden. |

Eine weitere Eigenheit des gelesenen Importers ist für Tests wichtig: Die
Ergänzung aus Gruppen erfolgt nur, solange noch keine Verwaltungseinheiten
vorhanden sind. Bei mehreren Gruppen kann die Antwort deshalb die
Verwaltungseinheiten der zuerst verarbeiteten Gruppe enthalten. Eine Forderung,
dass die Liste stets die vollständige Vereinigung aller Gruppen enthalten müsse,
wäre ebenfalls nicht durch diesen Anbieterstand gedeckt.

## Gegenprüfung anhand der niederländischen Datenquelle

Gelesener Datenstand:
`a42b397470b265d3f588fe4d8ec59db04e1e9678`.

Die offizielle Datei
[holidays.school.csv](https://github.com/openpotato/openholidaysapi.data/blob/a42b397470b265d3f588fe4d8ec59db04e1e9678/src/nl/holidays/holidays.school.csv)
enthält für die erfassten niederländischen Perioden eine `Groups`-Spalte und
**keine `Subdivisions`-Spalte**. Die IDs der 2026 überlappenden Antwortzeilen
entsprechen diesen Gruppenzeilen. Ihre Klassifikation ist `Regional`.
[groups.csv](https://github.com/openpotato/openholidaysapi.data/blob/a42b397470b265d3f588fe4d8ec59db04e1e9678/src/nl/groups.csv)
definiert die drei Identitäten `NL-NO`, `NL-MI` und `NL-ZU`.

Die lokalen Mitschnitte wurden in dieser unabhängigen Prüfung erneut als JSON
gelesen und strukturell ausgezählt; das ist **kein zusätzlicher Liveabruf**:

| Mitschnitt | Bytes | Zeilen | Mit Gruppen | Mit Verwaltungseinheiten | Gruppenbezogene Zeilen |
| --- | ---: | ---: | ---: | ---: | --- |
| `NL-SchoolHolidays.json` | 51.552 | 10 | 10 | 10 | Nord 6, Mitte 6, Süd 6 |
| `BE-SchoolHolidays.json` | 4.479 | 16 | 16 | 0 | Deutsch 4, Französisch 6, Niederländisch 6 |

Alle zehn niederländischen Zeilen tragen `regionalScope: Regional`, keine Tags
und jeweils 112, 126 oder 127 Verwaltungseinheiten. Die jeweiligen sechs
Gruppenzeilen schließen auch die Weihnachtsferien an beiden Jahresgrenzen ein.
Die Daten wurden nicht auf den angefragten Jahresbereich verkürzt.

SHA-256 der gelesenen Rohdateien:

- NL: `83b2b067dbb9556148f2ab60e2e91105bf83c6d3a7fce294443f45e0c6df1edd`
- BE: `c4f13dec2677986f9578e9ffc7d52a6c19a304f29b3f5b21703863b4831456f1`

Die ursprünglichen Anfrage-URLs, Abrufzeiten und HTTP-Metadaten gehören zu
`provider-capture/requests.json` und den zugehörigen Rohdateien. Der abschließende
Lieferbericht muss diese Dateien mit unveränderter Attribution zusammenführen.

## Abgeleitete Korrektur- und Prüfanforderungen

1. Gültige ausdrücklich genannte BE/NL-Gruppen dürfen bei einer Gruppenabfrage
   nicht allein wegen gleichzeitig vorhandener gültiger Verwaltungseinheiten
   verworfen oder durch diese ersetzt werden. Die Gruppenzuordnung wird aus der
   Antwort gelesen; sie wird niemals aus der Anfrage erfunden.
2. Fehlende, unbekannte, fremde, widersprüchliche oder beschädigte Gruppen dürfen
   keine scheinbar vollständige Cache-Ersetzung bestätigen. Beschädigte oder
   fremde zusätzliche Verwaltungseinheiten bleiben eine gesonderte
   Konsistenzverletzung; ihre Prüfung darf nicht wegen gültiger Gruppen entfallen.
3. Ausdrücklich lokale Datensätze dürfen konservativ im Gemeindebereich bleiben,
   ohne daraus vollständige Gruppenabdeckung abzuleiten. Das ist eine benannte
   Produktentscheidung; eine lückenlose Rekonstruktion der nicht übertragenen
   `HasSubdivisions`-Information wird damit nicht behauptet. Ein `Exception`-Tag
   allein reicht für diese Umdeutung nicht aus.
4. Landesweite öffentliche Feiertage müssen trotz ausgewählter Schulgruppe
   einmal pro Jahr ohne Gruppenparameter abgerufen werden. Ihre Zeilen und
   bestätigten Abrufbereiche behalten eine leere Region. Die spätere GUI-/MCP-
   Übernahme muss diesen separaten Bereich ausdrücklich akzeptieren.
5. Reale aufgezeichnete NL-/BE-Antworten müssen neben synthetischen Negativfällen
   durch die tatsächlichen Produktparser laufen. Die früheren Erwartungen, jede
   Kombination aus Gruppe und Verwaltungseinheit sei eine Gemeindeausnahme,
   sind kein gültiger Abnahmemaßstab.

Die API- und Datenquellen begründen diese Schlussfolgerungen. Sie beweisen keine
vollständige amtliche Kalenderabdeckung, keine native Benutzeroberflächenprüfung
und keine installierte Paketabnahme. Genau diese Grenzen bleiben bei der
Korrektur der bisherigen Teilpatches erhalten.
