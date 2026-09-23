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

from modul_laden import quellmodul_laden


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
            "kde_file_enabled": True, "kde_choose_directory": True,
            "permissions": {"kde_incoming_files": True}})
        assert valid["kde_device_id"] == "a" * 32
        assert valid["kde_download_directory"] == os.path.realpath(root)
        assert valid["kde_choose_directory"] is True
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
        escaped = appimage.replace("%", "%%").replace("\\", "\\\\\\\\").replace(
            '"', '\\\\"').replace("`", "\\\\`").replace("$", "\\\\$")
        assert escaped in text
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


def test_sms_reply_intent_is_bounded_expires_and_launches_without_shell():
    now = int(time.time() * 1000)
    encoded = background.sms_reply_intent_encode({"from": "+491701234567",
        "device_id": "d" * 32, "sms_id": "sms-1"}, now)
    decoded = background.sms_reply_intent_decode(encoded, now)
    assert decoded["number"] == "+491701234567" and decoded["device_id"] == "d" * 32
    with pytest.raises(ValueError):
        background.sms_reply_intent_decode(encoded,
            now + background.SMS_REPLY_LIFETIME_MS + 1)
    current = background.sms_reply_intent_encode({"from": "+491701234567",
        "device_id": "d" * 32, "sms_id": "sms-2"})
    notifications = background.NativeNotifications.__new__(background.NativeNotifications)
    notifications.executable = "/opt/Magnolie Organizer/bin/magnolie-organizer"
    with mock.patch.object(background.subprocess, "Popen") as popen:
        notifications.open_organizer(current)
    command = popen.call_args.args[0]
    assert command[:2] == [notifications.executable, "--sms-reply-file"]
    request_path = command[2]
    assert current not in " ".join(command)
    assert background.sms_reply_request_read(request_path) == current
    assert not os.path.exists(request_path)
    assert popen.call_args.kwargs.get("shell") is not True

    formatted = background.sms_reply_intent_encode({"from": "0170 / 123 45 67",
        "device_id": "d" * 32, "sms_id": "sms-3"}, now)
    assert background.sms_reply_intent_decode(formatted, now)["number"] == \
        "0170 / 123 45 67"


def test_headless_cli_dispatches_before_any_gui_import(tmp_path, monkeypatch):
    from magnolie_setup_state import write_state
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    write_state("complete")
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
        "magnolie-organizer", "2.0.20", "background-service")
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

    def accept_receive(self, receive_id, directory=""):
        self.calls.append(("accept_receive", receive_id, directory) if directory else
                          ("accept_receive", receive_id))

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


def test_gui_subscription_tracks_process_presence_and_window_visibility():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "runtime", "background.sock")
        server = background.IPCServer(FakeBackend(), path).start()
        proxy = background.KDEConnectProxy(path, callback=lambda *_args: None)
        try:
            assert proxy.start()
            assert server.gui_present() is False
            assert server.gui_connected() is True
            assert server.gui_notification_ready() is False
            assert proxy.set_ready(True)
            assert server.gui_notification_ready() is True
            assert proxy.set_visible(True) is True
            assert server.gui_present() is True
            assert proxy.set_visible(False) is False
            assert server.gui_present() is False
            assert server.gui_connected() is True
            proxy.stop()
            assert server.gui_present() is False
            assert server.gui_connected() is False
        finally:
            server.close()


class ImmediateGLib:
    @staticmethod
    def timeout_add(*arguments):
        return 1

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

    def open_organizer(self, intent=None):
        self.opened += 1
        self.intent = intent


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

    events("clipboard_proposal", {"id": "c" * 32, "text": "Desktop text"})
    notifications.items[-1][2][0][2]()
    assert backend.calls[-1] == ("accept_receive", "c" * 32)

    events("sms", {"notify": True, "from": "+49170\nBad", "text": "Hello\x00there"})
    assert notifications.opened == 0
    assert not notifications.items[-1][2]
    events("sms", {"notify": True, "from": "+491701234567", "text": "Hello",
        "device_id": "d" * 32, "sms_id": "sms-1"})
    notifications.items[-1][2][0][2]()
    assert notifications.opened == 1
    intent = background.sms_reply_intent_decode(notifications.intent)
    assert intent["number"] == "+491701234567" and intent["device_id"] == "d" * 32


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


