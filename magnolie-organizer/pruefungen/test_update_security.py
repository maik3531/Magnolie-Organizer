import base64
from email.message import Message
import importlib.machinery
import importlib.util
import hashlib
import io
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

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


# Ausschließlich synthetische Release-Daten und frisch erzeugte Testschlüssel.
TEST_VERSION = "9.8.7"
TEST_HANDBUCH_VERSION = "7.6.5"
TEST_REGISTRY = ("https://gitlab.com/api/v4/projects/78301901/"
                 "packages/generic/magnolie-desktop/")
TEST_INHALTE = {"deb": b"synthetisches Organizer-DEB",
                "appimage/url": b"synthetisches AppImage",
                "manual/linux/deb": b"synthetisches Handbuch-DEB",
                "windows/url": b"synthetischer Windows-Installer"}


def signiertes_release(ablage="registry", aenderungen=None):
    basis = (m.UPDATE_BASIS if ablage == "raw" else
             TEST_REGISTRY + TEST_VERSION + "/")
    windows_url = basis + "Magnolie-Organizer-Windows-%s-Setup-x64.exe" % TEST_VERSION
    windows_sha = hashlib.sha256(TEST_INHALTE["windows/url"]).hexdigest()
    felder = {
        "version": TEST_VERSION,
        "deb": basis + "magnolie-organizer_%s_all.deb" % TEST_VERSION,
        "sha256": hashlib.sha256(TEST_INHALTE["deb"]).hexdigest(),
        "appimage/architecture": "x86_64",
        "appimage/url": basis + "Magnolie-Organizer-%s-x86_64.AppImage" % TEST_VERSION,
        "appimage/sha256": hashlib.sha256(TEST_INHALTE["appimage/url"]).hexdigest(),
        "manual/version": TEST_HANDBUCH_VERSION,
        "manual/linux/deb": basis + "magnolie-handbuch_%s_all.deb" % TEST_HANDBUCH_VERSION,
        "manual/linux/sha256": hashlib.sha256(TEST_INHALTE["manual/linux/deb"]).hexdigest(),
        "manual/windows/url": windows_url,
        "manual/windows/sha256": windows_sha,
        "windows/version": TEST_VERSION,
        "windows/url": windows_url,
        "windows/sha256": windows_sha,
    }
    felder.update(aenderungen or {})
    privat = Ed25519PrivateKey.generate()
    oeffentlich = base64.b64encode(privat.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")
    nachricht = m.update_signatur_nachricht(
        felder["version"], felder["deb"], felder["sha256"],
        felder["appimage/url"], felder["appimage/sha256"],
        felder["manual/version"], felder["manual/linux/deb"],
        felder["manual/linux/sha256"], felder["manual/windows/url"],
        felder["manual/windows/sha256"], felder["windows/version"],
        felder["windows/url"], felder["windows/sha256"])
    felder["signature"] = base64.b64encode(privat.sign(nachricht)).decode("ascii")
    wurzel = ET.Element("update")
    for pfad, wert in felder.items():
        knoten = wurzel
        for teil in pfad.split("/"):
            kind = knoten.find(teil)
            knoten = ET.SubElement(knoten, teil) if kind is None else kind
        knoten.text = wert
    return ET.tostring(wurzel, encoding="unicode"), oeffentlich


def netz_attrappe(monkeypatch, inhalt, umleitung=None, status=302):
    """Benutzt den echten Redirect-Handler, ohne eine Netzverbindung zu öffnen."""
    anfragen = []

    class AttrappenOeffner:
        def __init__(self, handler):
            self.handler = handler
            handler.add_parent(self)

        def open(self, antrag, timeout):
            anfragen.append(antrag.full_url)
            antrag.timeout = timeout
            if umleitung is not None and len(anfragen) == 1:
                headers = Message()
                headers["Location"] = umleitung
                return getattr(self.handler, "http_error_%s" % status)(
                    antrag, io.BytesIO(), status, "Found", headers)
            return PaketAntwort(inhalt, len(inhalt))

    monkeypatch.setattr(urllib.request, "build_opener", AttrappenOeffner)
    return anfragen


@pytest.mark.parametrize("ablage", ("raw", "registry"))
@pytest.mark.parametrize("artifact", ("deb", "appimage"))
def test_signiertes_release_laesst_nur_sein_paket_herunterladen(
        tmp_path, monkeypatch, ablage, artifact):
    xml, schluessel = signiertes_release(ablage)
    if artifact == "appimage":
        ziel = tmp_path / "Magnolie-Organizer.AppImage"
        ziel.write_bytes(b"vorhandenes synthetisches AppImage")
        ziel.chmod(0o700)
        monkeypatch.setenv("APPIMAGE", str(ziel))
    else:
        monkeypatch.delenv("APPIMAGE", raising=False)
    manifest_abrufe = []
    geprueft = m.update_pruefen(
        lambda url: manifest_abrufe.append(url) or xml, schluessel)
    assert geprueft["ok"] and not geprueft["aktuell"]
    assert manifest_abrufe == [m.UPDATE_XML]
    handbuch = {"version": TEST_HANDBUCH_VERSION,
                "url": ET.fromstring(xml).findtext("manual/linux/deb"),
                "sha256": hashlib.sha256(TEST_INHALTE["manual/linux/deb"]).hexdigest(),
                "platform": "linux"}
    if ablage == "registry":
        handbuch["releaseVersion"] = TEST_VERSION
    assert geprueft["handbuch"] == handbuch
    feld = "appimage/url" if artifact == "appimage" else "deb"
    inhalt = TEST_INHALTE[feld]
    anfragen = netz_attrappe(monkeypatch, inhalt)

    ergebnis = m.update_herunterladen(datenbasis=str(tmp_path))

    assert ergebnis["ok"]
    assert ergebnis["artifact"] == artifact
    assert anfragen == [ET.fromstring(xml).findtext(feld)]
    assert m._VORBEREITETES_UPDATE["url"] == geprueft["url"]
    assert Path(m._VORBEREITETES_UPDATE["pfad"]).read_bytes() == inhalt


@pytest.mark.parametrize("ablage", ("raw", "registry"))
@pytest.mark.parametrize("art", ("deb", "appimage", "manual"))
def test_paketadressen_akzeptieren_keine_url_aliase(ablage, art):
    xml, _ = signiertes_release(ablage)
    pfad = {"deb": "deb", "appimage": "appimage/url", "manual": "manual/linux/deb"}[art]
    url = ET.fromstring(xml).findtext(pfad)
    basis, dateiname = url.rsplit("/", 1)
    pruefer = {
        "deb": lambda ziel: m._organizer_deb_update_url_erlaubt(ziel, TEST_VERSION),
        "appimage": lambda ziel: m._appimage_update_url_erlaubt(ziel, TEST_VERSION),
        "manual": lambda ziel: m._handbuch_update_url_erlaubt(
            ziel, TEST_HANDBUCH_VERSION, TEST_VERSION),
    }[art]
    assert pruefer(url)
    unzulaessig = (
        url.replace("https://", "http://"),
        url.replace("gitlab.com/", "gitlab.com.example.org/"),
        url.replace("gitlab.com/", "user@gitlab.com/"),
        url.replace("gitlab.com/", "gitlab.com:443/"),
        url + "?download=1", url + "?", url + "#download", url + "#",
        url + "/", " " + url, url + " ", url.replace("gitlab", "git\tlab", 1),
        basis + "/./" + dateiname,
        basis + "/anderer-ordner/../" + dateiname,
        basis + "//" + dateiname,
        basis + "/anderer-ordner/" + dateiname,
        basis + "/%2e/" + dateiname,
        basis + "/%" + format(ord(dateiname[0]), "02x") + dateiname[1:],
        basis + "/anderes-paket.deb",
        url.replace(TEST_VERSION, "9.8.8").replace(TEST_HANDBUCH_VERSION, "7.6.6"),
    )
    for ziel in unzulaessig:
        assert not pruefer(ziel), ziel
    if ablage == "registry":
        for ziel in (
                url.replace("/78301901/", "/78301902/"),
                url.replace("/78301901/", "/maik3531%2Fmint-forgs/"),
                url.replace("/magnolie-desktop/", "/magnolie-notes-fdroid-reference/"),
                url.replace("/" + TEST_VERSION + "/", "/9.8.8/"),
                url.replace("/" + TEST_VERSION + "/", "/9%2e8%2e7/")):
            assert not pruefer(ziel), ziel


@pytest.mark.parametrize("feld", ("deb", "appimage/url", "manual/linux/deb"))
@pytest.mark.parametrize("fehler", ("projekt", "paket", "version", "datei"))
def test_signatur_erweitert_die_registry_adressfreigabe_nicht(feld, fehler):
    xml, _ = signiertes_release()
    url = ET.fromstring(xml).findtext(feld)
    falsch = {
        "projekt": url.replace("/78301901/", "/78301902/"),
        "paket": url.replace("/magnolie-desktop/", "/anderes-programm/"),
        "version": url.replace("/" + TEST_VERSION + "/", "/9.8.8/"),
        "datei": url.rsplit("/", 1)[0] + "/falsches-paket.deb",
    }[fehler]
    xml, schluessel = signiertes_release(aenderungen={feld: falsch})
    if feld == "deb":
        with pytest.raises(RuntimeError):
            m.update_manifest_pruefen(xml, schluessel)
    else:
        geprueft = m.update_manifest_pruefen(xml, schluessel)
        assert geprueft["appimage" if feld == "appimage/url" else "handbuch"] == {}
        if feld == "manual/linux/deb":
            assert geprueft["handbuchFehler"]


@pytest.mark.parametrize("ablage", ("raw", "registry"))
def test_fremde_appimage_architektur_sperrt_das_deb_update_nicht(ablage):
    xml, _ = signiertes_release(ablage)
    url = ET.fromstring(xml).findtext("appimage/url").replace("x86_64", "aarch64")
    xml, schluessel = signiertes_release(ablage, {
        "appimage/architecture": "aarch64", "appimage/url": url})
    geprueft = m.update_manifest_pruefen(xml, schluessel)
    assert geprueft["url"] == ET.fromstring(xml).findtext("deb")
    assert geprueft["appimage"] == {}


@pytest.mark.parametrize("feld", (
    "version", "deb", "sha256", "appimage/url", "appimage/sha256",
    "manual/version", "manual/linux/deb", "manual/linux/sha256",
    "manual/windows/url", "manual/windows/sha256", "windows/version",
    "windows/url", "windows/sha256"))
def test_registry_manifest_bindet_alle_plattformfelder_an_die_signatur(feld):
    xml, schluessel = signiertes_release()
    wurzel = ET.fromstring(xml)
    knoten = wurzel.find(feld)
    if feld.endswith("sha256"):
        knoten.text = "00" * 32
    elif feld.endswith("version"):
        knoten.text = "9.8.8"
    else:
        knoten.text = m.UPDATE_BASIS + knoten.text.rsplit("/", 1)[-1]
    with pytest.raises(RuntimeError, match=re.escape(m._(
            "The update information has an invalid signature."))):
        m.update_manifest_pruefen(ET.tostring(wurzel, encoding="unicode"), schluessel)


def test_registry_handbuch_bindet_hauptversion_bis_zum_hashdownload(
        tmp_path, monkeypatch):
    xml, schluessel = signiertes_release()
    geprueft = m.update_pruefen(lambda _url: xml, schluessel)
    handbuch = geprueft["handbuch"]
    assert handbuch["version"] == TEST_HANDBUCH_VERSION
    assert handbuch["releaseVersion"] == TEST_VERSION
    assert m._LETZTES_HANDBUCH_MANIFEST == handbuch
    monkeypatch.setattr(m.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(m.shutil, "which",
                        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
    anfragen = netz_attrappe(monkeypatch, TEST_INHALTE["manual/linux/deb"])
    gestartet = []

    ergebnis = m.handbuch_paket_herunterladen(
        handbuch["url"], handbuch["version"], handbuch["sha256"],
        starter=gestartet.append)

    assert ergebnis["ok"]
    assert anfragen == [handbuch["url"]]
    assert gestartet == [["/usr/bin/xdg-open", ergebnis["pfad"]]]
    assert Path(ergebnis["pfad"]).read_bytes() == TEST_INHALTE["manual/linux/deb"]
    # Auch der ältere Browserweg darf nur die zuletzt signierte Registryadresse öffnen.
    assert m.handbuch_paket_oeffnen(handbuch["url"], gestartet.append)["ok"]
    assert not m.handbuch_paket_oeffnen(
        handbuch["url"].replace("/" + TEST_VERSION + "/", "/9.8.8/"),
        gestartet.append)["ok"]
    m._LETZTES_HANDBUCH_MANIFEST = dict(handbuch, releaseVersion="9.8.8")
    assert not m.handbuch_paket_herunterladen(
        handbuch["url"], handbuch["version"], handbuch["sha256"],
        starter=gestartet.append)["ok"]
    assert anfragen == [handbuch["url"]]


@pytest.mark.parametrize("art", ("deb", "appimage", "manual"))
@pytest.mark.parametrize("status", (301, 302, 303, 307, 308))
def test_registry_redirects_bleiben_an_exakte_signierte_adresse_gebunden(
        tmp_path, monkeypatch, art, status):
    xml, schluessel = signiertes_release()
    geprueft = m.update_pruefen(lambda _url: xml, schluessel)
    feld = {"deb": "deb", "appimage": "appimage/url", "manual": "manual/linux/deb"}[art]
    url = ET.fromstring(xml).findtext(feld)
    basis, dateiname = url.rsplit("/", 1)
    monkeypatch.setattr(m.tempfile, "tempdir", str(tmp_path))
    for ziel in (m.UPDATE_BASIS + dateiname,
                 url.replace("/" + TEST_VERSION + "/", "/9.8.8/"),
                 "https://example.org/" + dateiname,
                 basis + "/./" + dateiname,
                 "./" + dateiname,
                 basis + "/%" + format(ord(dateiname[0]), "02x") + dateiname[1:],
                 url + "?download=1", url + "#download"):
        anfragen = netz_attrappe(monkeypatch, TEST_INHALTE[feld], ziel, status)
        if art == "manual":
            h = geprueft["handbuch"]
            ergebnis = m.handbuch_paket_herunterladen(h["url"], h["version"], h["sha256"])
            assert not ergebnis["ok"]
        else:
            freigabe = {"version": TEST_VERSION, "url": url, "artifact": art,
                        "sha256": hashlib.sha256(TEST_INHALTE[feld]).hexdigest()}
            with pytest.raises(urllib.error.HTTPError):
                m._update_stream_speichern(freigabe, str(tmp_path), ".test")
        assert anfragen == [url]
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("form", ("vollstaendig", "absoluter_pfad", "dateiname"))
@pytest.mark.parametrize("status", (301, 302, 303, 307, 308))
def test_kanonische_redirects_koennen_nur_dieselbe_registry_datei_erreichen(
        tmp_path, monkeypatch, form, status):
    xml, _ = signiertes_release()
    url = ET.fromstring(xml).findtext("deb")
    ziel = {"vollstaendig": url,
            "absoluter_pfad": url.removeprefix("https://gitlab.com"),
            "dateiname": url.rsplit("/", 1)[-1]}[form]
    inhalt = TEST_INHALTE["deb"]
    anfragen = netz_attrappe(monkeypatch, inhalt, ziel, status)
    freigabe = {"version": TEST_VERSION, "url": url, "artifact": "deb",
                "sha256": hashlib.sha256(inhalt).hexdigest()}

    pfad = m._update_stream_speichern(freigabe, str(tmp_path), ".deb")

    assert anfragen == [url, url]
    assert Path(pfad).read_bytes() == inhalt


def test_raw_paket_erlaubt_keine_stille_umleitung_zur_registry(tmp_path, monkeypatch):
    inhalt = TEST_INHALTE["deb"]
    freigabe = manifest("deb", inhalt)
    registry_url = TEST_REGISTRY + TEST_VERSION + "/" + freigabe["url"].rsplit("/", 1)[-1]
    anfragen = netz_attrappe(monkeypatch, inhalt, registry_url)
    with pytest.raises(urllib.error.HTTPError):
        m._update_stream_speichern(freigabe, str(tmp_path), ".deb")
    assert anfragen == [freigabe["url"]]
    assert list(tmp_path.iterdir()) == []


def test_manifestadresse_bleibt_exakt_raw(monkeypatch):
    assert m._update_manifest_url_erlaubt(m.UPDATE_XML)
    for url in (TEST_REGISTRY + TEST_VERSION + "/update.xml",
                m.UPDATE_XML + "?download=1", m.UPDATE_XML + "#download",
                m.UPDATE_XML.replace("/update.xml", "/./update.xml"),
                " " + m.UPDATE_XML, m.UPDATE_XML + " "):
        assert not m._update_manifest_url_erlaubt(url)
    anfragen = netz_attrappe(monkeypatch, b"<update/>",
                            TEST_REGISTRY + TEST_VERSION + "/update.xml")
    with pytest.raises(RuntimeError):
        m._update_text_holen()
    assert anfragen == [m.UPDATE_XML]
