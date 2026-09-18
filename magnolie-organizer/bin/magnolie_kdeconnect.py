#!/usr/bin/env python3
"""Small, fail-closed KDE Connect protocol-v8 SMS client."""

import ipaddress
import json
import os
import re
import queue
import select
import socket
import sqlite3
import stat
import struct
import tempfile
import threading
import time
import unicodedata
import uuid
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import NameOID

try:
    import fcntl
except ImportError:  # Directed broadcasts are an optional Linux enhancement.
    fcntl = None

try:
    from OpenSSL import SSL, crypto
except ImportError:  # Reported by status; no insecure transport fallback.
    SSL = crypto = None


PROTOCOL_VERSION = 8
UDP_PORT = 1716
MIN_TCP_PORT = 1716
MAX_TCP_PORT = 1764
MAX_PACKET = 512 * 1024
PAIR_WINDOW = 30
PAIR_CLOCK_SKEW = 1800
DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]{32,38}$")
SMS_REQUEST_TYPE = "kdeconnect.sms.request"
SMS_REQUEST_CONVERSATIONS_TYPE = "kdeconnect.sms.request_conversations"
SMS_REQUEST_CONVERSATION_TYPE = "kdeconnect.sms.request_conversation"
SMS_MESSAGES_TYPE = "kdeconnect.sms.messages"
CONTACT_UIDS_REQUEST = "kdeconnect.contacts.request_all_uids_timestamps"
CONTACT_UIDS_RESPONSE = "kdeconnect.contacts.response_uids_timestamps"
CONTACT_VCARDS_REQUEST = "kdeconnect.contacts.request_vcards_by_uid"
CONTACT_VCARDS_RESPONSE = "kdeconnect.contacts.response_vcards"
MAX_CONTACT_PACKET = 4 * 1024 * 1024
SMS_TYPE = SMS_REQUEST_TYPE
CLIPBOARD_TYPE = "kdeconnect.clipboard"
CLIPBOARD_CONNECT_TYPE = "kdeconnect.clipboard.connect"
SHARE_TYPE = "kdeconnect.share.request"
MAX_CLIPBOARD_BYTES = 64 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_RECEIVE_PENDING = 8
RECEIVE_PROPOSAL_SECONDS = 10 * 60
MAX_MESSAGES = 1000
MAX_ADDRESSES = 32
MAX_ATTACHMENTS = 32
SMS_BOOTSTRAP_QUIET = 1.0
SMS_BOOTSTRAP_MAX = 5.0
MAX_PENDING = 8
CANDIDATE_TTL = 300
FAST_DISCOVERY_INTERVAL = 2.0
RECONNECT_BACKOFF = (5, 15, 30, 60)
SIOCGIFFLAGS = 0x8913
SIOCGIFADDR = 0x8915
SIOCGIFBRDADDR = 0x8919
IFF_UP = 0x1
IFF_BROADCAST = 0x2
IFF_LOOPBACK = 0x8
GSM_BASIC = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM_EXTENSION = set("^{}\\[~]|€")
SMS_MAX_SEGMENTS = 10


def local_device_name(hostname=None):
    product = "Magnolie Organizer"
    machine = " ".join(str(hostname if hostname is not None else
                           socket.gethostname()).split()).split(".", 1)[0]
    if not machine:
        return product
    room = 128 - len(product) - 3
    return "%s (%s)" % (product, machine[:room])


class ProtocolError(RuntimeError):
    pass


class SmsSubmissionJournal:
    """Non-restorable, digest-only reservations; a crash never permits a replay."""

    def __init__(self, path):
        self.path = path

    def submit(self, client_ref, number, text, country, device_id, send):
        if not isinstance(client_ref, str) or not 1 <= len(client_ref) <= 160:
            raise ValueError("invalid SMS submission identity")
        identity = sha256(client_ref.encode("utf-8")).hexdigest()
        payload = sha256(json.dumps([number, text, country, device_id],
            ensure_ascii=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        # Set private permissions before SQLite writes any data; never truncate.
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("PRAGMA synchronous=EXTRA")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL)")
            old = db.execute("SELECT payload, state FROM submissions WHERE id=?", (identity,)).fetchone()
            if old is not None:
                if old[0] != payload:
                    raise ValueError("SMS submission payload mismatch")
                state = "submitted" if old[1] == "submitted" else "uncertain"
                return {"ok": state == "submitted", "state": state}
            # Never evict an identity: an old content archive can replay it later.
            if db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] >= 10000:
                raise ValueError("SMS submission journal full")
            db.execute("INSERT INTO submissions VALUES (?, ?, 'uncertain')", (identity, payload))
            db.commit()
            # Persist the containing directory before allowing an external effect.
            parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            try:
                result = send()
                if result.get("ok") is True:
                    db.execute("UPDATE submissions SET state='submitted' WHERE id=?", (identity,))
                    db.commit()
                    return dict(result, state="submitted")
            except Exception:
                pass
            return {"ok": False, "state": "uncertain"}


NATIVE_KDE_NOTICE = "Native KDE Connect is used for SMS on already paired phones. Magnolie does not change KDE permissions."
NATIVE_KDE_LIMIT = "Native KDE Connect cannot enforce Magnolie approvals. Clipboard and file reception, incoming SMS/history and new pairing are unavailable. Magnolie Notes WLAN remains separate."
NATIVE_KDE_UNAVAILABLE = "Native KDE Connect is unavailable. Magnolie will not take over its network port."


def create_backend(directory, device_name=None, callback=None):
    """Prefer the session's native owner; never start it or change its plugins."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        native = KDEConnectNativeBackend(bus, Gio, GLib, callback=callback)
        running = native._call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                              'org.freedesktop.DBus', 'NameHasOwner', '(s)',
                              ('org.kde.kdeconnect',), '(b)')[0]
        activatable = native._call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                  'org.freedesktop.DBus', 'ListActivatableNames', None, (), '(as)')[0]
        if running or 'org.kde.kdeconnect' in activatable:
            return native
        # A filtered sandbox bus can hide the native daemon. Check the shared
        # network namespace before constructing any direct transport/identity.
        for table in ('/proc/net/udp', '/proc/net/udp6'):
            if table.endswith('udp6') and not os.path.exists(table):
                continue
            with open(table, encoding='ascii') as source:
                if any(int(line.split()[1].rsplit(':', 1)[1], 16) == UDP_PORT
                       for line in list(source)[1:] if line.strip()):
                    return native
    except Exception:
        # An inaccessible bus is not proof that nobody owns the desktop port.
        return KDEConnectNativeBackend(None, None, None, callback=callback)
    return KDEConnectSMSBackend(directory, device_name=device_name, callback=callback)


class KDEConnectNativeBackend:
    """Read-only native discovery and explicit SMS submission, no inbound channels."""
    native = True

    def __init__(self, bus, gio, glib, callback=None):
        self.bus, self.gio, self.glib = bus, gio, glib
        self.callback = callback
        self.pairing = None
        self.listening = False

    def _call(self, owner, path, interface, method, signature=None, args=(), reply=None, deadline=None):
        if self.bus is None:
            raise ProtocolError(NATIVE_KDE_UNAVAILABLE)
        timeout = 1500 if deadline is None else min(1500, int((deadline - time.monotonic()) * 1000))
        if timeout <= 0:
            raise TimeoutError(NATIVE_KDE_UNAVAILABLE)
        return self.bus.call_sync(owner, path, interface, method,
            self.glib.Variant(signature, args) if signature else None,
            self.glib.VariantType.new(reply) if reply else None,
            self.gio.DBusCallFlags.NO_AUTO_START, timeout, None).unpack()

    def _owner(self, deadline=None):
        return self._call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                          'org.freedesktop.DBus', 'GetNameOwner', '(s)',
                          ('org.kde.kdeconnect',), '(s)', deadline=deadline)[0]

    def _devices(self, owner):
        deadline = time.monotonic() + 1.5
        ids = self._call(owner, '/modules/kdeconnect', 'org.kde.kdeconnect.daemon',
                         'devices', '(bb)', (False, True), '(as)', deadline=deadline)[0]
        if not isinstance(ids, (list, tuple)) or len(ids) > 64:
            raise ProtocolError('invalid native KDE Connect device list')
        devices = []
        for device_id in dict.fromkeys(i for i in ids if isinstance(i, str) and DEVICE_ID.fullmatch(i)):
            path = '/modules/kdeconnect/devices/' + device_id
            props = self._call(owner, path, 'org.freedesktop.DBus.Properties',
                               'GetAll', '(s)', ('org.kde.kdeconnect.device',), '(a{sv})', deadline=deadline)[0]
            if props.get('isPaired') is not True or props.get('type') not in ('phone', 'tablet'):
                continue
            reachable = props.get('isReachable') is True
            sms = reachable and self._call(owner, path, 'org.kde.kdeconnect.device',
                'hasPlugin', '(s)', ('kdeconnect_sms',), '(b)', deadline=deadline)[0] is True
            name = props.get('name')
            devices.append({'device_id': device_id,
                'device_name': ''.join(c for c in name if c.isprintable())[:128] if isinstance(name, str) else device_id,
                'paired': True, 'reachable': reachable, 'sms_send': sms})
        if self._owner(deadline=deadline) != owner:
            raise ProtocolError(NATIVE_KDE_UNAVAILABLE)
        return devices

    def start(self):
        # This adapter has no transport to bind. A dormant native service is not
        # a failure of the independent Notes/background services.
        return True

    def stop(self):
        return None

    def status(self, timeout=0.25):
        running, reason, devices = False, '', []
        try:
            devices = self._devices(self._owner())
            running = True
        except Exception:
            reason = 'native_service_unavailable'
        capable = [d for d in devices if d['sms_send']]
        selected = capable[0] if len(capable) == 1 else None
        return {'backend': 'kdeconnect-native', 'native': True, 'service_running': running,
            'available': selected is not None, 'reason': reason or ('no_device' if not capable else
                'multiple_devices' if len(capable) > 1 else ''),
            'device_count': len(capable), 'devices': devices,
            'device_id': selected['device_id'] if selected else '',
            'peer_id': selected['device_id'] if selected else '',
            'peer_name': selected['device_name'] if selected else '',
            'paired': len(devices), 'paired_count': len(devices),
            'listening': False, 'listen_port': None, 'pairing_state': 'idle',
            'unpaired_candidates': [], 'unpaired_candidate_count': 0,
            'history_available': False, 'capabilities': {'sms_send': bool(capable),
                'clipboard_receive': False, 'file_receive': False, 'sms_receive': False, 'sms_history': False, 'pairing': False},
            'capability_explanation': NATIVE_KDE_LIMIT,
            'receive': dict(self.configure_receive(), pending_count=0, proposals=[])}

    def discover(self, timeout=0.7):
        # Do not broadcast or activate native discovery as a background side effect.
        return self.status(timeout)['devices']

    def configure_receive(self, *, clipboard_enabled=False, file_enabled=False,
                          device_id=None, clipboard_mode='confirm', file_mode='confirm',
                          download_directory=None):
        if clipboard_enabled or file_enabled:
            raise ProtocolError(NATIVE_KDE_LIMIT)
        return {'clipboard_enabled': False, 'file_enabled': False, 'device_id': '',
                'clipboard_mode': 'confirm', 'file_mode': 'confirm', 'download_directory': ''}

    def accept_receive(self, receive_id, directory=None):
        raise ProtocolError(NATIVE_KDE_LIMIT)

    def reject_receive(self, receive_id):
        # There are no native proposals or subscriptions to apply or acknowledge.
        return False

    def begin_pairing(self, device_id=None, replace_stored=False):
        raise ProtocolError(NATIVE_KDE_LIMIT)

    def complete_pairing(self, device_id):
        raise ProtocolError(NATIVE_KDE_LIMIT)

    def confirm_pairing(self, code_matches):
        raise ProtocolError(NATIVE_KDE_LIMIT)

    def send_sms(self, destination, message, device_id=None):
        if not isinstance(destination, str) or not re.fullmatch(r'\+[1-9][0-9]{5,19}', destination):
            raise ValueError('invalid SMS destination')
        normalized = normalize_sms_text(message)
        text = normalized['text']
        if not text.strip() or len(text) > 5000 or normalized['segments'] > SMS_MAX_SEGMENTS:
            raise ValueError('invalid SMS text')
        owner = self._owner()
        devices = [d for d in self._devices(owner) if d['sms_send'] and
                   (device_id is None or d['device_id'] == device_id)]
        if len(devices) != 1:
            raise ProtocolError('exactly one paired KDE Connect phone must be reachable')
        selected = devices[0]['device_id']
        # ConversationAddress is a variant containing the D-Bus struct (s).
        # Empty attachments cannot initiate any file read or transfer. No retry:
        # a D-Bus timeout can mean submission occurred, not safe failure to resend.
        self._call(owner, '/modules/kdeconnect/devices/' + selected + '/sms',
            'org.kde.kdeconnect.device.sms', 'sendSms', '(avsavx)',
            ([self.glib.Variant('(s)', (destination,))], text, [], -1), '()')
        return {'ok': True, 'state': 'queued', 'backend': 'kdeconnect-native', 'device_id': selected}


def normalize_sms_text(value):
    """Return deterministic GSM 03.38 text and its septet/segment counts."""
    if not isinstance(value, str):
        raise ValueError("invalid SMS text")
    original = value
    replacements = {"❤️": "<3", "❤": "<3", "🙂": ":)", "😊": ":)",
                    "👍": "+1", "👎": "-1", "😂": ":D", "😉": ";)",
                    "—": "-", "–": "-", "…": "...", "‘": "'", "’": "'",
                    "‚": "'", "“": '"', "”": '"', "„": '"', "\u00a0": " "}
    for source, target in replacements.items():
        value = value.replace(source, target)
    result = []
    for character in value:
        code = ord(character)
        if character in GSM_BASIC or character in GSM_EXTENSION:
            result.append(character)
        elif character in "\ufe0e\ufe0f" or 0x1F3FB <= code <= 0x1F3FF:
            continue
        elif character == "\t":
            result.append(" ")
        elif unicodedata.category(character).startswith("M"):
            continue
        elif unicodedata.category(character).startswith("L"):
            folded = "".join(part for part in unicodedata.normalize("NFKD", character)
                             if part in GSM_BASIC or part in GSM_EXTENSION)
            result.append(folded or "?")
        elif unicodedata.category(character).startswith(("S", "P")):
            result.append("[Symbol]")
        elif character.isprintable():
            result.append("?")
    text = "".join(result)
    units = sum(2 if character in GSM_EXTENSION else 1 for character in text)
    segments = 0 if not units else 1 if units <= 160 else (units + 152) // 153
    return {"text": text, "units": units, "segments": segments,
            "changed": text != original}


def _no_duplicate_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolError("duplicate JSON member")
        value[key] = item
    return value


def encode_packet(packet):
    if not isinstance(packet, dict):
        raise ProtocolError("packet must be an object")
    try:
        raw = json.dumps(packet, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as error:
        raise ProtocolError("packet is not valid JSON") from error
    if len(raw) > MAX_PACKET:
        raise ProtocolError("packet exceeds size limit")
    return raw


def decode_packet(raw, limit=MAX_PACKET):
    if not isinstance(raw, bytes) or not raw.endswith(b"\n") or b"\r" in raw:
        raise ProtocolError("packet must end in exactly one LF")
    if len(raw) > limit or b"\n" in raw[:-1] or not raw[:-1]:
        raise ProtocolError("invalid packet framing")
    try:
        value = json.loads(raw[:-1].decode("utf-8"),
                           object_pairs_hook=_no_duplicate_object,
                           parse_constant=lambda _value: (_ for _ in ()).throw(
                               ProtocolError("non-finite JSON number")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("invalid JSON packet") from error
    if not isinstance(value, dict):
        raise ProtocolError("packet must be an object")
    return value


def read_packet(stream, limit=MAX_PACKET, buffer=None):
    data = bytearray() if buffer is None else buffer
    while True:
        end = data.find(b"\n")
        if end >= 0:
            raw = bytes(data[:end + 1])
            del data[:end + 1]
            result = decode_packet(raw, limit)
            if len(raw) > MAX_PACKET and result.get("type") not in (CONTACT_UIDS_RESPONSE, CONTACT_VCARDS_RESPONSE):
                raise ProtocolError("packet exceeds size limit")
            return result
        if len(data) > limit:
            raise ProtocolError("packet exceeds size limit")
        part = stream.recv(1 if buffer is None else min(8192, limit + 1 - len(data)))
        if not part:
            raise ProtocolError("connection closed before packet terminator")
        data += part
        if buffer is None and part == b"\n":
            return decode_packet(bytes(data), limit)
    raise ProtocolError("packet exceeds size limit")


def network_packet(kind, body):
    return {"id": int(time.time() * 1000), "type": kind, "body": body}


def request_conversations_packet():
    return network_packet(SMS_REQUEST_CONVERSATIONS_TYPE, {})


def request_conversation_packet(thread_id, number_to_request=None):
    if not isinstance(thread_id, int) or isinstance(thread_id, bool) or thread_id < 0:
        raise ProtocolError("invalid SMS thread id")
    if (number_to_request is not None and
            (not isinstance(number_to_request, int) or isinstance(number_to_request, bool)
             or not 1 <= number_to_request <= 1000)):
        raise ProtocolError("invalid SMS request size")
    body = {"threadID": thread_id, "rangeStartTimestamp": -1}
    if number_to_request is not None:
        body["numberToRequest"] = number_to_request
    return network_packet(SMS_REQUEST_CONVERSATION_TYPE, body)


def _receive_envelope(packet, kind, extra=()):
    keys = {"id", "type", "body"} | set(extra)
    if (not isinstance(packet, dict) or set(packet) != keys
            or packet.get("type") != kind
            or not isinstance(packet.get("id"), int)
            or isinstance(packet.get("id"), bool)
            or not isinstance(packet.get("body"), dict)):
        raise ProtocolError("invalid %s packet" % kind)
    return packet["body"]


def parse_clipboard_packet(packet):
    """Return bounded UTF-8 clipboard content and an optional connect timestamp."""
    kind = packet.get("type") if isinstance(packet, dict) else None
    if kind not in (CLIPBOARD_TYPE, CLIPBOARD_CONNECT_TYPE):
        raise ProtocolError("invalid clipboard packet type")
    body = _receive_envelope(packet, kind)
    expected = {"content", "timestamp"} if kind == CLIPBOARD_CONNECT_TYPE else {"content"}
    if set(body) != expected or not isinstance(body.get("content"), str):
        raise ProtocolError("invalid clipboard body")
    try:
        size = len(body["content"].encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ProtocolError("invalid clipboard UTF-8") from error
    if size > MAX_CLIPBOARD_BYTES:
        raise ProtocolError("clipboard exceeds size limit")
    timestamp = body.get("timestamp")
    if kind == CLIPBOARD_CONNECT_TYPE and (not isinstance(timestamp, int)
            or isinstance(timestamp, bool) or not 0 <= timestamp <= 2 ** 63 - 1):
        raise ProtocolError("invalid clipboard timestamp")
    return {"text": body["content"], "timestamp": timestamp, "connect": timestamp is not None}


def _safe_basename(value):
    if (not isinstance(value, str) or not value or len(value) > 255
            or value in (".", "..") or value != os.path.basename(value)
            or "/" in value or "\\" in value
            or any(unicodedata.category(character).startswith("C") for character in value)):
        raise ProtocolError("unsafe shared filename")
    return value


def parse_share_packet(packet):
    """Validate KDE Connect's separate-payload file announcement."""
    body = _receive_envelope(packet, SHARE_TYPE, ("payloadSize", "payloadTransferInfo"))
    integer_metadata = {"creationTime", "lastModified", "numberOfFiles", "totalPayloadSize"}
    if set(body) - ({"filename", "open"} | integer_metadata) or "filename" not in body:
        raise ProtocolError("invalid share body")
    if "open" in body and not isinstance(body["open"], bool):
        raise ProtocolError("invalid share open flag")
    for field in integer_metadata:
        if field in body and (not isinstance(body[field], int) or isinstance(body[field], bool)
                or not 0 <= body[field] <= 2 ** 63 - 1):
            raise ProtocolError("invalid share aggregate metadata")
    size = packet["payloadSize"]
    transfer = packet["payloadTransferInfo"]
    if (not isinstance(size, int) or isinstance(size, bool)
            or not 0 <= size <= MAX_FILE_BYTES):
        raise ProtocolError("invalid share payload size")
    if not isinstance(transfer, dict) or set(transfer) != {"port"}:
        raise ProtocolError("invalid share transfer information")
    port = transfer["port"]
    if (not isinstance(port, int) or isinstance(port, bool)
            or not MIN_TCP_PORT <= port <= MAX_TCP_PORT):
        raise ProtocolError("invalid share payload port")
    return {"name": _safe_basename(body["filename"]), "size": size, "port": port}


