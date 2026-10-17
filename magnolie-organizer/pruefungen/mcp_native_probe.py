#!/usr/bin/env python3
"""Bounded Xvfb probe of the real source GTK/WebKit/native save/MCP stdio path."""
import importlib.machinery
import importlib.util
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zlib
import zipfile
import xml.etree.ElementTree as ET

BACKGROUND_PROBE = os.environ.get("MAGNOLIE_MCP_PROBE_BACKGROUND") == "1"
if BACKGROUND_PROBE:
    current_network = os.readlink("/proc/self/ns/net")
    outer_network = os.environ.get("MAGNOLIE_MCP_PROBE_OUTER_NETNS")
    if outer_network is None:
        os.environ["MAGNOLIE_MCP_PROBE_OUTER_NETNS"] = current_network
        os.environ["MAGNOLIE_MCP_PROBE_OUTER_UID"] = str(os.getuid())
        os.execvp("unshare", ["unshare", "--user", "--map-current-user", "--net", "--keep-caps", "--",
            "dbus-run-session", "--", sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:]])
    assert outer_network != current_network and os.environ["MAGNOLIE_MCP_PROBE_OUTER_UID"] == str(os.getuid()), "Background probe requires a private network namespace with unchanged UID"
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True, timeout=5)

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
temporary = tempfile.TemporaryDirectory(prefix="magnolie-mcp-native-", dir="/tmp/opencode")
for variable, directory in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                            ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"),
                            ("XDG_RUNTIME_DIR", "runtime")):
    target = Path(temporary.name) / directory
    target.mkdir(mode=0o700)
    os.environ[variable] = str(target)
os.environ["GSETTINGS_BACKEND"] = "memory"
os.environ["NO_AT_BRIDGE"] = "1"
os.environ["GIO_USE_VFS"] = "local"
os.environ["MESA_SHADER_CACHE_DISABLE"] = "true"
os.environ["SSH_AUTH_SOCK"] = str(Path(os.environ["XDG_RUNTIME_DIR"]) / "unused-ssh-agent.sock")
os.environ["GNOME_KEYRING_CONTROL"] = str(Path(os.environ["XDG_RUNTIME_DIR"]) / "keyring")
os.environ["WAYLAND_DISPLAY"] = ""
os.environ["GDK_BACKEND"] = "x11"
os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]

# dbus-run-session starts before Python replaces HOME/XDG. Validate its ownership
# before changing only this bus's activation environment, including display/socket
# paths so activated services cannot discover the user's session or keyring.
from gi.repository import Gio, GLib
native_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
def bus_pid(name):
    return native_bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
        "org.freedesktop.DBus", "GetConnectionUnixProcessID", GLib.Variant("(s)", (name,)),
        GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
def parent_pid(pid):
    return int(Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()[1])
ancestors = set()
ancestor = os.getpid()
for _ in range(16):
    if ancestor <= 1:
        break
    command = Path("/proc/%d/cmdline" % ancestor).read_bytes().split(b"\0")[0]
    if Path(os.fsdecode(command)).name == "dbus-run-session":
        ancestors.add(ancestor)
    ancestor = parent_pid(ancestor)
assert parent_pid(bus_pid("org.freedesktop.DBus")) in ancestors, "Probe requires its own dbus-run-session ancestor"
activation_keys = ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
    "SSH_AUTH_SOCK", "GNOME_KEYRING_CONTROL", "WAYLAND_DISPLAY", "GDK_BACKEND", "DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS")
activation_environment = {key: os.environ.get(key, "") for key in activation_keys}
native_bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
    "UpdateActivationEnvironment", GLib.Variant("(a{ss})", (activation_environment,)),
    None, Gio.DBusCallFlags.NONE, 5000, None)
private_service_handles = {}
def capture_private_secret_service():
    try:
        pid = bus_pid("org.freedesktop.secrets")
    except GLib.Error:
        return
    if pid in private_service_handles:
        return
    handle = os.pidfd_open(pid)
    try:
        environment = dict(item.split(b"=", 1) for item in Path("/proc/%d/environ" % pid).read_bytes().split(b"\0") if b"=" in item)
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR", "SSH_AUTH_SOCK", "GNOME_KEYRING_CONTROL", "DISPLAY"):
            assert environment.get(key.encode()) == activation_environment[key].encode(), "Activated service escaped private " + key
        private_service_handles[pid] = handle
    except BaseException:
        os.close(handle)
        raise
def stop_private_secret_service():
    capture_private_secret_service()
    for handle in private_service_handles.values():
        try:
            try:
                signal.pidfd_send_signal(handle, signal.SIGTERM)
            except ProcessLookupError:
                continue
            with selectors.DefaultSelector() as waiter:
                waiter.register(handle, selectors.EVENT_READ)
                if not waiter.select(3):
                    signal.pidfd_send_signal(handle, signal.SIGKILL)
                    assert waiter.select(3), "Private Secret Service did not exit"
        finally:
            os.close(handle)
    private_service_handles.clear()
sys.path.insert(0, str(ROOT / "bin"))
profile = Path(os.environ["XDG_DATA_HOME"]) / "magnolie-organizer"
profile.mkdir(mode=0o700)
data_file = profile / "daten.json"
data_file.write_text(json.dumps({"version": 6, "notizen": [{"id": "owned-native-fixture", "titel": "Owned fixture",
    "text": "No user data", "html": "No user data"}], "aufgaben": [{"id": "owned-native-series",
    "uid": "owned-native-series-uid", "titel": "Owned series fixture", "startDatum": "2026-01-01",
    "faellig": "2026-01-01", "startZeit": "08:00", "faelligZeit": "09:00", "icsRoundtrip": [
      "BEGIN:VTODO", "UID:owned-native-series-uid", "DTSTART:20260101T080000Z", "DUE:20260101T090000Z",
    "RRULE:FREQ=DAILY", "END:VTODO"]}], "termine": [
    {"id": "owned-readonly-event", "uid": "owned-readonly-event-uid", "datum": "2026-11-15", "titel": "Owned read-only event", "icsReadOnly": True},
    {"id": "owned-provider-event", "uid": "owned-provider-event-uid", "datum": "2026-11-16", "titel": "Owned provider event",
     "sync": True, "syncKalenderUid": "owned-source", "kalenderQuelle": {"id": "owned-source", "name": "Owned source"},
     "syncQuellen": {"owned-source": {"marker": "owned-native"}}, "providerMetadaten": {"fixture": {"marker": "owned-native"}},
     "icsRoundtrip": ["BEGIN:VEVENT", "UID:owned-provider-event-uid", "DTSTART;VALUE=DATE:20261116", "X-OWNED-FIXTURE:preserve", "END:VEVENT"]}
    ], "schichten": [{"id": "owned-cleanup-shift", "name": "Owned cleanup shift", "von": "22:00", "bis": "06:00", "farbe": "#aabbcc", "art": "night"}],
    "zyklusmarker": [{"id": "owned-cleanup-cycle", "name": "Owned cleanup cycle", "symbol": "🌱", "farbe": "#b86f8e", "art": "custom"}],
    "zeiterfassung": {"enabled": False, "actor": "22222222-2222-4222-8222-222222222222", "counter": 1,
        "entries": [{"id": "23232323-2323-4323-8323-232323232323", "startMinute": 30590000, "endMinute": 30590060,
            "pauseMinute": None, "pauseMinutes": 0, "zone": "UTC", "type": "Owned local conflict", "note": "Owned local version",
            "modifiedMs": 1, "deleted": False, "clock": {"22222222-2222-4222-8222-222222222222": 1}, "pausePlan": None}],
        "conflicts": {"23232323-2323-4323-8323-232323232323": [{"id": "23232323-2323-4323-8323-232323232323", "startMinute": 30590000, "endMinute": 30590060,
            "pauseMinute": None, "pauseMinutes": 0, "zone": "UTC", "type": "Owned remote conflict", "note": "Owned competing version",
            "modifiedMs": 1, "deleted": False, "clock": {"33333333-3333-4333-8333-333333333333": 1}, "pausePlan": None}]}}, "einstellungen": {
    "allgemein": {"wiederherstellungsintervall": "manual", "tray": {"aktiv": False}},
    "update": {"automatisch": False}, "sync": {"beimStart": False},
    "ort": {"land": "DE", "region": "DE-BE", "ferien": False, "alleRegionen": False},
    "erinnerung": {"an": False, "wecken": False, "jahrestage": {"an": False}}}}))
loader = importlib.machinery.SourceFileLoader("magnolie_mcp_native_product", str(ROOT / "bin/magnolie-organizer"))
spec = importlib.util.spec_from_loader(loader.name, loader)
product = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = product
loader.exec_module(product)
assert product.GTK_OK and product.WEBKIT_OK
product._REGIONAL = product.regional_einstellungen(dict(product._REGIONAL, timeZone="UTC", language="en", formatLocale="en-GB"))
state = {"started": False, "passed": False, "error": None, "transport_blocked": False, "activation_private": True, "network_isolated": BACKGROUND_PROBE}
def unrelated_transport(*_args, **_kwargs):
    state["transport_blocked"] = True
    raise RuntimeError("Handset transports are unavailable in this native book fixture")
product._kdeconnect_backend = unrelated_transport
product.kdeconnect_sms_stand = lambda *_args, **_kwargs: {
    "available": False, "device_count": 0, "device_id": "", "reason": "isolated_book_fixture", "pairing_state": "idle"}
window = product.Fenster(str(ROOT / "web"))
# This fixture proves the book/MCP/save path, not handset or tree transport.
# Keep unrelated startup transports inactive instead of binding another host listener.
window._telefon_stand_melden = lambda: None
window._telefon_dienst_pflegen = lambda: None
window._baum_dienst_pflegen = lambda: None
window.show_all()
owned = []