def test_connected_gui_owns_sms_notification_even_when_visibility_differs():
    backend = FakeBackend()
    notifications = RecordedNotifications()
    published = []
    copied = []
    settings = {"permissions": {"kde_pairing": True,
        "kde_incoming_files": True, "sms_phone_notifications": True}}
    events = background.DaemonEvents(lambda: backend, settings, notifications,
        ImmediateGLib, lambda event, payload: published.append((event, payload)),
        lambda: True, copied.append)
    events("pairing", {"device_name": "Phone", "code": "12345678"})
    events("file_proposal", {"id": "a" * 32, "name": "text.txt", "size": 4})
    events("clipboard_proposal", {"id": "b" * 32, "text": "Desktop text"})
    events("sms", {"notify": True, "from": "+49170", "text": "Hello"})
    events("clipboard_apply", {"text": "Desktop text"})
    events("file_ready", {"name": "text.txt", "path": "/tmp/text.txt"})
    events("receive_error", {"kind": "file", "reason": "transport"})
    assert [item[0] for item in notifications.items] == [
        "KDE Connect pairing", "Incoming KDE Connect file",
        "Copy this KDE Connect text to the clipboard?", "Magnolie Organizer",
        "Magnolie Organizer", "Magnolie Organizer"]
    assert [event for event, _payload in published] == [
        "sms", "clipboard_apply", "file_ready", "receive_error"]
    assert published[0][1]["notify"] is True
    assert copied == ["Desktop text"]


@pytest.mark.parametrize("gui_visible", [False, True])
@pytest.mark.parametrize("background_permission", [False, True])
def test_connected_organizer_sms_alert_does_not_require_daemon_only_permission(gui_visible, background_permission):
    notifications = RecordedNotifications()
    published = []
    events = background.DaemonEvents(lambda: FakeBackend(),
        {"permissions": {"sms_phone_notifications": background_permission}},
        notifications, ImmediateGLib,
        lambda event, payload: published.append((event, payload)),
        gui_present=lambda: gui_visible, gui_connected=lambda: True)
    events("sms", {"notify": True, "from": "+491701234567", "text": "Test"})
    assert published[-1][1]["notify"] is True
    assert notifications.items == []
    # Historical/suppressed backend events must still remain silent.
    events("sms", {"notify": False, "from": "+491701234567", "text": "History"})
    assert published[-1][1]["notify"] is False


def test_disconnected_organizer_still_requires_daemon_sms_permission():
    notifications = RecordedNotifications()
    published = []
    events = background.DaemonEvents(lambda: FakeBackend(),
        {"permissions": {"sms_phone_notifications": False}}, notifications,
        ImmediateGLib, lambda event, payload: published.append((event, payload)),
        gui_present=lambda: False, gui_connected=lambda: False)
    events("sms", {"notify": True, "from": "+491701234567", "text": "Test"})
    assert notifications.items == []
    assert published[-1][1]["notify"] is False


def test_proxy_restores_tray_readiness_and_cursor_after_service_restart():
    delivered = []
    proxy = background.KDEConnectProxy(path="unused-test-socket",
        callback=lambda event, payload: delivered.append(event))
    proxy._cursor = 99
    proxy._visible = False
    proxy._ready = True
    calls = []
    polls = []

    def request(operation, arguments, path, timeout):
        calls.append((operation, dict(arguments)))
        if operation == "poll_events":
            polls.append(arguments["after"])
            if len(polls) == 1:
                return {"cursor": 1, "events": []}
            proxy._event_stop.set()
            return {"cursor": 2, "events": [{"event": "sms", "payload": {}}]}
        return {}

    with mock.patch.object(background, "ipc_request", side_effect=request):
        proxy._event_loop()
    assert polls == [99, 1]
    assert delivered == ["sms"]
    assert sum(op == "gui_readiness" and data["ready"] is True for op, data in calls) == 2
    assert sum(op == "gui_visibility" and data["visible"] is False for op, data in calls) == 2


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
    phone_events("incoming_call", {"direction": "incoming", "state": "ringing", "number": "+49170"})
    assert notifications.items[-1][0] == "Incoming call"
    assert notifications.items[-1][2] == ()


def test_actionless_decisions_fall_back_to_visible_gui_without_rejecting():
    backend = FakeBackend()
    notifications = ActionlessNotifications()
    published = []
    events = background.DaemonEvents(lambda: backend, {
        "permissions": {"kde_pairing": True, "kde_incoming_files": True}},
        notifications, ImmediateGLib,
        lambda event, payload: published.append((event, payload)), lambda: True)
    events("pairing", {"device_name": "Phone", "code": "12345678"})
    events("file_proposal", {"id": "f" * 32, "name": "document.pdf", "size": 7})
    events("clipboard_proposal", {"id": "c" * 32, "text": "Desktop text"})
    assert backend.calls == []
    assert [event for event, _payload in published] == [
        "pairing", "file_proposal", "clipboard_proposal"]
    assert len(notifications.items) == 6
    assert all(not actions for _title, _body, actions, _close in notifications.items[1::2])


