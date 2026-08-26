import base64
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import urllib.error
import urllib.request

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


PROGRAMM = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
lader = importlib.machinery.SourceFileLoader("magnolie_update_security", str(PROGRAMM))
spec = importlib.util.spec_from_loader(lader.name, lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


def oeffentlicher_testschluessel():
    privat = Ed25519PrivateKey.generate()
    roh = privat.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(roh).decode("ascii")


def test_manifest_weist_entitaeten_vor_xml_parser_ab(monkeypatch):
    aufgerufen = False

    def parser(_text):
        nonlocal aufgerufen
        aufgerufen = True
        raise AssertionError("unsicheres XML erreichte ElementTree")

    monkeypatch.setattr(m.ET, "fromstring", parser)
    xml = "<!DOCTYPE update [<!ENTITY x 'Wert'>]><update><version>&x;</version></update>"
    with pytest.raises(RuntimeError):
        m.update_manifest_pruefen(xml, oeffentlicher_testschluessel())
    assert not aufgerufen


def test_update_umleitung_darf_allowlist_nicht_verlassen(monkeypatch):
    gebaut = []

    class AttrappenOeffner:
        def __init__(self, handler):
            self.handler = handler

        def open(self, _antrag, timeout):
            gebaut.append(timeout)
            return self.handler.redirect_request(
                urllib.request.Request(m.UPDATE_XML), io.BytesIO(), 302, "Found", {},
                "https://example.org/gestohlen.xml")

    monkeypatch.setattr(urllib.request, "build_opener", lambda handler: AttrappenOeffner(handler))
    with pytest.raises(urllib.error.HTTPError):
        m._update_antwort_oeffnen(
            urllib.request.Request(m.UPDATE_XML), 8, m._update_manifest_url_erlaubt)
    assert gebaut == [8]


def test_handbuch_umleitung_bleibt_an_erlaubtes_paket_gebunden(monkeypatch):
    version = "9.8.7"
    paket = m.UPDATE_BASIS + "magnolie-handbuch_9.8.7_all.deb"

    class AttrappenOeffner:
        def __init__(self, handler):
            self.handler = handler

        def open(self, _antrag, timeout):
            return self.handler.redirect_request(
                urllib.request.Request(paket), io.BytesIO(), 302, "Found", {},
                m.UPDATE_BASIS + "magnolie-handbuch_9.8.8_all.deb")

    monkeypatch.setattr(urllib.request, "build_opener", lambda handler: AttrappenOeffner(handler))
    with pytest.raises(urllib.error.HTTPError):
        m._update_antwort_oeffnen(
            urllib.request.Request(paket), 30,
            lambda ziel: m._handbuch_update_url_erlaubt(ziel, version))


def test_telefon_ablageschluessel_grenze_ist_dokumentiert():
    liesmich = (PROGRAMM.parents[1] / "LIESMICH.md").read_text(encoding="utf-8")
    assert "storage.key" in liesmich
    assert "gesamte\nBenutzerverzeichnis lesen" in liesmich
