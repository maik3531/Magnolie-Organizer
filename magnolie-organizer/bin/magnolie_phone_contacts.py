"""Read-only contact resources and the separately opted-in group-write resource."""
import json
import re
import unicodedata

VERSION = 5
PROFILE_VERSION = 7
PROFILE_DIAGNOSTIC_VERSION = 8
GROUP_WRITE_VERSION = 17
GROUP_PROBE_VERSION = 18
VALUE_WRITE_VERSION = 19  # Explicit phone/email values; read-only resource 5 stays unchanged.
GROUP_TITLE_VERSION = 20  # Separate explicit group-title operation and identity-bound inspection.
GROUP_TITLE_RUNTIME_ENABLED = True
DIAGNOSTIC_STAGES = {"canonical_header", "marked_header", "data", "photo", "finish"}
DIAGNOSTIC_OUTCOMES = {"ok", "no_cursor", "empty", "ambiguous", "invalid_identity", "permission_denied",
                       "unsupported_or_invalid", "provider_changed", "too_large", "no_profile", "provider_failure"}
PAGE_SIZE = 128
MAX_CONTACTS = 10000
MAX_CARD_BYTES = 96 * 1024
MAX_REPORT_BYTES = 128 * 1024
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")


def valid_uid(value):
    return isinstance(value, str) and 1 <= len(value) <= 256 and not any(
        unicodedata.category(c) in {"Cc", "Cs"} for c in value)


def readable_value_fields(vcard, contact):
    unfolded = re.sub(r"\r?\n[ \t]", "", vcard)
    return [field for property, field in (("TEL", "telefone"), ("EMAIL", "emailEintraege"))
            if isinstance(contact.get(field), list) and len(re.findall(r"^(?:[A-Za-z0-9-]+\.)?" + property + r"(?:;|:)", unfolded, re.M | re.I)) == len(contact[field])]


def _value_text(value, maximum, empty=False):
    if (not isinstance(value, str) or not empty and not value.strip() or len(value) > maximum or
            any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)):
        raise ValueError("invalid_contact_value")
    return value


def _value_header(value):
    if not isinstance(value, dict):
        raise ValueError("invalid_contact_value_schema")
    _integer(value.get("version"), VALUE_WRITE_VERSION, VALUE_WRITE_VERSION)
    if (not isinstance(value.get("request_id"), str) or not UUID4.fullmatch(value["request_id"]) or
            not valid_uid(value.get("uid")) or value.get("action") not in ("prepare", "apply") or
            len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_REPORT_BYTES):
        raise ValueError("invalid_contact_value_schema")


def value_field_names(value):
    names = value.get("field_names")
    if (not isinstance(names, list) or not 1 <= len(names) <= 2 or
            any(not isinstance(name, str) or name not in ("telefone", "emailEintraege") for name in names) or len(set(names)) != len(names)):
        raise ValueError("invalid_contact_fields")
    return names


def validate_value_fields_shape(value):
    fields = value.get("fields")
    if (not isinstance(fields, dict) or not fields or not set(fields) <= {"telefone", "emailEintraege"}):
        raise ValueError("invalid_contact_fields")
    for rows in fields.values():
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("invalid_contact_values")
        for row in rows:
            _exact(row, ("art", "wert"))
            if _value_text(row["art"], 32) not in ("privat", "arbeit", "mobil", "sonstige"):
                raise ValueError("invalid_contact_kind")
            _value_text(row["wert"], 4096)
        if len({(row["art"], row["wert"]) for row in rows}) != len(rows):
            raise ValueError("duplicate_contact_value")
    return list(fields)


def validate_value_request_shape(value):
    """Transport structure; native preparation also validates projection uniqueness."""
    _value_header(value)
    if value["action"] == "prepare":
        _exact(value, ("version", "request_id", "action", "uid", "field_names"))
        value_field_names(value)
    else:
        _exact(value, ("version", "request_id", "action", "uid", "token", "fields"))
        if not isinstance(value["token"], str) or not UUID4.fullmatch(value["token"]):
            raise ValueError("invalid_contact_value_token")
        validate_value_fields_shape(value)
    return value


def validate_value_report_shape(value):
    _value_header(value)
    _exact(value, ("version", "request_id", "action", "uid", "token", "account", "state", "fields"))
    if (not isinstance(value["token"], str) or not UUID4.fullmatch(value["token"]) or
            value["state"] != ("prepared" if value["action"] == "prepare" else "saved")):
        raise ValueError("invalid_contact_value_report")
    _exact(value["account"], ("name", "type", "data_set"))
    for text in value["account"].values():
        _value_text(text, 256, empty=True)
    validate_value_fields_shape(value)
    return value