def test_file_destination_choice_opens_gui_instead_of_accepting_natively():
    backend = FakeBackend()
    notifications = RecordedNotifications()
    published = []
    events = background.DaemonEvents(lambda: backend, {
        "permissions": {"kde_incoming_files": True},
        "kde_device_id": "a" * 32, "kde_download_directory": "/tmp",
        "kde_file_enabled": True, "kde_choose_directory": True},
        notifications, ImmediateGLib,
        lambda event, payload: published.append((event, payload)), lambda: False)
    events("file_proposal", {"id": "f" * 32, "name": "document.pdf", "size": 7})
    assert backend.calls == []
    assert len(notifications.items[-1][2]) == 1
    assert notifications.items[-1][2][0][0] == "open"
    assert published == [("file_proposal", {
        "id": "f" * 32, "name": "document.pdf", "size": 7})]


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

    def open_organizer(self, _intent=None):
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


def test_gui_bridge_migrates_legacy_receive_settings_and_keeps_native_decisions():
    module = quellmodul_laden("magnolie_background_bridge_test", PROGRAM)
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
    background_source = open(os.path.join(BIN, "magnolie_hintergrund.py"),
                             encoding="utf-8").read()
    assert 'gui_present and event in ("pairing", "file_proposal")' not in background_source
    assert 'event not in ("pairing", "file_proposal", "clipboard_proposal")' in background_source
    assert 'App.backgroundSettings' in source and "backgroundSettings(nutzlast)" in web
    assert 'cmd: "background_settings_set"' in web
    assert "dateienAutomatisch" not in web and "filesAutomatic" not in web
    assert 'file_mode": "confirm"' in open(
        os.path.join(BIN, "magnolie_hintergrund.py"), encoding="utf-8").read()


def test_gui_backend_factory_selects_proxy_while_daemon_is_running():
    module = quellmodul_laden("magnolie_background_proxy_test", PROGRAM)
    module._KDECONNECT_BACKEND = None
    proxy = mock.Mock()
    proxy.start.return_value = True
    with mock.patch.object(module, "daemon_available", return_value=True), \
         mock.patch.object(module, "KDEConnectProxy", return_value=proxy), \
         mock.patch.object(module, "create_backend") as local_backend, \
         mock.patch.object(module, "_hintergrund_bereitschaft_senden") as readiness:
        assert module._kdeconnect_backend() is proxy
    local_backend.assert_not_called()
    readiness.assert_called_once_with(proxy, False, "magnolie-kde-readiness")


def test_gui_visibility_helper_skips_thread_for_current_proxy_state():
    module = quellmodul_laden("magnolie_visibility_test", PROGRAM)
    backend = types.SimpleNamespace(_visible=True)
    with mock.patch.object(module.threading, "Thread") as thread:
        module._hintergrund_sichtbarkeit_senden(backend, True, "visibility-test")
    thread.assert_not_called()


def test_visibility_is_not_sent_again_after_success():
    for proxy_class in (background.KDEConnectProxy, background.PhoneServiceProxy):
        proxy = proxy_class("/unused")
        with mock.patch.object(background, "ipc_request",
                side_effect=lambda _operation, arguments, *_args, **_kwargs: {
                    "visible": arguments["visible"]}) as request:
            assert proxy.set_visible(True) is True
            assert proxy.set_visible(True) is True
            assert proxy.set_visible(False) is False
            assert proxy.set_visible(False) is False
        assert request.call_count == 2


def test_readiness_is_coalesced_and_stale_update_cannot_win():
    module = quellmodul_laden("magnolie_readiness_test", PROGRAM)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = []

    class Backend:
        _ready = None

        def set_ready(self, ready):
            calls.append(ready)
            if len(calls) == 1:
                entered.set()
                assert release.wait(2)
            else:
                finished.set()

    backend = Backend()
    module._hintergrund_bereitschaft_senden(backend, True, "readiness-test")
    assert entered.wait(2)
    module._hintergrund_bereitschaft_senden(backend, False, "readiness-test")
    release.set()
    assert finished.wait(2)
    assert calls == [True, False]


def test_proxy_readiness_is_not_sent_again_after_success():
    proxy = background.KDEConnectProxy("/unused")
    with mock.patch.object(background, "ipc_request",
            side_effect=lambda _operation, arguments, *_args, **_kwargs: {
                "ready": arguments["ready"]}) as request:
        assert proxy.set_ready(True) is True
        assert proxy.set_ready(True) is True
        assert proxy.set_ready(False) is False
        assert proxy.set_ready(False) is False
    assert request.call_count == 2


