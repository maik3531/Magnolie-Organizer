#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fester Releasevertrag fuer alle dateibasierten Im- und Exporte."""

import io
import os
import sys
import stat
import tempfile
import zipfile
from importlib.machinery import SourceFileLoader


PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
m = SourceFileLoader("magnolie_import_export_vertrag", PFAD).load_module()
fehler = 0


def pruefe(bedingung, text):
    global fehler
    if not bedingung:
        fehler += 1
    print("  %s - %s" % ("ok  " if bedingung else "FEHLT", text))


lange_notiz = "\n".join("Zeile %03d: Import und Export" % nr for nr in range(1, 92))

termin = {
    "uid": "vertrag-termin", "datum": "2026-08-07", "endDatum": "",
    "zeit": "09:15", "endZeit": "10:45", "titel": "Termin, Umlaut ae oe ue",
    "notiz": lange_notiz, "kategorien": "Arbeit", "vertraulich": True,
    "vorlaeufig": True, "kostenstelle": "K-17", "kunde": "Muster",
    "individuelleErinnerungTage": 7, "standardErinnerung": False,
    "wiederholung": {"art": "weekly", "bis": "2027-08-07"},
}
termin_zurueck = m.ics_lesen(m.ics_schreiben_termine([termin]))["termine"][0]
pruefe(all(termin_zurueck.get(feld) == termin.get(feld) for feld in (
    "uid", "datum", "endDatum", "zeit", "endZeit", "titel", "notiz",
    "kategorien", "vertraulich", "vorlaeufig", "kostenstelle", "kunde",
     "wiederholung")), "ICS-Termine behalten alle zugesagten Felder und lange Notizen")

monatsdonnerstag = {
    "uid": "vertrag-monatsdonnerstag", "datum": "2024-01-11", "zeit": "",
    "titel": "Zweiter Donnerstag", "wiederholung": {
        "art": "monthly", "bis": "", "ordinal": 2, "wochentag": "TH"}}
monatsdonnerstag_ics = m.ics_schreiben_termine([monatsdonnerstag])
monatsdonnerstag_zurueck = m.ics_lesen(monatsdonnerstag_ics)["termine"][0]
pruefe("DTSTART;VALUE=DATE:20240111" in monatsdonnerstag_ics and
       "RRULE:FREQ=MONTHLY;BYDAY=2TH" in monatsdonnerstag_ics and
       monatsdonnerstag_zurueck["wiederholung"] ==
       monatsdonnerstag["wiederholung"],
       "ordinaler Monatswochentag bleibt beim ganztägigen ICS-Rundlauf exakt")

zeitserie = {
    "uid": "vertrag-letzter-freitag", "datum": "2026-01-30",
    "endDatum": "2026-01-31", "zeit": "09:15", "endZeit": "10:45",
    "titel": "Letzter Freitag", "standardErinnerung": True,
    "wiederholung": {"art": "monthly", "bis": "", "ordinal": -1,
                      "wochentag": "FR", "rruleForm": "bysetpos"}}
zeitserie_ics = m.ics_schreiben_termine([zeitserie])
zeitserie_zurueck = m.ics_lesen(zeitserie_ics)["termine"][0]
pruefe("DTEND" in zeitserie_ics and
       "RRULE:FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1" in zeitserie_ics and
       all(zeitserie_zurueck.get(feld) == zeitserie.get(feld) for feld in (
           "datum", "endDatum", "zeit", "endZeit", "wiederholung")),
       "zeitgebundene zweitägige BYSETPOS-Monatsserie bleibt exakt")

aufgabe = {"uid": "vertrag-aufgabe", "titel": "Aufgabe", "faellig": "2026-09-01",
           "prio": 1, "erledigt": False, "notiz": lange_notiz,
           "erinnern": True, "individuelleErinnerungTage": 7}
aufgabe_zurueck = m.ics_lesen(m.ics_schreiben_aufgaben([aufgabe]))["aufgaben"][0]
pruefe(all(aufgabe_zurueck.get(feld) == aufgabe.get(feld) for feld in (
    "uid", "titel", "faellig", "prio", "erledigt", "notiz", "erinnern",
    "individuelleErinnerungTage")), "ICS-Aufgaben ueberstehen den Rundlauf")

