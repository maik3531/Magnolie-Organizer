import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_personal_sync as sync
import magnolie_telefon as phone
from test_personal_sync import _personal_service
from test_locale_completeness import _catalog

CONTRACTS = ROOT.parent / "contracts"
V = json.loads((CONTRACTS / "personal-custom-v4-vectors.json").read_text())
C = json.loads((CONTRACTS / "personal-custom-consent-v4-vectors.json").read_text())


def test_exact_wire_vectors_and_schema():
    schema = json.loads((CONTRACTS / "personal-custom-v4.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    assert sync.canonical(V["batch"]).decode() == V["canonical"]
    for body in (V["batch"], V["deletion"]):
        sync.validate_custom_body("personal_sync.custom_batch", body)
        validator.validate(body)
    for change in ({"textItemId": "secret"}, {"date": "2028-02-30"}, {"completed": 1},
                   {"time": "24:00"}, {"timezone": "Not/AZone"}):
        body = copy.deepcopy(V["batch"])
        body["upserts"][0]["value"].update(change)
        body["upserts"][0]["hash"] = sync.projection_hash(body["upserts"][0]["value"])
        with pytest.raises(ValueError):
            sync.validate_custom_body("personal_sync.custom_batch", body)
    body = copy.deepcopy(V["batch"]); body["upserts"] *= 2
    with pytest.raises(ValueError):
        sync.validate_custom_body("personal_sync.custom_batch", body)


def test_desktop_actual_snapshot_functions_validate_on_python():
    runtime = shutil.which("bun") or shutil.which("node")
    assert runtime, "JavaScript runtime required for cross-source snapshot check"
    result = subprocess.run([runtime, str(ROOT.parent / "Magnolie-Organizer-Windows-2.0.0/tests/personal-custom-snapshot.js"), "--emit"],
                            check=True, capture_output=True, text=True, timeout=30)
    for body in json.loads(result.stdout).values():
        sync.validate_custom_body("personal_sync.custom_batch", body)


def test_native_sender_durable_scope_revocation_and_mixed_peers(tmp_path):
    events = []
    service, peer_id = _personal_service(tmp_path, lambda event, body: events.append((event, body)))
    peer = service.store.peer(peer_id)
    peer["capabilities"] = phone.desktop_capabilities()
    peer["custom_sync"] = {"local": C["remote"], "remote": C["local"]}
    # Ordinary task permission remains OFF on both sides; Custom is independent.
    assert not peer["local_grants"]["grants"]["personal_tasks_sync"]
    service.store.save_peers()
    identifier = service.send_personal_sync(peer_id, "personal_sync.custom_batch", V["batch"])
    assert identifier in {m["message_id"] for m in service.store.pending(peer_id)}
    reopened = phone.PhoneService(str(tmp_path / "phone"), "Test", callback=lambda *_: None)
    assert reopened.store.peer(peer_id)["custom_sync"] == peer["custom_sync"]
    assert reopened._custom_allowed(peer_id, "personal_sync.custom_batch", V["batch"], True)
    reopened.send_personal_sync(peer_id, "personal_sync.custom_settings", C["revoked"])
    assert identifier not in {m["message_id"] for m in reopened.store.pending(peer_id)}
    assert not reopened._custom_allowed(peer_id, "personal_sync.custom_batch", V["batch"], True)
    # A batch captured before revocation cannot be sent after a new opt-in.
    reopened.send_personal_sync(peer_id, "personal_sync.custom_settings", C["reenabled"])
    assert not reopened._custom_allowed(peer_id, "personal_sync.custom_batch", V["batch"], True)
    reopened.store.peer(peer_id)["capabilities"]["items"]["personal_tasks_sync"]["versions"] = [1, 2, 3]
    with pytest.raises(RuntimeError):
        reopened.send_personal_sync(peer_id, "personal_sync.custom_settings", C["reenabled"])


def test_control_ack_after_save_and_duplicate_does_not_drop_batch(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id); peer["capabilities"] = phone.desktop_capabilities()
    peer["custom_sync"] = {"local": C["remote"], "remote": C["local"]}; service.store.save_peers()
    identifier = service.send_custom_sync(peer_id, "personal_sync.custom_batch", V["batch"])
    responses = []
    class Channel:
        def send(self, value):
            # ACK is observed only after reopening confirms the persisted consent.
            persisted = phone.PhoneStore(str(tmp_path / "phone"), "Test")
            assert persisted.peer(peer_id)["custom_sync"]["remote"] == C["local"]
            responses.append(value)
    now = phone.now_ms()
    packet = dict(type="message", v=1, message_id=str(uuid.uuid4()), kind="personal_sync.custom_settings",
                  created_ms=now, expires_ms=now + 60000, body=C["local"])
    service._payload(peer, Channel(), packet)
    assert responses[-1]["status"] == "accepted"
    assert identifier in {m["message_id"] for m in service.store.pending(peer_id)}


def test_all_twenty_manual_resources_match_frozen_text():
    data = json.loads((CONTRACTS / "personal-custom-ui.json").read_text())
    ui = json.loads((CONTRACTS / "ui-bugfixes.json").read_text())
    assert len(data["translations"]) == 20
    assert data["translations"].keys() == ui["translations"].keys()
    assert set(data["ids"]) & set(ui["ids"]) == set(data["ids"][:4])
    # The reviewed UI overlay owns these four labels; deletion/keep wording stays frozen.
    for locale, values in data["translations"].items():
        for index, name in enumerate(data["ids"][:4]):
            values[index] = ui["translations"][locale][ui["ids"].index(name)]
    native = json.loads((ROOT.parent / "Magnolie-Organizer-Windows-2.0.0/app/native-i18n.json").read_text())["locales"]
    for locale, values in data["translations"].items():
        folder = "values" if locale == "en" else "values-" + ("zh-rCN" if locale == "zh_CN" else locale)
        xml = ET.parse(ROOT.parent / "magnolie-notes-1.0.13/app/src/main/res" / folder / "strings.xml")
        resources = {node.attrib.get("name"): node.text for node in xml.findall("string")}
        for index, (key, msgid, text) in enumerate(zip(data["ids"], data["translations"]["en"], values)):
            assert resources[key].replace("\\'", "'").replace('\\"', '"') == text
            if locale != "en" and index in (0, 2, 3):
                assert native[locale][msgid] == text
                for base in (ROOT / "po", ROOT.parent / "Magnolie-Organizer-Windows-2.0.0/app/po"):
                    entry = _catalog(base / (locale + ".po"))[(None, msgid)]
                    assert entry["values"] == [text]
                    assert "fuzzy" not in entry["flags"]


def test_failed_consent_save_is_fail_closed_and_never_acknowledged(tmp_path, monkeypatch):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id); peer["capabilities"] = phone.desktop_capabilities()
    peer["custom_sync"] = {"local": C["remote"], "remote": C["local"]}; service.store.save_peers()
    with monkeypatch.context() as patch:
        patch.setattr(service.store, "save_peers", lambda: (_ for _ in ()).throw(OSError("synthetic fsync failure")))
        with pytest.raises(OSError):
            service.send_custom_sync(peer_id, "personal_sync.custom_settings", C["revoked"])
        assert not service._custom_allowed(peer_id, "personal_sync.custom_batch", V["batch"], True)
    service.send_custom_sync(peer_id, "personal_sync.custom_settings", C["revoked"])
    assert not phone.PhoneStore(str(tmp_path / "phone"), "Test").peer(peer_id)["custom_sync"]["local"]["enabled"]


def test_consent_ack_precedes_data_and_controls_cannot_be_starved(tmp_path):
    service, peer_id = _personal_service(tmp_path, lambda *_: None)
    peer = service.store.peer(peer_id); peer["capabilities"] = phone.desktop_capabilities()
    peer["custom_sync"] = {"local": C["remote"], "remote": C["local"]}; service.store.save_peers()
    bodies = [service.store.queue(peer_id, "personal_sync.custom_batch", V["batch"], 60000) for _ in range(40)]
    setting = service.store.queue(peer_id, "personal_sync.custom_settings", C["remote"], 60000)
    assert service.store.pending(peer_id)[0]["message_id"] == setting["message_id"]
    sent = []
    class Channel:
        def send(self, body): sent.append(body)
    assert not service._send_message(Channel(), peer_id, bodies[0])
    assert not sent
    service.store.acknowledge(peer_id, setting["message_id"])
    assert service._send_message(Channel(), peer_id, bodies[0])
    assert len(sent) == 1


@pytest.mark.parametrize("zone", ["UTC", "GMT", "Europe/Berlin", "US/Eastern", "Asia/Calcutta", "Etc/GMT+5", "EST", "MST", "HST", "CET", "EET", "MET", "WET", "EST5EDT", "CST6CDT", "MST7MDT", "PST8PDT"])
def test_iana_aliases(zone):
    body = copy.deepcopy(V["batch"])
    body["upserts"][0]["value"]["timezone"] = zone
    body["upserts"][0]["hash"] = sync.projection_hash(body["upserts"][0]["value"])
    sync.validate_custom_body("personal_sync.custom_batch", body)


@pytest.mark.parametrize("zone", ["W. Europe Standard Time", "+01:00", "GMT+01:00", "UTC+01:00", "Z", "Unknown/Shape", "localtime", "posixrules", "right/Europe/Berlin", "SystemV/EST5", "europe/berlin"])
def test_non_iana_rejected(zone):
    body = copy.deepcopy(V["batch"])
    body["upserts"][0]["value"]["timezone"] = zone
    body["upserts"][0]["hash"] = sync.projection_hash(body["upserts"][0]["value"])
    with pytest.raises(ValueError):
        sync.validate_custom_body("personal_sync.custom_batch", body)


def test_canonical_parsed_edges():
    assert sync.canonical(json.loads('{"n":-0,"ordinal":-1}')) == b'{"n":0,"ordinal":-1}'
    assert sync.canonical(json.loads('"\\ud83d\\ude00"')) == '"\U0001f600"'.encode()
    for raw in ['"\\ud800"', '{"\\udfff":1}', '0.5', '1e0', 'NaN']:
        with pytest.raises((ValueError, UnicodeError)):
            sync.canonical(json.loads(raw))
    with pytest.raises((ValueError, UnicodeError)):
        phone.strict_json(b'"\xff"')


def test_native_custom_ack_only_after_receiver_confirmation(tmp_path):
    events = []
    service, peer_id = _personal_service(tmp_path, lambda event, body: events.append((event, body)))
    peer = service.store.peer(peer_id)
    peer["capabilities"] = phone.desktop_capabilities()
    peer["custom_sync"] = {"local": C["remote"], "remote": C["local"]}
    service.store.save_peers()
    class Channel:
        def send(self, body): pass
    for status, error in [("rejected", "temporary_failure"), ("rejected", "not_granted"), ("accepted", "none"), ("duplicate", "none")]:
        identifier = service.send_custom_sync(peer_id, "personal_sync.custom_batch", V["deletion"])
        assert not [e for e in events if e[0] == "personal_custom_ack"]
        service._payload(peer, Channel(), dict(type="ack", message_id=identifier, status=status, error=error))
        receipts = [body for event, body in events if event == "personal_custom_ack"]
        assert bool(receipts) == (status != "rejected")
        if receipts:
            assert receipts == [{"device_id": peer_id, "body": {key: V["deletion"][key] for key in ("source_id", "revision", "deletions")}}]
        if error == "temporary_failure":
            assert identifier in {m["message_id"] for m in service.store.pending(peer_id)}
        events.clear()
