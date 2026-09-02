#!/usr/bin/env python3
"""Isolated adapter for the optional Magnolie Akonadi helper."""

import json
import os
import selectors
import shutil
import subprocess
import time


MAX_REQUEST = 16 * 1024 * 1024
MAX_RESPONSE = 64 * 1024 * 1024
MAX_CONTENT = 16 * 1024 * 1024
MAX_UID = 4096
MAX_LINE = 256 * 1024
DEFAULT_TIMEOUT = 15.0
HELPER_NAME = "magnolie-akonadi-helper"
HELPER_LOCATIONS = (
    "/usr/libexec/magnolie-organizer/magnolie-akonadi-helper",
    "/usr/lib/magnolie-organizer/magnolie-akonadi-helper",
)
KINDS = {
    "calendar": "akonadi-calendar:",
    "addressbook": "akonadi-addressbook:",
}


class AkonadiError(RuntimeError):
    """The helper failed or violated its protocol."""


class AkonadiUnavailable(AkonadiError):
    """No usable helper executable was found."""


class AkonadiProtocolError(AkonadiError):
    """The helper sent invalid data."""


def _executable(candidate, use_path=False):
    if not isinstance(candidate, str) or not candidate or "\0" in candidate:
        return None
    resolved = shutil.which(candidate) if use_path or os.sep not in candidate else candidate
    if not resolved:
        return None
    resolved = os.path.abspath(resolved)
    return resolved if os.path.isfile(resolved) and os.access(resolved, os.X_OK) else None


def discover_helper(explicit=None):
    """Return the first usable helper according to the documented precedence."""
    if os.environ.get("FLATPAK_ID"):
        return None
    if explicit is not None:
        return _executable(explicit, use_path=True)
    configured = os.environ.get("MAGNOLIE_AKONADI_HELPER")
    if configured:
        found = _executable(configured, use_path=True)
        if found:
            return found
    for location in HELPER_LOCATIONS:
        found = _executable(location)
        if found:
            return found
    return _executable(HELPER_NAME, use_path=True)


def _helper_environment():
    environment = os.environ.copy()
    appdir = environment.get("APPDIR")
    if not appdir and environment.get("APPIMAGE"):
        python_home = environment.get("PYTHONHOME")
        if python_home and os.path.basename(python_home) == "usr":
            appdir = os.path.dirname(python_home)
    if not appdir:
        return environment
    appdir = os.path.realpath(appdir)

    def bundled(path):
        try:
            return os.path.commonpath((appdir, os.path.realpath(path))) == appdir
        except (TypeError, ValueError, OSError):
            return False

    for name in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "GI_TYPELIB_PATH",
                 "XDG_DATA_DIRS"):
        values = [value for value in environment.get(name, "").split(os.pathsep)
                  if value and not bundled(value)]
        if values:
            environment[name] = os.pathsep.join(values)
        else:
            environment.pop(name, None)
    for name in ("PYTHONHOME", "GIO_MODULE_DIR", "OPENSSL_CONF",
                 "OPENSSL_MODULES", "SSL_CERT_FILE"):
        if bundled(environment.get(name)):
            environment.pop(name, None)
    return environment


def _json_object(raw):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AkonadiProtocolError("duplicate JSON response field")
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=unique_object)
    except AkonadiProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AkonadiProtocolError("malformed helper response") from error
    if not isinstance(value, dict):
        raise AkonadiProtocolError("helper response must be an object")
    if type(value.get("ok")) is not bool:
        raise AkonadiProtocolError("helper response needs a boolean ok field")
    if value["ok"]:
        if "error" in value:
            raise AkonadiProtocolError("successful helper response contains error")
        return value
    error = value.get("error")
    if (not isinstance(error, str) or not error or error != error.strip()
            or len(error.encode("utf-8")) > 8192 or "\0" in error):
        raise AkonadiProtocolError("invalid helper error response")
    raise AkonadiError(error)


