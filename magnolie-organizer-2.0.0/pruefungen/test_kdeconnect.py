import json
import os
import queue
import socket
import sys
import tempfile
import threading
import time
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import magnolie_kdeconnect as kde


def identity(device_id="a" * 32, port=1716, capabilities=None):
    return kde.network_packet("kdeconnect.identity", {"deviceId": device_id,
        "deviceName": "Phone", "deviceType": "phone", "protocolVersion": 8,
        "incomingCapabilities": capabilities or [], "outgoingCapabilities": [],
        "tcpPort": port})


def test_strict_newline_json_codec_over_loopback():
    left, right = socket.socketpair()
    try:
        packet = kde.network_packet("example", {"text": "Hallo"})
        left.sendall(kde.encode_packet(packet))
        assert kde.read_packet(right) == packet
        for invalid in (b'{"a":1}\r\n', b'{"a":1}\n{}\n', b'{"a":1,"a":2}\n',
                        b'{"a":NaN}\n', b'[]\n'):
            with pytest.raises(kde.ProtocolError):
                kde.decode_packet(invalid)
    finally:
        left.close(); right.close()


def test_identity_store_is_persistent_p256_and_rejects_open_key_permissions():
    with tempfile.TemporaryDirectory() as root:
        first = kde.IdentityStore(root, "Desktop")
        second = kde.IdentityStore(root, "Changed name")
        assert first.device_id == second.device_id
        assert first.certificate.fingerprint(kde.hashes.SHA256()) == second.certificate.fingerprint(kde.hashes.SHA256())
        assert first.key.curve.name == "secp256r1"
        os.chmod(first.key_path, 0o644)
        with pytest.raises(kde.ProtocolError):
            kde.IdentityStore(root, "Desktop")


def test_default_device_name_contains_short_hostname():
    with mock.patch.object(kde.socket, "gethostname", return_value="wohnzimmer.example.org"):
        assert kde.local_device_name() == "Magnolie Organizer (wohnzimmer)"
        with tempfile.TemporaryDirectory() as root:
            backend = kde.KDEConnectSMSBackend(root)
            assert backend.store.device_name == "Magnolie Organizer (wohnzimmer)"

    long_name = "a" * 200
    assert len(kde.local_device_name(long_name)) == 128


class FakeUdp:
    def __init__(self, datagrams): self.datagrams = list(datagrams)
    def recvfrom(self, _size): return self.datagrams.pop(0)


class BroadcastUdp:
    instances = []
    def __init__(self, *_args):
        self.sent = []; self.bound = None; self.closed = False
        self.instances.append(self)
    def setsockopt(self, *_args): pass
    def bind(self, address): self.bound = address
    def sendto(self, data, target): self.sent.append((kde.decode_packet(data), target))
    def close(self): self.closed = True


def test_discovery_accepts_only_valid_private_v8_identity():
    valid = kde.encode_packet(identity())
    invalid = kde.encode_packet(identity("b" * 32, port=9999))
    udp = FakeUdp([(invalid, ("192.168.1.5", 1716)),
                   (valid, ("198.51.100.4", 1716)),
                   (valid, ("127.0.0.1", 1716))])
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        found = {}
        for _item in range(3):
            backend._receive_udp_identity(udp, found)
        packet = backend.identity_packet(tcp_port=1732)
    found = list(found.values())
    assert len(found) == 1 and found[0].address == "127.0.0.1"
    assert packet["body"]["tcpPort"] == 1732


def free_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_service_keeps_dynamic_tcp_and_udp_listeners_until_idempotent_stop():
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, tcp_ports=[0],
            udp_port=free_udp_port(), backoff=[60])
        assert backend.start() and backend.start()
        port = backend.listen_port
        assert backend.status(0)["listening"] and port > 0
        probe = socket.create_connection(("127.0.0.1", port), timeout=1)
        probe.close()
        backend.stop(); backend.stop()
        assert not backend.listening and backend.reason == "stopped"


def test_concurrent_start_stop_does_not_replace_or_leak_service_socket():
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, tcp_ports=[0],
            udp_port=free_udp_port(), backoff=[60])
        starters = [threading.Thread(target=backend.start) for _item in range(4)]
        for thread in starters: thread.start()
        for thread in starters: thread.join(2)
        service = backend._service_thread
        udp = backend._udp
        assert service is not None and service.is_alive() and udp is not None
        stoppers = [threading.Thread(target=backend.stop) for _item in range(4)]
        for thread in stoppers: thread.start()
        for thread in stoppers: thread.join(12)
        assert all(not thread.is_alive() for thread in stoppers)
        assert backend._service_thread is None and backend._udp is None


def test_running_udp_listener_caches_private_identity():
    udp_port = free_udp_port()
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, tcp_ports=[0], udp_port=udp_port,
            backoff=[60])
        backend.start()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(kde.encode_packet(identity("b" * 32, kde.MIN_TCP_PORT)),
                      ("127.0.0.1", udp_port))
        deadline = time.monotonic() + 2
        while "b" * 32 not in backend._devices and time.monotonic() < deadline:
            time.sleep(.01)
        assert backend._devices["b" * 32][0].address == "127.0.0.1"
        sender.close(); backend.stop()


def test_broadcast_uses_per_interface_ephemeral_socket_and_udp_1716_only():
    with tempfile.TemporaryDirectory() as root:
        BroadcastUdp.instances = []
        backend = kde.KDEConnectSMSBackend(root, tcp_ports=[1716],
            socket_factory=BroadcastUdp)
        backend._udp = object(); backend.listen_port = 1764
        with mock.patch.object(kde, "ipv4_discovery_interfaces", return_value=(
                ("192.168.178.20", ("192.168.178.255", "255.255.255.255")),
                ("10.0.0.2", ("255.255.255.255",)),)):
            backend._broadcast()
        assert [item.bound for item in BroadcastUdp.instances] == [
            ("192.168.178.20", 0), ("10.0.0.2", 0)]
        sent = [entry for item in BroadcastUdp.instances for entry in item.sent]
        assert [target for _packet, target in sent] == [("192.168.178.255", 1716),
            ("255.255.255.255", 1716), ("255.255.255.255", 1716)]
        assert all(packet["body"]["tcpPort"] == 1764 for packet, _target in sent)
        assert all(item.closed for item in BroadcastUdp.instances)


def test_tcp_identity_accepts_android_target_without_tcp_port():
    left, right = socket.socketpair()
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        packet = identity("d" * 32)
        packet["body"].pop("tcpPort")
        packet["body"].update(targetDeviceId=backend.store.device_id,
                              targetProtocolVersion="8")
        right.sendall(kde.encode_packet(packet))
        pending = {left: (bytearray(), "127.0.0.1")}
        devices, accepted = {}, {}
        while left in pending:
            backend._receive_tcp_identity(left, pending, devices, accepted)
        assert accepted["d" * 32] is left
        assert devices["d" * 32].port == 1716
        assert devices["d" * 32].identity["targetProtocolVersion"] == 8
        accepted["d" * 32].close()
    right.close()


