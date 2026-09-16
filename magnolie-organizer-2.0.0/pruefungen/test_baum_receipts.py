"""Public receipt vectors, durable acceptance and private loopback delivery."""
import copy
import json
from pathlib import Path
import socket
import urllib.error

import pytest
from test_background_reliability import app as m, private


def pair():
    left = m.baum_schluessel_erzeugen('Linux fixture')
    right = m.baum_schluessel_erzeugen('Peer fixture')
    for own, remote in ((left, right), (right, left)):
        own['an'] = True
        peer = m.baum_partner_aufnehmen(own, remote['name'], remote['kennung'], remote['oeffentlich'], '127.0.0.1')
        peer['bestaetigt'] = True
    return left, right


def test_public_vector_and_all_rejected_mutations(private):
    source = Path(__file__).resolve().parents[2] / 'contracts' / 'baum-1-receipt-v1-vectors.json'
    if not source.is_file():
        source = Path(__file__).resolve().parents[1] / 'contracts' / source.name
    vector = json.loads(source.read_text())
    key = bytes.fromhex(vector['partnerKeyHex'])
    envelope, receipt = vector['envelope'], vector['receipt']
    assert m._baum_kanonisch(envelope).decode() == vector['canonicalEnvelope']
    assert m.baum_receipt(key, 'alpha', 'beta', envelope) == receipt
    assert m.baum_receipt_pruefen(key, 'alpha', 'beta', envelope, receipt)
    assert not m.baum_receipt_pruefen(bytes(32), 'alpha', 'beta', envelope, receipt)
    assert not m.baum_receipt_pruefen(key, 'beta', 'alpha', envelope, receipt)
    for changed in (dict(envelope, zaehler=2), dict(envelope, daten=envelope['daten'] + 'A')):
        assert not m.baum_receipt_pruefen(key, 'alpha', 'beta', changed, receipt)
    for changed in (dict(receipt, extra=True), {k:v for k,v in receipt.items() if k != 'mac'},
                    {'ok': True}, True, dict(receipt, counter=True), dict(receipt, version=True)):
        assert not m.baum_receipt_pruefen(key, 'alpha', 'beta', envelope, changed)


def receiver(state, root, fail_state=False):
    path, inbox = root / 'state.json', root / 'inbox.json'
    def save(value):
        if fail_state: raise OSError('fixture state write interrupted')
        m.atomar_text_schreiben(str(path), json.dumps(value))
    backend = m.BaumDienst(lambda: state, save,
        bei_nachricht=lambda peer, body: m.baum_eingang_ablegen(peer, body, str(inbox)), port=0)
    return backend, path, inbox


def test_durable_receipt_restart_replay_and_inbox_before_state_recovery(private):
    left, right = pair()
    initial = copy.deepcopy(right)
    envelope = m.umschlag_bauen(left['geheim'], left['partner'][0], left['kennung'], {'art': 'notiz', 'text': 'fixture'}, 1)
    failed, state_path, inbox = receiver(right, private, True)
    assert failed.behandeln('/magnolie/v1/nachricht', envelope, '127.0.0.1')[0] == 500
    assert len(m.baum_eingang_lesen(str(inbox))) == 1
    assert m.baum_eingang_lesen(str(inbox))[0]['directEnvelopeHash']
    restarted, state_path, inbox = receiver(initial, private)
    status, receipt = restarted.behandeln('/magnolie/v1/nachricht', envelope, '127.0.0.1')
    assert status == 200 and state_path.exists()
    assert len(m.baum_eingang_lesen(str(inbox))) == 1
    again, _, _ = receiver(json.loads(state_path.read_text()), private)
    assert again.behandeln('/magnolie/v1/nachricht', envelope, '127.0.0.1') == (200, receipt)
    changed = m.umschlag_bauen(left['geheim'], left['partner'][0], left['kennung'], {'art': 'notiz', 'text': 'other'}, 1)
    assert again.behandeln('/magnolie/v1/nachricht', changed, '127.0.0.1')[0] == 403
    assert len(m.baum_eingang_lesen(str(inbox))) == 1


