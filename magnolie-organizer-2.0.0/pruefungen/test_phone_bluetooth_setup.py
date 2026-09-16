import json
import hashlib
import os
from pathlib import Path
import socket
import sys
import threading
import time
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_telefon as phone

MAC = "AA:BB:CC:DD:EE:01"


def test_paired_discovery_deduplicates_address_not_friendly_name():
    backend = phone.BlueZBluetoothBackend()
    result = SimpleNamespace(returncode=0, stdout=(
        "Device AA:BB:CC:DD:EE:01 Friendly phone\n"
        "Device aa:bb:cc:dd:ee:01 Product model\n"
        "Device AA:BB:CC:DD:EE:02 Friendly phone\n"))
    with mock.patch.object(backend, "_bluetoothctl", return_value=result):
        assert backend.paired_devices() == [
            {"address": MAC, "name": "Friendly phone"},
            {"address": "AA:BB:CC:DD:EE:02", "name": "Friendly phone"}]


@pytest.mark.parametrize("attack", ["wrong-device", "wrong-target", "expired", "cancelled", "replayed-token", "bad-proof"])
def test_bt_scoped_handshake_never_persists_rejected_trust(tmp_path, attack):
    init = json.loads((ROOT / "pruefungen/telefon-protokoll-vektoren.json").read_text())["pairing"]["pair_init"]
    events = []
    service = phone.PhoneService(str(tmp_path), "Desktop", callback=lambda *event: events.append(event))
    offer = service.open_setup_pairing(init["device_id"], MAC, "bluetooth")
    init["pairing_token"] = offer["token"]
    if attack == "wrong-target": init["device_id"] = str(uuid.uuid4())
    if attack == "expired": service.pairing_until = time.monotonic() - 1
    if attack in ("cancelled", "replayed-token"):
        service.end_setup_pairing(offer["token"])
        if attack == "replayed-token": offer = service.open_setup_pairing(init["device_id"], MAC, "bluetooth")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=2) as client:
            server, _ = listener.accept()
            worker = threading.Thread(target=service._handle, args=(server,
                "bluetooth:" + ("AA:BB:CC:DD:EE:03" if attack == "wrong-device" else MAC), "bluetooth"))
            worker.start()
            phone.send_frame(client, init)
            if attack == "bad-proof":
                response = phone.receive_frame(client, phone.PAIR_FRAME_MAX)
                until = time.monotonic() + 2
                while not events and time.monotonic() < until: time.sleep(.01)
                challenge = next(event[1] for event in events if event[0] == "pairing_code")
                service.confirm_pairing(challenge["attempt_id"], True)
                transcript = hashlib.sha256(phone.canonical(init) + phone.canonical(response)).digest()
                phone.send_frame(client, {"p": phone.PROTOCOL, "type": "pair_confirm", "side": "phone",
                    "transcript": phone.b64(transcript), "proof": phone.b64(bytes(32))})
            assert client.recv(1) == b""
            worker.join(2)
            assert not worker.is_alive()
    service.end_setup_pairing(offer["token"])
    assert service.store.peers == []
    assert sum(event[0] == "pairing_code" for event in events) == (1 if attack == "bad-proof" else 0)


