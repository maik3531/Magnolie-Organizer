import importlib.util
import json
import os
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "bin" / "magnolie_akonadi.py"
SPEC = importlib.util.spec_from_file_location("magnolie_akonadi_test", PATH)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def helper(tmp_path, body):
    path = tmp_path / "fake helper; not shell syntax"
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def fixed_helper(tmp_path, response):
    return helper(tmp_path, "import json, sys\njson.load(sys.stdin)\n"
                  "json.dump(%r, sys.stdout)\n" % response)


def event(uid, title="Test"):
    return "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:%s\r\nSUMMARY:%s\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n" % (uid, title)


def card(uid, name="Test"):
    return "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:%s\r\nFN:%s\r\nEND:VCARD\r\n" % (uid, name)


def item(item_id, revision, uid, content):
    return {"id": item_id, "revision": revision, "gid": uid, "content": content}


def test_discovery_precedence_and_missing(tmp_path, monkeypatch):
    executable = fixed_helper(tmp_path, {"ok": True})
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", executable)
    assert m.discover_helper() == executable
    assert m.discover_helper(str(tmp_path / "missing")) is None
    monkeypatch.delenv("MAGNOLIE_AKONADI_HELPER")
    monkeypatch.setattr(m, "HELPER_LOCATIONS", ())
    monkeypatch.setenv("PATH", "")
    assert m.discover_helper() is None
    with pytest.raises(m.AkonadiUnavailable):
        m.helper_request({"command": "status"})


def test_flatpak_never_uses_an_unbridged_helper(tmp_path, monkeypatch):
    executable = fixed_helper(tmp_path, {"ok": True})
    monkeypatch.setenv("FLATPAK_ID", "io.gitlab.maik3531.MagnolieOrganizer")
    monkeypatch.setenv("MAGNOLIE_AKONADI_HELPER", executable)
    assert m.discover_helper(executable) is None
    with pytest.raises(m.AkonadiUnavailable):
        m.helper_request({"command": "status"})


def test_appimage_helper_environment_keeps_host_and_session_values(tmp_path, monkeypatch):
    appdir = tmp_path / "appdir"
    appdir.mkdir()
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "Organizer.AppImage"))
    monkeypatch.setenv("APPDIR", str(appdir))
    monkeypatch.setenv("PATH", str(appdir / "usr/bin") + ":/usr/bin")
    monkeypatch.setenv("LD_LIBRARY_PATH", str(appdir / "usr/lib") + ":/usr/lib")
    monkeypatch.setenv("PYTHONHOME", str(appdir / "usr"))
    monkeypatch.setenv("GI_TYPELIB_PATH", str(appdir / "usr/lib/girepository-1.0"))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("MAGNOLIE_TEST_SENTINEL", "keep")
    environment = m._helper_environment()
    assert environment["PATH"] == "/usr/bin"
    assert environment["LD_LIBRARY_PATH"] == "/usr/lib"
    assert "PYTHONHOME" not in environment and "GI_TYPELIB_PATH" not in environment
    assert environment["DBUS_SESSION_BUS_ADDRESS"].endswith("/bus")
    assert environment["MAGNOLIE_TEST_SENTINEL"] == "keep"


def test_status_validation_and_provider_shape(tmp_path):
    executable = fixed_helper(tmp_path, {
        "ok": True,
        "calendars": [{"collection": 12, "name": "Work",
                       "rights": ["read", "write"], "generation": 7,
                       "instance": "default"}],
        "addressbooks": [{"collection": 3, "name": "People",
                          "rights": "read", "generation": 9,
                          "instance": "default"}],
    })
    result = m.status(executable)
    assert result["calendars"] == [{
        "uid": "akonadi-calendar:12", "source": "akonadi", "name": "Work",
        "rights": ["read", "write"], "generation": 7,
        "instance": "default"}]
    assert result["addressbooks"][0]["uid"] == "akonadi-addressbook:3"


@pytest.mark.parametrize("response", [
    [], {"ok": "yes"}, {"ok": True, "error": "impossible"},
    {"ok": False}, {"ok": False, "error": ""},
])
def test_malformed_response_objects(tmp_path, response):
    executable = fixed_helper(tmp_path, response)
    with pytest.raises(m.AkonadiProtocolError):
        m.helper_request({"command": "status"}, executable)


def test_malformed_json_duplicate_fields_and_helper_error(tmp_path):
    malformed = helper(tmp_path, "import sys\nsys.stdin.read()\nsys.stdout.write('{')\n")
    with pytest.raises(m.AkonadiProtocolError):
        m.helper_request({}, malformed)
    duplicate = helper(tmp_path, "import sys\nsys.stdin.read()\nsys.stdout.write('{\"ok\":true,\"ok\":true}')\n")
    with pytest.raises(m.AkonadiProtocolError):
        m.helper_request({}, duplicate)
    failed = fixed_helper(tmp_path, {"ok": False, "error": "permission denied"})
    with pytest.raises(m.AkonadiError, match="permission denied"):
        m.helper_request({}, failed)


def test_timeout_and_oversized_response(tmp_path, monkeypatch):
    sleeper = helper(tmp_path, "import time\ntime.sleep(2)\n")
    with pytest.raises(m.AkonadiError, match="timed out"):
        m.helper_request({}, sleeper, timeout=0.05)
    monkeypatch.setattr(m, "MAX_RESPONSE", 100)
    oversized = helper(tmp_path, "import sys\nsys.stdin.read()\nsys.stdout.write('x' * 101)\n")
    with pytest.raises(m.AkonadiProtocolError, match="exceeds"):
        m.helper_request({}, oversized)


