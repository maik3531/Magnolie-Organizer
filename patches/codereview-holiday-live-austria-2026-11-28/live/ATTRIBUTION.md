# OpenHolidays-Daten in diesem Prüfpaket

Dieses Paket enthält Daten von [OpenHolidays API](https://www.openholidaysapi.org/),
bereitgestellt unter der [ODC Open Database License (ODbL)](https://raw.githubusercontent.com/openpotato/openholidaysapi.data/refs/heads/main/LICENSE).
Die offizielle [FAQ](https://www.openholidaysapi.org/en/faq/) benennt diese Lizenz
ausdrücklich für die aufbereiteten Daten. Die [Datenquellenliste](https://www.openholidaysapi.org/en/sources-europe/)
führt die verwendeten öffentlichen Ursprungsquellen auf.

Die vollständige beim Prüflauf gelesene Datenlizenz liegt in
`OPENHOLIDAYS-DATA-LICENSE.txt`. Abrufbeleg und SHA-256 stehen in
`license-receipt.json`. Sie gilt für die hier enthaltenen Providerdaten und
deren abgeleitete Datenansichten; aus der Softwarelizenz des Organizer-Projekts
wird keine abweichende Lizenzierung dieser Daten abgeleitet.

`capture/response-*.json`, `capture/at-*-school-2026.json`,
`capture/at-subdivisions.json`, `after-capture/response-*.json` und
`final-capture/response-*.json` sind unveränderte
HTTP-Antwortkörper. Die zugehörigen Belege enthalten die genauen Anfrage-URLs,
UTC-Zeitstempel, HTTP-Status, Byteanzahl und SHA-256. Die Dateien
`live-results.json` enthalten zusätzlich die durch die im Paket quellengebundenen
Produktfunktionen erzeugten normalisierten Kalenderdaten. Diese Datenansichten
bleiben gemeinsam mit ihren Rohquellen unter der oben angegebenen ODbL verfügbar.

Die neun Zuordnungen zwischen österreichischem ISO-Länderteilcode und
OpenHolidays-Code stammen aus der archivierten offiziellen `Subdivisions`-
Antwort. Es wurden keine Ferientermine erfunden oder aus Modellwissen ergänzt.
