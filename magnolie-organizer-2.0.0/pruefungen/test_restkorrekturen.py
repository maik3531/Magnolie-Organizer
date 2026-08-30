import base64
import copy
import importlib.machinery
import importlib.util
import json
import os
import time
from datetime import datetime

import pytest


PROGRAMM = os.path.join(os.path.dirname(__file__), "..", "bin", "magnolie-organizer")
lader = importlib.machinery.SourceFileLoader("magnolie_restkorrekturen", PROGRAMM)
spec = importlib.util.spec_from_loader(lader.name, lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


def test_rdate_vor_start_bleibt_opak_und_startduplikat_wird_ignoriert():
    text = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:rdate-grenze\r\nDTSTART:20260817T090000\r\n"
            "DTEND:20260817T100000\r\nRDATE:20260816T090000\r\nSUMMARY:Probe\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")
    termin = m.ics_lesen(text)["termine"][0]
    assert termin["icsKomplex"]
    assert "RDATE:20260816T090000" in termin["icsRoundtrip"]
    assert "RDATE:20260816T090000" in m.ics_schreiben_termine([termin])

    duplikat = m.ics_lesen(text.replace(
        "RDATE:20260816T090000", "RDATE:20260817T090000"))["termine"][0]
    assert not duplikat["icsKomplex"]
    assert duplikat["icsZusatzDaten"] == []


def test_externes_fehlendes_ende_bleibt_beim_roundtrip_abwesend():
    text = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:ende-fehlt\r\nDTSTART:20260817T090000\r\n"
            "SUMMARY:Probe\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    termin = m.ics_lesen(text)["termine"][0]
    export = m.ics_schreiben_termine([termin])
    ereignis = export.split("BEGIN:VEVENT\r\n", 1)[1].split("END:VEVENT", 1)[0]
    assert termin["icsEndeFehlt"] and not termin["icsNullDauer"]
    assert "DTEND" not in ereignis


def test_externes_null_ende_bleibt_ueber_zwei_roundtrips_explizit():
    text = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:ende-null\r\nDTSTART:20260817T090000\r\n"
            "DTEND:20260817T090000\r\nSUMMARY:Probe\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")
    for _durchlauf in range(2):
        termin = m.ics_lesen(text)["termine"][0]
        assert termin["icsNullDauer"] and not termin["icsEndeFehlt"]
        text = m.ics_schreiben_termine([termin])
        ereignis = text.split("BEGIN:VEVENT\r\n", 1)[1].split("END:VEVENT", 1)[0]
        start = next(zeile for zeile in ereignis.split("\r\n")
                     if zeile.startswith("DTSTART"))
        ende = next(zeile for zeile in ereignis.split("\r\n")
                    if zeile.startswith("DTEND"))
        assert ende.replace("DTEND", "DTSTART", 1) == start


def test_lokaler_termin_erhaelt_standardmaessig_30_minuten_ende():
    lokal = {"uid": "lokal", "datum": "2026-08-17", "zeit": "09:00",
             "titel": "Lokal", "wiederholung": {"art": "none"}}
    export = m.ics_schreiben_termine([lokal])
    ereignis = export.split("BEGIN:VEVENT\r\n", 1)[1].split("END:VEVENT", 1)[0]
    ende = next(zeile for zeile in ereignis.split("\r\n")
                if zeile.startswith("DTEND"))
    assert ende.endswith(":20260817T093000")


