#!/usr/bin/env python3
import json
import os
import tempfile
from importlib.machinery import SourceFileLoader

PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
m = SourceFileLoader("magnolie_gesamtarchiv", PFAD).load_module()


def vollmodell():
    return {
        "version": 6,
        "termine": [{"id": "t1", "titel": "Grüße 東京", "datum": "2026-08-11"}],
        "aufgaben": [{"id": "a1", "titel": "Prüfen"}],
        "kontakte": [{"id": "k1", "foto": "data:image/jpeg;base64,/9j/2Q==",
                       "emails": ["a@example.test", "b@example.test"],
                       "unbekanntKontakt": {"zukunft": True}},
                      {"id": "k2", "foto": "data:image/png;base64,iVBORw0KGgo="},
                      {"id": "k3", "foto": "data:image/webp;base64,UklGRg=="},
                      {"id": "k4", "foto": "data:image/gif;base64,R0lGODlh"}],
        "notizen": [{"id": "n1", "html": "<p>Bild</p>", "anhaenge": [
            {"daten": "data:image/png;base64,iVBORw0KGgo="},
            {"daten": "data:application/pdf;base64,JVBERi0xLjQ="}]}],
        "notizgruppen": [{"id": "g1", "name": "Alle"}],
        "notizbuecher": [{"id": "b1", "gruppeId": "g1", "name": "Buch"}],
        "jahrestage": [], "feiertage": [], "urlaube": [], "muelltermine": [],
        "personen": [{"id": "p1", "name": "Mia"}], "schichten": [],
        "zyklusmarker": [], "tagmarken": [],
        "gesundheit": {"vitalwerte": [{"id": "v1", "gewicht": 70.5}]},
        "papierkorb": [{"art": "notiz", "wert": {"anhaenge": [
            {"daten": "data:application/pdf;base64,JVBERi0xLjQ="}]}}],
        "tombstones": [{"id": "alt", "geaendert": 1}],
        "einstellungen": {"allgemein": {"tray": {"aktiv": True, "autostart": True},
                                           "sicherungsordner": "/fremd"},
                          "sync": {"kalenderUids": ["fremd"]}},
        "zukuenftigesFeld": {"unicode": "🪻", "roh": [1, None, False]},
    }


daten = vollmodell()
text = m.gesamtarchiv_erzeugen(
    daten, "linux", "2.0.0", erstellt="2026-08-11T12:34:56+00:00")
gelesen = m.gesamtarchiv_lesen_text(text)
assert json.loads(text)["datenschema"] == 2
assert gelesen["daten"] == daten
assert gelesen["fotos"] == 4 and gelesen["anhaenge"] == 3
assert gelesen["daten"]["kontakte"][0]["foto"] == daten["kontakte"][0]["foto"]

# Derselbe kanonische Datenhash ist der plattformübergreifende Golden Vector.
assert json.loads(text)["sha256"] == "e17205be343f22cf24d379d954c2bfec0fbf62807143fb7af29e90fe1ba1a0c9"
windows_text = m.gesamtarchiv_erzeugen(
    daten, "windows", "1.0.0", erstellt="2026-08-11T12:34:56.0000000+00:00")
assert m.gesamtarchiv_lesen_text(windows_text)["daten"] == daten

schema_1 = json.loads(text)
schema_1["datenschema"] = 1
assert m.gesamtarchiv_lesen_text(json.dumps(schema_1))["daten"] == daten

with open(os.path.join(os.path.dirname(__file__), "fixtures", "windows-ordinal.magnolie"),
          encoding="utf-8") as datei:
    windows_golden = m.gesamtarchiv_lesen_text(datei.read())
serien = windows_golden["daten"]["termine"]
assert windows_golden["plattform"] == "windows"
assert [termin["wiederholung"]["art"] for termin in serien] == ["monthly", "monthly"]
assert serien[0]["zeit"] == "09:15" and serien[0]["endDatum"] == "2026-01-14"
assert [termin["wiederholung"]["rruleForm"] for termin in serien] == ["byday", "bysetpos"]

legacy = vollmodell()
legacy["termine"] = [{"datum": "2024-01-11", "wiederholung": {
    "art": "monthly_weekday", "ordinal": 2, "wochentag": "TH"}}]
legacy_text = m.gesamtarchiv_erzeugen(legacy, "windows", "1.0.0")
assert '"monthly_weekday"' not in legacy_text
assert m.gesamtarchiv_lesen_text(legacy_text)["daten"]["termine"][0]["wiederholung"]["art"] == "monthly"

manipuliert = json.loads(text)
manipuliert["daten"]["termine"][0]["titel"] = "manipuliert"
try:
    m.gesamtarchiv_lesen_text(json.dumps(manipuliert))
    raise AssertionError("Hashmanipulation angenommen")
except RuntimeError:
    pass

unbekanntes_schema = json.loads(text)
unbekanntes_schema["datenschema"] = 3
try:
    m.gesamtarchiv_lesen_text(json.dumps(unbekanntes_schema))
    raise AssertionError("Unbekanntes Datenschema angenommen")
except RuntimeError:
    pass

verschluesselt = m.gesamtarchiv_erzeugen(daten, kennwort="Rosenholz1896")
assert m.gesamtarchiv_lesen_text(verschluesselt, "Rosenholz1896")["daten"] == daten
try:
    m.gesamtarchiv_lesen_text(verschluesselt, "falsch")
    raise AssertionError("Falsches Kennwort angenommen")
except RuntimeError:
    pass

unbekannt = json.loads(text)
unbekannt["zusaetzlich"] = {"bleibt": True}
assert m.gesamtarchiv_lesen_text(json.dumps(unbekannt))["daten"] == daten
unbekannt["fassung"] = 99
try:
    m.gesamtarchiv_lesen_text(json.dumps(unbekannt))
    raise AssertionError("Unbekanntes Pflichtformat angenommen")
except RuntimeError:
    pass

lokal = {"einstellungen": {"allgemein": {"tray": {"aktiv": False, "autostart": False},
                                             "sicherungsordner": "/lokal"},
                            "sync": {"kalenderUids": ["lokal"]}}}
ueberlagert = m.gesamtarchiv_lokales_bewahren(daten, lokal, True)
assert ueberlagert["einstellungen"] == lokal["einstellungen"]
mit_token = vollmodell()
mit_token["einstellungen"]["sync"]["graphToken"] = "geheim"
try:
    m.gesamtarchiv_erzeugen(mit_token)
    raise AssertionError("Graph-Token exportiert")
except RuntimeError:
    pass

with tempfile.TemporaryDirectory() as tmp:
    datei = os.path.join(tmp, "a.magnolie")
    with open(datei, "w", encoding="utf-8") as ausgabe:
        ausgabe.write(text)
    link = os.path.join(tmp, "link.magnolie")
    os.symlink(datei, link)
    try:
        m.gesamtarchiv_lesen(link)
        raise AssertionError("Symlink angenommen")
    except OSError:
        pass
    zu_gross = os.path.join(tmp, "gross.magnolie")
    with open(zu_gross, "wb") as ausgabe:
        ausgabe.truncate(m.GESAMTARCHIV_DATEI_MAX + 1)
    try:
        m.gesamtarchiv_lesen(zu_gross)
        raise AssertionError("Übergröße angenommen")
    except m.GroessenFehler:
        pass
    vorher = open(datei, encoding="utf-8").read()
    try:
        m.gesamtarchiv_lesen_text(json.dumps(manipuliert))
    except RuntimeError:
        pass
    assert open(datei, encoding="utf-8").read() == vorher

print("Gesamtarchiv-Vertrag: ok")
