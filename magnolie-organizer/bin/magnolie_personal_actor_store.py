"""Owner-bound raw actor inbox; authorization/source snapshots are native callbacks.

No transport, GUI dispatch, record merge or successful wire receipt is performed
here. Existing Personal Sync stagers use the private storage-peer namespace only
after the caller has authorized the actual source peer.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field

import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
import magnolie_content_scope as scope

HEX = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT = re.compile(r"^[0-9A-F]{4}(?:-[0-9A-F]{4}){3}$")
LIFETIME_MS = 30 * 60 * 1000
MAX_CONTEXTS = 32
MAX_ACTIVE = 4
MAX_PACKETS = 4096
MAX_ACTOR_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


class NativeBookOwnerScope:
    """Native lifecycle fence, not a document tracker or a client-supplied revision."""
    def __init__(self):
        self._lock = threading.Lock()
        self._ready = False
        self._binding = None
        self._source = None

    def set_ready(self, ready):
        if type(ready) is not bool:
            raise TypeError("Native readiness must be boolean")
        with self._lock:
            self._ready = ready
            if not ready:
                self._binding = self._source = None

    def invalidate(self):
        with self._lock:
            self._binding = self._source = None

    def current(self, native_binding, native_available):
        with self._lock:
            if (not self._ready or native_available is not True or
                    not isinstance(native_binding, str) or not native_binding):
                self._binding = self._source = None
                return None
            if self._source is None or self._binding != native_binding:
                self._binding = native_binding
                self._source = secrets.token_hex(32)
            return self._source


@dataclass(frozen=True)
class ActorHandle:
    actor_id: str
    owner_token: str = field(repr=False)


class ActorStore:
    # The native callback must bind the current book/profile scope as well as the
    # exact channel/key, fresh controls, ownership, grants and content scope.
    # A caller-supplied display fingerprint/revision alone is never authority.
    def __init__(self, store, current_source, *, epoch=None, clock=None, monotonic_clock=None, source_guard=None):
        if not callable(current_source):
            raise TypeError("A native current-source validator is required")
        self.store = store
        self.current_source = current_source
        self.source_guard = source_guard
        self.epoch = secrets.token_hex(32) if epoch is None else epoch
        if not isinstance(self.epoch, str) or not HEX.fullmatch(self.epoch):
            raise ValueError("Invalid native owner epoch")
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_clock = monotonic_clock or (lambda: time.monotonic_ns() // 1_000_000)
        self.revision_key = secrets.token_bytes(32)
        with self._database() as db:
            db.execute("CREATE TABLE IF NOT EXISTS personal_actor_context(actor_id TEXT PRIMARY KEY,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS personal_actor_wire(actor_id TEXT NOT NULL,message_id TEXT NOT NULL,wire_hash TEXT NOT NULL,byte_count INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(actor_id,message_id))")

    @contextmanager
    def _database(self):
        # Native source/service locks must precede SQLite, including post-checks.
        with self.source_guard if self.source_guard is not None else nullcontext():
            db = sqlite3.connect(self.store.database_path)
            try:
                with db:
                    yield db
            finally:
                db.close()

    def _decode(self, row):
        actor_id, expires, payload = row
        value = json.loads(self.store._decrypt(payload, "personal_actor_context", actor_id))
        fields = {"format", "actor_id", "peer_id", "fingerprint", "source_revision", "owner_epoch", "owner_hash", "storage_peer", "created_ms", "expires_ms", "created_monotonic_ms", "expires_monotonic_ms", "phase"}
        if (not isinstance(value, dict) or set(value) != fields or type(value["format"]) is not int or value["format"] != actor.VERSION or
                value["actor_id"] != actor_id or value["expires_ms"] != expires or
                value["storage_peer"] != actor.storage_peer(actor_id) or value["phase"] not in ("registered", "receiving", "cancelled")):
            raise ValueError("Invalid protected actor binding")
        actor.start(value["peer_id"])
        if (any(not isinstance(value[key], str) for key in ("fingerprint", "source_revision", "owner_epoch", "owner_hash")) or
                not FINGERPRINT.fullmatch(value["fingerprint"]) or not HEX.fullmatch(value["source_revision"]) or
                not HEX.fullmatch(value["owner_epoch"]) or not HEX.fullmatch(value["owner_hash"]) or
                type(value["created_ms"]) is not int or value["created_ms"] < 0 or type(expires) is not int or
                expires > 253402300799999 or not 0 < expires - value["created_ms"] <= LIFETIME_MS):
            raise ValueError("Invalid protected actor source")
        if (type(value["created_monotonic_ms"]) is not int or type(value["expires_monotonic_ms"]) is not int or
                value["created_monotonic_ms"] < 0 or value["expires_monotonic_ms"] - value["created_monotonic_ms"] != LIFETIME_MS):
            raise ValueError("Invalid protected actor monotonic lease")
        return value

    def _write(self, db, value):
        sealed = self.store._encrypt(personal.canonical(value), "personal_actor_context", value["actor_id"])
        db.execute("INSERT OR REPLACE INTO personal_actor_context VALUES(?,?,?)", (value["actor_id"], value["expires_ms"], sealed))

    def _require(self, db, handle, *, active=True, source=True):
        if not isinstance(handle, ActorHandle) or not isinstance(handle.owner_token, str) or not HEX.fullmatch(handle.owner_token):
            raise PermissionError("actor_not_found")
        row = db.execute("SELECT actor_id,expires_ms,payload FROM personal_actor_context WHERE actor_id=?", (handle.actor_id,)).fetchone()
        if row is None:
            raise PermissionError("actor_not_found")
        value = self._decode(row)
        token_hash = hashlib.sha256(handle.owner_token.encode("ascii")).hexdigest()
        if value["owner_epoch"] != self.epoch or not hmac.compare_digest(value["owner_hash"], token_hash):
            raise PermissionError("actor_not_found")
        if active and (value["phase"] == "cancelled" or value["expires_ms"] <= self.clock() or value["expires_monotonic_ms"] <= self.monotonic_clock()):
            raise PermissionError("actor_inactive")
        if source and self.current_source(value["peer_id"], value["fingerprint"]) != value["source_revision"]:
            raise PermissionError("actor_source_changed")
        return value

    def create(self, peer_id, fingerprint, source_revision, *, run_id=None):
        actor.start(peer_id)
        run_id = run_id or str(uuid.uuid4()); actor.start(run_id)
        fingerprint = fingerprint.upper() if isinstance(fingerprint, str) else ""
        if not FINGERPRINT.fullmatch(fingerprint) or not isinstance(source_revision, str) or not HEX.fullmatch(source_revision):
            raise ValueError("Invalid actor source snapshot")
        if self.current_source(peer_id, fingerprint) != source_revision:
            raise PermissionError("actor_source_changed")
        token = secrets.token_hex(32); created = self.clock(); monotonic = self.monotonic_clock()
        if type(created) is not int or not 0 <= created <= 253402300799999 - LIFETIME_MS or type(monotonic) is not int or monotonic < 0:
            raise ValueError("Invalid native actor clock")
        value = {"format": actor.VERSION, "actor_id": run_id, "peer_id": peer_id, "fingerprint": fingerprint,
            "source_revision": source_revision, "owner_epoch": self.epoch, "owner_hash": hashlib.sha256(token.encode("ascii")).hexdigest(),
            "storage_peer": actor.storage_peer(run_id), "created_ms": created, "expires_ms": created + LIFETIME_MS,
            "created_monotonic_ms": monotonic, "expires_monotonic_ms": monotonic + LIFETIME_MS, "phase": "registered"}
        with self._database() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = [self._decode(row) for row in db.execute("SELECT actor_id,expires_ms,payload FROM personal_actor_context")]
            active = sum(item["owner_epoch"] == self.epoch and item["phase"] != "cancelled" and
                item["expires_ms"] > created and item["expires_monotonic_ms"] > monotonic for item in rows)
            if len(rows) >= MAX_CONTEXTS or active >= MAX_ACTIVE:
                raise RuntimeError("actor_capacity")
            if any(item["actor_id"] == run_id for item in rows):
                raise ValueError("actor_identity_reused")
            if self.current_source(peer_id, fingerprint) != source_revision:
                raise PermissionError("actor_source_changed")
            self._write(db, value)
        return ActorHandle(run_id, token)

    def status(self, handle):
        with self._database() as db:
            value = self._require(db, handle, active=False, source=False)
            rows = db.execute("SELECT message_id,wire_hash,byte_count FROM personal_actor_wire WHERE actor_id=? ORDER BY message_id", (handle.actor_id,)).fetchall()
        packets, size = len(rows), sum(row[2] for row in rows)
        revision = hmac.new(self.revision_key, personal.canonical({"binding": value, "packets": rows}), hashlib.sha256).hexdigest()
        return {"actor_id": value["actor_id"], "peer_id": value["peer_id"], "fingerprint": value["fingerprint"],
            "phase": value["phase"], "expires_ms": value["expires_ms"], "packets": packets, "bytes": size, "revision": revision}

    def require_current(self, handle):
        """Native lifecycle check only, without returning raw content."""
        with self._database() as db:
            self._require(db, handle)
            self._require(db, handle)

    def put(self, handle, wire):
        """Store/deduplicate raw bytes only; neither result authorizes a success ACK."""
        if not isinstance(handle, ActorHandle):
            raise PermissionError("actor_not_found")
        if (not isinstance(wire, dict) or set(wire) != {"type", "v", "message_id", "kind", "created_ms", "expires_ms", "body"} or
                wire["type"] != "message" or type(wire["v"]) is not int or wire["v"] != 1 or
                wire["kind"] not in (actor.DATA_KIND, actor.ACK_KIND)):
            raise ValueError("Invalid raw actor wire frame")
        actor.start(wire["message_id"])
        if wire["kind"] == actor.DATA_KIND:
            kind, body = actor.unwrap(wire["body"])
            if kind == scope.DATA_KIND:
                kind = body["kind"]
            maximum_lifetime = 3600000 if kind == "personal_sync.request" else 86400000
        else:
            actor.validate_ack(wire["body"])
            maximum_lifetime = 60000
        clear = personal.canonical(wire)
        if (wire["body"]["run_id"] != handle.actor_id or len(clear) > personal.MAX_PACKET or
                type(wire["created_ms"]) is not int or type(wire["expires_ms"]) is not int or
                wire["created_ms"] < 0 or wire["expires_ms"] > 253402300799999 or
                not 0 < wire["expires_ms"] - wire["created_ms"] <= maximum_lifetime or
                wire["created_ms"] > self.clock() + 300000 or wire["expires_ms"] <= self.clock()):
            raise ValueError("Invalid actor wire identity/lifetime/budget")
        digest = hashlib.sha256(clear).hexdigest(); primary = handle.actor_id + ":" + wire["message_id"]
        sealed = self.store._encrypt(clear, "personal_actor_wire", primary)
        with self._database() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self._require(db, handle)
            old = db.execute("SELECT wire_hash,payload FROM personal_actor_wire WHERE actor_id=? AND message_id=?", (handle.actor_id, wire["message_id"])).fetchone()
            if old:
                if old[0] != digest or self.store._decrypt(old[1], "personal_actor_wire", primary) != clear:
                    raise ValueError("actor_frame_conflict")
                self._require(db, handle)
                return False
            count, size = db.execute("SELECT COUNT(*),COALESCE(SUM(length(payload)),0) FROM personal_actor_wire WHERE actor_id=?", (handle.actor_id,)).fetchone()
            total = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM personal_actor_wire").fetchone()[0]
            if count >= MAX_PACKETS or size + len(sealed) > MAX_ACTOR_BYTES or total + len(sealed) > MAX_TOTAL_BYTES:
                raise RuntimeError("actor_capacity")
            db.execute("INSERT INTO personal_actor_wire VALUES(?,?,?,?,?)", (handle.actor_id, wire["message_id"], digest, len(clear), sealed))
            value["phase"] = "receiving"; self._write(db, value)
            self._require(db, handle)
        return True

    def read(self, handle, message_id):
        with self._database() as db:
            self._require(db, handle)
            row = db.execute("SELECT wire_hash,byte_count,payload FROM personal_actor_wire WHERE actor_id=? AND message_id=?", (handle.actor_id, message_id)).fetchone()
            if row is None:
                raise KeyError("actor_packet_not_found")
            clear = self.store._decrypt(row[2], "personal_actor_wire", handle.actor_id + ":" + message_id)
            if len(clear) != row[1] or hashlib.sha256(clear).hexdigest() != row[0]:
                raise ValueError("Invalid protected actor packet")
            self._require(db, handle)
        return json.loads(clear)

    def cancel(self, handle):
        with self._database() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self._require(db, handle, active=False, source=False)
            value["phase"] = "cancelled"; self._write(db, value)
        return self.status(handle)
