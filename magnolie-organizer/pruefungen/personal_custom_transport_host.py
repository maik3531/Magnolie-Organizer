#!/usr/bin/env python3
"""Owned loopback fixture using the production queue and secure channel."""
import json
from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_telefon as phone

consent = json.loads((ROOT.parent / "contracts/personal-custom-consent-v4-vectors.json").read_text())
vectors = json.loads((ROOT.parent / "contracts/personal-custom-v4-vectors.json").read_text())
with tempfile.TemporaryDirectory(prefix="personal-custom-host-") as temp:
    service = phone.PhoneService(temp, "Synthetic", callback=lambda *_: None)
    peer_id = consent["other_source_id"]
    peer = dict(device_id=peer_id, display_name="Synthetic phone", static_public=phone.b64(b"p" * 32),
        state="paired", grants=phone.desktop_grants(), local_grants=phone.desktop_grants(),
        capabilities=phone.desktop_capabilities(), last_contact_ms=0, bluetooth=dict(enabled=False, address=""),
        personal_sync=dict(own_device=True, remote_own_device=True, auto_wifi=False, last_report={}),
        custom_sync=dict(local=consent["remote"], remote=consent["local"]))
    service.store.peers = [peer]; service.store.save_peers()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(20)
        print(listener.getsockname()[1], flush=True)
        sock, _ = listener.accept()
        with sock:
            sock.settimeout(20)
            channel = phone.SecureChannel(sock, bytes([7]) * 32, bytes([13]) * 32,
                bytes([14]) * 4, bytes([11]) * 32, bytes([12]) * 4)
            service.connections[peer_id] = channel; service.connection_transports[peer_id] = "wifi"
            for index, body in enumerate([vectors["batch"], vectors["batch"], vectors["deletion"], dict(vectors["batch"], revision=3)]):
                message_id = service.send_custom_sync(peer_id, "personal_sync.custom_batch", body)
                ack = channel.receive()
                assert ack["message_id"] == message_id
                assert ack["status"] == ("rejected" if index == 3 else "accepted")
                service._payload(peer, channel, ack)
                assert not any(item["message_id"] == message_id for item in service.store.pending(peer_id))
            settings = channel.receive(); service._payload(peer, channel, settings)
            assert not peer["custom_sync"]["remote"]["enabled"]
            assert not service._custom_allowed(peer_id, "personal_sync.custom_batch", vectors["batch"], True)
