"""Bounded read-only Notes contact-resource contract (device-status v5)."""
import json
import re
import unicodedata

VERSION = 5
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
    _integer(value["version"], VERSION, VERSION)
    if not isinstance(value["request_id"], str) or not UUID4.fullmatch(value["request_id"]):
        raise ValueError("invalid_contact_request")


def validate_request(value):
    _exact(value, ("version", "request_id", "action", "offset", "uids"))
    _header(value)
    offset = _integer(value["offset"], 0, MAX_CONTACTS)
    uids = value["uids"]
    if not isinstance(uids, list) or not all(valid_uid(uid) for uid in uids) or len(set(uids)) != len(uids):
        raise ValueError("invalid_contact_batch")
    if not (value["action"] == "index" and not uids or value["action"] == "cards" and offset == 0 and 1 <= len(uids) <= 5):
        raise ValueError("invalid_contact_request")
    return value


def validate_report(value):
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
