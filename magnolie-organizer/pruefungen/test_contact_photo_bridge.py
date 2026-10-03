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
    host = SimpleNamespace(_gesperrt=False, antwort=lambda name, value: replies.append((name, value)))
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
    host = SimpleNamespace(_gesperrt=False, antwort=lambda name, value: replies.append(value))
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


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("change", ["none", "lock", "key"])
def test_notes_source_is_separate_read_only_and_revalidated(native, monkeypatch, full, change):
    replies = []
    peer = "11111111-1111-4111-8111-111111111111"
    device = "notes:" + peer
    host = SimpleNamespace(_gesperrt=False, antwort=lambda name, value: replies.append((name, value)))
    def read_contacts(peer_id, uids):
        assert peer_id == peer and uids == ["card"]
        if change == "lock": host._gesperrt = True
        return {"device_id": device, "fingerprint": "a" * 64, "contacts": [{"uid": "card", "modified_ms": 1,
            "vcard": 'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Private name\r\nN:Name;Private;;;\r\n'
            'TEL:+491701234567\r\nNOTE:Review only\r\nPHOTO;ENCODING=b;TYPE=PNG:iVBORw0KGgo=\r\n'
            'X-MAGNOLIE-SOZIALES-MEDIUM:{"dienst":"whatsapp","wert":"+491701234567"}\r\nEND:VCARD\r\n'}]}
    def current(peer_id, fingerprint):
        assert peer_id == peer and fingerprint == "a" * 64
        return change != "key"
    host._telefon = SimpleNamespace(read_contacts=read_contacts, contact_source_current=current)
    monkeypatch.setattr(native, "_kdeconnect_backend", lambda: pytest.fail("Notes request entered the KDE transport"))
    native.Fenster._kontakt_fotos_lesen(host, {"cmd": "telefon_kontakte" if full else "telefon_kontaktfotos",
        "requestId": "fixture", "device_id": device, "uids": ["card"]})
    name, result = replies[-1]
    assert name == ("App.telefonKontakte" if full else "App.kontaktFotos")
    if change != "none":
        assert result == {"ok": False, "requestId": "fixture"}
    else:
        assert result["ok"]
        card = result["contacts"][0]
        assert "vcard" not in card
        if full:
            assert card["bindung"].startswith("urn:magnolie:import:notes:")
            assert card["kontakt"]["sozialeMedien"][0]["dienst"] == "whatsapp"
        else:
            assert "kontakt" not in card and "notiz" not in card and "sozialeMedien" not in card
            assert card["foto"].startswith("data:image/png;base64,")
