import importlib.machinery
import json
import os
import runpy
import socket
import stat
import sys
import tempfile
import threading
import time
import types
from unittest import mock

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
PROGRAM = os.path.join(BIN, "magnolie-organizer")
sys.path.insert(0, BIN)
import magnolie_hintergrund as background


def test_settings_are_normalized_atomic_private_and_reject_unenforced_policies():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "private", "background.json")
        status = background.write_settings({
            "enabled": "yes", "autostart": True,
            "encryption_policy": "keyring", "password": "must-not-survive",
            "permissions": {"kde_pairing": True, "kde_incoming_files": 1,
                "sms_phone_notifications": True, "unknown": True}}, path)
        with open(path, encoding="utf-8") as source:
            stored = json.load(source)
        assert stored["enabled"] is False and stored["autostart"] is True
        assert stored["encryption_policy"] == "notify_then_unlock"
        assert stored["permissions"] == dict.fromkeys(background.PERMISSIONS, False) | {
            "kde_pairing": True, "sms_phone_notifications": True}
        assert stored["kde_device_id"] == ""
        assert stored["kde_download_directory"] == ""
        assert stored["kde_clipboard_enabled"] is False
        assert stored["kde_file_enabled"] is False
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert "password" not in stored
        unsupported = background.settings_status(dict(stored, encryption_policy="keyring"))
        assert unsupported["encryption_policy_supported"] is True
        assert unsupported["keyring_available"] is False
        assert status["encryption_policy"] == "notify_then_unlock"


def test_kde_receive_settings_require_canonical_peer_and_directory():
    with tempfile.TemporaryDirectory() as root:
        valid = background.normalize_settings({"enabled": True,
            "kde_device_id": "a" * 32, "kde_download_directory": root,
            "kde_clipboard_enabled": True, "kde_clipboard_mode": "automatic",
            "kde_file_enabled": True,
            "permissions": {"kde_incoming_files": True}})
        assert valid["kde_device_id"] == "a" * 32
        assert valid["kde_download_directory"] == os.path.realpath(root)
        assert background.receive_configuration(valid) == {
            "clipboard_enabled": True, "file_enabled": True,
            "device_id": "a" * 32, "clipboard_mode": "automatic",
            "file_mode": "confirm", "download_directory": os.path.realpath(root)}
        invalid = background.normalize_settings({"enabled": True,
            "kde_device_id": "bad", "kde_download_directory": "relative",
            "kde_clipboard_enabled": True, "kde_file_enabled": True})
        assert invalid["kde_device_id"] == ""
        assert invalid["kde_download_directory"] == ""
        assert not invalid["kde_clipboard_enabled"] and not invalid["kde_file_enabled"]


def test_autostart_uses_stable_appimage_and_private_escaped_desktop_entry():
    with tempfile.TemporaryDirectory() as root:
        target = os.path.join(root, "autostart", "service.desktop")
        appimage = os.path.join(root, 'Magnolie $ "portable" %.AppImage')
        with mock.patch.dict(os.environ, {"APPIMAGE": appimage}, clear=False):
            assert background.configure_autostart({"enabled": True, "autostart": True},
                                                  path=target)
        text = open(target, encoding="utf-8").read()
        assert appimage.replace("$", "\\$").replace('"', '\\"').replace("%", "%%") in text
        assert "--hintergrunddienst" in text
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
        background.configure_autostart({}, path=target)
        assert not os.path.exists(target)


def test_flatpak_autostart_uses_host_visible_launcher():
    with mock.patch.dict(os.environ, {
            "FLATPAK_ID": "io.gitlab.maik3531.MagnolieOrganizer"}):
        contents = background.autostart_contents("/app/bin/magnolie-organizer")
    assert 'Exec="/usr/bin/flatpak" "run" "io.gitlab.maik3531.MagnolieOrganizer"' \
        in contents
    assert "/app/bin/magnolie-organizer" not in contents


