# #864: Polnische Schulferien, Anbieter-Datenkorrektur als Teil von #860

**Kein Magnolie-Produktpatch.** Die Datei `openholidays-pl-864.patch` richtet sich ausschließlich an den externen OpenHolidays-Datenquellbaum auf `65673ec67926c7819deac742ed78ae548d83272c`. Nicht in Produkt-main anwenden. Die drei neuen IDs sind eindeutige Vorschlags-IDs; upstream kann sie bei Übernahme festlegen. Kein Upstream-Push, keine Produktfreischaltung.

## Quellen und Reproduktion

- [Anbieter-CSV](https://github.com/openpotato/openholidaysapi.data/blob/65673ec67926c7819deac742ed78ae548d83272c/src/pl/holidays/holidays.school.csv), Blob `5e100014d14874260146bcb3b439998254574b47`.
- [Regionsverzeichnis](https://github.com/openpotato/openholidaysapi.data/blob/65673ec67926c7819deac742ed78ae548d83272c/src/pl/subdivisions.csv), Blob `c178158f3d5a9aa6b8f1efc51c13c9ff7947f9a5`.
- [MEN, Kalender 2026/27, veröffentlicht 15.05.2026](https://www.gov.pl/web/edukacja/ministerstwo-edukacji-narodowej-oglosilo-kalendarz-roku-szkolnego-20262027), abgerufen 28.11.2026; [Kreuzbeleg Kuratorium, 19.05.2026](https://www.kuratorium.waw.pl/pl/informacje/aktualnosci/19802%2CMinisterstwo-Edukacji-Narodowej-oglosilo-kalendarz-roku-szkolnego-20262027.html).
- [MEN, Ferien 2025/26, 16.01.2026](https://www.gov.pl/web/edukacja/rozpoczynamy-ferie-zimowe), abgerufen 28.11.2026; negative/Bestands-Gegenprobe, keine Änderung 2026-Winterferien.

Die 16 ISO-IDs werden aus dem tatsächlichen Verzeichnis auf Provider-ShortName abgebildet. Für 2027 sind PL-06/LB und PL-08/LU falsch oder fehlend, außerdem fehlen die nationalen Zeiträume 23.–31.12.2026, 25.–30.03.2027 und 26.06.–31.08.2027. Vorhandene IDs/übrige Datensätze bleiben unverändert. Inklusive Enddaten, keine Umrechnung in UTC-Instants. Die Probe prüft pro Gebiet exakte Winterintervalle 2026 und 2027 sowie je drei landesweite Intervalle, Mapping, eindeutige IDs und bekannte Codes. Die amtlichen Fakten sind in ISO-Form erfasst, nicht aus dem fehlerhaften CSV abgeleitet.

## Ausgeführt

Identischer V8-Prüfer: **33/83 → 83/83**. Vier Negativmutationen erkannt; exakte Vorwärts-/Rückwärtsanwendung des Kontext-Hunks im Speicher sowie unveränderter früherer Datenbestand geprüft. Keine Git-apply-Ausführung behauptet. [Vollständige Ergebnisse](results.json), [wiederholbarer Node-Prüfer](probe.cjs), [Datenpatch](openholidays-pl-864.patch). Der Prüfer kann mit den oben gebundenen Original-CSV-Dateien und nach Anwendung im separaten Upstream-Checkout ausgeführt werden:

```sh
node probe.cjs /path/to/openholidaysapi.data/src/pl/holidays/holidays.school.csv /path/to/openholidaysapi.data/src/pl/subdivisions.csv
```

## Lizenz / Grenzen / nächster Schritt

OpenHolidays API Data, [ODbL 1.0](https://github.com/openpotato/openholidaysapi.data/blob/65673ec67926c7819deac742ed78ae548d83272c/LICENSE), vollständiger Lizenztext beigefügt; der CSV-Diff ist eine bearbeitete Anbieter-Datenbank unter derselben Lizenz. Amtliche Quellen: Ministerstwo Edukacji Narodowej, Veröffentlichungs-/Abrufdatum oben; nur abgeleitete Kalenderfakten, keine Kopie amtlicher Gestaltung oder Texte. Kein vollständiger amtlicher Kalender außerhalb der genannten Intervalle/Schultypen.

Produktbasis `c3536a42a6695fb08c2a082809e6fd54dd43cca5`. Die bisherigen #850–#857-Übernahmen und neun Nationalmotive stehen laut ARBEITSSTAND in main; der aktuelle Swift-/Kotlin-/C#-Provider enthält nur die AT-Sonderabbildung, keine PL-Abbildung. Der große Linux-Produktblob wurde vom Connector leer zurückgegeben, Git-Checkout scheitert an DNS. Keine vollständige Produktquellenbindung für einen Vierplattform-Fix, keine tatsächliche Live-API-Abnahme. Kein Produktpatch und keine neue Regionswahl. Nächster freier Schritt in #860: Live-API/Upstream-Korrektur abgleichen und geprüfte PL-ISO-Grenzabbildung sowie sichere Coverage/Cache-Verarbeitung und GUI/Setup/Handbuch über alle Produktpfade entwickeln. Amtliche veröffentlichte Schuljahre explizit von vollständigen Kalenderjahren unterscheiden. Fehlende oder fehlerhafte Daten dürfen nicht alte Feriendaten löschen. #128 bleibt separat, Marker8 nicht bewerben. #691 und älterer Desktop-Pumpfix nicht als frisch übernommen behaupten.