class FakePhoneService:
    def call_event_current(self, peer_id, call_ref, revision, state):
        return True

    def call_is_current(self, peer_id, call_ref, revision):
        return True

    def call_action_tokens(self, peer_id, call_ref, revision):
        return {}

    def __init__(self):
        self.enabled = True
        self.listening = True
        self.stop_calls = 0
        self.replays = 0
        self.pairing_calls = []
        self.status_requests = []
        self.lock = threading.RLock()
        self.personal_dispatched = set()

    def report(self):
        return {"possible": True, "enabled": self.enabled,
                "listening": self.listening, "peers": []}

    def request_status(self, peer_id, request_id=None):
        self.status_requests.append((peer_id, request_id))
        return request_id if request_id is not None else "status:" + peer_id

    def replay_personal_sync(self):
        self.replays += 1

    def confirm_pairing(self, attempt, accepted):
        self.pairing_calls.append((attempt, accepted))

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
            request_id = "22222222-2222-4222-8222-222222222222"
            assert proxy.request_status("peer", request_id=request_id) == request_id
            assert phone.status_requests == [("peer", None), ("peer", request_id)]
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
    events("selected_notification", {"event": "posted", "app": "Mail", "text": "Message"})
    events("incoming_call", {"direction": "incoming", "state": "ringing", "name": "Alice"})
    events("sms", {"from": "+49170", "text": "Hello"})
    assert notifications.opened == 0
    assert len(notifications.items) == 3
    notifications.items[-1][2][0][2]()
    assert notifications.opened == 1


def test_phone_notifications_forward_calls_to_gui_without_duplicate_system_alert():
    phone = FakePhoneService()
    notifications = RecordedNotifications()
    published = []
    settings = {"permissions": {"phone_selected_notifications": True,
        "phone_call_notifications": True, "phone_sms_notifications": True,
        "phone_pairing_decisions": True}}
    events = background.PhoneDaemonEvents(lambda: phone, settings, notifications,
        ImmediateGLib, lambda *args: published.append(args) or True, lambda: True)
    events("selected_notification", {"event": "posted", "app": "Mail", "text": "Message"})
    events("incoming_call", {"direction": "incoming", "state": "ringing", "number": "+49170"})
    events("sms", {"from": "+49170", "text": "Hello"})
    events("pairing_code", {"attempt_id": "a" * 32, "code": "123 456"})
    assert len(notifications.items) == 3
    notifications.items[-1][2][0][2]()
    assert phone.pairing_calls == [("a" * 32, True)]
    assert len(published) == 3
    assert all(event == "phone_event" and "ticket" in payload
               for event, payload in published)


def test_dated_kde_sms_history_is_forwarded_without_native_replay():
    notifications = RecordedNotifications()
    published = []
    events = background.DaemonEvents(lambda: FakeBackend(), {
        "permissions": {"sms_phone_notifications": True}}, notifications,
        ImmediateGLib, lambda *args: published.append(args) or True, lambda: True,
        notification_since_ms=2000)
    events("sms", {"id": "old", "timestamp_ms": 1999, "read": False,
                   "from": "+49170", "text": "old", "notify": True})
    events("sms", {"id": "new", "timestamp_ms": 2000, "read": False,
                   "from": "+49170", "text": "new", "notify": True})
    assert notifications.items == []
    assert len(published) == 2
    assert published[0][1]["notify"] is False
    assert published[1][1]["notify"] is True


def test_old_clipboard_connect_replay_is_not_applied_or_offered():
    backend = FakeBackend()
    notifications = RecordedNotifications()
    copied = []
    events = background.DaemonEvents(lambda: backend, {}, notifications,
        ImmediateGLib, clipboard_setter=lambda text: copied.append(text) or True,
        notification_since_ms=2000)
    events("clipboard_apply", {"id": "a" * 32, "device_id": "d" * 32,
                               "timestamp_ms": 1999, "text": "old"})
    events("clipboard_proposal", {"id": "b" * 32, "device_id": "d" * 32,
                                  "timestamp_ms": 1999, "text": "old"})
    assert copied == [] and notifications.items == []
    assert backend.calls[-1] == ("reject_receive", "b" * 32)