def test_headless_cli_dispatches_before_any_gui_import():
    fake = types.ModuleType("magnolie_hintergrund")
    calls = []
    fake.daemon_main = mock.Mock(side_effect=lambda _args: calls.append("daemon") or 23)
    fake_crash = types.ModuleType("magnolie_crash")
    fake_crash.install = mock.Mock(side_effect=lambda *_args: calls.append("crash"))
    imported = []
    original_import = __import__

    def watched_import(name, *args, **kwargs):
        imported.append(name)
        return original_import(name, *args, **kwargs)

    with mock.patch.dict(sys.modules, {"magnolie_hintergrund": fake,
                                      "magnolie_crash": fake_crash}), \
         mock.patch.object(sys, "argv", [PROGRAM, "--background-service"]), \
         mock.patch("builtins.__import__", side_effect=watched_import), \
         pytest.raises(SystemExit) as stopped:
        runpy.run_path(PROGRAM, run_name="__main__")
    assert stopped.value.code == 23
    fake_crash.install.assert_called_once_with(
        "magnolie-organizer", "2.0.12", "background-service")
    assert calls == ["crash", "daemon"]
    assert fake.daemon_main.called
    assert "gi" not in imported
    assert "magnolie_telefon" not in imported


class FakeBackend:
    def __init__(self):
        self.calls = []

    def status(self, timeout=0.25):
        self.calls.append(("status", timeout))
        return {"available": True}

    def discover(self, timeout=0.7):
        self.calls.append(("discover", timeout))
        return []

    def begin_pairing(self, device_id=None, replace_stored=False):
        self.calls.append(("begin_pairing", device_id, replace_stored))
        return {"state": "requested", "device_id": device_id, "code": "12345678"}

    def confirm_pairing(self, accepted):
        self.calls.append(("confirm_pairing", accepted))
        return {"state": "accepted" if accepted else "rejected"}

    def accept_receive(self, receive_id):
        self.calls.append(("accept_receive", receive_id))

    def reject_receive(self, receive_id):
        self.calls.append(("reject_receive", receive_id))

    def configure_receive(self, **arguments):
        self.calls.append(("configure_receive", arguments))
        return arguments


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_private_ipc_enforces_one_owner_and_gui_proxy_uses_owner():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "runtime", "background.sock")
        backend = FakeBackend()
        operations = []
        server = background.IPCServer(backend, path,
            operation_callback=lambda operation, result:
                operations.append((operation, result))).start()
        try:
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
            server.lifecycle = "starting"
            assert background.daemon_status(path) == "starting"
            assert not background.daemon_available(path)
            server.lifecycle = "ready"
            assert background.daemon_available(path)
            assert background.daemon_status(path) == "ready"
            proxy = background.KDEConnectProxy(path)
            assert proxy.status()["available"] is True
            assert proxy.discover() == []
            pairing = proxy.begin_pairing("a" * 32)
            assert pairing["state"] == "requested"
            assert operations[-1] == ("begin_pairing", pairing)
            proxy.configure_receive(file_enabled=True, clipboard_enabled=False,
                device_id="a" * 32, clipboard_mode="confirm", file_mode="automatic",
                download_directory="/tmp")
            assert backend.calls[-1][1]["file_mode"] == "confirm"
            with pytest.raises(background.AlreadyRunning):
                background.IPCServer(FakeBackend(), path).start()
        finally:
            server.close()


def test_idle_ipc_client_is_timed_out_without_holding_a_handler():
    with tempfile.TemporaryDirectory() as root, mock.patch.object(
            background, "IPC_READ_TIMEOUT", 0.05):
        path = os.path.join(root, "runtime", "background.sock")
        server = background.IPCServer(FakeBackend(), path).start()
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1)
        try:
            client.connect(path)
            response = client.recv(4096)
            assert b'"ok":false' in response
            assert wait_until(lambda: server._handlers._value == background.MAX_IPC_HANDLERS)
        finally:
            client.close()
            server.close()


