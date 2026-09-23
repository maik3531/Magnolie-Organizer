#!/usr/bin/env python3
import copy
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from modul_laden import quellmodul_laden


PFAD = os.environ.get("MAGNOLIE_PROGRAMM") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bin", "magnolie-organizer")
m = quellmodul_laden("magnolie_journal", PFAD)
Disk = namedtuple("Disk", "total used free")


assert m.JOURNAL_GRUENDE == {
    "weekly", "manual", "pre-change", "pre-sync", "pre-restore", "pre-contact",
    "pre-contact-import", "pre-contact-merge", "pre-contact-delete",
}
web_quelle = (Path(PFAD).resolve().parents[1] / "web" / "anwendung.js").read_text(
    encoding="utf-8")
assert 'manual: pgettext("recovery snapshot reason", "Manual")' in web_quelle
assert '"pre-contact": _("Before synchronization")' in web_quelle
assert '_("Are you really sure?")' in web_quelle


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


vorher = daten()
einstellungen = copy.deepcopy(vorher)
einstellungen["einstellungen"]["ansicht"] = "month"
einstellungen["letzterSync"] = 123
einstellungen["syncMetadaten"] = {"nextcloud": {"ausstehendeTransaktion": "test"}}
assert not m.journal_inhalt_geaendert(vorher, einstellungen)
for feld in ("termine", "kontakte", "notizen", "customOrganizer", "gesundheit", "smsPlanung", "futureContent"):
    geaendert = copy.deepcopy(einstellungen)
    geaendert[feld] = [{"id": "changed"}]
    assert m.journal_inhalt_geaendert(vorher, geaendert), feld
geloescht = copy.deepcopy(vorher)
del geloescht["kontakte"]
assert m.journal_inhalt_geaendert(vorher, geloescht)


# Auch nach der ersten Migration von einer alten Version neu angelegte Punkte
# werden einzeln nachgezogen, ohne einen vorhandenen Zielpunkt zu überschreiben.
with tempfile.TemporaryDirectory() as tmp:
    alt = os.path.join(tmp, "alt")
    ziel = os.path.join(tmp, "ziel")
    os.mkdir(alt)
    os.mkdir(ziel)
    alt_id, ziel_id = str(uuid.uuid4()), str(uuid.uuid4())
    os.mkdir(os.path.join(alt, alt_id))
    os.mkdir(os.path.join(ziel, ziel_id))
    m._journal_altbestand_verschieben(alt, ziel)
    assert set(os.listdir(ziel)) == {alt_id, ziel_id}
    assert not os.path.exists(alt)


with tempfile.TemporaryDirectory() as tmp:
    zeit = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    quelle = daten()
    quelle_vorher = copy.deepcopy(quelle)
    stand = m.journal_snapshot_erzeugen(quelle, "weekly", basis=tmp,
                                         jetzt=zeit, disk_usage=disk)
    assert stand["format"] == "magnolie-snapshot"
    assert stand["formatVersion"] == 1 and stand["platform"] == "linux"
    assert stand["appVersion"] == m.PROGRAMM_FASSUNG and stand["integrity"] == "ok"
    assert stand["payload"]["schema"] == 1 and stand["summary"]["termine"] == 1
    assert os.stat(m.journal_verzeichnis(tmp)).st_mode & 0o777 == 0o700
    assert os.stat(os.path.join(stand["path"], "manifest.json")).st_mode & 0o777 == 0o600
    assert os.stat(os.path.join(stand["path"], "payload.magnolie")).st_mode & 0o777 == 0o600
    manifest = json.load(open(os.path.join(stand["path"], "manifest.json"), encoding="utf-8"))
    assert manifest["snapshotId"] == stand["snapshotId"]
    assert quelle == quelle_vorher, "Snapshot-Erzeugung mutierte die Quelldaten"

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

