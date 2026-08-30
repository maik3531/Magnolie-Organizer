import base64
import importlib.machinery
import importlib.util
import hashlib
import io
import os
from pathlib import Path
import re
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
    meldung = m._("The update information is unreadable.")
    with pytest.raises(RuntimeError, match=re.escape(meldung)):
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


class PaketAntwort:
    def __init__(self, inhalt, laenge=None):
        self._strom = io.BytesIO(inhalt)
        self.headers = {}
        if laenge is not None:
            self.headers["Content-Length"] = str(laenge)

    def read(self, groesse=-1):
        return self._strom.read(groesse)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def manifest(artifact, inhalt, version="9.8.7"):
    if artifact == "appimage":
        url = m.UPDATE_BASIS + "Magnolie-Organizer-%s-x86_64.AppImage" % version
    else:
        url = m.UPDATE_BASIS + "magnolie-organizer_%s_all.deb" % version
    return {"version": version, "url": url,
            "sha256": hashlib.sha256(inhalt).hexdigest(), "artifact": artifact}


def test_download_ist_parameterlos_an_vollstaendiges_manifest_gebunden(tmp_path):
    inhalt = b"signiertes deb"
    freigabe = manifest("deb", inhalt)
    m._LETZTES_UPDATE_MANIFEST = dict(freigabe)

    ergebnis = m.update_herunterladen(
        lambda antrag, timeout: PaketAntwort(inhalt, len(inhalt)),
        datenbasis=str(tmp_path))

    assert ergebnis == {"ok": True, "fehler": "", "version": "9.8.7",
                        "artifact": "deb", "bereit": True}
    assert {k: m._VORBEREITETES_UPDATE[k] for k in freigabe} == freigabe
    assert Path(m._VORBEREITETES_UPDATE["pfad"]).read_bytes() == inhalt
    m._LETZTES_UPDATE_MANIFEST = dict(freigabe, sha256="00" * 32)
    assert not m.update_installieren()["ok"]


def test_hashfehler_loescht_tempdatei(tmp_path):
    inhalt = b"veraendert"
    freigabe = manifest("deb", b"erwartet")
    m._LETZTES_UPDATE_MANIFEST = freigabe

    ergebnis = m.update_herunterladen(
        lambda antrag, timeout: PaketAntwort(inhalt), datenbasis=str(tmp_path))

    assert not ergebnis["ok"]
    update_ordner = tmp_path / m.PROGRAMM_NAME / "updates"
    assert list(update_ordner.iterdir()) == []
    assert m._VORBEREITETES_UPDATE == {}


def test_content_length_und_stream_haben_festes_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "UPDATE_PAKET_MAXIMUM", 4)
    freigabe = manifest("deb", b"12345")
    m._LETZTES_UPDATE_MANIFEST = freigabe
    zu_gross = m.update_herunterladen(
        lambda antrag, timeout: PaketAntwort(b"", 5), datenbasis=str(tmp_path))
    assert not zu_gross["ok"]

    m._LETZTES_UPDATE_MANIFEST = freigabe
    ohne_header = m.update_herunterladen(
        lambda antrag, timeout: PaketAntwort(b"12345"), datenbasis=str(tmp_path))
    assert not ohne_header["ok"]
    assert list((tmp_path / m.PROGRAMM_NAME / "updates").iterdir()) == []


def test_organizer_download_prueft_jedes_umleitungsziel(tmp_path, monkeypatch):
    freigabe = manifest("deb", b"paket")

    class AttrappenOeffner:
        def __init__(self, handler):
            self.handler = handler

        def open(self, antrag, timeout):
            return self.handler.redirect_request(
                antrag, io.BytesIO(), 302, "Found", {},
                m.UPDATE_BASIS + "magnolie-organizer_9.8.8_all.deb")

    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda handler: AttrappenOeffner(handler))
    with pytest.raises(urllib.error.HTTPError):
        m._update_stream_speichern(freigabe, str(tmp_path), ".deb")
    assert list(tmp_path.iterdir()) == []