def _canonical_integer(value, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        number = int(value)
    else:
        raise ValueError
    if not minimum <= number <= maximum:
        raise ValueError
    return number


def parse_sms_messages(packet, device_id, diagnostics=None):
    """Normalize official SMS-v2 messages, skipping malformed individual rows."""
    if (not isinstance(packet, dict) or set(packet) != {"id", "type", "body"}
            or packet.get("type") != SMS_MESSAGES_TYPE
            or not isinstance(packet.get("id"), int) or isinstance(packet.get("id"), bool)):
        raise ProtocolError("invalid SMS messages envelope")
    body = packet["body"]
    if (not isinstance(body, dict) or set(body) != {"version", "messages"}
            or body.get("version") != 2 or not isinstance(body.get("messages"), list)
            or len(body["messages"]) > MAX_MESSAGES):
        raise ProtocolError("invalid SMS messages body")
    result, skipped = [], 0
    for raw in body["messages"]:
        try:
            allowed = {"_id", "thread_id", "addresses", "body", "date", "type",
                       "read", "event", "sub_id", "attachments"}
            if not isinstance(raw, dict) or set(raw) - allowed:
                raise ValueError
            text = raw.get("body")
            if not isinstance(text, str) or not text:
                raise ValueError
            if len(text) > 5000:
                raise ProtocolError("SMS body exceeds size limit")
            thread_id = _canonical_integer(raw.get("thread_id"), 0, 2 ** 63 - 1)
            occurred = _canonical_integer(raw.get("date"), 1, 2 ** 63 - 1)
            if occurred > int(time.time() * 1000) + 86400000:
                raise ValueError
            message_type = _canonical_integer(raw.get("type"), 1, 6)
            event = _canonical_integer(raw.get("event"), 0, 2 ** 31 - 1)
            read = raw.get("read")
            if not isinstance(read, bool):
                read = bool(_canonical_integer(read, 0, 1))
            if "sub_id" in raw:
                _canonical_integer(raw["sub_id"], 0, 2 ** 31 - 1)
            message_id = (_canonical_integer(raw["_id"], 0, 2 ** 63 - 1)
                          if "_id" in raw else None)
            addresses = raw.get("addresses")
            if not isinstance(addresses, list) or not addresses:
                raise ValueError
            if len(addresses) > MAX_ADDRESSES:
                raise ProtocolError("SMS address list exceeds size limit")
            if (any(not isinstance(item, dict) or set(item) != {"address"}
                           or not isinstance(item["address"], str)
                           or not 1 <= len(item["address"]) <= 320
                           or item["address"] != item["address"].strip()
                           or any(ord(char) < 32 or ord(char) == 127 for char in item["address"])
                           for item in addresses)):
                raise ValueError
            attachments = raw.get("attachments")
            if attachments is not None:
                attachment_keys = {"part_id", "mime_type", "encoded_thumbnail",
                                   "unique_identifier"}
                if not isinstance(attachments, list):
                    raise ValueError
                if len(attachments) > MAX_ATTACHMENTS or any(
                        isinstance(item, dict) and isinstance(item.get("encoded_thumbnail"), str)
                        and len(item["encoded_thumbnail"]) > 256000 for item in attachments):
                    raise ProtocolError("SMS attachment metadata exceeds size limit")
                if (any(not isinstance(item, dict) or set(item) - attachment_keys
                               or not {"part_id", "mime_type", "unique_identifier"} <= set(item)
                               or (lambda part: not isinstance(part, (int, str)) or isinstance(part, bool)
                                   or not re.fullmatch(r"0|[1-9][0-9]*", str(part)))(item["part_id"])
                               or not isinstance(item["mime_type"], str)
                               or not 1 <= len(item["mime_type"]) <= 255
                               or not isinstance(item["unique_identifier"], str)
                               or not 1 <= len(item["unique_identifier"]) <= 512
                               or ("encoded_thumbnail" in item and
                                   not isinstance(item["encoded_thumbnail"], str))
                               for item in attachments)):
                    raise ValueError
            if not event & 0x1:
                skipped += 1
                continue
            if message_type not in (1, 2):
                skipped += 1
                continue
            numbers = list(dict.fromkeys(item["address"] for item in addresses))
            canonical = json.dumps([device_id, str(thread_id), str(occurred),
                str(message_type), numbers, text], ensure_ascii=False,
                separators=(",", ":"), allow_nan=False).encode("utf-8")
            sms_id = str(message_id) if message_id is not None else "h" + sha256(canonical).hexdigest()
            result.append({"id": "%s:%s:%s" % (device_id, thread_id, sms_id),
                           "device_id": device_id, "thread_id": str(thread_id),
                           "sms_id": sms_id, "from": numbers[0],
                            "addresses": numbers, "group": bool(event & 0x2),
                            "text": text, "timestamp_ms": occurred,
                            "incoming": message_type == 1, "read": read})
        except ProtocolError:
            raise
        except (KeyError, TypeError, ValueError):
            skipped += 1
    if diagnostics is not None:
        diagnostics.update(valid=len(result), skipped=skipped)
    return result


def validate_identity(packet, require_tcp=False):
    if not isinstance(packet, dict) or set(packet) - {"id", "type", "body"}:
        raise ProtocolError("invalid identity envelope")
    if (packet.get("type") != "kdeconnect.identity"
            or not isinstance(packet.get("id"), int) or isinstance(packet.get("id"), bool)):
        raise ProtocolError("invalid identity packet")
    body = packet.get("body")
    required = {"deviceId", "deviceName", "deviceType", "protocolVersion",
                "incomingCapabilities", "outgoingCapabilities"}
    allowed = required | {"tcpPort", "targetDeviceId", "targetProtocolVersion"}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - allowed:
        raise ProtocolError("invalid identity body")
    if not isinstance(body["deviceId"], str) or not DEVICE_ID.fullmatch(body["deviceId"]):
        raise ProtocolError("invalid device id")
    if (not isinstance(body["deviceName"], str) or not body["deviceName"].strip()
            or len(body["deviceName"]) > 128 or body["deviceType"] not in
            {"desktop", "laptop", "phone", "smartphone", "tablet", "tv"}):
        raise ProtocolError("invalid device identity")
    if body["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError("KDE Connect protocol v8 is required")
    target_version = body.get("targetProtocolVersion")
    if target_version is not None:
        if (not (isinstance(target_version, int) and not isinstance(target_version, bool)
                 and target_version == PROTOCOL_VERSION)
                and target_version != str(PROTOCOL_VERSION)):
            raise ProtocolError("invalid target protocol version")
        body = dict(body)
        body["targetProtocolVersion"] = PROTOCOL_VERSION
    for field in ("incomingCapabilities", "outgoingCapabilities"):
        values = body[field]
        if (not isinstance(values, list) or len(values) > 512
                or any(not isinstance(item, str) or not item or len(item) > 200
                       for item in values) or len(set(values)) != len(values)):
            raise ProtocolError("invalid capability list")
    if require_tcp or "tcpPort" in body:
        port = body.get("tcpPort")
        if not isinstance(port, int) or isinstance(port, bool) or not MIN_TCP_PORT <= port <= MAX_TCP_PORT:
            raise ProtocolError("invalid KDE Connect TCP port")
    return body


def pairing_code(local_certificate, peer_certificate, timestamp):
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp <= 0:
        raise ProtocolError("invalid pairing timestamp")
    keys = [certificate.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        for certificate in (local_certificate, peer_certificate)]
    keys.sort(reverse=True)
    return sha256(keys[0] + keys[1] + str(timestamp).encode("ascii")).hexdigest()[:8].upper()


def _atomic_write(path, data, mode):
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ipv4_discovery_interfaces():
    """Return active IPv4 source addresses and their optional broadcasts."""
    result = []
    if fcntl is None or not hasattr(socket, "if_nameindex"):
        return (("0.0.0.0", ("255.255.255.255",)),)
    try:
        interfaces = socket.if_nameindex()
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return (("0.0.0.0", ("255.255.255.255",)),)
    try:
        for _index, name in interfaces:
            request = struct.pack("256s", name.encode("utf-8")[:15])
            try:
                flags = struct.unpack("H", fcntl.ioctl(
                    probe.fileno(), SIOCGIFFLAGS, request)[16:18])[0]
                packed = fcntl.ioctl(probe.fileno(), SIOCGIFADDR, request)[20:24]
                source = ipaddress.ip_address(socket.inet_ntoa(packed))
                if not flags & IFF_UP or flags & IFF_LOOPBACK or source.version != 4:
                    continue
                targets = {"255.255.255.255"}
                if flags & IFF_BROADCAST:
                    packed = fcntl.ioctl(probe.fileno(), SIOCGIFBRDADDR, request)[20:24]
                    broadcast = ipaddress.ip_address(socket.inet_ntoa(packed))
                    if broadcast.version == 4:
                        targets.add(str(broadcast))
                result.append((str(source), tuple(sorted(targets))))
            except (OSError, ValueError):
                continue
    finally:
        probe.close()
    return tuple(result) or (("0.0.0.0", ("255.255.255.255",)),)


class IdentityStore:
    def __init__(self, directory, device_name):
        self.directory = os.path.abspath(directory)
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.key_path = os.path.join(self.directory, "identity-key.pem")
        self.cert_path = os.path.join(self.directory, "identity-cert.pem")
        self.identity_path = os.path.join(self.directory, "identity.json")
        self.peers_path = os.path.join(self.directory, "peers.json")
        self.device_name = " ".join(str(device_name or local_device_name()).split())[:128]
        self._lock = threading.RLock()
        self.device_id = self._load_or_create_device_id()
        self._load_or_create_identity()
        self.peers = self._load_peers()

    def _load_or_create_device_id(self):
        if not os.path.exists(self.identity_path):
            _atomic_write(self.identity_path, json.dumps({"deviceId": uuid.uuid4().hex},
                separators=(",", ":")).encode("ascii") + b"\n", 0o600)
        try:
            value = json.loads(open(self.identity_path, encoding="ascii").read(),
                               object_pairs_hook=_no_duplicate_object)
        except (OSError, UnicodeError, ValueError, ProtocolError) as error:
            raise ProtocolError("invalid KDE Connect device identity") from error
        if (not isinstance(value, dict) or set(value) != {"deviceId"}
                or not isinstance(value["deviceId"], str)
                or not DEVICE_ID.fullmatch(value["deviceId"])):
            raise ProtocolError("invalid KDE Connect device identity")
        return value["deviceId"]

    def _load_or_create_identity(self):
        if os.path.exists(self.key_path) != os.path.exists(self.cert_path):
            raise ProtocolError("incomplete KDE Connect identity")
        if not os.path.exists(self.key_path):
            key = ec.generate_private_key(ec.SECP256R1())
            now = datetime.now(timezone.utc)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self.device_id),
                              x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Magnolie Organizer")])
            certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
            _atomic_write(self.key_path, key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), 0o600)
            _atomic_write(self.cert_path, certificate.public_bytes(serialization.Encoding.PEM), 0o644)
        if stat.S_IMODE(os.stat(self.key_path).st_mode) & 0o077:
            raise ProtocolError("KDE Connect identity key permissions are too broad")
        try:
            with open(self.key_path, "rb") as source:
                self.key = serialization.load_pem_private_key(source.read(), None)
            with open(self.cert_path, "rb") as source:
                self.certificate = x509.load_pem_x509_certificate(source.read())
        except (OSError, ValueError) as error:
            raise ProtocolError("invalid KDE Connect identity") from error
        if not isinstance(self.key, ec.EllipticCurvePrivateKey) or not isinstance(self.key.curve, ec.SECP256R1):
            raise ProtocolError("identity key is not EC P-256")
        if self.key.public_key().public_numbers() != self.certificate.public_key().public_numbers():
            raise ProtocolError("identity key and certificate do not match")
        if self.certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value != self.device_id:
            raise ProtocolError("identity certificate has wrong device id")

    def _load_peers(self):
        if not os.path.exists(self.peers_path):
            return {}
        try:
            with open(self.peers_path, encoding="utf-8") as source:
                value = json.loads(source.read(), object_pairs_hook=_no_duplicate_object)
        except (OSError, ValueError, ProtocolError) as error:
            raise ProtocolError("invalid KDE Connect peer store") from error
        if not isinstance(value, dict):
            raise ProtocolError("invalid KDE Connect peer store")
        migrated = False
        for device_id, peer in value.items():
            required = {"name", "certificate", "protocolVersion"}
            optional = {"lastAddress", "lastPort", "lastSeenMs", "paired",
                        "pairingConfirmedMs"}
            if (not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id)
                    or not isinstance(peer, dict) or not required <= set(peer)
                    or set(peer) - required - optional or peer["protocolVersion"] != 8
                    or not isinstance(peer["name"], str) or len(peer["name"]) > 128
                    or not isinstance(peer.get("paired", False), bool)
                    or ("pairingConfirmedMs" in peer) != (peer.get("paired") is True)):
                raise ProtocolError("invalid KDE Connect peer entry")
            endpoint = {"lastAddress", "lastPort", "lastSeenMs"}
            if set(peer) & endpoint and not endpoint <= set(peer):
                raise ProtocolError("invalid KDE Connect peer entry")
            if endpoint <= set(peer):
                try:
                    address = ipaddress.ip_address(peer["lastAddress"])
                except (TypeError, ValueError) as error:
                    raise ProtocolError("invalid stored peer address") from error
                if (address.version != 4 or not (address.is_private or address.is_loopback)
                        or str(address) != peer["lastAddress"]
                        or not isinstance(peer["lastPort"], int)
                        or isinstance(peer["lastPort"], bool)
                        or not MIN_TCP_PORT <= peer["lastPort"] <= MAX_TCP_PORT
                        or not isinstance(peer["lastSeenMs"], int)
                        or isinstance(peer["lastSeenMs"], bool)
                        or not 0 < peer["lastSeenMs"] <= 2 ** 63 - 1):
                    raise ProtocolError("invalid stored peer endpoint")
            try:
                certificate = x509.load_pem_x509_certificate(peer["certificate"].encode("ascii"))
                _validate_peer_certificate(certificate, device_id)
            except (AttributeError, TypeError, ValueError) as error:
                raise ProtocolError("invalid stored peer certificate") from error
            if "paired" not in peer:
                peer["paired"] = False
                migrated = True
            if peer["paired"] and (not isinstance(peer["pairingConfirmedMs"], int)
                    or isinstance(peer["pairingConfirmedMs"], bool)
                    or not 0 < peer["pairingConfirmedMs"] <= 2 ** 63 - 1):
                raise ProtocolError("invalid pairing confirmation time")
        if migrated:
            self._write_peers(value)
        return value

    def _write_peers(self, peers=None):
        value = self.peers if peers is None else peers
        _atomic_write(self.peers_path, json.dumps(value, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n", 0o600)
        if peers is not None:
            self.peers = peers

    def save_peer(self, device_id, name, certificate, address=None, port=None):
        """Pin a certificate for TLS; this does not prove mutual pairing."""
        _validate_peer_certificate(certificate, device_id)
        with self._lock:
            peers = dict(self.peers)
            peers[device_id] = {"name": str(name)[:128], "protocolVersion": 8,
                "certificate": certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
                "paired": False}
            if address is not None:
                try:
                    parsed = ipaddress.ip_address(address)
                except (TypeError, ValueError) as error:
                    raise ProtocolError("invalid authenticated peer address") from error
                if (parsed.version != 4 or not (parsed.is_private or parsed.is_loopback)
                        or not isinstance(port, int) or isinstance(port, bool)
                        or not MIN_TCP_PORT <= port <= MAX_TCP_PORT):
                    raise ProtocolError("invalid authenticated peer endpoint")
                peers[device_id].update(lastAddress=str(parsed), lastPort=port,
                    lastSeenMs=int(time.time() * 1000))
            self._write_peers(peers)

    def confirm_peer_and_cleanup(self, device_id, name, certificate, address, port,
                                 connected_ids=()):
        _validate_peer_certificate(certificate, device_id)
        try:
            parsed = ipaddress.ip_address(address)
        except (TypeError, ValueError) as error:
            raise ProtocolError("invalid authenticated peer address") from error
        if (parsed.version != 4 or not (parsed.is_private or parsed.is_loopback)
                or not isinstance(port, int) or isinstance(port, bool)
                or not MIN_TCP_PORT <= port <= MAX_TCP_PORT):
            raise ProtocolError("invalid authenticated peer endpoint")
        certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
        with self._lock:
            peers = dict(self.peers)
            now = int(time.time() * 1000)
            peers[device_id] = {"name": str(name)[:128], "protocolVersion": 8,
                "certificate": certificate_pem, "paired": True,
                "pairingConfirmedMs": now, "lastAddress": str(parsed),
                "lastPort": port, "lastSeenMs": now}
            for old_id, old in list(peers.items()):
                if (old_id != device_id and old_id not in connected_ids
                        and old.get("name") == peers[device_id]["name"]
                        and old.get("certificate") != certificate_pem):
                    peers.pop(old_id)
            self._write_peers(peers)

    def mark_unpaired(self, device_id):
        with self._lock:
            if device_id not in self.peers:
                return
            peers = dict(self.peers)
            peers[device_id] = dict(peers[device_id], paired=False)
            peers[device_id].pop("pairingConfirmedMs", None)
            self._write_peers(peers)

    def update_endpoint(self, device_id, address, port, write=True):
        try:
            parsed = ipaddress.ip_address(address)
        except (TypeError, ValueError) as error:
            raise ProtocolError("invalid authenticated peer address") from error
        if (parsed.version != 4 or not (parsed.is_private or parsed.is_loopback)
                or not isinstance(port, int) or isinstance(port, bool)
                or not MIN_TCP_PORT <= port <= MAX_TCP_PORT):
            raise ProtocolError("invalid authenticated peer endpoint")
        with self._lock:
            if device_id not in self.peers:
                raise ProtocolError("KDE Connect peer is not paired")
            self.peers[device_id].update(lastAddress=str(parsed), lastPort=port,
                lastSeenMs=int(time.time() * 1000))
            if write:
                self._write_peers()

    def remove_peer(self, device_id):
        with self._lock:
            if device_id not in self.peers:
                raise ProtocolError("KDE Connect peer is not paired")
            peers = dict(self.peers)
            peers.pop(device_id)
            self._write_peers(peers)


def _validate_peer_certificate(certificate, device_id):
    now = datetime.now(timezone.utc)
    if hasattr(certificate, "not_valid_before_utc"):
        before, after = certificate.not_valid_before_utc, certificate.not_valid_after_utc
    else:
        before = certificate.not_valid_before.replace(tzinfo=timezone.utc)
        after = certificate.not_valid_after.replace(tzinfo=timezone.utc)
    if before > now or after < now or certificate.subject != certificate.issuer:
        raise ProtocolError("peer certificate is not a current self-signed certificate")
    names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(names) != 1 or names[0].value != device_id:
        raise ProtocolError("certificate device id does not match identity")
    public_key = certificate.public_key()
    try:
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            if public_key.key_size < 256:
                raise ProtocolError("peer EC key is too small")
            public_key.verify(certificate.signature, certificate.tbs_certificate_bytes,
                              ec.ECDSA(certificate.signature_hash_algorithm))
        elif isinstance(public_key, rsa.RSAPublicKey):
            if public_key.key_size < 2048:
                raise ProtocolError("peer RSA key is too small")
            public_key.verify(certificate.signature, certificate.tbs_certificate_bytes,
                              padding.PKCS1v15(), certificate.signature_hash_algorithm)
        else:
            raise ProtocolError("unsupported peer public key")
    except Exception as error:
        if isinstance(error, ProtocolError):
            raise
        raise ProtocolError("peer certificate signature is invalid") from error


@dataclass(frozen=True)
class DiscoveredDevice:
    address: str
    port: int
    identity: dict


class _TLSStream:
    def __init__(self, connection, timeout=8, raw=None):
        self.connection = connection
        self.timeout = timeout
        self.raw = raw
        self.closed = False

    def _call(self, operation, *args):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                return operation(*args)
            except SSL.WantReadError:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([self.connection], [], [], remaining)[0]:
                    raise TimeoutError("KDE Connect TLS read timed out") from None
            except SSL.WantWriteError:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.connection], [], remaining)[1]:
                    raise TimeoutError("KDE Connect TLS write timed out") from None

    def handshake(self):
        self._call(self.connection.do_handshake)

    def recv(self, size):
        try:
            return self._call(self.connection.recv, size)
        except SSL.ZeroReturnError:
            return b""

    def sendall(self, data):
        view = memoryview(data)
        while view:
            sent = self._call(self.connection.send, view)
            if sent <= 0:
                raise ProtocolError("KDE Connect TLS write failed")
            view = view[sent:]

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.connection.setblocking(False)
            self.connection.shutdown()
        except Exception:  # noqa: S110 - TLS shutdown is best effort.
            pass
        if self.raw is not None:
            try:
                self.raw.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            self.connection.close()
        except Exception:  # noqa: S110 - Closing an already failed TLS stream is best effort.
            pass
        if self.raw is not None:
            try:
                self.raw.close()
            except OSError:
                pass


