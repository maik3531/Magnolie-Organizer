#!/usr/bin/env python3
"""Bounded current-phone content membership. Fresh authenticated binding is a caller gate."""

import hashlib
import copy
import math
import uuid
import magnolie_personal_sync as personal

VERSION = 10
KIND = "personal_sync.content_scope"
MAX_MEMBERS = 50000
MIN_CHUNK = 32
MAX_CHUNK = 256
MAX_PARTS = math.ceil(MAX_MEMBERS / MIN_CHUNK)
PART_BYTES = 192 * 1024
KINDS = {"note": "notes", "task": "tasks"}


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


def identifier(value):
    if not personal._identifier(value):
        raise ValueError("invalid content scope identity")
    return value


def digest(members):
    return hashlib.sha256(personal.canonical(members)).hexdigest()


def checked_members(members):
    if not isinstance(members, dict) or set(members) != {"notes", "tasks"}:
        raise ValueError("invalid content scope members")
    total = 0
    for values in members.values():
        if not isinstance(values, list):
            raise ValueError("invalid content scope identities")
        for value in values:
            identifier(value)
        if values != sorted(set(values), key=lambda value: value.encode("utf-8")):
            raise ValueError("content scope identities must be unique and UTF-8 sorted")
        total += len(values)
    if total > MAX_MEMBERS:
        raise ValueError("content scope too large")
    return members


def validate(manifest):
    if (not isinstance(manifest, dict) or set(manifest) != {"format", "epoch", "revision", "scope_hash", "members"}
            or type(manifest.get("format")) is not int or manifest["format"] != VERSION
            or not isinstance(manifest.get("epoch"), str) or not personal.UUID4.fullmatch(manifest["epoch"])
            or type(manifest.get("revision")) is not int or not 1 <= manifest["revision"] <= personal.MAX_SAFE_INTEGER):
        raise ValueError("invalid content scope manifest")
    checked_members(manifest["members"])
    if manifest["scope_hash"] != digest(manifest["members"]):
        raise ValueError("content scope hash mismatch")
    return manifest


def create(notes, tasks, revision=1, epoch=None):
    members = {"notes": sorted(set(notes), key=lambda value: identifier(value).encode("utf-8")),
               "tasks": sorted(set(tasks), key=lambda value: identifier(value).encode("utf-8"))}
    return validate({"format": VERSION, "epoch": epoch or str(uuid.uuid4()), "revision": revision,
                     "scope_hash": digest(members), "members": members})


def advance(current, notes, tasks):
    validate(current)
    candidate = create(notes, tasks, current["revision"])
    if candidate["members"] == current["members"]:
        return current
    return create(notes, tasks, current["revision"] + 1)


def reference(manifest):
    validate(manifest)
    return {"scope_epoch": manifest["epoch"], "scope_revision": manifest["revision"], "scope_hash": manifest["scope_hash"]}


def require_current(body, manifest):
    expected = reference(manifest)
    if (not isinstance(body, dict) or type(body.get("scope_revision")) is not int
            or any(body.get(field) != value for field, value in expected.items())):
        raise ValueError("stale or different content scope")


def validate_part(body):
    fields = {"format", "epoch", "revision", "scope_hash", "part", "parts", "members"}
    if (not isinstance(body, dict) or set(body) != fields or type(body.get("format")) is not int or body["format"] != VERSION
            or not isinstance(body.get("epoch"), str) or not personal.UUID4.fullmatch(body["epoch"])
            or type(body.get("revision")) is not int or not 1 <= body["revision"] <= personal.MAX_SAFE_INTEGER
            or not isinstance(body.get("scope_hash"), str) or not personal.HASH.fullmatch(body["scope_hash"])
            or type(body.get("parts")) is not int or not 1 <= body["parts"] <= MAX_PARTS
            or type(body.get("part")) is not int or not 0 <= body["part"] < body["parts"]
            or not isinstance(body.get("members"), list) or len(body["members"]) > MAX_CHUNK):
        raise ValueError("invalid content scope part")
    entries = []
    for member in body["members"]:
        if not isinstance(member, dict) or set(member) != {"kind", "id"} or member.get("kind") not in KINDS:
            raise ValueError("invalid content scope member")
        entries.append((member["kind"], identifier(member["id"])))
    if entries != sorted(set(entries), key=lambda item: (item[0], item[1].encode("utf-8"))):
        raise ValueError("unordered or repeated content scope member")
    if len(personal.canonical(body)) > PART_BYTES:
        raise ValueError("content scope part too large")
    return body


