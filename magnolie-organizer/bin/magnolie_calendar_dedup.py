"""Conservative per-calendar plans for duplicate Magnolie birthday series.

Only explicit local contact/source bindings establish identity. This module never
performs provider writes and never treats matching names alone as proof.
"""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import re

from magnolie_recurrence import properties

METADATA = frozenset({"UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE",
    "X-EVOLUTION-CALDAV-ETAG", "X-EVOLUTION-ALARM-UID", "X-LIC-ERROR"})


def _tree(text):
    stack, roots = [], []
    for line in re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n").splitlines():
        if not line: continue
        if line.upper().startswith("BEGIN:"):
            node = {"kind": line[6:].upper(), "properties": [], "children": []}
            (stack[-1]["children"] if stack else roots).append(node); stack.append(node)
        elif line.upper().startswith("END:"):
            if not stack or stack[-1]["kind"] != line[4:].upper(): raise ValueError("unbalanced calendar component")
            stack.pop()
        else:
            parsed = properties([line])
            if not stack or len(parsed) != 1: raise ValueError("invalid calendar property")
            stack[-1]["properties"].append(parsed[0])
    if stack or len(roots) != 1: raise ValueError("incomplete calendar resource")
    return roots[0]


def _events(node):
    result = [node] if node["kind"] == "VEVENT" else []
    for child in node["children"]: result.extend(_events(child))
    return result


def _values(event):
    values = defaultdict(list)
    for name, params, value in event["properties"]: values[name].append((params, value))
    return dict(values)


def _one(values, name):
    entries = values.get(name, [])
    if len(entries) > 1: raise ValueError("ambiguous calendar property")
    return entries[0][1] if entries else ""


def _canonical(node, unknown_year=False):
    fields = []
    for name, params, value in node["properties"]:
        if name in METADATA: continue
        if unknown_year and name == "X-MAGNOLIE-DATE" and re.fullmatch(r"--\d{2}-\d{2}", value): continue
        if unknown_year and name in {"DTSTART", "DTEND"} and re.fullmatch(r"\d{8}", value): value = value[4:]
        fields.append((name, tuple(sorted(params.items())), value))
    return node["kind"], tuple(sorted(fields)), tuple(sorted(_canonical(child, unknown_year) for child in node["children"]))


def _source_uids(item, source_uid, source_key):
    result = set()
    source = (item.get("syncQuellen") or {}).get(source_key)
    if isinstance(source, dict) and source.get("id"): result.add(str(source["id"]))
    if item.get("syncKalenderUid") == source_uid or item.get("icsQuelleId") == source_key:
        result.update(str(item[field]) for field in ("uid", "icsSerienUid") if item.get(field))
    return result


