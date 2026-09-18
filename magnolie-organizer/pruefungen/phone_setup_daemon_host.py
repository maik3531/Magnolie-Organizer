"""Isolated real daemon/Unix IPC host for the phone integration fixtures."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


def environment(root):
    env = dict(os.environ)
    for key, name in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                      ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
        path = Path(root) / name
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
        env[key] = str(path)
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    return env


class IsolatedDaemon:
    def __init__(self, bluetooth_port=None):
        self.directory = tempfile.TemporaryDirectory(prefix="magnolie-setup-daemon-")
        env = environment(self.directory.name)
        self.env = env
        arguments = ["--serve"] if bluetooth_port is None else ["--serve-bt", str(bluetooth_port)]
        self.command = ["dbus-run-session", "--", sys.executable, "-u", __file__, *arguments]
        self._start()

    def _start(self):
        env = self.env
        self.process = subprocess.Popen(self.command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        from magnolie_hintergrund import daemon_available
        # The fixture emits its canonical socket name; no guessed production path.
        self.path = self.process.stdout.readline().strip()
        if not self.path.startswith(env["XDG_RUNTIME_DIR"] + "/"):
            raise RuntimeError("Isolated daemon did not publish its private socket: " + self.process.stderr.read())
        until = time.monotonic() + 8
        while not daemon_available(self.path) and time.monotonic() < until:
            if self.process.poll() is not None: raise RuntimeError(self.process.stderr.read())
            time.sleep(.05)
        if not daemon_available(self.path): raise RuntimeError("Private daemon did not become ready")

    def request(self, op, args=None):
        from magnolie_hintergrund import ipc_request
        return ipc_request(op, args or {}, path=self.path)

    def reconnect_bluetooth(self):
        self.process.stdin.write("DROP\n"); self.process.stdin.flush()
        assert self.process.stdout.readline().strip() == "RECONNECTED"

    def _stop(self):
        if self.process.poll() is None:
            self.process.stdin.write("QUIT\n"); self.process.stdin.flush()
            try: self.process.wait(8)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL); self.process.wait(3)
        error = self.process.stderr.read()
        if error: sys.stderr.write(error)
        self.process.stdout.close(); self.process.stderr.close()
        self.process.stdin.close()

    def restart(self):
        self._stop()
        self._start()

    def close(self):
        self._stop()
        self.directory.cleanup()


def serve(bluetooth_port=None):
    import threading
    from types import SimpleNamespace
    import magnolie_hintergrund as background
    from magnolie_setup_state import write_state
    from magnolie_telefon import PhoneService
    from gi.repository import GLib
    write_state("complete")
    settings = background.normalize_settings({"enabled": True, "permissions": {"phone_monitor": True}})
    if not os.path.exists(background.settings_path()): background.write_settings(settings, update_autostart=False)
    import socket
    class BoundSocket:
        def __init__(self, raw): self.raw = raw
        def __getattr__(self, name): return getattr(self.raw, name)
        def getpeername(self): return "AA:BB:CC:DD:EE:01", 1
    class Radio:
        bonded = False
        connections = 0
        last = None
        def availability(self): return (True, "available") if bluetooth_port else (False, "no_hardware")
        def paired_devices(self): return [{"address": "AA:BB:CC:DD:EE:01", "name": "Owned phone"}] if self.bonded else []
        def paired(self, address): return self.bonded and address == "AA:BB:CC:DD:EE:01"
        def discover_devices(self, cancelled): return [{"id": "fixture", "address": "AA:BB:CC:DD:EE:01", "name": "Owned phone"}]
        def pair_device(self, device, prompt, cancelled):
            assert device["address"] == "AA:BB:CC:DD:EE:01"
            answer = prompt({"kind": "confirm", "devices": [{"uid": device["address"], "name": device["name"]}], "code": "123456"})
            if answer != "accept": raise PermissionError()
            self.bonded = True
        def connect(self, address, service_uuid, cancelled=None):
            from magnolie_telefon import BLUETOOTH_UUID
            assert self.paired(address) and service_uuid == BLUETOOTH_UUID
            self.last = BoundSocket(socket.create_connection(("127.0.0.1", bluetooth_port), timeout=3))
            self.connections += 1
            return self.last
    radio = Radio()
    owner = [None]
    class Kde:
        def __init__(self, *_args, **_kwargs):
            self.store = SimpleNamespace(peers=[]); self.pairing = None; self._state_lock = threading.RLock()
        def start(self): return True
        def stop(self): pass
        def configure_receive(self, **_kwargs): return {}
        def status(self, **_kwargs): return {"available": False, "paired_count": 0}
    class Notifications:
        available = actions_supported = supported = False
        def __init__(self, _glib): pass
        def show(self, *_args): return False
        def open_organizer(self): raise AssertionError("Fixture must not open an application")
    def factory(root, name, callback):
        phone = PhoneService(root, name, callback, bluetooth_backend=radio)
        phone._publish = lambda: None
        if not os.path.exists(phone.store.settings_path): phone.store.save_settings(True)
        phone.enabled = phone.store.settings()["enabled"]
        owner[0] = phone
        return phone
    def commands():
        for command in sys.stdin:
            if command.strip() == "QUIT":
                os.kill(os.getpid(), signal.SIGTERM)
                return
            if command.strip() != "DROP" or owner[0] is None or radio.last is None: continue
            before = radio.connections
            radio.last.shutdown(socket.SHUT_RDWR); radio.last.close()
            owner[0].bluetooth_retry_at.clear()
            until = time.monotonic() + 12
            while time.monotonic() < until:
                if radio.connections > before and any(p["state"] == "online_bluetooth" for p in owner[0].report()["peers"]):
                    print("RECONNECTED", flush=True); break
                time.sleep(.1)
    threading.Thread(target=commands, daemon=True).start()
    print(background.socket_path(), flush=True)
    return background.daemon_main([], backend_factory=Kde, glib=GLib, notifications_factory=Notifications, phone_factory=factory)


if __name__ == "__main__":
    assert sys.argv[1:] == ["--serve"] or len(sys.argv) == 3 and sys.argv[1] == "--serve-bt"
    raise SystemExit(serve(int(sys.argv[2]) if len(sys.argv) == 3 else None))
