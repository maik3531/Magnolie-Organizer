"""Phone-contact import boundary; synthetic vCards, no device/profile access."""
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from modul_laden import quellmodul_laden


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'gi', None)
    return quellmodul_laden('contact_import_test', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')


VCARD = ('BEGIN:VCARD\r\nVERSION:3.0\r\nUID:untrusted-vcard-uid\r\n'
         'FN:Sample Person\r\nN:Person;Sample;;;\r\nORG:Example\r\n'
         'ADR;TYPE=HOME:;;Example Street;Example City;;12345;Germany\r\n'
         'TEL:+491701234567\r\nEMAIL:fixture@example.org\r\n'
         'NOTE:Keep this note\r\nBDAY:2000-02-29\r\n'
         'PHOTO;ENCODING=b;TYPE=PNG:iVBORw0KGgo=\r\nX-CUSTOM:Preserve extension\r\nEND:VCARD\r\n')


def batch():
    return dict(device_id='paired', fingerprint='a' * 64,
                contacts=[dict(uid='card', vcard=VCARD)])


def test_projection_retains_contact_content_without_importing_photo_or_identity(native):
    result = native.kde_kontakte_projizieren(batch(), 'paired', ['card'])
    item = result['contacts'][0]
    contact = item['kontakt']
    assert contact['vorname'] == 'Sample' and contact['nachname'] == 'Person'
    assert contact['firma'] == 'Example' and contact['notiz'] == 'Keep this note'
    assert contact['geburtstag'] == '2000-02-29'
    assert contact['anschriften'][0]['land'] == 'Germany'
    assert not {'foto', 'fotoManuell', 'uid', 'id', 'importBindungen'} & contact.keys()
    assert 'vcard' not in item
    assert any('X-CUSTOM:Preserve extension' in line for line in contact['vcardRoundtrip'])
    assert all('PHOTO' not in line and 'UID:' not in line for line in contact['vcardRoundtrip'])


def test_binding_is_stable_and_separates_device_certificate_and_uid(native):
    expected = 'urn:magnolie:import:kde:' + hashlib.sha256(
        ('kde-contact-v1\0paired\0' + 'a' * 64 + '\0card').encode()).hexdigest()
    assert native.kde_kontakt_bindung('paired', 'A' * 64, 'card') == expected
    assert len({expected, native.kde_kontakt_bindung('other', 'a' * 64, 'card'),
                native.kde_kontakt_bindung('paired', 'b' * 64, 'card'),
                native.kde_kontakt_bindung('paired', 'a' * 64, 'other')}) == 4
    for device, fingerprint, uid in [('paired', 'a' * 64 + '\n', 'card'),
                                      ('paired', 'a' * 64, 'card\0other'),
                                      ('paired', 'a' * 64, '😀' * 513)]:
        with pytest.raises((ValueError, UnicodeError)):
            native.kde_kontakt_bindung(device, fingerprint, uid)


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'unexpected', 'device', 'vcard', 'fingerprint'])
def test_incomplete_or_misattributed_batch_is_rejected(native, kind):
    result = batch()
    requested = ['card']
    if kind == 'missing': requested.append('missing')
    if kind == 'duplicate':
        requested.append('other')
        result['contacts'].append(copy.deepcopy(result['contacts'][0]))
    if kind == 'unexpected': result['contacts'][0]['uid'] = 'other'
    if kind == 'device': result['device_id'] = 'other'
    if kind == 'vcard': result['contacts'][0]['vcard'] += VCARD
    if kind == 'fingerprint': result['fingerprint'] = 'invalid'
    with pytest.raises(ValueError):
        native.kde_kontakte_projizieren(result, 'paired', requested)


@pytest.mark.parametrize('locked_during_read', [False, True])
def test_bridge_routes_full_contacts_and_discards_results_after_lock(native, monkeypatch, locked_during_read):
    replies = []
    host = SimpleNamespace(_gesperrt=False, antwort=lambda name, value: replies.append((name, value)))
    def cards(uids, device_id):
        assert uids == ['card'] and device_id == 'paired'
        host._gesperrt = locked_during_read
        return batch()
    monkeypatch.setattr(native, '_kdeconnect_backend', lambda: SimpleNamespace(contact_vcards=cards, native=True))
    native.Fenster._kontakt_fotos_lesen(host, dict(cmd='telefon_kontakte', requestId='fixture',
                                               device_id='paired', uids=['card']))
    name, result = replies[-1]
    assert name == 'App.telefonKontakte' and result['ok'] is not locked_during_read
    if locked_during_read:
        assert result == dict(ok=False, requestId='fixture')
    else:
        assert result['native_cache'] is True and result['contacts'][0]['kontakt']['vorname'] == 'Sample'
    assert host._kontakt_fotos_laeuft is False