def test_live_listener_routes_tcp_identity_callback_to_handler():
    udp_port = free_udp_port()
    handled = threading.Event()
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, tcp_ports=[0], udp_port=udp_port,
            backoff=[60])
        def handler(raw, device):
            assert device.identity["targetProtocolVersion"] == 8
            assert device.identity["deviceId"] == "9b68b0bf7d80417288655b914e4f60c7"
            raw.close(); handled.set()
        with mock.patch.object(backend, "_handle_incoming", side_effect=handler):
            assert backend.start()
            phone = socket.create_connection(("127.0.0.1", backend.listen_port), timeout=1)
            packet = identity("9b68b0bf7d80417288655b914e4f60c7")
            packet["body"].pop("tcpPort")
            packet["body"].update(deviceName="Galaxy S24",
                targetDeviceId=backend.store.device_id, targetProtocolVersion="8")
            phone.sendall(kde.encode_packet(packet))
            assert handled.wait(2)
            phone.close(); backend.stop()


def test_observed_android_identity_normalizes_only_canonical_target_version():
    packet = kde.network_packet("kdeconnect.identity", {
        "deviceId": "9b68b0bf7d80417288655b914e4f60c7", "deviceName": "Galaxy S24",
        "deviceType": "phone", "protocolVersion": 8,
        "incomingCapabilities": [kde.SMS_REQUEST_TYPE,
            kde.SMS_REQUEST_CONVERSATIONS_TYPE, kde.SMS_REQUEST_CONVERSATION_TYPE,
            "kdeconnect.sms.request_attachment"],
        "outgoingCapabilities": [kde.SMS_MESSAGES_TYPE],
        "targetDeviceId": "a" * 32, "targetProtocolVersion": "8"})
    assert kde.validate_identity(packet)["targetProtocolVersion"] == 8
    for invalid in (True, False, 7, 9, "08", " 8", "8 ", "8.0", "09"):
        changed = json.loads(json.dumps(packet))
        changed["body"]["targetProtocolVersion"] = invalid
        with pytest.raises(kde.ProtocolError):
            kde.validate_identity(changed)
    changed = json.loads(json.dumps(packet))
    changed["body"]["tcpPort"] = "1716"
    with pytest.raises(kde.ProtocolError):
        kde.validate_identity(changed)


def test_sms_capabilities_and_request_packet_goldens():
    with tempfile.TemporaryDirectory() as root:
        packet = kde.KDEConnectSMSBackend(root).identity_packet()
    assert packet["body"]["incomingCapabilities"] == [kde.SMS_MESSAGES_TYPE]
    assert packet["body"]["outgoingCapabilities"] == [kde.SMS_REQUEST_TYPE,
        kde.SMS_REQUEST_CONVERSATIONS_TYPE, kde.SMS_REQUEST_CONVERSATION_TYPE]
    conversations = kde.request_conversations_packet()
    assert {"type": conversations["type"], "body": conversations["body"]} == {
        "type": "kdeconnect.sms.request_conversations", "body": {}}
    conversation = kde.request_conversation_packet(42)
    assert {"type": conversation["type"], "body": conversation["body"]} == {
        "type": "kdeconnect.sms.request_conversation", "body": {
            "threadID": 42, "rangeStartTimestamp": -1}}


class FakeConnection:
    def __init__(self): self.sent = []; self.closed = False; self.connection = None
    def sendall(self, data): self.sent.append(kde.decode_packet(data))
    def close(self): self.closed = True


class FakeBatch:
    def __init__(self, devices): self.devices = devices
    def take(self, _device_id): return None
    def __enter__(self): return self
    def __exit__(self, *_args): pass


def test_text_only_sms_v2_is_sent_once_without_retry():
    device_id = "c" * 32
    discovered = kde.DiscoveredDevice("127.0.0.1", 1716,
        kde.validate_identity(identity(device_id, capabilities=[kde.SMS_TYPE]), True))
    secure = dict(discovered.identity)
    connection = FakeConnection()
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        backend.store.peers[device_id] = {"name": "Phone", "protocolVersion": 8,
            "certificate": backend.store.certificate.public_bytes(
                kde.serialization.Encoding.PEM).decode("ascii"), "paired": True,
            "pairingConfirmedMs": 1}
        def connect_now(device):
            opened()
            backend._remember_connection(connection, secure)
        with mock.patch.object(backend, "discover", return_value=[discovered]), \
             mock.patch.object(backend, "_tls_connection",
                 return_value=(connection, secure, backend.store.certificate)) as opened, \
             mock.patch.object(backend, "_connect_device", side_effect=connect_now), \
             mock.patch.object(threading.Thread, "start"):
            result = backend.send_sms("+491701234567", "One\nmessage")
    assert result["backend"] == "kdeconnect-direct" and opened.call_count == 1
    assert result["backend"] == "kdeconnect-direct"
    queued = backend._connections[device_id]["worker"].outgoing
    packets = []
    while not queued.empty(): packets.append(queued.get_nowait())
    assert [packet["type"] for packet in packets] == [kde.SMS_REQUEST_TYPE]
    assert packets[-1]["body"] == {"version": 2,
        "addresses": [{"address": "+491701234567"}], "messageBody": "One\nmessage"}
    assert set(packets[-1]["body"]) == {"version", "addresses", "messageBody"}


def test_sms_text_normalization_and_segment_boundaries():
    allowed = "äöüÄÖÜéàèùìòÇØøÅåÆæÑñ¿¡£¥€^{}\\[~]|"
    assert kde.normalize_sms_text(allowed)["text"] == allowed
    assert kde.normalize_sms_text("Grüße 🙂 ❤️ 👍🏽 — ‘ok’ …") ["text"] == \
        "Grüße :) <3 +1 - 'ok' ..."
    assert kde.normalize_sms_text("crème ô Ł ☀")["text"] == "crème o ? [Symbol]"
    assert kde.normalize_sms_text("a" * 160)["segments"] == 1
    assert kde.normalize_sms_text("a" * 161)["segments"] == 2
    assert kde.normalize_sms_text("^" * 80)["segments"] == 1
    assert kde.normalize_sms_text("^" * 81)["segments"] == 2
    assert kde.normalize_sms_text("a" * 306)["segments"] == 2
    assert kde.normalize_sms_text("a" * 307)["segments"] == 3


