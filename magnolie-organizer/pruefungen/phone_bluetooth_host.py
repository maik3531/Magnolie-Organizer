"""Synthetic OS bonding with real RFCOMM-equivalent duplex byte streams."""
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_telefon as phone
from magnolie_setup_state import SetupPhoneServices

PHONE = "AA:BB:CC:DD:EE:01"


class BoundSocket:
    def __init__(self, sock, mode): self.sock, self.mode = sock, mode
    def __getattr__(self, name): return getattr(self.sock, name)
    def getpeername(self): return ("AA:BB:CC:DD:EE:03" if self.mode == "wrong-device" else PHONE), 1


class FakeOs:
    def __init__(self, port, mode):
        self.port, self.bonded, self.connections, self.last = port, False, 0, None
        self.mode = mode
    def availability(self): return True, "available"
    def paired(self, address): return self.bonded and address == PHONE
    def discover_devices(self, cancelled):
        return [{"id": "fixture", "address": PHONE, "name": "Owned phone", "paired": self.bonded}]
    def paired_devices(self): return [{"address": PHONE, "name": "Owned phone"}] if self.bonded else []
    def pair_device(self, device, prompt, cancelled):
        assert device["id"] == "fixture" and device["address"] == PHONE
        if self.bonded: return
        print("OSPAIR", flush=True)
        if input() != "OSACCEPT": raise PermissionError()
        self.bonded = True
    def connect(self, address, service_uuid, cancelled=None):
        assert self.paired(address) and service_uuid == phone.BLUETOOTH_UUID
        self.last = BoundSocket(socket.create_connection(("127.0.0.1", self.port), timeout=3), self.mode)
        self.connections += 1
        return self.last


def main():
    platform, port = sys.argv[1], int(sys.argv[2])
    mode = sys.argv[3]
    if platform == "linux-daemon":
        from phone_setup_daemon_host import IsolatedDaemon
        host = IsolatedDaemon(port)
        def no_local(): raise AssertionError("GUI constructed a second phone owner")
        setup = SetupPhoneServices(no_local, lambda: "Owned GUI", daemon_active=lambda: True, ipc=host.request)
        def prompt(value):
            if value["kind"] == "select": return PHONE
            if not value.get("canMarkOwn"):
                print("OSPAIR", flush=True)
                return "accept" if input() == "OSACCEPT" else None
            print("CODE " + value["code"], flush=True)
            return "accept" if input() == "ACCEPT" else None
        try:
            result = setup.connect("bluetooth", prompt)
            assert result["authenticated"] and setup.phone is None
            print("RESULT", flush=True)
            assert input() == "RECONNECT"
            host.reconnect_bluetooth()
            assert "bluetooth" in setup.connected()
            print("RECONNECTED", flush=True)
            input()
            setup.close()
            assert host.request("phone_report")["listening"]
            assert not host.request("get_settings")["autostart"]
        finally:
            setup.close(); host.close()
        return 0
    if platform == "windows":
        dll = Path(os.environ["PHONE_TEST_WINDOWS_DLL"])
        if not dll.is_file():
            raise RuntimeError("Explicit Bluetooth gate requires the freshly built CoreTests DLL")
        return subprocess.call([os.environ.get("PHONE_TEST_DOTNET", "/tmp/opencode/dotnet-8.0.408/dotnet"), str(dll), "--phone-bt-host", str(port), mode])
    phone.PORT = 0  # No WLAN pairing, listener or discovery is used by the fixture.
    handlers = set()
    drained = threading.Condition()
    original_handle = phone.PhoneService._handle
    def owned_handle(self, *args):
        with drained: handlers.add(threading.current_thread())
        try:
            return original_handle(self, *args)
        finally:
            with drained:
                handlers.discard(threading.current_thread())
                drained.notify_all()
    phone.PhoneService._handle = owned_handle
    with tempfile.TemporaryDirectory(prefix="magnolie-bt-first-") as root:
        backend = FakeOs(port, mode)
        setup = SetupPhoneServices(lambda: root, lambda: "Owned desktop")
        def event(event, payload):
            if event == "pairing_code": setup.events.put((event, payload))
        setup.phone = phone.PhoneService(str(Path(root) / "telefon"), "Owned desktop", bluetooth_backend=backend,
            callback=event)
        setup.phone._publish = lambda: None
        def prompt(value):
            if value["kind"] == "select": return PHONE
            assert value.get("canMarkOwn") and value["code"]
            print("CODE " + value["code"], flush=True)
            return "accept" if input() == "ACCEPT" else None
        try:
            result = setup.connect("bluetooth", prompt)
            assert backend.connections == (3 if mode == "drop-finish" else 2), "Unexpected handshake connection count"
            assert result["authenticated"] and setup.phone.store.peer(result["deviceId"])["bluetooth"]["address"] == PHONE
            assert not setup.phone.store.peer(result["deviceId"])["personal_sync"]["own_device"]
            assert not setup.phone.store.settings()["enabled"]
            print("RESULT", flush=True)
            assert input() == "RECONNECT"
            previous_connections = backend.connections
            backend.last.shutdown(socket.SHUT_RDWR); backend.last.close()
            # Advance only the existing retry backoff; never bypass its authentication.
            setup.phone.bluetooth_retry_at[result["deviceId"]] = 0
            until = time.monotonic() + 15
            while time.monotonic() < until:
                if backend.connections > previous_connections and "bluetooth" in setup.connected(): break
                time.sleep(.1)
            else: raise AssertionError("Bluetooth reconnect did not authenticate")
            print("RECONNECTED", flush=True)
            input()
        except (PermissionError, RuntimeError, ValueError):
            if mode == "accept": raise
            assert setup.phone.store.peers == []
            assert not setup.phone.store.settings()["enabled"]
            print("REJECTED", flush=True)
        finally:
            setup.close()
            for worker in (setup.phone.thread, setup.phone.bluetooth_thread):
                if worker: worker.join(4)
            with drained:
                assert drained.wait_for(lambda: not handlers, timeout=5), "Owned Bluetooth handlers did not stop"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
