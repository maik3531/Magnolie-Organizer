"""Run explicitly with pytest, MAGNOLIE_RECEIPT_PROBE and MAGNOLIE_DOTNET.

No skip: missing compiled fresh-source probe is a failed prerequisite.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_baum_receipts import m, private, receiver


def test_current_windows_public_receipt_vectors(private):
    vectors = Path(__file__).resolve().parents[3] / 'contracts' / 'baum-1-receipt-v1-vectors.json'
    result = subprocess.run([os.environ['MAGNOLIE_DOTNET'], os.environ['MAGNOLIE_RECEIPT_PROBE'], str(vectors)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'Public receipt vectors passed' and not result.stderr.strip()


def test_fresh_windows_linux_pair_both_directions(private, monkeypatch):
    probe = os.environ['MAGNOLIE_RECEIPT_PROBE']
    dotnet = os.environ['MAGNOLIE_DOTNET']
    child = subprocess.Popen([dotnet, probe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    left = m.baum_schluessel_erzeugen('Linux fixture')
    left['an'] = True
    backend = None
    try:
        public = json.loads(child.stdout.readline())['public']
        peer = m.baum_partner_aufnehmen(left, 'Windows fixture', 'windows-fixture', public, '127.0.0.1')
        peer['bestaetigt'] = True
        child.stdin.write(json.dumps({'public': left['oeffentlich'], 'id': left['kennung']}) + '\n'); child.stdin.flush()
        peer['port'] = json.loads(child.stdout.readline())['port']
        post = []
        m.baum_einreihen(post, peer['kennung'], 'notiz', {'text': 'linux-to-windows'})
        report = m.baum_post_zustellen(left, post, sichern=lambda: m.baum_post_schreiben(post, str(private / 'outbox.json')))
        assert report['zugestellt'] == 1 and post == []
        assert json.loads(child.stdout.readline()) == {'received': True}
        backend, _, inbox = receiver(left, private)
        original = socket.socket.bind
        def bind(sock, address):
            if sock.family == socket.AF_INET and address[1] == 0:
                return original(sock, ('127.0.0.1', 0))
            raise OSError('test permits only ephemeral loopback')
        monkeypatch.setattr(socket.socket, 'bind', bind)
        monkeypatch.setattr(backend, '_rufdienst_starten', lambda: None)
        monkeypatch.setattr(m.BaumBluetoothDienst, 'starten', lambda self: False)
        monkeypatch.setattr(m, 'baum_mdns_veroeffentlichen', lambda *a: None)
        assert backend.starten()
        child.stdin.write(json.dumps({'port': backend.port}) + '\n'); child.stdin.flush()
        assert json.loads(child.stdout.readline()) == {'verified': True}
        child.wait(10)
        assert child.returncode == 0, child.stderr.read()
        assert m.baum_eingang_lesen(str(inbox))[0]['inhalt']['text'] == 'windows-to-linux'
    finally:
        if backend is not None: backend.anhalten()
        if child.poll() is None: child.kill()
        child.wait(10)
        for stream in (child.stdin, child.stdout, child.stderr): stream.close()
