"""Issue #42: pinned Internet requests complete only after authenticated acceptance."""
import copy
import json
import threading

import pytest
from test_background_reliability import app as m, private


def identity(state):
    return {key: state[key] for key in ("kennung", "name", "oeffentlich", "port")}


class SharedRuntime:
    _baum_weitergabe_aktuell = m.Fenster._baum_weitergabe_aktuell
    _baum_weitergabe_angebot = m.Fenster._baum_weitergabe_angebot
    _baum_weitergeben = m.Fenster._baum_weitergeben
    _baum_weitergabe_annehmen = m.Fenster._baum_weitergabe_annehmen

    def __init__(self, state, path):
        self.state, self.path, self.events = state, path, []
        self._baum_sperre = threading.RLock()
        self._gesperrt = False

    def _baum_zustand(self): return self.state
    def _baum_sichern(self, state): m.atomar_text_schreiben(str(self.path), json.dumps(state))
    def _baum_stand_melden(self): pass
    def _baum_kontakt_faehigkeiten_anmelden(self, peer): pass
    def antwort(self, name, payload): self.events.append((name, payload))


@pytest.mark.parametrize("accept", [True, False])
def test_three_computers_share_over_tcp_and_work_without_laptop(private, monkeypatch, accept):
    monkeypatch.setattr(m.BaumBluetoothDienst, "starten", lambda self: False)
    monkeypatch.setattr(m, "baum_mdns_veroeffentlichen", lambda *a: None)
    states = [m.baum_schluessel_erzeugen(name) for name in ("Home", "Laptop", "Office")]
    home, laptop, office = states
    runtimes = [SharedRuntime(state, private / (state["name"] + ".json")) for state in states]
    received = []
    services = [m.BaumDienst(runtime._baum_zustand, runtime._baum_sichern, port=0,
        bei_nachricht=lambda peer, content: received.append(content), sperre=runtime._baum_sperre) for runtime in runtimes]
    try:
        for state, service in zip(states, services):
            state["an"] = True
            assert service.starten()
            state["port"] = service.port
        for own, remote in ((home, laptop), (laptop, home), (laptop, office), (office, laptop)):
            peer = m.baum_partner_aufnehmen(own, remote["name"], remote["kennung"], remote["oeffentlich"], "127.0.0.1", remote["port"])
            peer["bestaetigt"] = True
        m.baum_weitergabe_erlauben(home, laptop["kennung"], laptop["oeffentlich"], True)
        home_peer = m.baum_partner(laptop, home["kennung"])
        home_peer.update(fernAdresse="127.0.0.1", fernPort=home["port"], port=1)
        runtimes[1]._baum_weitergeben(home["kennung"], office["kennung"], m.fingerabdruck(home["oeffentlich"]), m.fingerabdruck(office["oeffentlich"]))
        assert runtimes[1].events[-1][1]["ok"], runtimes[1].events
        assert len(office["partner"]) == 1
        assert len(office["weitergabeAngebote"]) == 1
        assert json.loads(runtimes[2].path.read_text())["weitergabeAngebote"] == office["weitergabeAngebote"]
        runtimes[1]._baum_weitergeben(home["kennung"], office["kennung"], m.fingerabdruck(home["oeffentlich"]), m.fingerabdruck(office["oeffentlich"]))
        assert len(office["weitergabeAngebote"]) == 1
        runtimes[2]._baum_weitergabe_annehmen(office["weitergabeAngebote"][0]["id"], accept)
        if not accept:
            runtimes[2].state = json.loads(runtimes[2].path.read_text())
            runtimes[1].state = json.loads(runtimes[1].path.read_text())
            runtimes[1]._baum_weitergeben(home["kennung"], office["kennung"], m.fingerabdruck(home["oeffentlich"]), m.fingerabdruck(office["oeffentlich"]))
            assert not runtimes[1].events[-1][1]["ok"]
            assert runtimes[2].state["weitergabeAngebote"] == [], "restart/retry must not recreate a rejected offer"
            assert len(home["partner"]) == 1
            return
        assert runtimes[2].events[-1][1]["ok"], runtimes[2].events
        runtimes[1]._baum_weitergeben(home["kennung"], office["kennung"], m.fingerabdruck(home["oeffentlich"]), m.fingerabdruck(office["oeffentlich"]))
        assert runtimes[1].events[-1][1]["ok"] and not runtimes[1].events[-1][1]["wartet"]
        assert office["weitergabeAngebote"] == []
        services[1].anhalten()
        child = m.baum_partner(home, office["kennung"])
        assert child["oeffentlich"] == office["oeffentlich"] != laptop["oeffentlich"]
        assert not child["kontakte"] and not child["weitergabeErlaubt"]
        assert m.baum_senden_fs(home, child, "notiz", {"titel": "Home without laptop"}, m._fs_b64(bytes(16)))
        assert received[-1]["titel"] == "Home without laptop"
    finally:
        for service in services:
            service.anhalten()


