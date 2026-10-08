"""Read-only contact protocol and live-request authorization; no real phone."""
import copy
import threading
import uuid

import pytest
from test_background_reliability import phone, private
import magnolie_phone_contacts as contract


def request(action="index", uids=None, offset=0):
    return {"version": 5, "request_id": str(uuid.uuid4()), "action": action, "offset": offset, "uids": uids or []}


def test_pages_cannot_spin_or_mutate_contacts():
    good = request()
    contract.validate_request(good)
    for bad in [request("delete"), request("cards"), request("cards", ["x", "x"]), request(offset=True),
                request("cards", ["x\nUID:other"]), request("cards", [str(i) for i in range(6)]), dict(good, write=True)]:
        with pytest.raises(ValueError): contract.validate_request(bad)
    reply = {k: v for k, v in good.items() if k != "uids"}
    reply.update(total=0, contacts=[])
    contract.validate_report(reply)
    with pytest.raises(ValueError): contract.validate_report(dict(reply, total=1))
    with pytest.raises(ValueError): contract.validate_report(dict(reply, total=True))


class Channel:
    def __init__(self): self.sent = []
    def send(self, message): self.sent.append(copy.deepcopy(message))


@pytest.mark.parametrize("change", ["none", "unrequested", "rekey", "permission", "replacement_channel", "expired", "wrong_uid", "old_capabilities"])
def test_reply_requires_current_key_scope_channel_and_exact_selection(private, change):
    service = phone.PhoneService(str(private / "phone"), "Fixture")
    service.enabled = True
    peer_id = "22222222-2222-4222-8222-222222222222"
    peer = {"device_id": peer_id, "display_name": "Fixture", "static_public": phone.b64(b"p" * 32), "state": "paired",
            "grants": phone.desktop_grants(), "local_grants": phone.desktop_grants(), "capabilities": phone.desktop_capabilities(),
            "last_contact_ms": 0, "bluetooth": {"enabled": False, "address": ""},
            "personal_sync": {"own_device": True, "remote_own_device": True, "auto_wifi": False, "last_report": {}}}
    service.store.peers.append(peer); service.store.save_peers()
    channel = Channel(); service.connections[peer_id] = channel
    assert not service.contacts_available(peer_id), "cached capability does not authorize a fresh connection"
    service.note_controls[channel] = copy.deepcopy({"capabilities.update": peer["capabilities"], "grants.update": peer["grants"],
        "personal_sync.settings": {"format": 1, "own_device": True}})
    assert service.contacts_available(peer_id)
    body = request("cards", ["lookup:1"])
    pending = {"peer": peer_id, "key": peer["static_public"], "channel": channel, "request": body,
               "deadline": phone.time.monotonic() + 8, "event": threading.Event(), "result": None}
    service.contact_requests[body["request_id"]] = pending
    report = {k: v for k, v in body.items() if k != "uids"}
    report.update(total=1, contacts=[{"uid": "lookup:1", "timestamp": 1, "vcard": "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Fixture\r\nEND:VCARD\r\n"}])
    if change == "unrequested": report["request_id"] = str(uuid.uuid4())
    if change == "rekey": pending["key"] = phone.b64(b"q" * 32)
    if change == "permission": peer["personal_sync"]["own_device"] = False
    if change == "replacement_channel": service.connections[peer_id] = Channel()
    if change == "expired": pending["deadline"] = phone.time.monotonic() - 1
    if change == "wrong_uid": report["contacts"][0]["uid"] = "other"
    if change == "old_capabilities": service.note_controls[channel].pop("capabilities.update")
    now = phone.now_ms()
    service._receive_contacts(peer, channel, {"type": "message", "v": 1, "kind": "device_status.report",
        "message_id": str(uuid.uuid4()), "created_ms": now, "expires_ms": now + 60000, "body": report})
    assert pending["event"].is_set() == (change == "none")
    assert channel.sent[-1]["status"] == ("accepted" if change == "none" else "rejected")
    assert not service.store.status(peer_id), "contact fields must not enter the normal status cache"


@pytest.mark.parametrize("change", ["none", "other_message", "other_channel", "rekey", "expired", "accepted", "completed"])
def test_rejected_contact_ack_releases_only_the_bound_unfinished_request(private, change):
    service = phone.PhoneService(str(private / "phone"), "Fixture")
    peer_id = "22222222-2222-4222-8222-222222222222"
    peer = {"device_id": peer_id, "display_name": "Fixture", "static_public": phone.b64(b"p" * 32), "state": "paired",
            "grants": phone.desktop_grants(), "local_grants": phone.desktop_grants(), "capabilities": phone.desktop_capabilities(),
            "last_contact_ms": 0, "bluetooth": {"enabled": False, "address": ""},
            "personal_sync": {"own_device": True, "remote_own_device": True, "auto_wifi": False, "last_report": {}}}
    service.store.peers.append(peer); service.store.save_peers()
    channel = Channel(); service.connections[peer_id] = channel
    body = request("cards", ["lookup:1"])
    message_id = str(uuid.uuid4())
    pending = {"peer": peer_id, "key": peer["static_public"], "channel": channel, "request": body,
               "message_id": message_id, "deadline": phone.time.monotonic() + 8,
               "event": threading.Event(), "result": None, "error": None}
    service.contact_requests[body["request_id"]] = pending
    if change == "other_message": message_id = str(uuid.uuid4())
    if change == "other_channel": channel = Channel()
    if change == "rekey": pending["key"] = phone.b64(b"q" * 32)
    if change == "expired": pending["deadline"] = phone.time.monotonic() - 1
    if change == "completed": pending["result"] = {"already": "validated"}
    ack = {"type": "ack", "message_id": message_id,
           "status": "accepted" if change == "accepted" else "rejected",
           "error": "none" if change == "accepted" else "temporary_failure"}
    service._payload(peer, channel, ack)
    assert pending["event"].is_set() == (change == "none")
    assert pending["error"] == ("temporary_failure" if change == "none" else None)
