"""Staged typed field codec: identity, exact field masks and real apply receipts."""
import copy
import pytest
import magnolie_phone_contacts as contract
from test_phone_contact_groups import fixture as group_fixture, Channel, phone, private
import uuid


ACCOUNT = {"name": "fixture@example.invalid", "type": "provider", "data_set": ""}


def messages():
    prepare = {"version": 19, "request_id": "11111111-1111-4111-8111-111111111111", "action": "prepare", "uid": "lookup:🧪",
               "field_names": ["telefone", "emailEintraege"]}
    fields = {"telefone": [{"art": "mobil", "wert": "+49 111"}], "emailEintraege": []}
    token = "22222222-2222-4222-8222-222222222222"
    apply = {key: value for key, value in prepare.items() if key != "field_names"}
    apply.update(action="apply", token=token, fields=copy.deepcopy(fields))
    report = dict(copy.deepcopy(apply), state="saved", account=copy.deepcopy(ACCOUNT))
    return prepare, apply, report


def test_preparation_and_actual_apply_reports_are_correlated():
    prepare, apply, report = messages()
    prepared = dict(report, action="prepare", state="prepared")
    contract.validate_correlated_value_report(prepared, prepare)
    contract.validate_correlated_value_report(report, apply, ACCOUNT)
    with pytest.raises(ValueError):
        contract.validate_request(prepare)
    with pytest.raises(ValueError):
        contract.validate_group_request(prepare)


def test_filtered_card_fields_never_become_complete_empty_native_lists():
    raw = "BEGIN:VCARD\r\nVERSION:3.0\r\nTEL;TYPE=CELL:111\r\nEMAIL:hidden@example.invalid\r\nEND:VCARD\r\n"
    assert contract.readable_value_fields(raw, {"telefone": [{"wert": "111"}], "emailEintraege": []}) == ["telefone"]
    assert contract.readable_value_fields(raw, {"telefone": [{"wert": "111"}], "emailEintraege": [{"wert": "hidden@example.invalid"}]}) == ["telefone", "emailEintraege"]


@pytest.mark.parametrize("change", ["request_id", "uid", "token", "account", "fields", "readback", "state"])
def test_wrong_source_mask_account_or_readback_is_not_a_save(change):
    _, apply, report = messages()
    if change in {"request_id", "token"}: report[change] = "33333333-3333-4333-8333-333333333333"
    elif change == "uid": report[change] = "foreign-native-contact"
    elif change == "account": report["account"]["name"] = "foreign@example.invalid"
    elif change == "fields": del report["fields"]["emailEintraege"]
    elif change == "readback": report["fields"]["telefone"][0]["wert"] = "old number"
    else: report["state"] = "prepared"
    with pytest.raises(ValueError): contract.validate_correlated_value_report(report, apply, ACCOUNT)


@pytest.mark.parametrize("change", ["kind", "boolean", "surrogate", "extra", "too-many", "duplicate"])
def test_malformed_values_fail_before_dispatch(change):
    _, apply, _ = messages()
    row = apply["fields"]["telefone"][0]
    if change == "kind": row["art"] = "fax"
    elif change == "boolean": row["wert"] = True
    elif change == "surrogate": row["wert"] = "\ud800"
    elif change == "extra": apply["arbitrary_write"] = True
    elif change == "duplicate": apply["fields"]["telefone"].append(copy.deepcopy(row))
    else: apply["fields"]["telefone"] = [{"art": "mobil", "wert": str(i)} for i in range(101)]
    with pytest.raises(ValueError): contract.validate_value_request_shape(apply)


class ValueChannel(Channel):
    mode = "normal"

    def send(self, message):
        self.sent.append(copy.deepcopy(message))
        if message.get("kind") != "device_status.request": return
        if self.ack_only:
            self.service._payload(self.peer, self, {"type": "ack", "message_id": message["message_id"], "status": "accepted", "error": "none"})
            entry = self.service.contact_requests[message["body"]["request_id"]]
            assert not entry["event"].is_set()
            entry["deadline"] = phone.time.monotonic() - 1
            return
        request = message["body"]
        report = {"version": 19, "request_id": request["request_id"], "action": request["action"], "uid": request["uid"],
                  "token": request.get("token") or str(uuid.uuid4()), "account": copy.deepcopy(ACCOUNT),
                  "state": "prepared" if request["action"] == "prepare" else "saved",
                  "fields": {name: [] for name in request["field_names"]} if request["action"] == "prepare" else copy.deepcopy(request["fields"])}
        def receive(value):
            now = phone.now_ms()
            self.service._payload(self.peer, self, {"type": "message", "v": 1, "kind": "device_status.report",
                "message_id": str(uuid.uuid4()), "created_ms": now, "expires_ms": now + 60000, "body": value})
        if self.mode != "normal" and request["action"] == "apply":
            wrong = copy.deepcopy(report)
            if self.mode == "account": wrong["account"]["name"] = "foreign@example.invalid"
            else: wrong["fields"]["telefone"] = [{"art": "mobil", "wert": "old number"}]
            receive(wrong)
            assert not self.service.contact_requests[request["request_id"]]["event"].is_set()
        receive(report)


def value_fixture(path):
    service, peer, old, fingerprint = group_fixture(path)
    assert peer["capabilities"]["items"]["device_status"]["versions"].count(19) == 1
    channel = ValueChannel(service, peer)
    service.connections[peer["device_id"]] = channel
    service.connection_transports[peer["device_id"]] = "wifi"
    service.note_controls[channel] = copy.deepcopy(service.note_controls[old])
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    return service, peer, channel, fingerprint


@pytest.mark.parametrize("mode", ["normal", "account", "readback"])
def test_native_value_rpc_requires_matching_provider_fields_account_and_one_live_ticket(private, mode):
    service, peer, channel, fingerprint = value_fixture(private)
    channel.mode = mode
    prepare, apply, _ = messages()
    with pytest.raises(ValueError): service.contact_groups(peer["device_id"], fingerprint, prepare)
    prepared = service.contact_values(peer["device_id"], fingerprint, prepare)
    assert prepared["state"] == "prepared"
    apply["token"] = prepared["token"]
    incomplete = copy.deepcopy(apply); del incomplete["fields"]["emailEintraege"]
    with pytest.raises(PermissionError): service.contact_values(peer["device_id"], fingerprint, incomplete)
    saved = service.contact_values(peer["device_id"], fingerprint, apply)
    assert saved["state"] == "saved" and saved["fields"] == apply["fields"]
    with pytest.raises(PermissionError): service.contact_values(peer["device_id"], fingerprint, apply)
    assert not service.store.status(peer["device_id"])


def test_read_only_or_reauthorized_peers_cannot_use_an_old_value_preparation(private):
    service, peer, channel, fingerprint = value_fixture(private)
    prepare, apply, _ = messages()
    prepared = service.contact_values(peer["device_id"], fingerprint, prepare)
    apply["token"] = prepared["token"]
    peer["capabilities"]["revision"] += 1
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    with pytest.raises(PermissionError): service.contact_values(peer["device_id"], fingerprint, apply)
    peer["capabilities"]["items"]["device_status"]["versions"].remove(19)
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    assert not service.contact_values_available(peer["device_id"])
    with pytest.raises(PermissionError): service.contact_values(peer["device_id"], fingerprint, prepare)


def test_transport_acceptance_alone_never_confirms_a_value_save(private):
    service, peer, channel, fingerprint = value_fixture(private)
    channel.ack_only = True
    with pytest.raises(TimeoutError): service.contact_values(peer["device_id"], fingerprint, messages()[0])
    assert not service.contact_group_preparations
