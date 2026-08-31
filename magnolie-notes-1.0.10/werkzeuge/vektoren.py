#!/usr/bin/env python3
"""Erzeugt Prüfvektoren mit dem *echten* Organizer-Code.

Der Organizer ist ein einzelnes Skript ohne Modulendung; es wird hier als
Modul geladen, ohne die GUI zu starten.
"""
import base64
import importlib.util
import importlib.machinery
import json
import os
import sys

QUELLE = os.environ.get(
    "MAGNOLIE_ORGANIZER_QUELLE",
    os.path.abspath(os.path.join(
        os.path.dirname(__file__), "../../../../../Downloads/Magnolie-GPT/",
        "magnolie-organizer-stamm/bin/magnolie-organizer")))

os.environ.setdefault("MAGNOLIE_NUR_IMPORT", "1")

spec = importlib.util.spec_from_loader(
    "organizer", importlib.machinery.SourceFileLoader("organizer", QUELLE))
organizer = importlib.util.module_from_spec(spec)
sys.modules["organizer"] = organizer
try:
    spec.loader.exec_module(organizer)
except SystemExit:
    pass

O = organizer

# --- feste Schlüssel, damit die Vektoren wiederholbar sind -------------------
GEHEIM_A = bytes(range(32))                    # der Organizer
GEHEIM_B = bytes((i * 7 + 3) % 256 for i in range(32))   # das Handy

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat)


def paar(roh):
    k = X25519PrivateKey.from_private_bytes(roh)
    return (base64.b64encode(roh).decode(),
            base64.b64encode(k.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw)).decode())


geheim_a, oeff_a = paar(GEHEIM_A)
geheim_b, oeff_b = paar(GEHEIM_B)

KENNUNG_A = "organizerabcdefg"
KENNUNG_B = "handyxyz23456789"

aus = {}

# 1. Kanonische Schreibweise -------------------------------------------------
proben = [
    {"b": 1, "a": "zwei"},
    {"text": "Grüße aus München – „Zitat“ & <Zeichen>"},
    {"leer": "", "null": None, "wahr": True, "zahl": -17},
    {"tab": "a\tb\nc\rdef", "hoch": "\U0001F33C Blüte"},
    {"tief": {"z": [1, 2, {"y": "x"}], "a": []}},
    {"anhang": [{"id": "1", "name": "Bild.png", "art": "image", "daten": "data:image/png;base64,AAAA"}]},
]
aus["kanonisch"] = [
    {"wert": p, "erwartet": O._baum_kanonisch(p).decode("utf-8")} for p in proben
]

# 2. Fingerabdruck und Paarungscode -----------------------------------------
aus["fingerabdruck"] = {
    "oeffentlichA": oeff_a, "erwartetA": O.fingerabdruck(oeff_a),
    "oeffentlichB": oeff_b, "erwartetB": O.fingerabdruck(oeff_b),
}
aus["paarungscode"] = {
    "a": oeff_a, "b": oeff_b, "erwartet": O.paarungs_code(oeff_a, oeff_b),
}

# 3. Partnerschlüssel und Auth-Schlüssel ------------------------------------
partner_b = {"kennung": KENNUNG_B, "oeffentlich": oeff_b}
sitz = O._sitzungsschluessel(geheim_a, oeff_b, KENNUNG_A, KENNUNG_B)
aus["partnerschluessel"] = {
    "geheim": geheim_a, "fremd": oeff_b,
    "kennungA": KENNUNG_A, "kennungB": KENNUNG_B,
    "erwartet": base64.b64encode(sitz).decode(),
}
auth = O._fs_auth_schluessel(geheim_a, partner_b, KENNUNG_A)
aus["authschluessel"] = {
    "geheim": geheim_a, "fremd": oeff_b,
    "eigene": KENNUNG_A, "partner": KENNUNG_B,
    "erwartet": base64.b64encode(auth).decode(),
}

# 4. Paarungsdatei Fassung 2 -------------------------------------------------
zustand_a = {
    "kennung": KENNUNG_A, "name": "Schreibtisch", "geheim": geheim_a,
    "oeffentlich": oeff_a, "port": 8737, "an": True, "partner": [],
    "paarungen": [], "paarungenVerbraucht": [],
}
import time
JETZT = int(time.time())   # die Prüfung des Organizers nimmt die echte Uhr
geheimnis = bytes((i * 11 + 5) % 256 for i in range(32))
dokument, einladung = O.baum_paarungsdatei_erzeugen(
    zustand_a, "192.168.1.50", 8737, jetzt=JETZT, geheimnis=geheimnis)
aus["paarungsdatei"] = {
    "dokument": dokument,
    "jetzt": JETZT,
}

