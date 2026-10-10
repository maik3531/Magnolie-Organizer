"""Direct DAV orchestration, conditional deletion and durable birthday recovery."""
import copy

import pytest

from test_eds_calendar_dedup import m
from test_calendar_birthday_dedup import event, local


SOURCE = "nextcloud-calendar:fixture"
COLLECTION = "https://fixture.invalid/calendar/"


def fixture(monkeypatch, tmp_path, *, initial=False, restore=False, readonly=False):
    remote = {}
    for uid in ("original", "copy"):
        text = event(uid, created="20260101T000000Z" if uid == "copy" else "20200101T000000Z")
        remote[uid] = {"href": COLLECTION + uid + ".ics", "etag": '"' + uid + '-1"',
                       "data": "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + text + "END:VCALENDAR\r\n"}
    writes = []
    archive = m.kalender_dubletten.CleanupArchive(tmp_path, SOURCE + "\0epoch", lambda: bytes([19]) * 32)

    class Dav:
        conflict = False
        crash = False
        fail_read = False

        def report(self, collection, kind):
            assert collection == COLLECTION and kind == "calendar"
            if self.fail_read:
                raise RuntimeError("synthetic REPORT failure")
            return copy.deepcopy(list(remote.values()))

        def delete(self, href, etag):
            assert href == remote["copy"]["href"] and etag == remote["copy"]["etag"]
            saved = archive.load()["operations"]["copy"]
            assert saved["phase"] == "prepared" and saved["removeText"] == remote["copy"]["data"]
            if self.conflict:
                raise RuntimeError("synthetic 412 conflict")
            writes.append((href, etag))
            del remote["copy"]
            if self.crash:
                raise RuntimeError("synthetic crash after DELETE")
            return True

        def put(self, *args, **kwargs):
            raise AssertionError("Unexpected calendar creation or update")

    dav = Dav()
    source = {"uid": SOURCE, "href": COLLECTION, "name": "Synthetic", "supportsVtodo": False,
              "readOnly": readonly}
    monkeypatch.setattr(m, "NextcloudDav", lambda _: dav)
    monkeypatch.setattr(m, "configured_client", lambda _: object())
    monkeypatch.setattr(m, "nextcloud_speicher", lambda: object())
    monkeypatch.setattr(m, "_nextcloud_quelle", lambda *_: source)
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    monkeypatch.setattr(m, "_sync_transaktionsschluessel", lambda: bytes([19]) * 32)
    items = []
    for uid in remote:
        item = local(uid, source=SOURCE)
        item["icsQuelleId"] = SOURCE
        item["davHref"], item["davEtag"] = remote[uid]["href"], remote[uid]["etag"]
        item["syncQuellen"] = {SOURCE: {"id": item["davHref"], "etag": item["davEtag"]},
                               "eds:other": {"id": "other-source-" + uid}}
        items.append(item)
    state = {"jahrestage": items, "syncEpoch": "epoch", "syncMetadaten": {
        "ersteSyncLoeschungsfrei": restore,
        "nextcloud": {"kalender": {SOURCE: {"initialisiert": not initial, "letzterSync": 1}}}}}

    def run():
        result = m.Fenster._nextcloud_sync_ausfuehren(
            object(), {"daten": copy.deepcopy(state)}, [SOURCE], "", antworten=False, snapshot=False)
        state.update(result)
        return result

    return remote, writes, state, run, dav, archive


def test_direct_dav_cleanup_preserves_other_sources_and_replays_without_writes(monkeypatch, tmp_path):
    remote, writes, state, run, _, _ = fixture(monkeypatch, tmp_path)
    assert run()["ok"] and set(remote) == {"original"} and len(writes) == 1
    for index, item in enumerate(state["jahrestage"]):
        assert item["uid"] == item["icsSerienUid"] == "original"
        assert item["davHref"] == item["syncQuellen"][SOURCE]["id"] == remote["original"]["href"]
        assert item["davEtag"] == item["syncQuellen"][SOURCE]["etag"] == remote["original"]["etag"]
        assert item["syncQuellen"]["eds:other"]["id"] == "other-source-" + ("original", "copy")[index]
    assert run()["ok"] and len(writes) == 1


@pytest.mark.parametrize("option", ["initial", "restore", "readonly"])
def test_first_import_restore_and_readonly_do_not_delete(monkeypatch, tmp_path, option):
    remote, writes, _, run, _, archive = fixture(monkeypatch, tmp_path, **{option: True})
    assert run()["ok"] and len(remote) == 2 and writes == [] and not archive.exists()


@pytest.mark.parametrize("etag", ["", 'W/"weak"', "unquoted", '"bad\r\ntag"'])
def test_missing_or_weak_etag_never_deletes(monkeypatch, tmp_path, etag):
    remote, writes, _, run, _, _ = fixture(monkeypatch, tmp_path)
    remote["copy"]["etag"] = etag
    with pytest.raises(ValueError, match="strong DAV ETag"):
        run()
    assert len(remote) == 2 and writes == []


def test_conflict_and_failed_report_preserve_local_aliases(monkeypatch, tmp_path):
    remote, writes, state, run, dav, _ = fixture(monkeypatch, tmp_path)
    before = copy.deepcopy(state)
    dav.conflict = True
    with pytest.raises(RuntimeError, match="412"):
        run()
    assert state == before and len(remote) == 2 and writes == []
    dav.conflict = False
    dav.fail_read = True
    with pytest.raises(RuntimeError, match="REPORT failure"):
        run()
    assert state == before and len(remote) == 2 and writes == []


def test_restart_after_delete_recovers_uid_and_resource_aliases(monkeypatch, tmp_path):
    remote, writes, state, run, dav, archive = fixture(monkeypatch, tmp_path)
    dav.crash = True
    with pytest.raises(RuntimeError, match="crash after DELETE"):
        run()
    assert archive.load()["operations"]["copy"]["phase"] == "prepared"
    assert state["jahrestage"][1]["uid"] == "copy" and len(remote) == 1
    dav.crash = False
    assert run()["ok"] and len(writes) == 1
    assert all(item["uid"] == "original" and item["davHref"] == remote["original"]["href"]
               for item in state["jahrestage"])


def test_changed_component_during_fresh_report_is_not_deleted(monkeypatch, tmp_path):
    remote, writes, _, run, dav, _ = fixture(monkeypatch, tmp_path)
    report = dav.report
    calls = []

    def changing_report(collection, kind):
        calls.append(collection)
        if len(calls) == 2:
            remote["copy"]["data"] = remote["copy"]["data"].replace("-PT10M", "-PT30M")
            remote["copy"]["etag"] = '"copy-2"'
        return report(collection, kind)

    dav.report = changing_report
    with pytest.raises(ValueError, match="component changed"):
        run()
    assert len(remote) == 2 and writes == []


def test_href_is_not_accepted_as_a_logical_event_uid(monkeypatch, tmp_path):
    remote, writes, state, run, _, _ = fixture(monkeypatch, tmp_path)
    for item in state["jahrestage"]:
        item.pop("syncKalenderUid")
        item.pop("icsQuelleId")
        # Even a coincidentally UID-shaped legacy source reference is insufficient.
        item["syncQuellen"][SOURCE]["id"] = item["uid"]
    assert run()["ok"] and len(remote) == 2 and writes == []
