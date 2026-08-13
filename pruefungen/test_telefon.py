#!/usr/bin/env python3
"""Protocol and separation checks for the Linux phone connection."""

import json
import hashlib
import hmac
import os
import socket
import sys
import tempfile
import time
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import magnolie_telefon as phone


def test_canonical_and_status_contract():
    assert phone.canonical({"z": 2, "a": "ä"}) == b'{"a":"\xc3\xa4","z":2}'
    request_id = str(uuid.uuid4())
    value = {"request_id": request_id, "model": "Pixel 9", "manufacturer": "Google",
             "os_name": "Android", "os_version": "16", "battery_percent": 73,
             "charging": "charging", "captured_ms": 1786617000000}
    assert phone.validate_device_status(value) is value
    for changed in (dict(value, battery_percent=101), dict(value, imei="secret"),
                    dict(value, charging="yes")):
        try:
            phone.validate_device_status(changed)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid device status accepted")


def test_cross_platform_golden_vectors():
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    path = os.path.join(ROOT, "..", "Entwicklungsnotizen",
                        "telefon-protokoll-vektoren.json")
    with open(path, encoding="utf-8") as source:
        vectors = json.load(source)
    assert phone.canonical(vectors["canonical_json"]["input"]).decode() == \
        vectors["canonical_json"]["expected"]
    pairing = vectors["pairing"]
    init, response = pairing["pair_init"], pairing["pair_response"]
    assert phone.canonical(init).decode() == pairing["canonical_pair_init"]
    assert phone.canonical(response).decode() == pairing["canonical_pair_response"]
    desktop_static = X25519PrivateKey.from_private_bytes(phone.unb64(
        pairing["desktop_static_private"], 32))
    desktop_ephemeral = X25519PrivateKey.from_private_bytes(phone.unb64(
        pairing["desktop_ephemeral_private"], 32))
    transcript, pair_key, code = phone.pairing_material(
        init, response, desktop_ephemeral, desktop_static)
    assert phone.b64(transcript) == pairing["transcript"]
    assert phone.b64(pair_key) == pairing["pair_key"] and code == pairing["code"]
    for phase in ("confirm", "finish"):
        for side in ("phone", "desktop"):
            expected = pairing[side + "_" + phase + "_proof"]
            assert phone.b64(phone.proof(pair_key,
                ("magnolie-phone-pair-v1/%s\0" % phase).encode(), side,
                transcript)) == expected

    session = vectors["session"]
    static_shared = phone.unb64(pairing["static_shared"], 32)
    ids = phone.unb64(session["ids"], 73)
    root = phone.hkdf(static_shared,
        hashlib.sha256(b"magnolie-phone-fs1/static-salt\0" + ids).digest(),
        b"magnolie-phone-fs1/static-root\0" + ids, 32)
    assert phone.b64(root) == session["static_root"]
    auth = phone.hkdf(root, None, b"magnolie-phone-fs1/auth\0", 32)
    assert phone.b64(auth) == session["auth_key"]
    start0, start = session["session_start_without_mac"], session["session_start"]
    assert phone.b64(hmac.new(auth, b"magnolie-phone-fs1/start\0" +
        phone.canonical(start0), hashlib.sha256).digest()) == start["mac"]
    response0, session_response = session["session_response_without_mac"], session["session_response"]
    assert phone.b64(hmac.new(auth, b"magnolie-phone-fs1/response\0" +
        phone.canonical(start) + phone.canonical(response0), hashlib.sha256).digest()) == session_response["mac"]
    fs_transcript = hashlib.sha256(phone.canonical(start) + phone.canonical(session_response)).digest()
    assert phone.b64(fs_transcript) == session["transcript"]
    salt = hmac.new(root, b"magnolie-phone-fs1/session-salt\0" + fs_transcript,
                    hashlib.sha256).digest()
    material = phone.hkdf(phone.unb64(pairing["ephemeral_shared"], 32), salt,
        b"magnolie-phone-fs1/session-keys\0" + fs_transcript, 72)
    assert phone.b64(material) == session["session_material"]
    encrypted = vectors["encryption"]
    assert phone.b64(material[32:36] + encrypted["seq"].to_bytes(8, "big")) == encrypted["nonce"]
    aad = {key: encrypted["envelope"][key] for key in ("p", "sid", "seq", "dir")}
    assert phone.canonical(aad).decode() == encrypted["aad_canonical"]
    ciphertext = AESGCM(material[:32]).encrypt(phone.unb64(encrypted["nonce"], 12),
        phone.canonical(encrypted["plaintext"]), phone.canonical(aad))
    assert phone.b64(ciphertext) == encrypted["ciphertext"]


