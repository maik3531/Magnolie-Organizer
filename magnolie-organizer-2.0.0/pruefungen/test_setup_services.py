import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_setup_state import SetupServices, write_state


@pytest.mark.parametrize("source,extension,art", [
    ("ics", "ics", "ics"), ("vcard", "vcf", "vcf"), ("ldif", "ldif", "claws"),
    ("claws", "xml", "claws"), ("csv-lotus", "csv", "lotus"),
    ("thunderbird", "ics", "ics"), ("thunderbird", "vcf", "vcf"),
])
def test_setup_delegates_files_without_writing_profile(tmp_path, source, extension, art):
    calls = []
    path = tmp_path / ("fixture." + extension)
    path.write_bytes(b"fixture content")
    services = SetupServices(lambda *args: calls.append(args) or {"kontakte": [{"name": "Fixture"}]},
                             lambda *_: pytest.fail("No automatic profile reads for a file"),
                             lambda: pytest.fail("No configuration writes during import"))
    result = services.prepare_import(source, str(path))
    assert calls == [(art, b"fixture content", str(path))]
    assert result["art"] == art
    assert list(tmp_path.iterdir()) == [path]


def test_thunderbird_detection_is_lazy_and_empty_result_requests_picker():
    calls = []
    services = SetupServices(None, lambda source: calls.append(source) or {}, None)
    assert calls == []
    assert services.prepare_import("thunderbird") is None
    assert calls == ["thunderbird"]


def test_staged_personal_data_is_not_saved_in_setup_marker(tmp_path):
    marker = tmp_path / "setup-state.json"
    selections = {"oneTimeImports": [], "stagedImports": [{"source": "vcard", "payload":
                  {"kontakte": [{"name": "PRIVATE FIXTURE"}]}}]}
    write_state("complete", selections, str(marker))
    assert "PRIVATE FIXTURE" not in marker.read_text()
    assert "stagedImports" not in json.loads(marker.read_text())["selections"]
    assert selections["stagedImports"][0]["payload"]["kontakte"]


def test_connection_draft_is_only_committed_explicitly():
    calls = []
    class Store:
        def save(self, *args, **kwargs):
            calls.append((args, kwargs))
    services = SetupServices(None, None, Store)
    services.connections["opaque"] = ("generic-dav", "https://example.invalid", "fixture", "memory-only")
    assert calls == []
    services.commit_connection("opaque")
    assert calls == [((True, False, "https://example.invalid", "fixture", "memory-only"), {"account_type": "generic-dav"})]
    services.close()
    assert not services.connections


def test_thunderbird_profile_version_is_optional_and_selection_triggered(tmp_path):
    (tmp_path / "compatibility.ini").write_text("[Compatibility]\nLastVersion=143.0_fixture\n")
    calls = []
    services = SetupServices(None, lambda _: {"kontakte": [{"name": "Fixture"}]}, None,
                             thunderbird_profiles=lambda: calls.append(True) or [str(tmp_path)])
    assert calls == []
    assert services.prepare_import("thunderbird")["sourceVersion"] == "143.0_fixture"
    assert calls == [True]


def test_phone_startup_rejects_unauthenticated_transport():
    from magnolie_setup_state import SetupPhoneServices
    services = SetupPhoneServices(lambda: pytest.fail("No profile access"), lambda: "fixture")
    with pytest.raises(RuntimeError, match="no longer connected"):
        services.commit_startup(["wifi"])


def test_finish_settings_restart_persists_connection_without_background(tmp_path, monkeypatch):
    import magnolie_hintergrund as background
    from magnolie_telefon import PhoneService
    from magnolie_setup_state import SetupPhoneServices
    services = SetupPhoneServices(lambda: str(tmp_path), lambda: "Fixture")
    services.phone = PhoneService(str(tmp_path / "phone"), "Fixture")
    services.connected = lambda: ["wifi"]
    monkeypatch.setattr(background, "write_settings", lambda *_: pytest.fail("No background opt-in"))
    monkeypatch.setattr(background, "start_service", lambda: pytest.fail("No host service startup"))
    markers = []
    services.finish_setup(lambda *args: markers.append(args), {"phoneBackgroundServices": []})
    assert markers[0][0] == "complete"
    assert services.phone.store.settings()["enabled"] is True
    services.close()
    restarted = PhoneService(str(tmp_path / "phone"), "Fixture")
    assert restarted.enabled is True
    assert restarted.store.identity == services.phone.store.identity