def test_deb_installation_oeffnet_nur_gepruefte_lokale_datei(tmp_path, monkeypatch):
    inhalt = b"deb paket"
    freigabe = manifest("deb", inhalt)
    paket = tmp_path / "magnolie-organizer-9.8.7.deb"
    paket.write_bytes(inhalt)
    m._LETZTES_UPDATE_MANIFEST = dict(freigabe)
    m._VORBEREITETES_UPDATE = dict(freigabe, pfad=str(paket), ziel=str(paket))
    neustart = tmp_path / "magnolie-organizer"
    neustart.write_text("#!/bin/sh\n", encoding="ascii")
    neustart.chmod(0o700)
    monkeypatch.setattr(m, "_update_neustart_befehl",
                        lambda artifact, appimage_ziel="": [str(neustart)])
    monkeypatch.setattr(m.shutil, "which",
                        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
    geoeffnet = []
    helper = []

    ergebnis = m.update_installieren(geoeffnet.append, helper.append)

    assert ergebnis["ok"] and ergebnis["bereitZumBeenden"]
    assert geoeffnet == [["/usr/bin/xdg-open", str(paket)]]
    assert len(helper) == 1 and helper[0][0] == os.path.realpath(os.sys.executable)
    assert "--update-helper" in helper[0]


def test_appimage_wird_am_laufenden_ort_atomar_ersetzt(tmp_path):
    alt = b"altes appimage"
    neu = b"neues signiertes appimage"
    appimage = tmp_path / "Magnolie-Organizer.AppImage"
    appimage.write_bytes(alt)
    appimage.chmod(0o700)
    freigabe = manifest("appimage", neu)
    m._LETZTES_UPDATE_MANIFEST = dict(freigabe)

    download = m.update_herunterladen(
        lambda antrag, timeout: PaketAntwort(neu), appimage_pfad=str(appimage))
    helper = []
    installation = m.update_installieren(helper_starter=helper.append)

    assert download["ok"] and installation["ok"]
    assert appimage.read_bytes() == neu
    assert os.access(appimage, os.X_OK)
    assert not any(p.name.startswith(".magnolie-update-") for p in tmp_path.iterdir())
    assert (tmp_path / "Magnolie-Organizer.AppImage.magnolie-update-backup").read_bytes() == alt
    assert helper and "--update-helper" in helper[0]


def test_appimage_symlink_und_fremder_tempstart_werden_abgewiesen(tmp_path):
    echt = tmp_path / "echt.AppImage"
    echt.write_bytes(b"alt")
    echt.chmod(0o700)
    link = tmp_path / "link.AppImage"
    link.symlink_to(echt)
    m._LETZTES_UPDATE_MANIFEST = manifest("appimage", b"neu")

    ergebnis = m.update_herunterladen(
        lambda antrag, timeout: PaketAntwort(b"neu"), appimage_pfad=str(link))

    assert not ergebnis["ok"]
    assert echt.read_bytes() == b"alt"


def test_appimage_in_beschreibbarem_elternordner_wird_abgewiesen(tmp_path):
    ordner = tmp_path / "unsicher"
    ordner.mkdir(mode=0o777)
    ordner.chmod(0o777)
    appimage = ordner / "Magnolie.AppImage"
    appimage.write_bytes(b"alt")
    appimage.chmod(0o700)
    m._LETZTES_UPDATE_MANIFEST = manifest("appimage", b"neu")

    ergebnis = m.update_herunterladen(
        lambda antrag, timeout: PaketAntwort(b"neu"), appimage_pfad=str(appimage))

    assert not ergebnis["ok"]
    assert appimage.read_bytes() == b"alt"


def test_appimage_helper_rollt_bei_fehlgeschlagenem_neustart_zurueck(
        tmp_path, monkeypatch):
    appimage = tmp_path / "Magnolie.AppImage"
    appimage.write_bytes(b"neu")
    appimage.chmod(0o700)
    sicherung = tmp_path / "Magnolie.AppImage.magnolie-update-backup"
    sicherung.write_bytes(b"alt")
    sicherung.chmod(0o700)
    gestartet = []
    monkeypatch.setattr(m.os, "kill", lambda pid, signal: (_ for _ in ()).throw(
        ProcessLookupError()))

    def starten(argumente):
        if not gestartet:
            gestartet.append("fehlgeschlagen")
            raise OSError("nicht startbar")
        gestartet.append(argumente)

    status = m._update_helper_lauf(
        "appimage", "9.8.7", 999999, [str(appimage)], zeitlimit=1,
        starter=starten, schlafer=lambda sekunden: None,
        appimage_sicherung=str(sicherung))

    assert status == 1
    assert gestartet == ["fehlgeschlagen", [str(appimage)]]
    assert appimage.read_bytes() == b"alt"
    assert not sicherung.exists()


def test_appimage_helper_rollt_bei_beenden_timeout_zurueck(tmp_path, monkeypatch):
    appimage = tmp_path / "Magnolie.AppImage"
    appimage.write_bytes(b"neu")
    appimage.chmod(0o700)
    sicherung = tmp_path / "Magnolie.AppImage.magnolie-update-backup"
    sicherung.write_bytes(b"alt")
    sicherung.chmod(0o700)
    zeiten = iter((0, 0, 2))
    monkeypatch.setattr(m.time, "monotonic", lambda: next(zeiten))
    monkeypatch.setattr(m.os, "kill", lambda pid, signal: None)

    status = m._update_helper_lauf(
        "appimage", "9.8.7", 999999, [str(appimage)], zeitlimit=1,
        schlafer=lambda sekunden: None, appimage_sicherung=str(sicherung))

    assert status == 1
    assert appimage.read_bytes() == b"alt"
    assert not sicherung.exists()


def test_helper_startet_nach_abbruch_alte_app_genau_einmal(tmp_path, monkeypatch):
    appimage = tmp_path / "Magnolie.AppImage"
    appimage.write_bytes(b"app")
    appimage.chmod(0o700)
    gestartet = []
    monkeypatch.setattr(m.os, "kill", lambda pid, signal: (_ for _ in ()).throw(
        ProcessLookupError()))

    status = m._update_helper_lauf(
        "appimage", "9.8.7", 999999, [str(appimage)],
        zeitlimit=1, starter=gestartet.append, schlafer=lambda sekunden: None)

    assert status == 0
    assert gestartet == [[str(appimage)]]


def test_deb_helper_startet_bei_installations_timeout_bisherige_app(monkeypatch):
    neustart = ["/usr/bin/magnolie-organizer"]
    gestartet = []
    zeiten = iter((0, 0, 1, 3))
    monkeypatch.setattr(m, "_update_neustart_befehl",
                        lambda artifact, appimage_ziel="": neustart)
    monkeypatch.setattr(m.time, "monotonic", lambda: next(zeiten))
    monkeypatch.setattr(m.os, "kill", lambda pid, signal: (_ for _ in ()).throw(
        ProcessLookupError()))

    def nicht_installiert(*_args, **_kwargs):
        raise OSError("abgebrochen")

    status = m._update_helper_lauf(
        "deb", "9.8.7", 999999, neustart, zeitlimit=3,
        abfrager=nicht_installiert, starter=gestartet.append,
        schlafer=lambda sekunden: None)

    assert status == 1
    assert gestartet == [neustart]
