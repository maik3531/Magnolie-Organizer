#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Belastungstest: Übernahme eines vollständigen Lotus-Bestandes.

Prüft, ob der Magnolie Organizer die Datenmenge eines jahrzehntelang
geführten Lotus Organizers verkraftet – beim Einlesen, beim Speichern,
beim Weitergeben und beim täglichen Betrieb.
"""

import json
import os
import resource
import sqlite3
import sys
import tempfile
import time
from modul_laden import quellmodul_laden
from datetime import datetime

sys.stdout.reconfigure(line_buffering=True)

PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
m = quellmodul_laden("magorg", PFAD)

GRENZEN = []
fehler = 0


def messe(name, arbeit, grenze_sekunden):
    global fehler
    beginn = time.perf_counter()
    ergebnis = arbeit()
    dauer = time.perf_counter() - beginn
    ok = dauer <= grenze_sekunden
    if not ok:
        fehler += 1
    print("  %-46s %7.2f s   (Grenze %.1f s) %s"
          % (name, dauer, grenze_sekunden, "ok" if ok else "ZU LANGSAM"))
    GRENZEN.append((name, dauer))
    return ergebnis


def speicher_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def pruefe(bedingung, text):
    global fehler
    if not bedingung:
        fehler += 1
    print("  %s – %s" % ("ok  " if bedingung else "FEHLT", text))


quelle = sys.argv[1] if len(sys.argv) > 1 else "/tmp/lotus-gross.csv"
print("Belastungstest mit %s" % quelle)
print("Speicher zu Beginn: %.0f MB" % speicher_mb())
print()

with open(quelle, "rb") as datei:
    rohbytes = datei.read()
print("Dateigröße: %.1f MB" % (len(rohbytes) / 1048576.0))
print()

print("Einlesen der Lotus-Datei")
text = rohbytes  # lotus_csv_lesen nimmt die Rohbytes selbst entgegen
ergebnis = messe("lotus_csv_lesen (30.000 Termine)",
                 lambda: m.lotus_csv_lesen(rohbytes), 12.0)
termine = ergebnis["termine"]
pruefe(len(termine) == 30000, "alle 30.000 Termine gelesen (%d)" % len(termine))
pruefe(ergebnis.get("uebersprungen", 0) == 0,
       "keine Zeile ausgelassen (%d)" % ergebnis.get("uebersprungen", 0))

erster = termine[0]
pruefe(erster["datum"] == "1996-01-02" and erster["zeit"] == "15:45",
       "erster Termin richtig: %s %s" % (erster["datum"], erster["zeit"]))
pruefe(any("ü" in t["titel"] or "ä" in t["titel"] or "ö" in t["titel"]
           for t in termine[:200]), "Umlaute kommen sauber an")
pruefe(any(t["vertraulich"] for t in termine),
       "vertrauliche Termine erkannt (%d)"
       % sum(1 for t in termine if t["vertraulich"]))
pruefe(any(t["vorlaeufig"] for t in termine),
       "vorläufige Termine erkannt (%d)"
       % sum(1 for t in termine if t["vorlaeufig"]))
pruefe(any(t["notiz"].count("\n") > 80 for t in termine),
       "mehr als 80 Zeilen lange Terminnotiz erhalten")
pruefe(any(t["kostenstelle"] for t in termine), "Kostenstellen erhalten")
print("Speicher nach dem Einlesen: %.0f MB" % speicher_mb())
print()

print("Die uebrigen Bereiche des Lotus Organizers")
bereiche = [("lotus-adressen.csv", "kontakte", 30000, "Adressen"),
            ("lotus-aufgaben.csv", "aufgaben", 30000, "Aufgaben"),
            ("lotus-jahrestage.csv", "jahrestage", 30000, "Jahrestage"),
            ("lotus-notizen.csv", "notizen", 30000, "Notizen")]
gelesen = {}
for pfad, schluessel, menge, name in bereiche:
    pfad = os.path.join(os.path.dirname(os.path.abspath(quelle)), pfad)
    with open(pfad, "rb") as datei:
        rohe = datei.read()
    erg = messe("%s einlesen (%d)" % (name, menge),
                lambda r=rohe: m.lotus_csv_lesen(r), 8.0)
    gelesen[schluessel] = erg.get(schluessel) or []
    pruefe(erg.get("lotusArt") == schluessel,
           "als %s erkannt (%s)" % (name, erg.get("lotusArt")))
    pruefe(len(gelesen[schluessel]) == menge,
           "alle %s gelesen (%d)" % (name, len(gelesen[schluessel])))

if gelesen.get("kontakte"):
    k = gelesen["kontakte"][0]
    pruefe(bool(k["nachname"] and k["ort"] and k["telefon"] and k["email"]),
           "Adressfelder vollstaendig: %s %s, %s %s, %s"
           % (k["vorname"], k["nachname"], k["plz"], k["ort"], k["telefon"]))
    pruefe(any("\u00fc" in x["nachname"] or "\u00e4" in x["strasse"]
               for x in gelesen["kontakte"][:400]),
            "Umlaute aus dem Windows-Zeichensatz kommen an")
    pruefe(any(x["notiz"].count("\n") > 80 for x in gelesen["kontakte"]),
           "mehr als 80 Zeilen lange Adressnotiz erhalten")
    vcf = messe("Adressen als vCard schreiben",
                lambda: m.vcf_schreiben(gelesen["kontakte"]), 8.0)
    zurueck_k = messe("vCard wieder einlesen", lambda: m.vcf_lesen(vcf), 12.0)
    pruefe(len(zurueck_k["kontakte"]) == len(gelesen["kontakte"]),
           "Rundlauf der Adressen ohne Verlust (%d)" % len(zurueck_k["kontakte"]))
    pruefe(zurueck_k["kontakte"][0]["telefon"] == k["telefon"] and
            zurueck_k["kontakte"][0]["email"] == k["email"] and
            zurueck_k["kontakte"][0]["notiz"].count("\n") > 80,
            "Telefon, E-Post und lange Notiz ueberstehen den Rundlauf")

if gelesen.get("aufgaben"):
    a = gelesen["aufgaben"][0]
    pruefe(bool(a["titel"] and a["faellig"] and a["prio"] in (1, 2, 3)),
           "Aufgabe vollstaendig: %s, faellig %s, Rang %d"
            % (a["titel"], a["faellig"], a["prio"]))
    pruefe(any(x["notiz"].count("\n") > 80 for x in gelesen["aufgaben"]),
           "mehr als 80 Zeilen lange Aufgabennotiz erhalten")
    ics_a = messe("Aufgaben als ICS schreiben",
                  lambda: m.ics_schreiben_aufgaben(gelesen["aufgaben"]), 8.0)
    zurueck_a = messe("Aufgaben-ICS wieder einlesen",
                      lambda: m.ics_lesen(ics_a), 12.0)
    pruefe(len(zurueck_a["aufgaben"]) == len(gelesen["aufgaben"]),
           "Rundlauf der Aufgaben ohne Verlust (%d)" % len(zurueck_a["aufgaben"]))

if gelesen.get("jahrestage"):
    j = gelesen["jahrestage"][0]
    pruefe(bool(j["name"] and j["datum"] and j["typ"]),
           "Jahrestag vollstaendig: %s am %s (%s)" % (j["name"], j["datum"], j["typ"]))
    ics_j = messe("Jahrestage als ICS schreiben",
                  lambda: m.ics_schreiben_jahrestage(gelesen["jahrestage"]), 8.0)
    zurueck_j = messe("Jahrestage-ICS wieder einlesen",
                      lambda: m.ics_lesen(ics_j), 12.0)
    pruefe(len(zurueck_j["jahrestage"]) == len(gelesen["jahrestage"]),
           "Rundlauf der Jahrestage ohne Verlust (%d)" % len(zurueck_j["jahrestage"]))

if gelesen.get("notizen"):
    n = gelesen["notizen"][0]
    pruefe(bool(n["titel"] and n["text"]), "Notiz vollstaendig: %s" % n["titel"])
    pruefe(any(x["text"].count("\n") > 80 for x in gelesen["notizen"]),
           "mehr als 80 Zeilen lange Notiz erhalten")

print()
print("Speichern und Wiederlesen")
for t in termine:
    t.setdefault("id", m.uid() if hasattr(m, "uid") else os.urandom(6).hex())
daten = {"version": 1, "termine": termine,
         "aufgaben": gelesen.get("aufgaben") or [],
         "kontakte": gelesen.get("kontakte") or [],
         "notizen": gelesen.get("notizen") or [],
         "jahrestage": gelesen.get("jahrestage") or [],
         "feiertage": [],
         "einstellungen": {}, "geloescht": {"termine": [], "kontakte": []}}

roh = messe("json.dumps des ganzen Bestandes",
            lambda: json.dumps(daten, ensure_ascii=False), 6.0)
print("    Datei wäre %.1f MB groß" % (len(roh.encode("utf-8")) / 1048576.0))
messe("json.loads des ganzen Bestandes", lambda: json.loads(roh), 6.0)

print()
print("Weitergeben")
messe("ics_schreiben_termine (30.000 Termine)",
      lambda: m.ics_schreiben_termine(termine), 12.0)
csv_text = messe("lotus_csv_schreiben (30.000 Termine)",
                 lambda: m.lotus_csv_schreiben(termine), 12.0)
zurueck = messe("erneutes Einlesen der geschriebenen CSV",
                lambda: m.lotus_csv_lesen(csv_text.encode("utf-8-sig")), 12.0)
pruefe(len(zurueck["termine"]) == 30000,
       "Rundlauf ohne Verlust (%d)" % len(zurueck["termine"]))
gleich = sum(1 for a, b in zip(termine, zurueck["termine"])
             if a["datum"] == b["datum"] and a["zeit"] == b["zeit"]
             and a["titel"] == b["titel"])
pruefe(gleich == 30000, "alle Termine unverändert (%d gleich)" % gleich)

print()
print("Weitergeben aller Bereiche")
if gelesen.get("kontakte"):
    vcf_gross = messe("30.000 Adressen als vCard",
                      lambda: m.vcf_schreiben(gelesen["kontakte"]), 10.0)
    print("    Die Datei wäre %.1f MB groß"
          % (len(vcf_gross.encode("utf-8")) / 1048576.0))
if gelesen.get("aufgaben"):
    messe("30.000 Aufgaben als ICS",
          lambda: m.ics_schreiben_aufgaben(gelesen["aufgaben"]), 10.0)
if gelesen.get("jahrestage"):
    messe("30.000 Jahrestage als ICS",
          lambda: m.ics_schreiben_jahrestage(gelesen["jahrestage"]), 10.0)

ics_gross = messe("30.000 Termine als ICS (erneut, mit Notizen)",
                  lambda: m.ics_schreiben_termine(termine), 12.0)
print("    Die Datei wäre %.1f MB groß"
      % (len(ics_gross.encode("utf-8")) / 1048576.0))
zurueck_ics = messe("und wieder einlesen",
                    lambda: m.ics_lesen(ics_gross), 20.0)
pruefe(len(zurueck_ics["termine"]) == 30000,
       "Rundlauf über ICS ohne Verlust (%d)" % len(zurueck_ics["termine"]))
gleich_ics = sum(1 for a, b in zip(termine, zurueck_ics["termine"])
                 if a["datum"] == b["datum"] and a["zeit"] == b["zeit"]
                 and a["titel"] == b["titel"] and a["notiz"] == b["notiz"])
pruefe(gleich_ics == 30000,
       "auch Notizen überstehen den ICS-Rundlauf (%d gleich)" % gleich_ics)

print()
print("Thunderbird ESR: 30.000 Eintraege aus Schema 23")
with tempfile.TemporaryDirectory(prefix="magnolie-thunderbird-last-") as tb_tmp:
    tb_db = os.path.join(tb_tmp, "local.sqlite")
    verbindung = sqlite3.connect(tb_db)
    verbindung.execute("""CREATE TABLE cal_events (
        cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, priority INTEGER,
        privacy TEXT, ical_status TEXT, flags INTEGER, event_start INTEGER,
        event_start_tz TEXT, event_end INTEGER, event_end_tz TEXT)""")
    verbindung.execute(
        "CREATE TABLE cal_properties (cal_id TEXT, item_id TEXT, key TEXT, value BLOB)")
    verbindung.execute(
        "CREATE TABLE cal_recurrence (cal_id TEXT, item_id TEXT, icalString TEXT)")
    basis_us = int(datetime(2000, 1, 1).timestamp() * 1000000)
    tag_us = 86400 * 1000000
    ereignisse, eigenschaften, wiederholungen = [], [], []
    lange_notiz = "\n".join("Thunderbird-Notizzeile %02d" % i for i in range(1, 92))
    for i in range(30000):
        jahrestag = i % 1000 == 0
        flags = 24 if jahrestag else (16 if i % 10 == 0 else 0)
        start = basis_us + i * tag_us
        ende = start + (tag_us if jahrestag else 3600 * 1000000)
        uid = "tb-last-%d" % i
        titel = ("Geburtstag Probe %d" if jahrestag else "Termin Probe %d") % i
        ereignisse.append(("last", uid, basis_us, titel, 0, "PUBLIC",
                           "CONFIRMED", flags, start, "UTC", ende, "UTC"))
        if i == 1:
            eigenschaften.append(("last", uid, "DESCRIPTION", lange_notiz))
        if jahrestag:
            eigenschaften.append(("last", uid, "CATEGORIES", "ANNIVERSARY"))
            eigenschaften.append(("last", uid, "X-MAGNOLIE-TYPE-ID", "birthday"))
            wiederholungen.append(("last", uid, "RRULE:FREQ=YEARLY"))
        elif flags & 16:
            wiederholungen.append(("last", uid, "RRULE:FREQ=WEEKLY"))
    verbindung.executemany("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           ereignisse)
    verbindung.executemany("INSERT INTO cal_properties VALUES (?,?,?,?)", eigenschaften)
    verbindung.executemany("INSERT INTO cal_recurrence VALUES (?,?,?)", wiederholungen)
    verbindung.commit()
    verbindung.close()
    tb_last = messe("Thunderbird local.sqlite einlesen (30.000)",
                    lambda: m._tb_normalisierte_kalenderdaten(tb_db), 20.0)
    pruefe(len(tb_last["termine"]) + len(tb_last["jahrestage"]) == 30000,
           "alle 30.000 Thunderbird-Eintraege gelesen")
    pruefe(len(tb_last["jahrestage"]) == 30 and
           all(j["typ"] == "birthday" for j in tb_last["jahrestage"]),
           "30 Thunderbird-Jahrestage in der richtigen Rubrik")
    pruefe(sum(1 for t in tb_last["termine"]
               if t["wiederholung"]["art"] == "weekly") == 2970 and
           tb_last["wiederholend"] == 0,
           "alle einfachen Thunderbird-Serien bleiben wiederkehrend")
    pruefe(any(t["notiz"].count("\n") > 80 for t in tb_last["termine"]),
           "mehr als 80 Zeilen lange Thunderbird-Notiz erhalten")

print()
print("Täglicher Betrieb")
jetzt = m.datetime(2020, 6, 15, 9, 0)
zustand = {"gemeldet": {}, "letzter_lauf": ""}
messe("faellige_erinnerungen über den ganzen Bestand",
      lambda: m.faellige_erinnerungen(daten, jetzt, zustand), 3.0)
messe("naechster_weckzeitpunkt über den ganzen Bestand",
      lambda: m.naechster_weckzeitpunkt(daten, jetzt), 3.0)

print()
print("Abgleich (Synchronisation)")
for i, t in enumerate(termine):
    t.setdefault("uid", "mag-%d@magnolie-organizer" % i)
    t.setdefault("geaendert", 1600000000000)
    t.setdefault("sync", False)
fremd = {}
for i, t in enumerate(termine[:15000]):
    fremd[t["uid"]] = dict(t, titel=t["titel"] + " (drüben geändert)",
                           geaendert=1700000000000)
messe("sync_merge: 30.000 hier gegen 15.000 drüben",
      lambda: m.sync_merge(termine, fremd, [], 0,
                            ("datum", "endDatum", "zeit", "endZeit", "titel", "notiz")), 15.0)

print()
print("Speicher am Ende: %.0f MB" % speicher_mb())
print()
if fehler:
    print("%d PRÜFUNGEN FEHLGESCHLAGEN" % fehler)
    sys.exit(1)
print("BELASTUNGSTEST BESTANDEN ✓")
