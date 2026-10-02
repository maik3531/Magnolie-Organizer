"""Content-time negotiation is strict and cannot consume legacy data counters."""
import copy
import json
from urllib.error import HTTPError

import pytest
from test_startup_read_failure import native, Host


def packet():
    return {"art": "kontakt_sync", "fassung": 3, "freigabeId": "share", "version": 1,
            "quelle": "peer", "geaendert": 1770000000000, "inhaltGeaendert": 1760000000000,
            "kontakt": {"vorname": "Person", "nachname": "", "firma": "", "notiz": "", "geburtstag": "",
                        "anzeigename": "", "jubilaeum": "", "vcardName": [],
                         "telefone": [], "emailEintraege": [], "anschriften": []}}


@pytest.mark.parametrize("revision,reliable", [
    ("REV:20260101T120000Z", True),
    ("REV:20260101T140000+0200", True),
    ("REV:20260101T063000-05:30", True),
    ("REV:2026-01-01T14:00:00+02:00", True),
    ("REV:2026-01-01T06:30:00-0530", True),
    ("REV:20260101t120000z", True),
    ("REV:20260101T120000ZZ", False),
    ("REV:20260101T120000+1460", False),
    ("REV:20260101T120000+1401", False),
    ("REV:20260230T120000Z", False),
    ("REV:20260101T120000", False),
    ("REV:20260101", False),
    ("REV:20260101T120000Z\r\nREV:20260102T120000Z", False),
    ("", False),
])
def test_vcard_original_time_requires_one_explicit_timezone(native, revision, reliable):
    card = native.vcf_lesen("BEGIN:VCARD\r\nVERSION:3.0\r\nN:Person;Test;;;\r\n" + revision + "\r\nEND:VCARD\r\n")["kontakte"][0]
    assert bool(card["vcardRev"]) is reliable
    if reliable: assert card["vcardRev"] == card["geaendert"] == 1767268800000
    card["geaendert"] = 0
    assert "REV:" not in native.vcf_schreiben([card]), "unknown modification time was replaced with export time"


def test_original_content_time_and_lossless_legacy_projection(native):
    message = packet()
    native.baum_kontakt_sync_pruefen(message)
    peer = {"bestaetigt": True, "kontaktFaehigkeiten": native.baum_kontakt_faehigkeiten()}
    converted = native.baum_kontakt_fuer_partner(peer, message)
    assert converted["fassung"] == 2 and "inhaltGeaendert" not in converted
    assert converted["kontakt"] == message["kontakt"] and message["fassung"] == 3
    native.baum_kontakt_sync_pruefen(converted)
    peer["kontaktFaehigkeiten"] = native.baum_kontakt_faehigkeiten(maximum=3)
    native.baum_kontakt_faehigkeiten_pruefen(peer["kontaktFaehigkeiten"])
    assert native.baum_kontakt_peer_fassung(peer, "kontakt_sync") == 3
    assert native.baum_kontakt_peer_fassung(peer, "kontakt_import") == 2
    peer["bestaetigt"] = False
    assert native.baum_kontakt_peer_fassung(peer, "kontakt_sync") == 1


@pytest.mark.parametrize("time", [None, True, -1, "1760000000000", 1.5, 253402300800000])
def test_invalid_content_time_is_rejected(native, time):
    message = packet(); message["inhaltGeaendert"] = time
    with pytest.raises(RuntimeError):
        native.baum_kontakt_sync_pruefen(message)


def peers(native):
    state = native.baum_schluessel_erzeugen("A")
    other = native.baum_schluessel_erzeugen("B")
    peer = native.baum_partner_aufnehmen(state, "B", other["kennung"], other["oeffentlich"], "127.0.0.1", 8737)
    peer.update(bestaetigt=True, protokoll="baum-1")
    return state, peer


@pytest.mark.parametrize("status,unsupported", [(400, True), (403, True), (404, True), (500, False)])
def test_optional_probe_is_fs1_and_does_not_drop_user_data(native, status, unsupported):
    state, peer = peers(native)
    post = []
    probe = native.baum_einreihen(post, peer["kennung"], "kontakt_faehigkeiten", native.baum_kontakt_faehigkeiten(maximum=3))
    probe["kontaktV3Probe"] = True
    data = native.baum_einreihen(post, peer["kennung"], "aufgabe", {"art": "aufgabe", "titel": "Keep"})
    before = copy.deepcopy(data)
    def send(url, body):
        assert url.endswith("/magnolie/v2/sitzung")
        raise HTTPError(url, status, "Fixture", {}, None)
    report = native.baum_post_zustellen(state, post, sender=send, hoechstens=1, sichern=lambda: True)
    assert peer.get("zaehler_raus", 0) == 0
    assert "briefUmschlag" not in probe
    assert data == before and data in post
    assert (probe not in post) is unsupported
    assert bool(peer.get("kontaktV3Geprueft")) is unsupported
    assert report["zugestellt"] == 0


