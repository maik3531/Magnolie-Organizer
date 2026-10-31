"""Resource-20 codec: a saved label must retain prepared native identity."""
import copy
from pathlib import Path
import sys
import uuid

import pytest
from test_phone_contact_groups import fixture as group_fixture, Channel, phone, private

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_phone_contacts as contacts


def messages():
    request = dict(version=20, request_id=str(uuid.uuid4()), action="prepare", uid="synthetic-lookup", old_title="Work", new_title="Arbeit")
    prepared = dict(request, token=str(uuid.uuid4()), state="prepared", group_id="42", group_identity="a" * 64, account=dict(name="synthetic", type="provider", data_set=""))
    apply = dict(request, request_id=str(uuid.uuid4()), action="apply", token=prepared["token"])
    saved = dict(prepared, request_id=apply["request_id"], action="apply", state="saved")
    return request, prepared, apply, saved


def test_preparation_and_saved_readback_retain_the_group_and_account():
    request, prepared, apply, saved = messages()
    assert contacts.validate_correlated_group_title_report(prepared, request) == prepared
    assert contacts.validate_correlated_group_title_report(saved, apply, prepared) == saved
    with pytest.raises(ValueError):
        contacts.validate_correlated_group_title_report(saved, apply)


@pytest.mark.parametrize("field,value", [
    ("request_id", str(uuid.uuid4())), ("uid", "another-lookup"), ("old_title", "Other"), ("new_title", "Other"),
    ("token", str(uuid.uuid4())), ("group_id", "43"), ("group_identity", "b" * 64), ("account", dict(name="another", type="provider", data_set="")),
    ("state", "prepared"), ("action", "prepare"),
])
def test_changed_readback_cannot_confirm_another_preparation(field, value):
    _, prepared, apply, saved = messages()
    changed = copy.deepcopy(saved)
    changed[field] = value
    with pytest.raises(ValueError):
        contacts.validate_correlated_group_title_report(changed, apply, prepared)


@pytest.mark.parametrize("group_id", ["0", "-1", "+1", "01", " 1", "1 ", "1.0", "9223372036854775808"])
def test_native_group_id_is_canonical_positive_signed_64_bit(group_id):
    _, prepared, _, _ = messages()
    with pytest.raises(ValueError):
        contacts.validate_group_title_report_shape(dict(prepared, group_id=group_id))
    contacts.validate_group_title_report_shape(dict(prepared, group_id="9223372036854775807"))


@pytest.mark.parametrize("title", ["", " Work", "Work ", "Work", "Ar\nbeit", "Cafe\u0301", "x" * 257, "\ud800"])
def test_invalid_or_unchanged_title_cannot_prepare(title):
    request, _, _, _ = messages()
    with pytest.raises(ValueError):
        contacts.validate_group_title_request_shape(dict(request, new_title=title))


def test_caller_cannot_add_a_group_id_or_retarget_the_preparation():
    request, prepared, apply, saved = messages()
    with pytest.raises(ValueError):
        contacts.validate_group_title_request_shape(dict(request, group_id="42"))
    with pytest.raises(ValueError):
        contacts.validate_correlated_group_title_report(saved, apply, dict(prepared, uid="another-lookup"))


def test_lost_write_report_is_resolved_only_by_same_native_identity_and_desired_title():
    request, prepared, _, _ = messages()
    inspect = dict(request, request_id=str(uuid.uuid4()), action="inspect", group_id=prepared["group_id"], account=prepared["account"])
    current = dict(inspect, state="current", group_identity=prepared["group_identity"], current_title="Arbeit")
    contacts.validate_correlated_group_title_report(current, inspect)
    assert contacts.group_title_matches_saved_intent(current, prepared)
    for field, value in [("current_title", "Work"), ("current_title", "Other"), ("group_identity", "b" * 64),
                         ("group_id", "43"), ("account", dict(name="another", type="provider", data_set=""))]:
        assert not contacts.group_title_matches_saved_intent(dict(current, **{field: value}), prepared)
    with pytest.raises(ValueError):
        contacts.validate_correlated_group_title_report(dict(current, group_id="43"), inspect)
    with pytest.raises(ValueError):
        contacts.validate_group_title_request_shape(dict(inspect, token=prepared["token"]))


class TitleChannel(Channel):
    mode = "normal"
    native_title = "Work"
    mutations = 0

    def send(self, message):
        self.sent.append(copy.deepcopy(message))
        if message.get("kind") != "device_status.request":
            return
        request = message["body"]
        if request["action"] == "apply":
            self.native_title = request["new_title"]
            self.mutations += 1
        if self.ack_only:
            self.service._payload(self.peer, self, dict(type="ack", message_id=message["message_id"], status="accepted", error="none"))
            entry = self.service.contact_requests[request["request_id"]]
            assert not entry["event"].is_set()
            entry["deadline"] = phone.time.monotonic() - 1
            return
        report = dict(copy.deepcopy(request), group_identity="a" * 64)
        if request["action"] == "inspect":
            report.update(state="current", current_title=self.native_title)
        else:
            report.update(token=request.get("token") or str(uuid.uuid4()), group_id="42",
                account=dict(name="synthetic", type="provider", data_set=""), state="prepared" if request["action"] == "prepare" else "saved")
        def receive(value, source=self):
            now = phone.now_ms()
            self.service._payload(self.peer, source, dict(type="message", v=1, kind="device_status.report",
                message_id=str(uuid.uuid4()), created_ms=now, expires_ms=now + 60000, body=value))
        if self.mode != "normal":
            wrong = copy.deepcopy(report)
            if self.mode == "channel":
                receive(wrong, Channel(self.service, self.peer))
            elif request["action"] == "apply":
                if self.mode == "account": wrong["account"]["name"] = "another"
                elif self.mode == "group_id": wrong["group_id"] = "43"
                else: wrong["group_identity"] = "b" * 64
                receive(wrong)
            assert not self.service.contact_requests[request["request_id"]]["event"].is_set()
        receive(report)