# Die Anfrage, die das Handy stellen würde – mit fester Nonce.
zustand_b = {
    "kennung": KENNUNG_B, "name": "Handy", "geheim": geheim_b,
    "oeffentlich": oeff_b, "port": 8737,
}
nonce = bytes((i * 13 + 9) % 256 for i in range(32))
anfrage = O.baum_paarungsanfrage_bauen(zustand_b, dokument, nonce=nonce)
aus["paarungsanfrage"] = {"nonce": base64.b64encode(nonce).decode(), "erwartet": anfrage}

# Die Antwort des Organizers auf genau diese Anfrage.
antwort = O.baum_paarungsanfrage_annehmen(zustand_a, anfrage, "192.168.1.99", jetzt=JETZT)
aus["paarungsantwort"] = {"erwartet": antwort}

# 5. baum-fs1: Start, Antwort, Umschlag, Quittung ---------------------------
partner_a_bei_b = {"kennung": KENNUNG_A, "oeffentlich": oeff_a, "bestaetigt": True}
partner_b_bei_a = {"kennung": KENNUNG_B, "oeffentlich": oeff_b, "bestaetigt": True}

sid = bytes(range(16))
eph_a = X25519PrivateKey.from_private_bytes(bytes((i * 3 + 1) % 256 for i in range(32)))
start, _ = O.fs_start_bauen(zustand_a, partner_b_bei_a, sid=sid, privat=eph_a)
aus["fs_start"] = {"erwartet": start,
                   "sid": base64.b64encode(sid).decode(),
                   "ephemer": base64.b64encode(
                       bytes((i * 3 + 1) % 256 for i in range(32))).decode()}

eph_b = X25519PrivateKey.from_private_bytes(bytes((i * 5 + 2) % 256 for i in range(32)))
zustand_b_voll = dict(zustand_b, partner=[])
fs_antwort, sitzung_b = O.fs_antwort_bauen(zustand_b_voll, partner_a_bei_b, start, privat=eph_b)
aus["fs_antwort"] = {"erwartet": fs_antwort,
                     "ephemer": base64.b64encode(
                         bytes((i * 5 + 2) % 256 for i in range(32))).decode(),
                     "kenc": base64.b64encode(bytes(sitzung_b["kenc"])).decode(),
                     "kack": base64.b64encode(bytes(sitzung_b["kack"])).decode(),
                     "transkript": base64.b64encode(sitzung_b["transkript"]).decode()}

# Der Organizer öffnet seinerseits die Antwort – dieselben Schlüssel?
sitzung_a = O.fs_antwort_oeffnen(zustand_a, partner_b_bei_a, start, fs_antwort, eph_a)
assert bytes(sitzung_a["kenc"]) == bytes(sitzung_b["kenc"])

# Ein Notizumschlag vom Organizer an das Handy.
inhalt = {
    "freigabeId": "f-1", "titel": "Einkauf für Sonntag",
    "text": "Milch\nBrot\nÄpfel – 2 kg", "html": "<div>Milch</div>",
    "anhaenge": [], "geaendert": 1770000123456, "version": 3,
    "quelle": KENNUNG_A, "art": "notiz",
}
mid = base64.b64encode(bytes((i * 17) % 256 for i in range(16))).decode()
nonce12 = bytes((i * 19 + 4) % 256 for i in range(12))
umschlag = O.umschlag_bauen_fs(sitzung_a, KENNUNG_A, KENNUNG_B, inhalt, mid, nonce=nonce12)
aus["fs_umschlag"] = {"inhalt": inhalt, "mid": mid,
                      "nonce": base64.b64encode(nonce12).decode(),
                      "erwartet": umschlag}

quittung = O.fs_ack_bauen(sitzung_b, umschlag)
aus["fs_quittung"] = {"erwartet": quittung}

# 6. baum-1 ------------------------------------------------------------------
umschlag1 = O.umschlag_bauen(geheim_a, partner_b_bei_a, KENNUNG_A, inhalt, 42)
# Nonce ist zufällig; für den Test wird nur die Öffnung geprüft.
aus["baum1"] = {"umschlag": umschlag1, "inhalt": dict(inhalt),
                "geheimB": geheim_b, "oeffentlichA": oeff_a,
                "kennungA": KENNUNG_A, "kennungB": KENNUNG_B, "zaehler": 42}

# 7. Identitäten für die Kotlin-Seite ---------------------------------------
aus["identitaeten"] = {
    "organizer": {"kennung": KENNUNG_A, "name": "Schreibtisch",
                  "geheim": geheim_a, "oeffentlich": oeff_a, "port": 8737},
    "handy": {"kennung": KENNUNG_B, "name": "Handy",
              "geheim": geheim_b, "oeffentlich": oeff_b, "port": 8737},
}

ziel = sys.argv[1] if len(sys.argv) > 1 else "vektoren.json"
with open(ziel, "w", encoding="utf-8") as datei:
    json.dump(aus, datei, ensure_ascii=False, indent=1)
print("Vektoren geschrieben:", ziel)
