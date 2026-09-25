#!/usr/bin/env python3
"""Unabhaengige Magnolie-Telefonverbindung (Protokollfassung 1)."""

import base64
import hashlib
import hmac
import io
import json
import os
import re
import socket
import sqlite3
import struct
import subprocess
import tempfile
import threading
from magnolie_personal_sync import CUSTOM_KINDS, validate_custom_body, accept_custom_settings, custom_scope_allowed
import time
import unicodedata
import uuid
from collections import deque

from magnolie_personal_sync import (CHUNK_RAW, MAX_ATTACHMENT, MAX_ATTACHMENTS, MIMES,
                                    decode_attachment_data_url, mime_from_magic, records_hash,
                                    validate_body as validate_personal_sync_body)
from magnolie_phone_region import enrich_call

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
CAPABILITY_NAMES = {"device_status", "selected_notifications_readonly", "dial_request",
                    "incoming_call_state", "incoming_call_number", "answer_call", "end_call",
                    "transport.bluetooth_rfcomm", "personal_notes_sync", "personal_tasks_sync",
                    "personal_deletions_sync"}
GRANT_NAMES = {"device_status", "selected_notifications_readonly", "dial_request",
               "incoming_call_state", "incoming_call_number", "answer_call", "end_call",
                "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync"}
LEGACY_CAPABILITY_NAMES = CAPABILITY_NAMES | {"sms_send", "sms_received", "call_control"}
LEGACY_GRANT_NAMES = GRANT_NAMES | {"sms_send", "sms_received", "call_control"}
CAPABILITY_REASONS = {"available", "not_implemented", "no_hardware", "disabled",
                      "permission_missing", "os_restricted"}
ACK_ERRORS = {"none", "expired", "invalid_schema", "unsupported", "not_granted",
              "too_large", "temporary_failure", "permanent_failure", "restore_unavailable", "conflict"}
RETRY_MS = (1000, 2000, 5000, 10000, 30000, 60000)
BLUETOOTH_FALLBACK_SECONDS = 15
BLUETOOTH_RETRY_SECONDS = 60
PERSONAL_COMMIT_SECONDS = 30
PERSONAL_ATTACHMENT_KINDS = {"personal_sync.attachment_request", "personal_sync.attachment_chunk",
                             "personal_sync.attachment_result"}
PERSONAL_DATA_KINDS = {"personal_sync.request", "personal_sync.batch", "personal_sync.report"} | PERSONAL_ATTACHMENT_KINDS
PERSONAL_DELETION_KINDS = {"personal_sync.deletion_proposals", "personal_sync.deletion_decision"}
PERSONAL_DATA_KINDS |= PERSONAL_DELETION_KINDS
BLUETOOTH_ADDRESS = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


def now_ms():
    return int(time.time() * 1000)


def desktop_capabilities(revision=1, bluetooth_available=False,
                         bluetooth_reason="not_implemented"):
    items = {}
    for name in sorted(CAPABILITY_NAMES):
        available = name in {"device_status", "dial_request", "incoming_call_state",
                             "incoming_call_number", "answer_call", "end_call",
                              "personal_notes_sync", "personal_tasks_sync"} or (
            name == "personal_deletions_sync" or
            name == "transport.bluetooth_rfcomm" and bluetooth_available)
        items[name] = {"available": available,
                       "reason": "available" if available else (
                           bluetooth_reason if name == "transport.bluetooth_rfcomm"
                           else "not_implemented"),
                         "versions": [1, 2, 3, 4] if name == "personal_tasks_sync" else
                                      [1, 2, 3, 4] if name == "device_status" else
                                      [1, 2, 3] if name == "personal_notes_sync" else
                                     [2] if name == "incoming_call_state" else [1]}
    return {"revision": revision, "items": items}


def desktop_grants(revision=1):
    return {"revision": revision,
            "grants": {name: name in {"device_status", "dial_request"}
                       for name in sorted(GRANT_NAMES)}}


def canonical(value):
    """Canonical JSON subset used by phone protocol version 1."""
    def check(item):
        if item is None or isinstance(item, (str, bool)):
            return
        if isinstance(item, int) and not isinstance(item, bool) and -(2**63) <= item < 2**63:
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


def personal_sync_grants_needed(kind, body):
    if kind in PERSONAL_DELETION_KINDS:
        return {"personal_deletions_sync"}
    if kind in {"personal_sync.attachment_request", "personal_sync.attachment_chunk",
                "personal_sync.attachment_result"}:
        return {"personal_notes_sync"}
    if kind == "personal_sync.batch":
        modules = {record.get("kind") for record in body.get("records", [])}
    elif kind == "personal_sync.request":
        modules = set(body.get("modules", []))
    else:
        counts = [body.get(name, {}) for name in ("sent", "received")]
        modules = set()
        if any(count.get("notes", 0) or count.get("notebooks", 0) for count in counts):
            modules.add("notes")
        if any(count.get("tasks", 0) for count in counts):
            modules.add("tasks")
    return {"personal_notes_sync" if item in {"note", "notebook", "notes"}
            else "personal_tasks_sync" for item in modules}


def negotiated_personal_notes_format(peer):
    versions = (((peer or {}).get("capabilities") or {}).get("items") or {}).get(
        "personal_notes_sync", {}).get("versions", [])
    return max((version for version in versions if version in (1, 2, 3)), default=1)