def test_phone_replays_removed_read_and_old_events_without_native_notifications():
    notifications = RecordedNotifications()
    published = []
    settings = {"permissions": {"phone_selected_notifications": True,
        "phone_call_notifications": True, "phone_sms_notifications": True}}
    events = background.PhoneDaemonEvents(lambda: FakePhoneService(), settings, notifications,
        ImmediateGLib, lambda *args: published.append(args) or True, lambda: True,
        notification_since_ms=2000)
    events("selected_notification", {"event": "removed", "posted_ms": 3000})
    events("selected_notification", {"event": "posted", "posted_ms": 1999,
                                      "app_label": "Mail", "text": "old"})
    events("incoming_call", {"direction": "incoming", "state": "ringing", "occurred_ms": 1999})
    events("sms", {"timestamp_ms": 3000, "read": True, "text": "read"})
    events("selected_notification", {"event": "posted", "posted_ms": 2000,
                                      "app_label": "Mail", "text": "new"})
    events("incoming_call", {"direction": "incoming", "state": "ringing", "occurred_ms": 2000})
    events("sms", {"timestamp_ms": 2000, "read": False, "text": "new"})
    assert len(notifications.items) == 2
    assert len(published) == 7
    assert events.take(published[2][1]["ticket"])["payload"]["notify"] is False
    assert events.take(published[5][1]["ticket"])["payload"]["notify"] is True


def test_background_freshness_survives_restart_without_storing_raw_event_ids():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "background-freshness.json")
        event_id = "private-event-identity"
        first = background.BackgroundFreshness(path, now_ms=2000)
        assert first.is_fresh("kde_connect", "sms", {
            "id": event_id, "timestamp_ms": 2000}, "timestamp_ms")
        assert not first.is_fresh("kde_connect", "sms", {
            "id": event_id, "timestamp_ms": 2001}, "timestamp_ms")

        restarted = background.BackgroundFreshness(path, now_ms=3000)
        assert restarted.notification_cutoff_ms == 3000
        assert not restarted.is_fresh("kde_connect", "sms", {
            "id": event_id, "timestamp_ms": 4000}, "timestamp_ms")
        assert restarted.is_fresh("kde_connect", "sms", {
            "id": "another-event", "timestamp_ms": 4000}, "timestamp_ms")
        assert event_id not in open(path, encoding="ascii").read()


def test_persistent_identity_suppresses_undated_native_replay_after_restart():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "background-freshness.json")
        settings = {"permissions": {"phone_sms_notifications": True}}
        payload = {"message_id": "stable-phone-message", "read": False,
                   "from": "+49170", "text": "Hello"}
        notifications = RecordedNotifications()
        first = background.PhoneDaemonEvents(lambda: FakePhoneService(), settings,
            notifications, ImmediateGLib, lambda *_args: True, lambda: False,
            freshness=background.BackgroundFreshness(path, now_ms=2000))
        first("sms", payload)
        restarted = background.PhoneDaemonEvents(lambda: FakePhoneService(), settings,
            notifications, ImmediateGLib, lambda *_args: True, lambda: False,
            freshness=background.BackgroundFreshness(path, now_ms=3000))
        restarted("sms", payload)
        assert len(notifications.items) == 1


def test_background_diagnostics_are_bounded_and_contain_no_payload_content():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "state", "background-events.log")
        diagnostics = background.BackgroundDiagnostics(path)
        diagnostics.record("kde_connect", "sms", {
            "device_id": "private-device-id", "from": "+491701234567",
            "title": "Private title", "text": "Private message",
            "incoming": True}, "historical", "suppressed")
        snapshot = diagnostics.storage_snapshot(root)
        diagnostics.close()
        text = open(path, encoding="utf-8").read()
        entry = json.loads(text)
        assert entry["source"] == "kde_connect"
        assert entry["freshness"] == "historical" and entry["outcome"] == "suppressed"
        assert entry["device"] != "private-device-id" and len(entry["device"]) == 12
        assert entry["payload_text_bytes"] > 0 and snapshot["event_log_bytes"] > 0
        assert not any(value in text for value in (
            "private-device-id", "+491701234567", "Private title", "Private message"))


def test_actionless_phone_pairing_falls_back_to_visible_gui():
    phone = FakePhoneService()
    notifications = ActionlessNotifications()
    published = []
    events = background.PhoneDaemonEvents(lambda: phone, {
        "permissions": {"phone_pairing_decisions": True}}, notifications,
        ImmediateGLib, lambda *args: published.append(args) or True, lambda: True)
    events("pairing_code", {"attempt_id": "a" * 32, "code": "123 456"})
    assert phone.pairing_calls == []
    assert len(notifications.items) == 2
    assert len(published) == 1 and published[0][0] == "phone_event"


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