def test_settings_mutations_are_serialized_and_revision_is_monotonic():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "runtime", "background.sock")
        active = 0
        maximum = 0
        guard = threading.Lock()

        def setter(value):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with guard:
                active -= 1
            return background.settings_status(value)

        server = background.IPCServer(FakeBackend(), path,
            settings_setter=setter).start()
        results = []
        try:
            threads = [threading.Thread(target=lambda enabled=enabled: results.append(
                background.ipc_request("set_settings", {"settings": {
                    "enabled": enabled}}, path))) for enabled in (True, False)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(2)
            assert maximum == 1
            assert sorted(item["settings_revision"] for item in results) == [1, 2]
        finally:
            server.close()


def test_settings_ipc_and_proxy_callback_deliver_bounded_non_actionable_events():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "runtime", "background.sock")
        current = background.normalize_settings({"enabled": True})
        updates = []

        def setter(value):
            nonlocal current
            current = background.normalize_settings(value)
            updates.append(current)
            return background.settings_status(current)

        server = background.IPCServer(FakeBackend(), path,
            settings_getter=lambda: current, settings_setter=setter).start()
        server.status_extra = {"native_notifications_supported": True,
                               "native_actions_supported": False}
        received = []
        try:
            proxy = background.KDEConnectProxy(path,
                callback=lambda event, payload: received.append((event, payload)))
            reported = proxy.get_settings()
            assert reported["enabled"] is True
            assert reported["native_notifications_supported"] is True
            assert reported["native_actions_supported"] is False
            changed = dict(current, autostart=True)
            assert proxy.set_settings(changed)["autostart"] is True
            assert updates[-1]["autostart"] is True
            server.publish_event("sms", {"text": "history", "notify": False})
            server.publish_event("pairing_status", {"state": "paired"})
            assert proxy.start()
            time.sleep(0.1)
            assert received == []
            server.publish_event("pairing_status", {"state": "new"})
            assert wait_until(lambda: len(received) == 1)
            assert received[0] == ("pairing_status", {"state": "new"})
            proxy.stop()
            for number in range(background.MAX_EVENTS + 20):
                server.publish_event("status", {"number": number})
            cursor, retained = 0, []
            while True:
                polled = background.ipc_request(
                    "poll_events", {"after": cursor, "timeout": 0}, path)
                retained.extend(polled["events"])
                if polled["cursor"] == cursor or not polled["events"]:
                    break
                cursor = polled["cursor"]
                if cursor >= background.MAX_EVENTS + 22:
                    break
            assert len(retained) == background.MAX_EVENTS
        finally:
            server.close()


def test_gui_subscription_tracks_window_visibility_instead_of_process_presence():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "runtime", "background.sock")
        server = background.IPCServer(FakeBackend(), path).start()
        proxy = background.KDEConnectProxy(path, callback=lambda *_args: None)
        try:
            assert proxy.start()
            assert server.gui_present() is False
            assert proxy.set_visible(True) is True
            assert server.gui_present() is True
            assert proxy.set_visible(False) is False
            assert server.gui_present() is False
            proxy.stop()
            assert server.gui_present() is False
        finally:
            server.close()


class ImmediateGLib:
    @staticmethod
    def idle_add(callback, *arguments):
        callback(*arguments)
        return 1


class RecordedNotifications:
    def __init__(self):
        self.items = []
        self.opened = 0
        self.withdrawn = []

    def show(self, title, body, actions=(), on_close=None, key=None):
        self.items.append((title, body, actions, on_close))
        return True

    def withdraw(self, key):
        self.withdrawn.append(key)
        return True

    def open_organizer(self):
        self.opened += 1


class ActionlessNotifications(RecordedNotifications):
    def show(self, title, body, actions=(), on_close=None, key=None):
        self.items.append((title, body, actions, on_close))
        return not actions


