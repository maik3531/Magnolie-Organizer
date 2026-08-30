#!/usr/bin/env python3
"""Private background-service foundation for Magnolie Organizer."""

import gettext
import json
import os
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections import deque

from magnolie_kdeconnect import (DEVICE_ID, KDEConnectSMSBackend, ProtocolError,
                                 local_device_name)


PROGRAM_NAME = "magnolie-organizer"
SETTINGS_NAME = "background-settings.json"
SOCKET_NAME = "background.sock"
AUTOSTART_NAME = "io.gitlab.maik3531.MagnolieOrganizer.Background.desktop"
MAX_IPC_MESSAGE = 64 * 1024
MAX_PHONE_ARGUMENTS = 2 * 1024 * 1024
MAX_PHONE_MESSAGE = 72 * 1024 * 1024
MAX_EVENTS = 256
MAX_IPC_HANDLERS = 8
IPC_READ_TIMEOUT = 5
LARGE_IPC_OPERATIONS = {
    "phone_send_personal_sync_run", "phone_index_local_attachments",
}
POLICIES = ("notify_then_unlock", "keyring", "pause_when_locked")
PERMISSIONS = (
    "kde_pairing",
    "kde_incoming_files",
    "sms_phone_notifications",
    "magnolienbaum_change_offers",
    "phone_monitor",
    "phone_sms_notifications",
    "phone_selected_notifications",
    "phone_call_notifications",
    "phone_personal_sync_offers",
    "phone_pairing_decisions",
)
DEFAULT_SETTINGS = {
    "enabled": False,
    "autostart": False,
    "encryption_policy": "notify_then_unlock",
    "permissions": {name: False for name in PERMISSIONS},
    "kde_device_id": "",
    "kde_download_directory": "",
    "kde_clipboard_enabled": False,
    "kde_clipboard_mode": "confirm",
    "kde_file_enabled": False,
    "kde_legacy_migrated": False,
    "kde_receive_managed": False,
}

_ = gettext.gettext


class IPCError(RuntimeError):
    pass


class AlreadyRunning(IPCError):
    pass


def data_directory():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, PROGRAM_NAME)
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def settings_path(directory=None):
    return os.path.join(directory or data_directory(), SETTINGS_NAME)


def normalize_settings(value):
    value = value if isinstance(value, dict) else {}
    permissions = value.get("permissions")
    permissions = permissions if isinstance(permissions, dict) else {}
    policy = value.get("encryption_policy")
    device_id = value.get("kde_device_id")
    device_id = device_id if isinstance(device_id, str) and DEVICE_ID.fullmatch(
        device_id) else ""
    directory = value.get("kde_download_directory")
    if (not isinstance(directory, str) or not directory or len(directory) > 4096
            or not os.path.isabs(directory) or "\0" in directory
            or any(unicodedata.category(char).startswith("C") for char in directory)):
        directory = ""
    else:
        directory = os.path.realpath(directory)
    clipboard = value.get("kde_clipboard_enabled") is True and bool(device_id)
    files = (value.get("kde_file_enabled") is True and bool(device_id)
             and bool(directory))
    return {
        "enabled": value.get("enabled") is True,
        "autostart": value.get("autostart") is True,
        "encryption_policy": (policy if policy == "notify_then_unlock"
                              else "notify_then_unlock"),
        "permissions": {name: permissions.get(name) is True for name in PERMISSIONS},
        "kde_device_id": device_id,
        "kde_download_directory": directory,
        "kde_clipboard_enabled": clipboard,
        "kde_clipboard_mode": ("automatic" if clipboard and
            value.get("kde_clipboard_mode") == "automatic" else "confirm"),
        "kde_file_enabled": files,
        "kde_legacy_migrated": value.get("kde_legacy_migrated") is True,
        "kde_receive_managed": value.get("kde_receive_managed") is True,
    }


def _locale_directory():
    script = os.path.dirname(os.path.realpath(__file__))
    for candidate in (os.environ.get("MAGNOLIE_LOCALE_DIR"),
            os.path.join(script, "..", "locale"), os.path.join(script, "locale"),
            "/usr/share/locale"):
        if candidate and os.path.isdir(os.path.abspath(candidate)):
            return os.path.abspath(candidate)
    return "/usr/share/locale"


def initialize_translation(arguments=None):
    global _
    arguments = list(arguments or ())
    language = None
    selected = None
    for index, argument in enumerate(arguments):
        if argument in ("--sprache", "--language") and index + 1 < len(arguments):
            selected = arguments[index + 1].strip().replace("-", "_")
            break
    if selected is None:
        config_base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        try:
            with open(os.path.join(config_base, PROGRAM_NAME, "locale.json"),
                      encoding="utf-8") as source:
                selected = str(json.load(source).get("language") or "system").replace("-", "_")
        except (OSError, TypeError, ValueError, AttributeError):
            selected = "system"
    if selected != "system" and re.fullmatch(
            r"[A-Za-z]{2,3}(?:_[A-Za-z0-9]{2,8})?", selected or ""):
        language = [selected]
    translation = gettext.translation(PROGRAM_NAME, localedir=_locale_directory(),
                                      languages=language, fallback=True)
    _ = translation.gettext
    return translation


def read_settings(path=None):
    try:
        with open(path or settings_path(), "r", encoding="utf-8") as source:
            return normalize_settings(json.load(source))
    except (OSError, TypeError, ValueError):
        return normalize_settings({})


def _atomic_text(path, text, mode=0o600):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".background-", dir=directory)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            descriptor = -1
            target.write(text)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def keyring_supported():
    """Encrypted organizer data is not available to the background service."""
    return False


def settings_status(settings=None):
    value = normalize_settings(settings if settings is not None else read_settings())
    value["encryption_policy_supported"] = value["encryption_policy"] == "notify_then_unlock"
    value["keyring_available"] = False
    return value