def validate_correlated_value_report(report, request, prepared_account=None):
    validate_value_request_shape(request)
    validate_value_report_shape(report)
    if any(report[key] != request[key] for key in ("request_id", "action", "uid")):
        raise ValueError("contact_value_source_changed")
    names = set(value_field_names(request) if request["action"] == "prepare" else request["fields"])
    if set(report["fields"]) != names:
        raise ValueError("contact_value_fields_changed")
    if request["action"] == "apply":
        if report["token"] != request["token"] or prepared_account is None or report["account"] != prepared_account:
            raise ValueError("contact_value_account_changed")
        for name in names:
            keys = lambda rows: {(row["art"], row["wert"]) for row in rows}
            if keys(report["fields"][name]) != keys(request["fields"][name]):
                raise ValueError("contact_value_readback_failed")
    return report


def _group_title_header(value):
    if not isinstance(value, dict):
        raise ValueError("invalid_contact_group_title_schema")
    _integer(value.get("version"), GROUP_TITLE_VERSION, GROUP_TITLE_VERSION)
    if (not isinstance(value.get("request_id"), str) or not UUID4.fullmatch(value["request_id"]) or
            not valid_uid(value.get("uid")) or value.get("action") not in ("prepare", "apply", "inspect")):
        raise ValueError("invalid_contact_group_title_schema")
    titles = [_value_text(value.get(field), 256) for field in ("old_title", "new_title")]
    if titles[0] == titles[1] or any(title != unicodedata.normalize("NFC", title.strip()) for title in titles):
        raise ValueError("invalid_contact_group_title")


def _group_title_budget(value):
    if len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) > 16 * 1024:
        raise ValueError("contact_group_title_too_large")


def validate_group_title_request_shape(value):
    _group_title_header(value)
    fields = ("version", "request_id", "action", "uid", "old_title", "new_title")
    _exact(value, fields + (("token",) if value["action"] == "apply" else ("group_id", "account") if value["action"] == "inspect" else ()))
    if value["action"] == "apply" and (not isinstance(value["token"], str) or not UUID4.fullmatch(value["token"])):
        raise ValueError("invalid_contact_group_title_token")
    if value["action"] == "inspect":
        _group_title_identity_fields(value)
    _group_title_budget(value)
    return value


def _group_title_identity_fields(value):
    group_id = _value_text(value["group_id"], 19)
    if not re.fullmatch(r"[1-9][0-9]{0,18}", group_id) or int(group_id) > 9223372036854775807:
        raise ValueError("invalid_contact_group_title_report")
    _exact(value["account"], ("name", "type", "data_set"))
    for text in value["account"].values():
        _value_text(text, 256, empty=True)


def validate_group_title_report_shape(value):
    _group_title_header(value)
    inspect = value["action"] == "inspect"
    _exact(value, ("version", "request_id", "action", "uid", "old_title", "new_title", "state", "group_id", "account", "group_identity") +
        (("current_title",) if inspect else ("token",)))
    _group_title_identity_fields(value)
    identity = _value_text(value["group_identity"], 64)
    if (not re.fullmatch(r"[a-f0-9]{64}", identity) or
            not inspect and (not isinstance(value["token"], str) or not UUID4.fullmatch(value["token"])) or
            value["state"] != ("current" if inspect else "prepared" if value["action"] == "prepare" else "saved")):
        raise ValueError("invalid_contact_group_title_report")
    if inspect:
        _value_text(value["current_title"], 256)
    _group_title_budget(value)
    return value


def validate_correlated_group_title_report(report, request, prepared=None):
    validate_group_title_request_shape(request)
    validate_group_title_report_shape(report)
    if any(report[key] != request[key] for key in ("request_id", "action", "uid", "old_title", "new_title")):
        raise ValueError("contact_group_title_source_changed")
    if request["action"] == "inspect" and any(report[key] != request[key] for key in ("group_id", "account")):
        raise ValueError("contact_group_title_source_changed")
    if request["action"] == "apply":
        if prepared is None:
            raise ValueError("contact_group_title_preparation_missing")
        validate_group_title_report_shape(prepared)
        if (prepared["action"] != "prepare" or report["token"] != request["token"] or
                any(report[key] != prepared[key] for key in ("uid", "old_title", "new_title", "token", "group_id", "account", "group_identity"))):
            raise ValueError("contact_group_title_preparation_changed")
    return report