def test_native_decision_actions_call_backend_without_opening_organizer():
    backend = FakeBackend()
    notifications = RecordedNotifications()
    settings = {"permissions": {"kde_pairing": True,
        "kde_incoming_files": True, "sms_phone_notifications": True}}
    events = background.DaemonEvents(lambda: backend, settings, notifications,
                                     ImmediateGLib)
    events("pairing", {"device_name": "Phone\nInjected", "code": "12345678"})
    title, body, actions, _on_close = notifications.items[-1]
    assert "\n" not in body and len(actions) == 2
    actions[0][2]()
    assert backend.calls[-1] == ("confirm_pairing", True)
    assert notifications.opened == 0

    events("file_proposal", {"id": "a" * 32, "name": "x\x00.txt", "size": 4})
    notifications.items[-1][2][1][2]()
    assert backend.calls[-1] == ("reject_receive", "a" * 32)
    notifications.items[-1][3]()
    assert backend.calls.count(("reject_receive", "a" * 32)) == 1
    events("file_proposal", {"id": "b" * 32, "name": "y.txt", "size": 5})
    events("receive_expired", {"id": "b" * 32, "kind": "file"})
    assert notifications.withdrawn == ["b" * 32]
    assert notifications.opened == 0

    events("sms", {"notify": True, "from": "+49170\nBad", "text": "Hello\x00there"})
    assert notifications.opened == 0
    notifications.items[-1][2][0][2]()
    assert notifications.opened == 1


def test_actionable_daemon_events_are_native_only_and_localized():
    backend = FakeBackend()
    notifications = RecordedNotifications()
    published = []
    settings = {"permissions": {"kde_pairing": True,
        "kde_incoming_files": True, "sms_phone_notifications": True}}
    with mock.patch.object(background, "_", side_effect=lambda text: "L:" + text):
        events = background.DaemonEvents(lambda: backend, settings, notifications,
            ImmediateGLib, lambda event, payload: published.append((event, payload)))
        events("pairing", {"device_name": "Phone", "code": "12345678"})
        events("file_proposal", {"id": "b" * 32, "name": "safe.txt", "size": 2})
        events("sms", {"notify": True, "from": "+49170", "text": "Hello"})
    assert notifications.items[0][0] == "L:KDE Connect pairing"
    assert notifications.items[0][2][0][1] == "L:Accept"
    assert [event for event, _payload in published] == ["sms"]
    assert published[0][1]["notify"] is False
    assert notifications.opened == 0


def test_actionless_notification_server_still_shows_events_and_rejects_files():
    backend = FakeBackend()
    notifications = ActionlessNotifications()
    events = background.DaemonEvents(lambda: backend, {
        "permissions": {"kde_incoming_files": True}}, notifications, ImmediateGLib)
    events("file_proposal", {"id": "f" * 32, "name": "document.pdf", "size": 7})
    assert len(notifications.items) == 2
    assert notifications.items[-1][2] == ()
    assert backend.calls[-1] == ("reject_receive", "f" * 32)

    phone_events = background.PhoneDaemonEvents(lambda: FakePhoneService(), {
        "permissions": {"phone_call_notifications": True}}, notifications,
        ImmediateGLib, lambda *_args: True, lambda: False)
    phone_events("incoming_call", {"state": "ringing", "number": "+49170"})
    assert notifications.items[-1][0] == "Incoming call"
    assert notifications.items[-1][2] == ()


def test_missing_native_action_capability_rejects_decisions_fail_closed():
    backend = FakeBackend()

    class NoActions:
        def show(self, *_arguments, **_keywords):
            return False

        def open_organizer(self):
            raise AssertionError("decision notification must not open Organizer")

    events = background.DaemonEvents(lambda: backend, {
        "permissions": {"kde_pairing": True, "kde_incoming_files": True}},
        NoActions(), ImmediateGLib)
    events("pairing", {"device_name": "Phone", "code": "12345678"})
    assert backend.calls[-1] == ("confirm_pairing", False)
    events("file_proposal", {"id": "c" * 32, "name": "file.txt", "size": 1})
    assert backend.calls[-1] == ("reject_receive", "c" * 32)


