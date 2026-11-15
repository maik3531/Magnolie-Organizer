"""Initial native probe delivery is not negotiation or source permission."""
from pathlib import Path

import pytest

from test_contact_notes_fs_origin import fixture, frame, native
from magnolie_contact_notes_return import NativeNotesProtocolNegotiation


@pytest.mark.parametrize('mode', ['success', 'wait', 'offline', 'copied', 'cancelled', 'untrusted',
    'contact-off', 'wrong-own-pin', 'changed-epoch', 'cancel-during-handshake', 'bad-receipt'])
def test_initial_probe_uses_native_pins_and_policy_but_only_a_fresh_echo_can_negotiate(native, tmp_path, mode):
    captured, server_sessions, calls = [], [], []
    sender, receiver, peer, _, service = fixture(native,
        lambda peer, body, origin, transport: captured.append((body, origin, transport)) or True)
    peer.update(vertraut=True, kontaktSync=True, protokoll='baum-fs1')
    pins = (sender['kennung'], sender['oeffentlich']), (receiver['kennung'], receiver['oeffentlich'])
    negotiation = NativeNotesProtocolNegotiation(*pins)
    request = negotiation.request()
    if mode == 'copied': negotiation = request
    if mode == 'cancelled': negotiation.cancel()
    if mode == 'untrusted': peer['vertraut'] = False
    if mode == 'contact-off': peer['kontaktSync'] = False
    if mode == 'wrong-own-pin':
        negotiation = NativeNotesProtocolNegotiation(pins[0], ('other-own-id', pins[1][1]))
    def send(url, body):
        calls.append(url)
        if mode == 'offline': raise ConnectionRefusedError('Synthetic peer offline')
        if url.endswith('/sitzung'):
            answer, session = native.fs_antwort_bauen(sender,
                {'kennung': receiver['kennung'], 'oeffentlich': receiver['oeffentlich']}, body)
            server_sessions.append(session)
            if mode == 'changed-epoch': receiver['syncEpoch'] = 'Changed native epoch'
            if mode == 'cancel-during-handshake': negotiation.cancel()
            return answer
        session = server_sessions[-1]
        clear, _ = native.umschlag_oeffnen_fs(session, sender['kennung'], receiver['kennung'], body)
        assert clear == request and clear['antwort'] is False
        receipt = native.fs_ack_bauen(session, body)
        if mode == 'bad-receipt': receipt['mac'] = native._fs_b64(b'X' * 32)
        return receipt
    try:
        if mode in ('success', 'wait', 'offline', 'bad-receipt'):
            delivered = native.baum_notes_protokollprobe_senden(lambda: receiver, negotiation, lambda: mode != 'wait', sender=send)
            assert delivered == (mode == 'success')
            with pytest.raises(PermissionError): negotiation.require_current()
            if mode == 'wait': assert calls == []
            if mode == 'success':
                assert len(calls) == 2
                offer = dict(request, antwort=True)
                channel, envelope, _ = frame(native, service, sender, receiver, offer)
                try:
                    status, receipt = service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')
                    assert status == 200 and native.fs_ack_pruefen(channel, envelope, receipt)
                    negotiation.accept(*captured.pop())
                    assert negotiation.require_current() == pins
                finally:
                    native.fs_sitzung_loeschen(channel)
        else:
            with pytest.raises(PermissionError):
                native.baum_notes_protokollprobe_senden(lambda: receiver, negotiation, lambda: True, sender=send)
            assert len(calls) == (1 if mode in ('changed-epoch', 'cancel-during-handshake') else 0)
        assert not Path(native.daten_verzeichnis(), 'notes-original-choice').exists(), 'A protocol probe created consent'
        for art in ('kontakt_original_aushandlung', 'notiz'):
            with pytest.raises(RuntimeError): native.baum_einreihen([], peer['kennung'], art, request)
            with pytest.raises(RuntimeError): native.baum_senden_fs(receiver, peer, art, request, '', sender=send)
    finally:
        for session in server_sessions: native.fs_sitzung_loeschen(session)
        service.anhalten()