def test_phone_storage_is_separate_and_disabled_by_default():
    with tempfile.TemporaryDirectory() as root:
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop")
        assert service.enabled is False
        assert service.server is None
        bluetooth = service.report()["bluetooth"]
        assert bluetooth["uuid"] == phone.BLUETOOTH_UUID
        assert bluetooth["reason"] in {"available", "no_hardware", "os_restricted"}
        files = set(os.listdir(os.path.join(root, "telefon")))
        assert {"identity.json", "identity.key", "phone.db", "storage.key"} <= files
        assert all(name.startswith("phone.db") or name in {
            "identity.json", "identity.key", "storage.key"} for name in files)
        assert not any(name.startswith("baum") for name in os.listdir(root))


def test_listener_uses_only_fixed_phone_port():
    with tempfile.TemporaryDirectory() as root:
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop")
        service.set_enabled(True)
        assert service.server is not None
        assert service.server.getsockname()[1] == phone.PORT == 8741
        probe = socket.create_connection(("127.0.0.1", phone.PORT), timeout=2)
        probe.close()
        service.set_enabled(False)
        time.sleep(0.05)
        assert service.server is None and not service.connections


def test_dedupe_is_persistent_and_phone_only():
    with tempfile.TemporaryDirectory() as root:
        store = phone.PhoneStore(os.path.join(root, "telefon"), "Test desktop")
        message_id = str(uuid.uuid4())
        store.remember_result("peer", message_id, "accepted", "none")
        assert store.dedupe_result("peer", message_id) == ("accepted", "none")
        reopened = phone.PhoneStore(os.path.join(root, "telefon"), "Test desktop")
        assert reopened.dedupe_result("peer", message_id) == ("accepted", "none")


