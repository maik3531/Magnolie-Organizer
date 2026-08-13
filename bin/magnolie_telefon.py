#!/usr/bin/env python3
"""Unabhaengige Magnolie-Telefonverbindung (Protokollfassung 1)."""

import base64
import hashlib
import hmac
import json
import os
import re
import socket
import sqlite3
import struct
import subprocess
import tempfile
import threading
import time
import uuid

PROTOCOL = "magnolie-phone/1"
PORT = 8741
MDNS_TYPE = "_magnolie-phone._tcp.local."
BLUETOOTH_UUID = "7b1d9e2a-5c43-4f68-a172-9d30e6b4c851"
PAIRING_SECONDS = 120
PAIR_FRAME_MAX = 65536
SECURE_FRAME_MAX = 1048576
APPLICATION_MAX = 262144
CONTROL_FIELDS = {"p", "type"}
PAIR_COMMIT_MS = 10 * 60 * 1000
CLOCK_SKEW_MS = 5 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
EVENT_RETENTION_MS = 7 * DAY_MS
CAPABILITY_NAMES = {"device_status", "sms_send", "sms_received",
                    "selected_notifications_readonly", "call_control",
                    "transport.bluetooth_rfcomm"}
GRANT_NAMES = {"device_status", "sms_send", "sms_received",
               "selected_notifications_readonly", "call_control"}
CAPABILITY_REASONS = {"available", "not_implemented", "no_hardware", "disabled",
                      "permission_missing", "os_restricted"}
ACK_ERRORS = {"none", "expired", "invalid_schema", "unsupported", "not_granted",
              "too_large", "permanent_failure"}
RETRY_MS = (1000, 2000, 5000, 10000, 30000, 60000)
BLUETOOTH_FALLBACK_SECONDS = 15
BLUETOOTH_RETRY_SECONDS = 60
BLUETOOTH_ADDRESS = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


def now_ms():
    return int(time.time() * 1000)


def desktop_capabilities(revision=1, bluetooth_available=False,
                         bluetooth_reason="not_implemented"):
    items = {}
    for name in sorted(CAPABILITY_NAMES):
        available = name == "device_status" or (
            name == "transport.bluetooth_rfcomm" and bluetooth_available)
        items[name] = {"available": available,
                       "reason": "available" if available else (
                           bluetooth_reason if name == "transport.bluetooth_rfcomm"
                           else "not_implemented"),
                       "versions": [1]}
    return {"revision": revision, "items": items}


def desktop_grants(revision=1):
    return {"revision": revision,
            "grants": {name: name in {"device_status", "sms_send"}
                       for name in sorted(GRANT_NAMES)}}


def canonical(value):
    """Canonical JSON subset used by phone protocol version 1."""
    def check(item):
        if item is None or isinstance(item, (str, bool)):
            return
        if isinstance(item, int) and not isinstance(item, bool):
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("unsupported canonical JSON value")
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def strict_json(raw):
    duplicates = []
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_float=lambda _value: (_ for _ in ()).throw(
                           ValueError("fractions are forbidden")),
                       parse_constant=lambda _value: (_ for _ in ()).throw(
                           ValueError("non-finite number")))
    if duplicates or not isinstance(value, dict):
        raise ValueError("invalid JSON object")
    canonical(value)
    return value


def b64(data):
    return base64.b64encode(data).decode("ascii")


def unb64(value, length):
    if not isinstance(value, str):
        raise ValueError("invalid base64")
    data = base64.b64decode(value, validate=True)
    if len(data) != length or b64(data) != value:
        raise ValueError("invalid base64")
    return data


def valid_uuid(value, version=None):
    try:
        parsed = uuid.UUID(value)
        return str(parsed) == value and (version is None or parsed.version == version)
    except (AttributeError, ValueError):
        return False


def hkdf(ikm, salt, info, length):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(hashes.SHA256(), length, salt, info).derive(ikm)


def fingerprint(public):
    digest = hashlib.sha256(b"magnolie-phone-fingerprint-v1\0" + public).hexdigest()
    text = digest[:16].upper()
    return "-".join(text[index:index + 4] for index in range(0, 16, 4))


def pairing_material(pair_init, pair_response, own_ephemeral, own_static):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    transcript = hashlib.sha256(canonical(pair_init) + canonical(pair_response)).digest()
    ephemeral = own_ephemeral.exchange(X25519PublicKey.from_public_bytes(
        unb64(pair_init["ephemeral_public"], 32)))
    shared = own_static.exchange(X25519PublicKey.from_public_bytes(
        unb64(pair_init["static_public"], 32)))
    if ephemeral == b"\0" * 32 or shared == b"\0" * 32:
        raise ValueError("invalid X25519 peer key")
    key = hkdf(ephemeral + shared,
               hashlib.sha256(b"magnolie-phone-pair-v1/salt\0" + transcript).digest(),
               b"magnolie-phone-pair-v1/key\0" + transcript, 32)
    code_hash = hmac.new(key, b"magnolie-phone-pair-v1/code\0" + transcript,
                         hashlib.sha256).digest()
    code = int.from_bytes(code_hash[:4], "big") % 1000000
    return transcript, key, "%03d %03d" % (code // 1000, code % 1000)


def proof(key, label, side, transcript):
    return hmac.new(key, label + side.encode("utf-8") + transcript,
                    hashlib.sha256).digest()


def _atomic(path, data, mode=0o600):
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".phone-", dir=folder)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as target:
            descriptor = -1
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except OSError:
            pass