@pytest.mark.parametrize('failure', ['bare', 'timeout', 'reset', 'http', 'cancel', 'refused', 'dns'])
def test_sender_persists_uncertainty_before_bytes_and_never_retries_ambiguous(private, failure):
    left, right = pair()
    post = []
    item = m.baum_einreihen(post, right['kennung'], 'notiz', {'text': 'fixture'})
    path = private / 'outbox.json'
    writes, calls = [], []
    def save():
        writes.append(copy.deepcopy(post))
        return m.baum_post_schreiben(post, str(path))
    def send(url, envelope):
        stored = m.baum_post_lesen(str(path))[0]
        assert stored['receiptProtocol'] == 1 and stored['receiptAttempted'] and stored['unsicher']
        assert stored['briefUmschlag'] == envelope
        calls.append(envelope)
        if failure == 'bare': return {'ok': True}
        if failure == 'timeout': raise TimeoutError()
        if failure == 'reset': raise ConnectionResetError()
        if failure == 'http': raise urllib.error.HTTPError(url, 503, 'fixture', {}, None)
        if failure == 'cancel': raise KeyboardInterrupt()
        if failure == 'refused': raise ConnectionRefusedError()
        raise socket.gaierror()
    class Mailbox:
        def receipt_exists(self, *args): return False
        def ensure(self, *args): pass
        def upload(self, *args):
            assert failure in ('refused', 'dns')
    if failure == 'cancel':
        with pytest.raises(KeyboardInterrupt):
            m.baum_post_zustellen(left, post, sender=send, sichern=save, mailbox=Mailbox())
    else:
        assert m.baum_post_zustellen(left, post, sender=send, sichern=save, mailbox=Mailbox())['zugestellt'] == 0
    assert post == [item] and len(calls) == 1
    stored = m.baum_post_lesen(str(path))[0]
    assert stored['unsicher'] == (failure not in ('refused', 'dns'))
    if stored['unsicher']:
        reopened = [stored]
        report = m.baum_post_zustellen(left, reopened, sender=lambda *a: pytest.fail('ambiguous automatic resend'), sichern=lambda: True)
        assert report['versucht'] == 0 and len(reopened) == 1


def test_old_reserved_envelope_never_sent_or_upgraded(private):
    left, right = pair()
    item = {'an': right['kennung'], 'briefUmschlag': {'fixture': 'old'}, 'briefZaehler': 1}
    left['partner'][0]['protokoll'] = 'baum-fs1'
    post = [item]
    report = m.baum_post_zustellen(left, post, sender=lambda *a: pytest.fail('old envelope resent'), sichern=lambda: True)
    assert report['versucht'] == 0 and item['unsicher'] and post == [item]


def test_private_linux_pair_http_receipt_only_removes_matching_outbox(private, monkeypatch):
    left, right = pair()
    backend, _, inbox = receiver(right, private)
    original = socket.socket.bind
    def bind(sock, address):
        if sock.family == socket.AF_INET and address[1] == 0:
            return original(sock, ('127.0.0.1', 0))
        raise OSError('fixture only supports private ephemeral IPv4')
    monkeypatch.setattr(socket.socket, 'bind', bind)
    monkeypatch.setattr(backend, '_rufdienst_starten', lambda: None)
    monkeypatch.setattr(m.BaumBluetoothDienst, 'starten', lambda self: False)
    monkeypatch.setattr(m, 'baum_mdns_veroeffentlichen', lambda *a: None)
    try:
        assert backend.starten()
        left['partner'][0]['port'] = backend.port
        post = []
        m.baum_einreihen(post, right['kennung'], 'notiz', {'text': 'loopback fixture'})
        path = private / 'outbox.json'
        report = m.baum_post_zustellen(left, post, sichern=lambda: m.baum_post_schreiben(post, str(path)))
        assert report['zugestellt'] == 1 and post == []
        assert len(m.baum_eingang_lesen(str(inbox))) == 1
    finally:
        backend.anhalten()


def test_failed_outbox_write_prevents_any_transmission(private):
    left, right = pair()
    post = []
    m.baum_einreihen(post, right['kennung'], 'notiz', {'text': 'fixture'})
    with pytest.raises(RuntimeError):
        m.baum_post_zustellen(left, post, sichern=lambda: False,
            sender=lambda *a: pytest.fail('sent before durable reservation'))


def test_receipt_cache_is_bounded_and_unknown_stale_counter_rejected(private):
    left, right = pair()
    backend, _, _ = receiver(right, private)
    first = None
    for counter in range(1, 66):
        envelope = m.umschlag_bauen(left['geheim'], left['partner'][0], left['kennung'], {'art': 'notiz', 'text': 'fixture'}, counter)
        if first is None: first = envelope
        assert backend.behandeln('/magnolie/v1/nachricht', envelope, '127.0.0.1', True)[0] == 200
    assert len(right['partner'][0]['directReceipts']) == 64
    assert backend.behandeln('/magnolie/v1/nachricht', first, '127.0.0.1', True)[0] == 403
    for _ in range(4):
        other = m.baum_schluessel_erzeugen('fixture')
        peer = m.baum_partner_aufnehmen(right, 'fixture', other['kennung'], other['oeffentlich'])
        peer['bestaetigt'] = True
        peer['directReceipts'] = [dict(right['partner'][0]['directReceipts'][0]) for _ in range(64)]
    envelope = m.umschlag_bauen(left['geheim'], left['partner'][0], left['kennung'], {'art': 'notiz', 'text': 'fixture'}, 66)
    assert backend.behandeln('/magnolie/v1/nachricht', envelope, '127.0.0.1', True)[0] == 200
    assert sum(len(peer['directReceipts']) for peer in right['partner']) == 256