def test_capability_and_grant_schemas_are_strict():
    capabilities = phone.desktop_capabilities(4)
    grants = phone.desktop_grants(7)
    assert phone.validate_capabilities(capabilities) is capabilities
    assert phone.validate_grants(grants) is grants
    assert grants["grants"] == {"call_control": False, "device_status": True,
        "selected_notifications_readonly": False, "sms_received": False,
        "sms_send": True}
    invalid = [dict(capabilities, revision=True),
               dict(capabilities, extra=True),
               dict(capabilities, items=dict(capabilities["items"],
                    device_status={"available": True, "reason": "disabled",
                                   "versions": [1]})),
                dict(grants, revision=0)]
    for value in invalid:
        validator = phone.validate_grants if "grants" in value else phone.validate_capabilities
        try:
            validator(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid capability/grant schema accepted")
    active = dict(grants, grants=dict(grants["grants"], sms_send=True))
    assert phone.validate_grants(active) is active


def test_sms_and_readonly_notification_schemas_are_strict():
    client_ref = str(uuid.uuid4())
    command = {"to": "+49 (170) 123-4567", "text": "Hallo\nWelt",
               "client_ref": client_ref}
    assert phone.validate_sms_send(command) is command
    for state in ("queued", "sent", "delivered"):
        result = {"client_ref": client_ref, "state": state, "error": "none",
                  "occurred_ms": phone.now_ms()}
        assert phone.validate_sms_result(result) is result
    failed = {"client_ref": client_ref, "state": "failed", "error": "no_service",
              "occurred_ms": phone.now_ms()}
    assert phone.validate_sms_result(failed) is failed
    received = {"sms_id": str(uuid.uuid4()), "from": "+491701234567",
                "text": "Antwort", "received_ms": phone.now_ms(), "subscription": -1}
    assert phone.validate_sms_received(received) is received
    assert phone.validate_sms_received(dict(received, **{"from": "BANKINFO"}))["from"] == "BANKINFO"
    posted = {"notification_id": str(uuid.uuid4()), "event": "posted",
              "package": "org.example.chat", "app_label": "Chat", "title": "Titel",
              "text": "Inhalt", "posted_ms": phone.now_ms()}
    assert phone.validate_selected_notification(posted) is posted
    invalid = [dict(command, to="0170"), dict(failed, error="none"),
               dict(received, subscription=17), dict(posted, action="reply"),
               dict(posted, event="removed", title="still present")]
    validators = [phone.validate_sms_send, phone.validate_sms_result,
                  phone.validate_sms_received, phone.validate_selected_notification,
                  phone.validate_selected_notification]
    for validator, value in zip(validators, invalid):
        try:
            validator(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid phone module payload accepted")


def test_notification_reply_kind_is_unsupported_but_sms_reply_is_a_command():
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    with tempfile.TemporaryDirectory() as root:
        service, peer_id = _paired_service(root, FakeBluetooth())
        peer = service.store.peer(peer_id)
        now = phone.now_ms()
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
            "kind": "selected_notifications_readonly.reply", "created_ms": now,
            "expires_ms": now + 60000, "body": {"text": "Nein"}}
        channel = Channel(); service._payload(peer, channel, message)
        assert channel.sent[-1]["error"] == "unsupported"
        assert phone.validate_sms_send({"to": "+491701234567", "text": "Antwort",
            "client_ref": str(uuid.uuid4())})


def test_sms_send_requires_phone_capability_and_grant_and_dedupes_client_ref():
    with tempfile.TemporaryDirectory() as root:
        service, peer_id = _paired_service(root, FakeBluetooth())
        peer = service.store.peer(peer_id)
        peer["capabilities"] = phone.desktop_capabilities()
        peer["capabilities"]["items"]["sms_send"] = {
            "available": True, "reason": "available", "versions": [1]}
        peer["grants"]["grants"]["sms_send"] = True
        reference = str(uuid.uuid4())
        service.send_sms(peer_id, "+491701234567", "Test", reference)
        assert service.store.sms_state(reference) == "queued"
        try:
            service.send_sms(peer_id, "+491701234567", "Test", reference)
        except RuntimeError:
            pass
        else:
            raise AssertionError("duplicate SMS client_ref accepted")


def test_incoming_phone_modules_require_local_grants():
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    with tempfile.TemporaryDirectory() as root:
        service, peer_id = _paired_service(root, FakeBluetooth())
        peer = service.store.peer(peer_id)
        now = phone.now_ms()
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
            "kind": "sms_received.event", "created_ms": now,
            "expires_ms": now + phone.DAY_MS, "body": {
                "sms_id": str(uuid.uuid4()), "from": "+491701234567", "text": "Hi",
                "received_ms": now, "subscription": -1}}
        channel = Channel(); service._payload(peer, channel, message)
        assert channel.sent[-1]["error"] == "not_granted"
        service.set_grant(peer_id, "sms_received", True)
        message["message_id"] = str(uuid.uuid4())
        service._payload(peer, channel, message)
        assert channel.sent[-1]["status"] == "accepted"


def test_secure_plaintext_must_be_canonical():
    class Socket:
        def __init__(self, frame): self.frame = frame
        def recv(self, length):
            part, self.frame = self.frame[:length], self.frame[length:]
            return part
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    sid, key, prefix = os.urandom(16), os.urandom(32), os.urandom(4)
    header = {"p": phone.PROTOCOL, "sid": phone.b64(sid), "seq": 0,
              "dir": "phone_to_desktop"}
    raw = b'{"type": "pong", "ping_id":"33333333-3333-4333-8333-333333333333","sent_ms":1}'
    cipher = AESGCM(key).encrypt(prefix + b"\0" * 8, raw, phone.canonical(header))
    envelope = dict(header, ciphertext=phone.b64(cipher))
    framed = phone.canonical(envelope)
    channel = phone.SecureChannel(Socket(len(framed).to_bytes(4, "big") + framed), sid,
                                  key, prefix, key, prefix)
    try:
        channel.receive()
    except ValueError:
        pass
    else:
        raise AssertionError("non-canonical secure plaintext accepted")