def test_delayed_legacy_reply_does_not_downgrade_new_capabilities(native, monkeypatch):
    state, peer = peers(native)
    peer["kontaktFaehigkeiten"] = native.baum_kontakt_faehigkeiten(maximum=3)
    host = Host(native); host._gesperrt = False
    monkeypatch.setattr(host, "_baum_zustand", lambda: state)
    monkeypatch.setattr(host, "_baum_stand_melden", lambda: None)
    monkeypatch.setattr(native, "baum_benachrichtigungstext", lambda *_: None)
    host._baum_empfangen(peer, native.baum_kontakt_faehigkeiten(antwort=True))
    assert native.baum_kontakt_peer_fassung(peer, "kontakt_sync") == 3
    host._baum_empfangen(peer, native.baum_kontakt_faehigkeiten(antwort=False))
    assert native.baum_kontakt_peer_fassung(peer, "kontakt_sync") == 2


def test_native_http_v3_negotiation_and_lost_ack_survive_receiver_restart(native, monkeypatch, tmp_path):
    """Real FS1 HTTP, native dispatch/inbox, and persisted transport replay state."""
    monkeypatch.setattr(native.BaumDienst, "_rufdienst_starten", lambda self: None)
    monkeypatch.setattr(native.BaumBluetoothDienst, "starten", lambda self: False)
    monkeypatch.setattr(native, "baum_mdns_veroeffentlichen", lambda *_: None)
    monkeypatch.setattr(native, "baum_benachrichtigungstext", lambda *_: None)
    a = native.baum_schluessel_erzeugen("Content-time A"); a["an"] = True
    b = native.baum_schluessel_erzeugen("Content-time B"); b["an"] = True
    ab = native.baum_partner_aufnehmen(a, "B", b["kennung"], b["oeffentlich"], "127.0.0.1", 1)
    ba = native.baum_partner_aufnehmen(b, "A", a["kennung"], a["oeffentlich"], "127.0.0.1", 1)
    for peer in (ab, ba): peer.update(bestaetigt=True, protokoll="baum-1")
    ab["zaehler_raus"] = 19
    replies = []
    hosts = []
    for state in (a, b):
        host = Host(native); host._gesperrt = False
        monkeypatch.setattr(host, "_baum_zustand", lambda state=state: state)
        monkeypatch.setattr(host, "_baum_stand_melden", lambda: None)
        monkeypatch.setattr(host, "_baum_kontakt_faehigkeiten_anmelden",
                            lambda peer, answer, maximum=2: replies.append(
                                native.baum_kontakt_faehigkeiten(antwort=answer, maximum=maximum)))
        hosts.append(host)
    persisted = tmp_path / "receiver.json"
    def save_receiver(state):
        persisted.write_text(json.dumps(state), encoding="utf-8")
        return True
    receiver = native.BaumDienst(lambda: b, save_receiver, bei_nachricht=hosts[1]._baum_empfangen, port=0)
    sender = native.BaumDienst(lambda: a, lambda _: True, bei_nachricht=hosts[0]._baum_empfangen, port=0)
    try:
        assert receiver.starten() and sender.starten()
        ab["port"] = receiver.port; ba["port"] = sender.port
        assert native.baum_senden(a, ab, "kontakt_faehigkeiten", native.baum_kontakt_faehigkeiten(maximum=3),
                                 transport_id=native._fs_b64(b"P" * 16), sendung={"kontaktV3Probe": True})
        assert ab["zaehler_raus"] == 19, "optional probe consumed a reserved legacy counter"
        assert len(replies) == 1 and replies[0]["kontakt_sync"] == [1, 2, 3]
        assert native.baum_senden_fs(b, ba, "kontakt_faehigkeiten", replies[0], native._fs_b64(b"R" * 16))
        assert native.baum_kontakt_peer_fassung(ab, "kontakt_sync") == 3
        message = packet(); message["quelle"] = a["kennung"]
        transport = native._fs_b64(b"D" * 16)
        def lose_ack(url, body):
            result = native._baum_http_json_senden(url, body, 3)
            if url.endswith("/nachricht"): raise ConnectionError("synthetic lost response after acceptance")
            return result
        assert not native.baum_senden_fs(a, ab, "kontakt_sync", message, transport, sender=lose_ack)
        inbox = native.baum_eingang_lesen()
        assert len(inbox) == 1 and inbox[0]["inhalt"] == message
        receiver.anhalten()
        b = json.loads(persisted.read_text(encoding="utf-8"))
        monkeypatch.setattr(hosts[1], "_baum_zustand", lambda: b)
        receiver = native.BaumDienst(lambda: b, save_receiver, bei_nachricht=hosts[1]._baum_empfangen, port=0)
        assert receiver.starten(); ab["port"] = receiver.port
        assert native.baum_senden_fs(a, ab, "kontakt_sync", message, transport)
        assert native.baum_eingang_lesen() == inbox, "lost ACK replay duplicated the contact offer"
        assert native.baum_eingang_lesen()[0]["inhalt"]["inhaltGeaendert"] == message["inhaltGeaendert"]
        assert ab["zaehler_raus"] == 19
    finally:
        receiver.anhalten(); sender.anhalten()