def group_title_matches_saved_intent(inspection, prepared):
    validate_group_title_report_shape(inspection)
    validate_group_title_report_shape(prepared)
    return (inspection["action"] == "inspect" and prepared["action"] == "prepare" and
        all(inspection[key] == prepared[key] for key in ("uid", "old_title", "new_title", "group_id", "account", "group_identity")) and
        inspection["current_title"] == prepared["new_title"])


def _exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("invalid_contact_schema")


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid_contact_schema")
    return value


def _header(value):
    _integer(value["version"], VERSION, PROFILE_DIAGNOSTIC_VERSION)
    if value["version"] not in (VERSION, PROFILE_VERSION, PROFILE_DIAGNOSTIC_VERSION):
        raise ValueError("invalid_contact_schema")
    if not isinstance(value["request_id"], str) or not UUID4.fullmatch(value["request_id"]):
        raise ValueError("invalid_contact_request")


def validate_request(value):
    _exact(value, ("version", "request_id", "action", "offset", "uids"))
    _header(value)
    offset = _integer(value["offset"], 0, MAX_CONTACTS)
    uids = value["uids"]
    if value["version"] in (PROFILE_VERSION, PROFILE_DIAGNOSTIC_VERSION):
        if value["action"] != "profile" or offset != 0 or uids != []:
            raise ValueError("invalid_profile_request")
        return value
    if not isinstance(uids, list) or not all(valid_uid(uid) for uid in uids) or len(set(uids)) != len(uids):
        raise ValueError("invalid_contact_batch")
    if not (value["action"] == "index" and not uids or value["action"] == "cards" and offset == 0 and 1 <= len(uids) <= 5):
        raise ValueError("invalid_contact_request")
    return value


def validate_report(value):
    if isinstance(value, dict) and value.get("version") in (PROFILE_VERSION, PROFILE_DIAGNOSTIC_VERSION):
        fields = ("version", "request_id", "action", "offset", "total", "contacts", "profile")
        _exact(value, fields + (("diagnostics",) if value["version"] == PROFILE_DIAGNOSTIC_VERSION else ()))
        _header(value)
        if value["version"] == PROFILE_DIAGNOSTIC_VERSION:
            entries = value["diagnostics"]
            if not isinstance(entries, list) or len(entries) > 32:
                raise ValueError("invalid_profile_diagnostics")
            for entry in entries:
                _exact(entry, ("stage", "rows", "outcome"))
                if (not isinstance(entry["stage"], str) or not isinstance(entry["outcome"], str) or
                        entry["stage"] not in DIAGNOSTIC_STAGES or entry["outcome"] not in DIAGNOSTIC_OUTCOMES):
                    raise ValueError("invalid_profile_diagnostics")
                _integer(entry["rows"], -1, 1000)
        profile = value["profile"]
        _exact(profile, ("state", "vcard"))
        card = profile["vcard"]
        if (value["action"] != "profile" or type(value["offset"]) is not int or value["offset"] != 0 or value["contacts"] != [] or
                profile["state"] not in ("available", "unavailable") or not isinstance(card, str) or
                type(value["total"]) is not int or value["total"] != int(profile["state"] == "available") or
                (profile["state"] == "unavailable" and card) or
                (profile["state"] == "available" and (not card.startswith("BEGIN:VCARD\r\n") or not card.endswith("END:VCARD\r\n") or len(card.encode("utf-8")) > MAX_CARD_BYTES))):
            raise ValueError("invalid_profile_report")
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("contact_report_too_large")
        return value
    _exact(value, ("version", "request_id", "action", "offset", "total", "contacts"))
    _header(value)
    total = _integer(value["total"], 0, MAX_CONTACTS)
    offset = _integer(value["offset"], 0, total)
    contacts = value["contacts"]
    if not isinstance(contacts, list) or not (
            value["action"] == "index" and len(contacts) <= PAGE_SIZE and offset + len(contacts) <= total and
            (contacts or offset == total) or
            value["action"] == "cards" and offset == 0 and 1 <= len(contacts) <= 5 and total == len(contacts)):
        raise ValueError("invalid_contact_report")
    seen = set()
    for item in contacts:
        _exact(item, ("uid", "timestamp") if value["action"] == "index" else ("uid", "timestamp", "vcard"))
        uid = item["uid"]
        if not valid_uid(uid) or uid in seen:
            raise ValueError("invalid_contact_uid")
        seen.add(uid)
        _integer(item["timestamp"], 0, 253402300799999)
        if value["action"] == "cards":
            card = item["vcard"]
            if (not isinstance(card, str) or not card.startswith("BEGIN:VCARD\r\n") or not card.endswith("END:VCARD\r\n") or
                    len(card.encode("utf-8")) > MAX_CARD_BYTES):
                raise ValueError("invalid_contact_vcard")
    if len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("contact_report_too_large")
    return value