def test_request_limit_and_no_shell_or_arguments(tmp_path, monkeypatch):
    marker = tmp_path / "shell-ran"
    executable = fixed_helper(tmp_path, {"ok": True})
    assert m.helper_request({"value": "$(touch %s)" % marker}, executable) == {"ok": True}
    assert not marker.exists()
    monkeypatch.setattr(m, "MAX_REQUEST", 20)
    with pytest.raises(ValueError, match="16 MiB"):
        m.helper_request({"value": "x" * 30}, executable)


@pytest.mark.parametrize("kind,uid", [
    ("calendar", "akonadi-addressbook:1"),
    ("addressbook", "akonadi-addressbook:"),
    ("addressbook", "akonadi-addressbook:-1"),
    ("addressbook", "akonadi-addressbook:0"),
    ("addressbook", "akonadi-addressbook:01"),
    ("other", "akonadi-calendar:1"),
])
def test_prefixed_uid_validation(kind, uid):
    with pytest.raises(ValueError):
        m.AkonadiClient(kind, uid, "/unused")


def test_complete_snapshot_cache_and_unfolded_vcard_uid(tmp_path):
    content = card("person-\r\n 1")
    executable = fixed_helper(tmp_path, {
        "ok": True, "complete": True,
        "items": [item(8, 2, "person-1", content)],
    })
    client = m.AkonadiClient("addressbook", "akonadi-addressbook:4", executable)
    assert client.contact_texts() == [content]
    assert client.contact_texts() == [content]
    assert client.exists("person-1")
    with pytest.raises(ValueError):
        client.event_texts()


@pytest.mark.parametrize("items", [
    [item(1, 1, "one", event("one")), item(1, 2, "two", event("two"))],
    [item(1, 1, "", event(""))],
    [item(1, 1, "wrong", event("content"))],
])
def test_snapshot_rejects_duplicate_empty_or_inconsistent_ids(tmp_path, items):
    executable = fixed_helper(tmp_path, {"ok": True, "complete": True, "items": items})
    client = m.AkonadiClient("calendar", "akonadi-calendar:2", executable)
    with pytest.raises(m.AkonadiProtocolError):
        client.event_texts()


def test_calendar_snapshot_keeps_detached_instances_read_only(tmp_path):
    first = event("series", "Master")
    detached = event("series", "Exception").replace(
        "SUMMARY:Exception", "RECURRENCE-ID:20260902T100000Z\r\nSUMMARY:Exception")
    executable = fixed_helper(tmp_path, {"ok": True, "complete": True,
        "items": [item(1, 1, "series", first), item(2, 1, "series", detached)]})
    client = m.AkonadiClient("calendar", "akonadi-calendar:2", executable)
    assert client.event_texts() == [first, detached]
    with pytest.raises(ValueError, match="read only"):
        client.modify("series", first)
    with pytest.raises(ValueError, match="read only"):
        client.delete("series")


def test_incomplete_snapshot_is_rejected(tmp_path):
    executable = fixed_helper(tmp_path, {"ok": True, "complete": False, "items": []})
    with pytest.raises(m.AkonadiProtocolError, match="incomplete"):
        m.AkonadiClient("calendar", "akonadi-calendar:2", executable).event_texts()


def test_mapping_crud_and_revision_refresh(tmp_path):
    log = tmp_path / "requests.jsonl"
    initial = event("meeting", "Old")
    created = event("new")
    modified = event("meeting", "New")
    script = """import json, sys
request = json.load(sys.stdin)
with open(%r, "a", encoding="utf-8") as stream:
    stream.write(json.dumps(request) + "\\n")
command = request["command"]
if command == "snapshot":
    response = {"ok": True, "complete": True, "items": [%r]}
elif command == "create":
    response = {"ok": True, "item": %r}
elif command == "modify":
    response = {"ok": True, "item": %r}
else:
    response = {"ok": True}
json.dump(response, sys.stdout)
""" % (str(log), item(10, 4, "meeting", initial),
       item(20, 1, "new", created), item(11, 5, "meeting", modified))
    executable = helper(tmp_path, script)
    client = m.AkonadiClient("calendar", "akonadi-calendar:6", executable)
    assert client.event_texts() == [initial]
    assert client.create(created) == "new" and client.exists("new")
    client.modify("meeting", modified)
    client.delete("meeting")
    assert not client.exists("meeting")
    requests = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [request["command"] for request in requests] == [
        "snapshot", "create", "modify", "delete"]
    assert requests[2]["id"] == 10 and requests[2]["revision"] == 4
    assert requests[3]["id"] == 11 and requests[3]["revision"] == 5
    assert all(request["kind"] == "calendar" and request["collection"] == 6
               for request in requests)


def test_crud_rejects_unknown_duplicate_and_uid_change(tmp_path):
    executable = fixed_helper(tmp_path, {
        "ok": True, "complete": True,
        "items": [item(1, 1, "known", card("known"))],
    })
    client = m.AkonadiClient("addressbook", "akonadi-addressbook:1", executable)
    client.contact_texts()
    with pytest.raises(ValueError, match="already exists"):
        client.create(card("known"))
    with pytest.raises(KeyError):
        client.delete("unknown")
    with pytest.raises(ValueError, match="does not match"):
        client.modify("known", card("changed"))