def test_native_bluez_agent_is_selected_device_bound_and_never_sets_trusted():
    from gi.repository import GLib
    backend = phone.BlueZBluetoothBackend()
    path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"
    selected = {"id": path, "address": MAC, "name": "Phone"}
    class Invocation:
        def __init__(self): self.done, self.error = threading.Event(), None
        def return_value(self, value): self.done.set()
        def return_dbus_error(self, name, text): self.error = name; self.done.set()
    class Bus:
        def __init__(self): self.calls, self.callback = [], None
        def register_object(self, _path, _info, callback, *_): self.callback = callback; return 1
        def unregister_object(self, registration): assert registration == 1
        def call_sync(self, name, object_path, interface, method, parameters, *_):
            self.calls.append((object_path, interface, method))
            if method == "GetNameOwner": return GLib.Variant("(s)", (":1.42",))
            if method == "Pair":
                for sender, device in ((":1.attacker", path), (":1.42", path + "wrong")):
                    request = Invocation()
                    self.callback(self, sender, "agent", "org.bluez.Agent1", "RequestConfirmation", GLib.Variant("(ou)", (device, 123456)), request)
                    assert request.error == "org.bluez.Error.Rejected"
                request = Invocation()
                self.callback(self, ":1.42", "agent", "org.bluez.Agent1", "RequestConfirmation", GLib.Variant("(ou)", (path, 123456)), request)
                assert request.done.wait(2) and request.error is None
            return GLib.Variant("()", ())
    bus = Bus()
    prompts = []
    def confirm(value):
        prompts.append(value)
        assert value["devices"][0]["uid"] == MAC and value["code"] == "123456" and not value.get("canMarkOwn")
        return "accept"
    with mock.patch.object(backend, "_bluez", return_value=(bus, {path: {"org.bluez.Device1": {"Address": MAC, "Paired": False}}})), \
         mock.patch.object(backend, "paired", return_value=True):
        backend.pair_device(selected, confirm, threading.Event())
    assert len(prompts) == 1
    assert [call for call in bus.calls if call[2] == "Pair"] == [(path, "org.bluez.Device1", "Pair")]
    assert not any(call[2] in ("Set", "RequestDefaultAgent") for call in bus.calls)
    assert bus.calls[-1][2] == "UnregisterAgent"


def test_bluez_client_profile_hands_off_a_real_owned_fd_and_rejects_other_devices():
    from gi.repository import GLib
    backend = phone.BlueZBluetoothBackend()
    path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=2) as client:
            remote, _ = listener.accept()
            original_socket = socket.socket
            class Bound:
                def __init__(self, raw): self.raw = raw
                def __getattr__(self, name): return getattr(self.raw, name)
                def getpeername(self): return MAC, 1
            def from_fd(*args, **kwargs):
                raw = original_socket(*args, **kwargs)
                return Bound(raw) if "fileno" in kwargs else raw
            class Invocation:
                error = None
                reads = 0
                def return_value(self, _): pass
                def return_dbus_error(self, name, _): self.error = name
                def get_message(self):
                    self.reads += 1
                    return SimpleNamespace(get_unix_fd_list=lambda: SimpleNamespace(get=lambda index: os.dup(client.fileno())))
            class Bus:
                calls = []
                callback = None
                def register_object(self, _path, _info, callback, *_): self.callback = callback; return 7
                def unregister_object(self, registration): assert registration == 7
                def call_sync(self, _name, obj, interface, method, parameters, *_):
                    self.calls.append(method)
                    if method == "GetNameOwner": return GLib.Variant("(s)", (":1.42",))
                    if method == "RegisterProfile":
                        _, service_uuid, options = parameters.unpack()
                        assert service_uuid == phone.BLUETOOTH_UUID
                        assert options == {"Role": "client", "RequireAuthentication": True, "AutoConnect": False}
                    if method == "ConnectProfile":
                        assert obj == path
                        for sender, device in ((":1.attacker", path), (":1.42", path + "wrong")):
                            invocation = Invocation()
                            self.callback(self, sender, "profile", "org.bluez.Profile1", "NewConnection",
                                GLib.Variant("(oha{sv})", (device, 0, {})), invocation)
                            assert invocation.error and invocation.reads == 0
                        invocation = Invocation()
                        self.callback(self, ":1.42", "profile", "org.bluez.Profile1", "NewConnection",
                            GLib.Variant("(oha{sv})", (path, 0, {})), invocation)
                        assert invocation.error is None and invocation.reads == 1
                    return GLib.Variant("()", ())
            bus = Bus()
            with mock.patch.object(backend, "_bluez", return_value=(bus, {path: {"org.bluez.Device1": {"Address": MAC, "Paired": True}}})), \
                 mock.patch.object(backend, "paired", return_value=True), mock.patch.object(phone.socket, "socket", side_effect=from_fd):
                stream = backend.connect(MAC, phone.BLUETOOTH_UUID)
            try:
                message = {"p": phone.PROTOCOL, "type": "pair_abort", "reason": "user_cancelled"}
                phone.send_frame(remote, message)
                assert phone.receive_frame(stream, 2048) == message
                phone.send_frame(stream, message)
                assert phone.receive_frame(remote, 2048) == message
            finally:
                stream.close(); stream.close(); remote.close()
            assert bus.calls.count("UnregisterProfile") == 1
            assert not any(method in bus.calls for method in ("Pair", "Set", "DisconnectProfile"))
