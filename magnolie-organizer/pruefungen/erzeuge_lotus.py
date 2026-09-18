#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt große Lotus-Organizer-CSV-Dateien für alle fünf Bereiche.

Jede Datei erhält dieselbe angeforderte Anzahl Einträge, damit Termine,
Adressen, Aufgaben, Jahrestage und Notizen gleich stark belastet werden.
"""

import csv
import io
import os
import random
import sys
from datetime import datetime, timedelta

KOPF = ["VERTRAULICH", "KATEGORIEN", "ANFANGSDATUMZEIT", "ENDDATUMZEIT",
        "BESCHREIBUNG", "KOSTENSTELLENCODE", "KUNDENNUMMER",
        "VORLAEUFIGZUSAGEN"]

KATEGORIEN = ["Geschäftlich", "Privat", "Urlaub", "Behörde", "Ärzte",
              "Verein", "Familie", "Fortbildung", "Reise", ""]

TITEL = [
    "Besprechung mit Herrn Müller", "Zahnarzt Dr. Schröder",
    "Jahreshauptversammlung", "Quartalsabschluß", "Kundentermin Weißenfels",
    "Übergabe der Unterlagen", "Grünflächenamt", "Prüfung der Bilanz",
    "Frühstück mit Käthe", "Änderungsschneiderei", "Straßenverkehrsamt",
    "Betriebsausflug", "Personalgespräch", "Wartung der Anlage",
    "Vortrag über Qualitätssicherung", "Sitzung des Aufsichtsrats",
    "Geschäftsessen im Löwenbräu", "Führerscheinverlängerung",
    "Abschlußbesprechung", "Empfang der Delegation",
]

NOTIZEN = [
    "", "", "",
    "Unterlagen mitbringen.",
    "Frau Schmidt informieren.\nRaum 214, zweiter Stock.",
    "Achtung: Parkplatz vorher reservieren!",
    "Betrifft Vorgang 1998/17 – siehe Ordner „Ablage Süd“.",
]
LANGE_NOTIZ = "\n".join("Zeile %02d – ausführlicher Probentext" % nummer
                          for nummer in range(1, 92))


def erzeuge(anzahl, ziel, kodierung="utf-8-sig"):
    zufall = random.Random(1996)          # immer dieselbe Datei
    beginn = datetime(1996, 1, 2, 8, 0)
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=",", lineterminator="\r\n",
                           quoting=csv.QUOTE_MINIMAL)
    schreiber.writerow(KOPF)

    tag = beginn
    geschrieben = 0
    while geschrieben < anzahl:
        # Pro Werktag ein bis drei Termine
        if tag.weekday() < 5:
            for _ in range(zufall.randint(1, 3)):
                if geschrieben >= anzahl:
                    break
                stunde = zufall.randint(7, 18)
                minute = zufall.choice([0, 15, 30, 45])
                start = tag.replace(hour=stunde, minute=minute)
                dauer = zufall.choice([30, 45, 60, 90, 120])
                ende = start + timedelta(minutes=dauer)
                titel = zufall.choice(TITEL)
                notiz = LANGE_NOTIZ if geschrieben == 0 else zufall.choice(NOTIZEN)
                beschreibung = titel + (("\n" + notiz) if notiz else "")
                schreiber.writerow([
                    "Ja" if zufall.random() < 0.06 else "Nein",
                    zufall.choice(KATEGORIEN),
                    start.strftime("%d.%m.%Y %H:%M:%S"),
                    ende.strftime("%d.%m.%Y %H:%M:%S"),
                    beschreibung,
                    zufall.choice(["", "", "KST-4711", "KST-0815", "KST-2000"]),
                    zufall.choice(["", "", "K-10023", "K-88120", "K-70551"]),
                    "Ja" if zufall.random() < 0.09 else "Nein",
                ])
                geschrieben += 1
        tag += timedelta(days=1)

    roh = puffer.getvalue()
    with open(ziel, "w", encoding=kodierung, newline="") as datei:
        datei.write(roh)
    return geschrieben, len(roh.encode(kodierung))


NACHNAMEN = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer",
             "Wagner", "Becker", "Schulz", "Hoffmann", "Schäfer", "Koch",
             "Bauer", "Richter", "Klein", "Wolf", "Schröder", "Neumann"]
VORNAMEN = ["Hans", "Käthe", "Jürgen", "Ursula", "Günther", "Änne", "Wolfgang",
            "Renate", "Karl-Heinz", "Ingeborg", "Björn", "Sönke"]
ORTE = [("47051", "Duisburg"), ("40210", "Düsseldorf"), ("45127", "Essen"),
        ("50667", "Köln"), ("44135", "Dortmund"), ("48143", "Münster")]


def erzeuge_adressen(anzahl, ziel, kodierung="cp1252"):
    """Adressbuch, wie Lotus es ausgibt: Semikolon und Windows-Zeichensatz."""
    zufall = random.Random(4711)
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n",
                           quoting=csv.QUOTE_MINIMAL)
    schreiber.writerow(["NACHNAME", "VORNAME", "FIRMA", "STRASSE", "PLZ",
                        "ORT", "TELEFON GESCHAEFTLICH", "MOBILTELEFON",
                        "EMAIL", "NOTIZEN"])
    for i in range(anzahl):
        nach = zufall.choice(NACHNAMEN)
        vor = zufall.choice(VORNAMEN)
        plz, ort = zufall.choice(ORTE)
        schreiber.writerow([
            nach, vor,
            zufall.choice(["", "", nach + " GmbH", "Stadtwerke " + ort]),
            "%sstraße %d" % (zufall.choice(["Haupt", "Bahnhof", "Garten",
                                            "Lindenallee", "Königs"]),
                             zufall.randint(1, 199)),
            plz, ort,
            "0%d %d" % (zufall.randint(200, 899), zufall.randint(100000, 999999)),
            "01%d %d" % (zufall.randint(50, 79), zufall.randint(1000000, 9999999)),
            "%s.%s%d@example.de" % (vor[:1].lower(),
                                    nach.lower().replace("ä", "ae")
                                    .replace("ö", "oe").replace("ü", "ue"), i),
            LANGE_NOTIZ if i == 0 else
            zufall.choice(["", "", "Stammkunde seit 1998", "nur vormittags"]),
        ])
    roh = puffer.getvalue()
    with open(ziel, "w", encoding=kodierung, newline="", errors="replace") as datei:
        datei.write(roh)
    return anzahl, len(roh.encode(kodierung, "replace"))


def erzeuge_aufgaben(anzahl, ziel, kodierung="utf-8-sig"):
    zufall = random.Random(1234)
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n")
    schreiber.writerow(["BESCHREIBUNG", "FAELLIGKEITSDATUM", "PRIORITAET",
                        "ERLEDIGT"])
    tag = datetime(2005, 1, 1)
    for i in range(anzahl):
        tag += timedelta(days=zufall.randint(1, 4))
        schreiber.writerow([
            ("Große Aufgabe\n" + LANGE_NOTIZ) if i == 0 else zufall.choice([
                "Steuererklärung abgeben", "Rechnung prüfen", "Angebot einholen",
                "Prospekte bestellen", "Wartungsvertrag verlängern"]),
            tag.strftime("%d.%m.%Y"),
            zufall.choice(["1", "2", "3", "Hoch", "Niedrig"]),
            zufall.choice(["Ja", "Nein", "Nein"]),
        ])
    roh = puffer.getvalue()
    with open(ziel, "w", encoding=kodierung, newline="") as datei:
        datei.write(roh)
    return anzahl, len(roh.encode(kodierung))


def erzeuge_jahrestage(anzahl, ziel, kodierung="utf-8-sig"):
    zufall = random.Random(99)
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n")
    schreiber.writerow(["NAME", "DATUM", "TYP"])
    for i in range(anzahl):
        schreiber.writerow([
            "%s %s" % (zufall.choice(VORNAMEN), zufall.choice(NACHNAMEN)),
            "%02d.%02d.%d" % (zufall.randint(1, 28), zufall.randint(1, 12),
                              zufall.randint(1930, 2010)),
            zufall.choice(["Geburtstag", "Geburtstag", "Hochzeitstag", ""]),
        ])
    roh = puffer.getvalue()
    with open(ziel, "w", encoding=kodierung, newline="") as datei:
        datei.write(roh)
    return anzahl, len(roh.encode(kodierung))


def erzeuge_notizen(anzahl, ziel, kodierung="utf-8-sig"):
    zufall = random.Random(7)
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n")
    schreiber.writerow(["TITEL", "TEXT"])
    for i in range(anzahl):
        schreiber.writerow([
            "Notiz %d – %s" % (i + 1, zufall.choice(
                ["Einkauf", "Besprechung", "Gedanken", "Rezept", "Werkstatt"])),
            LANGE_NOTIZ if i == 0 else zufall.choice([
                "Milch, Brot, Käse und Äpfel besorgen.",
                "Herrn Müller wegen der Lieferung anrufen.\nRückruf bis Freitag.",
                "Ölwechsel bei 120.000 km fällig – Werkstatt Schäfer.",
            ]),
        ])
    roh = puffer.getvalue()
    with open(ziel, "w", encoding=kodierung, newline="") as datei:
        datei.write(roh)
    return anzahl, len(roh.encode(kodierung))


if __name__ == "__main__":
    anzahl = int(sys.argv[1]) if len(sys.argv) > 1 else 30000
    ziel = sys.argv[2] if len(sys.argv) > 2 else "/tmp/lotus-gross.csv"
    zahl, groesse = erzeuge(anzahl, ziel)
    print("%d Termine geschrieben (%.1f MB): %s"
          % (zahl, groesse / 1048576.0, ziel))
    ordner = os.path.dirname(ziel) or "."
    for name, arbeit, menge in (
            ("lotus-adressen.csv", erzeuge_adressen, anzahl),
            ("lotus-aufgaben.csv", erzeuge_aufgaben, anzahl),
            ("lotus-jahrestage.csv", erzeuge_jahrestage, anzahl),
            ("lotus-notizen.csv", erzeuge_notizen, anzahl)):
        pfad = os.path.join(ordner, name)
        zahl, groesse = arbeit(menge, pfad)
        print("%d Einträge geschrieben (%.1f MB): %s"
              % (zahl, groesse / 1048576.0, pfad))
