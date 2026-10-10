#!/usr/bin/env python3
"""Peer-scoped common function preferences; authentication/consent remain caller gates."""

import copy
import re

VERSION = 9
KIND = "personal_sync.shared_settings"
MAX_COUNTER = 9007199254740991
ACTOR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
DEFAULTS = {"content_mode": "phone_scope", "auto_mode": "manual", "skip_deletions": True,
            "custom_enabled": False, "time_enabled": False, "time_mode": "phone_import"}
ENUMS = {"content_mode": {"phone_import", "phone_scope", "two_way"}, "time_mode": {"phone_import", "two_way"},
         "auto_mode": {"manual", "wifi", "connection"}}


def supported(local_items, remote_items):
    for items in (local_items, remote_items):
        if not isinstance(items, dict):
            return False
        for name in ("personal_notes_sync", "personal_tasks_sync"):
            item = items.get(name)
            if (not isinstance(item, dict) or item.get("available") is not True or
                    not isinstance(item.get("versions"), list) or
                    not any(type(value) is int and value == VERSION for value in item["versions"])):
                return False
    return True


def actor(value):
    if not isinstance(value, str) or not ACTOR.fullmatch(value):
        raise ValueError("invalid shared settings actor")
    return value


def setting_value(field, value):
    if field not in DEFAULTS:
        raise ValueError("unknown common function setting")
    if field in ENUMS:
        if not isinstance(value, str) or value not in ENUMS[field]:
            raise ValueError("invalid common function mode")
    elif type(value) is not bool:
        raise ValueError("invalid common function switch")
    return value


def validate(body):
    if (not isinstance(body, dict) or set(body) != {"format", "settings"}
            or type(body.get("format")) is not int or body["format"] != VERSION
            or not isinstance(body.get("settings"), dict) or not 1 <= len(body["settings"]) <= len(DEFAULTS)):
        raise ValueError("invalid shared function settings")
    for field, edits in body["settings"].items():
        if field not in DEFAULTS or not isinstance(edits, dict) or not 1 <= len(edits) <= 2:
            raise ValueError("invalid shared setting register")
        for origin, edit in edits.items():
            actor(origin)
            if (not isinstance(edit, dict) or set(edit) != {"counter", "value"}
                    or type(edit.get("counter")) is not int or not 0 <= edit["counter"] <= MAX_COUNTER):
                raise ValueError("invalid shared setting edit")
            setting_value(field, edit["value"])
    return body


def create(local_actor, initial=None):
    actor(local_actor)
    values = dict(DEFAULTS)
    for field, value in (initial or {}).items():
        values[field] = setting_value(field, value)
    return validate({"format": VERSION, "settings": {
        field: {local_actor: {"counter": 0, "value": value}} for field, value in values.items()}})


def effective(body):
    validate(body)
    result = {}
    for field, edits in body["settings"].items():
        newest = max(edit["counter"] for edit in edits.values())
        candidates = [(origin, edit["value"]) for origin, edit in edits.items() if edit["counter"] == newest]
        values = [value for _, value in candidates]
        # Only genuinely concurrent equal-clock edits need a deterministic tie rule.
        if field == "content_mode":
            chosen = next(value for value in ("phone_import", "phone_scope", "two_way") if value in values)
        elif field == "time_mode":
            chosen = "phone_import" if "phone_import" in values else "two_way"
        elif field in {"custom_enabled", "time_enabled"}:
            chosen = all(values)
        elif field == "skip_deletions":
            chosen = any(values)
        elif newest == 0:
            # Preserve existing Wi-Fi automation on either side during initial migration.
            # New transport-free automation is never implied by a legacy Wi-Fi flag.
            chosen = next(value for value in ("wifi", "manual", "connection") if value in values)
        else:
            chosen = next(value for value in ("manual", "wifi", "connection") if value in values)
        result[field] = chosen
    return result


def scoped(body, local_actor, peer_actor):
    validate(body)
    actor(local_actor); actor(peer_actor)
    if local_actor == peer_actor:
        raise ValueError("shared setting actors must be distinct")
    if any(set(edits) - {local_actor, peer_actor} for edits in body["settings"].values()):
        raise ValueError("shared settings belong to a different paired device")
    return body


def change(body, local_actor, peer_actor, field, value):
    scoped(body, local_actor, peer_actor)
    setting_value(field, value)
    result = copy.deepcopy(body)
    edits = result["settings"].get(field, {})
    counter = max((edit["counter"] for edit in edits.values()), default=0) + 1
    if counter > MAX_COUNTER:
        raise ValueError("shared setting counter exhausted")
    edits[local_actor] = {"counter": counter, "value": value}
    result["settings"][field] = edits
    return validate(result)


def merge(body, incoming, local_actor, peer_actor):
    scoped(body, local_actor, peer_actor); scoped(incoming, local_actor, peer_actor)
    result = copy.deepcopy(body)
    for field, edits in incoming["settings"].items():
        target = result["settings"].setdefault(field, {})
        for origin, edit in edits.items():
            previous = target.get(origin)
            if origin == local_actor:
                if previous is None or edit["counter"] > previous["counter"]:
                    raise ValueError("unknown local setting echo")
                if edit["counter"] == previous["counter"] and edit != previous:
                    raise ValueError("conflicting local setting echo")
                continue
            if previous is not None:
                if edit["counter"] < previous["counter"]:
                    continue
                if edit["counter"] == previous["counter"] and edit != previous:
                    raise ValueError("conflicting shared setting edit")
            target[origin] = copy.deepcopy(edit)
    return validate(result)