# Ein beschädigter, ansonsten identischer Pflichtstand darf nie dedupliziert werden.
with tempfile.TemporaryDirectory() as tmp:
    zeit = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    alt = m.journal_snapshot_erzeugen(daten(), "pre-sync", basis=tmp,
                                      jetzt=zeit, disk_usage=disk)
    with open(os.path.join(alt["path"], "payload.magnolie"), "ab") as ausgabe:
        ausgabe.write(b"beschaedigt")
    neu = m.journal_snapshot_erzeugen(daten(), "pre-sync", basis=tmp,
                                      jetzt=zeit + timedelta(minutes=1), disk_usage=disk)
    assert not neu["deduplicated"] and neu["snapshotId"] != alt["snapshotId"]
    assert m.journal_snapshot_lesen(neu["snapshotId"], basis=tmp)[0]["integrity"] == "ok"

assert m.journal_faellig("weekly", None)
assert not m.journal_faellig("off", None)
assert not m.journal_faellig("weekly", "2026-08-10T00:00:00Z",
                             "2026-08-12T00:00:00Z")
assert m.journal_faellig("6h", "2026-08-11T17:59:59Z", "2026-08-12T00:00:00Z")
assert not m.journal_faellig("12h", "2026-08-11T17:59:59Z", "2026-08-12T00:00:00Z")
assert m.journal_faellig("daily", "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z")

# Kennwortwechsel und -entfernung lassen vorhandene Punkte weiterhin lesbar.
with tempfile.TemporaryDirectory() as tmp:
    punkt = m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp, disk_usage=disk)
    bericht = m.journal_umschluesseln("Rosenholz1896", "", tmp)
    assert bericht == {"geschafft": 1, "misslungen": 0}
    m.journal_snapshot_lesen(punkt["snapshotId"], "Rosenholz1896", tmp)
    bericht = m.journal_umschluesseln("Magnolie1897", "Rosenholz1896", tmp)
    assert bericht == {"geschafft": 1, "misslungen": 0}
    m.journal_snapshot_lesen(punkt["snapshotId"], "Magnolie1897", tmp)
    bericht = m.journal_umschluesseln("", "Magnolie1897", tmp)
    assert bericht == {"geschafft": 1, "misslungen": 0}
    m.journal_snapshot_lesen(punkt["snapshotId"], "", tmp)

# Mehr als ein Jahr alte Einzelstände werden atomar als XZ komprimiert und
# bleiben auch über einen Kennwortwechsel hinweg lesbar.
with tempfile.TemporaryDirectory() as tmp:
    alt_zeit = datetime(2024, 1, 1, tzinfo=timezone.utc)
    punkt = m.journal_snapshot_erzeugen(
        daten(40), "manual", basis=tmp, jetzt=alt_zeit, disk_usage=disk)
    bericht = m.journal_komprimieren(tmp, alt_zeit + timedelta(days=366))
    assert bericht == {"geschafft": 1, "misslungen": 0}
    stand = next(x for x in m.journal_liste(tmp)
                 if x["snapshotId"] == punkt["snapshotId"])
    assert stand["payload"]["file"] == "payload.magnolie.xz"
    assert stand["payload"]["compression"] == "xz"
    assert not os.path.exists(os.path.join(stand["path"], "payload.magnolie"))
    assert len(m.journal_snapshot_lesen(punkt["snapshotId"], basis=tmp)[1]
               ["daten"]["termine"]) == 40
    assert m.journal_umschluesseln("Rosenholz1896", "", tmp) == {
        "geschafft": 1, "misslungen": 0}
    assert len(m.journal_snapshot_lesen(
        punkt["snapshotId"], "Rosenholz1896", tmp)[1]["daten"]["termine"]) == 40

