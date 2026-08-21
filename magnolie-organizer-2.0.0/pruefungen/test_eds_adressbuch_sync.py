import importlib.machinery
import importlib.util
from pathlib import Path

import pytest


PFAD = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
lader = importlib.machinery.SourceFileLoader("magnolie_eds_test", str(PFAD))
spec = importlib.util.spec_from_loader("magnolie_eds_test", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


def vcard(uid="remote-1", name="Remote", rev="20260812T120000Z"):
    uid_zeile = "UID:%s\r\n" % uid if uid is not None else ""
    return ("BEGIN:VCARD\r\nVERSION:3.0\r\n" + uid_zeile +
            "N:%s;;;;\r\nFN:%s\r\nREV:%s\r\nEND:VCARD\r\n" %
            (name, name, rev))


class Kontakt:
    def __init__(self, text=None, fehler=None):
        self.text = text
        self.fehler = fehler

    def inline_local_photos(self):
        return None

    def to_string(self, _format):
        if self.fehler:
            raise RuntimeError(self.fehler)
        return self.text


class Client:
    def __init__(self, kontakte=None, ergebnis=True, ausnahme=None,
                 refresh=True, capabilities=()):
        self.kontakte = kontakte or []
        self.ergebnis = ergebnis
        self.ausnahme = ausnahme
        self.refresh_ergebnis = refresh
        self.capabilities = list(capabilities)
        self.refreshes = 0

    def get_contacts_sync(self, _abfrage, _abbruch):
        if self.ausnahme:
            raise self.ausnahme
        return self.ergebnis, self.kontakte

    def get_capabilities(self):
        return self.capabilities

    def refresh_sync(self, _abbruch):
        self.refreshes += 1
        return self.refresh_ergebnis


class Probe:
    def __init__(self):
        self.snapshots = []

    def antwort(self, funktion, nutzlast):
        self.funktion = funktion
        self.nutzlast = nutzlast

    def _journal_snapshot(self, grund):
        self.snapshots.append(grund)


@pytest.fixture(autouse=True)
def econtact_format(monkeypatch):
    klasse = type("EBookContacts", (), {
        "VCardFormat": type("VCardFormat", (), {"VCARD_30": 1})})
    monkeypatch.setitem(m._EDS, "EBookContacts", klasse)
    monkeypatch.setitem(m._EDS, "buch_ok", True)


def test_strukturierter_vollstaendiger_read():
    gelesen = m.eds_kontakte_lesen(Client([Kontakt(vcard())]))
    assert gelesen["vollstaendig"]
    assert (gelesen["remoteGesamt"], gelesen["serialisiert"],
            gelesen["geparst"], gelesen["gueltigeUids"]) == (1, 1, 1, 1)
    assert gelesen["kontakte"][0]["uid"] == "remote-1"


@pytest.mark.parametrize("client", [
    Client(ausnahme=RuntimeError("get failed")),
    Client(ergebnis=False),
])
def test_get_failure_oder_false_bricht_ab(client):
    with pytest.raises(RuntimeError):
        m.eds_kontakte_lesen(client)


@pytest.mark.parametrize("kontakte", [
    [Kontakt(fehler="to-string")],
    [Kontakt("not a vcard")],
    [Kontakt(vcard(None))],
    [Kontakt(vcard("doppelt")), Kontakt(vcard("doppelt"))],
])
def test_partielle_reads_sind_unvollstaendig(kontakte):
    gelesen = m.eds_kontakte_lesen(Client(kontakte))
    assert not gelesen["vollstaendig"]
    assert gelesen["fehler"]


def sync_lauf(monkeypatch, client, lokale=None, tombstones=None, basis=None,
              anlegen_fehler=False, altbestand=None):
    erstellt, geaendert, geloescht = [], [], []
    monkeypatch.setattr(m, "eds_laden", lambda: True)
    monkeypatch.setattr(m, "eds_registry", lambda: object())
    monkeypatch.setattr(m, "eds_buch_client", lambda _registry, _uid: client)
    def anlegen(_client, text):
        if anlegen_fehler:
            raise RuntimeError("write failed")
        erstellt.append(text)
    monkeypatch.setattr(m, "eds_kontakt_anlegen", anlegen)
    monkeypatch.setattr(m, "eds_kontakt_aendern", lambda _client, text:
                        geaendert.append(text))
    monkeypatch.setattr(m, "eds_kontakt_loeschen", lambda _client, uid:
                        geloescht.append(uid))
    probe = Probe()
    letzte = {"kalender": {}, "adressbuecher": {}}
    if altbestand is not None:
        letzte["adressbuecher"]["google"] = altbestand
    sync_meta = {"eds": {"adressbuecher": {}}}
    if basis is not None:
        sync_meta["eds"]["adressbuecher"]["google"] = basis
    m.Fenster._sync_ausfuehren(probe, {
        "wahl": {"adressbuchUid": "google"},
        "daten": {"termine": [], "kontakte": lokale or [], "jahrestage": [],
                  "geloescht": {"termine": [], "kontakte": tombstones or []},
                  "letzterSync": 0, "letzteSyncs": letzte,
                  "syncMetadaten": sync_meta}})
    return probe, erstellt, geaendert, geloescht


def test_erster_sync_leer_lokal_remote_voll(monkeypatch):
    client = Client([Kontakt(vcard("r1")), Kontakt(vcard("r2", "Zwei"))],
                    capabilities=["refresh-supported"])
    probe, erstellt, geaendert, geloescht = sync_lauf(monkeypatch, client)
    assert client.refreshes == 1 and probe.snapshots == ["pre-sync"]
    assert {k["uid"] for k in probe.nutzlast["kontakte"]} == {"r1", "r2"}
    assert not erstellt and not geaendert and not geloescht
    assert probe.nutzlast["kontaktVorschau"]["lokalNeu"] == 2
    assert "2 " in probe.nutzlast["bericht"] and "keine Änderungen" not in probe.nutzlast["bericht"]
    assert probe.nutzlast["adressbuchBaselineKandidat"]["initialisiert"]
    assert "google" not in probe.nutzlast["syncMetadaten"]["eds"]["adressbuecher"]


def test_erster_sync_remote_leer_lokal_voll_und_tombstone_blockiert(monkeypatch):
    lokal = [{"uid": "lokal", "nachname": "Lokal", "geaendert": 100,
              "sync": True}]
    probe, erstellt, geaendert, geloescht = sync_lauf(
        monkeypatch, Client([]), lokal, [{"uid": "remote-alt", "zeit": 200}])
    assert [k["uid"] for k in probe.nutzlast["kontakte"]] == ["lokal"]
    assert probe.nutzlast["kontakte"][0]["sync"] is False
    assert not erstellt and not geaendert and not geloescht
    assert probe.nutzlast["kontaktVorschau"]["remoteGemeldet"] == 0
    assert probe.nutzlast["kontaktVorschau"]["modus"] == "erstimport"
    assert "google" not in probe.nutzlast["syncMetadaten"]["eds"]["adressbuecher"]


def test_erster_sync_beide_voll_reichert_eindeutig_an(monkeypatch):
    lokal = [{"uid": "lokal", "nachname": "Remote", "geaendert": 10,
              "sync": False}]
    probe, erstellt, geaendert, geloescht = sync_lauf(
        monkeypatch, Client([Kontakt(vcard("remote-1", "Remote"))]), lokal)
    assert len(probe.nutzlast["kontakte"]) == 1
    assert probe.nutzlast["kontakte"][0]["uid"] == "remote-1"
    assert not erstellt and not geaendert and not geloescht


def test_etablierter_bidirektionaler_sync_und_erfolgszaehler(monkeypatch):
    lokal = [{"uid": "lokal-neu", "nachname": "Lokal", "geaendert": 300,
              "sync": False},
             {"uid": "gemeinsam", "nachname": "Lokal neu", "geaendert": 2000000000000,
              "sync": True}]
    client = Client([Kontakt(vcard("remote-neu", "Remote", "20260812T120000Z")),
                     Kontakt(vcard("gemeinsam", "Remote alt", "20200101T000000Z"))])
    basis = {"initialisiert": True, "letzterSync": 100,
             "remoteAnzahl": 1, "snapshotHash": "a" * 64}
    probe, erstellt, geaendert, geloescht = sync_lauf(
        monkeypatch, client, lokal, basis=basis)
    assert {k["uid"] for k in probe.nutzlast["kontakte"]} == {
        "lokal-neu", "gemeinsam", "remote-neu"}
    assert len(erstellt) == 1 and len(geaendert) == 1 and not geloescht
    vorschau = probe.nutzlast["kontaktVorschau"]
    assert vorschau["remoteGeplant"] == {"anlegen": 1, "aendern": 1, "loeschen": 0}
    assert vorschau["remoteErfolgreich"] == vorschau["remoteGeplant"]
    neuer_cursor = probe.nutzlast["syncMetadaten"]["eds"]["adressbuecher"]["google"]
    assert neuer_cursor["initialisiert"] and neuer_cursor["letzterSync"] > basis["letzterSync"]


def test_etabliert_remote_leer_uebernimmt_remote_loeschung(monkeypatch):
    lokal = [{"uid": "weg", "nachname": "Weg", "geaendert": 10, "sync": True}]
    basis = {"initialisiert": True, "letzterSync": 100,
             "remoteAnzahl": 1, "snapshotHash": "b" * 64}
    probe, _erstellt, _geaendert, _geloescht = sync_lauf(
        monkeypatch, Client([]), lokal, basis=basis)
    assert probe.nutzlast["kontakte"] == []
    assert (probe.nutzlast["syncMetadaten"]["eds"]["adressbuecher"]["google"]
            ["letzterSync"] > basis["letzterSync"])


def test_remote_fehler_zaehlt_nicht_als_erfolg_und_schreibt_basis_nicht_fort(
        monkeypatch):
    lokal = [{"uid": "lokal-neu", "nachname": "Lokal", "geaendert": 300,
              "sync": False}]
    basis = {"initialisiert": True, "letzterSync": 100,
             "remoteAnzahl": 0, "snapshotHash": "c" * 64}
    probe, _erstellt, _geaendert, _geloescht = sync_lauf(
        monkeypatch, Client([]), lokal, basis=basis, anlegen_fehler=True)
    vorschau = probe.nutzlast["kontaktVorschau"]
    assert vorschau["remoteGeplant"]["anlegen"] == 1
    assert vorschau["remoteErfolgreich"]["anlegen"] == 0
    assert vorschau["fehler"] == 1
    assert probe.nutzlast["syncMetadaten"]["eds"]["adressbuecher"]["google"] == basis


def test_ausgelieferter_letzte_syncs_altbestand_wird_migriert(monkeypatch):
    altbestand = {"initialisiert": True, "letzterSync": 100,
                  "remoteAnzahl": 1, "snapshotHash": "d" * 64}
    lokal = [{"uid": "weg", "nachname": "Weg", "geaendert": 10, "sync": True}]
    probe, _erstellt, _geaendert, _geloescht = sync_lauf(
        monkeypatch, Client([]), lokal, altbestand=altbestand)
    assert probe.nutzlast["kontakte"] == []
    assert "google" not in probe.nutzlast["letzteSyncs"]["adressbuecher"]
    cursor = probe.nutzlast["syncMetadaten"]["eds"]["adressbuecher"]["google"]
    assert cursor["initialisiert"] and cursor["letzterSync"] > altbestand["letzterSync"]


def test_unvollstaendiger_sync_mutiert_keinen_stand(monkeypatch):
    lokal = [{"uid": "bleibt", "nachname": "Bleibt", "sync": True}]
    client = Client([Kontakt(fehler="kaputt")])
    with pytest.raises(RuntimeError):
        sync_lauf(monkeypatch, client, lokal)
    assert lokal == [{"uid": "bleibt", "nachname": "Bleibt", "sync": True}]


def test_erster_sync_retry_erzeugt_keine_dubletten(monkeypatch):
    client = Client([Kontakt(vcard("r1"))])
    erster, *_ = sync_lauf(monkeypatch, client)
    zweiter, erstellt, geaendert, geloescht = sync_lauf(
        monkeypatch, client, erster.nutzlast["kontakte"])
    assert len(zweiter.nutzlast["kontakte"]) == 1
    assert not erstellt and not geaendert and not geloescht
