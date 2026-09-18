import http.client
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading


PFAD = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                    "bin", "magnolie-organizer")
lader = importlib.machinery.SourceFileLoader("magorg_chromium", PFAD)
spec = importlib.util.spec_from_loader("magorg_chromium", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


def test_importauswahl_bevorzugt_webkit_und_sperrt_appimage_fallback():
    assert m.browser_transport_waehlen(True, True, False, "/bin/chromium") == "webkit"
    assert m.browser_transport_waehlen(True, False, False, "/bin/chromium") == "chromium"
    assert m.browser_transport_waehlen(True, False, True, "/bin/chromium") == "fehlt"
    assert m.browser_transport_waehlen(False, False, False, "/bin/chromium") == "fehlt"
    assert m.appimage_laufzeit({"APPIMAGE": "/tmp/x.AppImage"})
    assert not m.appimage_laufzeit({})


def test_chromium_finden_prueft_reihenfolge_und_ausfuehrbarkeit(tmp_path):
    nicht = tmp_path / "chromium"
    nicht.write_text("x", encoding="ascii")
    gut = tmp_path / "google-chrome"
    gut.write_text("#!/bin/sh\n", encoding="ascii")
    gut.chmod(0o700)
    werte = {"chromium": str(nicht), "chromium-browser": None,
             "google-chrome": str(gut)}
    assert m.chromium_finden(werte.get) == os.path.realpath(gut)


def _anfrage(server, methode, pfad, host=None):
    verbindung = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
    verbindung.putrequest(methode, pfad, skip_host=True)
    if host is not None:
        verbindung.putheader("Host", host)
    verbindung.endheaders()
    antwort = verbindung.getresponse()
    daten = antwort.read()
    kopf = dict(antwort.getheaders())
    verbindung.close()
    return antwort.status, daten, kopf


def test_statischer_server_erlaubt_nur_host_token_methode_und_allowlist(tmp_path):
    (tmp_path / "index.html").write_text("sicher", encoding="ascii")
    (tmp_path / "i18n").mkdir()
    (tmp_path / "i18n" / "de.js").write_text("deutsch", encoding="ascii")
    server = m.OrganizerHTTPServer(str(tmp_path), token="a" * 48, sprache="de-DE")
    server.start()
    try:
        host = "127.0.0.1:%d" % server.port
        status, daten, kopf = _anfrage(server, "GET", "/%s/index.html" % server.token,
                                       host)
        assert (status, daten) == (200, b"sicher")
        assert kopf["Cache-Control"] == "no-store"
        status, daten, _kopf = _anfrage(
            server, "GET", "/%s/i18n-active.js" % server.token, host)
        assert (status, daten) == (200, b"deutsch")
        assert "default-src 'none'" in kopf["Content-Security-Policy"]
        assert _anfrage(server, "GET", "/falsch/index.html", host)[0] == 404
        assert _anfrage(server, "GET", "/%s/../index.html" % server.token, host)[0] == 404
        assert _anfrage(server, "GET", "/%s/%%2e%%2e/index.html" % server.token,
                         host)[0] == 404
        assert _anfrage(server, "GET", "/%s/index.html?x=1" % server.token, host)[0] == 404
        assert _anfrage(server, "GET", "/%s/index.html" % server.token,
                         "localhost:%d" % server.port)[0] == 403
        assert _anfrage(server, "GET", "/%s/index.html" % server.token)[0] == 403
        assert _anfrage(server, "POST", "/%s/index.html" % server.token, host)[0] == 405
        assert _anfrage(server, "HEAD", "/%s/index.html" % server.token, host)[0] == 405
    finally:
        server.close()


def test_http_server_loest_systemsprache_auf_und_laesst_sich_aktualisieren(
        tmp_path, monkeypatch):
    (tmp_path / "i18n").mkdir()
    (tmp_path / "i18n" / "de.js").write_text("deutsch", encoding="ascii")
    (tmp_path / "i18n" / "fr.js").write_text("francais", encoding="ascii")
    monkeypatch.setattr(m, "system_sprache", lambda: "de")
    server = m.OrganizerHTTPServer(str(tmp_path), token="b" * 48, sprache="system")
    intern = "/%s/i18n-active.js" % server.token
    assert m.organizer_http_ressource(
        intern, server.token, str(tmp_path), server.sprache)[0].endswith("/de.js")
    transport = object.__new__(m.ChromiumTransport)
    transport.http = server
    transport.sprache = "system"
    transport.sprache_setzen("fr")
    assert transport.sprache == "fr" and server.sprache == "fr"
    assert m.organizer_http_ressource(
        intern, server.token, str(tmp_path), server.sprache)[0].endswith("/fr.js")
    server.server.server_close()


def test_cdp_pipe_framing_ist_fragmentfest_und_nur_json_objekte():
    erste = json.dumps({"id": 1}).encode("ascii") + b"\0" + b'{"met'
    nachrichten, rest = m.cdp_nachrichten(b"", erste)
    assert nachrichten == [{"id": 1}]
    nachrichten, rest = m.cdp_nachrichten(rest, b'hod":"Page.load"}\0')
    assert nachrichten == [{"method": "Page.load"}]
    assert rest == b""
    try:
        m.cdp_nachrichten(b"", b"[]\0")
    except ValueError:
        pass
    else:
        raise AssertionError("Nicht-Objekt wurde als CDP-Nachricht akzeptiert")


def test_chromium_pipe_ziele_ueberleben_close_fds():
    befehl_lesen, befehl_schreiben = os.pipe()
    ereignis_lesen, ereignis_schreiben = os.pipe()

    try:
        prozess = subprocess.Popen(
            [sys.executable, "-c",
             "import os,sys;os.dup2(int(sys.argv[1]),3);"
             "os.dup2(int(sys.argv[2]),4);os.execv(sys.argv[3],sys.argv[3:])",
             str(befehl_lesen), str(ereignis_schreiben), sys.executable, "-c",
             "import os; os.write(4, os.read(3, 4))"],
            close_fds=True,
            pass_fds=(befehl_lesen, ereignis_schreiben))
        os.close(befehl_lesen)
        befehl_lesen = -1
        os.close(ereignis_schreiben)
        ereignis_schreiben = -1
        os.write(befehl_schreiben, b"ping")
        assert os.read(ereignis_lesen, 4) == b"ping"
        assert prozess.wait(timeout=2) == 0
    finally:
        for fd in (befehl_lesen, befehl_schreiben,
                   ereignis_lesen, ereignis_schreiben):
            if fd >= 0:
                os.close(fd)


def test_cdp_abschluss_weckt_alle_sender_ohne_wartelisten_wettlauf():
    freigabe = threading.Event()

    class Leser:
        def read(self, _anzahl):
            freigabe.wait(2)
            return b""
        def close(self):
            freigabe.set()

    class Schreiber:
        def __init__(self):
            self.anzahl = 0
            self.sperre = threading.Lock()
        def write(self, _daten):
            with self.sperre:
                self.anzahl += 1
        def flush(self):
            pass
        def close(self):
            pass

    schreiber = Schreiber()
    client = m.CDPPipeClient(Leser(), schreiber)
    fehler = []

    def senden():
        try:
            client.sende("Page.test", timeout=2)
        except RuntimeError as ausnahme:
            fehler.append(str(ausnahme))

    faeden = [threading.Thread(target=senden) for _ in range(20)]
    for faden in faeden:
        faden.start()
    ende = m.time.monotonic() + 2
    while schreiber.anzahl < len(faeden) and m.time.monotonic() < ende:
        m.time.sleep(.01)
    assert schreiber.anzahl == len(faeden)
    freigabe.set()
    for faden in faeden:
        faden.join(2)
        assert not faden.is_alive()
    assert len(fehler) == len(faeden)
    assert not client._wartend


def test_cdp_bruecke_akzeptiert_nur_exakten_hauptkontext(monkeypatch):
    aufrufe = []

    class SofortGLib:
        @staticmethod
        def idle_add(rueckruf):
            return rueckruf()

    transport = object.__new__(m.ChromiumTransport)
    transport.session = "s1"
    transport.origin = "http://127.0.0.1:1234"
    transport.main_frame = "haupt"
    transport.bruecken_name = "bridge_zufall"
    transport.sprache = "de"
    transport.kontexte = set()
    transport.bei_nachricht = aufrufe.append
    transport.target = None
    monkeypatch.setattr(m, "GLib", SofortGLib)
    transport._ereignis({"sessionId": "s1", "method": "Runtime.executionContextCreated",
        "params": {"context": {"id": 7, "origin": transport.origin,
        "auxData": {"isDefault": True, "frameId": "haupt"}}}})
    transport._ereignis({"sessionId": "s1", "method": "Runtime.executionContextCreated",
        "params": {"context": {"id": 8, "origin": transport.origin,
        "auxData": {"isDefault": True, "frameId": "iframe"}}}})
    for kontext in (8, 9, 7):
        transport._ereignis({"sessionId": "s1", "method": "Runtime.bindingCalled",
            "params": {"name": "bridge_zufall", "executionContextId": kontext,
                       "payload": '{"cmd":"bereit"}'}})
    assert aufrufe == ['{"cmd":"bereit"}']
    script = m.ChromiumTransport._bruecken_script(transport)
    assert ("messageHandlers" in script and "localStorage" not in script and
            "chromium_extern_oeffnen" in script and "stopImmediatePropagation" in script)

    class FakeChromium:
        def __init__(self): self.ausgefuehrt = []
        def evaluate(self, quelltext): self.ausgefuehrt.append(quelltext)

    fake = FakeChromium()
    fenster = type("FakeFenster", (), {
        "_chromium": fake,
        "_organizer_vertraut": lambda _self: True,
    })()
    m.Fenster.sende_js(fenster, "App.trayEinstellungen();")
    assert fake.ausgefuehrt == ["App.trayEinstellungen();"]
