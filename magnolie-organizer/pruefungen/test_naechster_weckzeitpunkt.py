import importlib.machinery
import importlib.util
import os
from datetime import datetime

import pytest


PROGRAMM = os.path.join(os.path.dirname(__file__), "..", "bin", "magnolie-organizer")
lader = importlib.machinery.SourceFileLoader("magnolie_wecksuche", PROGRAMM)
spec = importlib.util.spec_from_loader(lader.name, lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


def vollmaterialisierte_referenz(daten, jetzt, vorlauf=15):
    """Bis N8 verwendete Suche als Differentialreferenz."""
    bester = None
    alarm_minuten = [minuten for termin in (daten or {}).get("termine") or []
                     if isinstance(termin, dict)
                     for minuten, _related, _absolut in m._strukturierte_alarme(termin)
                     if minuten is not None and minuten > 0]
    individuelle = [m._erinnerung_tage(termin.get("individuelleErinnerungTage"))
                    for termin in (daten or {}).get("termine") or []
                    if isinstance(termin, dict)]
    vorlauf_tage = max([1, (max(0, vorlauf) + 1439) // 1440] +
                       [(minuten + 1439) // 1440 for minuten in alarm_minuten] +
                       [tage for tage in individuelle if 1 <= tage <= 7])
    termine = m.termine_mit_wiederholungen(
        daten, jetzt, tage_zurueck=0, tage_vor=370 + vorlauf_tage)
    for termin in termine:
        if not isinstance(termin, dict):
            continue
        beginn = m._termin_zeitpunkt(termin)
        if beginn is None:
            continue
        kennung = str(termin.get("id") or termin.get("uid") or "?")
        for _marke, weckzeit, _tage, _basis, _alte_marken in m._termin_meldungen(
                termin, kennung, beginn, vorlauf):
            if weckzeit > jetzt and (bester is None or weckzeit < bester):
                bester = weckzeit
    return bester


def gemischter_bestand():
    return {"termine": [
        {"id": "einmalig", "datum": "2026-09-03", "zeit": "12:00",
         "standardErinnerung": False,
         "alarme": [{"aktiviert": True, "aktion": "display",
                      "absolut": "2026-09-01 07:13", "offsetMinuten": None}]},
        {"id": "taeglich", "datum": "2026-01-01", "zeit": "09:17",
         "endDatum": "2026-01-02", "endZeit": "10:02",
         "individuelleErinnerungTage": 7, "standardErinnerung": True,
         "wiederholung": {"art": "daily", "intervall": 3, "bis": "2027-01-10"},
         "icsAusnahmen": ["2026-08-30", "2026-09-02"],
         "icsZusatzDaten": ["2026-08-31"],
         "alarme": [
             {"aktiviert": True, "aktion": "display", "related": "START",
              "offsetMinuten": 180},
             {"aktiviert": True, "aktion": "display", "related": "END",
              "offsetMinuten": 20},
             {"aktiviert": True, "aktion": "display", "related": "START",
              "bearbeitbar": False, "triggerRaw": "+PT25M"}]},
        {"id": "woechentlich", "datum": "2025-12-29", "zeit": "06:00",
         "standardErinnerung": False,
         "wiederholung": {"art": "weekly", "intervall": 3, "bis": "2026-12-31"},
         "alarme": [{"aktiviert": True, "aktion": "display",
                      "offsetMinuten": 2880}]},
        {"id": "monatsende", "datum": "2024-01-31", "zeit": "20:00",
         "wiederholung": {"art": "monthly"}},
        {"id": "ordinal", "datum": "2024-01-12", "zeit": "08:00",
         "wiederholung": {"art": "monthly", "ordinal": -1,
                           "wochentag": "FR"}},
        {"id": "schalttag", "datum": "2024-02-29", "zeit": "11:00",
         "wiederholung": {"art": "yearly", "bis": "2028-02-29"}},
        {"id": "auswahl", "datum": "2026-01-01", "zeit": "15:00",
         "wiederholung": {"art": "custom",
                           "daten": ["2026-09-05", "2027-01-02"]},
         "icsAusnahmen": ["2026-09-05"],
         "icsZusatzDaten": ["2026-09-06"]},
    ]}


@pytest.mark.parametrize("jetzt,vorlauf", [
    (datetime(2026, 8, 29, 0, 0), 0),
    (datetime(2026, 8, 29, 8, 47), 15),
    (datetime(2026, 8, 31, 7, 13), 90),
    (datetime(2026, 9, 1, 7, 13), 1440),
    (datetime(2026, 12, 31, 23, 59), 10080),
])
def test_direktsuche_gleicht_vollmaterialisierte_referenz(jetzt, vorlauf):
    daten = gemischter_bestand()
    assert m.naechster_weckzeitpunkt(daten, jetzt, vorlauf) == \
        vollmaterialisierte_referenz(daten, jetzt, vorlauf)


def test_zeitzone_rdate_exdate_und_absolute_alarme_bleiben_erhalten():
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
           "UID:tz-serie\r\nDTSTART;TZID=Europe/Berlin:20261024T093000\r\n"
           "DTEND;TZID=Europe/Berlin:20261024T103000\r\n"
           "RRULE:FREQ=DAILY;COUNT=5\r\nEXDATE;TZID=Europe/Berlin:20261025T093000\r\n"
           "RDATE;TZID=Europe/Berlin:20261030T093000\r\n"
           "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER;RELATED=END:-PT20M\r\n"
           "END:VALARM\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:absolut\r\n"
           "DTSTART:20261101T120000Z\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\n"
           "TRIGGER;VALUE=DATE-TIME:20261025T011500Z\r\nEND:VALARM\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    daten = m.ics_lesen(ics)
    jetzt = datetime(2026, 10, 25, 1, 0)
    assert m.naechster_weckzeitpunkt(daten, jetzt) == \
        vollmaterialisierte_referenz(daten, jetzt)


def test_strikte_jetzt_und_seriengrenzen_stimmen_mit_referenz_ueberein():
    daten = {"termine": [{
        "id": "grenze", "datum": "2026-08-28", "zeit": "09:00",
        "wiederholung": {"art": "daily", "bis": "2026-08-30"},
        "icsAusnahmen": ["2026-08-30"],
        "icsZusatzDaten": ["2027-08-29"]}]}
    for jetzt in (datetime(2026, 8, 29, 8, 44),
                  datetime(2026, 8, 29, 8, 45),
                  datetime(2026, 8, 29, 8, 46),
                  datetime(2027, 8, 28, 8, 44)):
        assert m.naechster_weckzeitpunkt(daten, jetzt) == \
            vollmaterialisierte_referenz(daten, jetzt)


def test_suche_materialisiert_nur_alarmkandidaten(monkeypatch):
    anzahl = 4000
    daten = {"termine": [{
        "id": "serie-%d" % i, "datum": "2020-01-01", "zeit": "09:00",
        "wiederholung": {"art": "daily"}}
        for i in range(anzahl)]}
    echt = m._serieninstanz
    erzeugt = 0

    def zaehlen(termin, tag):
        nonlocal erzeugt
        erzeugt += 1
        return echt(termin, tag)

    monkeypatch.setattr(m, "_serieninstanz", zaehlen)
    monkeypatch.setattr(m, "termine_mit_wiederholungen",
                        lambda *_a, **_k: pytest.fail("Jahresmaterialisierung aufgerufen"))
    assert m.naechster_weckzeitpunkt(
        daten, datetime(2026, 8, 29, 8, 0)) == datetime(2026, 8, 29, 8, 45)
    assert erzeugt == 2 * anzahl