class PhoneStore:
    """Phone-only identity, peer blob and SQLite queue."""

    def __init__(self, root, display_name):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption,
                                                                  PrivateFormat, PublicFormat)
        self.root = root
        os.makedirs(root, mode=0o700, exist_ok=True)
        os.chmod(root, 0o700)
        self.identity_path = os.path.join(root, "identity.json")
        self.private_path = os.path.join(root, "identity.key")
        self.storage_path = os.path.join(root, "storage.key")
        self.peers_path = os.path.join(root, "peers.json")
        self.database_path = os.path.join(root, "phone.db")
        self.settings_path = os.path.join(root, "settings.json")
        if os.path.exists(self.storage_path):
            self.storage_key = self._read_exact(self.storage_path, 32)
        else:
            self.storage_key = os.urandom(32)
            _atomic(self.storage_path, self.storage_key)
        if os.path.exists(self.identity_path):
            with open(self.identity_path, "r", encoding="utf-8") as source:
                self.identity = json.load(source)
            expected = {"storage_version", "device_id", "role", "display_name",
                        "static_public"}
            if (set(self.identity) != expected or self.identity["storage_version"] != 1
                    or self.identity["role"] != "desktop"
                    or not valid_uuid(self.identity["device_id"])
                    or len(self.identity["display_name"]) not in range(1, 61)):
                raise RuntimeError("Telefonidentitaet ist beschaedigt.")
            public = unb64(self.identity["static_public"], 32)
            private_raw = self._decrypt_file(self.private_path, "identity", "private")
            self.private = X25519PrivateKey.from_private_bytes(private_raw)
            own_public = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            if not hmac.compare_digest(public, own_public):
                raise RuntimeError("Telefonidentitaet ist beschaedigt.")
        else:
            self.private = X25519PrivateKey.generate()
            private_raw = self.private.private_bytes(Encoding.Raw, PrivateFormat.Raw,
                                                     NoEncryption())
            public = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            self.identity = {"storage_version": 1, "device_id": str(uuid.uuid4()),
                             "role": "desktop", "display_name": display_name[:60] or "Magnolie",
                             "static_public": b64(public)}
            _atomic(self.identity_path, json.dumps(self.identity, ensure_ascii=False,
                    indent=1).encode("utf-8"))
            self._encrypt_file(self.private_path, private_raw, "identity", "private")
        self.peers = self._load_peers()
        self._database()
        self.cleanup()

    @staticmethod
    def _read_exact(path, length):
        with open(path, "rb") as source:
            data = source.read(length + 1)
        if len(data) != length:
            raise RuntimeError("Telefon-Speicherschluessel ist beschaedigt.")
        return data

    def _encrypt(self, data, object_type, primary):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        aad = b"magnolie-phone-storage-v1\0" + object_type.encode() + primary.encode()
        return nonce + AESGCM(self.storage_key).encrypt(nonce, data, aad)

    def _decrypt(self, data, object_type, primary):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(data) < 29:
            raise RuntimeError("Telefonablage ist beschaedigt.")
        aad = b"magnolie-phone-storage-v1\0" + object_type.encode() + primary.encode()
        return AESGCM(self.storage_key).decrypt(data[:12], data[12:], aad)

    def _encrypt_file(self, path, data, object_type, primary):
        _atomic(path, self._encrypt(data, object_type, primary))

    def _decrypt_file(self, path, object_type, primary):
        with open(path, "rb") as source:
            return self._decrypt(source.read(), object_type, primary)

    def _load_peers(self):
        if not os.path.exists(self.peers_path):
            return []
        raw = self._decrypt_file(self.peers_path, "peers", "all")
        peers = strict_json(raw)
        if set(peers) != {"storage_version", "items"} or peers["storage_version"] != 1:
            raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
        if not isinstance(peers["items"], list) or len(peers["items"]) > 8:
            raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
        now = now_ms()
        result = []
        for peer in peers["items"]:
            if set(peer.get("grants", {})) == GRANT_NAMES:
                peer["grants"] = {"revision": 1, "grants": peer["grants"]}
            if "bluetooth" not in peer:
                peer["bluetooth"] = {"enabled": False, "address": ""}
            if "local_grants" not in peer:
                peer["local_grants"] = desktop_grants()
            self._validate_peer(peer)
            if peer["state"] != "pair_commit_pending" or peer["pending_expires_ms"] > now:
                result.append(peer)
        if len(result) != len(peers["items"]):
            self.peers = result
            self.save_peers()
        return result

    @staticmethod
    def _validate_peer(peer):
        common = {"device_id", "display_name", "static_public", "state", "grants",
                  "local_grants", "capabilities", "last_contact_ms", "bluetooth"}
        pending = {"pending_transcript", "pending_phone_finish_proof",
                   "pending_desktop_finish_proof", "pending_expires_ms"}
        if (not isinstance(peer, dict) or peer.get("state") not in {
                "paired", "pair_commit_pending"}
                or set(peer) != common | (pending if peer.get("state") ==
                                          "pair_commit_pending" else set())
                or not valid_uuid(peer.get("device_id"))
                or not valid_text(peer.get("display_name"), 1, 60)
                or isinstance(peer.get("last_contact_ms"), bool)
                or not isinstance(peer.get("last_contact_ms"), int)):
            raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
        bluetooth = peer.get("bluetooth")
        if (not isinstance(bluetooth, dict) or set(bluetooth) != {"enabled", "address"}
                or not isinstance(bluetooth["enabled"], bool)
                or (bluetooth["address"] and not BLUETOOTH_ADDRESS.fullmatch(
                    bluetooth["address"]))
                or bluetooth["enabled"] != bool(bluetooth["address"])):
            raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
        unb64(peer["static_public"], 32)
        validate_grants(peer["grants"])
        validate_grants(peer["local_grants"])
        if peer["capabilities"]:
            validate_capabilities(peer["capabilities"])
        if peer["state"] == "pair_commit_pending":
            unb64(peer["pending_transcript"], 32)
            unb64(peer["pending_phone_finish_proof"], 32)
            unb64(peer["pending_desktop_finish_proof"], 32)
            if (isinstance(peer["pending_expires_ms"], bool)
                    or not isinstance(peer["pending_expires_ms"], int)):
                raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")

    def save_peers(self):
        raw = canonical({"storage_version": 1, "items": self.peers})
        self._encrypt_file(self.peers_path, raw, "peers", "all")

    def set_bluetooth(self, peer_id, enabled, address=""):
        peer = self.peer(peer_id)
        if not peer or peer.get("state") != "paired":
            raise RuntimeError("Das Telefon ist nicht gekoppelt.")
        normalized = str(address or "").strip().upper()
        if enabled and not BLUETOOTH_ADDRESS.fullmatch(normalized):
            raise ValueError("invalid Bluetooth address")
        peer["bluetooth"] = {"enabled": bool(enabled),
                             "address": normalized if enabled else ""}
        self.save_peers()

    def settings(self):
        try:
            with open(self.settings_path, "r", encoding="utf-8") as source:
                value = json.load(source)
            return {"enabled": value.get("enabled") is True}
        except (OSError, ValueError, AttributeError):
            return {"enabled": False}

    def save_settings(self, enabled):
        _atomic(self.settings_path, canonical({"enabled": bool(enabled)}))

    def peer(self, device_id):
        return next((peer for peer in self.peers if peer.get("device_id") == device_id), None)

    def _database(self):
        with sqlite3.connect(self.database_path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
              CREATE TABLE IF NOT EXISTS outbox(
                message_id TEXT PRIMARY KEY, peer_id TEXT NOT NULL, kind TEXT NOT NULL,
                created_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL, payload BLOB NOT NULL,
                attempts INTEGER NOT NULL, next_attempt_ms INTEGER NOT NULL, last_error TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS inbox(
                message_id TEXT NOT NULL, peer_id TEXT NOT NULL, kind TEXT NOT NULL,
                received_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL, payload BLOB NOT NULL,
                state TEXT NOT NULL, PRIMARY KEY(peer_id,message_id));
              CREATE TABLE IF NOT EXISTS dedupe(
                message_id TEXT NOT NULL, peer_id TEXT NOT NULL, result TEXT NOT NULL,
                error TEXT NOT NULL, seen_ms INTEGER NOT NULL, PRIMARY KEY(peer_id,message_id));
              CREATE TABLE IF NOT EXISTS sms_effect(client_ref TEXT PRIMARY KEY,
                state TEXT NOT NULL, first_seen_ms INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
            """)
        os.chmod(self.database_path, 0o600)
        for suffix in ("-wal", "-shm"):
            if os.path.exists(self.database_path + suffix):
                os.chmod(self.database_path + suffix, 0o600)

    def cache_status(self, peer_id, status):
        encrypted = self._encrypt(canonical({"cached_ms": now_ms(), "status": status}),
                                  "device_status", peer_id)
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       ("device_status:" + peer_id, encrypted))

    def register_status_request(self, peer_id, request_id, expires_ms):
        key = "status_request:%s:%s" % (peer_id, request_id)
        encrypted = self._encrypt(canonical({"expires_ms": expires_ms}),
                                  "status_request", key)
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, encrypted))

    def consume_status_request(self, peer_id, request_id):
        key = "status_request:%s:%s" % (peer_id, request_id)
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            db.execute("DELETE FROM meta WHERE key=?", (key,))
        if not row:
            return False
        value = strict_json(self._decrypt(row[0], "status_request", key))
        return value["expires_ms"] + CLOCK_SKEW_MS >= now_ms()

    def status(self, peer_id):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT value FROM meta WHERE key=?",
                             ("device_status:" + peer_id,)).fetchone()
        if not row:
            return {}
        value = strict_json(self._decrypt(row[0], "device_status", peer_id))
        if set(value) == {"cached_ms", "status"}:
            cached, status = value["cached_ms"], value["status"]
        else:
            cached, status = value.get("captured_ms", 0), value
        if now_ms() - cached > DAY_MS:
            return {}
        return status

    def queue(self, peer_id, kind, body, ttl_ms):
        now = now_ms()
        if not isinstance(ttl_ms, int) or not 0 < ttl_ms <= 30 * DAY_MS:
            raise ValueError("invalid message lifetime")
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
                   "kind": kind, "created_ms": now, "expires_ms": now + ttl_ms,
                   "body": body}
        encrypted = self._encrypt(canonical(message), "outbox", message["message_id"])
        with sqlite3.connect(self.database_path) as db:
            size = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM outbox").fetchone()[0]
            if size + len(encrypted) > 50 * 1024 * 1024:
                raise RuntimeError("queue_full")
            db.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?,?,?)",
                       (message["message_id"], peer_id, kind, now, now + ttl_ms,
                        encrypted, 0, now, ""))
        return message

    def pending(self, peer_id):
        now = now_ms()
        with sqlite3.connect(self.database_path) as db:
            rows = db.execute("SELECT message_id,payload FROM outbox WHERE peer_id=? AND "
                              "expires_ms>? AND next_attempt_ms<=? ORDER BY created_ms LIMIT 32",
                              (peer_id, now, now)).fetchall()
        return [strict_json(self._decrypt(payload, "outbox", message_id))
                for message_id, payload in rows]

    def mark_attempt(self, peer_id, message_id):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT attempts FROM outbox WHERE peer_id=? AND message_id=?",
                             (peer_id, message_id)).fetchone()
            if not row:
                return
            attempts = row[0] + 1
            base = RETRY_MS[attempts - 1] if attempts <= len(RETRY_MS) else 300000
            jitter = 1.0 if attempts <= len(RETRY_MS) else 0.8 + int.from_bytes(
                os.urandom(2), "big") / 65535 * 0.4
            db.execute("UPDATE outbox SET attempts=?,next_attempt_ms=?,last_error=? "
                       "WHERE peer_id=? AND message_id=?",
                       (attempts, now_ms() + int(base * jitter), "missing_ack",
                        peer_id, message_id))

    def acknowledge(self, peer_id, message_id):
        with sqlite3.connect(self.database_path) as db:
            db.execute("DELETE FROM outbox WHERE peer_id=? AND message_id=?",
                       (peer_id, message_id))

    def dedupe_result(self, peer_id, message_id):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT result,error FROM dedupe WHERE peer_id=? AND message_id=?",
                             (peer_id, message_id)).fetchone()
        return tuple(row) if row else None

    def remember_result(self, peer_id, message_id, result, error):
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT OR REPLACE INTO dedupe VALUES(?,?,?,?,?)",
                        (message_id, peer_id, result, error, int(time.time() * 1000)))

    def remember_message(self, peer_id, message, result, error):
        seen = now_ms()
        encrypted = self._encrypt(canonical(message), "inbox", message["message_id"])
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO inbox VALUES(?,?,?,?,?,?,?)",
                       (message["message_id"], peer_id, message["kind"], seen,
                        message["expires_ms"], encrypted, result))
            db.execute("INSERT OR REPLACE INTO dedupe VALUES(?,?,?,?,?)",
                       (message["message_id"], peer_id, result, error, seen))

    def cleanup(self):
        now = now_ms()
        with sqlite3.connect(self.database_path) as db:
            db.execute("DELETE FROM outbox WHERE expires_ms<=?", (now,))
            db.execute("DELETE FROM inbox WHERE received_ms<?", (now - 30 * DAY_MS,))
            db.execute("DELETE FROM inbox WHERE kind IN ('sms_received.event',"
                       "'selected_notifications_readonly.event') AND received_ms<?",
                       (now - EVENT_RETENTION_MS,))
            db.execute("DELETE FROM dedupe WHERE seen_ms<?", (now - 90 * DAY_MS,))
            db.execute("DELETE FROM sms_effect WHERE first_seen_ms<?", (now - 90 * DAY_MS,))
            for table, order, limit in (("inbox", "received_ms", 10000),
                                        ("sms_effect", "first_seen_ms", 100000)):
                db.execute("DELETE FROM %s WHERE rowid IN (SELECT rowid FROM %s ORDER BY %s "
                           "DESC LIMIT -1 OFFSET ?)" % (table, table, order), (limit,))
            peers = [row[0] for row in db.execute("SELECT DISTINCT peer_id FROM dedupe")]
            for peer_id in peers:
                db.execute("DELETE FROM dedupe WHERE rowid IN (SELECT rowid FROM dedupe "
                           "WHERE peer_id=? ORDER BY seen_ms DESC LIMIT -1 OFFSET 100000)",
                           (peer_id,))
            request_rows = db.execute("SELECT key,value FROM meta WHERE key LIKE 'status_request:%'").fetchall()
            for key, value in request_rows:
                try:
                    expired = strict_json(self._decrypt(value, "status_request", key))[
                        "expires_ms"] + CLOCK_SKEW_MS < now
                except Exception:
                    expired = True
                if expired:
                    db.execute("DELETE FROM meta WHERE key=?", (key,))

    def remember_sms(self, client_ref, state):
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT INTO sms_effect(client_ref,state,first_seen_ms) VALUES(?,?,?)",
                       (client_ref, state, now_ms()))

    def sms_state(self, client_ref):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT state FROM sms_effect WHERE client_ref=?",
                             (client_ref,)).fetchone()
        return row[0] if row else ""

    def update_sms(self, client_ref, state):
        with sqlite3.connect(self.database_path) as db:
            changed = db.execute("UPDATE sms_effect SET state=? WHERE client_ref=?",
                                 (state, client_ref)).rowcount
        return bool(changed)

    def next_revision(self, name):
        key = "own_revision:" + name
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            revision = int(bytes(row[0]).decode("ascii")) + 1 if row else 1
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                       (key, str(revision).encode("ascii")))
        return revision


class SecureChannel:
    def __init__(self, sock, sid, send_key, send_prefix, receive_key, receive_prefix):
        self.sock, self.sid = sock, sid
        self.send_key, self.send_prefix = send_key, send_prefix
        self.receive_key, self.receive_prefix = receive_key, receive_prefix
        self.send_seq = self.receive_seq = 0
        self.lock = threading.Lock()
        self.last_send = time.monotonic()

    def send(self, payload):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = canonical(payload)
        if len(raw) > APPLICATION_MAX:
            raise ValueError("application message too large")
        with self.lock:
            aad_object = {"p": PROTOCOL, "sid": b64(self.sid), "seq": self.send_seq,
                          "dir": "desktop_to_phone"}
            encrypted = AESGCM(self.send_key).encrypt(
                self.send_prefix + self.send_seq.to_bytes(8, "big"), raw,
                canonical(aad_object))
            self.send_seq += 1
            send_frame(self.sock, dict(aad_object, ciphertext=b64(encrypted)))
            self.last_send = time.monotonic()

    def receive(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        frame = receive_frame(self.sock, SECURE_FRAME_MAX)
        expected = {"p": PROTOCOL, "sid": b64(self.sid), "seq": self.receive_seq,
                    "dir": "phone_to_desktop"}
        if set(frame) != set(expected) | {"ciphertext"} or any(
                frame.get(key) != value for key, value in expected.items()):
            raise ValueError("secure envelope mismatch")
        ciphertext = base64.b64decode(frame["ciphertext"], validate=True)
        if b64(ciphertext) != frame["ciphertext"] or len(ciphertext) < 16:
            raise ValueError("invalid secure ciphertext")
        raw = AESGCM(self.receive_key).decrypt(
            self.receive_prefix + self.receive_seq.to_bytes(8, "big"), ciphertext,
            canonical(expected))
        self.receive_seq += 1
        if len(raw) > APPLICATION_MAX:
            raise ValueError("application message too large")
        value = strict_json(raw)
        if not hmac.compare_digest(raw, canonical(value)):
            raise ValueError("secure plaintext is not canonical JSON")
        return value


class BlueZBluetoothBackend:
    """Optional BlueZ/PyBluez adapter for outgoing phone RFCOMM sockets."""

    @staticmethod
    def _bluetoothctl(*arguments):
        return subprocess.run(["bluetoothctl", *arguments], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
            check=False, text=True)

    def availability(self):
        if not hasattr(socket, "AF_BLUETOOTH"):
            return False, "no_hardware"
        try:
            result = self._bluetoothctl("show")
            if result.returncode == 0 and "Powered: yes" in result.stdout:
                return True, "available"
            return False, "no_hardware"
        except (OSError, subprocess.SubprocessError):
            return False, "os_restricted"

    def paired(self, address):
        try:
            result = self._bluetoothctl("info", address)
            return result.returncode == 0 and "Paired: yes" in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    def connect(self, address, service_uuid):
        if service_uuid != BLUETOOTH_UUID or not self.paired(address):
            raise PermissionError("Bluetooth device is not system-paired")
        try:
            import bluetooth
            services = bluetooth.find_service(uuid=service_uuid, address=address)
            channels = [item.get("port") for item in services
                        if str(item.get("service-id", service_uuid)).lower() == service_uuid]
            if not channels:
                raise OSError("Magnolie Telefon RFCOMM service not found")
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        except ImportError:
            # Resolve SDP first; never guess a fixed channel belonging to another profile.
            try:
                result = subprocess.run(
                    ["sdptool", "search", "--bdaddr", address, service_uuid],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=8, check=False, text=True)
            except (OSError, subprocess.SubprocessError) as error:
                raise OSError("RFCOMM service discovery is unavailable") from error
            matches = re.findall(r"Channel:\s*([1-9]|[12][0-9]|30)\b", result.stdout)
            if result.returncode or len(matches) != 1:
                raise OSError("Magnolie Telefon RFCOMM service not found")
            channels = [int(matches[0])]
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                 socket.BTPROTO_RFCOMM)
        sock.connect((address, int(channels[0])))
        return sock


def send_frame(sock, value):
    raw = canonical(value)
    sock.sendall(struct.pack(">I", len(raw)) + raw)


def receive_exact(sock, length):
    parts = []
    while length:
        part = sock.recv(length)
        if not part:
            raise EOFError("incomplete frame")
        parts.append(part)
        length -= len(part)
    return b"".join(parts)


def receive_frame(sock, maximum):
    length = struct.unpack(">I", receive_exact(sock, 4))[0]
    if not 0 < length <= maximum:
        raise ValueError("invalid frame length")
    return strict_json(receive_exact(sock, length))


class PhoneService:
    """Own listener, pairing state, status cache and phone sessions."""

    def __init__(self, root, display_name, callback=None, bluetooth_backend=None):
        self.store = PhoneStore(root, display_name)
        self.callback = callback or (lambda _event, _payload: None)
        self.enabled = self.store.settings()["enabled"]
        self.server = self.thread = self.mdns = None
        self.stop_event = threading.Event()
        self.pairing_token = None
        self.pairing_until = 0
        self.pairings = {}
        self.connections = {}
        self.status_requests = {}
        self.lock = threading.RLock()
        self.active_by_ip = {}
        self.connection_transports = {}
        self.bluetooth_backend = bluetooth_backend or BlueZBluetoothBackend()
        self.bluetooth_thread = None
        self.wifi_missing_since = {}
        self.bluetooth_retry_at = {}

    def report(self):
        bluetooth_available, bluetooth_reason = self.bluetooth_backend.availability()
        peers = []
        for peer in self.store.peers:
            peer_id = peer.get("device_id", "")
            transport = self.connection_transports.get(peer_id, "")
            bluetooth = peer.get("bluetooth", {"enabled": False, "address": ""})
            peers.append({"device_id": peer_id, "display_name": peer.get("display_name", ""),
                          "fingerprint": fingerprint(unb64(peer["static_public"], 32)),
                           "state": "online_" + transport if transport else "offline",
                           "transport": transport,
                          "last_contact_ms": peer.get("last_contact_ms", 0),
                          "status": self.store.status(peer_id),
                           "capabilities": peer.get("capabilities", {}),
                            "grants": peer.get("grants", {}),
                            "local_grants": peer.get("local_grants", {}),
                           "bluetooth_enabled": bluetooth["enabled"],
                           "bluetooth_address": bluetooth["address"]})
        return {"possible": True, "enabled": self.enabled,
                "listening": bool(self.server), "port": PORT,
                "device_id": self.store.identity["device_id"],
                "display_name": self.store.identity["display_name"],
                "fingerprint": fingerprint(unb64(self.store.identity["static_public"], 32)),
                "pairing": bool(self.pairing_token and time.monotonic() < self.pairing_until),
                 "peers": peers, "bluetooth": {"available": bluetooth_available,
                    "reason": bluetooth_reason, "uuid": BLUETOOTH_UUID}}

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.store.save_settings(self.enabled)
        if self.enabled:
            self.start()
        else:
            self.stop()
        self.callback("status", self.report())

    def start(self):
        if not self.enabled or self.server:
            return bool(self.server)
        self.stop_event.clear()
        server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        try:
            server.bind(("::", PORT))
            server.listen(8)
            server.settimeout(0.5)
        except OSError:
            server.close()
            return False
        self.server = server
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()
        self._publish()
        if not self.bluetooth_thread or not self.bluetooth_thread.is_alive():
            self.bluetooth_thread = threading.Thread(target=self._bluetooth_loop, daemon=True)
            self.bluetooth_thread.start()
        return True

    def stop(self):
        self.cancel_pairing()
        self.stop_event.set()
        if self.server:
            try:
                self.server.close()
            except OSError:
                pass
            self.server = None
        for channel in list(self.connections.values()):
            try:
                channel.send({"type": "close", "reason": "shutdown"})
            except Exception:
                pass
            try:
                channel.sock.close()
            except OSError:
                pass
        self.connections.clear()
        self.connection_transports.clear()
        self._unpublish()

    def open_pairing(self):
        if not self.enabled:
            raise RuntimeError("Die Magnolie-Telefonverbindung ist ausgeschaltet.")
        self.start()
        self.pairing_token = os.urandom(16)
        self.pairing_until = time.monotonic() + PAIRING_SECONDS
        self._publish()
        token = b64(self.pairing_token)
        self.callback("pairing_open", {"token": token, "seconds": PAIRING_SECONDS,
                      "port": PORT, "display_name": self.store.identity["display_name"]})
        return token

    def cancel_pairing(self):
        self.pairing_token = None
        self.pairing_until = 0
        for context in list(self.pairings.values()):
            context["decision"] = False
            context["event"].set()
        self.pairings.clear()
        if self.enabled and self.server:
            self._publish()

    def confirm_pairing(self, attempt_id, accepted):
        context = self.pairings.get(attempt_id)
        if context:
            context["decision"] = bool(accepted)
            context["event"].set()

    def remove(self, peer_id):
        channel = self.connections.pop(peer_id, None)
        if channel:
            try:
                channel.send({"type": "close", "reason": "unpaired"})
            except Exception:
                pass
            try:
                channel.sock.close()
            except OSError:
                pass
        self.store.peers = [peer for peer in self.store.peers
                            if peer.get("device_id") != peer_id]
        self.store.save_peers()
        with sqlite3.connect(self.store.database_path) as db:
            for table in ("outbox", "inbox", "dedupe"):
                db.execute("DELETE FROM %s WHERE peer_id=?" % table, (peer_id,))
            db.execute("DELETE FROM meta WHERE key=?", ("device_status:" + peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("status_request:%s:%%" % peer_id,))
        self.callback("status", self.report())

    def set_bluetooth(self, peer_id, enabled, address=""):
        normalized = str(address or "").strip().upper()
        if enabled:
            available, reason = self.bluetooth_backend.availability()
            if not available:
                raise RuntimeError("Bluetooth-Daten sind nicht verfügbar (%s)." % reason)
            if not BLUETOOTH_ADDRESS.fullmatch(normalized):
                raise RuntimeError("Die Bluetooth-Adresse ist ungültig.")
            if not self.bluetooth_backend.paired(normalized):
                raise RuntimeError("Das Telefon muss zuerst in BlueZ systemgekoppelt sein.")
        self.store.set_bluetooth(peer_id, bool(enabled), normalized)
        if not enabled and self.connection_transports.get(peer_id) == "bluetooth":
            self._close_connection(peer_id, "normal")
        self.wifi_missing_since[peer_id] = time.monotonic()
        self.bluetooth_retry_at.pop(peer_id, None)
        self.callback("status", self.report())

    def request_status(self, peer_id):
        peer = self.store.peer(peer_id)
        if not peer or peer.get("state") != "paired":
            raise RuntimeError("Das Telefon ist nicht gekoppelt.")
        capability = (peer.get("capabilities") or {}).get("items", {}).get("device_status", {})
        versions = capability.get("versions", [])
        if (not capability.get("available") or 1 not in versions
                or not peer.get("grants", {}).get("grants", {}).get("device_status")):
            raise RuntimeError("Der Gerätestatus ist nicht freigegeben oder nicht verfügbar.")
        request_id = str(uuid.uuid4())
        body = {"request_id": request_id}
        if 2 in versions:
            body["version"] = 2
        message = self.store.queue(peer_id, "device_status.request", body, 60000)
        self.store.register_status_request(peer_id, request_id, message["expires_ms"])
        self.status_requests.setdefault(peer_id, {})[request_id] = time.monotonic() + 60
        channel = self.connections.get(peer_id)
        if channel:
            self._send_message(channel, peer_id, message)
        return request_id

    def set_grant(self, peer_id, name, enabled):
        if name not in {"sms_received", "selected_notifications_readonly"}:
            raise ValueError("invalid desktop grant")
        peer = self.store.peer(peer_id)
        if not peer or peer.get("state") != "paired":
            raise RuntimeError("Das Telefon ist nicht gekoppelt.")
        grants = peer.setdefault("local_grants", desktop_grants())
        if grants["grants"][name] == bool(enabled):
            return
        grants["revision"] = self.store.next_revision("grants.update")
        grants["grants"][name] = bool(enabled)
        self.store.save_peers()
        message = self.store.queue(peer_id, "grants.update", grants, DAY_MS)
        channel = self.connections.get(peer_id)
        if channel:
            self._send_message(channel, peer_id, message)
        self.callback("status", self.report())

    def send_sms(self, peer_id, destination, text, client_ref):
        peer = self.store.peer(peer_id)
        if not peer or peer.get("state") != "paired":
            raise RuntimeError("Das Telefon ist nicht gekoppelt.")
        capability = (peer.get("capabilities") or {}).get("items", {}).get("sms_send", {})
        if (not capability.get("available") or 1 not in capability.get("versions", [])
                or not peer.get("grants", {}).get("grants", {}).get("sms_send")):
            raise RuntimeError("SMS-Senden ist nicht freigegeben oder nicht verfügbar.")
        body = validate_sms_send({"to": destination, "text": text,
                                  "client_ref": client_ref})
        if self.store.sms_state(client_ref):
            raise RuntimeError("Diese SMS wurde bereits eingereiht.")
        self.store.remember_sms(client_ref, "queued")
        message = self.store.queue(peer_id, "sms_send.command", body, DAY_MS)
        channel = self.connections.get(peer_id)
        if channel:
            self._send_message(channel, peer_id, message)
        self.callback("sms_status", {"device_id": peer_id, "client_ref": client_ref,
                      "state": "queued", "error": "none", "occurred_ms": now_ms()})
        return client_ref

    def _send_message(self, channel, peer_id, message):
        channel.send(message)
        self.store.mark_attempt(peer_id, message["message_id"])

    def _ensure_desktop_updates(self, peer_id, revisions=None):
        revisions = revisions or {}
        available, reason = self.bluetooth_backend.availability()
        capabilities = lambda revision: desktop_capabilities(revision, available, reason)
        peer = self.store.peer(peer_id)
        grants = lambda revision: dict(peer["local_grants"], revision=revision)
        for kind, factory in (("capabilities.update", capabilities),
                              ("grants.update", grants)):
            revision = revisions[kind] if kind in revisions else self.store.next_revision(kind)
            body = factory(revision)
            self.store.queue(peer_id, kind, body, DAY_MS)

    def _accept(self):
        while not self.stop_event.is_set() and self.server:
            try:
                client, address = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            ip = address[0]
            with self.lock:
                if sum(self.active_by_ip.values()) >= 8 or self.active_by_ip.get(ip, 0) >= 2:
                    client.close()
                    continue
                self.active_by_ip[ip] = self.active_by_ip.get(ip, 0) + 1
            threading.Thread(target=self._handle, args=(client, ip, "wifi"), daemon=True).start()

    def _handle(self, sock, ip, transport="wifi"):
        sock.settimeout(10)
        try:
            first = receive_frame(sock, PAIR_FRAME_MAX)
            if first.get("p") != PROTOCOL:
                raise ValueError("wrong protocol")
            if first.get("type") == "pair_init":
                self._pair(sock, first)
            elif first.get("type") == "pair_finish":
                self._finish_pending(sock, first)
            elif first.get("type") == "session_start":
                expected_peer = ip.removeprefix("bluetooth:") if transport == "bluetooth" else None
                self._session(sock, first, transport, expected_peer)
            else:
                raise ValueError("unexpected first frame")
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
        finally:
            if transport != "wifi":
                return
            with self.lock:
                count = self.active_by_ip.get(ip, 1) - 1
                if count:
                    self.active_by_ip[ip] = count
                else:
                    self.active_by_ip.pop(ip, None)

    @staticmethod
    def _validate_pair_init(value):
        fields = {"p", "type", "pairing_token", "device_id", "role", "display_name",
                  "static_public", "ephemeral_public", "nonce", "versions"}
        if (set(value) != fields or value["p"] != PROTOCOL or value["type"] != "pair_init"
                or value["role"] != "phone" or not valid_uuid(value["device_id"])
                or not isinstance(value["display_name"], str)
                or not 1 <= len(value["display_name"]) <= 60
                or any(ord(char) < 32 for char in value["display_name"])
                or not isinstance(value["versions"], list) or 1 not in value["versions"]
                or len(value["versions"]) not in range(1, 17)
                or len(set(value["versions"])) != len(value["versions"])
                or any(isinstance(item, bool) or not isinstance(item, int)
                       or not 1 <= item <= 65535 for item in value["versions"])):
            raise ValueError("invalid pair_init")
        unb64(value["pairing_token"], 16)
        unb64(value["static_public"], 32)
        unb64(value["ephemeral_public"], 32)
        unb64(value["nonce"], 32)

    def _pair(self, sock, pair_init):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        self._validate_pair_init(pair_init)
        if (not self.pairing_token or time.monotonic() >= self.pairing_until
                or not hmac.compare_digest(unb64(pair_init["pairing_token"], 16),
                                           self.pairing_token)):
            raise ValueError("pairing window closed")
        known = self.store.peer(pair_init["device_id"])
        if known and known.get("static_public") != pair_init["static_public"]:
            raise ValueError("known device changed key")
        ephemeral = X25519PrivateKey.generate()
        pair_response = {"p": PROTOCOL, "type": "pair_response",
            "device_id": self.store.identity["device_id"], "role": "desktop",
            "display_name": self.store.identity["display_name"],
            "static_public": self.store.identity["static_public"],
            "ephemeral_public": b64(ephemeral.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw)), "nonce": b64(os.urandom(32)), "version": 1}
        send_frame(sock, pair_response)
        transcript, key, code = pairing_material(pair_init, pair_response,
                                                  ephemeral, self.store.private)
        attempt_id = str(uuid.uuid4())
        context = {"event": threading.Event(), "decision": None}
        self.pairings[attempt_id] = context
        self.callback("pairing_code", {"attempt_id": attempt_id, "code": code,
            "device_id": pair_init["device_id"], "display_name": pair_init["display_name"],
            "fingerprint": fingerprint(unb64(pair_init["static_public"], 32))})
        phone_confirm = receive_frame(sock, PAIR_FRAME_MAX)
        expected = {"p": PROTOCOL, "type": "pair_confirm", "side": "phone",
                    "transcript": b64(transcript), "proof": b64(proof(
                        key, b"magnolie-phone-pair-v1/confirm\0", "phone", transcript))}
        if phone_confirm != expected:
            raise ValueError("invalid phone confirmation")
        if not context["event"].wait(120) or context["decision"] is not True:
            send_frame(sock, {"p": PROTOCOL, "type": "pair_abort",
                              "reason": "user_cancelled"})
            return
        expires = now_ms() + PAIR_COMMIT_MS
        peer = known or {}
        peer.update({"device_id": pair_init["device_id"],
                     "display_name": pair_init["display_name"],
                     "static_public": pair_init["static_public"],
                     "state": "pair_commit_pending", "grants": desktop_grants(),
                     "local_grants": desktop_grants(),
                     "capabilities": {}, "last_contact_ms": 0,
                     "bluetooth": {"enabled": False, "address": ""},
                     "pending_transcript": b64(transcript),
                     "pending_phone_finish_proof": b64(proof(
                         key, b"magnolie-phone-pair-v1/finish\0", "phone", transcript)),
                     "pending_desktop_finish_proof": b64(proof(
                         key, b"magnolie-phone-pair-v1/finish\0", "desktop", transcript)),
                     "pending_expires_ms": expires})
        if not known:
            if len(self.store.peers) >= 8:
                raise ValueError("too many phones")
            self.store.peers.append(peer)
        self.store.save_peers()
        send_frame(sock, {"p": PROTOCOL, "type": "pair_confirm", "side": "desktop",
            "transcript": b64(transcript), "proof": b64(proof(
                key, b"magnolie-phone-pair-v1/confirm\0", "desktop", transcript))})
        phone_finish = receive_frame(sock, PAIR_FRAME_MAX)
        self._commit_pending(sock, peer, phone_finish)
        self.pairings.pop(attempt_id, None)
        self.pairing_token = None
        self.pairing_until = 0
        self._publish()
        self.callback("paired", {"device_id": peer["device_id"],
                                  "display_name": peer["display_name"]})
        self.callback("status", self.report())

    def _finish_pending(self, sock, finish):
        candidates = [peer for peer in self.store.peers
                      if peer.get("state") == "pair_commit_pending"
                      and peer.get("pending_expires_ms", 0) > now_ms()
                      and finish.get("transcript") == peer.get("pending_transcript")]
        if len(candidates) != 1:
            raise ValueError("unknown pending finish")
        self._commit_pending(sock, candidates[0], finish)

    def _commit_pending(self, sock, peer, finish):
        expected = {"p": PROTOCOL, "type": "pair_finish", "side": "phone",
                    "transcript": peer["pending_transcript"],
                    "proof": peer["pending_phone_finish_proof"]}
        if finish != expected or peer["pending_expires_ms"] <= now_ms():
            raise ValueError("invalid phone finish")
        response = {"p": PROTOCOL, "type": "pair_finish", "side": "desktop",
                    "transcript": peer["pending_transcript"],
                    "proof": peer["pending_desktop_finish_proof"]}
        for name in ("pending_transcript", "pending_phone_finish_proof",
                     "pending_desktop_finish_proof", "pending_expires_ms"):
            peer.pop(name, None)
        peer["state"] = "paired"
        peer["last_contact_ms"] = now_ms()
        self.store.save_peers()
        send_frame(sock, response)

    def _session(self, sock, start, transport="wifi", expected_peer=None):
        from cryptography.hazmat.primitives.asymmetric.x25519 import (X25519PrivateKey,
                                                                      X25519PublicKey)
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        fields = {"p", "type", "sid", "from", "to", "initiator_role",
                  "ephemeral_public", "nonce", "versions", "mac"}
        if (set(start) != fields or start["p"] != PROTOCOL
                or start["type"] != "session_start" or start["initiator_role"] != "phone"
                or start["to"] != self.store.identity["device_id"]
                or not valid_uuid(start["from"])
                or not isinstance(start["versions"], list)
                or len(start["versions"]) not in range(1, 17)
                or len(set(start["versions"])) != len(start["versions"])
                or any(isinstance(item, bool) or not isinstance(item, int)
                       or not 1 <= item <= 65535 for item in start["versions"])
                or 1 not in start["versions"]):
            raise ValueError("invalid session_start")
        sid = unb64(start["sid"], 16)
        unb64(start["nonce"], 32)
        peer_ephemeral = X25519PublicKey.from_public_bytes(
            unb64(start["ephemeral_public"], 32))
        peer = self.store.peer(start["from"])
        if not peer or peer.get("state") != "paired":
            raise ValueError("unknown phone")
        if expected_peer is not None and peer["device_id"] != expected_peer:
            raise ValueError("RFCOMM phone does not match configured peer")
        ids = sorted([peer["device_id"].encode(), self.store.identity["device_id"].encode()])
        ids = ids[0] + b"\0" + ids[1]
        shared = self.store.private.exchange(X25519PublicKey.from_public_bytes(
            unb64(peer["static_public"], 32)))
        if shared == b"\0" * 32:
            raise ValueError("invalid static key")
        static_root = hkdf(shared,
            hashlib.sha256(b"magnolie-phone-fs1/static-salt\0" + ids).digest(),
            b"magnolie-phone-fs1/static-root\0" + ids, 32)
        auth_key = hkdf(static_root, None, b"magnolie-phone-fs1/auth\0", 32)
        start_without_mac = dict(start)
        start_without_mac.pop("mac")
        expected_mac = hmac.new(auth_key, b"magnolie-phone-fs1/start\0" +
                                canonical(start_without_mac), hashlib.sha256).digest()
        if not hmac.compare_digest(unb64(start["mac"], 32), expected_mac):
            raise ValueError("invalid start MAC")
        ephemeral = X25519PrivateKey.generate()
        response_without_mac = {"p": PROTOCOL, "type": "session_response",
            "sid": start["sid"], "from": self.store.identity["device_id"],
            "to": peer["device_id"], "ephemeral_public": b64(
                ephemeral.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)),
            "nonce": b64(os.urandom(32)), "version": 1}
        response_mac = hmac.new(auth_key, b"magnolie-phone-fs1/response\0" +
            canonical(start) + canonical(response_without_mac), hashlib.sha256).digest()
        response = dict(response_without_mac, mac=b64(response_mac))
        send_frame(sock, response)
        transcript = hashlib.sha256(canonical(start) + canonical(response)).digest()
        exchanged = ephemeral.exchange(peer_ephemeral)
        if exchanged == b"\0" * 32:
            raise ValueError("invalid ephemeral key")
        salt = hmac.new(static_root, b"magnolie-phone-fs1/session-salt\0" + transcript,
                        hashlib.sha256).digest()
        material = hkdf(exchanged, salt,
                        b"magnolie-phone-fs1/session-keys\0" + transcript, 72)
        channel = SecureChannel(sock, sid, material[36:68], material[68:72],
                                material[0:32], material[32:36])
        capability_revision = self.store.next_revision("capabilities.update")
        grant_revision = self.store.next_revision("grants.update")
        ready = channel.receive()
        if (set(ready) != {"type", "connection_id", "capabilities_revision",
                           "last_received_seq"} or ready["type"] != "session_ready"
                or not valid_uuid(ready["connection_id"], 4)
                or isinstance(ready["capabilities_revision"], bool)
                or not isinstance(ready["capabilities_revision"], int)
                or ready["capabilities_revision"] < 1
                or ready["last_received_seq"] != -1):
            raise ValueError("invalid session_ready")
        channel.send({"type": "session_ready", "connection_id": str(uuid.uuid4()),
                      "capabilities_revision": capability_revision, "last_received_seq": -1})
        peer_id = peer["device_id"]
        self._activate_connection(peer_id, channel, transport)
        peer["last_contact_ms"] = int(time.time() * 1000)
        self.store.save_peers()
        self.callback("status", self.report())
        self._ensure_desktop_updates(peer["device_id"], {
            "capabilities.update": capability_revision, "grants.update": grant_revision})
        for message in self.store.pending(peer["device_id"]):
            self._send_message(channel, peer["device_id"], message)
        sock.settimeout(1)
        last_incoming = time.monotonic()
        try:
            while self.enabled:
                try:
                    payload = channel.receive()
                    last_incoming = time.monotonic()
                    if payload.get("type") == "close" and set(payload) == {"type", "reason"}:
                        if payload["reason"] not in {"normal", "shutdown", "better_transport",
                                                     "unpaired", "protocol_upgrade"}:
                            raise ValueError("invalid close reason")
                        break
                    self._payload(peer, channel, payload)
                except socket.timeout:
                    now = time.monotonic()
                    if now - last_incoming >= 75:
                        raise TimeoutError("phone heartbeat timeout")
                    if now - channel.last_send >= 25:
                        channel.send({"type": "ping", "ping_id": str(uuid.uuid4()),
                                      "sent_ms": now_ms()})
                    for message in self.store.pending(peer["device_id"]):
                        self._send_message(channel, peer["device_id"], message)
        finally:
            if self.connections.get(peer["device_id"]) is channel:
                self.connections.pop(peer["device_id"], None)
                self.connection_transports.pop(peer["device_id"], None)
            try:
                sock.close()
            except OSError:
                pass
            self.callback("status", self.report())

    def _activate_connection(self, peer_id, channel, transport):
        with self.lock:
            current = self.connections.get(peer_id)
            current_transport = self.connection_transports.get(peer_id)
            if transport == "bluetooth" and current_transport == "wifi":
                channel.send({"type": "close", "reason": "better_transport"})
                raise OSError("WLAN is already active")
            self.connections[peer_id] = channel
            self.connection_transports[peer_id] = transport
        if current and current is not channel:
            try:
                current.send({"type": "close", "reason": "better_transport"})
            except Exception:
                pass
            try:
                current.sock.close()
            except OSError:
                pass

    def _close_connection(self, peer_id, reason):
        channel = self.connections.get(peer_id)
        if not channel:
            return
        try:
            channel.send({"type": "close", "reason": reason})
        except Exception:
            pass
        try:
            channel.sock.close()
        except OSError:
            pass

    def _bluetooth_loop(self):
        while self.enabled and not self.stop_event.wait(1):
            self._bluetooth_tick()

    def _bluetooth_tick(self, now=None):
        now = time.monotonic() if now is None else now
        for peer in list(self.store.peers):
            peer_id = peer["device_id"]
            config = peer.get("bluetooth", {})
            transport = self.connection_transports.get(peer_id)
            if transport == "wifi":
                self.wifi_missing_since.pop(peer_id, None)
                continue
            if not config.get("enabled") or transport == "bluetooth":
                continue
            missing_since = self.wifi_missing_since.setdefault(peer_id, now)
            if (now - missing_since < BLUETOOTH_FALLBACK_SECONDS
                    or now < self.bluetooth_retry_at.get(peer_id, 0)):
                continue
            self.bluetooth_retry_at[peer_id] = now + BLUETOOTH_RETRY_SECONDS
            if not self.bluetooth_backend.paired(config["address"]):
                continue
            try:
                sock = self.bluetooth_backend.connect(config["address"], BLUETOOTH_UUID)
                sock.settimeout(10)
            except Exception:
                continue
            threading.Thread(target=self._handle,
                args=(sock, "bluetooth:" + peer_id, "bluetooth"), daemon=True).start()

    def _payload(self, peer, channel, payload):
        if payload.get("type") in ("ping", "pong") and set(payload) == {
                "type", "ping_id", "sent_ms"}:
            if (not valid_uuid(payload["ping_id"], 4)
                    or not valid_timestamp(payload["sent_ms"])):
                raise ValueError("invalid heartbeat")
            if payload["type"] == "pong":
                return
            channel.send({"type": "pong", "ping_id": payload["ping_id"],
                          "sent_ms": payload["sent_ms"]})
            return
        if payload.get("type") == "ack" and set(payload) == {
                "type", "message_id", "status", "error"}:
            if (not valid_uuid(payload["message_id"], 4)
                    or payload["status"] not in ("accepted", "duplicate", "rejected")
                    or payload["error"] not in ACK_ERRORS
                    or (payload["status"] != "rejected") != (payload["error"] == "none")):
                raise ValueError("invalid ack")
            self.store.acknowledge(peer["device_id"], payload["message_id"])
            return
        if payload.get("type") != "message":
            raise ValueError("unsupported secure payload")
        fields = {"type", "v", "message_id", "kind", "created_ms", "expires_ms", "body"}
        received = now_ms()
        if (set(payload) != fields or payload["v"] != 1 or not valid_uuid(
                payload["message_id"], 4) or not isinstance(payload["kind"], str)
                or not valid_timestamp(payload["created_ms"])
                or not valid_timestamp(payload["expires_ms"])
                or payload["expires_ms"] <= payload["created_ms"]
                or payload["expires_ms"] - payload["created_ms"] > 30 * DAY_MS
                or payload["created_ms"] > received + CLOCK_SKEW_MS):
            raise ValueError("invalid message")
        previous = self.store.dedupe_result(peer["device_id"], payload["message_id"])
        if previous:
            channel.send({"type": "ack", "message_id": payload["message_id"],
                          "status": "duplicate" if previous[0] == "accepted" else "rejected",
                          "error": "none" if previous[0] == "accepted" else previous[1]})
            return
        kind = payload["kind"]
        status, error = "accepted", "none"
        if payload["expires_ms"] + CLOCK_SKEW_MS < received:
            status, error = "rejected", "expired"
        elif ((kind == "device_status.report" and payload["expires_ms"] - payload["created_ms"] > 300000)
              or (kind == "sms_send.result" and payload["expires_ms"] - payload["created_ms"] > DAY_MS)
              or (kind == "sms_received.event" and payload["expires_ms"] - payload["created_ms"] > 30 * DAY_MS)
              or (kind == "selected_notifications_readonly.event" and
                  payload["expires_ms"] - payload["created_ms"] > DAY_MS)
              or (kind in {"capabilities.update", "grants.update"}
                  and payload["expires_ms"] - payload["created_ms"] > DAY_MS)):
            status, error = "rejected", "invalid_schema"
        elif kind == "device_status.report":
            try:
                if not peer.get("grants", {}).get("grants", {}).get("device_status"):
                    status, error = "rejected", "not_granted"
                    raise PermissionError
                report = validate_device_status(payload["body"])
                requests = self.status_requests.setdefault(peer["device_id"], {})
                now = time.monotonic()
                requests = {key: expiry for key, expiry in requests.items() if expiry > now}
                self.status_requests[peer["device_id"]] = requests
                spontaneous = bool((peer.get("capabilities") or {}).get("items", {}).get(
                    "device_status", {}).get("available"))
                persisted_request = self.store.consume_status_request(
                    peer["device_id"], report["request_id"])
                requested = report["request_id"] in requests or persisted_request
                if not requested and not spontaneous:
                    raise ValueError("unknown device status request")
                requests.pop(report["request_id"], None)
                self.store.cache_status(peer["device_id"], report)
                peer["last_contact_ms"] = int(time.time() * 1000)
                self.store.save_peers()
                self.callback("device_status", {"device_id": peer["device_id"],
                              "display_name": peer["display_name"], "status": report})
            except PermissionError:
                pass
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "capabilities.update":
            try:
                value = validate_capabilities(payload["body"])
                old = peer.get("capabilities") or {"revision": 0}
                if value["revision"] <= old["revision"]:
                    raise ValueError("stale capabilities revision")
                peer["capabilities"] = value
                self.store.save_peers()
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "grants.update":
            try:
                value = validate_grants(payload["body"])
                old = peer.get("grants") or {"revision": 0}
                if value["revision"] <= old["revision"]:
                    raise ValueError("stale grants revision")
                peer["grants"] = value
                self.store.save_peers()
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "sms_send.result":
            try:
                value = validate_sms_result(payload["body"])
                if not peer.get("grants", {}).get("grants", {}).get("sms_send"):
                    status, error = "rejected", "not_granted"
                    raise PermissionError
                if not self.store.update_sms(value["client_ref"], value["state"]):
                    raise ValueError("unknown SMS result")
                self.callback("sms_status", dict(value, device_id=peer["device_id"]))
            except PermissionError:
                pass
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "sms_received.event":
            try:
                local_grants = peer.setdefault("local_grants", desktop_grants())
                if not local_grants["grants"]["sms_received"]:
                    status, error = "rejected", "not_granted"
                    raise PermissionError
                value = validate_sms_received(payload["body"])
                self.callback("sms_received", dict(value, device_id=peer["device_id"],
                              display_name=peer["display_name"]))
            except PermissionError:
                pass
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "selected_notifications_readonly.event":
            try:
                local_grants = peer.setdefault("local_grants", desktop_grants())
                if not local_grants["grants"]["selected_notifications_readonly"]:
                    status, error = "rejected", "not_granted"
                    raise PermissionError
                value = validate_selected_notification(payload["body"])
                self.callback("selected_notification", dict(value,
                              device_id=peer["device_id"], display_name=peer["display_name"]))
            except PermissionError:
                pass
            except ValueError:
                status, error = "rejected", "invalid_schema"
        else:
            status, error = "rejected", "unsupported"
        self.store.remember_message(peer["device_id"], payload, status, error)
        channel.send({"type": "ack", "message_id": payload["message_id"],
                      "status": status, "error": error})

    def _publish(self):
        self._unpublish()
        if not self.enabled or not self.server:
            return
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
            properties = {"v": "1", "role": "desktop",
                          "id": self.store.identity["device_id"],
                          "name": self.store.identity["display_name"],
                          "pair": "1" if self.pairing_token else "0"}
            if self.pairing_token:
                properties["token"] = b64(self.pairing_token)
            route = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                route.connect(("192.0.2.1", 9))
                local_address = route.getsockname()[0]
            finally:
                route.close()
            if local_address.startswith("127."):
                raise OSError("Keine erreichbare lokale IPv4-Adresse")
            zc = Zeroconf(ip_version=IPVersion.All)
            service_host = self.store.identity["device_id"] + ".local."
            info = ServiceInfo(MDNS_TYPE, self.store.identity["device_id"] + "." + MDNS_TYPE,
                               addresses=[socket.inet_aton(local_address)], port=PORT,
                               properties=properties, server=service_host)
            zc.register_service(info)
            self.mdns = (zc, info)
        except Exception:
            self.mdns = None

    def _unpublish(self):
        if not self.mdns:
            return
        zc, info = self.mdns
        self.mdns = None
        try:
            zc.unregister_service(info)
        except Exception:
            pass
        try:
            zc.close()
        except Exception:
            pass


def validate_device_status(body):
    base_fields = {"request_id", "model", "manufacturer", "os_name", "os_version",
                   "battery_percent", "charging", "captured_ms"}
    extended_fields = {"sdk_int", "battery_temperature_deci_c", "power_source",
                       "storage_total_bytes", "storage_available_bytes",
                       "memory_total_bytes", "memory_available_bytes", "uptime_ms",
                       "network_transport", "network_validated", "network_metered"}
    if (not isinstance(body, dict) or set(body) not in (base_fields, base_fields | extended_fields)
            or not valid_uuid(body["request_id"])):
        raise ValueError("invalid device status")
    limits = {"model": (0, 80), "manufacturer": (0, 80), "os_name": (1, 20),
              "os_version": (0, 40)}
    for name, (minimum, maximum) in limits.items():
        value = body[name]
        if (not isinstance(value, str) or not minimum <= len(value) <= maximum
                or any(ord(char) < 32 for char in value)):
            raise ValueError("invalid device status")
    battery = body["battery_percent"]
    captured = body["captured_ms"]
    if (isinstance(battery, bool) or not isinstance(battery, int)
            or battery != -1 and not 0 <= battery <= 100
            or body["charging"] not in {"charging", "full", "discharging",
                                        "not_charging", "unknown"}
            or isinstance(captured, bool) or not isinstance(captured, int)
            or not 0 <= captured <= 253402300799999):
        raise ValueError("invalid device status")
    if set(body) == base_fields | extended_fields:
        integer_ranges = {
            "sdk_int": (1, 1000), "battery_temperature_deci_c": (-1, 2000),
            "storage_total_bytes": (-1, 1 << 60), "storage_available_bytes": (-1, 1 << 60),
            "memory_total_bytes": (-1, 1 << 60), "memory_available_bytes": (-1, 1 << 60),
            "uptime_ms": (-1, 253402300799999),
        }
        if any(isinstance(body[name], bool) or not isinstance(body[name], int)
               or not minimum <= body[name] <= maximum
               for name, (minimum, maximum) in integer_ranges.items()):
            raise ValueError("invalid device status")
        for available, total in (("storage_available_bytes", "storage_total_bytes"),
                                 ("memory_available_bytes", "memory_total_bytes")):
            if body[available] >= 0 and body[total] >= 0 and body[available] > body[total]:
                raise ValueError("invalid device status")
        if (body["power_source"] not in {"ac", "usb", "wireless", "dock", "none", "unknown"}
                or body["network_transport"] not in {"wifi", "cellular", "ethernet", "vpn", "bluetooth", "none"}
                or not isinstance(body["network_validated"], bool)
                or not isinstance(body["network_metered"], bool)):
            raise ValueError("invalid device status")
    return body


def _valid_phone(value, maximum=32, require_plus=True):
    if not valid_text(value, 1, maximum):
        return False
    normalized = re.sub(r"[\s()\-]", "", value)
    pattern = r"\+[0-9]{3,15}" if require_plus else r"\+?[0-9]{3,20}"
    return bool(re.fullmatch(pattern, normalized))


def validate_sms_send(body):
    if (not isinstance(body, dict) or set(body) != {"to", "text", "client_ref"}
            or not _valid_phone(body["to"]) or not valid_text(body["text"], 1, 5000, True)
            or not valid_uuid(body["client_ref"], 4)):
        raise ValueError("invalid SMS command")
    return body


def validate_sms_result(body):
    states = {"queued", "sent", "delivered", "failed"}
    errors = {"none", "permission_missing", "no_service", "invalid_destination",
              "os_restricted", "unknown"}
    if (not isinstance(body, dict) or set(body) != {"client_ref", "state", "error",
            "occurred_ms"} or not valid_uuid(body["client_ref"], 4)
            or body["state"] not in states or body["error"] not in errors
            or (body["state"] == "failed") != (body["error"] != "none")
            or not valid_timestamp(body["occurred_ms"])):
        raise ValueError("invalid SMS result")
    return body


def validate_sms_received(body):
    if (not isinstance(body, dict) or set(body) != {"sms_id", "from", "text",
            "received_ms", "subscription"} or not valid_uuid(body["sms_id"])
            or not valid_text(body["from"], 1, 128)
            or not valid_text(body["text"], 0, 10000, True)
            or not valid_timestamp(body["received_ms"])
            or isinstance(body["subscription"], bool)
            or not isinstance(body["subscription"], int)
            or body["subscription"] != -1 and not 0 <= body["subscription"] <= 16):
        raise ValueError("invalid received SMS")
    return body


def validate_selected_notification(body):
    fields = {"notification_id", "event", "package", "app_label", "title", "text",
              "posted_ms"}
    if (not isinstance(body, dict) or set(body) != fields
            or not valid_uuid(body["notification_id"]) or body["event"] not in {"posted", "removed"}
            or not valid_text(body["package"], 1, 255)
            or not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", body["package"])
            or not valid_text(body["app_label"], 0, 80)
            or not valid_text(body["title"], 0, 500, True)
            or not valid_text(body["text"], 0, 5000, True)
            or not valid_timestamp(body["posted_ms"])
            or body["event"] == "removed" and (body["title"] or body["text"])):
        raise ValueError("invalid selected notification")
    return body


def valid_timestamp(value):
    return (not isinstance(value, bool) and isinstance(value, int)
            and 0 <= value <= 253402300799999)


def valid_text(value, minimum, maximum, allow_lines=False):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        return False
    return not any(ord(char) < 32 and (not allow_lines or char not in "\n\t")
                   for char in value)


def _validate_revision(value):
    return (not isinstance(value, bool) and isinstance(value, int)
            and 1 <= value <= 9223372036854775807)


def validate_capabilities(body):
    if (not isinstance(body, dict) or set(body) != {"revision", "items"}
            or not _validate_revision(body["revision"])
            or not isinstance(body["items"], dict)
            or not CAPABILITY_NAMES <= set(body["items"])
            or len(body["items"]) > 64):
        raise ValueError("invalid capabilities")
    for name, item in body["items"].items():
        if (not valid_text(name, 1, 80) or not isinstance(item, dict)
                or set(item) != {"available", "reason", "versions"}
                or not isinstance(item["available"], bool)
                or item["reason"] not in CAPABILITY_REASONS
                or item["available"] != (item["reason"] == "available")
                or not isinstance(item["versions"], list)
                or len(item["versions"]) not in range(1, 17)
                or len(set(item["versions"])) != len(item["versions"])
                or any(isinstance(version, bool) or not isinstance(version, int)
                       or not 1 <= version <= 65535 for version in item["versions"])):
            raise ValueError("invalid capabilities")
    return body


def validate_grants(body):
    if (not isinstance(body, dict) or set(body) != {"revision", "grants"}
            or not _validate_revision(body["revision"])
            or not isinstance(body["grants"], dict)
            or set(body["grants"]) != GRANT_NAMES
            or any(not isinstance(value, bool) for value in body["grants"].values())):
        raise ValueError("invalid grants")
    return body
