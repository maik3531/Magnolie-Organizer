"""Concurrent CardDAV contact edits must wait for a source-bound user decision."""
import copy
import pytest

from test_startup_read_failure import native


def conflict(native):
    source = "generic-dav-addressbook:fixture"
    base = {"id": "local", "uid": "person", "vorname": "Original", "sync": True, "geaendert": 10}
    native._dav_syncquelle_setzen(base, source, "/book/person.vcf", '"v1"')
    local = copy.deepcopy(base); local.update(vorname="Local", geaendert=30)
    remote = {"uid": "person", "vorname": "Remote", "geaendert": 40}
    metadata = {"person": {"href": "/book/person.vcf", "etag": '"v2"'}}
    return source, local, remote, metadata


def test_concurrent_contact_change_stages_without_duplicate_or_provider_write(native):
    source, local, remote, metadata = conflict(native)
    before = copy.deepcopy(local)
    contacts, create, change, delete, count = native.sync_merge(
        [local], {"person": remote}, [], 20, native.KONTAKT_FELDER, dav=(source, {}, metadata))
    assert len(contacts) == 1, "contact conflict created a second person"
    assert not create and not change and not delete
    assert contacts[0]["vorname"] == "Local"
    assert contacts[0]["syncQuellen"] == before["syncQuellen"]
    pending = contacts[0]["kontaktProviderKonflikte"][source]
    assert pending["kontakt"]["vorname"] == "Remote"
    assert pending["mapping"]["etag"] == '"v2"'
    assert count["konflikte"] == 1
    native._dav_syncquelle_setzen(contacts[0], source, "/book/person.vcf", '"v2"')
    assert contacts[0]["syncQuellen"] == before["syncQuellen"], "post-sync bookkeeping acknowledged an unresolved conflict"


@pytest.mark.parametrize("first", [False, True])
def test_identical_contact_metadata_and_photo_do_not_remain_pending(native, first):
    source = "eds:synthetic"
    local = {"id": "local", "uid": "person", "vorname": "Same", "geaendert": 10,
             "foto": "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==", "fotoManuell": True,
             "vcardRoundtrip": ["REV:20260101T000000Z", "PRODID:old"]}
    remote = {"uid": "person", "vorname": "Same", "geaendert": 99,
              "foto": "data:image/gif;base64,R0lGODlhAQABAIAAAAD/AP///ywAAAAAAQABAAACAUwAOw==",
              "vcardRoundtrip": ["REV:20261006T000000Z", "PRODID:new", "PHOTO:https://example.invalid/photo"]}
    native._kontakt_provider_pruefung(local, remote, source, {"href": "person"}, transport="eds")
    if first:
        contacts, _ = native.kontakte_erster_sync([local], {"person": remote}, kontakt_quelle=source)
    else:
        contacts, create, change, delete, count = native.sync_merge([local], {"person": remote}, [], 20,
            native.KONTAKT_FELDER, kontakt_quelle=source)
        assert not create and not change and not delete and count["konflikte"] == 0
    assert len(contacts) == 1 and not contacts[0].get("kontaktProviderKonflikte")
    assert contacts[0]["foto"] == local["foto"]
    assert any(item["foto"] == remote["foto"] for item in contacts[0]["fotoAlternativen"])


