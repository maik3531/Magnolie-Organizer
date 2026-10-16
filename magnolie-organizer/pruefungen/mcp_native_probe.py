#!/usr/bin/env python3
"""Bounded Xvfb probe of the real source GTK/WebKit/native save/MCP stdio path."""
import importlib.machinery
import importlib.util
import base64
import hashlib
import json
import os
from pathlib import Path
import selectors
import struct
import subprocess
import sys
import tempfile
import threading
import traceback
import zlib

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
    "erinnerung": {"an": False, "wecken": False, "jahrestage": {"an": False}}}}))
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
        if os.environ.get("MAGNOLIE_MCP_PROBE_RESTORE_REPAIR") == "1":
            restore_point = call("tools/call", {"name": "organizer_recovery_snapshot_create"})
            assert not restore_point["isError"], restore_point
            restore_id = restore_point["structuredContent"]["snapshot"]["id"]
            before_restore = call("tools/call", {"name": "organizer_note_read", "arguments": {"id": note_id, "fields": ["id"]}})
            changed_for_restore = call("tools/call", {"name": "organizer_note_update", "arguments": {
                "id": note_id, "expected_revision": before_restore["structuredContent"]["revision"], "text": "Owned later native state"}})
            assert not changed_for_restore["isError"] and changed_for_restore["structuredContent"]["persisted"], changed_for_restore
            restore_done = threading.Event()
            restore_result = {}

            def restore_with_projection_failure():
                original_projection = window._erinnerungsprojektion_aktualisieren
                original_reply = window.antwort
                def failed_projection():
                    raise OSError("Owned native restore projection failure")
                def reply(callback, *values):
                    if callback == "App.journalWiederhergestellt":
                        value = values[0]
                        restore_result.update({key: value.get(key) for key in ("ok", "committed", "repairPending")})
                    return original_reply(callback, *values)
                window._erinnerungsprojektion_aktualisieren = failed_projection
                window.antwort = reply
                try:
                    window._journal_wiederherstellen(restore_id, ["notes"], "replace")
                finally:
                    window._erinnerungsprojektion_aktualisieren = original_projection
                    window.antwort = original_reply
                    restore_done.set()
                return False

            product.GLib.idle_add(restore_with_projection_failure)
            assert restore_done.wait(15), "Native restore did not complete"
            assert restore_result == {"ok": True, "committed": True, "repairPending": True}, restore_result
            assert next(item for item in json.loads(data_file.read_text())["notizen"] if item["id"] == note_id)["text"] == large_text
            restored_gui = call("tools/call", {"name": "organizer_content_read", "arguments": {"section": "notizen", "id": note_id, "path": ["text"], "limit": 5}})
            assert not restored_gui["isError"] and restored_gui["structuredContent"]["total_bytes"] == len(large_text.encode("utf8")), "Native GUI did not adopt the committed restore"
            assert base64.b64decode(restored_gui["structuredContent"]["data"]) == large_text.encode("utf8")[:5]
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        selector.close()
        state["passed"] = True
    except BaseException as error:
        state["error"] = traceback.format_exc(limit=6)
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
print("Native MCP PASS: GTK/WebKit/worker/stdio/FileReader, durable entities and attachment upload/remove/restore, recovery and bounded large UTF-8 reads")