def supports_personal_format(peer, capability, format):
    versions = (((peer or {}).get("capabilities") or {}).get("items") or {}).get(
        capability, {}).get("versions", [])
    return format in versions


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
            aktueller_name = display_name[:60] or "Magnolie"
            if self.identity["display_name"] != aktueller_name:
                self.identity["display_name"] = aktueller_name
                _atomic(self.identity_path, json.dumps(self.identity, ensure_ascii=False,
                        indent=1).encode("utf-8"))
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
        migrated = False
        for peer in peers["items"]:
            grants = peer.get("grants", {})
            if isinstance(grants, dict) and "revision" not in grants:
                if not set(grants) <= LEGACY_GRANT_NAMES or "device_status" not in grants:
                    raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
                grants = {"revision": 1, "grants": grants}
                peer["grants"] = grants
                migrated = True
            migrated |= self._migrate_grants(grants, False)
            if "bluetooth" not in peer:
                peer["bluetooth"] = {"enabled": False, "address": ""}
                migrated = True
            if "local_grants" not in peer:
                peer["local_grants"] = desktop_grants()
                migrated = True
            else:
                migrated |= self._migrate_grants(peer["local_grants"], True)
            if "personal_sync" not in peer:
                peer["personal_sync"] = {"own_device": False, "remote_own_device": False,
                                         "auto_wifi": False,
                                         "last_report": {}}
                migrated = True
            capabilities = peer.get("capabilities", {})
            if capabilities:
                items = capabilities.get("items")
                if not isinstance(items, dict):
                    raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
                for name in LEGACY_CAPABILITY_NAMES - CAPABILITY_NAMES:
                    if items.pop(name, None) is not None:
                        migrated = True
                for name in CAPABILITY_NAMES - set(items):
                    items[name] = {"available": False, "reason": "not_implemented",
                                   "versions": [1]}
                    migrated = True
                if items["incoming_call_state"].get("versions") != [2]:
                    items["incoming_call_state"]["versions"] = [2]
                    migrated = True
            self._validate_peer(peer)
            if peer["state"] != "pair_commit_pending" or peer["pending_expires_ms"] > now:
                result.append(peer)
        if migrated or len(result) != len(peers["items"]):
            self.peers = result
            self.save_peers()
        return result

    @staticmethod
    def _migrate_grants(container, local):
        if (not isinstance(container, dict) or set(container) != {"revision", "grants"}
                or not isinstance(container["grants"], dict)
                or not set(container["grants"]) <= LEGACY_GRANT_NAMES):
            raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
        grants = container["grants"]
        changed = False
        for name in LEGACY_GRANT_NAMES - GRANT_NAMES:
            if name in grants:
                grants.pop(name)
                changed = True
        defaults = {"device_status": True, "selected_notifications_readonly": False,
                    "dial_request": local, "incoming_call_state": False,
                    "incoming_call_number": False, "answer_call": False,
                    "end_call": False, "personal_notes_sync": False,
                    "personal_tasks_sync": False, "personal_deletions_sync": False}
        for name, value in defaults.items():
            if name not in grants:
                grants[name] = value
                changed = True
        return changed

    @staticmethod
    def _validate_peer(peer):
        common = {"device_id", "display_name", "static_public", "state", "grants",
                  "local_grants", "capabilities", "last_contact_ms", "bluetooth",
                  "personal_sync"}
        if isinstance(peer, dict) and "call_audio" in peer:
            common.add("call_audio")
            if (not isinstance(peer["call_audio"], dict)
                    or set(peer["call_audio"]) not in ({"prefer_pc"}, {"prefer_pc", "address"})
                    or not isinstance(peer["call_audio"]["prefer_pc"], bool)
                    or "address" in peer["call_audio"] and (
                        not isinstance(peer["call_audio"]["address"], str)
                        or not BLUETOOTH_ADDRESS.fullmatch(peer["call_audio"]["address"]))):
                raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
        if isinstance(peer, dict) and "custom_sync" in peer:
            common.add("custom_sync")
            custom = peer["custom_sync"]
            if not isinstance(custom, dict) or not set(custom) <= {"local", "remote"}:
                raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
            for settings in custom.values():
                validate_custom_body("personal_sync.custom_settings", settings)
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
        personal = peer.get("personal_sync")
        if (not isinstance(personal, dict) or set(personal) != {
                "own_device", "remote_own_device", "auto_wifi", "last_report"}
                or not isinstance(personal["own_device"], bool)
                or not isinstance(personal["remote_own_device"], bool)
                or not isinstance(personal["auto_wifi"], bool)
                or not isinstance(personal["last_report"], dict)):
            raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.")
        unb64(peer["static_public"], 32)
        validate_grants(peer["grants"])
        validate_grants(peer["local_grants"])
        if peer["capabilities"]:
            try:
                validate_capabilities(peer["capabilities"])
            except ValueError as error:
                raise RuntimeError("Telefon-Gegenstellenliste ist beschaedigt.") from error
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

    def binding_conflict(self):
        return len(self.peers) > 1

    def sole_peer(self, device_id=None):
        if len(self.peers) != 1:
            return None
        peer = self.peers[0]
        return peer if device_id is None or peer.get("device_id") == device_id else None

    def _database(self):
        with sqlite3.connect(self.database_path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
              CREATE TABLE IF NOT EXISTS outbox(
                message_id TEXT PRIMARY KEY, peer_id TEXT NOT NULL, kind TEXT NOT NULL,
                created_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL, payload BLOB NOT NULL,
                attempts INTEGER NOT NULL, next_attempt_ms INTEGER NOT NULL, last_error TEXT NOT NULL,
                transport_policy TEXT NOT NULL DEFAULT 'any');
              CREATE TABLE IF NOT EXISTS inbox(
                message_id TEXT NOT NULL, peer_id TEXT NOT NULL, kind TEXT NOT NULL,
                received_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL, payload BLOB NOT NULL,
                state TEXT NOT NULL, PRIMARY KEY(peer_id,message_id));
              CREATE TABLE IF NOT EXISTS dedupe(
                message_id TEXT NOT NULL, peer_id TEXT NOT NULL, result TEXT NOT NULL,
                error TEXT NOT NULL, seen_ms INTEGER NOT NULL, PRIMARY KEY(peer_id,message_id));
              CREATE TABLE IF NOT EXISTS command_effect(client_ref TEXT PRIMARY KEY,
                state TEXT NOT NULL, first_seen_ms INTEGER NOT NULL, peer_id TEXT NOT NULL DEFAULT '');
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
              CREATE TABLE IF NOT EXISTS personal_batch(
                peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,
                sequence INTEGER NOT NULL,batch_id TEXT NOT NULL UNIQUE,message_id TEXT NOT NULL UNIQUE,
                received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,last INTEGER NOT NULL,
                commit_token TEXT NOT NULL,
                PRIMARY KEY(peer_id,run_id,reply,sequence));
              CREATE TABLE IF NOT EXISTS personal_domain(
                peer_id TEXT NOT NULL,message_id TEXT NOT NULL,kind TEXT NOT NULL,
                received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,
                commit_token TEXT NOT NULL,PRIMARY KEY(peer_id,message_id));
               CREATE TABLE IF NOT EXISTS personal_attachment_transfer(
                peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,
                records_hash TEXT NOT NULL,sha256 TEXT NOT NULL,direction TEXT NOT NULL,
                size INTEGER NOT NULL,mime TEXT NOT NULL,transport_policy TEXT NOT NULL,
                 expires_ms INTEGER NOT NULL,complete INTEGER NOT NULL DEFAULT 0,metadata BLOB,
                PRIMARY KEY(peer_id,run_id,reply,records_hash,sha256,direction));
              CREATE TABLE IF NOT EXISTS personal_attachment_chunk(
                peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,
                records_hash TEXT NOT NULL,sha256 TEXT NOT NULL,direction TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,payload BLOB NOT NULL,
                PRIMARY KEY(peer_id,run_id,reply,records_hash,sha256,direction,chunk_index));
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(outbox)")}
            if "transport_policy" not in columns:
                db.execute("ALTER TABLE outbox ADD COLUMN transport_policy TEXT NOT NULL DEFAULT 'any'")
            personal_columns = {row[1] for row in db.execute("PRAGMA table_info(personal_batch)")}
            if "commit_token" not in personal_columns:
                db.execute("ALTER TABLE personal_batch ADD COLUMN commit_token TEXT NOT NULL DEFAULT ''")
            attachment_columns = {row[1] for row in db.execute("PRAGMA table_info(personal_attachment_transfer)")}
            if "metadata" not in attachment_columns:
                db.execute("ALTER TABLE personal_attachment_transfer ADD COLUMN metadata BLOB")
            command_columns = {row[1] for row in db.execute("PRAGMA table_info(command_effect)")}
            if "peer_id" not in command_columns:
                db.execute("ALTER TABLE command_effect ADD COLUMN peer_id TEXT NOT NULL DEFAULT ''")
        os.chmod(self.database_path, 0o600)
        with sqlite3.connect(self.database_path) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sms_effect'").fetchone():
                db.execute("INSERT OR IGNORE INTO command_effect(client_ref,state,first_seen_ms) "
                           "SELECT client_ref,state,first_seen_ms FROM sms_effect")
                db.execute("DROP TABLE sms_effect")
        for suffix in ("-wal", "-shm"):
            if os.path.exists(self.database_path + suffix):
                os.chmod(self.database_path + suffix, 0o600)

    def cache_status(self, peer_id, status):
        status = without_device_identifiers(status)
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

    def queue(self, peer_id, kind, body, ttl_ms, transport_policy="any"):
        if kind.startswith("device_status.") and ("identifiers" in body or body.get("version") == 4):
            raise ValueError("device identifiers cannot enter a persistent queue")
        now = now_ms()
        if not isinstance(ttl_ms, int) or not 0 < ttl_ms <= 30 * DAY_MS:
            raise ValueError("invalid message lifetime")
        if transport_policy not in {"any", "wifi_only"}:
            raise ValueError("invalid transport policy")
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
                   "kind": kind, "created_ms": now, "expires_ms": now + ttl_ms,
                   "body": body}
        encrypted = self._encrypt(canonical(message), "outbox", message["message_id"])
        with sqlite3.connect(self.database_path) as db:
            size = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM outbox").fetchone()[0]
            if size + len(encrypted) > 50 * 1024 * 1024:
                raise RuntimeError("queue_full")
            db.execute("INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (message["message_id"], peer_id, kind, now, now + ttl_ms,
                         encrypted, 0, now, "", transport_policy))
        return message

    def queue_format2_run(self, peer_id, messages, attachments, transport_policy):
        """Atomically encrypt-stage every source before record messages enter outbox."""
        if transport_policy not in {"any", "wifi_only"} or not messages:
            raise ValueError("invalid format 2 run")
        now = now_ms()
        prepared = []
        for kind, body, ttl_ms in messages:
            message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
                       "kind": kind, "created_ms": now, "expires_ms": now + ttl_ms, "body": body}
            prepared.append((message, self._encrypt(canonical(message), "outbox", message["message_id"])))
        run_id = messages[0][1]["run_id"]
        reply = bool(messages[-1][1].get("reply", False))
        aggregate_hash = messages[-1][1]["records_hash"]
        staged = []
        for descriptor, raw in attachments:
            if (len(raw) != descriptor["size"] or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]
                    or mime_from_magic(raw) != descriptor["mime"]):
                raise ValueError("attachment source changed after snapshot")
            for index, offset in enumerate(range(0, len(raw), CHUNK_RAW)):
                primary = self._attachment_primary(peer_id, run_id, reply, aggregate_hash, descriptor["sha256"], index, "outgoing")
                staged.append((descriptor, index, self._encrypt(raw[offset:offset + CHUNK_RAW],
                    "personal_attachment_chunk", primary)))
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            outbox_used = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM outbox").fetchone()[0]
            used = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk").fetchone()[0]
            run_used = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk WHERE peer_id=? AND run_id=?", (peer_id, run_id)).fetchone()[0]
            rows = db.execute("SELECT COUNT(*) FROM personal_attachment_chunk").fetchone()[0]
            active = db.execute("SELECT COUNT(DISTINCT run_id||':'||reply||':'||direction) FROM personal_attachment_transfer WHERE peer_id=?", (peer_id,)).fetchone()[0]
            hashes = db.execute("SELECT COUNT(DISTINCT sha256) FROM personal_attachment_transfer WHERE peer_id=? AND run_id=?", (peer_id, run_id)).fetchone()[0]
            added = sum(len(item[2]) for item in staged)
            unique = {item[0]["sha256"] for item in staged}
            if (outbox_used + sum(len(item[1]) for item in prepared) > 50 * 1024 * 1024
                    or staged and active >= 4 or hashes + len(unique) > 256
                    or rows + len(staged) > 4096 or used + added > 100 * 1024 * 1024
                    or run_used + added > 50 * 1024 * 1024):
                raise RuntimeError("attachment staging capacity")
            for descriptor in {item["sha256"]: item for item, _raw in attachments}.values():
                metadata = self._attachment_metadata(peer_id, run_id, reply, aggregate_hash, descriptor["sha256"],
                    "outgoing", descriptor["size"], descriptor["mime"], transport_policy, now + DAY_MS, False,
                    descriptor["attachment_id"])
                db.execute("INSERT INTO personal_attachment_transfer VALUES(?,?,?,?,?,?,?,?,?,?,0,?)",
                    (peer_id, run_id, int(reply), aggregate_hash, descriptor["sha256"], "outgoing",
                     descriptor["size"], descriptor["mime"], transport_policy, now + DAY_MS,
                     self._encrypt_attachment_metadata(metadata)))
            for descriptor, index, encrypted in staged:
                db.execute("INSERT INTO personal_attachment_chunk VALUES(?,?,?,?,?,?,?,?)",
                    (peer_id, run_id, int(reply), aggregate_hash, descriptor["sha256"], "outgoing", index, encrypted))
            for message, encrypted in prepared:
                db.execute("INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (message["message_id"], peer_id, message["kind"], now, message["expires_ms"],
                     encrypted, 0, now, "", transport_policy))
        return [item[0] for item in prepared]

    def pending(self, peer_id, transport="wifi"):
        if transport not in {"wifi", "bluetooth"}:
            raise ValueError("invalid current transport")
        now = now_ms()
        with sqlite3.connect(self.database_path) as db:
            rows = db.execute("SELECT message_id,payload FROM outbox WHERE peer_id=? AND "
                              "expires_ms>? AND next_attempt_ms<=? AND (transport_policy='any' OR ?='wifi') "
                              "ORDER BY CASE WHEN kind='personal_sync.custom_settings' THEN 0 ELSE 1 END,created_ms LIMIT 32", (peer_id, now, now, transport)).fetchall()
        return [strict_json(self._decrypt(payload, "outbox", message_id))
                for message_id, payload in rows]

    def mark_attempt(self, peer_id, message_id):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT attempts,kind,expires_ms FROM outbox WHERE peer_id=? AND message_id=?",
                             (peer_id, message_id)).fetchone()
            if not row:
                return
            attempts = row[0] + 1
            if row[1] in {"dial_request.command", "answer_call.command", "end_call.command"}:
                db.execute("UPDATE outbox SET attempts=?,next_attempt_ms=?,last_error=? "
                           "WHERE peer_id=? AND message_id=?",
                           (attempts, row[2], "missing_ack", peer_id, message_id))
                return
            base = RETRY_MS[attempts - 1] if attempts <= len(RETRY_MS) else 300000
            jitter = 1.0 if attempts <= len(RETRY_MS) else 0.8 + int.from_bytes(
                os.urandom(2), "big") / 65535 * 0.4
            db.execute("UPDATE outbox SET attempts=?,next_attempt_ms=?,last_error=? "
                       "WHERE peer_id=? AND message_id=?",
                       (attempts, now_ms() + int(base * jitter), "missing_ack",
                        peer_id, message_id))

    def acknowledge(self, peer_id, message_id, custom_accepted=None):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT kind,payload FROM outbox WHERE peer_id=? AND message_id=?",
                              (peer_id, message_id)).fetchone()
            if row and row[0] == "personal_sync.custom_batch" and custom_accepted is not None:
                body = strict_json(self._decrypt(row[1], "outbox", message_id))["body"]
                if body["deletions"]:
                    custom_accepted({key: body[key] for key in ("source_id", "revision", "deletions")})
            db.execute("DELETE FROM outbox WHERE peer_id=? AND message_id=?",
                        (peer_id, message_id))
        if row and row[0] == "personal_sync.deletion_decision":
            return strict_json(self._decrypt(row[1], "outbox", message_id))["body"]["decision_id"]
        return ""

    def outbox_policy(self, peer_id, message_id):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT transport_policy,kind,payload,expires_ms FROM outbox WHERE peer_id=? AND message_id=?",
                              (peer_id, message_id)).fetchone()
        if not row or row[0] not in {"any", "wifi_only"}:
            return None
        if row[3] <= now_ms():
            return "expired"
        if row[1] not in PERSONAL_DATA_KINDS:
            return row[0]
        message = strict_json(self._decrypt(row[2], "outbox", message_id))
        body = message.get("body", {})
        try:
            durable = self.run_policy(peer_id, body.get("run_id", ""))
        except ValueError:
            return "invalid"
        if durable == "expired":
            return "expired"
        trigger_bound = row[1] in {"personal_sync.request", "personal_sync.report"}
        expected = durable or ("wifi_only" if trigger_bound and body.get("trigger") == "auto_wifi"
                               else "any" if trigger_bound and body.get("trigger") == "manual" else None)
        return row[0] if expected == row[0] else "invalid"

    def run_policy(self, peer_id, run_id):
        stored = self._personal_run_record(peer_id, run_id)
        if not stored:
            return None
        if stored["expires_ms"] <= now_ms():
            return "expired"
        run = stored["body"]
        if run.get("trigger") == "auto_wifi":
            return "wifi_only"
        if run.get("trigger") == "manual":
            return "any"
        return None

    def remove_kind(self, peer_id, kind):
        with sqlite3.connect(self.database_path) as db:
            db.execute("DELETE FROM outbox WHERE peer_id=? AND kind=?", (peer_id, kind))

    def has_kind(self, peer_id, kind):
        with sqlite3.connect(self.database_path) as db:
            return db.execute("SELECT 1 FROM outbox WHERE peer_id=? AND kind=? AND expires_ms>? LIMIT 1",
                              (peer_id, kind, now_ms())).fetchone() is not None

    def queue_deletion_decision(self, peer_id, body, ttl_ms, transport_policy):
        with sqlite3.connect(self.database_path) as db:
            rows = db.execute("SELECT message_id,payload FROM outbox WHERE peer_id=? AND kind=?",
                              (peer_id, "personal_sync.deletion_decision")).fetchall()
        for message_id, encrypted in rows:
            message = strict_json(self._decrypt(encrypted, "outbox", message_id))
            if message["body"]["decision_id"] == body["decision_id"]:
                return message
        return self.queue(peer_id, "personal_sync.deletion_decision", body, ttl_ms, transport_policy)

    def purge_personal(self, peer_id):
        kinds = ("personal_sync.request", "personal_sync.batch", "personal_sync.report",
                  "personal_sync.attachment_request", "personal_sync.attachment_chunk",
                  "personal_sync.attachment_result", "personal_sync.deletion_proposals",
                  "personal_sync.deletion_decision")
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM dedupe WHERE peer_id=? AND message_id IN (SELECT message_id FROM inbox "
                        "WHERE peer_id=? AND kind IN (%s))" % ",".join("?" for _ in kinds), (peer_id, peer_id, *kinds))
            for table in ("outbox", "inbox"):
                db.execute("DELETE FROM %s WHERE peer_id=? AND kind IN (%s)" % (table, ",".join("?" for _ in kinds)),
                           (peer_id, *kinds))
            db.execute("DELETE FROM personal_batch WHERE peer_id=?", (peer_id,))
            db.execute("DELETE FROM personal_domain WHERE peer_id=?", (peer_id,))
            db.execute("DELETE FROM personal_attachment_chunk WHERE peer_id=?", (peer_id,))
            db.execute("DELETE FROM personal_attachment_transfer WHERE peer_id=?", (peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_run:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_applied:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_report:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_local_index:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key=?", ("personal_active_auto:" + peer_id,))

    def purge_personal_modules(self, peer_id, revoked):
        revoked = set(revoked)
        with sqlite3.connect(self.database_path) as db:
            run_rows = db.execute("SELECT key,value FROM meta WHERE key LIKE ?",
                                  ("personal_run:%s:%%" % peer_id,)).fetchall()
        runs = set()
        for key, encrypted in run_rows:
            stored = strict_json(self._decrypt(encrypted, "personal_run", key))
            body = stored.get("body", stored)
            if revoked.intersection(body.get("modules", [])):
                runs.add(body["run_id"])
        if not runs:
            return
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            for run_id in runs:
                for table in ("personal_batch", "personal_attachment_chunk", "personal_attachment_transfer"):
                    db.execute("DELETE FROM %s WHERE peer_id=? AND run_id=?" % table, (peer_id, run_id))
                for prefix in ("personal_run", "personal_report", "personal_local_index", "personal_applied"):
                    db.execute("DELETE FROM meta WHERE key LIKE ?", ("%s:%s:%s%%" % (prefix, peer_id, run_id),))
            for table in ("outbox", "inbox", "personal_domain"):
                rows = db.execute("SELECT message_id,payload FROM %s WHERE peer_id=?" % table,
                                  (peer_id,)).fetchall()
                for message_id, encrypted in rows:
                    try:
                        message = strict_json(self._decrypt(encrypted, table, message_id))
                    except Exception:
                        message = {}
                    if message.get("kind", "").startswith("personal_sync.") and message.get("body", {}).get("run_id") in runs:
                        db.execute("DELETE FROM %s WHERE peer_id=? AND message_id=?" % table,
                                   (peer_id, message_id))
                        if table == "inbox":
                            db.execute("DELETE FROM dedupe WHERE peer_id=? AND message_id=?", (peer_id, message_id))

    def purge_personal_deletion_wire(self, peer_id):
        kinds = tuple(sorted(PERSONAL_DELETION_KINDS))
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM dedupe WHERE peer_id=? AND message_id IN (SELECT message_id FROM inbox WHERE peer_id=? AND kind IN (?,?))",
                       (peer_id, peer_id, *kinds))
            db.execute("DELETE FROM outbox WHERE peer_id=? AND kind IN (?,?)", (peer_id, *kinds))
            db.execute("DELETE FROM inbox WHERE peer_id=? AND kind IN (?,?)", (peer_id, *kinds))
            db.execute("DELETE FROM personal_domain WHERE peer_id=?", (peer_id,))

    def stage_personal_batch(self, peer_id, message):
        body = message["body"]
        primary = "%s:%s:%d:%d" % (peer_id, body["run_id"], body["reply"], body["sequence"])
        encrypted = self._encrypt(canonical(message), "personal_batch", primary)
        now = now_ms()
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM meta WHERE key=?", (
                    "personal_applied:%s:%s:%d" % (peer_id, body["run_id"], body["reply"]),)).fetchone():
                raise ValueError("personal batch already committed")
            if not 0 <= body["sequence"] < 4096:
                raise ValueError("invalid personal batch sequence")
            old = db.execute("SELECT batch_id,message_id,payload,last FROM personal_batch WHERE peer_id=? AND run_id=? AND reply=? AND sequence=?",
                (peer_id, body["run_id"], int(body["reply"]), body["sequence"])).fetchone()
            if old:
                old_message = strict_json(self._decrypt(old[2], "personal_batch", primary))
                if (old[0], old[1], old[3], old_message) != (
                        body["batch_id"], message["message_id"], int(body["last"]), message):
                    raise ValueError("conflicting personal batch sequence")
            token_row = db.execute("SELECT commit_token FROM personal_batch WHERE peer_id=? AND run_id=? "
                "AND reply=? AND commit_token<>'' LIMIT 1",
                (peer_id, body["run_id"], int(body["reply"]))).fetchone()
            token = token_row[0] if token_row else b64(os.urandom(32))
            db.execute("UPDATE personal_batch SET commit_token=? WHERE peer_id=? AND run_id=? AND reply=? "
                       "AND commit_token=''", (token, peer_id, body["run_id"], int(body["reply"])))
            db.execute("INSERT OR IGNORE INTO personal_batch VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (peer_id, body["run_id"], int(body["reply"]), body["sequence"], body["batch_id"],
                 message["message_id"], now, message["expires_ms"], encrypted, int(body["last"]), token))
            inbox = self._encrypt(canonical(message), "inbox", message["message_id"])
            db.execute("INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,?,?,?)", (message["message_id"], peer_id,
                message["kind"], now, message["expires_ms"], inbox, "staged"))
            db.execute("INSERT OR IGNORE INTO dedupe VALUES(?,?,?,?,?)",
                (message["message_id"], peer_id, "accepted", "none", now))
            rows = db.execute("SELECT sequence,batch_id,message_id,payload,last FROM personal_batch "
                "WHERE peer_id=? AND run_id=? AND reply=? ORDER BY sequence",
                (peer_id, body["run_id"], int(body["reply"]))).fetchall()
            if len(rows) > 4096 or sum(len(row[3]) for row in rows) > 50 * 1024 * 1024:
                raise ValueError("personal run too large")
            final_sequences = [row[0] for row in rows if row[4]]
            if (len(final_sequences) > 1 or final_sequences and
                    any(row[0] > final_sequences[0] for row in rows)):
                raise ValueError("conflicting personal batch final sequence")
            record_count = 0
            for staged_sequence, _batch, _message, staged_payload, _last in rows:
                staged_primary = "%s:%s:%d:%d" % (peer_id, body["run_id"], body["reply"], staged_sequence)
                staged = strict_json(self._decrypt(staged_payload, "personal_batch", staged_primary))
                record_count += len(staged["body"]["records"])
            if record_count > 100000:
                raise ValueError("personal run too large")
        if len(rows) > 4096:
            raise ValueError("too many personal batches")
        last = [row[0] for row in rows if row[4]]
        if len(last) != 1 or [row[0] for row in rows] != list(range(last[0] + 1)):
            return None
        messages, records = [], []
        total = 0
        for sequence, _batch_id, _message_id, payload, _last in rows:
            item_primary = "%s:%s:%d:%d" % (peer_id, body["run_id"], body["reply"], sequence)
            item = strict_json(self._decrypt(payload, "personal_batch", item_primary))
            if item["body"].get("format", 1) != body.get("format", 1):
                raise ValueError("conflicting personal sync format")
            messages.append(item)
            records.extend(item["body"]["records"])
            total += len(payload)
        if body.get("format", 1) >= 2:
            advertised = {item["body"]["records_hash"] for item in messages}
            if len(advertised) != 1 or records_hash(records) != body["records_hash"]:
                raise ValueError("invalid aggregate records hash")
        if len(records) > 100000 or total > 50 * 1024 * 1024:
            raise ValueError("personal run too large")
        return {"format": body.get("format", 1), "commit_token": token,
                "run_id": body["run_id"], "reply": body["reply"],
                "message_id": messages[-1]["message_id"], "records": records, "messages": messages}

    def stage_personal_domain(self, peer_id, message):
        """Durably stage a deletion domain mutation until the document save commits it."""
        if message.get("kind") not in PERSONAL_DELETION_KINDS:
            raise ValueError("invalid personal domain kind")
        message_id = message["message_id"]
        encrypted = self._encrypt(canonical(message), "personal_domain", message_id)
        token = b64(os.urandom(32))
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload,commit_token FROM personal_domain WHERE peer_id=? AND message_id=?",
                             (peer_id, message_id)).fetchone()
            if old:
                if strict_json(self._decrypt(old[0], "personal_domain", message_id)) != message:
                    raise ValueError("conflicting personal domain message")
                token = old[1]
            else:
                db.execute("INSERT INTO personal_domain VALUES(?,?,?,?,?,?,?)", (peer_id, message_id,
                    message["kind"], now_ms(), message["expires_ms"], encrypted, token))
                inbox = self._encrypt(canonical(message), "inbox", message_id)
                db.execute("INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,?,?,?)", (message_id, peer_id,
                    message["kind"], now_ms(), message["expires_ms"], inbox, "staged"))
        return {"device_id": peer_id, "kind": message["kind"], "body": message["body"],
                "pending_message_id": message_id, "commit_token": token}

    def commit_personal_domain(self, peer_id, message_id, token):
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT 1 FROM personal_domain WHERE peer_id=? AND message_id=? AND commit_token=?",
                             (peer_id, message_id, token)).fetchone()
            if not row:
                return False
            seen = now_ms()
            db.execute("UPDATE inbox SET state='accepted' WHERE peer_id=? AND message_id=?", (peer_id, message_id))
            db.execute("INSERT OR REPLACE INTO dedupe VALUES(?,?,?,?,?)",
                       (message_id, peer_id, "accepted", "none", seen))
            db.execute("DELETE FROM personal_domain WHERE peer_id=? AND message_id=? AND commit_token=?",
                       (peer_id, message_id, token))
        return True

    def ready_personal_domains(self):
        with sqlite3.connect(self.database_path) as db:
            rows = db.execute("SELECT peer_id,message_id,payload,commit_token FROM personal_domain ORDER BY received_ms").fetchall()
        return [(peer_id, {"device_id": peer_id, "kind": message["kind"], "body": message["body"],
                "pending_message_id": message_id, "commit_token": token})
                for peer_id, message_id, payload, token in rows
                for message in [strict_json(self._decrypt(payload, "personal_domain", message_id))]]

    @staticmethod
    def _attachment_primary(peer_id, run_id, reply, aggregate_hash, digest, index, direction):
        return "%s:%s:%d:%s:%s:%s:%d" % (peer_id, run_id, int(reply), direction, aggregate_hash, digest, index)

    @staticmethod
    def _attachment_transfer_primary(peer_id, run_id, reply, aggregate_hash, digest, direction):
        return "%s:%s:%d:%s:%s:%s" % (peer_id, run_id, int(reply), direction, aggregate_hash, digest)

    def _attachment_metadata(self, peer_id, run_id, reply, aggregate_hash, digest, direction,
                             size, mime, policy, expires_ms, complete, attachment_id):
        return {"peer_id": peer_id, "run_id": run_id, "reply": bool(reply),
                "attachment_id": attachment_id, "records_hash": aggregate_hash,
                "sha256": digest, "direction": direction, "total_chunks": (size + CHUNK_RAW - 1) // CHUNK_RAW,
                "size": size, "mime": mime, "expires_ms": expires_ms,
                "complete": bool(complete), "transport_policy": policy}

    def _encrypt_attachment_metadata(self, metadata):
        primary = self._attachment_transfer_primary(metadata["peer_id"], metadata["run_id"], metadata["reply"],
            metadata["records_hash"], metadata["sha256"], metadata["direction"])
        return self._encrypt(canonical(metadata), "personal_attachment_transfer", primary)

    def _decode_attachment_row(self, row):
        if not row or row[-1] is None:
            raise ValueError("unauthenticated attachment metadata")
        columns = ("peer_id", "run_id", "reply", "records_hash", "sha256", "direction", "size", "mime",
                   "transport_policy", "expires_ms", "complete")
        visible = dict(zip(columns, row[:-1]))
        primary = self._attachment_transfer_primary(visible["peer_id"], visible["run_id"], visible["reply"],
            visible["records_hash"], visible["sha256"], visible["direction"])
        metadata = strict_json(self._decrypt(row[-1], "personal_attachment_transfer", primary))
        expected = self._attachment_metadata(visible["peer_id"], visible["run_id"], bool(visible["reply"]),
            visible["records_hash"], visible["sha256"], visible["direction"], visible["size"], visible["mime"],
            visible["transport_policy"], visible["expires_ms"], bool(visible["complete"]), metadata.get("attachment_id"))
        if metadata != expected or not isinstance(metadata["attachment_id"], str) or not metadata["attachment_id"].strip():
            raise ValueError("tampered attachment metadata")
        return metadata

    def _load_attachment_metadata(self, db, peer_id, run_id, reply, aggregate_hash, digest, direction):
        row = db.execute("SELECT peer_id,run_id,reply,records_hash,sha256,direction,size,mime,transport_policy,expires_ms,complete,metadata FROM personal_attachment_transfer WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction=?",
            (peer_id, run_id, int(reply), aggregate_hash, digest, direction)).fetchone()
        return self._decode_attachment_row(row) if row else None

    def stage_outgoing_attachment(self, peer_id, run_id, reply, aggregate_hash, digest,
                                  mime, raw, transport_policy, expires_ms, attachment_id=None):
        """Snapshot source bytes durably before a descriptor may be advertised."""
        if (transport_policy not in {"any", "wifi_only"} or len(raw) > MAX_ATTACHMENT
                or not raw or hashlib.sha256(raw).hexdigest() != digest or mime_from_magic(raw) != mime):
            raise ValueError("invalid outgoing attachment")
        chunks = ((index, raw[offset:offset + CHUNK_RAW]) for index, offset in
                  enumerate(range(0, len(raw), CHUNK_RAW)))
        self._stage_attachment_chunks(peer_id, run_id, reply, aggregate_hash, digest, "outgoing",
                                      len(raw), mime, chunks, transport_policy, expires_ms, attachment_id or digest)

    def stage_incoming_attachment(self, peer_id, run_id, reply, aggregate_hash, digest,
                                  size, mime, index, raw, transport_policy, expires_ms, attachment_id=None):
        if (isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_ATTACHMENT
                or mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
                or not re.fullmatch(r"[0-9a-f]{64}", digest) or not re.fullmatch(r"[0-9a-f]{64}", aggregate_hash)
                or transport_policy not in {"any", "wifi_only"}
                or not 0 <= index < (size + CHUNK_RAW - 1) // CHUNK_RAW or not raw
                or len(raw) != (CHUNK_RAW if index + 1 < (size + CHUNK_RAW - 1) // CHUNK_RAW
                                else size - index * CHUNK_RAW)):
            raise ValueError("invalid incoming attachment chunk")
        self._stage_attachment_chunks(peer_id, run_id, reply, aggregate_hash, digest, "incoming",
                                      size, mime, [(index, raw)], transport_policy, expires_ms, attachment_id or digest)

    def _stage_attachment_chunks(self, peer_id, run_id, reply, aggregate_hash, digest,
                                 direction, size, mime, chunks, policy, expires_ms, attachment_id):
        indexed = chunks
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            old_metadata = self._load_attachment_metadata(db, peer_id, run_id, reply, aggregate_hash, digest, direction)
            transfer_exists = old_metadata is not None
            metadata = self._attachment_metadata(peer_id, run_id, reply, aggregate_hash, digest, direction,
                size, mime, policy, old_metadata["expires_ms"] if old_metadata else expires_ms, False,
                old_metadata["attachment_id"] if old_metadata else attachment_id)
            if old_metadata is not None and old_metadata != metadata:
                raise ValueError("conflicting attachment metadata")
            active = db.execute("SELECT COUNT(DISTINCT run_id||':'||reply||':'||direction) FROM personal_attachment_transfer WHERE peer_id=?", (peer_id,)).fetchone()[0]
            hashes = db.execute("SELECT COUNT(DISTINCT sha256) FROM personal_attachment_transfer WHERE peer_id=? AND run_id=?", (peer_id, run_id)).fetchone()[0]
            used = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk").fetchone()[0]
            run_used = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk WHERE peer_id=? AND run_id=?", (peer_id, run_id)).fetchone()[0]
            rows = db.execute("SELECT COUNT(*) FROM personal_attachment_chunk").fetchone()[0]
            added = 0
            inserted = 0
            db.execute("INSERT OR IGNORE INTO personal_attachment_transfer VALUES(?,?,?,?,?,?,?,?,?,?,0,?)",
                       (peer_id, run_id, int(reply), aggregate_hash, digest, direction, size, mime, policy,
                        expires_ms, self._encrypt_attachment_metadata(metadata)))
            for index, raw in indexed:
                primary = self._attachment_primary(peer_id, run_id, reply, aggregate_hash, digest, index, direction)
                old = db.execute("SELECT payload FROM personal_attachment_chunk WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction=? AND chunk_index=?",
                    (peer_id, run_id, int(reply), aggregate_hash, digest, direction, index)).fetchone()
                if old:
                    if not hmac.compare_digest(self._decrypt(old[0], "personal_attachment_chunk", primary), raw):
                        raise ValueError("conflicting attachment chunk")
                else:
                    value = self._encrypt(raw, "personal_attachment_chunk", primary)
                    if ((not transfer_exists and (active >= 4 or hashes >= 256)) or rows + inserted + 1 > 4096):
                        raise ValueError("attachment staging limit")
                    if used + added + len(value) > 100 * 1024 * 1024 or run_used + added + len(value) > 50 * 1024 * 1024:
                        raise ValueError("attachment staging capacity")
                    db.execute("INSERT INTO personal_attachment_chunk VALUES(?,?,?,?,?,?,?,?)",
                        (peer_id, run_id, int(reply), aggregate_hash, digest, direction, index, value))
                    added += len(value); inserted += 1

    def register_incoming_attachment(self, peer_id, run_id, reply, aggregate_hash, digest,
                                     size, mime, policy, expires_ms, attachment_id=None):
        if (not 1 <= size <= MAX_ATTACHMENT or mime not in MIMES or policy not in {"any", "wifi_only"}):
            raise ValueError("invalid incoming attachment manifest")
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._load_attachment_metadata(db, peer_id, run_id, reply, aggregate_hash, digest, "incoming")
            metadata = self._attachment_metadata(peer_id, run_id, reply, aggregate_hash, digest, "incoming",
                size, mime, policy, expires_ms, False, attachment_id or digest)
            if old and old != metadata:
                raise ValueError("conflicting attachment manifest")
            db.execute("INSERT OR IGNORE INTO personal_attachment_transfer VALUES(?,?,?,?,?,?,?,?,?,?,0,?)",
                (peer_id, run_id, int(reply), aggregate_hash, digest, "incoming", size, mime,
                 policy, expires_ms, self._encrypt_attachment_metadata(metadata)))

    def complete_outgoing_attachment(self, peer_id, run_id, reply, aggregate_hash, digest):
        with sqlite3.connect(self.database_path) as db:
            args = (peer_id, run_id, int(reply), aggregate_hash, digest)
            metadata = self._load_attachment_metadata(db, peer_id, run_id, reply, aggregate_hash, digest, "outgoing")
            if not metadata:
                return
            metadata["complete"] = True
            db.execute("UPDATE personal_attachment_transfer SET complete=1,metadata=? WHERE peer_id=? AND run_id=? "
                       "AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing'",
                       (self._encrypt_attachment_metadata(metadata), *args))

    def has_outgoing_attachments(self, peer_id, run_id):
        with sqlite3.connect(self.database_path) as db:
            rows = db.execute("SELECT peer_id,run_id,reply,records_hash,sha256,direction,size,mime,transport_policy,expires_ms,complete,metadata FROM personal_attachment_transfer WHERE peer_id=? AND run_id=? AND direction='outgoing'",
                (peer_id, run_id)).fetchall()
        return any(not self._decode_attachment_row(row)["complete"] for row in rows)

    def begin_local_attachment_index(self, peer_id, run_id, reply):
        key = "personal_local_index:%s:%s:%d" % (peer_id, run_id, int(reply))
        with sqlite3.connect(self.database_path) as db:
            return db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)",
                (key, str(now_ms()).encode("ascii"))).rowcount == 1

    def hold_personal_report(self, peer_id, body):
        key = "personal_report:%s:%s" % (peer_id, body["run_id"])
        encrypted = self._encrypt(canonical(body), "personal_report", key)
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, encrypted))

    def release_personal_report(self, peer_id, run_id):
        if self.has_outgoing_attachments(peer_id, run_id):
            return None
        key = "personal_report:%s:%s" % (peer_id, run_id)
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        report = strict_json(self._decrypt(row[0], "personal_report", key))
        with sqlite3.connect(self.database_path) as db:
            db.execute("DELETE FROM meta WHERE key=? AND value=?", (key, row[0]))
        return report

    def reuse_staged_attachment(self, peer_id, run_id, reply, aggregate_hash, descriptor,
                                policy, expires_ms):
        """Reuse an exact encrypted local snapshot without exposing it to the domain layer."""
        with sqlite3.connect(self.database_path) as db:
            source = db.execute("SELECT run_id,reply,records_hash,size,mime FROM personal_attachment_transfer "
                "WHERE peer_id=? AND sha256=? AND direction='outgoing' AND expires_ms>? "
                "ORDER BY expires_ms DESC LIMIT 1", (peer_id, descriptor["sha256"], now_ms())).fetchone()
            if not source or source[3:] != (descriptor["size"], descriptor["mime"]):
                return False
            source_metadata = self._load_attachment_metadata(db, peer_id, source[0], bool(source[1]),
                source[2], descriptor["sha256"], "outgoing")
            if not source_metadata:
                return False
            rows = db.execute("SELECT chunk_index,payload FROM personal_attachment_chunk WHERE peer_id=? "
                "AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing' ORDER BY chunk_index",
                (peer_id, source[0], source[1], source[2], descriptor["sha256"])).fetchall()
        expected = (descriptor["size"] + CHUNK_RAW - 1) // CHUNK_RAW
        if [row[0] for row in rows] != list(range(expected)):
            return False
        self.register_incoming_attachment(peer_id, run_id, reply, aggregate_hash,
            descriptor["sha256"], descriptor["size"], descriptor["mime"], policy, expires_ms,
            descriptor["attachment_id"])
        for index, encrypted in rows:
            old_primary = self._attachment_primary(peer_id, source[0], bool(source[1]),
                source[2], descriptor["sha256"], index, "outgoing")
            raw = self._decrypt(encrypted, "personal_attachment_chunk", old_primary)
            self.stage_incoming_attachment(peer_id, run_id, reply, aggregate_hash,
                descriptor["sha256"], descriptor["size"], descriptor["mime"], index, raw,
                policy, expires_ms, descriptor["attachment_id"])
        return True

    def attachment_missing_ranges(self, peer_id, run_id, reply, aggregate_hash, digest):
        with sqlite3.connect(self.database_path) as db:
            transfer = self._load_attachment_metadata(db, peer_id, run_id, reply, aggregate_hash, digest, "incoming")
            present = {row[0] for row in db.execute("SELECT chunk_index FROM personal_attachment_chunk WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='incoming'",
                (peer_id, run_id, int(reply), aggregate_hash, digest))}
        if not transfer:
            return []
        missing = [index for index in range(transfer["total_chunks"]) if index not in present]
        ranges = []
        for index in missing:
            if ranges and ranges[-1][1] == index:
                ranges[-1][1] += 1
            else:
                ranges.append([index, index + 1])
        return ranges

    def requested_attachment_chunks(self, peer_id, run_id, reply, aggregate_hash, wants,
                                    transport="wifi"):
        """Scheduler window; callers still perform grant/own-device checks before send."""
        if transport not in {"wifi", "bluetooth"}:
            raise ValueError("invalid transport")
        result = []
        with sqlite3.connect(self.database_path) as db:
            for want in wants:
                digest = want["sha256"]
                metadata = self._load_attachment_metadata(db, peer_id, run_id, reply, aggregate_hash, digest, "outgoing")
                if not metadata or metadata["transport_policy"] == "wifi_only" and transport != "wifi":
                    continue
                for start, end in want["ranges"]:
                    for index in range(start, end):
                        row = db.execute("SELECT payload FROM personal_attachment_chunk WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing' AND chunk_index=?",
                            (peer_id, run_id, int(reply), aggregate_hash, digest, index)).fetchone()
                        if row:
                            primary = self._attachment_primary(peer_id, run_id, reply, aggregate_hash, digest, index, "outgoing")
                            result.append((digest, index, self._decrypt(row[0], "personal_attachment_chunk", primary)))
                        if len(result) == 8:
                            return result
        return result

    def verify_incoming_attachment(self, peer_id, run_id, reply, aggregate_hash, digest, sink):
        """Stream a complete file into sink while checking size, hash and magic."""
        with sqlite3.connect(self.database_path) as db:
            transfer = self._load_attachment_metadata(db, peer_id, run_id, reply, aggregate_hash, digest, "incoming")
            rows = db.execute("SELECT chunk_index,payload FROM personal_attachment_chunk WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='incoming' ORDER BY chunk_index",
                (peer_id, run_id, int(reply), aggregate_hash, digest)).fetchall()
        if not transfer or self.attachment_missing_ranges(peer_id, run_id, reply, aggregate_hash, digest):
            return False
        hasher, total, prefix = hashlib.sha256(), 0, bytearray()
        for index, payload in rows:
            primary = self._attachment_primary(peer_id, run_id, reply, aggregate_hash, digest, index, "incoming")
            raw = self._decrypt(payload, "personal_attachment_chunk", primary)
            if len(prefix) < 16:
                prefix.extend(raw[:16 - len(prefix)])
            hasher.update(raw); total += len(raw); sink.write(raw)
        valid = total == transfer["size"] and hasher.hexdigest() == digest and mime_from_magic(bytes(prefix)) == transfer["mime"]
        if valid:
            transfer["complete"] = True
            with sqlite3.connect(self.database_path) as db:
                db.execute("UPDATE personal_attachment_transfer SET complete=1,metadata=? WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='incoming'",
                    (self._encrypt_attachment_metadata(transfer), peer_id, run_id, int(reply), aggregate_hash, digest))
        return valid

    def _personal_run_record(self, peer_id, run_id):
        key = "personal_run:%s:%s" % (peer_id, run_id)
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        stored = strict_json(self._decrypt(row[0], "personal_run", key))
        if (not isinstance(stored, dict) or set(stored) - {"body", "created_ms", "expires_ms", "finished_ms"}
                or set(stored) < {"body", "created_ms", "expires_ms"}
                or not isinstance(stored["body"], dict) or stored["body"].get("run_id") != run_id
                or not valid_timestamp(stored["created_ms"]) or not valid_timestamp(stored["expires_ms"])
                or stored["expires_ms"] <= stored["created_ms"]):
            raise ValueError("invalid durable personal sync run")
        if stored["body"].get("trigger") not in {"manual", "auto_wifi"}:
            raise ValueError("invalid durable personal sync policy")
        return stored

    def remember_personal_run(self, peer_id, body, claimed_expires_ms=None):
        key = "personal_run:%s:%s" % (peer_id, body["run_id"])
        existing = self._personal_run_record(peer_id, body["run_id"])
        if existing:
            if existing["body"] != body:
                raise ValueError("conflicting personal sync run")
            if claimed_expires_ms is not None and claimed_expires_ms > existing["expires_ms"]:
                raise ValueError("personal sync run lifetime extension")
            return
        created = now_ms()
        expires = created + DAY_MS
        if claimed_expires_ms is not None:
            if not valid_timestamp(claimed_expires_ms) or claimed_expires_ms <= created:
                raise ValueError("expired personal sync run")
            expires = min(expires, claimed_expires_ms)
        value = self._encrypt(canonical({"body": body, "created_ms": created,
            "expires_ms": expires}), "personal_run", key)
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (key, value))

    def active_auto_run(self, peer_id):
        key = "personal_active_auto:" + peer_id
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            runs = db.execute("SELECT key,value FROM meta WHERE key LIKE ?",
                              ("personal_run:%s:%%" % peer_id,)).fetchall()
        if row:
            marker = strict_json(self._decrypt(row[0], "personal_active_auto", key))
            if marker.get("expires_ms", 0) > now_ms():
                return marker["run_id"]
        for run_key, encrypted in runs:
            stored = strict_json(self._decrypt(encrypted, "personal_run", run_key))
            body = stored.get("body", stored)
            if (body.get("trigger") == "auto_wifi" and not stored.get("finished_ms")
                    and stored.get("expires_ms", 0) > now_ms()):
                return body["run_id"]
        return ""

    def set_active_auto_run(self, peer_id, run_id):
        key = "personal_active_auto:" + peer_id
        created = now_ms()
        value = self._encrypt(canonical({"run_id": run_id, "created_ms": created,
            "expires_ms": created + DAY_MS}), "personal_active_auto", key)
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    def finish_auto_run(self, peer_id, run_id):
        run_key = "personal_run:%s:%s" % (peer_id, run_id)
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (run_key,)).fetchone()
            if row:
                stored = strict_json(self._decrypt(row[0], "personal_run", run_key))
                if "body" in stored:
                    stored["finished_ms"] = now_ms()
                    db.execute("UPDATE meta SET value=? WHERE key=?", (
                        self._encrypt(canonical(stored), "personal_run", run_key), run_key))
            db.execute("DELETE FROM meta WHERE key=?", ("personal_active_auto:" + peer_id,))

    def personal_run(self, peer_id, run_id):
        stored = self._personal_run_record(peer_id, run_id)
        return stored["body"] if stored else {}

    def commit_personal_batch(self, peer_id, message_id, token):
        if not all(isinstance(value, str) and value for value in (peer_id, message_id, token)):
            raise ValueError("invalid personal commit token")
        with sqlite3.connect(self.database_path) as db:
            identity = db.execute("SELECT run_id,reply FROM personal_batch WHERE peer_id=? AND message_id=? "
                "AND commit_token=?", (peer_id, message_id, token)).fetchone()
            if not identity:
                return peer_id, []
            run_id, reply = identity
            rows = db.execute("SELECT sequence,payload FROM personal_batch WHERE peer_id=? AND run_id=? AND reply=? "
                "AND commit_token=? ORDER BY sequence", (peer_id, run_id, reply, token)).fetchall()
        messages = []
        for sequence, payload in rows:
            primary = "%s:%s:%d:%d" % (peer_id, run_id, reply, sequence)
            messages.append(strict_json(self._decrypt(payload, "personal_batch", primary)))
        if (not messages or [row[0] for row in rows] != list(range(len(rows))) or
                not messages[-1]["body"]["last"] or messages[-1]["message_id"] != message_id or
                any(item["body"]["last"] for item in messages[:-1]) or
                any(item["expires_ms"] <= now_ms() for item in messages)):
            return peer_id, []
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT COUNT(*) FROM personal_batch WHERE peer_id=? AND run_id=? AND reply=? "
                "AND commit_token=?", (peer_id, run_id, reply, token)).fetchone()[0]
            if current != len(messages):
                return peer_id, []
            db.execute("UPDATE inbox SET state='accepted' WHERE peer_id=? AND message_id IN (%s)" %
                ",".join("?" for _ in messages), (peer_id, *[item["message_id"] for item in messages]))
            applied_key = "personal_applied:%s:%s:%d" % (peer_id, run_id, reply)
            applied = self._encrypt(canonical({"commit_token": token, "applied_ms": now_ms()}),
                                    "personal_applied", applied_key)
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (applied_key, applied))
            db.execute("DELETE FROM personal_batch WHERE peer_id=? AND run_id=? AND reply=? AND commit_token=?",
                       (peer_id, run_id, reply, token))
        return peer_id, [message["message_id"] for message in messages]

    def completed_incoming_for_batch(self, peer_id, message_id, token):
        with sqlite3.connect(self.database_path) as db:
            identity = db.execute("SELECT run_id,reply FROM personal_batch WHERE peer_id=? AND message_id=? "
                "AND commit_token=?", (peer_id, message_id, token)).fetchone()
            if not identity:
                return []
            rows = db.execute("SELECT peer_id,run_id,reply,records_hash,sha256,direction,size,mime,transport_policy,expires_ms,complete,metadata FROM personal_attachment_transfer WHERE peer_id=? AND run_id=? AND reply=? AND direction='incoming'",
                (peer_id, identity[0], identity[1])).fetchall()
            return [(identity[0], bool(identity[1]), metadata["records_hash"], metadata["sha256"])
                    for row in rows for metadata in [self._decode_attachment_row(row)] if metadata["complete"]]

    def has_personal_batch(self, peer_id, message_id, token):
        with sqlite3.connect(self.database_path) as db:
            return db.execute("SELECT 1 FROM personal_batch WHERE peer_id=? AND message_id=? "
                              "AND commit_token=?", (peer_id, message_id, token)).fetchone() is not None

    def ready_personal_batches(self):
        with sqlite3.connect(self.database_path) as db:
            groups = db.execute("SELECT peer_id,run_id,reply,MAX(sequence) FROM personal_batch GROUP BY peer_id,run_id,reply").fetchall()
        ready = []
        for peer_id, run_id, reply, sequence in groups:
            primary = "%s:%s:%d:%d" % (peer_id, run_id, reply, sequence)
            with sqlite3.connect(self.database_path) as db:
                row = db.execute("SELECT payload FROM personal_batch WHERE peer_id=? AND run_id=? AND reply=? AND sequence=?",
                    (peer_id, run_id, reply, sequence)).fetchone()
            if row:
                aggregate = self.stage_personal_batch(peer_id,
                    strict_json(self._decrypt(row[0], "personal_batch", primary)))
                if aggregate:
                    ready.append((peer_id, aggregate))
        return ready

    def dedupe_result(self, peer_id, message_id):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT result,error FROM dedupe WHERE peer_id=? AND message_id=?",
                             (peer_id, message_id)).fetchone()
        return tuple(row) if row else None

    def received_matches(self, peer_id, message):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT payload FROM inbox WHERE peer_id=? AND message_id=?",
                             (peer_id, message["message_id"])).fetchone()
        return bool(row and strict_json(self._decrypt(row[0], "inbox", message["message_id"])) == message)

    def remember_result(self, peer_id, message_id, result, error):
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT OR REPLACE INTO dedupe VALUES(?,?,?,?,?)",
                        (message_id, peer_id, result, error, int(time.time() * 1000)))

    def remember_message(self, peer_id, message, result, error):
        if message.get("kind") == "device_status.report":
            message = dict(message, body=without_device_identifiers(message["body"]))
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
        expired_runs = []
        with sqlite3.connect(self.database_path) as db:
            partial = db.execute("SELECT DISTINCT peer_id,run_id FROM personal_batch WHERE expires_ms<=?", (now,)).fetchall()
            db.execute("DELETE FROM outbox WHERE expires_ms<=?", (now,))
            db.execute("DELETE FROM inbox WHERE received_ms<?", (now - 30 * DAY_MS,))
            db.execute("DELETE FROM inbox WHERE kind='selected_notifications_readonly.event' "
                       "AND received_ms<?",
                       (now - EVENT_RETENTION_MS,))
            db.execute("DELETE FROM dedupe WHERE seen_ms<?", (now - 90 * DAY_MS,))
            db.execute("DELETE FROM personal_batch WHERE expires_ms<=? OR received_ms<?", (now, now - DAY_MS))
            db.execute("DELETE FROM personal_domain WHERE expires_ms<=? OR received_ms<?", (now, now - DAY_MS))
            db.execute("DELETE FROM personal_attachment_chunk WHERE EXISTS (SELECT 1 FROM personal_attachment_transfer t WHERE t.peer_id=personal_attachment_chunk.peer_id AND t.run_id=personal_attachment_chunk.run_id AND t.reply=personal_attachment_chunk.reply AND t.records_hash=personal_attachment_chunk.records_hash AND t.sha256=personal_attachment_chunk.sha256 AND t.direction=personal_attachment_chunk.direction AND t.expires_ms<=?)", (now,))
            db.execute("DELETE FROM personal_attachment_transfer WHERE expires_ms<=?", (now,))
            db.execute("DELETE FROM command_effect WHERE first_seen_ms<?", (now - 90 * DAY_MS,))
            for table, order, limit in (("inbox", "received_ms", 10000),
                                        ("command_effect", "first_seen_ms", 100000)):
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
            db.execute("DELETE FROM meta WHERE key LIKE 'personal_local_index:%' AND CAST(value AS INTEGER)<?",
                       (now - DAY_MS,))
            for key, encrypted in db.execute("SELECT key,value FROM meta WHERE key LIKE 'personal_run:%'").fetchall():
                try:
                    stored = strict_json(self._decrypt(encrypted, "personal_run", key))
                    body = stored.get("body", stored)
                    if stored.get("expires_ms", now + 1) <= now:
                        if stored.get("finished_ms"):
                            db.execute("DELETE FROM meta WHERE key=?", (key,))
                        else:
                            expired_runs.append((key.split(":", 2)[1], body["run_id"]))
                except Exception:
                    db.execute("DELETE FROM meta WHERE key=?", (key,))
            for peer_id, run_id in expired_runs:
                db.execute("DELETE FROM meta WHERE key=?", ("personal_active_auto:" + peer_id,))
                if (peer_id, run_id) not in partial:
                    partial.append((peer_id, run_id))
        for peer_id, run_id in set(partial):
            run = self.personal_run(peer_id, run_id)
            trigger = run.get("trigger", "manual")
            counts = {"notes": 0, "tasks": 0, "notebooks": 0}
            report = {"format": run.get("format", 1), "run_id": run_id, "state": "partial", "trigger": trigger,
                "transport": "wifi", "sent": counts, "received": dict(counts), "conflicts": 0,
                "attachments_omitted": 0, "oversized_skipped": 0, "started_ms": now,
                "finished_ms": now, "error": "protocol", "deletions": {
                    "pending": 0, "deleted": 0, "restored": 0, "conflicts": 0, "blocked": 0,
                    "trash": {"notes": 0, "tasks": 0, "notebooks": 0, "attachments": 0}}}
            if report["format"] >= 2:
                report["attachments"] = dict.fromkeys(("declared", "requested", "sent", "received",
                                                       "reused", "preserved", "failed", "bytes"), 0)
            shaped = bytearray(hashlib.sha256(("magnolie-expiry:%s:%s" % (peer_id, run_id)).encode()).digest()[:16])
            shaped[6] = (shaped[6] & 0x0f) | 0x40
            shaped[8] = (shaped[8] & 0x3f) | 0x80
            message_id = str(uuid.UUID(bytes=bytes(shaped)))
            message = {"type": "message", "v": 1, "message_id": message_id,
                       "kind": "personal_sync.report", "created_ms": now,
                       "expires_ms": now + DAY_MS, "body": report}
            encrypted = self._encrypt(canonical(message), "outbox", message_id)
            with sqlite3.connect(self.database_path) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT OR IGNORE INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (message_id, peer_id, message["kind"], now, now + DAY_MS, encrypted, 0, now, "",
                     "wifi_only" if trigger == "auto_wifi" else "any"))
                db.execute("DELETE FROM meta WHERE key IN (?,?)", (
                    "personal_active_auto:" + peer_id, "personal_run:%s:%s" % (peer_id, run_id)))

    def remember_command(self, peer_id, client_ref, state):
        with sqlite3.connect(self.database_path) as db:
            db.execute("INSERT INTO command_effect(client_ref,state,first_seen_ms,peer_id) VALUES(?,?,?,?)",
                       (client_ref, state, now_ms(), peer_id))

    def command_state(self, client_ref):
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT state FROM command_effect WHERE client_ref=?",
                             (client_ref,)).fetchone()
        return row[0] if row else ""

    def update_command(self, peer_id, client_ref, state):
        with sqlite3.connect(self.database_path) as db:
            changed = db.execute("UPDATE command_effect SET state=? WHERE peer_id=? AND client_ref=?",
                                   (state, peer_id, client_ref)).rowcount
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