def test_gemeinsamer_kontakt_sync_vertrag():
    pfad = os.path.join(os.path.dirname(__file__), "..", "contracts",
                        "kontakt-sync-contract.json")
    gemeinsam = os.path.join(os.path.dirname(__file__), "..", "..", "contracts",
                             "kontakt-sync-contract.json")
    if os.path.isfile(gemeinsam):
        with open(pfad, "rb") as lokal, open(gemeinsam, "rb") as geteilt:
            assert lokal.read() == geteilt.read()
    with open(pfad, encoding="utf-8") as datei:
        vertrag = json.load(datei)
    basis = vertrag["base"]
    limits = vertrag["limits"]

    def mit_vektor(vektor):
        probe = copy.deepcopy(basis)
        ziel = probe
        for teil in vektor["path"][:-1]:
            ziel = ziel[teil]
        ziel[vektor["path"][-1]] = copy.deepcopy(vektor["value"])
        return probe

    assert m.baum_kontakt_sync_pruefen(basis) is basis
    for vektor in vertrag["accepted_vectors"]:
        probe = mit_vektor(vektor)
        assert m.baum_kontakt_sync_pruefen(probe) is probe, vektor["name"]
    for vektor in vertrag["rejected_vectors"]:
        with pytest.raises(RuntimeError):
            m.baum_kontakt_sync_pruefen(mit_vektor(vektor))

    for geburtstag in vertrag["accepted_birthdays"]:
        m.baum_kontakt_sync_pruefen(mit_vektor(
            {"path": ["kontakt", "geburtstag"], "value": geburtstag}))
    for geburtstag in vertrag["rejected_birthdays"]:
        with pytest.raises(RuntimeError):
            m.baum_kontakt_sync_pruefen(mit_vektor(
                {"path": ["kontakt", "geburtstag"], "value": geburtstag}))

    emoji = "😀"
    for path, maximum in ((["freigabeId"], limits["root_id_code_points"]),
                          (["kontakt", "vorname"], limits["text_code_points"]),
                          (["kontakt", "notiz"], limits["note_code_points"])):
        m.baum_kontakt_sync_pruefen(mit_vektor(
            {"path": path, "value": emoji * maximum}))
        with pytest.raises(RuntimeError):
            m.baum_kontakt_sync_pruefen(mit_vektor(
                {"path": path, "value": emoji * maximum + "a"}))
    leer = {"art": "", "wert": ""}
    m.baum_kontakt_sync_pruefen(mit_vektor({
        "path": ["kontakt", "telefone"],
        "value": [leer] * limits["list_items"]}))
    with pytest.raises(RuntimeError):
        m.baum_kontakt_sync_pruefen(mit_vektor({
            "path": ["kontakt", "telefone"],
            "value": [leer] * (limits["list_items"] + 1)}))
    prefix = "data:image/png;base64,"
    anteil = (limits["photo_text_code_points"] - len(prefix)) // 4 * 4
    m.baum_kontakt_sync_pruefen(mit_vektor(
        {"path": ["kontakt", "foto"], "value": prefix + "A" * anteil}))
    with pytest.raises(RuntimeError):
        m.baum_kontakt_sync_pruefen(mit_vektor(
            {"path": ["kontakt", "foto"], "value": prefix + "A" * (anteil + 4)}))


def test_aufgaben_werden_bis_72_stunden_als_verpasst_nachgeholt():
    daten = {"aufgaben": [{"id": "a", "titel": "Abgabe",
                            "faellig": "2026-08-24", "faelligZeit": "08:00",
                            "erinnern": True, "erledigt": False}]}
    nach_15 = m.faellige_aufgaben(daten, datetime(2026, 8, 24, 23, 0))
    assert not nach_15["faellig"]
    assert [item["titel"] for item in nach_15["verpasst"]] == ["Abgabe"]
    assert nach_15["verpasst"][0]["verpasst"] is True
    assert not m.faellige_aufgaben(daten, datetime(2026, 8, 27, 8, 1))["verpasst"]


def test_whitespace_ordnervorwahl_nutzt_standard(monkeypatch, tmp_path):
    class Dialog:
        vorauswahl = None

        def add_buttons(self, *_args):
            pass

        def set_current_folder(self, pfad):
            self.vorauswahl = pfad

        def run(self):
            return m.Gtk.ResponseType.CANCEL

        def destroy(self):
            pass

    dialog = Dialog()
    monkeypatch.setattr(m.Gtk, "FileChooserDialog", lambda **_kwargs: dialog)

    m.Fenster._ordner_waehlen(object(), "Test", "   ", str(tmp_path))

    assert dialog.vorauswahl == str(tmp_path)


