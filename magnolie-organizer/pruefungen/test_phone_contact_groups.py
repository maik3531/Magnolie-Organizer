"""Separate write contract, live peer binding and actual provider-report requirement."""
import copy
import hashlib
import threading
import uuid

import pytest
from test_background_reliability import phone, private
import magnolie_phone_contacts as contract


ACCOUNT = {"name": "fixture@example.test", "type": "com.google", "data_set": ""}


def request(action="prepare", token=None):
    value = {"version": contract.GROUP_WRITE_VERSION, "request_id": str(uuid.uuid4()), "action": action, "uid": "lookup:fixture"}
    if action == "apply": value.update(token=token or str(uuid.uuid4()), groups=["Work", "Own group"])
    return value


def report(body, token):
    if body["version"] == contract.GROUP_PROBE_VERSION:
        return dict(body, state="failed", stage="groups", error_type="IllegalArgumentException",
            reason="contact_groups_unknown", raw_count=1, version_count=1, account_count=1, mime_supported=False, reader_complete=True)
    return {"version": contract.GROUP_WRITE_VERSION, "request_id": body["request_id"], "action": body["action"], "uid": body["uid"],
        "token": token, "state": "prepared" if body["action"] == "prepare" else "saved",
        "groups": ["Coworkers"] if body["action"] == "prepare" else body["groups"],
        "catalog": ["Coworkers", "Work"] if body["action"] == "prepare" else [], "account": ACCOUNT}


class Channel:
    def __init__(self, service, peer): self.service = service; self.peer = peer; self.sent = []; self.ack_only = False
    def send(self, message):
        self.sent.append(copy.deepcopy(message))
        if message.get("kind") != "device_status.request": return
        if self.ack_only:
            self.service._payload(self.peer, self, {"type": "ack", "message_id": message["message_id"], "status": "accepted", "error": "none"})
            entry = self.service.contact_requests[message["body"]["request_id"]]
            assert not entry["event"].is_set()
            entry["deadline"] = phone.time.monotonic() - 1
            return
        body = message["body"]; token = body.get("token") or str(uuid.uuid4()); now = phone.now_ms()
        self.service._receive_contacts(self.peer, self, {"type": "message", "v": 1, "kind": "device_status.report",
            "message_id": str(uuid.uuid4()), "created_ms": now, "expires_ms": now + 60000, "body": report(body, token)})


def fixture(path):
    service = phone.PhoneService(str(path / "phone"), "Fixture"); service.enabled = True
    peer = {"device_id": "22222222-2222-4222-8222-222222222222", "display_name": "Fixture", "static_public": phone.b64(b"p" * 32), "state": "paired",
        "grants": phone.desktop_grants(), "local_grants": phone.desktop_grants(), "capabilities": phone.desktop_capabilities(), "last_contact_ms": 0,
        "bluetooth": {"enabled": False, "address": ""}, "personal_sync": {"own_device": True, "remote_own_device": True, "auto_wifi": False, "last_report": {}}}
    service.store.peers.append(peer); service.store.save_peers()
    channel = Channel(service, peer); service.connections[peer["device_id"]] = channel
    service.note_controls[channel] = copy.deepcopy({"capabilities.update": peer["capabilities"], "grants.update": peer["grants"],
        "personal_sync.settings": {"format": 1, "own_device": True}})
    fingerprint = hashlib.sha256(b"p" * 32).hexdigest()
    return service, peer, channel, fingerprint


def test_write_resource_is_not_a_read_request_and_rejects_ambiguous_names():
    good = request(); contract.validate_group_request(good)
    with pytest.raises(ValueError): contract.validate_request(good)
    apply = request("apply"); contract.validate_group_request(apply)
    for bad in [dict(good, version=True), dict(good, version=16), dict(good, write=True), dict(good, uid="bad\nuid"),
                dict(apply, token="invalid"), dict(apply, groups=["Work", " work "]), dict(apply, groups=["\ud800"])]:
        with pytest.raises(ValueError): contract.validate_group_request(bad)


def test_account_bound_reports_reject_the_old_schema_and_missing_account():
    good = report(request(), str(uuid.uuid4()))
    contract.validate_group_report(good)
    missing = dict(good); del missing["account"]
    for bad in [dict(good, version=16), missing, dict(good, account={"name": "fixture"}),
                dict(good, account=dict(ACCOUNT, data_set="bad\nset"))]:
        with pytest.raises(ValueError): contract.validate_group_report(bad)