# Handgebaute Schema-1/2-Payloads tragen den echten Hash ihrer unnormalisierten
# Quelldaten. Beim Rekey auf Schema 3 muss das Manifest den migrierten Hash erhalten.
with tempfile.TemporaryDirectory() as tmp:
    quell_daten = daten()
    quell_daten["termine"] = [{"id": "legacy", "wiederholung": {
        "art": "monthly_weekday", "ordinal": 2, "wochentag": "TH"}}]
    quell_daten["aufgaben"] = [{"id": "ohne-uid"}]
    quell_vorher = copy.deepcopy(quell_daten)
    quellhash = hashlib.sha256(m._gesamtarchiv_kanonisch(quell_daten)).hexdigest()
    ids = []
    wurzel = m.journal_bereinigen(tmp)
    for schema in (1, 2):
        snapshot_id = str(uuid.uuid4())
        ids.append(snapshot_id)
        erstellt = "2026-08-1%dT12:00:00.000000Z" % schema
        archiv = {"magnolie": m.GESAMTARCHIV_KENNUNG,
                  "fassung": m.GESAMTARCHIV_FASSUNG, "datenschema": schema,
                  "erstellt": erstellt, "plattform": "linux", "appversion": "1.9.0",
                  "sha256": quellhash, "daten": copy.deepcopy(quell_daten)}
        payload = m._gesamtarchiv_kanonisch(archiv)
        manifest = {"format": m.JOURNAL_KENNUNG, "formatVersion": m.JOURNAL_FASSUNG,
                    "snapshotId": snapshot_id, "createdAt": erstellt,
                    "platform": "linux", "appVersion": "1.9.0", "reason": "manual",
                    "pinned": True, "payload": {
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "sourceSha256": quellhash, "size": len(payload),
                        "schema": m.JOURNAL_PAYLOAD_SCHEMA},
                    "summary": {"termine": 1, "aufgaben": 1},
                    "syncEpoch": str(uuid.uuid4())}
        ordner = os.path.join(wurzel, snapshot_id)
        os.mkdir(ordner)
        m.atomar_binaer_schreiben(os.path.join(ordner, "payload.magnolie"), payload)
        m.atomar_text_schreiben(os.path.join(ordner, "manifest.json"),
                                json.dumps(manifest, sort_keys=True) + "\n")

    for snapshot_id in ids:
        _stand, gelesen = m.journal_snapshot_lesen(snapshot_id, basis=tmp)
        assert gelesen["quellsha256"] == quellhash
        assert gelesen["daten"]["termine"][0]["wiederholung"]["art"] == "monthly"
        assert gelesen["daten"]["aufgaben"][0]["uid"]
        assert hashlib.sha256(m._gesamtarchiv_kanonisch(gelesen["daten"])).hexdigest() != quellhash
    assert quell_daten == quell_vorher

    bericht = m.journal_umschluesseln("Rosenholz1896", "", tmp)
    assert bericht == {"geschafft": 2, "misslungen": 0}
    for snapshot_id in ids:
        stand, gelesen = m.journal_snapshot_lesen(snapshot_id, "Rosenholz1896", tmp)
        migriert_hash = hashlib.sha256(
            m._gesamtarchiv_kanonisch(gelesen["daten"])).hexdigest()
        assert stand["payload"]["sourceSha256"] == migriert_hash
        assert gelesen["quellsha256"] == migriert_hash
    assert quell_daten == quell_vorher

# Ein Prozessabbruch zwischen den beiden Verzeichniswechseln stellt den alten Stand her.
with tempfile.TemporaryDirectory() as tmp:
    punkt = m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp, disk_usage=disk)
    wurzel = m.journal_verzeichnis(tmp)
    alt = os.path.join(wurzel, ".%s.rewrite-old" % punkt["snapshotId"])
    os.replace(punkt["path"], alt)
    m.journal_bereinigen(tmp)
    m.journal_snapshot_lesen(punkt["snapshotId"], "", tmp)

