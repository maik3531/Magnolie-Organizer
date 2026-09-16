import copy
import json
import pathlib
import threading
import sqlite3
import uuid

import pytest

from test_nextcloud import m, nc, SyncDav, empty_data, run_sync, event_ics, task_ics, contact_vcf


@pytest.mark.parametrize("xml", [b"<error/>", b"<multistatus/>", b"<x xmlns='wrong'><response/></x>"])
def test_report_requires_multistatus_root(xml):
    client = nc.DavHttpClient("https://fixture.invalid", "synthetic", "synthetic",
                              transport=lambda *args: (207, {}, xml))
    with pytest.raises(nc.NextcloudError):
        nc.NextcloudDav(client).report("https://fixture.invalid/calendar/", "calendar")


@pytest.mark.parametrize("kind,collection,field,wire", [
    ("event", "calendar", "termine", event_ics),
    ("task", "calendar", "aufgaben", task_ics),
    ("contact", "addressbook", "kontakte", contact_vcf)])
def test_stale_tombstones_never_mutate_remote(monkeypatch, kind, collection, field, wire):
    resource = {"href": "https://cloud.example/%s/item" % collection, "etag": '"v1"', "data": wire()}
    dav = SyncDav({"calendar": [], "addressbook": []})
    dav.resources[collection] = [resource]
    initialized = run_sync(monkeypatch, dav, empty_data(), collection == "calendar", collection == "addressbook").payload
    tombstone = copy.deepcopy(initialized[field][0]); tombstone["zeit"] = 9999999999999
    initialized[field] = []; initialized["geloescht"][field] = [tombstone]
    resource["etag"] = '"v2"'  # REV/LAST-MODIFIED deliberately unchanged.
    for _ in range(2):
        with pytest.raises(nc.NextcloudError):
            run_sync(monkeypatch, dav, copy.deepcopy(initialized), collection == "calendar", collection == "addressbook")
    assert not dav.puts and not dav.deletes
    assert initialized["geloescht"][field] == [tombstone]


@pytest.mark.parametrize("siblings", [False, True])
def test_personal_content_change_and_two_saved_followups(monkeypatch, siblings):
    class MemoryDav(SyncDav):
        def put(self, href, data, etag=None, create=False):
            current = self.resources["calendar"][0]
            assert etag == current["etag"] and not create
            self.puts.append(data)
            current.update(data=data, etag='"v%d"' % (len(self.puts) + 1))
            return current["etag"]
    text = task_ics(uid="parent")
    if siblings:
        child = "BEGIN:VTODO\r\nUID:child\r\nRELATED-TO;RELTYPE=PARENT:parent\r\nSUMMARY:Child\r\nEND:VTODO\r\n"
        text = text.replace("END:VCALENDAR", child + "END:VCALENDAR")
    dav = MemoryDav({"calendar": [{"href": "https://cloud.example/calendar/item.ics", "etag": '"v1"', "data": text}], "addressbook": []})
    data = run_sync(monkeypatch, dav, empty_data()).payload
    for item in data["aufgaben"]:
        item["titel"] = "phone edit without timestamp change: " + item["uid"]
    for _ in range(3):
        data = run_sync(monkeypatch, dav, json.loads(json.dumps(data))).payload
        assert data["ok"] and len(data["aufgaben"]) == (2 if siblings else 1)
    assert len(dav.puts) == (2 if siblings else 1)
    assert "phone edit" in dav.puts[0]


def test_upgrade_retains_uncertain_legacy_envelope_without_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(m, "baum_senden_fs", lambda *args: pytest.fail("Uncertain legacy delivery converted to FS1"))
    envelope = {"zaehler": 7, "daten": "synthetic-existing-envelope"}
    partner = {"kennung": "peer", "bestaetigt": True, "protokoll": "baum-fs1", "adresse": "127.0.0.1", "port": 8737}
    item = {"briefUmschlag": envelope}
    assert not m.baum_senden({"kennung": "own"}, partner, "aufgabe", {"titel": "fixture"},
        sender=lambda uri, payload: calls.append(payload) or True,
        gespeicherter_umschlag=envelope, transport_id="AAAAAAAAAAAAAAAAAAAAAA==",
        sendung=item, sichern=lambda: True)
    assert calls == [] and item["unsicher"]
    fs_calls = []
    monkeypatch.setattr(m, "baum_senden_fs", lambda *args: fs_calls.append(args) or True)
    assert m.baum_senden({"kennung": "own"}, partner, "aufgabe", {"titel": "new message"},
                         transport_id="AAAAAAAAAAAAAAAAAAAAAA==")
    assert len(fs_calls) == 1 and calls == []


def complete_result():
    return dict(empty_data(), aufgaben=[], letzterSync=100)


