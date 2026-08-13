# Quellen der Original-Testdateien

Die Dateien in diesem Ordner bleiben inhaltlich unveraenderte Proben ihrer
jeweiligen Erzeuger. Lediglich die Zeilenenden und der abschliessende
Zeilenumbruch sind im Quellbaum vereinheitlicht.

## OpenHolidaysAPI

- Datei: `openholidays-schulferien-bw-2026.ics`
- Abgerufen: 29. Juli 2026
- URL: <https://openholidaysapi.org/SchoolHolidays?countryIsoCode=DE&subdivisionCode=DE-BW&languageIsoCode=DE&validFrom=2026-01-01&validTo=2026-12-31>
- Erzeuger laut `PRODID`: STUEBER SYSTEMS OpenHolidaysApi

## icalendar

- Datei: `icalendar-all-components.ics`
- Original: <https://github.com/collective/icalendar/blob/9e08f2288b46af26380c88cb2ae595f8b4fa144d/src/icalendar/tests/calendars/issue_1050_all_components.ics>
- Lizenz: BSD-2-Clause, Copyright (c) 2012-2013, Plone Foundation
- Lizenztext: <https://github.com/collective/icalendar/blob/9e08f2288b46af26380c88cb2ae595f8b4fa144d/LICENSE.rst>

## ez-vcard

- Datei: `John_Doe_EVOLUTION.vcf`
- Original: <https://github.com/mangstadt/ez-vcard/blob/2396882d93f2da1eaab405d637fedeff582b2b66/src/test/resources/ezvcard/io/text/John_Doe_EVOLUTION.vcf>
- Lizenz: BSD-2-Clause, Copyright (c) 2012-2026, Michael Angstadt
- Lizenztext: <https://github.com/mangstadt/ez-vcard/blob/2396882d93f2da1eaab405d637fedeff582b2b66/LICENSE>

## Magnolie-LDIF-Golden

- Datei: `golden-kontakt.ldif`
- Projektspezifische, deterministische Probe fuer den identischen Linux- und
  Windows-Writer; keine externe Originaldatei.

## Thunderbird-Schema

Die in `test_parser.py` aufgebaute SQLite-Probe folgt dem aktuellen offiziellen
Schema 23 aus Mozillas `calStorageUpgrade.sys.mjs` und den Speicherflags aus
`calStorageHelpers.sys.mjs`:

- <https://github.com/mozilla/releases-comm-central/blob/72b8ba0761b3881d926be53f77fbf75d5a9316d5/calendar/providers/storage/calStorageUpgrade.sys.mjs>
- <https://github.com/mozilla/releases-comm-central/blob/72b8ba0761b3881d926be53f77fbf75d5a9316d5/calendar/providers/storage/calStorageHelpers.sys.mjs>
- Lizenz: Mozilla Public License 2.0

## Lotus Organizer

In den offiziellen IBM-Archiven und bekannten freien Projekten war keine
echte Exportdatei auffindbar, die alle Bereiche abdeckt und ausdrücklich
weiterverbreitet werden darf. Die Lastdateien werden deshalb reproduzierbar
von `../erzeuge_lotus.py` erzeugt. Der Parser setzt bewusst keine feste
Spaltenreihenfolge voraus, weil Lotus beim ASCII-Export Auswahl, Reihenfolge,
Trennzeichen und eine optionale Kopfzeile zulässt.

- Offizielles IBM-Archiv: <https://public.dhe.ibm.com/software/lotus/desktop/Organizer/>
- WebCalendar bestätigt Lotus Organizer 6 mit vCalendar 1.0: <https://github.com/craigk5n/webcalendar/blob/8a2c2a687f00c5dedfeef2891fae746c6d352ebc/help_import.php>

## Private anonymisierte Importproben

Die fünf Dateien `muster-*.ics` und `muster-*.csv` wurden am 7. August 2026
aus den vom Anwender bereitgestellten Thunderbird- und Lotus-Testexporten
abgeleitet. Namen und Kennungen sind ausdrücklich erfundene Testdaten; bei der
CSV-Probe wurde lediglich der Zeichensatz nach UTF-8 vereinheitlicht.