def _group_names(value, limit=100):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("invalid_contact_groups")
    keys = set()
    for name in value:
        if (not isinstance(name, str) or not name.strip() or len(name) > 256 or
                any(unicodedata.category(char) in {"Cc", "Cs"} for char in name)):
            raise ValueError("invalid_contact_groups")
        key = unicodedata.normalize("NFC", name.strip()).lower()
        if key in keys:
            raise ValueError("invalid_contact_groups")
        keys.add(key)


def _group_header(value):
    _integer(value["version"], GROUP_WRITE_VERSION, GROUP_WRITE_VERSION)
    if (not isinstance(value["request_id"], str) or not UUID4.fullmatch(value["request_id"]) or
            not valid_uid(value["uid"]) or value["action"] not in ("prepare", "apply")):
        raise ValueError("invalid_contact_group_request")
    if len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("contact_groups_too_large")


def validate_group_request(value):
    fields = {"version", "request_id", "action", "uid"}
    _exact(value, fields | ({"token", "groups"} if isinstance(value, dict) and value.get("action") == "apply" else set()))
    _group_header(value)
    if value["action"] == "apply":
        if not isinstance(value["token"], str) or not UUID4.fullmatch(value["token"]):
            raise ValueError("invalid_contact_group_token")
        _group_names(value["groups"])
    return value


def validate_group_report(value):
    _exact(value, {"version", "request_id", "action", "uid", "token", "state", "groups", "catalog", "account"})
    _group_header(value)
    if (not isinstance(value["token"], str) or not UUID4.fullmatch(value["token"]) or
            value["state"] != ("prepared" if value["action"] == "prepare" else "saved")):
        raise ValueError("invalid_contact_group_report")
    _group_names(value["groups"]); _group_names(value["catalog"], 1000)
    if value["action"] == "apply" and value["catalog"]:
        raise ValueError("invalid_contact_group_report")
    _exact(value["account"], {"name", "type", "data_set"})
    if any(not isinstance(text, str) or len(text) > 256 or
           any(unicodedata.category(char) in {"Cc", "Cs"} for char in text) for text in value["account"].values()):
        raise ValueError("invalid_contact_group_account")
    return value


def validate_group_probe_request(value):
    _exact(value, {"version", "request_id", "action", "uid"})
    _integer(value["version"], GROUP_PROBE_VERSION, GROUP_PROBE_VERSION)
    if value["action"] != "diagnostics": raise ValueError("invalid_contact_group_probe")
    validate_group_request(dict(value, version=GROUP_WRITE_VERSION, action="prepare"))
    return value


def validate_group_probe_report(value):
    _exact(value, {"version", "request_id", "action", "uid", "state", "stage", "error_type", "reason",
                   "raw_count", "version_count", "account_count", "mime_supported", "reader_complete"})
    validate_group_probe_request({key:value[key] for key in ("version", "request_id", "action", "uid")})
    stages = {"request", "permission", "snapshot", "snapshot_shape", "uid", "raw_versions", "account_scope", "groups", "catalog", "report", "complete"}
    if (value["state"] not in ("available", "failed") or value["stage"] not in stages or
        not isinstance(value["error_type"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", value["error_type"]) or
        value["reason"] not in ("none", "contact_groups_ambiguous_account", "contact_groups_unknown", "contact_groups_unavailable", "contact_groups_incomplete", "provider_failure") or
        type(value["mime_supported"]) is not bool or type(value["reader_complete"]) is not bool): raise ValueError("invalid_contact_group_probe")
    for key in ("raw_count", "version_count", "account_count"): _integer(value[key], 0, 10000)
    if value["state"] == "available" and ((value["stage"], value["error_type"], value["reason"]) != ("complete", "None", "none") or value["reader_complete"] is not True):
        raise ValueError("invalid_contact_group_probe")
    return value
