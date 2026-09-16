"""Regression coverage for the 2026-09-10 desktop data review; fake DAV only."""
import copy
from datetime import datetime, timezone

import pytest
from test_nextcloud import m, SyncDav, run_sync, empty_data, event_ics


@pytest.mark.parametrize("kind", ["termine", "aufgaben", "kontakte"])
def test_restore_missing_remote_survives_two_syncs(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    resources = {"calendar": [], "addressbook": []}
    if kind == "kontakte":
        resources["addressbook"] = [{"href": "https://cloud.example/addressbook/contact.vcf",
            "etag": '"v1"', "data": "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact\r\nFN:Contact\r\nN:Contact;;;;\r\nEND:VCARD\r\n"}]
    else:
        text = event_ics(rrule="") if kind == "termine" else (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:task\r\nSUMMARY:Task\r\nEND:VTODO\r\nEND:VCALENDAR\r\n")
        resources["calendar"] = [{"href": "https://cloud.example/calendar/fixture.ics", "etag": '"v1"', "data": text}]
    dav = SyncDav(resources)
    synced = run_sync(monkeypatch, dav, empty_data(), contacts=kind == "kontakte").payload
    assert len(synced[kind]) == 1
    restored = m.journal_restore_daten(copy.deepcopy(synced), aktuell=synced)
    dav.resources["calendar"] = []
    dav.resources["addressbook"] = []
    first = run_sync(monkeypatch, dav, restored, contacts=kind == "kontakte").payload
    assert len(first[kind]) == 1
    assert not first["syncMetadaten"]["ersteSyncLoeschungsfrei"]
    transaction = "a" * 64
    m.sync_transaktion_ergebnis(first, transaction)
    m.sync_transaktion_schreiben({"id": transaction, "phase": "complete", "zwischenstand": first})
    assert not m.sync_transaktion_abschliessen(transaction, restored)
    durable = copy.deepcopy(first)
    assert m.sync_transaktion_abschliessen(transaction, durable)
    second = run_sync(monkeypatch, dav, first, contacts=kind == "kontakte").payload
    assert len(second[kind]) == 1


@pytest.mark.parametrize("range_override", [True, False])
def test_task_range_override_removal_refreshes_expansion(monkeypatch, range_override):
    monkeypatch.setitem(m._REGIONAL, "timeZone", "UTC")
    master = "BEGIN:VTODO\r\nUID:series\r\nSUMMARY:Master\r\nDTSTART:20260901T090000Z\r\nDUE:20260901T100000Z\r\nRRULE:FREQ=DAILY;COUNT=30\r\nLAST-MODIFIED:20260901T000000Z\r\nEND:VTODO\r\n"
    override = "BEGIN:VTODO\r\nUID:series\r\nSUMMARY:Shifted\r\nRECURRENCE-ID;RANGE=THISANDFUTURE:20260910T090000Z\r\nDTSTART:20260910T110000Z\r\nDUE:20260910T120000Z\r\nLAST-MODIFIED:20260901T000000Z\r\nEND:VTODO\r\n"
    if not range_override:
        override = override.replace(";RANGE=THISANDFUTURE", "")
    resource = {"href": "https://cloud.example/calendar/fixture.ics", "etag": '"v1"',
                "data": "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + master + override + "END:VCALENDAR\r\n"}
    dav = SyncDav({"calendar": [resource], "addressbook": []})
    before = run_sync(monkeypatch, dav, empty_data()).payload
    if range_override:
        assert next(a for a in before["aufgaben"] if a["uid"] == "series")["icsRangeOverrides"]
    assert len(before["aufgaben"]) == 2
    modified = override.replace("T110000Z", "T130000Z").replace("T120000Z", "T140000Z")
    resource.update(etag='"v2"', data="BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + master + modified + "END:VCALENDAR\r\n")
    before = run_sync(monkeypatch, dav, before).payload
    assert any(item.get("startZeit") == "13:00" for item in before["aufgaben"])
    resource.update(etag='"v3"', data="BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + master + "END:VCALENDAR\r\n")
    after = run_sync(monkeypatch, dav, before).payload
    assert len(after["aufgaben"]) == 1
    assert not after["aufgaben"][0].get("icsRangeOverrides")
    expanded = m._ics_vorkommen(after["aufgaben"][0], datetime(2026, 9, 11, tzinfo=timezone.utc),
        datetime(2026, 9, 12, tzinfo=timezone.utc), aufgabe=True)
    assert expanded[0]["startZeit"] == "09:00"


def test_reconciled_save_requires_complete_durable_proof(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    transaction = "b" * 64
    baseline = {key: [] for key in ("termine", "aufgaben", "kontakte", "jahrestage")}
    baseline["geloescht"] = {key: [] for key in ("termine", "aufgaben", "kontakte")}
    baseline["aufgaben"] = [{"id": "one", "uid": "one", "titel": "before"}]
    result = copy.deepcopy(baseline)
    result.update(syncAbgleichBasis=copy.deepcopy(baseline), letzterSync=1, letzteSyncs={},
                  syncMetadaten={"syncEpoch": "epoch"})
    result["aufgaben"][0]["notiz"] = "remote note"
    m.sync_transaktion_ergebnis(result, transaction)
    m.sync_transaktion_schreiben({"id": transaction, "phase": "complete", "zwischenstand": result})
    proof = copy.deepcopy(baseline)
    proof["transactionId"] = transaction
    proof["aufgaben"][0]["titel"] = "intervening edit"
    saved = copy.deepcopy(result)
    saved["syncAbgleichNachweis"] = proof
    saved["aufgaben"][0]["titel"] = "intervening edit"
    incomplete = copy.deepcopy(saved)
    del incomplete["aufgaben"][0]["notiz"]
    assert not m.sync_transaktion_abschliessen(transaction, incomplete)
    wrong_transaction = copy.deepcopy(saved)
    wrong_transaction["syncAbgleichNachweis"]["transactionId"] = "c" * 64
    assert not m.sync_transaktion_abschliessen(transaction, wrong_transaction)
    assert m.sync_transaktion_abschliessen(transaction, saved)
