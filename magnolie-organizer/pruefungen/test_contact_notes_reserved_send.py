"""Native typed send lane over real FS1 crypto, isolated synthetic responder.

Not a physical Notes counterpart or installed production orchestration test.
"""
import hashlib
from pathlib import Path

import pytest

from test_contact_notes_consent import Harness, native
from magnolie_contact_notes_return import NativeNotesAckIntents, NativeNotesProtocolNegotiation, _frame_bytes


@pytest.mark.parametrize('mode', ['success', 'connection-wait', 'copied-intent', 'copied-negotiation', 'unnegotiated',
    'untrusted', 'sync-off', 'legacy-protocol', 'changed-epoch', 'revoked-during-handshake',
    'cancel-during-handshake', 'connection-lost-during-handshake', 'bad-receipt', 'offline', 'wrong-intent-pins',
    'recovered-intent', 'terminal-marked', 'revoked-after-send'])
def test_reserved_send_requires_genuine_saved_intent_negotiated_pins_and_current_native_policy(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    responder_sessions, client_sessions, network = [], [], []
    try:
        h.configure(); h.pending = h.choice.pending(); request = h.pending.request()
        result = {'art': 'kontakt_original_ergebnis', 'fassung': 1,
            **{name: request[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')},
            'request_sha256': hashlib.sha256(_frame_bytes(request)).hexdigest(),
            'receipt_id': '22222222-2222-4222-8222-222222222222', 'native_revision': 2, 'next_basis': 'd' * 64}
        h.send(result)
        with h.probe._daten_sperre: invocation = h.pending.prepare_commit()
        assert h.save(monkeypatch, invocation=invocation)['ok']
        intents = NativeNotesAckIntents(tmp_path / 'outcomes', lambda: b'J' * 32)
        intent = intents.seal_after_save(h.pending); expected = intent.body(); h.pending = None
        journal, = (tmp_path / 'outcomes').glob('*.bin')
        if mode in ('recovered-intent', 'terminal-marked'):
            h.restart()
            historical = result if mode == 'recovered-intent' else dict(result,
                art='kontakt_original_abschlussstatus', phase='settled', desktop_sha256=expected['desktop_sha256'])
            h.send(historical); body, origin, transport = h.results.pop()
            intent = intents.reauthorize(journal.stem, h.store, body, origin, transport)
            if mode == 'terminal-marked':
                intents.confirm_terminal(intent)
                intent = intents.reauthorize(journal.stem, h.store, body, origin, transport)
            assert h.probe._kontakt_quellen_buchaufnahme() is None
        before_journal, before_book = journal.read_bytes(), Path(native.daten_datei()).read_bytes()
        peer = native.baum_partner(h.receiver, h.sender['kennung'])
        peer.update(vertraut=True, kontaktSync=True, protokoll='baum-fs1')
        pins = (h.sender['kennung'], h.sender['oeffentlich']), (h.receiver['kennung'], h.receiver['oeffentlich'])
        negotiation = NativeNotesProtocolNegotiation(*pins)
        offer = dict(negotiation.request(), antwort=True)
        if mode == 'wrong-intent-pins':
            h.sender = native.baum_schluessel_erzeugen('Other negotiated synthetic peer')
            peer = native.baum_partner_aufnehmen(h.receiver, h.sender['name'], h.sender['kennung'], h.sender['oeffentlich'], '127.0.0.1')
            peer.update(bestaetigt=True, vertraut=True, kontaktSync=True, protokoll='baum-fs1')
            negotiation = NativeNotesProtocolNegotiation((h.sender['kennung'], h.sender['oeffentlich']), pins[1])
            offer = dict(negotiation.request(), antwort=True)
        h.send(offer); body, origin, transport = h.results.pop()
        if mode != 'unnegotiated': negotiation.accept(body, origin, transport)
        allowed = [mode != 'connection-wait']
        if mode == 'copied-intent': intent = expected
        if mode == 'copied-negotiation': negotiation = offer
        if mode == 'untrusted': peer['vertraut'] = False
        if mode == 'sync-off': peer['kontaktSync'] = False
        if mode == 'legacy-protocol': peer['protokoll'] = 'baum-1'
        actual_open = native.fs_antwort_oeffnen
        def client_open(*args):
            session = actual_open(*args); client_sessions.append(session); return session
        monkeypatch.setattr(native, 'fs_antwort_oeffnen', client_open)
        def send(url, body):
            network.append(url)
            if mode == 'offline': raise ConnectionRefusedError('Synthetic disconnected peer')
            if url.endswith('/sitzung'):
                answer, session = native.fs_antwort_bauen(h.sender,
                    {'kennung': h.receiver['kennung'], 'oeffentlich': h.receiver['oeffentlich']}, body)
                responder_sessions.append(session)
                if mode == 'changed-epoch': h.receiver['syncEpoch'] = 'Changed native epoch while awaiting response'
                if mode == 'revoked-during-handshake': h.store.revoke()
                if mode == 'cancel-during-handshake': negotiation.cancel()
                if mode == 'connection-lost-during-handshake': allowed[0] = False
                return answer
            assert url.endswith('/magnolie/v2/nachricht')
            session = responder_sessions[-1]
            clear, _ = native.umschlag_oeffnen_fs(session, h.sender['kennung'], h.receiver['kennung'], body)
            assert clear == expected
            receipt = native.fs_ack_bauen(session, body)
            if mode == 'bad-receipt': receipt['mac'] = native._fs_b64(b'X' * 32)
            if mode == 'revoked-after-send': h.store.revoke()
            return receipt
        if mode in ('success', 'recovered-intent', 'connection-wait', 'bad-receipt', 'offline'):
            sent = native.baum_notes_saveack_senden(lambda: h.receiver, intent, negotiation, lambda: allowed[0], sender=send)
            assert sent == (mode in ('success', 'recovered-intent'))
            if mode == 'connection-wait': assert not network
            if mode in ('success', 'recovered-intent'):
                assert len(network) == 2
                assert 'native_terminal_sha256' not in intents.load_held(journal.stem), 'Transport receipt was confused with settlement'
        else:
            with pytest.raises(PermissionError):
                native.baum_notes_saveack_senden(lambda: h.receiver, intent, negotiation, lambda: allowed[0], sender=send)
            if mode in ('changed-epoch', 'revoked-during-handshake', 'cancel-during-handshake', 'connection-lost-during-handshake'):
                assert len(network) == 1
            elif mode == 'revoked-after-send': assert len(network) == 2
            else: assert not network
        for session in client_sessions:
            assert bytes(session['kenc']) == bytes(session['kack']) == b'\0' * 32
        assert journal.read_bytes() == before_journal and Path(native.daten_datei()).read_bytes() == before_book
        # Existing generic JSON paths must still reject the exact same wire body.
        for generic in (lambda: native.baum_einreihen([], peer['kennung'], expected['art'], expected),
                        lambda: native.baum_senden_fs(h.receiver, peer, expected['art'], expected, '', sender=send)):
            count = len(network)
            with pytest.raises(RuntimeError): generic()
            assert len(network) == count
    finally:
        for session in responder_sessions: native.fs_sitzung_loeschen(session)
        h.service.anhalten()