def test_sms_backend_never_sends_original_unsupported_unicode():
    device_id = "b" * 32
    secure = kde.validate_identity(identity(device_id, capabilities=[kde.SMS_TYPE]), True)
    queued = queue.Queue()
    worker = mock.Mock(); worker.outgoing = queued
    worker.stopped.is_set.return_value = False
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        backend.store.peers[device_id] = {"name": "Phone", "protocolVersion": 8,
            "certificate": "unused", "paired": True, "pairingConfirmedMs": 1}
        backend._connections[device_id] = {"identity": secure, "worker": worker,
            "connection": mock.Mock()}
        worker.send.side_effect = queued.put
        backend.send_sms("+491701234567", "Hallo 🙂")
    assert queued.get_nowait()["body"]["messageBody"] == "Hallo :)"


def test_status_and_sms_reuse_held_connection_without_discovery():
    device_id = "e" * 32
    secure = kde.validate_identity(identity(device_id, capabilities=[kde.SMS_TYPE]), True)
    connection = FakeConnection()
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        backend.store.peers[device_id] = {"name": "Phone", "protocolVersion": 8,
            "certificate": backend.store.certificate.public_bytes(
                kde.serialization.Encoding.PEM).decode("ascii"), "paired": True,
            "pairingConfirmedMs": 1}
        with mock.patch.object(threading.Thread, "start"):
            backend._remember_connection(connection, secure)
        with mock.patch.object(backend, "discover") as discovery:
            status = backend.status()
            result = backend.send_sms("+491701234567", "Held connection")
        assert not discovery.called
        assert status["available"] and status["device_id"] == device_id
        assert result["device_id"] == device_id and not connection.closed
        assert backend._connections[device_id]["worker"].outgoing.qsize() == 1
        backend._forget_connection(device_id, connection)


def test_sms_v2_parser_is_bounded_marks_groups_and_stable_ids():
    packet = kde.network_packet(kde.SMS_MESSAGES_TYPE, {"version": 2, "messages": [
        {"_id": 7, "thread_id": 3, "addresses": [{"address": "+491701234567"}],
         "body": "Hallo", "date": "1786617000000", "type": "1", "read": 1,
         "sub_id": 0, "event": 1},
        {"_id": 8, "thread_id": 4, "addresses": [{"address": "+491701234567"},
          {"address": "+491709999999"}], "body": "Gruppe", "date": 1786617000001,
         "type": 2, "read": "0", "event": 3}]})
    parsed = kde.parse_sms_messages(packet, "a" * 32)
    assert parsed[0]["id"] == "a" * 32 + ":3:7" and parsed[0]["incoming"]
    assert not parsed[0]["group"] and parsed[1]["group"] and not parsed[1]["incoming"]


def test_sms_parser_skips_bad_rows_and_hashes_missing_official_id():
    valid = {"thread_id": "3", "addresses": [{"address": "+491701234567"}],
        "body": "Missed reply", "date": 1786617000000, "type": 1,
        "read": "0", "sub_id": "1", "event": 1}
    packet = kde.network_packet(kde.SMS_MESSAGES_TYPE, {"version": 2, "messages": [
        {}, dict(valid, event="text"), dict(valid, read="true"),
        dict(valid, event=2), valid]})
    stats = {}
    parsed = kde.parse_sms_messages(packet, "a" * 32, stats)
    assert len(parsed) == 1 and parsed[0]["sms_id"].startswith("h")
    assert parsed == kde.parse_sms_messages(packet, "a" * 32)
    assert stats == {"valid": 1, "skipped": 4}
    with pytest.raises(kde.ProtocolError):
        kde.parse_sms_messages(kde.network_packet(kde.SMS_MESSAGES_TYPE,
            {"version": 2, "messages": [dict(valid, body="x" * 5001)]}), "a" * 32)
    assert len(kde.parse_sms_messages(kde.network_packet(kde.SMS_MESSAGES_TYPE,
        {"version": 2, "messages": [dict(valid, read=True)]}), "a" * 32)) == 1


def sms_packet(thread, message_id, text, message_type=1, read=1):
    return kde.network_packet(kde.SMS_MESSAGES_TYPE, {"version": 2, "messages": [{
        "_id": message_id, "thread_id": thread,
        "addresses": [{"address": "+491701234567"}], "body": text,
        "date": 1786617000000 + int(message_id), "type": message_type,
        "read": read, "sub_id": 0, "event": 1}]})


def sms_messages_packet(rows):
    return kde.network_packet(kde.SMS_MESSAGES_TYPE, {"version": 2, "messages": [
        {"_id": message_id, "thread_id": thread,
         "addresses": [{"address": "+491701234567"}], "body": text,
         "date": 1786617000000 + int(message_id), "type": 1,
         "read": read, "sub_id": 0, "event": 1}
        for thread, message_id, text, read in rows]})


def sms_worker(capabilities=None):
    backend = mock.Mock()
    backend.clock.return_value = 100.0
    worker = kde._ConnectionWorker(backend, FakeConnection(), {
        "deviceId": "f" * 32, "incomingCapabilities": capabilities or [
            kde.SMS_REQUEST_CONVERSATIONS_TYPE,
            kde.SMS_REQUEST_CONVERSATION_TYPE]})
    worker.enable_sms()
    return backend, worker


def test_worker_collects_multiple_summaries_full_threads_then_notifies_live():
    backend, worker = sms_worker()
    worker._handle_sms_packet(sms_packet(1, 1, "summary one"))
    worker._handle_sms_packet(sms_packet(2, 2, "summary two"))
    assert not backend._deliver_sms.called
    requested = []
    while not worker.outgoing.empty(): requested.append(worker.outgoing.get_nowait())
    assert [item["type"] for item in requested] == [kde.SMS_REQUEST_CONVERSATIONS_TYPE,
        kde.SMS_REQUEST_CONVERSATION_TYPE, kde.SMS_REQUEST_CONVERSATION_TYPE]
    worker._handle_sms_packet(sms_packet(1, 3, "thread one", 2))
    worker._handle_sms_packet(sms_packet(2, 4, "missed reply"))
    assert [call.args[0]["text"] for call in backend._deliver_sms.call_args_list] == [
        "thread one", "missed reply"]
    assert all(call.kwargs["notify"] is False
               for call in backend._deliver_sms.call_args_list)
    backend.clock.return_value = 102.0
    worker._check_bootstrap_deadline()
    worker._handle_sms_packet(sms_packet(2, 5, "new live"))
    assert backend._deliver_sms.call_args.kwargs["notify"] is True
    assert backend._deliver_sms.call_args.args[0]["text"] == "new live"
    assert worker.diagnostics["bootstrap_state"] == "live"