@pytest.mark.parametrize("encrypted", [False, True])
def test_journal_requires_matching_on_disk_save_and_explicit_ack(monkeypatch, tmp_path, encrypted):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    path = tmp_path / "daten.json"
    monkeypatch.setattr(m, "daten_datei", lambda: str(path))
    transaction = "a" * 64
    result = complete_result(); result["termine"] = [{"uid": "u", "titel": "received"}]
    result["aufgaben"] = [{"uid": "task", "titel": "Task", "davHref": "remote", "davEtag": "v1",
        "syncQuellen": {"source": {"id": "remote", "etag": "v1"}}}]
    m.sync_transaktion_schreiben({"id": transaction, "phase": "complete", "zwischenstand": result})
    journal = pathlib.Path(m.sync_transaktionsdatei(transaction))

    class Probe:
        _daten_sperre = threading.RLock()
        _gesperrt = False
        _kennwort = "synthetic-password" if encrypted else ""
        def antwort(self, callback, value): self.response = callback, value
    probe = Probe()
    def save(data):
        text = json.dumps(data)
        if encrypted: text = m.daten_huelle_anlegen(text, probe._kennwort)[0]
        m.atomar_text_schreiben(str(path), text)
    save(complete_result())
    assert not m.Fenster._sync_bestaetigen(probe, transaction)
    assert journal.exists()
    assert not m.Fenster._sync_bestaetigen(probe, "b" * 64)
    assert journal.exists()
    normalized = copy.deepcopy(result)
    del normalized["aufgaben"][0]["davHref"]
    del normalized["aufgaben"][0]["davEtag"]
    save(normalized)
    assert journal.exists()  # Saving alone is not an ACK.
    assert m.Fenster._sync_bestaetigen(probe, transaction)
    assert probe.response == ("App.syncBestaetigt", {"transactionId": transaction, "ok": True})
    assert not journal.exists()


def test_pending_journals_survive_new_work_restore_and_capacity_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    for index in range(16):
        m.sync_transaktion_schreiben({"id": "%064x" % index, "phase": "nextcloud"})
    with pytest.raises(RuntimeError):
        m.sync_transaktion_schreiben({"id": "f" * 64, "phase": "nextcloud"})
    for index in range(16):
        assert m.sync_transaktion_lesen("%064x" % index)["phase"] == "nextcloud"
        assert not m.sync_transaktion_abschliessen("%064x" % index, complete_result())


def test_shipped_single_journal_migrates_without_overwriting_pending_work(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    old_id, new_id = "a" * 64, "b" * 64
    result = complete_result(); result["syncMetadaten"]["syncEpoch"] = "before-restore"
    m.sync_transaktion_schreiben({"id": old_id, "phase": "complete", "zwischenstand": result})
    pathlib.Path(m.sync_transaktionsdatei(old_id)).rename(m.sync_transaktionsdatei())
    m.sync_transaktion_schreiben({"id": new_id, "phase": "nextcloud"})
    assert m.sync_transaktion_lesen(old_id)["zwischenstand"] == result
    restored = copy.deepcopy(result); restored["syncMetadaten"]["syncEpoch"] = "after-restore"
    assert not m.sync_transaktion_abschliessen(old_id, restored)
    assert m.sync_transaktion_abschliessen(old_id, result)
    assert m.sync_transaktion_lesen(new_id)["phase"] == "nextcloud"


def test_completed_result_replays_until_ack_without_remote_repeat(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    calls = []
    class Probe:
        _sync_ausfuehren = m.Fenster._sync_ausfuehren
        def _nextcloud_sync_ausfuehren(self, *args, **kwargs):
            calls.append(1); return complete_result()
        def antwort(self, callback, value): self.result = value
    probe = Probe()
    request = {"daten": {}, "wahl": {"kalenderUids": ["nextcloud-calendar:fixture"]}}
    first = probe._sync_ausfuehren(request, snapshot=False)
    for _ in range(2):
        assert Probe()._sync_ausfuehren(request, snapshot=False) == first
    assert calls == [1]
    assert m.sync_transaktion_lesen(first["transactionId"])["phase"] == "complete"
    assert first["syncMetadaten"]["nextcloud"]["pendingCommitId"] == first["transactionId"]
    assert m.sync_transaktion_abschliessen(first["transactionId"], first)
    assert m.sync_transaktion_abschliessen(first["transactionId"], first)


def test_personal_staging_token_lifecycle(tmp_path):
    import magnolie_telefon as phone
    import magnolie_personal_sync as contract
    store = phone.PhoneStore(str(tmp_path), "synthetic")
    peer, run = str(uuid.uuid4()), str(uuid.uuid4())
    now = phone.now_ms()
    store.remember_personal_run(peer, {"format": 3, "run_id": run, "trigger": "manual", "modules": ["tasks"]})
    def message(sequence, last):
        return {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
            "kind": "personal_sync.batch", "created_ms": now, "expires_ms": now + 60000,
            "body": {"format": 3, "run_id": run, "batch_id": str(uuid.uuid4()), "sequence": sequence,
                "last": last, "reply": False, "records": [], "records_hash": contract.records_hash([])}}
    first, final = message(0, False), message(1, True)
    assert store.stage_personal_batch(peer, first) is None
    with sqlite3.connect(store.database_path) as db:
        token = db.execute("SELECT commit_token FROM personal_batch").fetchone()[0]
    assert store.commit_personal_batch(peer, first["message_id"], token) == (peer, [])
    staged = store.stage_personal_batch(peer, final)
    restarted = phone.PhoneStore(str(tmp_path), "synthetic")
    assert restarted.ready_personal_batches()[0][1]["commit_token"] == token
    assert restarted.commit_personal_batch(peer, final["message_id"], "wrong") == (peer, [])
    assert restarted.commit_personal_batch(peer, first["message_id"], token) == (peer, [])
    assert restarted.has_personal_batch(peer, final["message_id"], token)
    assert restarted.commit_personal_batch(peer, final["message_id"], staged["commit_token"])[1] == [first["message_id"], final["message_id"]]
    assert restarted.commit_personal_batch(peer, final["message_id"], token) == (peer, [])
    with pytest.raises(ValueError):
        restarted.stage_personal_batch(peer, first)