def test_shared_control_failed_save_never_authorizes_or_acknowledges(private):
    home = m.baum_schluessel_erzeugen("Home")
    laptop = m.baum_schluessel_erzeugen("Laptop")
    office = m.baum_schluessel_erzeugen("Office")
    for own, remote in ((home, laptop), (laptop, home)):
        own["an"] = True
        m.baum_partner_aufnehmen(own, remote["name"], remote["kennung"], remote["oeffentlich"], "127.0.0.1")["bestaetigt"] = True
    m.baum_weitergabe_erlauben(home, laptop["kennung"], laptop["oeffentlich"], True)
    before = copy.deepcopy(home)
    service = m.BaumDienst(lambda: home, lambda _: False)
    def send(url, body):
        status, response = service.behandeln("/magnolie/v2/" + url.rsplit("/", 1)[-1], body, "127.0.0.1")
        if status != 200:
            raise RuntimeError(response["fehler"])
        return response
    request = {"aktion": "einladung", "id": m._baum_b64url(bytes(16)), "ziel": identity(office), "adresse": "127.0.0.1", "port": 8737}
    with pytest.raises(RuntimeError):
        m.baum_weitergabe_rpc(laptop, m.baum_partner(laptop, home["kennung"]), request, sender=send)
    assert home == before, "a failed durable save must not leave an invitation authorized in memory"


def test_message_traffic_preserves_pairing_quota_and_combined_limit(private):
    service = m.BaumDienst(lambda: {}, lambda _: True)
    assert all(service._anfrage_erlaubt("192.0.2.3") for _ in range(12))
    assert all(service._anfrage_erlaubt("::ffff:192.0.2.3", True) for _ in range(8))
    assert not service._anfrage_erlaubt("192.0.2.3", True)
    assert all(service._anfrage_erlaubt("192.0.2.3") for _ in range(100))
    assert not service._anfrage_erlaubt("192.0.2.3")


def test_request_pin_and_remote_acceptance_are_required_without_transferring_data(private):
    left = m.baum_schluessel_erzeugen("Sender")
    right = m.baum_schluessel_erzeugen("Recipient")
    left["an"] = right["an"] = True
    with pytest.raises(RuntimeError):
        m.baum_paarungsanfrage_vormerken(left, identity(right), "127.0.0.1", "")
    peer = m.baum_paarungsanfrage_vormerken(left, identity(right), "127.0.0.1", m.fingerabdruck(right["oeffentlich"]))
    assert peer["anfrageAusgehend"] and peer["wartetFern"] and not peer["bestaetigt"]
    incoming = m.baum_partner_aufnehmen(right, left["name"], left["kennung"], left["oeffentlich"], "127.0.0.1")
    documents = []
    receiver = m.BaumDienst(lambda: right, lambda _: True, bei_nachricht=lambda *values: documents.append(values))
    paths = []
    def send(url, payload):
        paths.append(url)
        status, response = receiver.behandeln("/magnolie/v2/sitzung", payload, "127.0.0.1")
        if status != 200:
            raise RuntimeError("waiting")
        return response
    assert not m.baum_paarungsbestaetigung_pruefen(left, peer, send)
    incoming["bestaetigt"] = True
    assert m.baum_paarungsbestaetigung_pruefen(left, peer, send)
    assert documents == [] and all(path.endswith("/magnolie/v2/sitzung") for path in paths)
    assert m.baum_paarungsanfrage_abschliessen(left, peer["kennung"], peer["oeffentlich"], left["kennung"], left["oeffentlich"])
    assert peer["bestaetigt"] and not peer["wartetFern"]
    assert not peer["vertraut"] and not peer["kontakte"], "pairing completion must not grant extra data scopes"