def write_settings(value, path=None, update_autostart=None, executable=None):
    clean = normalize_settings(value)
    _atomic_text(path or settings_path(), json.dumps(
        clean, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    if update_autostart is None:
        update_autostart = path is None
    if update_autostart:
        configure_autostart(clean, executable=executable)
    return settings_status(clean)


def autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", AUTOSTART_NAME)


def service_executable(executable=None):
    appimage = os.environ.get("APPIMAGE")
    if appimage and os.path.isabs(appimage):
        return appimage
    candidate = executable or sys.argv[0]
    if os.path.sep not in candidate:
        resolved = shutil.which(candidate)
        if resolved:
            candidate = resolved
    return os.path.abspath(candidate)


def _desktop_exec_argument(value):
    if not isinstance(value, str) or not value or "\0" in value or "\n" in value or "\r" in value:
        raise ValueError("invalid desktop Exec argument")
    value = value.replace("%", "%%")
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("`", "\\`").replace("$", "\\$")
    return '"%s"' % value


def autostart_contents(executable=None):
    flatpak_id = os.environ.get("FLATPAK_ID", "")
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", flatpak_id):
        command = " ".join(_desktop_exec_argument(value) for value in
                           ("/usr/bin/flatpak", "run", flatpak_id))
    else:
        command = _desktop_exec_argument(service_executable(executable))
    return ("[Desktop Entry]\nType=Application\nVersion=1.0\n"
            "Name=%s\nComment=%s\n"
            "Exec=%s --hintergrunddienst\nTerminal=false\n"
            "NoDisplay=true\nX-GNOME-Autostart-enabled=true\n" % (
                _("Magnolie Organizer Background Service"),
                _("Run approved Magnolie background functions"), command))


def configure_autostart(settings=None, executable=None, path=None):
    value = normalize_settings(settings if settings is not None else read_settings())
    target = path or autostart_path()
    if value["enabled"] and value["autostart"]:
        _atomic_text(target, autostart_contents(executable), 0o600)
        return True
    try:
        os.unlink(target)
    except FileNotFoundError:
        pass
    return False


def runtime_directory():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and os.path.isabs(base):
        path = os.path.join(base, PROGRAM_NAME)
    else:
        path = os.path.join(data_directory(), "runtime")
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def socket_path():
    return os.path.join(runtime_directory(), SOCKET_NAME)


def start_service(executable=None, language=None, wait=3.0):
    command = [service_executable(executable), "--hintergrunddienst"]
    if language:
        command.extend(("--language", str(language)))
    subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + max(0, float(wait))
    while time.monotonic() < deadline:
        if daemon_available():
            return True
        time.sleep(0.05)
    return daemon_available()


def receive_configuration(settings):
    value = normalize_settings(settings)
    enabled = value["enabled"] and bool(value["kde_device_id"])
    return {
        "clipboard_enabled": enabled and value["kde_clipboard_enabled"],
        "file_enabled": (enabled and value["kde_file_enabled"] and
                         value["permissions"]["kde_incoming_files"]),
        "device_id": value["kde_device_id"] if enabled and (
            value["kde_clipboard_enabled"] or value["kde_file_enabled"]) else None,
        "clipboard_mode": value["kde_clipboard_mode"],
        "file_mode": "confirm",
        "download_directory": (value["kde_download_directory"]
                               if enabled and value["kde_file_enabled"] else None),
    }


def _safe_text(value, limit):
    text = "".join(" " if unicodedata.category(char).startswith("C") else char
                   for char in str(value or ""))
    return " ".join(text.split())[:limit]


def _json_safe(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    identity = getattr(value, "identity", None)
    if isinstance(identity, dict):
        return {"device_id": identity.get("deviceId", ""),
                "device_name": identity.get("deviceName", "")}
    raise TypeError("operation returned a non-JSON value")


def _read_message(connection, maximum=MAX_IPC_MESSAGE, dynamic_request=False):
    data = bytearray()
    limit = maximum
    while len(data) <= limit:
        part = connection.recv(min(65536, limit + 1 - len(data)))
        if not part:
            raise IPCError("incomplete IPC request")
        data.extend(part)
        if dynamic_request and limit == MAX_IPC_MESSAGE and len(data) <= MAX_IPC_MESSAGE:
            match = re.match(br'^\{"op":"([a-z_]+)","args":', data)
            if match:
                operation = match.group(1).decode("ascii")
                if operation in LARGE_IPC_OPERATIONS:
                    limit = MAX_PHONE_MESSAGE
                elif operation.startswith("phone_"):
                    limit = MAX_PHONE_ARGUMENTS
        if b"\n" in part:
            break
    if len(data) > limit or not data.endswith(b"\n") or b"\n" in data[:-1]:
        raise IPCError("invalid IPC framing")
    try:
        def unique_object(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise IPCError("duplicate IPC JSON member")
                result[key] = item
            return result
        value = json.loads(data[:-1].decode("utf-8"),
                           object_pairs_hook=unique_object,
                           parse_constant=lambda _value: (_ for _ in ()).throw(
                               IPCError("non-finite IPC number")))
    except (UnicodeDecodeError, ValueError) as error:
        raise IPCError("invalid IPC JSON") from error
    if not isinstance(value, dict):
        raise IPCError("IPC request must be an object")
    return value


def _write_message(connection, value, maximum=MAX_IPC_MESSAGE):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                     allow_nan=False).encode("utf-8") + b"\n"
    if len(raw) > maximum:
        raise IPCError("IPC response exceeds size limit")
    connection.sendall(raw)


def _request_shape(operation, arguments):
    if not isinstance(arguments, dict):
        raise IPCError("operation arguments must be an object")
    allowed = {
        "ping": set(), "status": {"timeout"}, "discover": {"timeout"},
        "get_settings": set(), "set_settings": {"settings"},
        "event_cursor": set(), "poll_events": {"after", "timeout", "subscriber"},
        "gui_subscribe": {"subscriber"}, "gui_unsubscribe": {"subscriber"},
        "gui_visibility": {"subscriber", "visible"},
        "send_sms": {"destination", "message", "device_id"},
        "begin_pairing": {"device_id", "replace_stored"},
        "complete_pairing": {"device_id"}, "confirm_pairing": {"code_matches"},
        "configure_receive": {"clipboard_enabled", "file_enabled", "device_id",
            "clipboard_mode", "file_mode", "download_directory"},
        "accept_receive": {"receive_id"}, "reject_receive": {"receive_id"},
        "phone_report": set(), "phone_set_enabled": {"enabled"},
        "phone_open_pairing": set(), "phone_cancel_pairing": set(),
        "phone_confirm_pairing": {"attempt_id", "accepted"},
        "phone_remove": {"peer_id"},
        "phone_set_bluetooth": {"peer_id", "enabled", "address"},
        "phone_request_status": {"peer_id"},
        "phone_set_grant": {"peer_id", "name", "enabled"},
        "phone_set_personal_sync": {"peer_id", "own_device", "auto_wifi"},
        "phone_send_personal_sync": {"peer_id", "kind", "body", "trigger"},
        "phone_send_personal_sync_run": {"peer_id", "request", "batches", "sources",
            "trigger", "report"},
        "phone_commit_personal_sync": {"peer_id", "message_id", "token", "success"},
        "phone_index_local_attachments": {"peer_id", "run_id", "reply",
            "aggregate_hash", "sources"},
        "phone_request_dial": {"peer_id", "destination", "client_ref"},
        "phone_request_answer": {"peer_id", "call_ref", "command_ref"},
        "phone_request_end_call": {"peer_id", "call_ref", "revision", "command_ref"},
        "phone_replay_personal_sync": set(), "phone_take_event": {"ticket"},
    }
    if operation not in allowed or set(arguments) - allowed[operation]:
        raise IPCError("operation is not allowed")
    encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    maximum = (MAX_PHONE_MESSAGE if operation in LARGE_IPC_OPERATIONS else
               MAX_PHONE_ARGUMENTS if operation.startswith("phone_") else 32 * 1024)
    if len(encoded.encode("utf-8")) > maximum:
        raise IPCError("operation arguments exceed size limit")
    if operation in ("status", "discover"):
        timeout = arguments.get("timeout", 0.25 if operation == "status" else 0.7)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 5:
            raise IPCError("invalid timeout")
    if operation == "set_settings" and not isinstance(arguments.get("settings"), dict):
        raise IPCError("settings must be an object")
    if operation == "poll_events":
        after = arguments.get("after")
        timeout = arguments.get("timeout", 20)
        if (not isinstance(after, int) or isinstance(after, bool) or after < 0
                or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not 0 <= timeout <= 25):
            raise IPCError("invalid event poll")
    if operation in ("gui_subscribe", "gui_unsubscribe", "gui_visibility") or operation == "poll_events" \
            and "subscriber" in arguments:
        subscriber = arguments.get("subscriber")
        if not isinstance(subscriber, str) or not re.fullmatch(r"[a-f0-9]{32}", subscriber):
            raise IPCError("invalid GUI subscriber")
    if operation == "gui_visibility" and not isinstance(arguments.get("visible"), bool):
        raise IPCError("invalid GUI visibility")
    if operation == "confirm_pairing" and not isinstance(
            arguments.get("code_matches"), bool):
        raise IPCError("pairing decision must be boolean")
    if operation == "begin_pairing" and not isinstance(
            arguments.get("replace_stored", False), bool):
        raise IPCError("pairing replacement flag must be boolean")
    return allowed


class IPCServer:
    def __init__(self, backend, path=None, settings_getter=None,
                 settings_setter=None, shutdown_callback=None,
                 operation_callback=None, phone_backend=None,
                 phone_event_getter=None):
        self.backend = backend
        self.path = path or socket_path()
        self.listener = None
        self.thread = None
        self.stopped = threading.Event()
        self.status_extra = None
        self.settings_getter = settings_getter or read_settings
        self.settings_setter = settings_setter or write_settings
        self.shutdown_callback = shutdown_callback
        self.operation_callback = operation_callback
        self.phone_backend = phone_backend
        self.phone_event_getter = phone_event_getter
        self._events = deque(maxlen=MAX_EVENTS)
        self._event_sequence = 0
        self._event_condition = threading.Condition()
        self._gui_subscribers = {}
        self.lifecycle = "ready"
        self._handlers = threading.BoundedSemaphore(MAX_IPC_HANDLERS)
        self._mutation_lock = threading.RLock()
        self.settings_revision = 0

    def gui_present(self):
        now = time.monotonic()
        with self._event_condition:
            self._gui_subscribers = {key: value for key, value in
                self._gui_subscribers.items() if value[0] > now}
            return any(value[1] for value in self._gui_subscribers.values())

    def publish_event(self, event, payload):
        if not isinstance(event, str) or not event or len(event) > 80:
            return False
        value = {"event": event, "payload": _json_safe(payload)}
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > 24 * 1024:
            return False
        with self._event_condition:
            self._event_sequence += 1
            value["sequence"] = self._event_sequence
            self._events.append(value)
            self._event_condition.notify_all()
        return True

    def _poll_events(self, after, timeout):
        deadline = time.monotonic() + timeout
        with self._event_condition:
            while self._event_sequence <= after and not self.stopped.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._event_condition.wait(remaining)
            events = []
            size = 0
            for item in self._events:
                if item["sequence"] <= after:
                    continue
                item_size = len(json.dumps(item, ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8"))
                if events and size + item_size > 48 * 1024:
                    break
                events.append(dict(item))
                size += item_size
            cursor = events[-1]["sequence"] if events else self._event_sequence
            return {"cursor": cursor, "events": events}

    def start(self):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        os.chmod(os.path.dirname(self.path), 0o700)
        if os.path.lexists(self.path):
            try:
                if ipc_request("ping", path=self.path).get("running"):
                    raise AlreadyRunning("background service is already running")
            except AlreadyRunning:
                raise
            except Exception:
                try:
                    details = os.lstat(self.path)
                    if not stat.S_ISSOCK(details.st_mode):
                        raise IPCError("background IPC path is not a socket")
                    os.unlink(self.path)
                except FileNotFoundError:
                    pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(self.path)
            os.chmod(self.path, 0o600)
            listener.listen(8)
            listener.settimeout(0.5)
        except Exception:
            listener.close()
            raise
        self.listener = listener
        details = os.lstat(self.path)
        self._socket_identity = (details.st_dev, details.st_ino)
        self.stopped.clear()
        self.thread = threading.Thread(target=self._serve, daemon=True,
                                       name="magnolie-background-ipc")
        self.thread.start()
        return self

    def _serve(self):
        while not self.stopped.is_set():
            try:
                connection, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            connection.settimeout(IPC_READ_TIMEOUT)
            if not self._handlers.acquire(blocking=False):
                connection.close()
                continue
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection):
        try:
            with connection:
                self._handle_request(connection)
        finally:
            self._handlers.release()

    def _handle_request(self, connection):
            try:
                # The private runtime directory, mode 0600 socket and SO_PEERCRED
                # deliberately define the current same-UID authorization boundary.
                if hasattr(socket, "SO_PEERCRED"):
                    credentials = connection.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                    _pid, uid, _gid = struct.unpack("3i", credentials)
                    if uid != os.getuid():
                        raise IPCError("IPC peer has a different user")
                request = _read_message(connection, MAX_IPC_MESSAGE, dynamic_request=True)
                if set(request) != {"op", "args"} or not isinstance(request["op"], str):
                    raise IPCError("invalid IPC request")
                operation, arguments = request["op"], request["args"]
                _request_shape(operation, arguments)
                if operation == "ping":
                    result = {"running": True, "lifecycle": self.lifecycle}
                elif operation == "get_settings":
                    result = settings_status(self.settings_getter())
                    if isinstance(self.status_extra, dict):
                        result.update(self.status_extra)
                    result.update(lifecycle=self.lifecycle,
                                  settings_revision=self.settings_revision)
                elif operation == "set_settings":
                    with self._mutation_lock:
                        result = self.settings_setter(arguments["settings"])
                        self.settings_revision += 1
                        result.update(lifecycle=self.lifecycle,
                                      settings_revision=self.settings_revision)
                        if not result["enabled"] and self.shutdown_callback:
                            self.shutdown_callback()
                elif operation == "event_cursor":
                    with self._event_condition:
                        oldest = (self._events[0]["sequence"] if self._events
                                  else self._event_sequence + 1)
                        result = {"cursor": self._event_sequence, "oldest": oldest}
                elif operation == "poll_events":
                    subscriber = arguments.get("subscriber")
                    if subscriber:
                        with self._event_condition:
                            visible = self._gui_subscribers.get(subscriber, (0, False))[1]
                            self._gui_subscribers[subscriber] = (time.monotonic() + 35, visible)
                    result = self._poll_events(arguments["after"],
                                               float(arguments.get("timeout", 20)))
                elif operation == "gui_subscribe":
                    with self._event_condition:
                        self._gui_subscribers[arguments["subscriber"]] = (
                            time.monotonic() + 35, False)
                        result = {"subscribed": True, "cursor": self._event_sequence}
                elif operation == "gui_visibility":
                    subscriber = arguments["subscriber"]
                    with self._event_condition:
                        if subscriber not in self._gui_subscribers:
                            raise IPCError("GUI subscriber is not registered")
                        self._gui_subscribers[subscriber] = (
                            time.monotonic() + 35, arguments["visible"])
                    result = {"visible": arguments["visible"]}
                elif operation == "gui_unsubscribe":
                    with self._event_condition:
                        self._gui_subscribers.pop(arguments["subscriber"], None)
                    result = {"subscribed": False}
                elif operation.startswith("phone_"):
                    result = self._phone_operation(operation, arguments)
                else:
                    if operation == "configure_receive":
                        arguments = dict(arguments, file_mode="confirm")
                    result = getattr(self.backend, operation)(**arguments)
                    if self.operation_callback is not None:
                        self.operation_callback(operation, result)
                    if operation == "status" and isinstance(result, dict) and \
                            isinstance(self.status_extra, dict):
                        background = dict(self.status_extra)
                        background.update(lifecycle=self.lifecycle,
                                          settings_revision=self.settings_revision)
                        result = dict(result, background=background)
                maximum = MAX_PHONE_MESSAGE if operation.startswith("phone_") else MAX_IPC_MESSAGE
                _write_message(connection, {"ok": True, "result": _json_safe(result)}, maximum)
            except Exception as error:
                try:
                    _write_message(connection, {"ok": False,
                        "error": _safe_text(error, 300) or type(error).__name__})
                except Exception:
                    pass

    def _phone_operation(self, operation, arguments):
        if operation == "phone_take_event":
            if self.phone_event_getter is None:
                raise IPCError("phone event is unavailable")
            return self.phone_event_getter(arguments["ticket"])
        phone = self.phone_backend
        if phone is None:
            raise IPCError("phone service is not owned by the background service")
        calls = {
            "phone_report": ("report", ()),
            "phone_set_enabled": ("set_enabled", ("enabled",)),
            "phone_open_pairing": ("open_pairing", ()),
            "phone_cancel_pairing": ("cancel_pairing", ()),
            "phone_confirm_pairing": ("confirm_pairing", ("attempt_id", "accepted")),
            "phone_remove": ("remove", ("peer_id",)),
            "phone_set_bluetooth": ("set_bluetooth", ("peer_id", "enabled", "address")),
            "phone_request_status": ("request_status", ("peer_id",)),
            "phone_set_grant": ("set_grant", ("peer_id", "name", "enabled")),
            "phone_set_personal_sync": ("set_personal_sync", ("peer_id", "own_device", "auto_wifi")),
            "phone_send_personal_sync": ("send_personal_sync", ("peer_id", "kind", "body", "trigger")),
            "phone_send_personal_sync_run": ("send_personal_sync_run",
                ("peer_id", "request", "batches", "sources", "trigger", "report")),
            "phone_commit_personal_sync": ("commit_personal_sync",
                ("peer_id", "message_id", "token", "success")),
            "phone_index_local_attachments": ("index_local_attachments",
                ("peer_id", "run_id", "reply", "aggregate_hash", "sources")),
            "phone_request_dial": ("request_dial", ("peer_id", "destination", "client_ref")),
            "phone_request_answer": ("request_answer", ("peer_id", "call_ref", "command_ref")),
            "phone_request_end_call": ("request_end_call",
                ("peer_id", "call_ref", "revision", "command_ref")),
            "phone_replay_personal_sync": ("replay_personal_sync", ()),
        }
        if operation not in calls:
            raise IPCError("phone operation is not allowed")
        method, names = calls[operation]
        return getattr(phone, method)(*(arguments[name] for name in names))

    def close(self):
        self.lifecycle = "stopping"
        self.stopped.set()
        with self._event_condition:
            self._event_condition.notify_all()
        if self.listener is not None:
            self.listener.close()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(2)
        try:
            details = os.lstat(self.path)
            identity = (details.st_dev, details.st_ino)
            if stat.S_ISSOCK(details.st_mode) and identity == getattr(
                    self, "_socket_identity", None):
                os.unlink(self.path)
        except FileNotFoundError:
            pass


def ipc_request(operation, arguments=None, path=None, timeout=6):
    _request_shape(operation, arguments or {})
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(path or socket_path())
        _write_message(connection, {"op": operation, "args": arguments or {}})
        response = _read_message(connection, MAX_PHONE_MESSAGE if operation.startswith("phone_")
                                 else MAX_IPC_MESSAGE)
    finally:
        connection.close()
    if set(response) != {"ok", "result"} and set(response) != {"ok", "error"}:
        raise IPCError("invalid IPC response")
    if response.get("ok") is not True:
        raise IPCError(str(response.get("error") or "background operation failed"))
    return response["result"]


def daemon_status(path=None):
    try:
        result = ipc_request("ping", path=path, timeout=0.3)
        if result.get("running") is True:
            return str(result.get("lifecycle") or "starting")
    except Exception:
        pass
    return "stopped"


def daemon_available(path=None):
    return daemon_status(path) == "ready"


def wait_for_daemon_release(path=None, timeout=6):
    deadline = time.monotonic() + max(0, float(timeout))
    while time.monotonic() < deadline:
        if daemon_status(path) == "stopped":
            return True
        time.sleep(0.05)
    return daemon_status(path) == "stopped"


class KDEConnectProxy:
    """The GUI-facing KDE Connect API while the daemon owns the transport."""
    def __init__(self, path=None, callback=None):
        self.path = path or socket_path()
        self.callback = callback
        self._event_stop = threading.Event()
        self._event_thread = None
        self._subscriber = os.urandom(16).hex()
        self._cursor = 0
        self._visible = None

    def start(self):
        available = daemon_available(self.path)
        if available and self.callback is not None and (
                self._event_thread is None or not self._event_thread.is_alive()):
            subscription = ipc_request("gui_subscribe",
                {"subscriber": self._subscriber}, self.path)
            self._cursor = max(0, int(subscription.get("cursor", 0)))
            self._visible = None
            self._event_stop.clear()
            self._event_thread = threading.Thread(target=self._event_loop, daemon=True,
                                                  name="magnolie-background-events")
            self._event_thread.start()
        return available

    def stop(self):
        # Transport lifetime belongs to the background service, not the GUI.
        self._event_stop.set()
        try:
            ipc_request("gui_unsubscribe", {"subscriber": self._subscriber}, self.path,
                        timeout=1)
        except Exception:
            pass
        return None

    def set_visible(self, visible):
        visible = bool(visible)
        if self._visible is visible:
            return visible
        try:
            result = ipc_request("gui_visibility", {"subscriber": self._subscriber,
                "visible": visible}, self.path, timeout=1)
            if result.get("visible") is visible:
                self._visible = visible
                return visible
            return False
        except Exception:
            return False

    def _event_loop(self):
        cursor = self._cursor
        while not self._event_stop.is_set():
            try:
                result = ipc_request("poll_events", {"after": cursor, "timeout": 1,
                                     "subscriber": self._subscriber},
                                     self.path, timeout=2)
                cursor = max(cursor, int(result.get("cursor", cursor)))
                for item in result.get("events", ()):
                    callback = self.callback
                    if callback is not None:
                        callback(item.get("event"), item.get("payload") or {})
            except Exception:
                if not daemon_available(self.path):
                    return

    def get_settings(self):
        return self._call("get_settings")

    def set_settings(self, settings):
        return self._call("set_settings", settings=settings)

    def _call(self, operation, **arguments):
        return ipc_request(operation, arguments, self.path)

    def status(self, timeout=0.25):
        return self._call("status", timeout=timeout)

    def discover(self, timeout=0.7):
        return self._call("discover", timeout=timeout)

    def send_sms(self, destination, message, device_id=None):
        arguments = {"destination": destination, "message": message}
        if device_id is not None:
            arguments["device_id"] = device_id
        return self._call("send_sms", **arguments)

    def begin_pairing(self, device_id=None, replace_stored=False):
        return self._call("begin_pairing", device_id=device_id,
                          replace_stored=replace_stored)

    def complete_pairing(self, device_id):
        return self._call("complete_pairing", device_id=device_id)

    def confirm_pairing(self, code_matches):
        return self._call("confirm_pairing", code_matches=code_matches)

    def configure_receive(self, **arguments):
        return self._call("configure_receive", **arguments)

    def accept_receive(self, receive_id):
        return self._call("accept_receive", receive_id=receive_id)

    def reject_receive(self, receive_id):
        return self._call("reject_receive", receive_id=receive_id)


class PhoneServiceProxy:
    """Explicit GUI API for the daemon-owned Magnolie Notes listener."""
    def __init__(self, path=None, callback=None):
        self.path = path or socket_path()
        self.callback = callback or (lambda _event, _payload: None)
        self._event_stop = threading.Event()
        self._event_thread = None
        self._subscriber = os.urandom(16).hex()
        self._cursor = 0
        self._visible = None

    def _call(self, operation, **arguments):
        return ipc_request("phone_" + operation, arguments, self.path, timeout=30)

    def start(self):
        if not daemon_available(self.path):
            return False
        if self._event_thread is None or not self._event_thread.is_alive():
            subscription = ipc_request("gui_subscribe",
                {"subscriber": self._subscriber}, self.path)
            self._cursor = max(0, int(subscription.get("cursor", 0)))
            self._visible = None
            self._event_stop.clear()
            self._event_thread = threading.Thread(target=self._event_loop, daemon=True,
                                                  name="magnolie-phone-events")
            self._event_thread.start()
            self._call("replay_personal_sync")
        return bool(self.report().get("listening"))

    def stop(self):
        self._event_stop.set()
        try:
            ipc_request("gui_unsubscribe", {"subscriber": self._subscriber}, self.path,
                        timeout=1)
        except Exception:
            pass

    def set_visible(self, visible):
        visible = bool(visible)
        if self._visible is visible:
            return visible
        try:
            result = ipc_request("gui_visibility", {"subscriber": self._subscriber,
                "visible": visible}, self.path, timeout=1)
            if result.get("visible") is visible:
                self._visible = visible
                return visible
            return False
        except Exception:
            return False

    def _event_loop(self):
        cursor = self._cursor
        while not self._event_stop.is_set():
            try:
                result = ipc_request("poll_events", {"after": cursor, "timeout": 1,
                    "subscriber": self._subscriber}, self.path, timeout=2)
                cursor = max(cursor, int(result.get("cursor", cursor)))
                for item in result.get("events", ()):
                    if item.get("event") != "phone_event":
                        continue
                    payload = item.get("payload") or {}
                    ticket = payload.get("ticket")
                    delivered = self._call("take_event", ticket=ticket) if ticket else None
                    if isinstance(delivered, dict):
                        self.callback(delivered.get("event"), delivered.get("payload") or {})
            except Exception:
                if not daemon_available(self.path):
                    return

    @property
    def enabled(self):
        return bool(self.report().get("enabled"))

    def report(self): return self._call("report")
    def set_enabled(self, enabled): return self._call("set_enabled", enabled=bool(enabled))
    def open_pairing(self): return self._call("open_pairing")
    def cancel_pairing(self): return self._call("cancel_pairing")
    def confirm_pairing(self, attempt_id, accepted):
        return self._call("confirm_pairing", attempt_id=attempt_id, accepted=bool(accepted))
    def remove(self, peer_id): return self._call("remove", peer_id=peer_id)
    def set_bluetooth(self, peer_id, enabled, address=""):
        return self._call("set_bluetooth", peer_id=peer_id, enabled=bool(enabled), address=address)
    def request_status(self, peer_id): return self._call("request_status", peer_id=peer_id)
    def set_grant(self, peer_id, name, enabled):
        return self._call("set_grant", peer_id=peer_id, name=name, enabled=bool(enabled))
    def set_personal_sync(self, peer_id, own_device, auto_wifi=False):
        return self._call("set_personal_sync", peer_id=peer_id,
                          own_device=bool(own_device), auto_wifi=bool(auto_wifi))
    def send_personal_sync(self, peer_id, kind, body, trigger="manual"):
        return self._call("send_personal_sync", peer_id=peer_id, kind=kind,
                          body=body, trigger=trigger)
    def send_personal_sync_run(self, peer_id, request, batches, sources,
                               trigger="manual", report=None):
        return self._call("send_personal_sync_run", peer_id=peer_id, request=request,
            batches=batches, sources=sources, trigger=trigger, report=report)
    def commit_personal_sync(self, peer_id, message_id, token, success):
        return self._call("commit_personal_sync", peer_id=peer_id,
            message_id=message_id, token=token, success=bool(success))
    def index_local_attachments(self, peer_id, run_id, reply, aggregate_hash, sources):
        return self._call("index_local_attachments", peer_id=peer_id, run_id=run_id,
            reply=bool(reply), aggregate_hash=aggregate_hash, sources=sources)
    def replay_personal_sync(self): return self._call("replay_personal_sync")
    def request_dial(self, peer_id, destination, client_ref):
        return self._call("request_dial", peer_id=peer_id, destination=destination,
                          client_ref=client_ref)
    def request_answer(self, peer_id, call_ref, command_ref):
        return self._call("request_answer", peer_id=peer_id, call_ref=call_ref,
                          command_ref=command_ref)
    def request_end_call(self, peer_id, call_ref, revision, command_ref):
        return self._call("request_end_call", peer_id=peer_id, call_ref=call_ref,
            revision=revision, command_ref=command_ref)


class NativeNotifications:
    def __init__(self, glib, executable=None):
        self.glib = glib
        self.executable = service_executable(executable)
        self.notifications = set()
        self.keyed_notifications = {}
        self.available = False
        self.actions_supported = False
        try:
            import gi
            gi.require_version("Notify", "0.7")
            from gi.repository import Notify
            self.Notify = Notify
            self.available = bool(Notify.init(_("Magnolie Organizer")))
            capabilities = set(Notify.get_server_caps() or ()) if self.available else set()
            self.actions_supported = "actions" in capabilities
        except Exception:
            self.Notify = None
        self.supported = self.actions_supported

    def show(self, title, body, actions=(), on_close=None, key=None):
        actions = tuple(actions)[:2]
        if not self.available or actions and not self.actions_supported:
            return False
        try:
            notification = self.Notify.Notification.new(
                _safe_text(title, 160), _safe_text(body, 500), PROGRAM_NAME)
            self.notifications.add(notification)
            if key:
                previous = self.keyed_notifications.pop(key, None)
                if previous is not None:
                    previous.close()
                self.keyed_notifications[key] = notification
            decided = {"value": False}

            def close(*_unused):
                self.notifications.discard(notification)
                if key and self.keyed_notifications.get(key) is notification:
                    self.keyed_notifications.pop(key, None)
                if not decided["value"] and on_close is not None:
                    decided["value"] = True
                    try:
                        on_close()
                    except Exception:
                        pass

            notification.connect("closed", close)
            for action_id, label, callback in actions:
                def activate(_notification, _action, _data=None, callback=callback):
                    if decided["value"]:
                        return
                    decided["value"] = True
                    try:
                        callback()
                    except Exception:
                        pass
                    finally:
                        close()
                notification.add_action(action_id, _safe_text(label, 60), activate)
            notification.show()
            return True
        except Exception:
            return False

    def withdraw(self, key):
        notification = self.keyed_notifications.pop(key, None)
        if notification is None:
            return False
        try:
            notification.close()
        except Exception:
            pass
        return True

    def open_organizer(self):
        subprocess.Popen([self.executable], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def native_clipboard_set(text):
    """Set the session clipboard without opening an Organizer window."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk
        initialized = Gtk.init_check([])
        if not (initialized[0] if isinstance(initialized, tuple) else initialized):
            return False
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(str(text), -1)
        clipboard.store()
        return True
    except Exception:
        return False


class DaemonEvents:
    def __init__(self, backend_getter, settings, notifications, glib,
                  event_publisher=None, gui_present=None, clipboard_setter=None):
        self.backend_getter = backend_getter
        self.settings = normalize_settings(settings)
        self.notifications = notifications
        self.glib = glib
        self.event_publisher = event_publisher or (lambda _event, _payload: None)
        self.gui_present = gui_present or (lambda: False)
        self.clipboard_setter = clipboard_setter or native_clipboard_set

    def __call__(self, event, payload):
        self.glib.idle_add(self._handle, event, dict(payload or {}))

    @staticmethod
    def _decision(callback):
        lock = threading.Lock()
        decided = {"value": False}

        def decide(value):
            with lock:
                if decided["value"]:
                    return False
                decided["value"] = True
            try:
                callback(value)
            except Exception:
                pass
            return True
        return decide

    def _handle(self, event, payload):
        permissions = self.settings["permissions"]
        backend = self.backend_getter()
        forward_decision = False
        if event == "receive_expired":
            withdraw = getattr(self.notifications, "withdraw", None)
            if withdraw is not None:
                withdraw(str(payload.get("id") or ""))
            return False
        if event == "pairing":
            if not permissions["kde_pairing"]:
                backend.confirm_pairing(False)
                return False
            name = _safe_text(payload.get("device_name"), 80) or _("KDE Connect device")
            code = _safe_text(payload.get("code"), 16)
            decide = self._decision(backend.confirm_pairing)
            title, body = _("KDE Connect pairing"), "%s: %s" % (name, code)
            shown = self.notifications.show(title, body, (
                     ("accept", _("Accept"), lambda: decide(True)),
                     ("reject", _("Reject"), lambda: decide(False))),
                on_close=lambda: decide(False))
            if not shown:
                if self.gui_present():
                    self.notifications.show(title, body)
                    forward_decision = True
                else:
                    self.notifications.show(title, "%s - %s" % (body, _("Reject")))
                    decide(False)
        elif event == "file_proposal":
            receive_id = str(payload.get("id") or "")
            if not permissions["kde_incoming_files"]:
                backend.reject_receive(receive_id)
                return False
            name = _safe_text(payload.get("name"), 180) or _("File")
            size = payload.get("size") if isinstance(payload.get("size"), int) else 0
            decide = self._decision(lambda accepted: (
                backend.accept_receive(receive_id) if accepted else
                backend.reject_receive(receive_id)))
            title, body = _("Incoming KDE Connect file"), "%s (%d bytes)" % (name, size)
            shown = self.notifications.show(title, body, (
                     ("accept", _("Accept"), lambda: decide(True)),
                     ("reject", _("Reject"), lambda: decide(False))),
                on_close=lambda: decide(False), key=receive_id)
            if not shown:
                if self.gui_present():
                    self.notifications.show(title, body, key=receive_id)
                    forward_decision = True
                else:
                    self.notifications.show(title, "%s - %s" % (body, _("Reject")),
                        key=receive_id)
                    decide(False)
        elif event == "clipboard_proposal":
            receive_id = str(payload.get("id") or "")
            text = str(payload.get("text") or "")
            decide = self._decision(lambda accepted: (
                backend.accept_receive(receive_id) if accepted else
                backend.reject_receive(receive_id)))
            title = _("Copy this KDE Connect text to the clipboard?")
            shown = self.notifications.show(title, _safe_text(text, 300), (
                     ("accept", _("Accept"), lambda: decide(True)),
                     ("reject", _("Reject"), lambda: decide(False))),
                on_close=lambda: decide(False), key=receive_id)
            if not shown:
                if self.gui_present():
                    self.notifications.show(title, _safe_text(text, 300), key=receive_id)
                    forward_decision = True
                else:
                    self.notifications.show(title, "%s - %s" % (
                        _safe_text(text, 300), _("Reject")), key=receive_id)
                    decide(False)
        elif event == "clipboard_apply":
            if self.clipboard_setter(str(payload.get("text") or "")):
                self.notifications.show(_("Magnolie Organizer"),
                                        _("Text copied to the clipboard."))
            else:
                self.notifications.show(_("Magnolie Organizer"),
                                        _("KDE Connect reception failed."))
        elif event == "file_ready":
            name = _safe_text(payload.get("name"), 180) or _("Unknown file")
            self.notifications.show(_("Magnolie Organizer"),
                _("File saved in Downloads: %(name)s") % {"name": name})
        elif event == "receive_error":
            self.notifications.show(_("Magnolie Organizer"),
                                    _("KDE Connect reception failed."))
        elif event == "sms" and payload.get("notify") and permissions[
                "sms_phone_notifications"]:
            sender = _safe_text(payload.get("from"), 80) or _("Phone")
            text = _safe_text(payload.get("text"), 300)
            if not self.notifications.show(_("SMS from %s") % sender, text, (
                    ("reply", _("Reply"), self.notifications.open_organizer),)):
                self.notifications.show(_("SMS from %s") % sender, text)
        if forward_decision or event not in ("pairing", "file_proposal", "clipboard_proposal"):
            forwarded = dict(payload)
            if event == "sms":
                forwarded["notify"] = False
            self.event_publisher(event, forwarded)
        return False


class PhoneDaemonEvents:
    """Keep phone data opaque, notify natively, and mirror it to an attached GUI."""
    def __init__(self, backend_getter, settings, notifications, glib,
                 event_publisher, gui_present):
        self.backend_getter = backend_getter
        self.settings = normalize_settings(settings)
        self.notifications = notifications
        self.glib = glib
        self.event_publisher = event_publisher
        self.gui_present = gui_present
        self._pending = {}
        self._pending_size = 0
        self._lock = threading.Lock()

    def __call__(self, event, payload):
        self.glib.idle_add(self._handle, event, dict(payload or {}))

    def take(self, ticket):
        if not isinstance(ticket, str):
            raise IPCError("invalid phone event ticket")
        with self._lock:
            item = self._pending.pop(ticket, None)
            if item is not None:
                self._pending_size -= item[1]
        if item is None:
            raise IPCError("phone event is no longer available")
        return item[0]

    def _forward(self, event, payload):
        value = {"event": event, "payload": _json_safe(payload)}
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size > MAX_PHONE_MESSAGE:
            return False
        ticket = os.urandom(16).hex()
        with self._lock:
            while self._pending and self._pending_size + size > MAX_PHONE_MESSAGE:
                oldest = next(iter(self._pending))
                self._pending_size -= self._pending.pop(oldest)[1]
            self._pending[ticket] = (value, size)
            self._pending_size += size
        if not self.event_publisher("phone_event", {"ticket": ticket}):
            with self._lock:
                removed = self._pending.pop(ticket, None)
                if removed:
                    self._pending_size -= removed[1]
            return False
        return True

    def _open_action(self):
        return (("open", _("Start Organizer"), self.notifications.open_organizer),)

    def _handle(self, event, payload):
        backend = self.backend_getter()
        permissions = self.settings["permissions"]
        gui_present = self.gui_present()
        if event in ("personal_sync", "personal_sync_offer"):
            token = payload.get("commit_token")
            if backend is not None and isinstance(token, str):
                with backend.lock:
                    backend.personal_dispatched.discard(token)
            if gui_present:
                self._forward(event, payload)
                return False
            if permissions["phone_personal_sync_offers"]:
                self.notifications.show(_("New phone changes are available"),
                    _("Start Organizer and synchronize."), self._open_action())
        elif event == "pairing_code":
            attempt = str(payload.get("attempt_id") or "")
            code = _safe_text(payload.get("code"), 16)
            if not permissions["phone_pairing_decisions"]:
                if backend is not None:
                    backend.confirm_pairing(attempt, False)
            elif not self.notifications.show(_("Magnolie Notes pairing"), code, (
                    ("accept", _("Accept"), lambda: backend.confirm_pairing(attempt, True)),
                    ("reject", _("Reject"), lambda: backend.confirm_pairing(attempt, False)))):
                self.notifications.show(_("Magnolie Notes pairing"), code)
                if gui_present:
                    self._forward(event, payload)
                else:
                    backend.confirm_pairing(attempt, False)
        elif event == "selected_notification" and permissions[
                "phone_selected_notifications"]:
            title = _safe_text(payload.get("app_label") or payload.get("title"), 100) or _("Phone notification")
            body = _safe_text(payload.get("text") or payload.get("body"), 400)
            if not self.notifications.show(title, body, self._open_action()):
                self.notifications.show(title, body)
        elif event == "incoming_call" and payload.get("state") == "ringing" and permissions[
                "phone_call_notifications"]:
            caller = _safe_text(payload.get("number"), 120) or _("Unknown caller")
            if not self.notifications.show(_("Incoming call"), caller, self._open_action()):
                self.notifications.show(_("Incoming call"), caller)
        elif event == "sms" and permissions["phone_sms_notifications"]:
            sender = _safe_text(payload.get("from"), 80) or _("Phone")
            title = _("SMS from %s") % sender
            body = _safe_text(payload.get("text"), 300)
            if not self.notifications.show(title, body, (
                    ("reply", _("Reply"), self.notifications.open_organizer),)):
                self.notifications.show(title, body)
        if gui_present and event != "pairing_code":
            self._forward(event, payload)
        return False


def daemon_main(_arguments=None, backend_factory=KDEConnectSMSBackend,
                 glib=None, notifications_factory=NativeNotifications,
                 phone_factory=None):
    """Run without importing Gtk, WebKit, AppIndicator, or creating a window."""
    initialize_translation(_arguments)
    settings = read_settings()
    if not settings["enabled"]:
        configure_autostart(settings)
        return 0
    if glib is None:
        try:
            import gi
            from gi.repository import GLib as glib
        except Exception as error:
            sys.stderr.write(_("Magnolie background service requires GLib: %s") % error + "\n")
            return 1
    holder = {"backend": None, "phone": None, "loop": None}
    notifications = notifications_factory(glib)
    server = None
    loop = glib.MainLoop()
    holder["loop"] = loop

    def make_phone():
        selected = phone_factory
        if selected is None:
            from magnolie_telefon import PhoneService
            selected = PhoneService
        return selected(os.path.join(data_directory(), "telefon"),
                        local_device_name(), callback=phone_events)

    def apply_settings(value):
        clean = write_settings(value)
        events.settings = normalize_settings(clean)
        phone_events.settings = normalize_settings(clean)
        receive_error = ""
        if holder["backend"] is not None and clean["enabled"]:
            try:
                holder["backend"].configure_receive(**receive_configuration(clean))
            except Exception:
                receive_error = "receive_configuration_unavailable"
                holder["backend"].configure_receive()
        if holder["phone"] is None and clean["enabled"] and clean[
                "permissions"]["phone_monitor"]:
            holder["phone"] = server.phone_backend = make_phone()
            holder["phone"].personal_sync_available = server.gui_present
        if holder["phone"] is not None:
            if clean["enabled"] and clean["permissions"]["phone_monitor"] and \
                    holder["phone"].enabled:
                holder["phone"].start()
            else:
                holder["phone"].stop()
        extra = settings_status(clean)
        extra.update(native_notifications_supported=bool(
            getattr(notifications, "available", False)),
            native_actions_supported=bool(
                getattr(notifications, "actions_supported",
                        getattr(notifications, "supported", False))),
            receive_configuration_error=receive_error)
        if server is not None:
            server.status_extra = extra
        if not clean["enabled"] and holder["loop"] is not None:
            server.lifecycle = "stopping"
            glib.idle_add(lambda: (holder["loop"].quit(), False)[1])
        return extra

    server = IPCServer(None, settings_getter=read_settings,
                       settings_setter=apply_settings,
                       shutdown_callback=lambda: None)
    server.lifecycle = "starting"
    events = DaemonEvents(lambda: holder["backend"], settings, notifications, glib,
                           server.publish_event, server.gui_present)
    phone_events = PhoneDaemonEvents(lambda: holder["phone"], settings, notifications,
                                     glib, server.publish_event, server.gui_present)
    server.phone_event_getter = phone_events.take
    server.operation_callback = lambda operation, result: (
        events("pairing", result) if operation in ("begin_pairing", "complete_pairing")
        and isinstance(result, dict) and result.get("state") == "requested" else None)
    server.status_extra = settings_status(settings)
    server.status_extra.update(native_notifications_supported=bool(
        getattr(notifications, "available", False)),
        native_actions_supported=bool(getattr(
            notifications, "actions_supported", getattr(notifications, "supported", False))),
        receive_configuration_error="")
    try:
        # Claim ownership before constructing the transport backend.
        server.start()
        if settings["permissions"]["phone_monitor"]:
            phone = make_phone()
            phone.personal_sync_available = server.gui_present
            holder["phone"] = server.phone_backend = phone
            if phone.enabled:
                deadline = time.monotonic() + 3
                while not phone.start() and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not phone.server:
                    raise OSError("Magnolie Notes phone listener is unavailable")
        backend = backend_factory(os.path.join(data_directory(), "kdeconnect"),
                                  device_name=local_device_name(), callback=events)
        holder["backend"] = server.backend = backend
        if not backend.start():
            raise ProtocolError("KDE Connect transport is unavailable: %s" %
                                getattr(backend, "reason", "unknown"))
        current_settings = read_settings()
        apply_settings(current_settings)
        if not current_settings["enabled"]:
            return 0
        server.lifecycle = "ready"
        if hasattr(glib, "unix_signal_add"):
            for signum in (signal.SIGTERM, signal.SIGINT):
                glib.unix_signal_add(glib.PRIORITY_DEFAULT, signum,
                                     lambda: (loop.quit(), False)[1])
        loop.run()
        return 0
    except AlreadyRunning:
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ProtocolError) as error:
        sys.stderr.write(_("Magnolie background service could not start: %s") % error + "\n")
        return 1
    finally:
        server.lifecycle = "stopping"
        if holder["backend"] is not None:
            holder["backend"].stop()
        if holder["phone"] is not None:
            holder["phone"].stop()
        server.close()
