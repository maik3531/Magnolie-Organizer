"""Bounded read-only Notes contact-resource contract (device-status v5)."""
import json
import re
import unicodedata

VERSION = 5
PROFILE_VERSION = 7
PROFILE_DIAGNOSTIC_VERSION = 8
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
