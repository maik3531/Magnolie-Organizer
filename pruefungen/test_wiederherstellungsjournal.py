#!/usr/bin/env python3
import json
import os
import tempfile
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from importlib.machinery import SourceFileLoader


PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
m = SourceFileLoader("magnolie_journal", PFAD).load_module()
Disk = namedtuple("Disk", "total used free")


def daten(n=1):
    return {"version": 6, "termine": [{"id": str(i)} for i in range(n)],
            "aufgaben": [], "kontakte": [{"id": "k1"}], "notizen": [],
            "jahrestage": [], "papierkorb": [], "tombstones": [],
            "geloescht": {"termine": [{"uid": "alt", "zeit": 1}],
                           "kontakte": [{"uid": "k-alt", "zeit": 1}]},
            "baumKontaktGeloescht": [{"freigabeId": "alt"}],
            "einstellungen": {"sync": {}, "allgemein": {}}}


def disk(_pfad):
    return Disk(100 * 1024 ** 3, 0, 10 * 1024 ** 3)


with tempfile.TemporaryDirectory() as tmp:
    zeit = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    stand = m.journal_snapshot_erzeugen(daten(), "weekly", basis=tmp,
                                         jetzt=zeit, disk_usage=disk)
    assert stand["format"] == "magnolie-snapshot"
    assert stand["formatVersion"] == 1 and stand["platform"] == "linux"
    assert stand["appVersion"] == "2.0.0" and stand["integrity"] == "ok"
    assert stand["payload"]["schema"] == 1 and stand["summary"]["termine"] == 1
    assert os.stat(m.journal_verzeichnis(tmp)).st_mode & 0o777 == 0o700
    assert os.stat(os.path.join(stand["path"], "manifest.json")).st_mode & 0o777 == 0o600
    assert os.stat(os.path.join(stand["path"], "payload.magnolie")).st_mode & 0o777 == 0o600
    manifest = json.load(open(os.path.join(stand["path"], "manifest.json"), encoding="utf-8"))
    assert manifest["snapshotId"] == stand["snapshotId"]

    # Gleiches Motiv und derselbe Quellhash innerhalb 15 Minuten werden dedupliziert.
    gleich = m.journal_snapshot_erzeugen(daten(), "weekly", basis=tmp,
                                          jetzt=zeit + timedelta(minutes=14), disk_usage=disk)
    assert gleich["deduplicated"] and gleich["snapshotId"] == stand["snapshotId"]
    anders = m.journal_snapshot_erzeugen(daten(2), "weekly", basis=tmp,
                                          jetzt=zeit + timedelta(minutes=14), disk_usage=disk)
    assert anders["snapshotId"] != stand["snapshotId"]

    # Unbekannte Manifestversionen werden nicht als gültige Stände angeboten.
    manifest_pfad = os.path.join(anders["path"], "manifest.json")
    falsch = json.load(open(manifest_pfad, encoding="utf-8"))
    falsch["formatVersion"] = 2
    with open(manifest_pfad, "w", encoding="utf-8") as ausgabe:
        json.dump(falsch, ausgabe)
    assert next(x for x in m.journal_liste(tmp)
                if x["snapshotId"] == anders["snapshotId"])["integrity"] == "damaged"

    # Payload-Manipulation wird vor Vorschau/Restore erkannt.
    payload = os.path.join(stand["path"], "payload.magnolie")
    with open(payload, "ab") as ausgabe:
        ausgabe.write(b"x")
    assert next(x for x in m.journal_liste(tmp)
                if x["snapshotId"] == stand["snapshotId"])["integrity"] == "damaged"
    try:
        m.journal_snapshot_lesen(stand["snapshotId"], basis=tmp)
        raise AssertionError("manipulierte Nutzlast angenommen")
    except RuntimeError:
        pass

    # Partielle Stände verschwinden beim nächsten Lauf, Symlinks werden nicht verfolgt.
    teil = os.path.join(m.journal_verzeichnis(tmp), ".abbruch.partial")
    os.mkdir(teil)
    open(os.path.join(teil, "rest"), "w").close()
    m.journal_bereinigen(tmp)
    assert not os.path.exists(teil)
    link = os.path.join(m.journal_verzeichnis(tmp), "link")
    os.symlink(anders["path"], link)
    assert all(x["snapshotId"] != "link" for x in m.journal_liste(tmp))