def helper_request(request, helper=None, timeout=DEFAULT_TIMEOUT):
    """Run one helper process and exchange exactly one JSON request/response."""
    executable = discover_helper(helper)
    if not executable:
        raise AkonadiUnavailable("Akonadi helper is not available")
    if not isinstance(request, dict):
        raise ValueError("helper request must be an object")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be positive")
    try:
        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as error:
        raise ValueError("helper request is not JSON serializable") from error
    if len(payload) > MAX_REQUEST:
        raise ValueError("helper request exceeds 16 MiB")

    try:
        process = subprocess.Popen(
            [executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False, close_fds=True,
            env=_helper_environment())
    except OSError as error:
        raise AkonadiUnavailable("could not start Akonadi helper") from error

    output = bytearray()
    sent = 0
    deadline = time.monotonic() + float(timeout)
    selector = selectors.DefaultSelector()
    try:
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)
        stdout_open = True
        while stdout_open:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired([executable], timeout)
            events = selector.select(remaining)
            if not events and process.poll() is None:
                raise subprocess.TimeoutExpired([executable], timeout)
            for key, mask in events:
                if key.fileobj is process.stdin and mask & selectors.EVENT_WRITE:
                    try:
                        written = os.write(process.stdin.fileno(), payload[sent:])
                    except BrokenPipeError:
                        written = 0
                        sent = len(payload)
                    sent += written
                    if sent == len(payload):
                        selector.unregister(process.stdin)
                        process.stdin.close()
                elif key.fileobj is process.stdout and mask & selectors.EVENT_READ:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if chunk:
                        output.extend(chunk)
                        if len(output) > MAX_RESPONSE:
                            raise AkonadiProtocolError("helper response exceeds 64 MiB")
                    else:
                        selector.unregister(process.stdout)
                        stdout_open = False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired([executable], timeout)
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        raise AkonadiError("Akonadi helper timed out") from error
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        selector.close()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.stdout and not process.stdout.closed:
            process.stdout.close()
    response = _json_object(bytes(output))
    if returncode != 0:
        raise AkonadiProtocolError(
            "Akonadi helper returned success with a failing exit status")
    return response