def _pending_peer(vectors, expires_ms):
    pairing = vectors["pairing"]
    return {"device_id": pairing["pair_init"]["device_id"],
            "display_name": pairing["pair_init"]["display_name"],
            "static_public": pairing["pair_init"]["static_public"],
            "state": "pair_commit_pending", "grants": phone.desktop_grants(),
            "capabilities": {}, "last_contact_ms": 0,
            "pending_transcript": pairing["transcript"],
            "pending_phone_finish_proof": pairing["phone_finish_proof"],
            "pending_desktop_finish_proof": pairing["desktop_finish_proof"],
            "pending_expires_ms": expires_ms}


def test_pair_commit_pending_survives_restart_and_retries_finish():
    path = os.path.join(ROOT, "..", "Entwicklungsnotizen",
                        "telefon-protokoll-vektoren.json")
    vectors = json.load(open(path, encoding="utf-8"))
    with tempfile.TemporaryDirectory() as root:
        store = phone.PhoneStore(os.path.join(root, "telefon"), "Test desktop")
        peer = _pending_peer(vectors, phone.now_ms() + phone.PAIR_COMMIT_MS)
        store.peers.append(peer)
        store.save_peers()
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop")
        left, right = socket.socketpair()
        try:
            finish = {"p": phone.PROTOCOL, "type": "pair_finish", "side": "phone",
                      "transcript": peer["pending_transcript"],
                      "proof": peer["pending_phone_finish_proof"]}
            service._finish_pending(left, finish)
            response = phone.receive_frame(right, phone.PAIR_FRAME_MAX)
            assert response["proof"] == vectors["pairing"]["desktop_finish_proof"]
            reopened = phone.PhoneStore(os.path.join(root, "telefon"), "Test desktop")
            assert reopened.peers[0]["state"] == "paired"
            assert not any(key.startswith("pending_") for key in reopened.peers[0])
        finally:
            left.close()
            right.close()


def test_expired_pair_commit_is_removed_on_restart():
    vectors = json.load(open(os.path.join(ROOT, "..", "Entwicklungsnotizen",
        "telefon-protokoll-vektoren.json"), encoding="utf-8"))
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "telefon")
        store = phone.PhoneStore(path, "Test desktop")
        store.peers.append(_pending_peer(vectors, phone.now_ms() - 1))
        store.save_peers()
        assert phone.PhoneStore(path, "Test desktop").peers == []


def test_queue_retry_ack_retention_and_status_request_persist():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "telefon")
        store = phone.PhoneStore(path, "Test desktop")
        message = store.queue("peer", "device_status.request",
                              {"request_id": str(uuid.uuid4())}, 60000)
        with mock.patch.object(phone, "now_ms", return_value=message["created_ms"]):
            store.mark_attempt("peer", message["message_id"])
        with __import__("sqlite3").connect(store.database_path) as db:
            attempt = db.execute("SELECT attempts,next_attempt_ms FROM outbox").fetchone()
        assert attempt == (1, message["created_ms"] + 1000)
        assert store.pending("peer") == []
        store.acknowledge("peer", message["message_id"])
        assert store.pending("peer") == []
        request_id = str(uuid.uuid4())
        store.register_status_request("peer", request_id, phone.now_ms() + 60000)
        reopened = phone.PhoneStore(path, "Test desktop")
        assert reopened.consume_status_request("peer", request_id)
        assert not reopened.consume_status_request("peer", request_id)


def test_payload_device_status_end_to_end_and_revision_rejection():
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    with tempfile.TemporaryDirectory() as root:
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop")
        peer_id = str(uuid.uuid4())
        peer = {"device_id": peer_id, "display_name": "Telefon",
                "static_public": phone.b64(os.urandom(32)), "state": "paired",
                "grants": phone.desktop_grants(), "capabilities": phone.desktop_capabilities(),
                "last_contact_ms": 0}
        service.store.peers.append(peer)
        service.store.save_peers()
        request_id = service.request_status(peer_id)
        report = {"request_id": request_id, "model": "Pixel", "manufacturer": "Google",
                  "os_name": "Android", "os_version": "16", "battery_percent": 50,
                  "charging": "discharging", "captured_ms": phone.now_ms()}
        channel = Channel()
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
                   "kind": "device_status.report", "created_ms": phone.now_ms(),
                   "expires_ms": phone.now_ms() + 300000, "body": report}
        service._payload(peer, channel, message)
        assert channel.sent[-1]["status"] == "accepted"
        assert service.store.status(peer_id)["request_id"] == request_id
        capabilities = phone.desktop_capabilities(2)
        peer["capabilities"] = phone.desktop_capabilities(3)
        message.update(message_id=str(uuid.uuid4()), kind="capabilities.update",
                       body=capabilities)
        service._payload(peer, channel, message)
        assert channel.sent[-1] == {"type": "ack", "message_id": message["message_id"],
                                    "status": "rejected", "error": "invalid_schema"}


