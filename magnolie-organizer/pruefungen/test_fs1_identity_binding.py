"""#627: actual FS1 receiver/crypto, synthetic state, no sockets or user keys."""
import pytest

from test_startup_read_failure import native


@pytest.mark.parametrize('change', ['normal', 'cosmetic', 'peer-key', 'own-key', 'unconfirmed'])
def test_open_channel_cannot_be_relabelled_as_a_new_pinned_identity(native, change):
    sender = native.baum_schluessel_erzeugen('Synthetic sender')
    receiver = native.baum_schluessel_erzeugen('Synthetic receiver'); receiver['an'] = True
    peer = native.baum_partner_aufnehmen(receiver, sender['name'], sender['kennung'], sender['oeffentlich'], '127.0.0.1')
    peer['bestaetigt'] = True
    remote = {'kennung': receiver['kennung'], 'oeffentlich': receiver['oeffentlich']}
    received, saved = [], []
    service = native.BaumDienst(lambda: receiver, lambda state: saved.append(True),
        bei_nachricht=lambda peer, message: received.append(message))
    start, private = native.fs_start_bauen(sender, remote)
    status, answer = service.behandeln('/magnolie/v2/sitzung', start, '127.0.0.1')
    assert status == 200
    channel = native.fs_antwort_oeffnen(sender, remote, start, answer, private)
    envelope = native.umschlag_bauen_fs(channel, sender['kennung'], receiver['kennung'],
        {'art': 'synthetic-audit'}, native._fs_b64(b'M' * 16))
    server_channel = service._fs_sitzungen[channel['sid']]['sitzung']
    try:
        if change == 'peer-key': peer['oeffentlich'] = native.baum_schluessel_erzeugen('Different synthetic sender')['oeffentlich']
        if change == 'own-key':
            replacement = native.baum_schluessel_erzeugen('Different synthetic receiver')
            receiver.update({key: replacement[key] for key in ('oeffentlich', 'geheim')})
        if change == 'unconfirmed': peer['bestaetigt'] = False
        if change == 'cosmetic': peer['name'] = receiver['name'] = 'Display only'
        status, response = service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')
        if change in ('normal', 'cosmetic'):
            assert status == 200 and native.fs_ack_pruefen(channel, envelope, response)
            assert received == [{'art': 'synthetic-audit'}] and len(saved) == 1
        else:
            assert status == 403 and received == [] and saved == []
        assert channel['sid'] not in service._fs_sitzungen
        assert bytes(server_channel['kenc']) == b'\0' * 32
        assert bytes(server_channel['kack']) == b'\0' * 32
        assert service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] == 403
    finally:
        native.fs_sitzung_loeschen(channel)
        service.anhalten()