def discover_setup_phones(timeout=4):
    """Untrusted NSD candidates, bounded to 16 resolutions and IPv4 LAN addresses."""
    import ipaddress
    from zeroconf import IPVersion, ServiceBrowser, Zeroconf
    found, seen = {}, set()
    lock = threading.Lock()
    service_type = "_magnolie-invite._tcp.local."

    class Listener:
        def add_service(self, zc, kind, name):
            with lock:
                if name in seen or len(seen) >= 16:
                    return
                seen.add(name)
            info = zc.get_service_info(kind, name, timeout=250)
            if not info or not 1024 <= info.port <= 65535:
                return
            try:
                fields = {key.decode("ascii"): value.decode("utf-8") for key, value in info.properties.items()}
                if set(fields) != {"v", "id", "name", "nonce"} or fields["v"] != "1" or not valid_uuid(fields["id"]):
                    return
                unb64(fields["nonce"], 16)
                display = fields["name"]
                if not 1 <= len(display) <= 60 or any(ord(c) < 32 or unicodedata.category(c) == "Cf" for c in display):
                    return
                for raw in info.addresses:
                    address = ipaddress.ip_address(raw)
                    if address.version == 4 and (address in ipaddress.ip_network("10.0.0.0/8") or
                            address in ipaddress.ip_network("172.16.0.0/12") or address in ipaddress.ip_network("192.168.0.0/16") or
                            address in ipaddress.ip_network("169.254.0.0/16")):
                        with lock:
                            found.setdefault(fields["id"], {"uid": fields["id"], "name": display,
                                "address": str(address), "port": info.port, "nonce": fields["nonce"]})
                        break
            except (ValueError, UnicodeError, AttributeError):
                return
        update_service = add_service
        def remove_service(self, *_args):
            pass

    with Zeroconf(ip_version=IPVersion.V4Only) as zc:
        browser = ServiceBrowser(zc, service_type, Listener())
        try:
            time.sleep(min(5, max(0, timeout)))
        finally:
            browser.cancel()
    with lock:
        return list(found.values())


