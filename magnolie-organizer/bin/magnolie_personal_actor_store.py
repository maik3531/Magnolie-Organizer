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


class _CompletionSourceLost(PermissionError):
    pass


class NativeBookOwnerScope:
    """Native lifecycle fence, not a document tracker or a client-supplied revision."""
    def __init__(self):
        self._lock = threading.Lock()
        self._ready = False
        self._binding = None
        self._source = None
        self._save_sequence = 0
        self._saved_hash = ""

    def _invalidate_locked(self):
        self._binding = self._source = None
        self._save_sequence = 0
        self._saved_hash = ""

    def set_ready(self, ready):
        if type(ready) is not bool:
            raise TypeError("Native readiness must be boolean")
        with self._lock:
            self._ready = ready
            if not ready:
                self._invalidate_locked()

    def invalidate(self):
        with self._lock:
            self._invalidate_locked()

    def current(self, native_binding, native_available):
        with self._lock:
            return self._current_locked(native_binding, native_available)

    def _current_locked(self, native_binding, native_available):
        if (not self._ready or native_available is not True or
                not isinstance(native_binding, str) or not native_binding):
            self._invalidate_locked()
            return None
        if self._source is None or self._binding != native_binding:
            self._invalidate_locked()
            self._binding = native_binding
            self._source = secrets.token_hex(32)
        return self._source

    def record_saved(self, native_binding, native_available, sha256):
        """Native writer observation only, after actual store commit; never a client receipt."""
        if not isinstance(sha256, str) or not HEX.fullmatch(sha256):
            raise ValueError("Invalid native saved-book hash")
        with self._lock:
            source = self._current_locked(native_binding, native_available)
            if source is None:
                return None
            self._save_sequence += 1
            self._saved_hash = sha256
            return {"book_source": source, "sequence": self._save_sequence, "sha256": self._saved_hash}

    def save_state(self, native_binding, native_available):
        with self._lock:
            source = self._current_locked(native_binding, native_available)
            return None if source is None else {"book_source": source, "sequence": self._save_sequence, "sha256": self._saved_hash}


@dataclass(frozen=True)
class ActorHandle:
    actor_id: str
    owner_token: str = field(repr=False)