# Ein unvollständiger neuer Umschreibestand darf den gültigen Altstand nicht verdrängen.
with tempfile.TemporaryDirectory() as tmp:
    punkt = m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp, disk_usage=disk)
    wurzel = m.journal_verzeichnis(tmp)
    alt = os.path.join(wurzel, ".%s.rewrite-old" % punkt["snapshotId"])
    neu = os.path.join(wurzel, ".%s.rewrite-new" % punkt["snapshotId"])
    os.replace(punkt["path"], alt)
    os.mkdir(neu)
    open(os.path.join(neu, "manifest.json"), "w").close()
    m.journal_bereinigen(tmp)
    assert not os.path.exists(neu) and not os.path.exists(alt)
    m.journal_snapshot_lesen(punkt["snapshotId"], "", tmp)

# Eine Stufe vor dem ersten Verzeichniswechsel ist unvollständig und verschwindet.
with tempfile.TemporaryDirectory() as tmp:
    punkt = m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp, disk_usage=disk)
    wurzel = m.journal_verzeichnis(tmp)
    neu = os.path.join(wurzel, ".%s.rewrite-new" % punkt["snapshotId"])
    os.mkdir(neu)
    open(os.path.join(neu, "rest"), "w").close()
    m.journal_bereinigen(tmp)
    assert not os.path.exists(neu)
    m.journal_snapshot_lesen(punkt["snapshotId"], "", tmp)

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

# Ein Archivfehler darf keinen bisherigen Snapshot der Retention aussetzen.
with tempfile.TemporaryDirectory() as tmp:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(2):
        m.journal_snapshot_erzeugen(daten(i + 1), "pre-sync", basis=tmp,
            jetzt=start + timedelta(hours=i), disk_usage=disk)
    wurzel = m.journal_verzeichnis(tmp)

    def baumzustand():
        zustand = {}
        for ordner, unterordner, dateien in os.walk(wurzel):
            relativ = os.path.relpath(ordner, wurzel)
            zustand[relativ] = (tuple(sorted(unterordner)), tuple(sorted(dateien)))
            for name in dateien:
                pfad = os.path.join(ordner, name)
                with open(pfad, "rb") as eingabe:
                    zustand[os.path.relpath(pfad, wurzel)] = eingabe.read()
        return zustand

    vorher = baumzustand()
    archiv_erzeugen = m.gesamtarchiv_erzeugen
    try:
        def archivfehler(*_args, **_kwargs):
            raise RuntimeError("Archivfehler")
        m.gesamtarchiv_erzeugen = archivfehler
        try:
            m.journal_snapshot_erzeugen(daten(3), "pre-sync", basis=tmp,
                jetzt=start + timedelta(days=30), disk_usage=disk)
            raise AssertionError("Archivfehler ignoriert")
        except RuntimeError as fehler:
            assert str(fehler) == "Archivfehler"
    finally:
        m.gesamtarchiv_erzeugen = archiv_erzeugen
    assert baumzustand() == vorher

# Geplante Retention schafft rechnerisch Platz, löscht aber erst nach dem Commit.
with tempfile.TemporaryDirectory() as tmp:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    m.journal_snapshot_erzeugen(daten(1), "pre-sync", basis=tmp,
        jetzt=start, disk_usage=disk)
    m.journal_snapshot_erzeugen(daten(2), "pre-sync", basis=tmp,
        jetzt=start + timedelta(hours=1), disk_usage=disk)
    wurzel = m.journal_verzeichnis(tmp)

    def platz_nach_retention(_pfad):
        sichtbar = [name for name in os.listdir(wurzel) if not name.startswith(".")]
        frei = m.JOURNAL_RESERVE if sichtbar else m.JOURNAL_RESERVE + 10 * 1024 ** 2
        return Disk(100 * 1024 ** 3, 0, frei)

    alte_ids = [stand["snapshotId"] for stand in m.journal_liste(tmp, integritaet=False)]
    try:
        m.journal_snapshot_erzeugen(daten(3), "pre-sync", basis=tmp,
            jetzt=start + timedelta(days=30), disk_usage=platz_nach_retention,
            haken=lambda stelle: (_ for _ in ()).throw(RuntimeError("Abbruch"))
            if stelle == "payload" else None)
        raise AssertionError("Abbruch ignoriert")
    except RuntimeError as fehler:
        assert str(fehler) == "Abbruch"
    assert [stand["snapshotId"] for stand in
            m.journal_liste(tmp, integritaet=False)] == alte_ids

    neu = m.journal_snapshot_erzeugen(daten(3), "pre-sync", basis=tmp,
        jetzt=start + timedelta(days=30), disk_usage=platz_nach_retention)
    staende = m.journal_liste(tmp, integritaet=False)
    assert [stand["snapshotId"] for stand in staende] == [neu["snapshotId"]]

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

