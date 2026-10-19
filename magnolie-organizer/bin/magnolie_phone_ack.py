"""Shared strict acknowledgement schema; no storage, transport or authorization."""
import re

ERRORS = frozenset({"none", "expired", "invalid_schema", "unsupported", "not_granted", "too_large",
    "temporary_failure", "permanent_failure", "restore_unavailable", "conflict"})
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def validate(value):
    if (not isinstance(value, dict) or set(value) != {"type", "message_id", "status", "error"} or
            value.get("type") != "ack" or not isinstance(value.get("message_id"), str) or
            not UUID4.fullmatch(value["message_id"]) or not isinstance(value.get("status"), str) or
            value["status"] not in {"accepted", "duplicate", "rejected"} or not isinstance(value.get("error"), str) or
            value["error"] not in ERRORS or (value["status"] != "rejected") != (value["error"] == "none")):
        raise ValueError("invalid ack")
    return value