class BlueZBluetoothBackend:
    """Native BlueZ pairing and selected-device RFCOMM client profiles."""

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

    def paired_devices(self):
        try:
            result = self._bluetoothctl("devices", "Paired")
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode:
            return []
        devices = []
        for line in result.stdout.splitlines():
            match = re.fullmatch(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
            if not match:
                continue
            address, name = match.groups()
            name = "".join(char for char in name if ord(char) >= 32).strip()[:60]
            if not any(device["address"] == address.upper() for device in devices):
                devices.append({"address": address.upper(), "name": name or address.upper()})
        return devices

    @staticmethod
    def _bluez():
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        objects = bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
            None, None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        return bus, objects

    @staticmethod
    def _register_bluez_object(bus, path, xml, callback):
        from gi.repository import Gio, GLib
        context = GLib.MainContext.new()
        context.push_thread_default()
        try:
            registration = bus.register_object(path, Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], callback, None, None)
        finally:
            context.pop_thread_default()
        loop = GLib.MainLoop.new(context, False)
        ready = threading.Event()
        def started(*_args):
            ready.set()
            return False
        source = GLib.idle_source_new()
        source.set_callback(started)
        source.attach(context)
        threading.Thread(target=loop.run, name="magnolie-phone-bluez", daemon=True).start()
        if not ready.wait(2):
            bus.unregister_object(registration)
            loop.quit()
            raise TimeoutError("BlueZ callback loop did not start")
        return registration, loop

    def discover_devices(self, cancelled):
        from gi.repository import Gio
        bus, objects = self._bluez()
        adapter = next((path for path, interfaces in sorted(objects.items())
                        if interfaces.get("org.bluez.Adapter1", {}).get("Powered")), None)
        if not adapter:
            return []
        owned = False
        try:
            bus.call_sync("org.bluez", adapter, "org.bluez.Adapter1", "StartDiscovery", None, None,
                          Gio.DBusCallFlags.NONE, 3000, None)
            owned = True
            cancelled.wait(8)
            if cancelled.is_set():
                raise InterruptedError("Bluetooth discovery cancelled")
            _bus, objects = self._bluez()
            result = []
            for path, interfaces in objects.items():
                device = interfaces.get("org.bluez.Device1", {})
                address = str(device.get("Address", "")).upper()
                if device.get("Adapter") != adapter or not BLUETOOTH_ADDRESS.fullmatch(address) or device.get("Blocked") or any(item["address"] == address for item in result):
                    continue
                name = str(device.get("Alias", device.get("Name", address)))
                name = "".join(c for c in name if not unicodedata.category(c).startswith("C"))[:60] or address
                result.append({"id": path, "address": address, "name": name, "paired": bool(device.get("Paired"))})
                if len(result) == 32:
                    break
            return result
        finally:
            if owned:
                try:
                    bus.call_sync("org.bluez", adapter, "org.bluez.Adapter1", "StopDiscovery", None, None,
                                  Gio.DBusCallFlags.NONE, 3000, None)
                except Exception:
                    pass

    def pair_device(self, selected, prompt, cancelled):
        from gi.repository import Gio, GLib
        bus, objects = self._bluez()
        path = selected["id"]
        owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
            GLib.Variant("(s)", ("org.bluez",)), None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        device = objects.get(path, {}).get("org.bluez.Device1", {})
        if str(device.get("Address", "")).upper() != selected["address"]:
            raise ValueError("Wrong Bluetooth device.")
        if device.get("Paired"):
            return
        agent_path = "/io/gitlab/magnolie/phone_setup_" + uuid.uuid4().hex
        xml = """<node><interface name='org.bluez.Agent1'>
          <method name='Release'/><method name='Cancel'/>
          <method name='RequestConfirmation'><arg type='o' direction='in'/><arg type='u' direction='in'/></method>
          <method name='RequestAuthorization'><arg type='o' direction='in'/></method>
          <method name='AuthorizeService'><arg type='o' direction='in'/><arg type='s' direction='in'/></method>
          <method name='RequestPinCode'><arg type='o' direction='in'/><arg type='s' direction='out'/></method>
          <method name='RequestPasskey'><arg type='o' direction='in'/><arg type='u' direction='out'/></method>
        </interface></node>"""
        finished = threading.Event()
        prompting = threading.Event()
        operation = Gio.Cancellable()
        def call(_bus, _sender, _path, _interface, method, parameters, invocation):
            args = parameters.unpack()
            if _sender != owner:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "Unexpected agent caller")
                return
            if method in ("Cancel", "Release"):
                operation.cancel()
                invocation.return_value(None)
                return
            if method not in ("RequestConfirmation", "RequestAuthorization") or not args or args[0] != path or prompting.is_set():
                invocation.return_dbus_error("org.bluez.Error.Rejected", "Unexpected pairing request")
                return
            prompting.set()
            def confirm():
                try:
                    answer = prompt({"kind": "confirm", "devices": [{"uid": selected["address"], "name": selected["name"]}],
                                     "code": "%06d" % args[1] if method == "RequestConfirmation" else ""})
                    if answer != "accept" or cancelled.is_set() or finished.is_set() or operation.is_cancelled():
                        raise PermissionError()
                    invocation.return_value(None)
                except Exception:
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "Pairing not confirmed")
                finally:
                    prompting.clear()
            threading.Thread(target=confirm, daemon=True).start()
        registration, loop = self._register_bluez_object(bus, agent_path, xml, call)
        registered = False
        def watch():
            until = time.monotonic() + 60
            while not finished.wait(.2):
                if cancelled.is_set() or time.monotonic() >= until:
                    operation.cancel()
                    return
        threading.Thread(target=watch, daemon=True).start()
        try:
            registered = True
            bus.call_sync("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                          GLib.Variant("(os)", (agent_path, "DisplayYesNo")), None, Gio.DBusCallFlags.NONE, 3000, None)
            bus.call_sync("org.bluez", path, "org.bluez.Device1", "Pair", None, None, Gio.DBusCallFlags.NONE, 60000, operation)
            if cancelled.is_set() or not self.paired(selected["address"]):
                raise PermissionError("Bluetooth system pairing was not confirmed.")
        finally:
            finished.set()
            if operation.is_cancelled():
                try:
                    bus.call_sync("org.bluez", path, "org.bluez.Device1", "CancelPairing", None, None, Gio.DBusCallFlags.NONE, 2000, None)
                except Exception:
                    pass
            if registered:
                try:
                    bus.call_sync("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                                  GLib.Variant("(o)", (agent_path,)), None, Gio.DBusCallFlags.NONE, 2000, None)
                except Exception:
                    pass
            bus.unregister_object(registration)
            loop.quit()

    def connect(self, address, service_uuid, cancelled=None):
        if not BLUETOOTH_ADDRESS.fullmatch(address) or service_uuid != BLUETOOTH_UUID or not self.paired(address):
            raise PermissionError("Bluetooth device is not system-paired")
        from gi.repository import Gio, GLib
        bus, objects = self._bluez()
        paths = [path for path, interfaces in objects.items() if
                 str(interfaces.get("org.bluez.Device1", {}).get("Address", "")).upper() == address and
                 interfaces.get("org.bluez.Device1", {}).get("Paired")]
        if len(paths) != 1:
            raise ValueError("Wrong Bluetooth device.")
        device_path = paths[0]
        owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
            GLib.Variant("(s)", ("org.bluez",)), None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        profile_path = "/io/gitlab/magnolie/phone_rfcomm_" + uuid.uuid4().hex
        xml = """<node><interface name='org.bluez.Profile1'>
          <method name='Release'/>
          <method name='NewConnection'><arg type='o' direction='in'/><arg type='h' direction='in'/><arg type='a{sv}' direction='in'/></method>
          <method name='RequestDisconnection'><arg type='o' direction='in'/></method>
        </interface></node>"""
        received = [None]
        closed = threading.Event()
        ownership = threading.Lock()
        registered = [False]
        def call(_bus, sender, _path, _interface, method, parameters, invocation):
            args = parameters.unpack()
            if sender != owner or method != "Release" and (not args or args[0] != device_path):
                invocation.return_dbus_error("org.bluez.Error.Rejected", "Wrong Bluetooth device")
                return
            if method == "NewConnection":
                ownership.acquire()
                if received[0] is not None or closed.is_set():
                    ownership.release()
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "Unexpected RFCOMM connection")
                    return
                fd = None
                raw = None
                try:
                    fd = invocation.get_message().get_unix_fd_list().get(args[1])
                    raw = socket.socket(fileno=fd)
                    if str(raw.getpeername()[0]).upper() != address:
                        raw.close()
                        raise ValueError("Wrong Bluetooth device")
                    received[0] = raw
                    invocation.return_value(None)
                except Exception:
                    if raw is not None:
                        raw.close()
                    elif fd is not None:
                        os.close(fd)
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "Invalid RFCOMM stream")
                finally:
                    ownership.release()
            elif method in ("Release", "RequestDisconnection"):
                if received[0] is not None:
                    received[0].close()
                invocation.return_value(None)
            else:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "Unexpected RFCOMM connection")
        registration, loop = self._register_bluez_object(bus, profile_path, xml, call)
        class ProfileSocket:
            def __getattr__(self, name): return getattr(received[0], name)
            def close(self):
                with ownership:
                    if closed.is_set(): return
                    closed.set()
                    if received[0] is not None: received[0].close()
                if registered[0]:
                    try:
                        bus.call_sync("org.bluez", "/org/bluez", "org.bluez.ProfileManager1", "UnregisterProfile",
                            GLib.Variant("(o)", (profile_path,)), None, Gio.DBusCallFlags.NONE, 2000, None)
                    except Exception:
                        pass
                bus.unregister_object(registration)
                loop.quit()
        stream = ProfileSocket()
        operation = Gio.Cancellable()
        connected = threading.Event()
        def cancel_connect():
            while not connected.wait(.1):
                if cancelled.is_set():
                    operation.cancel()
                    return
        if cancelled is not None:
            threading.Thread(target=cancel_connect, daemon=True).start()
        try:
            options = {"Role": GLib.Variant("s", "client"), "RequireAuthentication": GLib.Variant("b", True),
                       "AutoConnect": GLib.Variant("b", False)}
            registered[0] = True
            bus.call_sync("org.bluez", "/org/bluez", "org.bluez.ProfileManager1", "RegisterProfile",
                GLib.Variant("(osa{sv})", (profile_path, service_uuid, options)), None, Gio.DBusCallFlags.NONE, 3000, operation)
            # BlueZ resolves the 128-bit SDP UUID and hands over its connected fd.
            bus.call_sync("org.bluez", device_path, "org.bluez.Device1", "ConnectProfile",
                GLib.Variant("(s)", (service_uuid,)), None, Gio.DBusCallFlags.NONE, 10000, operation)
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError("Bluetooth connection cancelled")
            if received[0] is None:
                raise OSError("Open the phone connection screen and try again.")
            return stream
        except Exception:
            stream.close()
            raise
        finally:
            connected.set()


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

    def __init__(self, root, display_name, callback=None, bluetooth_backend=None, call_audio=None):
        self.store = PhoneStore(root, display_name)
        self.callback = callback or (lambda _event, _payload: None)
        self.enabled = self.store.settings()["enabled"]
        self.server = self.thread = self.mdns = None
        self.stop_event = threading.Event()
        self.pairing_token = None
        self.pairing_until = 0
        self.pairings = {}
        self.pairing_attempt_active = False
        self.connections = {}
        self.status_requests = {}
        self.identifier_requests = {}
        self.transient_identifiers = {}
        self.lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._workers = set()
        self._sockets = set()
        self._generation = 0
        self.active_by_ip = {}
        self.connection_transports = {}
        self.connection_errors = {}
        self.bluetooth_backend = bluetooth_backend or BlueZBluetoothBackend()
        self.bluetooth_thread = None
        self.wifi_missing_since = {}
        self.bluetooth_retry_at = {}
        self.incoming_calls = {}
        self.incoming_call_channels = {}
        from magnolie_anruf_audio import AnrufBluetooth
        self.call_audio = call_audio or AnrufBluetooth()
        self.call_audio.foreign_connection = self._audio_data_connection_in_use
        self.audio_thread = None
        self.audio_observations = {}
        self.audio_retired_calls = deque(maxlen=128)
        self.audio_capability = self.call_audio.snapshot("unavailable", "not_probed")
        self.audio_capability_at = 0
        self.audio_capability_address = ""
        self.call_action_tickets = {}
        self.personal_commit_events = {}
        self.personal_dispatched = set()
        self.personal_sync_available = lambda: True
        self.personal_offers = deque(maxlen=256)
        self.personal_offer_keys = set()

    def report(self):
        with self.lock:
            for peer_id, value in list(self.transient_identifiers.items()):
                if value[1] <= now_ms() or value[5] <= time.monotonic():
                    self._purge_identifiers(peer_id)
            for peer_id, request in list(self.identifier_requests.items()):
                if request[3] <= time.monotonic():
                    self._purge_identifiers(peer_id)
        bluetooth_available, bluetooth_reason = self.bluetooth_backend.availability()
        bluetooth_devices = (self.bluetooth_backend.paired_devices()
                             if bluetooth_available else [])
        peers = []
        binding_conflict = self.store.binding_conflict()
        for peer in self.store.peers:
            peer_id = peer.get("device_id", "")
            transport = self.connection_transports.get(peer_id, "")
            bluetooth = peer.get("bluetooth", {"enabled": False, "address": ""})
            personal = peer.get("personal_sync", {"own_device": False,
                "remote_own_device": False, "auto_wifi": False, "last_report": {}})
            peers.append({"device_id": peer_id, "display_name": peer.get("display_name", ""),
                          "fingerprint": fingerprint(unb64(peer["static_public"], 32)),
                           "state": "online_" + transport if transport else "offline",
                           "transport": transport,
                           "connection_error": self.connection_errors.get(peer_id, ""),
                          "last_contact_ms": peer.get("last_contact_ms", 0),
                          "status": self.store.status(peer_id),
                           "capabilities": peer.get("capabilities", {}),
                            "grants": peer.get("grants", {}),
                            "local_grants": peer.get("local_grants", {}),
                           "bluetooth_enabled": bluetooth["enabled"],
                            "bluetooth_address": bluetooth["address"],
                             "call_audio": dict(peer.get("call_audio", {}), address=self._call_audio_address(peer)),
                            "custom_sync": peer.get("custom_sync", {}),
                            "own_device": personal["own_device"] and not binding_conflict,
                           "remote_own_device": personal["remote_own_device"],
                           "auto_wifi": personal["auto_wifi"],
                           "personal_sync_active_auto": bool(
                               self.store.active_auto_run(peer_id)),
                           "personal_sync_report": personal["last_report"]})
        return {"possible": True, "enabled": self.enabled,
                "listening": bool(self.server), "port": PORT,
                "device_id": self.store.identity["device_id"],
                "display_name": self.store.identity["display_name"],
                "fingerprint": fingerprint(unb64(self.store.identity["static_public"], 32)),
                 "pairing": bool(self.pairing_token and time.monotonic() < self.pairing_until),
                 "binding_conflict": binding_conflict,
                  "call_audio": self.call_audio_status(),
                  "peers": peers, "bluetooth": {"available": bluetooth_available,
                    "reason": bluetooth_reason, "uuid": BLUETOOTH_UUID,
                    "devices": bluetooth_devices}}

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.store.save_settings(self.enabled)
        if self.enabled:
            self.start()
        else:
            self.stop()
        self.callback("status", self.report())

    @staticmethod
    def _call_audio_address(peer):
        return peer.get("call_audio", {}).get("address", peer.get("bluetooth", {}).get("address", ""))

    def _audio_data_connection_in_use(self, address):
        with self.lock:
            return any(self.connection_transports.get(peer.get("device_id")) == "bluetooth"
                and peer.get("bluetooth", {}).get("address") == address for peer in self.store.peers)

    def set_call_audio(self, peer_id, prefer_pc, address=None):
        if not isinstance(prefer_pc, bool):
            raise ValueError("Invalid call audio preference")
        with self.lock:
            peer = self.store.sole_peer(peer_id)
            if not peer or peer.get("state") != "paired":
                raise RuntimeError("Das Telefon ist nicht gekoppelt.")
            identity = peer["static_public"]
        if address is not None:
            if not isinstance(address, str):
                raise ValueError("Invalid call audio address")
            address = address.strip().upper()
            # Validate outside the service lock: audio cancellation takes the
            # audio lock before consulting the current phone context.
            self.call_audio.validate_binding(address)
        with self.lock:
            peer = self.store.sole_peer(peer_id)
            if not peer or peer.get("state") != "paired" or peer["static_public"] != identity:
                raise RuntimeError("Das Telefon ist nicht gekoppelt.")
            # A routing preference never grants call monitoring, answering or hanging up.
            previous = peer.get("call_audio")
            settings = dict(previous or {}, prefer_pc=prefer_pc)
            if address is not None:
                settings["address"] = address
            peer["call_audio"] = settings
            try:
                self.store.save_peers()
            except Exception:
                if previous is None:
                    peer.pop("call_audio", None)
                else:
                    peer["call_audio"] = previous
                raise
            self.audio_capability_at = 0
        if not prefer_pc:
            self.call_audio.restore()

    def call_audio_status(self):
        with self.lock:
            peers = [peer for peer in self.store.peers if peer.get("state") == "paired"]
            address = (self._call_audio_address(peers[0]) if len(peers) == 1
                       and peers[0].get("personal_sync", {}).get("own_device") else "")
            capability = (self.audio_capability if address == self.audio_capability_address else
                          self.call_audio.snapshot("unavailable", "not_probed"))
            route = dict(self.call_audio.state)
            if route.get("active"):
                context = self._call_audio_context()
                if not context or context != self.call_audio.active_context:
                    route = self.call_audio.snapshot("inactive", "call_changed")
            return dict(capability, route=route, authorization=self._call_audio_context(diagnostics=True))

    def _call_audio_context(self, diagnostics=False):
        with self.lock:
            peers = [peer for peer in self.store.peers if peer.get("state") == "paired"]
            peer = peers[0] if len(peers) == 1 else {}
            peer_id = peer.get("device_id", "")
            call = self.incoming_calls.get(peer_id, {})
            observation = self.audio_observations.get(peer_id)
            local, remote = peer.get("local_grants", {}), peer.get("grants", {})
            capability = peer.get("capabilities", {}).get("items", {}).get("incoming_call_state", {})
            address = self._call_audio_address(peer)
            checks = dict(service_ready=bool(self.enabled and not self.stop_event.is_set() and self.server),
                single_phone=len(peers) == 1 and not self.store.binding_conflict(),
                own_phone=bool(peer.get("personal_sync", {}).get("own_device")),
                pc_preferred=peer.get("call_audio", {}).get("prefer_pc") is True,
                local_grant=bool(local.get("grants", {}).get("incoming_call_state")),
                remote_grant=bool(remote.get("grants", {}).get("incoming_call_state")),
                call_capability=bool(capability.get("available") and 2 in capability.get("versions", [])),
                offhook=call.get("state") == "offhook", offhook_timestamp=bool(call.get("offhook_ms")),
                fresh_observation=bool(observation),
                current_call=bool(observation and observation[:2] == (call.get("call_ref"), call.get("revision"))),
                current_session=bool(observation and observation[2] is self.connections.get(peer_id)),
                current_grants=bool(observation and observation[3:] == (local.get("revision"), remote.get("revision"))),
                bluetooth_bound=bool(BLUETOOTH_ADDRESS.fullmatch(address)))
            if diagnostics:
                return checks  # Booleans only: no numbers, keys, call references or timestamps.
            if not all(checks.values()):
                return None
            return dict(device_id=peer_id, identity=peer["static_public"], session=id(observation[2]),
                        call_ref=call["call_ref"], revision=call["revision"], address=address,
                        consent=(local.get("revision"), remote.get("revision"), self._generation))

    def _call_audio_loop(self):
        try:
            while not self.stop_event.is_set():
                previous = self.call_audio_status()
                self.call_audio.update(self._call_audio_context)
                with self.lock:
                    peers = [peer for peer in self.store.peers if peer.get("state") == "paired"]
                    address = (self._call_audio_address(peers[0]) if len(peers) == 1
                               and peers[0].get("personal_sync", {}).get("own_device") else "")
                if self.call_audio.state.get("active"):
                    self.audio_capability = self.call_audio.snapshot("available", "ready")
                    self.audio_capability_address = address
                elif (not self.call_audio.modules_pending and not self.call_audio.profile_hold
                       and not getattr(self.call_audio, "connection_hold", None)
                       and not getattr(self.call_audio, "power_hold", None)
                      and (time.monotonic() >= self.audio_capability_at or address != self.audio_capability_address)):
                    self.audio_capability = self.call_audio.probe(address)
                    self.audio_capability_address = address
                    self.audio_capability_at = time.monotonic() + 10
                if previous != self.call_audio_status():
                    self.callback("call_audio", self.call_audio_status())
                self.stop_event.wait(.5)
        finally:
            self.call_audio.restore()

    def start(self):
        with self._lifecycle_lock:
            return self._start_owned()

    def _start_owned(self):
        if not self.enabled or self.server:
            return bool(self.server)
        with self.lock:
            if any(worker.is_alive() for worker in self._workers) or any(
                    worker is not None and worker.is_alive()
                    for worker in (self.thread, self.bluetooth_thread, self.audio_thread)):
                return False
            self._generation += 1
            self.stop_event = threading.Event()
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
        self.audio_thread = threading.Thread(target=self._call_audio_loop, name="magnolie-call-audio", daemon=True)
        self.audio_thread.start()
        self._ensure_pairing_available()
        self._publish()
        if not self.bluetooth_thread or not self.bluetooth_thread.is_alive():
            self.bluetooth_thread = threading.Thread(target=self._bluetooth_loop, daemon=True)
            self.bluetooth_thread.start()
        return True

    def stop(self):
        with self._lifecycle_lock:
            return self._stop_owned()

    def _stop_owned(self):
        self.stop_event.set()
        with self.lock:
            listener, self.server = self.server, None
            sockets = list(self._sockets) + [channel.sock for channel in self.connections.values()]
        for sock in sockets + ([listener] if listener is not None else []):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        setup = getattr(self, "setup_pairing", None)
        if setup:
            self.end_setup_pairing(b64(setup["token"]))
            self.setup_pairing = None
        self.cancel_pairing()
        self._unpublish()
        deadline = time.monotonic() + 15
        with self.lock:
            workers = list(self._workers) + [self.thread, self.bluetooth_thread, self.audio_thread]
        for worker in workers:
            if worker is not None and worker is not threading.current_thread():
                worker.join(max(0, deadline - time.monotonic()))
        with self.lock:
            drained = not any(worker is not None and worker.is_alive() for worker in workers)
        if drained:
            drained = self.call_audio.restore()
        with self.lock:
            if drained:
                self.connections.clear()
                self.connection_transports.clear()
                self.audio_observations.clear()
            return drained

    def _start_handler(self, sock, ip, transport):
        with self.lock:
            if self.stop_event.is_set():
                sock.close()
                return False
            worker = threading.Thread(target=self._handle,
                args=(sock, ip, transport, self._generation), daemon=True)
            self._workers.add(worker)
            self._sockets.add(sock)
            worker.start()
            return True

    def open_pairing(self):
        if not self.enabled:
            raise RuntimeError("Die Magnolie-Telefonverbindung ist ausgeschaltet.")
        if self.store.peers:
            raise RuntimeError("Only one Magnolie Notes phone can be paired. Remove the existing phone before changing devices.")
        self.start()
        setup = getattr(self, "setup_pairing", None)
        if setup:
            self.end_setup_pairing(b64(setup["token"]))
        self.setup_pairing = None
        self.pairing_token = os.urandom(16)
        self.pairing_until = float("inf")
        self._publish()
        token = b64(self.pairing_token)
        self.callback("pairing_open", {"token": token, "seconds": PAIRING_SECONDS,
                      "port": PORT, "display_name": self.store.identity["display_name"]})
        return token

    def open_setup_pairing(self, target, address, transport="wifi"):
        import ipaddress
        if not valid_uuid(target) or target == self.store.identity["device_id"] or transport not in ("wifi", "bluetooth"):
            raise ValueError("invalid setup target")
        if transport == "bluetooth":
            if not BLUETOOTH_ADDRESS.fullmatch(address):
                raise ValueError("invalid setup target")
            address = "bluetooth:" + address
        elif ipaddress.ip_address(address).version != 4:
            raise ValueError("invalid setup target")
        with self.lock:
            if self.store.peers or self.pairing_attempt_active:
                raise ValueError("phone binding already exists or pairing is active")
            token = os.urandom(16)
            self.pairing_token = token
            self.pairing_until = time.monotonic() + 120
            self.setup_pairing = {"target": target, "address": address, "token": token, "socket": None}
            timer = threading.Timer(120, self.end_setup_pairing, args=(b64(token),))
            timer.daemon = True
            self.setup_pairing["timer"] = timer
            timer.start()
        if transport == "wifi":
            self._publish()
        return {"device_id": self.store.identity["device_id"], "name": self.store.identity["display_name"], "token": b64(token)}

    def end_setup_pairing(self, token):
        sock = None
        with self.lock:
            setup = getattr(self, "setup_pairing", None)
            if setup and b64(setup["token"]) == token:
                self.pairing_until = 0
                setup["timer"].cancel()
                sock = setup["socket"]
                for context in list(self.pairings.values()):
                    context["decision"] = False
                    context["event"].set()
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if not setup or not setup["address"].startswith("bluetooth:"):
            self._publish()

    def cancel_pairing(self):
        self.pairing_token = None
        self.pairing_until = 0
        for context in list(self.pairings.values()):
            context["decision"] = False
            context["event"].set()
        self.pairings.clear()
        if self.enabled and self.server:
            self._ensure_pairing_available()
            self._publish()

    def confirm_pairing(self, attempt_id, accepted):
        context = self.pairings.get(attempt_id)
        if context:
            context["decision"] = bool(accepted)
            context["event"].set()

    def remove(self, peer_id):
        with self.lock:
            self._purge_identifiers(peer_id)
        channel = self.connections.pop(peer_id, None)
        if channel:
            try:
                channel.send({"type": "close", "reason": "unpaired"})
            except Exception:  # noqa: S110 - Local removal must survive a failed close frame.
                pass
            try:
                channel.sock.close()
            except OSError:
                pass
        self.store.peers = [peer for peer in self.store.peers
                            if peer.get("device_id") != peer_id]
        self.store.save_peers()
        with sqlite3.connect(self.store.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            for table in ("outbox", "inbox", "dedupe", "personal_batch", "personal_domain",
                          "personal_attachment_chunk", "personal_attachment_transfer"):
                db.execute("DELETE FROM %s WHERE peer_id=?" % table, (peer_id,))
            db.execute("DELETE FROM command_effect WHERE peer_id=? OR peer_id=''", (peer_id,))
            db.execute("DELETE FROM meta WHERE key=?", ("device_status:" + peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("status_request:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_run:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_applied:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_report:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key LIKE ?", ("personal_local_index:%s:%%" % peer_id,))
            db.execute("DELETE FROM meta WHERE key=?", ("personal_active_auto:" + peer_id,))
        self.connection_transports.pop(peer_id, None)
        self.connection_errors.pop(peer_id, None)
        self.status_requests.pop(peer_id, None)
        self._purge_identifiers(peer_id)
        self.incoming_calls.pop(peer_id, None)
        self.incoming_call_channels.pop(peer_id, None)
        self.wifi_missing_since.pop(peer_id, None)
        self.bluetooth_retry_at.pop(peer_id, None)
        if not self.store.peers:
            setup = getattr(self, "setup_pairing", None)
            if setup:
                setup["timer"].cancel()
                self.setup_pairing = None
        self._ensure_pairing_available()
        self._publish()
        self.callback("status", self.report())

    def _ensure_pairing_available(self):
        if self.enabled and self.server and not self.store.peers and not self.pairing_token:
            self.pairing_token = os.urandom(16)
            self.pairing_until = float("inf")

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

    def request_status(self, peer_id, include_identifiers=True, request_id=None):
        if type(include_identifiers) is not bool:
            raise ValueError("invalid identifier request")
        if request_id is not None and not valid_uuid(request_id, 4):
            raise ValueError("invalid identifier request")
        peer = self.store.peer(peer_id)
        if not peer or peer.get("state") != "paired":
            raise RuntimeError("Das Telefon ist nicht gekoppelt.")
        capability = (peer.get("capabilities") or {}).get("items", {}).get("device_status", {})
        versions = capability.get("versions", [])
        if (not capability.get("available") or 1 not in versions
                or not peer.get("grants", {}).get("grants", {}).get("device_status")):
            raise RuntimeError("Der Gerätestatus ist nicht freigegeben oder nicht verfügbar.")
        request_id = request_id if request_id is not None else str(uuid.uuid4())
        body = {"request_id": request_id}
        with self.lock:
            channel = self.connections.get(peer_id)
            if channel and self._identifiers_allowed(peer):
                self._purge_identifiers(peer_id)
                body.update(version=4, include_identifiers=include_identifiers)
                created = now_ms()
                self.identifier_requests[peer_id] = (request_id, channel, peer["static_public"], time.monotonic() + 60, include_identifiers)
                try:
                    channel.send({"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
                        "kind": "device_status.request", "created_ms": created, "expires_ms": created + 60000, "body": body})
                except Exception:
                    self._purge_identifiers(peer_id)
                    raise
                return request_id
        if 3 in versions:
            body["version"] = 3
        elif 2 in versions:
            body["version"] = 2
        message = self.store.queue(peer_id, "device_status.request", body, 60000)
        self.store.register_status_request(peer_id, request_id, message["expires_ms"])
        self.status_requests.setdefault(peer_id, {})[request_id] = time.monotonic() + 60
        channel = self.connections.get(peer_id)
        if channel:
            self._send_message(channel, peer_id, message)
        return request_id

    def _identifiers_allowed(self, peer):
        current = self.store.sole_peer(peer["device_id"])
        personal = peer.get("personal_sync", {})
        cap = peer.get("capabilities", {}).get("items", {}).get("device_status", {})
        return (current is not None and current.get("static_public") == peer.get("static_public") and peer.get("state") == "paired"
                and personal.get("own_device") is True and personal.get("remote_own_device") is True
                and cap.get("available") is True and 4 in cap.get("versions", [])
                and peer.get("grants", {}).get("grants", {}).get("device_status") is True
                and peer.get("local_grants", desktop_grants()).get("grants", {}).get("device_status") is True)

    def _purge_identifiers(self, peer_id):
        self.identifier_requests.pop(peer_id, None)
        self.transient_identifiers.pop(peer_id, None)

    def current_identifier_event(self, payload):
        with self.lock:
            peer_id = payload.get("device_id", "")
            peer = self.store.peer(peer_id)
            current = self.transient_identifiers.get(peer_id)
            status = payload.get("status", {})
            if (not peer or not current or peer_id not in self.connections or not self._identifiers_allowed(peer)
                    or current[1] <= now_ms() or current[5] <= time.monotonic() or current[3] != peer["static_public"]
                    or current[4] is not self.connections.get(peer_id)):
                self.transient_identifiers.pop(peer_id, None)
                return dict(payload, status=without_device_identifiers(status))
            if current[1] != status.get("identifiers_expires_ms") or current[2] != status.get("request_id"):
                return dict(payload, status=without_device_identifiers(status))
            return dict(payload, status=dict(status, identifiers=current[0]))

    def _receive_identifiers(self, peer, channel, payload):
        with self.lock:
            peer_id = peer["device_id"]
            current = self.store.peer(peer_id)
            request = self.identifier_requests.get(peer_id)
            error = "not_granted"
            try:
                report = validate_device_status(payload["body"])
                if (not current or current["static_public"] != peer["static_public"] or not self._identifiers_allowed(current)
                        or not request or request[:3] != (report["request_id"], channel, peer["static_public"])
                        or self.connections.get(peer_id) is not channel):
                    raise PermissionError
                error = "expired"
                if time.monotonic() >= request[3] or now_ms() >= payload["expires_ms"]:
                    raise PermissionError
                error = "invalid_schema"
                if payload["expires_ms"] - payload["created_ms"] > 60000 or report.get("version") != 4:
                    raise PermissionError
                if not request[4] and any(field["status"] != "not_shared" for field in report["identifiers"].values()):
                    raise PermissionError
                self.identifier_requests.pop(peer_id, None)
                expiry = min(payload["expires_ms"], now_ms() + 60000)
                self.transient_identifiers[peer_id] = (report["identifiers"], expiry, report["request_id"], peer["static_public"], channel,
                    time.monotonic() + max(0, expiry - now_ms()) / 1000)
                self.store.cache_status(peer_id, report)
                self.callback("device_status", {"device_id": peer_id, "display_name": peer["display_name"],
                    "status": dict(report, identifiers_expires_ms=expiry,
                        identifiers_peer_fingerprint=fingerprint(unb64(peer["static_public"], 32)))})
                channel.send({"type": "ack", "message_id": payload["message_id"], "status": "accepted", "error": "none"})
                return
            except ValueError:
                error = "invalid_schema"
            except PermissionError:
                pass
            # An old reply must not cancel a newer pending request or accepted result.
            if (request and isinstance(payload.get("body"), dict) and
                    request[:3] == (payload["body"].get("request_id"), channel, peer["static_public"])):
                self._purge_identifiers(peer_id)
            channel.send({"type": "ack", "message_id": payload["message_id"], "status": "rejected", "error": error})

    def set_grant(self, peer_id, name, enabled):
        if name not in {"selected_notifications_readonly", "incoming_call_state",
                        "incoming_call_number", "answer_call", "end_call",
                        "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync"}:
            raise ValueError("invalid desktop grant")
        peer = self.store.peer(peer_id)
        if not peer or peer.get("state") != "paired":
            raise RuntimeError("Das Telefon ist nicht gekoppelt.")
        grants = peer.setdefault("local_grants", desktop_grants())
        if grants["grants"][name] == bool(enabled):
            return
        with self.lock:
            self.call_action_tickets.clear()
        if name in {"personal_notes_sync", "personal_tasks_sync"} and not enabled:
            self.store.purge_personal_modules(peer_id, {
                "notes" if name == "personal_notes_sync" else "tasks"})
        if name == "personal_deletions_sync" and not enabled:
            self.store.purge_personal_deletion_wire(peer_id)
        grants["revision"] = self.store.next_revision("grants.update")
        grants["grants"][name] = bool(enabled)
        self.store.save_peers()
        message = self.store.queue(peer_id, "grants.update", grants, DAY_MS)
        channel = self.connections.get(peer_id)
        if channel:
            self._send_message(channel, peer_id, message)
        self.callback("status", self.report())

    def _custom_supported(self, peer):
        return (4 in desktop_capabilities()["items"]["personal_tasks_sync"]["versions"]
                and peer.get("capabilities", {}).get("items", {}).get("personal_tasks_sync", {}).get("available") is True
                and 4 in peer.get("capabilities", {}).get("items", {}).get("personal_tasks_sync", {}).get("versions", []))

    @staticmethod
    def _custom_settings(enabled, revision):
        value = {"format": 4, "scope": "custom", "enabled": enabled,
                 "revision": revision, "epoch": str(uuid.uuid4())}
        validate_custom_body("personal_sync.custom_settings", value)
        return value

    def _custom_allowed(self, peer_id, kind, body, outgoing=False):
        if peer_id in getattr(self, "custom_save_failed", set()):
            return False
        peer = self.store.sole_peer(peer_id)
        if not peer or not self._custom_supported(peer):
            return False
        custom = peer.get("custom_sync", {})
        if kind == "personal_sync.custom_settings":
            return not outgoing or body == custom.get("local")
        personal = peer.get("personal_sync", {})
        return custom_scope_allowed(custom.get("remote" if outgoing else "local"),
            custom.get("local" if outgoing else "remote"), [4], [4],
            personal.get("own_device"), personal.get("remote_own_device"),
            body.get("sender_epoch"), body.get("receiver_epoch"),
            body.get("sender_revision"), body.get("receiver_revision"))

    def _save_custom(self, peer, custom):
        previous = peer.get("custom_sync")
        recovering = peer["device_id"] in getattr(self, "custom_save_failed", set())
        peer["custom_sync"] = custom
        try:
            self.store.save_peers()
        except Exception:
            safe = dict(previous or {})
            for side in ("local", "remote"):
                if custom.get(side) and not custom[side]["enabled"]:
                    safe[side] = custom[side]
            peer["custom_sync"] = safe
            self.custom_save_failed = getattr(self, "custom_save_failed", set()) | {peer["device_id"]}
            raise
        if recovering and custom.get("local") and self._custom_supported(peer):
            self.store.remove_kind(peer["device_id"], "personal_sync.custom_settings")
            self.store.queue(peer["device_id"], "personal_sync.custom_settings", custom["local"], DAY_MS)
        self.custom_save_failed = getattr(self, "custom_save_failed", set()) - {peer["device_id"]}

    def _pause_custom(self, peer_id):
        with self.lock:
            peer = self.store.peer(peer_id)
            if not peer:
                return
            custom = dict(peer.get("custom_sync", {}))
            if custom.get("local"):
                custom["local"] = self._custom_settings(False, custom["local"]["revision"] + 1)
                self._save_custom(peer, custom)
                self.store.remove_kind(peer_id, "personal_sync.custom_batch")
                self.store.remove_kind(peer_id, "personal_sync.custom_settings")
                if self._custom_supported(peer):
                    self.store.queue(peer_id, "personal_sync.custom_settings", custom["local"], DAY_MS)

    def send_custom_sync(self, peer_id, kind, body):
        validate_custom_body(kind, body)
        with self.lock:
            peer = self.store.sole_peer(peer_id)
            if not peer or not self._custom_supported(peer) or kind == "personal_sync.custom_request":
                raise RuntimeError("Custom synchronization is not supported.")
            if kind == "personal_sync.custom_settings":
                custom = dict(peer.get("custom_sync", {}))
                changed = custom.get("local") != body
                custom["local"] = accept_custom_settings(custom.get("local"), body)
                self._save_custom(peer, custom)
                if changed or not body["enabled"]:
                    self.store.remove_kind(peer_id, "personal_sync.custom_batch")
                self.store.remove_kind(peer_id, kind)
            elif not self._custom_allowed(peer_id, kind, body, outgoing=True):
                raise RuntimeError("Custom synchronization is not permitted.")
            policy = "wifi_only" if body.get("trigger") == "auto_wifi" else "any"
            message = self.store.queue(peer_id, kind, body, DAY_MS, policy)
            channel = self.connections.get(peer_id)
            if channel:
                self._send_message(channel, peer_id, message)
        self.callback("status", self.report())
        return message["message_id"]

    def set_personal_sync(self, peer_id, own_device, auto_wifi=False):
        with self.lock:
            return self._set_personal_sync(peer_id, own_device, auto_wifi)

    def _set_personal_sync(self, peer_id, own_device, auto_wifi=False):
        peer = self.store.peer(peer_id)
        if not peer or peer.get("state") != "paired":
            raise RuntimeError("Das Telefon ist nicht gekoppelt.")
        if self.store.sole_peer(peer_id) is None:
            raise RuntimeError("Mehrere Magnolie-Notes-Telefone sind gespeichert. Entfernen Sie alle bis auf eines.")
        previous = peer.get("personal_sync", {})
        if own_device and not previous.get("own_device"):
            # Only a new own-phone confirmation gets the new default. Existing
            # installations wait for the GUI's explicit legacy preference migration.
            peer.setdefault("call_audio", {"prefer_pc": True})
        if not own_device:
            self._purge_identifiers(peer_id)
            self._pause_custom(peer_id)
            self.store.purge_personal(peer_id)
        peer["personal_sync"] = {"own_device": bool(own_device),
            "remote_own_device": previous.get("remote_own_device", False),
            "auto_wifi": bool(auto_wifi) if own_device else False,
            "last_report": previous.get("last_report", {})}
        self.store.save_peers()
        self.store.remove_kind(peer_id, "personal_sync.settings")
        self.store.queue(peer_id, "personal_sync.settings",
                         {"format": 1, "own_device": bool(own_device)}, DAY_MS)
        self.callback("status", self.report())

    def send_personal_sync(self, peer_id, kind, body, trigger="manual"):
        if kind in CUSTOM_KINDS:
            return self.send_custom_sync(peer_id, kind, body)
        if kind not in PERSONAL_DATA_KINDS:
            raise ValueError("invalid personal sync kind")
        body = dict(body)
        attachment_sources = body.pop("_attachment_sources", [])
        validate_personal_sync_body(kind, body)
        peer = self.store.peer(peer_id)
        needed = personal_sync_grants_needed(kind, body)
        local = (peer or {}).get("local_grants", {}).get("grants", {})
        remote = (peer or {}).get("grants", {}).get("grants", {})
        if not needed:
            needed = {name for name in ("personal_notes_sync", "personal_tasks_sync")
                      if local.get(name) and remote.get(name)}
        if (not peer or peer.get("state") != "paired"
                or self.store.sole_peer(peer_id) is None
                or not peer.get("personal_sync", {}).get("own_device")
                or not peer.get("personal_sync", {}).get("remote_own_device")
                or not needed or any(not local.get(name) or not remote.get(name) for name in needed)):
            raise RuntimeError("Persoenlicher Sync ist nicht beidseitig freigegeben.")
        format = body.get("format", 1)
        if format >= 2 and "personal_notes_sync" in needed and negotiated_personal_notes_format(peer) < 2:
            raise RuntimeError("Attachment-Format 2 wird von der Gegenstelle nicht unterstützt.")
        if format == 3 and any(not supports_personal_format(peer, name, 3) for name in needed):
            raise RuntimeError("Personal-Sync-Format 3 wurde nicht ausgehandelt.")
        if kind == "personal_sync.request":
            trigger = body["trigger"]
            if trigger == "auto_wifi" and self.store.active_auto_run(peer_id):
                raise RuntimeError("Ein automatischer Personal-Sync-Lauf ist bereits aktiv.")
            self.store.remember_personal_run(peer_id, body)
        else:
            run = self.store.personal_run(peer_id, body["run_id"])
            if kind in {"personal_sync.batch", "personal_sync.report"} and format != run.get("format", 1):
                raise ValueError("conflicting personal sync format")
            if run.get("trigger") not in {"manual", "auto_wifi"}:
                raise RuntimeError("Unbekannte Personal-Sync-Transportpolicy.")
            trigger = run["trigger"]
            if kind == "personal_sync.report" and body["trigger"] != trigger:
                raise RuntimeError("Widersprüchlicher Personal-Sync-Trigger.")
        ttl = 60 * 60 * 1000 if kind == "personal_sync.request" else DAY_MS
        policy = "wifi_only" if trigger == "auto_wifi" else "any"
        if attachment_sources:
            if kind != "personal_sync.batch" or body.get("format", 1) < 2:
                raise ValueError("attachment sources require format 2 batch")
            descriptors = {item["sha256"]: item for record in body["records"]
                           if record["kind"] == "note"
                           for item in record["value"]["attachments"]}
            if (not isinstance(attachment_sources, list) or len(attachment_sources) > MAX_ATTACHMENTS
                    or any(not isinstance(item, dict) or set(item) != {"sha256", "data"}
                           for item in attachment_sources)):
                raise ValueError("invalid attachment sources")
            seen = set()
            for source in attachment_sources:
                descriptor = descriptors.get(source["sha256"])
                if not descriptor or source["sha256"] in seen:
                    raise ValueError("attachment source is not in batch manifest")
                mime, raw = decode_attachment_data_url(source["data"])
                if (mime != descriptor["mime"] or len(raw) != descriptor["size"]
                        or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]):
                    raise ValueError("attachment source changed after snapshot")
                self.store.stage_outgoing_attachment(peer_id, body["run_id"], body["reply"],
                    body["records_hash"], descriptor["sha256"], mime, raw, policy,
                    now_ms() + DAY_MS, descriptor["attachment_id"])
                seen.add(source["sha256"])
        if kind == "personal_sync.report" and body.get("format", 1) >= 2 and self.store.has_outgoing_attachments(
                peer_id, body["run_id"]):
            self.store.hold_personal_report(peer_id, body)
            return ""
        message = (self.store.queue_deletion_decision(peer_id, body, ttl, policy)
                   if kind == "personal_sync.deletion_decision" else
                   self.store.queue(peer_id, kind, body, ttl, policy))
        if kind == "personal_sync.request" and trigger == "auto_wifi":
            self.store.set_active_auto_run(peer_id, body["run_id"])
        if kind == "personal_sync.report" and body["state"] in {
                "complete", "partial", "blocked", "failed"}:
            self.store.finish_auto_run(peer_id, body["run_id"])
        channel = self.connections.get(peer_id)
        current_transport = self.connection_transports.get(peer_id)
        if channel and (policy == "any" or current_transport == "wifi"):
            self._send_message(channel, peer_id, message)
        return message["message_id"]

    def send_personal_sync_run(self, peer_id, request, batches, sources, trigger="manual", report=None):
        """Validate and durably stage one complete attachment-capable direction."""
        validate_personal_sync_body("personal_sync.request", request)
        format = request["format"]
        if format not in (2, 3) or not isinstance(batches, list) or not batches:
            raise ValueError("invalid format 2 run")
        for body in batches:
            validate_personal_sync_body("personal_sync.batch", body)
        if report is not None:
            validate_personal_sync_body("personal_sync.report", report)
            if report["format"] != format or report["run_id"] != request["run_id"]:
                raise ValueError("inconsistent format 2 report")
        records = [record for body in batches for record in body["records"]]
        if (any(body["format"] != format or body["run_id"] != request["run_id"] or
                body["reply"] != batches[-1]["reply"] for body in batches)
                or [body["sequence"] for body in batches] != list(range(len(batches)))
                or not batches[-1]["last"] or any(body["last"] for body in batches[:-1])
                or len({body["records_hash"] for body in batches}) != 1
                or records_hash(records) != batches[-1]["records_hash"]):
            raise ValueError("inconsistent format 2 run")
        peer = self.store.peer(peer_id)
        local = (peer or {}).get("local_grants", {}).get("grants", {})
        remote = (peer or {}).get("grants", {}).get("grants", {})
        needed = personal_sync_grants_needed("personal_sync.request", request)
        if (not peer or peer.get("state") != "paired" or self.store.sole_peer(peer_id) is None
                or not peer.get("personal_sync", {}).get("own_device")
                or not peer.get("personal_sync", {}).get("remote_own_device")
                or any(not local.get(name) or not remote.get(name) for name in needed)
                or ("personal_notes_sync" in needed and negotiated_personal_notes_format(peer) < 2)
                or (format == 3 and any(not supports_personal_format(peer, name, 3)
                                       for name in needed))):
            raise RuntimeError("Persoenlicher Sync ist nicht beidseitig freigegeben.")
        descriptors = {item["sha256"]: item for record in records if record["kind"] == "note"
                       for item in record["value"]["attachments"]}
        if (not isinstance(sources, list) or len(sources) != len(descriptors)
                or any(not isinstance(item, dict) or set(item) != {"sha256", "data"} for item in sources)
                or {item["sha256"] for item in sources} != set(descriptors)):
            raise ValueError("incomplete attachment source set")
        decoded = []
        for source in sources:
            mime, raw = decode_attachment_data_url(source["data"])
            descriptor = descriptors[source["sha256"]]
            if mime != descriptor["mime"]:
                raise ValueError("attachment MIME changed after snapshot")
            decoded.append((descriptor, raw))
        trigger = request["trigger"]
        reply = batches[-1]["reply"]
        if trigger == "auto_wifi" and not reply and self.store.active_auto_run(peer_id):
            raise RuntimeError("Ein automatischer Personal-Sync-Lauf ist bereits aktiv.")
        if not reply:
            self.store.remember_personal_run(peer_id, request)
        elif self.store.personal_run(peer_id, request["run_id"]) != request:
            raise ValueError("conflicting personal sync reply")
        policy = "wifi_only" if trigger == "auto_wifi" else "any"
        messages = ([] if reply else [("personal_sync.request", request, 60 * 60 * 1000)]) + [
            ("personal_sync.batch", body, DAY_MS) for body in batches]
        queued = self.store.queue_format2_run(peer_id, messages, decoded, policy)
        if report is not None:
            if decoded:
                self.store.hold_personal_report(peer_id, report)
            else:
                self.send_personal_sync(peer_id, "personal_sync.report", report, trigger)
        if trigger == "auto_wifi" and not reply:
            self.store.set_active_auto_run(peer_id, request["run_id"])
        channel, transport = self.connections.get(peer_id), self.connection_transports.get(peer_id)
        if channel and (policy == "any" or transport == "wifi"):
            for message in queued:
                self._send_message(channel, peer_id, message)
        return queued[-1]["message_id"]

    def request_dial(self, peer_id, destination, client_ref):
        peer = self.store.peer(peer_id)
        eligible = []
        for candidate in self.store.peers:
            capability = (candidate.get("capabilities") or {}).get("items", {}).get(
                "dial_request", {})
            if (candidate.get("state") == "paired"
                    and candidate.get("device_id") in self.connections
                    and capability.get("available") and 1 in capability.get("versions", [])
                    and candidate.get("grants", {}).get("grants", {}).get("dial_request")):
                eligible.append(candidate.get("device_id"))
        if not peer or eligible != [peer_id]:
            raise RuntimeError("Genau ein online gekoppeltes Magnolie-Notes-Telefon muss das Wählen freigeben.")
        body = validate_dial_request({"to": destination, "client_ref": client_ref})
        if self.store.command_state(client_ref):
            raise RuntimeError("Dieser Wählauftrag wurde bereits eingereiht.")
        # Der explizite Wählauftrag erlaubt nur Status und Auflegen dieses ausgehenden Anrufs,
        # nicht das Annehmen eingehender Anrufe am Desktop.
        self.set_grant(peer_id, "incoming_call_state", True)
        self.set_grant(peer_id, "end_call", True)
        self.store.remember_command(peer_id, client_ref, "queued")
        message = self.store.queue(peer_id, "dial_request.command", body, 60000)
        self._send_message(self.connections[peer_id], peer_id, message)
        self.callback("dial_status", {"device_id": peer_id, "client_ref": client_ref,
                      "state": "queued", "error": "none", "occurred_ms": now_ms()})
        return client_ref

    def request_answer(self, peer_id, call_ref, command_ref):
        peer = self.store.peer(peer_id)
        capability = (peer or {}).get("capabilities", {}).get("items", {}).get(
            "answer_call", {})
        if (not peer or peer.get("state") != "paired" or peer_id not in self.connections or not capability.get("available")
                or 1 not in capability.get("versions", [])
                or not peer.get("grants", {}).get("grants", {}).get("answer_call")
                or not peer.get("local_grants", {}).get("grants", {}).get("answer_call")):
            raise RuntimeError("Das Annehmen von Anrufen ist nicht freigegeben oder nicht verfügbar.")
        current = self.incoming_calls.get(peer_id, {})
        if (current.get("call_ref") != call_ref or current.get("state") != "ringing"
                or current.get("direction") != "incoming"):
            raise RuntimeError("Der Anruf klingelt nicht mehr oder ist veraltet.")
        body = validate_answer_command({"command_ref": command_ref, "call_ref": call_ref,
                                        "expected_state": "ringing"})
        if self.store.command_state(command_ref):
            raise RuntimeError("Dieser Annehmauftrag wurde bereits eingereiht.")
        self.store.remember_command(peer_id, command_ref, "queued")
        message = self.store.queue(peer_id, "answer_call.command", body, 10000)
        self._send_message(self.connections[peer_id], peer_id, message)
        return command_ref

    def request_end_call(self, peer_id, call_ref, revision, command_ref):
        peer = self.store.peer(peer_id)
        capability = (peer or {}).get("capabilities", {}).get("items", {}).get("end_call", {})
        if (not peer or peer.get("state") != "paired" or peer_id not in self.connections or not capability.get("available")
                or 1 not in capability.get("versions", [])
                or not peer.get("grants", {}).get("grants", {}).get("end_call")
                or not peer.get("local_grants", {}).get("grants", {}).get("end_call")):
            raise RuntimeError("Das Beenden von Anrufen ist nicht freigegeben oder nicht verfügbar.")
        current = self.incoming_calls.get(peer_id, {})
        rejecting = current.get("state") == "ringing" and current.get("direction") == "incoming"
        if (current.get("call_ref") != call_ref or (current.get("state") != "offhook" and not rejecting)
                or rejecting and 2 not in capability.get("versions", [])
                or rejecting and not peer.get("local_grants", {}).get("grants", {}).get("answer_call")
                or current.get("revision") != revision):
            raise RuntimeError("Der Anruf ist nicht mehr aktiv oder wurde aktualisiert.")
        body = validate_end_command({"command_ref": command_ref, "call_ref": call_ref,
            "expected_revision": revision, "expected_state": current["state"]})
        if self.store.command_state(command_ref):
            raise RuntimeError("Dieser Auflegeauftrag wurde bereits eingereiht.")
        self.store.remember_command(peer_id, command_ref, "queued")
        message = self.store.queue(peer_id, "end_call.command", body, 10000)
        self._send_message(self.connections[peer_id], peer_id, message)
        return command_ref

    def call_event_current(self, peer_id, call_ref, revision, state):
        with self.lock:
            current = self.incoming_calls.get(peer_id, {})
            return bool(peer_id in self.connections
                and self.incoming_call_channels.get(peer_id) is self.connections[peer_id]
                and current.get("call_ref") == call_ref and current.get("revision") == revision
                and current.get("state") == state)

    def call_is_current(self, peer_id, call_ref, revision):
        with self.lock:
            peer = self.store.peer(peer_id) or {}
            current = self.incoming_calls.get(peer_id, {})
            capability = peer.get("capabilities", {}).get("items", {}).get("incoming_call_state", {})
            return bool(peer.get("state") == "paired" and peer_id in self.connections
                and self.call_event_current(peer_id, call_ref, revision, "ringing")
                and 0 <= now_ms() - current.get("occurred_ms", 0) <= 60000
                and current.get("call_ref") == call_ref and current.get("revision") == revision
                and current.get("state") == "ringing" and current.get("direction") == "incoming"
                and peer.get("local_grants", {}).get("grants", {}).get("incoming_call_state")
                and peer.get("grants", {}).get("grants", {}).get("incoming_call_state")
                and capability.get("available") and 2 in capability.get("versions", []))

    def call_action_tokens(self, peer_id, call_ref, revision):
        """Ephemeral capabilities, never phone numbers or durable launch requests."""
        with self.lock:
            now = time.monotonic()
            self.call_action_tickets = {key: value for key, value in self.call_action_tickets.items()
                                        if value[-1] > now}
            peer = self.store.peer(peer_id) or {}
            current = self.incoming_calls.get(peer_id, {})
            local = peer.get("local_grants", {}).get("grants", {})
            remote = peer.get("grants", {}).get("grants", {})
            if (peer.get("state") != "paired" or peer_id not in self.connections
                    or not self.call_is_current(peer_id, call_ref, revision)
                    or not peer.get("static_public") or current.get("call_ref") != call_ref
                    or current.get("revision") != revision or current.get("direction") != "incoming"
                    or current.get("state") != "ringing" or not local.get("incoming_call_state")
                    or not remote.get("incoming_call_state") or not local.get("answer_call")):
                return {}
            result = {}
            for action, capability, version in (("answer", "answer_call", 1), ("reject", "end_call", 2)):
                item = peer.get("capabilities", {}).get("items", {}).get(capability, {})
                if not (local.get(capability) and remote.get(capability) and item.get("available")
                        and version in item.get("versions", [])):
                    continue
                token = os.urandom(32).hex()
                self.call_action_tickets[token] = (peer_id, peer["static_public"],
                    self.connections[peer_id], call_ref, revision, action, now + 60)
                result[action] = token
            while len(self.call_action_tickets) > 64:
                self.call_action_tickets.pop(next(iter(self.call_action_tickets)))
            return result

    def call_action(self, token):
        with self.lock:
            item = self.call_action_tickets.pop(token, None) if isinstance(token, str) else None
            if item is None:
                return False
            peer_id, identity, connection, call_ref, revision, action, expires = item
            peer = self.store.peer(peer_id) or {}
            current = self.incoming_calls.get(peer_id, {})
            if (time.monotonic() >= expires or peer.get("static_public") != identity
                    or self.connections.get(peer_id) is not connection
                    or current.get("revision") != revision
                    or not self.call_action_tokens(peer_id, call_ref, revision).get(action)):
                return False
            # Consume sibling actions too: one alert cannot both answer and reject.
            self.call_action_tickets = {key: value for key, value in self.call_action_tickets.items()
                if (value[0], value[3]) != (peer_id, call_ref)}
            command_ref = str(uuid.uuid4())
            if action == "answer":
                self.request_answer(peer_id, call_ref, command_ref)
            else:
                self.request_end_call(peer_id, call_ref, revision, command_ref)
            return True

    def _send_message(self, channel, peer_id, message):
        policy = self.store.outbox_policy(peer_id, message.get("message_id", ""))
        if policy == "invalid" or policy == "wifi_only" and self.connection_transports.get(peer_id) != "wifi":
            return False
        if message.get("kind") in CUSTOM_KINDS:
            with self.lock:
                if message["kind"] == "personal_sync.custom_batch" and (
                        not self.personal_sync_available() or self.store.has_kind(peer_id, "personal_sync.custom_settings")):
                    return False
                if not self._custom_allowed(peer_id, message["kind"], message["body"], outgoing=True):
                    self.store.acknowledge(peer_id, message["message_id"])
                    return False
                channel.send(message)
                self.store.mark_attempt(peer_id, message["message_id"])
                return True
        if (message.get("kind", "").startswith("personal_sync.")
                and message.get("kind") != "personal_sync.settings"
                and not self.personal_sync_available()):
            return False
        if message.get("kind", "").startswith("personal_sync.") and message["kind"] != "personal_sync.settings":
            peer = self.store.peer(peer_id) or {}
            personal = peer.get("personal_sync", {})
            local = peer.get("local_grants", {}).get("grants", {})
            remote = peer.get("grants", {}).get("grants", {})
            body = message.get("body", {})
            needed = personal_sync_grants_needed(message["kind"], body)
            if not needed:
                needed = {name for name in ("personal_notes_sync", "personal_tasks_sync")
                          if local.get(name) and remote.get(name)}
            if (self.store.sole_peer(peer_id) is None or not personal.get("own_device")
                    or not personal.get("remote_own_device")
                    or not needed or any(not local.get(name) or not remote.get(name) for name in needed)):
                self.store.acknowledge(peer_id, message["message_id"])
                return False
        channel.send(message)
        self.store.mark_attempt(peer_id, message["message_id"])
        return True

    def commit_personal_sync(self, peer_id, message_id, token, success):
        if not success:
            if (not self.store.has_personal_batch(peer_id, message_id, token)
                    and not any(item[1]["pending_message_id"] == message_id and
                                item[1]["commit_token"] == token
                                for item in self.store.ready_personal_domains())):
                return False
            with self.lock:
                event = self.personal_commit_events.get(token)
            if event:
                event.set()
            return True
        if self.store.commit_personal_domain(peer_id, message_id, token):
            with self.lock:
                event = self.personal_commit_events.get(token)
                self.personal_dispatched.discard(token)
            if event:
                event.set()
            return True
        attachment_results = self.store.completed_incoming_for_batch(peer_id, message_id, token)
        committed_peer, message_ids = self.store.commit_personal_batch(peer_id, message_id, token)
        if committed_peer != peer_id:
            raise ValueError("invalid personal commit peer")
        with self.lock:
            event = self.personal_commit_events.get(token)
            self.personal_dispatched.discard(token)
        if event and message_ids:
            event.set()
        if message_ids:
            for run_id, reply, aggregate_hash, digest in attachment_results:
                run = self.store.personal_run(peer_id, run_id)
                self.send_personal_sync(peer_id, "personal_sync.attachment_result", {
                    "format": 2, "run_id": run_id, "reply": reply,
                    "records_hash": aggregate_hash, "sha256": digest,
                    "state": "complete", "error": "none"}, run.get("trigger", "manual"))
        return bool(message_ids)

    def replay_personal_sync(self):
        for peer_id, payload in self.store.ready_personal_domains():
            if self.store.sole_peer(peer_id) is None or payload["commit_token"] in self.personal_dispatched:
                continue
            self.personal_dispatched.add(payload["commit_token"])
            payload["transport"] = "wifi"
            self.callback("personal_sync", payload)
        for peer_id, aggregate in self.store.ready_personal_batches():
            if self.store.sole_peer(peer_id) is None:
                continue
            token = aggregate.pop("commit_token")
            if token in self.personal_dispatched:
                continue
            message_id = aggregate.pop("message_id")
            run = self.store.personal_run(peer_id, aggregate["run_id"])
            format = aggregate["messages"][-1]["body"].get("format", 1)
            if format >= 2 and not self._prepare_format2_aggregate(peer_id, aggregate, "wifi"):
                continue
            self.personal_dispatched.add(token)
            aggregate.pop("messages")
            self.callback("personal_sync", {"device_id": peer_id, "transport": "wifi",
                "kind": "personal_sync.batch", "commit_token": token,
                "pending_message_id": message_id, "body": {
                    "format": format, "run_id": aggregate["run_id"], "batch_id": str(uuid.uuid4()),
                    "sequence": 0, "last": True, "reply": aggregate["reply"],
                    "records": aggregate["records"], "requested_modules": run.get("modules", []),
                    "trigger": run.get("trigger", "manual"),
                    "attachment_data": aggregate.get("attachment_data", {})}})

    def _prepare_format2_aggregate(self, peer_id, aggregate, transport):
        messages = aggregate.get("messages", [])
        body = messages[-1]["body"] if messages else {}
        if body.get("format", 1) < 2:
            return True
        run = self.store.personal_run(peer_id, aggregate["run_id"])
        policy = "wifi_only" if run.get("trigger") == "auto_wifi" else "any"
        reply, digest = aggregate["reply"], body["records_hash"]
        descriptors = {item["sha256"]: item for record in aggregate["records"]
                       if record["kind"] == "note" for item in record["value"]["attachments"]}
        if len(descriptors) > 256 or sum(item["size"] for item in descriptors.values()) > 50 * 1024 * 1024:
            raise ValueError("attachment run too large")
        for item in descriptors.values():
            self.store.register_incoming_attachment(peer_id, aggregate["run_id"], reply, digest,
                item["sha256"], item["size"], item["mime"], policy, now_ms() + DAY_MS,
                item["attachment_id"])
            if self.store.attachment_missing_ranges(peer_id, aggregate["run_id"], reply, digest, item["sha256"]):
                self.store.reuse_staged_attachment(peer_id, aggregate["run_id"], reply, digest,
                    item, policy, now_ms() + DAY_MS)
        if any(self.store.attachment_missing_ranges(peer_id, aggregate["run_id"], reply, digest, key)
               for key in descriptors) and self.store.begin_local_attachment_index(
                   peer_id, aggregate["run_id"], reply):
            self.callback("personal_sync_attachment_index", {"device_id": peer_id,
                "run_id": aggregate["run_id"], "reply": reply, "records_hash": digest})
            return False
        wants = [{"sha256": key, "ranges": ranges} for key in sorted(descriptors)
                 if (ranges := self.store.attachment_missing_ranges(peer_id, aggregate["run_id"], reply, digest, key))]
        if wants:
            self.callback("personal_sync_progress", {"device_id": peer_id,
                "declared": len(descriptors), "received": len(descriptors) - len(wants),
                "bytes": sum(item["size"] for key, item in descriptors.items()
                             if key not in {want["sha256"] for want in wants})})
            request = {"format": 2, "run_id": aggregate["run_id"], "reply": reply,
                       "records_hash": digest, "wants": wants}
            self.store.remove_kind(peer_id, "personal_sync.attachment_request")
            message = self.store.queue(peer_id, "personal_sync.attachment_request", request, DAY_MS, policy)
            channel = self.connections.get(peer_id)
            if channel and (policy == "any" or transport == "wifi"):
                self._send_message(channel, peer_id, message)
            return False
        attachment_data = {}
        for key, item in descriptors.items():
            sink = io.BytesIO()
            if not self.store.verify_incoming_attachment(peer_id, aggregate["run_id"], reply, digest, key, sink):
                raise ValueError("invalid attachment content")
            attachment_data[key] = "data:%s;base64,%s" % (item["mime"], base64.b64encode(sink.getvalue()).decode("ascii"))
        aggregate["attachment_data"] = attachment_data
        return True

    def index_local_attachments(self, peer_id, run_id, reply, aggregate_hash, sources):
        if not isinstance(sources, list) or len(sources) > 256:
            raise ValueError("invalid local attachment index")
        run = self.store.personal_run(peer_id, run_id)
        peer = self.store.peer(peer_id)
        local = (peer or {}).get("local_grants", {}).get("grants", {})
        remote = (peer or {}).get("grants", {}).get("grants", {})
        needed = {"personal_notes_sync"}
        if (not peer or peer.get("state") != "paired" or self.store.sole_peer(peer_id) is None
                or not peer.get("personal_sync", {}).get("own_device")
                or not peer.get("personal_sync", {}).get("remote_own_device")
                or any(not local.get(name) or not remote.get(name) for name in needed)):
            raise PermissionError("personal sync revoked")
        policy = "wifi_only" if run.get("trigger") == "auto_wifi" else "any"
        with sqlite3.connect(self.store.database_path) as db:
            manifests = {row[0]: (row[1], row[2]) for row in db.execute(
                "SELECT sha256,size,mime FROM personal_attachment_transfer WHERE peer_id=? AND run_id=? "
                "AND reply=? AND records_hash=? AND direction='incoming'",
                (peer_id, run_id, int(reply), aggregate_hash))}
        seen = set()
        for source in sources:
            if (not isinstance(source, dict) or set(source) != {"sha256", "data"}
                    or source["sha256"] in seen):
                raise ValueError("invalid local attachment index")
            seen.add(source["sha256"])
            expected = manifests.get(source["sha256"])
            if not expected:
                continue
            mime, raw = decode_attachment_data_url(source["data"])
            if len(raw) != expected[0] or mime != expected[1] or hashlib.sha256(raw).hexdigest() != source["sha256"]:
                continue
            for index, offset in enumerate(range(0, len(raw), CHUNK_RAW)):
                self.store.stage_incoming_attachment(peer_id, run_id, reply, aggregate_hash,
                    source["sha256"], len(raw), mime, index, raw[offset:offset + CHUNK_RAW], policy,
                    now_ms() + DAY_MS, source["sha256"])
        self.replay_personal_sync()

    def _ensure_desktop_updates(self, peer_id, revisions=None):
        revisions = revisions or {}
        available, reason = self.bluetooth_backend.availability()
        capabilities = lambda revision: desktop_capabilities(revision, available, reason)
        peer = self.store.peer(peer_id)
        grants = lambda revision: dict(peer["local_grants"], revision=revision)
        for kind, factory in (("capabilities.update", capabilities),
                              ("grants.update", grants)):
            self.store.remove_kind(peer_id, kind)
            revision = revisions[kind] if kind in revisions else self.store.next_revision(kind)
            body = factory(revision)
            self.store.queue(peer_id, kind, body, DAY_MS)
        with self.lock:
            custom = peer.get("custom_sync", {})
            self.store.remove_kind(peer_id, "personal_sync.settings")
            self.store.queue(peer_id, "personal_sync.settings", {
                "format": 1, "own_device": bool(peer.get("personal_sync", {}).get("own_device"))}, DAY_MS)
            if self._custom_supported(peer) and custom.get("local"):
                self.store.remove_kind(peer_id, "personal_sync.custom_settings")
                self.store.queue(peer_id, "personal_sync.custom_settings", custom["local"], DAY_MS)

    def _accept(self):
        listener, stopped = self.server, self.stop_event
        while not stopped.is_set() and listener:
            try:
                client, address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            ip = address[0]
            with self.lock:
                if stopped.is_set():
                    client.close()
                    break
                if sum(self.active_by_ip.values()) >= 8 or self.active_by_ip.get(ip, 0) >= 2:
                    client.close()
                    continue
                self.active_by_ip[ip] = self.active_by_ip.get(ip, 0) + 1
                if not self._start_handler(client, ip, "wifi"):
                    count = self.active_by_ip[ip] - 1
                    if count: self.active_by_ip[ip] = count
                    else: self.active_by_ip.pop(ip, None)

    def _claim_pairing_attempt(self):
        with self.lock:
            if self.pairing_attempt_active:
                return False
            self.pairing_attempt_active = True
            return True

    def _release_pairing_attempt(self):
        with self.lock:
            self.pairing_attempt_active = False

    def _handle(self, sock, ip, transport="wifi", generation=None):
        worker = threading.current_thread()
        with self.lock:
            self._workers.add(worker)
            self._sockets.add(sock)
            current_generation = generation is None or generation == self._generation
        try:
            if self.stop_event.is_set() or not current_generation:
                return
            sock.settimeout(10)
            first = receive_frame(sock, PAIR_FRAME_MAX)
            if first.get("p") != PROTOCOL:
                raise ValueError("wrong protocol")
            if first.get("type") == "pair_init":
                if not self._claim_pairing_attempt():
                    raise ValueError("pairing attempt already active")
                try:
                    self._pair(sock, first, ip)
                finally:
                    self._release_pairing_attempt()
            elif first.get("type") == "pair_finish":
                self._finish_pending(sock, first)
            elif first.get("type") == "session_start":
                expected_peer = ip.removeprefix("bluetooth:") if transport == "bluetooth" else None
                self._session(sock, first, transport, expected_peer)
            else:
                raise ValueError("unexpected first frame")
        except Exception:  # noqa: S110 - Invalid unauthenticated connections are dropped.
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
            if transport == "wifi" and current_generation:
                with self.lock:
                    count = self.active_by_ip.get(ip, 1) - 1
                    if count:
                        self.active_by_ip[ip] = count
                    else:
                        self.active_by_ip.pop(ip, None)
            with self.lock:
                self._sockets.discard(sock)
                self._workers.discard(worker)

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

    def _pair(self, sock, pair_init, source=None):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        self._validate_pair_init(pair_init)
        setup = getattr(self, "setup_pairing", None)
        if setup:
            if not setup["address"].startswith("bluetooth:"):
                import ipaddress
                address = ipaddress.ip_address(source)
                source = str(getattr(address, "ipv4_mapped", None) or address)
            with self.lock:
                if setup["target"] != pair_init["device_id"] or setup["address"] != source:
                    raise ValueError("wrong setup target")
                setup["socket"] = sock
        if (not self.pairing_token or time.monotonic() >= self.pairing_until
                or not hmac.compare_digest(unb64(pair_init["pairing_token"], 16),
                                           self.pairing_token)):
            raise ValueError("pairing window closed")
        if self.store.peers:
            raise ValueError("phone binding already exists")
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
        try:
            sock.settimeout(120)
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
            sock.settimeout(10)
            expires = now_ms() + PAIR_COMMIT_MS
            peer = {}
            peer.update({"device_id": pair_init["device_id"],
                         "display_name": pair_init["display_name"],
                         "static_public": pair_init["static_public"],
                          "state": "pair_commit_pending", "grants": {"revision": 0, "grants": {name: False for name in GRANT_NAMES}},
                         "local_grants": desktop_grants(),
                         "capabilities": {}, "last_contact_ms": 0,
                          "bluetooth": {"enabled": bool(setup and setup["address"].startswith("bluetooth:")),
                                        "address": setup["address"][10:] if setup and setup["address"].startswith("bluetooth:") else ""},
                         "personal_sync": {"own_device": False, "remote_own_device": False,
                                           "auto_wifi": False,
                                           "last_report": {}},
                         "pending_transcript": b64(transcript),
                         "pending_phone_finish_proof": b64(proof(
                             key, b"magnolie-phone-pair-v1/finish\0", "phone", transcript)),
                         "pending_desktop_finish_proof": b64(proof(
                             key, b"magnolie-phone-pair-v1/finish\0", "desktop", transcript)),
                         "pending_expires_ms": expires})
            with self.lock:
                if setup and (self.setup_pairing is not setup or time.monotonic() >= self.pairing_until):
                    raise ValueError("setup invitation expired")
                self.store.peers.append(peer)
                self.store.save_peers()
            send_frame(sock, {"p": PROTOCOL, "type": "pair_confirm", "side": "desktop",
                "transcript": b64(transcript), "proof": b64(proof(
                    key, b"magnolie-phone-pair-v1/confirm\0", "desktop", transcript))})
            phone_finish = receive_frame(sock, PAIR_FRAME_MAX)
            self._commit_pending(sock, peer, phone_finish)
        finally:
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
        activated = False
        remote_unpaired = False
        try:
            self._ensure_desktop_updates(peer_id, {
                "capabilities.update": capability_revision, "grants.update": grant_revision})
            control_ids = {message["message_id"] for message in self.store.pending(peer_id, transport)
                           if message["kind"] in {"capabilities.update", "grants.update"}}
            for message in self.store.pending(peer_id, transport):
                self._send_message(channel, peer_id, message)
            sock.settimeout(10)
            deadline = time.monotonic() + 10
            while control_ids and time.monotonic() < deadline:
                payload = channel.receive()
                if payload.get("type") == "ack":
                    message_id = payload.get("message_id")
                    self._payload(peer, channel, payload)
                    if message_id in control_ids:
                        if payload.get("status") not in {"accepted", "duplicate"}:
                            self.connection_errors[peer_id] = "protocol_mismatch"
                            raise ValueError("desktop control update rejected")
                        control_ids.remove(message_id)
                else:
                    self._payload(peer, channel, payload)
            if control_ids:
                raise TimeoutError("desktop control update acknowledgement timeout")
            self._activate_connection(peer_id, channel, transport)
            activated = True
            self.connection_errors.pop(peer_id, None)
            peer["last_contact_ms"] = int(time.time() * 1000)
            self.store.save_peers()
            self.callback("status", self.report())
            sock.settimeout(1)
            last_incoming = time.monotonic()
            while self.enabled and not self.stop_event.is_set():
                try:
                    payload = channel.receive()
                    last_incoming = time.monotonic()
                    if payload.get("type") == "close" and set(payload) == {"type", "reason"}:
                        if payload["reason"] not in {"normal", "shutdown", "better_transport",
                                                     "unpaired", "protocol_upgrade"}:
                            raise ValueError("invalid close reason")
                        remote_unpaired = payload["reason"] == "unpaired"
                        break
                    self._payload(peer, channel, payload)
                except socket.timeout:
                    now = time.monotonic()
                    if now - last_incoming >= 75:
                        raise TimeoutError("phone heartbeat timeout") from None
                    if now - channel.last_send >= 25:
                        channel.send({"type": "ping", "ping_id": str(uuid.uuid4()),
                                      "sent_ms": now_ms()})
                    for message in self.store.pending(peer["device_id"], transport):
                        self._send_message(channel, peer["device_id"], message)
        finally:
            if activated and self.connections.get(peer_id) is channel:
                self._purge_identifiers(peer_id)
                self.connections.pop(peer_id, None)
                self.connection_transports.pop(peer_id, None)
            try:
                sock.close()
            except OSError:
                pass
            if remote_unpaired:
                self.remove(peer_id)
            else:
                self.callback("status", self.report())

    def _activate_connection(self, peer_id, channel, transport):
        with self.lock:
            if self.stop_event.is_set():
                raise OSError("phone service stopped")
            current = self.connections.get(peer_id)
            current_transport = self.connection_transports.get(peer_id)
            if transport == "bluetooth" and current_transport == "wifi":
                channel.send({"type": "close", "reason": "better_transport"})
                raise OSError("WLAN is already active")
            self._purge_identifiers(peer_id)
            # A fresh authenticated session must observe its own current call.
            # Retained ringing state must not mint tickets for the new transport.
            pending_call = self.incoming_calls.get(peer_id) if self.incoming_call_channels.get(peer_id) is channel else None
            if pending_call is None:
                self.incoming_calls.pop(peer_id, None)
                self.incoming_call_channels.pop(peer_id, None)
            self.call_action_tickets = {key: value for key, value in self.call_action_tickets.items()
                if value[0] != peer_id}
            self.connections[peer_id] = channel
            self.connection_transports[peer_id] = transport
        if current and current is not channel:
            try:
                current.send({"type": "close", "reason": "better_transport"})
            except Exception:  # noqa: S110 - Transport replacement continues after send failure.
                pass
            try:
                current.sock.close()
            except OSError:
                pass

        # A call can arrive during the authenticated control-message handshake.
        # Re-present only that exact channel's observation once it is activated.
        if pending_call is not None:
            peer = self.store.peer(peer_id) or {}
            self.callback("incoming_call", enrich_call(dict(pending_call,
                device_id=peer_id, display_name=peer.get("display_name", ""))))

    def _close_connection(self, peer_id, reason):
        self._purge_identifiers(peer_id)
        channel = self.connections.get(peer_id)
        if not channel:
            return
        try:
            channel.send({"type": "close", "reason": reason})
        except Exception:  # noqa: S110 - Closing a failed transport is best effort.
            pass
        try:
            channel.sock.close()
        except OSError:
            pass

    def _bluetooth_loop(self):
        while self.enabled and not self.stop_event.wait(1):
            self._bluetooth_tick()

    def _bluetooth_tick(self, now=None):
        if self.pairing_attempt_active:
            return
        now = time.monotonic() if now is None else now
        for peer in list(self.store.peers):
            peer_id = peer["device_id"]
            if peer.get("state") == "pair_commit_pending" and peer.get("pending_expires_ms", 0) <= now_ms():
                continue
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
                sock = self.bluetooth_backend.connect(config["address"], BLUETOOTH_UUID, self.stop_event)
                sock.settimeout(10)
                if self.stop_event.is_set() or not self.enabled:
                    sock.close()
                    continue
            except Exception:  # noqa: S112 - Bluetooth fallback retries after its backoff.
                continue
            self._start_handler(sock, "bluetooth:" + peer_id, "bluetooth")

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
            ack_policy = self.store.outbox_policy(peer["device_id"], payload["message_id"])
            if ack_policy == "expired":
                raise ValueError("acknowledgement for expired message or run")
            if (ack_policy == "invalid" or ack_policy == "wifi_only"
                    and self.connection_transports.get(peer["device_id"]) != "wifi"):
                raise ValueError("wifi-only acknowledgement received on bluetooth")
            if payload["status"] == "rejected" and payload["error"] == "temporary_failure":
                return
            decision_id = self.store.acknowledge(peer["device_id"], payload["message_id"],
                (lambda body: self.callback("personal_custom_ack", {"device_id": peer["device_id"], "body": body}))
                if payload["status"] in {"accepted", "duplicate"} else None)
            if decision_id and payload["status"] in {"accepted", "duplicate"}:
                self.callback("personal_decision_accepted", {"device_id": peer["device_id"],
                              "decision_id": decision_id})
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
        kind = payload["kind"]
        if kind in CUSTOM_KINDS:
            status, error = "accepted", "none"
            try:
                validate_custom_body(kind, payload["body"])
                if payload["expires_ms"] <= received or payload["expires_ms"] - payload["created_ms"] > DAY_MS:
                    raise ValueError("expired custom message")
                with self.lock:
                    current = self.store.sole_peer(peer["device_id"])
                    if not current or not self._custom_supported(current):
                        raise PermissionError
                    value = payload["body"]
                    if self.store.dedupe_result(peer["device_id"], payload["message_id"]) and not self.store.received_matches(peer["device_id"], payload):
                        raise ValueError("conflicting custom message identity")
                    if kind == "personal_sync.custom_settings":
                        custom = dict(current.get("custom_sync", {}))
                        changed = custom.get("remote") != value
                        custom["remote"] = accept_custom_settings(custom.get("remote"), value)
                        self._save_custom(current, custom)
                        if changed:
                            self.store.remove_kind(peer["device_id"], "personal_sync.custom_batch")
                        if not custom.get("local"):
                            self.send_custom_sync(peer["device_id"], kind, self._custom_settings(False, 1))
                    elif kind == "personal_sync.custom_request" and self._custom_allowed(peer["device_id"], kind, value):
                        if value["trigger"] == "auto_wifi" and self.connection_transports.get(peer["device_id"]) != "wifi":
                            raise PermissionError
                        self.callback("personal_custom_request", {"device_id": peer["device_id"], "trigger": value["trigger"]})
                    else:
                        raise PermissionError
                    self.store.remember_message(peer["device_id"], payload, status, error)
            except PermissionError:
                status, error = "rejected", "not_granted"
            except ValueError:
                status, error = "rejected", "invalid_schema"
            except OSError:
                status, error = "rejected", "temporary_failure"
            channel.send({"type": "ack", "message_id": payload["message_id"], "status": status, "error": error})
            self.callback("status", self.report())
            return
        if kind in PERSONAL_DATA_KINDS:
            value = validate_personal_sync_body(kind, payload["body"])
            if payload["expires_ms"] <= received:
                self.store.remember_message(peer["device_id"], payload, "rejected", "expired")
                channel.send({"type": "ack", "message_id": payload["message_id"],
                              "status": "rejected", "error": "expired"})
                return
            if kind == "personal_sync.request":
                policy = "wifi_only" if value["trigger"] == "auto_wifi" else "any"
                durable = self.store.run_policy(peer["device_id"], value["run_id"])
                if durable == "expired":
                    self.store.remember_message(peer["device_id"], payload, "rejected", "expired")
                    channel.send({"type": "ack", "message_id": payload["message_id"],
                                  "status": "rejected", "error": "expired"})
                    return
                if durable and durable != policy:
                    raise ValueError("conflicting durable run policy")
                policy = durable or policy
            else:
                policy = self.store.run_policy(peer["device_id"], value["run_id"])
                if policy == "expired":
                    self.store.remember_message(peer["device_id"], payload, "rejected", "expired")
                    channel.send({"type": "ack", "message_id": payload["message_id"],
                                  "status": "rejected", "error": "expired"})
                    return
                if policy is None:
                    if not self.personal_sync_available():
                        self.store.remember_message(peer["device_id"], payload,
                                                    "rejected", "restore_unavailable")
                        channel.send({"type": "ack", "message_id": payload["message_id"],
                            "status": "rejected", "error": "restore_unavailable"})
                        return
                    raise ValueError("personal sync request missing")
                if kind in {"personal_sync.batch", "personal_sync.report"} and value.get("format", 1) != self.store.personal_run(
                        peer["device_id"], value["run_id"]).get("format", 1):
                    raise ValueError("conflicting personal sync format")
            if policy == "wifi_only" and self.connection_transports.get(peer["device_id"]) != "wifi":
                raise ValueError("wifi-only run received on bluetooth")
        if kind == "device_status.report" and ("identifiers" in payload["body"] or "version" in payload["body"]):
            self._receive_identifiers(peer, channel, payload)
            return
        previous = self.store.dedupe_result(peer["device_id"], payload["message_id"])
        if previous:
            if kind.startswith("personal_sync.") and kind != "personal_sync.settings":
                try:
                    value = validate_personal_sync_body(kind, payload["body"])
                    personal = peer.get("personal_sync", {})
                    local = peer.get("local_grants", {}).get("grants", {})
                    remote = peer.get("grants", {}).get("grants", {})
                    needed = personal_sync_grants_needed(kind, value) or {
                        name for name in ("personal_notes_sync", "personal_tasks_sync")
                        if local.get(name) and remote.get(name)}
                    if (self.store.sole_peer(peer["device_id"]) is None or not personal.get("own_device")
                            or not personal.get("remote_own_device") or not needed or any(
                            not local.get(name) or not remote.get(name) for name in needed)):
                        raise PermissionError
                    if kind == "personal_sync.attachment_result" and value["state"] == "complete":
                        pending = self.store.release_personal_report(peer["device_id"], value["run_id"])
                        if pending:
                            run = self.store.personal_run(peer["device_id"], value["run_id"])
                            self.send_personal_sync(peer["device_id"], "personal_sync.report", pending,
                                run.get("trigger", "manual"))
                except (ValueError, PermissionError):
                    channel.send({"type": "ack", "message_id": payload["message_id"],
                                  "status": "rejected", "error": "not_granted"})
                    return
            channel.send({"type": "ack", "message_id": payload["message_id"],
                          "status": ("accepted" if payload["kind"] == "personal_sync.batch"
                                     else "duplicate") if previous[0] == "accepted" else "rejected",
                          "error": "none" if previous[0] == "accepted" else previous[1]})
            return
        status, error = "accepted", "none"
        if payload["expires_ms"] + CLOCK_SKEW_MS < received:
            status, error = "rejected", "expired"
        elif ((kind == "device_status.report" and payload["expires_ms"] - payload["created_ms"] > 300000)
              or (kind == "dial_request.result" and payload["expires_ms"] - payload["created_ms"] > 60000)
              or (kind == "selected_notifications_readonly.event" and
                  payload["expires_ms"] - payload["created_ms"] > DAY_MS)
              or (kind == "incoming_call_state.event" and
                  payload["expires_ms"] - payload["created_ms"] > 60000)
              or (kind == "answer_call.result" and
                  payload["expires_ms"] - payload["created_ms"] > 60000)
              or (kind == "end_call.result" and
                  payload["expires_ms"] - payload["created_ms"] > 60000)
              or (kind in {"capabilities.update", "grants.update"}
                  and payload["expires_ms"] - payload["created_ms"] > DAY_MS)
              or (kind == "personal_sync.request" and
                  payload["expires_ms"] - payload["created_ms"] > 60 * 60 * 1000)
              or (kind in {"personal_sync.settings", "personal_sync.batch", "personal_sync.report"} | PERSONAL_ATTACHMENT_KINDS and
                  payload["expires_ms"] - payload["created_ms"] > DAY_MS)):
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
            with self.lock:
                self._purge_identifiers(peer["device_id"])
                self.call_action_tickets.clear()
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
            with self.lock:
                self._purge_identifiers(peer["device_id"])
                self.call_action_tickets.clear()
            try:
                value = validate_grants(payload["body"])
                old = peer.get("grants") or {"revision": 0}
                if value["revision"] <= old["revision"]:
                    raise ValueError("stale grants revision")
                revoked = set()
                if not value["grants"].get("personal_notes_sync"):
                    revoked.add("notes")
                if not value["grants"].get("personal_tasks_sync"):
                    revoked.add("tasks")
                self.store.purge_personal_modules(peer["device_id"], revoked)
                if not value["grants"].get("personal_deletions_sync"):
                    self.store.purge_personal_deletion_wire(peer["device_id"])
                with self.lock:
                    observation = self.audio_observations.get(peer["device_id"])
                    # Notes reannounces grants after reconnecting to deliver a
                    # queued call event. An unchanged announcement is not a
                    # revocation. Rebase only the still-current observation;
                    # never bridge a real permission or session change.
                    if (old.get("grants") == value["grants"] and observation
                            and observation[2] is channel
                            and (self.connections.get(peer["device_id"]) is None
                                 or self.connections.get(peer["device_id"]) is channel)
                            and observation[3:] == (peer["local_grants"].get("revision"), old["revision"])):
                        self.audio_observations[peer["device_id"]] = (*observation[:4], value["revision"])
                    peer["grants"] = value
                self.store.save_peers()
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "dial_request.result":
            try:
                value = validate_dial_result(payload["body"])
                if not peer.get("grants", {}).get("grants", {}).get("dial_request"):
                    status, error = "rejected", "not_granted"
                    raise PermissionError
                if not self.store.update_command(peer["device_id"], value["client_ref"], value["state"]):
                    raise ValueError("unknown dial result")
                self.callback("dial_status", dict(value, device_id=peer["device_id"]))
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
        elif kind == "incoming_call_state.event":
            try:
                local = peer.setdefault("local_grants", desktop_grants())["grants"]
                remote = peer.get("grants", {}).get("grants", {})
                if not local["incoming_call_state"] or not remote.get("incoming_call_state"):
                    status, error = "rejected", "not_granted"
                    raise PermissionError
                value = validate_incoming_call_state(payload["body"])
                with self.lock:
                    if self.connections.get(peer["device_id"]) not in (None, channel):
                        raise ValueError("stale call connection")
                    previous_call = self.incoming_calls.get(peer["device_id"])
                    if previous_call and (value["occurred_ms"] < previous_call["occurred_ms"] or
                            previous_call["call_ref"] == value["call_ref"] and (
                                previous_call["direction"] != value["direction"] or
                                previous_call["state"] == "idle" and value["state"] != "idle")):
                        raise ValueError("stale call lifecycle")
                    if (previous_call and previous_call["call_ref"] == value["call_ref"]
                            and value["revision"] <= previous_call["revision"]):
                        raise ValueError("stale call revision")
                    self.incoming_calls[peer["device_id"]] = value
                    self.incoming_call_channels[peer["device_id"]] = channel
                    if previous_call and previous_call["call_ref"] != value["call_ref"]:
                        self.audio_retired_calls.append((peer["device_id"], previous_call["call_ref"]))
                    if value["state"] == "idle":
                        self.audio_retired_calls.append((peer["device_id"], value["call_ref"]))
                    if (0 <= now_ms() - value["occurred_ms"] <= 15000
                            and (peer["device_id"], value["call_ref"]) not in self.audio_retired_calls
                            and (self.connections.get(peer["device_id"]) is None
                                 or self.connections.get(peer["device_id"]) is channel)):
                        # Authenticated call events can precede the control ACK.
                        # Keep that observation, but _call_audio_context still
                        # requires this exact channel to be activated first.
                        self.audio_observations[peer["device_id"]] = (value["call_ref"], value["revision"], channel,
                            peer["local_grants"].get("revision"), peer["grants"].get("revision"))
                    else:
                        self.audio_observations.pop(peer["device_id"], None)
                self.callback("incoming_call", enrich_call(dict(value,
                    device_id=peer["device_id"], display_name=peer["display_name"])))
            except PermissionError:
                pass
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "answer_call.result":
            try:
                value = validate_answer_result(payload["body"])
                if not self.store.update_command(peer["device_id"], value["command_ref"], value["state"]):
                    raise ValueError("unknown answer result")
                self.callback("answer_status", dict(value, device_id=peer["device_id"]))
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind == "end_call.result":
            try:
                value = validate_end_result(payload["body"])
                if not self.store.update_command(peer["device_id"], value["command_ref"], value["state"]):
                    raise ValueError("unknown end result")
                self.callback("end_status", dict(value, device_id=peer["device_id"]))
            except ValueError:
                status, error = "rejected", "invalid_schema"
        elif kind in {"personal_sync.settings"} | PERSONAL_DATA_KINDS:
            try:
                value = validate_personal_sync_body(kind, payload["body"])
                personal = peer.get("personal_sync", {})
                local = peer.get("local_grants", {}).get("grants", {})
                remote = peer.get("grants", {}).get("grants", {})
                if kind == "personal_sync.settings":
                    if self.store.binding_conflict() and value["own_device"]:
                        status, error = "rejected", "not_granted"
                        raise PermissionError
                    if not value["own_device"]:
                        self._purge_identifiers(peer["device_id"])
                        self._pause_custom(peer["device_id"])
                        self.store.purge_personal(peer["device_id"])
                    personal["remote_own_device"] = value["own_device"]
                    self.store.save_peers()
                needed = personal_sync_grants_needed(kind, value)
                if kind != "personal_sync.settings" and not needed:
                    needed = {name for name in ("personal_notes_sync", "personal_tasks_sync")
                               if local.get(name) and remote.get(name)}
                format = value.get("format", 1)
                if format >= 2 and "personal_notes_sync" in needed and negotiated_personal_notes_format(peer) < 2:
                    raise ValueError("format 2 was not negotiated")
                if format == 3 and any(not supports_personal_format(peer, name, 3) for name in needed):
                    raise ValueError("format 3 was not negotiated")
                if (kind != "personal_sync.settings" and (self.store.sole_peer(
                        peer["device_id"]) is None or not personal.get("own_device")
                        or not personal.get("remote_own_device") or not needed or any(
                        not local.get(name) or not remote.get(name) for name in needed))):
                    status, error = "rejected", "not_granted"
                    raise PermissionError
                if kind == "personal_sync.attachment_request":
                    run = self.store.personal_run(peer["device_id"], value["run_id"])
                    if run.get("trigger") == "auto_wifi" and self.connection_transports.get(peer["device_id"]) != "wifi":
                        raise ValueError("auto attachment request outside wifi")
                    chunks = self.store.requested_attachment_chunks(peer["device_id"], value["run_id"],
                        value["reply"], value["records_hash"], value["wants"],
                        self.connection_transports.get(peer["device_id"], "wifi"))
                    for digest, index, raw in chunks:
                        self.send_personal_sync(peer["device_id"], "personal_sync.attachment_chunk", {
                            "format": 2, "run_id": value["run_id"], "reply": value["reply"],
                            "records_hash": value["records_hash"], "sha256": digest, "index": index,
                            "data": base64.b64encode(raw).decode("ascii")})
                    self.store.remember_message(peer["device_id"], payload, "accepted", "none")
                    channel.send({"type": "ack", "message_id": payload["message_id"],
                                  "status": "accepted", "error": "none"})
                    return
                if kind == "personal_sync.attachment_chunk":
                    run = self.store.personal_run(peer["device_id"], value["run_id"])
                    policy = "wifi_only" if run.get("trigger") == "auto_wifi" else "any"
                    if policy == "wifi_only" and self.connection_transports.get(peer["device_id"]) != "wifi":
                        raise ValueError("auto attachment chunk outside wifi")
                    descriptor = None
                    for staged_peer, aggregate in self.store.ready_personal_batches():
                        if staged_peer != peer["device_id"] or aggregate["run_id"] != value["run_id"] or aggregate["reply"] != value["reply"]:
                            continue
                        last = aggregate["messages"][-1]["body"]
                        if last.get("records_hash") != value["records_hash"]:
                            continue
                        descriptor = next((item for record in aggregate["records"] if record["kind"] == "note"
                                           for item in record["value"]["attachments"]
                                           if item["sha256"] == value["sha256"]), None)
                        if descriptor:
                            break
                    if not descriptor:
                        raise ValueError("attachment is not in staged manifest")
                    raw = base64.b64decode(value["data"], validate=True)
                    self.store.stage_incoming_attachment(peer["device_id"], value["run_id"], value["reply"],
                        value["records_hash"], value["sha256"], descriptor["size"], descriptor["mime"],
                        value["index"], raw, policy, payload["expires_ms"], descriptor["attachment_id"])
                    self.store.remember_message(peer["device_id"], payload, "accepted", "none")
                    channel.send({"type": "ack", "message_id": payload["message_id"],
                                  "status": "accepted", "error": "none"})
                    try:
                        self.replay_personal_sync()
                    except (ValueError, OSError):
                        self.send_personal_sync(peer["device_id"], "personal_sync.attachment_result", {
                            "format": 2, "run_id": value["run_id"], "reply": value["reply"],
                            "records_hash": value["records_hash"], "sha256": value["sha256"],
                            "state": "failed", "error": "invalid"}, run.get("trigger", "manual"))
                        self.callback("personal_sync_error", {"error": "invalid attachment"})
                    return
                if kind == "personal_sync.attachment_result":
                    if value["state"] == "complete":
                        self.store.complete_outgoing_attachment(peer["device_id"], value["run_id"],
                            value["reply"], value["records_hash"], value["sha256"])
                        pending_report = self.store.release_personal_report(peer["device_id"], value["run_id"])
                        if pending_report:
                            run = self.store.personal_run(peer["device_id"], value["run_id"])
                            self.send_personal_sync(peer["device_id"], "personal_sync.report", pending_report,
                                run.get("trigger", "manual"))
                if kind in PERSONAL_DELETION_KINDS:
                    if not self.personal_sync_available():
                        status, error = "rejected", "restore_unavailable"
                        raise PermissionError
                    staged = self.store.stage_personal_domain(peer["device_id"], payload)
                    token = staged["commit_token"]
                    staged["transport"] = self.connection_transports.get(peer["device_id"], "")
                    with self.lock:
                        event = self.personal_commit_events.setdefault(token, threading.Event())
                        dispatch = token not in self.personal_dispatched
                        if dispatch:
                            self.personal_dispatched.add(token)
                    if dispatch:
                        self.callback("personal_sync", staged)
                    event.wait(PERSONAL_COMMIT_SECONDS)
                    committed = not any(item[1]["pending_message_id"] == payload["message_id"]
                        for item in self.store.ready_personal_domains())
                    with self.lock:
                        self.personal_commit_events.pop(token, None)
                        if not committed:
                            self.personal_dispatched.discard(token)
                    if committed:
                        channel.send({"type": "ack", "message_id": payload["message_id"],
                                      "status": "accepted", "error": "none"})
                    elif kind == "personal_sync.deletion_decision":
                        channel.send({"type": "ack", "message_id": payload["message_id"],
                                      "status": "rejected", "error": "restore_unavailable"})
                    return
                if kind == "personal_sync.batch":
                    if not self.personal_sync_available():
                        status, error = "rejected", "restore_unavailable"
                        raise PermissionError
                    run = self.store.personal_run(peer["device_id"], value["run_id"])
                    if run.get("trigger") not in {"manual", "auto_wifi"} or not run.get("modules"):
                        raise ValueError("personal sync request missing")
                    aggregate = self.store.stage_personal_batch(peer["device_id"], payload)
                    # A batch transport ACK means encrypted durable staging, not semantic apply.
                    channel.send({"type": "ack", "message_id": payload["message_id"],
                                  "status": "accepted", "error": "none"})
                    if aggregate is None:
                        return
                    if value["format"] >= 2 and not self._prepare_format2_aggregate(
                            peer["device_id"], aggregate,
                            self.connection_transports.get(peer["device_id"], "")):
                        return
                    token = aggregate.pop("commit_token")
                    pending_message_id = aggregate.pop("message_id")
                    aggregate.pop("messages")
                    with self.lock:
                        event = self.personal_commit_events.setdefault(token, threading.Event())
                        dispatch = token not in self.personal_dispatched
                        if dispatch:
                            self.personal_dispatched.add(token)
                    if dispatch:
                        self.callback("personal_sync", {"device_id": peer["device_id"],
                            "transport": self.connection_transports.get(peer["device_id"], ""),
                            "kind": kind, "commit_token": token,
                            "pending_message_id": pending_message_id, "body": dict(value,
                                sequence=0, last=True, records=aggregate["records"],
                                attachment_data=aggregate.get("attachment_data", {}),
                                requested_modules=run.get("modules", []),
                                trigger=run.get("trigger", "manual"))})
                    event.wait(PERSONAL_COMMIT_SECONDS)
                    committed = not self.store.has_personal_batch(
                        peer["device_id"], pending_message_id, token)
                    with self.lock:
                        self.personal_commit_events.pop(token, None)
                        if not committed:
                            self.personal_dispatched.discard(token)
                    return
                if kind == "personal_sync.request":
                    if value["trigger"] == "auto_wifi" and self.connection_transports.get(peer["device_id"]) != "wifi":
                        raise ValueError("auto sync received outside wifi")
                    if not self.personal_sync_available():
                        offer_key = (peer["device_id"], value["run_id"])
                        with self.lock:
                            if offer_key not in self.personal_offer_keys:
                                if len(self.personal_offers) == self.personal_offers.maxlen:
                                    self.personal_offer_keys.discard(self.personal_offers[0])
                                self.personal_offers.append(offer_key)
                                self.personal_offer_keys.add(offer_key)
                                offer = True
                            else:
                                offer = False
                        if offer:
                            self.callback("personal_sync_offer", {
                                "device_id": peer["device_id"],
                                "display_name": peer["display_name"],
                                "run_id": value["run_id"],
                                "requested_modules": list(value["modules"]),
                                "trigger": value["trigger"]})
                        status, error = "rejected", "restore_unavailable"
                        raise PermissionError
                    self.store.remember_personal_run(peer["device_id"], value, payload["expires_ms"])
                    if value["trigger"] == "auto_wifi":
                        self.store.set_active_auto_run(peer["device_id"], value["run_id"])
                if kind == "personal_sync.report":
                    run = self.store.personal_run(peer["device_id"], value["run_id"])
                    if run.get("trigger") != value["trigger"]:
                        raise ValueError("personal sync report trigger mismatch")
                    personal["last_report"] = value
                    self.store.save_peers()
                    if value["state"] in {"complete", "partial", "blocked", "failed"}:
                        self.store.finish_auto_run(peer["device_id"], value["run_id"])
                if kind != "personal_sync.request" and kind not in PERSONAL_ATTACHMENT_KINDS:
                    self.callback("personal_sync", {"device_id": peer["device_id"],
                        "transport": self.connection_transports.get(peer["device_id"], ""),
                        "kind": kind, "body": value})
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
            pairing_active = self.pairing_token and time.monotonic() < self.pairing_until
            properties = {"v": "1", "role": "desktop",
                          "id": self.store.identity["device_id"],
                          "name": self.store.identity["display_name"],
                          "pair": "1" if pairing_active else "0"}
            if pairing_active:
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
        except Exception:  # noqa: S110 - mDNS teardown must tolerate a vanished service.
            pass
        try:
            zc.close()
        except Exception:  # noqa: S110 - mDNS teardown must tolerate a closed daemon.
            pass


def validate_device_status(body):
    base_fields = {"request_id", "model", "manufacturer", "os_name", "os_version",
                   "battery_percent", "charging", "captured_ms"}
    extended_fields = {"sdk_int", "battery_temperature_deci_c", "power_source",
                       "storage_total_bytes", "storage_available_bytes",
                       "memory_total_bytes", "memory_available_bytes", "uptime_ms",
                       "network_transport", "network_validated", "network_metered"}
    version3_fields = base_fields | extended_fields | {"app_version"}
    version4_fields = version3_fields | {"version", "identifiers"}
    if (not isinstance(body, dict) or set(body) not in (base_fields, base_fields | extended_fields,
                                                        version3_fields, version4_fields)
            or not valid_uuid(body["request_id"])):
        raise ValueError("invalid device status")
    limits = {"model": (0, 80), "manufacturer": (0, 80), "os_name": (1, 20),
              "os_version": (0, 40)}
    for name, (minimum, maximum) in limits.items():
        value = body[name]
        if (not isinstance(value, str) or not minimum <= len(value) <= maximum
                or any(ord(char) < 32 for char in value)):
            raise ValueError("invalid device status")
    if set(body) in (version3_fields, version4_fields):
        value = body["app_version"]
        if (not isinstance(value, str) or not 1 <= len(value) <= 80
                or any(unicodedata.category(char) == "Cc" for char in value)):
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
    if set(body) in (base_fields | extended_fields, version3_fields, version4_fields):
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
    if set(body) == version4_fields:
        identifiers = body["identifiers"]
        if type(body["version"]) is not int or body["version"] != 4 or not isinstance(identifiers, dict) or set(identifiers) != {"phone_number", "serial", "imei"}:
            raise ValueError("invalid device identifiers")
        for name, maximum in (("phone_number", 64), ("serial", 128), ("imei", 32)):
            field = identifiers[name]
            if not isinstance(field, dict) or set(field) != {"status", "value"}:
                raise ValueError("invalid device identifiers")
            state, value = field["status"], field["value"]
            if (state not in ("available", "not_shared", "permission_missing", "os_restricted", "no_subscription", "unavailable")
                    or not isinstance(value, str) or len(value) > maximum
                    or (state == "available") != bool(value)
                    or any(unicodedata.category(c) == "Cc" for c in value)
                    or name == "imei" and value and not re.fullmatch(r"[0-9]+", value)):
                raise ValueError("invalid device identifiers")
    return body


def without_device_identifiers(body):
    return {key: value for key, value in body.items()
            if key in {"request_id", "model", "manufacturer", "os_name", "os_version", "battery_percent",
                "charging", "captured_ms", "sdk_int", "battery_temperature_deci_c", "power_source",
                "storage_total_bytes", "storage_available_bytes", "memory_total_bytes", "memory_available_bytes",
                "uptime_ms", "network_transport", "network_validated", "network_metered", "app_version",
                "online", "last_contact_ms", "cached_ms", "kennung", "name", "letzterKontakt"}}


def validate_dial_request(body):
    if (not isinstance(body, dict) or set(body) != {"to", "client_ref"}
            or not isinstance(body["to"], str)
            or not re.fullmatch(r"\+[0-9]{3,15}", body["to"])
            or not valid_uuid(body["client_ref"], 4)):
        raise ValueError("invalid dial request")
    return body


def validate_dial_result(body):
    states = {"submitted", "failed"}
    errors = {"none", "invalid_destination", "dial_unavailable", "not_granted",
              "permission_missing", "no_telephony", "os_restricted", "unknown"}
    if (not isinstance(body, dict) or set(body) != {"client_ref", "state", "error", "occurred_ms"}
            or not valid_uuid(body["client_ref"], 4) or body["state"] not in states
            or body["error"] not in errors
            or (body["state"] == "failed") != (body["error"] != "none")
            or not valid_timestamp(body["occurred_ms"])):
        raise ValueError("invalid dial result")
    return body


def validate_selected_notification(body):
    fields = {"notification_id", "event", "package", "app_label", "title", "text",
              "posted_ms", "is_default_sms_app"}
    if (not isinstance(body, dict) or set(body) != fields
            or not valid_uuid(body["notification_id"]) or body["event"] not in {"posted", "removed"}
            or not valid_text(body["package"], 1, 255)
            or not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", body["package"])
            or not valid_text(body["app_label"], 0, 80)
            or not valid_text(body["title"], 0, 500, True)
            or not valid_text(body["text"], 0, 5000, True)
            or not isinstance(body["is_default_sms_app"], bool)
            or not valid_timestamp(body["posted_ms"])
            or body["event"] == "removed" and (body["title"] or body["text"])):
        raise ValueError("invalid selected notification")
    return body


def validate_incoming_call_state(body):
    fields = {"call_ref", "revision", "state", "direction", "number",
              "number_status", "started_ms", "offhook_ms", "ended_ms", "occurred_ms",
              "spam_status", "control_origin", "battery_percent", "battery_captured_ms"}
    if (not isinstance(body, dict) or set(body) != fields
            or not valid_uuid(body["call_ref"], 4)
            or isinstance(body["revision"], bool) or not isinstance(body["revision"], int)
            or body["revision"] < 1 or body["state"] not in {"ringing", "offhook", "idle"}
            or body["direction"] not in {"incoming", "outgoing", "unknown"}
            or body["number_status"] not in {"available", "withheld", "unavailable",
                                                     "permission_missing", "not_shared"}
            or not isinstance(body["number"], str)
            or (body["number_status"] == "available") != bool(
                re.fullmatch(r"\+[0-9]{3,15}", body["number"]))
            or body["number_status"] != "available" and body["number"]
            or body["spam_status"] not in {"suspected", "unknown"}
            or body["control_origin"] not in {"desktop", "phone", "unknown"}
            or not valid_timestamp(body["occurred_ms"])
            or not valid_timestamp(body["started_ms"]) or body["started_ms"] <= 0
            or body["started_ms"] > body["occurred_ms"]
            or not valid_timestamp(body["offhook_ms"]) or body["offhook_ms"] > body["occurred_ms"]
            or not valid_timestamp(body["ended_ms"]) or body["ended_ms"] > body["occurred_ms"]
            or (body["state"] == "idle") != (body["ended_ms"] > 0)
            or body["state"] == "offhook" and body["offhook_ms"] == 0
            or body["offhook_ms"] and body["offhook_ms"] < body["started_ms"]
            or body["ended_ms"] and body["ended_ms"] < max(body["started_ms"], body["offhook_ms"])
            or isinstance(body["battery_percent"], bool) or body["battery_percent"] not in range(-1, 101)
            or not valid_timestamp(body["battery_captured_ms"])
            or body["battery_captured_ms"] > body["occurred_ms"]
            or (body["battery_percent"] < 0) != (body["battery_captured_ms"] == 0)):
        raise ValueError("invalid incoming call state")
    return body


def validate_answer_command(body):
    if (not isinstance(body, dict) or set(body) != {"command_ref", "call_ref",
                                                    "expected_state"}
            or not valid_uuid(body["command_ref"], 4)
            or not valid_uuid(body["call_ref"], 4) or body["expected_state"] != "ringing"):
        raise ValueError("invalid answer command")
    return body


def validate_answer_result(body):
    fields = {"command_ref", "call_ref", "state", "error", "occurred_ms"}
    states = {"submitted", "already_answered", "failed"}
    errors = {"none", "expired", "not_granted", "permission_missing", "not_ringing",
              "stale_call", "os_restricted", "unknown"}
    if (not isinstance(body, dict) or set(body) != fields
            or not valid_uuid(body["command_ref"], 4) or not valid_uuid(body["call_ref"], 4)
            or body["state"] not in states or body["error"] not in errors
            or (body["state"] == "failed") != (body["error"] != "none")
            or not valid_timestamp(body["occurred_ms"])):
        raise ValueError("invalid answer result")
    return body


def validate_end_command(body):
    if (not isinstance(body, dict) or set(body) != {"command_ref", "call_ref",
            "expected_revision", "expected_state"} or not valid_uuid(body["command_ref"], 4)
            or not valid_uuid(body["call_ref"], 4) or not _validate_revision(body["expected_revision"])
            or body["expected_state"] not in {"offhook", "ringing"}):
        raise ValueError("invalid end command")
    return body


def validate_end_result(body):
    fields = {"command_ref", "call_ref", "state", "error", "occurred_ms"}
    states = {"submitted", "already_ended", "failed"}
    errors = {"none", "expired", "not_granted", "permission_missing", "unsupported_api",
              "stale_call", "not_active", "os_restricted", "unknown"}
    if (not isinstance(body, dict) or set(body) != fields or not valid_uuid(body["command_ref"], 4)
            or not valid_uuid(body["call_ref"], 4) or body["state"] not in states
            or body["error"] not in errors or (body["state"] == "failed") != (body["error"] != "none")
            or not valid_timestamp(body["occurred_ms"])):
        raise ValueError("invalid end result")
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
            or set(body["items"]) != CAPABILITY_NAMES):
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