def test_cancel_and_no_verified_connection_leave_settings_unchanged(tmp_path):
    from magnolie_telefon import PhoneService
    from magnolie_setup_state import SetupPhoneServices
    services = SetupPhoneServices(lambda: str(tmp_path), lambda: "Fixture")
    services.phone = PhoneService(str(tmp_path / "phone"), "Fixture")
    services.connected = lambda: []
    services.commit_startup([])
    assert not Path(services.phone.store.settings_path).exists()
    services.close()
    with pytest.raises(RuntimeError, match="cancelled"):
        services.commit_startup([])
    assert not Path(services.phone.store.settings_path).exists()


def test_phone_startup_changes_only_explicit_required_permissions(tmp_path):
    import types
    from magnolie_setup_state import SetupPhoneServices
    writes, enabled = [], []
    settings = {"enabled": False, "autostart": False, "permissions": {
        "phone_monitor": False, "kde_pairing": False, "phone_selected_notifications": False,
        "phone_sms_notifications": False, "phone_personal_sync_offers": False}}
    services = SetupPhoneServices(lambda: pytest.fail("No organizer access"), lambda: "fixture")
    services.phone = types.SimpleNamespace(store=types.SimpleNamespace(save_settings=enabled.append,
        settings_path=str(tmp_path / "phone-settings.json"), settings=lambda: {"enabled": False}))
    services.connected = lambda: ["wifi"]
    services._commit_startup_local(["wifi"], lambda: settings, lambda value: writes.append(value), start_service=False)
    assert enabled == [True] and len(writes) == 1
    assert {key for key, value in writes[0]["permissions"].items() if value} == {"phone_monitor"}
    assert not any(settings["permissions"].values())


def test_setup_real_importers_read_only_fixture_files(tmp_path, monkeypatch):
    import sqlite3
    from modul_laden import quellmodul_laden
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(key, str(tmp_path))
    program = quellmodul_laden("setup_fixture_importers", Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer")
    services = SetupServices(program.import_rohdaten_lesen,
        lambda source: program.lokal_scannen(basis=str(tmp_path), quelle=source),
        lambda: pytest.fail("Import must not save connections"))
    fixtures = [
        ("vcard", "vcf", "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Fixture Contact\r\nN:Contact;Fixture;;;\r\nEND:VCARD\r\n", "kontakte"),
        ("ics", "ics", "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:fixture-event\r\nDTSTART;VALUE=DATE:20260909\r\nSUMMARY:Fixture Event\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", "termine"),
        ("ldif", "ldif", "dn: cn=Fixture\nobjectClass: inetOrgPerson\ncn: Fixture LDIF\nsn: LDIF\ngivenName: Fixture\nmail: fixture@example.invalid\n\n", "kontakte"),
        ("csv-lotus", "csv", "Vorname;Nachname;E-Mail\nFixture;CSV;fixture@example.invalid\n", "kontakte"),
    ]
    for source, extension, content, key in fixtures:
        path = tmp_path / (source + "." + extension)
        path.write_text(content)
        assert services.prepare_import(source, str(path))[key]
    assert services.prepare_import("claws", str(tmp_path / "ldif.ldif"))["kontakte"]
    assert services.prepare_import("thunderbird") is None
    profile = tmp_path / ".thunderbird" / "fixture.default"
    profile.mkdir(parents=True)
    with sqlite3.connect(profile / "abook.sqlite") as db:
        db.executescript("CREATE TABLE properties(card TEXT,name TEXT,value TEXT); INSERT INTO properties VALUES('fixture','DisplayName','Fixture Thunderbird'),('fixture','LastName','Thunderbird'),('fixture','FirstName','Fixture');")
    assert services.prepare_import("thunderbird")["kontakte"]