class FakeDaemonBackend:
    instances = []

    def __init__(self, directory, device_name=None, callback=None):
        self.directory = directory
        self.device_name = device_name
        self.callback = callback
        self.calls = []
        self.reason = ""
        self.instances.append(self)

    def start(self):
        self.calls.append(("start",))
        return True

    def configure_receive(self, **arguments):
        self.calls.append(("configure_receive", arguments))
        return arguments

    def stop(self):
        self.calls.append(("stop",))
        self.stop_lifecycle = background.daemon_status()

    def status(self, timeout=0.25):
        return {"available": True}


class FakeLoop:
    def __init__(self):
        self.stopped = threading.Event()

    def run(self):
        self.stopped.wait(5)

    def quit(self):
        self.stopped.set()


class FakeDaemonGLib:
    PRIORITY_DEFAULT = 0
    loop = None

    @classmethod
    def MainLoop(cls):
        cls.loop = FakeLoop()
        return cls.loop

    @staticmethod
    def idle_add(callback, *arguments):
        callback(*arguments)
        return 1


class FakeNativeNotifications:
    available = True
    actions_supported = True
    supported = True

    def __init__(self, _glib):
        pass

    def show(self, *_arguments):
        return True

    def open_organizer(self):
        raise AssertionError("Organizer must open only from an SMS action")


def test_daemon_applies_persisted_receive_settings_runtime_updates_and_shutdown():
    with tempfile.TemporaryDirectory() as root:
        downloads = os.path.join(root, "Downloads")
        os.mkdir(downloads)
        environment = {"XDG_DATA_HOME": os.path.join(root, "data"),
            "XDG_CONFIG_HOME": os.path.join(root, "config"),
            "XDG_RUNTIME_DIR": os.path.join(root, "runtime")}
        os.mkdir(environment["XDG_RUNTIME_DIR"])
        initial = {"enabled": True, "autostart": True,
            "kde_device_id": "a" * 32, "kde_download_directory": downloads,
            "kde_clipboard_enabled": True, "kde_clipboard_mode": "automatic",
            "kde_file_enabled": True,
            "permissions": {"kde_incoming_files": True}}
        with mock.patch.dict(os.environ, environment, clear=False):
            background.write_settings(initial)
            FakeDaemonBackend.instances.clear()
            result = []
            thread = threading.Thread(target=lambda: result.append(background.daemon_main(
                ["--language", "en"], backend_factory=FakeDaemonBackend,
                glib=FakeDaemonGLib, notifications_factory=FakeNativeNotifications)))
            thread.start()
            assert wait_until(background.daemon_available)
            assert background.daemon_status() == "ready"
            backend = FakeDaemonBackend.instances[-1]
            assert wait_until(lambda: any(call[0] == "configure_receive"
                                          for call in backend.calls))
            startup = next(call[1] for call in backend.calls
                           if call[0] == "configure_receive")
            assert startup["file_enabled"] is True
            assert startup["file_mode"] == "confirm"
            assert startup["download_directory"] == downloads

            changed = dict(background.read_settings(), kde_file_enabled=False,
                           kde_clipboard_mode="confirm")
            background.ipc_request("set_settings", {"settings": changed})
            assert wait_until(lambda: backend.calls[-1][0] == "configure_receive" and
                              backend.calls[-1][1]["file_enabled"] is False)
            disabled = dict(background.read_settings(), enabled=False, autostart=False)
            background.ipc_request("set_settings", {"settings": disabled})
            assert background.wait_for_daemon_release(timeout=4)
            thread.join(4)
            assert not thread.is_alive() and result == [0]
            assert backend.calls[-1] == ("stop",)
            assert backend.stop_lifecycle == "stopping"
            assert not os.path.exists(background.autostart_path())