# Eine gewählte Obergrenze behält genau die neuesten Stände.
with tempfile.TemporaryDirectory() as tmp:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    erstellt = []
    for i in range(6):
        erstellt.append(m.journal_snapshot_erzeugen(daten(i + 1), "pre-sync",
            basis=tmp, jetzt=start + timedelta(hours=i), disk_usage=disk, maximum=3))
    behalten = m.journal_liste(tmp, integritaet=False)
    assert len(behalten) == 3
    assert [x["snapshotId"] for x in behalten] == [x["snapshotId"] for x in erstellt[-3:][::-1]]

# Die Obergrenze darf angeheftete und junge Vor-Wiederherstellungsstände nicht löschen.
with tempfile.TemporaryDirectory() as tmp:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manuell = m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp,
        jetzt=start, disk_usage=disk, maximum=3)
    restore = m.journal_snapshot_erzeugen(daten(2), "pre-restore", basis=tmp,
        jetzt=start + timedelta(hours=1), disk_usage=disk, maximum=3)
    for i in range(5):
        m.journal_snapshot_erzeugen(daten(i + 3), "pre-sync", basis=tmp,
            jetzt=start + timedelta(hours=i + 2), disk_usage=disk, maximum=3)
    behalten = m.journal_liste(tmp, integritaet=False)
    ids = {x["snapshotId"] for x in behalten}
    assert manuell["snapshotId"] in ids and restore["snapshotId"] in ids
    assert len(behalten) == 3

# Altersbasierte Aufbewahrung entfernt alte automatische, aber keine angehefteten Stände.
with tempfile.TemporaryDirectory() as tmp:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manuell = m.journal_snapshot_erzeugen(daten(), "manual", basis=tmp,
        jetzt=start, disk_usage=disk, tage=14)
    alt = m.journal_snapshot_erzeugen(daten(2), "pre-sync", basis=tmp,
        jetzt=start + timedelta(days=1), disk_usage=disk, tage=14)
    neu = m.journal_snapshot_erzeugen(daten(3), "pre-sync", basis=tmp,
        jetzt=start + timedelta(days=20), disk_usage=disk, tage=14)
    behalten = m.journal_liste(tmp, integritaet=False)
    ids = {x["snapshotId"] for x in behalten}
    assert manuell["snapshotId"] in ids and neu["snapshotId"] in ids
    assert alt["snapshotId"] not in ids