def test_debug_probe_is_read_only_bounded_and_requires_negotiated_wifi(private):
    service, peer, channel, fingerprint = fixture(private)
    probe = dict(request(), version=contract.GROUP_PROBE_VERSION, action="diagnostics")
    with pytest.raises(PermissionError): service.contact_groups(peer["device_id"], fingerprint, probe)
    peer["capabilities"]["items"]["device_status"]["versions"].append(contract.GROUP_PROBE_VERSION)
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    service.connection_transports[peer["device_id"]] = "bluetooth"
    with pytest.raises(PermissionError): service.contact_groups(peer["device_id"], fingerprint, probe)
    service.connection_transports[peer["device_id"]] = "wifi"
    result = service.contact_groups(peer["device_id"], fingerprint, probe)
    assert result["state"] == "failed" and result["stage"] == "groups" and result["raw_count"] == 1
    assert not service.contact_group_preparations and not service.store.status(peer["device_id"])
    for invalid in [dict(probe, token=str(uuid.uuid4())), dict(probe, groups=["Work"]), dict(probe, action="apply")]:
        with pytest.raises(ValueError): contract.validate_group_probe_request(invalid)
    for invalid in [dict(result, account=ACCOUNT), dict(result, raw_count=True), dict(result, stage="private-contact-field"),
                    dict(result, error_type="Exception: private account"), dict(result, state="available")]:
        with pytest.raises(ValueError): contract.validate_group_probe_report(invalid)


def test_prepare_and_apply_require_the_live_bound_provider_report(private):
    service, peer, channel, fingerprint = fixture(private)
    prepared = service.contact_groups(peer["device_id"], fingerprint, request())
    assert prepared["state"] == "prepared" and prepared["account"] == ACCOUNT
    result = service.contact_groups(peer["device_id"], fingerprint, request("apply", prepared["token"]))
    assert result["state"] == "saved" and result["groups"] == ["Work", "Own group"]
    assert not service.contact_group_preparations and not service.contact_requests
    assert not service.store.status(peer["device_id"]), "Contact account/group data leaked into normal device status"
    with pytest.raises(PermissionError): service.contact_groups(peer["device_id"], fingerprint, request("apply", prepared["token"]))


def test_ready_book_in_tray_can_sync_contacts_but_locked_or_unloaded_book_cannot(private):
    service, peer, channel, fingerprint = fixture(private)
    service.personal_sync_available = lambda: False  # no visible notes-review window
    service.contact_access_available = lambda: True  # native book is still ready and unlocked
    prepared = service.contact_groups(peer["device_id"], fingerprint, request())
    assert prepared["state"] == "prepared"
    service.contact_access_available = lambda: False
    before = len(channel.sent)
    with pytest.raises(PermissionError): service.contact_groups(peer["device_id"], fingerprint, request("apply", prepared["token"]))
    assert len(channel.sent) == before


@pytest.mark.parametrize("change", ["unprepared", "fingerprint", "revoke", "old_peer", "expire", "channel"])
def test_stale_or_ungranted_group_apply_is_not_dispatched(private, change):
    service, peer, channel, fingerprint = fixture(private)
    prepared = service.contact_groups(peer["device_id"], fingerprint, request())
    apply = request("apply", prepared["token"])
    if change == "unprepared": apply["token"] = str(uuid.uuid4())
    if change == "fingerprint": fingerprint = "f" * 64
    if change == "revoke": peer["local_grants"]["grants"]["device_status"] = False
    if change == "old_peer": peer["capabilities"]["items"]["device_status"]["versions"].remove(contract.GROUP_WRITE_VERSION)
    if change == "expire": service.contact_group_preparations[prepared["token"]]["deadline"] = phone.time.monotonic() - 1
    if change == "channel":
        replacement = Channel(service, peer); service.connections[peer["device_id"]] = replacement
        service.note_controls[replacement] = copy.deepcopy(service.note_controls[channel])
    before = len(channel.sent)
    with pytest.raises(PermissionError): service.contact_groups(peer["device_id"], fingerprint, apply)
    assert len(channel.sent) == before


def test_accepted_queue_ack_does_not_claim_group_storage(private):
    service, peer, channel, fingerprint = fixture(private)
    prepared = service.contact_groups(peer["device_id"], fingerprint, request())
    channel.ack_only = True
    with pytest.raises(TimeoutError): service.contact_groups(peer["device_id"], fingerprint, request("apply", prepared["token"]))
    assert not service.contact_group_preparations and not service.contact_requests


@pytest.mark.parametrize("change", ["none", "uid", "token", "account", "groups", "version"])
def test_group_saved_report_must_match_the_exact_preparation_and_request(private, change):
    service, peer, channel, fingerprint = fixture(private)
    body = request("apply"); value = report(body, body["token"])
    entry = {"peer": peer["device_id"], "key": peer["static_public"], "channel": channel, "request": body,
        "deadline": phone.time.monotonic() + 8, "event": threading.Event(), "result": None,
        "controls": (peer["capabilities"]["revision"], peer["grants"]["revision"]),
        "group_prepared": {"account": copy.deepcopy(ACCOUNT)}}
    service.contact_requests[body["request_id"]] = entry
    value = copy.deepcopy(value)
    if change == "uid": value["uid"] = "another-contact"
    if change == "token": value["token"] = str(uuid.uuid4())
    if change == "account": value["account"]["name"] = "other@example.test"
    if change == "groups": value["groups"] = ["Coworkers"]
    if change == "version": value["version"] = True
    now = phone.now_ms()
    service._receive_contacts(peer, channel, {"type": "message", "v": 1, "kind": "device_status.report", "message_id": str(uuid.uuid4()),
        "created_ms": now, "expires_ms": now + 60000, "body": value})
    assert entry["event"].is_set() == (change == "none")