def test_disabled_daemon_exits_before_glib_or_transport_initialization():
    with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {
            "XDG_DATA_HOME": os.path.join(root, "data"),
            "XDG_CONFIG_HOME": os.path.join(root, "config"),
            "XDG_RUNTIME_DIR": os.path.join(root, "runtime")}, clear=False):
        factory = mock.Mock()
        glib = mock.Mock()
        assert background.daemon_main([], backend_factory=factory, glib=glib) == 0
        factory.assert_not_called()
        glib.MainLoop.assert_not_called()


def test_daemon_gettext_uses_persisted_or_cli_language_without_gui_imports():
    with tempfile.TemporaryDirectory() as root:
        config = os.path.join(root, background.PROGRAM_NAME)
        os.mkdir(config)
        with open(os.path.join(config, "locale.json"), "w", encoding="utf-8") as target:
            json.dump({"language": "fr"}, target)
        translation = mock.Mock()
        translation.gettext.side_effect = lambda text: text
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": root}, clear=False), \
             mock.patch.object(background.gettext, "translation", return_value=translation) as load:
            background.initialize_translation([])
            assert load.call_args.kwargs["languages"] == ["fr"]
            background.initialize_translation(["--sprache", "de"])
            assert load.call_args.kwargs["languages"] == ["de"]


def test_gui_bridge_migrates_legacy_receive_settings_and_suppresses_native_decisions():
    loader = importlib.machinery.SourceFileLoader("magnolie_background_bridge_test", PROGRAM)
    module = loader.load_module()
    existing = background.normalize_settings({})
    captured = []
    with mock.patch.object(module, "background_settings_read", return_value=existing), \
         mock.patch.object(module, "hintergrund_einstellungen_schreiben",
                           side_effect=lambda value: captured.append(value) or {"ok": True}):
        module.kde_einstellungen_migrieren(True, True, "d" * 32, True, "/tmp")
    migrated = captured[-1]
    assert migrated["enabled"] is True and migrated["autostart"] is True
    assert migrated["kde_device_id"] == "d" * 32
    assert migrated["kde_download_directory"] == "/tmp"
    assert migrated["kde_clipboard_mode"] == "automatic"
    assert migrated["kde_file_enabled"] is True
    assert migrated["permissions"]["kde_incoming_files"] is True
    assert "password" not in migrated

    already = background.normalize_settings({"enabled": True, "autostart": True,
        "kde_legacy_migrated": True, "permissions": {"phone_monitor": True}})
    captured.clear()
    with mock.patch.object(module, "background_settings_read", return_value=already), \
         mock.patch.object(module, "hintergrund_einstellungen_schreiben",
                           side_effect=lambda value: captured.append(value) or {"ok": True}):
        module.kde_einstellungen_migrieren(False, False, "", False, "")
    changed = captured[-1]
    assert changed["enabled"] is True and changed["autostart"] is True
    assert changed["permissions"]["phone_monitor"] is True

    source = open(PROGRAM, encoding="utf-8").read()
    web = open(os.path.join(ROOT, "web", "anwendung.js"), encoding="utf-8").read()
    assert 'befehl == "background_settings_get"' in source
    assert 'befehl == "background_settings_set"' in source
    assert 'gui_present and event in ("pairing", "file_proposal")' in open(
        os.path.join(BIN, "magnolie_hintergrund.py"), encoding="utf-8").read()
    assert 'App.backgroundSettings' in source and "backgroundSettings(nutzlast)" in web
    assert 'cmd: "background_settings_set"' in web
    assert "dateienAutomatisch" not in web and "filesAutomatic" not in web
    assert 'file_mode": "confirm"' in open(
        os.path.join(BIN, "magnolie_hintergrund.py"), encoding="utf-8").read()


