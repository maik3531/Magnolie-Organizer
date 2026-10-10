"""Conservative per-calendar plans for duplicate Magnolie birthday series.

Only explicit local contact/source bindings establish identity. Provider writes
require a durable plan and never use matching names alone as proof.
"""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from magnolie_recurrence import properties

METADATA = frozenset({"UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE",
    "X-EVOLUTION-CALDAV-ETAG", "X-EVOLUTION-ALARM-UID"})


class CleanupArchive:
    """Encrypted, bounded per-source recovery proof outside the live sync queue."""
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, directory, binding, key_provider):
        self.directory = Path(directory)
        self.aad = b"magnolie-calendar-cleanup-v1\0" + binding.encode("utf-8")
        self.path = self.directory / ("calendar-cleanup-" + hashlib.sha256(self.aad).hexdigest() + ".aes")
        self.key_provider = key_provider
        self.lock = None

    def exists(self): return self.path.exists()

    def __enter__(self):
        import fcntl
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(str(self.path) + ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception: os.close(fd); raise
        self.lock = fd
        return self

    def __exit__(self, *args):
        import fcntl
        if self.lock is not None:
            fcntl.flock(self.lock, fcntl.LOCK_UN); os.close(self.lock); self.lock = None

    def load(self):
        if not self.path.exists(): return {}
        if self.path.is_symlink(): raise ValueError("invalid calendar cleanup archive")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with self.path.open("rb") as stream: raw = stream.read(self.MAX_BYTES + 1)
        if not 28 <= len(raw) <= self.MAX_BYTES: raise ValueError("invalid calendar cleanup archive size")
        return json.loads(AESGCM(self.key_provider()).decrypt(raw[:12], raw[12:], self.aad))

    def save(self, state):
        if self.lock is None or self.path.is_symlink(): raise ValueError("calendar cleanup archive is not owned")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        clear = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(clear) + 28 > self.MAX_BYTES: raise ValueError("calendar cleanup archive limit exceeded")
        nonce = os.urandom(12); raw = nonce + AESGCM(self.key_provider()).encrypt(nonce, clear, self.aad)
        fd, temp = tempfile.mkstemp(prefix=".calendar-cleanup-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temp, 0o600); os.replace(temp, self.path)
            parent = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(parent)
            finally: os.close(parent)
        finally:
            if os.path.exists(temp): os.unlink(temp)


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


class DavBirthdayProvider:
    """Resolve logical UIDs through complete REPORTs; delete with a fresh strong ETag."""

    def __init__(self, dav, collection, resources):
        self.dav = dav
        self.collection = collection
        self.current = self.index(resources)

    @staticmethod
    def index(resources):
        result, hrefs = {}, set()
        for resource in resources:
            href = resource["href"]
            if not href or href in hrefs:
                raise ValueError("ambiguous calendar resource location")
            hrefs.add(href)
            root = _tree(resource["data"])
            if root["kind"] != "VCALENDAR":
                raise ValueError("invalid DAV calendar resource")
            # Master and detached instances may share a UID within one resource.
            # The planner protects such resources from deletion.
            uids = {_one(_values(event), "UID") for event in _events(root)}
            for uid in uids:
                if not uid or uid in result:
                    raise ValueError("ambiguous calendar resource UID")
                result[uid] = resource
        return result

    def read_current(self, uid):
        # A complete successful REPORT confirms absence and also finds moved hrefs.
        self.current = self.index(self.dav.report(self.collection, "calendar"))
        resource = self.current.get(uid)
        return resource["data"] if resource is not None else None

    def remove(self, uid):
        resource = self.current[uid]
        etag = resource.get("etag")
        if not isinstance(etag, str) or not re.fullmatch(r'"[^"\x00-\x20\x7f]*"', etag):
            raise ValueError("calendar cleanup requires a strong DAV ETag")
        self.dav.delete(resource["href"], etag)

    def rebind_resources(self, local, source_uid):
        for item in local:
            if item.get("syncKalenderUid") != source_uid and item.get("icsQuelleId") != source_uid:
                continue
            resource = self.current.get(item.get("uid"))
            if resource is None:
                continue
            item["davHref"], item["davEtag"] = resource["href"], resource["etag"]
            source = (item.get("syncQuellen") or {}).get(source_uid)
            if isinstance(source, dict):
                source.update(id=resource["href"], etag=resource["etag"])


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
            if root["kind"] == "VCALENDAR":
                if any(name not in {"VERSION", "PRODID", "CALSCALE", "X-KDE-ICAL-IMPLEMENTATION-VERSION"} for name, _, _ in root["properties"]): continue
                # KCalendarCore adds this serializer marker to ordinary snapshots.
                # Unknown versions/parameters remain protected; keep the full raw backup.
                kde_version = _values(root).get("X-KDE-ICAL-IMPLEMENTATION-VERSION", [])
                if kde_version and kde_version != [({}, "1.0")]: continue
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


def apply_birthdays(local, texts, source_uid, source_key, *, read_current, remove,
                    load_state, save_state, type_id=lambda value: str(value or "").casefold()):
    """Apply only a fresh proven plan, with a durable pre-delete backup and alias proof.

    Provider adapters supply conditional/conflict-failing removal. A read failure
    must raise; only a confirmed absent object may be returned as None.
    """
    state = load_state()
    if not state: state = {"version": 1, "sourceUid": source_uid, "sourceKey": source_key, "operations": {}}
    if (not isinstance(state, dict) or set(state) != {"version", "sourceUid", "sourceKey", "operations"} or
            state["version"] != 1 or state["sourceUid"] != source_uid or state["sourceKey"] != source_key or
            not isinstance(state["operations"], dict)):
        raise ValueError("invalid calendar cleanup journal")
    local_index = defaultdict(list)
    referenced = set()
    for item in local:
        local_index[(str(item.get("kontaktId") or ""), item.get("datum"))].append(item)
        referenced.update(_source_uids(item, source_uid, source_key))
    recovered = 0
    # Finish an interrupted removal only from a previously durable exact plan.
    for uid, operation in state["operations"].items():
        required = {"phase", "plan", "keepText", "removeText"}
        if not isinstance(operation, dict) or set(operation) != required or operation["phase"] not in {"prepared", "removed"}:
            raise ValueError("invalid calendar cleanup operation")
        plan = operation["plan"]
        if (not isinstance(plan, dict) or plan.get("sourceUid") != source_uid or plan.get("sourceKey") != source_key or
                plan.get("removeUids") != [uid] or uid == plan.get("keepUid")):
            raise ValueError("invalid calendar cleanup identity")
        if uid not in referenced: continue
        if read_current(uid) is None and read_current(plan["keepUid"]) is not None:
            if operation["phase"] != "removed":
                operation["phase"] = "removed"; save_state(state)
            rebind_local(local_index.get((plan["contactId"], plan["date"]), []), plan)
            recovered += 1
    plans = plan_birthdays(local, texts, source_uid, source_key, type_id)
    count = 0
    for plan in plans:
        for uid in plan["removeUids"]:
            keeper = read_current(plan["keepUid"]); extra = read_current(uid)
            if keeper is None or extra is None:
                raise ValueError("calendar cleanup snapshot changed")
            if hashlib.sha256(keeper.encode()).hexdigest() != plan["hashes"][plan["keepUid"]] or hashlib.sha256(extra.encode()).hexdigest() != plan["hashes"][uid]:
                raise ValueError("calendar cleanup component changed")
            single = dict(plan, removeUids=[uid])
            state["operations"][uid] = {"phase": "prepared", "plan": single, "keepText": keeper, "removeText": extra}
            save_state(state)  # Must succeed before the first provider mutation.
            remove(uid)
            if read_current(uid) is not None or read_current(plan["keepUid"]) is None:
                raise ValueError("calendar cleanup readback failed")
            state["operations"][uid]["phase"] = "removed"
            save_state(state)
            rebind_local(local_index.get((single["contactId"], single["date"]), []), single)
            count += 1
    return {"removed": count, "recovered": recovered}