def plan_birthdays(local, texts, source_uid, source_key, type_id=lambda value: str(value or "").casefold()):
    """Return exact retained/removed UIDs with proof hashes, or no plan if ambiguous.

    `texts` must be a complete provider snapshot. Exceptions, finite recurrences,
    different alarms/details, unlinked records and mixed resources are protected.
    """
    resources, counts, by_uid = [], Counter(), {}
    try:
        for text in texts:
            root = _tree(text); events = _events(root); resources.append((text, root, events))
            for event in events: counts[_one(_values(event), "UID")] += 1
        for text, root, events in resources:
            if len(events) != 1 or root["kind"] not in {"VEVENT", "VCALENDAR"}: continue
            if root["kind"] == "VCALENDAR" and any(child["kind"] != "VEVENT" for child in root["children"]): continue
            if root["kind"] == "VCALENDAR" and any(name not in {"VERSION", "PRODID", "CALSCALE"} for name, _, _ in root["properties"]): continue
            event = events[0]; vals = _values(event); uid = _one(vals, "UID")
            if not uid or counts[uid] != 1: continue
            if any(field in vals for field in ("RECURRENCE-ID", "RDATE", "EXDATE", "EXRULE", "ATTENDEE", "ORGANIZER")): continue
            if _one(vals, "RRULE").upper() != "FREQ=YEARLY": continue
            if _one(vals, "STATUS").upper() not in {"", "CONFIRMED"}: continue
            kind = _one(vals, "X-MAGNOLIE-TYPE-ID") or _one(vals, "X-MAGNOLIE-JAHRESTAG-TYP") or _one(vals, "X-MAGNOLIE-TYP")
            if type_id(kind) != "birthday": continue
            start, end = _one(vals, "DTSTART"), _one(vals, "DTEND")
            if not re.fullmatch(r"\d{8}", start): continue
            start_date = datetime.strptime(start, "%Y%m%d")
            if end:
                if not re.fullmatch(r"\d{8}", end) or (datetime.strptime(end, "%Y%m%d") - start_date).days != 1: continue
            elif _one(vals, "DURATION") not in {"", "P1D"}: continue
            if any(child["kind"] != "VALARM" for child in event["children"]): continue
            by_uid[uid] = {"uid": uid, "event": event, "values": vals, "text": text,
                "month_day": start[4:6] + "-" + start[6:],
                "date": _one(vals, "X-MAGNOLIE-DATE") or start[:4] + "-" + start[4:6] + "-" + start[6:]}
    except (ValueError, TypeError, KeyError):
        return []
    groups = defaultdict(list)
    claims = defaultdict(set)
    for item in local:
        contact = item.get("kontaktId")
        if not isinstance(contact, str) or not contact or contact != contact.strip(): continue
        date = str(item.get("datum") or "")
        uids = _source_uids(item, source_uid, source_key)
        for uid in uids: claims[uid].add((contact, date, type_id(item.get("typ"))))
        if type_id(item.get("typ")) != "birthday" or not re.fullmatch(r"(?:\d{4}|-)-\d{2}-\d{2}", date): continue
        if uids: groups[(contact, date)].append((item, uids))
    plans = []
    used = set()
    for (contact, date), members in groups.items():
        uids = set().union(*(uids for _, uids in members))
        candidates = [by_uid[uid] for uid in sorted(uids) if uid in by_uid]
        if len(candidates) < 2 or any(item["month_day"] != date[-5:] for item in candidates): continue
        exact = len({_canonical(item["event"]) for item in candidates}) == 1
        matches = [item for item in candidates if item["date"] == date]
        unknown = (date.startswith("--") and bool(matches) and
            all(_one(item["values"], "X-MAGNOLIE-DATE") in ("", date) for item in candidates) and
            len({_canonical(item["event"], True) for item in candidates}) == 1)
        if not matches or not (exact or unknown): continue
        # Conflicting local owners/dates/types are not a reliable merge proof.
        if any(claims[uid] != {(contact, date, "birthday")} for uid in uids): continue
        keeper = min(matches, key=lambda item: (_one(item["values"], "CREATED"), item["uid"]))
        removed = sorted(item["uid"] for item in candidates if item["uid"] != keeper["uid"])
        if set(removed + [keeper["uid"]]) & used: continue
        used.update(removed + [keeper["uid"]])
        plans.append({"sourceUid": source_uid, "sourceKey": source_key, "contactId": contact,
            "date": date, "keepUid": keeper["uid"], "removeUids": removed,
            "hashes": {item["uid"]: hashlib.sha256(item["text"].encode("utf-8")).hexdigest() for item in candidates}})
    return plans


def rebind_local(local, plan):
    """Rewrite only confirmed aliases belonging to this one calendar source."""
    for item in local:
        if str(item.get("kontaktId") or "") != plan["contactId"] or item.get("datum") != plan["date"]: continue
        source = (item.get("syncQuellen") or {}).get(plan["sourceKey"])
        if isinstance(source, dict) and source.get("id") in plan["removeUids"]: source["id"] = plan["keepUid"]
        if item.get("syncKalenderUid") == plan["sourceUid"] or item.get("icsQuelleId") == plan["sourceKey"]:
            for field in ("uid", "icsSerienUid"):
                if item.get(field) in plan["removeUids"]: item[field] = plan["keepUid"]
    return local