def test_fs_sitzung_ueberlebt_falsche_quelle_und_kopf_aber_nicht_falsches_tag():
    zustand = {"an": True, "kennung": "empfaenger", "partner": [
        {"kennung": "sender", "bestaetigt": True}]}
    sitzung = {"sid": "sitzung", "kenc": bytearray(b"K" * 32),
               "kack": bytearray(b"A" * 32), "transkript": b"T" * 32}
    dienst = m.BaumDienst(lambda: zustand, lambda _zustand: None)
    dienst._fs_sitzungen[sitzung["sid"]] = {
        "sitzung": sitzung, "partner": "sender", "adresse": "127.0.0.1",
        "ablauf": time.monotonic() + 60}
    umschlag = m.umschlag_bauen_fs(
        sitzung, "sender", "empfaenger", {"art": "notiz", "text": "Probe"},
        m._fs_b64(b"M" * 16), nonce=b"N" * 12)

    assert dienst.behandeln("/magnolie/v2/nachricht", umschlag, "127.0.0.2")[0] == 403
    assert sitzung["sid"] in dienst._fs_sitzungen and not sitzung.get("verbraucht")
    falscher_kopf = dict(umschlag, an="anderer")
    assert dienst.behandeln("/magnolie/v2/nachricht", falscher_kopf, "127.0.0.1")[0] == 403
    assert sitzung["sid"] in dienst._fs_sitzungen and not sitzung.get("verbraucht")

    ciphertext = bytearray(base64.b64decode(umschlag["daten"]))
    ciphertext[-1] ^= 1
    falsches_tag = dict(umschlag, daten=base64.b64encode(ciphertext).decode("ascii"))
    assert dienst.behandeln("/magnolie/v2/nachricht", falsches_tag, "127.0.0.1")[0] == 403
    assert sitzung["sid"] not in dienst._fs_sitzungen
    assert sitzung["verbraucht"] and bytes(sitzung["kenc"]) == b"\0" * 32


def test_vcard_export_ueberspringt_einzelne_fehler_und_schreibt_atomar(tmp_path,
                                                                     monkeypatch):
    ziel = tmp_path / "kontakte.vcf"
    antworten = []
    probe = type("Probe", (), {
        "_datei_speichern": lambda self, *_args: str(ziel),
        "antwort": lambda self, name, payload: antworten.append((name, payload)),
    })()
    ersetzen = []
    original_replace = m.os.replace
    monkeypatch.setattr(m.os, "replace", lambda quelle, ende: (
        ersetzen.append((quelle, ende)), original_replace(quelle, ende))[1])

    m.Fenster.bei_export(probe, {"art": "vcf-adressen", "daten": [
        {"uid": "gut", "nachname": "Gueltig"},
        {"uid": "kaputt", "nachname": "Kaputt", "geburtstag": "2026-02-30"}]})

    payload = antworten[-1][1]
    assert payload["ok"] and payload["anzahl"] == 1 and payload["uebersprungen"] == 1
    assert ziel.read_text(encoding="utf-8").count("BEGIN:VCARD") == 1
    assert ersetzen and ersetzen[-1][1] == str(ziel)

    antworten.clear()
    m.Fenster.bei_export(probe, {"art": "vcf-adressen", "daten": [
        {"nachname": "Kaputt", "geburtstag": "2026-02-30"}]})
    assert antworten[-1][1]["ok"] is False


def test_vcard_export_ueberspringt_nicht_darstellbare_zeichen():
    bloecke, uebersprungen = m._vcf_bloecke([
        {"nachname": "Gueltig"},
        {"nachname": "Steuer\x00zeichen"},
        {"nachname": "Surrogat\ud800"},
    ])

    assert len(bloecke) == 1 and uebersprungen == 2


def test_vcf_schreiben_leere_eingabe_bleibt_leer():
    assert m.vcf_schreiben([]) == ""