def test_gui_backend_factory_selects_proxy_while_daemon_is_running():
    loader = importlib.machinery.SourceFileLoader("magnolie_background_proxy_test", PROGRAM)
    module = loader.load_module()
    module._KDECONNECT_BACKEND = None
    proxy = mock.Mock()
    proxy.start.return_value = True
    with mock.patch.object(module, "daemon_available", return_value=True), \
         mock.patch.object(module, "KDEConnectProxy", return_value=proxy), \
         mock.patch.object(module, "KDEConnectSMSBackend") as local_backend:
        assert module._kdeconnect_backend() is proxy
    local_backend.assert_not_called()


class FakePhoneService:
    def __init__(self):
        self.enabled = True
        self.listening = True
        self.stop_calls = 0
        self.replays = 0
        self.lock = threading.RLock()
        self.personal_dispatched = set()

    def report(self):
        return {"possible": True, "enabled": self.enabled,
                "listening": self.listening, "peers": []}

    def request_status(self, peer_id):
        return "status:" + peer_id

    def replay_personal_sync(self):
        self.replays += 1

    def stop(self):
        self.stop_calls += 1
        self.listening = False


def test_phone_proxy_has_one_listener_owner_forwards_events_and_close_keeps_daemon():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "runtime", "background.sock")
        phone = FakePhoneService()
        server = background.IPCServer(FakeBackend(), path, phone_backend=phone).start()
        received = []
        proxy = background.PhoneServiceProxy(path,
            callback=lambda event, payload: received.append((event, payload)))
        try:
            assert proxy.start()
            assert proxy.request_status("peer") == "status:peer"
            assert phone.listening and phone.stop_calls == 0
            ticket_payload = {"event": "selected_notification",
                              "payload": {"title": "Calendar", "text": "Meeting"}}
            server.phone_event_getter = lambda ticket: ticket_payload if ticket == "t" else None
            server.publish_event("phone_event", {"ticket": "t"})
            assert wait_until(lambda: received == [("selected_notification",
                {"title": "Calendar", "text": "Meeting"})])
            proxy.stop()
            assert phone.listening and phone.stop_calls == 0
            assert background.daemon_available(path)
        finally:
            server.close()


def test_closed_gui_phone_notifications_start_only_from_clicked_actions():
    phone = FakePhoneService()
    notifications = RecordedNotifications()
    settings = {"permissions": {"phone_selected_notifications": True,
        "phone_call_notifications": True, "phone_sms_notifications": True}}
    events = background.PhoneDaemonEvents(lambda: phone, settings, notifications,
        ImmediateGLib, lambda *_args: True, lambda: False)
    events("selected_notification", {"app": "Mail", "text": "Message"})
    events("incoming_call", {"state": "ringing", "name": "Alice"})
    events("sms", {"from": "+49170", "text": "Hello"})
    assert notifications.opened == 0
    assert len(notifications.items) == 3
    notifications.items[-1][2][0][2]()
    assert notifications.opened == 1


def test_closed_gui_personal_sync_offer_defers_payload_until_action_click():
    phone = FakePhoneService()
    phone.personal_dispatched.add("commit-token")
    notifications = RecordedNotifications()
    published = []
    events = background.PhoneDaemonEvents(lambda: phone, {
        "permissions": {"phone_personal_sync_offers": True}}, notifications,
        ImmediateGLib, lambda *args: published.append(args) or True, lambda: False)
    events("personal_sync", {"commit_token": "commit-token",
        "body": {"records": [{"kind": "note", "value": "opaque"}]}})
    assert "commit-token" not in phone.personal_dispatched
    assert published == []
    assert notifications.opened == 0
    title, body, actions, _on_close = notifications.items[-1]
    assert "phone changes" in title.lower()
    assert "synchronize" in body.lower()
    actions[0][2]()
    assert notifications.opened == 1
