"""Issue #164: confirmed renewal of one known phone, without deleting content."""
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import time
from unittest import mock

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_telefon as phone
from test_telefon import _complete_peer


def materials():
    vectors = json.loads(Path(__file__).with_name('telefon-protokoll-vektoren.json').read_text())['pairing']
    return vectors, dict(vectors['pair_init'])


@pytest.mark.parametrize('accepted', [True, False])
def test_known_phone_renewal_requires_new_confirmation_and_keeps_existing_content(tmp_path, accepted):
    vectors, init = materials()
    events = []
    attempts = []; shown = threading.Event()
    service = phone.PhoneService(str(tmp_path / 'phone'), 'Fixture')
    previous = _complete_peer(init['device_id'], public=phone.unb64(init['static_public'], 32))
    service.store.peers = [previous]; service.store.save_peers()
    shared_key = 'shared_settings:' + init['device_id']
    with sqlite3.connect(service.store.database_path) as db:
        db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)', (shared_key, b'preserved shared preferences'))
    service.pairing_token = phone.unb64(init['pairing_token'], 16)
    service.pairing_until = time.monotonic() + 60
    content = tmp_path / 'organizer-content.json'; content.write_bytes(b'{"notes":"preserved"}')
    before = hashlib.sha256(content.read_bytes()).hexdigest()
    def callback(event, payload):
        events.append(event)
        if event == 'pairing_code':
            attempts.append(payload['attempt_id']); shown.set()
    service.callback = callback
    server, client = socket.socketpair()
    client.settimeout(5)
    failures = []
    def run():
        try: service._pair(server, init)
        except Exception as error: failures.append(error)
        finally: server.close()
    thread = threading.Thread(target=run); thread.start()
    try:
        response = phone.receive_frame(client, phone.PAIR_FRAME_MAX)
        assert shown.wait(5)
        if not accepted:
            service.confirm_pairing(attempts[0], False)
            thread.join(5)
            assert not thread.is_alive()
            assert all(isinstance(error, (EOFError, OSError, ValueError)) for error in failures), failures
            assert service.store.peer(init['device_id']) is previous
            assert 'paired' not in events and not service.pairings
            assert hashlib.sha256(content.read_bytes()).hexdigest() == before
            with sqlite3.connect(service.store.database_path) as db:
                assert db.execute('SELECT value FROM meta WHERE key=?', (shared_key,)).fetchone()[0] == b'preserved shared preferences'
            return
        private = X25519PrivateKey.from_private_bytes(phone.unb64(vectors['phone_static_private'], 32))
        ephemeral = X25519PrivateKey.from_private_bytes(phone.unb64(vectors['phone_ephemeral_private'], 32))
        transcript = hashlib.sha256(phone.canonical(init) + phone.canonical(response)).digest()
        shared = private.exchange(X25519PublicKey.from_public_bytes(phone.unb64(response['static_public'], 32)))
        transient = ephemeral.exchange(X25519PublicKey.from_public_bytes(phone.unb64(response['ephemeral_public'], 32)))
        key = phone.hkdf(transient + shared, hashlib.sha256(b'magnolie-phone-pair-v1/salt\0' + transcript).digest(),
            b'magnolie-phone-pair-v1/key\0' + transcript, 32)
        phone.send_frame(client, {'p': phone.PROTOCOL, 'type': 'pair_confirm', 'side': 'phone',
            'transcript': phone.b64(transcript), 'proof': phone.b64(phone.proof(key, b'magnolie-phone-pair-v1/confirm\0', 'phone', transcript))})
        service.confirm_pairing(attempts[0], True)
        confirmation = phone.receive_frame(client, phone.PAIR_FRAME_MAX)
        if accepted:
            assert confirmation['type'] == 'pair_confirm'
            phone.send_frame(client, {'p': phone.PROTOCOL, 'type': 'pair_finish', 'side': 'phone',
                'transcript': phone.b64(transcript), 'proof': phone.b64(phone.proof(key, b'magnolie-phone-pair-v1/finish\0', 'phone', transcript))})
            assert phone.receive_frame(client, phone.PAIR_FRAME_MAX)['type'] == 'pair_finish'
        else:
            assert confirmation['type'] == 'pair_abort'
        thread.join(5); assert not thread.is_alive() and not failures
        assert len(service.store.peers) == 1
        current = service.store.peer(init['device_id'])
        assert current['state'] == 'paired'
        assert current['static_public'] == previous['static_public']
        if accepted:
            assert current is not previous and 'paired' in events
            assert not any(current['grants']['grants'].values())
        else:
            assert current is previous and 'paired' not in events
        assert hashlib.sha256(content.read_bytes()).hexdigest() == before
        with sqlite3.connect(service.store.database_path) as db:
            assert db.execute('SELECT value FROM meta WHERE key=?', (shared_key,)).fetchone()[0] == b'preserved shared preferences'
    finally:
        client.close(); thread.join(5)


@pytest.mark.parametrize('kind', ['different_id', 'different_key', 'multiple_peers'])
def test_renewal_does_not_replace_another_identity_or_key_before_confirmation(tmp_path, kind):
    _, init = materials()
    service = phone.PhoneService(str(tmp_path), 'Fixture')
    previous = _complete_peer(init['device_id'], public=phone.unb64(init['static_public'], 32))
    service.store.peers = [previous]
    if kind == 'different_id': service.store.peers = [_complete_peer()]
    elif kind == 'different_key': previous['static_public'] = phone.b64(bytes(range(32)))
    else: service.store.peers.append(_complete_peer())
    service.pairing_token = phone.unb64(init['pairing_token'], 16); service.pairing_until = time.monotonic() + 60
    before = list(service.store.peers)
    with pytest.raises(ValueError, match='binding already exists'):
        service._pair(mock.Mock(), init)
    assert service.store.peers == before and not service.pairings