def test_device_status_report_requires_confirmed_grant():
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    with tempfile.TemporaryDirectory() as root:
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop")
        peer_id, request_id = str(uuid.uuid4()), str(uuid.uuid4())
        grants = phone.desktop_grants(); grants["grants"]["device_status"] = False
        peer = {"device_id": peer_id, "display_name": "Telefon",
                "static_public": phone.b64(os.urandom(32)), "state": "paired",
                "grants": grants, "capabilities": {}, "last_contact_ms": 0}
        message = {"type": "message", "v": 1, "message_id": str(uuid.uuid4()),
                   "kind": "device_status.report", "created_ms": phone.now_ms(),
                   "expires_ms": phone.now_ms() + 300000, "body": {
                       "request_id": request_id, "model": "Pixel", "manufacturer": "Google",
                       "os_name": "Android", "os_version": "16", "battery_percent": 50,
                       "charging": "discharging", "captured_ms": phone.now_ms()}}
        channel = Channel(); service._payload(peer, channel, message)
        assert channel.sent[-1]["status"] == "rejected"
        assert channel.sent[-1]["error"] == "not_granted"


def test_kind_specific_ttl_is_rejected():
    class Channel:
        def __init__(self): self.sent = []
        def send(self, value): self.sent.append(value)
    with tempfile.TemporaryDirectory() as root:
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop")
        peer = {"device_id": str(uuid.uuid4()), "display_name": "Telefon",
                "static_public": phone.b64(os.urandom(32)), "state": "paired",
                "grants": phone.desktop_grants(), "capabilities": {}, "last_contact_ms": 0}
        now = phone.now_ms(); message = {"type": "message", "v": 1,
            "message_id": str(uuid.uuid4()), "kind": "capabilities.update",
            "created_ms": now, "expires_ms": now + phone.DAY_MS + 1,
            "body": phone.desktop_capabilities(2)}
        channel = Channel(); service._payload(peer, channel, message)
        assert channel.sent[-1]["error"] == "invalid_schema"


def test_source_has_no_tree_status_types():
    source = open(os.path.join(ROOT, "bin", "magnolie-organizer"),
                  encoding="utf-8").read()
    share_start = source.index("def _baum_teilen")
    share_end = source.index("def _baum_rueckmeldung", share_start)
    receive_start = source.index("def _baum_empfangen")
    receive_end = source.index("def _baum_bericht", receive_start)
    assert "geraete_status" not in source[share_start:share_end]
    assert "geraete_status" not in source[receive_start:receive_end]
    assert "baum_geraete_status_pruefen" not in source
    assert 'art in ("geraete_status_anfrage", "geraete_status")' in source
    assert "BAUM_BLUETOOTH_UUID" not in open(
        os.path.join(ROOT, "bin", "magnolie_telefon.py"), encoding="utf-8").read()


def test_mdns_publishes_routable_address():
    class RouteSocket:
        def connect(self, destination):
            assert destination == ("192.0.2.1", 9)
        def getsockname(self): return ("192.168.178.43", 54321)
        def close(self): pass

    class Zeroconf:
        published = None
        def __init__(self, **_kwargs): pass
        def register_service(self, info): Zeroconf.published = info

    class ServiceInfo:
        def __init__(self, *_args, **kwargs): self.kwargs = kwargs

    class IPVersion:
        All = object()

    with tempfile.TemporaryDirectory() as root, \
            mock.patch.object(phone.socket, "socket", return_value=RouteSocket()), \
            mock.patch.dict("sys.modules", {"zeroconf": mock.Mock(
                IPVersion=IPVersion, ServiceInfo=ServiceInfo, Zeroconf=Zeroconf)}):
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop")
        service.enabled = True
        service.server = object()
        service._publish()
        assert Zeroconf.published.kwargs["addresses"] == [phone.socket.inet_aton("192.168.178.43")]


