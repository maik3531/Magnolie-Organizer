"""Photo-only bridge boundary, no phone/network/profile writes."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from modul_laden import quellmodul_laden


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'gi', None)
    return quellmodul_laden('photo_bridge_test', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')


def test_bridge_exposes_only_photo_and_matching_fields(native, monkeypatch):
    replies = []
    host = SimpleNamespace(antwort=lambda name, value: replies.append((name, value)))
    def cards(uids, device_id):
        assert uids == ['card'] and device_id == 'paired'
        return dict(device_id='paired', fingerprint='a' * 64, contacts=[dict(uid='card', vcard=
            'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Private name\r\nN:Name;Private;;;\r\n'
            'TEL:+491701234567\r\nEMAIL:fixture@example.org\r\nNOTE:Not a photo field\r\n'
            'PHOTO;ENCODING=b;TYPE=PNG:iVBORw0KGgo=\r\nEND:VCARD\r\n')])
    monkeypatch.setattr(native, '_kdeconnect_backend', lambda: SimpleNamespace(contact_vcards=cards))
    native.Fenster._kontakt_fotos_lesen(host, dict(requestId='fixture', device_id='paired', uids=['card']))
    name, response = replies[-1]
    assert name == 'App.kontaktFotos' and response['ok'] is True
    contact = response['contacts'][0]
    assert set(contact) == {'uid', 'foto', 'telefone', 'telefon', 'mobil', 'email', 'emails', 'emailEintraege'}
    assert contact['foto'].startswith('data:image/png;base64,')
    assert contact['email'] == 'fixture@example.org'
    assert host._kontakt_fotos_laeuft is False


def test_failed_export_is_not_a_successful_empty_photo(native, monkeypatch):
    replies = []
    host = SimpleNamespace(antwort=lambda name, value: replies.append(value))
    def failed(*args): raise RuntimeError('private provider details')
    monkeypatch.setattr(native, '_kdeconnect_backend', lambda: SimpleNamespace(contact_uids=failed))
    native.Fenster._kontakt_fotos_lesen(host, dict(requestId='fixture', device_id='paired'))
    assert replies == [{'ok': False, 'requestId': 'fixture'}]
    assert host._kontakt_fotos_laeuft is False


def test_photo_cache_bookkeeping_does_not_create_recovery_points(native):
    original = {'kontakte': [{'id': 'one', 'foto': 'original'}]}
    changed = copy.deepcopy(original)
    changed['kontaktFotoCache'] = {'entries': [{'uid': 'one', 'modified_ms': 1}]}
    changed['kontakte'][0]['fotoQuelle'] = {'uid': 'one', 'hash': 'a' * 64}
    assert not native.journal_inhalt_geaendert(original, changed)
    changed['kontakte'][0]['foto'] = 'changed'
    assert native.journal_inhalt_geaendert(original, changed)