jahrestag = {"uid": "vertrag-jahrestag", "name": "Erika Beispiel",
             "datum": "1980-02-29", "typ": "birthday"}
jahrestag_zurueck = m.ics_lesen(m.ics_schreiben_jahrestage([jahrestag]))["jahrestage"][0]
pruefe(all(jahrestag_zurueck.get(feld) == jahrestag.get(feld) for feld in (
    "uid", "name", "datum", "typ")),
       "ICS-Jahrestage behalten Typ und Schaltjahrdatum")

kontakt = {
    "uid": "vertrag-kontakt", "nachname": "Beispiel", "vorname": "Erika",
    "firma": "Muster & Co.", "strasse": "Testweg 7", "plz": "47051",
    "ort": "Duisburg", "telefon": "+49 203 1234", "mobil": "+49 170 5678",
    "email": "erika@example.test", "notiz": lange_notiz,
    "emailEintraege": [{"wert": "erika@example.test", "typen": ["HOME"]},
                        {"wert": "buero@example.test", "typen": ["WORK"]}],
    "telefone": [{"wert": "+49 203 1234", "typen": ["HOME"]},
                  {"wert": "+49 170 5678", "typen": ["CELL"]}],
    "anschriften": [{"strasse": "Testweg 7", "plz": "47051", "ort": "Duisburg",
                      "land": "Deutschland", "typen": ["HOME"]}],
    "foto": "data:image/jpeg;base64,/9j/2Q==",
    "geburtstag": "--02-29", "geburtstagJahrUnbekannt": True,
}
kontakt_zurueck = m.vcf_lesen(m.vcf_schreiben([kontakt]))["kontakte"][0]
pruefe(all(kontakt_zurueck.get(feld) == kontakt.get(feld) for feld in (
    "uid", "nachname", "vorname", "firma", "strasse", "plz", "ort",
    "telefon", "mobil", "email", "notiz")),
       "vCard-Kontakte behalten Anschrift, Kommunikation und lange Notiz")
pruefe(kontakt_zurueck["foto"] == kontakt["foto"] and
       kontakt_zurueck["geburtstag"] == "--02-29" and
       kontakt_zurueck["geburtstagJahrUnbekannt"] and
       len(kontakt_zurueck["emailEintraege"]) == 2 and
       kontakt_zurueck["anschriften"][0]["land"] == "Deutschland",
       "VCF bewahrt Foto bytegleich, jahrlose BDAY, Typen und Land")

jahrlose_ics = m.ics_schreiben_jahrestage([
    {"uid": "vertrag-jahrlos", "name": "Jahrlos", "datum": "--02-29",
     "typ": "birthday"}])
pruefe("DTSTART;VALUE=DATE:20000229" in jahrlose_ics and
       "X-MAGNOLIE-DATE:--02-29" in jahrlose_ics and
       m.ics_lesen(jahrlose_ics)["jahrestage"][0]["datum"] == "--02-29",
       "ICS bewahrt jahrlose Jahrestage mit gültigem Projektdatum und Erweiterung")

ldif_kontakt = {
    "uid": "kontakt,sonder", "vorname": "Änne", "nachname": "Bei,spiel",
    "firma": "Muster GmbH",
    "emailEintraege": [{"wert": "aenne@example.org", "typen": ["HOME"]},
                        {"wert": "buero@example.org", "typen": ["WORK"]}],
    "telefone": [{"wert": "0203 1", "typen": ["VOICE"]},
                  {"wert": "0171 2", "typen": ["CELL"]},
                  {"wert": "0203 3", "typen": ["HOME"]},
                  {"wert": "0203 4", "typen": ["WORK"]},
                  {"wert": "0203 5", "typen": ["FAX"]},
                  {"wert": "0203 6", "typen": ["PAGER"]}],
    "anschriften": [
        {"strasse": "A$B Straße 1", "plz": "47051", "ort": "Duisburg",
         "land": "Deutschland"},
        {"strasse": "Büro 2", "plz": "10115", "ort": "Berlin",
         "land": "Deutschland"}],
    "notiz": ("Erste Zeile\nZweite Zeile mit Unicode Ä und einer ausreichend langen "
              "Beschreibung für eine sichere Faltung über mehrere physische LDIF-Zeilen."),
    "geburtstag": "1980-04-03", "foto": "data:image/jpeg;base64,/9j/2Q=="}