class FakeBluetooth:
    def __init__(self, paired=True):
        self.is_paired = paired
        self.connected = []
        self.socket = mock.Mock()
    def availability(self): return True, "available"
    def paired(self, _address): return self.is_paired
    def connect(self, address, service_uuid):
        self.connected.append((address, service_uuid))
        return self.socket


def _paired_service(root, backend):
    service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop",
                                 bluetooth_backend=backend)
    peer_id = str(uuid.uuid4())
    service.store.peers.append({"device_id": peer_id, "display_name": "Telefon",
        "static_public": phone.b64(os.urandom(32)), "state": "paired",
        "grants": phone.desktop_grants(), "capabilities": {}, "last_contact_ms": 0,
        "bluetooth": {"enabled": False, "address": ""}})
    service.store.save_peers()
    return service, peer_id


def test_bluetooth_uuid_peer_binding_and_encrypted_address():
    backend = FakeBluetooth()
    with tempfile.TemporaryDirectory() as root:
        service, peer_id = _paired_service(root, backend)
        address = "AA:BB:CC:DD:EE:FF"
        service.set_bluetooth(peer_id, True, address)
        assert service.store.peer(peer_id)["bluetooth"]["address"] == address
        assert address.encode() not in open(service.store.peers_path, "rb").read()
        assert not os.path.exists(service.store.settings_path)
        service.wifi_missing_since[peer_id] = 0
        with mock.patch.object(phone.threading, "Thread"):
            service._bluetooth_tick(phone.BLUETOOTH_FALLBACK_SECONDS + 1)
        assert backend.connected == [(address, phone.BLUETOOTH_UUID)]
        assert phone.BLUETOOTH_UUID != "6d61676e-6f6c-6965-6e62-61756d383733"


def test_system_pairing_without_phone_peer_cannot_enable_fallback():
    backend = FakeBluetooth()
    with tempfile.TemporaryDirectory() as root:
        service = phone.PhoneService(os.path.join(root, "telefon"), "Test desktop",
                                     bluetooth_backend=backend)
        try:
            service.set_bluetooth(str(uuid.uuid4()), True, "AA:BB:CC:DD:EE:FF")
        except RuntimeError:
            pass
        else:
            raise AssertionError("system-paired unknown device accepted")
        service._bluetooth_tick(100)
        assert backend.connected == []


def test_wifi_priority_fallback_delay_and_disable_closes_rfcomm():
    backend = FakeBluetooth()
    with tempfile.TemporaryDirectory() as root:
        service, peer_id = _paired_service(root, backend)
        service.set_bluetooth(peer_id, True, "AA:BB:CC:DD:EE:FF")
        service.wifi_missing_since[peer_id] = 10
        service._bluetooth_tick(24)
        assert backend.connected == []
        service.connection_transports[peer_id] = "wifi"
        service._bluetooth_tick(100)
        assert backend.connected == []
        channel = mock.Mock()
        service.connections[peer_id] = channel
        service.connection_transports[peer_id] = "bluetooth"
        service.set_bluetooth(peer_id, False)
        channel.send.assert_called_once_with({"type": "close", "reason": "normal"})
        channel.sock.close.assert_called_once()


def test_authenticated_wifi_replaces_bluetooth_in_order():
    with tempfile.TemporaryDirectory() as root:
        service, peer_id = _paired_service(root, FakeBluetooth())
        old = mock.Mock()
        service.connections[peer_id] = old
        service.connection_transports[peer_id] = "bluetooth"
        service._activate_connection(peer_id, mock.Mock(), "wifi")
        old.send.assert_called_once_with({"type": "close", "reason": "better_transport"})
        old.sock.close.assert_called_once()
        rejected = mock.Mock()
        try:
            service._activate_connection(peer_id, rejected, "bluetooth")
        except OSError:
            pass
        else:
            raise AssertionError("RFCOMM replaced active WLAN")
        rejected.send.assert_called_once_with(
            {"type": "close", "reason": "better_transport"})


if __name__ == "__main__":
    for name, value in sorted(globals().copy().items()):
        if name.startswith("test_") and callable(value):
            value()
            print("ok -", name)