def client():
    process = None
    try:
        process = subprocess.Popen([sys.executable, "-B", str(ROOT / "bin/magnolie-organizer"), "--mcp-stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        owned.append(process)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        sequence = 0
        def send(value):
            process.stdin.write(json.dumps(value, ensure_ascii=False).encode() + b"\n")
            process.stdin.flush()
        def call(method, params=None):
            nonlocal sequence
            sequence += 1
            request = {"jsonrpc": "2.0", "id": sequence, "method": method}
            if params is not None:
                request["params"] = params
            send(request)
            assert selector.select(20), "Native MCP response timed out"
            # Read a bounded record without buffered read-ahead across responses.
            frame = bytearray()
            while not frame.endswith(b"\n"):
                block = process.stdout.read(1)
                assert block, "Native MCP process closed stdout"
                frame.extend(block)
                assert len(frame) <= 1024 * 1024
            response = json.loads(frame)
            assert response["id"] == sequence, response
            assert "error" not in response, response
            return response["result"]
        def check_print_dialog(revision, tool="organizer_cards_print", arguments=None):
            print_probe = {"seen": False, "timer_active": True, "deadline": time.monotonic() + 12}
            def cancel_owned_print_dialog():
                for dialog in product.Gtk.Window.list_toplevels():
                    if dialog.__gtype__.name == "GtkPrintUnixDialog" and dialog.get_visible():
                        print_probe["seen"] = True
                        print_probe["timer_active"] = False
                        dialog.response(product.Gtk.ResponseType.CANCEL)
                        return False
                if time.monotonic() > print_probe["deadline"]:
                    print_probe["timer_active"] = False
                    print("Owned print dialog not observed: " + repr([(dialog.__gtype__.name, dialog.get_visible()) for dialog in product.Gtk.Window.list_toplevels()]), flush=True)
                    return False
                return True
            print_timer = product.GLib.timeout_add(50, cancel_owned_print_dialog)
            try:
                printed = call("tools/call", {"name": tool, "arguments": {
                    "expected_book_revision": revision, **(arguments if arguments is not None else {"section": "notes", "ids": ["owned-native-fixture"]})}})
                assert print_probe["seen"] and not printed["isError"], printed
                assert printed["structuredContent"]["stage"] == "dialog_returned" and printed["structuredContent"]["dialog_action"] == "cancel" and printed["structuredContent"]["paper_output_confirmed"] is False, printed
                state["print_dialog_verified"] = True
                state.setdefault("print_dialog_tools", []).append(tool)
            finally:
                if print_probe["timer_active"]:
                    product.GLib.source_remove(print_timer)
        result = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "owned-native-fixture", "version": "1"}})
        assert result["serverInfo"]["name"] == "magnolie-organizer"
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tool_page = call("tools/list")
        tools = list(tool_page["tools"])
        cursors = set()
        while "nextCursor" in tool_page:
            cursor = tool_page["nextCursor"]
            assert cursor not in cursors and len(cursors) < 100
            cursors.add(cursor)
            tool_page = call("tools/list", {"cursor": cursor})
            tools.extend(tool_page["tools"])
        assert cursors, "Native MCP fixture must exercise tool-list pagination"
        assert any(tool["name"] == "organizer_note_create" for tool in tools)
        status = call("tools/call", {"name": "organizer_status"})
        assert status["structuredContent"]["ready"] and not status["structuredContent"]["locked"], status
        notes = call("tools/call", {"name": "organizer_data_read", "arguments": {"section": "notizen"}})
        assert any(note["id"] == "owned-native-fixture" for note in notes["structuredContent"]["entries"])
        if os.environ.get("MAGNOLIE_MCP_PROBE_WASTE_ONLY") == "1":
            waste_path = Path(temporary.name) / "owned-waste.csv"
            waste_path.write_text("Datum;Abfallart;Ort;Notiz;UID\n04.02.2030;Biotonne;Owned point;Owned note;owned-bio\n05.02.2030;Papier;Owned point;;owned-paper\n", encoding="utf-8")
            waste_csv = {"has_header": True, "date_column": 0, "type_column": 1, "location_column": 2, "note_column": 3, "uid_column": 4, "date_format": "dot"}
            waste_preview = call("tools/call", {"name": "organizer_waste_import_preview", "arguments": {"path": str(waste_path), "csv": waste_csv}})
            assert not waste_preview["isError"] and len(waste_preview["structuredContent"]["groups"]) == 2, waste_preview
            preview_data = waste_preview["structuredContent"]
            organic = next(group for group in preview_data["groups"] if group["kind"] == "organic")
            ordinary_before = call("tools/call", {"name": "organizer_data_read", "arguments": {"section": "termine"}})["structuredContent"]["entries"]
            def apply_waste(preview, target, mapping, choices):
                arguments = {"path": str(target), "expected_revision": preview["revision"], "expected_book_revision": preview["book_revision"], "expected_mapping_revision": preview["mapping_revision"], "groups": choices}
                if mapping is not None: arguments["csv"] = mapping
                return call("tools/call", {"name": "organizer_waste_import_apply", "arguments": arguments})
            waste_choices = [{"type": organic["type"], "name": "Owned organic", "kind": "organic", "color": "#aabbcc"}]
            waste_applied = apply_waste(preview_data, waste_path, waste_csv, waste_choices)
            assert not waste_applied["isError"] and waste_applied["structuredContent"]["persisted"] and waste_applied["structuredContent"]["recovery_snapshot_confirmed"], waste_applied
            durable_waste = json.loads(data_file.read_text())
            assert durable_waste["termine"] == ordinary_before
            waste_group = next(group for group in durable_waste["muelltermine"] if group["id"] == waste_applied["structuredContent"]["group_ids"][0])
            assert waste_group["name"] == "Owned organic" and waste_group["farbe"] == "#aabbcc" and len(waste_group["importierteTermine"]) == 1
            assert waste_group["importierteTermine"][0]["notiz"] == "Owned note"
            waste_event_id = waste_group["importierteTermine"][0]["id"]
            replay_preview = call("tools/call", {"name": "organizer_waste_import_preview", "arguments": {"path": str(waste_path), "csv": waste_csv}})["structuredContent"]
            replayed = apply_waste(replay_preview, waste_path, waste_csv, waste_choices)
            assert not replayed["isError"], replayed
            assert json.loads(data_file.read_text())["muelltermine"] == durable_waste["muelltermine"]
            waste_path.write_text(waste_path.read_text().replace("04.02.2030", "06.02.2030"), encoding="utf-8")
            stale_waste = apply_waste(replay_preview, waste_path, waste_csv, waste_choices)
            assert stale_waste["isError"] and stale_waste["structuredContent"]["code"] == "conflict", stale_waste
            changed_preview = call("tools/call", {"name": "organizer_waste_import_preview", "arguments": {"path": str(waste_path), "csv": waste_csv}})["structuredContent"]
            changed_waste = apply_waste(changed_preview, waste_path, waste_csv, waste_choices)
            assert not changed_waste["isError"], changed_waste
            changed_group = next(group for group in json.loads(data_file.read_text())["muelltermine"] if group["id"] == waste_group["id"])
            assert len(changed_group["importierteTermine"]) == 1 and changed_group["importierteTermine"][0]["id"] == waste_event_id and changed_group["importierteTermine"][0]["datum"] == "2030-02-06"
            waste_ics_path = Path(temporary.name) / "owned-waste.ics"
            waste_ics_path.write_text(json.loads((ROOT.parent / "contracts/waste-calendar-v1.json").read_text())["ics"], encoding="utf-8")
            ics_preview = call("tools/call", {"name": "organizer_waste_import_preview", "arguments": {"path": str(waste_ics_path)}})
            assert not ics_preview["isError"], ics_preview
            ics_data = ics_preview["structuredContent"]
            assert sum(group["count"] for group in ics_data["groups"]) == 7
            ics_applied = apply_waste(ics_data, waste_ics_path, None, [{"type": group["type"]} for group in ics_data["groups"]])
            assert not ics_applied["isError"] and ics_applied["structuredContent"]["persisted"], ics_applied
            stored_waste = json.loads(data_file.read_text())
            assert stored_waste["termine"] == ordinary_before and sum(len(group.get("importierteTermine", [])) for group in stored_waste["muelltermine"]) == 8
            state["waste_import_verified"] = True
            process.stdin.close()
            assert process.wait(timeout=5) == 0
            selector.close()
            state["passed"] = True
            return
        if os.environ.get("MAGNOLIE_MCP_PROBE_PRINT_ONLY") == "1":
            print_revision = call("tools/call", {"name": "organizer_book_revision_read"})["structuredContent"]["revision"]
            check_print_dialog(print_revision)
            for print_tool, print_options in (
                    ("organizer_cards_print", {"section": "appointments", "year": 2026, "month": 11, "ids": ["owned-readonly-event"]}),
                    ("organizer_planner_print", {"year": 2030, "layout": "year"}),
                    ("organizer_planner_print", {"year": 2030, "layout": "month", "month": 2}),
                    ("organizer_health_print", {"table": "vital", "mode": "blank"}),
                    ("organizer_time_print", {"year": 2030, "month": 2, "days": [1, 4]})):
                check_print_dialog(print_revision, print_tool, print_options)
            assert call("tools/call", {"name": "organizer_book_revision_read"})["structuredContent"]["revision"] == print_revision
            process.stdin.close()
            assert process.wait(timeout=5) == 0
            selector.close()
            state["passed"] = True
            return
        note_id = "44444444-4444-4444-8444-444444444444"
        created = call("tools/call", {"name": "organizer_note_create", "arguments": {
            "id": note_id, "title": "Native MCP fixture", "text": "<script>not executable</script>\nOwned fixture"}})
        assert created["isError"] is False and created["structuredContent"]["persisted"] is True, created
        durable = json.loads(data_file.read_text())
        note = next(item for item in durable["notizen"] if item["id"] == note_id)
        assert note["titel"] == "Native MCP fixture" and "<script>" not in note["html"]
        reread = call("tools/call", {"name": "organizer_data_read", "arguments": {"section": "notizen", "id": note_id}})
        assert reread["structuredContent"]["entry"]["text"] == note["text"]
        duplicate = call("tools/call", {"name": "organizer_note_create", "arguments": {
            "id": note_id, "title": "Retry", "text": "Do not duplicate"}})
        assert duplicate["isError"] is True and duplicate["structuredContent"]["code"] == "already_exists"
        assert len([item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id]) == 1
        revision = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id}})
        assert revision["isError"] is False, revision
        updated = call("tools/call", {"name": "organizer_note_update", "arguments": {"id": note_id,
            "expected_revision": revision["structuredContent"]["revision"], "title": "Native revised fixture"}})
        assert updated["isError"] is False and updated["structuredContent"]["persisted"], updated
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["titel"] == "Native revised fixture"
        def png_chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + png_chunk(b"IDAT", zlib.compress(b"\0\0\0\0\xff")) + png_chunk(b"IEND", b"")
        attachment_note = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id, "fields": ["id"]}})
        staged = call("tools/call", {"name": "organizer_attachment_upload_begin", "arguments": {
            "note_id": note_id, "expected_revision": attachment_note["structuredContent"]["revision"],
            "name": "owned-native-fixture.png", "kind": "image", "size": len(png), "sha256": hashlib.sha256(png).hexdigest()}})
        assert not staged["isError"], staged
        upload_token = staged["structuredContent"]["token"]
        split = 17
        for offset, chunk in [(0, png[:split]), (split, png[split:])]:
            appended = call("tools/call", {"name": "organizer_attachment_upload_append", "arguments": {
                "token": upload_token, "offset": offset, "data": base64.b64encode(chunk).decode()}})
            assert not appended["isError"], appended
        attached = call("tools/call", {"name": "organizer_attachment_upload_finalize", "arguments": {"token": upload_token}})
        assert not attached["isError"] and attached["structuredContent"]["persisted"], attached
        attachment_id = attached["structuredContent"]["attachment_id"]
        embedded = next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["anhaenge"]
        assert base64.b64decode(next(item for item in embedded if item["id"] == attachment_id)["daten"].split(",", 1)[1]) == png
        attachment_note = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id, "fields": ["id"]}})
        attachment_save_path = Path(temporary.name) / "owned-saved-attachment.png"
        attachment_save_args = {"note_id": note_id, "attachment_id": attachment_id,
            "expected_revision": attachment_note["structuredContent"]["revision"], "path": str(attachment_save_path)}
        attachment_saved = call("tools/call", {"name": "organizer_attachment_save", "arguments": attachment_save_args})
        assert not attachment_saved["isError"] and attachment_saved["structuredContent"]["confirmed"], attachment_saved
        assert attachment_save_path.read_bytes() == png and attachment_saved["structuredContent"]["sha256"] == hashlib.sha256(png).hexdigest()
        attachment_existing = call("tools/call", {"name": "organizer_attachment_save", "arguments": attachment_save_args})
        assert attachment_existing["isError"] and attachment_save_path.read_bytes() == png, attachment_existing
        attachment_overwritten = call("tools/call", {"name": "organizer_attachment_save", "arguments": {**attachment_save_args, "overwrite": True}})
        assert not attachment_overwritten["isError"] and attachment_save_path.read_bytes() == png, attachment_overwritten
        attachment_profile_before = data_file.read_bytes()
        attachment_profile = call("tools/call", {"name": "organizer_attachment_save", "arguments": {**attachment_save_args, "path": str(data_file), "overwrite": True}})
        assert attachment_profile["isError"] and data_file.read_bytes() == attachment_profile_before, attachment_profile
        attachment_link = Path(temporary.name) / "owned-saved-link.png"
        attachment_link.symlink_to(attachment_save_path)
        attachment_link_result = call("tools/call", {"name": "organizer_attachment_save", "arguments": {**attachment_save_args, "path": str(attachment_link), "overwrite": True}})
        assert attachment_link_result["isError"] and attachment_link.is_symlink() and attachment_save_path.read_bytes() == png, attachment_link_result
        attachment_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        attachment_socket = str(Path(temporary.name) / "owned-attachment.sock")
        attachment_listener.bind(attachment_socket)
        attachment_listener.listen(1)
        attachment_listener.settimeout(5)
        own_viewer = Path(temporary.name) / "owned-attachment-viewer.py"
        own_viewer.write_text("import hashlib, socket, sys\nfrom pathlib import Path\n"
            "with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:\n"
            "    connection.connect(" + repr(attachment_socket) + ")\n"
            "    connection.sendall(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest().encode())\n")
        own_apps = Path(os.environ["XDG_DATA_HOME"]) / "applications"
        own_apps.mkdir(exist_ok=True)
        (own_apps / "owned-attachment-viewer.desktop").write_text(
            '[Desktop Entry]\nType=Application\nName=Owned attachment viewer\n'
            'Exec="' + sys.executable + '" "' + str(own_viewer) + '" %f\nTerminal=false\nMimeType=image/png;\n')
        (Path(os.environ["XDG_CONFIG_HOME"]) / "mimeapps.list").write_text(
            "[Default Applications]\nimage/png=owned-attachment-viewer.desktop;\n")
        previous_desktop = os.environ.get("XDG_CURRENT_DESKTOP")
        os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
        try:
            attachment_opened = call("tools/call", {"name": "organizer_attachment_open", "arguments": {
                "note_id": note_id, "attachment_id": attachment_id, "expected_revision": attachment_note["structuredContent"]["revision"]}})
            assert not attachment_opened["isError"] and attachment_opened["structuredContent"]["launched"], attachment_opened
            connection, _address = attachment_listener.accept()
            with connection:
                connection.settimeout(3)
                assert connection.recv(128).decode() == hashlib.sha256(png).hexdigest(), "Registered own viewer received different attachment bytes"
        finally:
            attachment_listener.close()
            if previous_desktop is None:
                os.environ.pop("XDG_CURRENT_DESKTOP", None)
            else:
                os.environ["XDG_CURRENT_DESKTOP"] = previous_desktop
        removed_attachment = call("tools/call", {"name": "organizer_attachment_remove", "arguments": {
            "note_id": note_id, "attachment_id": attachment_id, "expected_revision": attachment_note["structuredContent"]["revision"]}})
        assert not removed_attachment["isError"] and removed_attachment["structuredContent"]["persisted"], removed_attachment
        attachment_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {"id": removed_attachment["structuredContent"]["trash_id"]}})
        assert not attachment_restored["isError"] and attachment_restored["structuredContent"]["persisted"], attachment_restored
        assert any(item["id"] == attachment_id for item in next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["anhaenge"])
        task_id = "77777777-7777-4777-8777-777777777777"
        task_created = call("tools/call", {"name": "organizer_task_create", "arguments": {
            "id": task_id, "title": "Native task fixture", "priority": 1, "due_date": "2026-11-10"}})
        assert not task_created["isError"] and task_created["structuredContent"]["persisted"], task_created
        task = next(item for item in json.loads(data_file.read_text())["aufgaben"] if item["id"] == task_id)
        assert task["prio"] == 1 and task["faellig"] == "2026-11-10"
        task_read = call("tools/call", {"name": "organizer_task_read", "arguments": {"id": task_id}})
        task_updated = call("tools/call", {"name": "organizer_task_update", "arguments": {"id": task_id,
            "expected_revision": task_read["structuredContent"]["revision"], "title": "Native revised task"}})
        assert not task_updated["isError"] and task_updated["structuredContent"]["persisted"], task_updated
        assert next(item for item in json.loads(data_file.read_text())["aufgaben"] if item["id"] == task_id)["titel"] == "Native revised task"
        person_created = call("tools/call", {"name": "organizer_person_create", "arguments": {"name": "Owned native person"}})
        assert not person_created["isError"] and person_created["structuredContent"]["persisted"], person_created
        person_id = person_created["structuredContent"]["id"]
        person_read = call("tools/call", {"name": "organizer_person_read", "arguments": {"id": person_id}})
        person_updated = call("tools/call", {"name": "organizer_person_update", "arguments": {
            "id": person_id, "expected_revision": person_read["structuredContent"]["revision"], "name": "Revised native person", "abbreviation": "RN"}})
        assert not person_updated["isError"] and person_updated["structuredContent"]["persisted"], person_updated
        task_read = call("tools/call", {"name": "organizer_task_read", "arguments": {"id": task_id}})
        task_assigned = call("tools/call", {"name": "organizer_task_update", "arguments": {
            "id": task_id, "expected_revision": task_read["structuredContent"]["revision"], "persons": [person_id]}})
        assert not task_assigned["isError"] and task_assigned["structuredContent"]["persisted"], task_assigned
        person_read = call("tools/call", {"name": "organizer_person_read", "arguments": {"id": person_id}})
        person_deleted = call("tools/call", {"name": "organizer_person_delete", "arguments": {
            "id": person_id, "expected_revision": person_read["structuredContent"]["revision"]}})
        assert not person_deleted["isError"] and person_deleted["structuredContent"]["persisted"], person_deleted
        assert task_id in person_deleted["structuredContent"]["unassigned_tasks"]
        assert next(item for item in json.loads(data_file.read_text())["aufgaben"] if item["id"] == task_id)["personen"] == []
        child_id = "88888888-8888-4888-8888-888888888888"
        child_created = call("tools/call", {"name": "organizer_task_create", "arguments": {
            "id": child_id, "title": "Native child fixture", "parent_id": task_id}})
        assert not child_created["isError"] and child_created["structuredContent"]["persisted"], child_created
        task_read = call("tools/call", {"name": "organizer_task_read", "arguments": {"id": task_id}})
        task_deleted = call("tools/call", {"name": "organizer_task_delete", "arguments": {
            "id": task_id, "expected_revision": task_read["structuredContent"]["revision"]}})
        assert not task_deleted["isError"] and task_deleted["structuredContent"]["persisted"], task_deleted
        durable = json.loads(data_file.read_text())["aufgaben"]
        assert not any(item["id"] == task_id for item in durable)
        assert next(item for item in durable if item["id"] == child_id)["elternUid"] == ""
        task_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {
            "id": task_deleted["structuredContent"]["trash_id"]}})
        assert not task_restored["isError"] and task_restored["structuredContent"]["persisted"], task_restored
        series = call("tools/call", {"name": "organizer_task_read", "arguments": {"id": "owned-native-series"}})
        series_done = call("tools/call", {"name": "organizer_task_set_completed", "arguments": {
            "id": "owned-native-series", "expected_revision": series["structuredContent"]["revision"],
            "completed": True, "as_of": "2026-01-02"}})
        assert not series_done["isError"] and series_done["structuredContent"]["persisted"], series_done
        assert series_done["structuredContent"]["recurring"] is True
        durable = json.loads(data_file.read_text())["aufgaben"]
        master = next(item for item in durable if item["id"] == "owned-native-series")
        instance = next(item for item in durable if item["id"] == series_done["structuredContent"]["completed_id"])
        assert master["erledigt"] is False and instance["erledigt"] is True
        rid = next(line for line in instance["icsRoundtrip"] if line.startswith("RECURRENCE-ID"))
        canonical = json.dumps([{"VALUE": "DATE"} if ";VALUE=DATE:" in rid else {}, rid.rsplit(":", 1)[1]], separators=(",", ":"))
        assert instance["uid"] == master["uid"] + "-magnolie-instanz-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
        assert rid.replace("RECURRENCE-ID", "EXDATE") in master["icsRoundtrip"]
        instance_read = call("tools/call", {"name": "organizer_task_read", "arguments": {"id": instance["id"]}})
        reopened = call("tools/call", {"name": "organizer_task_set_completed", "arguments": {
            "id": instance["id"], "expected_revision": instance_read["structuredContent"]["revision"], "completed": False}})
        assert not reopened["isError"] and reopened["structuredContent"]["persisted"], reopened
        assert next(item for item in json.loads(data_file.read_text())["aufgaben"] if item["id"] == instance["id"])["erledigt"] is False
        appointment_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        appointment_created = call("tools/call", {"name": "organizer_appointment_create", "arguments": {
            "id": appointment_id, "title": "Native appointment fixture", "start_date": "2026-12-10", "start_time": "09:00", "end_time": "10:00",
            "location": "Owned fixture room", "recurrence": {"frequency": "weekly", "interval": 2}, "alarms": [{"offset_minutes": 15}]}})
        assert not appointment_created["isError"] and appointment_created["structuredContent"]["persisted"], appointment_created
        event = next(item for item in json.loads(data_file.read_text())["termine"] if item["id"] == appointment_id)
        assert event["zeit"] == "09:00" and event["wiederholung"]["intervall"] == 2
        appointment = call("tools/call", {"name": "organizer_appointment_read", "arguments": {"id": appointment_id}})
        appointment_updated = call("tools/call", {"name": "organizer_appointment_update", "arguments": {
            "id": appointment_id, "expected_revision": appointment["structuredContent"]["revision"], "start_time": "10:00", "end_time": "11:00"}})
        assert not appointment_updated["isError"] and appointment_updated["structuredContent"]["persisted"], appointment_updated
        assert next(item for item in json.loads(data_file.read_text())["termine"] if item["id"] == appointment_id)["zeit"] == "10:00"
        readonly = call("tools/call", {"name": "organizer_appointment_read", "arguments": {"id": "owned-readonly-event"}})
        readonly_deleted = call("tools/call", {"name": "organizer_appointment_delete", "arguments": {
            "id": "owned-readonly-event", "expected_revision": readonly["structuredContent"]["revision"]}})
        assert readonly_deleted["isError"] and readonly_deleted["structuredContent"]["code"] == "read_only", readonly_deleted
        provider = call("tools/call", {"name": "organizer_appointment_read", "arguments": {"id": "owned-provider-event"}})
        provider_moved = call("tools/call", {"name": "organizer_appointment_update", "arguments": {
            "id": "owned-provider-event", "expected_revision": provider["structuredContent"]["revision"], "calendar_uid": ""}})
        assert not provider_moved["isError"] and provider_moved["structuredContent"]["persisted"], provider_moved
        durable = json.loads(data_file.read_text())
        moved = next(item for item in durable["termine"] if item["id"] == "owned-provider-event")
        assert moved["syncKalenderUid"] == "" and "owned-source" not in moved["syncQuellen"]
        assert moved["providerMetadaten"]["fixture"]["marker"] == "owned-native" and "X-OWNED-FIXTURE:preserve" in moved["icsRoundtrip"]
        assert any(item["uid"] == "owned-provider-event-uid" and item["syncKalenderUid"] == "owned-source" for item in durable["geloescht"]["termine"])
        appointment = call("tools/call", {"name": "organizer_appointment_read", "arguments": {"id": appointment_id}})
        appointment_deleted = call("tools/call", {"name": "organizer_appointment_delete", "arguments": {
            "id": appointment_id, "expected_revision": appointment["structuredContent"]["revision"]}})
        assert not appointment_deleted["isError"] and appointment_deleted["structuredContent"]["persisted"], appointment_deleted
        appointment_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {
            "id": appointment_deleted["structuredContent"]["trash_id"]}})
        assert not appointment_restored["isError"] and appointment_restored["structuredContent"]["persisted"], appointment_restored
        assert any(item["id"] == appointment_id for item in json.loads(data_file.read_text())["termine"])
        contact_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        contact_created = call("tools/call", {"name": "organizer_contact_create", "arguments": {
            "id": contact_id, "first_name": "Owned", "last_name": "Native contact", "birth_date": "--02-29",
            "emails": [{"value": "owned-native@example.test"}], "phones": [{"value": "+12025550123", "types": ["CELL"]}],
            "addresses": [{"street": "Owned fixture street", "city": "Fixture town", "country": "US"}], "groups": ["Owned fixture group"]}})
        assert not contact_created["isError"] and contact_created["structuredContent"]["persisted"], contact_created
        contact = next(item for item in json.loads(data_file.read_text())["kontakte"] if item["id"] == contact_id)
        assert contact["email"] == "owned-native@example.test" and contact["geburtstag"] == "--02-29"
        anniversary_created = call("tools/call", {"name": "organizer_anniversary_create", "arguments": {
            "name": "Owned native anniversary", "date": "--12-31", "type": "other"}})
        assert not anniversary_created["isError"] and anniversary_created["structuredContent"]["persisted"], anniversary_created
        anniversary_id = anniversary_created["structuredContent"]["id"]
        anniversary_read = call("tools/call", {"name": "organizer_anniversary_read", "arguments": {"id": anniversary_id}})
        anniversary_updated = call("tools/call", {"name": "organizer_anniversary_update", "arguments": {
            "id": anniversary_id, "expected_revision": anniversary_read["structuredContent"]["revision"], "date": "--01-01"}})
        assert not anniversary_updated["isError"] and anniversary_updated["structuredContent"]["persisted"], anniversary_updated
        anniversary_read = call("tools/call", {"name": "organizer_anniversary_read", "arguments": {"id": anniversary_id}})
        anniversary_deleted = call("tools/call", {"name": "organizer_anniversary_delete", "arguments": {
            "id": anniversary_id, "expected_revision": anniversary_read["structuredContent"]["revision"]}})
        assert not anniversary_deleted["isError"] and anniversary_deleted["structuredContent"]["persisted"], anniversary_deleted
        anniversary_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {"id": anniversary_deleted["structuredContent"]["trash_id"]}})
        assert not anniversary_restored["isError"] and anniversary_restored["structuredContent"]["persisted"], anniversary_restored
        vacation_created = call("tools/call", {"name": "organizer_vacation_create", "arguments": {
            "from": "2028-02-29", "through": "2028-03-02", "symbol": "snowman"}})
        assert not vacation_created["isError"] and vacation_created["structuredContent"]["persisted"], vacation_created
        vacation_id = vacation_created["structuredContent"]["id"]
        vacation_read = call("tools/call", {"name": "organizer_vacation_read", "arguments": {"id": vacation_id}})
        vacation_updated = call("tools/call", {"name": "organizer_vacation_update", "arguments": {
            "id": vacation_id, "expected_revision": vacation_read["structuredContent"]["revision"], "through": "2028-03-03", "display": "symbol"}})
        assert not vacation_updated["isError"] and vacation_updated["structuredContent"]["persisted"], vacation_updated
        vacation = next(item for item in json.loads(data_file.read_text())["urlaube"] if item["id"] == vacation_id)
        assert vacation["bis"] == "2028-03-03" and vacation["darstellung"] == "symbol" and vacation["symbol"] == "snowman"
        vacation_read = call("tools/call", {"name": "organizer_vacation_read", "arguments": {"id": vacation_id}})
        vacation_deleted = call("tools/call", {"name": "organizer_vacation_delete", "arguments": {
            "id": vacation_id, "expected_revision": vacation_read["structuredContent"]["revision"]}})
        assert not vacation_deleted["isError"] and vacation_deleted["structuredContent"]["persisted"], vacation_deleted
        assert not any(item["id"] == vacation_id for item in json.loads(data_file.read_text())["urlaube"])
        waste = call("tools/call", {"name": "organizer_waste_create", "arguments": {
            "name": "Owned native collection", "first_date": "2028-02-29", "interval_days": 14}})
        assert not waste["isError"] and waste["structuredContent"]["persisted"], waste
        waste_id = waste["structuredContent"]["id"]
        waste_read = call("tools/call", {"name": "organizer_waste_read", "arguments": {"id": waste_id}})
        waste_updated = call("tools/call", {"name": "organizer_waste_update", "arguments": {
            "id": waste_id, "expected_revision": waste_read["structuredContent"]["revision"], "interval_days": 0, "color": "#aabbcc"}})
        assert not waste_updated["isError"] and waste_updated["structuredContent"]["persisted"], waste_updated
        waste_value = next(item for item in json.loads(data_file.read_text())["muelltermine"] if item["id"] == waste_id)
        assert waste_value["intervallTage"] == 0 and waste_value["farbe"] == "#aabbcc", waste_value
        waste_read = call("tools/call", {"name": "organizer_waste_read", "arguments": {"id": waste_id}})
        waste_deleted = call("tools/call", {"name": "organizer_waste_delete", "arguments": {
            "id": waste_id, "expected_revision": waste_read["structuredContent"]["revision"]}})
        assert not waste_deleted["isError"] and waste_deleted["structuredContent"]["persisted"], waste_deleted
        assert not any(item["id"] == waste_id for item in json.loads(data_file.read_text())["muelltermine"])
        for kind, key, values in (("vital", "vitalwerte", {"pulse": 72, "weight_kg": 70}),
                                  ("blood_glucose", "blutzucker", {"value": 108, "unit": "mg/dL"})):
            health_created = call("tools/call", {"name": f"organizer_{kind}_create", "arguments": {"date": "2028-02-29", "page": 2, **values}})
            assert not health_created["isError"] and health_created["structuredContent"]["persisted"], health_created
            health_id = health_created["structuredContent"]["id"]
            health_read = call("tools/call", {"name": f"organizer_{kind}_read", "arguments": {"id": health_id}})
            health_updated = call("tools/call", {"name": f"organizer_{kind}_update", "arguments": {
                "id": health_id, "expected_revision": health_read["structuredContent"]["revision"],
                **({"pulse": 80} if kind == "vital" else {"unit": "mmol/L"})}})
            assert not health_updated["isError"] and health_updated["structuredContent"]["persisted"], health_updated
            health_value = next(item for item in json.loads(data_file.read_text())["gesundheit"][key] if item["id"] == health_id)
            assert health_value["seite"] == 2 and (health_value["puls"] == 80 if kind == "vital" else health_value["wert"] == 6 and health_value["einheit"] == "mmol/L"), health_value
            health_read = call("tools/call", {"name": f"organizer_{kind}_read", "arguments": {"id": health_id}})
            health_deleted = call("tools/call", {"name": f"organizer_{kind}_delete", "arguments": {
                "id": health_id, "expected_revision": health_read["structuredContent"]["revision"]}})
            assert not health_deleted["isError"] and health_deleted["structuredContent"]["persisted"], health_deleted
            assert not any(item["id"] == health_id for item in json.loads(data_file.read_text())["gesundheit"][key])
        medication = call("tools/call", {"name": "organizer_medication_create", "arguments": {
            "name": "Owned synthetic medication", "weekdays": [1, 3], "weekly_plan": [{"day": 1, "morning": "fixture"}]}})
        assert not medication["isError"] and medication["structuredContent"]["persisted"], medication
        medication_id = medication["structuredContent"]["id"]
        medication_read = call("tools/call", {"name": "organizer_medication_read", "arguments": {"id": medication_id}})
        medication_updated = call("tools/call", {"name": "organizer_medication_update", "arguments": {
            "id": medication_id, "expected_revision": medication_read["structuredContent"]["revision"], "active": False}})
        assert not medication_updated["isError"] and medication_updated["structuredContent"]["persisted"], medication_updated
        medication_value = next(item for item in json.loads(data_file.read_text())["gesundheit"]["medikamente"] if item["id"] == medication_id)
        assert not medication_value["aktiv"] and medication_value["wochenplan"][0]["morgens"] == "fixture", medication_value
        medication_read = call("tools/call", {"name": "organizer_medication_read", "arguments": {"id": medication_id}})
        medication_deleted = call("tools/call", {"name": "organizer_medication_delete", "arguments": {
            "id": medication_id, "expected_revision": medication_read["structuredContent"]["revision"]}})
        assert not medication_deleted["isError"] and medication_deleted["structuredContent"]["persisted"], medication_deleted
        assert not any(item["id"] == medication_id for item in json.loads(data_file.read_text())["gesundheit"]["medikamente"])
        scheme = call("tools/call", {"name": "organizer_insulin_scheme_read"})
        scheme_updated = call("tools/call", {"name": "organizer_insulin_scheme_update", "arguments": {
            "expected_revision": scheme["structuredContent"]["revision"], "changes": {"hinweis": "Owned native scheme fixture"}}})
        assert not scheme_updated["isError"] and scheme_updated["structuredContent"]["persisted"], scheme_updated
        assert json.loads(data_file.read_text())["gesundheit"]["insulinschema"]["hinweis"] == "Owned native scheme fixture"
        time_settings = call("tools/call", {"name": "organizer_time_settings_read"})
        time_settings_updated = call("tools/call", {"name": "organizer_time_settings_update", "arguments": {
            "expected_revision": time_settings["structuredContent"]["revision"], "enabled": True, "report_name": "Owned native report"}})
        assert not time_settings_updated["isError"] and time_settings_updated["structuredContent"]["persisted"], time_settings_updated
        assert json.loads(data_file.read_text())["zeiterfassung"]["enabled"]
        time_created = call("tools/call", {"name": "organizer_time_record_create", "arguments": {
            "start_minute": 30590880, "end_minute": 30590940, "pause_minutes": 15, "zone": "UTC", "type": "Owned native manual time"}})
        assert not time_created["isError"] and time_created["structuredContent"]["persisted"], time_created
        time_id = time_created["structuredContent"]["id"]
        time_read = call("tools/call", {"name": "organizer_time_record_read", "arguments": {"id": time_id}})
        time_updated = call("tools/call", {"name": "organizer_time_record_update", "arguments": {
            "id": time_id, "expected_revision": time_read["structuredContent"]["revision"], "note": "Owned native time revision"}})
        assert not time_updated["isError"] and time_updated["structuredContent"]["persisted"], time_updated
        time_data = json.loads(data_file.read_text())["zeiterfassung"]
        time_value = next(item for item in time_data["entries"] if item["id"] == time_id)
        assert time_value["clock"][time_data["actor"]] == time_read["structuredContent"]["record"]["clock"][time_data["actor"]] + 1 and time_value["pauseMinutes"] == 15 and time_value["note"] == "Owned native time revision", time_value
        time_read = call("tools/call", {"name": "organizer_time_record_read", "arguments": {"id": time_id}})
        time_deleted = call("tools/call", {"name": "organizer_time_record_delete", "arguments": {
            "id": time_id, "expected_revision": time_read["structuredContent"]["revision"]}})
        assert not time_deleted["isError"] and time_deleted["structuredContent"]["persisted"], time_deleted
        assert next(item for item in json.loads(data_file.read_text())["zeiterfassung"]["entries"] if item["id"] == time_id)["deleted"]
        time_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {"id": time_deleted["structuredContent"]["trash_id"]}})
        assert not time_restored["isError"] and time_restored["structuredContent"]["persisted"], time_restored
        time_conflict = call("tools/call", {"name": "organizer_time_conflict_read", "arguments": {"id": "23232323-2323-4323-8323-232323232323"}})
        time_resolved = call("tools/call", {"name": "organizer_time_conflict_resolve", "arguments": {
            "id": "23232323-2323-4323-8323-232323232323", "expected_revision": time_conflict["structuredContent"]["revision"], "choice": 1}})
        assert not time_resolved["isError"] and time_resolved["structuredContent"]["persisted"], time_resolved
        resolved_data = json.loads(data_file.read_text())["zeiterfassung"]
        resolved_time = next(item for item in resolved_data["entries"] if item["id"] == "23232323-2323-4323-8323-232323232323")
        assert resolved_time["note"] == "Owned competing version" and resolved_time["clock"]["33333333-3333-4333-8333-333333333333"] == 1
        assert "23232323-2323-4323-8323-232323232323" not in resolved_data["conflicts"]
        custom_created = call("tools/call", {"name": "organizer_custom_module_create", "arguments": {
            "type": "notes", "page": "left", "title": "Owned native custom block", "lines": "on"}})
        assert not custom_created["isError"] and custom_created["structuredContent"]["persisted"], custom_created
        custom_id = custom_created["structuredContent"]["id"]
        custom_read = call("tools/call", {"name": "organizer_custom_module_read", "arguments": {"id": custom_id}})
        custom_updated = call("tools/call", {"name": "organizer_custom_module_update", "arguments": {
            "id": custom_id, "expected_revision": custom_read["structuredContent"]["revision"], "title": "Updated native custom block", "lines": "off"}})
        assert not custom_updated["isError"] and custom_updated["structuredContent"]["persisted"], custom_updated
        assert next(module for module in json.loads(data_file.read_text())["customOrganizer"]["modules"] if module["id"] == custom_id)["lines"] == "off"
        custom_read = call("tools/call", {"name": "organizer_custom_module_read", "arguments": {"id": custom_id}})
        custom_deleted = call("tools/call", {"name": "organizer_custom_module_delete", "arguments": {
            "id": custom_id, "expected_revision": custom_read["structuredContent"]["revision"]}})
        assert not custom_deleted["isError"] and custom_deleted["structuredContent"]["persisted"], custom_deleted
        assert not any(module["id"] == custom_id for module in json.loads(data_file.read_text())["customOrganizer"]["modules"])
        custom_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {"id": custom_deleted["structuredContent"]["trash_id"]}})
        assert not custom_restored["isError"] and custom_restored["structuredContent"]["persisted"], custom_restored
        custom_item_created = call("tools/call", {"name": "organizer_custom_item_create", "arguments": {
            "module_id": custom_id, "title": "Owned native text item", "html": "<p>Owned text</p><script>bad()</script>"}})
        assert not custom_item_created["isError"] and custom_item_created["structuredContent"]["persisted"], custom_item_created
        custom_item_id = custom_item_created["structuredContent"]["id"]
        custom_item_read = call("tools/call", {"name": "organizer_custom_item_read", "arguments": {"module_id": custom_id, "id": custom_item_id}})
        assert "script" not in custom_item_read["structuredContent"]["item"]["html"]
        custom_item_updated = call("tools/call", {"name": "organizer_custom_item_update", "arguments": {
            "module_id": custom_id, "id": custom_item_id, "expected_revision": custom_item_read["structuredContent"]["revision"], "text": "Revised native custom text"}})
        assert not custom_item_updated["isError"] and custom_item_updated["structuredContent"]["persisted"], custom_item_updated
        custom_module = next(module for module in json.loads(data_file.read_text())["customOrganizer"]["modules"] if module["id"] == custom_id)
        assert next(item for item in custom_module["items"] if item["id"] == custom_item_id)["text"] == "Revised native custom text"
        custom_item_read = call("tools/call", {"name": "organizer_custom_item_read", "arguments": {"module_id": custom_id, "id": custom_item_id}})
        custom_item_deleted = call("tools/call", {"name": "organizer_custom_item_delete", "arguments": {
            "module_id": custom_id, "id": custom_item_id, "expected_revision": custom_item_read["structuredContent"]["revision"]}})
        assert not custom_item_deleted["isError"] and custom_item_deleted["structuredContent"]["persisted"], custom_item_deleted
        custom_item_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {"id": custom_item_deleted["structuredContent"]["trash_id"]}})
        assert not custom_item_restored["isError"] and custom_item_restored["structuredContent"]["persisted"], custom_item_restored
        drawing_created = call("tools/call", {"name": "organizer_custom_module_create", "arguments": {"type": "drawing"}})
        assert not drawing_created["isError"] and drawing_created["structuredContent"]["persisted"], drawing_created
        drawing_id = drawing_created["structuredContent"]["id"]
        drawing_read = call("tools/call", {"name": "organizer_drawing_read", "arguments": {"id": drawing_id, "limit": 7}})
        sheet = {"version": 4, "width": 400, "height": 300, "autoSize": False, "background": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            "strokes": [{"tool": "pen", "color": "#123456", "width": 2, "points": [[0.1, 0.2, 0.3], [0.8, 0.9, 1]]}]}
        drawing_updated = call("tools/call", {"name": "organizer_drawing_replace", "arguments": {
            "id": drawing_id, "expected_revision": drawing_read["structuredContent"]["revision"], "sheet": sheet}})
        assert not drawing_updated["isError"] and drawing_updated["structuredContent"]["persisted"], drawing_updated
        assert next(module for module in json.loads(data_file.read_text())["customOrganizer"]["modules"] if module["id"] == drawing_id)["drawing"] == sheet
        drawing_read = call("tools/call", {"name": "organizer_drawing_read", "arguments": {"id": drawing_id}})
        assert json.loads(base64.b64decode(drawing_read["structuredContent"]["data"])) == sheet
        bad_background = call("tools/call", {"name": "organizer_drawing_replace", "arguments": {
            "id": drawing_id, "expected_revision": drawing_read["structuredContent"]["revision"],
            "sheet": {**sheet, "background": "data:image/png;base64," + base64.b64encode(png[:33] + b"invalid").decode("ascii")}}})
        assert bad_background["isError"] and bad_background["structuredContent"]["code"] == "invalid_image", bad_background
        large_sheet = {**sheet, "width": 401, "strokes": [{**sheet["strokes"][0], "points": [[0.1, 0.2, 0.3]] * 90000}]}
        drawing_bytes = json.dumps(large_sheet, separators=(",", ":")).encode("utf8")
        assert len(drawing_bytes) > 1024 * 1024, "Native drawing must exceed a single RPC frame"
        drawing_upload = call("tools/call", {"name": "organizer_drawing_upload_begin", "arguments": {
            "id": drawing_id, "expected_revision": drawing_read["structuredContent"]["revision"], "size": len(drawing_bytes), "sha256": hashlib.sha256(drawing_bytes).hexdigest()}})
        assert not drawing_upload["isError"], drawing_upload
        drawing_token = drawing_upload["structuredContent"]["token"]
        for offset in range(0, len(drawing_bytes), 65536):
            appended = call("tools/call", {"name": "organizer_drawing_upload_append", "arguments": {
                "token": drawing_token, "offset": offset, "data": base64.b64encode(drawing_bytes[offset:offset + 65536]).decode("ascii")}})
            assert not appended["isError"], appended
        drawing_finalized = call("tools/call", {"name": "organizer_drawing_upload_finalize", "arguments": {"token": drawing_token}})
        assert not drawing_finalized["isError"] and drawing_finalized["structuredContent"]["persisted"], drawing_finalized
        stored_drawing = next(module for module in json.loads(data_file.read_text())["customOrganizer"]["modules"] if module["id"] == drawing_id)["drawing"]
        assert stored_drawing["width"] == 401 and len(stored_drawing["strokes"][0]["points"]) == 90000
        large_drawing_read = call("tools/call", {"name": "organizer_drawing_read", "arguments": {"id": drawing_id, "limit": 7}})
        drawing_compacted = call("tools/call", {"name": "organizer_drawing_replace", "arguments": {
            "id": drawing_id, "expected_revision": large_drawing_read["structuredContent"]["revision"], "sheet": sheet}})
        assert not drawing_compacted["isError"] and drawing_compacted["structuredContent"]["persisted"], drawing_compacted
        for date in ("2028-04-01", "2028-04-02"):
            day = call("tools/call", {"name": "organizer_day_marker_read", "arguments": {"date": date}})
            assert day["structuredContent"]["marker"] is None, day
            assigned = call("tools/call", {"name": "organizer_day_marker_set", "arguments": {
                "date": date, "expected_revision": day["structuredContent"]["revision"], "shift_id": "owned-cleanup-shift",
                "cycle_marker_ids": ["owned-cleanup-cycle"] if date == "2028-04-01" else []}})
            assert not assigned["isError"] and assigned["structuredContent"]["persisted"], assigned
            assert any(mark["datum"] == date and mark["schichtId"] == "owned-cleanup-shift" for mark in json.loads(data_file.read_text())["tagmarken"])
        for kind, section in (("shift", "schichten"), ("cycle_marker", "zyklusmarker")):
            created = call("tools/call", {"name": f"organizer_{kind}_create", "arguments": {"name": "Owned native definition"}})
            assert not created["isError"] and created["structuredContent"]["persisted"], created
            definition_id = created["structuredContent"]["id"]
            read = call("tools/call", {"name": f"organizer_{kind}_read", "arguments": {"id": definition_id}})
            updated = call("tools/call", {"name": f"organizer_{kind}_update", "arguments": {
                "id": definition_id, "expected_revision": read["structuredContent"]["revision"], "name": "Updated native definition"}})
            assert not updated["isError"] and updated["structuredContent"]["persisted"], updated
            assert next(item for item in json.loads(data_file.read_text())[section] if item["id"] == definition_id)["name"] == "Updated native definition"
            for removed_id in (definition_id, "owned-cleanup-" + ("shift" if kind == "shift" else "cycle")):
                read = call("tools/call", {"name": f"organizer_{kind}_read", "arguments": {"id": removed_id}})
                deleted = call("tools/call", {"name": f"organizer_{kind}_delete", "arguments": {
                    "id": removed_id, "expected_revision": read["structuredContent"]["revision"]}})
                assert not deleted["isError"] and deleted["structuredContent"]["persisted"], deleted
                assert not any(item["id"] == removed_id for item in json.loads(data_file.read_text())[section])
            marks = json.loads(data_file.read_text())["tagmarken"]
            if kind == "shift":
                assert any(mark["datum"] == "2028-04-01" and mark["zyklusIds"] == ["owned-cleanup-cycle"] and not mark["schichtId"] for mark in marks), marks
                assert not any(mark["datum"] == "2028-04-02" for mark in marks), marks
            else:
                assert not any(mark["datum"] == "2028-04-01" for mark in marks), marks
        contact_read = call("tools/call", {"name": "organizer_contact_read", "arguments": {"id": contact_id, "fields": ["id", "vorname", "geburtstag"]}})
        assert contact_read["structuredContent"]["contact"]["geburtstag"] == "--02-29"
        assert "email" not in contact_read["structuredContent"]["contact"]
        contact_updated = call("tools/call", {"name": "organizer_contact_update", "arguments": {
            "id": contact_id, "expected_revision": contact_read["structuredContent"]["revision"], "first_name": "Revised owned"}})
        assert not contact_updated["isError"] and contact_updated["structuredContent"]["persisted"], contact_updated
        appointment = call("tools/call", {"name": "organizer_appointment_read", "arguments": {"id": appointment_id}})
        linked = call("tools/call", {"name": "organizer_appointment_update", "arguments": {
            "id": appointment_id, "expected_revision": appointment["structuredContent"]["revision"], "contact_id": contact_id}})
        assert not linked["isError"] and linked["structuredContent"]["persisted"], linked
        contact_read = call("tools/call", {"name": "organizer_contact_read", "arguments": {"id": contact_id}})
        contact_deleted = call("tools/call", {"name": "organizer_contact_delete", "arguments": {
            "id": contact_id, "expected_revision": contact_read["structuredContent"]["revision"]}})
        assert not contact_deleted["isError"] and contact_deleted["structuredContent"]["persisted"], contact_deleted
        assert contact_deleted["structuredContent"]["recovery_snapshot_confirmed"] is True
        durable = json.loads(data_file.read_text())
        assert not any(item["id"] == contact_id for item in durable["kontakte"])
        assert not any(item.get("kontaktId") == contact_id for item in durable["jahrestage"])
        assert next(item for item in durable["termine"] if item["id"] == appointment_id)["kontaktId"] == ""
        # The existing weekly policy may reuse a verified checkpoint. Confirm
        # its real payload integrity rather than requiring a newly named file.
        checkpoints = product.journal_liste()
        assert any(item["integrity"] == "ok" for item in checkpoints), checkpoints
        contact_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {
            "id": contact_deleted["structuredContent"]["trash_id"]}})
        assert not contact_restored["isError"] and contact_restored["structuredContent"]["persisted"], contact_restored
        assert any(item["id"] == contact_id for item in json.loads(data_file.read_text())["kontakte"])
        group_created = call("tools/call", {"name": "organizer_notebook_group_create", "arguments": {"name": "Owned native notebook group"}})
        assert not group_created["isError"] and group_created["structuredContent"]["persisted"], group_created
        group_info = group_created["structuredContent"]
        group_read = call("tools/call", {"name": "organizer_notebook_group_read", "arguments": {"id": group_info["id"]}})
        group_updated = call("tools/call", {"name": "organizer_notebook_group_update", "arguments": {
            "id": group_info["id"], "expected_revision": group_read["structuredContent"]["revision"], "name": "Revised owned native group", "position": 0}})
        assert not group_updated["isError"] and group_updated["structuredContent"]["persisted"], group_updated
        book_created = call("tools/call", {"name": "organizer_notebook_create", "arguments": {"group_id": group_info["id"], "name": "Owned native notebook"}})
        assert not book_created["isError"] and book_created["structuredContent"]["persisted"], book_created
        book_id = book_created["structuredContent"]["id"]
        structure_note = call("tools/call", {"name": "organizer_note_create", "arguments": {
            "title": "Owned native structure page", "text": "Preserve this page", "notebook_id": book_id}})
        assert not structure_note["isError"] and structure_note["structuredContent"]["persisted"], structure_note
        structure_note_id = structure_note["structuredContent"]["id"]
        book_read = call("tools/call", {"name": "organizer_notebook_read", "arguments": {"id": book_id}})
        book_updated = call("tools/call", {"name": "organizer_notebook_update", "arguments": {
            "id": book_id, "expected_revision": book_read["structuredContent"]["revision"], "name": "Revised owned native notebook", "position": 0}})
        assert not book_updated["isError"] and book_updated["structuredContent"]["persisted"], book_updated
        book_read = call("tools/call", {"name": "organizer_notebook_read", "arguments": {"id": book_id}})
        book_deleted = call("tools/call", {"name": "organizer_notebook_delete", "arguments": {
            "id": book_id, "expected_revision": book_read["structuredContent"]["revision"]}})
        assert not book_deleted["isError"] and book_deleted["structuredContent"]["persisted"], book_deleted
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == structure_note_id)["notizbuchId"] == group_info["notebook_id"]
        book_restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {"id": book_deleted["structuredContent"]["trash_id"]}})
        assert not book_restored["isError"] and book_restored["structuredContent"]["persisted"], book_restored
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == structure_note_id)["notizbuchId"] == book_id
        group_read = call("tools/call", {"name": "organizer_notebook_group_read", "arguments": {"id": group_info["id"]}})
        group_deleted = call("tools/call", {"name": "organizer_notebook_group_delete", "arguments": {
            "id": group_info["id"], "expected_revision": group_read["structuredContent"]["revision"]}})
        assert not group_deleted["isError"] and group_deleted["structuredContent"]["persisted"], group_deleted
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == structure_note_id)["text"] == "Preserve this page"
        # A normal full-note result would exceed the 1 MiB record bound; read
        # its metadata and UTF-8 bytes through the bounded product operations.
        large_text = "🌸é\n" * 100000
        current_note = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id}})
        large_updated = call("tools/call", {"name": "organizer_note_update", "arguments": {
            "id": note_id, "expected_revision": current_note["structuredContent"]["revision"], "text": large_text}})
        assert not large_updated["isError"] and large_updated["structuredContent"]["persisted"], large_updated
        projected = call("tools/call", {"name": "organizer_data_read", "arguments": {
            "section": "notizen", "id": note_id, "fields": ["id", "titel"]}})
        assert projected["structuredContent"]["entry"]["id"] == note_id
        assert "text" not in projected["structuredContent"]["entry"]
        first = call("tools/call", {"name": "organizer_content_read", "arguments": {
            "section": "notizen", "id": note_id, "path": ["text"], "limit": 5}})["structuredContent"]
        encoded = large_text.encode("utf-8")
        assert first["total_bytes"] == len(encoded) and base64.b64decode(first["data"]) == encoded[:5]
        second = call("tools/call", {"name": "organizer_content_read", "arguments": {
            "section": "notizen", "id": note_id, "path": ["text"], "offset": first["next_offset"],
            "limit": 65536, "expected_revision": first["revision"]}})["structuredContent"]
        assert base64.b64decode(second["data"]) == encoded[5:5 + 65536]
        stale = call("tools/call", {"name": "organizer_note_update", "arguments": {"id": note_id,
            "expected_revision": revision["structuredContent"]["revision"], "title": "Do not overwrite"}})
        assert stale["isError"] and stale["structuredContent"]["code"] == "conflict", stale
        current = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id, "fields": ["id", "titel"]}})
        deleted = call("tools/call", {"name": "organizer_note_delete", "arguments": {"id": note_id,
            "expected_revision": current["structuredContent"]["revision"]}})
        assert not deleted["isError"] and deleted["structuredContent"]["persisted"], deleted
        assert not any(item["id"] == note_id for item in json.loads(data_file.read_text())["notizen"])
        restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {
            "id": deleted["structuredContent"]["trash_id"]}})
        assert not restored["isError"] and restored["structuredContent"]["persisted"], restored
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["titel"] == "Native revised fixture"
        recovery_created = call("tools/call", {"name": "organizer_recovery_snapshot_create"})
        assert not recovery_created["isError"] and recovery_created["structuredContent"]["confirmed"], recovery_created
        recovery_id = recovery_created["structuredContent"]["snapshot"]["id"]
        native_manifest, native_archive = product.journal_snapshot_lesen(recovery_id)
        assert native_manifest["snapshotId"] == recovery_id
        assert native_archive["daten"]["zeiterfassung"]["enabled"]
        assert next(item for item in native_archive["daten"]["notizen"] if item["id"] == note_id)["text"] == large_text
        recovery_list = call("tools/call", {"name": "organizer_recovery_list"})
        assert not recovery_list["isError"], recovery_list
        assert any(item["id"] == recovery_id for item in recovery_list["structuredContent"]["snapshots"])
        assert all("path" not in item for item in recovery_list["structuredContent"]["snapshots"])
        recovery_preview = call("tools/call", {"name": "organizer_recovery_snapshot_preview", "arguments": {"id": recovery_id}})
        assert not recovery_preview["isError"] and recovery_preview["structuredContent"]["confirmed"], recovery_preview
        recovery_missing = call("tools/call", {"name": "organizer_recovery_snapshot_preview", "arguments": {"id": "00000000-0000-0000-0000-000000000000"}})
        assert recovery_missing["isError"] and recovery_missing["structuredContent"]["code"] == "native_operation_failed", recovery_missing
        recovery_revision = recovery_preview["structuredContent"]["revision"]
        recovery_path = Path(native_manifest["path"])
        assert recovery_path.is_relative_to(Path(temporary.name))
        assert recovery_path.parent == Path(product.journal_verzeichnis())
        with (recovery_path / native_manifest["payload"].get("file", "payload.magnolie")).open("ab") as stream:
            stream.write(b"owned recovery tamper")
        recovery_stale_delete = call("tools/call", {"name": "organizer_recovery_snapshots_delete", "arguments": {
            "snapshots": [{"id": recovery_id, "expected_revision": recovery_revision}]}})
        assert recovery_stale_delete["isError"] and recovery_stale_delete["structuredContent"]["code"] == "conflict", recovery_stale_delete
        assert recovery_path.is_dir()
        recovery_inspect = call("tools/call", {"name": "organizer_recovery_snapshot_preview", "arguments": {"id": recovery_id, "verify": False}})
        assert not recovery_inspect["isError"] and not recovery_inspect["structuredContent"]["verified"], recovery_inspect
        recovery_deleted = call("tools/call", {"name": "organizer_recovery_snapshots_delete", "arguments": {
            "snapshots": [{"id": recovery_id, "expected_revision": recovery_inspect["structuredContent"]["revision"]}]}})
        assert not recovery_deleted["isError"] and recovery_deleted["structuredContent"]["deleted_count"] == 1, recovery_deleted
        assert not recovery_path.exists()
        creation_policy = call("tools/call", {"name": "organizer_recovery_creation_policy_read"})
        creation_updated = call("tools/call", {"name": "organizer_recovery_creation_policy_update", "arguments": {
            "expected_revision": creation_policy["structuredContent"]["revision"], "creation_mode": "interval", "interval_minutes": 73}})
        assert not creation_updated["isError"] and creation_updated["structuredContent"]["persisted"], creation_updated
        creation_saved = json.loads(data_file.read_text())["einstellungen"]["allgemein"]
        assert creation_saved["wiederherstellungsmodus"] == "interval" and creation_saved["wiederherstellungsminuten"] == 73
        runtime_policy = call("tools/call", {"name": "organizer_recovery_runtime_policy_read"})
        runtime_updated = call("tools/call", {"name": "organizer_recovery_runtime_policy_update", "arguments": {
            "expected_revision": runtime_policy["structuredContent"]["revision"], "interval": "off", "retention_mode": "days", "maximum": 50, "days": 3650}})
        assert not runtime_updated["isError"] and runtime_updated["structuredContent"]["native_applied"] and runtime_updated["structuredContent"]["persisted"], runtime_updated
        runtime_saved = json.loads(data_file.read_text())["einstellungen"]["allgemein"]
        assert runtime_saved["wiederherstellungsintervall"] == "off" and runtime_saved["wiederherstellungsanzahl"] == 50
        runtime_readback = call("tools/call", {"name": "organizer_recovery_runtime_policy_read"})
        assert runtime_readback["structuredContent"]["policy"]["interval"] == "off" and runtime_readback["structuredContent"]["policy"]["maximum"] == 50
        backup_created = call("tools/call", {"name": "organizer_backup_create"})
        assert not backup_created["isError"] and backup_created["structuredContent"]["confirmed"], backup_created
        backup_path = Path(backup_created["structuredContent"]["path"])
        assert backup_path.is_relative_to(Path(temporary.name)) and backup_path.is_file()
        backup_data = json.loads(backup_path.read_text())
        assert next(item for item in backup_data["notizen"] if item["id"] == note_id)["text"] == large_text
        protected_backup = call("tools/call", {"name": "organizer_backup_create", "arguments": {
            "folder": str(Path(temporary.name) / "owned-external-backup"), "password": "owned-backup-fixture-password"}})
        assert not protected_backup["isError"] and protected_backup["structuredContent"]["confirmed"], protected_backup
        protected_path = Path(protected_backup["structuredContent"]["path"])
        assert protected_path.is_relative_to(Path(temporary.name)) and protected_path.is_file()
        protected_data = product.gesamtarchiv_lesen_text(protected_path.read_text(), "owned-backup-fixture-password")
        assert next(item for item in protected_data["daten"]["notizen"] if item["id"] == note_id)["text"] == large_text
        archive_preview = call("tools/call", {"name": "organizer_archive_preview", "arguments": {
            "path": str(protected_path), "password": "owned-backup-fixture-password"}})
        assert not archive_preview["isError"] and archive_preview["structuredContent"]["verified"] and archive_preview["structuredContent"]["encrypted"], archive_preview
        assert archive_preview["structuredContent"]["counts"], archive_preview
        archive_wrong_password = call("tools/call", {"name": "organizer_archive_preview", "arguments": {"path": str(protected_path), "password": "wrong"}})
        assert archive_wrong_password["isError"] and archive_wrong_password["structuredContent"]["code"] == "archive_verification_failed", archive_wrong_password
        export_path = Path(temporary.name) / "owned-export.magnolie"
        for password in ("", "owned-export-password"):
            exported = call("tools/call", {"name": "organizer_archive_export", "arguments": {
                "path": str(export_path), "password": password, "overwrite": bool(password)}})
            assert not exported["isError"] and exported["structuredContent"]["confirmed"], exported
            assert exported["structuredContent"]["encrypted"] == bool(password)
            exported_data = product.gesamtarchiv_lesen_text(export_path.read_text(), password)
            assert next(item for item in exported_data["daten"]["notizen"] if item["id"] == note_id)["text"] == large_text
        exported_bytes = export_path.read_bytes()
        rejected_export = call("tools/call", {"name": "organizer_archive_export", "arguments": {"path": str(export_path)}})
        assert rejected_export["isError"] and export_path.read_bytes() == exported_bytes, rejected_export
        profile_bytes = data_file.read_bytes()
        rejected_profile = call("tools/call", {"name": "organizer_archive_export", "arguments": {"path": str(data_file), "overwrite": True}})
        assert rejected_profile["isError"] and data_file.read_bytes() == profile_bytes, rejected_profile
        export_link = Path(temporary.name) / "owned-export-link.magnolie"
        export_link.symlink_to(export_path)
        rejected_link = call("tools/call", {"name": "organizer_archive_export", "arguments": {"path": str(export_link), "overwrite": True}})
        assert rejected_link["isError"] and export_link.is_symlink() and export_path.read_bytes() == exported_bytes, rejected_link
        if os.environ.get("MAGNOLIE_MCP_PROBE_RESTORE_REPAIR") == "1":
            restore_point = call("tools/call", {"name": "organizer_recovery_snapshot_create"})
            assert not restore_point["isError"], restore_point
            restore_id = restore_point["structuredContent"]["snapshot"]["id"]
            before_restore = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id, "fields": ["id"]}})
            changed_for_restore = call("tools/call", {"name": "organizer_note_update", "arguments": {
                "id": note_id, "expected_revision": before_restore["structuredContent"]["revision"], "text": "Owned later native state"}})
            assert not changed_for_restore["isError"] and changed_for_restore["structuredContent"]["persisted"], changed_for_restore
            restore_setup = threading.Event()
            restore_result = {}
            restore_originals = {}

            def configure_restore_projection_failure():
                restore_originals["projection"] = window._erinnerungsprojektion_aktualisieren
                restore_originals["reply"] = window.antwort
                def failed_projection():
                    raise OSError("Owned native restore projection failure")
                def reply(callback, *values):
                    if callback == "App.journalWiederhergestellt":
                        value = values[0]
                        restore_result.update({key: value.get(key) for key in ("ok", "committed", "repairPending")})
                    return restore_originals["reply"](callback, *values)
                window._erinnerungsprojektion_aktualisieren = failed_projection
                window.antwort = reply
                restore_setup.set()
                return False

            product.GLib.idle_add(configure_restore_projection_failure)
            assert restore_setup.wait(15), "Native restore fixture was not configured"
            restore_preview = call("tools/call", {"name": "organizer_recovery_snapshot_preview", "arguments": {"id": restore_id}})
            restore_book = call("tools/call", {"name": "organizer_book_revision_read"})
            stale_restore = call("tools/call", {"name": "organizer_recovery_snapshot_restore", "arguments": {
                "id": restore_id, "expected_revision": "0" * 64, "expected_book_revision": restore_book["structuredContent"]["revision"], "areas": ["notes"], "mode": "replace"}})
            assert stale_restore["isError"] and stale_restore["structuredContent"]["code"] == "conflict", stale_restore
            assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["text"] == "Owned later native state"
            restore_book = call("tools/call", {"name": "organizer_book_revision_read"})
            restored_api = call("tools/call", {"name": "organizer_recovery_snapshot_restore", "arguments": {
                "id": restore_id, "expected_revision": restore_preview["structuredContent"]["revision"], "expected_book_revision": restore_book["structuredContent"]["revision"], "areas": ["notes"], "mode": "replace"}})
            assert not restored_api["isError"] and restored_api["structuredContent"]["committed"] and restored_api["structuredContent"]["repair_pending"], restored_api
            assert restore_result == {"ok": True, "committed": True, "repairPending": True}, restore_result
            restore_cleaned = threading.Event()
            def clean_restore_fixture():
                window._erinnerungsprojektion_aktualisieren = restore_originals["projection"]
                window.antwort = restore_originals["reply"]
                restore_cleaned.set()
                return False
            product.GLib.idle_add(clean_restore_fixture)
            assert restore_cleaned.wait(5), "Native restore fixture was not cleaned"
            assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["text"] == large_text
            restored_gui = call("tools/call", {"name": "organizer_content_read", "arguments": {"section": "notizen", "id": note_id, "path": ["text"], "limit": 5}})
            assert not restored_gui["isError"] and restored_gui["structuredContent"]["total_bytes"] == len(large_text.encode("utf8")), "Native GUI did not adopt the committed restore"
            assert base64.b64decode(restored_gui["structuredContent"]["data"]) == large_text.encode("utf8")[:5]
        import_preview = call("tools/call", {"name": "organizer_archive_preview", "arguments": {
            "path": str(export_path), "password": "owned-export-password"}})
        assert not import_preview["isError"], import_preview
        import_revision = import_preview["structuredContent"]["revision"]
        before_import = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id, "fields": ["id"]}})
        changed_import = call("tools/call", {"name": "organizer_note_update", "arguments": {
            "id": note_id, "expected_revision": before_import["structuredContent"]["revision"], "text": "Owned before archive import"}})
        assert not changed_import["isError"], changed_import
        import_book = call("tools/call", {"name": "organizer_book_revision_read"})
        export_path.write_bytes(exported_bytes + b"\n")
        import_args = {"path": str(export_path), "password": "owned-export-password", "expected_revision": import_revision,
            "expected_book_revision": import_book["structuredContent"]["revision"], "mode": "replace"}
        stale_import = call("tools/call", {"name": "organizer_archive_import", "arguments": import_args})
        assert stale_import["isError"] and stale_import["structuredContent"]["code"] == "conflict", stale_import
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["text"] == "Owned before archive import"
        export_path.write_bytes(exported_bytes)
        import_setup = threading.Event()
        import_originals = {}
        def configure_import_projection_failure():
            import_originals["projection"] = window._erinnerungsprojektion_aktualisieren
            def failed_projection():
                raise OSError("Owned archive import projection failure")
            window._erinnerungsprojektion_aktualisieren = failed_projection
            import_setup.set()
            return False
        product.GLib.idle_add(configure_import_projection_failure)
        assert import_setup.wait(5)
        imported_api = call("tools/call", {"name": "organizer_archive_import", "arguments": import_args})
        assert not imported_api["isError"] and imported_api["structuredContent"]["committed"] and imported_api["structuredContent"]["repair_pending"], imported_api
        assert imported_api["structuredContent"]["previous_snapshot_id"], imported_api
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["text"] == large_text
        imported_gui = call("tools/call", {"name": "organizer_content_read", "arguments": {"section": "notizen", "id": note_id, "path": ["text"], "limit": 5}})
        assert not imported_gui["isError"] and imported_gui["structuredContent"]["total_bytes"] == len(large_text.encode("utf8")), imported_gui
        import_cleaned = threading.Event()
        def clean_import_fixture():
            window._erinnerungsprojektion_aktualisieren = import_originals["projection"]
            import_cleaned.set()
            return False
        product.GLib.idle_add(clean_import_fixture)
        assert import_cleaned.wait(5)
        for backup_password in ("", "owned-classic-backup-password"):
            classic_path = Path(temporary.name) / "owned-classic-backup.json"
            classic_text = json.dumps(backup_data, ensure_ascii=False)
            if backup_password:
                classic_text = product.verschluesseln(classic_text, backup_password)
            classic_path.write_text(classic_text)
            classic_preview = call("tools/call", {"name": "organizer_backup_preview", "arguments": {
                "path": str(classic_path), "password": backup_password}})
            assert not classic_preview["isError"] and classic_preview["structuredContent"]["verified"], classic_preview
            assert classic_preview["structuredContent"]["encrypted"] == bool(backup_password)
            if backup_password:
                wrong_backup = call("tools/call", {"name": "organizer_backup_preview", "arguments": {"path": str(classic_path), "password": "wrong"}})
                assert wrong_backup["isError"] and wrong_backup["structuredContent"]["code"] == "backup_verification_failed", wrong_backup
            before_classic = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id, "fields": ["id"]}})
            changed_classic = call("tools/call", {"name": "organizer_note_update", "arguments": {
                "id": note_id, "expected_revision": before_classic["structuredContent"]["revision"], "text": "Owned before classic restore"}})
            assert not changed_classic["isError"], changed_classic
            classic_book = call("tools/call", {"name": "organizer_book_revision_read"})
            classic_args = {"path": str(classic_path), "password": backup_password,
                "expected_revision": classic_preview["structuredContent"]["revision"], "expected_book_revision": classic_book["structuredContent"]["revision"], "mode": "replace"}
            classic_path.write_text(classic_text + "\n")
            stale_classic = call("tools/call", {"name": "organizer_backup_restore", "arguments": classic_args})
            assert stale_classic["isError"] and stale_classic["structuredContent"]["code"] == "conflict", stale_classic
            classic_path.write_text(classic_text)
            import_setup.clear(); import_cleaned.clear()
            product.GLib.idle_add(configure_import_projection_failure)
            assert import_setup.wait(5)
            restored_classic = call("tools/call", {"name": "organizer_backup_restore", "arguments": classic_args})
            assert not restored_classic["isError"] and restored_classic["structuredContent"]["committed"] and restored_classic["structuredContent"]["repair_pending"], restored_classic
            assert restored_classic["structuredContent"]["previous_snapshot_id"], restored_classic
            stored_classic = data_file.read_text()
            if backup_password:
                assert product.ist_verschluesselt(stored_classic)
                stored_classic = product.entschluesseln(stored_classic, backup_password)
            assert next(item for item in json.loads(stored_classic)["notizen"] if item["id"] == note_id)["text"] == large_text
            classic_gui = call("tools/call", {"name": "organizer_content_read", "arguments": {"section": "notizen", "id": note_id, "path": ["text"], "limit": 5}})
            assert not classic_gui["isError"] and classic_gui["structuredContent"]["total_bytes"] == len(large_text.encode("utf8")), classic_gui
            product.GLib.idle_add(clean_import_fixture)
            assert import_cleaned.wait(5)
        bin_before = call("tools/call", {"name": "organizer_trash_revision_read"})
        bin_note = call("tools/call", {"name": "organizer_note_create", "arguments": {"title": "Owned trash clear fixture", "text": "Owned"}})
        assert not bin_note["isError"], bin_note
        bin_note_id = bin_note["structuredContent"]["id"]
        bin_note_read = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": bin_note_id, "fields": ["id"]}})
        bin_note_deleted = call("tools/call", {"name": "organizer_note_delete", "arguments": {
            "id": bin_note_id, "expected_revision": bin_note_read["structuredContent"]["revision"]}})
        assert not bin_note_deleted["isError"], bin_note_deleted
        stale_bin = call("tools/call", {"name": "organizer_trash_empty", "arguments": {"expected_revision": bin_before["structuredContent"]["revision"]}})
        assert stale_bin["isError"] and stale_bin["structuredContent"]["code"] == "conflict", stale_bin
        saved_before_empty = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        bin_revision = call("tools/call", {"name": "organizer_trash_revision_read"})
        empty_bin = call("tools/call", {"name": "organizer_trash_empty", "arguments": {"expected_revision": bin_revision["structuredContent"]["revision"]}})
        assert not empty_bin["isError"] and empty_bin["structuredContent"]["persisted"], empty_bin
        assert empty_bin["structuredContent"]["deleted_count"] == bin_revision["structuredContent"]["total"] > 0
        saved_after_empty = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        assert saved_after_empty["papierkorb"] == []
        assert saved_before_empty["tombstones"] == saved_after_empty["tombstones"]
        assert saved_before_empty["notizen"] == saved_after_empty["notizen"]
        own_before = call("tools/call", {"name": "organizer_own_profile_read"})
        own_written = call("tools/call", {"name": "organizer_own_profile_update", "arguments": {
            "expected_revision": own_before["structuredContent"]["revision"], "first_name": "Owned", "last_name": "Profile",
            "emails": [{"value": "owned@example.org"}], "phones": [{"value": "+49123456789", "types": ["cell"]}],
            "addresses": [{"street": "Owned profile street 2", "postal_code": "10115", "city": "Owned town"}],
            "birth_date": "--02-29", "anniversaries": [{"type": "anniversary", "date": "2020-01-02"}]}})
        assert not own_written["isError"] and own_written["structuredContent"]["persisted"], own_written
        own_stale = call("tools/call", {"name": "organizer_own_profile_update", "arguments": {
            "expected_revision": own_before["structuredContent"]["revision"], "company": "stale"}})
        assert own_stale["isError"] and own_stale["structuredContent"]["code"] == "conflict", own_stale
        own_read = call("tools/call", {"name": "organizer_own_profile_read", "arguments": {"fields": ["vorname"]}})
        assert own_read["structuredContent"]["profile"]["data"] == {"vorname": "Owned"}, own_read
        own_updated = call("tools/call", {"name": "organizer_own_profile_update", "arguments": {
            "expected_revision": own_read["structuredContent"]["revision"], "company": "Owned company"}})
        assert not own_updated["isError"] and own_updated["structuredContent"]["persisted"], own_updated
        own_file = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        own_profile = own_file["eigenesProfil"]
        assert own_profile["kind"] == "own_profile" and own_profile["id"] == own_written["structuredContent"]["id"]
        assert own_profile["data"]["firma"] == "Owned company" and own_profile["data"]["geburtstag"] == "--02-29"
        assert len(own_profile["data"]["profilJahrestage"]) == 2 and "uid" not in own_profile["data"]
        assert own_file["kontakte"] == saved_after_empty["kontakte"] and own_file["jahrestage"] == saved_after_empty["jahrestage"]
        holiday_visits = []
        class HolidayFixture(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                holiday_visits.append(self.path)
                payload = json.dumps([{"startDate": "2028-01-01", "endDate": "2028-01-01",
                    "name": [{"language": "EN", "text": "Owned HTTP holiday"}], "nationwide": True}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        holiday_server = HTTPServer(("127.0.0.1", 0), HolidayFixture)
        holiday_thread = threading.Thread(target=holiday_server.serve_forever, daemon=True)
        holiday_thread.start()
        holiday_endpoint = product.FEIERTAG_DIENST
        product.FEIERTAG_DIENST = "http://127.0.0.1:%d" % holiday_server.server_port
        try:
            holidays = call("tools/call", {"name": "organizer_holidays_read"})
            assert holidays["structuredContent"]["settings"]["land"] == "DE", holidays
            holiday_settings = call("tools/call", {"name": "organizer_holidays_settings_update", "arguments": {
                "expected_revision": holidays["structuredContent"]["revision"], "country": "DE", "region": "DE-BY", "all_regions": False, "school_holidays": False}})
            assert not holiday_settings["isError"] and holiday_settings["structuredContent"]["persisted"], holiday_settings
            holidays = call("tools/call", {"name": "organizer_holidays_read"})
            saved_holiday_settings = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))["einstellungen"]["ort"]
            assert holidays["structuredContent"]["settings"]["region"] == "DE-BY" and saved_holiday_settings["region"] == "DE-BY"
            fetched_holidays = call("tools/call", {"name": "organizer_holidays_retrieve", "arguments": {
                "expected_revision": holidays["structuredContent"]["revision"], "years": [2028]}})
            assert not fetched_holidays["isError"] and fetched_holidays["structuredContent"]["persisted"] and fetched_holidays["structuredContent"]["imported_count"] == 1, fetched_holidays
            assert len(holiday_visits) == 1 and holiday_visits[0].startswith("/PublicHolidays?") and "countryIsoCode=DE" in holiday_visits[0] and "subdivisionCode=DE-BY" in holiday_visits[0], holiday_visits
            holiday_file = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
            assert any(item["name"] == "Owned HTTP holiday" and item["country"] == "DE" for item in holiday_file["feiertage"])
            assert 2028 in holiday_file["einstellungen"]["ort"]["jahre"]
            stale_holidays = call("tools/call", {"name": "organizer_holidays_clear", "arguments": {"expected_revision": holidays["structuredContent"]["revision"]}})
            assert stale_holidays["isError"] and stale_holidays["structuredContent"]["code"] == "conflict", stale_holidays
            fresh_holidays = call("tools/call", {"name": "organizer_holidays_read"})
            cleared_holidays = call("tools/call", {"name": "organizer_holidays_clear", "arguments": {"expected_revision": fresh_holidays["structuredContent"]["revision"]}})
            assert not cleared_holidays["isError"] and cleared_holidays["structuredContent"]["persisted"], cleared_holidays
            holiday_file = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
            assert holiday_file["feiertage"] == [] and holiday_file["einstellungen"]["ort"]["abgerufen"] == 0
        finally:
            product.FEIERTAG_DIENST = holiday_endpoint
            holiday_server.shutdown(); holiday_server.server_close(); holiday_thread.join(timeout=3)
        vault_ticks = {"count": 0}
        vault_tick_ready = threading.Event()
        def prepare_vault_heartbeat():
            def tick():
                vault_ticks["count"] += 1
                return True
            vault_ticks["source"] = product.GLib.timeout_add(100, tick)
            vault_tick_ready.set()
            return False
        product.GLib.idle_add(prepare_vault_heartbeat)
        assert vault_tick_ready.wait(5)
        vault_started = time.monotonic()
        backup_settings = call("tools/call", {"name": "organizer_backup_settings_read"})
        vault_elapsed = time.monotonic() - vault_started
        assert vault_elapsed < 1 or vault_ticks["count"] >= 2, "GTK heartbeat stalled during native vault status lookup"
        product.GLib.source_remove(vault_ticks["source"])
        assert not backup_settings["isError"] and backup_settings["structuredContent"]["settings"]["password_available"] is False, backup_settings
        capture_private_secret_service()
        backup_settings_updated = call("tools/call", {"name": "organizer_backup_settings_update", "arguments": {
            "expected_revision": backup_settings["structuredContent"]["revision"], "folder": str(Path(temporary.name) / "owned-configured-backups"),
            "enabled": False, "interval": "weekly", "retention": 9}})
        assert not backup_settings_updated["isError"] and backup_settings_updated["structuredContent"]["persisted"], backup_settings_updated
        backup_settings_file = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))["einstellungen"]["allgemein"]
        assert backup_settings_file["sicherungsordner"].endswith("/owned-configured-backups")
        assert backup_settings_file["cloudSicherung"]["aufbewahrung"] == 9 and backup_settings_file["cloudSicherung"]["intervall"] == "weekly"
        backup_settings_fresh = call("tools/call", {"name": "organizer_backup_settings_read"})
        backup_not_ready = call("tools/call", {"name": "organizer_backup_settings_update", "arguments": {
            "expected_revision": backup_settings_fresh["structuredContent"]["revision"], "enabled": True}})
        assert backup_not_ready["isError"] and backup_not_ready["structuredContent"]["code"] == "backup_not_ready", backup_not_ready
        assert json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))["einstellungen"]["allgemein"]["cloudSicherung"]["aktiv"] is False
        unready_book = call("tools/call", {"name": "organizer_book_revision_read"})
        unready_test = call("tools/call", {"name": "organizer_backup_test", "arguments": {"expected_book_revision": unready_book["structuredContent"]["revision"]}})
        assert unready_test["isError"] and unready_test["structuredContent"]["code"] == "backup_not_ready", unready_test
        # The private Secret Service is unavailable. Exercise native store/result
        # correlation with an owned backend; this is not an OS-keyring success proof.
        class OwnedVault:
            value = None
            fail = True
            def store(self, _account, password):
                if self.fail:
                    raise RuntimeError("owned-private-vault-error")
                self.value = password
                return True
            def lookup(self, _account):
                return self.value
        owned_vault = OwnedVault()
        vault_original = window._cloud_sicherung_secrets
        vault_swapped = threading.Event()
        def configure_owned_vault():
            window._cloud_sicherung_secrets = product.ArchiveSecretStore(backend=owned_vault)
            vault_swapped.set()
            return False
        product.GLib.idle_add(configure_owned_vault)
        assert vault_swapped.wait(5)
        try:
            vault_book = call("tools/call", {"name": "organizer_book_revision_read"})
            vault_args = {"expected_book_revision": vault_book["structuredContent"]["revision"], "password": "owned-protected-test-secret"}
            failed_vault = call("tools/call", {"name": "organizer_backup_password_store", "arguments": vault_args})
            assert failed_vault["isError"] and failed_vault["structuredContent"]["code"] == "secret_store_failed", failed_vault
            assert "owned-private-vault-error" not in json.dumps(failed_vault)
            owned_vault.fail = False
            saved_vault = call("tools/call", {"name": "organizer_backup_password_store", "arguments": vault_args})
            assert not saved_vault["isError"] and saved_vault["structuredContent"]["stored"] and saved_vault["structuredContent"]["password_available"], saved_vault
            assert owned_vault.value == vault_args["password"]
            assert vault_args["password"] not in json.dumps(saved_vault)
            assert vault_args["password"] not in product.entschluesseln(data_file.read_text(), "owned-classic-backup-password")
            verified_book = call("tools/call", {"name": "organizer_book_revision_read"})
            verified_test = call("tools/call", {"name": "organizer_backup_test", "arguments": {"expected_book_revision": verified_book["structuredContent"]["revision"]}})
            assert not verified_test["isError"] and verified_test["structuredContent"]["verified"] and verified_test["structuredContent"]["persisted"], verified_test
            verified_path = Path(verified_test["structuredContent"]["path"])
            assert verified_path.is_relative_to(Path(temporary.name)) and verified_path.is_file()
            verified_archive = product.gesamtarchiv_lesen(str(verified_path), vault_args["password"])
            assert next(item for item in verified_archive["daten"]["notizen"] if item["id"] == note_id)["text"] == large_text
            verified_preferences = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))["einstellungen"]["allgemein"]["cloudSicherung"]
            assert verified_preferences["status"] == "success" and verified_preferences["letzterErfolg"] == verified_test["structuredContent"]["last_success"]
        finally:
            vault_restored = threading.Event()
            def restore_vault_fixture():
                window._cloud_sicherung_secrets = vault_original
                vault_restored.set()
                return False
            product.GLib.idle_add(restore_vault_fixture)
            assert vault_restored.wait(5)
        health_before = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))["gesundheit"]
        health_settings = call("tools/call", {"name": "organizer_health_settings_read"})
        health_updated = call("tools/call", {"name": "organizer_health_settings_update", "arguments": {
            "expected_revision": health_settings["structuredContent"]["revision"], "enabled": False,
            "units": {"temperature": "fahrenheit", "weight": "lb", "height": "in", "blood_glucose": "mg/dL"},
            "views": {"vital": True, "medications": False, "blood_glucose": True, "history": False},
            "planning": {"vital": {"enabled": True, "start_date": "2028-02-29", "interval_days": 7}}}})
        assert not health_updated["isError"] and health_updated["structuredContent"]["persisted"], health_updated
        health_file = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        assert health_file["gesundheit"] == health_before
        assert health_file["einstellungen"]["kalender"]["gesundheitEinheiten"]["gewicht"] == "lb"
        assert health_file["einstellungen"]["kalender"]["gesundheitPlanung"]["vital"]["intervallTage"] == 7
        assert health_file["einstellungen"]["kalender"]["gesundheitAn"] is False and health_file["einstellungen"]["allgemein"]["registerkarten"]["gesundheit"] is False
        stale_health = call("tools/call", {"name": "organizer_health_settings_update", "arguments": {
            "expected_revision": health_settings["structuredContent"]["revision"], "enabled": True}})
        assert stale_health["isError"] and stale_health["structuredContent"]["code"] == "conflict", stale_health
        health_fresh = call("tools/call", {"name": "organizer_health_settings_read"})
        assert health_fresh["structuredContent"]["settings"]["units"]["weight"] == "lb"
        no_health_view = call("tools/call", {"name": "organizer_health_settings_update", "arguments": {
            "expected_revision": health_fresh["structuredContent"]["revision"], "views": {"vital": False, "medications": False, "blood_glucose": False, "history": False}}})
        assert no_health_view["isError"] and no_health_view["structuredContent"]["code"] == "invalid_settings", no_health_view
        calendar_file = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        calendar_keys = ("termine", "jahrestage", "tagmarken", "schichten", "zyklusmarker", "urlaube", "muelltermine")
        calendar_records = {key: calendar_file[key] for key in calendar_keys}
        calendar_settings = call("tools/call", {"name": "organizer_calendar_settings_read"})
        assert calendar_settings["structuredContent"]["settings"]["cycle_options"]["prediction"] is False
        calendar_updated = call("tools/call", {"name": "organizer_calendar_settings_update", "arguments": {
            "expected_revision": calendar_settings["structuredContent"]["revision"], "click_creates_entry": False, "week_numbers": True,
            "planner_week_numbers": True, "show_past_appointments": True, "show_past_anniversaries": True, "show_past_holidays": True,
            "shift_planner": True, "cycle_calendar": True, "vacation_planner": True, "waste_calendar": True,
            "cycle_options": {"lead_days": 4, "difference_days": 9}}})
        assert not calendar_updated["isError"] and calendar_updated["structuredContent"]["persisted"], calendar_updated
        calendar_saved = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        assert {key: calendar_saved[key] for key in calendar_keys} == calendar_records
        calendar_preferences = calendar_saved["einstellungen"]["kalender"]
        assert calendar_preferences["wochenNummern"] and calendar_preferences["planerWochenNummern"] and calendar_preferences["schichtplanerAn"]
        assert calendar_preferences["zyklusErinnerungen"] == {"prognose": False, "abweichung": False, "vorlauf": 4, "abweichungTage": 9}
        stale_calendar = call("tools/call", {"name": "organizer_calendar_settings_update", "arguments": {
            "expected_revision": calendar_settings["structuredContent"]["revision"], "week_numbers": False}})
        assert stale_calendar["isError"] and stale_calendar["structuredContent"]["code"] == "conflict", stale_calendar
        display_file = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        display_record_keys = ("notizen", "aufgaben", "kontakte", "customOrganizer", "gesundheit")
        display_records = {key: display_file[key] for key in display_record_keys}
        display_settings = call("tools/call", {"name": "organizer_display_settings_read"})
        display_updated = call("tools/call", {"name": "organizer_display_settings_update", "arguments": {
            "expected_revision": display_settings["structuredContent"]["revision"], "selection_options_visible": False,
            "focus_frame": True, "date_picker_buttons": True, "attachment_preview_height": 180,
            "typography": {"typeface": "handwriting", "ink_color": "blue", "size": "large", "spellcheck": False, "lined_paper": False, "time_wheel_direction": "up-later"},
            "tabs": {"notes": False, "contacts": False, "health": False}, "custom_tab": {"enabled": True, "name": "Owned Custom"}, "calendar_view": "month"}})
        assert not display_updated["isError"] and display_updated["structuredContent"]["persisted"], display_updated
        display_saved = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        assert {key: display_saved[key] for key in display_record_keys} == display_records
        assert display_saved["einstellungen"]["schrift"]["art"] == "handwriting" and display_saved["einstellungen"]["schrift"]["groesse"] == "large"
        assert display_saved["einstellungen"]["allgemein"]["hilfsrahmen"] and display_saved["einstellungen"]["allgemein"]["notizAnhangHoehe"] == 180
        assert display_saved["einstellungen"]["allgemein"]["customTab"]["name"] == "Owned Custom"
        assert display_saved["einstellungen"]["ansicht"] == "month"
        display_readback = call("tools/call", {"name": "organizer_display_settings_read"})
        assert display_readback["structuredContent"]["settings"]["current_calendar_view"] == "month"
        spell_ready = threading.Event()
        spell_state = {}
        def read_native_spell_flag():
            spell_state["enabled"] = window.ansicht.get_context().get_spell_checking_enabled()
            spell_ready.set()
            return False
        product.GLib.idle_add(read_native_spell_flag)
        assert spell_ready.wait(5) and spell_state["enabled"] is False
        stale_display = call("tools/call", {"name": "organizer_display_settings_update", "arguments": {
            "expected_revision": display_settings["structuredContent"]["revision"], "focus_frame": False}})
        assert stale_display["isError"] and stale_display["structuredContent"]["code"] == "conflict", stale_display
        spelling_profile = data_file.read_bytes()
        spelling = call("tools/call", {"name": "organizer_spellcheck_word", "arguments": {"word": "hello", "language": "en"}})
        assert not spelling["isError"] and spelling["structuredContent"]["correct"] is True, spelling
        dictionary_file = Path(product.eigene_woerter_datei())
        assert dictionary_file.is_relative_to(Path(temporary.name)) and dictionary_file.parent == profile
        dictionary_word = "magnolieownedwordfixturexyz"
        before_word = call("tools/call", {"name": "organizer_spellcheck_word", "arguments": {"word": dictionary_word, "language": "en"}})
        assert not before_word["isError"] and before_word["structuredContent"]["correct"] is False, before_word
        word_book = call("tools/call", {"name": "organizer_book_revision_read"})
        word_added = call("tools/call", {"name": "organizer_dictionary_add_word", "arguments": {
            "word": dictionary_word, "language": "en", "expected_book_revision": word_book["structuredContent"]["revision"]}})
        assert not word_added["isError"] and word_added["structuredContent"]["confirmed"] and word_added["structuredContent"]["added"], word_added
        assert dictionary_word in dictionary_file.read_text().splitlines()
        import enchant
        dictionary_language = next(value for value in product.rechtschreib_sprachen("en") if enchant.dict_exists(value))
        fresh_dictionary = enchant.DictWithPWL(dictionary_language, str(dictionary_file))
        assert fresh_dictionary.check(dictionary_word), "Cold personal-dictionary reader did not observe the added word"
        del fresh_dictionary
        assert data_file.read_bytes() == spelling_profile, "Personal-dictionary operations rewrote book data"
        regional_path = Path(product.regional_datei())
        assert regional_path.is_relative_to(Path(temporary.name))
        regional_before = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        regional_record_keys = ("termine", "aufgaben", "kontakte", "notizen", "jahrestage", "feiertage",
            "tagmarken", "schichten", "zyklusmarker", "urlaube", "muelltermine", "zeiterfassung", "gesundheit", "customOrganizer")
        regional_records = {key: regional_before[key] for key in regional_record_keys}
        regional_settings = call("tools/call", {"name": "organizer_regional_settings_read"})
        assert not regional_settings["isError"], regional_settings
        regional_updated = call("tools/call", {"name": "organizer_regional_settings_update", "arguments": {
            "expected_revision": regional_settings["structuredContent"]["revision"], "language": "en", "format_locale": "en_GB", "hour_cycle": "h12",
            "first_day_of_week": "sunday", "temperature_unit": "fahrenheit", "time_zone": "Etc/UTC", "home_country": "us"}})
        assert not regional_updated["isError"] and regional_updated["structuredContent"]["native_saved"] and regional_updated["structuredContent"]["persisted"] and regional_updated["structuredContent"]["restart_required"], regional_updated
        regional_native_file = json.loads(regional_path.read_text())
        assert regional_native_file["hourCycle"] == "h12" and regional_native_file["timeZone"] == "Etc/UTC" and regional_native_file["homeCountry"] == "US"
        regional_book = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        assert regional_book["einstellungen"]["regional"] == regional_native_file
        assert {key: regional_book[key] for key in regional_record_keys} == regional_records
        regional_stale = call("tools/call", {"name": "organizer_regional_settings_update", "arguments": {
            "expected_revision": regional_settings["structuredContent"]["revision"], "hour_cycle": "h23"}})
        assert regional_stale["isError"] and regional_stale["structuredContent"]["code"] == "conflict", regional_stale
        regional_readback = call("tools/call", {"name": "organizer_regional_settings_read"})
        assert regional_readback["structuredContent"]["settings"]["hour_cycle"] == "h12" and regional_readback["structuredContent"]["book_settings"]["time_zone"] == "Etc/UTC"
        tray_setup = threading.Event()
        tray_registered = threading.Event()
        tray_fixture = {"previous_desktop": os.environ.get("XDG_CURRENT_DESKTOP"), "original": dict(window._tray_einstellungen)}
        tray_xml = """<node><interface name="org.kde.StatusNotifierWatcher">
          <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
          <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
          <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
          <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
          <property name="ProtocolVersion" type="i" access="read"/>
          <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
        </interface></node>"""
        def configure_private_tray_host():
            try:
                os.environ["XDG_CURRENT_DESKTOP"] = "KDE"
                info = Gio.DBusNodeInfo.new_for_xml(tray_xml).interfaces[0]
                def method(connection, sender, object_path, interface, name, parameters, invocation):
                    if name == "RegisterStatusNotifierItem":
                        item = parameters.unpack()[0]
                        tray_fixture["item"] = (sender, item) if item.startswith("/") else (item, "/StatusNotifierItem")
                        tray_registered.set()
                    invocation.return_value(GLib.Variant("()", ()))
                def prop(_connection, _sender, _path, _interface, name):
                    if name == "IsStatusNotifierHostRegistered": return GLib.Variant("b", True)
                    if name == "ProtocolVersion": return GLib.Variant("i", 0)
                    return GLib.Variant("as", [])
                tray_fixture["registration"] = native_bus.register_object("/StatusNotifierWatcher", info, method, prop, None)
                result = native_bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                    GLib.Variant("(su)", ("org.kde.StatusNotifierWatcher", 0)), GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
                assert result.unpack()[0] == 1
                tray_fixture["owned"] = True
            except BaseException:
                tray_fixture["error"] = traceback.format_exc(limit=3)
            tray_setup.set()
            return False
        product.GLib.idle_add(configure_private_tray_host)
        assert tray_setup.wait(5) and "error" not in tray_fixture, tray_fixture
        try:
            tray_before = call("tools/call", {"name": "organizer_tray_settings_read"})
            assert not tray_before["isError"] and tray_before["structuredContent"]["available"], tray_before
            tray_enabled = call("tools/call", {"name": "organizer_tray_settings_update", "arguments": {
                "expected_revision": tray_before["structuredContent"]["revision"], "autostart": True, "show_counter": True, "open_mode": "centered"}})
            assert not tray_enabled["isError"] and tray_enabled["structuredContent"]["native_applied"] and tray_enabled["structuredContent"]["persisted"] and tray_enabled["structuredContent"]["active"] and tray_enabled["structuredContent"]["autostart_registered"], tray_enabled
            assert tray_registered.wait(5), "Native indicator did not register with the private tray host"
            item_service, item_path = tray_fixture["item"]
            item_status = native_bus.call_sync(item_service, item_path, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", "Status")), GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, 5000, None)
            assert item_status.unpack()[0] == "Active", item_status
            tray_entry = Path(product.tray_autostart_datei())
            tray_config = Path(product.tray_datei())
            assert tray_entry.is_relative_to(Path(temporary.name)) and tray_config.is_relative_to(Path(temporary.name))
            assert tray_entry.is_file() and product.tray_autostart_registriert()
            assert json.loads(tray_config.read_text())["autostart"] is True
            tray_book = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))["einstellungen"]["allgemein"]["tray"]
            assert tray_book["aktiv"] and tray_book["autostart"] and tray_book["startMinimiert"]
            tray_current = call("tools/call", {"name": "organizer_tray_settings_read"})
            tray_disabled = call("tools/call", {"name": "organizer_tray_settings_update", "arguments": {
                "expected_revision": tray_current["structuredContent"]["revision"], "enabled": False}})
            assert not tray_disabled["isError"] and tray_disabled["structuredContent"]["native_applied"] and not tray_disabled["structuredContent"]["active"] and not tray_disabled["structuredContent"]["autostart_registered"], tray_disabled
            assert not tray_entry.exists()
        finally:
            tray_cleaned = threading.Event()
            def clean_private_tray_host():
                try:
                    window._tray_einstellungen_setzen(tray_fixture["original"])
                    native_bus.unregister_object(tray_fixture["registration"])
                    if tray_fixture.get("owned"):
                        native_bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ReleaseName",
                            GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)), None, Gio.DBusCallFlags.NONE, 5000, None)
                finally:
                    if tray_fixture["previous_desktop"] is None: os.environ.pop("XDG_CURRENT_DESKTOP", None)
                    else: os.environ["XDG_CURRENT_DESKTOP"] = tray_fixture["previous_desktop"]
                    tray_cleaned.set()
                return False
            product.GLib.idle_add(clean_private_tray_host)
            assert tray_cleaned.wait(5)
        privacy_before = call("tools/call", {"name": "organizer_reminder_privacy_read"})
        assert not privacy_before["isError"] and privacy_before["structuredContent"]["native_state"]["projection_verified"], privacy_before
        privacy_record_keys = ("notizen", "kontakte", "termine", "aufgaben", "jahrestage")
        privacy_book_before = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        privacy_records = {key: privacy_book_before[key] for key in privacy_record_keys}
        privacy_allowed = call("tools/call", {"name": "organizer_reminder_privacy_update", "arguments": {
            "expected_revision": privacy_before["structuredContent"]["revision"], "allow_when_locked": True, "include_confidential": False}})
        assert not privacy_allowed["isError"] and privacy_allowed["structuredContent"]["persisted"], privacy_allowed
        assert privacy_allowed["structuredContent"]["native_state"]["projection_present"] and privacy_allowed["structuredContent"]["native_state"]["projection_verified"], privacy_allowed
        privacy_projection_path = Path(product.erinnerungsdaten_datei())
        assert privacy_projection_path.is_relative_to(Path(temporary.name))
        privacy_book = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        privacy_projection = json.loads(privacy_projection_path.read_text())
        assert not any(key in privacy_projection for key in ("notizen", "kontakte", "eigenesProfil"))
        assert {key: privacy_book[key] for key in privacy_record_keys} == privacy_records
        assert privacy_book["einstellungen"]["sicherheit"]["hintergrund"] == privacy_book_before["einstellungen"]["sicherheit"]["hintergrund"]
        privacy_current = call("tools/call", {"name": "organizer_reminder_privacy_read"})
        privacy_confidential = call("tools/call", {"name": "organizer_reminder_privacy_update", "arguments": {
            "expected_revision": privacy_current["structuredContent"]["revision"], "include_confidential": True}})
        assert not privacy_confidential["isError"] and privacy_confidential["structuredContent"]["native_state"]["include_confidential"], privacy_confidential
        privacy_backup = Path(str(privacy_projection_path) + ".bak")
        privacy_backup.write_text("Owned obsolete projection copy")
        privacy_tampered = call("tools/call", {"name": "organizer_reminder_privacy_read"})
        assert not privacy_tampered["isError"] and not privacy_tampered["structuredContent"]["native_state"]["projection_verified"], privacy_tampered
        privacy_revoked = call("tools/call", {"name": "organizer_reminder_privacy_update", "arguments": {
            "expected_revision": privacy_tampered["structuredContent"]["revision"], "allow_when_locked": False}})
        assert not privacy_revoked["isError"] and privacy_revoked["structuredContent"]["persisted"], privacy_revoked
        assert privacy_revoked["structuredContent"]["native_state"]["projection_verified"] and not privacy_revoked["structuredContent"]["settings"]["include_confidential"], privacy_revoked
        assert not privacy_projection_path.exists() and not privacy_backup.exists()
        stale_privacy = call("tools/call", {"name": "organizer_reminder_privacy_update", "arguments": {
            "expected_revision": privacy_tampered["structuredContent"]["revision"], "allow_when_locked": True}})
        assert stale_privacy["isError"] and stale_privacy["structuredContent"]["code"] == "conflict", stale_privacy
        contact_preferences_before = call("tools/call", {"name": "organizer_contact_settings_read"})
        assert not contact_preferences_before["isError"], contact_preferences_before
        contact_book_before = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        contact_records_keys = ("kontakte", "eigenesProfil", "jahrestage", "termine", "aufgaben")
        contact_records_before = {key: contact_book_before[key] for key in contact_records_keys}
        contact_preferences = call("tools/call", {"name": "organizer_contact_settings_update", "arguments": {
            "expected_revision": contact_preferences_before["structuredContent"]["revision"],
            "sender_address": "Owned native sender\nOwned native street 1", "sort_order": "first-name", "search_country": "France",
            "own_profile_visible": False, "photos": False, "groups_visible": False, "communication_icons": False,
            "letter_layout": "compact", "route": True, "map_service": "openstreetmap"}})
        assert not contact_preferences["isError"] and contact_preferences["structuredContent"]["persisted"], contact_preferences
        contact_book = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        contact_settings = contact_book["einstellungen"]["adressen"]
        assert contact_settings["sortierung"] == "first-name" and contact_settings["landCode"] == "" and contact_settings["briefLayout"] == "compact"
        assert contact_settings["absender"] == "Owned native sender\nOwned native street 1" and contact_settings["routeFestgelegt"] is True
        assert all(contact_settings[key] is False for key in ("eigenesProfilAn", "foto", "personengruppenAn", "sozialeSymbole"))
        assert {key: contact_book[key] for key in contact_records_keys} == contact_records_before
        assert contact_settings["kommunikation"] == contact_book_before["einstellungen"]["adressen"]["kommunikation"]
        stale_contact_preferences = call("tools/call", {"name": "organizer_contact_settings_update", "arguments": {
            "expected_revision": contact_preferences_before["structuredContent"]["revision"], "photos": True}})
        assert stale_contact_preferences["isError"] and stale_contact_preferences["structuredContent"]["code"] == "conflict", stale_contact_preferences
        trash_policy_before = call("tools/call", {"name": "organizer_trash_settings_read"})
        assert not trash_policy_before["isError"], trash_policy_before
        trash_before = contact_book["papierkorb"]
        trash_policy = call("tools/call", {"name": "organizer_trash_settings_update", "arguments": {
            "expected_revision": trash_policy_before["structuredContent"]["revision"], "enabled": False, "retention_days": 0}})
        assert not trash_policy["isError"] and trash_policy["structuredContent"]["persisted"], trash_policy
        trash_book = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        assert trash_book["einstellungen"]["papierkorb"] == {"an": False, "tage": 0}
        assert trash_book["papierkorb"] == trash_before
        assert {key: trash_book[key] for key in contact_records_keys} == contact_records_before
        stale_trash_policy = call("tools/call", {"name": "organizer_trash_settings_update", "arguments": {
            "expected_revision": trash_policy_before["structuredContent"]["revision"], "enabled": True}})
        assert stale_trash_policy["isError"] and stale_trash_policy["structuredContent"]["code"] == "conflict", stale_trash_policy
        reminder_before = call("tools/call", {"name": "organizer_notification_settings_read"})
        assert not reminder_before["isError"], reminder_before
        reminder_records_keys = ("notizen", "termine", "aufgaben", "kontakte", "gesundheit", "zeiterfassung")
        reminder_book_before = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        reminder_records = {key: reminder_book_before[key] for key in reminder_records_keys}
        reminder_children = []
        reminder_original_popen, reminder_original_program = subprocess.Popen, sys.argv[0]
        sys.argv[0] = str(ROOT / "bin/magnolie-organizer")
        def tracked_reminder_popen(*args, **kwargs):
            command = args[0] if args else kwargs.get("args")
            child = reminder_original_popen(*args, **kwargs)
            if isinstance(command, (list, tuple)) and "--wecker" in command:
                reminder_children.append(child)
                owned.append(child)
            return child
        subprocess.Popen = tracked_reminder_popen
        try:
            reminder_enabled = call("tools/call", {"name": "organizer_notification_settings_update", "arguments": {
                "expected_revision": reminder_before["structuredContent"]["revision"], "enabled": True,
                "lead_minutes": 30, "wake_from_suspend": False, "anniversaries": {"enabled": False, "lead_days": 3}}})
            assert not reminder_enabled["isError"] and reminder_enabled["structuredContent"]["persisted"], reminder_enabled
            assert reminder_enabled["structuredContent"]["native_state"] == {"backend": "session-worker", "foreground_enabled": True,
                "worker_running": True, "autostart_registered": True}, reminder_enabled
            assert reminder_enabled["structuredContent"]["wake_scheduled"] is None
            assert len(reminder_children) == 1 and reminder_children[0].poll() is None
            reminder_pid = reminder_children[0].pid
            assert Path(product.wecker_marke()).is_relative_to(Path(temporary.name))
            assert int(Path(product.wecker_marke()).read_text()) == reminder_pid and product.wecker_lebt()
            reminder_environment = dict(item.split(b"=", 1) for item in Path("/proc/%d/environ" % reminder_pid).read_bytes().split(b"\0") if b"=" in item)
            assert reminder_environment[b"HOME"] == os.environ["HOME"].encode()
            assert reminder_environment[b"DBUS_SYSTEM_BUS_ADDRESS"] == os.environ["DBUS_SESSION_BUS_ADDRESS"].encode()
            reminder_entry = Path(product.autostart_datei())
            assert reminder_entry.is_relative_to(Path(temporary.name)) and reminder_entry.is_file()
            reminder_book = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
            assert reminder_book["einstellungen"]["erinnerung"]["vorlauf"] == 30
            assert {key: reminder_book[key] for key in reminder_records_keys} == reminder_records
            stale_reminder = call("tools/call", {"name": "organizer_notification_settings_update", "arguments": {
                "expected_revision": reminder_before["structuredContent"]["revision"], "include_missed": False}})
            assert stale_reminder["isError"] and stale_reminder["structuredContent"]["code"] == "conflict", stale_reminder
            reminder_current = call("tools/call", {"name": "organizer_notification_settings_read"})
            reminder_disabled = call("tools/call", {"name": "organizer_notification_settings_update", "arguments": {
                "expected_revision": reminder_current["structuredContent"]["revision"], "enabled": False}})
            assert not reminder_disabled["isError"] and reminder_disabled["structuredContent"]["persisted"], reminder_disabled
            assert reminder_disabled["structuredContent"]["native_state"] == {"backend": "session-worker", "foreground_enabled": False,
                "worker_running": True, "autostart_registered": False}, reminder_disabled
            assert not reminder_entry.exists()
        finally:
            subprocess.Popen, sys.argv[0] = reminder_original_popen, reminder_original_program
            for child in reminder_children:
                if child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
        assert not product.wecker_lebt(), "Owned reminder worker lease was not released"
        if BACKGROUND_PROBE:
            import magnolie_hintergrund as background_product
            assert os.readlink("/proc/self/ns/net") != os.environ["MAGNOLIE_MCP_PROBE_OUTER_NETNS"]
            assert os.environ["DBUS_SYSTEM_BUS_ADDRESS"] == os.environ["DBUS_SESSION_BUS_ADDRESS"]
            for private_path in (background_product.settings_path(), background_product.autostart_path(), background_product.socket_path()):
                assert Path(private_path).is_relative_to(Path(temporary.name))
            background_before = call("tools/call", {"name": "organizer_background_permissions_read"})
            assert not background_before["isError"] and background_before["structuredContent"]["supported"], background_before
            background_record_keys = ("notizen", "termine", "aufgaben", "kontakte", "gesundheit", "zeiterfassung")
            background_book_before = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
            background_records = {key: background_book_before[key] for key in background_record_keys}
            optional_permissions = ("kde_incoming_files", "sms_phone_notifications", "phone_sms_notifications", "phone_selected_notifications", "phone_call_notifications", "phone_personal_sync_offers")
            background_handle = None
            original_popen = subprocess.Popen
            original_program = sys.argv[0]
            sys.argv[0] = str(ROOT / "bin/magnolie-organizer")
            background_log = Path(temporary.name) / "owned-background-start.log"
            background_log_handle = background_log.open("wb")
            def tracked_background_popen(*args, **kwargs):
                command = args[0] if args else kwargs.get("args")
                is_background = isinstance(command, (list, tuple)) and "--hintergrunddienst" in command
                if is_background:
                    kwargs["stdout"] = background_log_handle
                    kwargs["stderr"] = background_log_handle
                child = original_popen(*args, **kwargs)
                if is_background:
                    owned.append(child)
                return child
            subprocess.Popen = tracked_background_popen
            try:
                background_applied = call("tools/call", {"name": "organizer_background_permissions_update", "arguments": {
                    "expected_revision": background_before["structuredContent"]["revision"], "permissions": {key: False for key in optional_permissions}}})
                assert not background_applied["isError"] and background_applied["structuredContent"]["native_applied"] and background_applied["structuredContent"]["persisted"] and background_applied["structuredContent"]["running"], {"result": background_applied, "state": product.hintergrund_einstellungen_lesen(False), "launcher_log": background_log.read_text(errors="replace")[-4000:]}
                assert background_product.daemon_available()
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as daemon_connection:
                    daemon_connection.settimeout(3)
                    daemon_connection.connect(background_product.socket_path())
                    daemon_pid, daemon_uid, _daemon_gid = struct.unpack("3i", daemon_connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                assert daemon_uid == os.getuid() and daemon_pid != os.getpid()
                background_handle = os.pidfd_open(daemon_pid)
                daemon_environment = dict(item.split(b"=", 1) for item in Path("/proc/%d/environ" % daemon_pid).read_bytes().split(b"\0") if b"=" in item)
                assert daemon_environment[b"HOME"] == os.environ["HOME"].encode() and daemon_environment[b"DBUS_SYSTEM_BUS_ADDRESS"] == os.environ["DBUS_SESSION_BUS_ADDRESS"].encode()
                assert os.readlink("/proc/%d/ns/net" % daemon_pid) == os.readlink("/proc/self/ns/net")
                native_background_file = Path(background_product.settings_path())
                background_autostart_file = Path(background_product.autostart_path())
                assert native_background_file.is_relative_to(Path(temporary.name)) and background_autostart_file.is_relative_to(Path(temporary.name))
                assert native_background_file.is_file() and background_autostart_file.is_file()
                background_book = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
                book_permissions = background_book["einstellungen"]["sicherheit"]["hintergrund"]["permissions"]
                assert all(book_permissions[key] is False for key in optional_permissions)
                assert all(book_permissions[key] is True for key in ("kde_pairing", "phone_monitor", "phone_pairing_decisions"))
                assert {key: background_book[key] for key in background_record_keys} == background_records
                stale_background = call("tools/call", {"name": "organizer_background_permissions_update", "arguments": {
                    "expected_revision": background_before["structuredContent"]["revision"], "permissions": {"phone_selected_notifications": True}}})
                assert stale_background["isError"] and stale_background["structuredContent"]["code"] == "conflict", stale_background
            finally:
                try:
                    current_background = background_product.read_settings()
                    current_background.update(enabled=False, autostart=False, permissions={key: False for key in background_product.PERMISSIONS})
                    background_cleanup = product.hintergrund_einstellungen_schreiben(current_background)
                finally:
                    subprocess.Popen = original_popen
                    sys.argv[0] = original_program
                    background_log_handle.close()
                    if background_handle is not None:
                        try:
                            with selectors.DefaultSelector() as waiter:
                                waiter.register(background_handle, selectors.EVENT_READ)
                                if not waiter.select(3):
                                    signal.pidfd_send_signal(background_handle, signal.SIGTERM)
                                    if not waiter.select(3):
                                        signal.pidfd_send_signal(background_handle, signal.SIGKILL)
                                        assert waiter.select(3)
                        finally:
                            os.close(background_handle)
                assert background_cleanup.get("ok") and background_product.wait_for_daemon_release(), background_cleanup
                assert not Path(background_product.autostart_path()).exists()
        review_book_before = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        reviewed_contact = review_book_before["kontakte"][0]
        assert reviewed_contact.get("uid"), "Owned native review fixture requires its existing contact UID"
        review_file = Path(temporary.name) / "owned-native-review.vcf"
        review_file.write_text(product.vcf_schreiben([
            {"uid": reviewed_contact["uid"], "vorname": "Owned reviewed", "nachname": reviewed_contact.get("nachname", ""), "notiz": "Owned native reviewed content"},
            {"uid": "owned-native-review-new", "vorname": "Native review", "nachname": "Created", "geburtstag": "--02-29", "geburtstagJahrUnbekannt": True}]))
        review_revision = call("tools/call", {"name": "organizer_book_revision_read"})["structuredContent"]["revision"]
        staged_import = call("tools/call", {"name": "organizer_import_review_begin", "arguments": {
            "format": "vcf", "path": str(review_file), "expected_book_revision": review_revision}})
        assert not staged_import["isError"] and staged_import["structuredContent"]["contacts_total"] == 2, staged_import
        staged = staged_import["structuredContent"]
        assert json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password")) == review_book_before
        review_page = call("tools/call", {"name": "organizer_import_review_read", "arguments": {"token": staged["token"]}})
        assert not review_page["isError"] and len(review_page["structuredContent"]["plans"]) == 2, review_page
        selected_import = call("tools/call", {"name": "organizer_import_review_decide", "arguments": {
            "token": staged["token"], "expected_selection_revision": 0, "decisions": [{"index": 0, "action": "replace", "target_id": reviewed_contact["id"]}]}})
        assert not selected_import["isError"] and selected_import["structuredContent"]["unresolved_contacts"] == 0, selected_import
        imported_review = call("tools/call", {"name": "organizer_import_review_apply", "arguments": {
            "token": staged["token"], "expected_selection_revision": selected_import["structuredContent"]["selection_revision"], "expected_book_revision": review_revision}})
        assert not imported_review["isError"] and imported_review["structuredContent"]["persisted"] and imported_review["structuredContent"]["counts"]["contacts"] == 2, imported_review
        review_book_after = json.loads(product.entschluesseln(data_file.read_text(), "owned-classic-backup-password"))
        kept_contact = next(contact for contact in review_book_after["kontakte"] if contact["id"] == reviewed_contact["id"])
        assert kept_contact["uid"] == reviewed_contact["uid"] and kept_contact["vorname"] == "Owned reviewed"
        assert kept_contact.get("syncQuellen") == reviewed_contact.get("syncQuellen")
        new_review_contact = next(contact for contact in review_book_after["kontakte"] if contact["uid"] == "owned-native-review-new")
        assert new_review_contact["sync"] is False and not new_review_contact.get("baumKontakt")
        assert len([anniversary for anniversary in review_book_after["jahrestage"] if anniversary.get("kontaktId") == new_review_contact["id"]]) == 1
        for untouched in ("notizen", "termine", "aufgaben", "gesundheit", "zeiterfassung"):
            assert review_book_after[untouched] == review_book_before[untouched], untouched
        stale_review_apply = call("tools/call", {"name": "organizer_import_review_apply", "arguments": {
            "token": staged["token"], "expected_selection_revision": 1, "expected_book_revision": review_revision}})
        assert stale_review_apply["isError"] and stale_review_apply["structuredContent"]["code"] == "not_found", stale_review_apply
        records_envelope_before = data_file.read_text()
        records_book = json.loads(product.entschluesseln(records_envelope_before, "owned-classic-backup-password"))
        records_revision = call("tools/call", {"name": "organizer_book_revision_read"})["structuredContent"]["revision"]
        exported_formats = []
        for export_format, section in (("ics-termine", "termine"), ("csv-termine", "termine"), ("ics-aufgaben", "aufgaben"),
                ("ics-jahrestage", "jahrestage"), ("vcf-adressen", "kontakte"), ("ldif-adressen", "kontakte")):
            if not records_book[section]:
                continue
            export_path = Path(temporary.name) / ("owned-records-" + export_format)
            records_export = call("tools/call", {"name": "organizer_records_export", "arguments": {
                "expected_book_revision": records_revision, "format": export_format, "path": str(export_path)}})
            assert not records_export["isError"] and records_export["structuredContent"]["confirmed"], records_export
            actual_export = export_path.read_bytes()
            export_proof = records_export["structuredContent"]
            assert export_proof["bytes"] == len(actual_export) and export_proof["sha256"] == hashlib.sha256(actual_export).hexdigest()
            assert export_proof["exported_count"] > 0 and export_proof["raw_omitted_count"] is None
            assert actual_export.startswith(b"\xef\xbb\xbf") == (export_format == "csv-termine")
            import_format = "lotus" if export_format == "csv-termine" else "vcf" if export_format == "vcf-adressen" else "ldif" if export_format == "ldif-adressen" else "ics"
            import_preview = call("tools/call", {"name": "organizer_import_preview", "arguments": {"format": import_format, "path": str(export_path)}})
            assert not import_preview["isError"], import_preview
            import_proof = import_preview["structuredContent"]
            assert import_proof["sha256"] == export_proof["sha256"] and import_proof["bytes"] == len(actual_export)
            assert sum(import_proof["counts"].values()) > 0 and len(json.dumps(import_preview)) < 4096
            same_import_preview = call("tools/call", {"name": "organizer_import_preview", "arguments": {
                "format": import_format, "path": str(export_path), "expected_revision": import_proof["revision"]}})
            assert not same_import_preview["isError"], same_import_preview
            exported_formats.append(export_format)
            repeated_export = call("tools/call", {"name": "organizer_records_export", "arguments": {
                "expected_book_revision": records_revision, "format": export_format, "path": str(export_path)}})
            assert repeated_export["isError"] and repeated_export["structuredContent"]["code"] == "native_operation_failed", repeated_export
            assert export_path.read_bytes() == actual_export
        assert all(format in exported_formats for format in ("ics-termine", "csv-termine", "vcf-adressen", "ldif-adressen")), exported_formats
        protected_export = call("tools/call", {"name": "organizer_records_export", "arguments": {
            "expected_book_revision": records_revision, "format": "ics-termine", "path": str(data_file), "overwrite": True}})
        assert protected_export["isError"] and data_file.read_text() == records_envelope_before, protected_export
        large_import_path = Path(temporary.name) / "owned-large-preview.ics"
        large_import_path.write_text("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(
            "BEGIN:VEVENT\r\nUID:owned-large-preview-%d@example.invalid\r\nDTSTART:20300102T090000Z\r\nSUMMARY:Owned preview\r\nDESCRIPTION:owned-private-import-description-%s\r\nEND:VEVENT\r\n" % (index, "x" * 4096)
            for index in range(300)) + "END:VCALENDAR\r\n")
        large_import_preview = call("tools/call", {"name": "organizer_import_preview", "arguments": {"format": "ics", "path": str(large_import_path)}})
        assert not large_import_preview["isError"] and large_import_preview["structuredContent"]["bytes"] > 1024 * 1024, large_import_preview
        assert large_import_preview["structuredContent"]["counts"]["appointments"] == 300 and len(json.dumps(large_import_preview)) < 4096
        assert "owned-private-import-description" not in json.dumps(large_import_preview)
        large_import_path.write_text(large_import_path.read_text() + "\n")
        stale_import_preview = call("tools/call", {"name": "organizer_import_preview", "arguments": {
            "format": "ics", "path": str(large_import_path), "expected_revision": large_import_preview["structuredContent"]["revision"]}})
        assert stale_import_preview["isError"] and stale_import_preview["structuredContent"]["code"] == "conflict", stale_import_preview
        assert data_file.read_text() == records_envelope_before
        assert call("tools/call", {"name": "organizer_book_revision_read"})["structuredContent"]["revision"] == records_revision
        for planner_layout in ("year", "month"):
            planner_path = Path(temporary.name) / ("owned-native-planner-" + planner_layout + ".ods")
            planner_args = {"expected_book_revision": records_revision, "year": 2030, "layout": planner_layout,
                "path": str(planner_path), **({"month": 2} if planner_layout == "month" else {})}
            for attempt in range(10):
                planner_result = call("tools/call", {"name": "organizer_planner_export", "arguments": planner_args})
                if not planner_result["isError"]:
                    break
                assert planner_result["structuredContent"]["code"] == "native_busy", planner_result
                time.sleep(0.1)
            assert not planner_result["isError"] and planner_result["structuredContent"]["confirmed"], planner_result
            actual_planner = planner_path.read_bytes()
            assert planner_result["structuredContent"]["bytes"] == len(actual_planner)
            assert planner_result["structuredContent"]["sha256"] == hashlib.sha256(actual_planner).hexdigest()
            with zipfile.ZipFile(planner_path) as archive:
                assert archive.read("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet"
                assert b"office:spreadsheet" in archive.read("content.xml")
            planner_exists = call("tools/call", {"name": "organizer_planner_export", "arguments": planner_args})
            assert planner_exists["isError"] and planner_path.read_bytes() == actual_planner, planner_exists
        for sheet_tool, options in (
                ("organizer_contacts_spreadsheet_export", {"fields": ["vorname", "nachname", "emails"]}),
                ("organizer_health_spreadsheet_export", {"table": "vital", "mode": "blank"}),
                ("organizer_time_spreadsheet_export", {"year": 2030, "month": 2, "days": [1, 4], "report_name": "Owned native report"})):
            sheet_path = Path(temporary.name) / ("owned-native-" + sheet_tool + ".ods")
            spreadsheet = call("tools/call", {"name": sheet_tool, "arguments": {"expected_book_revision": records_revision, "path": str(sheet_path), **options}})
            assert not spreadsheet["isError"] and spreadsheet["structuredContent"]["confirmed"], spreadsheet
            actual_sheet = sheet_path.read_bytes()
            assert spreadsheet["structuredContent"]["bytes"] == len(actual_sheet)
            assert spreadsheet["structuredContent"]["sha256"] == hashlib.sha256(actual_sheet).hexdigest()
            with zipfile.ZipFile(sheet_path) as archive:
                assert archive.read("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet"
                assert b"office:spreadsheet" in archive.read("content.xml")
        document_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        document_socket = str(Path(temporary.name) / "owned-document.sock")
        document_listener.bind(document_socket); document_listener.listen(1); document_listener.settimeout(5)
        document_viewer = Path(temporary.name) / "owned-document-viewer.py"
        document_viewer.write_text("import hashlib, socket, sys\nfrom pathlib import Path\n"
            "with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:\n"
            "    connection.connect(" + repr(document_socket) + ")\n"
            "    connection.sendall(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest().encode())\n")
        (own_apps / "owned-document-viewer.desktop").write_text(
            '[Desktop Entry]\nType=Application\nName=Owned document viewer\n'
            'Exec="' + sys.executable + '" "' + str(document_viewer) + '" %f\nTerminal=false\nMimeType=application/vnd.oasis.opendocument.spreadsheet;\n')
        (Path(os.environ["XDG_CONFIG_HOME"]) / "mimeapps.list").write_text(
            "[Default Applications]\nimage/png=owned-attachment-viewer.desktop;\napplication/vnd.oasis.opendocument.spreadsheet=owned-document-viewer.desktop;\n")
        old_document_desktop = os.environ.get("XDG_CURRENT_DESKTOP"); os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
        try:
            opened_document_path = Path(temporary.name) / "owned-opened-planner.ods"
            opened_document = call("tools/call", {"name": "organizer_planner_export", "arguments": {
                "expected_book_revision": records_revision, "year": 2030, "layout": "year", "path": str(opened_document_path), "open_with_registered_app": True}})
            assert not opened_document["isError"] and opened_document["structuredContent"]["confirmed"] and opened_document["structuredContent"]["launcher_accepted"] is True, opened_document
            connection, _address = document_listener.accept()
            with connection:
                connection.settimeout(3)
                assert connection.recv(128).decode() == opened_document["structuredContent"]["sha256"]
        finally:
            document_listener.close()
            if old_document_desktop is None: os.environ.pop("XDG_CURRENT_DESKTOP", None)
            else: os.environ["XDG_CURRENT_DESKTOP"] = old_document_desktop
        letter_path = Path(temporary.name) / "owned-native-letter.fodt"
        native_letter = call("tools/call", {"name": "organizer_letter_export", "arguments": {
            "expected_book_revision": records_revision, "recipient_type": "own_profile", "layout": "din5008-a",
            "sender_address": "Owned sender\nOwn Street 2", "path": str(letter_path)}})
        assert not native_letter["isError"] and native_letter["structuredContent"]["confirmed"] and native_letter["structuredContent"]["format"] == "fodt", native_letter
        letter_bytes = letter_path.read_bytes()
        assert native_letter["structuredContent"]["bytes"] == len(letter_bytes) and native_letter["structuredContent"]["sha256"] == hashlib.sha256(letter_bytes).hexdigest()
        letter_text = "".join(ET.fromstring(letter_bytes).itertext())
        assert "Owned Profile" in letter_text and "Owned profile street 2" in letter_text
        assert data_file.read_text() == records_envelope_before
        password_before = call("tools/call", {"name": "organizer_password_status"})
        # Observe and cancel only the real print dialog of this private Xvfb book.
        # No physical printer is selected and no print job is submitted.
        check_print_dialog(records_revision)
        assert data_file.read_text() == records_envelope_before
        assert not password_before["isError"] and password_before["structuredContent"]["encrypted"] and password_before["structuredContent"]["matches_book"], password_before
        password_state = password_before["structuredContent"]
        original_envelope = data_file.read_text()
        original_plain = product.entschluesseln(original_envelope, "owned-classic-backup-password")
        assert password_state["state_revision"] == hashlib.sha256(original_envelope.encode()).hexdigest()
        stale_password = call("tools/call", {"name": "organizer_password_set", "arguments": {
            "expected_book_revision": password_state["book_revision"], "expected_state_revision": "0" * 64,
            "new_password": "owned-mcp-password"}})
        assert stale_password["isError"] and stale_password["structuredContent"]["code"] == "conflict", stale_password
        assert data_file.read_text() == original_envelope
        password_changed = call("tools/call", {"name": "organizer_password_set", "arguments": {
            "expected_book_revision": password_state["book_revision"], "expected_state_revision": password_state["state_revision"],
            "new_password": "owned-mcp-password"}})
        assert not password_changed["isError"] and password_changed["structuredContent"]["persisted"] and password_changed["structuredContent"]["verified"], password_changed
        assert product.entschluesseln(data_file.read_text(), "owned-mcp-password") == original_plain
        assert "owned-mcp-password" not in json.dumps(password_changed) and "owned-mcp-password" not in original_plain
        changed_state = password_changed["structuredContent"]
        password_removed = call("tools/call", {"name": "organizer_password_remove", "arguments": {
            "expected_book_revision": changed_state["stored_book_revision"], "expected_state_revision": changed_state["state_revision"]}})
        assert not password_removed["isError"] and password_removed["structuredContent"]["verified"] and not password_removed["structuredContent"]["encrypted"], password_removed
        assert data_file.read_text() == original_plain
        removed_state = password_removed["structuredContent"]
        password_reenabled = call("tools/call", {"name": "organizer_password_set", "arguments": {
            "expected_book_revision": removed_state["stored_book_revision"], "expected_state_revision": removed_state["state_revision"],
            "new_password": "owned-classic-backup-password"}})
        assert not password_reenabled["isError"] and password_reenabled["structuredContent"]["verified"] and password_reenabled["structuredContent"]["encrypted"], password_reenabled
        assert product.entschluesseln(data_file.read_text(), "owned-classic-backup-password") == original_plain
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        selector.close()
        state["passed"] = True
    except BaseException as error:
        state["error"] = traceback.format_exc(limit=6)
        print(state["error"], file=sys.stderr, flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        def stop_window():
            for dialog in product.Gtk.Window.list_toplevels():
                if isinstance(dialog, product.Gtk.Dialog):
                    dialog.response(product.Gtk.ResponseType.CANCEL)
                    dialog.destroy()
            if product._KDECONNECT_BACKEND is not None or window._telefon is not None or window._baumdienst is not None:
                state["passed"] = False
                state["error"] = "An unrelated transport started inside the isolated book fixture"
            window.ansicht.terminate_web_process()
            window.destroy()
            return False
        product.GLib.idle_add(stop_window)


worker = None
def start_client():
    global worker
    if getattr(window, "_mcp_server", None) is None:
        return True
    state["started"] = True
    worker = threading.Thread(target=client, name="owned-mcp-native-probe")
    worker.start()
    return False


def deadline():
    state["error"] = "Native MCP probe exceeded 90 seconds"
    for dialog in product.Gtk.Window.list_toplevels():
        if isinstance(dialog, product.Gtk.Dialog):
            dialog.response(product.Gtk.ResponseType.CANCEL)
            dialog.destroy()
    for process in owned:
        if process.poll() is None:
            process.terminate()
    window.destroy()
    return False


product.GLib.timeout_add(50, start_client)
product.GLib.timeout_add_seconds(90, deadline)
try:
    product.Gtk.main()
finally:
    if worker is not None:
        worker.join(timeout=5)
    for process in owned:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    try:
        stop_private_secret_service()
    except BaseException:
        state["passed"] = False
        state["error"] = (state.get("error") or "") + "\nPrivate service cleanup:\n" + traceback.format_exc(limit=4)
    print("Native MCP fixture state:", json.dumps(state), flush=True)
    temporary.cleanup()
assert state["passed"], state
if os.environ.get("MAGNOLIE_MCP_PROBE_WASTE_ONLY") == "1":
    print("Native MCP WASTE PASS: actual CSV/ICS parsing, mapping/source/book revisions, pre-change checkpoints, durable readback, replay and stable UID correction")
elif os.environ.get("MAGNOLIE_MCP_PROBE_PRINT_ONLY") == "1":
    print("Native MCP PRINT PASS: real private GTK system print dialog observed/cancelled, correlated return, unchanged book revision")
else:
    print("Native MCP PASS: GTK/WebKit/worker/stdio/FileReader, durable entities and attachment upload/remove/restore, recovery and bounded large UTF-8 reads")
