#!/usr/bin/env python3
"""Real encrypted Notes contact reads with synthetic established-session keys."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import hashlib
import socket
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
from modul_laden import quellmodul_laden

PHONE = os.environ.get("PHONE_TEST_DEVICE_ID", "22222222-2222-4222-8222-222222222222")


def main():
    app = quellmodul_laden("contact_read_host_app", Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer")
    with tempfile.TemporaryDirectory(prefix="contact-read-host-") as directory:
        title_uid = os.environ.get("PHONE_TEST_GROUP_TITLE_UID")
        service = phone.PhoneService(str(Path(directory) / "phone"), "Synthetic desktop")
        service.store.identity["device_id"] = "11111111-1111-4111-8111-111111111111"
        service.enabled = True
        peer = {"device_id": PHONE, "display_name": "Synthetic phone", "static_public": phone.b64(b"p" * 32),
                "state": "paired", "grants": phone.desktop_grants(), "local_grants": phone.desktop_grants(),
                "capabilities": phone.desktop_capabilities(), "last_contact_ms": 0,
                "bluetooth": {"enabled": False, "address": ""},
                "personal_sync": {"own_device": True, "remote_own_device": False, "auto_wifi": False, "last_report": {}}}
        service.store.peers.append(peer); service.store.save_peers()
        service.store.initialize_shared_settings(PHONE, peer["static_public"],
            dict(phone.shared_sync_contract.DEFAULTS, content_mode="phone_import"))
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as workers:
            listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(25)
            print(listener.getsockname()[1], flush=True)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                channel = phone.SecureChannel(connection, bytes([7]) * 32,
                    bytes([13]) * 32, bytes([14]) * 4, bytes([11]) * 32, bytes([12]) * 4)
                service.connections[PHONE] = channel; service.connection_transports[PHONE] = "wifi"
                assert not service.contacts_available(PHONE), "stored capabilities bypassed the fresh-control gate"
                service._ensure_desktop_updates(PHONE)
                for message in service.store.pending(PHONE):
                    service._send_message(channel, PHONE, message)

                def read_contacts():
                    if title_uid:
                        return write_title()
                    if os.environ.get("PHONE_TEST_VALUES_UID"):
                        return write_values()
                    if os.environ.get("PHONE_TEST_GROUP_UID"):
                        return write_groups()
                    index = service.read_contacts(PHONE)
                    assert len(index["contacts"]) == 130 and index["device_id"] == "notes:" + PHONE
                    for card_index in range(6):
                        uid = "fixture-%03d" % card_index
                        cards = service.read_contacts(PHONE, [uid])
                        assert len(cards["contacts"]) == 1 and cards["contacts"][0]["uid"] == uid
                        contact = app.vcf_lesen(cards["contacts"][0]["vcard"])["kontakte"][0]
                        assert contact["vorname"] == "Fixture" and contact["foto"].startswith("data:image/png;base64,")
                        assert len(contact["sozialeMedien"]) == 1
                        app.kde_kontakte_projizieren(cards, "notes:" + PHONE, [uid], "notes")
                        assert cards["contacts"][0]["bindung"].startswith("urn:magnolie:import:notes:")
                    assert not service.store.status(PHONE), "contact reply leaked into ordinary status history"
                    with service.lock:
                        peer["local_grants"]["grants"]["device_status"] = False
                        service.store.save_peers()
                    assert not service.contacts_available(PHONE)
                    try:
                        service.read_contacts(PHONE)
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("revoked contact read reached the network")

                def write_title():
                    from magnolie_phone_contacts import group_title_matches_saved_intent
                    fingerprint = hashlib.sha256(b"p" * 32).hexdigest()
                    def request(action, **extra):
                        return dict(version=20, request_id=str(uuid.uuid4()), action=action, uid=title_uid,
                            old_title="Coworkers", new_title="Arbeit", **extra)
                    prepared = service.contact_group_title(PHONE, fingerprint, request("prepare"))
                    apply = request("apply", token=prepared["token"])
                    try:
                        service.contact_group_title(PHONE, fingerprint, apply)
                    except TimeoutError:
                        pass  # The native provider saved; the result is deliberately lost below.
                    else:
                        raise AssertionError("Lost native title result was incorrectly confirmed")
                    try:
                        service.contact_group_title(PHONE, fingerprint, apply)
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("Consumed native title ticket was reused")
                    observed = service.contact_group_title(PHONE, fingerprint, request("inspect", group_id=prepared["group_id"], account=prepared["account"]))
                    assert group_title_matches_saved_intent(observed, prepared)
                    assert not service.contact_group_preparations and not service.store.status(PHONE)

                def write_values():
                    uid = os.environ["PHONE_TEST_VALUES_UID"]
                    fingerprint = hashlib.sha256(b"p" * 32).hexdigest()
                    def request(action, **extra):
                        return dict(version=19, request_id=str(uuid.uuid4()), action=action, uid=uid, **extra)
                    prepared = service.contact_values(PHONE, fingerprint, request("prepare", field_names=["telefone", "emailEintraege"]))
                    assert prepared["fields"]["telefone"][0]["wert"] == "111"
                    assert prepared["fields"]["emailEintraege"][0]["wert"] == "old@example.invalid"
                    fields = {"telefone": [{"art": "mobil", "wert": "222"}], "emailEintraege": [{"art": "arbeit", "wert": "new@example.invalid"}]}
                    apply = request("apply", token=prepared["token"], fields=fields)
                    saved = service.contact_values(PHONE, fingerprint, apply)
                    assert saved["fields"] == fields and saved["account"] == prepared["account"]
                    try: service.contact_values(PHONE, fingerprint, apply)
                    except PermissionError: pass
                    else: raise AssertionError("Consumed field preparation was reused")
                    fresh = service.contact_values(PHONE, fingerprint, request("prepare", field_names=["emailEintraege"]))
                    assert fresh["fields"]["emailEintraege"][0]["wert"] == "new@example.invalid"
                    cleared = service.contact_values(PHONE, fingerprint, request("apply", token=fresh["token"], fields={"emailEintraege": []}))
                    assert cleared["fields"] == {"emailEintraege": []}
                    assert not service.contact_group_preparations and not service.store.status(PHONE)

                def write_groups():
                    uid = os.environ["PHONE_TEST_GROUP_UID"]
                    fingerprint = hashlib.sha256(b"p" * 32).hexdigest()
                    from magnolie_phone_contacts import GROUP_WRITE_VERSION
                    assert service.contact_groups_available(PHONE)
                    if os.environ.get("PHONE_TEST_GROUP_PROBE"):
                        from magnolie_phone_contacts import GROUP_PROBE_VERSION
                        body = dict(version=GROUP_PROBE_VERSION, request_id=str(uuid.uuid4()), action="diagnostics", uid=uid)
                        if os.environ.get("PHONE_TEST_PROBE_DENIED"):
                            try:
                                service.contact_groups(PHONE, fingerprint, body)
                            except RuntimeError as error:
                                assert str(error) == "contact_groups_not_granted"
                            else:
                                raise AssertionError("Debug probe bypassed the phone's local Wi-Fi debug opt-in")
                        else:
                            probe = service.contact_groups(PHONE, fingerprint, body)
                            assert probe["state"] == "available" and probe["stage"] == "complete"
                            assert probe["raw_count"] == 2 and probe["account_count"] == 2 and probe["version_count"] == 2
                            assert "account" not in probe and "groups" not in probe and "token" not in probe
                        assert not service.contact_group_preparations and not service.store.status(PHONE)
                        return
                    def request(action, **extra):
                        return dict(version=GROUP_WRITE_VERSION, request_id=str(uuid.uuid4()), action=action, uid=uid, **extra)
                    prepared = service.contact_groups(PHONE, fingerprint, request("prepare"))
                    assert prepared["groups"] == ["Coworkers"]
                    assert prepared["account"] == {"name": "fixture@example.test", "type": "synthetic-provider", "data_set": ""}
                    wanted = ["Own group", "Work"]
                    saved = service.contact_groups(PHONE, fingerprint, request("apply", token=prepared["token"], groups=wanted))
                    assert saved["state"] == "saved" and saved["groups"] == wanted
                    try:
                        service.contact_groups(PHONE, fingerprint, request("apply", token=prepared["token"], groups=wanted))
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("Consumed write preparation was reused")
                    fresh = service.contact_groups(PHONE, fingerprint, request("prepare"))
                    assert fresh["groups"] == wanted
                    cleared = service.contact_groups(PHONE, fingerprint, request("apply", token=fresh["token"], groups=[]))
                    assert cleared["state"] == "saved" and cleared["groups"] == []
                    assert not service.contact_group_preparations and not service.store.status(PHONE)

                operation = None
                discard_title_save = bool(title_uid)
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        packet = channel.receive()
                        if discard_title_save and packet.get("kind") == "device_status.report" and packet.get("body", {}).get("version") == 20 and packet["body"].get("action") == "apply":
                            discard_title_save = False
                            channel.send(dict(type="ack", message_id=packet["message_id"], status="accepted", error="none"))
                        else:
                            service._payload(peer, channel, packet)
                    except socket.timeout:
                        pass
                    if operation is None and (service.contact_group_titles_available(PHONE) if title_uid else service.contact_values_available(PHONE) if os.environ.get("PHONE_TEST_VALUES_UID") else service.contact_groups_available(PHONE) if os.environ.get("PHONE_TEST_GROUP_UID") else service.contacts_available(PHONE)):
                        operation = workers.submit(read_contacts)
                    for message in service.store.pending(PHONE):
                        service._send_message(channel, PHONE, message)
                    if operation is not None and operation.done():
                        operation.result()
                        channel.send({"type": "close", "reason": "normal"})
                        # Notes sends a resource report followed by its transport
                        # ACK. Closing with that ACK still unread resets TCP and
                        # can discard the already-sent close frame. Half-close
                        # and drain until Notes closes its side instead.
                        connection.shutdown(socket.SHUT_WR)
                        connection.settimeout(5)
                        drained = 0
                        while True:
                            chunk = connection.recv(4096)
                            if not chunk: break
                            drained += len(chunk)
                            if drained > 65536: raise RuntimeError("bounded close drain exceeded")
                        print("Python Notes live native title identity/lost-result inspection passed." if title_uid else "Python Notes live native field write/readback passed." if os.environ.get("PHONE_TEST_VALUES_UID") else "Python Notes live native group write/readback passed." if os.environ.get("PHONE_TEST_GROUP_UID") else
                              "Python Notes contact paging, photo, messenger preview, source binding and revocation passed.", flush=True)
                        return
                raise TimeoutError("contact read fixture did not finish")


if __name__ == "__main__":
    main()