ldif_text = m.ldif_schreiben([ldif_kontakt])
ldif_zurueck = m.ldif_lesen(ldif_text)["kontakte"][0]
pruefe(ldif_zurueck["vorname"] == "Änne" and
       ldif_zurueck["emails"] == ["aenne@example.org", "buero@example.org"] and
       len(ldif_zurueck["telefone"]) == 6 and len(ldif_zurueck["anschriften"]) == 2 and
       ldif_zurueck["anschriften"][0]["strasse"] == "A$B Straße 1" and
       ldif_zurueck["foto"] == ldif_kontakt["foto"] and
       ldif_zurueck["geburtstag"] == "1980-04-03",
       "LDIF-Kontakte behalten Unicode, Mehrfachwerte, Dollar, JPEG und Geburtstag")
pruefe("dateOfBirth" not in m.ldif_schreiben([
           {"nachname": "Jahrlos", "geburtstag": "--04-03"}]),
       "LDIF-Ausgabe erfindet für jahrlose Geburtstage kein Jahr")
with open(os.path.join(os.path.dirname(__file__), "fixtures", "golden-kontakt.ldif"),
          encoding="utf-8", newline="") as datei:
    golden_ldif = datei.read()
pruefe(ldif_text == golden_ldif and
       max(len(zeile.encode("utf-8")) for zeile in ldif_text.splitlines()) <= 76,
       "LDIF-Ausgabe entspricht dem plattformgleichen Golden und der Faltungsgrenze")
pruefe(m._ldif_dn_wert(" #Komma,+Gleich=\\Ende ") ==
       "\\ #Komma\\,\\+Gleich\\=\\\\Ende\\ ",
       "LDIF-DN maskiert führende und abschließende Leerzeichen und Sonderzeichen")
angriff = {"uid": " #,+=\\\"<>; ", "nachname": "Name\r\nmail: injected@example.org",
           "email": "sicher@example.org"}
png = {"nachname": "PNG", "foto": "data:image/png;base64,iVBORw0KGgo="}
sicher_text, sicher_weg, foto_weg = m._ldif_export(
    [angriff, png, {}, dict(ldif_kontakt), dict(ldif_kontakt)])
pruefe(sicher_text.count("\r\nmail: injected@example.org") == 0 and
       sicher_text.count("objectClass: inetOrgPerson") == 4 and
       len(set(zeile for zeile in sicher_text.splitlines() if zeile.startswith("uid: "))) == 4 and
       sicher_weg == 1 and foto_weg == 1 and "iVBOR" not in sicher_text,
       "LDIF maskiert Injektionen, erzeugt eindeutige UIDs und verwirft unbrauchbare Daten")
ldif_ziel = os.path.join(tempfile.mkdtemp(prefix="magnolie-ldif-"), "adressen.ldif")
m.atomar_text_schreiben(ldif_ziel, ldif_text, modus=0o600)
pruefe(open(ldif_ziel, "rb").read() == ldif_text.encode("utf-8") and
       stat.S_IMODE(os.stat(ldif_ziel).st_mode) == 0o600,
       "LDIF wird atomar, ohne BOM und mit privaten Dateirechten geschrieben")

komplex = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:vertrag-serie\r\n"
           "DTSTART;TZID=America/New_York:20261101T013000\r\nDURATION:PT90M\r\n"
           "RRULE:FREQ=WEEKLY;BYDAY=MO,WE\r\nEXDATE;TZID=America/New_York:20261109T013000\r\n"
           "LOCATION:Raum 7\r\nATTACH:https://example.org/a.pdf\r\nBEGIN:VALARM\r\n"
           "ACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nSUMMARY:Serie\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
komplex_import = m.ics_lesen(komplex)["termine"][0]
komplex_export = m.ics_schreiben_termine([komplex_import])
pruefe(komplex_import["icsKomplex"] and
       "DTSTART;TZID=America/New_York:20261101T013000" in komplex_export and
       "RRULE:FREQ=WEEKLY;BYDAY=MO,WE" in komplex_export and
       "BEGIN:VALARM" in komplex_export and "ATTACH:https://example.org/a.pdf" in komplex_export,
       "komplexe ICS-Serie, Quell-TZID, Alarm und Anhang bleiben opak erhalten")

