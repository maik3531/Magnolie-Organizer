"""Owned live WLAN fixture for Android JVM tests; no production profile access."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from zeroconf import IPVersion, ServiceInfo, Zeroconf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from magnolie_setup_state import SetupPhoneServices
from magnolie_telefon import PhoneService


def main():
    platform, target, nonce, port, address = sys.argv[1:]
    original_pair = PhoneService._pair
    pair_done = threading.Event()
    def checked_pair(self, sock, first, source=None):
        try:
            return original_pair(self, sock, first, source)
        except Exception:
            import traceback
            traceback.print_exc()
            raise
        finally:
            pair_done.set()
    PhoneService._pair = checked_pair
    kind = "_magnolie-invite._tcp.local."
    info = ServiceInfo(kind, target + "." + kind, addresses=[socket.inet_aton(address)],
                       port=int(port), server="phone-fixture-" + target + ".local.",
                       properties={"v": "1", "id": target, "name": "Owned phone fixture", "nonce": nonce})
    with Zeroconf(interfaces=[address], ip_version=IPVersion.V4Only) as zc:
        zc.register_service(info)
        try:
            if platform == "windows":
                remote = os.environ.get("PHONE_TEST_WINDOWS_REMOTE")
                if remote:
                    print("Owned invitation endpoint:", address, port, file=sys.stderr, flush=True)
                    dll = os.environ["PHONE_TEST_WINDOWS_DLL"]
                    return subprocess.call(["ssh", "-o", "BatchMode=yes", remote, "dotnet", dll, "--phone-invite-host", target])
                dotnet = os.environ.get("PHONE_TEST_DOTNET", "/tmp/opencode/dotnet-8.0.408/dotnet")
                dll = Path(os.environ["PHONE_TEST_WINDOWS_DLL"])
                if not dll.is_file():
                    raise RuntimeError("Explicit invitation gate requires the freshly built CoreTests DLL")
                return subprocess.call([dotnet, str(dll), "--phone-invite-host", target])
            if platform in ("linux-daemon", "linux-daemon-startup"):
                from phone_setup_daemon_host import IsolatedDaemon
                host = IsolatedDaemon()
                def no_local(): raise AssertionError("GUI must not construct a local phone owner")
                setup = SetupPhoneServices(no_local, lambda: "Owned GUI", daemon_active=lambda: True, ipc=host.request)
                def prompt(value):
                    if value["kind"] == "select":
                        assert any(d["uid"] == target for d in value["devices"])
                        return target
                    assert value["devices"][0]["uid"] == target
                    print("CODE " + value["code"], flush=True)
                    return "accept" if input() == "ACCEPT" else None
                try:
                    result = setup.connect("wifi", prompt)
                    assert result["authenticated"] and result["deviceId"] == target and setup.phone is None
                    assert not host.request("get_settings")["permissions"]["phone_pairing_decisions"]
                    if platform == "linux-daemon-startup":
                        from magnolie_setup_state import write_state
                        from magnolie_hintergrund import IPCError
                        marker = Path(host.directory.name) / "gui-setup.json"
                        setup.finish_setup(lambda status, values=None: write_state(status, values, str(marker)), {"phoneBackgroundServices": ["wifi"]})
                        assert host.request("get_settings")["phone_setup_services"] == ["wifi"]
                        assert host.request("get_settings")["autostart"]
                        entries = list((Path(host.env["XDG_CONFIG_HOME"]) / "autostart").glob("*.desktop"))
                        assert len(entries) == 1 and "--hintergrunddienst" in entries[0].read_text()
                        host.restart()
                        try: setup.connected()
                        except IPCError as error: assert "expired" in str(error)
                        else: raise AssertionError("Restart accepted stale setup token")
                        import time
                        until = time.monotonic() + 8
                        while time.monotonic() < until:
                            if any(p["device_id"] == target and p["state"] == "online_wifi" for p in host.request("phone_report")["peers"]): break
                            time.sleep(.1)
                        else: raise AssertionError("Persisted daemon route did not reconnect")
                        assert host.request("get_settings")["autostart"] and host.request("get_settings")["phone_setup_services"] == ["wifi"]
                    print("RESULT " + json.dumps(result), flush=True)
                    input()
                    setup.close()
                    assert host.request("phone_report")["listening"]
                    assert host.request("get_settings")["autostart"] == (platform == "linux-daemon-startup")
                finally:
                    setup.close(); host.close()
                return 0
            with tempfile.TemporaryDirectory(prefix="magnolie-phone-invite-") as root:
                setup = SetupPhoneServices(lambda: root, lambda: "Owned desktop fixture")
                def prompt(value):
                    if value["kind"] == "select":
                        assert any(d["uid"] == target for d in value["devices"]), "Fixture phone not discovered"
                        return target
                    assert value["devices"][0]["uid"] == target
                    print("CODE " + value["code"], flush=True)
                    return "accept" if input() == "ACCEPT" else None
                try:
                    result = setup.connect("wifi", prompt)
                    assert result["authenticated"] and result["deviceId"] == target
                    assert not setup.phone.store.peer(target)["personal_sync"]["own_device"]
                    assert not setup.phone.store.settings()["enabled"]
                    print("RESULT " + json.dumps(result), flush=True)
                    input()
                finally:
                    setup.close()
                    pair_done.wait(5)
        finally:
            zc.unregister_service(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
