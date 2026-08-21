import http.client
import importlib.machinery
import importlib.util
import json
import os
import tempfile


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
    server = m.OrganizerHTTPServer(str(tmp_path), token="a" * 48)
    server.start()
    try:
        host = "127.0.0.1:%d" % server.port
        status, daten, kopf = _anfrage(server, "GET", "/%s/index.html" % server.token,
                                       host)
        assert (status, daten) == (200, b"sicher")
        assert kopf["Cache-Control"] == "no-store"
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