def _number(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AkonadiProtocolError("invalid %s" % label)
    return value


def _short_text(value, label, maximum=4096, empty=False):
    if (not isinstance(value, str) or (not empty and not value)
            or value != value.strip() or "\0" in value
            or len(value.encode("utf-8")) > maximum):
        raise AkonadiProtocolError("invalid %s" % label)
    return value


def _rights(value):
    if isinstance(value, str):
        return _short_text(value, "collection rights", empty=True)
    if not isinstance(value, list) or len(value) > 64:
        raise AkonadiProtocolError("invalid collection rights")
    result = [_short_text(item, "collection right", 128) for item in value]
    if len(result) != len(set(result)):
        raise AkonadiProtocolError("duplicate collection right")
    return result


def _collections(values, kind):
    if not isinstance(values, list) or len(values) > 100000:
        raise AkonadiProtocolError("invalid collection list")
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {
                "collection", "name", "rights", "generation", "instance"}:
            raise AkonadiProtocolError("invalid collection")
        collection = _number(value["collection"], "collection id", 1)
        if collection in seen:
            raise AkonadiProtocolError("duplicate collection id")
        seen.add(collection)
        result.append({
            "uid": KINDS[kind] + str(collection),
            "source": "akonadi",
            "name": _short_text(value["name"], "collection name"),
            "rights": _rights(value["rights"]),
            "generation": _number(value["generation"], "collection generation"),
            "instance": _short_text(value["instance"], "Akonadi instance", 256,
                                    empty=True),
        })
    return result


def status(helper=None, timeout=DEFAULT_TIMEOUT):
    response = helper_request({"command": "status"}, helper, timeout)
    if set(response) != {"ok", "calendars", "addressbooks"}:
        raise AkonadiProtocolError("invalid status response fields")
    return {
        "calendars": _collections(response["calendars"], "calendar"),
        "addressbooks": _collections(response["addressbooks"], "addressbook"),
    }


def _logical_uid(content, kind):
    if not isinstance(content, str) or not content or "\0" in content:
        raise AkonadiProtocolError("invalid item content")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_CONTENT:
        raise AkonadiProtocolError("item content is too large")
    physical = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded = []
    for line in physical:
        if len(line.encode("utf-8")) > MAX_LINE:
            raise AkonadiProtocolError("item content line is too long")
        if line.startswith((" ", "\t")):
            if not unfolded:
                raise AkonadiProtocolError("invalid folded item content")
            unfolded[-1] += line[1:]
            if len(unfolded[-1].encode("utf-8")) > MAX_LINE:
                raise AkonadiProtocolError("unfolded item line is too long")
        else:
            unfolded.append(line)
    upper = [line.upper() for line in unfolded]
    begin, end = (("BEGIN:VEVENT", "END:VEVENT") if kind == "calendar"
                  else ("BEGIN:VCARD", "END:VCARD"))
    if begin not in upper or end not in upper or upper.index(begin) >= upper.index(end):
        raise AkonadiProtocolError("item content has no valid component")
    uids = []
    inside = False
    for line in unfolded:
        marker = line.upper()
        if marker == begin:
            if inside:
                raise AkonadiProtocolError("nested item component")
            inside = True
            continue
        if marker == end:
            inside = False
            continue
        if not inside or ":" not in line:
            continue
        left, value = line.split(":", 1)
        if left.split(";", 1)[0].upper() == "UID":
            if (not value or value != value.strip() or "\0" in value
                    or len(value.encode("utf-8")) > MAX_UID
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise AkonadiProtocolError("invalid logical UID")
            uids.append(value)
    if len(uids) != 1:
        raise AkonadiProtocolError("item must contain exactly one logical UID")
    return uids[0]


def _prefixed_uid(kind, uid):
    if kind not in KINDS:
        raise ValueError("kind must be calendar or addressbook")
    if not isinstance(uid, str) or not uid.startswith(KINDS[kind]):
        raise ValueError("invalid prefixed Akonadi UID")
    suffix = uid[len(KINDS[kind]):]
    if not suffix or not suffix.isascii() or not suffix.isdigit() or (len(suffix) > 1 and suffix[0] == "0"):
        raise ValueError("invalid prefixed Akonadi UID")
    result = int(suffix)
    if result < 1:
        raise ValueError("invalid prefixed Akonadi UID")
    return result


class AkonadiClient:
    """One collection client backed by a cached complete helper snapshot."""

    def __init__(self, kind, uid, helper=None, timeout=DEFAULT_TIMEOUT,
                 generation=None, instance=None):
        self.kind = kind
        self.uid = uid
        self.collection = _prefixed_uid(kind, uid)
        self.helper = helper
        self.timeout = timeout
        if (generation is None) != (instance is None):
            raise ValueError("generation and instance must be provided together")
        self.generation = (None if generation is None else
                           _number(generation, "collection generation"))
        self.instance = (None if instance is None else
                         _short_text(instance, "Akonadi instance", 256, empty=True))
        self._items = None

    def _call(self, request):
        request.update({"kind": self.kind, "collection": self.collection})
        if self.generation is not None:
            request.update({"generation": self.generation,
                            "instance": self.instance})
        return helper_request(request, self.helper, self.timeout)

    def _snapshot(self):
        if self._items is not None:
            return
        response = self._call({"command": "snapshot"})
        if set(response) != {"ok", "complete", "items"} or response["complete"] is not True:
            raise AkonadiProtocolError("incomplete or invalid snapshot response")
        if not isinstance(response["items"], list) or len(response["items"]) > 1000000:
            raise AkonadiProtocolError("invalid snapshot items")
        items = {}
        item_ids = set()
        for raw in response["items"]:
            logical, item = self._validate_item(raw)
            if logical in items and self.kind != "calendar":
                raise AkonadiProtocolError("duplicate logical UID")
            if item["id"] in item_ids:
                raise AkonadiProtocolError("duplicate item id")
            items.setdefault(logical, []).append(item)
            item_ids.add(item["id"])
        self._items = items

    def _validate_item(self, raw, expected_uid=None):
        if not isinstance(raw, dict) or set(raw) != {"id", "revision", "gid", "content"}:
            raise AkonadiProtocolError("invalid item metadata")
        item_id = _number(raw["id"], "item id", 1)
        revision = _number(raw["revision"], "item revision")
        gid = _short_text(raw["gid"], "item gid", MAX_UID)
        logical = _logical_uid(raw["content"], self.kind)
        if gid != logical or expected_uid is not None and logical != expected_uid:
            raise AkonadiProtocolError("item GID and content UID differ")
        return logical, {"id": item_id, "revision": revision,
                         "gid": gid, "content": raw["content"]}

    def event_texts(self):
        if self.kind != "calendar":
            raise ValueError("event_texts requires a calendar client")
        self._snapshot()
        return [item["content"] for group in self._items.values() for item in group]

    def contact_texts(self):
        if self.kind != "addressbook":
            raise ValueError("contact_texts requires an addressbook client")
        self._snapshot()
        return [group[0]["content"] for group in self._items.values()]

    def create(self, content):
        logical = _logical_uid(content, self.kind)
        self._snapshot()
        if logical in self._items:
            raise ValueError("logical UID already exists")
        response = self._call({"command": "create", "content": content})
        if set(response) != {"ok", "item"}:
            raise AkonadiProtocolError("invalid create response")
        returned, item = self._validate_item(response["item"], logical)
        if any(existing["id"] == item["id"] for group in self._items.values()
               for existing in group):
            raise AkonadiProtocolError("create returned an existing item id")
        self._items[returned] = [item]
        return returned

    def modify(self, logical_uid, content):
        logical_uid = _short_text(logical_uid, "logical UID", MAX_UID)
        if _logical_uid(content, self.kind) != logical_uid:
            raise ValueError("content UID does not match logical UID")
        self._snapshot()
        if logical_uid not in self._items:
            raise KeyError(logical_uid)
        group = self._items[logical_uid]
        if len(group) != 1:
            raise ValueError("recurrence instances are read only")
        current = group[0]
        response = self._call({"command": "modify", "id": current["id"],
                               "revision": current["revision"], "content": content})
        if set(response) != {"ok", "item"}:
            raise AkonadiProtocolError("invalid modify response")
        returned, item = self._validate_item(response["item"], logical_uid)
        if any(uid != logical_uid and existing["id"] == item["id"]
               for uid, group in self._items.items() for existing in group):
            raise AkonadiProtocolError("modify returned a duplicate item id")
        self._items[returned] = [item]

    def modify_content(self, content):
        self.modify(_logical_uid(content, self.kind), content)

    def delete(self, logical_uid):
        logical_uid = _short_text(logical_uid, "logical UID", MAX_UID)
        self._snapshot()
        if logical_uid not in self._items:
            raise KeyError(logical_uid)
        group = self._items[logical_uid]
        if len(group) != 1:
            raise ValueError("recurrence instances are read only")
        current = group[0]
        response = self._call({"command": "delete", "id": current["id"],
                               "revision": current["revision"]})
        if set(response) != {"ok"}:
            raise AkonadiProtocolError("invalid delete response")
        del self._items[logical_uid]

    def exists(self, logical_uid):
        if not isinstance(logical_uid, str) or not logical_uid:
            return False
        self._snapshot()
        return logical_uid in self._items

    def verify_exists(self, logical_uid):
        logical_uid = _short_text(logical_uid, "logical UID", MAX_UID)
        response = self._call({"command": "exists", "uid": logical_uid})
        if set(response) != {"ok", "exists"} or type(response["exists"]) is not bool:
            raise AkonadiProtocolError("invalid exists response")
        return response["exists"]


find_helper = discover_helper
invoke_helper = helper_request
akonadi_status = status
