#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prüft die Import-/Export- und Abgleichfunktionen des Magnolie Organizers."""

import importlib.machinery
import importlib.util
import base64
import hashlib
import io
import json
import ast
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest import mock

import os

PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
QUELLWURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KATALOG = os.path.join(
    QUELLWURZEL, "locale", "de", "LC_MESSAGES", "magnolie-organizer.mo")
if os.path.isfile(os.path.join(QUELLWURZEL, "po", "de.po")) and not os.path.isfile(KATALOG):
    sys.exit("Deutscher Prüfkatalog fehlt. Zuerst ausführen: "
             "msgfmt -o locale/de/LC_MESSAGES/magnolie-organizer.mo po/de.po")
lader = importlib.machinery.SourceFileLoader("magorg", PFAD)
spec = importlib.util.spec_from_loader("magorg", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)

fehler = []
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def pruefe(bedingung, text):
    if bedingung:
        print("  ok  –", text)
    else:
        print("FEHLT –", text)
        fehler.append(text)


# ---------------------------------------------------------------- ICS lesen
print("\n[ICS lesen – Thunderbird-artige Datei]")
pruefe(m.kanonischer_text(" Straße  ÄÖÜ ") == "strasse aou" and
       m.jahrestag_typ_id("Geburtstag") == "birthday" and
       m.wiederholung_art("Tag") == "daily" and
       m.wiederholung_art("Woche") == "weekly" and
       m.erinnerungs_art("Meldung") == "notification",
       "deutsche Altwerte und Textschlüssel werden sprachneutral kanonisiert")
ics = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Mozilla.org//NONSGML Thunderbird//EN\r\n"
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Europe/Berlin\r\n"
    "BEGIN:STANDARD\r\n"
    "DTSTART:19701025T030000\r\n"
    "END:STANDARD\r\n"
    "END:VTIMEZONE\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:abc-123@thunderbird\r\n"
    "SUMMARY:Zahnarzt\\, Kontrolle\r\n"
    "DESCRIPTION:Bitte Karte mitbringen\\nund früh da sein\r\n"
    "DTSTART;TZID=Europe/Berlin:20260803T093000\r\n"
    "DTEND;TZID=Europe/Berlin:20260803T101500\r\n"
    "LAST-MODIFIED:20260701T120000Z\r\n"
    "CLASS:CONFIDENTIAL\r\n"
    "STATUS:TENTATIVE\r\n"
    "CATEGORIES:Gesundheit\r\n"
    "X-MAGNOLIE-KOSTENSTELLE:KS-7\r\n"
    "X-MAGNOLIE-KUNDE:4711\r\n"
    "BEGIN:VALARM\r\n"
    "ACTION:DISPLAY\r\n"
    "TRIGGER:-PT15M\r\n"
    "DESCRIPTION:Erinnerung mit DTSTART:falsch\r\n"
    "END:VALARM\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:ganztag-1\r\n"
    "SUMMARY:Messe Duisburg mit einem sehr langen Titel der die Zeilenfaltung au\r\n"
    " sprobiert und weitergeht\r\n"
    "DTSTART;VALUE=DATE:20260810\r\n"
    "DTEND;VALUE=DATE:20260811\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:geb-1\r\n"
    "SUMMARY:Oma Erna\r\n"
    "DTSTART;VALUE=DATE:19400212\r\n"
    "RRULE:FREQ=YEARLY\r\n"
    "CATEGORIES:Birthday\r\n"
    "X-MAGNOLIE-TYPE-ID:birthday\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:woech-1\r\n"
    "SUMMARY:Stammtisch\r\n"
    "DTSTART:20260805T190000\r\n"
    "DTEND:20260805T200000\r\n"
    "RRULE:FREQ=WEEKLY;BYDAY=WE\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VTODO\r\n"
    "UID:todo-1\r\n"
    "SUMMARY:Steuer abgeben\r\n"
    "DUE;VALUE=DATE:20260901\r\n"
    "PRIORITY:1\r\n"
    "DESCRIPTION:Belege sortieren\r\n"
    "END:VTODO\r\n"
    "BEGIN:VTODO\r\n"
    "UID:todo-2\r\n"
    "SUMMARY:Keller aufräumen\r\n"
    "STATUS:COMPLETED\r\n"
    "PRIORITY:9\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR\r\n")
g = m.ics_lesen(ics)
pruefe(len(g["termine"]) == 3, "3 Termine gelesen (2 normale + 1 wöchentlicher)")
t0 = g["termine"][0]
pruefe(t0["titel"] == "Zahnarzt, Kontrolle", "Komma-Maskierung im Titel aufgelöst")
pruefe(t0["notiz"] == "Bitte Karte mitbringen\nund früh da sein", "Zeilenumbruch in Notiz")
pruefe(t0["datum"] == "2026-08-03" and t0["zeit"] == "09:30",
       "TZID in der eigenen Zone bewahrt die Ortszeit")
pruefe(t0["endZeit"] == "10:15", "Ende-Uhrzeit übernommen")
pruefe(t0["vertraulich"] is True and t0["vorlaeufig"] is True, "VERTRAULICH und VORLÄUFIG erkannt")
pruefe(t0["kostenstelle"] == "KS-7" and t0["kunde"] == "4711", "Kostenstelle und Kundennummer")
pruefe(t0["geaendert"] > 0, "LAST-MODIFIED als Zeitstempel")
t1 = g["termine"][1]
pruefe(t1["zeit"] == "" and "Zeilenfaltung ausprobiert" in t1["titel"],
       "Ganztags-Termin mit entfalteter Langzeile")
pruefe(len(g["jahrestage"]) == 1 and g["jahrestage"][0]["typ"] == "birthday"
       and g["jahrestage"][0]["datum"] == "1940-02-12",
       "FREQ=YEARLY wird zum Geburtstag-Jahrestag")
pruefe(g["termine"][2]["wiederholung"] == {"art": "weekly", "bis": ""} and
       g["wiederholend"] == 0,
       "einfache wöchentliche Wiederholung wird übernommen")
monatsregeln = []
for regel in ("FREQ=MONTHLY;BYDAY=2TH",
              "FREQ=MONTHLY;BYDAY=TH;BYSETPOS=2"):
    gelesen = m.ics_lesen(
        "BEGIN:VEVENT\r\nUID:monat-2th\r\nSUMMARY:Zweiter Donnerstag\r\n"
        "DTSTART;VALUE=DATE:20240111\r\nRRULE:" + regel + "\r\nEND:VEVENT\r\n")
    monatsregeln.append(gelesen["termine"][0])
pruefe(monatsregeln[0]["wiederholung"] == {"art": "monthly", "bis": "",
                                           "ordinal": 2, "wochentag": "TH"} and
       monatsregeln[1]["wiederholung"] == {"art": "monthly", "bis": "",
          "ordinal": 2, "wochentag": "TH", "rruleForm": "bysetpos"} and
       all(not t["icsKomplex"] for t in monatsregeln),
       "Google- und BYSETPOS-Form des zweiten Donnerstags werden exakt gelesen")
unpassendes_setpos = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Falsches Setpos\r\nDTSTART;VALUE=DATE:20240111\r\n"
    "RRULE:FREQ=WEEKLY;BYSETPOS=2\r\nEND:VEVENT\r\n")
pruefe(unpassendes_setpos["termine"][0]["icsKomplex"] and
       unpassendes_setpos["termine"][0]["wiederholung"]["art"] == "none",
       "BYSETPOS außerhalb der exakt darstellbaren Monatsregel bleibt komplex")
negatives_ordinal = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:monat-minus-zwei\r\nSUMMARY:Vorletzter Freitag\r\n"
    "DTSTART;VALUE=DATE:20240119\r\nRRULE:FREQ=MONTHLY;BYDAY=-2FR\r\nEND:VEVENT\r\n")
negativ_termin = negatives_ordinal["termine"][0]
pruefe(negativ_termin["icsKomplex"] and
       negativ_termin["wiederholung"]["art"] == "none" and
       "RRULE:FREQ=MONTHLY;BYDAY=-2FR" in m.ics_schreiben_termine([negativ_termin]),
       "nicht darstellbare negative Monatsordinale bleiben opak erhalten")
abweichender_start = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:monat-start\r\nSUMMARY:Erstes Vorkommen\r\n"
    "DTSTART;VALUE=DATE:20260105\r\nRRULE:FREQ=MONTHLY;BYDAY=1FR\r\nEND:VEVENT\r\n")["termine"][0]
pruefe(abweichender_start["datum"] == "2026-01-05" and
       abweichender_start["wiederholung"]["ordinal"] == 1 and
       abweichender_start["wiederholung"]["wochentag"] == "FR",
       "DTSTART bleibt das erste Vorkommen einer abweichenden Monatsregel")
monatsserie = monatsregeln[0]
richtige_monate = ["2024-02-08", "2024-03-14", "2024-04-11"]
falsche_tage = ["2024-02-01", "2024-02-15", "2024-03-07", "2024-04-18"]
pruefe(all(m.wiederholung_trifft(monatsserie,
                                  datetime.strptime(tag, "%Y-%m-%d"))
           for tag in richtige_monate) and
       not any(m.wiederholung_trifft(monatsserie,
                                      datetime.strptime(tag, "%Y-%m-%d"))
               for tag in falsche_tage),
       "Monatsserie enthält nur 08.02., 14.03. und 11.04.2024")
taeglich = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Tabletten\r\nDTSTART:20260805T080000\r\n"
    "DTEND:20260805T083000\r\n"
    "RRULE:FREQ=DAILY\r\nEND:VEVENT\r\n")
pruefe(taeglich["termine"][0]["wiederholung"] == {"art": "daily", "bis": ""},
       "einfache tägliche Wiederholung wird übernommen")
intervall_regel = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Vierzehntäglich\r\n"
    "DTSTART:20260805T190000\r\nDTEND:20260805T193000\r\n"
    "RRULE:FREQ=WEEKLY;INTERVAL=2\r\n"
    "END:VEVENT\r\n")
pruefe(intervall_regel["termine"][0]["wiederholung"] ==
       {"art": "weekly", "bis": "", "intervall": 2} and
       intervall_regel["wiederholend"] == 0,
       "vierzehntägliche RRULE wird exakt übernommen")
mit_ausnahme = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:ausnahme-1\r\nSUMMARY:Wochenrunde\r\n"
    "DTSTART:20260805T190000\r\nRRULE:FREQ=WEEKLY\r\n"
    "EXDATE:20260812T190000\r\nEND:VEVENT\r\n")
pruefe(mit_ausnahme["termine"][0]["wiederholung"]["art"] == "none" and
       mit_ausnahme["wiederholend"] == 0,
       "RRULE mit EXDATE wird nicht falsch angenähert und sichtbar gemeldet")
mit_zusatz = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:zusatz-1\r\nSUMMARY:Sondertermine\r\n"
    "DTSTART;VALUE=DATE:20260805\r\nRDATE;VALUE=DATE:20260812,20260819\r\n"
    "END:VEVENT\r\n")
pruefe(mit_zusatz["termine"][0]["wiederholung"] ==
       {"art": "custom", "bis": "", "daten": ["2026-08-12", "2026-08-19"]} and
       mit_zusatz["wiederholend"] == 0,
       "RDATE ohne RRULE wird als benutzerdefinierte Tagesauswahl übernommen")
mit_instanz = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:serie-1\r\nSUMMARY:Serie\r\n"
    "DTSTART:20260805T190000\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:serie-1\r\nRECURRENCE-ID:20260812T190000\r\n"
    "SUMMARY:Verschobene Serie\r\nDTSTART:20260813T200000\r\nEND:VEVENT\r\n")
pruefe(len(mit_instanz["termine"]) == 2 and
       all(t["wiederholung"]["art"] == "none" for t in mit_instanz["termine"]) and
       len({t["uid"] for t in mit_instanz["termine"]}) == 2 and
       mit_instanz["wiederholend"] == 0,
       "RECURRENCE-ID-Komponenten werden ohne falsche Expansion abgeflacht")
instanz_geaendert = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:serie-1\r\nRECURRENCE-ID:20260812T190000\r\n"
    "DTSTAMP:20260810T120000Z\r\nSUMMARY:Neuer Titel\r\n"
    "DTSTART:20260813T210000\r\nEND:VEVENT\r\n")
pruefe(instanz_geaendert["termine"][0]["uid"] ==
       mit_instanz["termine"][1]["uid"],
       "Instanzkennung bleibt trotz geänderter Nutzdaten stabil")
monatsende = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Monatsende\r\nDTSTART;VALUE=DATE:20260131\r\n"
    "RRULE:FREQ=MONTHLY\r\nEND:VEVENT\r\n")
schalttag = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Schalttag\r\nDTSTART;VALUE=DATE:20240229\r\n"
    "RRULE:FREQ=YEARLY\r\nEND:VEVENT\r\n")
pruefe(monatsende["termine"][0]["icsKomplex"] and
       schalttag["termine"][0]["icsKomplex"] and
       monatsende["wiederholend"] == schalttag["wiederholend"] == 0,
       "RFC-Regeln mit ausfallenden Kalendertagen werden nicht verschoben")
mehrtaegige_serie = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Wochenendkurs\r\nDTSTART;VALUE=DATE:20260801\r\n"
    "DTEND;VALUE=DATE:20260803\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n")
pruefe(not mehrtaegige_serie["termine"][0]["icsKomplex"] and
       mehrtaegige_serie["termine"][0]["endDatum"] == "2026-08-02" and
       mehrtaegige_serie["termine"][0]["wiederholung"]["art"] == "weekly",
       "mehrtägige Serien behalten ihre exakt verschiebbare Tagesdauer")
utc_serie = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:utc-serie\r\nSUMMARY:UTC-Serie\r\n"
    "DTSTART:20260115T110000Z\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n")
pruefe(utc_serie["termine"][0]["icsKomplex"] and
       utc_serie["termine"][0]["wiederholung"]["art"] == "none",
       "zeitzonenabhängige UTC-Serie wird nicht als feste Ortszeit angenähert")
ohne_dauer = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Ohne Dauer\r\nDTSTART:20260805T190000\r\n"
    "RRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n")
mit_sekunden = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Mit Sekunden\r\nDTSTART:20260805T190030\r\n"
    "DTEND:20260805T200030\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n")
pruefe(ohne_dauer["termine"][0]["icsKomplex"] and
       mit_sekunden["termine"][0]["icsKomplex"],
       "Dauer und Sekunden einer Serie werden nicht erfunden oder gerundet")
pruefe(len(g["aufgaben"]) == 2, "2 Aufgaben (VTODO) gelesen")
a0, a1 = g["aufgaben"]
pruefe(a0["prio"] == 1 and a0["faellig"] == "2026-09-01" and not a0["erledigt"],
       "Aufgabe 1: Priorität, Fälligkeit, offen")
pruefe(a1["prio"] == 3 and a1["erledigt"], "Aufgabe 2: niedrige Priorität, erledigt")
ungueltig = m.ics_lesen("BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261340\r\n"
                       "SUMMARY:Kaputt\r\nEND:VEVENT\r\n")
pruefe(not ungueltig["termine"] and ungueltig["uebersprungen"] == 1,
       "ungültiges ICS-Datum wird ohne Absturz ausgelassen")

with open(os.path.join(FIXTURES, "muster-jahrestage-thunderbird.ics"),
          encoding="utf-8") as datei:
    thunderbird_jahrestage = m.ics_lesen(datei.read())
with open(os.path.join(FIXTURES, "muster-jahrestage-lotus.ics"),
          encoding="utf-8") as datei:
    lotus_jahrestage = m.ics_lesen(datei.read())
pruefe(len(thunderbird_jahrestage["termine"]) == 3 and
       not thunderbird_jahrestage["jahrestage"] and
       len(lotus_jahrestage["termine"]) == 3 and
       not lotus_jahrestage["jahrestage"],
       "externe Thunderbird- und Lotus-Ereignisse bleiben ohne Magnolie-Typ Termine")
with open(os.path.join(FIXTURES, "muster-organizer-lotus.ics"),
          encoding="utf-8") as datei:
    lotus_ics_original = m.ics_lesen(datei.read())
with open(os.path.join(FIXTURES, "muster-planer-lotus.ics"),
          encoding="utf-8") as datei:
    lotus_planer_original = m.ics_lesen(datei.read())
with open(os.path.join(FIXTURES, "muster-organizer-lotus.csv"), "rb") as datei:
    lotus_csv_original = m.lotus_csv_lesen(datei.read())
pruefe(len(lotus_ics_original["termine"]) == 2 and
       len(lotus_planer_original["termine"]) == 2 and
       bool(lotus_planer_original["termine"][0]["titel"]) and
       len(lotus_csv_original["termine"]) == 3 and
       not lotus_csv_original["uebersprungen"],
       "bereitgestellte Lotus-Kalender und Nanosekunden-CSV werden vollständig gelesen")
pruefe(not m.ics_lesen("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")["termine"],
       "ein gültiger leerer Kalender bleibt von einem falschen Dateiformat unterscheidbar")
for bezeichnung, arbeit in (
        ("SQLite als ICS", lambda: m.ics_lesen("SQLite format 3\x00")),
        ("SQLite als CSV", lambda: m.lotus_csv_lesen(b"SQLite format 3\x00")),
        ("unbekannte CSV", lambda: m.lotus_csv_lesen(b"foo,bar,baz\n1,2,3\n")),
        ("unvollständige ICS", lambda: m.ics_lesen(
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Offen\r\n"))):
    try:
        arbeit()
        formatfehler = False
    except ValueError:
        formatfehler = True
    pruefe(formatfehler, bezeichnung + " wird mit einem sichtbaren Formatfehler abgewiesen")
utf16_ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:UTF-16\r\n"
             "DTSTART;VALUE=DATE:20260807\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
pruefe(m.ics_lesen(m._text_dekodieren(utf16_ics.encode("utf-16")))["termine"][0]
       ["titel"] == "UTF-16", "UTF-16-Kalender werden anhand ihrer BOM gelesen")

print("\n[ICS lesen – echte OpenHolidaysAPI-Datei]")
with open(os.path.join(FIXTURES, "openholidays-schulferien-bw-2026.ics"),
          encoding="utf-8") as datei:
    ferien = m.ics_lesen(datei.read())
pruefe(len(ferien["termine"]) == 7, "alle 7 Ferienabschnitte gelesen")
sommer = next(t for t in ferien["termine"] if t["titel"] == "Sommerferien (BW)")
pruefe(sommer["datum"] == "2026-07-30" and
       sommer["endDatum"] == "2026-09-12",
       "exklusives DTEND wird zum letzten Ferientag 12.09.2026")
ferien_zurueck = m.ics_lesen(m.ics_schreiben_termine([sommer]))["termine"][0]
pruefe(ferien_zurueck["endDatum"] == sommer["endDatum"],
       "mehrtägiger Ganztagstermin übersteht die ICS-Rundreise")
gemischte_bloecke, gemischt_uebersprungen = m._ics_termine_bloecke([
    sommer,
    {"titel": "Ohne Datum", "datum": ""},
    {"titel": "Unmöglicher Tag", "datum": "2026-02-31"},
    {"titel": "Falsche Uhrzeit", "datum": "2026-08-01", "zeit": "29:10"},
])
pruefe(len(gemischte_bloecke) == 1 and gemischt_uebersprungen == 3,
       "beschädigte Termine werden einzeln übersprungen")
pruefe(m.ics_schreiben_termine([sommer, {"datum": "kaputt"}]).count(
           "BEGIN:VEVENT") == 1,
       "ein beschädigter Termin bricht den gesamten Export nicht ab")
jahrestag_bloecke, jahrestag_uebersprungen = m._ics_jahrestage_bloecke([
    {"datum": "1980-04-12", "name": "Geburtstag"},
    {"datum": "1980-13-40", "name": "Kaputt"},
])
pruefe(len(jahrestag_bloecke) == 1 and jahrestag_uebersprungen == 1,
       "beschädigte Jahrestage werden beim Export einzeln übersprungen")
aufgaben_bloecke, aufgaben_uebersprungen = m._ics_aufgaben_bloecke([
    {"titel": "Erledigen", "faellig": "2026-09-01"},
    {"titel": "Kaputt", "faellig": "2026-02-31"},
])
pruefe(len(aufgaben_bloecke) == 1 and aufgaben_uebersprungen == 1,
       "beschädigte Aufgaben werden beim Export einzeln übersprungen")

print("\n[ICS lesen – echte icalendar-Komponentenprobe]")
with open(os.path.join(FIXTURES, "icalendar-all-components.ics"),
          encoding="utf-8") as datei:
    komponenten = m.ics_lesen(datei.read())
pruefe(len(komponenten["termine"]) == 1 and
       komponenten["termine"][0]["zeit"] == "16:00" and
       komponenten["termine"][0]["endZeit"] == "17:00",
       "VEVENT mit VTIMEZONE und VALARM in die Organizer-Zone umgerechnet")
pruefe(len(komponenten["aufgaben"]) == 1 and
       komponenten["aufgaben"][0]["uid"] == "todo-1",
       "VTODO zwischen fremden Komponenten gelesen")
pruefe(komponenten["uebersprungen"] == 2,
       "VJOURNAL und unbekannte Top-Level-Komponente stehen im Importbericht")
verlustprobe = m.ics_lesen(
    "BEGIN:VCALENDAR\r\nBEGIN:VTIMEZONE\r\nTZID:UTC\r\nEND:VTIMEZONE\r\n"
    "BEGIN:VEVENT\r\nUID:alarm-event\r\nDTSTART:20260818T100000Z\r\n"
    "SUMMARY:Alarm\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\n"
    "END:VALARM\r\nEND:VEVENT\r\nBEGIN:VJOURNAL\r\nUID:j-1\r\n"
    "END:VJOURNAL\r\nBEGIN:VFREEBUSY\r\nUID:f-1\r\nEND:VFREEBUSY\r\n"
    "END:VCALENDAR\r\n")
pruefe(verlustprobe["uebersprungen"] == 2 and
       "BEGIN:VALARM" in verlustprobe["termine"][0]["icsRoundtrip"] and
       "END:VALARM" in verlustprobe["termine"][0]["icsRoundtrip"],
       "VJOURNAL/VFREEBUSY werden gemeldet, VTIMEZONE und VALARM bleiben erhalten")
try:
    m.ics_lesen("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260818T100000Z\r\n"
                "BEGIN:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    verschachtelungsfehler = False
except ValueError:
    verschachtelungsfehler = True
pruefe(verschachtelungsfehler,
       "unvollständige ICS-Verschachtelung bleibt ein sichtbarer Fehler")

print("\n[ICS lesen – UTC-Zeit wird Ortszeit]")
g2 = m.ics_lesen("BEGIN:VEVENT\r\nUID:u1\r\nSUMMARY:UTC-Probe\r\n"
                 "DTSTART:20260115T110000Z\r\nEND:VEVENT\r\n")
pruefe(g2["termine"][0]["zeit"] == "12:00",
       "11:00 UTC im Januar = 12:00 deutscher Zeit (Container-TZ: %s)"
       % g2["termine"][0]["zeit"])
fremde_zone = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:New York\r\n"
    "DTSTART;TZID=America/New_York:20260803T093000\r\nEND:VEVENT\r\n")
pruefe(fremde_zone["termine"][0]["zeit"] == "15:30",
       "09:30 in New York wird im Sommer zu 15:30 deutscher Zeit")
regional_dst_alt = dict(m._REGIONAL)
try:
    dst_matrix = (
        ("Europe/Berlin", "2026-03-29", "03:30"),
        ("Etc/UTC", "2026-03-29", "01:30"),
        ("America/New_York", "2026-03-28", "21:30"),
        ("Australia/Lord_Howe", "2026-03-29", "12:30"),
    )
    dst_ergebnisse = []
    for zone, datum, zeit in dst_matrix:
        m._REGIONAL["timeZone"] = zone
        dst_ergebnisse.append(
            m._ics_datumzeit("20260329T013000Z", {}) == (datum, zeit))
    pruefe(all(dst_ergebnisse),
           "UTC-Zeit wird in Berlin, UTC, New York und Lord Howe korrekt umgerechnet")

    berlin_zone = "\n".join(m._vtimezone_zeilen("Europe/Berlin", 2026, 2026))
    new_york_zone = "\n".join(
        m._vtimezone_zeilen("America/New_York", 2026, 2026))
    lord_howe_zone = "\n".join(
        m._vtimezone_zeilen("Australia/Lord_Howe", 2026, 2026))
    pruefe(all(text in berlin_zone for text in (
               "20260329T020000", "20261025T030000",
               "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200")) and
           all(text in new_york_zone for text in (
               "20260308T020000", "20261101T020000",
               "TZOFFSETFROM:-0500", "TZOFFSETTO:-0400")) and
           all(text in lord_howe_zone for text in (
               "20260405T020000", "20261004T020000",
               "TZOFFSETFROM:+1100", "TZOFFSETTO:+1030",
               "TZOFFSETFROM:+1030", "TZOFFSETTO:+1100")),
           "VTIMEZONE bildet europäische, amerikanische und halbstündige DST-Sprünge ab")
finally:
    m._REGIONAL.clear()
    m._REGIONAL.update(regional_dst_alt)

# ------------------------------------------------------------- ICS Rundreise
print("\n[ICS schreiben und wieder lesen]")
termin = {"datum": "2026-12-24", "endDatum": "", "zeit": "18:00",
          "endZeit": "19:30",
          "titel": "Bescherung; feierlich", "notiz": "Erst Essen,\ndann Geschenke",
          "kategorien": "Familie,Fest", "vertraulich": True, "vorlaeufig": False,
          "kostenstelle": "", "kunde": "", "individuelleErinnerungTage": 7,
          "standardErinnerung": False,
          "wiederholung": {"art": "none", "bis": ""},
          "uid": "rund-1@magnolie", "geaendert": 1750000000000}
text = m.ics_schreiben_termine([termin])
zurueck = m.ics_lesen(text)["termine"][0]
for feld in m.TERMIN_FELDER + ["uid"]:
    pruefe(zurueck[feld] == termin[feld], "Rundreise-Feld %s" % feld)
jt = {"name": "Hochzeit Müller", "datum": "1999-06-05", "typ": "wedding-anniversary",
      "uid": "jt-1", "geaendert": 0}
jtz = m.ics_lesen(m.ics_schreiben_jahrestage([jt]))["jahrestage"][0]
pruefe(jtz["name"] == jt["name"] and jtz["typ"] == "wedding-anniversary"
       and jtz["datum"] == jt["datum"], "Jahrestag-Rundreise mit Typ")
jt_jahrlos = {"name": "Jahrloser Schalttag", "datum": "--02-29",
              "typ": "birthday", "uid": "jt-jahrlos"}
jt_jahrlos_text = m.ics_schreiben_jahrestage([jt_jahrlos])
jt_jahrlos_zurueck = m.ics_lesen(jt_jahrlos_text)["jahrestage"][0]
pruefe("DTSTART;VALUE=DATE:20000229" in jt_jahrlos_text and
       "X-MAGNOLIE-DATE:--02-29" in jt_jahrlos_text and
       jt_jahrlos_zurueck["datum"] == "--02-29",
       "jahrlose ICS-Jahrestage nutzen nur an der Grenze ein gültiges Projektdatum")
echtes_2000 = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Echtes Jahr 2000\r\nCATEGORIES:Birthday\r\n"
    "DTSTART;VALUE=DATE:20000229\r\nRRULE:FREQ=YEARLY\r\n"
    "X-MAGNOLIE-TYPE-ID:birthday\r\nEND:VEVENT\r\n")
ungueltige_erweiterung = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Kaputte Erweiterung\r\nCATEGORIES:Birthday\r\n"
    "DTSTART;VALUE=DATE:20000229\r\nRRULE:FREQ=YEARLY\r\n"
    "X-MAGNOLIE-TYPE-ID:birthday\r\n"
    "X-MAGNOLIE-DATE:--02-30\r\nEND:VEVENT\r\n")
pruefe(echtes_2000["jahrestage"][0]["datum"] == "2000-02-29" and
       ungueltige_erweiterung["jahrestage"][0]["datum"] == "2000-02-29",
       "ICS-Jahr 2000 bleibt ohne gültige Magnolie-Erweiterung ein echtes Jahr")
eigener_jt = dict(jt, name="Vereinsgründung", typ="Familientag", uid="jt-2")
eigener_jtz = m.ics_lesen(m.ics_schreiben_jahrestage([eigener_jt]))["jahrestage"][0]
pruefe(eigener_jtz["typ"] == "Familientag",
       "freie Jahrestagsart übersteht die ICS-Rundreise")
auf = {"titel": "Reifen wechseln", "faellig": "2026-10-15", "prio": 3,
       "startDatum": "2026-10-14", "startZeit": "14:00", "faelligZeit": "16:30",
       "erledigt": False, "notiz": "", "erinnern": True,
       "individuelleErinnerungTage": 4, "uid": "a-1", "geaendert": 0}
aufz = m.ics_lesen(m.ics_schreiben_aufgaben([auf]))["aufgaben"][0]
pruefe(aufz["titel"] == auf["titel"] and aufz["prio"] == 3
       and aufz["faellig"] == auf["faellig"] and aufz["uid"] == auf["uid"],
       "Aufgaben-Rundreise mit stabiler UID")
pruefe(aufz["erinnern"] and aufz["individuelleErinnerungTage"] == 4,
       "Aufgabenerinnerungen überstehen die ICS-Rundreise")
pruefe(aufz["startDatum"] == "2026-10-14" and
       aufz["startZeit"] == "14:00" and aufz["faelligZeit"] == "16:30",
       "Aufgabenzeitfenster übersteht die ICS-Rundreise")
kind_aufgabe = dict(auf, uid="kind-1", elternUid="eltern-1", reihenfolge=7,
                    icsRoundtrip=["RELATED-TO;RELTYPE=SIBLING:fremd",
                                  "RELATED-TO;RELTYPE=PARENT:veraltet",
                                  "X-MAGNOLIE-REIHENFOLGE:99"])
kind_text = m.ics_schreiben_aufgaben([kind_aufgabe])
kind_zurueck = m.ics_lesen(kind_text)["aufgaben"][0]
pruefe(kind_zurueck["elternUid"] == "eltern-1" and
       kind_zurueck["reihenfolge"] == 7 and
       kind_text.count("RELATED-TO;RELTYPE=PARENT:") == 1 and
       kind_text.count("X-MAGNOLIE-REIHENFOLGE:") == 1 and
       "RELATED-TO;RELTYPE=SIBLING:fremd" in kind_text,
       "Aufgabenhierarchie und fremde Beziehungen überstehen die ICS-Rundreise")
gemischte_resource = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:termin-1\r\n"
                      "DTSTART;VALUE=DATE:20261015\r\nSUMMARY:Termin behalten\r\nEND:VEVENT\r\n" +
                      "\r\n".join(m._vtodo_zeilen(kind_aufgabe)) +
                      "\r\nEND:VCALENDAR\r\n")
gemischt_neu = m.ics_aufgabe_resource_aktualisieren(
    gemischte_resource, dict(kind_aufgabe, titel="Geändert"))
gemischt_ohne = m.ics_aufgabe_resource_entfernen(gemischt_neu, "kind-1")
pruefe("SUMMARY:Termin behalten" in gemischt_neu and "SUMMARY:Geändert" in gemischt_neu and
       gemischt_ohne is not None and "BEGIN:VEVENT" in gemischt_ohne and
       "BEGIN:VTODO" not in gemischt_ohne,
       "VTODO-Änderung oder -Löschung erhält eine gemischte Kalenderressource")
stale_aufgabe = m.ics_lesen("""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VTODO\r
UID:stale-task\r
SUMMARY:Alte Aufgabe\r
PRIORITY:9\r
STATUS:COMPLETED\r
PERCENT-COMPLETE:100\r
X-MAGNOLIE-ERINNERUNG-AM-TAG:1\r
END:VTODO\r
END:VCALENDAR\r
""")["aufgaben"][0]
stale_aufgabe.update({"prio": 1, "erledigt": False, "erinnern": False})
stale_export = m.ics_schreiben_aufgaben([stale_aufgabe])
stale_zurueck = m.ics_lesen(stale_export)["aufgaben"][0]
pruefe(stale_export.count("PRIORITY:") == 1 and "PRIORITY:9" not in stale_export and
       "PERCENT-COMPLETE:100" not in stale_export and
       "X-MAGNOLIE-ERINNERUNG-AM-TAG:1" not in stale_export and
       stale_zurueck["prio"] == 1 and not stale_zurueck["erledigt"] and
       not stale_zurueck["erinnern"],
       "gelöschte und geänderte Aufgabenmerkmale kehren nicht aus Roundtripdaten zurück")
alte_faelligkeit = m.ics_lesen("""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VTODO\r
UID:due-task\r
SUMMARY:Fälligkeit ändern\r
DUE;VALUE=DATE:20260101\r
END:VTODO\r
END:VCALENDAR\r
""")["aufgaben"][0]
alte_faelligkeit["faellig"] = "2026-12-24"
due_export = m.ics_schreiben_aufgaben([alte_faelligkeit])
pruefe("DUE;VALUE=DATE:20261224" in due_export and "20260101" not in due_export,
       "eine geänderte Aufgabenfälligkeit kehrt nicht aus Roundtripdaten zurück")
falt_original = "SUMMARY:" + ("Grüße 🌸 aus Köln, " * 12)
falt_text = m._falte(falt_original)
pruefe(all(len(zeile.encode("utf-8")) <= 75
           for zeile in falt_text.split("\r\n")),
       "ICS-Zeilen werden nach höchstens 75 UTF-8-Oktetten gefaltet")
pruefe(m._entfalte_zeilen(falt_text + "\r\n") == [falt_original],
       "mehrbyteige Zeichen überstehen Faltung und Entfaltung unverändert")
ohne_endzeit = dict(termin, datum="2026-08-10", endDatum="", zeit="10:00",
                    endZeit="", titel="Kurzer Termin", uid="ohne-ende")
ohne_endzeit_text = m.ics_schreiben_termine([ohne_endzeit])
ohne_endzeit_zurueck = m.ics_lesen(ohne_endzeit_text)["termine"][0]
pruefe(":20260810T103000" in ohne_endzeit_text and
       ohne_endzeit_zurueck["endZeit"] == "10:30",
       "eine fehlende Endzeit wird als halbstündiger Termin exportiert")
spaet = dict(ohne_endzeit, datum="2026-08-10", zeit="23:50", uid="spaet")
spaet_text = m.ics_schreiben_termine([spaet])
spaet_zurueck = m.ics_lesen(spaet_text)["termine"][0]
pruefe(":20260811T002000" in spaet_text and
       spaet_zurueck["endDatum"] == "2026-08-11" and
       spaet_zurueck["endZeit"] == "00:20",
       "die Vorgabedauer läuft bei Bedarf korrekt über Mitternacht")
pruefe("DTSTART;TZID=Europe/Berlin:" in ohne_endzeit_text and
       "DTEND;TZID=Europe/Berlin:" in ohne_endzeit_text and
       "BEGIN:VTIMEZONE" in ohne_endzeit_text and
       "TZID:Europe/Berlin" in ohne_endzeit_text and
       "BEGIN:STANDARD" in ohne_endzeit_text and
       "BEGIN:DAYLIGHT" in ohne_endzeit_text,
       "zeitgebundene Termine erhalten eine vollständige Organizer-Zeitzone")
wiederkehrend = dict(termin, wiederholung={"art": "monthly", "bis": "2027-03-31"},
                     uid="wiederkehrend")
wiederkehrend_text = m.ics_schreiben_termine([wiederkehrend])
wiederkehrend_zurueck = m.ics_lesen(wiederkehrend_text)["termine"][0]
pruefe("RRULE:FREQ=MONTHLY;UNTIL=20270331T160000Z" in wiederkehrend_text and
       wiederkehrend_zurueck["wiederholung"] ==
       {"art": "monthly", "bis": "2027-03-31"},
       "zeitgebundenes UNTIL wird als UTC exportiert und korrekt zurückgelesen")
taeglich_rund = dict(termin, wiederholung={"art": "daily", "bis": "2026-08-12"},
                     uid="taeglich")
taeglich_text = m.ics_schreiben_termine([taeglich_rund])
taeglich_zurueck = m.ics_lesen(taeglich_text)["termine"][0]
pruefe("RRULE:FREQ=DAILY;UNTIL=" in taeglich_text and
       taeglich_zurueck["wiederholung"] == {"art": "daily", "bis": "2026-08-12"},
       "tägliche Wiederholungen überstehen den ICS-Rundlauf")
intervall_rund = dict(termin, wiederholung={"art": "weekly", "intervall": 3, "bis": ""},
                       uid="dreiwochen")
intervall_text = m.ics_schreiben_termine([intervall_rund])
intervall_zurueck = m.ics_lesen(intervall_text)["termine"][0]
pruefe("RRULE:FREQ=WEEKLY;INTERVAL=3" in intervall_text and
       intervall_zurueck["wiederholung"] == {"art": "weekly", "bis": "", "intervall": 3},
       "Drei-Wochen-Regel übersteht den ICS-Rundlauf")
eigene_rund = dict(termin, wiederholung={"art": "custom", "bis": "",
                    "daten": ["2027-01-19", "2027-02-05"]}, uid="eigene-tage")
eigene_text = m.ics_schreiben_termine([eigene_rund])
eigene_zurueck = m.ics_lesen(eigene_text)["termine"][0]
pruefe("RDATE:" in eigene_text and eigene_zurueck["wiederholung"] == eigene_rund["wiederholung"],
       "benutzerdefinierte Tage überstehen den ICS-Rundlauf")
regional_ics_alt = dict(m._REGIONAL)
try:
    m._REGIONAL["timeZone"] = "America/New_York"
    westlich = m.ics_lesen(
        "BEGIN:VEVENT\r\nSUMMARY:Späte Montagsrunde\r\n"
        "DTSTART;TZID=America/New_York:20260803T210000\r\n"
        "DTEND;TZID=America/New_York:20260803T220000\r\n"
        "RRULE:FREQ=WEEKLY;UNTIL=20260804T010000Z\r\nEND:VEVENT\r\n")
    pruefe(westlich["termine"][0]["wiederholung"] ==
           {"art": "weekly", "bis": "2026-08-03"},
           "UTC-UNTIL wird westlich von Greenwich nicht um einen Tag verlängert")
finally:
    m._REGIONAL.clear()
    m._REGIONAL.update(regional_ics_alt)
jahresbesprechung = m.ics_lesen(
    "BEGIN:VEVENT\r\nSUMMARY:Jahresbesprechung\r\n"
    "DTSTART:20260912T140000\r\nDTEND:20260912T150000\r\n"
    "RRULE:FREQ=YEARLY\r\nEND:VEVENT\r\n")
pruefe(len(jahresbesprechung["termine"]) == 1 and
       not jahresbesprechung["jahrestage"] and
       jahresbesprechung["termine"][0]["zeit"] == "14:00" and
       jahresbesprechung["termine"][0]["wiederholung"]["art"] == "yearly",
       "eine jährliche Besprechung bleibt ein Termin mit Uhrzeit")
feiertage = m.ics_lesen(
    "BEGIN:VEVENT\r\nUID:befreiung\r\n"
    "SUMMARY:Jahrestag der Befreiung vom Nationalsozialismus\r\n"
    "CATEGORIES:Regionaler Feiertag\r\nDTSTART;VALUE=DATE:20260508\r\n"
    "RRULE:FREQ=YEARLY\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:google-geburtstag\r\n"
    "SUMMARY:Herzlichen Glückwunsch zum Geburtstag\r\n"
    "CATEGORIES:Birthday\r\nDTSTART;VALUE=DATE:19900826\r\n"
    "RRULE:FREQ=YEARLY\r\nEND:VEVENT\r\n")
pruefe(len(feiertage["termine"]) == 2 and not feiertage["jahrestage"] and
       all(t["wiederholung"]["art"] == "yearly" for t in feiertage["termine"]),
       "Titel und Kategorie machen Ganztagstermine nicht zu Jahrestagen")

# ------------------------------------------------------------------ vCard
print("\n[vCard lesen – 3.0, 2.1 mit Quoted-Printable, 4.0]")
fn_allein = m.vcf_lesen("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Hans Müller\r\nEND:VCARD\r\n")["kontakte"][0]
pruefe((fn_allein["vorname"], fn_allein["nachname"], fn_allein["anzeigename"]) == ("", "", "Hans Müller"),
       "FN-only-vCard erfindet keine strukturierten Namensbestandteile")
vcf = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "N:Müller;Hans;;;\r\n"
    "FN:Hans Müller\r\n"
    "ORG:Bäckerei Müller;Filiale Nord\r\n"
    "TEL;TYPE=HOME,VOICE:0203 123456\r\n"
    "TEL;TYPE=CELL:0171 9876543\r\n"
    "TEL;TYPE=WORK,VOICE:0203 200001\r\n"
    "TEL;TYPE=WORK,VOICE:0203 200002\r\n"
    "TEL;TYPE=HOME,VOICE:+49 203 333333\r\n"
    "TEL;TYPE=FAX:0203 444444\r\n"
    "TEL;TYPE=PAGER:0203 555555\r\n"
    "TEL;TYPE=VOICE:0203 666666\r\n"
    "TEL;TYPE=CELL:0171 7777777\r\n"
    "EMAIL;TYPE=INTERNET:hans@example.org\r\n"
    "item1.EMAIL;TYPE=WORK,INTERNET:h.mueller@baeckerei.example\r\n"
    "item1.X-ABLabel:Verein\r\n"
    "EMAIL:47110815\r\n"
    "ADR;TYPE=HOME:;;Bäckerstraße 5;Duisburg;;47051;Deutschland\r\n"
    "ADR;TYPE=WORK:;;Filialstr. 8;Moers;;47441;Deutschland\r\n"
    "BDAY:1965-03-17\r\n"
    "NOTE:Stammkunde\\nmag Roggenbrot\r\n"
    "UID:hans-1@buch\r\n"
    "REV:20260601T080000Z\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:2.1\r\n"
    "N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Sch=C3=B6nefeld;J=C3=BCrgen\r\n"
    "TEL;HOME;VOICE:030 555\r\n"
    "BDAY:--0402\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:4.0\r\n"
    "FN:Firma Sonnenschein GmbH\r\n"
    "ORG:Sonnenschein GmbH\r\n"
    "TEL;TYPE=cell:+49 160 111222\r\n"
    "BDAY:19800229\r\n"
    "END:VCARD\r\n")
vg = m.vcf_lesen(vcf)
pruefe(len(vg["kontakte"]) == 3, "3 Karten gelesen")
k0 = vg["kontakte"][0]
pruefe(k0["nachname"] == "Müller" and k0["vorname"] == "Hans", "Name aus N")
pruefe(k0["firma"] == "Bäckerei Müller", "ORG erster Teil")
pruefe(k0["telefon"] == "0203 123456" and k0["mobil"] == "0171 9876543",
       "Festnetz und Mobil getrennt")
pruefe(len(k0["telefone"]) == 9 and
       any(t["wert"] == "0203 444444" and "FAX" in t["typen"] for t in k0["telefone"]),
       "alle neun typisierten Telefonnummern bleiben erhalten")
pruefe(k0["emails"] ==
       ["hans@example.org", "h.mueller@baeckerei.example"] and
       k0["email"] == "hans@example.org",
       "nur echte E-Post-Anschriften bleiben in ihrer Reihenfolge erhalten")
pruefe("WORK" in k0["emailEintraege"][1]["typen"] and
       k0["emailEintraege"][1]["label"] == "Verein",
       "E-Post-Art und freie Bezeichnung werden aus vCard gelesen")
pruefe(m._email_adresse("Hans Müller <hans.neu@example.org>") ==
       "hans.neu@example.org" and not m._email_adresse("47110815"),
       "Anzeigenamen werden bereinigt und bloße Nummern verworfen")
pruefe(not m._email_adresse("4d87d88e8c565eed@nowhere.invalid") and
       not m._email_adresse("x@UNTER.DOMAIN.INVALID"),
       "reservierte Platzhalteradressen werden verworfen")
pruefe(k0["strasse"] == "Bäckerstraße 5" and k0["ort"] == "Duisburg"
       and k0["plz"] == "47051", "Anschrift aus ADR")
pruefe(len(k0["anschriften"]) == 2 and
       k0["anschriften"][1]["strasse"] == "Filialstr. 8",
       "mehrere Anschriften bleiben erhalten")
pruefe(m._telefon_schluessel("0203 123456") ==
       m._telefon_schluessel("+49 (0)203 123456") ==
       m._telefon_schluessel("0049 203 123456"),
       "Landesvorwahl und nationale Schreibweise ergeben denselben Schlüssel")
adress_probe = {"anschriften": [
    {"strasse": "Musterstraße 7", "plz": "47051", "ort": "Duisburg"},
    {"strasse": "Musterstr. 7", "plz": "47051", "ort": "Duisburg"},
    {"strasse": "Musterstrasse 7", "plz": "47051", "ort": "Duisburg"}]}
pruefe(len(m._anschrift_liste(adress_probe)) == 1,
       "Straße, Strasse und Str. werden als dieselbe Anschrift erkannt")
adress_ergaenzt = m._anschrift_liste({"anschriften": [
    {"strasse": "28 Albert-Einstein Straße"},
    {"strasse": "28 Albert-Einstein Straße", "plz": "02625", "ort": "Bautzen"}]})
pruefe(len(adress_ergaenzt) == 1 and adress_ergaenzt[0]["plz"] == "02625" and
       adress_ergaenzt[0]["ort"] == "Bautzen",
       "eine vervollständigte Teilanschrift wird nicht als zweite Anschrift angelegt")
pruefe(k0["notiz"] == "Stammkunde\nmag Roggenbrot", "NOTE mit Umbruch")
pruefe(k0["uid"] == "hans-1@buch" and k0["geaendert"] > 0, "UID und REV")
k1 = vg["kontakte"][1]
pruefe(k1["nachname"] == "Schönefeld" and k1["vorname"] == "Jürgen",
       "Quoted-Printable-Umlaute (vCard 2.1)")
pruefe(k1["telefon"] == "030 555", "nackter HOME-Parameter (2.1)")
k2 = vg["kontakte"][2]
pruefe(k2["firma"] == "Sonnenschein GmbH" and not k2["nachname"] and
       not k2["vorname"], "Firmenname wird nicht in Personennamen zerlegt")
pruefe(k2["mobil"] == "+49 160 111222", "TYPE=cell kleingeschrieben (4.0)")
name_only = m.vcf_lesen(
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:name-only\r\n"
    "N:;;;;\r\nFN:Meyer Schulze\r\nEND:VCARD\r\n")["kontakte"][0]
pruefe(name_only["nachname"] == "" and name_only["vorname"] == "" and
       name_only["anzeigename"] == "Meyer Schulze",
       "unstrukturierter Anzeigename bleibt von leeren Namensfeldern getrennt")

cardbook_vcf = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nN:CardBook;Clara;;;\r\n"
    "TEL;TYPE=home:0203 111111\r\n"
    "TEL;TYPE=mobile:0171 222222\r\n"
    "TEL;TYPE=homeFax:0203 333333\r\n"
    "TEL;TYPE=PREF;TYPE=workFax:0203 444444\r\n"
    "item1.TEL:0171 555555\r\nitem1.X-ABLabel:Privates Mobiltelefon\r\n"
    "item2.TEL:0203 666666\r\nitem2.X-ABLabel:Zuhause\r\n"
    "END:VCARD\r\n")
cardbook = m.vcf_lesen(cardbook_vcf)["kontakte"][0]
pruefe(cardbook["telefon"] == "0203 111111" and
       cardbook["mobil"] == "0171 222222",
       "CardBook-Google-Typen trennen Zuhause und Mobil")
pruefe(any(t["wert"] == "0203 333333" and
           set(t["typen"]) >= {"HOME", "FAX"} for t in cardbook["telefone"]) and
       any(t["wert"] == "0203 444444" and
           set(t["typen"]) >= {"WORK", "FAX", "PREF"}
           for t in cardbook["telefone"]),
       "CardBook-Google-Faxtypen und wiederholte TYPE-Parameter bleiben richtig")
pruefe(any(t.get("label") == "Privates Mobiltelefon" and "CELL" in t["typen"]
           for t in cardbook["telefone"]) and
       any(t.get("label") == "Zuhause" and "HOME" in t["typen"]
           for t in cardbook["telefone"]),
       "freie CardBook-Telefonlabels bleiben erhalten und semantisch zugeordnet")
geb = {(g_["anzeigename"], g_["geburtstag"]) for g_ in vg["kontakte"] if g_.get("geburtstag")}
pruefe(not vg["geburtstage"], "F30: Kontaktgeburtstage werden nicht losgeloest verdoppelt")
pruefe(("Hans Müller", "1965-03-17") in geb, "Geburtstag aus BDAY")
pruefe(k1["geburtstag"] == "--04-02" and k1["geburtstagJahrUnbekannt"] and
       (k1["vorname"], k1["nachname"], k1["anzeigename"]) == ("Jürgen", "Schönefeld", ""),
       "BDAY ohne Jahr bleibt direkt in kanonischer jahrloser Form erhalten")
pruefe(all(m._maschinen_datum(wert) == wert for wert in (
           "1815-12-10", "--02-29", "--12-31")) and
       all(not m._maschinen_datum(wert) for wert in (
           "2000-02-30", "--02-30", "--2-03", "2000-2-03", " 2000-02-03 ",
           "1900-02-29", "2000-00-01", "2000-01-01T00:00")),
       "Maschinendaten akzeptieren nur gültiges YYYY-MM-DD oder --MM-DD")

print("\n[Claws Mail – LDIF und natives XML]")
claws_name = m.base64.b64encode("Änne Beispiel".encode("utf-8")).decode("ascii")
ldif = ("version: 1\n\n"
        "dn: mail=aenne@example.org,dc=example,dc=org\n"
        "objectClass: inetOrgPerson\n"
        "cn:: %s\n" % claws_name +
        "givenName: Änne\n"
        "sn: Beispiel\n"
        "mail: aenne@example.org\n"
        "mail: arbeit@example.org\n"
        "mail: technisch@nowhere.invalid\n"
        "o: Beispiel GmbH\n"
        "telephoneNumber: 0203 123456\n"
        "telephoneNumber: +49 203 222222\n"
        "homePhone: 0203 333333\n"
        "mobile: 0171 9876543\n"
        "facsimileTelephoneNumber: 0203 444444\n"
        "street: Testweg 7\n"
        "postalCode: 47051\n"
        "l: Duisburg\n"
        "postalAddress: Zweigweg 8$Moers$47441 Moers$DE\n"
        "description: Erste Zeile und ein sehr langer Hinweis, der\n"
        " in derselben logischen Zeile weitergeht.\n"
        "dateOfBirth: 1980-04-03\n\n")
claws_ldif = m.ldif_lesen(ldif)
pruefe(len(claws_ldif["kontakte"]) == 1 and
       claws_ldif["kontakte"][0]["vorname"] == "Änne" and
       claws_ldif["kontakte"][0]["nachname"] == "Beispiel",
       "Claws-LDIF liest Base64- und Namensfelder")
pruefe(claws_ldif["kontakte"][0]["emails"] ==
       ["aenne@example.org", "arbeit@example.org"] and
       claws_ldif["kontakte"][0]["firma"] == "Beispiel GmbH" and
       claws_ldif["kontakte"][0]["mobil"] == "0171 9876543",
       "Claws-LDIF übernimmt mehrere gültige Adressen, Firma und Telefone")
ldif_jahrlos = m.ldif_lesen(
    "dn: cn=Jahrlos\ncn: Jahrlos\nsn: Jahrlos\nbirthMonth: 2\nbirthDay: 29\n\n")
pruefe(ldif_jahrlos["kontakte"][0]["geburtstag"] == "--02-29" and
       not ldif_jahrlos["geburtstage"],
       "LDIF-Monat und -Tag ohne Jahr werden kanonisch jahrlos importiert")
pruefe(m.ldif_lesen(m.ldif_schreiben([
           {"nachname": "Jahrlos", "geburtstag": "--02-29"}]))["kontakte"][0]["geburtstag"] == "--02-29",
       "LDIF-Export bewahrt Monat und Tag ohne erfundenes Jahr")
pruefe(len(claws_ldif["kontakte"][0]["telefone"]) == 5 and
       len(claws_ldif["kontakte"][0]["anschriften"]) == 2,
       "Claws-LDIF verliert keine wiederholten Rufnummern oder Anschriften")
pruefe("logischen Zeile" in claws_ldif["kontakte"][0]["notiz"] and
       claws_ldif["kontakte"][0]["geburtstag"] == "1980-04-03" and not claws_ldif["geburtstage"],
       "Claws-LDIF entfaltet Notizen und übernimmt Geburtstage")

claws_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<address-book name="Privat">
  <person uid="1" first-name="J\xc3\xbcrgen" last-name="Schmidt" cn="J\xc3\xbcrgen Schmidt">
    <address-list>
      <address uid="2" email="juergen@example.org" remarks="bevorzugt" />
      <address uid="3" email="kennung@nowhere.invalid" remarks="" />
    </address-list>
    <attribute-list>
      <attribute uid="4" name="o">Schmidt &amp; Sohn</attribute>
      <attribute uid="5" name="telephoneNumber">030 555123</attribute>
      <attribute uid="6" name="mobile">0160 777888</attribute>
      <attribute uid="61" name="mobile">0160 999000</attribute>
      <attribute uid="62" name="facsimileTelephoneNumber">030 555999</attribute>
      <attribute uid="7" name="postalAddress">Hauptstra\xc3\x9fe 5$Berlin$10115 Berlin$DE</attribute>
      <attribute uid="8" name="description">Claws-Notiz</attribute>
      <attribute uid="9" name="dateOfBirth">1975-12-09</attribute>
    </attribute-list>
  </person>
</address-book>'''
claws_x = m.claws_xml_lesen(claws_xml)
pruefe(len(claws_x["kontakte"]) == 1 and
       claws_x["kontakte"][0]["emails"] == ["juergen@example.org"] and
       claws_x["kontakte"][0]["firma"] == "Schmidt & Sohn" and
       claws_x["kontakte"][0]["strasse"] == "Hauptstraße 5",
       "natives Claws-XML übernimmt Kontaktfelder und verwirft Platzhalter")
pruefe(claws_x["kontakte"][0]["geburtstag"] == "1975-12-09" and not claws_x["geburtstage"],
       "natives Claws-XML übernimmt den Geburtstag")
try:
    m.claws_xml_lesen(b'<?xml version="1.0"?><!DOCTYPE x><address-book/>')
    pruefe(False, "DOCTYPE im Claws-XML muss scheitern")
except ValueError as f:
    pruefe(str(f) == "DOCTYPE ist in einem Claws-Mail-Adressbuch nicht erlaubt.",
           "Claws-XML erlaubt keine externe Dokumenttypdefinition")

print("\n[vCard lesen – echte Evolution-Datei]")
with open(os.path.join(FIXTURES, "John_Doe_EVOLUTION.vcf"), encoding="utf-8") as datei:
    evolution = m.vcf_lesen(datei.read())
pruefe(len(evolution["kontakte"]) == 1, "Evolution-vCard gelesen")
evo = evolution["kontakte"][0]
pruefe(evo["nachname"] == "Doe" and evo["vorname"] == "John" and
       evo["firma"] == "IBM", "Evolution-N-, FN- und ORG-Felder gelesen")
pruefe(evo["mobil"] == "905-666-1234" and
       evo["telefon"] == "905-555-1234" and evo["email"] == "john.doe@ibm.com",
       "gefaltete Evolution-Kontaktdaten gelesen")

vcf_foto_alt = ("BEGIN:VCARD\r\nVERSION:2.1\r\nN:Bild;Alte;;\r\n"
                 "PHOTO;ENCODING=BASE64;TYPE=PNG:iVBORw0K\r\n"
                 "Ggo=\r\nEND:VCARD\r\n")
foto_alt = m.vcf_lesen(vcf_foto_alt)["kontakte"][0]["foto"]
pruefe(foto_alt == "data:image/png;base64,iVBORw0KGgo=",
       "alte vCard-Fotozeilen ohne Einzug werden zusammengesetzt")

print("\n[vCard schreiben und wieder lesen]")
kontakt = {"nachname": "Schmidt-Rüttgers", "vorname": "Änne", "firma": "Werft & Co",
           "strasse": "Am Hafen 3; Halle 2", "plz": "47119", "ort": "Duisburg",
           "telefon": "0203 44", "mobil": "0170 55", "email": "aenne@werft.example",
            "telefone": [{"wert": "0203 44", "typen": ["VOICE", "WORK"],
                           "label": "Zentrale"},
                          {"wert": "0170 55", "typen": ["CELL"]},
                          {"wert": "0203 99", "typen": ["FAX"]}],
           "anschriften": [{"strasse": "Am Hafen 3; Halle 2", "plz": "47119",
                               "ort": "Duisburg", "land": "Deutschland", "typen": ["WORK"],
                               "label": "Verwaltung"},
                             {"strasse": "Werftweg 9", "plz": "20457", "ort": "Hamburg",
                                "land": "Deutschland", "typen": ["X-SECONDARY-OFFICE"]}],
             "emails": ["aenne@werft.example", "werft@beispiel.de"],
             "emailEintraege": [
                 {"wert": "aenne@werft.example", "typen": ["INTERNET", "WORK"]},
                 {"wert": "werft@beispiel.de", "typen": ["INTERNET"],
                  "label": "Verein"}],
            "notiz": "Zeile 1\nZeile 2",
             "kontaktpersonName": "Peter Schmidt",
             "kontaktpersonTelefon": "0203 123456",
             "kontaktpersonStatus": "Sohn",
              "kontaktpersonen": [
                  {"name": "Peter Schmidt", "telefon": "0203 123456", "status": "Sohn"},
                  {"name": "Maria Nachbar", "telefon": "0203 654321",
                   "status": "Nachbarin"}],
              "sozialeMedien": [
                  {"dienst": "whatsapp", "wert": "+49 170 1234567",
                    "aktionArt": "program", "aktionZiel": "zapzap {ziel}"},
                  {"dienst": "mastodon", "wert": "@aenne@beispiel.social"},
                  {"dienst": "teams", "wert": "aenne@werft.example"},
                  {"dienst": "snapchat", "wert": "aenne"},
                  {"dienst": "tiktok", "wert": "aenne"},
                  {"dienst": "youtube", "wert": "werft"},
                  {"dienst": "telegram", "wert": "aenne"},
                  {"dienst": "x", "wert": "aenne"},
                  {"dienst": "linkedin", "wert": "aenne-schmidt"},
                  {"dienst": "reddit", "wert": "aenne"},
                   {"dienst": "custom", "wert": "https://irc.example/aenne",
                    "symbol": "irc"}],
              "geburtstag": "1980-06-15", "geburtstagJahrUnbekannt": False,
              "jubilaeum": "--06-07", "anzeigename": "Anzeigename",
              "foto": "data:image/png;base64,iVBORw0KGgo=",
           "uid": "k-rund@magnolie", "geaendert": 1750000000000}
kz = m.vcf_lesen(m.vcf_schreiben([kontakt]))["kontakte"][0]
for feld in m.KONTAKT_FELDER + ["uid"]:
    if feld in kontakt:
        pruefe(kz[feld] == kontakt[feld], "Rundreise-Feld %s" % feld)
parameter_karte = m.vcf_lesen(
    "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Parameter\r\n"
    "TEL;TYPE=WORK:+49 30 222222\r\n"
    "TEL;TYPE=HOME:+493 0222222\r\n"
    "TEL;TYPE=CELL;X-MEINS=eins:+49 30 111111\r\n"
    "EMAIL;X-MAIL=eins:probe@example.test\r\n"
    "ADR;X-ADR=eins:;;Weg 1;Ort;;12345;DE\r\nEND:VCARD\r\n")["kontakte"][0]
parameter_export = m.vcard_text(parameter_karte)
pruefe("TEL;TYPE=CELL;X-MEINS=eins:+49 30 111111" in parameter_export and
       "EMAIL;TYPE=INTERNET;X-MAIL=eins:probe@example.test" in parameter_export and
       "ADR;X-ADR=eins:;;Weg 1;Ort;;12345;DE" in parameter_export,
       "vCard-Restparameter bleiben am zugehörigen Eintrag")

sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "whatsapp", "+49 170 1234567", sozial_aufrufe.append,
    lambda name: "/usr/bin/whatsie" if name == "whatsie" else None)
pruefe(sozial["ok"] and sozial["womit"] == "whatsie" and
       sozial_aufrufe[0] == ["/usr/bin/whatsie",
                             "whatsapp://send?phone=491701234567"],
       "Whatsie öffnet unmittelbar den Kontakt über das WhatsApp-Schema")
sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "whatsapp", "+49 170 1234567", sozial_aufrufe.append,
    lambda name: "/usr/bin/zapzap" if name == "zapzap" else None)
pruefe(sozial["ok"] and sozial["womit"] == "zapzap" and
       sozial_aufrufe[0][1] == "https://wa.me/491701234567",
       "WhatsApp bevorzugt ein installiertes passendes Programm")
sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "facebook", "magnolie.beispiel", sozial_aufrufe.append,
    lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
pruefe(sozial["ok"] and sozial_aufrufe[0][1].startswith(
       "https://www.facebook.com/"),
       "ohne eigenes Programm wird ein kontrolliertes Webziel geöffnet")
sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "sms", "+49 170 1234567", sozial_aufrufe.append,
    lambda name: "/opt/telefon/bin/eigenes-sms" if name == "eigenes-sms" else None,
    aktion_art="programm", aktion_ziel="eigenes-sms --to {nummer}")
pruefe(sozial["ok"] and sozial_aufrufe[0] ==
       ["/opt/telefon/bin/eigenes-sms", "--to", "+491701234567"],
       "ein ausgewählter Programmbefehl wird ohne Shell und mit Platzhalter gestartet")
sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "sms", "+49 170 1234567", sozial_aufrufe.append,
    lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
pruefe(sozial["ok"] and sozial_aufrufe[0] ==
       ["/usr/bin/xdg-open", "sms:+491701234567"],
        "SMS wird als adressierter Entwurf an den Systemstandard übergeben")

class KdeBackend:
    def __init__(self): self.sms = []
    def start(self): return True
    def stop(self): self.stopped = True
    def status(self):
        return {"available": True, "device_count": 1, "device_id": "a" * 32,
                "reason": "", "pairing_state": "idle"}
    def send_sms(self, nummer, text, device_id=None):
        self.sms.append((nummer, text, device_id))
        return {"ok": True, "state": "queued", "backend": "kdeconnect-direct"}

kde_backend = KdeBackend()
m._KDECONNECT_BACKEND = kde_backend
kde = m.kdeconnect_sms_stand()
pruefe(kde["available"] and kde["device_id"] == "a" * 32,
       "Direktes KDE Connect meldet genau ein gepaartes SMS-Gerät")
text = "Test; $(kein Befehl)\nzweite Zeile"
with tempfile.TemporaryDirectory() as kde_journal, mock.patch.object(m, "daten_verzeichnis", return_value=kde_journal):
    kde = m.kdeconnect_sms_senden("+49 170 1234567", text, "DE", client_ref="parser-first")
    pruefe(kde["ok"] and kde_backend.sms == [("+491701234567", text, None)],
           "KDE-SMS übergibt Nummer und Text direkt und unverändert an das Backend")
    kde = m.kdeconnect_sms_senden("+49 170 1234567", text, "DE", device_id="a" * 32,
                                client_ref="parser-selected")
    pruefe(kde["ok"] and kde_backend.sms[-1] == ("+491701234567", text, "a" * 32),
           "eine SMS-Antwort bleibt an das ursprüngliche KDE-Gerät gebunden")

class KdeFensterProbe:
    def __init__(self): self.antworten = []
    def antwort(self, ziel, nutzlast): self.antworten.append((ziel, nutzlast))

kde_fenster = KdeFensterProbe()
with tempfile.TemporaryDirectory() as kde_journal, mock.patch.object(m, "daten_verzeichnis", return_value=kde_journal):
    m.Fenster._kde_sms_senden(kde_fenster, "+49 170 1234567", "Client ref", "DE", "ref-4711")
pruefe(kde_fenster.antworten == [("App.kdeSmsStatus", {
    "ok": True, "state": "submitted", "backend": "kdeconnect-direct",
    "client_ref": "ref-4711"})],
       "KDE-SMS-Antwort reicht client_ref unverändert an den Web-Chat zurück")
with open(m.__file__, "r", encoding="utf-8") as kde_quelle:
    kde_quelltext = kde_quelle.read()
pruefe("_kdeconnect_backend(self._kde_ereignis)" in kde_quelltext and
       "_KDECONNECT_BACKEND.stop()" in kde_quelltext,
       "das Fenster startet KDE Connect früh und beendet es erst beim echten Ende")
pruefe(kde_quelltext.index("if \"--wecker\" in sys.argv[1:]") <
       kde_quelltext.index(
           "fenster = Fenster(web_verzeichnis, setup_auswahl=setup_auswahl)"),
       "der Weckerzweig endet vor Fenster und KDE-Listener")
sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "signal", "+49 170 1234567", sozial_aufrufe.append,
    lambda name: "/usr/bin/flatpak" if name == "flatpak" else None,
    aktion_art="programm", aktion_ziel="flatpak:org.signal.Signal {ziel}")
pruefe(sozial["ok"] and sozial_aufrufe[0][:3] ==
       ["/usr/bin/flatpak", "run", "org.signal.Signal"],
       "ein ausdrücklich gewähltes Flatpak wird ohne Shell gestartet")
sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "telefon", "+49 170 1234567", sozial_aufrufe.append,
    lambda name: "/usr/bin/snap" if name == "snap" else None,
    aktion_art="programm", aktion_ziel="snap:skype {nummer}")
pruefe(sozial["ok"] and sozial_aufrufe[0] ==
       ["/usr/bin/snap", "run", "skype", "+491701234567"],
       "ein ausdrücklich gewähltes Snap wird ohne Shell gestartet")
sozial_aufrufe = []
sozial = m.sozial_oeffnen(
    "whatsapp", "+49 170 1234567", sozial_aufrufe.append,
    lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None,
    aktion_art="webseite", aktion_ziel="https://beispiel.test/chat/{nummer}")
pruefe(sozial["ok"] and sozial_aufrufe[0][1] ==
       "https://beispiel.test/chat/+491701234567",
       "eine ausgewählte HTTPS-Vorlage wird sicher mit der Kontaktnummer geöffnet")
pruefe(not m.sozial_oeffnen(
    "sms", "+49 170 1234567", lambda _a: None, lambda _n: None,
    aktion_art="webseite", aktion_ziel="http://unsicher.test/{nummer}")["ok"],
    "unsichere angepasste Webseiten werden abgewiesen")
pruefe(not m.sozial_oeffnen("mastodon", "unvollständig",
                             lambda _a: None, lambda _n: None)["ok"],
       "eine unvollständige Mastodon-Kennung wird verständlich abgewiesen")
soziale_ziele = {
    "teams": "https://teams.microsoft.com/l/chat/0/0?users=aenne@werft.example",
    "snapchat": "https://www.snapchat.com/add/aenne",
    "tiktok": "https://www.tiktok.com/@aenne",
    "youtube": "https://www.youtube.com/@werft",
    "telegram": "https://t.me/aenne", "x": "https://x.com/aenne",
    "linkedin": "https://www.linkedin.com/in/aenne-schmidt",
    "reddit": "https://www.reddit.com/user/aenne"}
for sozial_dienst, sozial_ziel in soziale_ziele.items():
    sozial_aufrufe = []
    sozial_wert = {"teams": "aenne@werft.example", "youtube": "werft",
                   "linkedin": "aenne-schmidt"}.get(sozial_dienst, "aenne")
    sozial = m.sozial_oeffnen(
        sozial_dienst, sozial_wert, sozial_aufrufe.append,
        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
    pruefe(sozial["ok"] and sozial_aufrufe[0][1] == sozial_ziel,
           "%s öffnet ein kontrolliertes Profilziel" % sozial_dienst)
soziale_aliasse = m._soziale_medien_liste({"sozialeMedien": [
    {"dienst": "twitter", "wert": "aenne"},
    {"dienst": "custom", "wert": "https://chat.example/aenne", "symbol": "twitch"}]})
pruefe(soziale_aliasse == [
    {"dienst": "x", "wert": "aenne"},
    {"dienst": "custom", "wert": "https://chat.example/aenne", "symbol": "twitch"}],
    "Twitter-Alias und benutzerdefiniertes Magnolie-Symbol bleiben erhalten")
pruefe(not m.sozial_oeffnen(
    "custom", "irc.example/aenne", lambda _a: None, lambda _n: None)["ok"],
    "Benutzerdefiniert verlangt ohne eigene Aktion eine sichere HTTPS-Adresse")
medikament_aufrufe = []
pruefe(m.medikament_suche_oeffnen("ASS 100 & Test", medikament_aufrufe.append) and
       len(medikament_aufrufe) == 1 and
       os.path.basename(medikament_aufrufe[0][0]) == "xdg-open" and
       medikament_aufrufe[0][1] ==
       "https://www.gelbe-liste.de/suche/ASS%20100%20%26%20Test" and
       not m.medikament_suche_oeffnen("", medikament_aufrufe.append),
       "Medikamentensuche öffnet nur das feste Arzneimittelportal mit kodiertem Namen")

# --------------------------------------------------------------- Lotus-CSV
print("\n[Lotus-CSV lesen]")
csv_text = ("VERTRAULICH,KATEGORIEN,ANFANGSDATUMZEIT,ENDDATUMZEIT,BESCHREIBUNG,"
            "KOSTENSTELLENCODE,KUNDENNUMMER,VORLAEUFIGZUSAGEN\r\n"
            'Ja,"Geschäft,Reise",03.08.2026 09:30,03.08.2026 10:15,'
            '"Besprechung ""Umbau""",KS-1,10023,Nein\r\n'
            "Nein,,15.08.2026,15.08.2026,Sommerfest,,,Ja\r\n"
            ",,Quatschdatum,,kaputt,,,\r\n")
lg = m.lotus_csv_lesen(csv_text.encode("utf-8"))
pruefe(len(lg["termine"]) == 2 and lg["uebersprungen"] == 1,
       "2 gültige Zeilen, 1 übersprungen")
l0 = lg["termine"][0]
pruefe(l0["vertraulich"] and l0["kategorien"] == "Geschäft,Reise"
       and l0["titel"] == 'Besprechung "Umbau"', "Anführungszeichen und Kategorien")
pruefe(l0["datum"] == "2026-08-03" and l0["zeit"] == "09:30"
       and l0["endZeit"] == "10:15", "deutsches Datumsformat mit Ende")
pruefe(l0["kostenstelle"] == "KS-1" and l0["kunde"] == "10023", "Kostenstelle/Kunde")
l1 = lg["termine"][1]
pruefe(l1["zeit"] == "" and l1["vorlaeufig"], "Ganztags + vorläufig")

csv_mehrtag = ("ANFANGSDATUMZEIT,ENDDATUMZEIT,BESCHREIBUNG\r\n"
                "30.07.2026,12.09.2026,Sommerferien\r\n")
lotus_mehrtag = m.lotus_csv_lesen(csv_mehrtag.encode("ascii"))["termine"][0]
pruefe(lotus_mehrtag["endDatum"] == "2026-09-12",
       "Lotus-Enddatum eines mehrtägigen Termins übernommen")

print("\n[Lotus-CSV mit Semikolon und cp1252]")
csv2 = ("VERTRAULICH;KATEGORIEN;ANFANGSDATUMZEIT;ENDDATUMZEIT;BESCHREIBUNG;"
        "KOSTENSTELLENCODE;KUNDENNUMMER;VORLÄUFIGZUSAGEN\r\n"
        "Nein;Privat;01.09.26 14:00;;Kaffee bei Frau Größe;;;Ja\r\n")
lg2 = m.lotus_csv_lesen(csv2.encode("cp1252"))
pruefe(len(lg2["termine"]) == 1 and lg2["termine"][0]["titel"] == "Kaffee bei Frau Größe",
       "Semikolon-Trenner, cp1252-Umlaute, Umlaut-Spaltenkopf")
pruefe(lg2["termine"][0]["datum"] == "2026-09-01", "zweistelliges Jahr")

print("\n[Lotus-CSV/ANSI mit Tabulator und allgemeinen Spalten]")
csv_tab = ("Datum\tUhrzeit\tEndzeit\tBetreff\tKategorien\r\n"
           "Mittwoch, 3. August 2026\t9.30\t10:15\tGrüße an Müller\tPrivat\r\n")
lg_tab = m.lotus_csv_lesen(csv_tab.encode("cp1252"))
pruefe(len(lg_tab["termine"]) == 1 and
       lg_tab["termine"][0]["titel"] == "Grüße an Müller",
       "ANSI-Zeichen und Tabulator-Trenner")
pruefe(lg_tab["termine"][0]["datum"] == "2026-08-03" and
       lg_tab["termine"][0]["zeit"] == "09:30" and
       lg_tab["termine"][0]["endZeit"] == "10:15",
       "allgemeine Datums-, Zeit- und Betreffspalten")

csv_us = ("Start Date,Start Time,End Time,Subject\r\n"
          "8/4/2026,9:15 AM,10:45 AM,US-Zeitformat\r\n")
lg_us = m.lotus_csv_lesen(csv_us.encode("ascii"))
pruefe(len(lg_us["termine"]) == 1 and
       lg_us["termine"][0]["datum"] == "2026-08-04" and
       lg_us["termine"][0]["zeit"] == "09:15",
       "Schrägstrichdatum und zwölfstündige Uhrzeit")

print("\n[Lotus-CSV ohne Kopfzeile]")
lg3 = m.lotus_csv_lesen(b"Ja,Kat,05.10.2026 08:00,05.10.2026 09:00,Fruehbesprechung,K,9,Nein\r\n")
pruefe(len(lg3["termine"]) == 1 and lg3["termine"][0]["titel"] == "Fruehbesprechung",
       "Spaltenreihenfolge ohne Kopf angenommen")

print("\n[Lotus-CSV schreiben und wieder lesen]")
lt = {"datum": "2026-08-03", "endDatum": "2026-08-04",
      "zeit": "09:30", "endZeit": "10:15",
      "titel": 'Umbau, Phase "2"', "notiz": "", "kategorien": "Geschäft",
      "vertraulich": True, "vorlaeufig": True, "kostenstelle": "KS-1",
      "kunde": "10023", "uid": "", "geaendert": 0}
geschrieben = m.lotus_csv_schreiben([lt])
pruefe(geschrieben.splitlines()[0] == ",".join(m.LOTUS_SPALTEN),
       "Kopfzeile exakt in Originalreihenfolge")
lz = m.lotus_csv_lesen(geschrieben.encode("utf-8-sig"))["termine"][0]
for feld in ["datum", "endDatum", "zeit", "endZeit", "titel", "kategorien",
             "vertraulich", "vorlaeufig", "kostenstelle", "kunde"]:
    pruefe(lz[feld] == lt[feld], "Rundreise-Feld %s" % feld)

# ------------------------------------------------------------- Sync-Abgleich
print("\n[Zwei-Wege-Abgleich]")
F = m.TERMIN_FELDER
lokal = [
    {"uid": "nur-lokal-neu", "titel": "Neu hier", "datum": "2026-08-01",
     "geaendert": 100, "sync": False},
    {"uid": "drueben-weg", "titel": "Alt", "datum": "2026-08-02",
     "geaendert": 50, "sync": True},
    {"uid": "drueben-weg-aber-geaendert", "titel": "Wichtig", "datum": "2026-08-03",
     "geaendert": 900, "sync": True},
    {"uid": "konflikt", "titel": "Lokal älter", "datum": "2026-08-04",
     "wiederholung": {"art": "woche", "bis": ""},
     "geaendert": 100, "sync": True},
    {"uid": "konflikt2", "titel": "Lokal neuer", "datum": "2026-08-05",
     "geaendert": 9999, "sync": True},
]
fern = {
    "konflikt": {"uid": "konflikt", "titel": "Fern neuer", "datum": "2026-08-04",
                  "wiederholung": {"art": "monat", "bis": "2027-08-04"},
                  "geaendert": 500},
    "konflikt2": {"uid": "konflikt2", "titel": "Fern älter", "datum": "2026-08-05",
                  "geaendert": 100},
    "nur-fern": {"uid": "nur-fern", "titel": "Vom Server", "datum": "2026-08-06",
                 "geaendert": 200},
    "hier-geloescht": {"uid": "hier-geloescht", "titel": "Soll weg",
                       "datum": "2026-08-07", "geaendert": 100},
    "hier-geloescht-drueben-neu": {"uid": "hier-geloescht-drueben-neu",
                                   "titel": "Wiederbelebt", "datum": "2026-08-08",
                                   "geaendert": 800},
}
tote = [{"uid": "hier-geloescht", "zeit": 400},
        {"uid": "hier-geloescht-drueben-neu", "zeit": 400}]
neu, anlegen, aendern, loeschen, z = m.sync_merge(lokal, fern, tote, 300, F)
uids = {t["uid"] for t in neu}
pruefe("nur-lokal-neu" in uids and any(t["uid"] == "nur-lokal-neu" for t in anlegen),
       "neuer lokaler Eintrag wird hochgegeben")
pruefe("drueben-weg" not in uids and z["lokal_geloescht"] == 1,
       "drüben gelöscht + lokal unverändert -> lokal entfernt")
pruefe(any(t["uid"] == "drueben-weg-aber-geaendert" for t in anlegen),
       "drüben gelöscht + lokal frisch geändert -> neu hochgegeben")
konflikt = next(t for t in neu if t["uid"] == "konflikt")
pruefe(konflikt["titel"] == "Fern neuer" and konflikt["geaendert"] == 500 and
       konflikt["wiederholung"] == {"art": "monat", "bis": "2027-08-04"},
       "Konflikt: neuere ferne Fassung gewinnt einschließlich Wiederholung")
pruefe(any(t["uid"] == "konflikt2" for t in aendern),
       "Konflikt: neuere lokale Fassung wird hochgegeben")
pruefe("nur-fern" in uids and z["lokal_neu"] == 2,
       "ferne Einträge kommen herein (neuer + wiederbelebter)")
pruefe(loeschen == ["hier-geloescht"], "Tombstone löscht drüben")
wieder = next((t for t in neu if t["uid"] == "hier-geloescht-drueben-neu"), None)
pruefe(wieder is not None and wieder["titel"] == "Wiederbelebt",
       "drüben nach Löschung geändert -> wiederbelebt")
pruefe(all(t.get("sync") for t in neu), "alle verbliebenen tragen sync=True")

foto_data = "data:image/png;base64,iVBORw0KGgo="
foto_lokal = [{"uid": "foto", "nachname": "Bild", "foto": "",
               "geaendert": 900, "sync": True}]
foto_fern = {"foto": {"uid": "foto", "nachname": "Bild", "foto": foto_data,
                       "geaendert": 100}}
foto_neu, _anlegen, foto_aendern, _loeschen, _z = m.sync_merge(
    foto_lokal, foto_fern, [], 0, m.KONTAKT_FELDER)
pruefe(foto_neu[0]["foto"] == foto_data and foto_aendern[0]["foto"] == foto_data,
       "später geliefertes Serverfoto überlebt einen neueren lokalen Zeitstempel")

foto_lokal = [{"uid": "foto2", "nachname": "Bild", "foto": foto_data,
               "geaendert": 100, "sync": True}]
foto_fern = {"foto2": {"uid": "foto2", "nachname": "Bild neu", "foto": "",
                         "geaendert": 900}}
foto_neu, _anlegen, foto_aendern, _loeschen, _z = m.sync_merge(
    foto_lokal, foto_fern, [], 0, m.KONTAKT_FELDER)
pruefe(foto_neu[0]["nachname"] == "Bild neu" and
       foto_neu[0]["foto"] == foto_data and foto_aendern,
       "fehlendes PHOTO-Feld löscht beim Abgleich kein vorhandenes Bild")

mail_lokal = [{"uid": "mail", "nachname": "Mehrfach",
               "email": "privat@example.org",
               "emails": ["privat@example.org", "alt@example.org", "483920"],
               "geaendert": 100, "sync": True}]
mail_fern = {"mail": {"uid": "mail", "nachname": "Mehrfach neu",
                       "email": "arbeit@example.org",
                       "emails": ["arbeit@example.org", "ALT@example.org", "99182"],
                       "geaendert": 900}}
mail_neu, _anlegen, mail_aendern, _loeschen, _z = m.sync_merge(
    mail_lokal, mail_fern, [], 0, m.KONTAKT_FELDER)
pruefe(mail_neu[0]["emails"] == ["privat@example.org", "alt@example.org",
                                  "arbeit@example.org"] and
       mail_neu[0]["email"] == "privat@example.org",
       "E-Post-Anschriften beider Seiten werden ohne Großschreibungsdubletten vereinigt")
pruefe(len(mail_aendern) == 1 and
       mail_aendern[0]["emails"] == mail_neu[0]["emails"],
       "lokal fehlende EDS-Anschriften kommen herein und lokale Ergänzungen gehen zurück")

lokale_kontakte = [{"uid": "lokaler-cache", "nachname": "Atelco",
                    "vorname": "", "geaendert": 900, "sync": False}]
ferne_kontakte = {
    "google-atelco": {"uid": "google-atelco", "nachname": "Atelco",
                       "telefon": "0800 1144444",
                       "email": "4d87d88e8c565eed@nowhere.invalid",
                       "emails": ["4d87d88e8c565eed@nowhere.invalid"],
                       "geaendert": 100}}
m.kontakte_vor_sync_zuordnen(lokale_kontakte, ferne_kontakte)
pruefe(lokale_kontakte[0]["uid"] == "google-atelco" and
       lokale_kontakte[0]["telefon"] == "0800 1144444" and
       lokale_kontakte[0]["emails"] == [],
       "sparsame lokale Kontaktkopie wird eindeutig der vollständigen Online-Karte zugeordnet")

mehrdeutig = [{"uid": "lokal", "nachname": "Müller", "sync": False}]
m.kontakte_vor_sync_zuordnen(mehrdeutig, {
    "eins": {"uid": "eins", "nachname": "Müller"},
    "zwei": {"uid": "zwei", "nachname": "Müller"}})
pruefe(mehrdeutig[0]["uid"] == "lokal",
       "mehrdeutige Namensgleichheit wird nicht automatisch zusammengeführt")

print("\n[Mehrere Kalender in einem Abgleich]")
remote_kalender = {
    "kal-a": [m.vevent_text({"uid": "gleich", "datum": "2026-10-01",
                               "titel": "Aus A", "geaendert": 100}),
              ("BEGIN:VEVENT\r\nUID:extern-komplex\r\nSUMMARY:Externe Serie\r\n"
               "DTSTART:20261005T100000\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n"),
              ("BEGIN:VEVENT\r\nUID:extern-komplex\r\n"
               "RECURRENCE-ID:20261012T100000\r\nSUMMARY:Verschoben\r\n"
               "DTSTART:20261012T110000\r\nSTATUS:CANCELLED\r\nEND:VEVENT\r\n")],
    "kal-b": [m.vevent_text({"uid": "gleich", "datum": "2026-10-02",
                              "titel": "Aus B", "geaendert": 100})],
}
angelegt = []
geaendert_eds = []

class _SyncProbe:
    def antwort(self, funktion, nutzlast):
        self.funktion = funktion
        self.nutzlast = nutzlast

probe = _SyncProbe()
alt_eds_laden = m.eds_laden
alt_registry = m.eds_registry
alt_client = m.eds_kalender_client
alt_lesen = m.eds_events_lesen
alt_anlegen = m.eds_event_anlegen
alt_aendern = m.eds_event_aendern
alt_loeschen = m.eds_event_loeschen
try:
    m.eds_laden = lambda: True
    m.eds_registry = lambda: object()
    m.eds_kalender_client = lambda _registry, uid: uid
    m.eds_events_lesen = lambda client: remote_kalender[client]
    m.eds_event_anlegen = lambda client, text: (
        angelegt.append((client, text)) or m.ics_lesen(text)["termine"][0]["uid"])
    m.eds_event_aendern = lambda client, text: geaendert_eds.append((client, text))
    m.eds_event_loeschen = lambda _client, _uid: None
    m.Fenster._sync_ausfuehren(probe, {
        "wahl": {"kalenderUid": "kal-a", "kalenderUids": ["kal-a", "kal-b"]},
        "daten": {"termine": [{"uid": "lokal-neu", "datum": "2026-10-03",
                                   "titel": "Nur einmal hochladen", "geaendert": 500,
                                   "sync": False},
                                  {"uid": "extern-komplex", "datum": "2026-10-05",
                                   "titel": "Lokale alte Kopie", "geaendert": 900,
                                   "sync": True}],
                  "kontakte": [], "jahrestage": [],
                  "geloescht": {"termine": [], "kontakte": []},
                  "letzterSync": 0, "letzteSyncs": {"kalender": {}}}})
finally:
    m.eds_laden = alt_eds_laden
    m.eds_registry = alt_registry
    m.eds_kalender_client = alt_client
    m.eds_events_lesen = alt_lesen
    m.eds_event_anlegen = alt_anlegen
    m.eds_event_aendern = alt_aendern
    m.eds_event_loeschen = alt_loeschen

kal_termine = probe.nutzlast["termine"]
pruefe(sum(t["uid"] == "gleich" for t in kal_termine) == 2 and
       {t["syncKalenderUid"] for t in kal_termine if t["uid"] == "gleich"} ==
       {"kal-a", "kal-b"},
       "gleiche Termin-UIDs aus zwei Kalendern bleiben getrennt")
pruefe(not angelegt,
       "ein unzugeordneter lokaler Termin wird nicht ungefragt hochgeladen")
pruefe(not geaendert_eds and
       any(t["uid"] == "extern-komplex" and
            t["titel"] == "Lokale alte Kopie" and not t.get("syncKalenderUid")
            for t in kal_termine) and
       any(t["uid"] == "extern-komplex" and t["titel"] == "Externe Serie" and
           t.get("icsReadOnly") and t.get("icsReadOnlyGrund") == "EDS"
           for t in kal_termine),
       "komplexe EDS-Serie bleibt neben einer unzugeordneten lokalen Kopie erhalten")
pruefe(any(t.get("icsReadOnly") and t.get("icsSerienUid") == "extern-komplex" and
           t["uid"] != "extern-komplex" and
           any(zeile.startswith("RECURRENCE-ID")
               for zeile in t.get("icsRoundtrip", [])) for t in kal_termine),
       "neue komplexe EDS-Serieninstanz wird vollständig und nur lesbar importiert")
pruefe("nur lesbar" in probe.nutzlast["bericht"].lower() or
       "nur lesen" in probe.nutzlast["bericht"].lower() or
       "read-only" in probe.nutzlast["bericht"].lower(),
       "EDS-Bericht kennzeichnet neue komplexe Serien als nur lesbar")
pruefe(set(probe.nutzlast["letzteSyncs"]["kalender"]) == {"kal-a", "kal-b"},
       "jeder ausgewählte Kalender erhält einen eigenen Abgleichzeitpunkt")
pruefe("Internetkonten des Systems" in probe.nutzlast["bericht"] and
       "Termine:" in probe.nutzlast["bericht"] and
       "kal-a" not in probe.nutzlast["bericht"] and
       "kal-b" not in probe.nutzlast["bericht"],
       "deutscher Abgleichbericht verändert oder verrät keine Quellenkennungen")

print()
print()
print("— Lokale Datenquellen (Evolution/Thunderbird) —")

import os
import sqlite3

basis = tempfile.mkdtemp(prefix="magnolie-heim-")


def _ordner(*teile):
    pfad = os.path.join(basis, *teile)
    os.makedirs(pfad, exist_ok=True)
    return pfad


# Evolution: lokales Adressbuch (contacts.db mit vcard-Spalte)
ev_adr = _ordner(".local/share/evolution/addressbook", "system")
foto_pfad = os.path.join(ev_adr, "anna.png")
with open(foto_pfad, "wb") as foto_datei:
    foto_datei.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
foto_vcard = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Fotoprobe\r\n"
              "PHOTO;VALUE=uri:file://" + foto_pfad + "\r\nEND:VCARD\r\n")
pruefe(not m.vcf_lesen(foto_vcard)["kontakte"][0].get("foto") and
       m.vcf_lesen(foto_vcard, lokale_dateien=True)["kontakte"][0]["foto"].startswith(
           "data:image/png;base64,"),
       "fremde vCards lesen keine lokalen Dateien, vertrauenswürdige Ablagen schon")
verb = sqlite3.connect(os.path.join(ev_adr, "contacts.db"))
verb.execute("CREATE TABLE folder_id (uid TEXT, vcard TEXT, bdata TEXT)")
verb.execute("INSERT INTO folder_id VALUES (?,?,?)", ("meta", "kein vCard", None))
verb.execute("INSERT INTO folder_id VALUES (?,?,?)", ("u1",
    "BEGIN:VCARD\r\nVERSION:3.0\r\nN:M\u00fcller;Anna;;;\r\nFN:Anna M\u00fcller\r\n"
    "EMAIL:anna@beispiel.de\r\nBDAY:1950-03-04\r\n"
    "PHOTO;VALUE=uri:file://" + foto_pfad + "\r\nEND:VCARD\r\n", None))
verb.execute("INSERT INTO folder_id VALUES (?,?,?)", ("u2",
    "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Schmidt;Bert;;;\r\nFN:Bert Schmidt\r\n"
    "TEL;TYPE=CELL:0171 111\r\nEND:VCARD\r\n", None))
verb.commit()
verb.close()

# Evolution: Zwischenspeicher eines Online-Kontos (cache.db, Spalte heißt anders)
ev_cache = _ordner(".cache/evolution/addressbook", "google123")
verb = sqlite3.connect(os.path.join(ev_cache, "cache.db"))
verb.execute("CREATE TABLE objects (uid TEXT, revision TEXT, object TEXT)")
verb.execute("INSERT INTO objects VALUES (?,?,?)", ("u3", "1",
    "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Online;Carla;;;\r\nFN:Carla Online\r\n"
    "EMAIL:carla@online.de\r\nEND:VCARD\r\n"))
verb.commit()
verb.close()

# Evolution: lokaler Kalender als schlichte ICS-Datei
ev_kal = _ordner(".local/share/evolution/calendar", "kal1")
with open(os.path.join(ev_kal, "calendar.ics"), "w", encoding="utf-8") as f:
    f.write("BEGIN:VCALENDAR\nVERSION:2.0\n"
            "BEGIN:VEVENT\nUID:e1\nDTSTART:20260810T090000\n"
            "SUMMARY:Evolution-Termin\nEND:VEVENT\n"
            "BEGIN:VEVENT\nUID:e2\nDTSTART;VALUE=DATE:19600505\nRRULE:FREQ=YEARLY\n"
            "SUMMARY:Gartenfest\nEND:VEVENT\n"
            "BEGIN:VTODO\nUID:t1\nSUMMARY:Evolution-Aufgabe\nEND:VTODO\n"
            "END:VCALENDAR\n")

# Thunderbird: Adressbuch (properties-Tabelle) und Kalender (icalString)
tb_profil = _ordner(".thunderbird", "abc.default")
tb_fotos = _ordner(".thunderbird", "abc.default", "Photos")
with open(os.path.join(tb_fotos, "dora.png"), "wb") as foto_datei:
    foto_datei.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
verb = sqlite3.connect(os.path.join(tb_profil, "abook.sqlite"))
verb.execute("CREATE TABLE properties (card TEXT, name TEXT, value TEXT)")
for eintrag in [("k1", "FirstName", "Dora"), ("k1", "LastName", "Vogel"),
                  ("k1", "PrimaryEmail", "dora@post.de"),
                  ("k1", "SecondEmail", "DORA@ARBEIT.EXAMPLE"),
                  ("k1", "HomePhone", "0203 111111"),
                  ("k1", "WorkPhone", "+49 203 222222"),
                  ("k1", "CellularNumber", "0171 3333333"),
                  ("k1", "FaxNumber", "0203 444444"),
                  ("k1", "HomeFax", "0203 555555"),
                  ("k1", "WorkFax", "0203 666666"),
                  ("k1", "PagerNumber", "0203 777777"),
                  ("k1", "HomeAddress", "Privatweg 1"),
                  ("k1", "HomeCity", "Duisburg"),
                  ("k1", "HomeZipCode", "47051"),
                  ("k1", "WorkAddress", "Büroweg 2"),
                  ("k1", "WorkCity", "Moers"),
                  ("k1", "WorkZipCode", "47441"),
                 ("k1", "PhotoName", "dora.png"),
                ("k1", "BirthMonth", "7"), ("k1", "BirthDay", "12"),
                ("k1", "BirthYear", "1980"),
                ("k2", "DisplayName", "Firma Kn\u00f6del GmbH"),
                 ("k2", "PrimaryEmail", "info@knoedel.de"),
                 ("k2", "HomeCity", "Duisburg"),
                 ("k3", "LastName", "Meyer Schulze"),
                 ("k3", "DisplayName", "Meyer Schulze"),
                 ("k3", "PrimaryEmail", "meyer@example.test"),
                 ("k3", "_vCard", "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:k3\r\n"
                  "N:;;;;\r\nFN:Meyer Schulze\r\nEMAIL:meyer@example.test\r\nEND:VCARD\r\n")]:
    verb.execute("INSERT INTO properties VALUES (?,?,?)", eintrag)
verb.commit()
verb.close()
tb_kal = _ordner(".thunderbird", "abc.default", "calendar-data")
verb = sqlite3.connect(os.path.join(tb_kal, "local.sqlite"))
verb.execute("CREATE TABLE cal_events (cal_id TEXT, id TEXT, icalString TEXT)")
verb.execute("INSERT INTO cal_events VALUES (?,?,?)", ("c", "e9",
    "BEGIN:VEVENT\r\nUID:tb1\r\nDTSTART:20260815T140000\r\n"
    "SUMMARY:Thunderbird-Termin\r\nEND:VEVENT\r\n"))
verb.commit()
verb.close()

# Thunderbird aktuell: normalisierte Tabellen gemäß Mozilla-Schema v23.
tb_neu = _ordner(".thunderbird", "modern.default", "calendar-data")
verb = sqlite3.connect(os.path.join(tb_neu, "local.sqlite"))
verb.execute("""CREATE TABLE cal_events (
    cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, priority INTEGER,
    privacy TEXT, ical_status TEXT, flags INTEGER, event_start INTEGER,
    event_start_tz TEXT, event_end INTEGER, event_end_tz TEXT)""")
verb.execute("""CREATE TABLE cal_todos (
    cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, priority INTEGER,
    ical_status TEXT, todo_due INTEGER, todo_due_tz TEXT,
    percent_complete INTEGER)""")
verb.execute("CREATE TABLE cal_properties (cal_id TEXT, item_id TEXT, key TEXT, value BLOB)")
verb.execute("CREATE TABLE cal_recurrence (cal_id TEXT, item_id TEXT, icalString TEXT)")

def _tb_native(jahr, monat, tag, stunde=0, minute=0):
    return int(datetime(jahr, monat, tag, stunde, minute,
                        tzinfo=timezone.utc).timestamp() * 1000000)

verb.execute("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
    "modern", "tb-modern-event", _tb_native(2026, 7, 1),
    "Thunderbird-Ferien", 0, "PRIVATE", "TENTATIVE", 8,
    _tb_native(2026, 7, 30), "UTC", _tb_native(2026, 9, 13), "UTC"))
verb.execute("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
    "modern", "tb-modern-weekly", _tb_native(2026, 7, 3),
    "Thunderbird-Wochenrunde", 0, "PUBLIC", "CONFIRMED", 16,
    _tb_native(2026, 8, 5, 19), "floating",
    _tb_native(2026, 8, 5, 20), "floating"))
verb.execute("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
    "modern", "tb-modern-monthly-weekday", _tb_native(2024, 1, 11),
    "Thunderbird-Zweiter-Donnerstag", 0, "PUBLIC", "CONFIRMED", 24,
    _tb_native(2024, 1, 11), "UTC", _tb_native(2024, 1, 12), "UTC"))
verb.execute("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
    "modern", "tb-modern-birthday", _tb_native(2026, 7, 4),
    "Geburtstag Frieda (1955)", 0, "PRIVATE", "CONFIRMED", 24,
    _tb_native(1955, 3, 3), "UTC", _tb_native(1955, 3, 4), "UTC"))
verb.execute("INSERT INTO cal_todos VALUES (?,?,?,?,?,?,?,?,?)", (
    "modern", "tb-modern-todo", _tb_native(2026, 7, 2),
    "Thunderbird-Aufgabe", 1, "NEEDS-ACTION", _tb_native(2026, 9, 1),
    "UTC", 100))
verb.execute("INSERT INTO cal_properties VALUES (?,?,?,?)",
             ("modern", "tb-modern-event", "DESCRIPTION", "Sommerpause"))
verb.execute("INSERT INTO cal_properties VALUES (?,?,?,?)",
             ("modern", "tb-modern-event", "CATEGORIES", "Schule"))
verb.execute("INSERT INTO cal_properties VALUES (?,?,?,?)",
             ("modern", "tb-modern-weekly", "DESCRIPTION", "Jeden Mittwoch"))
verb.execute("INSERT INTO cal_properties VALUES (?,?,?,?)",
             ("modern", "tb-modern-birthday", "DESCRIPTION", "Familiennotiz"))
verb.execute("INSERT INTO cal_properties VALUES (?,?,?,?)",
             ("modern", "tb-modern-birthday", "CATEGORIES", "ANNIVERSARY"))
verb.execute("INSERT INTO cal_properties VALUES (?,?,?,?)",
             ("modern", "tb-modern-birthday", "X-MAGNOLIE-TYPE-ID", "birthday"))
verb.execute("INSERT INTO cal_recurrence VALUES (?,?,?)",
             ("modern", "tb-modern-weekly", "RRULE:FREQ=WEEKLY;BYDAY=WE"))
verb.execute("INSERT INTO cal_recurrence VALUES (?,?,?)",
             ("modern", "tb-modern-monthly-weekday",
              "RRULE:FREQ=MONTHLY;BYDAY=TH;BYSETPOS=2"))
verb.execute("INSERT INTO cal_recurrence VALUES (?,?,?)",
             ("modern", "tb-modern-birthday", "RRULE:FREQ=YEARLY"))
verb.execute("INSERT INTO cal_properties VALUES (?,?,?,?)",
             ("modern", "tb-modern-todo", "DESCRIPTION", "Unterlagen sortieren"))
verb.commit()
verb.close()

erg = m.lokal_scannen(basis)
pruefe(len(erg["kontakte"]) == 6,
       "6 Adressen aus drei Quellen gefunden (%d)" % len(erg["kontakte"]))
namen = {k["nachname"] or k["firma"] for k in erg["kontakte"]}
pruefe("M\u00fcller" in namen and "Vogel" in namen,
       "Umlaute und Thunderbird-Namen kommen sauber an")
pruefe(any(k["nachname"] == "Müller" and
            k["foto"].startswith("data:image/png;base64,")
            for k in erg["kontakte"]),
       "lokales Foto aus Gnome-Kontakte wird in die Karte eingebettet")
pruefe(any(k["nachname"] == "Vogel" and
             k["foto"].startswith("data:image/png;base64,")
             for k in erg["kontakte"]),
       "Thunderbird-Fotodatei wird beim lokalen Import eingebettet")
tb_dora = next(k for k in erg["kontakte"] if k["nachname"] == "Vogel")
pruefe(len(tb_dora["telefone"]) == 7 and len(tb_dora["anschriften"]) == 2 and
       tb_dora["emails"] == ["dora@post.de", "DORA@ARBEIT.EXAMPLE"] and
       tb_dora["uid"].startswith("thunderbird:") and tb_dora["uid"].endswith(":k1"),
       "Thunderbird übernimmt alle Nummern, Anschriften, E-Mails und die Karten-UID")
pruefe(any(k["email"] == "info@knoedel.de" and k["ort"] == "Duisburg"
           for k in erg["kontakte"]),
       "Karte nur mit Anzeigename wird samt Ort \u00fcbernommen")
pruefe(any(k["uid"].startswith("thunderbird:") and k["uid"].endswith(":k3") and k["nachname"] == "Meyer Schulze" and
            not k["vorname"] for k in erg["kontakte"]),
       "Thunderbird-_vCard bewahrt den strukturierten mehrteiligen Nachnamen")
pruefe(len(erg["geburtstage"]) == 0,
       "Thunderbird-Geburtstage werden nicht neben dem Kontakt verdoppelt (%d)" % len(erg["geburtstage"]))
pruefe(tb_dora["geburtstag"] == "1980-07-12",
       "Thunderbird-Geburtstag mit Jahr bleibt am Kontakt")
pruefe(len(erg["termine"]) == 6,
       "Termine aus ICS-Datei, altem und aktuellem local.sqlite (%d)"
       % len(erg["termine"]))
tb_modern = next(t for t in erg["termine"] if t["uid"] == "tb-modern-event")
pruefe(tb_modern["datum"] == "2026-07-30" and
       tb_modern["endDatum"] == "2026-09-12" and
       tb_modern["vertraulich"] and tb_modern["vorlaeufig"],
       "aktuelles Thunderbird-Ereignis samt Enddatum und Status")
pruefe(tb_modern["notiz"] == "Sommerpause" and
       tb_modern["kategorien"] == "Schule",
       "Thunderbird-Eigenschaften aus cal_properties")
tb_woechentlich = next(t for t in erg["termine"] if t["uid"] == "tb-modern-weekly")
pruefe(tb_woechentlich["wiederholung"] == {"art": "weekly", "bis": ""} and
       tb_woechentlich["notiz"] == "Jeden Mittwoch" and not tb_woechentlich["icsKomplex"],
       "aktuelle Thunderbird-Wiederholung aus cal_recurrence bleibt erhalten")
tb_monatlich = next(t for t in erg["termine"]
                    if t["uid"] == "tb-modern-monthly-weekday")
pruefe(tb_monatlich["zeit"] == "" and tb_monatlich["wiederholung"] == {
           "art": "monthly", "bis": "", "ordinal": 2, "wochentag": "TH",
           "rruleForm": "bysetpos"} and
       not tb_monatlich["icsKomplex"],
       "ganztägiger ordinaler Monatswochentag bleibt im Thunderbird-Sync erhalten")
pruefe(any(j["uid"] == "tb-modern-birthday" and j["typ"] == "birthday" and
           j["datum"] == "1955-03-03" for j in erg["jahrestage"]),
       "aktueller Thunderbird-Jahrestag landet trotz Beschreibung in der Rubrik")
gartenfest = next(t for t in erg["termine"] if t["uid"] == "e2")
pruefe(gartenfest["wiederholung"]["art"] == "yearly" and
       len(erg["jahrestage"]) == 1,
       "allgemeine jährliche Wiederholung bleibt ein Termin")
pruefe(len(erg["aufgaben"]) == 2,
       "Aufgaben aus Evolution und aktuellem Thunderbird")
tb_aufgabe = next(a for a in erg["aufgaben"] if a["uid"] == "tb-modern-todo")
pruefe(tb_aufgabe["faellig"] == "2026-09-01" and tb_aufgabe["prio"] == 1 and
       tb_aufgabe["erledigt"] and tb_aufgabe["notiz"] == "Unterlagen sortieren",
       "aktuelle Thunderbird-Aufgabe vollständig gelesen")
pruefe("Evolution" in erg["bericht"] and "Thunderbird" in erg["bericht"],
       "Fundbericht nennt beide Quellen: " + erg["bericht"])
nur_kontakte = m.lokal_scannen(basis, nur_kontakte=True)
pruefe(len(nur_kontakte["kontakte"]) == 6 and
       not nur_kontakte["geburtstage"] and
       not nur_kontakte["termine"] and not nur_kontakte["jahrestage"] and
       not nur_kontakte["aufgaben"],
       "Kontaktassistent liest ausschließlich lokale Kontakte")

tb_regional_alt = dict(m._REGIONAL)
m._REGIONAL["timeZone"] = "Europe/Berlin"
tb_spaet = _tb_native(2026, 8, 3, 23, 30)
pruefe(m._tb_native_datumzeit(tb_spaet, "UTC") == ("2026-08-04", "01:30"),
       "Thunderbird-UTC wird in die Organizer-Zeitzone umgerechnet")
pruefe(m._tb_native_datumzeit(tb_spaet, "America/New_York") ==
       ("2026-08-04", "01:30"),
       "Thunderbird-Zeitpunkte mit TZID werden in die Organizer-Zone umgerechnet")
pruefe(m._tb_native_datumzeit(tb_spaet, "floating") == ("2026-08-03", "23:30") and
       m._tb_native_datumzeit(tb_spaet, "UTC", True) == ("2026-08-03", ""),
       "schwebende und ganztägige Thunderbird-Zeiten bleiben Wandwerte")
m._REGIONAL.clear()
m._REGIONAL.update(tb_regional_alt)

leer = m.lokal_scannen(tempfile.mkdtemp(prefix="magnolie-leer-"))
pruefe(not leer["kontakte"] and "keine" in leer["bericht"],
       "Leere Heimat liefert h\u00f6flichen Hinweis")

class _VCardFormat:
    VCARD_30 = 30


class _EBookContacts:
    VCardFormat = _VCardFormat
    class ContactField:
        EMAIL = "EMAIL"
        EMAIL_1 = "EMAIL_1"
        EMAIL_2 = "EMAIL_2"
        EMAIL_3 = "EMAIL_3"
        EMAIL_4 = "EMAIL_4"
        TEL = "TEL"
        PHONE_MOBILE = "PHONE_MOBILE"
        PHONE_HOME = "PHONE_HOME"
        PHONE_HOME_1 = "PHONE_HOME_1"
        PHONE_HOME_2 = "PHONE_HOME_2"
        PHONE_BUSINESS = "PHONE_BUSINESS"
        PHONE_BUSINESS_1 = "PHONE_BUSINESS_1"
        PHONE_BUSINESS_2 = "PHONE_BUSINESS_2"
        PHONE_HOME_FAX = "PHONE_HOME_FAX"
        PHONE_BUSINESS_FAX = "PHONE_BUSINESS_FAX"
        PHONE_PAGER = "PHONE_PAGER"
        PHONE_OTHER = "PHONE_OTHER"
        PHOTO = "PHOTO"


class _EdsFotoKontakt:
    def __init__(self):
        self.inline = False

    def inline_local_photos(self):
        self.inline = True
        return True

    def get(self, feld):
        if feld == "EMAIL":
            return ["gnome@beispiel.de", "zweite@beispiel.de", "47110815"]
        if feld == "PHOTO":
            return b"\x89PNG\r\n\x1a\n" + b"\0" * 40
        if feld == "PHONE_MOBILE":
            return [131526931463024, "0171 1234567"]
        if feld in ("PHONE_HOME", "PHONE_BUSINESS"):
            return 127346988749744
        return None

    def get_attributes(self, feld):
        class Parameter:
            def __init__(self, typen):
                self.typen = typen

            def get_name(self):
                return "TYPE"

            def get_values(self):
                return self.typen

        class Attribut:
            def __init__(self, wert, typen):
                self.wert, self.typen = wert, typen

            def get_values(self):
                return [self.wert]

            def get_params(self):
                return [Parameter(self.typen)]

        if feld == "EMAIL":
            return [Attribut(wert, ["INTERNET"]) for wert in (
                "gnome@beispiel.de", "zweite@beispiel.de",
                "pflege@rosengarten.example", "leitung@rosengarten.example")]
        if feld == "TEL":
            return [Attribut("0203 55%02d" % nummer,
                             ["CELL"] if nummer % 2 else ["WORK", "VOICE"])
                    for nummer in range(1, 11)]
        return []

    def to_string(self, _format):
        return ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:eds-fotoprobe\r\nN:Bild;Gnome;;;\r\n"
                "EMAIL:gnome@beispiel.de\r\n" +
                "".join("TEL:0203 55%02d\r\n" % nummer for nummer in range(1, 7)) +
                "END:VCARD\r\n")


class _EdsFotoClient:
    def __init__(self, kontakt):
        self.kontakt = kontakt

    def get_contacts_sync(self, _abfrage, _abbruch):
        return [self.kontakt]


eds_alt = dict(m._EDS)
eds_kontakt = _EdsFotoKontakt()
m._EDS["EBookContacts"] = _EBookContacts
eds_snapshot = m.eds_kontakte_lesen(_EdsFotoClient(eds_kontakt))
m._EDS.clear()
m._EDS.update(eds_alt)
eds_gelesen = eds_snapshot["kontakte"][0]
pruefe(eds_snapshot["vollstaendig"] and eds_snapshot["remoteGesamt"] == 1,
       "EDS-Leser meldet einen vollständig validierten Snapshot")
pruefe(eds_kontakt.inline and eds_gelesen["foto"].startswith(
       "data:image/png;base64,"),
       "EDS-Fotofeld wird auch bei unvollständiger vCard-Ausgabe eingebettet")
pruefe(eds_gelesen["emails"] == ["gnome@beispiel.de", "zweite@beispiel.de",
       "pflege@rosengarten.example", "leitung@rosengarten.example"],
       "EDS-Attribute ergänzen alle vier E-Post-Anschriften")
pruefe(len(eds_gelesen["telefone"]) == 10 and
       {t["wert"] for t in eds_gelesen["telefone"]} ==
       {"0203 55%02d" % nummer for nummer in range(1, 11)},
       "EDS-Attribute ergänzen alle zehn Rufnummern ohne feste Obergrenze")
pruefe(not m._telefon_liste({"mobil": "134215178987712", "telefone": [
    {"wert": "131526931995120", "typen": ["CELL"]}]}),
       "bereits gespeicherte EDS-Zeigerwerte werden entfernt")

print()
print("— Quellsuche und deutsche Fehlertexte —")


class _QAttrappe:
    def __init__(self, uid):
        self._uid = uid

    def get_uid(self):
        return self._uid


class _NurRef:
    def ref_source(self, uid):
        return _QAttrappe(uid) if uid == "a" else None


class _NurLookup:  # ältere Hüllen
    def lookup_by_uid(self, uid):
        return _QAttrappe(uid) if uid == "b" else None


class _NurListe:  # weder ref_source noch lookup_by_uid – der Fall des Fehlerberichts
    def list_sources(self, erweiterung):
        return [_QAttrappe("x"), _QAttrappe("c")]


class _FalscheSignatur:
    def ref_source(self, uid, extra):  # TypeError beim üblichen Aufruf
        return None

    def list_sources(self):  # und list_sources ohne Argument
        return [_QAttrappe("d")]


pruefe(m._quelle(_NurRef(), "a").get_uid() == "a", "ref_source wird bevorzugt")
pruefe(m._quelle(_NurLookup(), "b").get_uid() == "b", "lookup_by_uid als Ausweg")
pruefe(m._quelle(_NurListe(), "c").get_uid() == "c",
       "ohne beide Methoden hilft die Quellenliste")
pruefe(m._quelle(_FalscheSignatur(), "d").get_uid() == "d",
       "abweichende Signaturen werden abgefangen")
try:
    m._quelle(_NurListe(), "gibtsnicht")
    pruefe(False, "unbekannte Kennung muss scheitern")
except RuntimeError as f:
    pruefe("neu auswählen" in str(f), "Nichtfund meldet sich deutsch")

pruefe(m.fehler_deutsch(RuntimeError("Bitte zuerst wählen.")) ==
       "Bitte zuerst wählen.", "eigene deutsche Texte bleiben unverändert")
satz = m.fehler_deutsch(AttributeError(
    "'SourceRegistry' object has no attribute 'lookup_by_uid'"))
pruefe(satz.startswith("Die Verbindung zu den Online-Konten") and
       "technische Angabe" in satz, "Technik-Fehler werden deutsch gerahmt")
pruefe(m.fehler_deutsch(ValueError(""), "Das Durchsuchen des Rechners")
       .startswith("Das Durchsuchen des Rechners") and
       "ValueError" in m.fehler_deutsch(ValueError("")),
       "leere Meldungen nennen die Fehlerklasse, Kontext ist wählbar")

print()
print("— Feiertage und Schulferien —")

import json as _json

gerufen = []


def _holer(url):
    gerufen.append(url)
    if "PublicHolidays" in url and "2026" in url:
        return _json.dumps([
            {"startDate": "2026-01-01", "endDate": "2026-01-01",
             "name": [{"language": "EN", "text": "New Year"},
                      {"language": "DE", "text": "Neujahr"}]},
            {"startDate": "2026-10-03", "endDate": "2026-10-03",
             "name": [{"language": "DE", "text": "Tag der Deutschen Einheit"}]},
            {"startDate": "kaputt", "name": [{"language": "DE", "text": "Unfug"}]},
            {"startDate": "2026-12-25", "name": []},
        ])
    if "SchoolHolidays" in url and "2026" in url:
        return _json.dumps([
            {"startDate": "2026-07-06", "endDate": "2026-08-18",
             "name": [{"language": "DE", "text": "Sommerferien"}]},
            {"startDate": "2026-10-12", "endDate": "2026-10-24",
             "name": [{"language": "DE", "text": "Herbstferien"}]},
        ])
    return "[]"


erg = m.feiertage_abrufen("de", "de-nw", [2026], True, _holer)
pruefe(len(erg["feiertage"]) == 4,
       "2 Feiertage und 2 Ferienabschnitte erkannt (%d)" % len(erg["feiertage"]))
pruefe(erg["feiertage"][0]["name"] == "Neujahr",
       "deutscher Name wird bevorzugt")
sommer = [f for f in erg["feiertage"] if f["name"] == "Sommerferien"][0]
pruefe(sommer["von"] == "2026-07-06" and sommer["bis"] == "2026-08-18"
       and sommer["art"] == "school-holiday", "Ferienzeitraum vollständig")
einheit = [f for f in erg["feiertage"] if "Einheit" in f["name"]][0]
pruefe(einheit["bis"] == einheit["von"] and einheit["art"] == "public-holiday",
       "eintägiger Feiertag ohne Enddatum")
pruefe("2 Feiertage" in erg["bericht"] and "2 Ferienabschnitte" in erg["bericht"],
       "Bericht: " + erg["bericht"])
pruefe(any("subdivisionCode=DE-NW" in u for u in gerufen),
       "Bundesland wird an den Dienst weitergereicht")
pruefe(any("languageIsoCode=DE" in u for u in gerufen),
       "deutsche Sprache wird angefordert")

class _AntwortKopf:
    def __init__(self, laenge=None):
        self.laenge = laenge
    def get(self, name):
        return self.laenge if name == "Content-Length" else None

class _AntwortProbe:
    def __init__(self, roh, laenge=None, schritt=None):
        self.roh = roh
        self.headers = _AntwortKopf(laenge)
        self.gelesen = []
        self.schritt = schritt
    def read(self, menge):
        self.gelesen.append(menge)
        menge = min(menge, self.schritt) if self.schritt else menge
        teil, self.roh = self.roh[:menge], self.roh[menge:]
        return teil

antwort_probe = _AntwortProbe(b"x" * 32, "32")
pruefe(m.antwort_begrenzt_lesen(antwort_probe, 32, "zu groß") == b"x" * 32 and
       antwort_probe.gelesen == [33, 1],
       "HTTP-Antworten exakt an der Grenze werden begrenzt gelesen")
antwort_probe = _AntwortProbe(b"", "33")
try:
    m.antwort_begrenzt_lesen(antwort_probe, 32, "zu groß")
    antwort_zu_gross = False
except m.GroessenFehler:
    antwort_zu_gross = True
pruefe(antwort_zu_gross and not antwort_probe.gelesen,
       "zu große Content-Length wird vor dem Lesen abgewiesen")
try:
    m.antwort_begrenzt_lesen(_AntwortProbe(b"x" * 33), 32, "zu groß")
    chunk_zu_gross = False
except m.GroessenFehler:
    chunk_zu_gross = True
pruefe(chunk_zu_gross,
       "Antworten ohne Content-Length sind durch Limit plus ein Byte begrenzt")
try:
    m.antwort_begrenzt_lesen(
        _AntwortProbe(b"x" * 33, schritt=3), 32, "zu groß")
    kurzlesung_zu_gross = False
except m.GroessenFehler:
    kurzlesung_zu_gross = True
pruefe(kurzlesung_zu_gross,
       "wiederholte HTTP-Kurzlesungen umgehen das Gesamtlimit nicht")

def _holer_ferien_zu_gross(url):
    if "SchoolHolidays" in url:
        raise m.GroessenFehler("Der Feiertagsdienst hat zu viele Daten geschickt.")
    return _holer(url)

try:
    m.feiertage_abrufen("DE", "DE-NW", [2026], True,
                        _holer_ferien_zu_gross)
    ferien_zu_gross = False
except m.GroessenFehler:
    ferien_zu_gross = True
pruefe(ferien_zu_gross,
       "eine zu große Schulferienantwort wird nicht still übersprungen")

_kumulativ_probe = "[]" + (" " * (m.FEIERTAG_ABRUF_MAX // 2))
try:
    m.feiertage_abrufen("DE", "DE-NW", [2026], True,
                        lambda _url: _kumulativ_probe)
    abruf_zu_gross = False
except m.GroessenFehler:
    abruf_zu_gross = True
pruefe(abruf_zu_gross,
       "mehrere einzeln gültige Antworten überschreiten zusammen nicht acht Megabyte")
del _kumulativ_probe

regional_alt = dict(m._REGIONAL)
gettext_feiertag_alt, ngettext_feiertag_alt = m._, m.ngettext
en_feiertag = m.gettext_uebersetzung("en")
m._REGIONAL["language"] = "en"
m._, m.ngettext = en_feiertag.gettext, en_feiertag.ngettext
gerufen.clear()
erg_en = m.feiertage_abrufen("DE", "DE-NW", [2026], True, _holer)
pruefe(any("languageIsoCode=EN" in u for u in gerufen) and
       not any("languageIsoCode=DE" in u for u in gerufen),
       "englische Oberfläche fordert englische Providernamen an")
pruefe(erg_en["feiertage"][0]["name"] == "New Year" and
       all(eintrag["art"] in ("public-holiday", "school-holiday")
           for eintrag in erg_en["feiertage"]),
       "englischer Providername wird bevorzugt und Feiertagsarten bleiben stabil")
pruefe("2 public holidays" in erg_en["bericht"] and
       "2 holiday periods" in erg_en["bericht"],
       "englischer Feiertagsbericht verwendet korrekte Pluralformen")
m._REGIONAL.clear()
m._REGIONAL.update(regional_alt)
m._, m.ngettext = gettext_feiertag_alt, ngettext_feiertag_alt

gerufen.clear()
erg = m.feiertage_abrufen(
    "DE", "", [2026], True, _holer,
    regionen=[["DE-NW", "Nordrhein-Westfalen"], ["DE-BY", "Bayern"]],
    region_erforderlich=True)
pruefe(any("subdivisionCode=DE-NW" in u for u in gerufen) and
       any("subdivisionCode=DE-BY" in u for u in gerufen),
       "„Alle Bundesländer“ fragt jede ausdrücklich gewählte Region ab")
pruefe(len(erg["feiertage"]) == 4,
       "gleiche Einträge der Bundesländer werden zusammengefasst")
pruefe(all("alle Bundesländer" in f["name"] for f in erg["feiertage"]),
       "zusammengefasste Einträge nennen ihre regionale Geltung")

try:
    m.feiertage_abrufen(
        "DE", "", [2026], True, _holer, region_erforderlich=True)
    pruefe(False, "Land allein müsste bei regionalen Angaben abgewiesen werden")
except RuntimeError as f:
    pruefe("Bundesland" in str(f) and "Alle Bundesländer" in str(f),
           "ohne Bundesland kommt ein verständlicher Hinweis")

gerufen.clear()
erg = m.feiertage_abrufen("DE", "", [2026], False, _holer)
pruefe(all("SchoolHolidays" not in u for u in gerufen),
       "ohne Haken werden keine Ferien geholt")
pruefe(all("subdivisionCode" not in u for u in gerufen),
       "ohne Region keine Bundesland-Angabe")

gerufen.clear()
erg = m.feiertage_abrufen("DE", "DE-NW", [2026, 2026, 2027], True, _holer)
pruefe(erg["jahre"] == [2026, 2027], "Jahre werden entdoppelt und sortiert")
namen = [f["name"] for f in erg["feiertage"]]
pruefe(len(namen) == len(set(namen)), "keine doppelten Einträge")


def _holer_ferien_fehlt(url):
    if "SchoolHolidays" in url:
        raise RuntimeError("Der Feiertagsdienst hat die Anfrage abgelehnt.")
    return _holer(url)


erg = m.feiertage_abrufen("DE", "DE-NW", [2026], True, _holer_ferien_fehlt)
pruefe(len(erg["feiertage"]) == 2,
       "fehlende Ferien verhindern die Feiertage nicht")


def _holer_kaputt(url):
    return "kein JSON"


try:
    m.feiertage_abrufen("DE", "", [2026], False, _holer_kaputt)
    pruefe(False, "unlesbare Antwort muss scheitern")
except RuntimeError as f:
    pruefe("unlesbare" in str(f), "unlesbare Antwort meldet sich deutsch")

for falsch, worum in ((("", "", [2026]), "ohne Land"), (("DE", "", []), "ohne Jahr")):
    try:
        m.feiertage_abrufen(falsch[0], falsch[1], falsch[2], False, _holer)
        pruefe(False, worum + " muss scheitern")
    except RuntimeError as f:
        pruefe("Bitte" in str(f), worum + ": höflicher deutscher Hinweis")

pruefe(m._ist_iso("2026-02-29") is False and m._ist_iso("2028-02-29") is True,
       "Datumsprüfung erkennt Schaltjahre")

print()
print("— Drei-Tage-Wetter —")
wetter_aufrufe = []
wetter_probe = json.dumps({
    "nearest_area": [{"areaName": [{"value": "Duisburg"}]}],
    "weather": [
        {"date": "2026-07-30", "mintempC": "17", "maxtempC": "25",
         "hourly": [{"time": "1200", "weatherCode": "113",
                     "lang_de": [{"value": "Sonnig"}],
                     "weatherDesc": [{"value": "Sunny"}]}]},
        {"date": "2026-07-31", "mintempC": "15", "maxtempC": "21",
         "hourly": [{"time": "1200", "weatherCode": "296",
                     "lang_de": [{"value": "Leichter Regen"}],
                     "weatherDesc": [{"value": "Light rain"}]}]},
        {"date": "2026-08-01", "mintempC": "16", "maxtempC": "24",
         "hourly": [{"time": "1200", "weatherCode": "116",
                     "weatherDesc": [{"value": "Partly cloudy"}]}]}
    ]})


def _wetter_holer(url):
    wetter_aufrufe.append(url)
    return wetter_probe


wetter = m.wetter_abrufen("47051 Duisburg", _wetter_holer)
pruefe(wetter["quelle"] == "adresse" and wetter["ort"] == "Duisburg",
       "Ort aus der eigenen Anschrift wird bevorzugt")
pruefe(len(wetter["tage"]) == 3 and wetter["tage"][0]["beschreibung"] == "Sonnig" and
       wetter["tage"][1]["min"] == 15 and wetter["tage"][1]["max"] == 21,
       "drei Tage mit deutscher Beschreibung und Temperaturen gelesen")
pruefe("47051%20Duisburg" in wetter_aufrufe[-1] and
       "format=j1" in wetter_aufrufe[-1] and "lang=de" in wetter_aufrufe[-1],
       "Ort und deutsche Sprache werden sicher an wttr.in übergeben")

wetter_regional_alt = dict(m._REGIONAL)
wetter_gettext_alt, wetter_ngettext_alt = m._, m.ngettext
wetter_en = m.gettext_uebersetzung("en")
m._REGIONAL["language"] = "en"
m._, m.ngettext = wetter_en.gettext, wetter_en.ngettext
wetter_aufrufe.clear()
wetter_englisch = m.wetter_abrufen("47051 Duisburg", _wetter_holer)
pruefe("lang=en" in wetter_aufrufe[-1] and
       wetter_englisch["tage"][0]["beschreibung"] == "Sunny" and
       wetter_englisch["ort"] == "Duisburg" and
       wetter_englisch["quelle"] == "adresse",
       "englischer Wetterabruf bewahrt Ort und fordert englische Providertexte an")
try:
    m.wetter_abrufen("Duisburg", lambda _url: "kein JSON")
    wetter_fehler_en = ""
except RuntimeError as wetterfehler:
    wetter_fehler_en = str(wetterfehler)
pruefe(wetter_fehler_en == "The weather service returned unreadable data.",
       "englischer Wetterparserfehler kommt aus gettext")
m._REGIONAL.clear()
m._REGIONAL.update(wetter_regional_alt)
m._, m.ngettext = wetter_gettext_alt, wetter_ngettext_alt

wetter = m.wetter_abrufen("", _wetter_holer, lambda: {
    "felder": {"postalcode": "47051", "l": "Duisburg"}})
pruefe(wetter["quelle"] == "libreoffice" and
       "47051%20Duisburg" in wetter_aufrufe[-1],
       "LibreOffice-Ort ist der zweite Rückfall")
wetter = m.wetter_abrufen("", _wetter_holer, lambda: {"felder": {}})
pruefe(wetter["quelle"] == "ip" and "/?format=j1" in wetter_aufrufe[-1],
       "ohne gespeicherten Ort bleibt die ungefähre IP-Ermittlung")
wetter_aufrufe.clear()
wetter = m.wetter_abrufen(
    "", _wetter_holer, lambda: {"felder": {}}, ohne_ort_abrufen=False)
pruefe(wetter["ohneOrt"] and wetter["quelle"] == "none" and
       not wetter["tage"] and not wetter_aufrufe,
       "mit Datenschutzoption erfolgt ohne Ort keinerlei Wetter-Netzwerkzugriff")
wetter = m.wetter_abrufen(
    "", _wetter_holer,
    lambda: {"felder": {"postalcode": "47051", "l": "Duisburg"}},
    ohne_ort_abrufen=False)
pruefe(wetter["quelle"] == "libreoffice" and len(wetter_aufrufe) == 1,
       "ein lokaler LibreOffice-Ort bleibt trotz IP-Sperre verwendbar")
wetter_aufrufe.clear()
wetter = m.wetter_abrufen(
    "47051 Duisburg", _wetter_holer, lambda: {"felder": {}},
    ohne_ort_abrufen=False)
pruefe(wetter["quelle"] == "adresse" and len(wetter_aufrufe) == 1,
       "ein ausdrücklich gespeicherter Ort bleibt trotz IP-Sperre verwendbar")

class _WetterFenster:
    antworten = []
    def antwort(self, name, nutzlast):
        self.antworten.append((name, nutzlast))

wetter_abrufen_alt = m.wetter_abrufen
wetter_bridge_werte = []
try:
    m.wetter_abrufen = lambda ort, ohne_ort_abrufen=True: (
        wetter_bridge_werte.append((ort, ohne_ort_abrufen)) or
        {"ok": True, "ohneOrt": True, "tage": []})
    wetter_fenster = _WetterFenster()
    m.Fenster._wetter_arbeit(wetter_fenster, {
        "ort": "", "ohneOrtAbrufen": False, "kennung": 17})
    m.Fenster._wetter_arbeit(wetter_fenster, {"ort": "", "kennung": 18})
finally:
    m.wetter_abrufen = wetter_abrufen_alt
pruefe(wetter_bridge_werte == [("", False), ("", True)] and
       [antwort[1]["kennung"] for antwort in wetter_fenster.antworten] == [17, 18],
       "die Bridge überträgt Datenschutzoption und Kompatibilitätsvorgabe korrekt")
try:
    m.wetter_abrufen("Duisburg", lambda _url: "kein JSON")
    pruefe(False, "unlesbares Wetter muss scheitern")
except RuntimeError as f:
    pruefe("unlesbare" in str(f), "unlesbare Wetterantwort wird verständlich gemeldet")

print()
print("— Aktualisierungsprüfung —")
with open(os.path.join(os.path.dirname(PFAD), "..", "debian", "changelog"), encoding="utf-8") as datei:
    paket_fassung = re.match(r"magnolie-organizer \(([^)]+)\)", datei.readline()).group(1)
pruefe(m.PROGRAMM_FASSUNG == paket_fassung, "Programmkern trägt die neue Fassung")
desktop_pfad = os.path.abspath(os.path.join(os.path.dirname(PFAD), "..",
                                             "magnolie-organizer.desktop"))
with open(desktop_pfad, encoding="utf-8") as datei:
    desktop_inhalt = datei.read()
pruefe("Actions=StartDebug;" in desktop_inhalt and
       "[Desktop Action StartDebug]" in desktop_inhalt and
       "Exec=magnolie-organizer --debug" in desktop_inhalt and
       "Name[de]=Magnolie Organizer im Debugmodus starten" in desktop_inhalt,
       "das Startmenü bietet einen lokalisierten Debugstart an")
projektwurzel = os.path.abspath(os.path.join(os.path.dirname(PFAD), ".."))
with open(os.path.join(projektwurzel, "debian", "rules"), encoding="utf-8") as datei:
    paketregeln = datei.read()
with open(os.path.join(projektwurzel, "debian", "control"), encoding="utf-8") as datei:
    paketsteuerung = datei.read()
with open(os.path.join(projektwurzel, "werkzeuge", "release_bauen.sh"),
          encoding="utf-8") as datei:
    release_regeln = datei.read()
with open(os.path.join(projektwurzel, "werkzeuge", "appimage_bauen.sh"),
          encoding="utf-8") as datei:
    appimage_regeln = datei.read()
with open(os.path.join(projektwurzel, "debian", "tests", "control"),
          encoding="utf-8") as datei:
    autopkgtest_steuerung = datei.read()
pruefe("$(JS_LAUFER) pruefungen/test.js" in paketregeln and
       "pruefungen/test_import_export_vertrag.py" in paketregeln and
       "filter nocheck,$(DEB_BUILD_OPTIONS)" in paketregeln,
       "der Paketbau führt DOM- und Import-/Export-Vertragstests aus")
pruefe(all(text in release_regeln for text in (
       "pruefungen/test_parser.py", "pruefungen/test_import_export_vertrag.py",
       "pruefungen/test_telefon.py", "pruefungen/test_eds_adressbuch_sync.py",
       "pruefungen/test_wiederherstellungsjournal.py",
       "pruefungen/test.js", "pruefungen/last_test.py", "pruefungen/last_test.js",
       "werkzeuge/appimage_jammy_bauen.sh", "pruefungen/test_appimage.sh",
       "pruefungen/test_appimage_arch.sh",
       '"$LIVE_SOURCE/werkzeuge/release_gate.py" seal --root "$LIVE_ROOT"',
       '"$LIVE_SOURCE/werkzeuge/release_gate.py" promote --root "$LIVE_ROOT"',
       '--approval "$3" --accept-candidate "$4"')) and
       release_regeln.index("pruefungen/test_appimage_arch.sh") <
       release_regeln.index('"$LIVE_SOURCE/werkzeuge/release_gate.py" seal') and
       re.search(r"(?m)^set -[^\n]*e", release_regeln) is not None,
       "der Releasebau sperrt Freigaben ohne alle fachlichen und AppImage-Tests")
pruefe("LINUXDEPLOY_SHA=" in appimage_regeln and
       "APPIMAGETOOL_SHA=" in appimage_regeln and
       "sha256sum -c" in appimage_regeln,
       "der AppImage-Bau prüft seine festgeschriebenen Bauwerkzeuge")
with open(os.path.join(projektwurzel, "werkzeuge", "appimage_jammy_bauen.sh"),
          encoding="utf-8") as datei:
    jammy_regeln = datei.read()
pruefe("ubuntu-base-22.04.5" in jammy_regeln and "BASIS_SHA=" in jammy_regeln and
       "SNAPSHOT=" in jammy_regeln and "PROOT_SHA=" in jammy_regeln and
       "TALLOC_SHA=" in jammy_regeln and '"$PROOT" -0 -r' in jammy_regeln and
       "elf_glibc_pruefen.py" in appimage_regeln,
       "das AppImage entsteht rootlos aus einer festgeschriebenen alten Buildbasis")
pruefe("SOURCE_DATE_EPOCH ?= $(shell dpkg-parsechangelog -STimestamp)" in
       paketregeln and "export SOURCE_DATE_EPOCH" in paketregeln,
       "der Paketbau verwendet den Changelog-Zeitpunkt reproduzierbar")
pruefe("nodejs" in paketsteuerung and "node-jsdom" in paketsteuerung,
       "die Debian-Bauabhängigkeiten enthalten Node.js und jsdom")
pruefe(paketsteuerung.count("python3-zeroconf") == 2,
       "Build und Laufzeit installieren den portablen mDNS-Adapter")
pruefe(paketsteuerung.count("python3-qrcode") == 2 and
       "python3-qrcode" in jammy_regeln,
       "Build, Laufzeit und AppImage installieren den QR-Erzeuger")
autopkgtest_skripte = ("installed", "web-dom", "gtk-webkit", "systemd-user", "ufw")
pruefe(all("Tests: " + name in autopkgtest_steuerung for name in autopkgtest_skripte) and
       autopkgtest_steuerung.count("isolation-machine") == 2 and
       "breaks-testbed" in autopkgtest_steuerung and
       all(os.access(os.path.join(projektwurzel, "debian", "tests", name), os.X_OK)
           for name in autopkgtest_skripte),
       "autopkgtest deckt installierte Dateien, WebKit, systemd und UFW sicher ab")
pruefe(m.versions_schluessel("v1.30.0-2") > m.versions_schluessel("1.30.0"),
       "Fassungen mit Nachtragsnummer werden richtig verglichen")
from cryptography.hazmat.primitives import serialization as update_serialisierung
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
update_privat = Ed25519PrivateKey.generate()
update_oeffentlich = m.base64.b64encode(update_privat.public_key().public_bytes(
    update_serialisierung.Encoding.Raw,
    update_serialisierung.PublicFormat.Raw)).decode("ascii")
update_summe = "ab" * 32
# The signed fixtures exercise an installed 2.0.18 upgrading to 2.0.19,
# independently of the current source release checked above.
from unittest.mock import patch as update_patch
update_installierte_fassung = update_patch.object(m, "PROGRAMM_FASSUNG", "2.0.18")
update_installierte_fassung.start()
update_paket = m.UPDATE_BASIS + "magnolie-organizer_2.0.19_all.deb"
update_signatur = m.base64.b64encode(update_privat.sign(
    m.update_signatur_nachricht("2.0.19", update_paket, update_summe))).decode("ascii")
update_xml = ("<?xml version='1.0'?><update><version>2.0.19</version>"
               "<deb>" + update_paket + "</deb><sha256>" + update_summe +
               "</sha256><signature>" + update_signatur + "</signature></update>")
version, paket = m.update_info_lesen(update_xml)
pruefe(version == "2.0.19" and paket.endswith("_2.0.19_all.deb"),
       "update.xml liefert Fassung und Paketadresse")
update_neu = m.update_pruefen(lambda _url: update_xml, update_oeffentlich)
pruefe(update_neu["ok"] and not update_neu["aktuell"] and
       update_neu["version"] == "2.0.19" and
       update_neu["sha256"] == update_summe and update_neu["url"] == update_paket,
       "eine Debian-Installation erhält das signierte Debian-Paket")
appimage_paket = m.UPDATE_BASIS + "Magnolie-Organizer-2.0.19-x86_64.AppImage"
appimage_summe = "ef" * 32
appimage_xml = ("<update><version>2.0.19</version><deb>" + update_paket +
                 "</deb><sha256>" + update_summe + "</sha256><appimage>"
                 "<architecture>x86_64</architecture><url>" + appimage_paket +
                 "</url><sha256>" + appimage_summe + "</sha256></appimage>")
appimage_signatur = m.base64.b64encode(update_privat.sign(
    m.update_signatur_nachricht("2.0.19", update_paket, update_summe,
                               appimage_paket, appimage_summe))).decode("ascii")
appimage_xml += "<signature>" + appimage_signatur + "</signature></update>"
appimage_umgebung = os.environ.get("APPIMAGE")
os.environ["APPIMAGE"] = "/tmp/Magnolie-Organizer.AppImage"
try:
    appimage_update = m.update_pruefen(lambda _url: appimage_xml, update_oeffentlich)
    appimage_fehlt = m.update_pruefen(lambda _url: update_xml, update_oeffentlich)
finally:
    if appimage_umgebung is None:
        os.environ.pop("APPIMAGE", None)
    else:
        os.environ["APPIMAGE"] = appimage_umgebung
pruefe(appimage_update["ok"] and not appimage_update["aktuell"] and
       appimage_update["url"] == appimage_paket and
       appimage_update["sha256"] == appimage_summe and not appimage_fehlt["ok"],
       "eine AppImage-Installation erhält nur das passende geprüfte AppImage")
aarch64_paket = m.UPDATE_BASIS + "Magnolie-Organizer-2.0.19-aarch64.AppImage"
aarch64_xml = ("<update><version>2.0.19</version><deb>" + update_paket +
               "</deb><sha256>" + update_summe + "</sha256><appimage>"
               "<architecture>aarch64</architecture><url>" + aarch64_paket +
               "</url><sha256>" + appimage_summe + "</sha256></appimage>")
aarch64_signatur = m.base64.b64encode(update_privat.sign(
    m.update_signatur_nachricht("2.0.19", update_paket, update_summe,
                               aarch64_paket, appimage_summe))).decode("ascii")
aarch64_geprueft = m.update_manifest_pruefen(
    aarch64_xml + "<signature>" + aarch64_signatur + "</signature></update>",
    update_oeffentlich)
pruefe(aarch64_geprueft["url"] == update_paket and not aarch64_geprueft["appimage"],
       "ein signierter fremder AppImage-Abschnitt sperrt das Debian-Update nicht")
aktuell_paket = m.UPDATE_BASIS + "magnolie-organizer_2.0.16_all.deb"
aktuell_signatur = m.base64.b64encode(update_privat.sign(
    m.update_signatur_nachricht("2.0.16", aktuell_paket, update_summe))).decode("ascii")
aktuell_xml = ("<update><version>2.0.16</version><deb>" + aktuell_paket +
               "</deb><sha256>" + update_summe + "</sha256><signature>" +
               aktuell_signatur + "</signature></update>")
update_aktuell = m.update_pruefen(lambda _url: aktuell_xml, update_oeffentlich)
pruefe(update_aktuell["ok"] and update_aktuell["aktuell"] and
       update_aktuell["version"] == "2.0.16" and not update_aktuell["url"],
       "dieselbe signierte Fassung gilt als aktuell")
alt_paket = m.UPDATE_BASIS + "magnolie-organizer_2.0.0_all.deb"
alt_signatur = m.base64.b64encode(update_privat.sign(
    m.update_signatur_nachricht("2.0.0", alt_paket, update_summe))).decode("ascii")
alt_xml = ("<update><version>2.0.0</version><deb>" + alt_paket +
           "</deb><sha256>" + update_summe + "</sha256><signature>" +
           alt_signatur + "</signature></update>")
update_alt = m.update_pruefen(lambda _url: alt_xml, update_oeffentlich)
pruefe(update_alt["ok"] and update_alt["aktuell"] and
       update_alt["version"] == "2.0.0" and not update_alt["url"],
       "eine ältere signierte Fassung wird nicht als Update angeboten")
handbuch_paket = m.UPDATE_BASIS + "magnolie-handbuch_1.9.8_all.deb"
handbuch_summe = "cd" * 32
handbuch_signatur = m.base64.b64encode(update_privat.sign(
    m.update_signatur_nachricht("2.0.16", aktuell_paket, update_summe,
                               manual_version="1.9.8", manual_linux=handbuch_paket,
                               manual_linux_sha=handbuch_summe))).decode("ascii")
handbuch_xml = ("<update><version>2.0.16</version><deb>" + aktuell_paket +
    "</deb><sha256>" + update_summe + "</sha256><manual><version>1.9.8</version>"
    "<linux><deb>" + handbuch_paket + "</deb><sha256>" + handbuch_summe +
    "</sha256></linux></manual><signature>" + handbuch_signatur +
    "</signature></update>")
handbuch_update = m.update_pruefen(lambda _url: handbuch_xml, update_oeffentlich)
pruefe(handbuch_update["ok"] and handbuch_update["aktuell"] and
       handbuch_update["version"] == "2.0.16" and
       handbuch_update["handbuch"] == {"version": "1.9.8",
       "url": handbuch_paket, "sha256": handbuch_summe, "platform": "linux"},
       "verschachtelte Handbuchdaten verändern die Organizerfelder nicht")
pruefe(bool(handbuch_update.get("handbuch")) and
       m._LETZTES_HANDBUCH_MANIFEST == handbuch_update["handbuch"],
       "der Handbuchdownload wird an das zuletzt validierte Manifest gebunden")
falsches_handbuch_paket = m.UPDATE_BASIS + "magnolie-organizer_1.9.8_all.deb"
falsche_handbuch_signatur = m.base64.b64encode(update_privat.sign(
    m.update_signatur_nachricht("2.0.16", aktuell_paket, update_summe,
                               manual_version="1.9.8",
                               manual_linux=falsches_handbuch_paket,
                               manual_linux_sha=handbuch_summe))).decode("ascii")
ungueltiges_handbuch = m.update_manifest_pruefen(handbuch_xml.replace(
    handbuch_paket, falsches_handbuch_paket).replace(
    handbuch_signatur, falsche_handbuch_signatur), update_oeffentlich)
pruefe(ungueltiges_handbuch["handbuch"] == {},
       "ein Organizerpaket wird nicht als Handbuchdownload angeboten")
pruefe(bool(ungueltiges_handbuch.get("handbuchFehler")),
       "ein ungültiger Handbuchabschnitt wird trotz gültigem Organizer gemeldet")
for falsches_paket in (handbuch_paket + "?download=1",
                       m.UPDATE_BASIS + "magnolie-handbuch_1.9.9_all.deb",
                       "https://example.org/magnolie-handbuch_1.9.8_all.deb"):
    pruefe(not m._handbuch_update_url_erlaubt(falsches_paket, "1.9.8"),
           "Handbuchadresse, Dateiname und Version werden strikt gebunden")
altes_update_xml = ("<update><version>2.0.16</version><deb>" +
                    update_paket + "</deb></update>")
update_abrufe = []
update_ohne_schluessel = m.update_pruefen(
    lambda url: update_abrufe.append(url) or altes_update_xml, "")
pruefe(not update_ohne_schluessel["ok"] and not update_abrufe and
       "schlüssel" in update_ohne_schluessel["fehler"].lower(),
       "ein leerer Release-Schlüssel sperrt die Aktualisierung vor dem Netzabruf")
update_abrufe = []
update_mit_ungueltigem_schluessel = m.update_pruefen(
    lambda url: update_abrufe.append(url) or update_xml, "kein-base64!")
pruefe(not update_mit_ungueltigem_schluessel["ok"] and not update_abrufe,
       "ein ungültiger Release-Schlüssel sperrt die Aktualisierung vor dem Netzabruf")
update_ohne_signatur = m.update_pruefen(
    lambda _url: altes_update_xml.replace("</deb>", "</deb><sha256>" +
                                           update_summe + "</sha256>"),
    update_oeffentlich)
pruefe(not update_ohne_signatur["ok"] and "signatur" in
       update_ohne_signatur["fehler"].lower(),
       "ein Manifest ohne Signatur wird mit gültigem Release-Schlüssel abgewiesen")
update_veraendert = m.update_pruefen(
    lambda _url: update_xml.replace("<version>2.0.19</version>",
                                    "<version>2.0.20</version>"),
    update_oeffentlich)
pruefe(not update_veraendert["ok"] and any(text in
       update_veraendert["fehler"].lower() for text in
       ("invalid signature", "ungültige signatur")),
       "jede nachträgliche Änderung der Updateinformationen fällt auf")
update_oeffnungen = []
welcher_abgelehntes_update = m.shutil.which
m.shutil.which = lambda _name: "/usr/bin/xdg-open"
try:
    abgelehntes_oeffnen = m.update_paket_oeffnen(
        update_paket, lambda argumente: update_oeffnungen.append(argumente))
finally:
    m.shutil.which = welcher_abgelehntes_update
pruefe(not abgelehntes_oeffnen["ok"] and not update_oeffnungen and
       m._LETZTES_UPDATE_PAKET == "",
       "nach abgelehntem Manifest wird keine Download- oder Öffnungsfolge gestartet")
update_fremd = m.update_pruefen(lambda _url:
    "<update><version>9.0</version><deb>https://example.org/fremd.deb</deb>"
    "<sha256>" + update_summe + "</sha256><signature>" + update_signatur +
    "</signature></update>", update_oeffentlich)
pruefe(not update_fremd["ok"] and "erlaubte Paketadresse" in update_fremd["fehler"],
       "fremde Paketadressen werden abgewiesen")

with tempfile.TemporaryDirectory() as signier_ordner:
    privater_pfad = os.path.join(signier_ordner, "release.pem")
    paket_pfad = os.path.join(signier_ordner, "magnolie-organizer_9.8.7_all.deb")
    appimage_pfad = os.path.join(
        signier_ordner, "Magnolie-Organizer-9.8.7-x86_64.AppImage")
    xml_pfad = os.path.join(signier_ordner, "update.xml")
    with open(privater_pfad, "wb") as datei:
        datei.write(update_privat.private_bytes(
            update_serialisierung.Encoding.PEM,
            update_serialisierung.PrivateFormat.PKCS8,
            update_serialisierung.NoEncryption()))
    with open(paket_pfad, "wb") as datei:
        datei.write(b"reproduzierbares Testpaket")
    with open(appimage_pfad, "wb") as datei:
        datei.write(b"reproduzierbares AppImage")
    with open(xml_pfad, "w", encoding="utf-8") as datei:
        datei.write("<update><version>9.8.7</version><deb>" + m.UPDATE_BASIS +
                    os.path.basename(paket_pfad) + "</deb><appimage>"
                    "<architecture>x86_64</architecture><url>" + m.UPDATE_BASIS +
                    os.path.basename(appimage_pfad) + "</url></appimage></update>")
    signier_befehl = [sys.executable, os.path.join(
        projektwurzel, "werkzeuge", "update_signieren.py"),
        privater_pfad, xml_pfad, paket_pfad, appimage_pfad]
    os.chmod(privater_pfad, 0o640)
    unsicheres_ergebnis = subprocess.run(signier_befehl,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pruefe(unsicheres_ergebnis.returncode != 0,
           "das Releasewerkzeug weist einen zu offenen privaten Schlüssel ab")
    os.chmod(privater_pfad, 0o600)
    subprocess.run(signier_befehl, check=True,
        stdout=subprocess.DEVNULL)
    with open(xml_pfad, encoding="utf-8") as datei:
        signiertes_manifest = m.update_manifest_pruefen(
            datei.read(), update_oeffentlich)
    pruefe(signiertes_manifest["version"] == "9.8.7" and
           signiertes_manifest["sha256"] == hashlib.sha256(
               b"reproduzierbares Testpaket").hexdigest() and
           signiertes_manifest["appimage"]["sha256"] == hashlib.sha256(
               b"reproduzierbares AppImage").hexdigest(),
            "das Releasewerkzeug signiert Debian-Paket und AppImage gemeinsam")
update_aufrufe = []
m.update_pruefen(lambda _url: update_xml, update_oeffentlich)
welcher_update = m.shutil.which
m.shutil.which = lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
try:
    geoeffnet = m.update_paket_oeffnen(
        paket, lambda argumente: update_aufrufe.append(argumente))
finally:
    m.shutil.which = welcher_update
pruefe(geoeffnet["ok"] and update_aufrufe == [["/usr/bin/xdg-open", paket]],
       "freigegebenes Aktualisierungspaket wird im Browser geöffnet")
appimage_aufrufe = []
appimage_umgebung = os.environ.get("APPIMAGE")
os.environ["APPIMAGE"] = "/tmp/Magnolie-Organizer.AppImage"
try:
    m.update_pruefen(lambda _url: appimage_xml, update_oeffentlich)
finally:
    if appimage_umgebung is None:
        os.environ.pop("APPIMAGE", None)
    else:
        os.environ["APPIMAGE"] = appimage_umgebung
m.shutil.which = lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
try:
    appimage_geoeffnet = m.update_paket_oeffnen(
        appimage_paket, lambda argumente: appimage_aufrufe.append(argumente))
finally:
    m.shutil.which = welcher_update
pruefe(appimage_geoeffnet["ok"] and
       appimage_aufrufe == [["/usr/bin/xdg-open", appimage_paket]],
       "freigegebenes AppImage wird im Browser geöffnet")
handbuch_download_aufrufe = []
m.shutil.which = lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
try:
    handbuch_download = m.handbuch_paket_oeffnen(
        handbuch_paket, lambda argumente: handbuch_download_aufrufe.append(argumente))
finally:
    m.shutil.which = welcher_update
pruefe(handbuch_download["ok"] and handbuch_download_aufrufe ==
       [["/usr/bin/xdg-open", handbuch_paket]] and
       not m.handbuch_paket_oeffnen(update_paket)["ok"],
       "nur ein freigegebenes Handbuchpaket wird zum Download geöffnet")

handbuch_aufrufe = []
welcher_handbuch = m.shutil.which
m.shutil.which = lambda name: ("/usr/bin/magnolie-handbuch"
                                 if name == "magnolie-handbuch" else None)
try:
    pruefe(m.handbuch_installiert(), "installiertes Handbuch wird erkannt")
    handbuch_erg = m.handbuch_oeffnen(
        lambda argumente: handbuch_aufrufe.append(argumente))
finally:
    m.shutil.which = welcher_handbuch
pruefe(handbuch_erg["ok"] and
       handbuch_aufrufe == [["/usr/bin/magnolie-handbuch"]],
       "Handbuch wird über seinen festen Programmweg geöffnet")
m.shutil.which = lambda _name: None
try:
    pruefe(not m.handbuch_installiert() and
           not m.handbuch_oeffnen()["ok"],
           "fehlendes Handbuch wird verständlich gemeldet")
finally:
    m.shutil.which = welcher_handbuch

print()
update_installierte_fassung.stop()
print("— Rechtschreibprüfung: Sprachen —")

pruefe(m.rechtschreib_sprachen("de") == ["de_DE", "de"],
       "deutsche Oberfläche verwendet deutsche Wörterbücher")
pruefe(m.rechtschreib_sprachen("en") == ["en_US", "en"],
       "englische Oberfläche verwendet englische Wörterbücher")
pruefe(m.rechtschreib_sprachen("system", {"LANG": "en_GB.UTF-8"}) ==
       ["en_GB", "en_US", "en"],
       "englische Systemumgebung behält ihren regionalen Rückfall")
pruefe(m.rechtschreib_sprachen("system", {"LANG": "de_AT@euro"}) ==
       ["de_AT", "de_DE", "de"],
       "deutsche Systemumgebung behält ihren regionalen Rückfall")
pruefe(m.rechtschreib_sprachen("system", {"LANG": "fr_FR.UTF-8"}) ==
       ["en_US", "en"] and
       m.rechtschreib_sprachen("system", {"LANG": "C"}) == ["en_US", "en"],
       "nicht unterstützte Systemsprachen folgen dem englischen UI-Rückfall")
pruefe(m.woerterbuch_paket("de") == "hunspell-de-de" and
       m.woerterbuch_paket("en") == "hunspell-en-us" and
       m.woerterbuch_paket("de-AT") == "hunspell-de-at" and
       m.woerterbuch_paket("en-GB") == "hunspell-en-gb",
       "Wörterbuchhinweise nennen das zur Sprache passende Hunspell-Paket")

print()
print("— Rechtschreibvorschläge —")


class _BuchAttrappe:
    def __init__(self):
        self.bekannt = {"Milch", "Brot", "Termin"}
        self.aufgenommen = []

    def check(self, wort):
        return wort in self.bekannt

    def suggest(self, wort):
        return ["Milch", wort, "Molch"] if wort == "Milhc" else []

    def add(self, wort):
        self.aufgenommen.append(wort)
        self.bekannt.add(wort)


buch = _BuchAttrappe()
erg = m.rechtschreib_pruefen("Milch", buch)
pruefe(erg["richtig"] is True and not erg["vorschlaege"],
       "bekanntes Wort gilt als richtig")
erg = m.rechtschreib_pruefen("Milhc", buch)
pruefe(erg["richtig"] is False, "Tippfehler wird erkannt")
pruefe(erg["vorschlaege"] == ["Milch", "Molch"],
       "Vorschläge ohne das Wort selbst: %r" % erg["vorschlaege"])
erg = m.rechtschreib_pruefen("Krixkrax", buch)
pruefe(erg["richtig"] is False and erg["vorschlaege"] == [],
       "ohne Vorschläge bleibt die Liste leer")
erg = m.rechtschreib_pruefen("   ", buch)
pruefe(erg["richtig"] is True, "Leerraum wird nicht bemängelt")

erg = m.wort_aufnehmen("Duisburg", buch)
pruefe(erg["ok"] is True and "Duisburg" in buch.aufgenommen,
       "Wort wird ins Wörterbuch aufgenommen")
pruefe(m.rechtschreib_pruefen("Duisburg", buch)["richtig"] is True,
       "aufgenommenes Wort gilt danach als richtig")
erg = m.wort_aufnehmen("", buch)
pruefe(erg["ok"] is False and "kein Wort" in erg["fehler"],
       "leeres Wort wird höflich abgelehnt")


class _BuchKaputt:
    def check(self, wort):
        raise RuntimeError("Wörterbuch kaputt")


erg = m.rechtschreib_pruefen("Milch", _BuchKaputt())
pruefe(erg["richtig"] is True and erg["fehler"],
       "ein kaputtes Wörterbuch bemängelt nichts, meldet aber: " + erg["fehler"])

m._WOERTERBUCH["geprueft"] = True
m._WOERTERBUCH["buch"] = None
m._WOERTERBUCH["fehler"] = "Baustein fehlt: sudo apt install python3-enchant"
erg = m.rechtschreib_pruefen("Milhc")
pruefe(erg["richtig"] is True and "python3-enchant" in erg["fehler"],
       "fehlendes Wörterbuch nennt den Nachrüstbefehl")
erg = m.wort_aufnehmen("Milhc")
pruefe(erg["ok"] is False and "python3-enchant" in erg["fehler"],
       "Aufnehmen ohne Wörterbuch meldet sich ebenso")


class _EnchantAttrappe:
    def __init__(self):
        self.aufgerufen = []

    @staticmethod
    def dict_exists(_sprache):
        return True

    def DictWithPWL(self, sprache, _pfad):
        self.aufgerufen.append(sprache)
        return _BuchAttrappe()

    def Dict(self, sprache):
        self.aufgerufen.append(sprache)
        return _BuchAttrappe()


enchant_alt = sys.modules.get("enchant")
woerter_datei_alt = m.eigene_woerter_datei
enchant_attrappe = _EnchantAttrappe()
sys.modules["enchant"] = enchant_attrappe
m.eigene_woerter_datei = lambda: os.path.join(
    tempfile.mkdtemp(prefix="magnolie-woerter-"), "eigene.txt")
m._WOERTERBUCH.update({"geprueft": False, "buch": None, "fehler": ""})
m._WOERTERBUECHER.clear()
m._WOERTERBUECHER["de"] = m._WOERTERBUCH
try:
    deutsches_buch = m.woerterbuch_laden("de")
    englische_buecher = []
    threads = [m.threading.Thread(
        target=lambda: englische_buecher.append(m.woerterbuch_laden("en")))
        for _index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
finally:
    m.eigene_woerter_datei = woerter_datei_alt
    if enchant_alt is None:
        del sys.modules["enchant"]
    else:
        sys.modules["enchant"] = enchant_alt
pruefe(enchant_attrappe.aufgerufen == ["de_DE", "en_US"] and
       deutsches_buch is not englische_buecher[0] and
       len({id(buch) for buch in englische_buecher}) == 1,
       "Wörterbücher werden getrennt je Sprache und threadsicher einmal geladen")

print()
print("— Fensterzustand —")

regional_ordner = tempfile.mkdtemp(prefix="magnolie-regional-")
regional_probe = os.path.join(regional_ordner, "locale.json")
regional = m.regional_einstellungen({"language": "fr-CH", "formatLocale": "en_US",
                                     "hourCycle": "h12", "firstDayOfWeek": "sunday",
                                     "weekRule": "fremd", "temperatureUnit": "fahrenheit",
                                     "timeZone": "America/New_York"})
pruefe(regional == {"language": "fr-CH", "formatLocale": "en-US",
                     "hourCycle": "h12", "firstDayOfWeek": "sunday",
                     "weekRule": "iso", "temperatureUnit": "fahrenheit",
                     "timeZone": "America/New_York", "homeCountry": "DE"},
       "Regionalwerte werden sprachunabhängig und begrenzt übernommen")
pruefe(m.regional_einstellungen_schreiben(regional, regional_probe) and
       m.regional_einstellungen_lesen(regional_probe) == regional,
       "frühe Regionalauswahl lässt sich unabhängig von verschlüsselten Daten speichern")
pruefe((os.stat(regional_probe).st_mode & 0o777) == 0o600,
       "Regionalauswahl ist nur für das eigene Benutzerkonto lesbar")
pruefe(m.regional_einstellungen({"language": "../../de", "timeZone": "../Berlin"}) ==
       m.REGIONAL_STANDARD,
       "ungültige Sprach- und Zeitzonenwerte fallen auf das deutsche Bestandsprofil zurück")
pruefe(m.gettext_uebersetzung("de").gettext("Settings") == "Einstellungen",
       "Python lädt denselben deutschen gettext-Katalog wie die Weboberfläche")
pruefe(m.gettext_uebersetzung("de").gettext("The backup file was not found.") ==
       "Die Sicherungsdatei wurde nicht gefunden." and
       m.gettext_uebersetzung("en").gettext("The backup file was not found.") ==
       "The backup file was not found.",
       "Sicherungsfehler folgen in Python der gewählten Sprache")
pruefe(m.gettext_uebersetzung("de").gettext("No word was provided.") ==
       "Es wurde kein Wort übergeben." and
       m.gettext_uebersetzung("en").gettext("No word was provided.") ==
       "No word was provided.",
       "Wörterbuchfehler folgen in Python der gewählten Sprache")
pruefe("python3-enchant" in m.gettext_uebersetzung("de").gettext(
       "A component for spelling suggestions is missing. Install it with:  "
       "sudo apt install %s") % m.PAKET_ENCHANT and
       m.PAKET_ENCHANT == "python3-enchant" and
       m.PAKET_WOERTER == "hunspell-de-de",
       "übersetzte Wörterbuchhinweise bewahren die Paketnamen")
resttexte = {
    "Importing the old data failed: %s": "Übernahme der alten Daten fehlgeschlagen: %s",
    "Warning: The data file could not be read (%s).":
        "Warnung: Datendatei nicht lesbar (%s).",
    "Copy stored at: %s": "Kopie abgelegt unter: %s",
    "The tray applet could not be started: %s":
        "Tray-Applet konnte nicht gestartet werden: %s",
    "Unreadable message from the interface: %s":
        "Unlesbare Nachricht aus der Oberfläche: %s",
    "Save rejected: The data is encrypted and has not been unlocked yet.":
        "Speichern abgelehnt: Die Daten sind verschlüsselt und noch nicht entsperrt.",
    "Saving failed: %s": "Speichern fehlgeschlagen: %s",
    "Backup failed: %s": "Sicherung fehlgeschlagen: %s",
    "GTK is not available": "GTK ist nicht verfügbar",
    "no reason given": "kein Grund genannt",
}
pruefe(all(m.gettext_uebersetzung("de").gettext(quelle) == deutsch and
           m.gettext_uebersetzung("en").gettext(quelle) == quelle
           for quelle, deutsch in resttexte.items()),
       "verbleibende Backend- und stderr-Texte folgen der gewählten Sprache")

class _DateiwahlProbe:
    def __init__(self):
        self.oeffnen = []
        self.speichern = []
        self.antworten = []
    def _datei_oeffnen(self, titel, filter_liste):
        self.oeffnen.append((titel, filter_liste))
        return None
    def _datei_speichern(self, titel, vorschlag, filter_liste):
        self.speichern.append((titel, vorschlag, filter_liste))
        return None
    def antwort(self, funktion, nutzlast):
        self.antworten.append((funktion, nutzlast))

gettext_alt, ngettext_alt = m._, m.ngettext
de_uebersetzung = m.gettext_uebersetzung("de")
en_uebersetzung = m.gettext_uebersetzung("en")
m._, m.ngettext = de_uebersetzung.gettext, de_uebersetzung.ngettext
pruefe(m._zaehl_satz("Evolution", 1, 2, 1) ==
       "Evolution: 1 Adresse, 2 Termine, 1 Aufgabe",
       "deutscher Rechner-Fundbericht verwendet korrekte Pluralformen")
sync_zaehler = {"lokal_neu": 1, "remote_neu": 2,
                "lokal_geaendert": 1, "remote_geaendert": 2,
                "lokal_geloescht": 1, "remote_geloescht": 0}
pruefe(m._sync_satz(m._("Appointments"), sync_zaehler, 2) ==
       "Termine: 1 übernommen, 2 hochgegeben, 3 abgeglichen, 1 gelöscht, 2 Fehler.",
       "deutscher EDS-Bericht ist vollständig und grammatisch stabil")
m._, m.ngettext = en_uebersetzung.gettext, en_uebersetzung.ngettext
dateiwahl_probe = _DateiwahlProbe()
m.Fenster.bei_import(dateiwahl_probe, {"art": "ics"})
m.Fenster.bei_export(dateiwahl_probe, {"art": "ics-termine", "daten": []})
m.Fenster.bei_export(dateiwahl_probe, {"art": "ldif-adressen", "daten": []})
pruefe(m._zaehl_satz("Evolution", 1, 2, 1) ==
       "Evolution: 1 contact, 2 appointments, 1 task",
       "englischer Rechner-Fundbericht verwendet korrekte Pluralformen")
pruefe(m._sync_satz(m._("Appointments"), sync_zaehler, 2) ==
       "Appointments: 1 received, 2 uploaded, 3 synchronized, 1 deleted, 2 errors.",
       "englischer EDS-Bericht verwendet vollständige gettext-Texte")
try:
    m._quelle(_NurListe(), "provider-uid-unveraendert")
    englischer_quellfehler = ""
except RuntimeError as quellfehler:
    englischer_quellfehler = str(quellfehler)
pruefe(englischer_quellfehler ==
       "The selected source was not found. Select it again in Settings.",
       "englischer Quellenfehler lässt die technische Kennung aus dem Text")
pruefe(dateiwahl_probe.oeffnen[0][0] == "Import calendar file" and
       dateiwahl_probe.oeffnen[0][1][0] == ("iCalendar (*.ics)", "*.ics") and
       dateiwahl_probe.oeffnen[0][1][-1] == ("All files", "*"),
       "englische Importauswahl bewahrt Dateimuster und Formate")
pruefe(dateiwahl_probe.speichern[0][0] == "Save appointments" and
       dateiwahl_probe.speichern[0][1] == "magnolie-termine.ics" and
       dateiwahl_probe.speichern[0][2] == [("Calendar (*.ics)", "*.ics")],
       "englische Exportauswahl bewahrt Standarddatei und Dateimuster")
pruefe(dateiwahl_probe.speichern[1][0] == "Save contacts for Claws Mail" and
       dateiwahl_probe.speichern[1][1] == "magnolie-adressen-claws.ldif" and
       dateiwahl_probe.speichern[1][2] == [("LDIF address book (*.ldif)", "*.ldif")],
       "englische LDIF-Auswahl bewahrt Claws-Dateiname und Dateimuster")

anhang_formate = {
    "image/jpeg": (b"\xff\xd8\xff\xe0probe", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\nprobe", ".png"),
    "image/webp": (b"RIFF\x04\x00\x00\x00WEBPprobe", ".webp"),
    "image/gif": (b"GIF89aprobe", ".gif"),
    "application/pdf": (b"%PDF-1.4\nprobe", ".pdf"),
}
for mime, (roh, endung) in anhang_formate.items():
    url = "data:%s;base64,%s" % (mime, base64.b64encode(roh).decode("ascii"))
    gelesen = m.notiz_anhang_dekodieren(url, "../Ordner\\Datei.exe")
    pruefe(gelesen["mime"] == mime and gelesen["daten"] == roh and
           gelesen["name"].endswith(endung) and "/" not in gelesen["name"] and
           "\\" not in gelesen["name"] and len(gelesen["name"]) <= 180,
           "nativer Notizanhang prüft %s und kanonisiert seinen Namen" % mime)


def anhang_wirft(url):
    try:
        m.notiz_anhang_dekodieren(url, "x")
        return False
    except ValueError:
        return True


ungueltige_anhaenge = [
    "", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,!!!!",
    "data:image/png;base64," + base64.b64encode(b"%PDF-1.4").decode("ascii"),
    "data:application/pdf;base64,",
    "data:image/png;base64," + "A" * (m.NOTIZ_ANHANG_URL_MAX + 1),
    "data:image/png;base64," + base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"x" * m.NOTIZ_ANHANG_DATEI_MAX).decode("ascii"),
]
pruefe(all(anhang_wirft(url) for url in ungueltige_anhaenge),
       "native Anhangsgrenzen sperren MIME-, Base64-, Magic-, Leer- und Größenangriffe")
pruefe(m.notiz_anhang_name("." * 300 + "/\x00falsch.pdf", "image/png") ==
       "_falsch.png", "gefährliche Anhangsnamen erhalten eine kanonische Endung")


class _AnhangDateiProbe:
    def __init__(self, ziel=None):
        self._notiz_anhang_temp = None
        self.ziel = ziel
        self.antworten = []
        self.dialoge = []
    def _datei_speichern(self, titel, name, filter_liste):
        self.dialoge.append((titel, name, filter_liste))
        return self.ziel
    def antwort(self, funktion, nutzlast):
        self.antworten.append((funktion, nutzlast))


pdf_roh = anhang_formate["application/pdf"][0]
pdf_url = "data:application/pdf;base64," + base64.b64encode(pdf_roh).decode("ascii")
with tempfile.TemporaryDirectory(prefix="magnolie-attachment-test-") as ordner:
    ziel = os.path.join(ordner, "saved.pdf")
    speichern_probe = _AnhangDateiProbe(ziel)
    m.Fenster.bei_notiz_anhang_datei(speichern_probe,
        {"id": 7, "aktion": "save", "name": "Plan.exe", "daten": pdf_url})
    with open(ziel, "rb") as datei:
        gespeichert = datei.read()
    pruefe(gespeichert == pdf_roh and stat.S_IMODE(os.stat(ziel).st_mode) == 0o600 and
           speichern_probe.dialoge[0][1] == "Plan.pdf" and
           speichern_probe.antworten[-1][1]["ok"],
           "Speichern unter schreibt geprüfte Binärdaten atomisch und privat")
    abbrechen_probe = _AnhangDateiProbe(None)
    m.Fenster.bei_notiz_anhang_datei(abbrechen_probe,
        {"id": 8, "aktion": "save", "name": "Plan.pdf", "daten": pdf_url})
    pruefe(abbrechen_probe.antworten[-1][1]["abgebrochen"] and
           not abbrechen_probe.antworten[-1][1]["fehler"],
           "Abbruch des nativen Speichern-unter-Dialogs bleibt still")
    oeffnen_probe = _AnhangDateiProbe()
    aufrufe = []
    which_alt = m.shutil.which
    m.shutil.which = lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
    try:
        m.Fenster.bei_notiz_anhang_datei(oeffnen_probe,
            {"id": 9, "aktion": "open", "name": "../Plan.exe", "daten": pdf_url},
            starter=lambda argumente: aufrufe.append(argumente))
        temp_pfad = aufrufe[0][1]
        with open(temp_pfad, "rb") as datei:
            temporaer = datei.read()
        pruefe(aufrufe == [["/usr/bin/xdg-open", temp_pfad]] and
               os.path.dirname(temp_pfad) == oeffnen_probe._notiz_anhang_temp and
               os.path.basename(temp_pfad) == "_Plan.pdf" and temporaer == pdf_roh and
               stat.S_IMODE(os.stat(temp_pfad).st_mode) == 0o600,
               "Öffnen verwendet private Tempdaten und xdg-open ohne Shell")
    finally:
        m.shutil.which = which_alt
        if oeffnen_probe._notiz_anhang_temp:
            m.shutil.rmtree(oeffnen_probe._notiz_anhang_temp)

claws_fehlertexte = {
    "The LDIF address book is larger than 32 megabytes.":
        "Das LDIF-Adressbuch ist größer als 32 Megabyte.",
    "The LDIF address book contains too many people.":
        "Das LDIF-Adressbuch enthält zu viele Personen.",
    "The Claws Mail address book is larger than 32 megabytes.":
        "Das Claws-Adressbuch ist größer als 32 Megabyte.",
    "DOCTYPE is not allowed in a Claws Mail address book.":
        "DOCTYPE ist in einem Claws-Mail-Adressbuch nicht erlaubt.",
    "No Claws Mail address book was detected.":
        "Kein Claws-Mail-Adressbuch erkannt.",
    "The Claws Mail address book contains too many people.":
        "Das Claws-Adressbuch enthält zu viele Personen.",
}
pruefe(all(de_uebersetzung.gettext(quelle) == deutsch and
           en_uebersetzung.gettext(quelle) == quelle
           for quelle, deutsch in claws_fehlertexte.items()),
       "Claws- und LDIF-Validierungsfehler folgen der gewählten Sprache")
groessen_fehlertexte = {
    "The import file is larger than 32 megabytes.":
        "Die Importdatei ist größer als 32 Megabyte.",
    "The backup file is larger than 256 megabytes.":
        "Die Sicherungsdatei ist größer als 256 Megabyte.",
    "The holiday service returned too much data.":
        "Der Feiertagsdienst hat zu viele Daten geliefert.",
    "The selected path is not a regular file.":
        "Der gewählte Pfad ist keine reguläre Datei.",
}
pruefe(all(de_uebersetzung.gettext(quelle) == deutsch and
           en_uebersetzung.gettext(quelle) == quelle
           for quelle, deutsch in groessen_fehlertexte.items()),
       "Größen- und Dateitypfehler sind verständlich übersetzt")

grenzen_ordner = tempfile.mkdtemp(prefix="magnolie-groessen-")
grenze_pfad = os.path.join(grenzen_ordner, "grenze.ics")
with open(grenze_pfad, "wb") as datei:
    datei.write(b"x" * 32)
pruefe(m.datei_begrenzt_lesen(grenze_pfad, 32, "zu groß") == b"x" * 32,
       "reguläre Datei exakt an der Grenze wird gelesen")
with open(grenze_pfad, "ab") as datei:
    datei.write(b"x")
try:
    m.datei_begrenzt_lesen(grenze_pfad, 32, "zu groß")
    datei_zu_gross = False
except m.GroessenFehler:
    datei_zu_gross = True
pruefe(datei_zu_gross, "Datei mit Grenze plus einem Byte wird abgewiesen")
verweis_pfad = os.path.join(grenzen_ordner, "verweis.ics")
os.symlink(grenze_pfad, verweis_pfad)
try:
    m.datei_begrenzt_lesen(verweis_pfad, 32, "zu groß")
    verweis_abgewiesen = False
except OSError:
    verweis_abgewiesen = True
pruefe(verweis_abgewiesen, "symbolische Verweise werden vor dem Lesen abgewiesen")

import_zu_gross_pfad = os.path.join(grenzen_ordner, "zu-gross.ics")
with open(import_zu_gross_pfad, "wb") as datei:
    datei.truncate(m.IMPORT_DATEI_MAX + 1)
class _ImportZuGrossProbe(_DateiwahlProbe):
    def _datei_oeffnen(self, titel, filter_liste):
        return import_zu_gross_pfad
import_zu_gross_probe = _ImportZuGrossProbe()
m.Fenster.bei_import(import_zu_gross_probe, {"art": "ics"})
pruefe(import_zu_gross_probe.antworten == [("App.importErgebnis", {
    "art": "ics", "abgebrochen": False,
    "fehler": "The import file is larger than 32 megabytes."
})], "zu großer Import erreicht die Oberfläche mit verständlichem Fehler")

claws_fehler_pfad = os.path.join(tempfile.mkdtemp(prefix="magnolie-claws-"),
                                 "addrbook.xml")
with open(claws_fehler_pfad, "wb") as datei:
    datei.write(b'<?xml version="1.0"?><!DOCTYPE x><address-book/>')
class _ClawsFehlerProbe(_DateiwahlProbe):
    def _datei_oeffnen(self, titel, filter_liste):
        self.oeffnen.append((titel, filter_liste))
        return claws_fehler_pfad
claws_fehler_probe = _ClawsFehlerProbe()
m.Fenster.bei_import(claws_fehler_probe, {"art": "claws"})
pruefe(claws_fehler_probe.antworten == [("App.importErgebnis", {
    "art": "claws", "abgebrochen": False,
    "fehler": "File could not be read: DOCTYPE is not allowed in a Claws Mail address book."
})], "englischer Claws-Fehler erreicht die Oberfläche ohne Formatverlust")
m._, m.ngettext = gettext_alt, ngettext_alt

fensterprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-fenster-"), "fenster.json")
standard = m.fenster_zustand_lesen(fensterprobe)
pruefe(standard["breite"] == 1280 and standard["hoehe"] == 860
       and not standard["maximiert"] and not standard["vollbild"],
       "ohne Datei gilt die Voreinstellung")

pruefe(m.fenster_zustand_schreiben(
    {"breite": 1600, "hoehe": 900, "maximiert": False, "vollbild": True},
    fensterprobe), "Zustand lässt sich ablegen")
pruefe((os.stat(fensterprobe).st_mode & 0o777) == 0o600,
       "der Fensterzustand bleibt privat")
gelesen = m.fenster_zustand_lesen(fensterprobe)
pruefe(gelesen["breite"] == 1600 and gelesen["hoehe"] == 900,
       "Fenstergröße kommt zurück")
pruefe(gelesen["vollbild"] is True and gelesen["maximiert"] is False,
       "Vollbild wird gemerkt")

m.fenster_zustand_schreiben({"breite": 20, "hoehe": 99999, "maximiert": "ja"},
                            fensterprobe)
gelesen = m.fenster_zustand_lesen(fensterprobe)
pruefe(gelesen["breite"] == 980 and gelesen["hoehe"] == 10000,
       "unsinnige Größen werden zurechtgerückt: %dx%d"
       % (gelesen["breite"], gelesen["hoehe"]))
pruefe(gelesen["maximiert"] is True, "maximiert wird sauber gedeutet")

with open(fensterprobe, "w", encoding="utf-8") as datei:
    datei.write("kein JSON")
gelesen = m.fenster_zustand_lesen(fensterprobe)
pruefe(gelesen["breite"] == 1280, "kaputte Datei fällt auf die Voreinstellung")
pruefe(m.fenster_zustand_lesen(os.path.join(fensterprobe, "gibtsnicht"))["hoehe"]
       == 860, "fehlende Datei stört nicht")

class _SchliessProbe:
    _wirklich_beenden = False
    _tray_indikator = None
    _tray_einstellungen = {}

    def __init__(self):
        self.angefragt = 0

    def _beenden_anfragen(self):
        self.angefragt += 1

schliess_probe = _SchliessProbe()
pruefe(m.Fenster._bei_schliessen(schliess_probe) is True and
       schliess_probe.angefragt == 1,
       "das Fenster wartet beim Schließen auf den abschließenden Schreibvorgang")

class _BeendenWaechterProbe:
    _beenden_angefragt = False
    _wirklich_beenden = False

    def __init__(self):
        self.gesendet = []
        self.zerstoert = 0

    def sende_js(self, text):
        self.gesendet.append(text)

    def destroy(self):
        self.zerstoert += 1

    def _beenden_endgueltig(self):
        return m.Fenster._beenden_endgueltig(self)

    def _organizer_vertraut(self):
        return True

class _JsWertProbe:
    def __init__(self, wert):
        self.wert = wert

    def to_string(self):
        return self.wert

class _GLibWaechter:
    rueckrufe = []

    @classmethod
    def timeout_add_seconds(cls, _sekunden, rueckruf):
        cls.rueckrufe.append(rueckruf)

glib_alt = m.GLib
m.GLib = _GLibWaechter
try:
    waechter_probe = _BeendenWaechterProbe()
    m.Fenster._beenden_anfragen(waechter_probe)
    _GLibWaechter.rueckrufe[0]()
    pruefe(waechter_probe.gesendet == ["App.vorBeenden();"] and
           waechter_probe.zerstoert == 0 and
           not waechter_probe._beenden_angefragt,
           "der Schließwächter verwirft ohne Speicherbestätigung keine Daten")
    _GLibWaechter.rueckrufe.clear()
    waechter_probe = _BeendenWaechterProbe()
    waechter_probe._speicher_laeuft = True
    m.Fenster._beenden_anfragen(waechter_probe)
    pruefe(_GLibWaechter.rueckrufe[0]() is False and
           waechter_probe.zerstoert == 0,
           "der Schließwächter schneidet keinen laufenden Save ab")
    waechter_probe._speicher_laeuft = False
    waechter_probe._beenden_angefragt = True
    waechter_probe._beenden_speicherfehler = True
    m.Fenster.bei_nachricht(waechter_probe, None, _JsWertProbe(json.dumps({
        "cmd": "beenden_abgebrochen"})))
    pruefe(not waechter_probe._beenden_angefragt and
           not waechter_probe._beenden_speicherfehler and
           waechter_probe.zerstoert == 0,
           "Abbrechen setzt den nativen Schließwächter sofort zurück")
    m.Fenster._beenden_anfragen(waechter_probe)
    pruefe(waechter_probe.gesendet.count("App.vorBeenden();") == 2,
           "nach Abbrechen kann das Fenster sofort erneut geschlossen werden")
finally:
    m.GLib = glib_alt

print()
print("— Asynchrones serielles Speichern —")

class _SpeicherProbe:
    def __init__(self):
        self._speicher_auftraege = m.queue.Queue()
        self._speicher_laeuft = False
        self._daten_sperre = m.threading.RLock()
        self._aktuelle_daten = {}
        self._kennwort = ""
        self._beenden_angefragt = False
        self._beenden_speicherfehler = False
        self.antworten = []
        self.fertig = m.threading.Event()

    def _vielleicht_verschluesseln(self, text):
        return text

    def _journal_snapshot(self, _grund):
        return None

    def antwort(self, funktion, nutzlast):
        self.antworten.append((funktion, nutzlast))
        if len(self.antworten) >= 2:
            self.fertig.set()

speicher_alt = m.speichere_text
erinnerung_speicher_alt = m.erinnerungsdaten_schreiben
speicher_begonnen = m.threading.Event()
speicher_freigeben = m.threading.Event()
geschrieben = []

def _blockierend_speichern(text):
    geschrieben.append(text)
    if len(geschrieben) == 1:
        speicher_begonnen.set()
        speicher_freigeben.wait(2)

m.speichere_text = _blockierend_speichern
m.erinnerungsdaten_schreiben = lambda *args, **kwargs: True
try:
    speicher_probe = _SpeicherProbe()
    speicher_thread = m.threading.Thread(
        target=m.Fenster._speicher_lauf, args=(speicher_probe,), daemon=True)
    speicher_thread.start()
    speicher_probe._speicher_auftraege.put((1, '{"stand":"A"}'))
    pruefe(speicher_begonnen.wait(1),
           "der erste Save läuft im Arbeitsfaden an")
    start = time.monotonic()
    speicher_probe._speicher_auftraege.put((2, '{"stand":"B"}'))
    pruefe(time.monotonic() - start < 0.1,
           "das Einreihen des nächsten Saves blockiert die Oberfläche nicht")
    pruefe(geschrieben == ['{"stand":"A"}'],
           "ein zweiter Save läuft nicht parallel zum ersten")
    speicher_freigeben.set()
    pruefe(speicher_probe.fertig.wait(2) and
           geschrieben == ['{"stand":"A"}', '{"stand":"B"}'] and
           [antwort[1]["id"] for antwort in speicher_probe.antworten] == [1, 2],
           "der serielle Arbeiter bestätigt Saves in dauerhafter Reihenfolge")
    speicher_probe._speicher_auftraege.put(None)
    speicher_thread.join(1)

    def _speicherfehler(_text):
        raise OSError("Datenträger voll")

    m.speichere_text = _speicherfehler
    fehler_probe = _SpeicherProbe()
    fehler_erhalten = m.threading.Event()
    def _fehler_antwort(funktion, nutzlast):
        fehler_probe.antworten.append((funktion, nutzlast))
        fehler_erhalten.set()
    fehler_probe.antwort = _fehler_antwort
    fehler_thread = m.threading.Thread(
        target=m.Fenster._speicher_lauf, args=(fehler_probe,), daemon=True)
    fehler_thread.start()
    fehler_probe._speicher_auftraege.put((3, '{"stand":"C"}'))
    pruefe(fehler_erhalten.wait(2) and
           fehler_probe.antworten[0][1]["id"] == 3 and
           not fehler_probe.antworten[0][1]["ok"] and
           fehler_probe.antworten[0][1]["fehler"] and
           fehler_probe._beenden_speicherfehler,
           "Speicherfehler kommt mit Vorgangskennung zurück und sperrt Beenden")
    fehler_probe._speicher_auftraege.put(None)
    fehler_thread.join(1)
finally:
    m.speichere_text = speicher_alt
    m.erinnerungsdaten_schreiben = erinnerung_speicher_alt

tray_ordner = tempfile.mkdtemp(prefix="magnolie-tray-")
tray_probe = os.path.join(tray_ordner, "tray.json")
tray = m.tray_einstellungen({"aktiv": 1, "minimierenInTray": True,
                             "schliessenInTray": False,
                             "startMinimiert": True, "autostart": True,
                             "oeffnen": "zentriert", "zaehler": True})
pruefe(tray == {"aktiv": True, "minimierenInTray": True,
                "schliessenInTray": False,
                "startMinimiert": True, "autostart": True,
                 "oeffnen": "centered", "zaehler": True},
       "Tray-Einstellungen werden vollständig und begrenzt übernommen")
pruefe(m.tray_einstellungen_schreiben(tray, tray_probe)["ok"] and
       m.tray_einstellungen_lesen(tray_probe) == tray,
       "Tray-Einstellungen lassen sich unabhängig von den Organiserdaten speichern")
pruefe((os.stat(tray_probe).st_mode & 0o777) == 0o600,
       "die Tray-Einstellungen sind nur für das eigene Benutzerkonto lesbar")

class _JSSofortGLib:
    Error = m.GLib.Error
    @staticmethod
    def idle_add(rueckruf): return rueckruf()

class _JSAnsichtNeu:
    def __init__(self): self.aufrufe = []
    def evaluate_javascript(self, *_werte): self.aufrufe.append("evaluate")
    def run_javascript(self, *_werte): self.aufrufe.append("run")

class _JSAnsichtAlt:
    def __init__(self): self.aufrufe = []
    def run_javascript(self, *_werte): self.aufrufe.append("run")

class _JSSendeProbe:
    def __init__(self, ansicht): self.ansicht = ansicht
    def _organizer_vertraut(self): return True

js_glib_alt = m.GLib
m.GLib = _JSSofortGLib
try:
    js_neu = _JSSendeProbe(_JSAnsichtNeu())
    m.Fenster.sende_js(js_neu, "1 + 1")
    pruefe(js_neu.ansicht.aufrufe == ["evaluate"],
           "neues WebKit verwendet nur den nicht veralteten JavaScript-Aufruf")
    js_alt = _JSSendeProbe(_JSAnsichtAlt())
    m.Fenster.sende_js(js_alt, "1 + 1")
    pruefe(js_alt.ansicht.aufrufe == ["run"],
           "altes WebKit behält den kompatiblen JavaScript-Rückfall")
finally:
    m.GLib = js_glib_alt

class _SichtbarkeitsProbe:
    def __init__(self):
        self.aufrufe = []
        self.erster_aufruf = m.threading.Event()
        self.fortsetzen = m.threading.Event()
    def set_visible(self, sichtbar):
        self.aufrufe.append(sichtbar)
        if len(self.aufrufe) == 1:
            self.erster_aufruf.set()
            self.fortsetzen.wait(2)

sichtbarkeits_probe = _SichtbarkeitsProbe()
m._hintergrund_sichtbarkeit_senden(
    sichtbarkeits_probe, False, "magnolie-visibility-test-old")
pruefe(sichtbarkeits_probe.erster_aufruf.wait(2),
       "die erste Hintergrundsichtbarkeit wird ohne GUI-Blockade gesendet")
sichtbarkeits_start = time.monotonic()
m._hintergrund_sichtbarkeit_senden(
    sichtbarkeits_probe, True, "magnolie-visibility-test-new")
pruefe(time.monotonic() - sichtbarkeits_start < 0.2,
       "das Einreihen neuer Hintergrundsichtbarkeit blockiert die GUI nicht")
sichtbarkeits_probe.fortsetzen.set()
for _versuch in range(200):
    if len(sichtbarkeits_probe.aufrufe) == 2:
        break
    time.sleep(0.01)
pruefe(sichtbarkeits_probe.aufrufe == [False, True],
       "schnelle Sichtbarkeitswechsel enden mit dem neuesten GUI-Zustand")

class _FehlerhafteSichtbarkeitsProbe:
    def set_visible(self, _sichtbar):
        raise RuntimeError("visibility probe")

fehlerhafte_sichtbarkeits_probe = _FehlerhafteSichtbarkeitsProbe()
m._hintergrund_sichtbarkeit_senden(
    fehlerhafte_sichtbarkeits_probe, True, "magnolie-visibility-test-error")
for _versuch in range(200):
    with m._HINTERGRUND_SICHTBARKEITS_SPERRE:
        if id(fehlerhafte_sichtbarkeits_probe) not in m._HINTERGRUND_SICHTBARKEITS_ARBEITER:
            break
    time.sleep(0.01)
with m._HINTERGRUND_SICHTBARKEITS_SPERRE:
    sichtbarkeits_fehler_aufgeraeumt = (id(fehlerhafte_sichtbarkeits_probe) not in
                                       m._HINTERGRUND_SICHTBARKEITS_ARBEITER)
pruefe(sichtbarkeits_fehler_aufgeraeumt,
       "ein fehlgeschlagener Sichtbarkeitsaufruf blockiert spätere Meldungen nicht")
pruefe("_hintergrund_sichtbarkeit_senden" in
       m.Fenster._telefon_dienst_pflegen.__code__.co_names,
       "auch der Telefonstatus bündelt Sichtbarkeitsmeldungen seriell")

class _TrayZaehlerProbe:
    def __init__(self, art):
        self._tray_art = art
        self._tray_zaehler = 7
        self._tray_einstellungen = {"zaehler": True}
        self.aufrufe = []
        self._tray_indikator = self
    def set_label(self, *werte): self.aufrufe.append(werte)
    def set_tooltip_text(self, _text): pass

xapp_zaehler_probe = _TrayZaehlerProbe("xapp")
m.Fenster._tray_zaehler_anzeigen(xapp_zaehler_probe)
pruefe(xapp_zaehler_probe.aufrufe == [("7",)],
       "XApp zeigt den Benachrichtigungszähler sichtbar am Tray-Symbol")
appindicator_zaehler_probe = _TrayZaehlerProbe("appindicator")
m.Fenster._tray_zaehler_anzeigen(appindicator_zaehler_probe)
pruefe(appindicator_zaehler_probe.aufrufe == [("7", "99+")],
       "AppIndicator behält den sichtbaren Tray-Zähler")

class _TrayMenuProbe:
    def __init__(self, label=""):
        self.label, self.kinder, self.signale = label, [], []
        self.submenu, self.sichtbar = None, None
    def append(self, eintrag): self.kinder.append(eintrag)
    def connect(self, *werte): self.signale.append(werte)
    def set_submenu(self, menu): self.submenu = menu
    def set_visible(self, sichtbar): self.sichtbar = sichtbar
    def show_all(self): pass
class _TrayGtkProbe:
    Menu = _TrayMenuProbe
    MenuItem = _TrayMenuProbe
class _TrayStoreProbe:
    peers = [{"device_id": "telefon-1", "display_name": "Gekoppeltes Telefon"}]
class _TrayTelefonProbe:
    enabled = True
    def report(self):
        return {"peers": _TrayStoreProbe.peers}
class _TrayFensterProbe:
    _gesperrt = False
    _telefon = _TrayTelefonProbe()
    _tray_telefone = _TrayMenuProbe("Telefone")
    _tray_telefon_verbinden_eintrag = None
    def _tray_telefon_zeigen(self, *_werte): pass

tray_gtk_alt = m.Gtk
m.Gtk = _TrayGtkProbe
try:
    tray_fenster = _TrayFensterProbe()
    m.Fenster._tray_telefone_aktualisieren(tray_fenster)
    pruefe(tray_fenster._tray_telefone.sichtbar and
           [x.label for x in tray_fenster._tray_telefone.submenu.kinder] ==
           ["Gekoppeltes Telefon"],
           "gekoppelte Telefone bleiben im dynamischen Tray-Untermenü")
    programmtext = open(PFAD, encoding="utf-8").read()
    pruefe('Gtk.MenuItem(label=_("Connect phone"))' not in programmtext and
           'Gtk.MenuItem(label=_("Telefon verbinden"))' not in programmtext,
           "das Tray erzeugt keinen statischen Eintrag ‚Telefon verbinden‘")
finally:
    m.Gtk = tray_gtk_alt
tray_autostart = os.path.join(tray_ordner, "autostart", "tray.desktop")
pruefe(m.tray_autostart_einrichten(True, tray_autostart)["ok"] and
       "--tray-start" in open(tray_autostart, encoding="utf-8").read(),
       "das Tray-Applet lässt sich beim Anmelden starten")
tray_autostart_inhalt = open(tray_autostart, encoding="utf-8").read()
pruefe("Name=Magnolie Organizer – Tray-Applet" in tray_autostart_inhalt and
       ('Exec="%s" --tray-start' % m.eigener_pfad()) in tray_autostart_inhalt and
       "X-GNOME-Autostart-enabled=true" in tray_autostart_inhalt,
       "sichtbare Tray-Metadaten sind deutsch und technische Werte unverändert")
pruefe(m.tray_autostart_einrichten(False, tray_autostart)["ok"] and
       not os.path.exists(tray_autostart),
       "das Abschalten entfernt nur den eigenen Tray-Autostart")
appimage_alt = os.environ.get("APPIMAGE")
os.environ["APPIMAGE"] = "/tmp/Magnolie Organizer-${HOME}-100%.AppImage"
try:
    pruefe('Exec="/tmp/Magnolie Organizer-\\\\${HOME}-100%%.AppImage" --tray-start' in
           m.tray_autostart_text() and
           'ExecStart="/tmp/Magnolie Organizer-$${HOME}-100%%.AppImage" --erinnerung' in
           m.systemd_dienst_text() and
           'Exec="/tmp/Magnolie Organizer-\\\\${HOME}-100%%.AppImage" --wecker' in
           m.autostart_text(),
           "dauerhafte AppImage-Registrierungen verwenden das stabile Abbild")
finally:
    if appimage_alt is None:
        os.environ.pop("APPIMAGE", None)
    else:
        os.environ["APPIMAGE"] = appimage_alt
if m.AppIndicator is not None:
    pruefe(m.tray_system_verfuegbar("X-Cinnamon", []),
           "Cinnamon unterstützt den StatusNotifier ohne GNOME-Erweiterung")
    pruefe(m.tray_system_verfuegbar("KDE", []),
           "KDE unterstützt den StatusNotifier ohne GNOME-Erweiterung")
    pruefe(not m.tray_system_verfuegbar("GNOME", []),
           "GNOME ohne AppIndicator-Erweiterung startet nicht unsichtbar")
    pruefe(m.tray_system_verfuegbar(
        "GNOME", ["appindicatorsupport@rgcjonas.gmail.com"]),
        "GNOME mit aktivierter AppIndicator-Erweiterung unterstützt das Tray")
if m.XApp is not None:
    pruefe(m.tray_system_verfuegbar("X-Cinnamon", []),
           "Cinnamon erkennt XApp als natives Tray unter X11 und Wayland")

class _FensterZustandsProbe:
    def __init__(self):
        self._fenster = {"maximiert": False, "vollbild": True,
                         "x": None, "y": None}
        self._tray_window_hidden = True
        self._tray_hide_quelle = None
        self._tray_wechsel = 0
        self._tray_oeffnet = False
        self._tray_indikator = object()
        self._tray_einstellungen = {"aktiv": True, "minimierenInTray": True,
                                    "oeffnen": "letzte"}
        self.gdk_zustand = 0
        self.aktionen = []
    def fullscreen(self): self.aktionen.append("vollbild")
    def unfullscreen(self): self.aktionen.append("kein-vollbild")
    def maximize(self): self.aktionen.append("maximiert")
    def unmaximize(self): self.aktionen.append("nicht-maximiert")
    def move(self, *_a): self.aktionen.append("verschoben")
    def show_all(self): self.aktionen.append("gezeigt")
    def deiconify(self): self.aktionen.append("entminimiert")
    def present(self): self.aktionen.append("vorn")
    def hide(self): self.aktionen.append("verborgen")
    def get_visible(self): return True
    def get_mapped(self): return True
    def get_window(self):
        zustand = self.gdk_zustand
        return type("GdkFensterProbe", (), {"get_state": lambda _self: zustand})()
    def _tray_hide_abbrechen(self): self._tray_hide_quelle = None; return False
    def _tray_hide_planen(self): self.aktionen.append("hide-geplant"); return True
    def _tray_zeigen(self): self.aktionen.append("tray-gezeigt")
    def _tray_verbergen(self): self.aktionen.append("tray-verborgen")

fenster_zustands_probe = _FensterZustandsProbe()
m.Fenster._tray_zeigen(fenster_zustands_probe)
pruefe(fenster_zustands_probe.aktionen[:3] ==
       ["gezeigt", "entminimiert", "vollbild"] and
       not fenster_zustands_probe._tray_window_hidden,
       "Zurückholen stellt das zuletzt gespeicherte Vollbild wieder her")
fenster_zustands_probe._tray_window_hidden = True
ereignis = type("Ereignis", (), {"new_window_state": 0, "changed_mask": 0})()
m.Fenster._bei_fensterzustand(fenster_zustands_probe, None, ereignis)
pruefe(fenster_zustands_probe._fenster["vollbild"] is True,
       "nachlaufende Fensterereignisse löschen verborgenes Vollbild nicht")
fenster_zustands_probe._tray_window_hidden = False
fenster_zustands_probe.aktionen = []
ereignis = type("Ereignis", (), {
    "new_window_state": m.Gdk.WindowState.ICONIFIED | m.Gdk.WindowState.MAXIMIZED,
    "changed_mask": m.Gdk.WindowState.MAXIMIZED})()
m.Fenster._bei_fensterzustand(fenster_zustands_probe, None, ereignis)
pruefe("hide-geplant" not in fenster_zustands_probe.aktionen,
       "eine reine Maximierungsänderung mit altem ICONIFIED plant kein erneutes Verbergen")
fenster_zustands_probe._tray_oeffnet = True
ereignis = type("Ereignis", (), {
    "new_window_state": m.Gdk.WindowState.ICONIFIED,
    "changed_mask": m.Gdk.WindowState.ICONIFIED})()
m.Fenster._bei_fensterzustand(fenster_zustands_probe, None, ereignis)
pruefe("hide-geplant" not in fenster_zustands_probe.aktionen,
       "ein eigenes ICONIFIED-Ereignis beim Öffnen löst keinen neuen Tray-Hide aus")
fenster_zustands_probe._tray_oeffnet = False
ereignis = type("Ereignis", (), {
    "new_window_state": m.Gdk.WindowState.ICONIFIED,
    "changed_mask": m.Gdk.WindowState.ICONIFIED})()
m.Fenster._bei_fensterzustand(fenster_zustands_probe, None, ereignis)
pruefe("hide-geplant" in fenster_zustands_probe.aktionen,
       "eine echte neue Minimierung wird weiterhin ins Tray übernommen")
fenster_zustands_probe._tray_window_hidden = True
fenster_zustands_probe.aktionen = []
m.Fenster._tray_umschalten(fenster_zustands_probe)
pruefe(fenster_zustands_probe.aktionen == ["tray-gezeigt"],
       "Tray-Klick holt ein verborgen markiertes Fenster trotz GTK-Sichtbarkeit zurück")
fenster_zustands_probe._tray_window_hidden = False
fenster_zustands_probe.aktionen = []
m.Fenster._tray_umschalten(fenster_zustands_probe)
pruefe(fenster_zustands_probe.aktionen == ["tray-verborgen"],
       "Tray-Klick verbirgt ein tatsächlich sichtbares Fenster")

class _TrayGLibProbe:
    naechste_quelle = 1
    rueckrufe = {}
    entfernt = []

    @classmethod
    def _merken(cls, rueckruf):
        quelle = cls.naechste_quelle
        cls.naechste_quelle += 1
        cls.rueckrufe[quelle] = rueckruf
        return quelle

    @classmethod
    def idle_add(cls, rueckruf): return cls._merken(rueckruf)

    @classmethod
    def timeout_add(cls, _millisekunden, rueckruf): return cls._merken(rueckruf)

    @classmethod
    def source_remove(cls, quelle):
        cls.entfernt.append(quelle)
        cls.rueckrufe.pop(quelle, None)
        return True

glib_alt = m.GLib
m.GLib = _TrayGLibProbe
try:
    fenster_zustands_probe._tray_hide_quelle = 77
    _TrayGLibProbe.rueckrufe[77] = lambda: False
    pruefe(m.Fenster._tray_hide_abbrechen(fenster_zustands_probe) and
           fenster_zustands_probe._tray_hide_quelle is None and
           77 in _TrayGLibProbe.entfernt,
           "Zurückholen storniert ein bereits vorgemerktes Tray-Verbergen")

    fenster_zustands_probe.aktionen = []
    fenster_zustands_probe._tray_wechsel = 10
    m.Fenster._tray_hide_planen(fenster_zustands_probe)
    hide_rueckruf = _TrayGLibProbe.rueckrufe[
        fenster_zustands_probe._tray_hide_quelle]
    fenster_zustands_probe._tray_wechsel += 1
    hide_rueckruf()
    pruefe("verborgen" not in fenster_zustands_probe.aktionen and
           fenster_zustands_probe._tray_hide_quelle is None,
           "ein überholter Idle-Hide kann das zurückgeholte Fenster nicht verbergen")

    fenster_zustands_probe.aktionen = []
    fenster_zustands_probe._tray_window_hidden = True
    fenster_zustands_probe.gdk_zustand = m.Gdk.WindowState.ICONIFIED
    m.Fenster._tray_zeigen(fenster_zustands_probe)
    retry_rueckruf = _TrayGLibProbe.rueckrufe[max(_TrayGLibProbe.rueckrufe)]
    retry_rueckruf()
    pruefe(fenster_zustands_probe.aktionen.count("entminimiert") == 2 and
           fenster_zustands_probe.aktionen.count("vorn") == 2,
           "die Nachprüfung wiederholt Entminimieren und Präsentieren")
finally:
    m.GLib = glib_alt

class _ProbeAnwendung:
    def __init__(self, remote):
        self.remote, self.aktiviert, self.gehalten = remote, 0, 0
    def connect(self, *_a): pass
    def register(self, _a): pass
    def get_is_remote(self): return self.remote
    def activate(self): self.aktiviert += 1
    def hold(self): self.gehalten += 1
    def add_action(self, aktion): self.aktion = aktion
    def activate_action(self, _name, parameter): self.aktion.rueckruf(self.aktion, parameter)
class _ProbeAktion:
    @classmethod
    def new(cls, *_a): return cls()
    def connect(self, _signal, rueckruf): self.rueckruf = rueckruf
class _ProbeApplication:
    remote = False
    letzte = None
    @classmethod
    def new(cls, *_a):
        cls.letzte = _ProbeAnwendung(cls.remote)
        return cls.letzte
class _ProbeGio:
    Application = _ProbeApplication
    SimpleAction = _ProbeAktion
    class ApplicationFlags:
        FLAGS_NONE = 0
gio_echt = m.Gio
gtk_echt = m.Gtk
m.Gtk = type("_ProbeGtkApplication", (), {"Application": _ProbeApplication})
m.Gio = _ProbeGio
_ProbeApplication.remote = False
app, schon = m.einzelinstanz_anmelden("io.test.Magnolie", lambda: None)
pruefe(not schon and app.gehalten == 1,
       "die erste Organizer-Instanz hält die eindeutige Sitzungsanmeldung")
_ProbeApplication.remote = True
app, schon = m.einzelinstanz_anmelden("io.test.Magnolie", lambda: None)
pruefe(schon and app.aktiviert == 1,
       "ein zweiter Organizer-Start aktiviert nur das vorhandene Fenster")
m.Gio = gio_echt
m.Gtk = gtk_echt

print()
print("— Erinnerungen an Termine —")

from datetime import datetime as _dt

marke_geheilt = m.faellige_erinnerungen(
    {"termine": []}, _dt(2026, 8, 25, 12, 0),
    {"gemeldet": {"kaputt": "kein-zeitstempel"}})["zustand"]
pruefe(marke_geheilt["gemeldet"].get("kaputt") == "2026-08-25 12:00",
       "unlesbare Meldemarke wird ohne Doppelmeldung mit alterndem Zeitpunkt geheilt")
marke_gealtert = m.faellige_erinnerungen(
    {"termine": []}, _dt(2026, 9, 10, 12, 0), marke_geheilt)["zustand"]
pruefe("kaputt" not in marke_gealtert["gemeldet"],
       "geheilte Meldemarke wird nach der Schonfrist entfernt")

daten_wecker = {"termine": [
    {"id": "t1", "datum": "2026-07-25", "zeit": "10:00", "titel": "Zahnarzt"},
    {"id": "t2", "datum": "2026-07-25", "zeit": "16:00", "titel": "Sport"},
    {"id": "t3", "datum": "2026-07-24", "zeit": "09:00", "titel": "Gestern verpasst"},
    {"id": "t4", "datum": "2026-07-25", "zeit": "", "titel": "Ganztägig"},
    {"id": "t5", "datum": "2026-01-01", "zeit": "09:00", "titel": "Uralt"},
]}
leer = {"gemeldet": {}, "letzter_lauf": ""}

erg = m.faellige_erinnerungen(daten_wecker, _dt(2026, 7, 25, 9, 50), leer, vorlauf=15)
namen = [e["titel"] for e in erg["faellig"]]
pruefe(namen == ["Zahnarzt"], "zehn Minuten vor dem Termin ist genau einer fällig: %r" % namen)
pruefe([e["titel"] for e in erg["verpasst"]] == ["Gestern verpasst", "Ganztägig"],
       "Verpasstes wird nachgereicht: %r" % [e["titel"] for e in erg["verpasst"]])
pruefe("Uralt" not in str(erg), "sehr alte Termine bleiben außen vor")

zweiter = m.faellige_erinnerungen(daten_wecker, _dt(2026, 7, 25, 9, 55),
                                  erg["zustand"], vorlauf=15)
pruefe(not zweiter["faellig"] and not zweiter["verpasst"],
       "nichts wird zweimal gemeldet")

vorlauf_alt = m.faellige_erinnerungen(
    {"termine": [daten_wecker["termine"][0]]},
    _dt(2026, 7, 25, 9, 50), leer, vorlauf=15)
vorlauf_neu = m.faellige_erinnerungen(
    {"termine": [daten_wecker["termine"][0]]},
    _dt(2026, 7, 25, 9, 50), vorlauf_alt["zustand"], vorlauf=30)
pruefe(not vorlauf_neu["faellig"] and not vorlauf_neu["verpasst"],
       "geänderter Standardvorlauf meldet denselben Termin nicht erneut")
legacy_marke = {"gemeldet": {"t1@202607251000": "2026-07-25 09:50"}}
legacy_ergebnis = m.faellige_erinnerungen(
    {"termine": [daten_wecker["termine"][0]]},
    _dt(2026, 7, 25, 9, 50), legacy_marke, vorlauf=15)
pruefe(not legacy_ergebnis["faellig"] and not legacy_ergebnis["verpasst"],
       "frühere basisgebundene Meldemarken werden einmalig übernommen")

erg = m.faellige_erinnerungen(daten_wecker, _dt(2026, 7, 25, 9, 30), leer, vorlauf=15)
pruefe([e["titel"] for e in erg["faellig"]] == [],
       "eine halbe Stunde vorher ist noch nichts fällig")
erg = m.faellige_erinnerungen(daten_wecker, _dt(2026, 7, 25, 9, 30), leer, vorlauf=60)
pruefe([e["titel"] for e in erg["faellig"]] == ["Zahnarzt"],
       "mit einer Stunde Vorlauf schon")

erg = m.faellige_erinnerungen(daten_wecker, _dt(2026, 7, 25, 12, 0), leer,
                              vorlauf=15, verpasste=False)
pruefe(not erg["verpasst"] and any(k.startswith("t3@") for k in
                                   erg["zustand"]["gemeldet"]),
       "ohne Haken wird Verpasstes still abgehakt")

verschoben = {"termine": [{"id": "t1", "datum": "2026-07-25", "zeit": "11:00",
                            "titel": "Zahnarzt verschoben"}]}
neu_geplant = m.faellige_erinnerungen(
    verschoben, _dt(2026, 7, 25, 10, 50), erg["zustand"], vorlauf=15)
pruefe([e["titel"] for e in neu_geplant["faellig"]] == ["Zahnarzt verschoben"],
       "ein bereits gemeldeter und danach verschobener Termin wird neu erinnert")

pruefe(m._termin_zeitpunkt({"datum": "2026-07-25", "zeit": ""}) == _dt(2026, 7, 25, 8, 0),
       "ganztägige Termine gelten ab 8 Uhr")
pruefe(m._termin_zeitpunkt({"datum": "krumm", "zeit": "10:00"}) is None,
       "unbrauchbares Datum liefert nichts")

weck = m.naechster_weckzeitpunkt(daten_wecker, _dt(2026, 7, 25, 10, 30), vorlauf=15)
pruefe(weck == _dt(2026, 7, 25, 15, 45),
       "nächster Weckzeitpunkt liegt vor dem übernächsten Termin: %s" % weck)
pruefe(m.naechster_weckzeitpunkt({"termine": []}, _dt(2026, 7, 25, 10, 0)) is None,
       "ohne Termine kein Weckruf")

kopf, rumpf = m.erinnerungstext({"titel": "Zahnarzt", "datum": "2026-07-25",
                                 "zeit": "10:00", "verpasst": True})
pruefe(kopf == "Termin verpasst" and "25.07.2026" in rumpf and "10:00" in rumpf,
       "Text für Verpasstes: %s – %s" % (kopf, rumpf))
kopf, rumpf = m.erinnerungstext({"titel": "Sport", "datum": "2026-07-25",
                                 "zeit": "16:00", "verpasst": False})
pruefe(kopf == "Termin steht an" and "16:00" in rumpf, "Text für Anstehendes")

individuell = {"termine": [{"id": "ti", "datum": "2026-08-01",
    "zeit": "10:00", "titel": "Arztbesuch", "individuelleErinnerungTage": 7,
    "standardErinnerung": True}]}
erg = m.faellige_erinnerungen(individuell, _dt(2026, 7, 25, 10, 0), leer,
                              vorlauf=120)
pruefe(len(erg["faellig"]) == 1 and
       erg["faellig"][0]["individuelleTage"] == 7,
       "individuelle Terminerinnerung kommt sieben Tage vorher")
kopf, rumpf = m.erinnerungstext(erg["faellig"][0])
pruefe(kopf == "Termin vormerken" and "in 7 Tagen" in rumpf,
       "individuelle Terminerinnerung nennt ihren Vorlauf")

strukturierter_termin = {"termine": [{
    "id": "ta", "datum": "2026-08-10", "zeit": "10:00",
    "endDatum": "2026-08-10", "endZeit": "11:00", "titel": "Werkstatt",
    "individuelleErinnerungTage": 1, "standardErinnerung": False,
    "alarme": [
        {"offsetMinuten": 1440, "aktiviert": True, "related": "START",
         "aktion": "display"},
        {"offsetMinuten": 120, "aktiviert": True, "related": "START",
         "aktion": "display"},
        {"offsetMinuten": 10, "aktiviert": True, "related": "START",
         "aktion": "display"},
        {"offsetMinuten": 15, "aktiviert": True, "related": "END",
         "aktion": "display"},
        {"offsetMinuten": 180, "aktiviert": False, "related": "START",
         "aktion": "display"},
        {"offsetMinuten": 90, "aktiviert": True, "related": "START",
         "aktion": "email"},
        {"offsetMinuten": 0, "aktiviert": True, "related": "START",
         "aktion": "display", "bearbeitbar": False},
    ]}]}
alarm_zustand = leer
alarm_faelle = []
for alarm_jetzt in (_dt(2026, 8, 9, 10, 0), _dt(2026, 8, 10, 8, 0),
                    _dt(2026, 8, 10, 9, 50), _dt(2026, 8, 10, 10, 45)):
    alarm_ergebnis = m.faellige_erinnerungen(
        strukturierter_termin, alarm_jetzt, alarm_zustand, vorlauf=15)
    alarm_faelle.append(alarm_ergebnis["faellig"])
    alarm_zustand = alarm_ergebnis["zustand"]
pruefe([len(eintraege) for eintraege in alarm_faelle] == [1, 1, 1, 1],
       "strukturierte Tages-, Stunden-, Minuten- und END-Alarme werden einzeln fällig")
pruefe(alarm_faelle[0][0]["id"].endswith(":individuell-1"),
       "äquivalenter strukturierter Tagesalarm verdoppelt die Legacy-Meldung nicht")
pruefe(all("alarm-START-180" not in str(eintraege) and
           "alarm-START-90" not in str(eintraege) for eintraege in alarm_faelle),
       "deaktivierte und nicht anzeigende strukturierte Alarme bleiben still")
pruefe((0, "START", "") not in m._strukturierte_alarme(
    strukturierter_termin["termine"][0]),
    "nicht bearbeitbare importierte Alarme lösen keine Ersatzmeldung aus")
pruefe(m.naechster_weckzeitpunkt(
    strukturierter_termin, _dt(2026, 8, 10, 7, 0), vorlauf=15) ==
    _dt(2026, 8, 10, 8, 0),
    "der nächste native Weckzeitpunkt berücksichtigt strukturierte Alarme")

serien_wecker = {"termine": [{
    "id": "serie-wecker", "datum": "2026-08-03", "zeit": "10:00",
    "titel": "Wochenrunde", "wiederholung": {"art": "weekly", "bis": ""}}]}
pruefe(m.naechster_weckzeitpunkt(
    serien_wecker, _dt(2026, 8, 4, 12, 0), vorlauf=15) ==
    _dt(2026, 8, 10, 9, 45),
    "der native Wecker plant auch die nächste Instanz einer laufenden Serie")

import_alarme = {"termine": [{
    "id": "import-alarm", "datum": "2026-08-10", "zeit": "10:00",
    "titel": "Importierte Alarme", "standardErinnerung": False,
    "alarme": [
        {"offsetMinuten": 0, "aktiviert": True, "related": "START",
         "aktion": "display", "bearbeitbar": False, "triggerRaw": "+PT10M"},
        {"offsetMinuten": 0, "aktiviert": True, "related": "START",
         "aktion": "display", "bearbeitbar": False,
         "triggerRaw": "20260810T103000"},
    ]}]}
nach_start = m.faellige_erinnerungen(
    import_alarme, _dt(2026, 8, 10, 10, 10), leer, vorlauf=15)
absolut = m.faellige_erinnerungen(
    import_alarme, _dt(2026, 8, 10, 10, 30), nach_start["zustand"], vorlauf=15)
pruefe(len(nach_start["faellig"]) == 1 and len(absolut["faellig"]) == 1,
       "positive und absolute importierte Display-Alarme werden ausgelöst")
pruefe(m.naechster_weckzeitpunkt(
    import_alarme, _dt(2026, 8, 10, 10, 5), vorlauf=15) ==
    _dt(2026, 8, 10, 10, 10),
    "positive importierte Alarme werden als künftiger Weckzeitpunkt geplant")

erinnerung_gettext_alt, erinnerung_ngettext_alt = m._, m.ngettext
erinnerung_regional_alt = dict(m._REGIONAL)
erinnerung_en = m.gettext_uebersetzung("en")
m._, m.ngettext = erinnerung_en.gettext, erinnerung_en.ngettext
m._REGIONAL["formatLocale"] = "en-US"
kopf_en, rumpf_en = m.erinnerungstext({
    "titel": "Zahnarzt", "datum": "2026-07-25", "zeit": "10:00",
    "verpasst": True})
pruefe(kopf_en == "Missed appointment" and "7/25/2026" in rumpf_en and
       "10:00" in rumpf_en,
       "englische Terminerinnerung folgt Sprache und Formatgebiet")
kopf_en, rumpf_en = m.erinnerungstext(erg["faellig"][0])
pruefe(kopf_en == "Appointment reminder" and "in 7 days" in rumpf_en,
       "englischer individueller Vorlauf verwendet gettext-Plurale")
kopf_en, rumpf_en = m.jahrestagstext(
    {"name": "Max Mustermann", "typ": "Birthday"}, 1)
pruefe(kopf_en == "Birthday" and
       rumpf_en == "Max Mustermann has a birthday tomorrow.",
       "englischer Geburtstagstyp wird semantisch erkannt")
kopf_en, rumpf_en = m.jahrestagstext(
    {"name": "Erika und Max", "typ": "Hochzeitstag"}, 0)
pruefe(kopf_en == "Wedding anniversary" and "today" in rumpf_en,
       "deutscher Bestandstyp bleibt unter englischer Oberfläche erkannt")
pruefe("Description=Magnolie Organizer – appointment reminders" in
       m.systemd_dienst_text("/opt/Magnolie Organizer/bin/magnolie-organizer") and
       "Name=Magnolie Organizer – reminders" in
       m.autostart_text("/opt/Magnolie Organizer/bin/magnolie-organizer") and
       'Exec="/opt/Magnolie Organizer/bin/magnolie-organizer" --wecker' in
       m.autostart_text("/opt/Magnolie Organizer/bin/magnolie-organizer"),
       "englische Diensttexte bewahren Einheiten und Befehle")
m._, m.ngettext = erinnerung_gettext_alt, erinnerung_ngettext_alt
m._REGIONAL.clear()
m._REGIONAL.update(erinnerung_regional_alt)
standard = m.faellige_erinnerungen(
    individuell, _dt(2026, 8, 1, 8, 0), erg["zustand"], vorlauf=120)
pruefe(len(standard["faellig"]) == 1 and
       not standard["faellig"][0]["individuelleTage"],
       "individuelle und Standardbenachrichtigung arbeiten nebeneinander")
individuell["termine"][0]["standardErinnerung"] = False
ohne_standard = m.faellige_erinnerungen(
    individuell, _dt(2026, 8, 1, 8, 0), erg["zustand"], vorlauf=120)
pruefe(not ohne_standard["faellig"],
       "Standardbenachrichtigung lässt sich je Termin abschalten")
ohne_individuelle = {"termine": [{"id": "ts", "datum": "2026-08-01",
    "zeit": "10:00", "titel": "Besprechung", "individuelleErinnerungTage": 0,
    "standardErinnerung": False}]}
standard_erzwungen = m.faellige_erinnerungen(
    ohne_individuelle, _dt(2026, 8, 1, 8, 0), leer, vorlauf=120)
pruefe(len(standard_erzwungen["faellig"]) == 1,
       "ohne individuellen Vorlauf bleibt die Standardbenachrichtigung aktiv")

zustandsprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-wecker-"), "e.json")
pruefe(m.erinnerung_zustand_schreiben({"gemeldet": {"t1": "2026-07-25 09:50"},
                                       "letzter_lauf": "2026-07-25 09:50"},
                                      zustandsprobe), "Zustand lässt sich ablegen")
pruefe((os.stat(zustandsprobe).st_mode & 0o777) == 0o600,
       "der Erinnerungszustand bleibt privat")
zurueck = m.erinnerung_zustand_lesen(zustandsprobe)
pruefe(zurueck["gemeldet"].get("t1") == "2026-07-25 09:50", "Zustand kommt zurück")
pruefe(m.erinnerung_zustand_lesen(zustandsprobe + "-weg")["gemeldet"] == {},
       "fehlende Zustandsdatei stört nicht")

gerufene = []
pruefe(m.ton_abspielen([["gibtsnichtxyz"]], lambda a: gerufene.append(a)) == "",
       "fehlendes Tonwerkzeug wird übersprungen")
pruefe(m.ton_abspielen([["sh", "-c", "true"]], lambda a: gerufene.append(a)) == "sh",
       "vorhandenes Tonwerkzeug wird benutzt")

class _TonProzess:
    def __init__(self, status):
        self.status = status

    def wait(self, timeout=None):
        return self.status

ton_versuche = []
def _ton_starter(argumente):
    ton_versuche.append(argumente[0])
    return _TonProzess(1 if len(ton_versuche) == 1 else 0)

pruefe(m.ton_abspielen([["sh", "-c", "false"], ["sh", "-c", "true"]],
                       _ton_starter) == "sh" and len(ton_versuche) == 2,
       "nach sofortigem Audiofehler wird der nächste vorhandene Weg versucht")
native_grafik = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":1"}
with mock.patch.object(m.os, "environ", native_grafik):
    m._grafik_kompatibilitaet_einrichten()
pruefe("WEBKIT_DISABLE_DMABUF_RENDERER" not in native_grafik and
       "GDK_BACKEND" not in native_grafik,
       "Wayland und DMA-BUF bleiben im Normalbetrieb nativ")
kompatible_grafik = {"MAGNOLIE_GRAPHICS_COMPAT": "1",
                     "WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":1"}
with mock.patch.object(m.os, "environ", kompatible_grafik):
    m._grafik_kompatibilitaet_einrichten()
pruefe(kompatible_grafik.get("WEBKIT_DISABLE_DMABUF_RENDERER") == "1" and
       kompatible_grafik.get("GDK_BACKEND") == "x11" and
       "WEBKIT_DISABLE_COMPOSITING_MODE" not in kompatible_grafik,
       "der explizite Grafikfallback nutzt XWayland ohne Compositing-Bremse")

# Eigener Klang der Magnolie
klangdatei = m.finde_klang_datei()
pruefe(bool(klangdatei) and klangdatei.endswith("erinnerung.wav"),
       "der mitgelieferte Klang wird gefunden: %s" % klangdatei)
import wave as _wave
_datei = _wave.open(klangdatei)
pruefe(_datei.getframerate() == 44100 and _datei.getsampwidth() == 2,
       "Klang liegt in gewohnter Güte vor")
_dauer = _datei.getnframes() / _datei.getframerate()
pruefe(1.0 < _dauer < 3.0, "Klang dauert %.1f s – kurz genug" % _dauer)
import array as _array
_werte = _array.array("h")
_werte.frombytes(_datei.readframes(_datei.getnframes()))
pruefe(max(abs(w) for w in _werte) > 10000, "der Klang ist deutlich hörbar")
pruefe(abs(_werte[0]) < 500 and abs(_werte[-1]) < 500,
       "der Klang beginnt und endet ohne Knacken")

wege = m.klang_befehle("/tmp/x.wav")
pruefe(wege[0][0] == "paplay" and any(b[0] == "aplay" for b in wege),
       "mehrere Abspielwege stehen bereit")
pruefe(all("/tmp/x.wav" in b for b in wege), "jeder Weg bekommt die Datei")

weckruf_regional_alt = dict(m._REGIONAL)
m._REGIONAL["timeZone"] = "America/New_York"
from zoneinfo import ZoneInfo as _ZoneInfo
organizer_jetzt = m._organizer_jetzt()
erwartet_jetzt = datetime.now(timezone.utc).astimezone(
    _ZoneInfo("America/New_York")).replace(tzinfo=None)
pruefe(abs((organizer_jetzt - erwartet_jetzt).total_seconds()) < 2,
       "Hintergrundwecker verwendet die aktuelle Organizer-Wandzeit")
m._REGIONAL["timeZone"] = "Europe/Berlin"
befehl = m.weckruf_befehl(_dt(2026, 7, 25, 15, 45))
pruefe("--timer-property=WakeSystem=true" in befehl,
       "Weckruf verlangt das Aufwachen")
pruefe("--on-calendar=2026-07-25 15:45:00 Europe/Berlin" in befehl,
       "Weckzeit und Organizer-Zeitzone stehen im Befehl: %r" % befehl)
sommerluecke = m.weckruf_befehl(_dt(2026, 3, 29, 2, 30))
pruefe("--on-calendar=2026-03-29 03:30:00 Europe/Berlin" in sommerluecke,
       "nicht existente Ortszeit wird auf den ersten gültigen Weckzeitpunkt gelegt")
rueckstellung = m.weckruf_befehl(_dt(2026, 10, 25, 2, 30))
pruefe("--on-calendar=2026-10-25 02:30:00 Europe/Berlin" in rueckstellung,
       "mehrdeutige Ortszeit bleibt als einmalig markierte erste Instanz erhalten")
m._REGIONAL.clear()
m._REGIONAL.update(weckruf_regional_alt)
gestoppte_weckrufe = []
pruefe(m.weckruf_stellen(None, lambda argumente: gestoppte_weckrufe.append(argumente) or 0)["ok"]
       is False and gestoppte_weckrufe == [["systemctl", "--user", "stop",
                                            m.ERINNERUNG_EINHEIT + "-weckruf.timer"]],
       "ohne Zeitpunkt wird ein alter Weckruf entfernt")

pruefe("OnCalendar=*:0/1" in m.systemd_wecker_text() and
       "Persistent=true" in m.systemd_wecker_text(),
       "Der Dienst sieht jede Minute nach und holt Versäumtes nach")
pruefe("--erinnerung" in m.systemd_dienst_text() and
       ('ExecStart="%s"' % m.eigener_pfad()) in m.systemd_dienst_text(),
       "Der Dienst ruft das Programm im Weckbetrieb auf")

dienstordner = tempfile.mkdtemp(prefix="magnolie-dienst-")
laeufe = []
erg = m.erinnerungsdienst_einrichten(True, dienstordner,
                                     lambda a: (laeufe.append(a), 0)[1])
pruefe(erg["ok"] is True, "Dienst lässt sich einrichten: %s" % erg.get("fehler"))
pruefe(os.path.isfile(os.path.join(dienstordner, "magnolie-erinnerung.timer")),
       "Weckerdatei wurde angelegt")
pruefe(any("enable" in " ".join(a) for a in laeufe), "Dienst wird eingeschaltet")
erg = m.erinnerungsdienst_einrichten(False, dienstordner,
                                     lambda a: (laeufe.append(a), 0)[1])
pruefe(not os.path.exists(os.path.join(dienstordner, "magnolie-erinnerung.timer")),
       "Abschalten räumt die Dateien wieder weg")

print()
print("— Frühere Systemkalender-Zuordnung entfernen —")

kalender_standard = {"text/calendar": "magnolie-organizer.desktop"}
kalender_aufrufe = []
kalender_merker = os.path.join(tempfile.mkdtemp(prefix="magnolie-kalender-"),
                               "systemkalender.json")
with open(kalender_merker, "w", encoding="utf-8") as datei:
    json.dump({"vorher": {
        "text/calendar": "org.gnome.Calendar.desktop"}}, datei)


def _kalender_abfragen(mime_typ):
    return kalender_standard.get(mime_typ, "")


def _kalender_setzen(mime_typ, desktop):
    kalender_aufrufe.append((mime_typ, desktop))
    kalender_standard[mime_typ] = desktop
    return True


erg = m.systemkalender_bereinigen(
    merkdatei=kalender_merker, abfrager=_kalender_abfragen,
    setzer=_kalender_setzen)
pruefe(erg and
       kalender_standard["text/calendar"] == "org.gnome.Calendar.desktop",
       "die alte Zuordnung wird entfernt und der vorige Kalender wiederhergestellt")
pruefe(not os.path.exists(kalender_merker),
       "die nicht mehr benötigte Merkdatei wird entfernt")

kalender_standard["text/calendar"] = "magnolie-organizer.desktop"
erg = m.systemkalender_bereinigen(
    merkdatei=kalender_merker, abfrager=_kalender_abfragen,
    setzer=_kalender_setzen, ersatz="org.example.Calendar.desktop")
pruefe(erg and
       kalender_standard["text/calendar"] == "org.example.Calendar.desktop",
       "ohne Merkdatei wird ein anderer installierter Kalender gewählt")

with open(kalender_merker, "w", encoding="utf-8") as datei:
    json.dump({"vorher": {
        "text/calendar": "org.gnome.Calendar.desktop"}}, datei)
kalender_standard["text/calendar"] = "org.example.NewCalendar.desktop"
erg = m.systemkalender_bereinigen(
    merkdatei=kalender_merker, abfrager=_kalender_abfragen,
    setzer=_kalender_setzen)
pruefe(erg and
       kalender_standard["text/calendar"] == "org.example.NewCalendar.desktop",
       "eine später von Hand gewählte Kalenderanwendung wird nicht überschrieben")
pruefe(not hasattr(m, "systemkalender_schalten"),
       "Magnolie kann sich nicht mehr als Systemkalender eintragen")

mimeapps = os.path.join(tempfile.mkdtemp(prefix="magnolie-mimeapps-"),
                        "mimeapps.list")
with open(mimeapps, "w", encoding="utf-8") as datei:
    datei.write("[Default Applications]\n"
                "text/calendar=magnolie-organizer.desktop;\n"
                "text/plain=org.x.editor.desktop;\n")
m._systemkalender_standard_entfernen("text/calendar", [mimeapps])
with open(mimeapps, encoding="utf-8") as datei:
    mimeapps_inhalt = datei.read()
pruefe("magnolie-organizer.desktop" not in mimeapps_inhalt and
       "text/plain=org.x.editor.desktop" in mimeapps_inhalt,
       "nur Magnolies frühere MIME-Zuordnung wird entfernt")

print()
print("— Öffnen aus der Benachrichtigung —")

gestartet = []
_welcher_echt = m.shutil.which
m.shutil.which = lambda name: ("/usr/bin/" + name
                                if name in ("gtk-launch", "gio") else None)
try:
    weg = m.organizer_starten(lambda a: gestartet.append(a))
finally:
    m.shutil.which = _welcher_echt
pruefe(weg == "gtk-launch", "der erste verfügbare Startweg wurde gewählt: %s" % weg)
pruefe(gestartet == [["/usr/bin/gtk-launch", "io.gitlab.maik3531.MagnolieOrganizer"]],
       "der Startbefehl wurde tatsächlich abgesetzt")


def _starter_kaputt(argumente):
    raise OSError("geht nicht")


pruefe(m.organizer_starten(_starter_kaputt) == "",
       "scheitern alle Wege, wird das ehrlich gemeldet")

pruefe("magnolie-meldung" in m.MAGNOLIE_MELDUNG_STIL.decode("utf-8") and
       "#f6efdc" in m.MAGNOLIE_MELDUNG_STIL.decode("utf-8"),
       "das eigene Meldeblatt trägt den Papierton")
_anzeige_alt = {name: os.environ.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY")}
try:
    os.environ.pop("DISPLAY", None)
    os.environ.pop("WAYLAND_DISPLAY", None)
    pruefe(m.magnolie_meldung("Probe", "ohne Bildschirm") is False,
           "ohne Bildschirm scheitert das eigene Blatt still")
    pruefe(m.melden("Probe", "Text", "magnolie") in ("", "system"),
           "ohne Bildschirm fällt melden() sauber zurück")
finally:
    for _name, _wert in _anzeige_alt.items():
        if _wert is None:
            os.environ.pop(_name, None)
        else:
            os.environ[_name] = _wert

print()
print("— Umgebung der Sitzung finden —")

prozessordner = tempfile.mkdtemp(prefix="magnolie-proc-")


def _lege_prozess(nummer, eintraege):
    ordner = os.path.join(prozessordner, str(nummer))
    os.makedirs(ordner, exist_ok=True)
    roh = b"\0".join(("%s=%s" % (k, v)).encode("utf-8")
                     for k, v in eintraege.items())
    with open(os.path.join(ordner, "environ"), "wb") as datei:
        datei.write(roh + b"\0")


_lege_prozess(1, {"PATH": "/usr/bin", "HOME": "/root"})          # ohne Anzeige
_lege_prozess(42, {"DISPLAY": ":1", "XAUTHORITY": "/heim/.Xauthority",
                   "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/bus",
                   "XDG_RUNTIME_DIR": "/run/user/1000"})
_lege_prozess(99, {"DISPLAY": ":9"})
os.makedirs(os.path.join(prozessordner, "kein-prozess"), exist_ok=True)

umgebungsprobe = {"PATH": "/usr/bin"}
geholt = m.sitzungsumgebung_uebernehmen(prozessordner, umgebungsprobe)
pruefe(geholt.get("DISPLAY") == ":1",
       "die Anzeige der Sitzung wird gefunden: %r" % geholt.get("DISPLAY"))
pruefe(geholt.get("DBUS_SESSION_BUS_ADDRESS") == "unix:path=/run/bus",
       "auch der Sitzungsbus wird übernommen")
pruefe(umgebungsprobe["XAUTHORITY"] == "/heim/.Xauthority",
       "die Werte landen in der Umgebung")

vorhanden = {"DISPLAY": ":0", "PATH": "/usr/bin"}
pruefe(m.sitzungsumgebung_uebernehmen(prozessordner, vorhanden) == {},
       "ist eine Anzeige da, wird nichts angefasst")
pruefe(vorhanden["DISPLAY"] == ":0", "die vorhandene Anzeige bleibt stehen")

leerer = tempfile.mkdtemp(prefix="magnolie-leer-proc-")
notfall = {"PATH": "/usr/bin"}
pruefe(m.sitzungsumgebung_uebernehmen(leerer, notfall).get("DISPLAY") == ":0",
       "ohne Fund bleibt die übliche erste Anzeige")

_anzeige_alt = {name: os.environ.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY")}
try:
    os.environ.pop("DISPLAY", None)
    os.environ.pop("WAYLAND_DISPLAY", None)
    pruefe(m.anzeige_bereit() is False,
           "ohne echte Anzeige wird kein Fenster versucht")
finally:
    for _name, _wert in _anzeige_alt.items():
        if _wert is None:
            os.environ.pop(_name, None)
        else:
            os.environ[_name] = _wert
pruefe("After=graphical-session.target" in m.systemd_dienst_text(),
       "der Dienst wartet auf die angemeldete Sitzung")
pruefe("TimeoutStartSec=" in m.systemd_dienst_text(),
       "der Dienst hängt nicht endlos an einer offenen Meldung")

bericht = m.erinnerungs_probe()
pruefe(any(z.startswith("Anzeige:") for z in bericht),
       "der Prüfbericht nennt die Anzeige")
pruefe(any(z.startswith("Eigenes Fenster möglich:") for z in bericht),
       "der Prüfbericht sagt, ob ein eigenes Blatt möglich ist")
pruefe(any("Klangdatei" in z for z in bericht),
       "der Prüfbericht nennt die Klangdatei")
pruefe(any(z.startswith("Meldung erschien:") for z in bericht),
       "der Prüfbericht sagt, ob die Meldung ankam")
pruefe(all(isinstance(z, str) and z == z.rstrip() for z in bericht),
       "der Bericht besteht aus sauberen Zeilen")
pruefe(any(z.startswith("Wecker im Hintergrund:") for z in bericht),
       "der Prüfbericht sagt, ob der Wecker läuft")
pruefe(any(z.startswith("Autostart-Eintrag:") for z in bericht),
       "der Prüfbericht nennt den Autostart-Eintrag")

probe_gettext_alt = m._
m._ = m.gettext_uebersetzung("en").gettext
bericht_en = m.erinnerungs_probe()
m._ = probe_gettext_alt
pruefe(any(z.startswith("Display:") for z in bericht_en) and
       any(z.startswith("Own window available:") for z in bericht_en) and
       any(z.startswith("Sound file:") for z in bericht_en) and
       any(z.startswith("Notification appeared:") for z in bericht_en) and
       any(z.startswith("Alarm monitor in background:") for z in bericht_en) and
       any(z.startswith("Autostart entry:") for z in bericht_en),
       "englischer Prüfbericht lokalisiert alle Statusfelder")

def _haupt_ausgabe(argumente, sprache, stderr=False):
    argv_alt = m.sys.argv
    ziel_alt = m.sys.stderr if stderr else m.sys.stdout
    gettext_alt, ngettext_alt = m._, m.ngettext
    uebersetzung_alt = m._UEBERSETZUNG
    regional_alt = dict(m._REGIONAL)
    ziel = m.io.StringIO()
    m.sys.argv = ["magnolie-organizer"] + argumente
    if stderr:
        m.sys.stderr = ziel
    else:
        m.sys.stdout = ziel
    m._ = m.gettext_uebersetzung(sprache).gettext
    try:
        m.haupt()
    except SystemExit as ende:
        code = ende.code
    else:
        code = None
    finally:
        m.sys.argv = argv_alt
        if stderr:
            m.sys.stderr = ziel_alt
        else:
            m.sys.stdout = ziel_alt
        m._ = gettext_alt
        m.ngettext = ngettext_alt
        m._UEBERSETZUNG = uebersetzung_alt
        m._REGIONAL.clear()
        m._REGIONAL.update(regional_alt)
    return code, ziel.getvalue()

hilfe_code_en, hilfe_en = _haupt_ausgabe(["--help"], "en")
hilfe_code_de, hilfe_de = _haupt_ausgabe(["--hilfe"], "de")
pruefe(hilfe_code_en == 0 and "Usage:" in hilfe_en and
       "Open the application" in hilfe_en and
       "-t, --tray-start" in hilfe_en and "--reminder-check" in hilfe_en and
       "--wayland-magnolie-probe" in hilfe_en and "EXPERIMENTAL:" in hilfe_en and
       hilfe_code_de == 0 and "Aufruf:" in hilfe_de and
       "Programm öffnen" in hilfe_de and
       "-t, --tray-start" in hilfe_de and "--erinnerung" in hilfe_de and
       "--wayland-magnolie-probe" in hilfe_de and "EXPERIMENTELL:" in hilfe_de and
       m.befehlszeile_lesen(["--wayland-magnolie-probe"]) == (None, None, None),
        "Befehlsübersicht folgt der Sprache und bewahrt alle Optionen")

hilfe_kurz = _haupt_ausgabe(["-l", "de", "-h"], "en")
version_kurz = _haupt_ausgabe(["-V"], "de")
unbekannt = _haupt_ausgabe(["--does-not-exist"], "de", stderr=True)
unbekannt_override = _haupt_ausgabe(
    ["--language", "de", "--does-not-exist"], "en", stderr=True)
pruefe(hilfe_kurz[0] == 0 and "Aufruf:" in hilfe_kurz[1] and
       version_kurz == (0, m.PROGRAMM_FASSUNG + "\n") and
       unbekannt[0] == 2 and "Unbekannte Option: --does-not-exist" in unbekannt[1] and
       unbekannt_override == (2, "Unbekannte Option: --does-not-exist\n") and
       m.kurzoptionen_normalisieren(["-r", "-w", "-p", "-t", "-d", "-b", "-P"]) ==
       ["--erinnerung", "--wecker", "--probe", "--tray-start", "--debug",
        "--background-service", "--pot-template"],
       "Kurzoptionen, Version und unbekannte Optionen folgen dem CLI-Vertrag")

hilfe_cli_en = _haupt_ausgabe(["--sprache", "en", "--hilfe"], "de")
hilfe_cli_de = _haupt_ausgabe(["--language", "de", "--help"], "en")
pruefe(hilfe_cli_en[0] == 0 and "Usage:" in hilfe_cli_en[1] and
       "Use a supported language code or system" in hilfe_cli_en[1] and
       hilfe_cli_de[0] == 0 and "Aufruf:" in hilfe_cli_de[1] and
       "unterstützten Sprachcode oder system" in hilfe_cli_de[1],
       "explizite deutsche und englische Sprachoptionen gelten vor der Hilfe")

sprache_fehlt = _haupt_ausgabe(["--sprache"], "de", stderr=True)
sprache_fr = _haupt_ausgabe(["--language", "fr", "--help"], "en")
sprache_falsch = _haupt_ausgabe(["--language", "xx"], "en", stderr=True)
pruefe(sprache_fehlt[0] == 2 and "benötigt eine Sprache" in sprache_fehlt[1] and
       sprache_fr[0] == 0 and "Invalid language" not in sprache_fr[1] and
       sprache_falsch[0] == 2 and "Invalid language: xx" in sprache_falsch[1],
       "zusätzliche Sprachen gelten; fehlende und ungültige Werte enden mit Fehler")

man_ordner = os.path.join(os.path.dirname(PFAD), "..", "man")
man_en = open(os.path.join(man_ordner, "magnolie-organizer.1"), encoding="utf-8").read()
man_de = open(os.path.join(man_ordner, "de", "magnolie-organizer.1"), encoding="utf-8").read()
pruefe(all(wert in man_en and wert in man_de for wert in
           (r"\-\-sprache", r"\-\-language", r"\fBar\fR", r"\fBzh_CN\fR",
            r"\fBsystem\fR")),
       "deutsche und englische Manpage nennen Aliasse und alle Sprachcodegruppen")

debug_staat = tempfile.mkdtemp(prefix="magnolie-debug-state-")
debug_umgebung = dict(os.environ)
debug_umgebung["XDG_STATE_HOME"] = debug_staat
debug_aufruf = subprocess.run(
    [sys.executable, PFAD, "--debug", "--language", "en", "--help"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    env=debug_umgebung, check=False)
debug_datei = os.path.join(debug_staat, "magnolie-organizer", "debug.log")
debug_text = open(debug_datei, encoding="utf-8").read() if os.path.isfile(debug_datei) else ""
pruefe(debug_aufruf.returncode == 0 and "Usage:" in debug_aufruf.stdout and
       "Debug log:" in debug_aufruf.stderr and os.path.isfile(debug_datei) and
       os.stat(debug_datei).st_mode & 0o077 == 0 and
       "startup.branch" in debug_text and 'branch="help"' in debug_text and
       "DBUS_SESSION_BUS_ADDRESS=" not in debug_text,
       "--debug schreibt eine private Start- und Traydiagnose ohne Sitzungsbusadresse")

pot_quelle = os.path.join(os.path.dirname(PFAD), "..", "po",
                          "magnolie-organizer.pot")
pot_vorher = open(pot_quelle, "rb").read()
def test_anruf_lautstaerke_restores_exact_default_sink_volume():
    calls = []
    def runner(args, **_kwargs):
        calls.append(args)
        result = type("Result", (), {"returncode": 0, "stdout": ""})()
        if args[1] == "get-default-sink": result.stdout = "sink.test\n"
        if args[1] == "get-sink-volume": result.stdout = "Volume: 80% / 80%\n"
        return result
    duck = m.AnrufLautstaerke(runner=runner, finder=lambda name: "/usr/bin/" + name)
    assert duck.lower("call-a") and duck.lower("call-a")
    assert [call for call in calls if "set-sink-volume" in call] == [
        ["/usr/bin/pactl", "set-sink-volume", "sink.test", "20%"]]
    assert not duck.restore("call-b") and duck.restore("call-a")
    assert calls[-1] == ["/usr/bin/pactl", "set-sink-volume", "sink.test", "80%"]
    assert not duck.restore("call-a")


def test_anruf_bluetooth_is_native_phone_owned():
    # The full fake BlueZ/Pulse lifecycle lives in test_call_audio.py.
    from magnolie_anruf_audio import AnrufBluetooth
    assert m.AnrufBluetooth is AnrufBluetooth
    assert not hasattr(m, "_ANRUF_BLUETOOTH")
    assert not hasattr(m.Fenster, "_telefon_anruf_bluetooth")


if __name__ == "__main__":
    test_anruf_lautstaerke_restores_exact_default_sink_volume()
    test_anruf_bluetooth_is_native_phone_owned()


kommunikation_vertrag = os.path.join(
    QUELLWURZEL, "pruefungen", "kommunikation-msgids.txt")
kommunikation_msgids = {json.loads(zeile) for zeile in open(
    kommunikation_vertrag, encoding="utf-8") if zeile.strip()}
sichtbare_kommunikation_de = {
    "Answer": "Annehmen",
    "Answer calls on the computer and talk": "Anrufe am Computer annehmen und sprechen",
    "Answering the call": "Anruf wird angenommen",
    "Application command": "Programmbefehl",
    "Ending the call": "Anruf wird beendet",
    "Incoming call": "Eingehender Anruf",
    "Lower other sounds while ringing": "Andere Töne während des Klingelns leiser stellen",
    "Notify me about incoming calls": "Über eingehende Anrufe benachrichtigen",
    "The command is started safely without a shell. Use {nummer} for the selected number.":
        "Der Befehl wird sicher ohne Shell gestartet. Verwenden Sie {nummer} für die ausgewählte Rufnummer.",
    "These options require the matching permissions in Magnolie Notes. Call audio is not sent over the Magnolie data connection.":
        "Diese Optionen erfordern die entsprechenden Berechtigungen in Magnolie Notes. Anrufton wird nicht über die Magnolie-Datenverbindung übertragen.",
    "Unknown caller": "Unbekannter Anrufer",
}
# Für diesen sichtbaren Vertrag gibt es keine sprachlich legitimen Gleichheiten.
identische_kommunikation_ausnahmen = set()
po_ordner = os.path.dirname(pot_quelle)
web_i18n_ordner = os.path.join(QUELLWURZEL, "web", "i18n")
for sprache in m.UNTERSTUETZTE_SPRACHEN:
    po_pfad = os.path.join(po_ordner, sprache + ".po")
    po_text = subprocess.check_output(
        ["msgattrib", "--no-obsolete", po_pfad], text=True)
    bloecke = [block for block in po_text.split("\n\n") if "msgid " in block]
    katalog = {}
    unscharf = set()
    for block in bloecke:
        id_zeilen = re.search(r'(?m)^msgid (".*")(\n(?:".*"\n?)*)?', block)
        str_zeilen = re.search(r'(?m)^msgstr (".*")(\n(?:".*"\n?)*)?', block)
        if not id_zeilen or not str_zeilen:
            continue
        msgid = "".join(ast.literal_eval(zeile) for zeile in
                        id_zeilen.group(0).replace("msgid ", "", 1).splitlines())
        msgstr = "".join(ast.literal_eval(zeile) for zeile in
                         str_zeilen.group(0).replace("msgstr ", "", 1).splitlines())
        katalog[msgid] = msgstr
        if "#, fuzzy" in block:
            unscharf.add(msgid)
    pruefe(all(katalog.get(msgid) and msgid not in unscharf
               for msgid in kommunikation_msgids),
            "Kommunikations-msgids sind in %s vollständig und nicht unscharf" % sprache)
    pruefe(all(katalog.get(msgid) != msgid or
               (sprache, msgid) in identische_kommunikation_ausnahmen
               for msgid in sichtbare_kommunikation_de),
            "sichtbare Kommunikations-msgids sind in %s wirklich übersetzt" % sprache)
    if sprache == "de":
        pruefe(all(katalog.get(msgid) == erwartet for msgid, erwartet in
                   sichtbare_kommunikation_de.items()),
               "deutscher PO-Katalog enthält die festgelegten sichtbaren Übersetzungen")
    web_text = open(os.path.join(web_i18n_ordner, sprache + ".js"),
                    encoding="utf-8").read()
    pruefe(all(json.dumps(msgid, ensure_ascii=False) in web_text
               for msgid in kommunikation_msgids),
           "Webkatalog %s enthält alle Kommunikations-msgids" % sprache)
pruefe('"KDE Connect for SMS":"KDE Connect für SMS"' in open(
           os.path.join(web_i18n_ordner, "de.js"), encoding="utf-8").read() and
       '"Reconnect":"Erneut verbinden"' in open(
           os.path.join(web_i18n_ordner, "de.js"), encoding="utf-8").read(),
        "deutscher Webkatalog fällt bei sichtbaren KDE-Texten auf Englisch zurück")
de_web_text = open(os.path.join(web_i18n_ordner, "de.js"), encoding="utf-8").read()
pruefe(all(json.dumps(msgid, ensure_ascii=False) + ":" +
           json.dumps(erwartet, ensure_ascii=False) in de_web_text
           for msgid, erwartet in sichtbare_kommunikation_de.items()),
       "deutscher Webkatalog enthält die festgelegten sichtbaren Übersetzungen")
arbeitsordner = tempfile.mkdtemp(prefix="magnolie-pot-test-")
alter_arbeitsordner = os.getcwd()
try:
    os.chdir(arbeitsordner)
    pot_standard = _haupt_ausgabe(["--sprache", "de", "--pot"], "en")
    pot_eigen = os.path.join(arbeitsordner, "eigen", "vorlage.pot")
    pot_alias = _haupt_ausgabe(
        ["--language", "en", "--pot-template", pot_eigen], "de")
finally:
    os.chdir(alter_arbeitsordner)
pruefe(pot_standard[0] == 0 and
       os.path.isfile(os.path.join(arbeitsordner, "magnolie-organizer.pot")) and
       "POT-Vorlage geschrieben nach:" in pot_standard[1] and
       pot_alias[0] == 0 and os.path.isfile(pot_eigen) and
       "POT template written to:" in pot_alias[1] and
       open(pot_quelle, "rb").read() == pot_vorher,
       "POT-Option und Alias schreiben Standard- und Zielpfad ohne Quell-POT")

installiert = os.path.join(arbeitsordner, "share", "magnolie-organizer")
installiert_web = os.path.join(installiert, "web")
os.makedirs(installiert_web)
for name in ("i18n-markers.js", "anwendung.js"):
    with open(os.path.join(installiert_web, name), "w", encoding="utf-8") as datei:
        datei.write("gettext('test');\n")
installierter_start = os.path.join(arbeitsordner, "magnolie-organizer")
with open(installierter_start, "w", encoding="utf-8") as datei:
    datei.write("#!/usr/bin/env python3\n")
installierter_hintergrund = os.path.join(arbeitsordner, "magnolie_hintergrund.py")
with open(installierter_hintergrund, "w", encoding="utf-8") as datei:
    datei.write("#!/usr/bin/env python3\n")
installierte_setup_ui = os.path.join(arbeitsordner, "magnolie_setup_ui.py")
with open(installierte_setup_ui, "w", encoding="utf-8") as datei:
    datei.write("#!/usr/bin/env python3\n")
pot_lader = importlib.machinery.SourceFileLoader(
    "magorg_pot", os.path.join(os.path.dirname(PFAD), "..", "werkzeuge",
                               "pot_erzeugen.py"))
pot_spec = importlib.util.spec_from_loader("magorg_pot", pot_lader)
pot_modul = importlib.util.module_from_spec(pot_spec)
pot_lader.exec_module(pot_modul)
installierte_quellen = pot_modul.quellen_finden(installiert, installierter_start)
pruefe(installierte_quellen == [
           os.path.join(installiert_web, "i18n-markers.js"),
           os.path.join(installiert_web, "anwendung.js"), installierter_start,
           installierter_hintergrund, installierte_setup_ui],
       "POT-Erzeuger findet Webquellen und Launcher im installierten Aufbau")

pot_erzeugen_alt = m.pot_erzeugen
def _pot_fehler(_ziel):
    raise FileNotFoundError("xgettext")
m.pot_erzeugen = _pot_fehler
pot_fehler = _haupt_ausgabe(["--sprache", "de", "--pot"], "en", stderr=True)
m.pot_erzeugen = pot_erzeugen_alt
pruefe(pot_fehler[0] == 1 and
       "POT-Vorlage konnte nicht erzeugt werden: xgettext" in pot_fehler[1],
       "fehlendes xgettext erzeugt einen lokalisierten POT-Fehler")

probe_alt = m.erinnerungs_probe
m.erinnerungs_probe = lambda: ["Display: none"]
probe_code, probe_ausgabe = _haupt_ausgabe(["--probe"], "en")
m.erinnerungs_probe = probe_alt
pruefe(probe_code == 0 and probe_ausgabe.startswith("Reminder test\n") and
       probe_ausgabe.endswith("Display: none\n"),
       "englischer Probeaufruf trägt lokalisierte Überschrift")

gtk_alt, gtk_fehler_alt = m.GTK_OK, m.GTK_FEHLER
bereinigen_alt = m.systemkalender_bereinigen
m.GTK_OK, m.GTK_FEHLER = False, "technical GTK detail"
m.systemkalender_bereinigen = lambda: None
gtk_code, gtk_ausgabe = _haupt_ausgabe([], "en", stderr=True)
m.GTK_OK, m.GTK_FEHLER = gtk_alt, gtk_fehler_alt
m.systemkalender_bereinigen = bereinigen_alt
pruefe(gtk_code == 1 and
       "Magnolie Organizer requires GTK 3 and WebKit2GTK." in gtk_ausgabe and
       "sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1" in gtk_ausgabe and
       "Error: technical GTK detail" in gtk_ausgabe,
       "englischer Startfehler bewahrt Paketbefehl und technische Einzelheit")

print()
print("— Wecker im Hintergrund —")

autostartprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-auto-"),
                              "autostart", "magnolie-erinnerung.desktop")
erg = m.autostart_einrichten(True, autostartprobe)
pruefe(erg["ok"] and os.path.isfile(autostartprobe),
       "Autostart-Eintrag wird angelegt")
inhalt = open(autostartprobe, encoding="utf-8").read()
pruefe(('Exec="%s" --wecker' % m.eigener_pfad()) in inhalt,
       "der Eintrag startet den Wecker")
pruefe("NoDisplay=true" in inhalt and "Type=Application" in inhalt,
       "der Eintrag bleibt im Menü unsichtbar")
pruefe(m.autostart_einrichten(False, autostartprobe)["ok"] and
       not os.path.exists(autostartprobe),
       "Abschalten entfernt den Eintrag wieder")

markenprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-marke-"), "wecker.pid")
pruefe(m.wecker_lebt(markenprobe) is False, "ohne Marke wacht niemand")
with open(markenprobe, "w", encoding="utf-8") as datei:
    datei.write("999999")
pruefe(m.wecker_lebt(markenprobe) is False,
       "eine Marke ohne lebenden Prozess zählt nicht")
with open(markenprobe, "w", encoding="utf-8") as datei:
    datei.write("1")
pruefe(m.wecker_lebt(markenprobe) is False,
       "ein fremder Prozess mit gleicher Nummer zählt nicht als Wecker")

# Nach einem Neustart trägt die liegengebliebene Marke oft eine Nummer,
# die inzwischen einem ganz anderen Prozess gehört.
prozessprobe = tempfile.mkdtemp(prefix="magnolie-cmd-")
def _lege_befehl(nummer, text):
    ordner = os.path.join(prozessprobe, str(nummer))
    os.makedirs(ordner, exist_ok=True)
    with open(os.path.join(ordner, "cmdline"), "wb") as datei:
        datei.write(text.replace(" ", "\0").encode("utf-8") + b"\0")

_lege_befehl(101, "/usr/bin/magnolie-organizer --wecker")
_lege_befehl(102, "/usr/lib/firefox/firefox")
_lege_befehl(103, "/usr/bin/magnolie-organizer")
pruefe(m.ist_unser_wecker(101, prozessprobe) is True,
       "unser Wecker wird an der Befehlszeile erkannt")
pruefe(m.ist_unser_wecker(102, prozessprobe) is False,
       "ein fremdes Programm wird nicht verwechselt")
pruefe(m.ist_unser_wecker(103, prozessprobe) is False,
       "der Organizer selbst ist noch kein Wecker")
pruefe(m.ist_unser_wecker(999, prozessprobe) is False,
       "ohne Einblick gilt: kein Wecker")
with open(markenprobe, "w", encoding="utf-8") as datei:
    datei.write("kein Zahlenwert")
pruefe(m.wecker_lebt(markenprobe) is False, "unbrauchbare Marke stört nicht")

laeufe = []
geschlafen = []
zahl = m.wecker_schleife(takt=30, hoechstens=3,
                         schlafen=lambda s: geschlafen.append(s),
                         lauf=lambda: laeufe.append(1))
pruefe(zahl == 3 and len(laeufe) == 3, "der Wecker sieht wiederholt nach")
pruefe(geschlafen == [30, 30], "zwischen den Durchgängen wird gewartet")


def _lauf_mit_fehler():
    laeufe.append(1)
    raise RuntimeError("etwas ging schief")


m.wecker_schleife(takt=5, hoechstens=2, schlafen=lambda s: None,
                  lauf=_lauf_mit_fehler)
pruefe(len(laeufe) == 5, "ein Fehlschlag hält den Wecker nicht auf")

log_notiz_alt, log_gettext_alt = m.wecker_notiz, m._
log_meldungen = []
m.wecker_notiz = lambda text, *args, **kwargs: log_meldungen.append(text)
m._ = en_uebersetzung.gettext
m.wecker_schleife(takt=5, hoechstens=1, schlafen=lambda s: None,
                  lauf=lambda: (_ for _ in ()).throw(RuntimeError("technical detail")))
m._ = de_uebersetzung.gettext
m.wecker_schleife(takt=5, hoechstens=1, schlafen=lambda s: None,
                  lauf=lambda: (_ for _ in ()).throw(RuntimeError("technische Einzelheit")))
m.wecker_notiz, m._ = log_notiz_alt, log_gettext_alt
pruefe(log_meldungen == ["Run failed: technical detail",
                         "Durchgang fehlgeschlagen: technische Einzelheit"],
       "Weckerfehler folgen der Sprache und bewahren technische Einzelheiten")

log_texte = {
    "Alarm monitor start canceled – one is already running.":
        "Start abgebrochen – es wacht bereits einer.",
    "Alarm monitor stopped.": "Wecker beendet.",
    "Event loop is not available: %s": "Ereignisschleife nicht möglich: %s",
    "Operation ended (%s).": "Betrieb beendet (%s).",
    "Run failed: %s": "Durchgang fehlgeschlagen: %s",
    "Magnolie sheet": "Blatt der Magnolie",
    "system notification": "Meldung des Systems",
    "not delivered": "nicht angekommen",
    "event loop": "Ereignisschleife",
    "waiting loop": "Warteschleife",
}
pruefe(all(de_uebersetzung.gettext(quelle) == deutsch and
           en_uebersetzung.gettext(quelle) == quelle
           for quelle, deutsch in log_texte.items()),
       "Zustellwege und Betriebsarten des Weckerprotokolls sind vollständig lokalisiert")
log_nutzdaten = en_uebersetzung.gettext(
    "Reported (%(method)s): %(title)s – %(body)s") % {
        "method": "system notification", "title": "Mülltonne rausstellen",
        "body": "technical detail"}
pruefe("Mülltonne rausstellen" in log_nutzdaten and
       "technical detail" in log_nutzdaten,
       "englische Logvorlage verändert weder Titel noch technischen Text")

gtk_code_alt, glib_alt = m.GTK_OK, m.GLib
schleife_alt, erinnerungslauf_alt = m.wecker_schleife, m.erinnerungslauf
class _ProbeSchleife:
    def run(self):
        pass
class _ProbeGLib:
    @staticmethod
    def timeout_add_seconds(*_args):
        return 1
    @staticmethod
    def MainLoop():
        return _ProbeSchleife()
m.GTK_OK, m.GLib = True, _ProbeGLib
m.erinnerungslauf = lambda **_kwargs: {"gemeldet": 0, "fehler": ""}
ereignis_code = m.wecker_betrieb()
m.GTK_OK = False
m.wecker_schleife = lambda **_kwargs: 1
warte_code = m.wecker_betrieb()
m.GTK_OK, m.GLib = gtk_code_alt, glib_alt
m.wecker_schleife, m.erinnerungslauf = schleife_alt, erinnerungslauf_alt
pruefe((ereignis_code, warte_code) == ("ereignisschleife", "warteschleife"),
       "interne Betriebsarten bleiben durch die Lokalisierung unverändert")

gestartete = []
wecker_lebt_original = m.wecker_lebt
m.wecker_lebt = lambda: False
try:
    pruefe(m.wecker_starten(lambda a: gestartete.append(a)) == "gestartet",
           "der Wecker lässt sich sofort starten")
finally:
    m.wecker_lebt = wecker_lebt_original
pruefe(gestartete and gestartete[0][-1] == "--wecker",
       "und zwar im Weckbetrieb: %r" % (gestartete[0] if gestartete else None))

protokollprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-log-"), "wecker.log")
pruefe(m._PROTOKOLL["an"] is False,
       "das Protokoll ist voreingestellt abgeschaltet")
m._PROTOKOLL["an"] = True
m.wecker_notiz("Erster Eintrag", protokollprobe)
m.wecker_notiz("Zweiter Eintrag", protokollprobe)
zeilen = m.wecker_protokoll_lesen(10, protokollprobe)
pruefe(len(zeilen) == 2 and zeilen[1].endswith("Zweiter Eintrag"),
       "das Protokoll sammelt Einträge: %r" % zeilen[-1:])
pruefe(zeilen[0][:2].isdigit() and "." in zeilen[0][:10],
       "jede Zeile beginnt mit Datum und Uhrzeit")
for nummer in range(30):
    m.wecker_notiz("Eintrag %d" % nummer, protokollprobe, hoechstens=10)
zeilen = m.wecker_protokoll_lesen(50, protokollprobe)
pruefe(len(zeilen) == 10, "das Protokoll bleibt klein: %d Zeilen" % len(zeilen))
pruefe(zeilen[-1].endswith("Eintrag 29"), "die neuesten Zeilen bleiben stehen")
pruefe(m.wecker_protokoll_lesen(5, protokollprobe + "-weg") == [],
       "fehlendes Protokoll stört nicht")

print()
print("— Magnolienbaum: Schlüssel und Paarung —")

with open(os.path.join(QUELLWURZEL, "debian", "install"),
          encoding="utf-8") as datei:
    paket_installation = datei.read()
pruefe(not any(marker in paket_installation.upper() for marker in (
           "REVIEW", "ENTWURF", "OFFENE-PUNKTE", "ANALYSE", "AUDIT")),
       "interne Arbeitsnotizen werden nicht installiert")

pruefe(m.baum_moeglich() is True, "der Baum steht zur Verfügung")

zweig_a = m.baum_schluessel_erzeugen("Küche")
zweig_b = m.baum_schluessel_erzeugen("Werkstatt")
pruefe(len(zweig_a["kennung"]) == 16 and zweig_a["kennung"] != zweig_b["kennung"],
       "jede Instanz bekommt eine eigene Kennung")
pruefe(zweig_a["geheim"] != zweig_b["geheim"] and len(zweig_a["geheim"]) > 40,
       "jede Instanz bekommt ein eigenes Schlüsselpaar")
pruefe(zweig_a["an"] is False, "der Baum ist zunächst abgeschaltet")

baum_identitaet_ordner = tempfile.mkdtemp(prefix="magnolie-baum-identitaet-")
baum_identitaet_pfad = m.baum_datei(baum_identitaet_ordner)
zweig_a["partner"] = [{"kennung": zweig_b["kennung"], "name": "Werkstatt Geheim",
    "oeffentlich": zweig_b["oeffentlich"], "adresse": "192.0.2.44", "port": 8737,
    "bestaetigt": True, "zaehler_raus": 7, "zaehler_rein": 5}]
with open(baum_identitaet_pfad, "w", encoding="utf-8") as datei:
    json.dump(zweig_a, datei, ensure_ascii=False)
gelesener_baum, baum_dek, baum_dek_kennung, baum_umschlag = m.baum_lesen(
    baum_identitaet_pfad, "Blütenblatt 2026", True)
with open(baum_identitaet_pfad, "r", encoding="utf-8") as datei:
    baum_identitaet_roh = datei.read()
pruefe(m.baum_datei_ist_verschluesselt(baum_identitaet_roh) and
       zweig_a["geheim"] not in baum_identitaet_roh and
       "Werkstatt Geheim" not in baum_identitaet_roh and
       "192.0.2.44" not in baum_identitaet_roh,
       "privater Baumschlüssel und Partnermetadaten liegen nicht im Klartext")
pruefe(gelesener_baum["geheim"] == zweig_a["geheim"] and
       gelesener_baum["partner"][0]["zaehler_rein"] == 5 and
       gelesener_baum["partner"][0]["vertraut"] is False and
       gelesener_baum["partner"][0]["fernAdresse"] == "" and
       gelesener_baum["partner"][0]["fernPort"] == m.BAUM_PORT and
       len(baum_dek) == 32 and len(baum_dek_kennung) == 16,
       "die verschlüsselte Baumidentität kommt vollständig zurück und migriert "
       "alte Partner vorsichtig")
baum_roh_vor_falsch = baum_identitaet_roh
try:
    m.baum_lesen(baum_identitaet_pfad, "falsch", True)
    pruefe(False, "ein falsches Kennwort dürfte die Baumidentität nicht öffnen")
except RuntimeError:
    with open(baum_identitaet_pfad, "r", encoding="utf-8") as datei:
        pruefe(datei.read() == baum_roh_vor_falsch,
               "ein falsches Kennwort verändert die Baumidentität nicht")

baum_huelle_vor = json.loads(baum_identitaet_roh)
m.baum_ablagen_umschluesseln(
    "Neues Blütenblatt", "Blütenblatt 2026", baum_identitaet_ordner)
with open(baum_identitaet_pfad, "r", encoding="utf-8") as datei:
    baum_huelle_nach = json.load(datei)
pruefe(baum_huelle_nach["daten"] == baum_huelle_vor["daten"] and
       baum_huelle_nach["datenNonce"] == baum_huelle_vor["datenNonce"] and
       baum_huelle_nach["dekDaten"] != baum_huelle_vor["dekDaten"],
       "Kennwortwechsel umhüllt nur den DEK und lässt die Baumnutzdaten bytegleich")
pruefe(m.baum_lesen(baum_identitaet_pfad, "Neues Blütenblatt")["geheim"] ==
       zweig_a["geheim"], "die Baumidentität übersteht den Kennwortwechsel")
m.baum_ablagen_umschluesseln("", "Neues Blütenblatt", baum_identitaet_ordner)
with open(baum_identitaet_pfad, encoding="utf-8") as datei:
    baum_freigegeben_roh = datei.read()
pruefe(m.baum_lesen(baum_identitaet_pfad)["geheim"] == zweig_a["geheim"] and
       not m.baum_datei_ist_verschluesselt(baum_freigegeben_roh),
       "Kennwortentfernung gibt dieselbe Baumidentität wieder frei")

baum_defekt_pfad = os.path.join(baum_identitaet_ordner, "defekt.json")
with open(baum_defekt_pfad, "w", encoding="utf-8") as datei:
    datei.write('{"kennung":"nicht ersetzen"')
try:
    m.baum_lesen(baum_defekt_pfad)
    pruefe(False, "eine beschädigte Baumidentität dürfte nicht ersetzt werden")
except RuntimeError:
    with open(baum_defekt_pfad, "r", encoding="utf-8") as datei:
        pruefe(datei.read() == '{"kennung":"nicht ersetzen"',
               "eine beschädigte Baumidentität bleibt zur Rettung unangetastet")

abdruck = m.fingerabdruck(zweig_a["oeffentlich"])
pruefe(len(abdruck) == 19 and abdruck.count("-") == 3,
       "der Fingerabdruck ist gut vorlesbar: %s" % abdruck)
pruefe(m.fingerabdruck(zweig_a["oeffentlich"]) == abdruck,
       "und bleibt gleich")
pruefe(m.fingerabdruck(zweig_b["oeffentlich"]) != abdruck,
       "verschiedene Schlüssel, verschiedene Abdrücke")
pruefe(m.baum_fingerabdruck_normieren(abdruck.lower().replace("-", " ")) == abdruck,
       "ein eingetippter Fingerabdruck wird sicher vereinheitlicht")
pruefe(m.baum_fingerabdruck_normieren("ABCD") == "",
       "ein unvollständiger Fingerabdruck wird abgewiesen")
pruefe(m.baum_oeffentliche_adresse(holer=lambda: "8.8.8.8") == "8.8.8.8",
       "eine öffentliche Internetadresse wird erkannt")
pruefe(m.baum_oeffentliche_adresse(holer=lambda: "2001:4860:4860::8888") ==
       "2001:4860:4860::8888", "auch eine öffentliche IPv6-Adresse wird erkannt")
pruefe(m.baum_url("2001:db8::7", 8737, "/magnolie/v1/paarung") ==
       "http://[2001:db8::7]:8737/magnolie/v1/paarung" and
       m.baum_url("fe80::1%eth0", 8737) == "http://[fe80::1%25eth0]:8737" and
       m.baum_host_port_anzeigen("::1", 8737) == "[::1]:8737",
       "IPv6-Adressen werden an URL- und Anzeigegrenzen eindeutig geklammert")
pruefe(m.baum_host_normieren("BÜRO.local") == "xn--bro-hoa.local" and
       m.baum_quelladresse_normieren("::ffff:127.0.0.1") == "127.0.0.1",
       "Hostnamen und IPv4-abgebildete IPv6-Quellen werden kanonisiert")
meldung = m.baum_benachrichtigungstext(
    {"name": "Werkstatt"}, {"art": "notiz"})
pruefe(meldung and "Werkstatt" in meldung[1] and
       "gemeinsame Notiz freigeben" in meldung[1] and
       m.baum_benachrichtigungstext({}, {"art": "notiz_sync"}) is None and
       m.baum_benachrichtigungstext(
           {"vertraut": True}, {"art": "aufgabe"}) is None and
       m.baum_benachrichtigungstext(
           {"vertraut": True}, {"art": "unbekannt"}) is None,
       "nur entscheidungspflichtige, nicht automatisch behandelte Angebote "
       "erzeugen eine Benachrichtigung")

kontakt_sync = {
    "art": "kontakt_sync", "fassung": 1, "freigabeId": "werkstatt:k1",
    "version": 2, "quelle": "werkstatt", "geaendert": 1786500000000,
    "kontakt": {"vorname": "Ada", "nachname": "Lovelace", "firma": "",
                "notiz": "Mathematik", "geburtstag": "1815-12-10",
                "telefone": [{"art": "mobil", "wert": "+49 170 123"}],
                "emailEintraege": [{"art": "arbeit", "wert": "ada@example.test"}],
                "anschriften": [{"art": "privat", "strasse": "Main Street 1",
                                  "plz": "12345", "ort": "London", "region": "",
                                  "land": "UK"}]}}
pruefe(m.baum_kontakt_sync_pruefen(kontakt_sync) is kontakt_sync,
       "kontakt_sync akzeptiert exakt den interoperablen Vertrag")
kontakt_sync_jahrlos = json.loads(json.dumps(kontakt_sync))
kontakt_sync_jahrlos["kontakt"]["geburtstag"] = "--12-10"
pruefe(m.baum_kontakt_sync_pruefen(kontakt_sync_jahrlos) is kontakt_sync_jahrlos,
       "kontakt_sync akzeptiert ein kanonisches jahrloses Geburtsdatum")
kontakt_sync_foto = json.loads(json.dumps(kontakt_sync))
kontakt_sync_foto["kontakt"]["foto"] = "data:image/png;base64,iVBORw0KGgo="
pruefe(m.baum_kontakt_sync_pruefen(kontakt_sync_foto) is kontakt_sync_foto,
       "kontakt_sync akzeptiert ein optionales gültiges Foto bytegetreu")
kontakt_sync_nullzeit = json.loads(json.dumps(kontakt_sync))
kontakt_sync_nullzeit["geaendert"] = 0
pruefe(m.baum_kontakt_sync_pruefen(kontakt_sync_nullzeit) is kontakt_sync_nullzeit,
       "kontakt_sync erlaubt den Millisekunden-Zeitstempel null")
kontakt_fehler = []
for aenderung in (
        lambda x: x.update(fassung=2),
        lambda x: x.update(version=True),
        lambda x: x.update(freigabeId="x" * 129),
        lambda x: x["kontakt"].update(foto="data:image/gif;base64,R0lGODlh"),
        lambda x: x["kontakt"].update(foto="data:image/png;base64,iV BO"),
        lambda x: x["kontakt"].update(foto="data:image/png;base64,%%%"),
        lambda x: x["kontakt"].update(foto="data:image/png;base64,"),
        lambda x: x["kontakt"].update(foto="data:image/png;base64," +
                                      "A" * 2800000),
        lambda x: x["kontakt"].update(telefone=[{"art": "x", "wert": "data:image/png"}]),
        lambda x: x["kontakt"].update(geloescht=True),
        lambda x: x["kontakt"].update(telefone=[{"art": "delete", "wert": "1"}])):
    probe = json.loads(json.dumps(kontakt_sync))
    aenderung(probe)
    try:
        m.baum_kontakt_sync_pruefen(probe)
    except RuntimeError:
        kontakt_fehler.append(True)
pruefe(len(kontakt_fehler) == 11,
       "kontakt_sync lehnt Fassung, Typen, Überlängen, fremde/kaputte Fotos und Löschmarker ab")
ungueltige_kontaktdaten = 0
for datum in ("--02-30", "2000-2-03", " 2000-02-03 "):
    probe = json.loads(json.dumps(kontakt_sync))
    probe["kontakt"]["geburtstag"] = datum
    try:
        m.baum_kontakt_sync_pruefen(probe)
    except RuntimeError:
        ungueltige_kontaktdaten += 1
pruefe(ungueltige_kontaktdaten == 3,
       "kontakt_sync lehnt ungültige oder nicht kanonische Geburtsdaten ab")
kontakt_post = []
m.baum_einreihen(kontakt_post, zweig_b["kennung"], "kontakt_sync", kontakt_sync)
pruefe(kontakt_post[0]["inhalt"] == kontakt_sync,
       "kontakt_sync wird nur nach nativer Sendevalidierung eingereiht")
try:
    m.baum_einreihen([], zweig_b["kennung"], "kontakt_sync", {"art": "kontakt_sync"})
    pruefe(False, "ungültiges kontakt_sync dürfte nicht in den Postausgang gelangen")
except RuntimeError:
    pruefe(True, "ungültiges kontakt_sync gelangt nicht in den Postausgang")
kontakt_loeschen = {"art": "kontakt_loeschen", "fassung": 1,
                    "freigabeId": "werkstatt:k1", "version": 3,
                    "quelle": "werkstatt", "geaendert": 1786500000001}
pruefe(m.baum_kontakt_loeschen_pruefen(kontakt_loeschen) is kontakt_loeschen,
       "kontakt_loeschen akzeptiert exakt den manuellen Löschvertrag")
loesch_fehler = 0
for probe in ({**kontakt_loeschen, "fassung": 2},
              {**kontakt_loeschen, "version": 0},
              {**kontakt_loeschen, "freigabeId": "x" * 129},
              {**kontakt_loeschen, "geloescht": True}):
    try:
        m.baum_kontakt_loeschen_pruefen(probe)
    except RuntimeError:
        loesch_fehler += 1
pruefe(loesch_fehler == 4,
       "kontakt_loeschen lehnt Fassung, Version, Überlänge und Zusatzfelder ab")
loesch_post = []
m.baum_einreihen(loesch_post, zweig_b["kennung"], "kontakt_loeschen",
                 kontakt_loeschen)
pruefe(loesch_post[0]["inhalt"] == kontakt_loeschen,
       "kontakt_loeschen wird nur nach nativer Validierung eingereiht")

code_hin = m.paarungs_code(zweig_a["oeffentlich"], zweig_b["oeffentlich"])
code_her = m.paarungs_code(zweig_b["oeffentlich"], zweig_a["oeffentlich"])
pruefe(code_hin == code_her,
       "beide Seiten errechnen denselben Code: %s" % code_hin)
pruefe(len(code_hin) == 7 and code_hin[3] == " ",
       "der Code hat sechs Ziffern mit Lücke: %r" % code_hin)
dritter = m.baum_schluessel_erzeugen("Fremder")
pruefe(m.paarungs_code(zweig_a["oeffentlich"], dritter["oeffentlich"]) != code_hin,
       "ein Dritter bekommt einen anderen Code")

print()
print("— Magnolienbaum: einmalige Paarungsdatei —")

paar_a = m.baum_schluessel_erzeugen("Datei-Küche")
paar_b = m.baum_schluessel_erzeugen("Datei-Werkstatt")
paar_a["an"] = paar_b["an"] = True
paar_jetzt = int(time.time())
paar_datei, _paar_einladung = m.baum_paarungsdatei_erzeugen(
    paar_a, "127.0.0.1", 8737, paar_jetzt, b"P" * 32)
pruefe(len(m._baum_b64url_lesen(paar_datei["geheimnis"], 32)) == 32 and
       paar_datei["gueltigBis"] == paar_jetzt + 15 * 60,
       "Paarungsdatei trägt einen 256-Bit-Einmalschlüssel und läuft zeitnah ab")
paar_link = m.baum_paarungslink(paar_datei)
paar_link_text = base64.urlsafe_b64decode(
    paar_link.removeprefix("magnolie-pair:") + "==").decode("utf-8")
pruefe(paar_link.startswith("magnolie-pair:") and
       json.loads(paar_link_text) == paar_datei and
       m.baum_paarungsqr(paar_datei).startswith("data:image/svg+xml;base64,"),
       "QR transportiert unverändert die bestehende Paarungsdatei")
paar_ipv6_zustand = m.baum_schluessel_erzeugen("IPv6-Einladung")
paar_ipv6, _ = m.baum_paarungsdatei_erzeugen(
    paar_ipv6_zustand, "2001:0db8:0:0::9", 8737, paar_jetzt, b"6" * 32)
pruefe(paar_ipv6["ziel"]["adresse"] == "2001:db8::9" and
       m.baum_paarungsdatei_pruefen(paar_ipv6, paar_jetzt) is paar_ipv6,
       "Paarungsdatei 2 akzeptiert kanonische IPv6-Zieladressen")
try:
    m.baum_paarungsdatei_erzeugen(
        m.baum_schluessel_erzeugen("Link-lokal"), "fe80::1", 8737, paar_jetzt)
    pruefe(False, "eine link-lokale IPv6-Adresse ohne Zone dürfte nicht genügen")
except RuntimeError:
    pruefe(True, "link-lokale IPv6-Paarungsziele verlangen eine Schnittstellenzone")
paar_anfrage_probe = m.baum_paarungsanfrage_bauen(
    paar_b, paar_datei, nonce=b"N" * 32)
pruefe(paar_datei["geheimnis"] not in json.dumps(paar_anfrage_probe),
       "das Einmalgeheimnis wird nicht über das Netz übertragen")

def _paarungsdatei_server(_adresse, anfrage):
    return m.baum_paarungsanfrage_annehmen(
        paar_a, anfrage, "127.0.0.1", paar_jetzt)

datei_partner = m.baum_paarungsdatei_importieren(
    paar_datei, paar_b, _paarungsdatei_server)
pruefe(datei_partner["bestaetigt"] and
       datei_partner["vertraut"] is True and
       datei_partner["protokoll"] == "baum-fs1" and
       m.baum_partner(paar_a, paar_b["kennung"])["bestaetigt"] and
       m.baum_partner(paar_a, paar_b["kennung"])["vertraut"] is True and
       m.baum_partner(paar_a, paar_b["kennung"])["protokoll"] == "baum-fs1",
       "Paarungsdatei bestätigt und vertraut beiden Zweigen und pinnt Forward Secrecy")
try:
    m.baum_paarungsdatei_importieren(
        paar_datei, m.baum_schluessel_erzeugen("Kopierter Zweig"),
        _paarungsdatei_server)
    pruefe(False, "eine verbrauchte Paarungsdatei dürfte kein zweites Mal gelten")
except RuntimeError:
    pruefe(True, "die Paarungsdatei ist nach der ersten Verwendung verbraucht")
paar_verbogen = json.loads(json.dumps(paar_datei))
paar_verbogen["ziel"]["adresse"] = "127.0.0.2"
try:
    m.baum_paarungsdatei_pruefen(paar_verbogen, paar_jetzt)
    pruefe(False, "eine veränderte Paarungsdatei müsste auffallen")
except RuntimeError:
    pruefe(True, "Adresse und Identität der Paarungsdatei sind HMAC-gebunden")
paar_dateipfad = os.path.join(tempfile.mkdtemp(prefix="magnolie-paarungsdatei-"),
                              "probe.magnolie-paarung")
m.atomar_text_schreiben(paar_dateipfad, json.dumps(paar_datei))
pruefe(m.baum_paarungsdatei_laden(paar_dateipfad, paar_jetzt)["paarung"] ==
       paar_datei["paarung"] and (os.stat(paar_dateipfad).st_mode & 0o777) == 0o600,
       "Paarungsdatei wird streng begrenzt und nur für den Eigentümer lesbar geladen")

print()
print("— Magnolienbaum: verschlüsselte Umschläge —")

partner_b = {"kennung": zweig_b["kennung"], "oeffentlich": zweig_b["oeffentlich"]}
partner_a = {"kennung": zweig_a["kennung"], "oeffentlich": zweig_a["oeffentlich"]}

umschlag = m.umschlag_bauen(zweig_a["geheim"], partner_b, zweig_a["kennung"],
                            {"art": "aufgabe", "titel": "Mülltonne"}, 1)
pruefe(umschlag["magnolie"] == "baum-1" and umschlag["zaehler"] == 1,
       "der Umschlag ist gekennzeichnet")
pruefe("Mülltonne" not in _json.dumps(umschlag),
       "der Inhalt ist nicht mehr lesbar")

inhalt, zaehler = m.umschlag_oeffnen(zweig_b["geheim"], partner_a,
                                     zweig_b["kennung"], umschlag, 0)
pruefe(inhalt["titel"] == "Mülltonne" and zaehler == 1,
       "die Gegenstelle kann ihn öffnen")

try:
    m.umschlag_oeffnen(zweig_b["geheim"], partner_a, zweig_b["kennung"],
                       umschlag, 1)
    pruefe(False, "eine wiederholte Nachricht müsste auffallen")
except RuntimeError as f:
    pruefe("bereits empfangen" in str(f) or "already been received" in str(f),
           "eine aufgezeichnete Nachricht lässt sich nicht erneut einspielen")

try:
    m.umschlag_oeffnen(dritter["geheim"], partner_a, dritter["kennung"],
                       umschlag, 0)
    pruefe(False, "ein Dritter dürfte den Umschlag nicht öffnen können")
except RuntimeError:
    pruefe(True, "ein Dritter kann den Umschlag nicht öffnen")

verbogen = dict(umschlag)
verbogen["daten"] = ("B" if umschlag["daten"].startswith("A") else "A") + \
    umschlag["daten"][1:]
try:
    m.umschlag_oeffnen(zweig_b["geheim"], partner_a, zweig_b["kennung"],
                       verbogen, 0)
    pruefe(False, "eine Veränderung müsste auffallen")
except RuntimeError:
    pruefe(True, "jede Veränderung unterwegs fällt auf")

print()
print("— Magnolienbaum: Forward Secrecy —")

fs_partner_b = m.baum_partner(paar_a, paar_b["kennung"])
fs_partner_a = m.baum_partner(paar_b, paar_a["kennung"])
fs_start, fs_privat_a = m.fs_start_bauen(paar_a, fs_partner_b, sid=b"S" * 16)
fs_antwort, fs_sitzung_b = m.fs_antwort_bauen(paar_b, fs_partner_a, fs_start)
fs_sitzung_a = m.fs_antwort_oeffnen(
    paar_a, fs_partner_b, fs_start, fs_antwort, fs_privat_a)
pruefe(bytes(fs_sitzung_a["kenc"]) == bytes(fs_sitzung_b["kenc"]) and
       bytes(fs_sitzung_a["kack"]) == bytes(fs_sitzung_b["kack"]),
       "beide Seiten leiten dieselben ephemeren Nachrichten- und Quittungsschlüssel ab")
fs_umschlag = m.umschlag_bauen_fs(
    fs_sitzung_a, paar_a["kennung"], paar_b["kennung"],
    {"art": "aufgabe", "titel": "Nur ephemer"}, m._fs_b64(b"M" * 16),
    nonce=b"Q" * 12)
fs_inhalt, fs_mid = m.umschlag_oeffnen_fs(
    fs_sitzung_b, paar_b["kennung"], paar_a["kennung"], fs_umschlag)
fs_quittung = m.fs_ack_bauen(fs_sitzung_b, fs_umschlag)
pruefe(fs_inhalt["titel"] == "Nur ephemer" and fs_mid == m._fs_b64(b"M" * 16) and
       m.fs_ack_pruefen(fs_sitzung_a, fs_umschlag, fs_quittung),
       "ephemere Nachricht und authentisierte Empfangsbestätigung funktionieren")
max_data_url = "data:application/pdf;base64," + "A" * (
    12000000 - len("data:application/pdf;base64,"))
max_notiz_umschlag = m.umschlag_bauen_fs(
    fs_sitzung_a, paar_a["kennung"], paar_b["kennung"],
    {"art": "notiz_sync", "freigabeId": "a:max", "titel": "Grenze",
     "text": "", "html": "", "anhaenge": [
         {"id": "max-1", "name": "grenze-1.pdf", "art": "pdf",
          "daten": max_data_url},
         {"id": "max-2", "name": "grenze-2.pdf", "art": "pdf",
          "daten": max_data_url}]}, m._fs_b64(b"L" * 16), nonce=b"R" * 12)
max_notiz_draht = len(json.dumps(max_notiz_umschlag).encode("utf-8"))
pruefe(8 * 1024 * 1024 < max_notiz_draht <= m.BAUM_NACHRICHT_MAX and
       m.BAUM_NACHRICHT_MAX == 40 * 1024 * 1024 and
       m.BAUM_HTTP_NACHRICHT_MAX == m.BAUM_NACHRICHT_MAX and
       m.BAUM_BLUETOOTH_RAHMEN_MAX == m.BAUM_NACHRICHT_MAX,
       "24 Millionen Data-URL-Zeichen passen verschlüsselt in die gemeinsame 40-MiB-Grenze")
del max_notiz_umschlag, max_data_url
statischer_schluessel = m._sitzungsschluessel(
    paar_a["geheim"], fs_partner_b["oeffentlich"],
    paar_a["kennung"], paar_b["kennung"])
pruefe(statischer_schluessel != bytes(fs_sitzung_a["kenc"]),
       "der Nachrichtenschlüssel ist nicht aus dem später kompromittierbaren statischen DH ableitbar")
try:
    m.umschlag_oeffnen_fs(
        fs_sitzung_b, paar_b["kennung"], paar_a["kennung"], fs_umschlag)
    pruefe(False, "eine ephemere Sitzung dürfte nicht zweimal öffnen")
except RuntimeError:
    pruefe(True, "jede ephemere Sitzung ist auf genau eine Nachricht begrenzt")
m.fs_sitzung_loeschen(fs_sitzung_a)
m.fs_sitzung_loeschen(fs_sitzung_b)
pruefe(not any(fs_sitzung_a["kenc"]) and not any(fs_sitzung_b["kack"]),
       "abgeleitete Sitzungsschlüssel werden nach Gebrauch überschrieben")

print()
print("— Magnolienbaum: Warteschlange —")

post = []
m.baum_einreihen(post, "abc", "aufgabe", {"titel": "Mülltonne"},
                 _dt(2026, 7, 28, 10, 0))
pruefe(len(post) == 1 and post[0]["versuche"] == 0, "die Sendung liegt bereit")
pruefe(m.baum_faellig(post[0], _dt(2026, 7, 28, 10, 0)),
       "der erste Versuch geschieht sofort")
m.baum_fehlversuch(post[0], _dt(2026, 7, 28, 10, 0))
pruefe(not m.baum_faellig(post[0], _dt(2026, 7, 28, 10, 0, 30)),
       "nach einem Fehlversuch wird kurz gewartet")
pruefe(m.baum_faellig(post[0], _dt(2026, 7, 28, 10, 2)),
       "nach einer Minute geht es weiter")
for _ in range(5):
    m.baum_fehlversuch(post[0], _dt(2026, 7, 28, 11, 0))
pruefe(not m.baum_faellig(post[0], _dt(2026, 7, 28, 11, 30)),
       "die Abstände werden größer")
pruefe(m.baum_zu_alt(post[0], _dt(2026, 8, 5, 10, 0)),
       "nach sieben Tagen gilt sie als unzustellbar")
pruefe(not m.baum_zu_alt(post[0], _dt(2026, 7, 30, 10, 0)),
       "vorher nicht")
for versuche, minuten in ((1, 1), (2, 2), (3, 5), (4, 10),
                           (5, 30), (6, 60), (20, 60)):
    grenz_sendung = {"versuche": versuche, "zuletzt": "2026-07-28 10:00:00"}
    grenze = _dt(2026, 7, 28, 10, 0) + m.timedelta(minutes=minuten)
    pruefe(not m.baum_faellig(
        grenz_sendung, grenze - m.timedelta(seconds=1)) and
        m.baum_faellig(grenz_sendung, grenze),
        "Wiederholungsabstand %d liegt exakt bei %d Minuten" %
        (versuche, minuten))
baum_speicher_ordner = tempfile.mkdtemp(prefix="magnolie-baum-post-")
warteschlangen_pfad = m.baum_postdatei(baum_speicher_ordner)
m.baum_post_schreiben(post, warteschlangen_pfad, "Blütenblatt 2026")
pruefe((os.stat(warteschlangen_pfad).st_mode & 0o777) == 0o600,
       "auch eine Warteschlange mit Anhängen ist nur für den Eigentümer lesbar")
with open(warteschlangen_pfad, "r", encoding="utf-8") as datei:
    baum_post_roh = datei.read()
pruefe(m.ist_verschluesselt(baum_post_roh) and "Mülltonne" not in baum_post_roh and
       m.baum_post_lesen(warteschlangen_pfad, "Blütenblatt 2026") == post,
       "die Warteschlange ist mit Organizerkennwort authentisiert verschlüsselt")
try:
    m.baum_post_lesen(warteschlangen_pfad, "falsch")
    pruefe(False, "ein falsches Kennwort dürfte die Baum-Post nicht öffnen")
except RuntimeError:
    pruefe(True, "ein falsches Kennwort öffnet die Baum-Post nicht")

eingangs_pfad = m.baum_eingangsdatei(baum_speicher_ordner)
eingang = [{"id": "e1", "art": "kontakt", "inhalt": {"name": "Erika Geheim"}}]
m.baum_eingang_schreiben(eingang, eingangs_pfad, "Blütenblatt 2026")
with open(eingangs_pfad, "r", encoding="utf-8") as datei:
    baum_eingang_roh = datei.read()
pruefe(m.ist_verschluesselt(baum_eingang_roh) and
       "Erika Geheim" not in baum_eingang_roh and
       m.baum_eingang_lesen(eingangs_pfad, "Blütenblatt 2026") == eingang,
       "auch der Magnolienbaum-Eingang liegt nicht im Klartext")
m.baum_ablagen_umschluesseln("Neues Blütenblatt", "Blütenblatt 2026",
                              baum_speicher_ordner)
pruefe(m.baum_post_lesen(warteschlangen_pfad, "Neues Blütenblatt") == post and
       m.baum_eingang_lesen(eingangs_pfad, "Neues Blütenblatt") == eingang,
       "beide Baumablagen überstehen einen Kennwortwechsel")
m.baum_ablagen_umschluesseln("", "Neues Blütenblatt", baum_speicher_ordner)
pruefe(m.baum_post_lesen(warteschlangen_pfad) == post and
       m.baum_eingang_lesen(eingangs_pfad) == eingang,
       "beim Entfernen des Kennworts werden beide Baumablagen wieder freigegeben")

print()
print("— Magnolienbaum: selbstständige Wiederholungszustellung —")

wartung_ordner = tempfile.mkdtemp(prefix="magnolie-baum-wartung-")
wartung_pfad = m.baum_postdatei(wartung_ordner)
wartung_zustand = m.baum_schluessel_erzeugen("Wartung")
wartung_zustand["an"] = True
wartung_partner_zustand = m.baum_schluessel_erzeugen("Gegenstelle")
wartung_partner = m.baum_partner_aufnehmen(
    wartung_zustand, "Gegenstelle", wartung_partner_zustand["kennung"],
    wartung_partner_zustand["oeffentlich"], "127.0.0.1", 19999)
wartung_partner["bestaetigt"] = True
pruefe(wartung_partner["vertraut"] is False,
       "Code- und alte Partner bleiben ohne ausdrückliche Freigabe unvertraut")
m.baum_partner_einstellungen(
    wartung_partner, True, "VPN.Example", "9443")
pruefe(wartung_partner["vertraut"] is True and
       wartung_partner["fernAdresse"] == "vpn.example" and
       wartung_partner["fernPort"] == 9443,
       "Vertrauen und fernes Direktziel werden streng normalisiert")
for host, port in (("https://proxy.invalid", "9443"), ("vpn.example", "0"),
                   ("vpn.example", "65536"), ("vpn.example", "9.5")):
    try:
        m.baum_partner_einstellungen(wartung_partner, True, host, port)
        pruefe(False, "ungültiges fernes Direktziel dürfte nicht gespeichert werden")
    except RuntimeError:
        pruefe(True, "ungültiges fernes Direktziel wird abgewiesen")
try:
    m.baum_partner_einstellungen(wartung_partner, "ja", "vpn.example", 9443)
    pruefe(False, "ein nicht-boolescher Vertrauenswert dürfte nicht gelten")
except RuntimeError:
    pruefe(True, "der Vertrauenswert wird typstreng geprüft")

def baum_test_senden(zustand, partner, art, inhalt, sender=None):
    post = []
    m.baum_einreihen(post, partner["kennung"], art, inhalt)
    return m.baum_post_zustellen(zustand, post, sender=sender,
                                sichern=lambda: True)["zugestellt"] == 1


def wartung_quittung(adresse, envelope):
    key = m._sitzungsschluessel(wartung_zustand["geheim"], wartung_partner["oeffentlich"],
                               wartung_zustand["kennung"], wartung_partner["kennung"])
    return m.baum_receipt(key, wartung_zustand["kennung"], wartung_partner["kennung"], envelope)


fallback_aufrufe = []
wartung_partner.update({"protokoll": "baum-1", "adresse": "192.0.2.10", "port": 8737,
                         "fernAdresse": "vpn.example", "fernPort": 9443})
def fallback_sender(adresse, envelope):
    fallback_aufrufe.append(adresse)
    if not adresse.startswith("http://vpn.example:9443/"):
        raise ConnectionRefusedError()
    return wartung_quittung(adresse, envelope)

fallback_ok = baum_test_senden(
    wartung_zustand, wartung_partner, "aufgabe", {"titel": "Direkt"},
    sender=fallback_sender)
pruefe(fallback_ok and fallback_aufrufe == [
    "http://192.0.2.10:8737/magnolie/v1/nachricht",
    "http://vpn.example:9443/magnolie/v1/nachricht"],
       "Zustellung versucht beobachtetes und danach fernes Direktziel ohne Proxy")
wartung_partner.update({"adresse": "vpn.example", "port": 9443})
pruefe(m.baum_partner_endpunkte(wartung_partner) == [("vpn.example", 9443)],
       "identische Direktziele werden nur einmal versucht")

bericht_alt = (m.baum_post_lesen, m.baum_eingang_lesen)
try:
    m.baum_post_lesen = lambda **_werte: []
    m.baum_eingang_lesen = lambda **_werte: []
    class _PartnerBericht:
        _baum_sperre = m.threading.RLock()
        _kennwort = ""
        _baum_fehler = ""
        _baumdienst = None
        def _baum_zustand(self): return wartung_zustand
    partner_bericht = m.Fenster._baum_bericht(_PartnerBericht())["partner"][0]
    pruefe(partner_bericht["vertraut"] is True and
           partner_bericht["fernAdresse"] == "vpn.example" and
           partner_bericht["fernPort"] == 9443,
           "App.baumStand berichtet Vertrauen und fernes Direktziel")
finally:
    m.baum_post_lesen, m.baum_eingang_lesen = bericht_alt

class _PartnerBruecke:
    _baum_sperre = m.threading.RLock()
    antworten = []
    gesichert = 0
    gemeldet = 0
    def _baum_zustand(self): return wartung_zustand
    def _baum_sichern(self, _zustand): self.gesichert += 1
    def antwort(self, name, wert): self.antworten.append((name, wert))
    def _baum_stand_melden(self): self.gemeldet += 1

partner_bruecke = _PartnerBruecke()
m.Fenster._baum_partner_einstellungen(
    partner_bruecke, wartung_partner["kennung"], False, "relay.example", "10443")
pruefe(partner_bruecke.antworten[-1][0] == "App.baumPartnerEinstellungen" and
       partner_bruecke.antworten[-1][1]["ok"] and partner_bruecke.gesichert == 1 and
       wartung_partner["vertraut"] is False and
       wartung_partner["fernAdresse"] == "relay.example" and
       wartung_partner["fernPort"] == 10443,
       "der native Bridge-Befehl validiert und persistiert Partnereinstellungen")
m.Fenster._baum_partner_einstellungen(
    partner_bruecke, wartung_partner["kennung"], True, "https://falsch", "10443")
pruefe(not partner_bruecke.antworten[-1][1]["ok"] and
       partner_bruecke.gesichert == 1 and wartung_partner["vertraut"] is False,
       "ungültige Bridge-Werte verändern den gespeicherten Partner nicht")
wartung_post = []
m.baum_einreihen(wartung_post, wartung_partner["kennung"], "aufgabe",
                  {"titel": "Ohne neue Sendung"}, _dt(2026, 7, 28, 10, 0))
m.baum_post_schreiben(wartung_post, wartung_pfad)
wartung_aufrufe = []
def wartung_refused(adresse, inhalt):
    wartung_aufrufe.append((adresse, inhalt))
    raise ConnectionRefusedError()

bericht = m.baum_post_wartung(
    wartung_zustand, wartung_pfad, jetzt=_dt(2026, 7, 28, 10, 0),
    sender=wartung_refused)
neu_gelesen = m.baum_post_lesen(wartung_pfad)
pruefe(bericht["versucht"] == 1 and len(wartung_aufrufe) == 2 and
       [aufruf[0] for aufruf in wartung_aufrufe] == [
           "http://vpn.example:9443/magnolie/v1/nachricht",
           "http://relay.example:10443/magnolie/v1/nachricht"] and
       neu_gelesen[0]["versuche"] == 1 and
       neu_gelesen[0]["zuletzt"] == "2026-07-28 10:00:00",
       "ein vorhandener Queue-Eintrag wird ohne neue Sendung versucht und persistiert")
with open(wartung_pfad, "rb") as datei:
    wartung_vorher = datei.read()
wartung_aufrufe.clear()
m.baum_post_wartung(
    wartung_zustand, wartung_pfad, jetzt=_dt(2026, 7, 28, 10, 0, 59),
    sender=lambda *_args: wartung_aufrufe.append(True) or True)
with open(wartung_pfad, "rb") as datei:
    wartung_nachher = datei.read()
pruefe(not wartung_aufrufe and wartung_vorher == wartung_nachher,
       "vor Ablauf des Backoffs wird weder gesendet noch die Queue neu geschrieben")
m.baum_post_wartung(
    wartung_zustand, wartung_pfad, jetzt=_dt(2026, 7, 28, 10, 1),
    sender=lambda adresse, envelope: wartung_aufrufe.append(True) or wartung_quittung(adresse, envelope))
pruefe(len(wartung_aufrufe) == 1 and not m.baum_post_lesen(wartung_pfad),
       "genau an der Backoff-Grenze wird die alte Sendung zugestellt und entfernt")
wartung_zustand["an"] = False
pruefe(m.baum_post_wartung(wartung_zustand, wartung_pfad)["grund"] == "aus",
       "ein abgeschalteter Baum öffnet oder verändert seine Warteschlange nicht")

class _GesperrteWartung:
    _gesperrt = True

pruefe(m.Fenster._baum_post_lauf(_GesperrteWartung())["grund"] == "gesperrt",
       "ein gesperrter Organizer öffnet keine verschlüsselte Baum-Warteschlange")

class _SofortThread:
    ziele = []

    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon
        self.__class__.ziele.append(target)

    def start(self):
        pass

class _SofortGLib:
    @staticmethod
    def idle_add(rueckruf):
        return rueckruf()

class _TickProbe:
    _baum_post_stop = False
    _baum_post_timer = 1
    _baum_post_laeuft = False
    _gesperrt = False
    meldungen = 0

    def _baum_post_lauf(self):
        return {"geaendert": True}

    def _baum_stand_melden(self):
        self.meldungen += 1

thread_alt, glib_alt = m.threading.Thread, m.GLib
try:
    m.threading.Thread, m.GLib = _SofortThread, _SofortGLib
    tick_probe = _TickProbe()
    m.Fenster._baum_post_tick(tick_probe)
    m.Fenster._baum_post_tick(tick_probe)
    pruefe(len(_SofortThread.ziele) == 1 and tick_probe._baum_post_laeuft,
           "während eines Wartungslaufs startet kein überlappender zweiter Arbeiter")
    _SofortThread.ziele.pop()()
    pruefe(not tick_probe._baum_post_laeuft and tick_probe.meldungen == 1,
           "nach Abschluss darf der nächste Wartungstakt wieder laufen")
finally:
    m.threading.Thread, m.GLib = thread_alt, glib_alt

send_reihenfolge = []
send_funktionen = (m.baum_post_lesen, m.baum_post_schreiben,
                   m.baum_post_zustellen)
try:
    m.baum_post_lesen = lambda **_werte: []
    m.baum_post_schreiben = lambda *_args, **_werte: send_reihenfolge.append(
        "persistiert") or True
    m.baum_post_zustellen = lambda *_args, **_werte: send_reihenfolge.append(
        "netz") or {"zugestellt": 1, "offen": 0, "aufgegeben": 0, "versucht": 1}
    class _SendFenster:
        _baum_sperre = m.threading.RLock()
        _kennwort = ""
        def _baum_zustand(self): return wartung_zustand
        def _baum_sichern(self, _zustand): pass
        def _baum_stand_melden(self): pass
        def antwort(self, *_args): pass
    wartung_zustand["an"] = True
    m.Fenster._baum_sendung(
        _SendFenster(), wartung_partner["kennung"], "aufgabe", {"titel": "Durabel"})
    pruefe(send_reihenfolge[:2] == ["persistiert", "netz"],
           "jede neue Sendung liegt vor ihrem ersten Netzversuch dauerhaft in der Queue")
finally:
    (m.baum_post_lesen, m.baum_post_schreiben,
     m.baum_post_zustellen) = send_funktionen

print()
print("— Kennworttransaktion nach Prozessabbruch —")

transaktions_dateien = list(m.KENNWORT_TRANSAKTION_DATEIEN)
transaktions_alt = {name: "ALT:" + name for name in transaktions_dateien}
transaktions_neu = {name: "NEU:" + name for name in transaktions_dateien}
abbruchstellen = ["vor-journal", "nach-journal"] + [
    "nach-" + name for name in transaktions_dateien] + ["vor-bereinigung"]

for abbruchstelle in abbruchstellen:
    transaktions_ordner = tempfile.mkdtemp(prefix="magnolie-transaktion-")
    for name, text in transaktions_alt.items():
        m.atomar_text_schreiben(os.path.join(transaktions_ordner, name), text)

    def _transaktions_abbruch(stelle, ziel=abbruchstelle):
        if stelle == ziel:
            raise RuntimeError("simulierter Prozessabbruch")

    m._KENNWORT_TRANSAKTION_HAKEN["funktion"] = _transaktions_abbruch
    try:
        m.kennwort_transaktion_ausfuehren(
            transaktions_neu, "aendern", transaktions_ordner)
    except RuntimeError:
        pass
    finally:
        m._KENNWORT_TRANSAKTION_HAKEN["funktion"] = None
    m.kennwort_transaktion_reparieren(transaktions_ordner)
    erwartet = transaktions_alt if abbruchstelle == "vor-journal" else transaktions_neu
    ist = {}
    for name in transaktions_dateien:
        with open(os.path.join(transaktions_ordner, name), encoding="utf-8") as datei:
            ist[name] = datei.read()
    pruefe(ist == erwartet and not os.path.exists(
        m.kennwort_transaktion_ordner(transaktions_ordner)),
        "Recovery liefert nach %s einen einheitlichen Bestand" % abbruchstelle)

# Auch ein zweiter Abbruch mitten in der Recovery bleibt idempotent.
doppel_ordner = tempfile.mkdtemp(prefix="magnolie-transaktion-doppelt-")
for name, text in transaktions_alt.items():
    m.atomar_text_schreiben(os.path.join(doppel_ordner, name), text)
m._KENNWORT_TRANSAKTION_HAKEN["funktion"] = lambda stelle: (
    (_ for _ in ()).throw(RuntimeError("erster Abbruch"))
    if stelle == "nach-journal" else None)
try:
    m.kennwort_transaktion_ausfuehren(transaktions_neu, "aendern", doppel_ordner)
except RuntimeError:
    pass
m._KENNWORT_TRANSAKTION_HAKEN["funktion"] = lambda stelle: (
    (_ for _ in ()).throw(RuntimeError("zweiter Abbruch"))
    if stelle == "nach-baum-post.json" else None)
try:
    m.kennwort_transaktion_reparieren(doppel_ordner)
except RuntimeError:
    pass
m._KENNWORT_TRANSAKTION_HAKEN["funktion"] = None
m.kennwort_transaktion_reparieren(doppel_ordner)
def _transaktions_text(ordner, name):
    with open(os.path.join(ordner, name), encoding="utf-8") as datei:
        return datei.read()

pruefe(all(_transaktions_text(doppel_ordner, name) == text
           for name, text in transaktions_neu.items()),
       "Recovery bleibt auch nach einem zweiten Prozessabbruch idempotent")

# Der echte Kryptopfad stellt Hauptdaten und alle Baumdateien gemeinsam um.
krypto_tx_ordner = tempfile.mkdtemp(prefix="magnolie-transaktion-krypto-")
m.atomar_text_schreiben(os.path.join(krypto_tx_ordner, "daten.json"),
                        '{"notizen":[{"titel":"Gemeinsam"}]}')
m.baum_schreiben(m.baum_schluessel_erzeugen("Transaktionsbaum"),
                  m.baum_datei(krypto_tx_ordner))
m.baum_post_schreiben(post, m.baum_postdatei(krypto_tx_ordner))
m.baum_eingang_schreiben(eingang, m.baum_eingangsdatei(krypto_tx_ordner))
krypto_vorbereitet = m.baum_ablagen_vorbereiten(
    "Gemeinsam 2026", "", krypto_tx_ordner)
krypto_dateien = dict(krypto_vorbereitet["dateien"])
krypto_dateien["daten.json"] = m.verschluesseln(
    '{"notizen":[{"titel":"Gemeinsam"}]}', "Gemeinsam 2026")
m.kennwort_transaktion_ausfuehren(krypto_dateien, "setzen", krypto_tx_ordner)
with open(os.path.join(krypto_tx_ordner, "daten.json"), encoding="utf-8") as datei:
    krypto_daten_roh = datei.read()
pruefe(json.loads(m.entschluesseln(krypto_daten_roh, "Gemeinsam 2026"))
       ["notizen"][0]["titel"] == "Gemeinsam" and
       m.baum_lesen(m.baum_datei(krypto_tx_ordner), "Gemeinsam 2026")["name"] ==
       "Transaktionsbaum" and
       m.baum_post_lesen(m.baum_postdatei(krypto_tx_ordner), "Gemeinsam 2026") == post and
       m.baum_eingang_lesen(m.baum_eingangsdatei(krypto_tx_ordner),
                            "Gemeinsam 2026") == eingang,
       "Hauptdaten und drei Baumdateien wechseln gemeinsam in den Kennwortschutz")

print()
print("— Magnolienbaum: wem gehört eine Aufgabe —")

hier = {"geaendert": 100, "herkunft": "A", "quelle": "A", "titel": "hier"}
dort = {"geaendert": 200, "herkunft": "A", "quelle": "B", "titel": "dort"}
pruefe(m.aufgabe_zusammenfuehren(hier, dort)["titel"] == "dort",
       "die neuere Änderung gewinnt")
pruefe(m.aufgabe_zusammenfuehren(dort, hier)["titel"] == "dort",
       "auch andersherum")
gleich = dict(dort, geaendert=100)
pruefe(m.aufgabe_zusammenfuehren(hier, gleich)["titel"] == "hier",
       "bei Gleichstand entscheidet die Herkunft")
pruefe(m.darf_loeschen(hier, "A") is True, "die Herkunft darf löschen")
pruefe(m.darf_loeschen(hier, "B") is False, "die Gegenstelle nicht")
pruefe(m.darf_loeschen({}, "B") is True,
       "eine Aufgabe ohne Herkunft gehört dem, der sie hat")

import time as _t
import http.client as _http
import socket as _socket

print()
print("— Magnolienbaum: HTTP-Härtung —")

def _warte_baum(bedingung, zeit=3.0):
    ende = _t.monotonic() + zeit
    while _t.monotonic() < ende:
        if bedingung():
            return True
        _t.sleep(0.01)
    return bool(bedingung())

def _baum_aktive(dienst):
    server = dienst._server
    if not server:
        return 0
    with server._aktive_sperre:
        return len(server._aktive)

def _baum_roh(port, quelle="127.0.0.1"):
    buechse = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    buechse.settimeout(2)
    buechse.bind((quelle, 0))
    buechse.connect(("127.0.0.1", port))
    return buechse

def _baum_antwort(buechse):
    teile = []
    try:
        while True:
            teil = buechse.recv(65536)
            if not teil:
                break
            teile.append(teil)
    except (ConnectionResetError, _socket.timeout):
        pass
    return b"".join(teile)

http_zustand = m.baum_schluessel_erzeugen("HTTP-Härtung")
http_zustand["an"] = True
http_dienst = m.BaumDienst(
    lambda: http_zustand, lambda _zustand: None, port=0,
    http_zeitgrenze=1.5, http_pro_adresse=4)
http_dienst._rufdienst_starten = lambda: None
nummer, transport_antwort = http_dienst.behandeln(
    "/unbekannt", {}, "aa:bb:cc:dd:ee:ff")
pruefe(nummer == 404 and "fehler" in transport_antwort,
       "Baumpfade werden unabhängig vom HTTP-Transport behandelt")

import struct as _struct
bluetooth_aufrufe = []
class _BluetoothBaumdienst:
    def behandeln(self, pfad, nutzlast, quelle):
        bluetooth_aufrufe.append((pfad, nutzlast, quelle))
        return 200, {"ok": True}

bluetooth_probe = m.BaumBluetoothDienst(_BluetoothBaumdienst())
bluetooth_server, bluetooth_client = _socket.socketpair()
bluetooth_probe._plaetze.acquire()
bluetooth_faden = threading.Thread(
    target=bluetooth_probe._bedienen,
    args=("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF", bluetooth_server))
bluetooth_faden.start()
bluetooth_nutzlast = json.dumps({
    "pfad": "/magnolie/v2/sitzung", "nutzlast": {"von": "zweig"}
}).encode("utf-8")
bluetooth_client.sendall(
    _struct.pack(">I", len(bluetooth_nutzlast)) + bluetooth_nutzlast)
bluetooth_laenge = _struct.unpack(
    ">I", m.BaumBluetoothDienst._vollstaendig_lesen(bluetooth_client, 4))[0]
bluetooth_antwort = json.loads(
    m.BaumBluetoothDienst._vollstaendig_lesen(
        bluetooth_client, bluetooth_laenge).decode("utf-8"))
bluetooth_client.close()
bluetooth_faden.join(timeout=2)
pruefe(bluetooth_antwort == {"ok": True} and bluetooth_aufrufe == [(
    "/magnolie/v2/sitzung", {"von": "zweig"}, "aa:bb:cc:dd:ee:ff")],
       "RFCOMM nutzt Android-Rahmung, feste UUID und die Geräteadresse")
pruefe(m.BAUM_BLUETOOTH_UUID ==
       "6d61676e-6f6c-6965-6e62-61756d383733" and
       m.BAUM_BLUETOOTH_RAHMEN_MAX == m.BAUM_NACHRICHT_MAX == 40 * 1024 * 1024,
       "Organizer und Android verwenden dieselben Bluetooth-Drahtwerte")

pruefe(http_dienst.starten() and http_dienst.port > 0,
       "der gehärtete HTTP-Dienst lauscht auf einem freien Prüfport")
blockierer = []
try:
    for nummer in range(16):
        buechse = _baum_roh(http_dienst.port, "127.0.0.%d" % (nummer // 4 + 1))
        buechse.sendall(
            b"POST /magnolie/v1/nachricht HTTP/1.1\r\nHost: localhost\r\nX-Slow: ")
        blockierer.append(buechse)
    pruefe(_warte_baum(lambda: _baum_aktive(http_dienst) == 16),
           "höchstens 16 unvollständige HTTP-Anfragen belegen feste Plätze")
    ueberlast = _baum_roh(http_dienst.port, "127.0.0.5")
    ueberlast.sendall(b"POST /unbekannt HTTP/1.1\r\nHost: localhost\r\n"
                      b"Content-Length: 2\r\nConnection: close\r\n\r\n{}")
    pruefe(_baum_antwort(ueberlast) == b"",
           "eine siebzehnte Verbindung wird ohne weiteren Arbeitsfaden abgewiesen")
    ueberlast.close()
    pruefe(_warte_baum(lambda: _baum_aktive(http_dienst) == 0),
           "absolute Fristen lösen alle langsam tröpfelnden Verbindungsplätze")
finally:
    for buechse in blockierer:
        buechse.close()

voll = _http.HTTPConnection("127.0.0.1", http_dienst.port, timeout=2)
voll.request("POST", "/unbekannt", body=b"{}",
             headers={"Content-Type": "application/json"})
voll_antwort = voll.getresponse()
voll_antwort.read()
pruefe(voll_antwort.status == 404 and
       voll_antwort.getheader("Connection") == "close" and
       _warte_baum(lambda: _baum_aktive(http_dienst) == 0),
       "nach Platzerschöpfung funktioniert genau eine sauber geschlossene Anfrage")
voll.close()

kurz = _baum_roh(http_dienst.port)
kurz.sendall(b"POST /unbekannt HTTP/1.1\r\nHost: localhost\r\n"
             b"Content-Length: 10\r\n\r\n{}")
kurz.shutdown(_socket.SHUT_WR)
pruefe(b" 400 " in _baum_antwort(kurz) and
       _warte_baum(lambda: _baum_aktive(http_dienst) == 0),
       "ein vorzeitig beendeter Nachrichtenkörper gibt seinen Platz sofort frei")
kurz.close()

for rahmung, status in ((
        b"Content-Length: 2\r\nContent-Length: 2\r\n", b" 400 "), (
        b"Transfer-Encoding: chunked\r\n", b" 400 "), (
        b"Content-Length: 2\r\nExpect: 100-continue\r\n", b" 417 ")):
    probe = _baum_roh(http_dienst.port)
    probe.sendall(b"POST /unbekannt HTTP/1.1\r\nHost: localhost\r\n" +
                  rahmung + b"Connection: close\r\n\r\n{}")
    pruefe(status in _baum_antwort(probe),
           "mehrdeutige oder vorauseilende HTTP-Rahmung wird abgewiesen")
    probe.close()

stopp_probe = _baum_roh(http_dienst.port)
stopp_probe.sendall(b"POST /unbekannt HTTP/1.1\r\nHost: localhost\r\nX-Slow: ")
pruefe(_warte_baum(lambda: _baum_aktive(http_dienst) == 1),
       "eine unvollständige Verbindung ist vor dem Abschalten aktiv")
http_dienst.anhalten()
pruefe(_baum_antwort(stopp_probe) == b"" and http_dienst._faden is None,
       "Abschalten beendet aktive Clients und den Serverfaden deterministisch")
stopp_probe.close()

print()
print("— Magnolienbaum: zwei Instanzen im Gespräch —")

ufw_probe = os.path.join(tempfile.mkdtemp(prefix="magnolie-ufw-"), "ufw.conf")
with open(ufw_probe, "w", encoding="utf-8") as datei:
    datei.write("ENABLED=yes\n")
ufw_aufrufe = []
class _UfwErgebnis:
    returncode = 0

ufw_ok, ufw_fehler = m.baum_firewall_einrichten(
    ufw_probe,
    lambda befehl, **_werte: ufw_aufrufe.append(befehl) or _UfwErgebnis(),
    ufw_befehl="/usr/sbin/ufw", pkexec_befehl="/usr/bin/pkexec")
pruefe(ufw_ok and not ufw_fehler and len(ufw_aufrufe) == 1 and
       ufw_aufrufe[0][-3:] == ["/usr/sbin/ufw", "allow", "Magnolie Organizer"],
       "aktives UFW wird erst beim Einschalten automatisch eingerichtet")
postinst_pfad = os.path.join(os.path.dirname(PFAD), "..", "debian", "postinst")
with open(postinst_pfad, encoding="utf-8") as datei:
    pruefe("ufw allow" not in datei.read(),
            "die Paketinstallation öffnet nicht vorsorglich den Baum-Port")
with open(os.path.join(os.path.dirname(PFAD), "..", "magnolie-organizer"),
          encoding="utf-8") as datei:
    ufw_profil = datei.read()
pruefe("8737/tcp" in ufw_profil and "8737/udp" in ufw_profil and
       "8741/tcp" in ufw_profil and "1716/udp" in ufw_profil and
       "1716:1764/tcp" in ufw_profil and "5353/udp" in ufw_profil,
       "das UFW-Profil erlaubt Baum, Telefonverbindung, Alt-Rundruf und mDNS")

suchziele = m.baum_suchziele()
pruefe(suchziele == ["127.0.0.1", "255.255.255.255"],
       "der alte IPv4-Fallback bleibt auf Rundruf und Rückschleife begrenzt")

class _MDNSInfo:
    port = 8737
    properties = {b"kennung": b"abcdefgh23456789", b"name": "Büro".encode(),
                  b"fingerabdruck": b"ABCD-1234-EF56-7890"}
    def parsed_scoped_addresses(self):
        return ["192.0.2.7", "2001:db8::7"]

mdns_eintrag = m._baum_mdns_eintrag(_MDNSInfo())
pruefe(mdns_eintrag["adresse"] == "2001:db8::7" and
       mdns_eintrag["adressen"] == ["2001:db8::7", "192.0.2.7"] and
       mdns_eintrag["fundart"] == "mdns",
       "mDNS löst IPv4 und IPv6 auf und bevorzugt eine nicht-lokale IPv6-Adresse")

class _IPVersion:
    All = "all"

class _MDNSZeroconf:
    registriert = []
    geschlossen = 0
    def __init__(self, **werte): self.werte = werte
    def register_service(self, info): self.__class__.registriert.append(info)
    def unregister_service(self, info): self.__class__.registriert.remove(info)
    def get_service_info(self, _art, _name, timeout=0): return _MDNSInfo()
    def close(self): self.__class__.geschlossen += 1

class _MDNSServiceInfo:
    def __init__(self, art, name, **werte):
        self.art, self.name, self.werte = art, name, werte

class _MDNSBrowser:
    def __init__(self, zc, art, lauscher):
        self.abgebrochen = False
        lauscher.add_service(zc, art, "probe." + art)
        lauscher.update_service(zc, art, "probe." + art)
    def cancel(self): self.abgebrochen = True

mdns_handle = m.baum_mdns_veroeffentlichen(
    zweig_a, 8737, (_MDNSZeroconf, _MDNSServiceInfo, _IPVersion))
mdns_funde = m.baum_mdns_suchen(
    0, "andererzweig", (_MDNSZeroconf, _MDNSBrowser, _IPVersion))
pruefe(mdns_handle and len(_MDNSZeroconf.registriert) == 1 and
       len(mdns_funde) == 1 and mdns_funde[0]["kennung"] == "abcdefgh23456789",
       "DNS-SD-Veröffentlichung und Suche nutzen den portablen mDNS-Adapter")
m.baum_mdns_beenden(mdns_handle)
pruefe(not _MDNSZeroconf.registriert and _MDNSZeroconf.geschlossen == 2,
       "mDNS-Suche und -Veröffentlichung werden vollständig geschlossen")

netz_a = m.baum_schluessel_erzeugen("Küche")
netz_a["an"] = True
netz_a["port"] = 18841
netz_b = m.baum_schluessel_erzeugen("Werkstatt")
netz_b["an"] = True
netz_b["port"] = 18842

grenz_zustand = m.baum_schluessel_erzeugen("Grenzprobe")
grenz_zustand["partner"] = [
    {"kennung": "wartet-%d" % i, "bestaetigt": False}
    for i in range(m.BAUM_UNBESTAETIGT_MAX)]
try:
    m.baum_partner_aufnehmen(
        grenz_zustand, "Noch einer", "noch-einer", netz_a["oeffentlich"])
    pruefe(False, "zu viele offene Paarungen müssten abgewiesen werden")
except RuntimeError:
    pruefe(True, "offene Paarungen sind mengenmäßig begrenzt")

empfangen = []
empfangen_a = []
dienst_a = m.BaumDienst(lambda: netz_a, lambda z: None,
                        bei_nachricht=lambda p, i: empfangen_a.append(
                            (p["name"], i)), port=18841)
dienst_b = m.BaumDienst(lambda: netz_b, lambda z: None,
                        bei_nachricht=lambda p, i: empfangen.append((p["name"], i)),
                        port=18842)
pruefe(all(dienst_b._anfrage_erlaubt("203.0.113.9", True) for _ in range(8)) and
       not dienst_b._anfrage_erlaubt("203.0.113.9", True),
       "Paarungsversuche werden pro Absender begrenzt")
lief = dienst_a.starten() and dienst_b.starten()
pruefe(lief, "beide Gegenstellen lauschen")
_t.sleep(0.3)

try:
    try:
        m.baum_anfragen("127.0.0.1", 18842, netz_a,
                        erwarteter_fingerabdruck="0000-0000-0000-0000")
        pruefe(False, "ein falscher erwarteter Fingerabdruck müsste abbrechen")
    except RuntimeError as f:
        pruefe("stimmt nicht" in str(f),
               "ein falscher erwarteter Fingerabdruck bricht die Paarung ab")
    antwort = m.baum_anfragen(
        "127.0.0.1", 18842, netz_a,
        erwarteter_fingerabdruck=m.fingerabdruck(netz_b["oeffentlich"]))
    pruefe(antwort.get("kennung") == netz_b["kennung"],
            "die Gegenstelle stellt sich vor")
    if dienst_b._server6:
        antwort_ipv6 = m.baum_anfragen(
            "::1", 18842, netz_a,
            erwarteter_fingerabdruck=m.fingerabdruck(netz_b["oeffentlich"]))
        pruefe(antwort_ipv6.get("kennung") == netz_b["kennung"] and
               m.baum_partner(netz_b, netz_a["kennung"])["adresse"] == "::1",
               "dieselbe Paarung erreicht den getrennten IPv6-Listener über ::1")
    else:
        pruefe(True, "IPv6-Listener ist auf diesem System nicht verfügbar")
    verbindung = _http.HTTPConnection("127.0.0.1", 18842, timeout=3)
    verbindung.putrequest("POST", "/magnolie/v1/nachricht")
    verbindung.putheader("Content-Length", str(m.BAUM_HTTP_NACHRICHT_MAX + 1))
    verbindung.endheaders()
    zu_gross = verbindung.getresponse()
    pruefe(zu_gross.status == 413,
           "zu große Anhangsnachrichten werden vor dem Einlesen abgewiesen")
    verbindung.close()
    pruefe(antwort.get("code") == m.paarungs_code(netz_a["oeffentlich"],
                                                  antwort["oeffentlich"]),
           "beide Seiten zeigen denselben Code: %s" % antwort.get("code"))

    partner_bei_a = m.baum_partner_aufnehmen(
        netz_a, antwort["name"], antwort["kennung"], antwort["oeffentlich"],
        "127.0.0.1", 18842)
    pruefe(partner_bei_a["bestaetigt"] is False,
           "vor der Bestätigung gilt niemand als vertraut")

    # Ohne Bestätigung wird nichts angenommen
    partner_bei_a["bestaetigt"] = True
    ohne = baum_test_senden(netz_a, partner_bei_a, "aufgabe", {"titel": "Zu früh"})
    _t.sleep(0.3)
    pruefe(not empfangen,
           "solange die Gegenstelle nicht bestätigt hat, nimmt sie nichts an")

    # Beide bestätigen
    partner_bei_b = m.baum_partner(netz_b, netz_a["kennung"])
    pruefe(partner_bei_b is not None,
           "die Gegenstelle hat den Anfragenden vermerkt")
    partner_bei_b["bestaetigt"] = True
    try:
        m.baum_partner_aufnehmen(
            netz_b, "Betrüger", netz_a["kennung"], dritter["oeffentlich"],
            "127.0.0.1", 18841)
        pruefe(False, "ein bestätigter Schlüssel dürfte nicht ersetzt werden")
    except RuntimeError as f:
        pruefe("Schlüssel" in str(f),
               "ein bestätigter Schlüssel lässt sich nicht unbemerkt ersetzen")

    ok = baum_test_senden(netz_a, partner_bei_a, "aufgabe",
                       {"titel": "Mülltonne rausstellen",
                        "faellig": "2026-07-29",
                        "herkunft": netz_a["kennung"]})
    _t.sleep(0.4)
    pruefe(ok, "die Aufgabe wird zugestellt")
    pruefe(len(empfangen) == 1 and
           empfangen[0][1]["titel"] == "Mülltonne rausstellen",
           "und kommt vollständig an: %r" % (empfangen[0][1] if empfangen else None))
    pruefe(empfangen[0][0] == "Küche",
           "die Gegenstelle weiß, von wem sie kam")

    # Nach erfolgreicher Dateipaarung werden neue Nachrichten ausschließlich
    # über ephemere Sitzungen mit authentisierter Quittung transportiert.
    partner_bei_a["protokoll"] = "baum-fs1"
    partner_bei_b["protokoll"] = "baum-fs1"
    ok = m.baum_senden(netz_a, partner_bei_a, "aufgabe",
                       {"titel": "Ephemer zugestellt"},
                       transport_id=m._fs_b64(b"E" * 16))
    _t.sleep(0.3)
    pruefe(ok and len(empfangen) == 2 and
           empfangen[-1][1]["titel"] == "Ephemer zugestellt",
           "der echte Zweiphasenkanal liefert mit Forward Secrecy aus")
    pruefe(not m.baum_senden_fs(
        netz_a, partner_bei_a, "aufgabe", {"titel": "Falsches HTTP-OK"},
        m._fs_b64(b"F" * 16), lambda _url, _inhalt: {"ok": True}),
        "ein bloßes HTTP-OK ohne kryptografische Quittung gilt nicht als zugestellt")

    ok = m.baum_senden(
        netz_b, partner_bei_b, "stand",
        {"id": "aufgabe-1", "erledigt": True, "geaendert": 123456})
    _t.sleep(0.4)
    pruefe(ok and len(empfangen_a) == 1,
           "die Erledigt-Rückmeldung reist zurück zum Erschaffer")
    pruefe(empfangen_a[0][1]["art"] == "stand" and
           empfangen_a[0][1]["id"] == "aufgabe-1" and
           empfangen_a[0][1]["erledigt"] is True,
           "die Rückmeldung nennt Aufgabe und neuen Stand")

    # Warteschlange: unerreichbarer Partner
    post = []
    m.baum_einreihen(post, netz_b["kennung"], "aufgabe", {"titel": "Später"})
    partner_bei_a["port"] = 18899          # dort lauscht niemand
    bericht = m.baum_post_zustellen(netz_a, post, _dt(2026, 7, 28, 10, 0))
    pruefe(bericht["zugestellt"] == 0 and bericht["offen"] == 1,
           "unzustellbares bleibt in der Warteschlange")
    pruefe(post[0]["versuche"] == 1, "und der Versuch wird gezählt")
    partner_bei_a["port"] = 18842
    bericht = m.baum_post_zustellen(netz_a, post, _dt(2026, 7, 28, 10, 5))
    _t.sleep(0.3)
    pruefe(bericht["zugestellt"] == 1 and not post,
           "sobald die Gegenstelle wieder da ist, wird zugestellt")

    # Nachbarsuche
    gefunden = m.baum_suchen(18842, 1.2, netz_a["kennung"])
    pruefe(any(g["kennung"] == netz_b["kennung"] for g in gefunden),
           "die Gegenstelle antwortet auf den Rundruf: %r"
           % [g.get("name") for g in gefunden])
finally:
    dienst_a.anhalten()
    dienst_b.anhalten()

print()
print("— Erinnerung an Aufgaben —")

aufgaben_daten = {"aufgaben": [
    {"id": "a1", "titel": "Mülltonne rausstellen", "faellig": "2026-07-28",
     "erinnern": True, "erledigt": False, "personenNamen": ["Max"]},
    {"id": "a2", "titel": "Ohne Erinnerung", "faellig": "2026-07-28",
     "erinnern": False, "erledigt": False},
    {"id": "a3", "titel": "Schon erledigt", "faellig": "2026-07-28",
     "erinnern": True, "erledigt": True},
]}

erg = m.faellige_aufgaben(aufgaben_daten, _dt(2026, 7, 28, 8, 5))
titel = [e["titel"] for e in erg["faellig"]]
pruefe(titel == ["Mülltonne rausstellen"],
       "nur die gewünschte offene Aufgabe wird gemeldet: %r" % titel)
kopf, rumpf = m.erinnerungstext(erg["faellig"][0])
pruefe(kopf == "Aufgabe fällig" and "Max" in rumpf,
       "die Meldung nennt die Aufgabe und die Person: %s – %s" % (kopf, rumpf))
zweiter = {"faellig": [], "verpasst": [], "zustand": erg["zustand"]}
erg2 = m.faellige_aufgaben(aufgaben_daten, _dt(2026, 7, 28, 8, 30), zweiter)
pruefe(not erg2["faellig"], "und wird nicht zweimal gemeldet")
pruefe(not m.faellige_aufgaben(aufgaben_daten, _dt(2026, 7, 28, 6, 0))["faellig"],
       "vor der eingestellten Stunde bleibt es still")
pruefe(not m.faellige_aufgaben(aufgaben_daten, _dt(2026, 7, 29, 12, 0))["faellig"],
       "einen Tag später wird nichts nachgereicht")
ohne_verpasste = m.faellige_aufgaben(
    aufgaben_daten, _dt(2026, 7, 28, 23, 0), verpasste=False)
pruefe(not ohne_verpasste["faellig"] and not ohne_verpasste["verpasst"],
       "abgeschaltete verpasste Erinnerungen gelten auch für Aufgaben")
aufgabe_individuell = {"aufgaben": [{"id": "ai", "titel": "Unterlagen senden",
    "faellig": "2026-08-04", "erinnern": True, "erledigt": False,
    "individuelleErinnerungTage": 7}]}
vorher = m.faellige_aufgaben(aufgabe_individuell, _dt(2026, 7, 28, 8, 0))
pruefe(len(vorher["faellig"]) == 1 and
       vorher["faellig"][0]["individuelleTage"] == 7,
       "Aufgabe meldet sich sieben Tage vor Fälligkeit")
am_tag = m.faellige_aufgaben(aufgabe_individuell, _dt(2026, 8, 4, 8, 0),
    {"faellig": [], "verpasst": [], "zustand": vorher["zustand"]})
pruefe(len(am_tag["faellig"]) == 1 and
       not am_tag["faellig"][0]["individuelleTage"],
       "individuelle und Fälligkeitstagsmeldung arbeiten nebeneinander")
zeitaufgabe = {"aufgaben": [{"id": "az", "titel": "Abgabe", "faellig": "2026-08-04",
    "faelligZeit": "14:30", "erinnern": True, "erledigt": False}]}
pruefe(not m.faellige_aufgaben(zeitaufgabe, _dt(2026, 8, 4, 14, 29))["faellig"] and
       m.faellige_aufgaben(zeitaufgabe, _dt(2026, 8, 4, 14, 30))["faellig"][0]["zeit"] == "14:30",
       "Aufgabe wird zur gewählten Fälligkeitszeit statt pauschal um 08:00 gemeldet")
alter_aufgabenstand = {"faellig": [], "verpasst": [], "zustand": {"gemeldet": {
    "af-alt-2026-08-04": "2026-08-04 08:00",
    "af-alt-2026-08-04-vorher-7": "2026-07-28 08:00"}, "letzter_lauf": ""}}
alte_aufgabe = {"aufgaben": [{"id": "alt", "titel": "Migriert",
    "faellig": "2026-08-04", "erinnern": True, "erledigt": False,
    "individuelleErinnerungTage": 7}]}
migriert = m.faellige_aufgaben(alte_aufgabe, _dt(2026, 8, 4, 8, 5), alter_aufgabenstand)
pruefe(not migriert["faellig"] and
       "af-alt-2026-08-04-0800" in migriert["zustand"]["gemeldet"],
       "alte Aufgaben-Erinnerungsmarken werden ohne Doppelmeldung übernommen")

print()
print("— Wiederkehrende Termine —")

woechentlich = {"id": "w1", "datum": "2026-07-07", "zeit": "08:00",
                "titel": "Mülltonne raus",
                "wiederholung": {"art": "woche", "bis": ""}}
monatlich = {"id": "m1", "datum": "2026-01-31", "zeit": "10:00",
             "titel": "Monatsabschluss",
             "wiederholung": {"art": "monat", "bis": ""}}
monatlicher_wochentag = {
    "id": "m2", "datum": "2024-01-11", "zeit": "",
    "titel": "Zweiter Donnerstag",
    "wiederholung": {"art": "monthly", "bis": "", "ordinal": 2,
                     "wochentag": "TH"}}
jaehrlich = {"id": "j1", "datum": "2024-02-29", "zeit": "09:00",
             "titel": "Jahresrechnung Garten",
             "wiederholung": {"art": "jahr", "bis": ""}}

pruefe(m.wiederholung_trifft(woechentlich, _dt(2026, 7, 28)),
       "der Dienstag darauf gehört dazu")
pruefe(not m.wiederholung_trifft(woechentlich, _dt(2026, 7, 29)),
       "der Mittwoch nicht")
pruefe(not m.wiederholung_trifft(woechentlich, _dt(2026, 6, 30)),
       "vor dem ersten Mal gibt es nichts")
pruefe(not m.wiederholung_trifft(woechentlich, _dt(2026, 7, 7)),
       "das erste Mal selbst wird nicht doppelt gezählt")
intervall_wochen = dict(woechentlich,
    wiederholung={"art": "weekly", "intervall": 3, "bis": ""})
eigene_tage = dict(woechentlich,
    wiederholung={"art": "custom", "daten": ["2026-07-19", "2026-08-03"], "bis": ""})
pruefe(m.wiederholung_trifft(intervall_wochen, _dt(2026, 7, 28)) and
       not m.wiederholung_trifft(intervall_wochen, _dt(2026, 7, 21)),
       "Drei-Wochen-Regel trifft nur im 21-Tage-Abstand")
pruefe(m.wiederholung_trifft(eigene_tage, _dt(2026, 7, 19)) and
       not m.wiederholung_trifft(eigene_tage, _dt(2026, 7, 20)),
       "benutzerdefinierte Tagesauswahl trifft nur gewählte Tage")

pruefe(m.wiederholung_trifft(monatlich, _dt(2026, 3, 31)),
       "der 31. im März gehört dazu")
pruefe(m.wiederholung_trifft(monatlich, _dt(2026, 4, 30)),
       "im April rückt es auf den 30.")
pruefe(not m.wiederholung_trifft(monatlich, _dt(2026, 4, 29)),
       "aber nicht auf den 29.")
pruefe(all(m.wiederholung_trifft(monatlicher_wochentag, _dt(*datum))
           for datum in ((2024, 2, 8), (2024, 3, 14), (2024, 4, 11))) and
       not any(m.wiederholung_trifft(monatlicher_wochentag, _dt(*datum))
               for datum in ((2024, 2, 1), (2024, 3, 21), (2024, 4, 18))),
       "zweiter Donnerstag wird monatlich ohne falsche Treffer expandiert")

pruefe(m.wiederholung_trifft(jaehrlich, _dt(2028, 2, 29)),
       "im Schaltjahr am 29. Februar")
pruefe(m.wiederholung_trifft(jaehrlich, _dt(2027, 2, 28)),
       "sonst am 28. Februar")
pruefe(not m.wiederholung_trifft(jaehrlich, _dt(2028, 2, 28)),
       "im Schaltjahr aber nicht am 28.")

mit_ende = dict(woechentlich, wiederholung={"art": "woche", "bis": "2026-07-21"})
pruefe(not m.wiederholung_trifft(mit_ende, _dt(2026, 7, 28)),
       "nach dem Enddatum ist Schluss")
pruefe(m.wiederholung_trifft(mit_ende, _dt(2026, 7, 14)),
       "davor aber schon")

ohne = dict(woechentlich, wiederholung={"art": "keine", "bis": ""})
pruefe(not m.wiederholung_trifft(ohne, _dt(2026, 7, 28)),
       "ein einmaliger Termin wiederholt sich nicht")

daten_w = {"termine": [woechentlich]}
alle = m.termine_mit_wiederholungen(daten_w, _dt(2026, 7, 28, 7, 50))
pruefe(len(alle) == 2, "der Ursprung und das heutige Mal (%d)" % len(alle))
pruefe(any(x["id"] == "w1@2026-07-28" for x in alle),
       "jedes Mal bekommt eine eigene Kennung")

ordinal_mehrtag = {
    "id": "m3", "datum": "2026-01-30", "endDatum": "2026-01-31",
    "zeit": "09:15", "endZeit": "10:45", "titel": "Letzter Freitag",
    "wiederholung": {"art": "monthly", "bis": "", "ordinal": -1,
                      "wochentag": "FR", "rruleForm": "bysetpos"}}
ordinal_alle = m.termine_mit_wiederholungen(
    {"termine": [ordinal_mehrtag]}, _dt(2026, 2, 27, 9, 0))
ordinal_folge = next(x for x in ordinal_alle if x.get("folge"))
pruefe(ordinal_folge["datum"] == "2026-02-27" and
       ordinal_folge["endDatum"] == "2026-02-28" and
       ordinal_folge["zeit"] == "09:15" and ordinal_folge["endZeit"] == "10:45",
       "native Expansion verschiebt die zweitägige zeitgebundene Ordinalserie exakt")
ordinal_alarm = m.faellige_erinnerungen(
    {"termine": [ordinal_mehrtag]}, _dt(2026, 2, 27, 9, 0),
    {"gemeldet": {}, "letzter_lauf": ""}, vorlauf=15)
pruefe(any(e["titel"] == "Letzter Freitag" for e in ordinal_alarm["faellig"]),
       "nativer Wecker erinnert an die zeitgebundene letzte-Freitag-Serie")

zustand_w = {"gemeldet": {}, "letzter_lauf": ""}
erg = m.faellige_erinnerungen(daten_w, _dt(2026, 7, 28, 7, 50), zustand_w,
                              vorlauf=15)
pruefe(any(e["titel"] == "Mülltonne raus" for e in erg["faellig"]),
       "der Wecker erinnert an das wiederkehrende Mal")
erg2 = m.faellige_erinnerungen(daten_w, _dt(2026, 7, 28, 7, 55),
                               erg["zustand"], vorlauf=15)
pruefe(not erg2["faellig"], "und meldet es kein zweites Mal")

print()
print("— Erinnerung an Jahrestage —")

jt_daten = {"jahrestage": [
    {"id": "j1", "name": "Max Mustermann", "datum": "1980-07-27",
     "typ": "Geburtstag"},
    {"id": "j2", "name": "Anna und Otto", "datum": "--07-25",
     "typ": "Hochzeitstag"},
    {"id": "j3", "name": "Vereinsjubiläum", "datum": "1975-12-24",
     "typ": "Sonstiges"},
]}

erg = m.faellige_jahrestage(jt_daten, _dt(2026, 7, 25, 9, 0),
                            tage_vorher=2, auch_am_tag=True)
namen = [e["titel"] for e in erg["faellig"]]
pruefe(any("Max Mustermann hat übermorgen Geburtstag" in n for n in namen),
       "zwei Tage vorher wird an den Geburtstag erinnert: %r" % namen)
pruefe(any("Anna und Otto" in n for n in namen),
       "der Hochzeitstag am selben Tag wird gemeldet")
pruefe(not any("Vereinsjubiläum" in n for n in namen),
       "ein Jahrestag im Dezember bleibt still")

erg2 = m.faellige_jahrestage(jt_daten, _dt(2026, 7, 25, 9, 30), erg,
                             tage_vorher=2, auch_am_tag=True)
pruefe(len(erg2["faellig"]) == len(erg["faellig"]),
       "nichts wird zweimal gemeldet")

erg = m.faellige_jahrestage(jt_daten, _dt(2026, 7, 27, 8, 5),
                            tage_vorher=0, auch_am_tag=True)
pruefe(any("hat heute Geburtstag" in e["titel"] for e in erg["faellig"]),
       "am Tag selbst heißt es „heute“: %r"
       % [e["titel"] for e in erg["faellig"]])

erg = m.faellige_jahrestage(jt_daten, _dt(2026, 7, 26, 8, 5),
                            tage_vorher=1, auch_am_tag=False)
pruefe(any("hat morgen Geburtstag" in e["titel"] for e in erg["faellig"]),
       "einen Tag vorher heißt es „morgen“")

erg = m.faellige_jahrestage(jt_daten, _dt(2026, 7, 27, 23, 50),
                            tage_vorher=0, auch_am_tag=True)
pruefe(not erg["faellig"], "spät am Abend wird nichts mehr nachgereicht")

kopf, rumpf = m.jahrestagstext(
    {"name": "Max Mustermann", "typ": "Geburtstag"}, 0)
pruefe(kopf.startswith("Geburtstag") and "hat heute Geburtstag" in rumpf,
       "Text am Tag selbst: %s – %s" % (kopf, rumpf))
pruefe(m._jahrestag_im_jahr({"datum": "2000-02-29"}, 2027).day == 28 and
       m._jahrestag_im_jahr({"datum": "--02-29"}, 2027).day == 28 and
       m._jahrestag_im_jahr({"datum": "--02-29"}, 2028).day == 29,
       "der 29. Februar rutscht auch jahrlos nur in Nicht-Schaltjahren auf den 28.")

print()
print("— Nur eine Stelle meldet —")
zustandsprobe2 = os.path.join(tempfile.mkdtemp(prefix="magnolie-einmal-"), "e.json")
pruefe(m.protokoll_oeffnen(lambda a: None)["ok"] is True,
       "das Protokoll lässt sich öffnen")
oeffner_alt = m.shutil.which
oeffner_aufrufe = []
m.shutil.which = lambda name: "/usr/bin/" + name if name in ("xdg-open", "xed") else None
try:
    oeffner_erg = m.protokoll_oeffnen(lambda a: oeffner_aufrufe.append(a))
finally:
    m.shutil.which = oeffner_alt
pruefe(oeffner_erg["womit"] == "xdg-open" and
       oeffner_aufrufe[0][0] == "/usr/bin/xdg-open",
       "die voreingestellte Textanwendung gewinnt vor zufällig installierten Editoren")
erg = m.protokoll_oeffnen(lambda a: (_ for _ in ()).throw(OSError("nein")))
pruefe(erg["ok"] is False and "Protokoll" in erg["fehler"],
       "misslingt es, wird der Pfad genannt")

print()
print("— Protokoll bleibt klein —")

jetzt_probe = _dt(2026, 7, 26, 12, 0)
zeilen_probe = [
    "01.01.2026 08:00:00  uralt",
    "20.06.2026 08:00:00  vor über 30 Tagen",
    "26.06.2026 12:00:01  gerade noch drin",
    "25.07.2026 08:00:00  gestern",
    "ohne Datum, aber wichtig",
]
gekuerzt = m.protokoll_kuerzen(zeilen_probe, jetzt_probe, tage=30)
pruefe("uralt" not in " ".join(gekuerzt) and
       "vor über 30 Tagen" not in " ".join(gekuerzt),
       "alte Einträge verschwinden")
pruefe(any("gerade noch drin" in z for z in gekuerzt) and
       any("gestern" in z for z in gekuerzt),
       "junge Einträge bleiben")
pruefe(any("ohne Datum" in z for z in gekuerzt),
       "Zeilen ohne lesbares Datum bleiben vorsichtshalber stehen")

viele = ["26.07.2026 08:00:%02d  Zeile %d" % (i % 60, i) for i in range(500)]
pruefe(len(m.protokoll_kuerzen(viele, jetzt_probe, hoechstens=200)) == 200,
       "die Zeilenzahl bleibt gedeckelt")
pruefe(m.protokoll_kuerzen(viele, jetzt_probe, hoechstens=200)[-1].endswith("499"),
       "und zwar bleiben die jüngsten Zeilen")

protokollprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-prot-"), "w.log")
m._PROTOKOLL["an"] = False
m.wecker_notiz("darf nicht erscheinen", protokollprobe)
pruefe(not os.path.exists(protokollprobe),
       "abgeschaltet wird gar nichts geschrieben")
m._PROTOKOLL["an"] = True
m.wecker_notiz("nun aber", protokollprobe)
pruefe(os.path.isfile(protokollprobe) and
       "nun aber" in open(protokollprobe, encoding="utf-8").read(),
       "eingeschaltet landet die Zeile im Protokoll")

print()
print("— Kein überflüssiger Aufwand —")

schreibprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-schreib-"),
                            "tief", "datei.txt")
fsync_probe_pfad = os.path.join(tempfile.mkdtemp(prefix="magnolie-fsync-"),
                                "datei.txt")
fsync_alt = m.os.fsync
fsync_arten = []
def _fsync_probe(fd):
    fsync_arten.append("ordner" if stat.S_ISDIR(os.fstat(fd).st_mode) else "datei")
    return fsync_alt(fd)
m.os.fsync = _fsync_probe
try:
    m.atomar_text_schreiben(fsync_probe_pfad, "Inhalt")
finally:
    m.os.fsync = fsync_alt
pruefe("datei" in fsync_arten and "ordner" in fsync_arten,
       "atomares Schreiben synchronisiert Datei und Verzeichniseintrag")
pruefe(m.schreibe_wenn_anders(schreibprobe, "Inhalt") is True,
       "neue Datei wird angelegt")
pruefe(m.schreibe_wenn_anders(schreibprobe, "Inhalt") is False,
       "gleicher Inhalt wird nicht noch einmal geschrieben")
pruefe(m.schreibe_wenn_anders(schreibprobe, "anders") is True,
       "geänderter Inhalt wird geschrieben")

datenprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-daten-"), "daten.json")
with open(datenprobe, "w", encoding="utf-8") as datei:
    datei.write('{"termine": [{"id": "t1"}]}')
erst = m.daten_lesen_gepuffert(datenprobe)
nochmal = m.daten_lesen_gepuffert(datenprobe)
pruefe(erst is nochmal, "unveränderte Daten werden nicht neu eingelesen")
import time as _zeit
_zeit.sleep(0.01)
with open(datenprobe, "w", encoding="utf-8") as datei:
    datei.write('{"termine": [{"id": "t2"}]}')
danach = m.daten_lesen_gepuffert(datenprobe)
pruefe(danach is not erst and danach["termine"][0]["id"] == "t2",
       "geänderte Daten werden neu eingelesen")
pruefe(m.daten_lesen_gepuffert(datenprobe + "-weg") is None,
       "fehlende Daten stören nicht")

print()
print("— Aussehen der Fenster —")

stil_text = m.MAGNOLIE_MELDUNG_STIL.decode("utf-8")
pruefe("box.rahmen" in stil_text and "border-radius: 13px" in stil_text,
       "das Meldeblatt hat einen abgerundeten Lederrahmen")
pruefe("window.magnolie-meldung { background-color: transparent; }" in stil_text,
       "mit Bildmischung ist das Fenster durchsichtig")
pruefe("ohne-mischung { background-color: #55291c; }" in stil_text,
       "ohne Bildmischung bleibt es beim gefüllten Leder – nicht schwarz")
pruefe("ohne-mischung box.rahmen { border-radius: 0; }" in stil_text,
       "und dann ohne runde Ecken, damit kein Rand stehen bleibt")

with open(PFAD, encoding="utf-8") as datei:
    quelle = datei.read()
with open(os.path.join(QUELLWURZEL, "web", "index.html"), encoding="utf-8") as datei:
    organizer_html = datei.read()
pruefe(organizer_html.count('<script src="i18n-active.js"></script>') == 1 and
       not re.search(r'<script src="i18n/[^\"]+\.js"></script>', organizer_html),
       "die Oberfläche lädt beim Start nur den aktiven Sprachkatalog")
pruefe("def zeige_wenn_bereit" in quelle,
       "das Fenster wird erst nach dem Laden gezeigt")
pruefe("LoadEvent.FINISHED" in quelle and "timeout_add_seconds" in quelle,
       "mit Sicherheitsnetz, falls das Laden hakt")
pruefe("magnolie-fenster { background-color: #2e3a34; }" in quelle,
       "das Fenster trägt von Anfang an die Filzfarbe")
pruefe(quelle.count("set_border_width(0)") >= 1,
       "der eckige Rand um das Meldeblatt ist fort")

web_probe_wurzel = tempfile.mkdtemp(prefix="magnolie-web-ursprung-")
web_probe = os.path.join(web_probe_wurzel, "web")
try:
    os.makedirs(os.path.join(web_probe, "i18n"))
    os.makedirs(os.path.join(web_probe, "schriften"))
    feste_web_dateien = ("index.html", "stil.css", "i18n.js", "i18n-en.js",
                         "i18n-start.js", "anwendung.js")
    katalog_dateien = tuple("i18n/%s.js" % sprache
                            for sprache in m.UNTERSTUETZTE_SPRACHEN)
    for web_name in feste_web_dateien + katalog_dateien:
        web_pfad = os.path.join(web_probe, web_name)
        with open(web_pfad, "w", encoding="utf-8") as datei:
            datei.write(web_name)
    schrift_pfad = os.path.join(web_probe, "schriften", "Z003-MediumItalic.otf")
    with open(schrift_pfad, "wb") as datei:
        datei.write(b"OTTO")
    pruefe(m.contributor_hash_lesen(web_probe) == "",
           "Quellbau aktiviert Contributor-Branding")
    config_pfad = os.path.join(os.path.dirname(web_probe), "build-config.json")
    with open(config_pfad, "w", encoding="ascii") as datei:
        json.dump({"contributorHash": "ab" * 32}, datei)
    pruefe(m.contributor_hash_lesen(web_probe) == "ab" * 32,
           "gültige Contributor-Buildkonfiguration wird nicht gelesen")

    freigabe_daten = {"einstellungen": {"allgemein": {
        "contributorFreigeschaltet": True}}}
    gesperrte_daten = {"einstellungen": {"allgemein": {
        "contributorFreigeschaltet": False}}}
    pruefe(not m.contributor_dauerhaft_freigeschaltet(freigabe_daten, ""),
           "Eigenbau ohne Hash darf keine markerfreien Logs liefern")
    pruefe(not m.contributor_dauerhaft_freigeschaltet(gesperrte_daten, "ab" * 32),
           "offizieller, nicht freigeschalteter Build darf keinen Marker verlieren")
    pruefe(m.contributor_dauerhaft_freigeschaltet(freigabe_daten, "ab" * 32),
           "persistente Contributor-Freischaltung wird nicht erkannt")
    pruefe(not m.contributor_dauerhaft_freigeschaltet(None, "ab" * 32),
           "gesperrte Daten müssen bei Logs fail-closed bleiben")

    for original in ("", "eine Zeile\n",
                     'eins\n"No valid"\nzwei\n"No valid"\ndrei\n'):
        ansicht = m.protokoll_aufbereiten(original, False, jetzt_probe)
        ansicht_zeilen = ansicht.splitlines()
        pruefe(ansicht_zeilen.count('"No valid"') == 1,
               "Logmarker steht nicht exakt einmal allein")
        marker_pos = ansicht_zeilen.index('"No valid"')
        pruefe(0 < marker_pos < len(ansicht_zeilen) - 1,
               "Logmarker steht am Anfang oder Ende")
    pruefe('"No valid"' not in m.protokoll_aufbereiten(
        'eins\n"No valid"\nzwei\n', True, jetzt_probe),
        "alter Logmarker bleibt nach Freischaltung erhalten")
    os.unlink(config_pfad)

    ressource = m.organizer_ressource(m.ORGANIZER_URI, web_probe)
    pruefe(ressource and ressource[0] == os.path.join(web_probe, "index.html") and
           ressource[1] == "text/html",
           "nur der feste Organizer-Ursprung liefert die Hauptoberfläche")
    pruefe(all(m.organizer_ressource(
        "magnolie-organizer://app/i18n/%s.js" % sprache, web_probe)
        for sprache in m.UNTERSTUETZTE_SPRACHEN),
        "das interne URI-Schema liefert alle Sprachkataloge")
    aktiver_katalog = m.organizer_ressource(
        "magnolie-organizer://app/i18n-active.js", web_probe, "pt-BR")
    pruefe(aktiver_katalog and aktiver_katalog[0] == os.path.join(
        web_probe, "i18n", "pt.js"),
        "das interne URI-Schema liefert nur den normalisierten aktiven Sprachkatalog")
    englischer_katalog = m.organizer_ressource(
        "magnolie-organizer://app/i18n-active.js", web_probe, "en-US")
    pruefe(englischer_katalog and englischer_katalog[0] == os.path.join(
        web_probe, "i18n-en.js"),
        "Englisch startet ohne einen künstlichen Übersetzungskatalog")
    schrift_ressource = m.organizer_ressource(
        "magnolie-organizer://app/schriften/Z003-MediumItalic.otf", web_probe)
    pruefe(schrift_ressource and schrift_ressource[0] == schrift_pfad and
           schrift_ressource[1] == "font/otf",
           "das interne URI-Schema liefert die gebündelte Handschrift")
    pruefe(all(m.organizer_ressource(adresse, web_probe) is None for adresse in (
        "file:///tmp/angriff.html",
        "magnolie-organizer://fremd/index.html",
        "magnolie-organizer://app/../daten.json",
        "magnolie-organizer://app/%2e%2e/daten.json",
        "magnolie-organizer://app/index.html?fremd=1",
        "magnolie-organizer://app/unbekannt.js")),
        "das interne URI-Schema besitzt eine geschlossene Datei-Allowlist")
finally:
    m.shutil.rmtree(web_probe_wurzel)

pruefe(m.organizer_navigation(m.ORGANIZER_URI) == "intern" and
       m.organizer_navigation("file:///tmp/angriff.html", True) == "sperren" and
       m.organizer_navigation("about:blank", True) == "sperren" and
       m.organizer_navigation("javascript:alert(1)", True) == "sperren" and
       m.organizer_navigation("data:application/pdf;base64,JVBERi0=", True) == "sperren" and
       m.organizer_navigation("https://example.org", False) == "sperren" and
       m.organizer_navigation("https://example.org", True) == "extern" and
       m.organizer_navigation("mailto:test@example.org", True) == "extern",
       "Navigation bleibt intern geschlossen und öffnet nur bewusste Weblinks extern")

class _UriAnsicht:
    def __init__(self, uri):
        self.uri = uri

    def get_uri(self):
        return self.uri

class _VertrauensProbe:
    _organizer_geladen = True
    _organizer_uri = m.ORGANIZER_URI
    ansicht = _UriAnsicht(m.ORGANIZER_URI)

vertrauens_probe = _VertrauensProbe()
pruefe(m.Fenster._organizer_vertraut(vertrauens_probe),
       "die festgeschriebene und geladene Organizer-URI darf die Brücke verwenden")
vertrauens_probe.ansicht.uri = "file:///tmp/angriff.html"
pruefe(not m.Fenster._organizer_vertraut(vertrauens_probe),
       "eine fremde lokale Datei verliert eingehende und ausgehende Brückenrechte")
pruefe("bridge_\" + os.urandom(16).hex()" in quelle and
       "UserContentInjectedFrames.TOP_FRAME" in quelle and
       "if not self._organizer_vertraut()" in quelle and
       "load_uri(self._organizer_uri)" in quelle,
       "die native Brücke ist zufällig, nur im Topframe und beidseitig URI-gebunden")

alt_wayland = os.environ.get("WAYLAND_DISPLAY")
alt_wayland_meldung = os.environ.get("MAGNOLIE_WAYLAND_MELDUNG")
alt_magnolie_meldung = m.magnolie_meldung
alt_benachrichtigen = m.benachrichtigen
wege = []
try:
    os.environ["WAYLAND_DISPLAY"] = "wayland-0"
    m.magnolie_meldung = lambda *_a, **_k: wege.append("magnolie") or True
    m.benachrichtigen = lambda *_a, **_k: wege.append("system") or True
    pruefe(m.melden("Probe", "Text", "magnolie") == "system" and
           wege == ["system"],
           "unter Wayland fällt das nicht platzierbare Magnolie-Meldeblatt auf das System zurück")
    wege.clear()
    os.environ["MAGNOLIE_WAYLAND_MELDUNG"] = "1"
    pruefe(m.melden("Probe", "Text", "magnolie") == "magnolie" and
           wege == ["magnolie"],
           "der Wayland-Entwicklerprobe kann das Magnolie-Meldeblatt ausdrücklich freischalten")
    wege.clear()
    m.magnolie_meldung = lambda *_a, **_k: wege.append("magnolie") or False
    pruefe(m.melden("Probe", "Text", "magnolie") == "system" and
           wege == ["magnolie", "system"],
           "ein unsichtbares Wayland-Meldeblatt fällt auf die Systemmeldung zurück")
finally:
    m.magnolie_meldung = alt_magnolie_meldung
    m.benachrichtigen = alt_benachrichtigen
    if alt_wayland is None:
        os.environ.pop("WAYLAND_DISPLAY", None)
    else:
        os.environ["WAYLAND_DISPLAY"] = alt_wayland
    if alt_wayland_meldung is None:
        os.environ.pop("MAGNOLIE_WAYLAND_MELDUNG", None)
    else:
        os.environ["MAGNOLIE_WAYLAND_MELDUNG"] = alt_wayland_meldung

class _SmsGLibProbe:
    rueckrufe = []

    @classmethod
    def idle_add(cls, rueckruf):
        cls.rueckrufe.append(rueckruf)
        return len(cls.rueckrufe)

class _SmsFensterProbe:
    def __init__(self):
        self.aktionen = []

    def _tray_zeigen(self):
        self.aktionen.append("tray")

    def antwort(self, name, wert):
        self.aktionen.append((name, wert))

sms_glib_alt = m.GLib
sms_thread_alt = m.threading.Thread
sms_magnolie_alt = m.magnolie_meldung
sms_system_alt = m.benachrichtigen
sms_aufrufe = []
sms_wayland_alt = os.environ.pop("WAYLAND_DISPLAY", None)
try:
    m.GLib = _SmsGLibProbe
    m.threading.Thread = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("notification thread"))
    m.magnolie_meldung = lambda *args, **kwargs: sms_aufrufe.append(
        ("magnolie", args, kwargs)) or True
    m.benachrichtigen = lambda *args, **kwargs: sms_aufrufe.append(
        ("system", args, kwargs)) or True
    sms_fenster = _SmsFensterProbe()
    m.Fenster._telefon_sms_benachrichtigen(sms_fenster, {
        "name": "Ada", "nummer": "+49170", "kennung": "telefon-1",
        "text": "Hallo", "stil": "magnolie", "dauer": 30})
    pruefe(not sms_aufrufe and len(_SmsGLibProbe.rueckrufe) == 1,
           "SMS-Meldungen werden nur in den GLib-Hauptkontext eingeplant")
    _SmsGLibProbe.rueckrufe.pop(0)()
    magnolie_aktion = sms_aufrufe[0][2]["aktion"]
    magnolie_aktion()
    magnolie_aktion()
    pruefe(sms_aufrufe[0][0] == "magnolie" and
           sms_aufrufe[0][2]["eigene_schleife"] is False and
           sms_fenster.aktionen == ["tray", ("App.telefonAntwort", {
               "kennung": "telefon-1", "nummer": "+49170"})],
           "Magnolie-SMS nutzt keine eigene GTK-Schleife und antwortet genau einmal")

    sms_aufrufe.clear()
    m.magnolie_meldung = lambda *_a, **_k: False
    m.Fenster._telefon_sms_benachrichtigen(sms_fenster, {
        "name": "Ada", "nummer": "+49170", "kennung": "telefon-1",
        "text": "Fallback", "stil": "magnolie"})
    _SmsGLibProbe.rueckrufe.pop(0)()
    pruefe(sms_aufrufe[0][0] == "system" and
           sms_aufrufe[0][2]["eigene_schleife"] is False,
           "auch der System-Fallback bleibt nichtblockierend im GLib-Hauptkontext")
finally:
    m.GLib = sms_glib_alt
    m.threading.Thread = sms_thread_alt
    m.magnolie_meldung = sms_magnolie_alt
    m.benachrichtigen = sms_system_alt
    if sms_wayland_alt is not None:
        os.environ["WAYLAND_DISPLAY"] = sms_wayland_alt

anruf_glib_alt = m.GLib
anruf_magnolie_alt = m.magnolie_meldung
anruf_system_alt = m.benachrichtigen
anruf_wayland_alt = os.environ.pop("WAYLAND_DISPLAY", None)
try:
    _SmsGLibProbe.rueckrufe.clear()
    m.GLib = mock.Mock(idle_add=_SmsGLibProbe.idle_add, timeout_add=lambda *_: 1)
    anruf_aufrufe = []
    m.magnolie_meldung = lambda *args, **kwargs: anruf_aufrufe.append(
        ("magnolie", args, kwargs)) or True
    m.benachrichtigen = lambda *args, **kwargs: anruf_aufrufe.append(
        ("system", args, kwargs)) or True
    anruf_fenster = _SmsFensterProbe()
    anruf_fenster._telefon = mock.Mock()
    anruf_fenster._telefon.call_action_tokens.return_value = {"answer": "a" * 64, "reject": "b" * 64}
    anruf_fenster._daten_sperre = m.threading.RLock()
    anruf_fenster._aktuelle_daten = {"kontakte": [{"vorname": "Ada", "nachname": "Lovelace",
        "telefone": [{"wert": "+491711234567"}], "foto": "data:image/png;base64,iVBORw0KGgo="}]}
    anruf_fenster._call_system_notifications = mock.Mock()
    anruf_fenster._call_system_notifications.show.side_effect = lambda *args, **kwargs: anruf_aufrufe.append(
        ("system", args, kwargs)) or True

    def _anruf_probe_anzeigen(call_ref):
        anruf_fenster._aktueller_anruf_hinweis = {
            "state": "ringing", "direction": "incoming", "call_ref": call_ref,
            "device_id": "telefon-1", "revision": 1, "occurred_ms": int(m.time.time() * 1000),
            "number": "+491711234567", "number_status": "available"}
        m.Fenster._telefon_anruf_anzeigen(anruf_fenster, {
            "state": "ringing", "callRef": call_ref, "kennung": "telefon-1", "revision": 1,
            "name": "Untrusted remote name", "annehmen": True, "stil": "magnolie", "dauer": 60})

    _anruf_probe_anzeigen("call-1")
    pruefe(not anruf_aufrufe and len(_SmsGLibProbe.rueckrufe) == 1,
           "Anrufmeldungen werden nur in den GLib-Hauptkontext eingeplant")
    _SmsGLibProbe.rueckrufe.pop(0)()
    anruf_aktion = anruf_aufrufe[0][2]["aktionen"][0][2]
    anruf_aktion()
    _anruf_probe_anzeigen("call-1")
    pruefe([aufruf[0] for aufruf in anruf_aufrufe] == ["magnolie"] and
           anruf_aufrufe[0][2]["eigene_schleife"] is False and
           anruf_aufrufe[0][2]["foto"].startswith(b"\x89PNG") and
           anruf_aufrufe[0][2]["initialen"] == "AL" and
           anruf_fenster._telefon.call_action.call_args == mock.call("a" * 64) and
           anruf_fenster._telefon.call_action.call_count == 1 and not _SmsGLibProbe.rueckrufe and
           not anruf_fenster._telefon.request_answer.called,
           "eigene Anrufmeldung nutzt lokale Foto/Initialen, kein Duplikat und das gebundene Aktionsticket")

    anruf_aufrufe.clear()
    m.magnolie_meldung = lambda *_a, **_k: False
    _anruf_probe_anzeigen("call-2")
    _SmsGLibProbe.rueckrufe.pop(0)()
    pruefe([aufruf[0] for aufruf in anruf_aufrufe] == ["system"],
           "bei fehlgeschlagener eigener Anrufmeldung erscheint genau eine Systemmeldung")

    anruf_aufrufe.clear()
    m.magnolie_meldung = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kaputt"))
    _anruf_probe_anzeigen("call-3")
    _SmsGLibProbe.rueckrufe.pop(0)()
    pruefe([aufruf[0] for aufruf in anruf_aufrufe] == ["system"],
           "auch nach einer Ausnahme erscheint genau eine System-Anrufmeldung")

    anruf_aufrufe.clear()
    os.environ["WAYLAND_DISPLAY"] = "wayland-0"
    m.magnolie_meldung = lambda *args, **kwargs: anruf_aufrufe.append(
        ("magnolie", args, kwargs)) or True
    _anruf_probe_anzeigen("call-4")
    _SmsGLibProbe.rueckrufe.pop(0)()
    pruefe([aufruf[0] for aufruf in anruf_aufrufe] == ["magnolie"],
           "unter Wayland darf die kompakte Anrufmeldung ohne Systemduplikat erscheinen")
finally:
    m.GLib = anruf_glib_alt
    m.magnolie_meldung = anruf_magnolie_alt
    m.benachrichtigen = anruf_system_alt
    if anruf_wayland_alt is None:
        os.environ.pop("WAYLAND_DISPLAY", None)
    else:
        os.environ["WAYLAND_DISPLAY"] = anruf_wayland_alt

print()
print("— Kennwortschutz und Verschlüsselung —")

pruefe(m.kennwort_moeglich() is True,
       "die Verschlüsselung steht zur Verfügung")

klartext = '{"termine": [{"titel": "Geheimer Termin"}]}'
huelle = m.verschluesseln(klartext, "Rosenholz1896")
pruefe(m.ist_verschluesselt(huelle), "die Hülle wird als solche erkannt")
lange_huelle = huelle[:-1] + ', "reserve": "' + ("x" * 1000) + '"}'
pruefe(len(lange_huelle) > 400 and
       m.ist_verschluesselt(lange_huelle) and
       m.sieht_verschluesselt_aus(lange_huelle[:400]),
       "auch der Anfang einer großen Hülle wird sicher erkannt")
pruefe("Geheimer Termin" not in huelle,
       "der Klartext steht nicht mehr in der Datei")
pruefe(m.entschluesseln(huelle, "Rosenholz1896") == klartext,
       "mit dem richtigen Kennwort kommt alles zurück")

huellen_felder = {
    "magnolie": "fremd",
    "fassung": 2,
    "verfahren": "AES-128-GCM",
    "runden": m.KENNWORT_RUNDEN_MAX + 1,
    "salz": "AA==",
    "nonce": "!kein-base64!",
    "daten": "AA==",
}
for feld, wert in huellen_felder.items():
    beschaedigt = json.loads(huelle)
    beschaedigt[feld] = wert
    try:
        m.entschluesseln(json.dumps(beschaedigt), "Rosenholz1896")
        pruefe(False, "ungültiger Hüllenparameter %s müsste scheitern" % feld)
    except RuntimeError as f:
        pruefe("beschädigt" in str(f),
               "ungültiger Hüllenparameter %s wird vor der Ableitung abgewiesen" % feld)

for runden in (True, 49999, "240000"):
    beschaedigt = json.loads(huelle)
    beschaedigt["runden"] = runden
    try:
        m.entschluesseln(json.dumps(beschaedigt), "Rosenholz1896")
        pruefe(False, "ungültige Rundenzahl %r müsste scheitern" % runden)
    except RuntimeError as f:
        pruefe("beschädigt" in str(f),
               "ungültige Rundenzahl %r wird begrenzt" % runden)

for falsch in ("rosenholz1896", "Rosenholz1897", "", "1234"):
    try:
        m.entschluesseln(huelle, falsch)
        pruefe(False, "falsches Kennwort %r müsste scheitern" % falsch)
    except RuntimeError as f:
        pruefe("Kennwort" in str(f) or "beschädigt" in str(f),
               "falsches Kennwort %r wird abgewiesen" % falsch)

zwei = m.verschluesseln(klartext, "Rosenholz1896")
pruefe(zwei != huelle, "zweimal verschlüsseln ergibt nicht dasselbe (Salz)")
pruefe(m.entschluesseln(zwei, "Rosenholz1896") == klartext,
       "und lässt sich trotzdem öffnen")

verbogen = huelle.replace('"daten": "', '"daten": "A')
try:
    m.entschluesseln(verbogen, "Rosenholz1896")
    pruefe(False, "veränderte Daten müssten auffallen")
except RuntimeError:
    pruefe(True, "jede Veränderung der Datei fällt auf")

daten_v2, daten_dek, daten_dek_kennung, daten_umschlag = (
    m.daten_huelle_anlegen(klartext, "Rosenholz1896"))
daten_v2_huelle = json.loads(daten_v2)
pruefe(daten_v2_huelle["fassung"] == 2 and
       daten_v2_huelle["verfahren"] == m.DATEN_VERFAHREN and
       klartext not in daten_v2 and
       m.daten_entschluesseln(daten_v2, "Rosenholz1896") == klartext,
       "Hauptdaten verwenden eine authentisierte DEK-Hülle der Fassung 2")

kdf_alt = m._schluessel_ableiten
kdf_aufrufe = []
def _kdf_zaehlen(*args, **kwargs):
    kdf_aufrufe.append(1)
    return kdf_alt(*args, **kwargs)

m._schluessel_ableiten = _kdf_zaehlen
try:
    daten_v2_neu = m.daten_verschluesseln(
        klartext + " neu", "Rosenholz1896", daten_dek,
        daten_dek_kennung, daten_umschlag)
finally:
    m._schluessel_ableiten = kdf_alt
daten_v2_neu_huelle = json.loads(daten_v2_neu)
pruefe(not kdf_aufrufe and all(
       daten_v2_neu_huelle[name] == daten_v2_huelle[name] for name in
       ("dekKennung", "runden", "salz", "dekNonce", "dekDaten")) and
       daten_v2_neu_huelle["datenNonce"] != daten_v2_huelle["datenNonce"],
       "normales Speichern behält DEK und Umschlag ohne neue KDF bei")

(daten_v2_umgeschlagen, daten_dek_nach, daten_kennung_nach,
 _daten_umschlag_nach) = m.daten_umschlagen(
    daten_v2_neu, "Rosenholz1896", "Magnolie 2026")
daten_v2_um_huelle = json.loads(daten_v2_umgeschlagen)
pruefe(daten_dek_nach == daten_dek and
       daten_kennung_nach == daten_dek_kennung and
       daten_v2_um_huelle["daten"] == daten_v2_neu_huelle["daten"] and
       daten_v2_um_huelle["datenNonce"] == daten_v2_neu_huelle["datenNonce"] and
       daten_v2_um_huelle["dekDaten"] != daten_v2_neu_huelle["dekDaten"] and
       m.daten_entschluesseln(
           daten_v2_umgeschlagen, "Magnolie 2026") == klartext + " neu",
       "Kennwortwechsel umhüllt nur den stabilen Hauptdaten-DEK neu")
try:
    m.daten_entschluesseln(daten_v2_umgeschlagen, "Rosenholz1896")
    pruefe(False, "der alte Hauptdatenumschlag dürfte nicht mehr öffnen")
except RuntimeError:
    pruefe(True, "nach dem Umschlagen gilt nur das neue Kennwort")

for feld in ("dekDaten", "daten", "dekKennung"):
    manipuliert = dict(daten_v2_huelle)
    roh = bytearray(m.base64.b64decode(manipuliert[feld]))
    roh[len(roh) // 2] ^= 1
    manipuliert[feld] = m.base64.b64encode(bytes(roh)).decode("ascii")
    try:
        m.daten_entschluesseln(json.dumps(manipuliert), "Rosenholz1896")
        erkannt = False
        meldung = ""
    except RuntimeError as crypto_fehler:
        erkannt = True
        meldung = str(crypto_fehler)
    pruefe(erkannt, "Manipulation am Hauptdatenfeld %s fällt auf" % feld)
    if feld == "daten":
        pruefe(meldung == m._("The encrypted file is damaged."),
               "beschädigte Nutzdaten gelten nicht als falsches Kennwort")

migrations_ordner = tempfile.mkdtemp(prefix="magnolie-daten-migration-")
migrations_datei = os.path.join(migrations_ordner, "daten.json")
with open(migrations_datei, "w", encoding="utf-8") as datei:
    datei.write(huelle)

class _MigrationsFenster:
    _erinnerungsprojektion_aktualisieren = m.Fenster._erinnerungsprojektion_aktualisieren
    def __init__(self):
        self._daten_sperre = m.threading.RLock()
        self._baum_sperre = m.threading.RLock()
        self._tray_einstellungen = {}
        self._regional = {}
        self._kennwort = ""
        self._gesperrt = True
        self.antworten = []

    def antwort(self, funktion, nutzlast):
        self.antworten.append((funktion, nutzlast))

    def _baum_dienst_pflegen(self):
        return None

migrations_alt = {
    "daten_datei": m.daten_datei,
    "erinnerungsdaten_datei": m.erinnerungsdaten_datei,
    "baum_ablagen_vorbereiten": m.baum_ablagen_vorbereiten,
    "kennwort_transaktion_ausfuehren": m.kennwort_transaktion_ausfuehren,
}
m.daten_datei = lambda: migrations_datei
m.erinnerungsdaten_datei = lambda: os.path.join(migrations_ordner, "erinnerungsdaten.json")
m.baum_ablagen_vorbereiten = lambda *_args, **_kwargs: {
    "dateien": {}, "baum": None}
def _migration_schreiben(dateien, *_args, **_kwargs):
    m.atomar_text_schreiben(migrations_datei, dateien["daten.json"])

m.kennwort_transaktion_ausfuehren = _migration_schreiben
try:
    migrations_fenster = _MigrationsFenster()
    m.Fenster._entsperren(migrations_fenster, "Rosenholz1896")
    with open(migrations_datei, encoding="utf-8") as datei:
        migrations_huelle = datei.read()
    pruefe(json.loads(migrations_huelle)["fassung"] == 2 and
           m.daten_entschluesseln(
               migrations_huelle, "Rosenholz1896") == klartext and
           migrations_fenster._daten_dek is not None and
           not migrations_fenster._gesperrt,
           "alte Hauptdaten werden erst nach erfolgreichem Entsperren migriert")
finally:
    for migrations_name, migrations_wert in migrations_alt.items():
        setattr(m, migrations_name, migrations_wert)

pruefe(m.ist_verschluesselt('{"termine": []}') is False,
       "gewöhnliche Daten gelten nicht als verschlüsselt")
pruefe(m.ist_verschluesselt("") is False, "leerer Text ebenso wenig")

security_gettext_alt, security_ngettext_alt = m._, m.ngettext
security_en = m.gettext_uebersetzung("en")
m._, m.ngettext = security_en.gettext, security_en.ngettext

class _SecurityFenster:
    _kennwort = ""
    _erinnerungsprojektion_aktualisieren = m.Fenster._erinnerungsprojektion_aktualisieren

    def __init__(self):
        self.antworten = []
        self._daten_sperre = m.threading.RLock()
        self._baum_sperre = m.threading.RLock()

    def antwort(self, funktion, nutzlast):
        self.antworten.append((funktion, nutzlast))

security_fenster = _SecurityFenster()
m.Fenster._kennwort_setzen(security_fenster, "abc", "")
pruefe(security_fenster.antworten[-1] == (
    "App.kennwortStand", {"ok": False,
      "fehler": "Choose at least four characters."}),
    "englischer Backendfehler prüft die Kennwortlänge")

security_ordner = tempfile.mkdtemp(prefix="magnolie-security-en-")
security_datei = os.path.join(security_ordner, "daten.json")
with open(security_datei, "w", encoding="utf-8") as datei:
    datei.write('{"termine": [], "aufgaben": [], "personen": [], '
                '"jahrestage": [], "einstellungen": {}}')
security_alt = {
    "daten_datei": m.daten_datei,
    "speichere_text": m.speichere_text,
    "erinnerungsdaten_schreiben": m.erinnerungsdaten_schreiben,
    "sicherungen_umschluesseln": m.sicherungen_umschluesseln,
    "journal_umschluesseln": m.journal_umschluesseln,
    "baum_ablagen_vorbereiten": m.baum_ablagen_vorbereiten,
    "kennwort_transaktion_ausfuehren": m.kennwort_transaktion_ausfuehren,
    "sperre_schreiben": m.sperre_schreiben,
}
m.daten_datei = lambda: security_datei
m.speichere_text = lambda _text: True
m.erinnerungsdaten_schreiben = lambda *args, **kwargs: True
m.sicherungen_umschluesseln = lambda *_args, **_kwargs: {
    "geschafft": 1, "misslungen": 2}
m.journal_umschluesseln = lambda *_args, **_kwargs: {
    "geschafft": 3, "misslungen": 4}
m.baum_ablagen_vorbereiten = lambda *_args, **_kwargs: {
    "dateien": {}, "baum": None}
m.kennwort_transaktion_ausfuehren = lambda *_args, **_kwargs: True
m.sperre_schreiben = lambda _zustand: True
security_fenster.antworten.clear()
m.Fenster._kennwort_setzen(security_fenster, "Magnolie 1896", "")
security_antwort = security_fenster.antworten[-1]
pruefe(security_antwort[0] == "App.kennwortStand" and
       security_antwort[1]["ok"] and security_antwort[1]["an"] and
       security_antwort[1]["sicherungen"] == 1 and
       security_antwort[1]["sicherungenFehler"] == 2 and
       security_antwort[1]["journal"] == 3 and
       security_antwort[1]["journalFehler"] == 4,
       "Umschlüsselungsbericht reicht Erfolge und Fehler an die Oberfläche")

security_fenster._kennwort = ""
with open(security_datei, "w", encoding="utf-8") as datei:
    datei.write(huelle)
security_fenster.antworten.clear()
m.Fenster._kennwort_entfernen(security_fenster)
pruefe(security_fenster.antworten[-1][1]["fehler"] ==
       "The data is encrypted. Unlock the organizer with the password first.",
       "englischer Entfernungsfehler kommt aus gettext")
for security_name, security_wert in security_alt.items():
    setattr(m, security_name, security_wert)
m._, m.ngettext = security_gettext_alt, security_ngettext_alt

print()
print("— Erinnerungen trotz Kennwortschutz —")

erinner_daten = {
    "termine": [
        {"id": "offen", "uid": "termin-uid", "datum": "2026-08-19",
         "endDatum": "2026-08-19", "zeit": "09:30", "endZeit": "10:00",
         "titel": "Zahnarzt",
         "individuelleErinnerungTage": 2, "standardErinnerung": False,
         "alarme": [{"offsetMinuten": 60, "aktiviert": True,
                      "related": "END", "aktion": "display",
                      "id": "alarm-geheim", "triggerRaw": "Alarmgeheimnis"},
                     {"offsetMinuten": 30, "aktiviert": True,
                      "related": "START", "aktion": {"token": "Alarmtoken"}}],
         "wiederholung": {"art": "monthly", "bis": "2027-08-19",
                            "ordinal": 3, "wochentag": "WE",
                            "intervall": 1, "daten": [],
                            "notiz": "Wiederholungsgeheimnis"},
         "vertraulich": False, "notiz": "Terminnotiz", "personen": ["p"],
         "links": ["https://example.invalid"], "lotusUid": "lotus-termin",
         "syncMetadaten": {"etag": "termin-etag"}},
        {"id": "geheim", "titel": "Beratung", "vertraulich": True},
    ],
    "aufgaben": [
        {"id": "a", "uid": "aufgabe-uid", "titel": "Brief abgeben",
         "faellig": "2026-08-20", "erledigt": False, "erinnern": True,
         "startDatum": "2026-08-19", "startZeit": "09:00", "faelligZeit": "10:00",
         "individuelleErinnerungTage": 1, "vertraulich": False,
         "notiz": "Aufgabennotiz", "personen": ["p"], "delegiertAn": "p",
         "links": ["https://example.invalid"], "lotusId": "lotus-aufgabe",
         "davEtag": "aufgabe-etag"},
        {"id": "a-geheim", "titel": "Geheime Aufgabe", "vertraulich": True},
    ],
    "personen": [{"id": "p", "name": "Max"}],
    "jahrestage": [
        {"id": "j", "uid": "jahrestag-uid", "name": "Anna", "typ": "Birthday",
         "datum": "1980-08-21", "vertraulich": False,
         "notiz": "Jahrestagsnotiz", "personId": "p",
         "link": "https://example.invalid", "lotusFeld": "lotus-jahrestag",
         "sync": True},
        {"id": "j-geheim", "name": "Geheimer Jahrestag",
         "vertraulich": True},
    ],
    "kontakte": [{"nachname": "Darf nicht hinein"}],
    "notizen": [{"text": "Darf ebenfalls nicht hinein"}],
    "notizbuchseiten": [{"titel": "Auch nicht"}],
    "syncMetadaten": {"token": "bestand-token"},
    "customOrganizer": {"version": 3, "modules": [
        {"id": "modul-t", "type": "appointments", "title": "Privat",
         "reminders": True, "items": [
             {"id": "offen", "title": "Abholen", "date": "2026-08-19",
               "time": "11:00", "remind": True,
               "wiederholung": {"art": "yearly", "bis": "",
                                  "notiz": "Customgeheimnis"}}]},
        {"id": "modul-a", "type": "tasks", "title": "Werkstatt",
         "reminders": True, "items": [
             {"id": "a", "title": "Prüfen", "due": "2026-08-20",
              "time": "12:00", "done": False, "remind": True}]},
    ]},
    "einstellungen": {
        "erinnerung": {
            "an": True, "vorlauf": 15, "verpasste": True,
            "aufgaben": True, "art": "both", "stil": "system",
            "jahrestage": {"an": True, "tage": 2, "amTag": True,
                            "stunde": 8, "notiz": "Einstellungsgeheimnis"},
            "protokoll": True, "protokollVoreinstellung": False,
            "notiz": "Nicht für den Wecker"},
        "sicherheit": {
            "erinnernTrotzKennwort": True,
            "vertraulicheErinnerungen": False,
        },
    },
}
auswahl = m.erinnerungsdaten_auswaehlen(erinner_daten)
pruefe([t["id"] for t in auswahl["termine"]] ==
       ["offen", "custom:modul-t:offen"],
       "vertrauliche Termine bleiben ohne zweite Zustimmung draußen")
pruefe(auswahl["termine"][1]["wiederholung"] == {"art": "yearly", "bis": ""},
       "eigene Serientermine behalten ihre gefilterte Wiederholung im Weckerbestand")
viele_custom_termine, _ = m._custom_erinnerungseintraege({
    "customOrganizer": {"modules": [{"id": "viele", "type": "appointments",
        "reminders": True, "items": [{"id": str(index), "title": "Termin",
                                        "date": "2026-08-19"}
                                       for index in range(150)]}]}})
pruefe(len(viele_custom_termine) == 150 and
       viele_custom_termine[-1]["id"] == "custom:viele:149",
       "alle 150 eigenen Termine gelangen in den Weckerbestand")
pruefe(m._custom_erinnerungseintraege({"customOrganizer": {"modules": [
    {"id": "kaputt", "type": "appointments", "reminders": True,
     "items": {"kein": "array"}}]}}) == ([], []),
       "unförmige eigene Einträge bringen den Weckerbestand nicht zum Absturz")
pruefe([a["id"] for a in auswahl["aufgaben"]] ==
       ["a", "custom:modul-a:a"] and
       [j["id"] for j in auswahl["jahrestage"]] == ["j"],
       "eigene Aufgaben werden getrennt projiziert und Vertrauliches bleibt draußen")
pruefe(set(auswahl) == {"version", "nurErinnerungen", "termine", "aufgaben",
                        "jahrestage", "einstellungen"},
       "Personen, Kontaktkarten, Notizbuchseiten und Sync-Metadaten fehlen oben")
pruefe(set(auswahl["termine"][0]) == set(m.ERINNERUNG_TERMIN_FELDER) |
       {"alarme", "wiederholung"} and
       set(auswahl["termine"][0]["alarme"][0]) ==
       set(m.ERINNERUNG_ALARM_FELDER) and
       set(auswahl["termine"][0]["wiederholung"]) ==
       set(m.ERINNERUNG_WIEDERHOLUNG_FELDER),
       "Termine und Alarme enthalten ausschließlich erlaubte Erinnerungsfelder")
pruefe(set(auswahl["aufgaben"][0]) == set(m.ERINNERUNG_AUFGABE_FELDER) and
       set(auswahl["jahrestage"][0]) == set(m.ERINNERUNG_JAHRESTAG_FELDER),
       "Aufgaben und Jahrestage enthalten ausschließlich ihre Whitelists")
pruefe(auswahl["jahrestage"][0]["typ"] == "Birthday",
       "der begrenzte Bestand bewahrt die Bedeutung eines Jahrestags")
pruefe(set(auswahl["einstellungen"]["erinnerung"]) ==
       set(m.ERINNERUNG_EINSTELLUNG_FELDER) | {"jahrestage"} and
       set(auswahl["einstellungen"]["erinnerung"]["jahrestage"]) ==
       set(m.ERINNERUNG_JAHRESTAG_EINSTELLUNG_FELDER),
       "Erinnerungseinstellungen enthalten ausschließlich erlaubte Felder")
verbotene_werte = {"Terminnotiz", "Wiederholungsgeheimnis", "Aufgabennotiz",
                   "Alarmgeheimnis", "Alarmtoken", "alarm-geheim", "Jahrestagsnotiz",
                   "Einstellungsgeheimnis", "bestand-token",
                   "termin-etag", "aufgabe-etag", "lotus-termin",
                   "lotus-aufgabe", "lotus-jahrestag",
                   "https://example.invalid", "Max", "Customgeheimnis"}
auswahl_text = _json.dumps(auswahl, ensure_ascii=False)
pruefe(not any(wert in auswahl_text for wert in verbotene_werte),
       "Notizen, Lotus-Felder, Links, Zuordnungen und Sync-Daten werden verworfen")

erinner_daten["einstellungen"]["sicherheit"]["vertraulicheErinnerungen"] = True
auswahl = m.erinnerungsdaten_auswaehlen(erinner_daten)
pruefe({t["id"] for t in auswahl["termine"]} ==
       {"offen", "geheim", "custom:modul-t:offen"},
       "die zweite Zustimmung nimmt vertrauliche Termine ausdrücklich auf")
pruefe({a["id"] for a in auswahl["aufgaben"]} ==
       {"a", "a-geheim", "custom:modul-a:a"} and
       {j["id"] for j in auswahl["jahrestage"]} == {"j", "j-geheim"} and
       all("vertraulich" not in eintrag for gruppe in
           (auswahl["termine"], auswahl["aufgaben"], auswahl["jahrestage"])
           for eintrag in gruppe),
       "zweite Zustimmung gilt für alle Typen, ohne das Filterfeld offenzulegen")

erinner_pfad = os.path.join(
    tempfile.mkdtemp(prefix="magnolie-erinnerungsdaten-"), "erinnerungsdaten.json")
erinner_profil = os.path.join(os.path.dirname(erinner_pfad), "daten.json")
m.atomar_text_schreiben(erinner_profil, m.daten_huelle_anlegen(
    _json.dumps(erinner_daten), "synthetic-reminder-password")[0])
pruefe(m.erinnerungsdaten_schreiben(erinner_daten, erinner_pfad,
        profil_pfad=erinner_profil, kennwort="synthetic-reminder-password"),
       "der begrenzte Erinnerungsbestand wird geschrieben")
pruefe((os.stat(erinner_pfad).st_mode & 0o777) == 0o600,
       "nur das eigene Benutzerkonto darf ihn lesen")
pruefe(m.erinnerungsdaten_lesen(erinner_pfad, profil_pfad=erinner_profil)["nurErinnerungen"] is True,
       "der Wecker erkennt den begrenzten Bestand")
erinner_daten["einstellungen"]["sicherheit"]["erinnernTrotzKennwort"] = False
m.atomar_text_schreiben(erinner_profil, m.daten_huelle_anlegen(
    _json.dumps(erinner_daten), "synthetic-reminder-password")[0])
pruefe(m.erinnerungsdaten_schreiben(erinner_daten, erinner_pfad,
        profil_pfad=erinner_profil, kennwort="synthetic-reminder-password") and
       not os.path.exists(erinner_pfad),
       "das Abschalten entfernt die unverschlüsselte Erinnerungsdatei")

# Große Datenmenge – der Vater-Bestand soll zügig auf- und zugehen
gross = _json.dumps({"termine": [{"id": "t%d" % i, "titel": "Termin %d" % i}
                                for i in range(30000)]})
beginn = _zeit.perf_counter()
grosse_huelle = m.verschluesseln(gross, "Rosenholz1896")
dauer_zu = _zeit.perf_counter() - beginn
beginn = _zeit.perf_counter()
zurueck = m.entschluesseln(grosse_huelle, "Rosenholz1896")
dauer_auf = _zeit.perf_counter() - beginn
pruefe(zurueck == gross, "auch 30.000 Termine überstehen den Rundlauf")
pruefe(dauer_zu < 3.0 and dauer_auf < 3.0,
       "und zwar zügig (%.2f s zu, %.2f s auf)" % (dauer_zu, dauer_auf))

print()
print("— Verschlüsselte Daten sind vor Überschreiben geschützt —")


class _FensterAttrappe:
    """Nur die beiden Methoden, auf die es hier ankommt."""
    _kennwort = ""

    def __init__(self, pfad):
        self._pfad = pfad

    _darf_schreiben = m.Fenster._darf_schreiben


schutzordner = tempfile.mkdtemp(prefix="magnolie-schutz-")
schutzdatei = os.path.join(schutzordner, "daten.json")
with open(schutzdatei, "w", encoding="utf-8") as datei:
    datei.write(m.verschluesseln(gross, "Rosenholz1896"))
with open(schutzdatei, encoding="utf-8") as datei:
    anfang = datei.read(400)
pruefe(m.sieht_verschluesselt_aus(anfang),
       "schon die ersten Zeichen verraten die Verschlüsselung")
alt_daten_datei = m.daten_datei
m.daten_datei = lambda: schutzdatei
try:
    pruefe(_FensterAttrappe(schutzdatei)._darf_schreiben() is False,
           "die echte Schreibsperre schützt eine große verschlüsselte Datei")
finally:
    m.daten_datei = alt_daten_datei
with open(schutzdatei, "w", encoding="utf-8") as datei:
    datei.write('{"termine": []}')
with open(schutzdatei, encoding="utf-8") as datei:
    pruefe(m.ist_verschluesselt(datei.read(400)) is False,
           "unverschlüsselte Daten werden nicht verwechselt")

print()
print("— Kennwortschutz entfernen —")

entfernordner = tempfile.mkdtemp(prefix="magnolie-entfern-")
entferndatei = os.path.join(entfernordner, "daten.json")
klar_probe = '{"termine": [{"titel": "Bleibt erhalten"}]}'

with open(entferndatei, "w", encoding="utf-8") as datei:
    datei.write(m.verschluesseln(klar_probe, "4711"))
with open(entferndatei, encoding="utf-8") as datei:
    pruefe(m.ist_verschluesselt(datei.read()), "zunächst ist verschlüsselt")

# So arbeitet das Entfernen: entschlüsseln und offen zurückschreiben
with open(entferndatei, encoding="utf-8") as datei:
    zurueck = m.entschluesseln(datei.read(), "4711")
with open(entferndatei, "w", encoding="utf-8") as datei:
    datei.write(zurueck)
with open(entferndatei, encoding="utf-8") as datei:
    inhalt = datei.read()
pruefe(m.ist_verschluesselt(inhalt) is False,
       "danach liegt die Datei offen da")
pruefe("Bleibt erhalten" in inhalt, "und der Inhalt ist unversehrt")
pruefe(m.ist_verschluesselt(inhalt[:400]) is False,
       "auch der Anfang verrät keine Verschlüsselung mehr – "
       "so erkennt es der Organizer beim nächsten Start")

print()
print("— Sperre nach Fehlversuchen —")

sperrprobe = os.path.join(tempfile.mkdtemp(prefix="magnolie-sperre-"), "s.json")
leer_z = m.sperre_lesen(sperrprobe)
pruefe(leer_z == {"versuche": 0, "bis": ""}, "ohne Datei ist nichts gesperrt")
pruefe(m.sperre_pruefen(leer_z, _dt(2026, 7, 27, 10, 0))[0] is True,
       "und es darf versucht werden")

z = leer_z
z = m.sperre_fehlversuch(z, _dt(2026, 7, 27, 10, 0))
pruefe(z["versuche"] == 1 and not z["bis"], "erster Fehlversuch sperrt nicht")
z = m.sperre_fehlversuch(z, _dt(2026, 7, 27, 10, 0))
pruefe(z["versuche"] == 2 and not z["bis"], "zweiter auch nicht")
z = m.sperre_fehlversuch(z, _dt(2026, 7, 27, 10, 0))
pruefe(bool(z["bis"]), "der dritte sperrt")
erlaubt, sekunden = m.sperre_pruefen(z, _dt(2026, 7, 27, 10, 1))
pruefe(erlaubt is False and 230 < sekunden <= 241,
       "gesperrt für rund vier Minuten Rest (%d s)" % sekunden)
pruefe(m.sperre_pruefen(z, _dt(2026, 7, 27, 10, 6))[0] is True,
       "nach fünf Minuten geht es weiter")
pruefe(m.sperre_schreiben(z, sperrprobe) and
       m.sperre_lesen(sperrprobe)["bis"] == z["bis"],
       "die Sperre übersteht einen Neustart des Programms")
pruefe((os.stat(sperrprobe).st_mode & 0o777) == 0o600,
       "der Sperrzustand bleibt privat")
pruefe(m.sperre_zuruecksetzen() == {"versuche": 0, "bis": ""},
       "nach richtigem Kennwort ist alles zurückgesetzt")

print()
print("— Sicherungen mitverschlüsseln —")
sicherordner = tempfile.mkdtemp(prefix="magnolie-sicher-")
for name in ("sicherung-20260101-120000.json", "sicherung-20260202-130000.json"):
    with open(os.path.join(sicherordner, name), "w", encoding="utf-8") as datei:
        datei.write('{"termine": [{"titel": "Alte Sicherung"}]}')
with open(os.path.join(sicherordner, "daten.json"), "w", encoding="utf-8") as datei:
    datei.write("{}")
erg = m.sicherungen_umschluesseln("Rosenholz1896", None, sicherordner)
pruefe(erg["geschafft"] == 2 and erg["misslungen"] == 0,
       "beide Sicherungen wurden verschlüsselt")
pruefe(all((os.stat(os.path.join(sicherordner, name)).st_mode & 0o777) == 0o600
           for name in ("sicherung-20260101-120000.json",
                        "sicherung-20260202-130000.json")) and
       not any(name.endswith(".neu") or name.startswith(".magnolie-")
               for name in os.listdir(sicherordner)),
       "umgeschlüsselte Sicherungen sind sofort privat und atomar ersetzt")
with open(os.path.join(sicherordner, "sicherung-20260101-120000.json"),
          encoding="utf-8") as datei:
    inhalt = datei.read()
pruefe(m.ist_verschluesselt(inhalt) and "Alte Sicherung" not in inhalt,
       "und enthalten keinen Klartext mehr")
erg = m.sicherungen_umschluesseln("NeuesProgrammkennwort",
                                  "Rosenholz1896", sicherordner)
with open(os.path.join(sicherordner, "sicherung-20260101-120000.json"),
          encoding="utf-8") as datei:
    unveraendert = datei.read()
pruefe(erg["geschafft"] == 0 and
       "Alte Sicherung" in m.entschluesseln(unveraendert, "Rosenholz1896"),
       "das vergebene externe Sicherungskennwort bleibt eigenständig")
with open(os.path.join(sicherordner, "daten.json"), encoding="utf-8") as datei:
    pruefe(datei.read() == "{}", "die Datendatei selbst bleibt unberührt")
erg = m.sicherungen_umschluesseln("", "Rosenholz1896", sicherordner)
pruefe(erg["geschafft"] == 0,
       "externe Sicherungen werden beim Abschalten nicht freigegeben")
with open(os.path.join(sicherordner, "sicherung-20260101-120000.json"),
          encoding="utf-8") as datei:
    pruefe(m.ist_verschluesselt(datei.read()),
           "außerhalb des Datenstandorts bleibt kein Klartext zurück")

backup_probe = tempfile.mkdtemp(prefix="magnolie-backup-probe-")
quelle_probe = os.path.join(backup_probe, "daten.json")
with open(quelle_probe, "w", encoding="utf-8") as datei:
    datei.write('{"notizen": [{"titel": "Sicher"}]}')
daten_datei_alt = m.daten_datei
m.daten_datei = lambda: quelle_probe
eigener_ordner = os.path.join(backup_probe, "Mein Sicherungsordner")
try:
    m.lege_sicherung_an(eigener_ordner)
    ohne_kennwort_abgewiesen = False
except RuntimeError as sicherungsfehler:
    ohne_kennwort_abgewiesen = "mindestens vier Zeichen" in str(sicherungsfehler)
pruefe(ohne_kennwort_abgewiesen,
       "eine externe Sicherung ohne Kennwort wird abgewiesen")
backup_ziel = m.lege_sicherung_an(eigener_ordner, kennwort="Sicher1896")
backup_max_alt = m.SICHERUNG_DATEI_MAX
m.SICHERUNG_DATEI_MAX = 64
try:
    m.lege_sicherung_an(eigener_ordner, kennwort="Sicher1896")
    huelle_zu_gross = False
except m.GroessenFehler:
    huelle_zu_gross = True
finally:
    m.SICHERUNG_DATEI_MAX = backup_max_alt
m.daten_datei = daten_datei_alt
pruefe(huelle_zu_gross,
       "Verschlüsselungsaufblähung kann keine unlesbar große Sicherung erzeugen")
pruefe(backup_ziel and os.path.dirname(backup_ziel) == eigener_ordner and
       os.path.isfile(backup_ziel) and
       (os.stat(backup_ziel).st_mode & 0o777) == 0o600 and
       not any(name.endswith(".neu") or name.startswith(".magnolie-")
               for name in os.listdir(eigener_ordner)),
       "Sicherung wird privat und atomar im frei gewählten Ordner angelegt")
pruefe(m.sicherung_lesen(backup_ziel)["brauchtKennwort"],
       "die externe Sicherung verlangt ihr Kennwort")
pruefe(m.sicherung_lesen(os.path.join(backup_probe, "fehlt.json"))["fehler"] ==
       "Die Sicherungsdatei wurde nicht gefunden.",
       "fehlende Sicherungen melden sich über den deutschen Katalog")
backup_zu_gross = os.path.join(backup_probe, "sicherung-zu-gross.json")
with open(backup_zu_gross, "wb") as datei:
    datei.write(b'{"verschluesselt":true}')
    datei.truncate(m.SICHERUNG_DATEI_MAX + 1)
gelesen_zu_gross = m.sicherung_lesen(backup_zu_gross)
pruefe(not gelesen_zu_gross["ok"] and
       "256 Megabyte" in gelesen_zu_gross["fehler"],
       "zu große verschlüsselt markierte Sicherung wird vor Entschlüsselung abgewiesen")
backup_verweis = os.path.join(backup_probe, "sicherung-verweis.json")
os.symlink(backup_ziel, backup_verweis)
pruefe(not m.sicherung_lesen(backup_verweis)["ok"],
       "symbolischer Verweis wird nicht als Sicherung geöffnet")
gelesen = m.sicherung_lesen(backup_ziel, "Sicher1896")
pruefe(gelesen["ok"] and
       gelesen["daten"]["notizen"][0]["titel"] == "Sicher",
       "nur das bei der Sicherung vergebene Kennwort öffnet die Kopie")
verschluesselte_probe = os.path.join(backup_probe, "verschluesselt.json")
with open(verschluesselte_probe, "w", encoding="utf-8") as datei:
    datei.write(m.verschluesseln('{"notizen":[{"titel":"Geheim"}]}',
                                "Magnolie1896"))
pruefe(m.sicherung_lesen(verschluesselte_probe)["brauchtKennwort"],
       "eine verschlüsselte Sicherung fordert ihr Kennwort an")
pruefe(not m.sicherung_lesen(verschluesselte_probe, "falsch")["ok"],
       "ein falsches Sicherungskennwort verändert nichts")
pruefe(m.sicherung_lesen(
       verschluesselte_probe, "Magnolie1896")["daten"]["notizen"][0]["titel"]
       == "Geheim",
       "eine verschlüsselte Sicherung wird mit richtigem Kennwort gelesen")

aktuelle_datei = os.path.join(backup_probe, "aktuell.json")
with open(aktuelle_datei, "w", encoding="utf-8") as datei:
    datei.write('{"notizen":[{"titel":"Vorher"}]}')
antworten = []
fenster_attrappe = type("FensterAttrappe", (), {})()
fenster_attrappe._erinnerungsprojektion_aktualisieren = m.Fenster._erinnerungsprojektion_aktualisieren.__get__(fenster_attrappe)
fenster_attrappe._kennwort = ""
fenster_attrappe._daten_sperre = m.threading.RLock()
fenster_attrappe._baum_sperre = m.threading.RLock()
fenster_attrappe.antwort = lambda funktion, nutzlast: antworten.append(
    (funktion, nutzlast))
daten_datei_alt = m.daten_datei
erinnerungsdaten_datei_alt = m.erinnerungsdaten_datei
baum_vorbereiten_alt = m.baum_ablagen_vorbereiten
kennwort_transaktion_alt = m.kennwort_transaktion_ausfuehren
m.daten_datei = lambda: aktuelle_datei
m.erinnerungsdaten_datei = lambda: os.path.join(backup_probe, "erinnerungsdaten.json")
m.baum_ablagen_vorbereiten = lambda *_args, **_kwargs: {
    "dateien": {}, "baum": None}
def _wiederherstellungs_transaktion(dateien, *_args, **_kwargs):
    m.atomar_text_schreiben(aktuelle_datei, dateien["daten.json"])
    return True

m.kennwort_transaktion_ausfuehren = _wiederherstellungs_transaktion
m.Fenster._sicherung_wiederherstellen(
    fenster_attrappe, verschluesselte_probe, "Magnolie1896", eigener_ordner)
m.daten_datei = daten_datei_alt
m.erinnerungsdaten_datei = erinnerungsdaten_datei_alt
m.baum_ablagen_vorbereiten = baum_vorbereiten_alt
m.kennwort_transaktion_ausfuehren = kennwort_transaktion_alt
with open(aktuelle_datei, encoding="utf-8") as datei:
    wiederhergestellt = datei.read()
pruefe(m.ist_verschluesselt(wiederhergestellt) and
       json.loads(m.entschluesseln(
           wiederhergestellt, "Magnolie1896"))["notizen"][0]["titel"]
       == "Geheim",
       "die Wiederherstellung ersetzt den Bestand und behält den Schutz")
pruefe(any(name.startswith("sicherung-vor-wiederherstellung-")
           for name in os.listdir(eigener_ordner)),
       "vor der Wiederherstellung wird der aktuelle Bestand gesichert")
pruefe(antworten[-1][0] == "App.sicherungWiederhergestellt" and
       antworten[-1][1]["ok"],
       "die Oberfläche erhält den wiederhergestellten Bestand")

print()
print("— Anschriften weiterverwenden —")

kontakt_probe = {"vorname": "Hans", "nachname": "Müller", "firma": "Müller GmbH",
                 "strasse": "Hauptstraße 12", "plz": "47051", "ort": "Duisburg",
                 "telefon": "0203 123456", "email": "h.mueller@example.de"}

pruefe(m.anschrift_zeilen(kontakt_probe) ==
       ["Hans Müller", "Müller GmbH", "Hauptstraße 12", "47051 Duisburg"],
       "die Anschrift steht in der richtigen Reihenfolge")
pruefe(m.anschrift_zeilen({}) == [], "eine leere Karteikarte gibt nichts her")

brief = m.fodt_brief(
    kontakt_probe, "Erika Beispiel\nMusterweg 3\n47051 Duisburg",
    layout="din5008")
pruefe(brief.startswith("<?xml") and "office:document" in brief,
       "der Brief ist eine gültige ODF-Datei")
pruefe("Hauptstraße 12" in brief and "Hans Müller" in brief,
       "die Anschrift steht im Brief")
pruefe('draw:name="Anschriftfeld"' in brief and 'svg:y="4.5cm"' in brief and
       'svg:width="8.5cm"' in brief,
       "das Anschriftfeld sitzt passend für einen Fensterumschlag")
pruefe('draw:name="Absenderblock"' in brief and
       brief.count('text:style-name="Absender"') == 3 and
       brief.count('text:style-name="Rueckadresse"') == 1,
       "Form B hat einen mehrzeiligen Absenderkopf und eine Ruecksendezeile")
pruefe(all(name in brief for name in
           ("Faltmarke-oben", "Lochmarke", "Faltmarke-unten")) and
       'svg:y1="10.5cm"' in brief and 'svg:y1="21cm"' in brief and
       'svg:x1="1.5cm"' in brief,
       "DIN-Falt- und Lochmarken liegen innerhalb des Druckbereichs")
pruefe("Sehr geehrte Damen und Herren," in brief and
       "Mit freundlichen Grüßen" in brief, "Anrede und Gruß sind vorbereitet")
ohne = m.fodt_brief(kontakt_probe, "", layout="din5008")
pruefe('text:style-name="Rueckadresse"></text:p>' in ohne and "Musterweg" not in ohne,
       "ohne eigene Anschrift bleibt die Ruecksendezeile leer")
pruefe("&amp;" in m.fodt_brief({"nachname": "Meier & Sohn"}, ""),
       "Sonderzeichen werden sauber verpackt")
kompakt = m.fodt_brief(
    kontakt_probe, "Erika Beispiel\nMusterweg 3\n47051 Duisburg",
    layout="kompakt")
pruefe("Erika Beispiel · Musterweg 3 · 47051 Duisburg" in kompakt and
       "Faltmarke-oben" not in kompakt,
       "die kompakte Absenderzeile ist wählbar")
standard = m.fodt_brief(
    kontakt_probe, "Erika Beispiel\nMusterweg 3\n47051 Duisburg")
pruefe("Erika Beispiel · Musterweg 3 · 47051 Duisburg" in standard and
       "Faltmarke-oben" in standard and 'svg:y="4.5cm"' in standard,
       "Form B mit linker Ruecksendezeile ist Standard")

adressen_gettext_alt, adressen_ngettext_alt = m._, m.ngettext
adressen_regional_alt = dict(m._REGIONAL)
adressen_en = m.gettext_uebersetzung("en")
m._, m.ngettext = adressen_en.gettext, adressen_en.ngettext
m._REGIONAL["formatLocale"] = "en-US"
brief_en = m.fodt_brief(
    kontakt_probe, "Erika Beispiel\nMusterweg 3\n47051 Duisburg",
    datum=_dt(2026, 7, 25), layout="din5008")
pruefe("Dear Sir or Madam," in brief_en and "Yours sincerely," in brief_en and
       "7/25/2026" in brief_en,
       "englischer Brief verwendet gettext und das gewählte Formatgebiet")
pruefe("Hauptstraße 12" in brief_en and "Hans Müller" in brief_en and
       'draw:name="Anschriftfeld"' in brief_en and "Faltmarke-oben" in brief_en,
       "englischer Brief bewahrt Anschrift und ODF-Struktur")
pruefe(m.brief_oeffnen({}, "")["fehler"] ==
       "This contact card has no postal address.",
       "englischer Briefadressfehler fehlt")
pruefe("Tools ▸ Options ▸ User Data" in
       m.libreoffice_benutzerdaten("/does/not/exist")["fehler"],
       "englischer LibreOffice-Hinweis fehlt")
pruefe(m.mail_oeffnen("not-an-address")["fehler"] ==
       "This contact card has no email address.",
       "englischer E-Post-Fehler fehlt")
pruefe(m.sozial_oeffnen("mastodon", "name")["fehler"] ==
       "Enter the complete Mastodon address @name@server or an HTTPS address.",
       "englischer Kommunikationsfehler bewahrt Mastodon-Syntax")
pruefe(m.sozial_oeffnen("telefon", "123")["fehler"] ==
       "Enter a complete phone number.",
       "englischer Rufnummernfehler fehlt")
welcher_alt = m.shutil.which
m.shutil.which = lambda _name: None
karten_fehler_en = m.karte_oeffnen(kontakt_probe)["fehler"]
m.shutil.which = welcher_alt
pruefe("sudo apt install gnome-maps" in karten_fehler_en and
       karten_fehler_en.startswith("No map service was found."),
       "englischer Kartenfehler bewahrt den Paketbefehl")
m._, m.ngettext = adressen_gettext_alt, adressen_ngettext_alt
m._REGIONAL.clear()
m._REGIONAL.update(adressen_regional_alt)

gerufene = []
erg = m.brief_oeffnen(kontakt_probe, "", lambda a: gerufene.append(a))
pruefe(erg["ok"] and erg["pfad"].endswith(".fodt"), "der Brief wird abgelegt")
pruefe(os.stat(os.path.dirname(erg["pfad"])).st_mode & 0o777 == 0o700 and
       os.stat(erg["pfad"]).st_mode & 0o777 == 0o600,
       "temporärer Brief liegt mit privaten Rechten")
pruefe(bool(gerufene) and gerufene[0][-1] == erg["pfad"],
       "und an das Schreibprogramm übergeben")
pruefe(m.brief_oeffnen({}, "")["ok"] is False,
       "ohne Anschrift wird kein Brief geschrieben")

pruefe(m.karten_adresse(kontakt_probe) ==
       "Hauptstraße 12, 47051 Duisburg, Deutschland",
       "die Kartenanfrage nennt auch das Land: %s"
       % m.karten_adresse(kontakt_probe))
pruefe(m.karten_adresse(kontakt_probe, "Österreich").endswith("Österreich"),
       "ein anderes Land lässt sich einstellen")
pruefe(m.karten_adresse({"ort": "Wien, Österreich"}, "Österreich")
       == "Wien, Österreich", "das Land wird nicht doppelt angehängt")
pruefe(m.karten_adresse({}, "Deutschland") == "",
       "ohne Anschrift bleibt die Anfrage leer")
wege = m.karten_wege("Hauptstraße 12, 47051 Duisburg", "auto")
pruefe(wege[0][0] == "gnome-maps" and wege[0][1][1].startswith("maps:q="),
       "zuerst wird Gnome-Karten mit der Suchadresse versucht: %r"
       % wege[0][1][1][:20])
pruefe(any(w[1][1].startswith("geo:") for w in wege),
       "die geo-Adresse bleibt als letzter Versuch erhalten")
pruefe(any(w[1][1] == "Hauptstraße 12, 47051 Duisburg" for w in wege),
       "auch die schlichte Anschrift wird versucht")
pruefe(any(w[0] == "openstreetmap" for w in wege),
       "ersatzweise OpenStreetMap")
pruefe(all(w[0] == "google" for w in m.karten_wege("x", "google")),
       "bei Google-Wahl nur Google")
pruefe("%C3%9F" in m.karten_wege("Straße", "openstreetmap")[0][1][1],
       "Umlaute werden für die Adresszeile verpackt")

gerufene = []
erg = m.karte_oeffnen(kontakt_probe, "openstreetmap", lambda a: gerufene.append(a))
pruefe(erg["ok"] and erg["womit"] == "openstreetmap", "die Karte wird geöffnet")
pruefe(m.karte_oeffnen({}, "auto")["ok"] is False,
       "ohne Anschrift keine Karte")

# Route: nicht nur zeigen, sondern hinführen
routen = m.karten_wege("Hauptstraße 12, 47051 Duisburg, Deutschland",
                       "auto", True)
pruefe(any(w[0] == "gnome-maps" and "daddr=" in w[1][1] for w in routen),
       "Gnome-Karten bekommt ein Routenziel")
pruefe(any("openstreetmap.org/directions?to=" in w[1][1] for w in routen),
       "OpenStreetMap berechnet den Weg")
googlerouten = m.karten_wege("Hauptstraße 12", "google", True)
pruefe(all("maps/dir/" in w[1][1] for w in googlerouten),
       "Google Maps wird zur Wegbeschreibung aufgerufen")
pruefe(all("directions" not in w[1][1] and "daddr" not in w[1][1]
           for w in m.karten_wege("Hauptstraße 12", "auto", False)),
       "ohne Haken wird nur der Ort gezeigt")

gerufene = []
erg = m.karte_oeffnen(kontakt_probe, "openstreetmap",
                      lambda a: gerufene.append(a), route=True)
pruefe(erg["ok"] and any("directions" in " ".join(a) for a in gerufene),
       "die Route wird geöffnet: %r" % (gerufene[-1] if gerufene else None))

# Ohne Ausgangspunkt rechnet kein Dienst – die eigene Anschrift muss mit
eigene = "Erika Beispiel\nBeispiel & Söhne\nMusterweg 3\n47051 Duisburg"
pruefe(m.eigene_route_adresse(eigene) ==
       "Musterweg 3, 47051 Duisburg, Deutschland",
       "aus der eigenen Anschrift wird eine Kartenzeile ohne Namen: %r"
       % m.eigene_route_adresse(eigene))
pruefe(m.eigene_route_adresse("") == "",
       "ohne Angabe bleibt der Ausgangspunkt leer")
pruefe(m.eigene_route_adresse("Nur ein Name") == "",
       "eine Zeile ohne Hausnummer taugt nicht als Ausgangspunkt")
pruefe(m.eigene_route_adresse(eigene, "Österreich").endswith("Österreich"),
       "das Land wird angehängt")

wege_mit = m.karten_wege("Ziel 1, 40210 Düsseldorf", "openstreetmap", True,
                         "Musterweg 3, 47051 Duisburg")
pruefe("from=Musterweg" in wege_mit[0][1][1] and "&to=Ziel" in wege_mit[0][1][1],
       "OpenStreetMap bekommt Start und Ziel: %s" % wege_mit[0][1][1][:80])
wege_google = m.karten_wege("Ziel 1", "google", True, "Start 2")
pruefe("origin=Start" in wege_google[0][1][1],
       "Google Maps bekommt den Ausgangspunkt")
wege_gnome = m.karten_wege("Ziel 1", "gnome-maps", True, "Start 2")
pruefe("saddr=" in wege_gnome[0][1][1] and "daddr=" in wege_gnome[0][1][1],
       "Gnome-Karten bekommt Start und Ziel: %s" % wege_gnome[0][1][1])
wege_ohne = m.karten_wege("Ziel 1", "openstreetmap", True, "")
pruefe("from=" not in wege_ohne[0][1][1],
       "ohne eigene Anschrift wird kein leerer Start angehängt")

gerufene = []
m.karte_oeffnen(kontakt_probe, "openstreetmap",
                lambda a: gerufene.append(a), route=True, absender=eigene)
pruefe(any("from=Musterweg" in " ".join(a) for a in gerufene),
       "die eigene Anschrift landet in der Anfrage")

gerufene = []
erg = m.mail_oeffnen("h.mueller@example.de", "Rückfrage",
                     lambda a: gerufene.append(a), "Hans Müller")
pruefe(erg["ok"], "das Postprogramm wird geöffnet")
pruefe(any("mailto:Hans%20M%C3%BCller%20%3Ch.mueller@example.de%3E" in " ".join(a)
           for a in gerufene),
       "mit Name und Anschrift im Empfängerfeld: %r" % gerufene)
pruefe(any("subject=R%C3%BCckfrage" in " ".join(a) for a in gerufene),
       "und mit Betreff")
pruefe(m.mail_oeffnen("kein-at-zeichen")["ok"] is False,
       "unbrauchbare Anschriften werden abgelehnt")

gerufene = []
erg = m.drucken("<html><body>Probe</body></html>", "probe",
                 lambda a: gerufene.append(a))
pruefe(erg["ok"] and erg["pfad"].endswith(".html"),
       "die Druckseite wird abgelegt: %s" % erg["pfad"])
pruefe("Probe" in open(erg["pfad"], encoding="utf-8").read(),
       "und trägt den übergebenen Inhalt")
pruefe(os.stat(os.path.dirname(erg["pfad"])).st_mode & 0o777 == 0o700 and
       os.stat(erg["pfad"]).st_mode & 0o777 == 0o600,
       "temporäre Druckseite liegt mit privaten Rechten")

with tempfile.TemporaryDirectory() as ausgabe_basis:
    alt = os.path.join(ausgabe_basis, "magnolie-brief-alt")
    frisch = os.path.join(ausgabe_basis, "magnolie-druck-frisch")
    fremd = os.path.join(ausgabe_basis, "andere-anwendung-alt")
    verweis = os.path.join(ausgabe_basis, "magnolie-ods-verweis")
    os.mkdir(alt)
    os.mkdir(frisch)
    os.mkdir(fremd)
    os.symlink(fremd, verweis)
    alter_stand = time.time() - 8 * 24 * 60 * 60
    os.utime(alt, (alter_stand, alter_stand))
    os.utime(fremd, (alter_stand, alter_stand))
    entfernt = m.temporaere_ausgaben_bereinigen(
        ausgabe_basis, jetzt=time.time(), max_alter=7 * 24 * 60 * 60)
    pruefe(entfernt == 1 and not os.path.exists(alt),
           "alte eigene Brief- und Druckausgaben werden entfernt")
    pruefe(os.path.isdir(frisch) and os.path.isdir(fremd) and os.path.islink(verweis),
           "frische, fremde und verlinkte Temporärverzeichnisse bleiben unangetastet")

print()
print("— ODS-Kontakttabelle —")

ods_spalten = ["Nachname", "Vorname", "Anschriften", "Telefonnummern",
               "Notfallkontakte", "Notiz"]
ods_zeilen = [["Müller & Söhne", "Zoë\nFirma: Tee <Handel>",
               "Privatanschrift\nHauptstraße 1\n47051 Duisburg\nDeutschland\n\n"
               "Lager & West\nNebenweg 2\n47441 Moers",
               "Festnetz: 0203 1\nMobil: 0171 2\nAtelier: 0203 3",
               "Notfallkontakt: Ada <Eins> · Schwester\nTelefon: 111",
               "Erste Zeile\nZweite & <dritte> Zeile"],
              ["Weisse Zeile", "Ohne Einzug", "Musterstrasse 2", "0203 2",
               "Ada Zwei", "Notiz zwei"]]
ods_daten = m.adressen_ods_bytes(
    "Magnolie Organizer · Adressen", ods_spalten, ods_zeilen)
pruefe(m.adressen_ods_bytes("Geburtstagsliste", ["Geburtstag"],
                            [["05.04.1980"]]).startswith(b"PK"),
       "ODS-Smoke-Test erlaubt eine gezielt gewählte einzelne Inhaltsspalte")
pruefe(m.adressen_ods_bytes("Vollständige Adressen",
                            ["Spalte %d" % i for i in range(14)],
                            [["Wert %d" % i for i in range(14)]],
                            logo_pfad="").startswith(b"PK"),
       "ODS erzeugt auch die vollständige neue Vierzehn-Spalten-Tabelle")
ods_privater_pfad = m.adressen_ods_schreiben(
    "Geburtstagsliste", ["Geburtstag"], [["05.04.1980"]])
pruefe(os.stat(os.path.dirname(ods_privater_pfad)).st_mode & 0o777 == 0o700 and
       os.stat(ods_privater_pfad).st_mode & 0o777 == 0o600,
       "temporäre ODS-Kontakttabelle liegt mit privaten Rechten")
with zipfile.ZipFile(io.BytesIO(ods_daten)) as ods_archiv:
    namen = ods_archiv.namelist()
    info = ods_archiv.getinfo("mimetype")
    pruefe(namen[0] == "mimetype" and info.compress_type == zipfile.ZIP_STORED and
           ods_archiv.read("mimetype") ==
           b"application/vnd.oasis.opendocument.spreadsheet",
           "ODS-Mimetype liegt zuerst und unkomprimiert im ZIP")
    pruefe("META-INF/manifest.xml" in namen and "content.xml" in namen and
           "styles.xml" in namen, "ODS enthält Manifest, Inhalt und Stile")
    inhalt = ods_archiv.read("content.xml").decode("utf-8")
    stile = ods_archiv.read("styles.xml").decode("utf-8")
    manifest = ods_archiv.read("META-INF/manifest.xml").decode("utf-8")
    for name, xml in (("content", inhalt), ("styles", stile),
                      ("manifest", manifest)):
        try:
            ET.fromstring(xml)
            xml_ok = True
        except ET.ParseError:
            xml_ok = False
        pruefe(xml_ok, "%s.xml ist wohlgeformt" % name)
    pruefe("Pictures/magnolie-organizer.png" in namen and
           "Pictures/magnolie-organizer.png" in manifest and
           ods_archiv.read("Pictures/magnolie-organizer.png").startswith(
               b"\x89PNG\r\n\x1a\n") and
           "table:shapes" in inhalt and
           "table:anchor-cell-address=\"'Adressen'.A1\"" in inhalt and
           "xlink:href=\"Pictures/magnolie-organizer.png\"" in inhalt,
           "das Magnolien-PNG ist als zellverankerte Calc-Zeichnung eingebettet")
    pruefe("table:table-header-rows" in inhalt and "table:print=\"true\"" in inhalt and
           inhalt.index("Nachname") < inhalt.index("Vorname") and
           "fo:wrap-option=\"wrap\"" in inhalt,
           "Spaltenreihenfolge, Druckkopf und umbrochene Zellen sind gesetzt")
    pruefe("Müller &amp; Söhne" in inhalt and "Tee &lt;Handel&gt;" in inhalt and
           "Zweite &amp; &lt;dritte&gt; Zeile" in inhalt and
           inhalt.count("text:line-break") >= 8,
           "Unicode, XML-Zeichen und mehrzeilige Felder bleiben erhalten")
    pruefe('<text:p>Weisse Zeile</text:p>' in inhalt and
           '<text:p> Weisse Zeile</text:p>' not in inhalt and
           'style:name="cellAlt" style:family="table-cell"><style:table-cell-properties '
           'fo:background-color="#faf7f0" fo:border="0.01cm solid #cbb894" '
           'fo:padding="0.1cm"' in inhalt,
           "abwechselnd helle ODS-Zeilen erhalten weder Textleerraum noch anderen Einzug")
    pruefe("fo:page-width=\"29.7cm\"" in stile and
           "fo:page-height=\"21cm\"" in stile and
           "style:print-orientation=\"landscape\"" in stile and
           "style:scale-to=\"92%\"" in stile and
           "style:scale-to-X" not in stile and "text:page-number" in stile,
           "A4-Querformat, Kontakt-ODS-Skalierung und Seitenfuß sind eingerichtet")

kalender_spalten = ["Monat %d" % monat for monat in range(1, 13)]
kalender_zeilen = [["%d Mo" % tag for _monat in range(12)] for tag in range(1, 32)]
kalender_stile = [["" for _monat in range(12)] for _tag in range(31)]
kalender_stile[0][0] = "holiday"
kalender_stile[1][0] = "vacation"
kalender_stile[2][0] = "saturday"
kalender_stile[3][0] = "sunday"
kalender_stile[30][1] = "empty"
kalender_ods = m.adressen_ods_bytes(
    "Magnolie Organizer · Jahresplaner 2026", kalender_spalten,
    kalender_zeilen, logo_pfad="", zellstile=kalender_stile, kompakt=True)
with zipfile.ZipFile(io.BytesIO(kalender_ods)) as kalender_archiv:
    kalender_inhalt = kalender_archiv.read("content.xml").decode("utf-8")
    kalender_seitenstil = kalender_archiv.read("styles.xml").decode("utf-8")
    pruefe(kalender_inhalt.count('style:column-width="2.3417cm"') == 12 and
           'style:name="calendarHoliday"' in kalender_inhalt and
           'style:name="calendarVacation"' in kalender_inhalt and
           'style:name="calendarSaturday"' in kalender_inhalt and
           'style:name="calendarSunday"' in kalender_inhalt and
           'style:name="calendarEmpty"' in kalender_inhalt and
           'table:style-name="calendarHoliday"' in kalender_inhalt,
           "Planer-ODS besitzt zwölf kompakte Spalten und Kalenderzellfarben")
    pruefe('style:scale-to-pages="1"' in kalender_seitenstil and
           'style:scale-to="92%"' not in kalender_seitenstil and
           'fo:margin="0.8cm"' in kalender_seitenstil and
           'fo:font-size="7pt"' in kalender_seitenstil and
           'text:page-number' not in kalender_seitenstil and
           'table:print-ranges="&apos;Jahresplaner 2026&apos;.A1:'
           '&apos;Jahresplaner 2026&apos;.L33"' in kalender_inhalt and
           'fo:font-size="17pt"' in kalender_inhalt and
           'fo:font-size="5.5pt"' in kalender_inhalt and
           'fo:font-size="3.6pt"' in kalender_inhalt and
           'fo:background-color="#f1ede4"' in kalender_inhalt and
           'fo:border="0.01cm solid #29251d"' in kalender_inhalt and
           'fo:border="0.01cm solid #625b50"' in kalender_inhalt,
           "Planer-ODS passt Schrift und Druckbereich auf genau eine Seite ein")
monat_inhalte_zeile = [
    {"datum": "1", "eintraege": []},
    {"datum": "1", "marker": [{"text": "💧", "farbe": "#ad3f50"}],
     "eintraege": [{"text": "Frühdienst", "farbe": "#c68a34", "art": "schicht"},
                   {"text": "Restmüll", "farbe": "#4c4b47", "art": "muell"}],
     "mehr": 0},
] + [{"datum": str(tag), "eintraege": []} for tag in range(2, 8)]
monat_ods = m.adressen_ods_bytes(
    "Magnolie Organizer · Januar 2026", ["KW", "Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    [["1", "1 Mo\nFrühdienst", "2 Di", "3 Mi", "4 Do", "5 Fr", "6 Sa", "7 So"]] * 6,
    logo_pfad="", zellstile=[["week-number", "", "", "", "", "", "saturday",
                               "sunday"]] * 6, kompakt=True,
    kalenderinhalte=[monat_inhalte_zeile] * 6)
with zipfile.ZipFile(io.BytesIO(monat_ods)) as monat_archiv:
    monat_inhalt = monat_archiv.read("content.xml").decode("utf-8")
    monat_seitenstil = monat_archiv.read("styles.xml").decode("utf-8")
    pruefe(monat_inhalt.count('style:column-width="3.8714cm"') == 7 and
           'style:column-width="1cm"' in monat_inhalt and
           'style:name="calendarWeek"' in monat_inhalt and
           'table:style-name="calendarWeek"' in monat_inhalt,
           "Monats-ODS besitzt eine KW-Spalte und sieben breite Tagesfelder")
    pruefe('style:name="calendarMonthRow"' in monat_inhalt and
           'style:row-height="2.792cm"' in monat_inhalt and
            'style:name="calendarMonthDate"' in monat_inhalt and
            'Frühdienst' in monat_inhalt and 'Restmüll' in monat_inhalt and
            '💧' in monat_inhalt and
            'fo:background-color="#e8dfcf"' in monat_inhalt and
            'fo:background-color="#e8e4dc"' in monat_inhalt and
            'fo:border-left="0.25cm solid #c68a34"' in monat_inhalt and
            'fo:border-left="0.25cm solid #4c4b47"' in monat_inhalt and
            'fo:font-size="11pt"' in monat_inhalt and
           'fo:background-color="#5c3f25"' in monat_inhalt and
           'fo:background-color="#8b6a35"' in monat_inhalt and
           'table:print-ranges="&apos;Januar 2026&apos;.A1:'
           '&apos;Januar 2026&apos;.H8"' in monat_inhalt and
            'fo:font-size="8pt"' in monat_seitenstil and
            'fo:margin="0.8cm"' in monat_seitenstil and
            'text:page-number' not in monat_seitenstil and
            monat_inhalt.count('style:vertical-align="top"') >= 8,
            "Monats-ODS übernimmt oben ausgerichtete Vorschau-Einträge einschließlich Müll")
try:
    m.adressen_ods_bytes("Kalender", ["Januar"], [["1 Do"]], logo_pfad="",
                         zellstile=[["nicht-erlaubt"]], kompakt=True)
    kalender_stil_grenze_ok = False
except ValueError:
    kalender_stil_grenze_ok = True
pruefe(kalender_stil_grenze_ok,
       "Planer-ODS weist unbekannte Zellstile an der Backend-Grenze ab")

gesundheit_tabellen = [
    {"titel": "Vitalwerte", "links": ["Datum", "Puls", "Blutdruck"],
     "rechts": ["Datum", "Puls", "Blutdruck"],
     "zeilen": [["01.08.2026", "72", "120/80", "02.08.2026", "74", "122/81"],
                ["Müller & Co.", "", "", "", "", ""]]},
    {"titel": "Medikamentenplan", "links": ["Medikament", "Stärke"],
     "rechtsTitel": "Blutzuckerschema / [BZ] & Insulin",
     "rechts": ["Morgens", "Mittags", "Grund / Besonderheiten"],
     "zeilen": [["Magnolie <forte>", "10 mg", "1", "", "Bedarf & Reise"]]},
]
gesundheit_ods = m.gesundheit_ods_bytes(gesundheit_tabellen)
with zipfile.ZipFile(io.BytesIO(gesundheit_ods)) as gesundheit_archiv:
    gesundheit_inhalt = gesundheit_archiv.read("content.xml").decode("utf-8")
    gesundheit_stile = gesundheit_archiv.read("styles.xml").decode("utf-8")
    pruefe(ET.fromstring(gesundheit_inhalt) is not None and
           ET.fromstring(gesundheit_stile) is not None and
           gesundheit_inhalt.count("<table:table table:name=") == 2 and
           'table:name="Vitalwerte"' in gesundheit_inhalt and
           'table:name="Medikamentenplan"' in gesundheit_inhalt,
           "Gesundheits-ODS enthält mehrere wohlgeformte Tabellenblätter")
    pruefe(gesundheit_inhalt.count('style:column-width="4.5333cm"') == 9 and
           gesundheit_inhalt.count('style:column-width="6.8cm"') == 2 and
           gesundheit_inhalt.count('style:name="healthGutterColumn"') == 1 and
           gesundheit_inhalt.count('table:style-name="healthGutterColumn"') == 2 and
           'style:column-width="0.9cm"' in gesundheit_inhalt,
           "Tabellenhälften teilen die Restbreite neben einer 0,9-cm-Falzspalte")
    gesundheit_ns = {
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
        "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    }
    gesundheit_wurzel = ET.fromstring(gesundheit_inhalt)
    gesundheit_blaetter = gesundheit_wurzel.findall(".//table:table", gesundheit_ns)
    gesundheit_spaltenzahlen = []
    gesundheit_falzzellen_ok = True
    gesundheit_titel = []
    for blatt, tabelle in zip(gesundheit_blaetter, gesundheit_tabellen):
        linkszahl = len(tabelle["links"])
        spaltenzahl = linkszahl + 1 + len(tabelle["rechts"])
        gesundheit_spaltenzahlen.append(len(blatt.findall("table:table-column", gesundheit_ns)))
        zeilen = [blatt.find("table:table-row", gesundheit_ns),
                  blatt.find("table:table-header-rows/table:table-row", gesundheit_ns)]
        zeilen += blatt.findall("table:table-row", gesundheit_ns)[1:]
        titelzellen = list(zeilen[0])
        linker_titel = titelzellen[0]
        rechter_titel = titelzellen[linkszahl + 1]
        gesundheit_titel.append(("".join(linker_titel.itertext()),
                                  "".join(rechter_titel.itertext()),
                                  linker_titel.get("{%s}number-columns-spanned" %
                                                   gesundheit_ns["table"]),
                                  rechter_titel.get("{%s}number-columns-spanned" %
                                                    gesundheit_ns["table"])))
        for zeile in zeilen:
            zellen = list(zeile)
            falzzelle = zellen[linkszahl]
            gesundheit_falzzellen_ok = gesundheit_falzzellen_ok and (
                len(zellen) == spaltenzahl and not list(falzzelle) and
                falzzelle.get("{%s}style-name" % gesundheit_ns["table"]) ==
                "healthSpacer")
    falzstil = gesundheit_wurzel.find(
        ".//style:style[@style:name='healthSpacer']/style:table-cell-properties",
        gesundheit_ns)
    pruefe(gesundheit_spaltenzahlen == [7, 6] and gesundheit_falzzellen_ok and
           falzstil is not None and
           not any("border" in attribut for attribut in falzstil.attrib),
           "Titel-, Kopf- und Datenzeilen enthalten eine leere randlose Falzzelle")
    pruefe(gesundheit_titel == [
               ("Vitalwerte", "Vitalwerte", "3", "3"),
               ("Medikamentenplan", "Blutzuckerschema / [BZ] & Insulin", "2", "3")],
           "jede Hälfte erhält ihren eigenen Titel und seine genaue Spaltenbreite")
    pruefe('fo:page-width="29.7cm"' in gesundheit_stile and
           'fo:page-height="21cm"' in gesundheit_stile and
           'style:print-orientation="landscape"' in gesundheit_stile and
           'style:scale-to-X="1"' in gesundheit_stile and
           'style:scale-to-Y="0"' in gesundheit_stile and
           'fo:margin="0.8cm"' in gesundheit_stile,
           "Gesundheits-ODS druckt A4 quer und passt nur die Breite auf eine Seite an")
    pruefe(gesundheit_inhalt.count("table:table-header-rows") == 4 and
           'style:row-height="0.86cm"' in gesundheit_inhalt and
           'style:use-optimal-row-height="false"' in gesundheit_inhalt,
           "Gesundheitsblätter wiederholen Köpfe und verwenden feste Seitenfüllzeilen")
    pruefe('fo:background-color="#7e5685"' in gesundheit_inhalt and
           'fo:border="0.02cm solid #5e3864"' in gesundheit_inhalt and
           'fo:border="0.01cm solid #aa8caf"' in gesundheit_inhalt and
           "Müller &amp; Co." in gesundheit_inhalt and
           "Magnolie &lt;forte&gt;" in gesundheit_inhalt and
           "Bedarf &amp; Reise" in gesundheit_inhalt,
           "Gesundheitsblätter besitzen violette Gestaltung und sichere Nutzdaten")

gesundheit_diagramm = {
    "titel": "Blutdruck",
    "serien": [
        {"name": "Systolisch", "farbe": "#a7444e",
         "punkte": [["2026-08-01", 120], ["2026-08-02", 125.5]]},
        {"name": "Diastolisch", "farbe": "#456f91",
         "punkte": [["2026-08-01", 80], ["2026-08-02", 82]]},
    ],
}
gesundheit_diagramm_ods = m.gesundheit_ods_bytes([{
    "titel": "Gesundheitsverläufe",
    "diagramme": [gesundheit_diagramm] * 6,
}])
with zipfile.ZipFile(io.BytesIO(gesundheit_diagramm_ods)) as diagramm_archiv:
    diagramm_inhalt = diagramm_archiv.read("content.xml").decode("utf-8")
    diagramm_manifest = diagramm_archiv.read("META-INF/manifest.xml").decode("utf-8")
    diagramm_bilder = [name for name in diagramm_archiv.namelist()
                       if name.startswith("Pictures/gesundheit-diagramm-")]
    pruefe(ET.fromstring(diagramm_inhalt) is not None and
           diagramm_inhalt.count("<table:table table:name=") == 1 and
           diagramm_inhalt.count("<draw:frame ") == 6 and
           len(diagramm_bilder) == 6 and
           all(ET.fromstring(diagramm_archiv.read(name)) is not None
               for name in diagramm_bilder) and
           diagramm_manifest.count('manifest:media-type="image/svg+xml"') == 6 and
           "Systolisch" in diagramm_archiv.read(diagramm_bilder[0]).decode("utf-8"),
           "sechs Gesundheitsverläufe erscheinen als eingebettetes 2-mal-3-Diagrammraster")

gesundheit_einzel_diagramm = m.gesundheit_ods_bytes([{
    "titel": "Verlauf · Blutdruck", "rechtsTitel": "Blutdruck",
    "links": ["Datum", "Systolisch", "Diastolisch"], "rechts": ["Blutdruck"],
    "diagramm": gesundheit_diagramm,
    "zeilen": [["01.08.2026", "120", "80", ""],
               ["02.08.2026", "125,5", "82", ""]],
}])
with zipfile.ZipFile(io.BytesIO(gesundheit_einzel_diagramm)) as einzel_archiv:
    einzel_inhalt = einzel_archiv.read("content.xml").decode("utf-8")
    pruefe(einzel_inhalt.count("<draw:frame ") == 1 and
           'table:number-rows-spanned="2"' in einzel_inhalt and
           "Pictures/gesundheit-diagramm-1.svg" in einzel_inhalt,
           "ein einzelner Gesundheitsverlauf stellt Messwertliste und Diagramm nebeneinander")

gesundheit_fehlerfaelle = [
    [],
    [{"titel": "Vital/werte", "links": ["A"], "rechts": ["B"],
      "zeilen": [["", ""]]}],
    [{"titel": "Vital", "links": ["A"], "rechts": ["B"],
      "zeilen": [["", ""]]},
     {"titel": "vital", "links": ["A"], "rechts": ["B"],
      "zeilen": [["", ""]]}],
    [{"titel": "Vital", "links": ["A"], "rechts": ["B"],
      "zeilen": [["nur eine Zelle"]]}],
    [{"titel": "Vital", "links": ["A"], "rechts": ["B"],
       "zeilen": [["", 2]]}],
    [{"titel": "Vital", "rechtsTitel": "", "links": ["A"],
      "rechts": ["B"], "zeilen": [["", ""]]}],
    [{"titel": "Vital", "rechtsTitel": "Zeile\nZwei", "links": ["A"],
      "rechts": ["B"], "zeilen": [["", ""]]}],
    [{"titel": "Vital", "rechtsTitel": "Anzeige", "zusatz": True,
      "links": ["A"], "rechts": ["B"], "zeilen": [["", ""]]}],
    [{"titel": "Verläufe", "diagramme": [{"titel": "Puls", "serien": [
        {"name": "Puls", "farbe": "red", "punkte": [["2026-08-01", 72]]}]}]}],
]
gesundheit_grenzen_ok = True
for gesundheit_fehlerfall in gesundheit_fehlerfaelle:
    try:
        m.gesundheit_ods_bytes(gesundheit_fehlerfall)
        gesundheit_grenzen_ok = False
    except ValueError:
        pass
pruefe(gesundheit_grenzen_ok,
       "Gesundheits-ODS weist leere, unsichere, doppelte und unförmige Tabellen ab")
gesundheit_privater_pfad = m.gesundheit_ods_schreiben(gesundheit_tabellen)
pruefe(os.stat(os.path.dirname(gesundheit_privater_pfad)).st_mode & 0o777 == 0o700 and
       os.stat(gesundheit_privater_pfad).st_mode & 0o777 == 0o600,
       "temporäre Gesundheits-ODS liegt mit privaten Rechten")

ods_ohne_logo = m.adressen_ods_bytes(
    "Magnolie Organizer · Adressen", ods_spalten, ods_zeilen, logo_pfad="")
with zipfile.ZipFile(io.BytesIO(ods_ohne_logo)) as ods_archiv:
    inhalt_ohne = ods_archiv.read("content.xml").decode("utf-8")
    pruefe(not any(name.startswith("Pictures/") for name in ods_archiv.namelist()) and
           "xlink:href=\"Pictures/" not in inhalt_ohne and
           "Magnolie Organizer · Adressen" in inhalt_ohne,
           "ohne Logo bleibt ein gültiger Texttitel ohne kaputten Bildverweis")

ods_aufrufe = []
def _ods_starter(argumente):
    ods_aufrufe.append(argumente)
    if argumente[0] == "/usr/bin/libreoffice":
        raise OSError("Probe")

ods_programme = {"libreoffice": "/usr/bin/libreoffice",
                 "soffice": "/usr/bin/soffice", "xdg-open": "/usr/bin/xdg-open"}
ods_erg = m.ods_oeffnen("/tmp/Magnolie Adressen;touch-NIEMALS.ods",
                        starter=_ods_starter,
                        welcher=lambda name: ods_programme.get(name))
pruefe(ods_erg["ok"] and ods_erg["womit"] == "soffice" and
       ods_aufrufe == [["/usr/bin/libreoffice", "--calc",
                        "/tmp/Magnolie Adressen;touch-NIEMALS.ods"],
                       ["/usr/bin/soffice", "--calc",
                        "/tmp/Magnolie Adressen;touch-NIEMALS.ods"]],
       "ODS-Öffner nutzt Listen ohne Shell und fällt von LibreOffice auf soffice zurück")
pruefe(m.ods_oeffnen("/tmp/probe.ods", starter=lambda _a: None,
                     welcher=lambda _name: None)["ok"] is False,
       "ODS-Öffner meldet einen fehlenden Desktop-Öffner")
ods_aufrufe = []
ods_erg = m.ods_oeffnen("/tmp/probe.ods", starter=lambda a: ods_aufrufe.append(a),
                        welcher=lambda name: "/usr/bin/xdg-open"
                        if name == "xdg-open" else None)
pruefe(ods_erg["womit"] == "xdg-open" and
       ods_aufrufe == [["/usr/bin/xdg-open", "/tmp/probe.ods"]],
       "ODS-Öffner fällt zuletzt ohne Shell auf xdg-open zurück")
try:
    m.adressen_ods_bytes("Titel", ["A", "B"],
                         [["x" * (m.ODS_MAX_ZEICHEN + 1), ""]], logo_pfad="")
    ods_grenze_ok = False
except ValueError:
    ods_grenze_ok = True
pruefe(ods_grenze_ok, "übergroße ODS-Zellen werden an der Backend-Grenze abgewiesen")
try:
    m.adressen_ods_bytes("Titel", ["A", "B"],
                         [["", ""]] * (m.ODS_MAX_ZEILEN + 1), logo_pfad="")
    ods_grenze_ok = False
except ValueError:
    ods_grenze_ok = True
pruefe(ods_grenze_ok, "übergroße ODS-Zeilenzahlen werden abgewiesen")

print()
print("— Absender aus LibreOffice —")

lo_ordner = tempfile.mkdtemp(prefix="magnolie-lo-")
lo_datei = os.path.join(lo_ordner, "libreoffice", "4", "user",
                        "registrymodifications.xcu")
os.makedirs(os.path.dirname(lo_datei), exist_ok=True)
with open(lo_datei, "w", encoding="utf-8") as datei:
    datei.write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<oor:items>\n'
        '<item oor:path="/org.openoffice.Office.Common/Save">'
        '<prop oor:name="givenname"><value>NichtIch</value></prop></item>\n'
        '<item oor:path="/org.openoffice.UserProfile/Data">'
        '<prop oor:name="givenname" oor:op="fuse"><value>Erika</value></prop></item>\n'
        '<item oor:path="/org.openoffice.UserProfile/Data">'
        '<prop oor:name="sn" oor:op="fuse"><value>Beispiel</value></prop></item>\n'
        '<item oor:path="/org.openoffice.UserProfile/Data">'
        '<prop oor:name="o" oor:op="fuse"><value>Beispiel &amp; Söhne</value></prop></item>\n'
        '<item oor:path="/org.openoffice.UserProfile/Data">'
        '<prop oor:name="street" oor:op="fuse"><value>Musterweg 3</value></prop></item>\n'
        '<item oor:path="/org.openoffice.UserProfile/Data">'
        '<prop oor:name="postalcode" oor:op="fuse"><value>47051</value></prop></item>\n'
        '<item oor:path="/org.openoffice.UserProfile/Data">'
        '<prop oor:name="l" oor:op="fuse"><value>Duisburg</value></prop></item>\n'
        '</oor:items>\n')

pruefe(m.libreoffice_einstellungsdatei(lo_ordner) == lo_datei,
       "die Einstellungsdatei von LibreOffice wird gefunden")
erg = m.libreoffice_benutzerdaten(lo_datei)
pruefe(erg["ok"], "die Benutzerdaten lassen sich lesen")
zeilen = erg["absender"].splitlines()
pruefe(zeilen[0] == "Erika Beispiel", "Name zusammengesetzt: %r" % zeilen[0])
pruefe(zeilen[1] == "Beispiel & Söhne",
       "XML-Zeichen zurückverwandelt: %r" % zeilen[1])
pruefe(zeilen[2] == "Musterweg 3" and zeilen[3] == "47051 Duisburg",
       "Anschrift vollständig: %r" % zeilen[2:])
pruefe("NichtIch" not in erg["absender"],
       "Felder aus anderen Bereichen werden nicht verwechselt")
pruefe(m.libreoffice_einstellungsdatei(tempfile.mkdtemp()) == "",
       "ohne LibreOffice wird nichts gefunden")
erg = m.libreoffice_benutzerdaten("/gibt/es/nicht")
pruefe(erg["ok"] is False and "Benutzerdaten" in erg["fehler"],
       "und es wird freundlich erklärt")

print()
print("— Lotus: alle Bereiche —")

adressen_probe = (
    "NACHNAME;VORNAME;FIRMA;STRASSE;PLZ;ORT;TELEFON GESCHAEFTLICH;"
    "MOBILTELEFON;TELEFON PRIVAT;FAX;PAGER;STRASSE PRIVAT;PLZ PRIVAT;"
    "ORT PRIVAT;STRASSE GESCHAEFTLICH;PLZ GESCHAEFTLICH;ORT GESCHAEFTLICH;"
    "EMAIL;NOTIZEN\r\n"
    "Müller;Hans;Müller GmbH;Hauptstraße 12;47051;Duisburg;0203 123456;"
    "0171 9876543;0203 222222;0203 333333;0203 444444;Privatweg 1;47057;"
    "Duisburg;Büroweg 2;47441;Moers;"
    "h.mueller@example.de;Stammkunde seit 1998\r\n"
).encode("cp1252")
erg = m.lotus_csv_lesen(adressen_probe)
pruefe(erg.get("lotusArt") == "kontakte", "Adressdatei wird als solche erkannt")
k = erg["kontakte"][0]
pruefe(k["nachname"] == "Müller" and k["vorname"] == "Hans",
       "Name gelesen: %s %s" % (k["vorname"], k["nachname"]))
pruefe(k["strasse"] == "Hauptstraße 12" and k["plz"] == "47051"
       and k["ort"] == "Duisburg", "Anschrift vollständig")
pruefe(k["telefon"] == "0203 123456" and k["mobil"] == "0171 9876543",
       "Telefon und Mobil getrennt")
pruefe(len(k["telefone"]) == 5 and
       any("FAX" in t["typen"] for t in k["telefone"]),
       "alle Lotus-Rufnummern einschließlich Fax und Pager bleiben erhalten")
pruefe(len(k["anschriften"]) == 3 and
       {a["ort"] for a in k["anschriften"]} == {"Duisburg", "Moers"},
       "Lotus übernimmt allgemeine, private und geschäftliche Anschriften")
pruefe(k["email"] == "h.mueller@example.de" and "Stammkunde" in k["notiz"],
       "E-Post und Bemerkung gelesen")

aufgaben_probe = (
    "BESCHREIBUNG;FAELLIGKEITSDATUM;PRIORITAET;ERLEDIGT\r\n"
    "Steuererklärung abgeben;31.05.2026;Hoch;Nein\r\n"
    "Alte Ablage sichten;01.02.2020;3;Ja\r\n"
    "Archiv schließen;02.02.2020;2;Completed\r\n"
).encode("utf-8-sig")
erg = m.lotus_csv_lesen(aufgaben_probe)
pruefe(erg.get("lotusArt") == "aufgaben", "Aufgabendatei wird erkannt")
a1, a2, a3 = erg["aufgaben"]
pruefe(a1["titel"] == "Steuererklärung abgeben" and a1["faellig"] == "2026-05-31",
       "Aufgabe mit Fälligkeit: %s / %s" % (a1["titel"], a1["faellig"]))
pruefe(a1["prio"] == 1 and a1["erledigt"] is False, "„Hoch“ wird zu Rang 1")
pruefe(a2["prio"] == 3 and a2["erledigt"] is True, "Ziffern und „Ja“ verstanden")
pruefe(a3["erledigt"] is True, "englischer Lotus-Status Completed verstanden")

jahrestage_probe = (
    "NAME;DATUM;TYP\r\nOma Erna;04.03.1950;Geburtstag\r\n"
    "Anna und Otto;12.06.2001;Hochzeitstag\r\n"
    "Kegelverein;07.09.1988;Familientag\r\n"
).encode("utf-8-sig")
erg = m.lotus_csv_lesen(jahrestage_probe)
pruefe(erg.get("lotusArt") == "jahrestage", "Jahrestagsdatei wird erkannt")
pruefe(erg["jahrestage"][0]["datum"] == "1950-03-04" and
       erg["jahrestage"][0]["typ"] == "birthday", "Geburtstag gelesen")
pruefe(erg["jahrestage"][1]["typ"] == "wedding-anniversary", "Hochzeitstag gelesen")
pruefe(erg["jahrestage"][2]["typ"] == "Familientag",
       "freie Jahrestagsart aus Lotus gelesen")

notizen_probe = (
    "TITEL;TEXT\r\nEinkauf;Milch, Brot und Käse besorgen.\r\n"
).encode("utf-8-sig")
erg = m.lotus_csv_lesen(notizen_probe)
pruefe(erg.get("lotusArt") == "notizen", "Notizdatei wird erkannt")
pruefe(erg["notizen"][0]["titel"] == "Einkauf" and
       "Käse" in erg["notizen"][0]["text"], "Notiz gelesen")

# Englische Spaltennamen und andere Schreibweisen
englisch = (
    "LastName,FirstName,Company,Street,ZIP,City,Phone,Mobile,Email,Notes\r\n"
    "Smith,John,ACME Ltd,Main Road 5,12345,London,020 111,079 222,"
    "j@acme.uk,VIP\r\n"
).encode("utf-8")
erg = m.lotus_csv_lesen(englisch)
pruefe(erg.get("lotusArt") == "kontakte" and
       erg["kontakte"][0]["nachname"] == "Smith",
       "auch englische Spaltennamen werden zugeordnet")

print()
print("— Lotus: Betreff und Notiz —")

lotus_probe = (
    "VERTRAULICH,KATEGORIEN,ANFANGSDATUMZEIT,ENDDATUMZEIT,BESCHREIBUNG,"
    "KOSTENSTELLENCODE,KUNDENNUMMER,VORLAEUFIGZUSAGEN\r\n"
    "Ja,Geschäftlich,03.08.2026 09:00:00,03.08.2026 10:30:00,"
    "\"Besprechung mit Herrn Müller\nUnterlagen mitbringen.\nRaum 214\","
    "KST-4711,K-10023,Nein\r\n"
    "Nein,,04.08.2026 14:00:00,04.08.2026 15:00:00,Kurzer Termin,,,Ja\r\n"
).encode("utf-8-sig")

erg = m.lotus_csv_lesen(lotus_probe)
eins, zwei = erg["termine"]
pruefe(eins["titel"] == "Besprechung mit Herrn Müller",
       "die erste Zeile wird zum Betreff: %r" % eins["titel"])
pruefe(eins["notiz"] == "Unterlagen mitbringen.\nRaum 214",
       "der Rest wird zur Notiz: %r" % eins["notiz"])
pruefe(eins["vertraulich"] is True and eins["kostenstelle"] == "KST-4711",
       "die übrigen Lotus-Felder stimmen")
pruefe(zwei["titel"] == "Kurzer Termin" and zwei["notiz"] == "",
       "einzeilige Beschreibungen bleiben wie sie sind")

zurueck = m.lotus_csv_lesen(
    m.lotus_csv_schreiben(erg["termine"]).encode("utf-8-sig"))
pruefe(zurueck["termine"][0]["titel"] == eins["titel"] and
       zurueck["termine"][0]["notiz"] == eins["notiz"],
       "Betreff und Notiz überstehen den Rundlauf unverändert")

print()
print("— Native Ordnerauswahl und KDE-Empfang —")

class _OrdnerDialog:
    def __init__(self):
        self.vorauswahl = ""
    def add_buttons(self, *args):
        pass
    def set_current_folder(self, pfad):
        self.vorauswahl = pfad
    def run(self):
        return m.Gtk.ResponseType.CANCEL
    def get_filename(self):
        return None
    def destroy(self):
        pass

for eingabe, erwartet in (
        ("$HOME/Sicherungen", os.path.abspath(os.path.expanduser("~/Sicherungen"))),
        ("relativ", os.path.abspath("relativ")),
        ("   ", m.daten_verzeichnis())):
    ordner_dialog = _OrdnerDialog()
    with mock.patch.object(m.Gtk, "FileChooserDialog", return_value=ordner_dialog), \
            mock.patch.object(m.os.path, "isdir", return_value=True):
        m.Fenster._ordner_waehlen(object(), "Test", eingabe)
    pruefe(ordner_dialog.vorauswahl == erwartet,
           "Ordner-Vorauswahl wird vollständig normalisiert: %r" % eingabe)

kde_backend = mock.Mock()
kde_fenster = mock.Mock()
kde_fenster._kde_ereignis = mock.Mock()
with mock.patch.object(m, "_kdeconnect_backend", return_value=kde_backend), \
        mock.patch.object(m.os, "makedirs", side_effect=PermissionError("gesperrt")):
    m.Fenster._kde_receive_settings(kde_fenster, True, True, "a" * 32,
                                    False, "/nicht/verfügbar")
kde_werte = kde_backend.configure_receive.call_args.kwargs
kde_fehler_nutzlast = kde_fenster.antwort.call_args.args[1]
pruefe(kde_werte["clipboard_enabled"] is True and
       kde_werte["file_enabled"] is False and
       kde_werte["device_id"] == "a" * 32 and
       kde_fenster.antwort.call_count == 1 and
       kde_fehler_nutzlast["filesDisabled"] is True,
       "fehlerhafter Dateiordner lässt KDE-Zwischenablage aktiv")

kde_backend = mock.Mock()
kde_backend.configure_receive.side_effect = [PermissionError("gesperrt"), None]
kde_fenster = mock.Mock()
kde_fenster._kde_ereignis = mock.Mock()
with mock.patch.object(m, "_kdeconnect_backend", return_value=kde_backend):
    m.Fenster._kde_receive_settings(kde_fenster, True, True, "a" * 32,
                                    False, "/tmp")
pruefe(kde_backend.configure_receive.call_count == 2 and
       kde_backend.configure_receive.call_args.kwargs["file_enabled"] is False and
       kde_fenster.antwort.call_args.args[1]["filesDisabled"] is True,
       "fehlgeschlagene Datei-Konfiguration wird deaktiviert und nicht erneut versucht")

if fehler:
    print("%d PRÜFUNGEN FEHLGESCHLAGEN" % len(fehler))
    sys.exit(1)
print("ALLE PARSER- UND ABGLEICH-TESTS BESTANDEN ✓")