def test_summary_full_overlap_is_delivered_once_and_not_early():
    backend, worker = sms_worker()
    worker._handle_sms_packet(sms_packet(7, 41, "same message"))
    assert not backend._deliver_sms.called
    worker._handle_sms_packet(sms_messages_packet([
        (7, 41, "same message", 0), (7, 42, "same message", 1)]))
    assert [call.args[0]["sms_id"] for call in backend._deliver_sms.call_args_list] == [
        "41", "42"]
    assert all(call.kwargs["notify"] is False
               for call in backend._deliver_sms.call_args_list)


def test_mixed_packet_routes_pending_history_and_buffers_new_summary():
    backend, worker = sms_worker()
    worker._handle_sms_packet(sms_packet(1, 1, "summary one"))
    worker._handle_sms_packet(sms_messages_packet([
        (1, 1, "summary one", 0), (1, 3, "older one", 1),
        (2, 2, "summary two", 1)]))
    assert [call.args[0]["sms_id"] for call in backend._deliver_sms.call_args_list] == [
        "1", "3"]
    assert set(worker.bootstrap_buffered) == {"2"}
    worker._handle_sms_packet(sms_messages_packet([
        (2, 2, "summary two", 0), (2, 4, "older two", 1)]))
    assert [call.args[0]["sms_id"] for call in backend._deliver_sms.call_args_list] == [
        "1", "3", "2", "4"]


def test_bootstrap_timeout_flushes_unanswered_summaries_once():
    backend, worker = sms_worker()
    worker._handle_sms_packet(sms_packet(9, 9, "fallback"))
    backend.clock.return_value = 106.0
    worker._check_bootstrap_deadline()
    worker._check_bootstrap_deadline()
    assert backend._deliver_sms.call_count == 1
    assert backend._deliver_sms.call_args.args[0]["sms_id"] == "9"
    assert backend._deliver_sms.call_args.kwargs["notify"] is False
    worker._handle_sms_packet(sms_messages_packet([
        (9, 9, "fallback", 1), (9, 10, "older", 1)]))
    assert backend._deliver_sms.call_count == 2
    assert backend._deliver_sms.call_args.args[0]["sms_id"] == "10"
    assert backend._deliver_sms.call_args.kwargs["notify"] is False


def test_same_official_id_read_variation_is_delivered_once():
    backend, worker = sms_worker()
    worker._handle_sms_packet(sms_packet(3, "41", "message", read=0))
    assert not backend._deliver_sms.called
    worker._handle_sms_packet(sms_messages_packet([
        (3, "41", "message", 1), (3, 41, "message", 0)]))
    assert backend._deliver_sms.call_count == 1


def test_conversation_summaries_deliver_without_full_history_capability():
    backend, worker = sms_worker([kde.SMS_REQUEST_CONVERSATIONS_TYPE])
    worker._handle_sms_packet(sms_packet(1, 1, "summary"))
    assert backend._deliver_sms.call_count == 1
    assert backend._deliver_sms.call_args.kwargs["notify"] is False


def test_delivery_emits_outgoing_history_without_notification():
    events = []
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root,
            callback=lambda event, value: events.append((event, value)))
        device_id = "a" * 32
        backend.store.peers[device_id] = {"paired": True}
        backend._deliver_sms({"device_id": device_id, "incoming": False,
            "group": False}, notify=True)
    assert events[0][1]["notify"] is False and events[0][1]["incoming"] is False


def test_outbound_newcomer_loses_to_healthy_connection():
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        secure = kde.validate_identity(identity("e" * 32), True)
        old, new = FakeConnection(), FakeConnection()
        first = backend._remember_connection(old, secure, start=False)
        second = backend._remember_connection(new, secure, start=False)
        assert second is first and backend._connections["e" * 32]["connection"] is old
        assert new.closed and not old.closed


