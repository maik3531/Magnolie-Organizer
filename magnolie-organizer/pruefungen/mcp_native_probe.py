#!/usr/bin/env python3
"""Bounded Xvfb probe of the real source GTK/WebKit/native save/MCP stdio path."""
import importlib.machinery
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import threading

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
sys.path.insert(0, str(ROOT / "bin"))
profile = Path(os.environ["XDG_DATA_HOME"]) / "magnolie-organizer"
profile.mkdir(mode=0o700)
data_file = profile / "daten.json"
data_file.write_text(json.dumps({"version": 6, "notizen": [{"id": "owned-native-fixture", "titel": "Owned fixture",
    "text": "No user data", "html": "No user data"}], "aufgaben": [{"id": "owned-native-series",
    "uid": "owned-native-series-uid", "titel": "Owned series fixture", "startDatum": "2026-01-01",
    "faellig": "2026-01-01", "startZeit": "08:00", "faelligZeit": "09:00", "icsRoundtrip": [
      "BEGIN:VTODO", "UID:owned-native-series-uid", "DTSTART:20260101T080000Z", "DUE:20260101T090000Z",
      "RRULE:FREQ=DAILY", "END:VTODO"]}], "einstellungen": {
    "allgemein": {"wiederherstellungsintervall": "manual", "tray": {"aktiv": False}},
    "update": {"automatisch": False}, "sync": {"beimStart": False}}}))
loader = importlib.machinery.SourceFileLoader("magnolie_mcp_native_product", str(ROOT / "bin/magnolie-organizer"))
spec = importlib.util.spec_from_loader(loader.name, loader)
product = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = product
loader.exec_module(product)
assert product.GTK_OK and product.WEBKIT_OK
product._REGIONAL = product.regional_einstellungen(dict(product._REGIONAL, timeZone="UTC", language="en", formatLocale="en-GB"))
state = {"started": False, "passed": False, "error": None, "transport_blocked": False}
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
            process.stdin.write(json.dumps(value).encode() + b"\n")
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
        result = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "owned-native-fixture", "version": "1"}})
        assert result["serverInfo"]["name"] == "magnolie-organizer"
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = call("tools/list")["tools"]
        assert any(tool["name"] == "organizer_note_create" for tool in tools)
        status = call("tools/call", {"name": "organizer_status"})
        assert status["structuredContent"]["ready"] and not status["structuredContent"]["locked"], status
        notes = call("tools/call", {"name": "organizer_data_read", "arguments": {"section": "notizen"}})
        assert any(note["id"] == "owned-native-fixture" for note in notes["structuredContent"]["entries"])
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
        stale = call("tools/call", {"name": "organizer_note_update", "arguments": {"id": note_id,
            "expected_revision": revision["structuredContent"]["revision"], "title": "Do not overwrite"}})
        assert stale["isError"] and stale["structuredContent"]["code"] == "conflict", stale
        current = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id}})
        deleted = call("tools/call", {"name": "organizer_note_delete", "arguments": {"id": note_id,
            "expected_revision": current["structuredContent"]["revision"]}})
        assert not deleted["isError"] and deleted["structuredContent"]["persisted"], deleted
        assert not any(item["id"] == note_id for item in json.loads(data_file.read_text())["notizen"])
        restored = call("tools/call", {"name": "organizer_trash_restore", "arguments": {
            "id": deleted["structuredContent"]["trash_id"]}})
        assert not restored["isError"] and restored["structuredContent"]["persisted"], restored
        assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["titel"] == "Native revised fixture"
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        selector.close()
        state["passed"] = True
    except BaseException as error:
        state["error"] = str(error)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        def stop_window():
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
            process.kill()
            process.wait(timeout=3)
    print("Native MCP fixture state:", json.dumps(state), flush=True)
    temporary.cleanup()
assert state["passed"], state
print("Native MCP PASS: real GTK/WebKit/recurrence worker, stdio, durable note/task CRUD, native instance identity, trash restore and cleanup")