class _ConnectionWorker:
    """The only reader and writer for one TLS connection."""
    def __init__(self, backend, connection, identity):
        self.backend = backend
        self.connection = connection
        self.identity = identity
        self.outgoing = queue.Queue(maxsize=128)
        self.stopped = threading.Event()
        self.bootstrap = True
        self.bootstrap_requested = set()
        self.bootstrap_responded = set()
        self.bootstrap_buffered = {}
        self.bootstrap_started = 0.0
        self.bootstrap_quiet_deadline = 0.0
        self.bootstrap_deadline = 0.0
        self.sms_started = False
        self.seen = set()
        self.seen_order = deque()
        self.sms_read_states = {}
        self.read_buffer = bytearray()
        self.contacts_lock = threading.Lock()
        self.contacts_condition = threading.Condition()
        self.contacts_pending = None
        self.diagnostics = {"last_packet_type": "", "parse_valid": 0,
            "parse_skipped": 0, "last_receive_ms": 0, "bootstrap_state": "idle"}
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name="kdeconnect-" + identity["deviceId"][:8])

    def start(self):
        self.thread.start()
        if self.backend._is_confirmed(self.identity["deviceId"]):
            self.enable_sms()

    def enable_sms(self):
        if self.sms_started:
            return
        self.sms_started = True
        capabilities = self.identity["incomingCapabilities"]
        if SMS_REQUEST_CONVERSATIONS_TYPE in capabilities:
            self.send(request_conversations_packet())
            now = self.backend.clock()
            self.bootstrap_started = now
            self.bootstrap_quiet_deadline = now + SMS_BOOTSTRAP_QUIET
            self.bootstrap_deadline = now + SMS_BOOTSTRAP_MAX
            self.diagnostics["bootstrap_state"] = "collecting"
        else:
            self.bootstrap = False
            self.diagnostics["bootstrap_state"] = "live"

    def send(self, packet):
        if self.stopped.is_set():
            raise ProtocolError("KDE Connect connection is closed")
        try:
            self.outgoing.put_nowait(packet)
        except queue.Full as error:
            raise ProtocolError("KDE Connect output queue is full") from error

    def close(self, join=False):
        self.stopped.set()
        with self.contacts_condition:
            self.contacts_condition.notify_all()
        self.connection.close()
        if (join and self.thread is not threading.current_thread()
                and self.thread.is_alive()):
            self.thread.join(1)

    def _run(self):
        try:
            while not self.stopped.is_set():
                while True:
                    try:
                        packet = self.outgoing.get_nowait()
                    except queue.Empty:
                        break
                    self.connection.sendall(encode_packet(packet))
                pending = getattr(self.connection.connection, "pending", lambda: 0)()
                readable = (b"\n" in self.read_buffer or pending or
                    select.select([self.connection.connection], [], [], 0.25)[0])
                if not readable:
                    self._check_bootstrap_deadline()
                    continue
                limit = MAX_CONTACT_PACKET if self.backend._is_confirmed(self.identity["deviceId"]) else MAX_PACKET
                packet = read_packet(self.connection, limit, self.read_buffer)
                if packet.get("type") in (CONTACT_UIDS_RESPONSE, CONTACT_VCARDS_RESPONSE):
                    with self.contacts_condition:
                        pending_contact = self.contacts_pending
                        if pending_contact and pending_contact["type"] == packet.get("type"):
                            pending_contact["body"] = packet.get("body")
                            self.contacts_condition.notify_all()
                    self._check_bootstrap_deadline()
                    continue
                if packet.get("type") == "kdeconnect.pair":
                    self.backend._pair_packet(self, packet)
                    continue
                if packet.get("type") in (CLIPBOARD_TYPE, CLIPBOARD_CONNECT_TYPE,
                                           SHARE_TYPE):
                    self.backend._handle_receive_packet(self, packet)
                    continue
                if packet.get("type") != SMS_MESSAGES_TYPE or not self.sms_started:
                    continue
                self._handle_sms_packet(packet)
        except Exception:  # noqa: S110 - A failed connection worker terminates silently.
            pass
        finally:
            self.stopped.set()
            with self.contacts_condition:
                self.contacts_condition.notify_all()
            self.backend._worker_died(self.identity["deviceId"], self)

    def contact_request(self, kind, body, response_type, timeout=5):
        """One bounded, read-only contact request; the TLS loop stays responsive."""
        if (kind not in self.identity["incomingCapabilities"] or
                response_type not in self.identity["outgoingCapabilities"]):
            raise ProtocolError("Contact export is unavailable on the paired phone")
        with self.contacts_lock:
            if self.stopped.is_set() or not self.backend._is_confirmed(self.identity["deviceId"]):
                raise ProtocolError("Contact source is no longer paired")
            pending = {"type": response_type}
            deadline = time.monotonic() + timeout
            with self.contacts_condition:
                self.contacts_pending = pending
                try:
                    self.send(network_packet(kind, body))
                    while "body" not in pending and not self.stopped.is_set():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ProtocolError("Contact export timed out; check contact access on the phone")
                        self.contacts_condition.wait(remaining)
                    if self.stopped.is_set() or not self.backend._is_confirmed(self.identity["deviceId"]):
                        raise ProtocolError("Contact source disconnected")
                    result = pending.get("body")
                    if not isinstance(result, dict):
                        raise ProtocolError("Invalid contact export response")
                    return result
                finally:
                    self.contacts_pending = None

    def _check_bootstrap_deadline(self, now=None):
        if not self.bootstrap or not self.bootstrap_started:
            return
        now = self.backend.clock() if now is None else now
        complete = (self.bootstrap_requested <= self.bootstrap_responded
                    and now >= self.bootstrap_quiet_deadline)
        if complete or now >= self.bootstrap_deadline:
            self._finish_bootstrap()

    def _remember_seen(self, message_id):
        if message_id in self.seen:
            return False
        self.seen.add(message_id)
        self.seen_order.append(message_id)
        while len(self.seen_order) > 10000:
            oldest = self.seen_order.popleft()
            self.seen.discard(oldest)
            self.sms_read_states.pop(oldest, None)
        return True

    def _deliver_message(self, message, notify=False):
        message_id = message["id"]
        current_read = message["read"]
        previous_read = self.sms_read_states.get(message_id)
        fresh = self._remember_seen(message_id)
        self.sms_read_states[message_id] = current_read
        if fresh:
            self.backend._deliver_sms(message, notify=notify)
            return True
        if previous_read is not None and previous_read != current_read:
            self.backend._deliver_sms(message, notify=False)
            return True
        return False

    def _deliver_messages(self, messages):
        handled = set()
        for message in messages:
            if message["id"] not in handled:
                self._deliver_message(message, notify=False)
                handled.add(message["id"])

    def _finish_bootstrap(self):
        for messages in self.bootstrap_buffered.values():
            self._deliver_messages(messages)
        self.bootstrap_buffered.clear()
        self.bootstrap = False
        self.diagnostics["bootstrap_state"] = "live"

    def transfer_sms_state(self, previous):
        """Preserve bootstrap and dedupe state across an active link swap."""
        self.sms_started = previous.sms_started
        self.bootstrap = previous.bootstrap
        self.bootstrap_requested = set(previous.bootstrap_requested)
        self.bootstrap_responded = set(previous.bootstrap_responded)
        self.bootstrap_buffered = {
            thread_id: list(messages)
            for thread_id, messages in previous.bootstrap_buffered.items()}
        self.bootstrap_started = previous.bootstrap_started
        self.bootstrap_quiet_deadline = previous.bootstrap_quiet_deadline
        self.bootstrap_deadline = previous.bootstrap_deadline
        self.seen = set(previous.seen)
        self.seen_order = deque(previous.seen_order)
        self.sms_read_states = dict(previous.sms_read_states)
        self.diagnostics.update(previous.diagnostics)
        if not self.sms_started:
            return
        pending = self.bootstrap_requested - self.bootstrap_responded
        if self.bootstrap and pending:
            for thread_id in sorted(pending, key=int):
                self.send(request_conversation_packet(int(thread_id)))
        elif self.bootstrap:
            self.send(request_conversations_packet())

    def _handle_sms_packet(self, packet):
        stats = {}
        messages = parse_sms_messages(packet, self.identity["deviceId"], stats)
        now = self.backend.clock()
        self.diagnostics.update(last_packet_type=SMS_MESSAGES_TYPE,
            parse_valid=stats["valid"], parse_skipped=stats["skipped"],
            last_receive_ms=int(time.time() * 1000))
        grouped = {}
        for message in messages:
            grouped.setdefault(message["thread_id"], []).append(message)
        if not self.bootstrap:
            pending = self.bootstrap_requested - self.bootstrap_responded
            for thread_id, thread_messages in grouped.items():
                history_response = thread_id in pending
                if history_response:
                    self.bootstrap_responded.add(thread_id)
                handled = set()
                for message in thread_messages:
                    if message["id"] not in handled:
                        self._deliver_message(message,
                            notify=not history_response and not message["read"])
                        handled.add(message["id"])
            return

        full_history = SMS_REQUEST_CONVERSATION_TYPE in self.identity[
            "incomingCapabilities"]
        for thread_id, thread_messages in grouped.items():
            pending = thread_id in (self.bootstrap_requested - self.bootstrap_responded)
            if full_history and pending:
                self.bootstrap_responded.add(thread_id)
                self.bootstrap_buffered.pop(thread_id, None)
                self._deliver_messages(thread_messages)
            elif full_history and thread_id not in self.bootstrap_requested:
                buffered = self.bootstrap_buffered.setdefault(thread_id, [])
                buffered_ids = {message["id"] for message in buffered}
                buffered.extend(message for message in thread_messages
                                if message["id"] not in buffered_ids)
                self.bootstrap_quiet_deadline = now + SMS_BOOTSTRAP_QUIET
                self.send(request_conversation_packet(int(thread_id)))
                self.bootstrap_requested.add(thread_id)
            else:
                self.bootstrap_responded.add(thread_id)
                self._deliver_messages(thread_messages)
        self.diagnostics["bootstrap_state"] = "waiting_threads"
        self._check_bootstrap_deadline(now)


