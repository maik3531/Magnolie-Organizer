#!/usr/bin/env python3
import json
import os
import stat
import tempfile
from importlib.machinery import SourceFileLoader


PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
m = SourceFileLoader("magnolie_cloud_backup", PFAD).load_module()


with tempfile.TemporaryDirectory(prefix="magnolie-cloud-backup-") as tmp:
    datenordner = os.path.join(tmp, "daten")
    cloudordner = os.path.join(tmp, "cloud")
    os.makedirs(datenordner)
    quelldatei = os.path.join(datenordner, "daten.json")
    daten = {"version": 6, "termine": [], "notizen": [{"titel": "Portable"}]}
    with open(quelldatei, "w", encoding="utf-8") as datei:
        json.dump(daten, datei)

    altes_datenverzeichnis = m.daten_verzeichnis
    altes_datendatei = m.daten_datei
    m.daten_verzeichnis = lambda: datenordner
    m.daten_datei = lambda: quelldatei
    try:
        lokal = m.lege_sicherung_an()
        erstes = m.lege_sicherung_an(cloudordner, kennwort="Rosenholz1896")
        zweites = m.lege_sicherung_an(cloudordner, kennwort="Rosenholz1896")
    finally:
        m.daten_verzeichnis = altes_datenverzeichnis
        m.daten_datei = altes_datendatei

    assert lokal.endswith(".json")
    assert erstes != zweites
    assert erstes.endswith(".magnolie") and zweites.endswith(".magnolie")
    assert stat.S_IMODE(os.stat(erstes).st_mode) == 0o600
    with open(erstes, encoding="utf-8") as datei:
        gespeichert = datei.read()
    assert m.ist_verschluesselt(gespeichert)
    assert "Portable" not in gespeichert
    gelesen = m.gesamtarchiv_lesen(erstes, "Rosenholz1896")
    assert gelesen["plattform"] == "linux"
    assert gelesen["appversion"] == m.PROGRAMM_FASSUNG
    assert gelesen["daten"] == daten
    assert m.sicherung_lesen(erstes, "Rosenholz1896")["daten"] == daten
    assert not any(name.startswith(".magnolie-") for name in os.listdir(cloudordner))

print("Cloud-Sicherungsvertrag: ok")