fixture_pfad = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(fixture_pfad, "golden-komplex.ics"), encoding="utf-8") as datei:
    golden_ics = m.ics_lesen(datei.read())["termine"][0]
with open(os.path.join(fixture_pfad, "golden-kontakt.vcf"), encoding="utf-8") as datei:
    golden_vcf = m.vcf_lesen(datei.read())["kontakte"][0]
golden_ics_zurueck = m.ics_lesen(m.ics_schreiben_termine([golden_ics]))["termine"][0]
golden_vcf_zurueck = m.vcf_lesen(m.vcf_schreiben([golden_vcf]))["kontakte"][0]
pruefe("TRIGGER:-PT15M" in golden_ics_zurueck["icsRoundtrip"] and
       golden_vcf_zurueck["foto"] == golden_vcf["foto"] and
       golden_vcf_zurueck["geburtstagJahrUnbekannt"],
       "plattformübergreifende Goldens bewahren Serie, Alarm, Foto und BDAY")

with open(os.path.join(fixture_pfad, "caldav-series-resource.ics"),
          encoding="utf-8") as datei:
    caldav_ressource = datei.read()
caldav_import = m.ics_lesen(caldav_ressource)
caldav_export = m.ics_schreiben_termine(caldav_import["termine"])
pruefe(len(caldav_import["termine"]) == 2 and
       "X-EXAMPLE-META;X-TOKEN=alpha:opaque-value" in caldav_export and
       "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC" in caldav_export and
       caldav_export.count("BEGIN:VALARM") == 2 and
       caldav_export.count("DESCRIPTION:Reminder") == 1,
       "unbekannte ICS-Eigenschaften, Parameter und Alarme bleiben im Roundtrip erhalten")
pruefe(caldav_export.count("UID:caldav-series-1") == 2 and
       caldav_export.count("RECURRENCE-ID") == 1 and
       "RRULE:FREQ=WEEKLY;COUNT=4" in caldav_export,
       "Serienstamm und Ausnahme behalten beim Export dieselbe UID")

lotus_zurueck = m.lotus_csv_lesen(m.lotus_csv_schreiben([termin]).encode("utf-8-sig"))
pruefe(len(lotus_zurueck["termine"]) == 1 and
       lotus_zurueck["termine"][0]["titel"] == termin["titel"] and
       lotus_zurueck["termine"][0]["notiz"] == termin["notiz"] and
       lotus_zurueck.get("uebersprungen", 0) == 0,
       "Lotus-CSV-Termine ueberstehen Export und erneuten Import")

ods = m.adressen_ods_bytes("Vertrag", ["Name", "Notiz"],
                           [["Erika Beispiel", lange_notiz]], logo_pfad="")
try:
    with zipfile.ZipFile(io.BytesIO(ods)) as archiv:
        inhalt = archiv.read("content.xml")
        ods_ok = (archiv.read("mimetype") ==
                  b"application/vnd.oasis.opendocument.spreadsheet" and
                  b"Zeile 001: Import und Export" in inhalt and
                  b"Zeile 091: Import und Export" in inhalt and
                  inhalt.count(b"<text:line-break/>") >= 90)
except (KeyError, zipfile.BadZipFile):
    ods_ok = False
pruefe(ods_ok, "ODS-Export bleibt gueltig und bewahrt lange Zellinhalte")

pruefe(callable(m.ics_lesen) and callable(m.vcf_lesen) and
       callable(m.lotus_csv_lesen) and callable(m.ldif_lesen) and
       callable(m.ldif_schreiben) and callable(m.claws_xml_lesen),
       "alle zugesagten Dateiimportpfade bleiben im Programmkern vorhanden")

if fehler:
    print("%d IMPORT-/EXPORT-VERTRAGSPRUEFUNGEN FEHLGESCHLAGEN" % fehler)
    sys.exit(1)
print("IMPORT-/EXPORT-VERTRAG BESTANDEN")