def test_android_inbound_replaces_link_and_stale_finalizer_keeps_new_generation():
    device_id = "0" * 32
    secure = kde.validate_identity(identity(device_id), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        old, new = FakeConnection(), FakeConnection()
        first = backend._remember_connection(old, secure, start=False,
            direction="incoming")
        second = backend._remember_connection(new, secure, start=False,
            direction="incoming")
        entry = backend._connections[device_id]
        assert second is not first and entry["connection"] is new
        assert entry["direction"] == "incoming" and entry["generation"] == 2
        assert old.closed and not new.closed
        backend._worker_died(device_id, first)
        assert backend._connections[device_id]["worker"] is second
        assert not new.closed


def test_inbound_replacement_transfers_sms_bootstrap_and_seen_state():
    device_id = "0" * 32
    secure = kde.validate_identity(identity(device_id, capabilities=[
        kde.SMS_REQUEST_TYPE, kde.SMS_REQUEST_CONVERSATIONS_TYPE,
        kde.SMS_REQUEST_CONVERSATION_TYPE]), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        backend.store.peers[device_id] = {"paired": True}
        first = backend._remember_connection(FakeConnection(), secure, start=False,
            direction="incoming")
        first.enable_sms()
        first._handle_sms_packet(sms_packet(7, 41, "pending summary"))
        first._remember_seen(device_id + ":8:42")
        second = backend._remember_connection(FakeConnection(), secure, start=False,
            direction="incoming")
        assert second.sms_started and second.bootstrap
        assert second.bootstrap_requested == {"7"}
        assert second.bootstrap_buffered["7"][0]["sms_id"] == "41"
        assert device_id + ":8:42" in second.seen
        assert list(second.seen_order)[-1] == device_id + ":8:42"


def test_inbound_replacement_transfers_pending_pairing_without_resetting_flags():
    device_id = "f" * 32
    secure = kde.validate_identity(identity(device_id), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        certificate = backend.store.certificate
        first = backend._remember_connection(FakeConnection(), secure, certificate,
            "127.0.0.1", 1716, start=False, direction="incoming")
        backend.pairing = {"state": "requested", "direction": "incoming",
            "worker": first, "identity": secure, "certificate": certificate,
            "timestamp": 123, "address": "127.0.0.1", "port": 1716,
            "local_confirmed": True, "remote_confirmed": True, "deadline": 456}
        second = backend._remember_connection(FakeConnection(), secure, certificate,
            "127.0.0.2", 1717, start=False, direction="incoming")
        assert backend.pairing["worker"] is second
        assert backend.pairing["timestamp"] == 123
        assert backend.pairing["local_confirmed"] is True
        assert backend.pairing["remote_confirmed"] is True
        assert backend.pairing["deadline"] == 456


def test_pairing_code_matches_protocol_v8_sorted_spki_formula():
    with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
        a, b = kde.IdentityStore(one, "A"), kde.IdentityStore(two, "B")
        timestamp = 1786617000
        keys = [cert.public_key().public_bytes(kde.serialization.Encoding.DER,
            kde.serialization.PublicFormat.SubjectPublicKeyInfo) for cert in (a.certificate, b.certificate)]
        keys.sort(reverse=True)
        expected = kde.sha256(keys[0] + keys[1] + str(timestamp).encode()).hexdigest()[:8].upper()
        assert kde.pairing_code(a.certificate, b.certificate, timestamp) == expected


def test_pairing_acceptance_requires_remote_and_local_confirmation():
    with tempfile.TemporaryDirectory() as local_root, tempfile.TemporaryDirectory() as peer_root:
        backend = kde.KDEConnectSMSBackend(local_root, "Desktop")
        peer = kde.IdentityStore(peer_root, "Phone")
        peer_identity = kde.validate_identity(identity(peer.device_id,
            capabilities=[kde.SMS_TYPE]))
        worker = mock.Mock(); worker.identity = peer_identity
        backend.pairing = {"state": "requested", "direction": "outgoing", "worker": worker,
            "identity": peer_identity, "certificate": peer.certificate,
            "timestamp": 1786617000, "address": "127.0.0.1", "port": 1716,
            "local_confirmed": False, "remote_confirmed": False,
            "deadline": kde.time.monotonic() + 10}
        assert backend.confirm_pairing(True)["state"] == "waiting_for_phone"
        assert peer.device_id not in backend.store.peers
        backend._pair_packet(worker, kde.network_packet("kdeconnect.pair", {"pair": True}))
        reopened = kde.IdentityStore(local_root, "Desktop")
        assert peer.device_id in reopened.peers
        assert reopened.peers[peer.device_id]["paired"] is True
        assert reopened.peers[peer.device_id]["pairingConfirmedMs"] > 0
        assert reopened.peers[peer.device_id]["lastAddress"] == "127.0.0.1"
        assert reopened.peers[peer.device_id]["lastPort"] == 1716
        stored = kde.x509.load_pem_x509_certificate(
            reopened.peers[peer.device_id]["certificate"].encode("ascii"))
        assert stored.fingerprint(kde.hashes.SHA256()) == peer.certificate.fingerprint(
            kde.hashes.SHA256())
        worker.enable_sms.assert_called_once()


def test_inbound_pairing_event_confirm_and_reject_without_automatic_trust():
    events = []
    with tempfile.TemporaryDirectory() as local_root, tempfile.TemporaryDirectory() as peer_root:
        backend = kde.KDEConnectSMSBackend(local_root,
            callback=lambda event, payload: events.append((event, payload)))
        peer = kde.IdentityStore(peer_root, "Phone")
        connection = FakeConnection()
        secure = kde.validate_identity(identity(peer.device_id,
            capabilities=[kde.SMS_TYPE]))
        timestamp = int(time.time())
        worker = backend._remember_connection(connection, secure, peer.certificate,
            "127.0.0.1", 1716, start=False)
        backend._pair_packet(worker, kde.network_packet("kdeconnect.pair", {
            "pair": True, "timestamp": timestamp}))
        assert events[0][0] == "pairing" and events[0][1]["device_name"] == "Phone"
        assert len(events[0][1]["code"]) == 8 and peer.device_id not in backend.store.peers
        result = backend.confirm_pairing(True)
        assert result["state"] == "paired" and peer.device_id in backend.store.peers
        assert worker.outgoing.get_nowait()["body"] == {"pair": True}

        rejected = FakeConnection()
        rejected_worker = mock.Mock()
        backend.pairing = {"state": "requested", "direction": "incoming",
            "worker": rejected_worker, "identity": secure, "certificate": peer.certificate,
            "timestamp": 1786617000, "address": "127.0.0.1", "port": 1716,
            "local_confirmed": False, "remote_confirmed": True,
            "deadline": backend.clock() + 30}
        assert backend.confirm_pairing(False) == {"state": "rejected"}
        assert rejected_worker.send.call_args.args[0]["body"] == {"pair": False}


def test_confirmed_pair_true_requires_repair_once_without_echo():
    events = []
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root,
            callback=lambda event, value: events.append((event, value)))
        device_id = "3" * 32
        backend.store.peers[device_id] = {"paired": True}
        worker = mock.Mock(); worker.identity = {"deviceId": device_id}
        packet = kde.network_packet("kdeconnect.pair", {"pair": True})
        backend._pair_packet(worker, packet)
        backend._pair_packet(worker, packet)
        assert backend.store.peers[device_id]["paired"] is False
        assert len(events) == 1 and events[0][1]["reason"] == "repair_required"
        worker.send.assert_not_called()


def test_pairing_ttl_closes_connection_and_disconnect_reschedules():
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        worker = mock.Mock()
        backend.pairing = {"state": "requested", "worker": worker,
            "deadline": backend.clock() - 1}
        backend._expire_state(backend.clock())
        assert backend.pairing is None
        assert worker.send.call_args.args[0]["body"] == {"pair": False}
        connection = FakeConnection()
        backend._next_broadcast = 999999999
        worker = mock.Mock(); worker.connection = connection
        backend._connections["a" * 32] = {"worker": worker,
            "connection": connection, "identity": kde.validate_identity(identity()),
            "address": "127.0.0.1", "port": 1716}
        backend._worker_died("a" * 32, worker)
        assert backend._next_broadcast <= backend.clock() + kde.FAST_DISCOVERY_INTERVAL


def test_reconnect_broadcast_backoff_is_deterministic_and_bounded():
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, backoff=[5, 15, 30, 60])
        with mock.patch.object(backend, "_broadcast") as broadcast, \
             mock.patch.object(backend, "_reconnect_pinned"):
            for now in (100, 105, 120, 150, 210):
                backend._broadcast_due(now)
        assert broadcast.call_count == 5
        assert backend._next_broadcast == 270 and backend._backoff_index == 3


def test_candidate_cache_fast_discovery_and_expiry_use_fake_clock():
    now = [100.0]
    device_id = "4" * 32
    candidate = kde.DiscoveredDevice("127.0.0.1", 1716,
        kde.validate_identity(identity(device_id), True))
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, clock=lambda: now[0],
            backoff=[5, 15, 30, 60])
        backend._remember_device(candidate, reconnect=False)
        now[0] = 130.0
        with mock.patch.object(backend, "start"):
            status = backend.status(0)
        assert kde.CANDIDATE_TTL >= 300
        assert status["unpaired_candidate_id"] == device_id
        assert status["unpaired_candidate_age_seconds"] == 30
        assert not status["unpaired_candidate_reachable"] and status["fast_discovery"]
        backend._last_broadcast = float("-inf")
        with mock.patch.object(backend, "_broadcast"), \
             mock.patch.object(backend, "_reconnect_pinned"):
            backend._broadcast_due(now[0])
        assert backend._next_broadcast == 132.0
        now[0] = 400.0
        backend._expire_state(now[0])
        assert device_id not in backend._devices and not backend._fast_discovery(now[0])
        backend._last_broadcast = float("-inf")
        backend._backoff_index = 0
        with mock.patch.object(backend, "_broadcast"), \
             mock.patch.object(backend, "_reconnect_pinned"):
            backend._broadcast_due(now[0])
        assert backend._next_broadcast == 405.0


