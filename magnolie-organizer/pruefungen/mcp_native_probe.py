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
import subprocess
import sys
import tempfile
import threading
import traceback

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
    ], "einstellungen": {
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
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXb8AAAAASUVORK5CYII=")
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