# Die Altersaufbewahrung lässt auch nach langer Pause den neuesten Stand übrig.
with tempfile.TemporaryDirectory() as tmp:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    m.journal_snapshot_erzeugen(daten(), "pre-sync", basis=tmp,
        jetzt=start, disk_usage=disk)
    letzter = m.journal_snapshot_erzeugen(daten(2), "pre-sync", basis=tmp,
        jetzt=start + timedelta(days=1), disk_usage=disk)
    m.journal_retention(tmp, start + timedelta(days=100), disk_usage=disk, tage=14)
    behalten = m.journal_liste(tmp, integritaet=False)
    assert [stand["snapshotId"] for stand in behalten] == [letzter["snapshotId"]]

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
alt["geloescht"]["aufgaben"] = [{"uid": "a-tot"}]
neu = m.journal_restore_daten(alt)
assert neu["syncEpoch"] != alt.get("syncEpoch")
assert neu["syncMetadaten"]["ersteSyncLoeschungsfrei"] is True
assert neu["syncMetadaten"]["quarantinedDeletes"]["geloescht"] == alt["geloescht"]
assert neu["syncMetadaten"]["quarantinedDeletes"]["geloescht"]["aufgaben"] == [{"uid": "a-tot"}]
assert neu["geloescht"] == {"termine": [], "aufgaben": [], "kontakte": []}
assert neu["tombstones"] == [] and neu["baumKontaktGeloescht"] == []
assert neu["einstellungen"]["sync"]["syncEpoch"] == neu["syncEpoch"]

# Automatic snapshots retain attachment bytes without mutating live data.
with tempfile.TemporaryDirectory() as tmp:
    mit_anhang = daten()
    mit_anhang["notizen"] = [{"id": "n1", "anhaenge": [{"name": "a.pdf",
        "sha256": "a" * 64, "daten": "data:application/pdf;base64,JVBERg=="}]}]
    stand = m.journal_snapshot_erzeugen(
        mit_anhang, "pre-change", basis=tmp, disk_usage=disk)
    _manifest, gelesen = m.journal_snapshot_lesen(stand["snapshotId"], basis=tmp)
    assert gelesen["anhaenge"] == 1
    assert gelesen["daten"]["notizen"] == mit_anhang["notizen"]
    assert m.journal_restore_daten(gelesen["daten"], daten())["notizen"] == mit_anhang["notizen"]
    assert mit_anhang["notizen"][0]["anhaenge"][0]["daten"].startswith("data:")

# Teilrestore kann Fehlendes ergänzen oder den ausgewählten Bereich ersetzen.
snapshot = daten()
snapshot["kontakte"] = [{"uid": "k1", "nachname": "Alt", "geburtstag": "1980-04-03",
                          "sync": True, "geaendert": 1},
                         {"uid": "k2", "nachname": "Zurück", "sync": True, "geaendert": 1}]
snapshot["jahrestage"] = [{"uid": "j1", "name": "Alt", "datum": "1980-04-03"}]
aktuell = daten()
aktuell["kontakte"] = [{"uid": "k1", "nachname": "Neu", "geburtstag": ""},
                        {"uid": "k3", "nachname": "Später"}]
aktuell["termine"] = [{"uid": "t-neu"}]
additiv = m.journal_restore_daten(snapshot, aktuell, ["contacts"], "additive")
assert {k["uid"] for k in additiv["kontakte"]} == {"k1", "k2", "k3"}
assert next(k for k in additiv["kontakte"] if k["uid"] == "k1")["geburtstag"] == "1980-04-03"
assert additiv["termine"] == aktuell["termine"] and len(additiv["jahrestage"]) == 1
ersetzt = m.journal_restore_daten(snapshot, aktuell, ["contacts"], "replace")
assert {k["uid"] for k in ersetzt["kontakte"]} == {"k1", "k2"}
assert ersetzt["termine"] == aktuell["termine"]
assert all(k["geaendert"] > 1 for k in ersetzt["kontakte"] if k.get("sync"))
voll = m.journal_restore_daten(snapshot, aktuell, ["all"], "replace")
assert voll["kontakte"][0]["nachname"] == "Alt"
for bereiche, aktueller_stand in ((["all", "contacts"], aktuell), (["contacts"], None)):
    try:
        m.journal_restore_daten(snapshot, aktueller_stand, bereiche, "replace")
        raise AssertionError("ungültige Wiederherstellungswahl wurde angenommen")
    except ValueError:
        pass

print("Wiederherstellungsjournal-Vertrag: ok")