def test_android_link_stops_discovery_pairing_and_replacement_stays_bounded():
    now = [100.0]
    device_id = "a" * 32
    secure = kde.validate_identity(identity(device_id), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, clock=lambda: now[0], backoff=[5])
        backend._remember_device(kde.DiscoveredDevice("127.0.0.1", 1716, secure),
                                 reconnect=False)
        links = []
        with mock.patch.object(backend, "_broadcast") as broadcast, \
             mock.patch.object(backend, "_reconnect_pinned") as reconnect:
            backend._broadcast_due(now[0])
            assert broadcast.call_count == 1
            link_a = FakeConnection(); links.append(link_a)
            worker_a = backend._remember_connection(link_a, secure,
                backend.store.certificate, "127.0.0.1", 1716, start=False,
                direction="incoming")
            backend._pairing_pending = True
            assert not backend._fast_discovery(now[0])
            backend._pairing_pending = False
            now[0] += 2
            backend._broadcast_due(now[0])
            assert broadcast.call_count == 1 and reconnect.call_count == 1
            assert not backend._fast_discovery(now[0])

            link_b = FakeConnection(); links.append(link_b)
            worker_b = backend._remember_connection(link_b, secure,
                backend.store.certificate, "127.0.0.1", 1716, start=False,
                direction="incoming")
            assert worker_b is not worker_a and link_a.closed and not link_b.closed
            timestamp = int(time.time())
            backend._pair_packet(worker_b, kde.network_packet("kdeconnect.pair", {
                "pair": True, "timestamp": timestamp}))
            for _tick in range(20):
                now[0] += 2
                backend._broadcast_due(now[0])
            assert broadcast.call_count == 1 and reconnect.call_count == 1
            assert backend.pairing["worker"] is worker_b
            assert sum(not link.closed for link in links) == 1


def test_reject_and_timeout_keep_live_link_visible_without_discovery():
    now = [100.0]
    device_id = "b" * 32
    secure = kde.validate_identity(identity(device_id), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root, clock=lambda: now[0], backoff=[5])
        backend._remember_device(kde.DiscoveredDevice("127.0.0.1", 1716, secure),
                                 reconnect=False)
        worker = backend._remember_connection(FakeConnection(), secure,
            backend.store.certificate, "127.0.0.1", 1716, start=False,
            direction="incoming")
        backend.pairing = {"state": "requested", "worker": worker,
            "identity": secure, "deadline": now[0] - 1}
        backend._expire_state(now[0])
        assert backend.pairing is None and not backend._fast_discovery(now[0])
        with mock.patch.object(backend, "_broadcast") as broadcast, \
             mock.patch.object(backend, "_reconnect_pinned") as reconnect:
            backend._broadcast_due(now[0])
        assert not broadcast.called and not reconnect.called
        with mock.patch.object(backend, "start"):
            status = backend.status(0)
        assert status["unpaired_candidate_reachable"]
        assert status["connection_direction"] == "incoming"
        assert status["connection_generation"] == 1


def test_pairing_uses_exact_cached_endpoint_without_fresh_discovery():
    requested, other = "5" * 32, "6" * 32
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        candidate = kde.DiscoveredDevice("127.0.0.1", 1718,
            kde.validate_identity(identity(requested, 1718), True))
        backend._remember_device(candidate, reconnect=False)
        connection = FakeConnection()
        with mock.patch.object(backend, "start"), \
             mock.patch.object(backend, "discover") as discovery, \
             mock.patch.object(backend, "_tls_connection", return_value=(
                 connection, candidate.identity, backend.store.certificate)) as opened, \
             mock.patch.object(threading.Thread, "start"):
            result = backend.begin_pairing(requested)
        assert result["device_id"] == requested and not discovery.called
        assert opened.call_args.args[0].address == "127.0.0.1"
        assert opened.call_args.args[0].port == 1718
        assert opened.call_args.kwargs["allow_unpaired"] is True
        assert backend.confirm_pairing(False) == {"state": "rejected"}
        with pytest.raises(kde.ProtocolError):
            backend.begin_pairing(other)