def chunks(manifest, size=MAX_CHUNK):
    validate(manifest)
    if type(size) is not int or not MIN_CHUNK <= size <= MAX_CHUNK:
        raise ValueError("invalid scope chunk size")
    entries = [{"kind": kind, "id": value} for kind, bucket in KINDS.items() for value in manifest["members"][bucket]]
    parts = max(1, math.ceil(len(entries) / size))
    header = {field: manifest[field] for field in ("format", "epoch", "revision", "scope_hash")}
    return [validate_part(dict(header, part=index, parts=parts, members=entries[index * size:(index + 1) * size]))
            for index in range(parts)]


def assemble(pieces):
    by_index = {}
    header = None
    for piece in pieces:
        validate_part(piece)
        shape = {field: piece[field] for field in ("format", "epoch", "revision", "scope_hash", "parts")}
        if header is not None and shape != header:
            raise ValueError("mixed content scope generations")
        header = shape
        if piece["part"] in by_index and by_index[piece["part"]] != piece:
            raise ValueError("conflicting content scope duplicate")
        by_index[piece["part"]] = piece
    if header is None or set(by_index) != set(range(header["parts"])):
        raise ValueError("incomplete content scope")
    members = {"notes": [], "tasks": []}
    for index in range(header["parts"]):
        for member in by_index[index]["members"]:
            members[KINDS[member["kind"]]].append(member["id"])
    checked_members(members)
    return validate({field: header[field] for field in ("format", "epoch", "revision", "scope_hash")} | {"members": members})


def filter_records(records, manifest):
    """Select live member content and only notebooks required by selected notes.

    Producers must select IDs before materializing expensive content/attachments;
    receivers additionally validate records and current physical presence at commit.
    """
    validate(manifest)
    allowed = {kind: set(manifest["members"][bucket]) for kind, bucket in KINDS.items()}
    selected = []
    notebooks = set()
    for record in records:
        kind = record.get("kind")
        if kind not in KINDS or record.get("id") not in allowed[kind] or record.get("state") != "live":
            continue
        selected.append(record)
        if kind == "note":
            notebook = record.get("value", {}).get("notebook_id", "")
            if notebook:
                notebooks.add(identifier(notebook))
    selected_keys = {(record["kind"], record["id"]) for record in selected}
    return [record for record in records if record.get("state") == "live" and (record.get("kind"), record.get("id")) in selected_keys or
            record.get("kind") == "notebook" and record.get("state") == "live" and record.get("id") in notebooks]


class ScopeSession:
    """Connection-local receive evidence. Persisted manifests alone cannot authorize a reply.

    The transport supplies an immutable (peer ID, public key, connection generation)
    binding after authentication, capability negotiation and grants validation.
    A new incomplete generation closes the gate until all its parts agree.
    """
    def __init__(self, binding):
        if not isinstance(binding, tuple) or len(binding) != 3 or any(value is None for value in binding):
            raise ValueError("invalid scope session binding")
        self.binding = binding
        self._header = None
        self._parts = {}
        self._manifest = None
        self._failed = False

    def receive(self, binding, part):
        if binding != self.binding:
            raise PermissionError("content scope session changed")
        if self._failed:
            raise ValueError("content scope session failed")
        try:
            validate_part(part)
            header = {field: part[field] for field in ("format", "epoch", "revision", "scope_hash", "parts")}
            if self._header is not None:
                if header["revision"] < self._header["revision"]:
                    return None  # Reordered old frame never reopens or replaces the current generation.
                if header["revision"] == self._header["revision"] and header != self._header:
                    raise ValueError("conflicting scope generation")
                if header["revision"] > self._header["revision"] and header["epoch"] == self._header["epoch"]:
                    raise ValueError("scope epoch reused for changed membership")
            if header != self._header:
                self._header = header
                self._parts = {}
                self._manifest = None
            previous = self._parts.get(part["part"])
            if previous is not None and previous != part:
                raise ValueError("conflicting scope part replay")
            if previous is None:
                # Bounded even when a dishonest sender claims too many full chunks.
                if sum(len(value["members"]) for value in self._parts.values()) + len(part["members"]) > MAX_MEMBERS:
                    raise ValueError("content scope session too large")
                self._parts[part["part"]] = copy.deepcopy(part)
            if len(self._parts) == header["parts"]:
                self._manifest = assemble(self._parts.values())
            return copy.deepcopy(self._manifest)
        except Exception:
            self._failed = True
            self._manifest = None
            self._parts.clear()
            raise

    def current(self, binding, claimed):
        if binding != self.binding or self._failed or self._manifest is None:
            raise PermissionError("content scope is not current on this connection")
        require_current(claimed, self._manifest)
        return copy.deepcopy(self._manifest)