def test_pending_pin_and_inflight_completion_cannot_change_peer_or_identity(private):
    own = m.baum_schluessel_erzeugen("Sender")
    remote = m.baum_schluessel_erzeugen("Recipient")
    attacker = m.baum_schluessel_erzeugen("Other")
    peer = m.baum_paarungsanfrage_vormerken(own, identity(remote), "127.0.0.1", m.fingerabdruck(remote["oeffentlich"]))
    before = copy.deepcopy(peer)
    with pytest.raises(RuntimeError):
        m.baum_partner_aufnehmen(own, "Changed", remote["kennung"], attacker["oeffentlich"], "192.0.2.1")
    assert peer == before
    assert not m.baum_paarungsanfrage_abschliessen(own, peer["kennung"], peer["oeffentlich"], own["kennung"], attacker["oeffentlich"])
    own["partner"] = []
    assert not m.baum_paarungsanfrage_abschliessen(own, peer["kennung"], peer["oeffentlich"], own["kennung"], own["oeffentlich"])


def test_shared_connection_invitation_is_bound_to_new_device_and_current_authorization(private):
    home = m.baum_schluessel_erzeugen("Home")
    laptop = m.baum_schluessel_erzeugen("Laptop")
    office = m.baum_schluessel_erzeugen("Office")
    parent = m.baum_partner_aufnehmen(home, laptop["name"], laptop["kennung"], laptop["oeffentlich"], "127.0.0.1")
    parent["bestaetigt"] = True
    with pytest.raises(RuntimeError):
        m.baum_verbindungsfreigabe_erzeugen(home, parent["kennung"], parent["oeffentlich"], identity(office), "127.0.0.1")
    m.baum_weitergabe_erlauben(home, parent["kennung"], parent["oeffentlich"], True)
    document = m.baum_verbindungsfreigabe_erzeugen(home, parent["kennung"], parent["oeffentlich"], identity(office), "127.0.0.1")
    assert document["einlader"]["oeffentlich"] == home["oeffentlich"]
    wrong = m.baum_schluessel_erzeugen("Wrong recipient")
    with pytest.raises(RuntimeError):
        m.baum_paarungsanfrage_annehmen(home, m.baum_paarungsanfrage_bauen(wrong, document))
    assert len(home["paarungen"]) == 1, "a wrong recipient must not consume the correct device's invitation"
    request = m.baum_paarungsanfrage_bauen(office, document)
    m.baum_weitergabe_erlauben(home, parent["kennung"], parent["oeffentlich"], False)
    with pytest.raises(RuntimeError):
        m.baum_paarungsanfrage_annehmen(home, request)
    m.baum_weitergabe_erlauben(home, parent["kennung"], parent["oeffentlich"], True)
    with pytest.raises(RuntimeError):
        m.baum_paarungsanfrage_annehmen(home, request)
    with pytest.raises(RuntimeError):
        m.baum_weitergabe_erlauben(home, parent["kennung"], office["oeffentlich"], False)
    assert parent["weitergabeErlaubt"], "stale identity must not change authorization"
    document = m.baum_verbindungsfreigabe_erzeugen(home, parent["kennung"], parent["oeffentlich"], identity(office), "127.0.0.1")
    request = m.baum_paarungsanfrage_bauen(office, document)
    response = m.baum_paarungsanfrage_annehmen(home, request)
    m.baum_paarungsantwort_pruefen(document, request, response)
    child = m.baum_partner(home, office["kennung"])
    assert child["bestaetigt"] and child["oeffentlich"] == office["oeffentlich"]
    assert child["oeffentlich"] != parent["oeffentlich"] and not child["weitergabeErlaubt"]
    assert not child["kontakte"] and not child["vertraut"], "forwarding cannot silently broaden existing permissions"
    assert m.baum_paarungsanfrage_annehmen(home, request) == response
    assert len(home["partner"]) == 2
    home["partner"].remove(child)
    with pytest.raises(RuntimeError):
        m.baum_paarungsanfrage_annehmen(home, request)
