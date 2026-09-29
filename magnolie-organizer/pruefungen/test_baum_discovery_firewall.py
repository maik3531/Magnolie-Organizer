"""Discovery must receive replies on its allowed port without stealing the listener."""
import base64
import json
from pathlib import Path
import socket
import threading

from modul_laden import quellmodul_laden

m = quellmodul_laden('baum_discovery_firewall', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')


def test_search_reuses_listener_and_still_answers_other_searches(monkeypatch):
    state = {'an': True, 'kennung': 'local-fixture', 'name': 'Local fixture',
             'oeffentlich': base64.b64encode(bytes(32)).decode()}
    service = m.BaumDienst(lambda: state, lambda *_: True, port=0)
    service._rufdienst_starten()
    assert service._ruf is not None
    service.port = service._ruf.getsockname()[1]
    state['port'] = service.port
    monkeypatch.setattr(m, 'baum_suchziele', lambda: ['127.0.0.1'])
    observations = []
    errors = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        peer.bind(('127.0.0.1', 0))
        peer.settimeout(2)
        target_port = peer.getsockname()[1]

        def respond():
            try:
                request, endpoint = peer.recvfrom(2048)
                observations.append((request, endpoint[1]))
                for packet in (b'[]', b'{"magnolie":[],"kennung":"bad"}',
                               json.dumps({'magnolie': m.BAUM_HÜLLE, 'kennung': 'remote-fixture'}).encode()):
                    peer.sendto(packet, endpoint)
                peer.sendto(m.BAUM_RUF, endpoint)
                reply, _ = peer.recvfrom(2048)
                observations.append(json.loads(reply)['kennung'])
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=respond)
        thread.start()
        try:
            found = m.baum_suchen(target_port, .4, state['kennung'], mdns_suche=lambda *_: [], rufdienst=service)
            thread.join(timeout=3)
            assert not thread.is_alive() and not errors
            assert observations == [(m.BAUM_RUF, service.port), 'local-fixture']
            assert [item['kennung'] for item in found] == ['remote-fixture']
            assert found[0]['adresse'] == '127.0.0.1'
            assert m.baum_suchen(target_port, .1, state['kennung'], mdns_suche=lambda *_: [], rufdienst=service) == []
            assert service._ruf.fileno() >= 0
        finally:
            service.anhalten()
            thread.join(timeout=3)
