"""Real TCP negative tests of the setup-bound existing telephone handshake."""
import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_telefon as phone


@pytest.mark.parametrize("attack", ["wrong-target", "wrong-source", "expired", "cancelled", "replayed-token"])
def test_setup_scope_rejects_before_prompt_or_persistence(tmp_path, attack):
    vectors = json.loads((ROOT / "pruefungen/telefon-protokoll-vektoren.json").read_text())
    init = dict(vectors["pairing"]["pair_init"])
    events = []
    service = phone.PhoneService(str(tmp_path / "phone"), "Fixture", callback=lambda *value: events.append(value))
    with mock.patch.object(phone, "PORT", 0), mock.patch.object(service, "_publish"), mock.patch.object(service, "_unpublish"):
        service.enabled = True
        assert service.start()
        target = init["device_id"]
        address = "192.168.1.99" if attack == "wrong-source" else "127.0.0.1"
        offer = service.open_setup_pairing(target, address)
        init["pairing_token"] = offer["token"]
        try:
            if attack == "wrong-target":
                init["device_id"] = str(uuid.uuid4())
            elif attack == "expired":
                service.pairing_until = time.monotonic() - 1
            elif attack in ("cancelled", "replayed-token"):
                service.end_setup_pairing(offer["token"])
                if attack == "replayed-token":
                    offer = service.open_setup_pairing(target, address)
            with socket.create_connection(("127.0.0.1", service.server.getsockname()[1]), timeout=2) as client:
                phone.send_frame(client, init)
                assert client.recv(1) == b""
            assert not any(event[0] == "pairing_code" for event in events)
            assert service.store.peers == []
            assert not service.store.settings()["enabled"]
        finally:
            service.end_setup_pairing(offer["token"])
            service.stop()


def test_setup_never_replaces_existing_peer(tmp_path):
    service = phone.PhoneService(str(tmp_path), "Fixture")
    peer = {"device_id": str(uuid.uuid4()), "state": "paired", "static_public": phone.b64(os.urandom(32))}
    service.store.peers = [peer]
    with pytest.raises(ValueError):
        service.open_setup_pairing(str(uuid.uuid4()), "192.168.1.2")
    assert service.store.peers == [peer]