class ActorStore:
    # The native callback must bind the current book/profile scope as well as the
    # exact channel/key, fresh controls, ownership, grants and content scope.
    # A caller-supplied display fingerprint/revision alone is never authority.
    def __init__(self, store, current_source, *, epoch=None, clock=None, monotonic_clock=None, source_guard=None, source_owned=None):
        if not callable(current_source):
            raise TypeError("A native current-source validator is required")
        self.store = store
        self.current_source = current_source
        self.source_guard = source_guard
        self.source_owned = source_owned or (lambda actor_id: True)
        self.epoch = secrets.token_hex(32) if epoch is None else epoch
        if not isinstance(self.epoch, str) or not HEX.fullmatch(self.epoch):
            raise ValueError("Invalid native owner epoch")
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_clock = monotonic_clock or (lambda: time.monotonic_ns() // 1_000_000)
        self.revision_key = secrets.token_bytes(32)
        self.completion_guards = {}
        self.data_retired = set()
        with self._database() as db:
            db.execute("CREATE TABLE IF NOT EXISTS personal_actor_context(actor_id TEXT PRIMARY KEY,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS personal_actor_wire(actor_id TEXT NOT NULL,message_id TEXT NOT NULL,wire_hash TEXT NOT NULL,byte_count INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(actor_id,message_id))")
            db.execute("CREATE TABLE IF NOT EXISTS personal_actor_completion_wire(actor_id TEXT NOT NULL,message_id TEXT NOT NULL,wire_hash TEXT NOT NULL,byte_count INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(actor_id,message_id))")

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
                value["storage_peer"] != actor.storage_peer(actor_id) or value["phase"] not in ("registered", "receiving", "completion", "completed", "cancelled", "cancelled_clean")):
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
        if active and (value["actor_id"] in self.data_retired or value["phase"] not in ("registered", "receiving") or value["expires_ms"] <= self.clock() or value["expires_monotonic_ms"] <= self.monotonic_clock()):
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
        self.reap()
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
            active = sum(item["owner_epoch"] == self.epoch and item["phase"] in ("registered", "receiving", "completion") and
                item["expires_ms"] > created and item["expires_monotonic_ms"] > monotonic for item in rows)
            if len(rows) >= MAX_CONTEXTS or active >= MAX_ACTIVE:
                raise RuntimeError("actor_capacity")
            if any(item["actor_id"] == run_id for item in rows):
                raise ValueError("actor_identity_reused")
            if self.current_source(peer_id, fingerprint) != source_revision:
                raise PermissionError("actor_source_changed")
            self._write(db, value)
        return ActorHandle(run_id, token)

    def reap(self):
        """Retire before native cleanup; reclaim only expired or previous-epoch owners."""
        with self.source_guard if self.source_guard is not None else nullcontext():
            wall, monotonic = self.clock(), self.monotonic_clock()
            retired = []
            with self._database() as db:
                db.execute("BEGIN IMMEDIATE")
                rows = [self._decode(row) for row in db.execute("SELECT actor_id,expires_ms,payload FROM personal_actor_context")]
                for value in rows:
                    discard = (value["owner_epoch"] != self.epoch or value["expires_ms"] <= wall or
                        value["expires_monotonic_ms"] <= monotonic or value["created_monotonic_ms"] > monotonic)
                    if not discard and value["phase"] == "cancelled_clean":
                        continue
                    lost_source = False
                    if self.source_owned(value["actor_id"]):
                        if value["phase"] in ("completion", "completed"):
                            guard = self.completion_guards.get(value["actor_id"])
                            try:
                                state = guard("maintain", None) if guard is not None else False
                                lost_source = state is not True and state is not None
                            except (PermissionError, ValueError, TypeError):
                                lost_source = True
                        else:
                            lost_source = value["actor_id"] in self.data_retired or value["phase"] == "cancelled" or self.current_source(value["peer_id"], value["fingerprint"]) != value["source_revision"]
                    if discard or lost_source:
                        if value["phase"] not in ("cancelled", "cancelled_clean"):
                            value["phase"] = "cancelled"
                            self._write(db, value)
                        retired.append((value, discard))
            for value, discard in retired:
                self.data_retired.add(value["actor_id"])
                self.completion_guards.pop(value["actor_id"], None)
                # Existing domain cleanup runs after retirement and outside the registry
                # transaction. A failed cleanup leaves an inactive, retryable context.
                if value["phase"] != "cancelled_clean":
                    self.store.purge_personal(value["storage_peer"])
                with self._database() as db:
                    queued = db.execute("SELECT message_id,payload FROM outbox WHERE peer_id=?", (value["peer_id"],)).fetchall()
                    for message_id, payload in queued:
                        message = json.loads(self.store._decrypt(payload, "outbox", message_id))
                        if message.get("kind") == actor.DATA_KIND and message.get("body", {}).get("run_id") == value["actor_id"]:
                            actor.unwrap(message["body"])
                            db.execute("DELETE FROM outbox WHERE peer_id=? AND message_id=?", (value["peer_id"], message_id))
                    if discard:
                        db.execute("DELETE FROM personal_actor_wire WHERE actor_id=?", (value["actor_id"],))
                        db.execute("DELETE FROM personal_actor_completion_wire WHERE actor_id=?", (value["actor_id"],))
                        db.execute("DELETE FROM personal_actor_context WHERE actor_id=?", (value["actor_id"],))
                        self.data_retired.discard(value["actor_id"])
                    else:
                        value["phase"] = "cancelled_clean"
                        self._write(db, value)
            return len(retired)

    def status(self, handle):
        with self._database() as db:
            value = self._require(db, handle, active=False, source=False)
            rows = db.execute("SELECT message_id,wire_hash,byte_count FROM personal_actor_wire WHERE actor_id=? UNION ALL SELECT message_id,wire_hash,byte_count FROM personal_actor_completion_wire WHERE actor_id=? ORDER BY message_id", (handle.actor_id, handle.actor_id)).fetchall()
        packets, size = len(rows), sum(row[2] for row in rows)
        revision = hmac.new(self.revision_key, personal.canonical({"binding": value, "packets": rows}), hashlib.sha256).hexdigest()
        return {"actor_id": value["actor_id"], "peer_id": value["peer_id"], "fingerprint": value["fingerprint"],
            "phase": "cancelled" if value["phase"] == "cancelled_clean" else value["phase"], "expires_ms": value["expires_ms"], "packets": packets, "bytes": size, "revision": revision}

    def require_current(self, handle):
        """Native lifecycle check only, without returning raw content."""
        with self._database() as db:
            self._require(db, handle)
            self._require(db, handle)

    def _wire_payload(self, handle, wire, *, completion=False, fresh=True):
        if not isinstance(handle, ActorHandle):
            raise PermissionError("actor_not_found")
        if (not isinstance(wire, dict) or set(wire) != {"type", "v", "message_id", "kind", "created_ms", "expires_ms", "body"} or
                wire["type"] != "message" or type(wire["v"]) is not int or wire["v"] != 1 or
                wire["kind"] not in (actor.DATA_KIND, actor.ACK_KIND)):
            raise ValueError("Invalid raw actor wire frame")
        actor.start(wire["message_id"])
        if wire["kind"] == actor.DATA_KIND:
            kind, body = actor.unwrap(wire["body"])
            if completion and kind != "personal_sync.deletion_decision":
                raise ValueError("Completion storage accepts only deletion controls")
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
                fresh and (wire["created_ms"] > self.clock() + 300000 or wire["expires_ms"] <= self.clock())):
            raise ValueError("Invalid actor wire identity/lifetime/budget")
        return clear

    @staticmethod
    def _wire_usage(db, actor_id=None):
        where = " WHERE actor_id=?" if actor_id is not None else ""
        parameters = (actor_id, actor_id) if actor_id is not None else ()
        return db.execute("SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM (SELECT length(payload) AS bytes FROM personal_actor_wire" + where +
            " UNION ALL SELECT length(payload) AS bytes FROM personal_actor_completion_wire" + where + ")", parameters).fetchone()

    def put(self, handle, wire):
        """Store/deduplicate raw bytes only; neither result authorizes a success ACK."""
        clear = self._wire_payload(handle, wire)
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
            count, size = self._wire_usage(db, handle.actor_id)
            total = self._wire_usage(db)[1]
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

    @contextmanager
    def _completion_database(self, handle):
        with self.source_guard if self.source_guard is not None else nullcontext():
            try:
                with self._database() as db:
                    db.execute("BEGIN IMMEDIATE")
                    yield db
            except _CompletionSourceLost as error:
                # Retire outside the failed transaction, so its rollback cannot
                # revive a source which the native callback has already denied.
                self.completion_guards.pop(handle.actor_id, None)
                self.data_retired.add(handle.actor_id)
                try:
                    self.cancel(handle)
                except (PermissionError, sqlite3.Error):
                    pass  # The volatile capability is already irreversibly gone.
                raise PermissionError(str(error)) from None

    def _require_completion(self, db, handle, operation, wire=None):
        value = self._require(db, handle, active=False, source=False)
        if not self.source_owned(value["actor_id"]):
            raise PermissionError("actor_not_found")
        if value["phase"] not in ("completion", "completed"):
            raise PermissionError("actor_completion_inactive")
        wall, mono = self.clock(), self.monotonic_clock()
        if (type(wall) is not int or type(mono) is not int or
                not value["created_ms"] <= wall < value["expires_ms"] or
                not value["created_monotonic_ms"] <= mono < value["expires_monotonic_ms"]):
            raise _CompletionSourceLost("actor_completion_inactive")
        guard = self.completion_guards.get(value["actor_id"])
        if guard is None:
            raise _CompletionSourceLost("actor_completion_owner_lost")
        try:
            result = guard(operation, wire)
        except PermissionError as error:
            raise _CompletionSourceLost("actor_completion_source_changed") from error
        except ValueError as error:
            if wire is not None:
                raise  # Unexpected control metadata must not cancel a valid owner.
            raise _CompletionSourceLost("actor_completion_source_changed") from error
        if result is None:
            raise PermissionError("actor_completion_not_ready")
        if result is not True:
            raise _CompletionSourceLost("actor_completion_source_changed")
        return value

    def begin_completion(self, handle, native_guard):
        """Close data irrevocably; register a native-only metadata validator.

        The callback must bind the exact saved claim, control IDs/targets and
        fresh native authority/resulting scope. True permits that metadata
        operation, None waits for fresh evidence, False retires the owner.
        It must not perform document writes or network/GUI I/O under this guard.
        """
        if not callable(native_guard):
            raise TypeError("A native completion validator is required")
        installed = False
        try:
            with self._completion_database(handle) as db:
                value = self._require(db, handle, active=False, source=False)
                if value["phase"] in ("completion", "completed"):
                    if self.completion_guards.get(handle.actor_id) is not native_guard:
                        raise PermissionError("actor_completion_owner_changed")
                    self._require_completion(db, handle, "begin")
                else:
                    self._require(db, handle)
                    self.completion_guards[handle.actor_id] = native_guard
                    installed = True
                    value["phase"] = "completion"
                    self._write(db, value)
                    self._require_completion(db, handle, "begin")
                    try:
                        self._require(db, handle, active=False, source=True)
                    except PermissionError as error:
                        raise _CompletionSourceLost("actor_completion_source_changed") from error
                    self.data_retired.add(handle.actor_id)
        except BaseException:
            if installed and self.completion_guards.get(handle.actor_id) is native_guard:
                self.completion_guards.pop(handle.actor_id, None)
            raise
        return self.status(handle)

    def put_completion_control(self, handle, wire):
        """Persist only correlated deletion-control/ACK metadata, never content.

        A stored packet is not a successful application receipt. Native callers
        must still prove the document save before acknowledging or completing.
        """
        clear = self._wire_payload(handle, wire, completion=True)
        snapshot = json.loads(clear)
        digest = hashlib.sha256(clear).hexdigest(); primary = handle.actor_id + ":" + wire["message_id"]
        sealed = self.store._encrypt(clear, "personal_actor_completion_wire", primary)
        with self._completion_database(handle) as db:
            self._require_completion(db, handle, "put", snapshot)
            if db.execute("SELECT 1 FROM personal_actor_wire WHERE actor_id=? AND message_id=?", (handle.actor_id, wire["message_id"])).fetchone():
                raise ValueError("actor_frame_conflict")
            old = db.execute("SELECT wire_hash,payload FROM personal_actor_completion_wire WHERE actor_id=? AND message_id=?", (handle.actor_id, wire["message_id"])).fetchone()
            if old:
                if old[0] != digest or self.store._decrypt(old[1], "personal_actor_completion_wire", primary) != clear:
                    raise ValueError("actor_frame_conflict")
                self._require_completion(db, handle, "put", snapshot)
                if personal.canonical(snapshot) != clear:
                    raise ValueError("actor_completion_callback_mutated_packet")
                return False
            count, size = self._wire_usage(db, handle.actor_id)
            total = self._wire_usage(db)[1]
            if count >= MAX_PACKETS or size + len(sealed) > MAX_ACTOR_BYTES or total + len(sealed) > MAX_TOTAL_BYTES:
                raise RuntimeError("actor_capacity")
            db.execute("INSERT INTO personal_actor_completion_wire VALUES(?,?,?,?,?)", (handle.actor_id, wire["message_id"], digest, len(clear), sealed))
            self._require_completion(db, handle, "put", snapshot)
            if personal.canonical(snapshot) != clear:
                raise ValueError("actor_completion_callback_mutated_packet")
        return True

    def read_completion_controls(self, handle):
        with self._completion_database(handle) as db:
            self._require_completion(db, handle, "read")
            rows = db.execute("SELECT message_id,wire_hash,byte_count,payload FROM personal_actor_completion_wire WHERE actor_id=? ORDER BY message_id", (handle.actor_id,)).fetchall()
            result = []
            for message_id, digest, size, payload in rows:
                clear = self.store._decrypt(payload, "personal_actor_completion_wire", handle.actor_id + ":" + message_id)
                if len(clear) != size or hashlib.sha256(clear).hexdigest() != digest:
                    raise ValueError("Invalid protected actor completion packet")
                wire = json.loads(clear)
                if wire.get("message_id") != message_id or self._wire_payload(handle, wire, completion=True, fresh=False) != clear:
                    raise ValueError("Invalid protected actor completion packet")
                result.append(wire)
            self._require_completion(db, handle, "read")
        return result

    def finish_completion(self, handle):
        with self._completion_database(handle) as db:
            value = self._require_completion(db, handle, "finish")
            value["phase"] = "completed"
            self._write(db, value)
            self._require_completion(db, handle, "finish")
        return self.status(handle)

    def cancel(self, handle):
        with self._database() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self._require(db, handle, active=False, source=False)
            self.data_retired.add(handle.actor_id)
            self.completion_guards.pop(handle.actor_id, None)
            if value["phase"] != "cancelled_clean":
                value["phase"] = "cancelled"; self._write(db, value)
        return self.status(handle)
