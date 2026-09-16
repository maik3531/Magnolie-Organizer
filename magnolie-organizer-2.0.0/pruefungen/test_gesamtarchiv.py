#!/usr/bin/env python3
import copy
import json
import os
import tempfile
from modul_laden import quellmodul_laden

PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
m = quellmodul_laden("magnolie_gesamtarchiv", PFAD)


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
assert json.loads(text)["datenschema"] == 3
assert gelesen["daten"] == json.loads(text)["daten"]
assert gelesen["fotos"] == 4 and gelesen["anhaenge"] == 3
assert gelesen["daten"]["kontakte"][0]["foto"] == daten["kontakte"][0]["foto"]

# Derselbe kanonische Datenhash ist der plattformübergreifende Golden Vector.
assert json.loads(text)["sha256"] == "b673f30a36c0c0b1a3151121ce33d0c76abd9103aaa52bafed1564ce53be16e4"

graph = [{"id": "ä-1"}, {"id": "kind", "uid": "doppelt", "elternUid": "doppelt"},
         {"id": "zweites", "uid": "doppelt", "elternUid": "fehlt"}]
m._aufgaben_graph_normalisieren(graph)
assert graph[0]["uid"] == "mag-task-c841a738bc2a124a@magnolie-organizer"
assert len({item["uid"] for item in graph}) == 3 and all(not item["elternUid"] for item in graph)

# Eindeutige vorhandene UIDs sind vor Ersatzkennungen reserviert. Die zweite
# Kennung folgt Windows' Salt "0"; die spätere Elternreferenz bleibt unverändert.
reservierte_uid = "mag-task-1055c918df76a360@magnolie-organizer"
graph = [{"id": "a"},
         {"id": "z", "uid": reservierte_uid},
         {"id": "zz", "uid": "kind", "elternUid": reservierte_uid}]
m._aufgaben_graph_normalisieren(graph)
assert graph[0]["uid"] == "mag-task-df0ba9f89fa36c86@magnolie-organizer"
assert graph[1]["uid"] == reservierte_uid and graph[2]["elternUid"] == reservierte_uid

# Viele gleiche IDs und adversariell reservierte Anfangskandidaten benötigen
# nur einen fortlaufenden Salt-Durchlauf statt eines quadratischen Neustarts.
reserviert = [m._stabile_aufgaben_uid(
    "gleich", "" if index == 0 else str(index - 1)) for index in range(1000)]
viele = [{"id": "gleich"} for _index in range(2000)] + [
    {"id": "z-%04d" % index, "uid": uid} for index, uid in enumerate(reserviert)]
vorlage = copy.deepcopy(viele)
original_uid = m._stabile_aufgaben_uid
aufrufe = [0]
try:
    def gezaehlte_uid(kennung, salt=""):
        aufrufe[0] += 1
        return original_uid(kennung, salt)
    m._stabile_aufgaben_uid = gezaehlte_uid
    m._aufgaben_graph_normalisieren(viele)
finally:
    m._stabile_aufgaben_uid = original_uid
assert aufrufe[0] == 3000
assert viele[0]["uid"] == "mag-task-c550891a472d30da@magnolie-organizer"
assert viele[1999]["uid"] == "mag-task-93262cbd5f907f91@magnolie-organizer"
assert [item["uid"] for item in viele[2000:]] == reserviert
zweiter_lauf = copy.deepcopy(vorlage)
m._aufgaben_graph_normalisieren(zweiter_lauf)
assert zweiter_lauf == viele

technische_uids = ["ä", "z", "\U00010000", "a", "é", "e\u0301", "\ue000"]
technischer_graph = [{"id": uid, "uid": uid, "reihenfolge": 0}
                      for uid in reversed(technische_uids)]
m._aufgaben_graph_normalisieren(technischer_graph)
assert [item["uid"] for item in sorted(technischer_graph,
                                       key=lambda item: item["reihenfolge"])] == [
    "a", "e\u0301", "z", "ä", "é", "\ue000", "\U00010000"]

windows_text = m.gesamtarchiv_erzeugen(
    daten, "windows", "1.0.0", erstellt="2026-08-11T12:34:56.0000000+00:00")
assert m.gesamtarchiv_lesen_text(windows_text)["daten"] == json.loads(windows_text)["daten"]

schema_1 = json.loads(text)
schema_1["datenschema"] = 1
assert m.gesamtarchiv_lesen_text(json.dumps(schema_1))["daten"] == json.loads(text)["daten"]

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
legacy_vorher = copy.deepcopy(legacy)
legacy_text = m.gesamtarchiv_erzeugen(legacy, "windows", "1.0.0")
assert '"monthly_weekday"' not in legacy_text
assert m.gesamtarchiv_lesen_text(legacy_text)["daten"]["termine"][0]["wiederholung"]["art"] == "monthly"
assert legacy == legacy_vorher

manipuliert = json.loads(text)
manipuliert["daten"]["termine"][0]["titel"] = "manipuliert"
try:
    m.gesamtarchiv_lesen_text(json.dumps(manipuliert))
    raise AssertionError("Hashmanipulation angenommen")
except RuntimeError:
    pass

unbekanntes_schema = json.loads(text)
unbekanntes_schema["datenschema"] = 4
try:
    m.gesamtarchiv_lesen_text(json.dumps(unbekanntes_schema))
    raise AssertionError("Unbekanntes Datenschema angenommen")
except RuntimeError:
    pass

verschluesselt = m.gesamtarchiv_erzeugen(daten, kennwort="Rosenholz1896")
assert m.gesamtarchiv_lesen_text(verschluesselt, "Rosenholz1896")["daten"] == gelesen["daten"]
try:
    m.gesamtarchiv_lesen_text(verschluesselt, "falsch")
    raise AssertionError("Falsches Kennwort angenommen")
except RuntimeError:
    pass

unbekannt = json.loads(text)
unbekannt["zusaetzlich"] = {"bleibt": True}
assert m.gesamtarchiv_lesen_text(json.dumps(unbekannt))["daten"] == gelesen["daten"]
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
