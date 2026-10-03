#!/usr/bin/env python3
"""Real encrypted Notes contact reads with synthetic established-session keys."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_telefon as phone
from modul_laden import quellmodul_laden

PHONE = "22222222-2222-4222-8222-222222222222"


def main():
    app = quellmodul_laden("contact_read_host_app", Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer")
    with tempfile.TemporaryDirectory(prefix="contact-read-host-") as directory:
        service = phone.PhoneService(str(Path(directory) / "phone"), "Synthetic desktop")
        service.enabled = True
        peer = {"device_id": PHONE, "display_name": "Synthetic phone", "static_public": phone.b64(b"p" * 32),
                "state": "paired", "grants": phone.desktop_grants(), "local_grants": phone.desktop_grants(),
                "capabilities": phone.desktop_capabilities(), "last_contact_ms": 0,
                "bluetooth": {"enabled": False, "address": ""},
                "personal_sync": {"own_device": True, "remote_own_device": False, "auto_wifi": False, "last_report": {}}}
        service.store.peers.append(peer); service.store.save_peers()
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
                    index = service.read_contacts(PHONE)
                    assert len(index["contacts"]) == 130 and index["device_id"] == "notes:" + PHONE
                    cards = service.read_contacts(PHONE, ["fixture-000"])
                    contact = app.vcf_lesen(cards["contacts"][0]["vcard"])["kontakte"][0]
                    assert contact["vorname"] == "Fixture" and contact["foto"].startswith("data:image/png;base64,")
                    assert len(contact["sozialeMedien"]) == 1
                    app.kde_kontakte_projizieren(cards, "notes:" + PHONE, ["fixture-000"], "notes")
                    assert cards["contacts"][0]["bindung"].startswith("urn:magnolie:import:notes:")
                    assert not service.store.status(PHONE), "contact reply leaked into ordinary status history"
                    with service.lock:
                        peer["personal_sync"]["own_device"] = False
                        service.store.save_peers()
                    assert not service.contacts_available(PHONE)
                    try:
                        service.read_contacts(PHONE)
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("revoked contact read reached the network")

                operation = None
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        service._payload(peer, channel, channel.receive())
                    except socket.timeout:
                        pass
                    if operation is None and service.contacts_available(PHONE):
                        operation = workers.submit(read_contacts)
                    for message in service.store.pending(PHONE):
                        service._send_message(channel, PHONE, message)
                    if operation is not None and operation.done():
                        operation.result()
                        channel.send({"type": "close", "reason": "normal"})
                        print("Python Notes contact paging, photo, messenger preview, source binding and revocation passed.", flush=True)
                        return
                raise TimeoutError("contact read fixture did not finish")


if __name__ == "__main__":
    main()