assert m.journal_faellig("weekly", None)
assert not m.journal_faellig("off", None)
assert not m.journal_faellig("weekly", "2026-08-10T00:00:00Z",
                             "2026-08-12T00:00:00Z")
assert m.journal_faellig("6h", "2026-08-11T17:59:59Z", "2026-08-12T00:00:00Z")
assert not m.journal_faellig("12h", "2026-08-11T17:59:59Z", "2026-08-12T00:00:00Z")
assert m.journal_faellig("daily", "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z")

# Ein fehlgeschlagener Pflichtstand beendet den Sync vor jeder externen Mutation.
class SyncProbe:
    def _journal_snapshot(self, _grund):
        raise OSError("snapshot failed")

try:
    m.Fenster._sync_ausfuehren(SyncProbe(), {"daten": {}, "wahl": {"kalenderUid": "x"}})
    raise AssertionError("Sync trotz fehlendem Pflichtsnapshot begonnen")
except OSError:
    pass

# Reserve und Budget blockieren vor dem Schreiben.
with tempfile.TemporaryDirectory() as tmp:
    knapp = lambda _pfad: Disk(100 * 1024 ** 3, 0, m.JOURNAL_RESERVE)
    try:
        m.journal_snapshot_erzeugen(daten(), "pre-sync", basis=tmp, disk_usage=knapp)
        raise AssertionError("Pflichtsnapshot ohne Reserve geschrieben")
    except OSError:
        pass
    assert not m.journal_liste(tmp)

# Retention: manuell angeheftet bleibt, Wochen/Monate und Kurzzeitstände sind begrenzt.
with tempfile.TemporaryDirectory() as tmp:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    manuell = m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp,
        jetzt=start, disk_usage=disk)
    for i in range(10):
        m.journal_snapshot_erzeugen(daten(i + 2), "weekly", basis=tmp,
            jetzt=start + timedelta(days=7 * i), disk_usage=disk)
    for i in range(22):
        m.journal_snapshot_erzeugen(daten(i + 20), "pre-sync", basis=tmp,
            jetzt=start + timedelta(days=100, hours=i), disk_usage=disk)
    m.journal_retention(tmp, start + timedelta(days=101), disk_usage=disk)
    behalten = m.journal_liste(tmp, integritaet=False)
    assert any(x["snapshotId"] == manuell["snapshotId"] for x in behalten)
    assert len([x for x in behalten if x["reason"] == "weekly"]) <= 8
    assert len([x for x in behalten if x["reason"] == "pre-sync"]) <= 20

# Atomarer Fehler hinterlässt keinen sichtbaren Stand.
with tempfile.TemporaryDirectory() as tmp:
    def abbrechen(stelle):
        if stelle == "payload":
            raise RuntimeError("Abbruch")
    try:
        m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp,
                                     disk_usage=disk, haken=abbrechen)
        raise AssertionError("Abbruch ignoriert")
    except RuntimeError:
        pass
    assert not m.journal_liste(tmp)

# Restore rotiert die Epoch, quarantänisiert Löschungen und ist für alte Peers additiv.
alt = daten()
neu = m.journal_restore_daten(alt)
assert neu["syncEpoch"] != alt.get("syncEpoch")
assert neu["syncMetadaten"]["ersteSyncLoeschungsfrei"] is True
assert neu["syncMetadaten"]["quarantinedDeletes"]["geloescht"] == alt["geloescht"]
assert neu["geloescht"] == {"termine": [], "kontakte": []}
assert neu["tombstones"] == [] and neu["baumKontaktGeloescht"] == []
assert neu["einstellungen"]["sync"]["syncEpoch"] == neu["syncEpoch"]

print("Wiederherstellungsjournal-Vertrag: ok")
