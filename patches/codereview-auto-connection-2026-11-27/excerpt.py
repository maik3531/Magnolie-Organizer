import re
FORMATS = [1, 2, 3, 14]
PROVENANCE_FORMAT = 14
FORMAT = 1
MAX_TIMESTAMP = 253402300799999
MAX_SAFE_INTEGER = 9007199254740991
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
NOTE_MODE_KIND = "personal_sync.note_settings"
DESKTOP_FEATURES_KIND = "personal_sync.desktop_features"
AUTO_CONNECTION_VERSION = 8
AUTO_CONNECTION_TRIGGER = "auto_connection"
SYNC_TRIGGERS = frozenset({"manual", "auto_wifi", AUTO_CONNECTION_TRIGGER})
AUTOMATIC_TRIGGERS = frozenset({"auto_wifi", AUTO_CONNECTION_TRIGGER})


def auto_connection_supported(local_items, remote_items):
    def marked(items):
        if not isinstance(items, dict):
            return False
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            item = items.get(name)
            if (not isinstance(item, dict) or item.get("available") is not True
                    or not isinstance(item.get("versions"), list)
                    or not any(type(value) is int and value == AUTO_CONNECTION_VERSION for value in item["versions"])):
                return False
        return True
    return marked(local_items) and marked(remote_items)


def automatic_trigger(transport, negotiated):
    if transport not in {"wifi", "bluetooth"}:
        return None
    if negotiated:
        return AUTO_CONNECTION_TRIGGER
    return "auto_wifi" if transport == "wifi" else None


def sync_trigger_allowed(trigger, negotiated):
    return trigger in SYNC_TRIGGERS and (trigger != AUTO_CONNECTION_TRIGGER or negotiated)


def validate_body(kind, body):
    if kind == DESKTOP_FEATURES_KIND:
        return validate_desktop_features(body)
    if not isinstance(body, dict) or type(body.get("format")) is not int:
        raise ValueError("invalid personal sync body")
    if kind == NOTE_MODE_KIND:
        validate_note_settings(body)
    elif kind == "personal_sync.settings":
        if set(body) != {"format", "own_device"} or body.get("format") != FORMAT or not isinstance(body.get("own_device"), bool):
            raise ValueError("invalid personal sync settings")
    elif kind == "personal_sync.request":
        if (set(body) != {"format", "run_id", "trigger", "modules"} | ({"send_item"} if "send_item" in body else set()) or body.get("format") not in FORMATS
                or not UUID4.fullmatch(body.get("run_id", "")) or body.get("trigger") not in {"manual", "auto_wifi"}
                or body.get("modules") not in (["notes"], ["tasks"], ["notes", "tasks"])):
            raise ValueError("invalid personal sync request")
        if "send_item" in body:
            item = body["send_item"]
            if (body["format"] not in {3, PROVENANCE_FORMAT} or body["trigger"] != "manual" or not isinstance(item, dict)
                    or set(item) != {"kind", "id"} or item["kind"] not in {"note", "task"}
                    or not _identifier(item["id"]) or body["modules"] != ["notes" if item["kind"] == "note" else "tasks"]):
                raise ValueError("invalid single-item send")
    elif kind == "personal_sync.report":
        format = body.get("format")
        fields = {"format", "run_id", "state", "trigger", "transport", "sent", "received",
                   "conflicts", "attachments_omitted", "oversized_skipped", "started_ms", "finished_ms", "error",
                   "deletions"}
        if format >= 2:
            fields.add("attachments")
        if set(body) != fields or format not in FORMATS or not UUID4.fullmatch(body.get("run_id", "")):
            raise ValueError("invalid personal sync report")
        if body.get("state") not in {"complete", "partial", "blocked", "failed"} or body.get("trigger") not in {"manual", "auto_wifi"} or body.get("transport") not in {"wifi", "bluetooth"}:
            raise ValueError("invalid personal sync report state")
        counts = {"notes", "tasks", "notebooks"}
        if any(not isinstance(body.get(name), int) or isinstance(body.get(name), bool) or body[name] < 0
               or body[name] > (MAX_TIMESTAMP if name.endswith("_ms") else MAX_SAFE_INTEGER)
               for name in {"conflicts", "attachments_omitted", "oversized_skipped", "started_ms", "finished_ms"}):
            raise ValueError("invalid personal sync report count")
        if (any(not isinstance(body.get(name), dict) or set(body[name]) != counts or any(
                 not isinstance(number, int) or isinstance(number, bool) or
                 not 0 <= number <= MAX_SAFE_INTEGER for number in body[name].values())
               for name in {"sent", "received"}) or body.get("error") not in {
                   "none", "offline", "not_granted", "too_large", "save_failed", "protocol", "unknown"}
                 or body["finished_ms"] < body["started_ms"]):
            raise ValueError("invalid personal sync report counters")
        if format >= 2:
            attachments = body["attachments"]
            names = {"declared", "requested", "sent", "received", "reused", "preserved", "failed", "bytes"}
            if (not isinstance(attachments, dict) or set(attachments) != names or any(
                    isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= MAX_SAFE_INTEGER
                    for number in attachments.values())):
                raise ValueError("invalid attachment report")
        deletions = body["deletions"]
        if (not isinstance(deletions, dict) or set(deletions) != {
                "pending", "deleted", "restored", "conflicts", "blocked", "trash"}):
            raise ValueError("invalid deletion report")
        trash = deletions.get("trash")
        if (not isinstance(trash, dict) or set(trash) != {"notes", "tasks", "notebooks", "attachments"}
                or any(isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= MAX_SAFE_INTEGER
                       for number in trash.values())
                or any(isinstance(deletions[name], bool) or not isinstance(deletions[name], int)
                       or not 0 <= deletions[name] <= MAX_SAFE_INTEGER
                       for name in {"pending", "deleted", "restored", "conflicts", "blocked"})):
            raise ValueError("invalid deletion report counters")
    return body