class KDEConnectSMSBackend:
    def __init__(self, directory, device_name=None, socket_factory=None,
                 callback=None, tcp_ports=None, udp_port=UDP_PORT, backoff=None,
                 clock=None):
        self.store = IdentityStore(directory, device_name)
        self.socket_factory = socket_factory or socket.socket
        self.callback = callback or (lambda _event, _payload: None)
        self.tcp_ports = tuple(tcp_ports or range(MIN_TCP_PORT, MAX_TCP_PORT + 1))
        self.udp_port = int(udp_port)
        self.backoff = tuple(backoff or RECONNECT_BACKOFF)
        self.clock = clock or time.monotonic
        self.pairing = None
        self._pairing_pending = False
        self._state_lock = threading.RLock()
        self._devices_changed = threading.Condition(self._state_lock)
        self._connection_lock = threading.RLock()
        self._connections = {}
        self._connection_generation = 0
        self._devices = {}
        self._pending = {}
        self._accepted = set()
        self._handshakes = set()
        self._handlers = set()
        self._connecting = set()
        self._listener = None
        self._udp = None
        self._wake_read = None
        self._wake_write = None
        self._service_thread = None
        self._stop_event = threading.Event()
        self._next_broadcast = 0
        self._last_broadcast = float("-inf")
        self._backoff_index = 0
        self._pairing_failures = {}
        self._repair_prompts = set()
        self._pair_prompt_seen = {}
        self._receive_settings = {"clipboard_enabled": False, "file_enabled": False,
            "device_id": "", "clipboard_mode": "confirm", "file_mode": "confirm",
            "download_directory": ""}
        self._receive_pending = {}
        self._receive_slots = 0
        self._clipboard_connect_seen = {}
        self._transfer_queue = queue.Queue()
        self._transfer_thread = None
        self._transfer_stop = threading.Event()
        self._payload_active = None
        self._staging_directory = ""
        self.listening = False
        self.listen_port = None
        self.reason = "not_started"

    def _emit(self, event, payload):
        try:
            self.callback(event, payload)
        except Exception:  # noqa: S110 - Client callbacks cannot break the transport service.
            pass

    def configure_receive(self, *, clipboard_enabled=False, file_enabled=False,
                          device_id=None, clipboard_mode="confirm", file_mode="confirm",
                          download_directory=None):
        """Configure opt-in receive features for one explicitly paired device."""
        if not isinstance(clipboard_enabled, bool) or not isinstance(file_enabled, bool):
            raise ValueError("receive feature flags must be booleans")
        if clipboard_mode not in ("confirm", "automatic") or file_mode not in (
                "confirm", "automatic"):
            raise ValueError("receive mode must be confirm or automatic")
        enabled = clipboard_enabled or file_enabled
        if enabled:
            if (not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id)
                    or not self._is_confirmed(device_id)):
                raise ValueError("receive device must be an explicitly paired device")
        elif device_id not in (None, ""):
            raise ValueError("disabled receive features cannot select a device")
        download = ""
        if file_enabled:
            if (not isinstance(download_directory, str)
                    or not os.path.isabs(download_directory)
                    or not os.path.isdir(download_directory)
                    or os.path.realpath(download_directory) != download_directory):
                raise ValueError("download directory must be an absolute existing real directory")
            download = download_directory
            staging = os.path.join(download, ".magnolie-kdeconnect-staging")
            try:
                os.mkdir(staging, 0o700)
            except FileExistsError:
                details = os.lstat(staging)
                if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                    raise ValueError("receive staging path is not a directory")
            os.chmod(staging, 0o700)
        else:
            if download_directory not in (None, ""):
                raise ValueError("download directory is only valid when file receive is enabled")
            staging = ""
        self._stop_receive()
        with self._state_lock:
            self._receive_settings = {"clipboard_enabled": clipboard_enabled,
                "file_enabled": file_enabled, "device_id": device_id or "",
                "clipboard_mode": clipboard_mode, "file_mode": file_mode,
                "download_directory": download}
            self._staging_directory = staging
            self._transfer_stop.clear()
        self._cleanup_staging()
        self._reschedule_discovery()
        return dict(self._receive_settings)

    def _cleanup_staging(self):
        directory = self._staging_directory
        if not directory or not os.path.isdir(directory):
            return
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    os.unlink(entry.path)
            except OSError:
                pass

    def _new_receive_id(self):
        return uuid.uuid4().hex

    def _reserve_receive(self):
        with self._state_lock:
            if self._receive_slots >= MAX_RECEIVE_PENDING:
                return False
            self._receive_slots += 1
            return True

    def _release_receive(self):
        with self._state_lock:
            self._receive_slots = max(0, self._receive_slots - 1)

    def _handle_receive_packet(self, worker, packet):
        device_id = worker.identity["deviceId"]
        with self._state_lock:
            settings = dict(self._receive_settings)
        if device_id != settings["device_id"] or not self._is_confirmed(device_id):
            return
        kind = packet.get("type")
        if kind in (CLIPBOARD_TYPE, CLIPBOARD_CONNECT_TYPE):
            if not settings["clipboard_enabled"]:
                return
            parsed = parse_clipboard_packet(packet)
            if parsed["connect"]:
                with self._state_lock:
                    previous = self._clipboard_connect_seen.get(device_id, -1)
                    if parsed["timestamp"] == 0 or parsed["timestamp"] <= previous:
                        return
                    self._clipboard_connect_seen[device_id] = parsed["timestamp"]
            receive_id = self._new_receive_id()
            value = {"id": receive_id, "device_id": device_id, "text": parsed["text"],
                     "timestamp_ms": parsed["timestamp"]}
            if settings["clipboard_mode"] == "automatic":
                self._emit("clipboard_apply", value)
            elif self._reserve_receive():
                with self._state_lock:
                    self._receive_pending[receive_id] = {"kind": "clipboard",
                        "device_id": device_id, "text": parsed["text"],
                        "timestamp_ms": parsed["timestamp"],
                        "deadline": self.clock() + RECEIVE_PROPOSAL_SECONDS}
                self._emit("clipboard_proposal", value)
            return
        if kind != SHARE_TYPE or not settings["file_enabled"]:
            return
        parsed = parse_share_packet(packet)
        if not self._reserve_receive():
            return
        with self._connection_lock:
            entry = self._connections.get(device_id)
            address = entry.get("address") if entry and entry.get("worker") is worker else None
        if not address:
            self._release_receive()
            return
        task = dict(parsed, device_id=device_id, address=address,
                    mode=settings["file_mode"], id=self._new_receive_id())
        self._transfer_queue.put(task)
        self._ensure_transfer_worker()

    def _ensure_transfer_worker(self):
        with self._state_lock:
            if self._transfer_thread and self._transfer_thread.is_alive():
                return
            self._transfer_stop.clear()
            self._transfer_thread = threading.Thread(target=self._transfer_loop,
                daemon=True, name="kdeconnect-payload")
            self._transfer_thread.start()

    def _transfer_loop(self):
        while not self._transfer_stop.is_set():
            try:
                task = self._transfer_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            staged = None
            try:
                staged = self._download_payload(task)
                if self._transfer_stop.is_set():
                    raise ProtocolError("receive service stopped")
                pending = dict(task, kind="file", staged=staged,
                               deadline=self.clock() + RECEIVE_PROPOSAL_SECONDS)
                if task["mode"] == "automatic":
                    path = self._accept_file(pending)
                    self._release_receive()
                    self._emit("file_ready", {"id": task["id"],
                        "device_id": task["device_id"], "name": os.path.basename(path),
                        "size": task["size"], "path": path})
                else:
                    with self._state_lock:
                        self._receive_pending[task["id"]] = pending
                    self._emit("file_proposal", {"id": task["id"],
                        "device_id": task["device_id"], "name": task["name"],
                        "size": task["size"]})
                    staged = None
            except Exception:
                self._release_receive()
                self._emit("receive_error", {"id": task["id"], "kind": "file",
                    "device_id": task["device_id"], "name": task["name"]})
            finally:
                if staged:
                    try:
                        os.unlink(staged)
                    except FileNotFoundError:
                        pass

    def _download_payload(self, task):
        directory = self._staging_directory
        if not directory:
            raise ProtocolError("file receive is not configured")
        fd, path = tempfile.mkstemp(prefix="incoming-", dir=directory)
        stream = None
        try:
            os.fchmod(fd, 0o600)
            stream = self._payload_tls_connection(task["device_id"], task["address"], task["port"])
            with self._state_lock:
                self._payload_active = stream
            remaining = task["size"]
            with os.fdopen(fd, "wb") as output:
                fd = -1
                while remaining:
                    part = stream.recv(min(65536, remaining))
                    if not part:
                        raise ProtocolError("payload ended before advertised size")
                    output.write(part)
                    remaining -= len(part)
                if stream.recv(1):
                    raise ProtocolError("payload exceeds advertised size")
                output.flush()
                os.fsync(output.fileno())
            return path
        except Exception:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            raise
        finally:
            if fd >= 0:
                os.close(fd)
            if stream is not None:
                stream.close()
            with self._state_lock:
                if self._payload_active is stream:
                    self._payload_active = None

    def _payload_tls_connection(self, device_id, address, port):
        if SSL is None:
            raise RuntimeError("PyOpenSSL is required for KDE Connect payloads")
        peer = self.store.peers.get(device_id)
        if not peer or peer.get("paired") is not True:
            raise ProtocolError("payload peer is not paired")
        expected = x509.load_pem_x509_certificate(peer["certificate"].encode("ascii"))
        context = SSL.Context(SSL.TLS_CLIENT_METHOD)
        context.set_min_proto_version(SSL.TLS1_2_VERSION)
        context.set_options(SSL.OP_NO_COMPRESSION)
        context.use_privatekey(crypto.load_privatekey(crypto.FILETYPE_PEM,
            self.store.key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption())))
        context.use_certificate(crypto.load_certificate(crypto.FILETYPE_PEM,
            self.store.certificate.public_bytes(serialization.Encoding.PEM)))
        context.check_privatekey()

        def verify(_connection, certificate, _error, depth, _preverified):
            if depth != 0:
                return False
            try:
                candidate = x509.load_der_x509_certificate(crypto.dump_certificate(
                    crypto.FILETYPE_ASN1, certificate))
                _validate_peer_certificate(candidate, device_id)
                return candidate.fingerprint(hashes.SHA256()) == expected.fingerprint(hashes.SHA256())
            except (ProtocolError, ValueError):
                return False

        context.set_verify(SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT, verify)
        raw = socket.create_connection((address, port), timeout=3)
        raw.settimeout(8)
        connection = SSL.Connection(context, raw)
        connection.set_connect_state()
        stream = _TLSStream(connection, timeout=8, raw=raw)
        try:
            stream.handshake()
            certificate = x509.load_der_x509_certificate(crypto.dump_certificate(
                crypto.FILETYPE_ASN1, connection.get_peer_certificate()))
            if certificate.fingerprint(hashes.SHA256()) != expected.fingerprint(hashes.SHA256()):
                raise ProtocolError("payload peer certificate pin changed")
            return stream
        except Exception:
            stream.close()
            raise

    def _accept_file(self, pending, directory=None):
        directory = directory or self._receive_settings["download_directory"]
        if not directory:
            raise ProtocolError("file receive is no longer configured")
        if (not isinstance(directory, str) or not os.path.isabs(directory)
                or not os.path.isdir(directory)
                or os.path.realpath(directory) != directory):
            raise ProtocolError("file receive destination is invalid")
        stem, suffix = os.path.splitext(pending["name"])
        for number in range(10000):
            name = pending["name"] if number == 0 else "%s (%d)%s" % (stem, number, suffix)
            destination = os.path.join(directory, name)
            try:
                os.link(pending["staged"], destination)
                os.unlink(pending["staged"])
                os.chmod(destination, 0o600)
                return destination
            except FileExistsError:
                continue
        raise ProtocolError("no collision-safe download filename is available")

    def accept_receive(self, receive_id, directory=None):
        if not isinstance(receive_id, str) or not re.fullmatch(r"[0-9a-f]{32}", receive_id):
            raise ValueError("invalid receive id")
        with self._state_lock:
            pending = self._receive_pending.pop(receive_id, None)
        if pending is None:
            raise ProtocolError("receive proposal does not exist")
        completed = False
        try:
            if pending["kind"] == "clipboard":
                value = {"id": receive_id, "device_id": pending["device_id"],
                         "text": pending["text"]}
                self._emit("clipboard_apply", value)
                completed = True
                return dict(value, kind="clipboard")
            path = self._accept_file(pending, directory)
            value = {"id": receive_id, "device_id": pending["device_id"],
                "name": os.path.basename(path), "size": pending["size"], "path": path}
            self._emit("file_ready", value)
            completed = True
            return dict(value, kind="file")
        finally:
            if completed:
                self._release_receive()
            else:
                with self._state_lock:
                    self._receive_pending[receive_id] = pending

    def reject_receive(self, receive_id):
        if not isinstance(receive_id, str) or not re.fullmatch(r"[0-9a-f]{32}", receive_id):
            raise ValueError("invalid receive id")
        with self._state_lock:
            pending = self._receive_pending.pop(receive_id, None)
        if pending is None:
            raise ProtocolError("receive proposal does not exist")
        if pending.get("staged"):
            try:
                os.unlink(pending["staged"])
            except FileNotFoundError:
                pass
        self._release_receive()
        return {"id": receive_id, "state": "rejected", "kind": pending["kind"]}

    def start(self):
        with self._state_lock:
            if self._service_thread and self._service_thread.is_alive():
                return True
            if SSL is None:
                self.reason = "pyopenssl_missing"
                return False
            listener = udp = wake_read = wake_write = None
            try:
                listener, port = self._open_listener()
                udp = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
                # UDP 1716 is deliberately exclusive. SO_REUSEADDR here could
                # divert identities from an already running KDE Connect daemon.
                udp.bind(("", self.udp_port))
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                udp.setblocking(False)
                wake_read, wake_write = socket.socketpair()
                wake_read.setblocking(False)
                wake_write.setblocking(False)
            except (OSError, ProtocolError):
                for opened in (listener, udp, wake_read, wake_write):
                    if opened is not None:
                        opened.close()
                self.listening = False
                self.listen_port = None
                self.reason = "udp_port_unavailable" if listener is not None else "tcp_ports_unavailable"
                return False
            self._listener, self._udp = listener, udp
            self._wake_read, self._wake_write = wake_read, wake_write
            self.listen_port = port
            self.listening = True
            self.reason = ""
            self._stop_event.clear()
            self._backoff_index = 0
            self._next_broadcast = self.clock()
            self._service_thread = threading.Thread(
                target=self._service_loop, daemon=True, name="kdeconnect-listener")
            self._service_thread.start()
            return True

    def stop(self):
        self._stop_receive()
        with self._state_lock:
            thread = self._service_thread
            if thread is None:
                self.listening = False
                return
            self._stop_event.set()
            self._wake()
        if thread is not threading.current_thread():
            thread.join(10)
        with self._state_lock:
            handlers = list(self._handlers)
            pending = list(self._pending)
            accepted = list(self._accepted)
            handshakes = list(self._handshakes)
            self.pairing = None
            self._pairing_pending = False
            connections = list(self._connections.values())
            self._connections.clear()
            self._connecting.clear()
            for opened in (self._listener, self._udp, self._wake_read, self._wake_write):
                if opened is not None:
                    try:
                        opened.close()
                    except OSError:
                        pass
            for raw in set(pending + accepted + handshakes):
                raw.close()
            self._pending.clear()
            self._accepted.clear()
            self._handshakes.clear()
            self._listener = self._udp = self._wake_read = self._wake_write = None
            self._service_thread = None
            self.listening = False
            self.listen_port = None
            self.reason = "stopped"
        for entry in connections:
            entry["worker"].close()
        for entry in connections:
            if entry["worker"].thread.is_alive():
                entry["worker"].thread.join(9)
        for handler in handlers:
            if handler is not threading.current_thread():
                handler.join(9)

    def _stop_receive(self):
        self._transfer_stop.set()
        with self._state_lock:
            active = self._payload_active
        if active is not None:
            active.close()
        thread = self._transfer_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(10)
        with self._state_lock:
            staged = [item.get("staged") for item in self._receive_pending.values()]
            self._receive_pending.clear()
            self._receive_slots = 0
            self._transfer_thread = None
            self._payload_active = None
            while True:
                try:
                    self._transfer_queue.get_nowait()
                except queue.Empty:
                    break
        for path in staged:
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
        self._cleanup_staging()

    def _wake(self):
        try:
            self._wake_write.send(b"x")
        except (AttributeError, BlockingIOError, OSError):
            pass

    def _service_loop(self):
        try:
            while not self._stop_event.is_set():
                now = self.clock()
                self._expire_state(now)
                if now >= self._next_broadcast:
                    self._broadcast_due(now)
                with self._state_lock:
                    sockets = [self._udp, self._listener, self._wake_read] + list(self._pending)
                    timeout = max(0.05, min(1.0, self._next_broadcast - self.clock()))
                try:
                    readable = select.select([item for item in sockets if item], [], [], timeout)[0]
                except (OSError, ValueError):
                    if self._stop_event.is_set():
                        break
                    continue
                for source in readable:
                    if source is self._wake_read:
                        try:
                            source.recv(4096)
                        except (BlockingIOError, OSError):
                            pass
                    elif source is self._udp:
                        self._receive_udp_identity(source)
                    elif source is self._listener:
                        self._accept_tcp()
                    else:
                        self._receive_tcp_identity(source)
        finally:
            with self._state_lock:
                self.listening = False

    def _expire_state(self, now):
        expired_pairing = None
        expired_receive = []
        with self._state_lock:
            for raw, value in list(self._pending.items()):
                if value[2] <= now:
                    self._pending.pop(raw, None)
                    raw.close()
            for device_id, (_device, _last_seen, deadline) in list(self._devices.items()):
                if deadline <= now and not self._is_confirmed(device_id):
                    with self._connection_lock:
                        entry = self._connections.get(device_id)
                        active = entry is not None and self._worker_alive(entry["worker"])
                    if not active:
                        self._devices.pop(device_id, None)
            for key, deadline in list(self._pair_prompt_seen.items()):
                if deadline <= now:
                    self._pair_prompt_seen.pop(key, None)
            if self.pairing and self.pairing["deadline"] <= now:
                expired_pairing, self.pairing = self.pairing, None
            for receive_id, pending in list(self._receive_pending.items()):
                if pending.get("deadline", now + 1) <= now:
                    expired_receive.append((receive_id, pending))
                    self._receive_pending.pop(receive_id, None)
                    self._receive_slots = max(0, self._receive_slots - 1)
        for receive_id, pending in expired_receive:
            if pending.get("staged"):
                try:
                    os.unlink(pending["staged"])
                except FileNotFoundError:
                    pass
            self._emit("receive_expired", {"id": receive_id,
                "kind": pending["kind"], "device_id": pending["device_id"]})
        if expired_pairing:
            try:
                expired_pairing["worker"].send(network_packet(
                    "kdeconnect.pair", {"pair": False}))
            except Exception:  # noqa: S110 - The expired connection may already be closed.
                pass
            self._emit("pairing_status", {"state": "failed", "reason": "timeout"})
            self._reschedule_discovery(immediate=False)

    def _broadcast(self):
        with self._state_lock:
            port = self.listen_port
        if not port or self._stop_event.is_set():
            return
        announcement = encode_packet(self.identity_packet(tcp_port=port))
        for source, targets in ipv4_discovery_interfaces():
            sender = None
            try:
                sender = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
                sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sender.bind((source, 0))
                for address in targets:
                    sender.sendto(announcement, (address, UDP_PORT))
            except (BlockingIOError, OSError):
                pass
            finally:
                if sender is not None:
                    sender.close()

    def _broadcast_due(self, now):
        if now < self._last_broadcast + FAST_DISCOVERY_INTERVAL:
            self._next_broadcast = self._last_broadcast + FAST_DISCOVERY_INTERVAL
            return
        if self._discovery_blocked(now):
            self._next_broadcast = now + max(1.0, float(self.backoff[0]))
            return
        self._broadcast()
        self._last_broadcast = now
        self._reconnect_pinned()
        if self._fast_discovery(now):
            delay = FAST_DISCOVERY_INTERVAL
        else:
            delay = self.backoff[min(self._backoff_index, len(self.backoff) - 1)]
            self._backoff_index = min(self._backoff_index + 1, len(self.backoff) - 1)
        self._next_broadcast = now + max(0.1, float(delay))

    def _fast_discovery(self, now=None):
        now = self.clock() if now is None else now
        with self._state_lock:
            with self._connection_lock:
                active = {device_id for device_id, entry in self._connections.items()
                    if not entry["worker"].stopped.is_set()}
                connecting = set(self._connecting)
            active_unconfirmed = {device_id for device_id in active
                if not self._is_confirmed(device_id)}
            if self._live_pairing() or active_unconfirmed or (
                    self._pairing_pending and connecting):
                return False
            return bool(self._pairing_pending or any(
                deadline > now and not self._is_confirmed(device_id)
                and device_id not in active and device_id not in connecting
                for device_id, (_device, _last_seen, deadline) in self._devices.items()))

    @staticmethod
    def _worker_alive(worker):
        try:
            return not worker.stopped.is_set()
        except AttributeError:
            return True

    def _live_pairing(self):
        return bool(self.pairing and self._worker_alive(self.pairing.get("worker")))

    def _discovery_blocked(self, now=None):
        now = self.clock() if now is None else now
        with self._state_lock:
            if self._live_pairing():
                return True
            candidate_ids = {device_id for device_id, (_device, _seen, deadline)
                in self._devices.items()
                if deadline > now and not self._is_confirmed(device_id)}
            with self._connection_lock:
                active_unconfirmed = {device_id for device_id, entry
                    in self._connections.items() if not self._is_confirmed(device_id)
                    and self._worker_alive(entry["worker"])}
                return bool(active_unconfirmed or candidate_ids & set(self._connecting))

    def _reschedule_discovery(self, immediate=True):
        with self._state_lock:
            self._backoff_index = 0
            now = self.clock()
            due = now if immediate else now + FAST_DISCOVERY_INTERVAL
            self._next_broadcast = min(self._next_broadcast, due) if self._next_broadcast else due
            self._next_broadcast = max(self._next_broadcast,
                                       self._last_broadcast + FAST_DISCOVERY_INTERVAL)
        self._wake()

    def _normal_discovery_after_pairing(self):
        with self._state_lock:
            self._backoff_index = 0
            self._next_broadcast = self.clock() + float(self.backoff[0])
        self._wake()

    def _start_handler(self, target, *args):
        def run():
            try:
                target(*args)
            finally:
                with self._state_lock:
                    self._handlers.discard(threading.current_thread())
        thread = threading.Thread(target=run, daemon=True, name="kdeconnect-incoming")
        with self._state_lock:
            self._handlers.add(thread)
        thread.start()

    def _connect_device(self, device):
        device_id = device.identity["deviceId"]
        with self._state_lock:
            if self._live_pairing():
                return
        with self._connection_lock:
            if device_id in self._connections or device_id in self._connecting:
                return
            self._connecting.add(device_id)

        def connect():
            connection = None
            try:
                connection, identity, _certificate = self._tls_connection(device)
                if not self._peer_useful(identity):
                    raise ProtocolError("peer advertises no enabled KDE Connect capability")
                self.store.update_endpoint(device_id, device.address, device.port)
                self._pairing_failures.pop(device_id, None)
                self._remember_connection(connection, identity, _certificate,
                                          device.address, device.port, direction="outgoing")
                connection = None
            except Exception as error:
                if "unexpected eof" in str(error).lower():
                    self._pairing_failures[device_id] = self._pairing_failures.get(device_id, 0) + 1
                self._reschedule_discovery()
            finally:
                if connection is not None:
                    connection.close()
                with self._connection_lock:
                    self._connecting.discard(device_id)
        self._start_handler(connect)

    def _reconnect_pinned(self):
        with self._state_lock:
            if self._live_pairing():
                return
        for device_id, peer in list(self.store.peers.items()):
            if not {"lastAddress", "lastPort", "lastSeenMs"} <= set(peer):
                continue
            body = {"deviceId": device_id, "deviceName": peer["name"],
                "deviceType": "phone", "protocolVersion": PROTOCOL_VERSION,
                "incomingCapabilities": [SMS_REQUEST_TYPE],
                "outgoingCapabilities": [SMS_MESSAGES_TYPE], "tcpPort": peer["lastPort"]}
            self._connect_device(DiscoveredDevice(peer["lastAddress"], peer["lastPort"], body))

    def _handle_incoming(self, raw, device):
        connection = None
        device_id = device.identity["deviceId"]
        try:
            connection, identity, certificate = self._tls_connection(
                device, allow_unpaired=device_id not in self.store.peers, accepted=raw)
            if device_id in self.store.peers:
                if not self._peer_useful(identity):
                    raise ProtocolError("peer advertises no enabled KDE Connect capability")
                self.store.update_endpoint(device_id, device.address, device.port)
                self._pairing_failures.pop(device_id, None)
                self._remember_connection(connection, identity, certificate,
                                          device.address, device.port, direction="incoming")
                connection = None
                return
            self._remember_connection(connection, identity, certificate,
                                      device.address, device.port, direction="incoming")
            connection = None
        except Exception:  # noqa: S110 - Invalid incoming peers are deliberately dropped.
            pass
        finally:
            with self._state_lock:
                self._accepted.discard(raw)
            if connection is not None:
                connection.close()

    def _remember_connection(self, connection, identity, certificate=None,
                             address=None, port=None, start=True, direction="outgoing"):
        device_id = identity["deviceId"]
        if not self._is_confirmed(device_id) and address and port:
            self._remember_device(DiscoveredDevice(address, port, identity), reconnect=False)
        worker = _ConnectionWorker(self, connection, identity)
        previous = None
        with self._state_lock:
            with self._connection_lock:
                previous = self._connections.get(device_id)
                previous_alive = (previous is not None
                    and self._worker_alive(previous["worker"]))
                if previous_alive and direction != "incoming":
                    connection.close()
                    return previous["worker"]
                self._connection_generation += 1
                generation = self._connection_generation
                self._connections[device_id] = {"connection": connection,
                    "identity": identity, "worker": worker, "certificate": certificate,
                    "address": address, "port": port, "direction": direction,
                    "generation": generation}
                worker.generation = generation
                if self.pairing and self.pairing.get("worker") is (
                        previous["worker"] if previous else None):
                    self.pairing.update(worker=worker, identity=identity,
                        certificate=certificate or self.pairing.get("certificate"),
                        address=address or self.pairing.get("address"),
                        port=port or self.pairing.get("port"))
                if start and previous is None:
                    worker.start()
        if previous is not None and previous["worker"] is not worker:
            previous["worker"].close(join=True)
            worker.transfer_sms_state(previous["worker"])
            if start:
                worker.start()
        return worker

    def _forget_connection(self, device_id, connection):
        removed = None
        with self._connection_lock:
            current = self._connections.get(device_id)
            if current is not None and current["connection"] is connection:
                removed = self._connections.pop(device_id)
        if removed is not None:
            removed["worker"].close(join=True)
        else:
            connection.close()

    def _worker_died(self, device_id, worker):
        removed = False
        entry = None
        with self._connection_lock:
            current = self._connections.get(device_id)
            if current is not None and current["worker"] is worker:
                entry = self._connections.pop(device_id, None)
                removed = True
        if removed:
            with self._state_lock:
                if self.pairing and self.pairing.get("worker") is worker:
                    self.pairing = None
                if not self._is_confirmed(device_id) and entry is not None:
                    now = self.clock()
                    cached = self._devices.get(device_id)
                    device = cached[0] if cached else DiscoveredDevice(
                        entry.get("address") or "", entry.get("port") or UDP_PORT,
                        entry["identity"])
                    last_seen = cached[1] if cached else now
                    self._devices[device_id] = (device, last_seen, now + CANDIDATE_TTL)
        worker.connection.close()
        if removed and not self._stop_event.is_set():
            self._reschedule_discovery(immediate=False)

    def _deliver_sms(self, message, notify):
        if not self._is_confirmed(message["device_id"]):
            return
        if not message["group"]:
            value = dict(message)
            value["notify"] = bool(notify and message["incoming"])
            self._emit("sms", value)

    def _capable_connections(self, device_id=None):
        with self._connection_lock:
            return [entry for key, entry in self._connections.items()
                    if self._is_confirmed(key)
                    and (device_id is None or key == device_id)
                    and not entry["worker"].stopped.is_set()
                     and SMS_REQUEST_TYPE in entry["identity"]["incomingCapabilities"]]

    def _contact_connections(self, device_id=None):
        with self._connection_lock:
            return [entry for key, entry in self._connections.items()
                if self._is_confirmed(key) and (device_id is None or key == device_id)
                and not entry["worker"].stopped.is_set()
                and {CONTACT_UIDS_REQUEST, CONTACT_VCARDS_REQUEST} <= set(entry["identity"]["incomingCapabilities"])
                and {CONTACT_UIDS_RESPONSE, CONTACT_VCARDS_RESPONSE} <= set(entry["identity"]["outgoingCapabilities"])]

    def _contact_query(self, device_id, kind, body, response):
        connections = self._contact_connections(device_id)
        if len(connections) != 1:
            raise ProtocolError("contacts_unavailable")
        entry = connections[0]
        certificate = entry.get("certificate")
        if certificate is None:
            raise ProtocolError("contacts_unavailable")
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        identity = certificate.fingerprint(hashes.SHA256()).hex()
        peer_id = entry["identity"]["deviceId"]
        expected = x509.load_pem_x509_certificate(self.store.peers[peer_id]["certificate"].encode("ascii"))
        if expected.fingerprint(hashes.SHA256()).hex() != identity:
            raise ProtocolError("contact_source_changed")
        result = entry["worker"].contact_request(kind, body, response)
        if not any(current is entry for current in self._contact_connections(peer_id)):
            raise ProtocolError("contact_source_changed")
        current = x509.load_pem_x509_certificate(self.store.peers[peer_id]["certificate"].encode("ascii"))
        if current.fingerprint(hashes.SHA256()).hex() != identity:
            raise ProtocolError("contact_source_changed")
        return peer_id, identity, result

    @staticmethod
    def _contact_uids(value):
        if (not isinstance(value, list) or len(value) > 20000
                or any(not isinstance(uid, str) or not 1 <= len(uid) <= 1024
                       or any(ord(char) < 32 for char in uid) for uid in value)
                or len(set(value)) != len(value)):
            raise ProtocolError("invalid_contact_uids")
        return value

    def contact_uids(self, device_id=None):
        peer, identity, body = self._contact_query(device_id, CONTACT_UIDS_REQUEST, {}, CONTACT_UIDS_RESPONSE)
        values = []
        for uid in self._contact_uids(body.get("uids")):
            timestamp = body.get(uid)
            if type(timestamp) is not int or not 0 <= timestamp <= 2**53 - 1:
                raise ProtocolError("invalid_contact_timestamp")
            values.append({"uid": uid, "modified_ms": timestamp})
        return {"device_id": peer, "fingerprint": identity, "contacts": values}

    def contact_vcards(self, uids, device_id=None):
        requested = self._contact_uids(uids)
        if not 1 <= len(requested) <= 5:
            raise ProtocolError("invalid_contact_batch")
        peer, identity, body = self._contact_query(device_id, CONTACT_VCARDS_REQUEST,
            {"uids": requested}, CONTACT_VCARDS_RESPONSE)
        result = []
        for uid in self._contact_uids(body.get("uids")):
            card = body.get(uid)
            if uid not in requested or not isinstance(card, str) or len(card.encode("utf-8")) > MAX_CONTACT_PACKET:
                raise ProtocolError("invalid_contact_vcard")
            result.append({"uid": uid, "vcard": card})
        return {"device_id": peer, "fingerprint": identity, "contacts": result}

    def _is_confirmed(self, device_id):
        return self.store.peers.get(device_id, {}).get("paired") is True

    def _peer_useful(self, identity):
        if SMS_REQUEST_TYPE in identity["incomingCapabilities"]:
            return True
        with self._state_lock:
            settings = self._receive_settings
            if identity["deviceId"] != settings["device_id"]:
                return False
            outgoing = identity["outgoingCapabilities"]
            return ((settings["clipboard_enabled"] and (CLIPBOARD_TYPE in outgoing
                or CLIPBOARD_CONNECT_TYPE in outgoing))
                or (settings["file_enabled"] and SHARE_TYPE in outgoing))

    @staticmethod
    def _validate_pair_packet(packet):
        if (not isinstance(packet, dict) or set(packet) != {"id", "type", "body"}
                or packet.get("type") != "kdeconnect.pair"
                or not isinstance(packet.get("id"), int)
                or isinstance(packet.get("id"), bool)
                or not isinstance(packet.get("body"), dict)):
            raise ProtocolError("invalid KDE Connect pair packet")
        body = packet["body"]
        if body in ({"pair": False}, {"pair": True}):
            return body["pair"], None
        if set(body) == {"pair", "timestamp"} and body.get("pair") is True:
            timestamp = body["timestamp"]
            if (not isinstance(timestamp, int) or isinstance(timestamp, bool)
                    or abs(int(time.time()) - timestamp) > PAIR_CLOCK_SKEW):
                raise ProtocolError("pairing request timestamp is outside the allowed clock skew")
            return True, timestamp
        raise ProtocolError("invalid KDE Connect pair body")

    def _pair_packet(self, worker, packet):
        try:
            wants_pair, timestamp = self._validate_pair_packet(packet)
        except ProtocolError:
            return
        device_id = worker.identity["deviceId"]
        if not wants_pair:
            with self._state_lock:
                if self.pairing and self.pairing.get("worker") is worker:
                    self.pairing = None
            self.store.mark_unpaired(device_id)
            self._emit("pairing_status", {"state": "failed", "reason": "rejected",
                                           "device_id": device_id})
            self._reschedule_discovery(immediate=False)
            return
        if self._is_confirmed(device_id):
            # A confirmed Android peer sending pair=true considers this link
            # unpaired. Require a fresh explicit local confirmation; never echo
            # pair=true automatically, which Android interprets as unpairing.
            self.store.mark_unpaired(device_id)
            if timestamp is None:
                if device_id not in self._repair_prompts:
                    self._repair_prompts.add(device_id)
                    self._emit("pairing_status", {"state": "failed",
                        "reason": "repair_required", "device_id": device_id})
                return
        with self._state_lock:
            pending = self.pairing
            if timestamp is not None:
                with self._connection_lock:
                    entry = self._connections.get(device_id)
                if entry is None or entry.get("certificate") is None:
                    return
                if pending is not None and pending["identity"]["deviceId"] != device_id:
                    return
                if pending is None or pending.get("timestamp") != timestamp:
                    pending = {"state": "requested", "direction": "incoming",
                        "worker": worker, "identity": worker.identity,
                        "certificate": entry["certificate"], "timestamp": timestamp,
                        "address": entry["address"], "port": entry["port"],
                        "local_confirmed": False, "remote_confirmed": True,
                        "deadline": self.clock() + PAIR_WINDOW}
                    self.pairing = pending
                else:
                    pending.update(worker=worker, identity=worker.identity,
                        certificate=entry["certificate"], address=entry["address"],
                        port=entry["port"], remote_confirmed=True)
            elif pending is None or pending["identity"]["deviceId"] != device_id:
                return
            else:
                pending["worker"] = worker
                pending["remote_confirmed"] = True
        prompt_key = (device_id, timestamp)
        if timestamp is not None and prompt_key not in self._pair_prompt_seen:
            self._pair_prompt_seen[prompt_key] = self.clock() + PAIR_WINDOW
            self._emit("pairing", {"state": "requested", "device_id": device_id,
                "device_name": worker.identity["deviceName"],
                "code": pairing_code(self.store.certificate, pending["certificate"], timestamp),
                "expires_in": PAIR_WINDOW,
                "instruction": "confirm_code_on_both_devices"})
        elif pending.get("local_confirmed"):
            self._finish_pairing(pending)

    def _finish_pairing(self, pending):
        if not (pending.get("local_confirmed") and pending.get("remote_confirmed")):
            return None
        with self._state_lock:
            if self.pairing is not pending or self.clock() > pending["deadline"]:
                raise ProtocolError("no active pairing operation")
            self.pairing = None
        identity = pending["identity"]
        with self._connection_lock:
            connected = set(self._connections)
        self.store.confirm_peer_and_cleanup(identity["deviceId"], identity["deviceName"],
            pending["certificate"], pending["address"], pending["port"], connected)
        with self._state_lock:
            self._devices.clear()
        self._repair_prompts.discard(identity["deviceId"])
        pending["worker"].enable_sms()
        result = {"state": "paired", "device_id": identity["deviceId"]}
        self._emit("pairing_status", result)
        self._normal_discovery_after_pairing()
        return result

    def identity_packet(self, target=None, tcp_port=None):
        incoming = [SMS_MESSAGES_TYPE, CONTACT_UIDS_RESPONSE, CONTACT_VCARDS_RESPONSE]
        with self._state_lock:
            if self._receive_settings["clipboard_enabled"]:
                incoming.extend((CLIPBOARD_TYPE, CLIPBOARD_CONNECT_TYPE))
            if self._receive_settings["file_enabled"]:
                incoming.append(SHARE_TYPE)
        body = {"deviceId": self.store.device_id, "deviceName": self.store.device_name,
                "deviceType": "desktop", "protocolVersion": 8,
                "incomingCapabilities": incoming,
                "outgoingCapabilities": [SMS_REQUEST_TYPE,
                    SMS_REQUEST_CONVERSATIONS_TYPE, SMS_REQUEST_CONVERSATION_TYPE,
                    CONTACT_UIDS_REQUEST, CONTACT_VCARDS_REQUEST]}
        if tcp_port is not None:
            body["tcpPort"] = tcp_port
        if target:
            body.update(targetDeviceId=target, targetProtocolVersion=8)
        return network_packet("kdeconnect.identity", body)

    def _open_listener(self):
        for port in self.tcp_ports:
            listener = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("", port))
                listener.listen(8)
                listener.setblocking(False)
                return listener, listener.getsockname()[1]
            except OSError:
                listener.close()
        raise ProtocolError("no KDE Connect TCP discovery port is available")

    def _remember_device(self, device, reconnect=True):
        with self._devices_changed:
            now = self.clock()
            self._devices[device.identity["deviceId"]] = (
                device, now, now + CANDIDATE_TTL)
            if not self._is_confirmed(device.identity["deviceId"]):
                self._backoff_index = 0
                self._next_broadcast = min(self._next_broadcast or now + FAST_DISCOVERY_INTERVAL,
                    max(now, self._last_broadcast + FAST_DISCOVERY_INTERVAL))
            self._devices_changed.notify_all()
        self._wake()
        if reconnect and device.identity["deviceId"] in self.store.peers:
            self._connect_device(device)

    def _receive_udp_identity(self, udp, devices=None):
        try:
            raw, source = udp.recvfrom(MAX_PACKET + 1)
            address = ipaddress.ip_address(source[0])
            if not (address.is_private or address.is_loopback):
                return
            body = validate_identity(decode_packet(raw), require_tcp=True)
            if body["deviceId"] != self.store.device_id:
                device = DiscoveredDevice(source[0], body["tcpPort"], body)
                if devices is not None:
                    devices[body["deviceId"]] = device
                else:
                    self._remember_device(device)
        except (OSError, ProtocolError, ValueError):
            return

    def _accept_tcp(self):
        try:
            raw, source = self._listener.accept()
            address = ipaddress.ip_address(source[0])
            with self._state_lock:
                allowed = ((address.is_private or address.is_loopback)
                           and len(self._pending) + len(self._accepted) < MAX_PENDING)
                if allowed:
                    raw.setblocking(False)
                    self._pending[raw] = (bytearray(), source[0], self.clock() + 5)
            if not allowed:
                raw.close()
        except (OSError, ValueError):
            return

    def _receive_tcp_identity(self, raw, pending=None, devices=None, accepted=None):
        table = pending if pending is not None else self._pending
        value = table.get(raw)
        if value is None:
            return
        buffer, address = value[:2]
        try:
            part = raw.recv(1)  # Do not consume a pipelined TLS ClientHello.
            if not part:
                raise ProtocolError("connection closed before identity")
            buffer += part
            if len(buffer) > MAX_PACKET:
                raise ProtocolError("identity exceeds size limit")
            if part != b"\n":
                return
            body = validate_identity(decode_packet(bytes(buffer)))
            if (body.get("targetDeviceId") != self.store.device_id
                    or body.get("targetProtocolVersion") != PROTOCOL_VERSION
                    or body["deviceId"] == self.store.device_id):
                raise ProtocolError("identity targets a different KDE Connect device")
            table.pop(raw)
            raw.setblocking(True)
            raw.settimeout(8)
            device = DiscoveredDevice(address, body.get("tcpPort", UDP_PORT), body)
            if accepted is not None:
                old = accepted.pop(body["deviceId"], None)
                if old is not None:
                    old.close()
                accepted[body["deviceId"]] = raw
                devices[body["deviceId"]] = device
            else:
                self._remember_device(device, reconnect=False)
                with self._state_lock:
                    self._accepted.add(raw)
                self._start_handler(self._handle_incoming, raw, device)
        except (OSError, ProtocolError, ValueError):
            table.pop(raw, None)
            raw.close()

    def discover(self, timeout=0.7):
        self.start()
        self._reschedule_discovery()
        return self._wait_for_devices(timeout)

    def _wait_for_devices(self, timeout):
        deadline = self.clock() + max(0.01, float(timeout))
        with self._devices_changed:
            while not self._devices and self.clock() < deadline:
                self._devices_changed.wait(deadline - self.clock())
            return [item[0] for item in self._devices.values()]

    def status(self, timeout=0.25):
        def with_candidates(result):
            now = self.clock()
            with self._state_lock:
                candidates = [(device, last_seen, deadline)
                    for device, last_seen, deadline in self._devices.values()
                    if deadline > now and not self._is_confirmed(device.identity["deviceId"])]
                settings = dict(self._receive_settings)
                pending_receive = [{"id": key, "kind": value["kind"],
                    "device_id": value["device_id"],
                    **({"name": value["name"], "size": value["size"]}
                       if value["kind"] == "file" else {})}
                    for key, value in self._receive_pending.items()]
                receive_slots = self._receive_slots
            result["receive"] = {"clipboard_enabled": settings["clipboard_enabled"],
                "file_enabled": settings["file_enabled"],
                "device_id": settings["device_id"],
                "clipboard_mode": settings["clipboard_mode"],
                "file_mode": settings["file_mode"],
                "download_directory_configured": bool(settings["download_directory"]),
                "pending_count": receive_slots, "proposals": pending_receive}
            with self._connection_lock:
                reachable = [entry for key, entry in self._connections.items()
                    if not self._is_confirmed(key) and not entry["worker"].stopped.is_set()]
            known = {item.identity["deviceId"] for item, _seen, _deadline in candidates}
            candidates += [(DiscoveredDevice(entry.get("address") or "", entry.get("port") or 1716,
                entry["identity"]), now, now + CANDIDATE_TTL) for entry in reachable
                if entry["identity"]["deviceId"] not in known]
            reachable_ids = {entry["identity"]["deviceId"] for entry in reachable}
            result["unpaired_candidates"] = [{"device_id": item.identity["deviceId"],
                "device_name": item.identity["deviceName"],
                "currently_reachable": item.identity["deviceId"] in reachable_ids,
                "age_seconds": max(0, int(now - last_seen))}
                for item, last_seen, _deadline in candidates]
            result["unpaired_candidate_count"] = len(candidates)
            result["transport_reachable"] = bool(capable or reachable)
            result["encrypted_link_count"] = len(capable) + len(reachable)
            if len(candidates) == 1:
                candidate = candidates[0][0]
                result["unpaired_candidate_id"] = candidate.identity["deviceId"]
                result["unpaired_candidate_name"] = candidate.identity["deviceName"]
                result["unpaired_candidate_reachable"] = candidate.identity["deviceId"] in reachable_ids
                result["unpaired_candidate_age_seconds"] = max(0, int(now - candidates[0][1]))
                matches = [key for key, peer in self.store.peers.items()
                    if peer["name"] == candidate.identity["deviceName"]]
                result["replacement_peer_id"] = matches[0] if len(matches) == 1 else ""
                if not result.get("peer_name"):
                    result["peer_name"] = candidate.identity["deviceName"]
            else:
                result["unpaired_candidate_id"] = ""
                result["unpaired_candidate_name"] = ""
                result["replacement_peer_id"] = ""
                result["unpaired_candidate_reachable"] = False
                result["unpaired_candidate_age_seconds"] = 0
            result["fast_discovery"] = self._fast_discovery(now)
            result["next_discovery_seconds"] = max(0, round(self._next_broadcast - now, 1))
            diagnostic = capable[0] if len(capable) == 1 else (
                reachable[0] if len(reachable) == 1 else None)
            result["connection_generation"] = diagnostic.get("generation", 0) if diagnostic else 0
            result["connection_direction"] = diagnostic.get("direction", "") if diagnostic else ""
            contacts = self._contact_connections()
            result["contacts_available"] = len(contacts) == 1
            result["contacts_device_id"] = contacts[0]["identity"]["deviceId"] if len(contacts) == 1 else ""
            if capable:
                capabilities = capable[0]["identity"]["incomingCapabilities"]
                result["history_available"] = (SMS_REQUEST_CONVERSATIONS_TYPE in capabilities
                    and SMS_REQUEST_CONVERSATION_TYPE in capabilities)
                result["sms_protocol"] = dict(capable[0]["worker"].diagnostics)
            else:
                result["history_available"] = False
                result["sms_protocol"] = {"last_packet_type": "", "parse_valid": 0,
                    "parse_skipped": 0, "last_receive_ms": 0, "bootstrap_state": "offline"}
            return result

        confirmed_peers = {key: value for key, value in self.store.peers.items()
                           if value.get("paired") is True}
        legacy_peers = {key: value for key, value in self.store.peers.items()
                        if value.get("paired") is not True}
        paired = len(confirmed_peers)
        peer_id = next(iter(confirmed_peers), "") if paired == 1 else ""
        peer_name = self.store.peers.get(peer_id, {}).get("name", "")
        capable = self._capable_connections()
        if not capable:
            self.start()
        if not self.listening:
            if capable:
                return with_candidates({"available": len(capable) == 1, "device_count": len(capable),
                        "device_id": capable[0]["identity"]["deviceId"] if len(capable) == 1 else "",
                        "paired": paired, "paired_count": paired,
                        "legacy_pinned_count": len(legacy_peers),
                        "locally_pinned_count": len(self.store.peers),
                        "reason": "" if len(capable) == 1 else "multiple_devices",
                        "pairing_state": self.pairing["state"] if self.pairing else "idle",
                        "peer_id": peer_id, "peer_name": peer_name,
                        "listening": False, "listen_port": None})
            return with_candidates({"available": False, "device_count": 0, "device_id": "",
                    "paired": paired, "paired_count": paired,
                    "legacy_pinned_count": len(legacy_peers),
                    "locally_pinned_count": len(self.store.peers),
                    "reason": self.reason, "pairing_state": "idle",
                    "peer_id": peer_id, "peer_name": peer_name,
                    "listening": False, "listen_port": None})
        capable = self._capable_connections()
        if capable:
            return with_candidates({"available": len(capable) == 1, "device_count": len(capable),
                    "device_id": capable[0]["identity"]["deviceId"] if len(capable) == 1 else "",
                    "paired": paired, "paired_count": paired,
                    "legacy_pinned_count": len(legacy_peers),
                    "locally_pinned_count": len(self.store.peers),
                    "reason": "" if len(capable) == 1 else "multiple_devices",
                    "pairing_state": self.pairing["state"] if self.pairing else "idle",
                    "peer_id": peer_id, "peer_name": peer_name,
                    "listening": True, "listen_port": self.listen_port})
        self._wait_for_devices(timeout)
        capable = self._capable_connections()
        reason = "" if len(capable) == 1 else ("no_device" if not capable else "multiple_devices")
        if not capable and any(count >= 2 for count in self._pairing_failures.values()):
            reason = "pairing_mismatch"
        return with_candidates({"available": len(capable) == 1, "device_count": len(capable),
                "device_id": capable[0]["identity"]["deviceId"] if len(capable) == 1 else "",
                "paired": paired, "paired_count": paired,
                "legacy_pinned_count": len(legacy_peers),
                "locally_pinned_count": len(self.store.peers), "reason": reason,
                "pairing_state": self.pairing["state"] if self.pairing else "idle",
                "peer_id": peer_id, "peer_name": peer_name,
                "listening": True, "listen_port": self.listen_port})

    def _tls_connection(self, device, allow_unpaired=False, accepted=None):
        if SSL is None:
            raise RuntimeError("PyOpenSSL is required for direct KDE Connect")
        device_id = device.identity["deviceId"]
        stored = self.store.peers.get(device_id)
        if not stored and not allow_unpaired:
            raise ProtocolError("KDE Connect peer is not paired")
        expected = (x509.load_pem_x509_certificate(stored["certificate"].encode("ascii"))
                    if stored else None)
        context = SSL.Context(SSL.TLS_CLIENT_METHOD if accepted is not None
                              else SSL.TLS_SERVER_METHOD)
        context.set_min_proto_version(SSL.TLS1_2_VERSION)
        context.set_options(SSL.OP_NO_COMPRESSION)
        context.use_privatekey(crypto.load_privatekey(crypto.FILETYPE_PEM,
            self.store.key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption())))
        context.use_certificate(crypto.load_certificate(crypto.FILETYPE_PEM,
            self.store.certificate.public_bytes(serialization.Encoding.PEM)))
        context.check_privatekey()

        def verify(_connection, certificate, error_number, depth, preverified):
            if depth != 0:
                return False
            try:
                candidate = x509.load_der_x509_certificate(crypto.dump_certificate(
                    crypto.FILETYPE_ASN1, certificate))
                _validate_peer_certificate(candidate, device_id)
                if expected is not None:
                    return candidate.fingerprint(hashes.SHA256()) == expected.fingerprint(hashes.SHA256())
                return allow_unpaired and (preverified or error_number == 18)
            except (ProtocolError, ValueError):
                return False

        context.set_verify(SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT, verify)
        raw = accepted or socket.create_connection((device.address, device.port), timeout=5)
        raw.settimeout(8)
        with self._state_lock:
            self._handshakes.add(raw)
        try:
            if accepted is None:
                raw.sendall(encode_packet(self.identity_packet(device_id)))
            connection = SSL.Connection(context, raw)
            if accepted is None:
                connection.set_accept_state()  # TCP client becomes TLS server.
            else:
                connection.set_connect_state()  # Accepted TCP server becomes TLS client.
            stream = _TLSStream(connection, raw=raw)
            stream.handshake()
            if accepted is None:
                stream.sendall(encode_packet(self.identity_packet()))
                secure = validate_identity(read_packet(stream))
            else:
                secure = validate_identity(read_packet(stream))
                stream.sendall(encode_packet(self.identity_packet()))
            if secure["deviceId"] != device_id:
                raise ProtocolError("secure identity changed device id")
            peer = x509.load_der_x509_certificate(crypto.dump_certificate(
                crypto.FILETYPE_ASN1, connection.get_peer_certificate()))
            _validate_peer_certificate(peer, device_id)
            if expected and peer.fingerprint(hashes.SHA256()) != expected.fingerprint(hashes.SHA256()):
                raise ProtocolError("peer certificate pin changed")
            return stream, secure, peer
        except Exception:
            raw.close()
            raise
        finally:
            with self._state_lock:
                self._handshakes.discard(raw)

    def begin_pairing(self, device_id=None, replace_stored=False):
        self.start()
        with self._state_lock:
            if self.pairing:
                raise ProtocolError("a pairing operation is already active")
        now = self.clock()
        with self._state_lock:
            candidates = [item for item, _last_seen, deadline in self._devices.values()
                if deadline > now and not self._is_confirmed(item.identity["deviceId"])
                and (device_id is None or item.identity["deviceId"] == device_id)]
        if not candidates and device_id is None:
            with self._state_lock:
                self._pairing_pending = True
            self._reschedule_discovery()
            try:
                self._wait_for_devices(5.0)
            finally:
                with self._state_lock:
                    self._pairing_pending = False
            now = self.clock()
            with self._state_lock:
                candidates = [item for item, _last_seen, deadline in self._devices.values()
                    if deadline > now and not self._is_confirmed(item.identity["deviceId"])]
        if len(candidates) != 1:
            if not candidates:
                self._normal_discovery_after_pairing()
            raise ProtocolError("exactly one KDE Connect device must be selected")
        candidate = candidates[0]
        with self._state_lock:
            cached, last_seen, deadline = self._devices[candidate.identity["deviceId"]]
            self._devices[candidate.identity["deviceId"]] = (
                cached, last_seen, max(deadline, self.clock() + PAIR_WINDOW))
        if replace_stored:
            matches = [key for key, peer in self.store.peers.items()
                if peer["name"] == candidate.identity["deviceName"]]
            if len(matches) != 1:
                raise ProtocolError("exactly one same-name KDE Connect peer must be selected for replacement")
        with self._connection_lock:
            entry = self._connections.get(candidate.identity["deviceId"])
        if entry is not None and not entry["worker"].stopped.is_set():
            return self.complete_pairing(candidate.identity["deviceId"])
        device_id = candidate.identity["deviceId"]
        with self._connection_lock:
            self._connecting.add(device_id)
        try:
            connection, identity, certificate = self._tls_connection(candidate, allow_unpaired=True)
        finally:
            with self._connection_lock:
                self._connecting.discard(device_id)
        worker = self._remember_connection(connection, identity, certificate,
            candidate.address, candidate.port, start=False)
        timestamp = int(time.time())
        with self._state_lock:
            self.pairing = {"state": "requested", "direction": "outgoing",
                "worker": worker, "identity": identity, "certificate": certificate,
                "timestamp": timestamp, "address": candidate.address, "port": candidate.port,
                "local_confirmed": False, "remote_confirmed": False,
                "deadline": self.clock() + PAIR_WINDOW}
        try:
            worker.send(network_packet("kdeconnect.pair", {"pair": True, "timestamp": timestamp}))
            worker.start()
        except Exception:
            with self._state_lock:
                self.pairing = None
            self._forget_connection(identity["deviceId"], connection)
            raise
        return {"state": "requested", "device_id": identity["deviceId"],
                "device_name": identity["deviceName"],
                "code": pairing_code(self.store.certificate, certificate, timestamp),
                "expires_in": PAIR_WINDOW}

    def complete_pairing(self, device_id):
        with self._connection_lock:
            entry = self._connections.get(device_id)
        if entry is None or self._is_confirmed(device_id):
            raise ProtocolError("selected KDE Connect device has no unconfirmed encrypted link")
        with self._state_lock:
            if self.pairing:
                raise ProtocolError("a pairing operation is already active")
            timestamp = int(time.time())
            self.pairing = {"state": "requested", "direction": "outgoing",
                "worker": entry["worker"], "identity": entry["identity"],
                "certificate": entry["certificate"], "timestamp": timestamp,
                "address": entry["address"], "port": entry["port"],
                "local_confirmed": False, "remote_confirmed": False,
                "deadline": self.clock() + PAIR_WINDOW}
        entry["worker"].send(network_packet("kdeconnect.pair",
                                             {"pair": True, "timestamp": timestamp}))
        return {"state": "requested", "device_id": device_id,
            "device_name": entry["identity"]["deviceName"],
            "code": pairing_code(self.store.certificate, entry["certificate"], timestamp),
            "expires_in": PAIR_WINDOW, "instruction": "confirm_code_on_both_devices"}

    def confirm_pairing(self, code_matches):
        with self._state_lock:
            pending = self.pairing
        if not pending or pending["state"] != "requested" or self.clock() > pending["deadline"]:
            raise ProtocolError("no active pairing operation")
        if not code_matches:
            with self._state_lock:
                self.pairing = None
            pending["worker"].send(network_packet("kdeconnect.pair", {"pair": False}))
            self._reschedule_discovery(immediate=False)
            return {"state": "rejected"}
        pending["local_confirmed"] = True
        if pending.get("direction") == "incoming":
            pending["worker"].send(network_packet("kdeconnect.pair", {"pair": True}))
        result = self._finish_pairing(pending)
        return result or {"state": "waiting_for_phone", "device_id": pending["identity"]["deviceId"]}

    def send_sms(self, destination, message, device_id=None):
        if not isinstance(destination, str) or not re.fullmatch(r"\+[1-9][0-9]{5,19}", destination):
            raise ValueError("invalid SMS destination")
        normalized = normalize_sms_text(message)
        message = normalized["text"]
        if (not message.strip() or len(message) > 5000
                or normalized["segments"] > SMS_MAX_SEGMENTS):
            raise ValueError("invalid SMS text")
        capable = self._capable_connections(device_id)
        if not capable:
            candidates = [item for item in self.discover(5.0)
                          if self._is_confirmed(item.identity["deviceId"])
                          and (device_id is None or item.identity["deviceId"] == device_id)]
            for candidate in candidates:
                self._connect_device(candidate)
            deadline = self.clock() + 5
            while not capable and self.clock() < deadline:
                time.sleep(0.05)
                capable = self._capable_connections(device_id)
        if len(capable) != 1:
            raise ProtocolError("exactly one paired KDE Connect phone must be reachable")
        entry = capable[0]
        connection, identity, worker = (entry["connection"], entry["identity"], entry["worker"])
        packet = network_packet(SMS_REQUEST_TYPE, {"version": 2,
            "addresses": [{"address": destination}], "messageBody": message})
        try:
            worker.send(packet)  # Exactly one queued attempt; the worker never retries it.
        except Exception:
            self._forget_connection(identity["deviceId"], connection)
            raise
        return {"ok": True, "state": "queued", "backend": "kdeconnect-direct",
                "device_id": identity["deviceId"]}
