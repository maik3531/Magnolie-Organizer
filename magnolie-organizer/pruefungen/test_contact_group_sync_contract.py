"""#195: authoritative version-4 groups cannot disappear in legacy projection."""
import copy
from urllib.error import HTTPError

import pytest
from test_contact_time_contract import native, Host, packet, peers


def grouped(groups=None):
    value = packet(); value['fassung'] = 4
    value['kontakt']['gruppen'] = ['Arbeit', 'Kollegen'] if groups is None else groups
    return value


@pytest.mark.parametrize('groups', [['Arbeit', 'Kollegen'], ['Arbeit'], []])
def test_native_explicit_group_set_and_empty_clear_are_supported_only_by_v4(native, groups):
    value = grouped(groups)
    assert native.baum_kontakt_sync_pruefen(value) == value
    peer = {'bestaetigt': True, 'kontaktFaehigkeiten': native.baum_kontakt_faehigkeiten(maximum=4)}
    assert native.baum_kontakt_peer_fassung(peer, 'kontakt_sync') == 4
    assert native.baum_kontakt_fuer_partner(peer, value) == value
    for maximum in (2, 3):
        peer['kontaktFaehigkeiten'] = native.baum_kontakt_faehigkeiten(maximum=maximum)
        with pytest.raises(RuntimeError): native.baum_kontakt_fuer_partner(peer, value)


@pytest.mark.parametrize('invalid', [None, 'Arbeit', [''], ['bad\nname'], [False], ['x' * 257], ['a'] * 101])
def test_missing_or_malformed_membership_sets_are_not_sanitized_to_removal(native, invalid):
    value = grouped(); value['kontakt']['gruppen'] = invalid
    with pytest.raises(RuntimeError): native.baum_kontakt_sync_pruefen(value)


def test_group_capability_does_not_downgrade_on_old_reply(native, monkeypatch):
    state, peer = peers(native)
    peer['kontaktFaehigkeiten'] = native.baum_kontakt_faehigkeiten(maximum=4)
    host = Host(native); host._gesperrt = False
    monkeypatch.setattr(host, '_baum_zustand', lambda: state)
    monkeypatch.setattr(host, '_baum_stand_melden', lambda: None)
    monkeypatch.setattr(native, 'baum_benachrichtigungstext', lambda *_: None)
    host._baum_empfangen(peer, native.baum_kontakt_faehigkeiten(antwort=True, maximum=3))
    assert native.baum_kontakt_peer_fassung(peer, 'kontakt_sync') == 4


def test_old_peer_rejecting_v4_probe_preserves_contact_data_and_v3_state(native):
    state, peer = peers(native)
    peer['kontaktFaehigkeiten'] = native.baum_kontakt_faehigkeiten(maximum=3)
    post = []
    probe = native.baum_einreihen(post, peer['kennung'], 'kontakt_faehigkeiten', native.baum_kontakt_faehigkeiten(maximum=4))
    probe['kontaktV4Probe'] = True
    data = native.baum_einreihen(post, peer['kennung'], 'kontakt_sync', packet())
    before = copy.deepcopy(data)
    def send(url, _body):
        assert url.endswith('/magnolie/v2/sitzung')
        raise HTTPError(url, 400, 'old peer', {}, None)
    native.baum_post_zustellen(state, post, sender=send, hoechstens=1, sichern=lambda: True)
    assert probe not in post and data == before and data in post
    assert peer['kontaktV4Geprueft'] is True
    assert native.baum_kontakt_peer_fassung(peer, 'kontakt_sync') == 3