@pytest.mark.parametrize("first", [False, True])
def test_same_person_with_another_uid_and_photo_is_not_imported_twice(native, first):
    local = {"id": "local", "uid": "one", "vorname": "Synthetic", "nachname": "Person",
             "email": "person@example.test", "telefon": "+491711234567", "sync": True}
    remote = dict(local, uid="two", foto="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
    incoming = {"one": dict(local), "two": remote}
    if first: contacts, _ = native.kontakte_erster_sync([local], incoming)
    else: contacts, *_ = native.sync_merge([local], incoming, [], 0, native.KONTAKT_FELDER)
    assert len(contacts) == 1
    assert contacts[0]["uid"] == "one"
    assert "two" in contacts[0]["kontaktAliase"]["uids"]
    assert any(item["foto"] == remote["foto"] for item in contacts[0]["fotoAlternativen"])


def test_existing_same_person_cards_are_consolidated_without_remote_deletion(native):
    first = {"id": "first", "uid": "one", "vorname": "Synthetic", "nachname": "Person",
             "email": "person@example.test", "telefon": "+491711234567", "sync": True}
    second = dict(first, id="second", uid="two", foto="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
    contacts, create, change, delete, _ = native.sync_merge([first, second], {"one": dict(first), "two": dict(second)}, [], 0, native.KONTAKT_FELDER)
    assert len(contacts) == 1 and not create and not delete
    assert "second" in contacts[0]["kontaktAliase"]["ids"]
    assert contacts[0]["foto"] == second["foto"]


def test_remote_deletion_during_pending_review_does_not_delete_or_recreate_contact(native):
    source, local, remote, metadata = conflict(native)
    contacts, *_ = native.sync_merge([local], {"person": remote}, [], 20, native.KONTAKT_FELDER,
                                     dav=(source, {}, metadata))
    contacts, create, change, delete, _ = native.sync_merge(contacts, {}, [], 50, native.KONTAKT_FELDER,
                                                          dav=(source, {}, {}))
    assert len(contacts) == 1 and contacts[0]["vorname"] == "Local"
    assert not create and not change and not delete
    assert contacts[0]["kontaktProviderKonflikte"][source]["entfernt"] is True


def test_restore_first_sync_preserves_unresolved_contact(native):
    source, local, remote, metadata = conflict(native)
    contacts, *_ = native.sync_merge([local], {"person": remote}, [], 20, native.KONTAKT_FELDER,
                                     dav=(source, {}, metadata))
    restored, _ = native.kontakte_erster_sync(contacts, {"person": remote}, dav=(source, {}, metadata))
    assert len(restored) == 1 and restored[0]["vorname"] == "Local"
    assert restored[0]["kontaktProviderKonflikte"][source]["mapping"]["etag"] == '"v2"'


def test_explicit_keep_baseline_allows_only_the_next_guarded_local_upload(native):
    source, local, remote, metadata = conflict(native)
    contacts, *_ = native.sync_merge([local], {"person": remote}, [], 20, native.KONTAKT_FELDER,
                                     dav=(source, {}, metadata))
    current = contacts[0]
    current["syncQuellen"][source] = current["kontaktProviderKonflikte"][source]["mapping"]
    del current["kontaktProviderKonflikte"]
    contacts, create, change, delete, _ = native.sync_merge([current], {"person": remote}, [], 50,
                                                          native.KONTAKT_FELDER, dav=(source, {}, metadata))
    assert not create and not delete and len(change) == 1
    assert contacts[0]["vorname"] == "Local"


def test_first_sync_requires_review_before_changing_existing_uid(native):
    source, local, remote, metadata = conflict(native)
    local.pop("syncQuellen")
    local["sync"] = False
    contacts, plan = native.kontakte_erster_sync([local], {"person": remote}, dav=(source, {}, metadata))
    assert len(contacts) == 1 and contacts[0]["vorname"] == "Local"
    assert contacts[0]["kontaktProviderKonflikte"][source]["kontakt"]["vorname"] == "Remote"
    assert contacts[0]["syncQuellen"][source]["etag"] == "", "first review invented an acknowledged source baseline"
    assert plan["remoteAnlegen"] == plan["remoteAendern"] == plan["remoteLoeschen"] == 0


def test_unreviewed_first_sync_cannot_authorize_remote_deletion(native):
    source, local, remote, metadata = conflict(native)
    local.pop("syncQuellen")
    contacts, _ = native.kontakte_erster_sync([local], {"person": remote}, dav=(source, {}, metadata))
    tombstone = {"uid": "person", "zeit": 100, "syncQuellen": contacts[0]["syncQuellen"]}
    with pytest.raises(native.NextcloudError):
        native.sync_merge([], {"person": remote}, [tombstone], 50, native.KONTAKT_FELDER,
                          dav=(source, metadata, metadata))


@pytest.mark.parametrize("local_changed,remote_changed", [(False, False), (True, False), (False, True), (True, True)])
def test_eds_content_baselines_distinguish_one_sided_and_concurrent_changes(native, local_changed, remote_changed):
    source = "eds:fixture"
    remote = native.vcf_lesen("BEGIN:VCARD\nVERSION:3.0\nUID:person\nN:Person;Original;;;\nFN:Original Person\nEND:VCARD\n")["kontakte"][0]
    local = copy.deepcopy(remote); local.update(id="local", sync=True)
    native._kontakt_eds_baseline(local, source, remote)
    if local_changed: local["notiz"] = "Local note"
    if remote_changed: remote["firma"] = "Remote company"
    contacts, create, change, delete, _ = native.sync_merge([local], {"person": remote}, [], 9999999999999,
        native.KONTAKT_FELDER, kontakt_quelle=source)
    assert not create and not delete
    if local_changed and remote_changed:
        assert len(change) == 1 and contacts[0]["notiz"] == "Local note"
        assert contacts[0]["firma"] == "Remote company"
        assert not contacts[0].get("kontaktProviderKonflikte")
    elif local_changed:
        assert len(change) == 1 and contacts[0]["notiz"] == "Local note"
    elif remote_changed:
        assert not change and contacts[0]["firma"] == "Remote company"
    else:
        assert not change and not contacts[0].get("kontaktProviderKonflikte")


def test_eds_unknown_baseline_and_readonly_sources_never_write_unreviewed_changes(native):
    source, local, remote, _ = conflict(native)
    source = "eds:fixture"
    contacts, create, change, delete, _ = native.sync_merge([local], {"person": remote}, [], 0,
        native.KONTAKT_FELDER, kontakt_quelle=source, kontakt_nur_lesen=True)
    assert not create and not change and not delete
    assert contacts[0]["vorname"] == "Local"
    assert contacts[0]["kontaktProviderKonflikte"][source]["nurLesen"] is True
    contacts, create, change, delete, _ = native.sync_merge(contacts, {}, [], 0,
        native.KONTAKT_FELDER, kontakt_quelle=source, kontakt_nur_lesen=True)
    assert len(contacts) == 1 and not create and not change and not delete
    assert contacts[0]["kontaktProviderKonflikte"][source]["entfernt"] is True


def test_eds_explicit_keep_uses_reviewed_remote_hash_instead_of_clock_order(native):
    source = "eds:fixture"
    local = {"id": "local", "uid": "person", "vorname": "Local", "sync": True, "geaendert": 1}
    remote = {"uid": "person", "vorname": "Remote", "geaendert": 9999999999999}
    contacts, *_ = native.sync_merge([local], {"person": remote}, [], 0, native.KONTAKT_FELDER, kontakt_quelle=source)
    current = contacts[0]
    current["syncQuellen"][source] = current["kontaktProviderKonflikte"][source]["mapping"]
    current["syncQuellen"][source]["pruefungFreigegeben"] = True
    del current["kontaktProviderKonflikte"]
    contacts, create, change, delete, _ = native.sync_merge([current], {"person": remote}, [], 0,
        native.KONTAKT_FELDER, kontakt_quelle=source)
    assert contacts[0]["vorname"] == "Local" and len(change) == 1 and not create and not delete