def test_cached_candidate_reuses_active_worker_and_survives_worker_death():
    device_id = "2" * 32
    secure = kde.validate_identity(identity(device_id), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        backend._remember_device(kde.DiscoveredDevice("127.0.0.1", 1716, secure),
                                 reconnect=False)
        worker = mock.Mock(); worker.identity = secure
        worker.stopped.is_set.return_value = False
        worker.connection = FakeConnection()
        backend._connections[device_id] = {"connection": worker.connection,
            "identity": secure, "worker": worker, "certificate": backend.store.certificate,
            "address": "127.0.0.1", "port": 1716}
        with mock.patch.object(backend, "start"), \
             mock.patch.object(backend, "_tls_connection") as opened:
            result = backend.begin_pairing(device_id)
        assert result["device_id"] == device_id and not opened.called
        worker.send.assert_called_once()
        backend.pairing = None
        backend._worker_died(device_id, worker)
        assert device_id in backend._devices
        assert backend._next_broadcast <= backend.clock() + kde.FAST_DISCOVERY_INTERVAL


def test_stale_worker_finally_cannot_remove_replacement():
    device_id = "1" * 32
    secure = kde.validate_identity(identity(device_id), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        stale = mock.Mock(); stale.connection = FakeConnection()
        replacement = mock.Mock(); replacement.stopped.is_set.return_value = False
        backend._connections[device_id] = {"connection": object(), "identity": secure,
            "worker": replacement, "certificate": None, "address": None, "port": None}
        backend._worker_died(device_id, stale)
        assert backend._connections[device_id]["worker"] is replacement


def test_incoming_pair_prompt_is_deduplicated_and_pair_clears_fast_discovery():
    events = []
    with tempfile.TemporaryDirectory() as local_root, tempfile.TemporaryDirectory() as peer_root:
        backend = kde.KDEConnectSMSBackend(local_root,
            callback=lambda event, payload: events.append((event, payload)))
        peer = kde.IdentityStore(peer_root, "Phone")
        secure = kde.validate_identity(identity(peer.device_id))
        worker = mock.Mock(); worker.identity = secure
        backend._connections[peer.device_id] = {"connection": object(), "identity": secure,
            "worker": worker, "certificate": peer.certificate,
            "address": "127.0.0.1", "port": 1716}
        backend._remember_device(kde.DiscoveredDevice("127.0.0.1", 1716, secure),
                                 reconnect=False)
        timestamp = int(time.time())
        packet = kde.network_packet("kdeconnect.pair", {"pair": True, "timestamp": timestamp})
        backend._pair_packet(worker, packet)
        backend._pair_packet(worker, packet)
        assert [event for event, _payload in events].count("pairing") == 1
        assert backend.confirm_pairing(True)["state"] == "paired"
        assert not backend._devices and not backend._fast_discovery()


def test_peer_store_reads_old_schema_and_strictly_validates_new_endpoint():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as peer_root:
        peer = kde.IdentityStore(peer_root, "Phone")
        store = kde.IdentityStore(root, "Desktop")
        old = {peer.device_id: {"name": "Galaxy S24", "protocolVersion": 8,
            "certificate": peer.certificate.public_bytes(
                kde.serialization.Encoding.PEM).decode("ascii")}}
        kde._atomic_write(store.peers_path, json.dumps(old).encode() + b"\n", 0o600)
        migrated = kde.IdentityStore(root, "Desktop").peers[peer.device_id]
        assert "lastAddress" not in migrated and migrated["paired"] is False
        store = kde.IdentityStore(root, "Desktop")
        store.save_peer(peer.device_id, "Galaxy S24", peer.certificate,
                        "192.168.178.21", 1716)
        pinned = kde.IdentityStore(root, "Desktop").peers[peer.device_id]
        assert pinned["lastPort"] == 1716 and pinned["paired"] is False
        broken = dict(store.peers)
        broken[peer.device_id] = dict(broken[peer.device_id], lastAddress="8.8.8.8")
        kde._atomic_write(store.peers_path, json.dumps(broken).encode() + b"\n", 0o600)
        with pytest.raises(kde.ProtocolError):
            kde.IdentityStore(root, "Desktop")


def test_tls_pin_without_pairing_proof_is_reachable_but_not_available():
    device_id = "7" * 32
    secure = kde.validate_identity(identity(device_id, capabilities=[kde.SMS_TYPE]), True)
    connection = FakeConnection()
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        backend.store.peers[device_id] = {"name": "Galaxy S24", "protocolVersion": 8,
            "certificate": backend.store.certificate.public_bytes(
                kde.serialization.Encoding.PEM).decode("ascii"), "paired": False}
        with mock.patch.object(threading.Thread, "start"):
            worker = backend._remember_connection(connection, secure,
                backend.store.certificate, "127.0.0.1", 1716)
        status = backend.status(0)
        assert not status["available"] and status["device_count"] == 0
        assert status["transport_reachable"] and status["legacy_pinned_count"] == 1
        assert status["peer_name"] == "Phone" and worker.outgoing.empty()


def test_complete_pairing_reuses_existing_worker_and_sends_one_request():
    device_id = "6" * 32
    secure = kde.validate_identity(identity(device_id), True)
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        worker = mock.Mock(); worker.identity = secure; worker.stopped.is_set.return_value = False
        backend._connections[device_id] = {"connection": object(), "identity": secure,
            "worker": worker, "certificate": backend.store.certificate,
            "address": "127.0.0.1", "port": 1716}
        result = backend.complete_pairing(device_id)
        assert result["state"] == "requested" and len(result["code"]) == 8
        worker.send.assert_called_once()
        assert worker.send.call_args.args[0]["body"]["pair"] is True
        assert "timestamp" in worker.send.call_args.args[0]["body"]


def test_pinned_endpoint_reconnects_without_discovery_and_is_saved_only_after_auth():
    device_id = "9" * 32
    with tempfile.TemporaryDirectory() as root:
        backend = kde.KDEConnectSMSBackend(root)
        backend.store.peers[device_id] = {"name": "Galaxy S24", "protocolVersion": 8,
            "certificate": backend.store.certificate.public_bytes(
                kde.serialization.Encoding.PEM).decode("ascii"),
            "lastAddress": "192.168.178.21", "lastPort": 1716, "lastSeenMs": 1}
        captured = []
        with mock.patch.object(backend, "_connect_device", side_effect=captured.append):
            backend._reconnect_pinned()
        assert [(item.address, item.port) for item in captured] == [("192.168.178.21", 1716)]
        device = captured[0]
        with mock.patch.object(backend, "_tls_connection", side_effect=EOFError("Unexpected EOF")), \
             mock.patch.object(backend.store, "update_endpoint") as update:
            backend._connect_device(device)
            for handler in list(backend._handlers): handler.join(2)
        assert not update.called and backend._pairing_failures[device_id] == 1


def test_replacement_pairing_is_transactional_on_accept_reject_and_timeout():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as new_root:
        backend = kde.KDEConnectSMSBackend(root)
        old_id = "8" * 32
        new_peer = kde.IdentityStore(new_root, "Galaxy S24")
        backend.store.peers[old_id] = {"name": "Galaxy S24", "protocolVersion": 8,
            "certificate": backend.store.certificate.public_bytes(
                kde.serialization.Encoding.PEM).decode("ascii"), "paired": False}
        candidate = kde.DiscoveredDevice("127.0.0.1", 1716,
            kde.validate_identity(identity(new_peer.device_id), True))
        candidate.identity["deviceName"] = "Galaxy S24"
        connection = FakeConnection()
        backend._remember_device(candidate, reconnect=False)
        with mock.patch.object(backend, "start"), \
             mock.patch.object(backend, "_tls_connection",
                 return_value=(connection, candidate.identity, new_peer.certificate)), \
             mock.patch.object(threading.Thread, "start"):
            request = backend.begin_pairing(new_peer.device_id, replace_stored=True)
        assert request["state"] == "requested" and len(request["code"]) == 8
        assert old_id in backend.store.peers and new_peer.device_id not in backend.store.peers
        backend.confirm_pairing(False)
        assert old_id in backend.store.peers and new_peer.device_id not in backend.store.peers

        timeout = mock.Mock()
        backend.pairing = {"state": "requested", "worker": timeout,
            "replace_device_id": old_id, "deadline": backend.clock() - 1}
        backend._expire_state(backend.clock())
        assert old_id in backend.store.peers

        accepted = mock.Mock(); accepted.identity = candidate.identity
        backend.pairing = {"state": "requested", "direction": "outgoing",
            "worker": accepted, "identity": candidate.identity,
            "certificate": new_peer.certificate, "timestamp": int(time.time()),
            "address": candidate.address, "port": candidate.port,
            "local_confirmed": True, "remote_confirmed": False,
            "deadline": backend.clock() + 30}
        backend._pair_packet(accepted, kde.network_packet("kdeconnect.pair", {"pair": True}))
        result = {"device_id": new_peer.device_id}
        assert result["device_id"] == new_peer.device_id
        assert old_id not in backend.store.peers and new_peer.device_id in backend.store.peers
        reopened = kde.IdentityStore(root, "Desktop")
        assert old_id not in reopened.peers and new_peer.device_id in reopened.peers


def test_stale_inbound_pair_request_is_closed_without_callback_or_trust():
    events = []
    with tempfile.TemporaryDirectory() as local_root, tempfile.TemporaryDirectory() as peer_root:
        backend = kde.KDEConnectSMSBackend(local_root,
            callback=lambda event, payload: events.append((event, payload)))
        peer = kde.IdentityStore(peer_root, "Phone")
        connection = FakeConnection()
        secure = kde.validate_identity(identity(peer.device_id))
        connection.recv_packets = [kde.network_packet("kdeconnect.pair",
            {"pair": True, "timestamp": int(time.time()) - 31})]
        with mock.patch.object(backend, "_tls_connection",
                 return_value=(connection, secure, peer.certificate)), \
             mock.patch.object(kde, "read_packet",
                 side_effect=lambda stream: stream.recv_packets.pop(0)):
            backend._handle_incoming(connection,
                kde.DiscoveredDevice("127.0.0.1", 1716, secure))
            deadline = time.monotonic() + 1
            while not connection.closed and time.monotonic() < deadline:
                time.sleep(.01)
        assert connection.closed and not events and peer.device_id not in backend.store.peers


@pytest.mark.skipif(kde.SSL is None, reason="PyOpenSSL is not installed")
def test_outbound_tcp_uses_inverted_mutual_tls_and_secure_identity():
    listener = socket.socket()
    for port in range(kde.MIN_TCP_PORT, kde.MAX_TCP_PORT + 1):
        try:
            listener.bind(("127.0.0.1", port)); break
        except OSError:
            continue
    else:
        pytest.skip("no KDE Connect test port is free")
    listener.listen(1)
    errors = []
    with tempfile.TemporaryDirectory() as local_root, tempfile.TemporaryDirectory() as peer_root:
        backend = kde.KDEConnectSMSBackend(local_root, "Desktop")
        peer = kde.IdentityStore(peer_root, "Phone")
        backend.store.save_peer(peer.device_id, "Phone", peer.certificate)
        peer_identity = kde.validate_identity(identity(peer.device_id, port,
            [kde.SMS_TYPE]), require_tcp=True)
        device = kde.DiscoveredDevice("127.0.0.1", port, peer_identity)

        def phone():
            raw = None
            try:
                raw, _address = listener.accept()
                plaintext = kde.read_packet(raw)
                assert plaintext["body"]["targetDeviceId"] == peer.device_id
                context = kde.SSL.Context(kde.SSL.TLS_CLIENT_METHOD)
                context.set_min_proto_version(kde.SSL.TLS1_2_VERSION)
                context.set_verify(kde.SSL.VERIFY_NONE, lambda *_args: True)
                context.use_privatekey(kde.crypto.load_privatekey(kde.crypto.FILETYPE_PEM,
                    peer.key.private_bytes(kde.serialization.Encoding.PEM,
                        kde.serialization.PrivateFormat.PKCS8,
                        kde.serialization.NoEncryption())))
                context.use_certificate(kde.crypto.load_certificate(kde.crypto.FILETYPE_PEM,
                    peer.certificate.public_bytes(kde.serialization.Encoding.PEM)))
                connection = kde.SSL.Connection(context, raw)
                connection.set_connect_state()
                stream = kde._TLSStream(connection)
                stream.handshake()
                kde.validate_identity(kde.read_packet(stream))
                stream.sendall(kde.encode_packet(identity(peer.device_id, port,
                    [kde.SMS_TYPE])))
                stream.close()
            except Exception as error:
                errors.append(error)
                if raw is not None: raw.close()

        worker = threading.Thread(target=phone)
        worker.start()
        connection, secure, certificate = backend._tls_connection(device)
        assert secure["deviceId"] == peer.device_id
        assert certificate.fingerprint(kde.hashes.SHA256()) == peer.certificate.fingerprint(
            kde.hashes.SHA256())
        connection.close(); worker.join(5)
        assert not worker.is_alive() and not errors
    listener.close()


@pytest.mark.skipif(kde.SSL is None, reason="PyOpenSSL is not installed")
def test_accepted_tcp_uses_tls_client_role_and_secure_identity():
    left, right = socket.socketpair()
    errors = []
    with tempfile.TemporaryDirectory() as local_root, tempfile.TemporaryDirectory() as peer_root:
        backend = kde.KDEConnectSMSBackend(local_root, "Desktop")
        peer = kde.IdentityStore(peer_root, "Phone")
        device_id = peer.device_id
        peer_identity = kde.validate_identity(identity(device_id, capabilities=[kde.SMS_TYPE]), True)
        device = kde.DiscoveredDevice("127.0.0.1", 1716, peer_identity)

        def phone():
            try:
                context = kde.SSL.Context(kde.SSL.TLS_SERVER_METHOD)
                context.set_min_proto_version(kde.SSL.TLS1_2_VERSION)
                context.set_verify(kde.SSL.VERIFY_NONE, lambda *_args: True)
                context.use_privatekey(kde.crypto.load_privatekey(kde.crypto.FILETYPE_PEM,
                    peer.key.private_bytes(kde.serialization.Encoding.PEM,
                        kde.serialization.PrivateFormat.PKCS8,
                        kde.serialization.NoEncryption())))
                context.use_certificate(kde.crypto.load_certificate(kde.crypto.FILETYPE_PEM,
                    peer.certificate.public_bytes(kde.serialization.Encoding.PEM)))
                connection = kde.SSL.Connection(context, right)
                connection.set_accept_state()
                stream = kde._TLSStream(connection)
                stream.handshake()
                stream.sendall(kde.encode_packet(identity(device_id, capabilities=[kde.SMS_TYPE])))
                secure = kde.validate_identity(kde.read_packet(stream))
                assert secure["deviceId"] == backend.store.device_id
                stream.close()
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=phone)
        worker.start()
        connection, secure, certificate = backend._tls_connection(
            device, allow_unpaired=True, accepted=left)
        assert secure["deviceId"] == device_id
        assert certificate.fingerprint(kde.hashes.SHA256()) == peer.certificate.fingerprint(
            kde.hashes.SHA256())
        connection.close(); worker.join(5)
        assert not worker.is_alive() and not errors