def title_fixture(path):
    service, peer, old, fingerprint = group_fixture(path)
    assert phone.desktop_capabilities()["items"]["device_status"]["versions"].count(20) == 1
    channel = TitleChannel(service, peer)
    service.connections[peer["device_id"]] = channel
    service.connection_transports[peer["device_id"]] = "wifi"
    service.note_controls[channel] = copy.deepcopy(service.note_controls[old])
    service.note_controls[channel]["capabilities.update"] = copy.deepcopy(peer["capabilities"])
    return service, peer, channel, fingerprint


@pytest.mark.parametrize("mode", ["normal", "channel", "account", "group_id", "group_identity"])
def test_title_rpc_requires_original_preparation_and_same_current_native_identity(private, mode):
    service, peer, channel, fingerprint = title_fixture(private)
    request, _, apply, _ = messages()
    assert service.contact_group_titles_available(peer["device_id"])
    service.contact_group_title_writes_enabled = False
    assert not service.contact_group_titles_available(peer["device_id"])
    with pytest.raises(PermissionError):
        service.contact_group_title(peer["device_id"], fingerprint, request)
    assert not channel.sent
    service.contact_group_title_writes_enabled = True
    channel.mode = mode
    with pytest.raises(ValueError):
        service.contact_groups(peer["device_id"], fingerprint, request)
    prepared = service.contact_group_title(peer["device_id"], fingerprint, request)
    apply["token"] = prepared["token"]
    with pytest.raises(PermissionError):
        service.contact_group_title(peer["device_id"], fingerprint, dict(apply, new_title="Other"))
    saved = service.contact_group_title(peer["device_id"], fingerprint, apply)
    assert saved["group_id"] == prepared["group_id"] and saved["group_identity"] == prepared["group_identity"]
    with pytest.raises(PermissionError):
        service.contact_group_title(peer["device_id"], fingerprint, apply)
    assert channel.mutations == 1


def test_native_lost_result_uses_readonly_inspection_instead_of_another_write(private):
    service, peer, channel, fingerprint = title_fixture(private)
    service.contact_group_title_writes_enabled = True
    request, _, apply, _ = messages()
    prepared = service.contact_group_title(peer["device_id"], fingerprint, request)
    apply["token"] = prepared["token"]
    channel.ack_only = True
    with pytest.raises(TimeoutError):
        service.contact_group_title(peer["device_id"], fingerprint, apply)
    channel.ack_only = False
    inspect = dict(request, request_id=str(uuid.uuid4()), action="inspect", group_id=prepared["group_id"], account=prepared["account"])
    observed = service.contact_group_title(peer["device_id"], fingerprint, inspect)
    assert contacts.group_title_matches_saved_intent(observed, prepared)
    assert channel.mutations == 1


def test_title_rpc_rejects_bluetooth_and_changed_control_revision(private):
    service, peer, channel, fingerprint = title_fixture(private)
    service.contact_group_title_writes_enabled = True
    request, _, apply, _ = messages()
    service.connection_transports[peer["device_id"]] = "bluetooth"
    with pytest.raises(PermissionError):
        service.contact_group_title(peer["device_id"], fingerprint, request)
    service.connection_transports[peer["device_id"]] = "wifi"
    prepared = service.contact_group_title(peer["device_id"], fingerprint, request)
    apply["token"] = prepared["token"]
    peer["capabilities"]["revision"] += 1
    with pytest.raises(PermissionError):
        service.contact_group_title(peer["device_id"], fingerprint, apply)
    assert channel.mutations == 0


def test_title_prepare_apply_and_readonly_inspect_cross_the_real_daemon_proxy(private):
    from test_hintergrunddienst import background, FakeBackend
    service, peer, channel, fingerprint = title_fixture(private)
    service.contact_group_title_writes_enabled = True
    path = str(private / "runtime" / "title.sock")
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path)
    request, _, apply, _ = messages()
    try:
        prepared = proxy.contact_group_title(peer["device_id"], fingerprint, request)
        apply["token"] = prepared["token"]
        saved = proxy.contact_group_title(peer["device_id"], fingerprint, apply)
        assert saved["group_id"] == prepared["group_id"]
        inspect = dict(request, request_id=str(uuid.uuid4()), action="inspect", group_id=prepared["group_id"], account=prepared["account"])
        observed = proxy.contact_group_title(peer["device_id"], fingerprint, inspect)
        assert contacts.group_title_matches_saved_intent(observed, prepared)
        assert channel.mutations == 1
    finally:
        server.close()
